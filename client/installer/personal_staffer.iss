; Build with Inno Setup 6 after `flutter build windows --release`.
; This creates an unsigned development installer unless your authorized
; SignTool configuration is supplied separately. No certificate in source.
#define AppVersion "0.1.0"
[Setup]
AppId={{CFAB06DC-53DC-4990-BB42-04AAD54D5F63}
AppName=Personal Staffer
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Personal Staffer
DefaultGroupName=Personal Staffer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=PersonalStaffer-{#AppVersion}-unsigned-setup
UninstallDisplayIcon={app}\personal_staffer.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
[Files]
Source: "..\build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Personal Staffer"; Filename: "{app}\personal_staffer.exe"; AppUserModelID: "PersonalStaffer.Desktop"
[Registry]
Root: HKCU; Subkey: "Software\Classes\personalstaffer"; ValueType: string; ValueName: ""; ValueData: "URL:Personal Staffer Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\personalstaffer"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\personalstaffer\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\personal_staffer.exe"" ""%1"""
Root: HKCU; Subkey: "Software\PersonalStaffer"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "PersonalStaffer"; Flags: uninsdeletevalue
[Run]
Filename: "{app}\personal_staffer.exe"; Description: "Open Personal Staffer"; Flags: nowait postinstall skipifsilent
