<#
.SYNOPSIS
    Sınav ajanının GERÇEK Windows üzerinde uçtan uca testi (GitHub Actions'ta çalışır).

.DESCRIPTION
    MediaMTX'i ve Python sunucusunu başlatır, SinavAjan.exe'yi çalıştırır ve arayüzünü
    UI Automation ile bir öğrenci gibi kullanır:

      keşif -> sınıf/öğretmen onayı -> giriş -> ekran yayını (ffmpeg/gdigrab -> MediaMTX)
      -> sınav başlatma -> izinsiz programların kapatılması -> öndeki pencere toleransı
      -> kaydetmeden teslim uyarısı -> teslim -> ajanın kapanması ve iz bırakmaması
      -> ajan zorla sonlandırıldığında ffmpeg'in de kapanması (Job Object)

    Packet Tracer bu ortamda kurulu olmadığı için "Packet Tracer açılamadı" olayı beklenir.
    Yönetici olarak ve etkileşimli bir masaüstü oturumunda çalıştırılmalıdır.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File agent\tests\E2E\windows-e2e.ps1 -AgentDir publish\SinavAjan
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AgentDir,
    [string]$Python = 'python',
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$AgentDir = (Resolve-Path $AgentDir).Path
if (-not $OutDir) { $OutDir = Join-Path $root 'e2e-out' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$shots = Join-Path $OutDir 'shots'
New-Item -ItemType Directory -Force -Path $shots | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class Native
{
    public delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);

    public static List<string> Windows()
    {
        var list = new List<string>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hwnd)) return true;
            var text = new StringBuilder(300);
            GetWindowText(hwnd, text, 300);
            uint pid;
            GetWindowThreadProcessId(hwnd, out pid);
            list.Add(pid + "|" + text);
            return true;
        }, IntPtr.Zero);
        return list;
    }

    // A background process may not take the foreground; a simulated ALT key lifts that restriction.
    public static void Focus(IntPtr hwnd)
    {
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        ShowWindow(hwnd, 5);
        SetForegroundWindow(hwnd);
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
    }

    public static uint ForegroundPid()
    {
        uint pid;
        GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        return pid;
    }
}
"@

# ------------------------------------------------------------------ helpers

$script:failures = New-Object System.Collections.Generic.List[string]
$script:agent = $null
$base = 'http://127.0.0.1:8000'

function Step([string]$title) { Write-Host ''; Write-Host "=== $title" }

function Check([bool]$condition, [string]$what) {
    if ($condition) { Write-Host "  [OK]   $what" }
    else { Write-Host "  [FAIL] $what"; $script:failures.Add($what) }
}

function Wait-Until([scriptblock]$condition, [double]$timeoutSec, [int]$intervalMs = 400) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try { $result = & $condition; if ($result) { return $result } } catch { }
        Start-Sleep -Milliseconds $intervalMs
    }
    return $null
}

