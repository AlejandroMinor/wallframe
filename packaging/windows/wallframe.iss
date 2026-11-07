; The installer: iscc /DAppVersion=1.2.3 packaging\windows\wallframe.iss, after build.sh.
; It installs for this user alone, so it asks for no administrator.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7C4E8E1A-5B2F-4B7D-9C31-2F6A0D8E4A11}
AppName=wallframe
AppVersion={#AppVersion}
AppPublisher=Alejandro Minor
AppPublisherURL=https://github.com/AlejandroMinor/wallframe
DefaultDirName={autopf}\wallframe
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=wallframe-{#AppVersion}-setup
SetupIconFile=wallframe.ico
UninstallDisplayIcon={app}\wallframe.exe
DisableReadyPage=yes
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\wallframe\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\wallframe"; Filename: "{app}\wallframe.exe"; AppUserModelID: "AlejandroMinor.wallframe"
Name: "{autodesktop}\wallframe"; Filename: "{app}\wallframe.exe"; AppUserModelID: "AlejandroMinor.wallframe"; Tasks: desktopicon

[Run]
Filename: "{app}\wallframe.exe"; Description: "{cm:LaunchProgram,wallframe}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\app"
