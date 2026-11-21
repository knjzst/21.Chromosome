; Inno Setup script – builds LowDarts-Setup.exe from the PyInstaller folder
#define AppVersion GetEnv("LOWDARTS_VERSION")
#if AppVersion == ""
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{6B1F3C1E-5D2A-4C8B-9E51-0D5A7F2B9C11}
AppName=LowDarts
AppVersion={#AppVersion}
AppPublisher=LowDarts
DefaultDirName={autopf}\LowDarts
DefaultGroupName=LowDarts
OutputDir=..\dist
OutputBaseFilename=LowDarts-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzlich:"

[Files]
Source: "..\dist\LowDarts\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\LowDarts"; Filename: "{app}\LowDarts.exe"
Name: "{autodesktop}\LowDarts"; Filename: "{app}\LowDarts.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LowDarts.exe"; Description: "LowDarts starten"; Flags: nowait postinstall skipifsilent
