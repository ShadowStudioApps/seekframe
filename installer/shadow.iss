; Seekframe installer (formerly Shadow; Inno Setup 6, free: https://jrsoftware.org).
; Build with build_installer.bat (it reads VERSION from render_core.py and needs dist\Seekframe.exe from build_exe.bat).
; Installs per user (no admin) to %LOCALAPPDATA%\Seekframe; an existing Shadow install keeps its folder (same AppId,
; UsePreviousAppDir) and gets Seekframe.exe in place of Shadow.exe.
; Settings (%USERPROFILE%\.shadow_renderer.json) and logs are never touched, also not by the uninstaller.

#ifndef AppVer
  #define AppVer "0.0"
#endif

[Setup]
AppId={{8C4C2F4E-6B1E-4C1A-9E57-5A4D2B7C9E21}
AppName=Seekframe
AppVersion={#AppVer}
AppVerName=Seekframe {#AppVer}
AppPublisher=Shadow Studio
AppPublisherURL=https://github.com/ShadowStudioApps
AppSupportURL=https://github.com/ShadowStudioApps/seekframe/issues
VersionInfoVersion={#AppVer}
DefaultDirName={localappdata}\Seekframe
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Seekframe-{#AppVer}-Setup
SetupIconFile=..\assets\shadow.ico
UninstallDisplayIcon={app}\Seekframe.exe
UninstallDisplayName=Seekframe {#AppVer}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
; always write %TEMP%\Setup Log <date> #nnn.txt (clues if an update ever fails)
SetupLogging=yes
RestartApplications=no
ShowLanguageDialog=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ar"; MessagesFile: "compiler:Languages\Arabic.isl"

[CustomMessages]
en.StartMenuIcon=Create a Start menu shortcut
ar.StartMenuIcon=إنشاء اختصار في قائمة ابدأ
en.Needed=Seekframe needs these (installed with winget, internet required):
ar.Needed=Seekframe يحتاج هذه البرامج (تُنصَّب عبر winget، يحتاج إنترنت):
en.NeedChrome=Install Google Chrome (Seekframe renders with it)
ar.NeedChrome=تنصيب Google Chrome (Seekframe يرندر بيه)
en.NeedFFmpeg=Install ffmpeg (encoding and the quality check)
ar.NeedFFmpeg=تنصيب ffmpeg (للترميز وفحص الجودة)
en.InstallingChrome=Installing Google Chrome (a console window opens)...
ar.InstallingChrome=جاري تنصيب Google Chrome (تنفتح نافذة أوامر)...
en.InstallingFFmpeg=Installing ffmpeg (a console window opens)...
ar.InstallingFFmpeg=جاري تنصيب ffmpeg (تنفتح نافذة أوامر)...
en.NoWinget=winget was not found on this PC, so these could not be installed automatically:%n%n%1%nInstall them yourself, then open Seekframe and check the top bar (or press "Install missing").
ar.NoWinget=ما لگينا winget بهذه الحاسبة، فما گدرنا ننصّب هذه تلقائياً:%n%n%1%nنصّبها بنفسك، وبعدين افتح Seekframe وشوف الشريط الفوگاني (أو اضغط "Install missing").
en.FFmpegFresh=ffmpeg was just installed. If Seekframe shows "ffmpeg (missing)", sign out and back in (or restart Windows) once.
ar.FFmpegFresh=ffmpeg انتصب هسه. إذا Seekframe طلّع "ffmpeg (missing)"، سوّي تسجيل خروج ودخول (أو ريستارت) مرة وحدة.

[Tasks]
; 3.27: never in a silent install (/SILENT, /VERYSILENT, winget, the in-app update): the winget console waits for the
;   user to accept terms and "|| pause" for a key, so an unattended install never finished (winget-pkgs validation failed).
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "{cm:StartMenuIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "chrome"; Description: "{cm:NeedChrome}"; GroupDescription: "{cm:Needed}"; Check: NeedChrome and not WizardSilent
Name: "ffmpeg"; Description: "{cm:NeedFFmpeg}"; GroupDescription: "{cm:Needed}"; Check: NeedFFmpeg and not WizardSilent

[Files]
Source: "..\dist\Seekframe.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\shadow.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; 3.25: the app was called Shadow - remove the old exe and its shortcuts when updating
Type: files; Name: "{app}\Shadow.exe"
Type: files; Name: "{autoprograms}\Shadow.lnk"
Type: files; Name: "{autodesktop}\Shadow.lnk"

[Icons]
Name: "{autoprograms}\Seekframe"; Filename: "{app}\Seekframe.exe"; WorkingDir: "{app}"; IconFilename: "{app}\shadow.ico"; Tasks: startmenuicon
Name: "{autodesktop}\Seekframe"; Filename: "{app}\Seekframe.exe"; WorkingDir: "{app}"; IconFilename: "{app}\shadow.ico"; Tasks: desktopicon

[Run]
; visible console: winget shows its own prompts (the user accepts Chrome's / ffmpeg's terms there)
Filename: "{cmd}"; Parameters: "/c winget install -e --id Google.Chrome || pause"; StatusMsg: "{cm:InstallingChrome}"; Tasks: chrome; Check: HasWinget; Flags: waituntilterminated
Filename: "{cmd}"; Parameters: "/c winget install -e --id Gyan.FFmpeg || pause"; StatusMsg: "{cm:InstallingFFmpeg}"; Tasks: ffmpeg; Check: HasWinget; Flags: waituntilterminated
Filename: "{app}\Seekframe.exe"; Description: "{cm:LaunchProgram,Seekframe}"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent
; the in-app updater runs the setup with /SILENT /relaunch=1: start Shadow again when done.
; PYINSTALLER_RESET_ENVIRONMENT=1: the old Shadow (onefile) handed its _PYI_* variables down to this setup; without the reset
; the new Shadow.exe would look for python3xx.dll in the old copy's deleted _MEI folder ("Failed to load Python DLL", v3.0 -> 3.1)
Filename: "{cmd}"; Parameters: "/c set PYINSTALLER_RESET_ENVIRONMENT=1&& start """" ""{app}\Seekframe.exe"""; WorkingDir: "{app}"; Flags: nowait runhidden; Check: WantRelaunch

[Code]
function OnPath(Name: String): Boolean;
begin
  Result := FileSearch(Name, GetEnv('PATH')) <> '';
end;

function ChromePresent: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\Google\Chrome\Application\chrome.exe'))
    or FileExists(ExpandConstant('{commonpf32}\Google\Chrome\Application\chrome.exe'))
    or FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe'));
end;

function NeedChrome: Boolean;
begin
  Result := not ChromePresent;
end;

function NeedFFmpeg: Boolean;
begin
  Result := not (OnPath('ffmpeg.exe') and OnPath('ffprobe.exe'));
end;

function WantRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;

function HasWinget: Boolean;
begin
  Result := OnPath('winget.exe');
end;

function ShadowRunningHere: Boolean;
var rc: Integer;
begin
  // a Shadow.exe started from THIS install folder (another copy elsewhere does not block the update)
  Exec('powershell.exe', '-NoProfile -NonInteractive -Command "if (Get-Process Seekframe,Shadow -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' +
       ExpandConstant('{app}') + '\*'' }) { exit 0 } else { exit 1 }"', '', SW_HIDE, ewWaitUntilTerminated, rc);
  Result := rc = 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var i: Integer;
begin
  // In-app update (/relaunch=1): the old Shadow closes itself right after starting this setup, but a onefile exe keeps
  // its file locked for a second or two while it cleans up - replacing it then failed silently (first update attempt
  // stayed on the old version). Wait until it is really gone (max 30 s), then install.
  Result := '';
  if WantRelaunch then begin
    i := 0;
    while ShadowRunningHere and (i < 60) do begin Sleep(500); i := i + 1; end;
    Log(Format('Shadow update: waited %d ms for the old Shadow to exit (still running: %d)', [i * 500, Ord(ShadowRunningHere)]));
  end;
end;

function InitializeSetup: Boolean;
begin
  Log(Format('Shadow setup: Chrome present=%d, ffmpeg+ffprobe on PATH=%d, winget on PATH=%d', [Ord(ChromePresent), Ord(not NeedFFmpeg), Ord(HasWinget)]));
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Missing: String;
begin
  if CurStep = ssPostInstall then begin
    Missing := '';
    if WizardIsTaskSelected('chrome') and not HasWinget then Missing := Missing + '- Google Chrome (google.com/chrome)' + #13#10;
    if WizardIsTaskSelected('ffmpeg') and not HasWinget then Missing := Missing + '- ffmpeg (ffmpeg.org)' + #13#10;
    if Missing <> '' then
      SuppressibleMsgBox(FmtMessage(CustomMessage('NoWinget'), [Missing]), mbInformation, MB_OK, IDOK)
    else if WizardIsTaskSelected('ffmpeg') then
      SuppressibleMsgBox(CustomMessage('FFmpegFresh'), mbInformation, MB_OK, IDOK);
  end;
end;
