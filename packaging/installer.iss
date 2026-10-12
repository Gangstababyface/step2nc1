#ifndef AppVersion
  #define AppVersion "1.3.0-rc3"
#endif

[Setup]
AppId={{3F498574-92DE-4A09-BF05-F435CCAE8D8D}
AppName=STEP2NC1
AppVersion={#AppVersion}
AppPublisher=STEP2NC1
DefaultDirName={localappdata}\Programs\STEP2NC1
DefaultGroupName=STEP2NC1
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
DisableStartupPrompt=yes
UninstallDisplayIcon={app}\STEP2NC1.exe
OutputDir=..\dist\installer
OutputBaseFilename=STEP2NC1-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Files]
Source: "..\dist\STEP2NC1\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\STEP2NC1"; Filename: "{app}\STEP2NC1.exe"; WorkingDir: "{userdocs}"
Name: "{userdesktop}\STEP2NC1"; Filename: "{app}\STEP2NC1.exe"; WorkingDir: "{userdocs}"

[Run]
Filename: "{app}\STEP2NC1.exe"; WorkingDir: "{userdocs}"; Flags: nowait skipifsilent

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  { Inno intentionally retains Ready when every earlier page is disabled.
    Queue its normal Install action once the window's message loop starts. }
  if (CurPageID = wpReady) and not WizardSilent then
  begin
    WizardForm.PageNameLabel.Caption := 'Installing STEP2NC1';
    WizardForm.PageDescriptionLabel.Caption := 'Setup starts automatically.';
    WizardForm.ReadyMemo.Visible := False;
    WizardForm.NextButton.Visible := False;
    WizardForm.BackButton.Visible := False;
    Log('Starting one-click installation automatically.');
    PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0); { BM_CLICK }
  end;
end;
