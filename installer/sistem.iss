; ============================================================================
;  Sınav İzleme Sistemi - kurulum (sınavı yapan kişinin bilgisayarı)
;
;  Her şey içindedir: Python, gereken paketler, MediaMTX ve öğrenci programı.
;  Kurulum internet gerektirmez. Derleme: installer\hazirla.ps1
; ============================================================================
#ifndef AppVersion
  #define AppVersion "1.0.2"
#endif
#ifndef Source
  #define Source "..\build\sistem"
#endif
#ifndef OutputDir
  #define OutputDir "..\publish"
#endif
#define AppName "Sınav İzleme Sistemi"

[Setup]
AppId={{6F0B8E0D-3C1D-4E0B-9B36-5D2F6C1E7A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Sınav İzleme
DefaultDirName={autopf}\Sinav Izleme
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=SinavIzleme-Kurulum
SetupIconFile=sinav-izleme.ico
UninstallDisplayIcon={app}\sinav-izleme.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ShowLanguageDialog=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Messages]
; Hazır çeviride düğmenin adı (Kur) ile yazı (Sonraki) uyuşmuyor; yazılar sadeleştirildi.
tr.ReadyLabel2a=Kuruluma başlamak için Kur düğmesine basın.
tr.ReadyLabel2b=Kuruluma başlamak için Kur düğmesine basın.
tr.FinishedLabel=[name] kuruldu. Masaüstündeki simgeye çift tıklayarak açabilirsiniz.
tr.FinishedLabelNoIcons=[name] kuruldu.
tr.ClickFinish=Bu pencereyi kapatmak için Bitti düğmesine basın.

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "sinav-izleme.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server\run.py"" --app"; WorkingDir: "{app}"; IconFilename: "{app}\sinav-izleme.ico"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server\run.py"" --app"; WorkingDir: "{app}"; IconFilename: "{app}\sinav-izleme.ico"

[Run]
; Öğrenci bilgisayarlarının bağlanabilmesi için güvenlik duvarı izinleri (yalnızca Özel + Ortak ağ).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Kesif (UDP 47000)"""; Flags: runhidden; StatusMsg: "Güvenlik duvarı izinleri ekleniyor..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Sinav Izleme - Kesif (UDP 47000)"" dir=in action=allow protocol=UDP localport=47000 profile=private,public"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - API (TCP 8000)"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Sinav Izleme - API (TCP 8000)"" dir=in action=allow protocol=TCP localport=8000 profile=private,public"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - RTSP (TCP 8554)"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Sinav Izleme - RTSP (TCP 8554)"" dir=in action=allow protocol=TCP localport=8554 profile=private,public"; Flags: runhidden
; Programların kendisi için izin: ilk açılışta "Windows Güvenlik Uyarısı" sorulmaz.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Sunucu"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Sinav Izleme - Sunucu"" dir=in action=allow program=""{app}\python\pythonw.exe"" profile=private,public"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Ekran Aktarimi"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Sinav Izleme - Ekran Aktarimi"" dir=in action=allow program=""{app}\mediamtx\mediamtx.exe"" profile=private,public"; Flags: runhidden
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server\run.py"" --app"; WorkingDir: "{app}"; Description: "{#AppName} şimdi başlatılsın"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
; Çalışıyorsa önce kapat (sunucu MediaMTX'i de kapatır).
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\server\run.py"" --stop"; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "Durdur"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Kesif (UDP 47000)"""; Flags: runhidden; RunOnceId: "Kural1"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - API (TCP 8000)"""; Flags: runhidden; RunOnceId: "Kural2"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - RTSP (TCP 8554)"""; Flags: runhidden; RunOnceId: "Kural3"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Sunucu"""; Flags: runhidden; RunOnceId: "Kural4"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Sinav Izleme - Ekran Aktarimi"""; Flags: runhidden; RunOnceId: "Kural5"

[UninstallDelete]
; Sınav kayıtları ve teslimler burada DEĞİLDİR (panelde seçilen sınav klasöründedir) ve silinmez.
Type: filesandordirs; Name: "{app}"

[Code]
// Yeni sürüm eskisinin üzerine kurulurken sistem çalışıyorsa önce kapatılır; yoksa dosyalar
// kullanımda olduğu için değiştirilemez.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\python\pythonw.exe')) and FileExists(ExpandConstant('{app}\server\run.py')) then
    Exec(ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\server\run.py') + '" --stop',
         ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