function Shot([string]$name) {
    try {
        $area = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bitmap = New-Object System.Drawing.Bitmap($area.Width, $area.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($area.Left, $area.Top, 0, 0, $bitmap.Size)
        $bitmap.Save((Join-Path $shots "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose(); $bitmap.Dispose()
    } catch { Write-Host "  (ekran görüntüsü alınamadı: $($_.Exception.Message))" }
}

function Show-Windows {
    foreach ($entry in [Native]::Windows()) {
        $parts = $entry.Split('|', 2)
        if (-not $parts[1]) { continue }
        $path = ''
        try { $path = (Get-Process -Id $parts[0] -ErrorAction Stop).Path } catch { }
        Write-Host ("    pid {0,-6} {1}  [{2}]" -f $parts[0], $path, $parts[1])
    }
}

function Curl-Text([string[]]$arguments) {
    $output = & curl.exe -s @arguments
    return ($output -join "`n")
}

function Get-Snapshot {
    $raw = Curl-Text @('-m', '5', "$base/panel/api/state")
    if (-not $raw) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Get-Student([string]$numara) {
    $snapshot = Get-Snapshot
    if (-not $snapshot) { return $null }
    return $snapshot.students | Where-Object { $_.numara -eq $numara } | Select-Object -First 1
}

function Get-Events([string]$numara) {
    $raw = Curl-Text @('-m', '5', "$base/panel/api/events?numara=$numara")
    if (-not $raw) { return @() }
    return @(($raw | ConvertFrom-Json).events)
}

function Count-Events([string]$numara, [string]$type, [string]$namePattern = '') {
    return @(Get-Events $numara | Where-Object {
        $_.type -eq $type -and (-not $namePattern -or ("$($_.details.name)" -match $namePattern))
    }).Count
}

# Not through curl.exe: Windows PowerShell strips the double quotes of a JSON argument.
function Panel-Post([string]$path, [string]$json = '{}') {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base$path" -TimeoutSec 10 `
            -Headers @{ 'X-Panel' = '1' } -ContentType 'application/json' -Body $json
        return $response.Content
    } catch {
        return "HATA: $($_.Exception.Message)"
    }
}

# ---- UI Automation over the agent's windows -------------------------------------------

$AE = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$Types = [System.Windows.Automation.ControlType]

function Agent-Elements {
    $byProcess = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $script:agent.Id)
    foreach ($window in $AE::RootElement.FindAll($Scope::Children, $byProcess)) {
        $window
        foreach ($element in $window.FindAll($Scope::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
            $element
        }
    }
}

function Find-Agent([string]$pattern, $type = $null, [string[]]$ids = @()) {
    foreach ($element in (Agent-Elements)) {
        try {
            $current = $element.Current
            if ($type -and $current.ControlType -ne $type) { continue }
            if ($ids.Count -gt 0) { if ($ids -contains $current.AutomationId) { return $element } else { continue } }
            if ($current.Name -match $pattern) { return $element }
        } catch { }
    }
    return $null
}

function Agent-Texts {
    $texts = @()
    foreach ($element in (Agent-Elements)) {
        try {
            if ($element.Current.Name) { $texts += $element.Current.Name }
            $value = $null
            if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) {
                if ($value.Current.Value) { $texts += $value.Current.Value }
            }
            $document = $null   # multi-line text boxes expose their content through TextPattern
            if ($element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$document)) {
                $content = $document.DocumentRange.GetText(4000)
                if ($content) { $texts += $content }
            }
        } catch { }
    }
    return $texts
}

function Wait-AgentText([string]$pattern, [double]$timeoutSec) {
    return Wait-Until { Agent-Texts | Where-Object { $_ -match $pattern } | Select-Object -First 1 } $timeoutSec
}

# BM_CLICK is posted, not sent: the click handler may open a modal dialog and must not block us.
function Click-Element($element, [string]$label) {
    if (-not $element) { throw "Düğme bulunamadı: $label" }
    $handle = [IntPtr]$element.Current.NativeWindowHandle
    if ($handle -eq [IntPtr]::Zero) { throw "Düğmenin pencere tanıtıcısı yok: $label" }
    [Native]::PostMessage($handle, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
}

function Click-Agent([string]$pattern, [double]$timeoutSec = 15) {
    $button = Wait-Until { Find-Agent $pattern $Types::Button } $timeoutSec
    Click-Element $button $pattern
}

function Click-DialogButton([string[]]$ids, [double]$timeoutSec = 10) {
    $button = Wait-Until { Find-Agent '' $Types::Button $ids } $timeoutSec
    Click-Element $button ("dialog " + ($ids -join '/'))
}

function Set-AgentText([string]$name, [string]$text) {
    $edit = Wait-Until { Find-Agent ('^' + [regex]::Escape($name) + '$') $Types::Edit } 15
    if (-not $edit) { throw "Metin kutusu bulunamadı: $name" }
    $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($text)
}

# The agent's own main window (not the notice popup, which is also a top-level window).
function Get-AgentWindowHandle([string]$title) {
    $byProcess = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $script:agent.Id)
    foreach ($window in $AE::RootElement.FindAll($Scope::Children, $byProcess)) {
        try { if ($window.Current.Name -eq $title) { return [IntPtr]$window.Current.NativeWindowHandle } } catch { }
    }
    return [IntPtr]::Zero
}

function Start-Agent {
    $script:agent = Start-Process -FilePath (Join-Path $AgentDir 'SinavAjan.exe') -WorkingDirectory $AgentDir -PassThru
    Write-Host "  ajan başlatıldı (pid $($script:agent.Id))"
}

function Login-Agent([string]$numara, [string]$ad, [string]$soyad) {
    # Discovery: either the confirmation screen (one server) or the server list (several answers).
    $found = Wait-Until { Find-Agent '^(Doğru|Seç)$' $Types::Button } 25
    if (-not $found) { throw 'Ajan sunucuyu bulamadı (ne "Doğru" ne "Seç" düğmesi göründü).' }
    if ($found.Current.Name -eq 'Seç') {
        Write-Host '  birden fazla keşif yanıtı geldi; ilki seçiliyor'
        Click-Element $found 'Seç'
        $found = Wait-Until { Find-Agent '^Doğru$' $Types::Button } 15
    }
    $texts = Agent-Texts
    Check ([bool]($texts | Where-Object { $_ -eq 'Sınıf: CI-101' })) 'keşif: sınıf adı büyük harflerle gösteriliyor (Sınıf: CI-101)'
    Check ([bool]($texts | Where-Object { $_ -eq 'Öğretmen: E2E Öğretmen' })) 'keşif: öğretmen adı gösteriliyor (Türkçe karakterler doğru)'
    Shot "onay-$numara"
    Click-Element $found 'Doğru'

    Set-AgentText 'Öğrenci numarası' $numara
    Set-AgentText 'Ad' $ad
    Set-AgentText 'Soyad' $soyad
    Shot "giris-$numara"
    Click-Agent '^Giriş yap$'
}

# -------------------------------------------------------------------- setup

$mediamtx = $null
$server = $null
$numara = '2021001'
$localDir = Join-Path $env:LOCALAPPDATA 'SinavAjan'

try {
    Step 'Ortam'
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Write-Host "  kullanıcı: $($identity.Name)  yönetici: $isAdmin  oturum: $([Diagnostics.Process]::GetCurrentProcess().SessionId)"
    Write-Host "  işletim sistemi: $((Get-CimInstance Win32_OperatingSystem).Caption)  kültür: $((Get-Culture).Name)"
    Write-Host "  ekran: $([System.Windows.Forms.SystemInformation]::VirtualScreen)"
    Write-Host '  görünür pencereler:'
    Show-Windows
    if (Test-Path $localDir) { Remove-Item -Recurse -Force $localDir }

    $config = Join-Path $OutDir 'config.yaml'
    $yaml = @"
sinif_adi: "CI-101"
ogretmen_adi: "E2E Öğretmen"
yayin:
  kullanici: "sinavajan"
  sifre: "sinav-yayin-2026"
izin_listesi:
  - 'C:\Program Files\Cisco Packet Tracer*\'
# CI koşucusunun kendi süreçleri kapatılmasın (yine de öndeyse bildirilirler).
kapatma_disi:
  - 'C:\actions-runner\**'
  - 'D:\**'
  - 'C:\hostedtoolcache\**'
  - 'C:\Program Files\PowerShell\**'
  - 'C:\Program Files\Git\**'
  - 'C:\Program Files\dotnet\**'
  - 'C:\ProgramData\**'
  - 'C:\Packages\**'
  - 'C:\Users\**'
  - 'C:\Program Files\WindowsApps\Microsoft.WindowsTerminal*\**'
  - '$root\**'
esikler:
  on_pencere_toleransi_sn: 5
  kopma_suresi_sn: 10
  kapatma_geri_sayim_sn: 4
klasorler:
  teslimler: '$OutDir\submissions'
  kayitlar: '$root\recordings'
  veri: '$OutDir\data'
  dagitim: '$OutDir\dist'
"@
    [IO.File]::WriteAllText($config, $yaml, (New-Object Text.UTF8Encoding($false)))

    Step 'MediaMTX ve sunucu'
    $mediamtx = Start-Process -FilePath (Join-Path $root 'mediamtx\mediamtx.exe') `
        -ArgumentList ('"' + (Join-Path $root 'mediamtx\mediamtx.yml') + '"') `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $server = Start-Process -FilePath $Python `
        -ArgumentList @(('"' + (Join-Path $root 'server\run.py') + '"'), '--config', ('"' + $config + '"')) `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $OutDir 'server.out.log') `
        -RedirectStandardError (Join-Path $OutDir 'server.err.log')
    $ready = Wait-Until { (Curl-Text @('-m', '2', "$base/api/info")) -match 'CI-101' } 60
    Check ([bool]$ready) 'sunucu yanıt veriyor (/api/info)'
    if (-not $ready) { throw 'Sunucu başlamadı.' }
    $healthy = Wait-Until { $s = Get-Snapshot; $s -and $s.health.mediamtx_ok -and -not $s.health.discovery_error } 20
    Check ([bool]$healthy) 'MediaMTX denetim API''si ve UDP keşif dinleyicisi çalışıyor'

    # ------------------------------------------------------------- waiting phase
    Step 'Ajan: keşif, onay, giriş'
    Start-Agent
    Login-Agent $numara 'Şükrü Çağrı' 'Işık'
    $waiting = Wait-AgentText 'Sınavın başlamasını bekleyin' 20
    Check ([bool]$waiting) 'giriş başarılı: "Sınavın başlamasını bekleyin" ekranı'
    if (-not $waiting) { Write-Host ('  ajan metinleri: ' + ((Agent-Texts) -join ' | ')) }

    $student = Wait-Until { Get-Student $numara } 10
    Check ([bool]$student) 'öğrenci panelde görünüyor'
    if ($student) {
        Check ($student.hostname -eq $env:COMPUTERNAME) "bilgisayar adı kaydedildi ($($student.hostname))"
        Check ($student.ip -match '^\d+\.\d+\.\d+\.\d+$') "IP adresi kaydedildi ($($student.ip))"
        Check ($student.mac -match '^([0-9A-F]{2}:){5}[0-9A-F]{2}$') "MAC adresi kaydedildi ($($student.mac))"
    }

    Step 'Ekran yayını (ffmpeg gdigrab -> RTSP -> MediaMTX)'
    $streaming = Wait-Until { $s = Get-Student $numara; if ($s -and $s.stream_ready) { $s } } 30
    Check ([bool]$streaming) 'MediaMTX''te öğrencinin yayını var (giriş sonrası 30 sn içinde)'
    $alive = Wait-Until { $s = Get-Student $numara; if ($s -and $s.ffmpeg_alive) { $s } } 20
    Check ([bool]$alive) 'ajan ffmpeg''in kare gönderdiğini bildiriyor (ffmpeg_alive)'
    $ffmpeg = @(Get-Process ffmpeg -ErrorAction SilentlyContinue)
    Check ($ffmpeg.Count -eq 1) "tek bir ffmpeg.exe çalışıyor ($($ffmpeg.Count))"
    Check ([bool](Wait-AgentText 'Ekran yayını: gönderiliyor' 10)) 'ajan ekranında "Ekran yayını: gönderiliyor"'
    Check ($student -and (Get-Student $numara).status -ne 'lost') 'kutu kırmızı değil'
    Shot 'bekleme'

    # During WAITING nothing is closed: Notepad must survive.
    $survivor = Start-Process notepad.exe -PassThru
    Start-Sleep -Seconds 4
    Check ((Count-Events $numara 'process_killed') -eq 0) 'bekleme aşamasında hiçbir program kapatılmıyor'
    Get-Process -Name notepad -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    # --------------------------------------------------------------- exam start
    Step 'Sınavı başlat'
    $exam = Join-Path $OutDir 'sinav.pka'
    [IO.File]::WriteAllBytes($exam, [Text.Encoding]::ASCII.GetBytes(('PKA-E2E-SINAV-DOSYASI ' * 400)))
    $upload = Curl-Text @('-m', '10', '-H', 'X-Panel: 1', '-F', "file=@$exam", "$base/panel/api/exam-file")
    Check ($upload -match 'sha256') 'sınav dosyası yüklendi'
    $start = Panel-Post '/panel/api/start' '{"duration_min": 30}'
    Check ($start -match 'RUNNING') "sınav başlatıldı ($start)"
    if ($start -notmatch 'RUNNING') { throw 'Sınav başlatılamadı; kalan adımlar anlamsız.' }

    $countdown = Wait-AgentText 'Sınav başlıyor' 8
    Check ([bool]$countdown) 'ajan: "Sınav başlıyor." uyarısı ve geri sayım'
    Shot 'geri-sayim'
    $running = Wait-AgentText '^Sınav sürüyor$' 20
    Check ([bool]$running) 'geri sayımdan sonra yan panel: "Sınav sürüyor"'
    Check ([bool](Wait-AgentText '^Kalan süre: \d\d:\d\d$' 5)) 'yan panelde kalan süre görünüyor'

    $pka = Join-Path $localDir "$numara\sinav.pka"
    $downloaded = Wait-Until { Test-Path $pka } 10
    Check ([bool]$downloaded) "sınav dosyası indirildi: $pka"
    if ($downloaded) {
        Check ((Get-FileHash $pka).Hash -eq (Get-FileHash $exam).Hash) 'indirilen dosya yüklenenle aynı'
    }
    Check ([bool](Wait-Until { (Count-Events $numara 'enforcement_started') -ge 1 } 10)) 'olay: uygulama denetimi başladı'
    Check ([bool](Wait-Until { (Count-Events $numara 'pt_launch_failed') -ge 1 } 10)) 'olay: Packet Tracer açılamadı (bu ortamda kurulu değil; beklenen)'
    Start-Sleep -Seconds 2
    Shot 'yan-panel'
    Write-Host '  sınav başında kapatılan programlar:'
    Get-Events $numara | Where-Object { $_.type -eq 'process_killed' } | ForEach-Object { Write-Host "    $($_.details.path)  [$($_.details.title)]" }

    # ----------------------------------------------------------------- kill rule
    Step 'İzinsiz programlar kapatılıyor'
    $before = Count-Events $numara 'process_killed' 'notepad'
    Start-Process notepad.exe | Out-Null
    $killed = Wait-Until { (Count-Events $numara 'process_killed' 'notepad') -gt $before } 10
    Check ([bool]$killed) 'Not Defteri açılınca kapatıldı ve olay düştü'
    Check ([bool](Wait-AgentText 'sınav sırasında kullanılamaz' 6)) 'öğrenciye "… sınav sırasında kullanılamaz." bildirimi gösterildi'
    Shot 'bildirim'
    $gone = Wait-Until { -not (Get-Process -Name notepad -ErrorAction SilentlyContinue) } 6
    Check ([bool]$gone) 'Not Defteri süreci kalmadı'
    $st = Get-Student $numara
    Check ($st.status -eq 'warn' -and $st.warn_count -ge 1) "panelde kutu sarı (uyarı sayısı $($st.warn_count))"

    $chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
    if (Test-Path $chrome) {
        Start-Process $chrome -ArgumentList @('--no-first-run', '--no-default-browser-check', 'about:blank') | Out-Null
        $killed = Wait-Until { (Count-Events $numara 'process_killed' 'chrome') -ge 1 } 15
        Check ([bool]$killed) 'Chrome açılınca kapatıldı ve olay düştü'
    } else { Write-Host '  (Chrome kurulu değil; atlandı)' }

    # ----------------------------------------------------------- foreground rule
    Step 'Öndeki pencere toleransı (5 sn)'
    $agentWindow = Wait-Until { $h = Get-AgentWindowHandle 'Sınav'; if ($h -ne [IntPtr]::Zero) { $h } } 10
    Check ([bool]$agentWindow) 'ajanın yan paneli bulundu (pencere başlığı "Sınav")'
    $winver = Start-Process winver.exe -PassThru   # C:\Windows altında: kapatılmaz, yalnızca izlenir
    $winverWindow = Wait-Until { $winver.Refresh(); if ($winver.MainWindowHandle -ne [IntPtr]::Zero) { $winver.MainWindowHandle } } 10
    Check ([bool]$winverWindow) 'winver penceresi açıldı (C:\Windows altı)'
    if ($winverWindow -and $agentWindow) {
        [Native]::Focus($agentWindow); Start-Sleep -Seconds 2
        Check ([Native]::ForegroundPid() -eq $script:agent.Id) 'ajan paneli öne alınabildi'
        $foreignBefore = Count-Events $numara 'foreign_foreground'

        [Native]::Focus($winverWindow); Start-Sleep -Milliseconds 2500
        $wasWinver = [Native]::ForegroundPid() -eq $winver.Id
        [Native]::Focus($agentWindow); Start-Sleep -Seconds 3
        Check $wasWinver 'winver öne alınabildi'
        Check ((Count-Events $numara 'foreign_foreground') -eq $foreignBefore) '2,5 sn süren geçiş uyarı üretmedi'

        [Native]::Focus($winverWindow)
        $warned = Wait-Until { (Count-Events $numara 'foreign_foreground' 'winver') -ge 1 } 12
        Check ([bool]$warned) '5 sn''den uzun önde kalınca "Packet Tracer dışında bir pencere önde: winver.exe" uyarısı'
        Check (-not $winver.HasExited) 'C:\Windows altındaki program kapatılmadı'
        [Native]::Focus($agentWindow)
        Check ([bool](Wait-Until { (Count-Events $numara 'foreground_restored') -ge 1 } 8)) 'izinli pencere öne dönünce olay kaydı'
    }
    if (-not $winver.HasExited) { $winver.Kill() }
    Check ((Count-Events $numara 'foreground_change') -ge 2) 'öndeki pencere değişimleri olay kaydına yazılıyor'

    # -------------------------------------------------------------------- submit
    Step 'Teslim'
    Click-Agent '^Teslim et$'
    $notSaved = Wait-AgentText 'Ctrl\+S ile kaydedin' 8
    Check ([bool]$notSaved) 'kaydedilmemiş dosyada "Önce Packet Tracer''da Ctrl+S ile kaydedin." uyarısı'
    Shot 'kaydedilmedi'
    Click-DialogButton @('1', '2')
    Start-Sleep -Seconds 1

    [IO.File]::AppendAllText($pka, "`ncozum-$numara")   # "Ctrl+S": the file changes on disk
    $localHash = (Get-FileHash $pka -Algorithm SHA256).Hash.ToLowerInvariant()
    Click-Agent '^Teslim et$'
    $confirm = Wait-AgentText 'Teslim etmek istediğinize emin misiniz' 8
    Check ([bool]$confirm) 'onay sorusu: "Teslim etmek istediğinize emin misiniz? …"'
    Click-DialogButton @('6')   # IDYES

    $done = Wait-AgentText 'Teslim alındı' 20
    Check ([bool]$done) '"Teslim alındı" penceresi'
    Shot 'teslim-alindi'
    $texts = (Agent-Texts) -join "`n"
    Check ($texts -match $localHash) 'pencerede dosyanın SHA-256 değeri gösteriliyor'
    Check ($texts -match '2021001_SukruCagriIsik\.pka') 'dosya adı Türkçe karakterler çevrilerek oluşturuldu (2021001_SukruCagriIsik.pka)'
    Click-Agent '^Kapat'

    $exited = $script:agent.WaitForExit(20000)
    Check $exited 'ajan teslimden sonra kapandı'
    Start-Sleep -Seconds 2
    Check (-not (Get-Process ffmpeg -ErrorAction SilentlyContinue)) 'ajan kapanınca ffmpeg.exe de kapandı'
    $submitted = Join-Path $OutDir 'submissions\2021001_SukruCagriIsik.pka'
    Check (Test-Path $submitted) 'teslim dosyası sunucuda kaydedildi'
    if (Test-Path $submitted) {
        Check ((Get-FileHash $submitted -Algorithm SHA256).Hash.ToLowerInvariant() -eq $localHash) 'sunucudaki dosya öğrencinin kaydettiğiyle birebir aynı'
    }
    Check ((Get-Student $numara).status -eq 'done') 'panelde kutu gri (teslim etti)'

    Step 'İz bırakmama'
    $run = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue | Out-String
    Check ($run -notmatch 'SinavAjan') 'başlangıç (Run) kayıtlarında ajan yok'
    Check (-not (Get-Service | Where-Object { $_.Name -match 'Sinav' -or $_.DisplayName -match 'Sinav' })) 'ajana ait servis yok'
    Check (-not (Get-ScheduledTask | Where-Object { $_.TaskName -match 'Sinav' })) 'ajana ait zamanlanmış görev yok'
    Check (-not (Get-Process SinavAjan -ErrorAction SilentlyContinue)) 'SinavAjan.exe çalışmıyor'
    Write-Host "  $localDir içeriği:"
    Get-ChildItem -Recurse -File $localDir | ForEach-Object { Write-Host "    $($_.FullName.Substring($localDir.Length + 1))  ($($_.Length) bayt)" }

    # ------------------------------------------------- forced kill: Job Object
    Step 'Ajan zorla sonlandırılınca ffmpeg de kapanıyor (Job Object) ve kutu kırmızıya dönüyor'
    $second = '2021002'
    Start-Agent
    Login-Agent $second 'Deneme' 'Öğrenci'
    $streaming = Wait-Until { $s = Get-Student $second; if ($s -and $s.stream_ready) { $s } } 40
    Check ([bool]$streaming) 'ikinci öğrencinin yayını geldi'
    $ffmpeg = @(Get-Process ffmpeg -ErrorAction SilentlyContinue)
    Check ($ffmpeg.Count -eq 1) 'ffmpeg.exe çalışıyor'
    Stop-Process -Id $script:agent.Id -Force       # like "End task" in Task Manager
    $killedAt = Get-Date
    $ffmpegGone = Wait-Until { -not (Get-Process ffmpeg -ErrorAction SilentlyContinue) } 5 200
    Check ([bool]$ffmpegGone) 'ajan sonlandırıldıktan sonra ffmpeg.exe kalmadı'
    $lost = Wait-Until { $s = Get-Student $second; if ($s -and $s.status -eq 'lost') { $s } } 16 500
    Check ([bool]$lost) ("kutu kırmızıya döndü ({0:N0} sn sonra)" -f ((Get-Date) - $killedAt).TotalSeconds)

    Step 'Sınavı bitir ve kayıtlar'
    $end = Panel-Post '/panel/api/end'
    Check ($end -match 'ENDED') 'sınav bitirildi'
    $recordings = @(Get-ChildItem (Join-Path $root "recordings\s\$numara") -Filter *.mp4 -ErrorAction SilentlyContinue)
    Check ($recordings.Count -ge 1 -and ($recordings | Measure-Object Length -Sum).Sum -gt 20000) "ekran kaydı oluştu: recordings\s\$numara ($($recordings.Count) dosya)"
}
catch {
    Write-Host ''
    Write-Host "!!! BEKLENMEYEN HATA: $($_.Exception.Message)"
    Write-Host $_.ScriptStackTrace
    $script:failures.Add("beklenmeyen hata: $($_.Exception.Message)")
    Shot 'hata'
    try { Write-Host ('  ajan metinleri: ' + ((Agent-Texts) -join ' | ')) } catch { }
}
finally {
    Step 'Tanılama'
    try {
        foreach ($n in @('2021001', '2021002', '')) {
            Write-Host "  olaylar ($n):"
            Get-Events $n | ForEach-Object { Write-Host "    [$($_.severity)] $($_.type): $($_.message)" }
        }
    } catch { Write-Host "  (olaylar okunamadı: $($_.Exception.Message))" }
    Write-Host '  görünür pencereler:'
    try { Show-Windows } catch { }

    Get-Process SinavAjan, ffmpeg -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($process in @($server, $mediamtx)) {
        if ($process -and -not $process.HasExited) { try { $process.Kill() } catch { } }
    }
    Start-Sleep -Seconds 1

    $agentLog = Join-Path $localDir 'ajan.log'
    if (Test-Path $agentLog) { Copy-Item $agentLog (Join-Path $OutDir 'ajan.log') -Force }
    $mediaLog = Join-Path $root 'data\mediamtx.log'
    if (Test-Path $mediaLog) { Copy-Item $mediaLog (Join-Path $OutDir 'mediamtx.log') -Force }
    $recordingDir = Join-Path $root 'recordings'
    if (Test-Path $recordingDir) { Copy-Item $recordingDir (Join-Path $OutDir 'recordings') -Recurse -Force }
    foreach ($log in @('ajan.log', 'server.err.log', 'server.out.log', 'mediamtx.log')) {
        $path = Join-Path $OutDir $log
        if (Test-Path $path) {
            Write-Host ''
            Write-Host "----- $log (son 60 satır)"
            Get-Content $path -Tail 60 -Encoding UTF8 | ForEach-Object { Write-Host "  $_" }
        }
    }
}

Write-Host ''
if ($script:failures.Count -eq 0) {
    Write-Host 'SONUÇ: tüm denetimler geçti.'
    exit 0
}
Write-Host "SONUÇ: $($script:failures.Count) denetim BAŞARISIZ:"
$script:failures | ForEach-Object { Write-Host "  - $_" }
exit 1
