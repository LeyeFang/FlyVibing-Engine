; ============================================================
;  FlyVibingEngine - Inno Setup script (offline installer, v1)
;  Build : Utils/Dev/Installer/build_installer.py (invokes ISCC with /D defines)
;  Docs  : Utils/Dev/Installer/README.md
;  Notes : ASCII-only (installer UI language = English; Chinese .isl later)
; ============================================================

#ifndef StageDir
  #define StageDir "..\build\stage"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{7E3A9C4B-52D1-4F8E-9B2A-6C1D4E8F0A37}
AppName=FlyVibingEngine
AppVersion={#AppVersion}
AppVerName=FlyVibingEngine {#AppVersion}
DefaultDirName={autopf}\FlyVibingEngine
DefaultGroupName=FlyVibingEngine
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=FlyVibingEngine-Setup-{#AppVersion}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
; per-user by default; the wizard shows an "install for me / all users" choice
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
ChangesEnvironment=yes
ChangesAssociations=yes
AllowNoIcons=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "addtopath"; Description: "Add 'engine-editor-mcp' to PATH (for AI agent workspaces)"; GroupDescription: "Integration:"
Name: "fileassoc"; Description: "Associate .myproj project files with FlyVibingEngine"; GroupDescription: "Integration:"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\FlyVibingEngine"; Filename: "{app}\startup.bat"; WorkingDir: "{app}"
Name: "{group}\Uninstall FlyVibingEngine"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FlyVibingEngine"; Filename: "{app}\startup.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; PATH entry (HKA = HKCU\Environment or HKLM\...\Environment per install mode)
Root: HKA; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath('{app}')
; .myproj file association (opens the editor with the file path as argument)
Root: HKA; Subkey: "Software\Classes\.myproj"; ValueType: string; ValueName: ""; ValueData: "FlyVibingEngine.Project"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\FlyVibingEngine.Project"; ValueType: string; ValueName: ""; ValueData: "FlyVibingEngine Project"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\FlyVibingEngine.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\startup.bat"" ""%1"""; Flags: uninsdeletekey; Tasks: fileassoc

[Run]
Filename: "{app}\startup.bat"; Description: "Launch FlyVibingEngine now"; Flags: nowait postinstall skipifsilent

[Code]
function EnvRegRoot(): Integer;
begin
  if IsAdminInstallMode then
    Result := HKLM
  else
    Result := HKCU;
end;

function EnvRegSubKey(): string;
begin
  if IsAdminInstallMode then
    Result := 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
  else
    Result := 'Environment';
end;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(EnvRegRoot(), EnvRegSubKey(), 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  OrigPath, AppDir, NewPath: string;
  Index: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  if not RegQueryStringValue(EnvRegRoot(), EnvRegSubKey(), 'Path', OrigPath) then
    exit;
  AppDir := ExpandConstant('{app}');
  Index := Pos(Uppercase(AppDir), Uppercase(OrigPath));
  if Index = 0 then
    exit;
  Delete(OrigPath, Index, Length(AppDir));
  NewPath := OrigPath;
  while Pos(';;', NewPath) > 0 do
    StringChangeEx(NewPath, ';;', ';', True);
  if (Length(NewPath) > 0) and (NewPath[1] = ';') then
    Delete(NewPath, 1, 1);
  if (Length(NewPath) > 0) and (NewPath[Length(NewPath)] = ';') then
    Delete(NewPath, Length(NewPath), 1);
  RegWriteExpandStringValue(EnvRegRoot(), EnvRegSubKey(), 'Path', NewPath);
end;
