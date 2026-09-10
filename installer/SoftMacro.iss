; SoftMacro installer script (Inno Setup 6+).
;
; Build:  build_installer.bat   (or:  ISCC.exe installer\SoftMacro.iss)
; Input:  ..\dist\SoftMacro\   (PyInstaller one-folder output)
; Output: ..\dist\installer\SoftMacroSetup.exe
;
; Per-user install: no admin prompt, everything under %LOCALAPPDATA%.
; Macros live in %APPDATA%\SoftMacro and are never touched by install,
; upgrade or uninstall.

#define AppName "SoftMacro"
; Version comes from the VERSION file in the project root.
#define AppVersion Trim(FileRead(FileOpen(AddBackslash(SourcePath) + "..\VERSION")))
#define AppPublisher "Wayne Scicluna"
#define AppURL "https://github.com/JagerWayne/SoftMacro"
#define AppExe "SoftMacro.exe"

[Setup]
AppId={{D8F1A6C4-2E7B-4A93-B5D0-6C9E3F1A7B24}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=SoftMacroSetup
SetupIconFile=..\softmacro.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
MinVersion=10.0
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start SoftMacro when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\SoftMacro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; PyInstaller one-folder layout: drop stale files from a previous version
; (e.g. renamed or removed data files) before copying the new build.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\SoftMacro.exe"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "SoftMacro"; ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
; Interactive install: offer to launch when the user clicks Finish.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall; Check: not WizardSilent

; Silent update (built-in updater): postinstall entries are skipped, so
; relaunch the app explicitly once the files have been replaced.
Filename: "{app}\{#AppExe}"; Flags: nowait runhidden; Check: WizardSilent
