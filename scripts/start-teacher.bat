@echo off
chcp 65001 >nul
rem ============================================================================
rem  Sınav İzleme Sistemi - öğretmen başlatıcı
rem
rem  1) İlk çalıştırmada, internet varken: Python ortamını kurar, MediaMTX'i indirir
rem  2) Güvenlik duvarı kurallarını denetler; eksikse yönetici izniyle ekler:
rem       UDP 47000 keşif, TCP 8000 API, TCP 8554 RTSP - yalnızca Özel + Ortak profiller
rem  3) MediaMTX'i, sonra Python sunucusunu başlatır ve paneli tarayıcıda açar
rem     (sistem zaten çalışıyorsa yalnızca paneli yeniden açar)
rem
rem  Portları server\config.yaml içinde değiştirirseniz aşağıdaki üç satırı da değiştirin.
rem ============================================================================
setlocal EnableExtensions

set "API_PORT=8000"
set "DISCOVERY_PORT=47000"
set "RTSP_PORT=8554"

set "RULE_DISCOVERY=Sinav Izleme - Kesif (UDP %DISCOVERY_PORT%)"
set "RULE_API=Sinav Izleme - API (TCP %API_PORT%)"
set "RULE_RTSP=Sinav Izleme - RTSP (TCP %RTSP_PORT%)"

cd /d "%~dp0.."
set "ROOT=%CD%"

if /i "%~1"=="--firewall" goto firewall

title Sınav İzleme - Öğretmen
echo.
echo  ==== Sınav İzleme Sistemi - öğretmen başlatıcı ====
echo.

rem Sistem arka planda zaten çalışıyorsa (panel penceresi kapatılmış olabilir) yalnızca
rem paneli yeniden aç.
curl.exe -s -m 2 -o nul "http://127.0.0.1:%API_PORT%/api/info" 2>nul
if not errorlevel 1 goto already_running

rem ---------------------------------------------------------------- 1) Python
set "PY=%ROOT%\.venv\Scripts\python.exe"
if exist "%PY%" goto python_ready

echo  [1/4] İlk kurulum: Python ortamı hazırlanıyor. Bu adım İNTERNET gerektirir.
set "BASEPY="
where py >nul 2>&1
if not errorlevel 1 set "BASEPY=py -3"
if defined BASEPY goto have_python
where python >nul 2>&1
if not errorlevel 1 set "BASEPY=python"
if defined BASEPY goto have_python
echo.
echo  HATA: Python bulunamadı. https://www.python.org/downloads/ adresinden Python 3.11
echo        veya daha yenisini kurun. Kurulumda "Add python.exe to PATH" kutusunu işaretleyin.
goto fail

:have_python
%BASEPY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto old_python
%BASEPY% -m venv "%ROOT%\.venv"
if errorlevel 1 goto venv_failed
"%PY%" -m pip install --disable-pip-version-check -r "%ROOT%\server\requirements.txt"
if errorlevel 1 goto pip_failed
goto python_ready

:old_python
echo.
echo  HATA: Python 3.11 veya daha yenisi gerekli. Kurulu sürüm çok eski ya da çalışmıyor.
goto fail

:venv_failed
echo.
echo  HATA: Python sanal ortamı oluşturulamadı.
goto fail

:pip_failed
echo.
echo  HATA: Python paketleri indirilemedi. İnternet bağlantınızı kontrol edip yeniden deneyin.
rmdir /s /q "%ROOT%\.venv" >nul 2>&1
goto fail

:python_ready
echo  [1/4] Python ortamı hazır.

rem -------------------------------------------------------------- 2) MediaMTX
if exist "%ROOT%\mediamtx\mediamtx.exe" goto mediamtx_ready
echo  [2/4] MediaMTX indiriliyor. Bu adım İNTERNET gerektirir.
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\fetch-mediamtx.ps1"
if errorlevel 1 goto mediamtx_failed
if not exist "%ROOT%\mediamtx\mediamtx.exe" goto mediamtx_failed
goto mediamtx_ready

:mediamtx_failed
echo.
echo  HATA: MediaMTX indirilemedi. İnternet varken yeniden deneyin.
goto fail

:mediamtx_ready
echo  [2/4] MediaMTX hazır.

rem ------------------------------------------------------- 3) Güvenlik duvarı
call :check_rules
if not defined MISSING goto firewall_ready
echo  [3/4] Güvenlik duvarı kuralları eksik. Yönetici izni istenecek; açılan pencerede "Evet" deyin.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--firewall' -Verb RunAs -Wait"
call :check_rules
if not defined MISSING goto firewall_ready
echo.
echo  UYARI: Güvenlik duvarı kuralları EKLENEMEDİ. Öğrenciler sunucuya bağlanamayabilir.
echo         Bu dosyaya sağ tıklayıp "Yönetici olarak çalıştır" ile yeniden deneyin.
echo.
goto firewall_done

