; ============================================================================
;  Sınav Ajanı - kurulum (öğrenci bilgisayarı)
;
;  Yalnızca programı kopyalar ve masaüstüne kısayol koyar. Servis, başlangıç kaydı ya da
;  zamanlanmış görev EKLEMEZ: program yalnızca öğrenci açtığında çalışır.
;  Derleme: installer\hazirla.ps1
; ============================================================================
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AgentExe
  #define AgentExe "..\publish\SinavAjan.exe"
#endif
#ifndef OutputDir
  #define OutputDir "..\publish"
#endif
#define AppName "Sınav Ajanı"

[Setup]
AppId={{B2B7C2A9-7C1B-4C54-8E57-2F1E3D9A6C02}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Sınav İzleme
DefaultDirName={autopf}\Sinav Ajani
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=SinavAjan-Kurulum
SetupIconFile=sinav-ajan.ico
UninstallDisplayIcon={app}\SinavAjan.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
; Program zaten sıkıştırılmıştır; yeniden sıkıştırmak yalnızca kurulumu yavaşlatır.
Compression=none
ShowLanguageDialog=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "{#AgentExe}"; DestDir: "{app}"; DestName: "SinavAjan.exe"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SinavAjan.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\SinavAjan.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\SinavAjan.exe"; WorkingDir: "{app}"; Description: "{#AppName} şimdi başlatılsın"; Flags: postinstall nowait skipifsilent unchecked runascurrentuser

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/im SinavAjan.exe /f"; Flags: runhidden; RunOnceId: "Durdur"

[UninstallDelete]
; Programın kendi küçük kayıt dosyası; öğrencinin dosyalarına dokunulmaz.
Type: filesandordirs; Name: "{localappdata}\SinavAjan"
Type: filesandordirs; Name: "{app}"
