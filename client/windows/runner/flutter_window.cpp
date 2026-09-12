#include "flutter_window.h"

#include <optional>
#include <flutter/standard_method_codec.h>
#include "resource.h"

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());
  DWORD tray_saved = 0, bytes = sizeof(DWORD);
  RegGetValueW(HKEY_CURRENT_USER, L"Software\\PersonalStaffer", L"TrayEnabled",
               RRF_RT_REG_DWORD, nullptr, &tray_saved, &bytes);
  UpdateTray(tray_saved == 1);
  desktop_channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "personalstaffer/desktop",
      &flutter::StandardMethodCodec::GetInstance());
  desktop_channel_->SetMethodCallHandler([this](const auto& call, auto result) {
    if (call.method_name() == "show") {
      ShowWindow(GetHandle(), SW_RESTORE); SetForegroundWindow(GetHandle());
      result->Success(); return;
    }
    if (call.method_name() == "preferences") {
      DWORD startup = 0, startup_bytes = sizeof(DWORD);
      RegGetValueW(HKEY_CURRENT_USER, L"Software\\PersonalStaffer", L"StartupEnabled",
                   RRF_RT_REG_DWORD, nullptr, &startup, &startup_bytes);
      result->Success(flutter::EncodableValue(flutter::EncodableMap{
          {flutter::EncodableValue("tray"), flutter::EncodableValue(tray_enabled_)},
          {flutter::EncodableValue("startup"), flutter::EncodableValue(startup == 1)}})); return;
    }
    if (call.method_name() == "configure") {
      const auto* values = std::get_if<flutter::EncodableMap>(call.arguments());
      if (!values) { result->Error("INVALID_ARGUMENT", "Expected preferences"); return; }
      auto t = values->find(flutter::EncodableValue("tray"));
      auto s = values->find(flutter::EncodableValue("startup"));
      if (t == values->end() || s == values->end() || !std::holds_alternative<bool>(t->second)
          || !std::holds_alternative<bool>(s->second)) {
        result->Error("INVALID_ARGUMENT", "Expected boolean preferences"); return;
      }
      const bool tray = std::get<bool>(t->second), startup = std::get<bool>(s->second);
      if (!SetStartup(startup)) { result->Error("STARTUP_FAILED", "Could not update startup preference"); return; }
      const bool was_tray = tray_enabled_;
      UpdateTray(tray);
      if (tray && !was_tray && tray_enabled_) {
        // Windows 11 places new notification-area icons under the "hidden icons" chevron by
        // default; a one-time balloon from the icon tells the user where it lives.
        tray_data_.uFlags |= NIF_INFO;
        tray_data_.dwInfoFlags = NIIF_INFO;
        wcscpy_s(tray_data_.szInfoTitle, L"Personal Staffer stays in the tray");
        wcscpy_s(tray_data_.szInfo,
                 L"Closing the window keeps notifications running. Find this icon under the ^ hidden-icons button; right-click it for Open and Exit.");
        Shell_NotifyIconW(NIM_MODIFY, &tray_data_);
        tray_data_.uFlags &= ~NIF_INFO;
      }
      HKEY key;
      if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\PersonalStaffer", 0, nullptr, 0,
                         KEY_SET_VALUE, nullptr, &key, nullptr) == ERROR_SUCCESS) {
        DWORD enabled = tray ? 1 : 0;
        RegSetValueExW(key, L"TrayEnabled", 0, REG_DWORD, reinterpret_cast<BYTE*>(&enabled), sizeof(enabled));
        enabled = startup ? 1 : 0;
        RegSetValueExW(key, L"StartupEnabled", 0, REG_DWORD, reinterpret_cast<BYTE*>(&enabled), sizeof(enabled));
        RegCloseKey(key);
      }
      result->Success(); return;
    }
    result->NotImplemented();
  });


  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    if (!tray_enabled_ || wcsstr(GetCommandLineW(), L"--background") == nullptr) this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  UpdateTray(false);
  desktop_channel_ = nullptr;
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  if (message == RegisterWindowMessageW(L"TaskbarCreated") && tray_enabled_) {
    Shell_NotifyIconW(NIM_ADD, &tray_data_); return 0;
  }
  if (message == WM_CLOSE && tray_enabled_) { ShowWindow(hwnd, SW_HIDE); return 0; }
  if (message == WM_APP + 19) {
    if (lparam == WM_LBUTTONUP || lparam == WM_LBUTTONDBLCLK) {
      ShowWindow(hwnd, SW_RESTORE); SetForegroundWindow(hwnd);
    } else if (lparam == WM_RBUTTONUP) {
      HMENU menu = CreatePopupMenu();
      AppendMenuW(menu, MF_STRING, 1, L"Open Personal Staffer");
      AppendMenuW(menu, MF_STRING, 2, L"Exit Personal Staffer");
      POINT point; GetCursorPos(&point); SetForegroundWindow(hwnd);
      const UINT choice = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY,
                                        point.x, point.y, 0, hwnd, nullptr);
      DestroyMenu(menu);
      if (choice == 1) { ShowWindow(hwnd, SW_RESTORE); SetForegroundWindow(hwnd); }
      if (choice == 2) { UpdateTray(false); Destroy(); }
    }
    return 0;
  }
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}

void FlutterWindow::UpdateTray(bool enabled) {
  if (tray_enabled_) Shell_NotifyIconW(NIM_DELETE, &tray_data_);
  tray_enabled_ = enabled;
  if (!enabled) return;
  tray_data_ = {};
  tray_data_.cbSize = sizeof(tray_data_); tray_data_.hWnd = GetHandle(); tray_data_.uID = 1;
  tray_data_.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
  tray_data_.uCallbackMessage = WM_APP + 19;
  tray_data_.hIcon = LoadIconW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(IDI_APP_ICON));
  wcscpy_s(tray_data_.szTip, L"Personal Staffer — background notifications");
  if (!Shell_NotifyIconW(NIM_ADD, &tray_data_)) tray_enabled_ = false;
}
bool FlutterWindow::SetStartup(bool enabled) {
  HKEY key;
  if (RegCreateKeyExW(HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
      0, nullptr, 0, KEY_SET_VALUE, nullptr, &key, nullptr) != ERROR_SUCCESS) return false;
  LONG result;
  if (enabled) {
    wchar_t path[32768];
    DWORD length = GetModuleFileNameW(nullptr, path, 32768);
    if (!length || length == 32768) { RegCloseKey(key); return false; }
    std::wstring command = L"\"" + std::wstring(path) + L"\" --background";
    result = RegSetValueExW(key, L"PersonalStaffer", 0, REG_SZ,
        reinterpret_cast<const BYTE*>(command.c_str()), static_cast<DWORD>((command.size() + 1) * sizeof(wchar_t)));
  } else {
    result = RegDeleteValueW(key, L"PersonalStaffer");
    if (result == ERROR_FILE_NOT_FOUND) result = ERROR_SUCCESS;
  }
  RegCloseKey(key); return result == ERROR_SUCCESS;
}