:firewall_ready
echo  [3/4] Güvenlik duvarı kuralları hazır: UDP %DISCOVERY_PORT%, TCP %API_PORT%, TCP %RTSP_PORT% - Özel + Ortak ağ.

:firewall_done

rem ------------------------------------------------------- 4) Servisleri başlat
if not exist "%ROOT%\data" mkdir "%ROOT%\data"

tasklist /fi "imagename eq mediamtx.exe" 2>nul | find /i "mediamtx.exe" >nul
if not errorlevel 1 goto mediamtx_running
echo  [4/4] MediaMTX başlatılıyor: ayrı bir pencerede açılır, kapatmayın.
start "MediaMTX - Sinav Izleme (kapatmayin)" /min /d "%ROOT%" "%ROOT%\mediamtx\mediamtx.exe" "%ROOT%\mediamtx\mediamtx.yml"
goto start_server

:mediamtx_running
echo  [4/4] MediaMTX zaten çalışıyor.

:start_server
echo        Sunucu başlatılıyor; panel birkaç saniye içinde tarayıcıda açılacak.
echo.
start "" /b cmd /c "ping -n 5 127.0.0.1 >nul & start http://localhost:%API_PORT%/panel"

"%PY%" "%ROOT%\server\run.py"
set "SERVER_EXIT=%ERRORLEVEL%"

echo.
echo  Sunucu durdu. MediaMTX kapatılıyor...
taskkill /im mediamtx.exe /f >nul 2>&1
rem 10 = panelden "Sistemi kapat" denildi: sorulacak bir şey yok, pencere de kapanır.
if "%SERVER_EXIT%"=="10" exit /b 0
echo  Bu pencereyi kapatabilirsiniz.
pause
exit /b 0

:already_running
echo  Sınav sistemi zaten çalışıyor; panel tarayıcıda açılıyor.
start "" "http://localhost:%API_PORT%/panel"
ping -n 3 127.0.0.1 >nul
exit /b 0

rem ============================================================================
rem  Güvenlik duvarı kurallarını ekler. Yönetici olarak çalışır (yukarıdan çağrılır).
rem ============================================================================
:firewall
title Sınav İzleme - Güvenlik duvarı
echo.
echo  Windows Güvenlik Duvarı'na gelen bağlantı kuralları ekleniyor.
echo  Kurallar yalnızca "Özel" ve "Ortak" ağ profilleri için geçerlidir.
echo.
rem  S-1-16-12288 = yüksek bütünlük düzeyi, yani yönetici olarak çalışıyor
whoami /groups | find "S-1-16-12288" >nul
if errorlevel 1 goto not_admin
call :ensure_rule "%RULE_DISCOVERY%" UDP %DISCOVERY_PORT%
call :ensure_rule "%RULE_API%" TCP %API_PORT%
call :ensure_rule "%RULE_RTSP%" TCP %RTSP_PORT%
echo.
echo  Bitti. Bu pencere 8 saniye içinde kapanacak.
timeout /t 8 >nul
exit /b 0

:not_admin
echo  HATA: Bu adım yönetici yetkisi gerektirir. Kural eklenmedi.
timeout /t 8 >nul
exit /b 1

rem  call :ensure_rule "kural adı" PROTOKOL PORT
:ensure_rule
netsh advfirewall firewall show rule name=%1 >nul 2>&1
if not errorlevel 1 goto rule_exists
netsh advfirewall firewall add rule name=%1 dir=in action=allow protocol=%2 localport=%3 profile=private,public >nul
if errorlevel 1 goto rule_failed
echo    [EKLENDİ]   %~1  - gelen %2 %3, profiller: Özel + Ortak
exit /b 0
:rule_exists
echo    [ZATEN VAR] %~1
exit /b 0
:rule_failed
echo    [HATA]      %~1 eklenemedi
exit /b 1

rem  Kurallardan biri eksikse MISSING değişkenini ayarlar.
:check_rules
set "MISSING="
netsh advfirewall firewall show rule name="%RULE_DISCOVERY%" >nul 2>&1
if errorlevel 1 set "MISSING=1"
netsh advfirewall firewall show rule name="%RULE_API%" >nul 2>&1
if errorlevel 1 set "MISSING=1"
netsh advfirewall firewall show rule name="%RULE_RTSP%" >nul 2>&1
if errorlevel 1 set "MISSING=1"
exit /b 0

:fail
echo.
echo  Başlatma tamamlanamadı. Ayrıntılı kurulum adımları: docs\KURULUM.md
pause
exit /b 1
