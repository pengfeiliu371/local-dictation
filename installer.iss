; Build with Inno Setup 6 after running build_portable.ps1.
#define AppName "Local Dictation"
#define AppVersion "1.0.0"
#define AppPublisher "Pengfei"
#define AppExeName "Local Dictation.exe"

[Setup]
AppId={{2F38D7B9-5484-4D30-A3BF-5343A062A6A3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Local Dictation
DefaultGroupName={#AppName}
OutputDir=installer-output
OutputBaseFilename=Local-Dictation-Setup
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=local-dictation.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\Local Dictation\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autodesktop}\Local Dictation"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\Local Dictation"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start Local Dictation"; Flags: nowait postinstall skipifsilent
