# Windows client

Personal Staffer is a Flutter native application, not a browser product. The target machine is the specified Asus Vivobook Pro 15. Confirm its Windows version during setup.

## Toolchain

Install Flutter **3.47.4** stable (Dart **3.13.3**) and Visual Studio 2022 (or Build Tools) with the Desktop development with C++ workload, Windows SDK, CMake tooling **and the C++ ATL component** (`Microsoft.VisualStudio.Component.VC.ATL`; the secure-storage and notification plugins include `atlbase.h`/`atlstr.h`). One elevated command installs the toolchain: `winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --add Microsoft.VisualStudio.Component.VC.ATL"`. Enable Windows Developer Mode (Settings > System > For developers) so Flutter can create plugin symlinks. Visual Studio Code alone does not supply the native compiler. Install Git and, for the local backend, Docker Desktop/WSL2. Follow the current [Flutter Windows setup](https://docs.flutter.dev/platform-integration/windows/setup).

In PowerShell from `client/`:

```powershell
$env:CI = 'true'
flutter --suppress-analytics doctor -v
flutter --suppress-analytics pub get --enforce-lockfile
flutter --suppress-analytics analyze
flutter --suppress-analytics test
flutter --suppress-analytics run -d windows --dart-define=API_BASE_URL=http://127.0.0.1:5555
```

`CI=true` is the upstream Flutter bot-detector configuration; it short-circuits the optional Azure instance-metadata probe. An initial tool invocation in the engineering environment was rejected automatically for that probe. After read-only inspection of `flutter_tools/lib/src/base/bot_detector.dart`, the standard CI configuration prevented that network request and normal generation/dependency/test commands were allowed. No review control was disabled.

The production API origin must use HTTPS. No provider or backend secrets belong in `--dart-define`. The runtime cache refuses to open unless the linked SQLite provides the encryption `cipher` pragma. Cache keys and opaque session credentials are held in platform secure storage. Cache namespaces separate backend origins and explicit demo/live builds.

`scripts\check_desktop_prerequisites.ps1` (repository root) prints a read-only PASS/WARN/FAIL table for Git, Docker Desktop and its running engine, Compose, WSL 2, exact Flutter 3.47.4/Dart 3.13.3, Visual Studio C++ tools, Windows SDK, CMake, Ninja and Inno Setup 6. It installs nothing. Building Windows plugins also requires symlink support, which means Windows Developer Mode (Settings > System > For developers) or an elevated shell.

A credentialless demonstration is optional and visibly synthetic. `scripts\start_desktop_demo.ps1` performs the whole sequence below in an isolated Compose project using an ignored `.env.demo`; `scripts\stop_desktop_demo.ps1` stops it and keeps the demo database volume. Start the local backend with both `APP_ENV=local` and `DEMO_MODE=true`, run its `demo-seed` command, and add `--dart-define=DEMO_MODE=true` to a debug Windows run. The app also verifies the server's demo state; production builds never silently populate samples.

## Installer and update

Install Inno Setup 6 (`winget install --id JRSoftware.InnoSetup`; a per-user install lands in `%LOCALAPPDATA%\Programs\Inno Setup 6`, pass its `ISCC.exe` with `-Iscc`), then from `client/`:

```powershell
.\tool\build_windows.ps1 -ApiBaseUrl 'https://YOUR-AUTHORIZED-SERVER'
```

This runs locked dependencies, analysis, tests, `flutter build windows --release`, and `ISCC.exe installer/personal_staffer.iss`. Expected output is `client/build/installer/PersonalStaffer-0.1.0-unsigned-setup.exe`, **only after the command succeeds on Windows**. The current source handoff does not claim this installer exists. The script prints SHA256 checksums of actual files.

The per-user installer registers `personalstaffer://`, a Start menu shortcut and stable `PersonalStaffer.Desktop` application identity. The runner forwards link activation to an existing instance. Native toast integration uses the same app identity and a fixed GUID. Inno packaging currently produces an unsigned development installer. Add an authorized certificate/signing service separately; do not treat it as signed MSIX. Uninstall removes the binary and protocol registration; server records remain. Explicit sign-out clears sensitive device cache and pending changes before uninstall if required.

For updates, preserve application identity and cache schema, verify the new checksum/signature through a trusted channel, close the app and install the new package over the existing installation. Back up the server first for backend migrations. No downloaded executable is run automatically.

## Acceptance on the actual Windows device

```powershell
flutter --suppress-analytics test integration_test/device_storage_test.dart -d windows --dart-define=API_BASE_URL=https://YOUR-AUTHORIZED-SERVER
Start-Process 'personalstaffer://jobs/REPLACE-WITH-AN-AUTHORIZED-JOB-UUID'
```

Run foreground, minimized, closed, signed-out, reboot and reconnect checks. Check toast click to exact application/review/report; Google browser return; secure cache reopening after process restart; keyboard traversal; screen-reader names; small windows and enlarged fonts; and install/update/uninstall.

The present Windows delivery polls the authoritative inbox while the app is running. It suppresses the initial backlog and summarizes later batches. The Windows runner includes an opt-in tray mode with Open/Exit menu and a separate Windows-sign-in startup switch. Both default off; enabling tray mode keeps the process alive when the window closes. Exiting it stops local polling and the app catches up on reopening. The native runner and installer still need a real Windows build and lifecycle tests, so full M3/M8 native acceptance is not complete. Linux encryption and widget tests are not Windows device verification.

## Owner checklist for physical Phase C acceptance

Run the debug demo (`scripts\start_desktop_demo.ps1`) and tick each item, noting anything unexpected:

1. Settings > Desktop: enable "Keep notifications running when window closes"; close the window; a tray icon remains; right-click shows Open / Exit; Open restores the window; Exit stops the app.
2. Settings > Desktop: enable "Open Personal Staffer when I sign in to Windows"; confirm `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PersonalStaffer` exists; sign out/in and confirm the app starts in the tray; disable and confirm the value is removed.
3. Leave the app running for a minute; a Windows toast appears for a new inbox item when one is produced; clicking it opens the exact record.
4. Tab/Shift+Tab traverse every control with a visible focus ring; Alt+Left/Alt+Right move through history; Narrator reads destination names.
5. Windows Settings > Accessibility > Text size 150%: all screens remain usable; shrink the window below 1000 px wide: the bottom navigation bar appears.
6. Disable Wi-Fi: the sidebar footer turns amber "Offline"; saved records still open; Save shows Pending; re-enable Wi-Fi and the change synchronizes.
7. Sign out: the cache is cleared and the sign-in screen appears; sign back in with "Open local demo".


## Docker Desktop on this laptop: the crash-on-start trap (13 September 2026)

Docker Desktop 4.85 can leave AF_UNIX socket files behind after an unclean exit (`%LOCALAPPDATA%\Docker\run\*`, `%LOCALAPPDATA%\docker-secrets-engine\engine.sock`) that Windows reports as *"The file cannot be accessed by the system"*. On the next start the backend cannot delete them, dies with `initializing Inference manager / Secrets Engine: listening on unix://...: remove ...`, and shows a dialog whose only actions are **Quit** and **Reset to factory defaults**. The reset wipes every container and volume - the live Personal Staffer database. It was clicked once (13 September, 18:36); the data disk survived only because the backend died before the wipe ran. A verified copy of that disk was kept at `C:\Users\crick\DockerBackup\`.

- **Never click "Reset to factory defaults".** Run `scripts\repair_docker_sockets.ps1` instead: it moves the stale socket directories aside (never deletes), disables the Docker AI / inference features that own them, and starts Docker Desktop.
- The scheduled task **"Personal Staffer - repair and start Docker"** runs that script one minute after logon, so Docker and the backend (containers are `restart: unless-stopped`) come back after a reboot without any clicks.
- The scheduled task **"Personal Staffer - nightly database backup"** runs `scripts\backup_local.ps1` at 02:00 (wake-to-run, catch-up if missed): a compressed `pg_dump` of the live database into `%USERPROFILE%\PersonalStafferBackups`, 14 kept, each verified as a pg_dump archive. Restore instructions are in the script header. The encrypted restic path in BACKUP_RESTORE.md remains the plan for the hosted phase.
