<#
.SYNOPSIS
    Kurulum dosyalarının GERÇEK Windows üzerinde denemesi (GitHub Actions'ta çalışır).

.DESCRIPTION
    Bir kullanıcının yapacağını yapar:

      iki kurulum dosyasını çalıştırır -> dosyalar, masaüstü ve Başlat menüsü kısayolları,
      güvenlik duvarı izinleri -> sistemi MASAÜSTÜ KISAYOLUNDAN başlatır (konsol penceresi
      yok, MediaMTX gizli, panel kendi penceresinde) -> kısayola yeniden basılınca ikinci
      kopya açılmaz -> klasör seçme penceresi -> öğrenci programı kısayolundan açılır ve
      sınıfı bulur -> sistem çalışırken kaldırma: önce kendini kapatır -> kaldırınca
      kısayollar, dosyalar ve güvenlik duvarı izinleri gider, sınav verileri kalır.

    Yönetici olarak ve etkileşimli bir masaüstü oturumunda çalıştırılmalıdır.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\kurulum-testi.ps1 -SetupDir publish
#>
[CmdletBinding()]
param(
    # SinavIzleme-Kurulum.exe ve SinavAjan-Kurulum.exe dosyalarının bulunduğu klasör
    [Parameter(Mandatory = $true)][string]$SetupDir,
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$SetupDir = (Resolve-Path $SetupDir).Path
if (-not $OutDir) { $OutDir = Join-Path (Resolve-Path (Join-Path $here '..')).Path 'e2e-out\kurulum' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
[Console]::OutputEncoding = [Text.Encoding]::UTF8

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class Win
{
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);

    // Controls inside a window as "handle|class|usable|text" (usable: visible and enabled).
    public static List<string> Children(long parent)
    {
        var result = new List<string>();
        EnumChildWindows(new IntPtr(parent), (hWnd, lParam) =>
        {
            var name = new StringBuilder(128);
            GetClassName(hWnd, name, name.Capacity);
            var text = new StringBuilder(512);
            GetWindowText(hWnd, text, text.Capacity);
            var usable = IsWindowVisible(hWnd) && IsWindowEnabled(hWnd);
            result.Add(hWnd.ToInt64() + "|" + name + "|" + (usable ? "1" : "0") + "|" + text);
            return true;
        }, IntPtr.Zero);
        return result;
    }

    public static void Click(long handle)
    {
        PostMessage(new IntPtr(handle), 0x00F5 /* BM_CLICK */, IntPtr.Zero, IntPtr.Zero);
    }

    // Visible top-level windows as "pid|handle|title".
    public static List<string> Windows()
    {
        var result = new List<string>();
        EnumWindows((hWnd, lParam) =>
        {
            if (!IsWindowVisible(hWnd)) return true;
            var text = new StringBuilder(512);
            GetWindowText(hWnd, text, text.Capacity);
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            result.Add(pid + "|" + hWnd.ToInt64() + "|" + text);
            return true;
        }, IntPtr.Zero);
        return result;
    }

    public static void Close(long handle)
    {
        PostMessage(new IntPtr(handle), 0x0010 /* WM_CLOSE */, IntPtr.Zero, IntPtr.Zero);
    }
}
"@

$script:failures = New-Object System.Collections.Generic.List[string]
$script:passed = 0
function Step([string]$text) { Write-Host ''; Write-Host "=== $text" }
function Check([bool]$condition, [string]$what) {
    if ($condition) { $script:passed++; Write-Host "  [OK]   $what" }
    else { $script:failures.Add($what); Write-Host "  [HATA] $what" }
}
function Wait-Until([scriptblock]$probe, [double]$seconds = 20, [int]$stepMs = 500) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { $value = & $probe } catch { $value = $null }
        if ($value) { return $value }
        Start-Sleep -Milliseconds $stepMs
    }
    return $null
}
function Shot([string]$name) {
    try {
        $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
        $bitmap.Save((Join-Path $OutDir "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose(); $bitmap.Dispose()
    } catch { Write-Host "  (ekran görüntüsü alınamadı: $($_.Exception.Message))" }
}
# Windows whose title matches: objects with Pid, Handle, Title.
function Find-Windows([string]$pattern) {
    foreach ($line in [Win]::Windows()) {
        $parts = $line.Split('|', 3)
        if ($parts[2] -match $pattern) {
            New-Object psobject -Property @{ Pid = [int]$parts[0]; Handle = [long]$parts[1]; Title = $parts[2] }
        }
    }
}
function Get-Json([string]$path) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:8000" + $path) -TimeoutSec 5
    return ([Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()) | ConvertFrom-Json)
}
function Test-Rule([string]$name) {
    return [bool](Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)
}
# Reads a shortcut. (Not WScript.Shell: it cannot open a path with letters outside the
# system code page, such as "ı" and "İ" on an English Windows.)
function Get-Shortcut([string]$path) {
    $shell = New-Object -ComObject Shell.Application
    $item = $shell.Namespace((Split-Path -Parent $path)).ParseName((Split-Path -Leaf $path))
    $link = $item.GetLink
    $icon = ''
    try { $null = $link.GetIconLocation([ref]$icon) } catch { }
    return (New-Object psobject -Property @{
        TargetPath = $link.Path; Arguments = $link.Arguments; WorkingDirectory = $link.WorkingDirectory; IconLocation = "$icon"
    })
}
function Install([string]$setup, [string]$log) {
    $process = Start-Process -FilePath (Join-Path $SetupDir $setup) -PassThru -Wait `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + (Join-Path $OutDir $log) + '"'))
    return $process.ExitCode
}
# Runs a setup file the way a double-click does (with its windows) and presses the buttons a
# user would press. Returns the texts of the buttons that were pressed, in order; $null when
# the setup did not finish.
function Install-ByHand([string]$setup, [string]$titlePattern, [string]$shotPrefix) {
    $process = Start-Process -FilePath (Join-Path $SetupDir $setup) -PassThru
    $pressed = New-Object System.Collections.Generic.List[string]
    $shots = 0
    $deadline = (Get-Date).AddSeconds(240)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        $process.Refresh()
        if ($process.HasExited) { break }
        # The setup may own more than one window with this title; take the one with buttons.
        $window = $null; $buttons = @(); $go = $null
        foreach ($candidate in @(Find-Windows $titlePattern)) {
            $buttons = @([Win]::Children($candidate.Handle) | ForEach-Object {
                $parts = $_.Split('|', 4)
                if ($parts[2] -eq '1' -and $parts[1] -match 'Button' -and $parts[3]) {
                    New-Object psobject -Property @{ Handle = [long]$parts[0]; Text = $parts[3].Replace('&', '') }
                }
            })
            # The page that asks nothing more than "install" / "next", and the last page.
            $go = $buttons | Where-Object { $_.Text -match '^(Kur|Install|İleri >|Next >|Bitti|Bitir|Son|Finish)$' } | Select-Object -First 1
            if ($go) { $window = $candidate; break }
        }
        if (-not $go) { continue }
        if ($shots -lt 4) { $shots++; Shot ("{0}-{1}-{2}" -f $shotPrefix, $shots, ($go.Text -replace '[^A-Za-z]', '')) }
        Write-Host "  pencere: $($window.Title) | düğmeler: $(($buttons | ForEach-Object { $_.Text }) -join ', ') | basılan: $($go.Text)"
        $pressed.Add($go.Text)
        [Win]::Click($go.Handle)
        if ($go.Text -match '^(Bitti|Bitir|Son|Finish)$') {
            $null = $process.WaitForExit(30000)
            break
        }
        Start-Sleep -Seconds 1
    }
    $process.Refresh()
    if (-not $process.HasExited) {
        Shot "$shotPrefix-takildi"
        try { $process.Kill() } catch { }
        return $null
    }
    return ,$pressed.ToArray()
}

function Uninstall([string]$folder, [string]$log) {
    $uninstaller = Join-Path $folder 'unins000.exe'
    if (-not (Test-Path $uninstaller)) { return -1 }
    $process = Start-Process -FilePath $uninstaller -PassThru -Wait `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="' + (Join-Path $OutDir $log) + '"'))
    # The uninstaller continues in a copy of itself; wait until the folder is really gone.
    $null = Wait-Until { -not (Test-Path $folder) } 60
    return $process.ExitCode
}

$systemName = 'Sınav İzleme Sistemi'
$agentName = 'Sınav Ajanı'
$systemDir = Join-Path $env:ProgramFiles 'Sinav Izleme'
$agentDir = Join-Path $env:ProgramFiles 'Sinav Ajani'
$desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
$programs = [Environment]::GetFolderPath('CommonPrograms')
$systemLink = Join-Path $desktop "$systemName.lnk"
$agentLink = Join-Path $desktop "$agentName.lnk"
$dataHome = Join-Path $env:LOCALAPPDATA 'SinavIzleme'
$agentHome = Join-Path $env:LOCALAPPDATA 'SinavAjan'
$rules = @('Sinav Izleme - Kesif (UDP 47000)', 'Sinav Izleme - API (TCP 8000)', 'Sinav Izleme - RTSP (TCP 8554)',
           'Sinav Izleme - Sunucu', 'Sinav Izleme - Ekran Aktarimi')
$uninstallKeys = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
$panelTitle = '^Sınav İzleme($| — )'

try {
    Step 'Hazırlık'
    Get-Process msedge, pythonw, mediamtx, SinavAjan, ffmpeg -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    foreach ($rule in $rules) { Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue }
    if (Test-Path $dataHome) { Remove-Item -Recurse -Force $dataHome }
    try { (New-Object -ComObject Shell.Application).MinimizeAll() } catch { }
    Get-ChildItem $SetupDir -Filter '*.exe' | ForEach-Object { Write-Host ("  {0}  {1:N0} MB" -f $_.Name, ($_.Length / 1MB)) }

    # ---------------------------------------------------------------- install
    Step 'Sistemin kurulumu: çift tıklanmış gibi (SinavIzleme-Kurulum.exe)'
    $started = Get-Date
    $pressed = Install-ByHand 'SinavIzleme-Kurulum.exe' $systemName 'kurulum-sistem'
    Check ($null -ne $pressed) ("kurulum tamamlandı ({0:N0} sn); basılan düğmeler: $($pressed -join ' > ')" -f ((Get-Date) - $started).TotalSeconds)
    if ($null -eq $pressed) {
        Write-Host '  pencereli kurulum bitmedi; sessiz kurulumla sürdürülüyor'
        $code = Install 'SinavIzleme-Kurulum.exe' 'kurulum-sistem.log'
        Check ($code -eq 0) "sessiz kurulum tamamlandı (çıkış kodu $code)"
    } else {
        # The last page offers to start the system; it is ticked by default.
        $info = Wait-Until { Get-Json '/api/info' } 90
        Check ([bool]$info) 'kurulumun son sayfasından çıkınca sistem kendiliğinden açıldı'
        $panel = Wait-Until { @(Find-Windows $panelTitle) } 120
        Check ([bool]$panel) 'panel penceresi açıldı'
        Start-Sleep -Seconds 4
        Shot 'kurulumdan-sonra'
        # Close it again: the next steps start it from the desktop shortcut.
        $stop = Start-Process -FilePath (Join-Path $systemDir 'python\pythonw.exe') -PassThru -Wait `
            -ArgumentList @(('"' + (Join-Path $systemDir 'server\run.py') + '"'), '--stop')
        Check ($stop.ExitCode -eq 0) "çalışan sistem kapatılabildi (run.py --stop, çıkış kodu $($stop.ExitCode))"
        Check (-not (Get-Process pythonw, mediamtx -ErrorAction SilentlyContinue)) 'sunucu ve MediaMTX kapandı'
        Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    foreach ($file in @('python\pythonw.exe', 'python\python.exe', 'server\run.py', 'server\config.yaml', 'server\static\panel.html',
                        'mediamtx\mediamtx.exe', 'mediamtx\mediamtx.yml', 'sinav-izleme.ico', 'unins000.exe')) {
        Check (Test-Path (Join-Path $systemDir $file)) "kuruldu: $file"
    }
    Check (Test-Path $systemLink) "masaüstünde kısayol var: $systemName"
    Check (Test-Path (Join-Path $programs "$systemName.lnk")) 'Başlat menüsünde kısayol var'
    if (Test-Path $systemLink) {
        $link = Get-Shortcut $systemLink
        Write-Host "  kısayol: $($link.TargetPath) $($link.Arguments)"
        Check ($link.TargetPath -eq (Join-Path $systemDir 'python\pythonw.exe')) 'kısayol konsolsuz Python''u çalıştırıyor (pythonw.exe)'
        Check ($link.Arguments -match 'run\.py" --app$') 'kısayol sistemi uygulama kipinde başlatıyor'
        Check ($link.IconLocation -match 'sinav-izleme\.ico') 'kısayolun kendi simgesi var'
    }
    foreach ($rule in $rules) { Check (Test-Rule $rule) "güvenlik duvarı izni eklendi: $rule" }
    $entry = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq $systemName }
    Check ([bool]$entry) 'Denetim Masası''ndaki "Program kaldır" listesinde görünüyor'

    Step 'Paketlenen Python'
    $python = Join-Path $systemDir 'python\python.exe'
    $output = & $python -c "import sys, tkinter, fastapi, uvicorn, yaml, openpyxl, multipart; tkinter.Tcl().eval('info patchlevel'); print('tamam', sys.version.split()[0]); print('YOL:' + '|'.join(sys.path))" 2>&1 | Out-String
    Write-Host "  $($output.Trim())"
    Check ($output -match 'tamam \d+\.\d+') 'kurulan Python çalışıyor; paketler ve klasör seçme penceresi için gereken tkinter içinde'
    $pathLine = @($output -split "`r?`n" | Where-Object { $_ -like 'YOL:*' })
    Check ($pathLine.Count -eq 1) 'Python''un modül yolları okunabildi'
    if ($pathLine.Count -eq 1) {
        $foreign = @($pathLine[0].Substring(4) -split '\|' | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith($systemDir, [StringComparison]::OrdinalIgnoreCase) })
        Check ($foreign.Count -eq 0) "Python yalnızca kendi klasörlerini kullanıyor (bilgisayardaki başka Python karışmıyor) $($foreign -join '; ')"
    }

    Step 'Öğrenci programının kurulumu: çift tıklanmış gibi (SinavAjan-Kurulum.exe)'
    $pressed = Install-ByHand 'SinavAjan-Kurulum.exe' $agentName 'kurulum-ajan'
    Check ($null -ne $pressed) "kurulum tamamlandı; basılan düğmeler: $($pressed -join ' > ')"
    if ($null -eq $pressed) {
        Write-Host '  pencereli kurulum bitmedi; sessiz kurulumla sürdürülüyor'
        $code = Install 'SinavAjan-Kurulum.exe' 'kurulum-ajan.log'
        Check ($code -eq 0) "sessiz kurulum tamamlandı (çıkış kodu $code)"
    }
    $agentFiles = @(Get-ChildItem -LiteralPath $agentDir -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name } | Sort-Object)
    Write-Host "  kurulan dosyalar: $($agentFiles -join ', ')"
    Check ($agentFiles -contains 'SinavAjan.exe') 'SinavAjan.exe kuruldu'
    Check (Test-Path $agentLink) "masaüstünde kısayol var: $agentName"
    Check (Test-Path (Join-Path $programs "$agentName.lnk")) 'Başlat menüsünde kısayol var'
    if (Test-Path $agentLink) { Check ((Get-Shortcut $agentLink).TargetPath -eq (Join-Path $agentDir 'SinavAjan.exe')) 'kısayol SinavAjan.exe''yi açıyor' }
    $entry = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq $agentName }
    Check ([bool]$entry) '"Program kaldır" listesinde görünüyor'
    $run = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue | Out-String
    Check ($run -notmatch 'Sinav') 'kurulum Windows açılışına bir şey eklemedi'
    Check (-not (Get-Service | Where-Object { $_.Name -match 'Sinav' -or $_.DisplayName -match 'Sinav' })) 'kurulum servis eklemedi'
    Check (-not (Get-ScheduledTask | Where-Object { $_.TaskName -match 'Sinav' })) 'kurulum zamanlanmış görev eklemedi'
    Check (-not (Get-Process SinavAjan, pythonw, mediamtx -ErrorAction SilentlyContinue)) 'öğrenci programının kurulumundan sonra arka planda çalışan bir şey yok'

    # ------------------------------------------------------------------ start
    Step 'Masaüstü kısayolundan başlatma'
    Start-Process -FilePath $systemLink          # what a double-click does
    $info = Wait-Until { Get-Json '/api/info' } 90
    Check ([bool]$info) 'sistem açıldı (sunucu yanıt veriyor)'
    if (-not $info) { throw 'Sistem kısayoldan açılmadı.' }
    $servers = @(Get-Process pythonw -ErrorAction SilentlyContinue)
    Check ($servers.Count -eq 1 -and $servers[0].Path -eq (Join-Path $systemDir 'python\pythonw.exe')) "kurulu Python çalışıyor ($($servers | ForEach-Object { $_.Path }))"
    $healthy = Wait-Until { $s = Get-Json '/panel/api/state'; if ($s.health.mediamtx_ok -and -not $s.health.discovery_error) { $s } } 30
    Check ([bool]$healthy) 'ekran aktarımı bileşeni (MediaMTX) ve keşif çalışıyor'
    $media = @(Get-Process mediamtx -ErrorAction SilentlyContinue)
    Check ($media.Count -eq 1 -and $media[0].Path -eq (Join-Path $systemDir 'mediamtx\mediamtx.exe')) 'kurulu MediaMTX çalışıyor'
    $ownIds = @($servers + $media | ForEach-Object { "$($_.Id)" })
    $consoles = @([Win]::Windows() | Where-Object { $ownIds -contains $_.Split('|', 3)[0] })
    Check ($consoles.Count -eq 0) "siyah pencere yok: sunucu ve MediaMTX görünür pencere açmıyor ($($consoles -join '; '))"
    Check (Test-Path (Join-Path $dataHome 'sistem.log')) 'kayıt dosyası kullanıcının klasöründe (sistem.log)'
    Check (Test-Path (Join-Path $dataHome 'data')) 'sistemin verileri kullanıcının klasöründe (Program Files''a yazılmıyor)'
    $panel = Wait-Until { @(Find-Windows $panelTitle) } 120
    Check ([bool]$panel) 'panel kendi penceresinde açıldı'
    $connected = Wait-Until { $s = Get-Json '/panel/api/state'; if ($s.health.panel_clients -ge 1) { $s } } 60
    Check ([bool]$connected) 'panel sunucuya bağlandı'
    Start-Sleep -Seconds 5
    Shot 'panel'

    Step 'Kısayola yeniden basılınca ikinci kopya açılmıyor'
    Start-Process -FilePath $systemLink
    Start-Sleep -Seconds 12
    $servers = @(Get-Process pythonw -ErrorAction SilentlyContinue)
    Check ($servers.Count -eq 1) "tek sunucu çalışıyor ($($servers.Count))"
    Check (@(Get-Process mediamtx -ErrorAction SilentlyContinue).Count -eq 1) 'tek MediaMTX çalışıyor'
    Check ([bool](Get-Json '/api/info')) 'sistem çalışmaya devam ediyor'

    Step 'Klasör seçme penceresi'
    $job = Start-Job -ScriptBlock {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:8000/panel/api/pick-folder' -TimeoutSec 120 `
                -Headers @{ 'X-Panel' = '1' } -ContentType 'application/json' -Body '{}'
            [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
        } catch { "HATA: $($_.Exception.Message)" }
    }
    $dialog = Wait-Until { @(Find-Windows '^(Sınav klasörünü seçin|Browse For Folder|Klasöre Gözat)$') } 40
    Check ([bool]$dialog) 'klasör seçme penceresi açıldı'
    if ($dialog) {
        Write-Host "  pencere: $($dialog[0].Title)"
        Check ($dialog[0].Title -eq 'Sınav klasörünü seçin') 'pencere Windows''un yeni klasör seçicisi (paketlenen Python''daki tkinter ile)'
        Shot 'klasor-sec'
        foreach ($window in $dialog) { [Win]::Close($window.Handle) }
    }
    $done = Wait-Job -Job $job -Timeout 60
    if ($done) { $answer = Receive-Job -Job $done } else { $answer = 'HATA: panel yanıt vermedi' }
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    Write-Host "  yanıt: $answer"
    Check ("$answer" -notmatch 'HATA') 'pencere kapatılınca panel yanıt aldı'

    Step 'Öğrenci programı masaüstü kısayolundan açılıyor ve sınıfı buluyor'
    Start-Process -FilePath $agentLink
    $agent = Wait-Until { Get-Process SinavAjan -ErrorAction SilentlyContinue | Select-Object -First 1 } 30
    Check ([bool]$agent) 'SinavAjan.exe çalışıyor'
    if ($agent) {
        Check ($agent.Path -eq (Join-Path $agentDir 'SinavAjan.exe')) "kurulu kopya çalışıyor ($($agent.Path))"
        $className = (Get-Json '/api/info').sinif_adi
        $texts = Wait-Until {
            $condition = New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::ProcessIdProperty, $agent.Id)
            $window = [Windows.Automation.AutomationElement]::RootElement.FindFirst([Windows.Automation.TreeScope]::Children, $condition)
            if ($window) {
                $names = @($window.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition) | ForEach-Object { $_.Current.Name })
                if (($names -join ' | ') -match [regex]::Escape($className)) { $names }
            }
        } 60 1000
        Check ([bool]$texts) "öğrenci programı sınıfı buldu ve adını gösteriyor: $className"
        if ($texts) { Write-Host ('  ekrandaki yazılar: ' + (($texts | Where-Object { $_ }) -join ' | ')) }
        Shot 'ogrenci-programi'
        Stop-Process -Id $agent.Id -Force -ErrorAction SilentlyContinue
    }

    # --------------------------------------------------------------- uninstall
    Step 'Sistem çalışırken kaldırma: önce kendini kapatıyor'
    Check (@(Get-Process pythonw -ErrorAction SilentlyContinue).Count -eq 1) 'kaldırmadan önce sistem çalışıyor'
    $code = Uninstall $systemDir 'kaldirma-sistem.log'
    Check ($code -eq 0) "kaldırma tamamlandı (çıkış kodu $code)"
    Check (-not (Get-Process pythonw, mediamtx -ErrorAction SilentlyContinue)) 'sunucu ve MediaMTX kapandı'
    Check (-not (Test-Path $systemDir)) 'program klasörü silindi'
    Check (-not (Test-Path $systemLink)) 'masaüstü kısayolu silindi'
    Check (-not (Test-Path (Join-Path $programs "$systemName.lnk"))) 'Başlat menüsü kısayolu silindi'
    foreach ($rule in $rules) { Check (-not (Test-Rule $rule)) "güvenlik duvarı izni kaldırıldı: $rule" }
    Check (-not (Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq $systemName })) '"Program kaldır" listesinden çıktı'
    Check (Test-Path (Join-Path $dataHome 'data')) 'sistemin kendi verileri (ayarlar, sınav durumu) silinmedi'

    Step 'Öğrenci programını kaldırma'
    $code = Uninstall $agentDir 'kaldirma-ajan.log'
    Check ($code -eq 0) "kaldırma tamamlandı (çıkış kodu $code)"
    Check (-not (Test-Path $agentDir)) 'program klasörü silindi'
    Check (-not (Test-Path $agentLink)) 'masaüstü kısayolu silindi'
    Check (-not (Test-Path $agentHome)) 'programın kayıt klasörü silindi (%LOCALAPPDATA%\SinavAjan)'
    Check (-not (Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq $agentName })) '"Program kaldır" listesinden çıktı'
}
catch {
    $script:failures.Add("beklenmeyen hata: $($_.Exception.Message)")
    Write-Host ''
    Write-Host "BEKLENMEYEN HATA: $($_.Exception.Message)"
    Write-Host $_.ScriptStackTrace
    Shot 'hata'
}
finally {
    Step 'Tanılama'
    Write-Host '  görünür pencereler:'
    try { [Win]::Windows() | Where-Object { $_.Split('|', 3)[2] } | ForEach-Object { Write-Host "    $_" } } catch { }
    Get-Process msedge, pythonw, mediamtx, SinavAjan, ffmpeg -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($log in @((Join-Path $dataHome 'sistem.log'), (Join-Path $dataHome 'data\mediamtx.log'))) {
        if (Test-Path $log) {
            Copy-Item $log $OutDir -Force
            Write-Host ''
            Write-Host "----- $(Split-Path -Leaf $log) (son 40 satır)"
            Get-Content $log -Tail 40 -Encoding UTF8 | ForEach-Object { Write-Host "  $_" }
        }
    }
    # Leave the machine as it was, also after a failure.
    foreach ($folder in @($systemDir, $agentDir)) {
        if (Test-Path (Join-Path $folder 'unins000.exe')) { $null = Uninstall $folder 'kaldirma-son.log' }
    }
}

Write-Host ''
if ($script:failures.Count -eq 0) {
    Write-Host "SONUÇ: kurulum denemesi geçti ($($script:passed) denetim)."
    exit 0
}
Write-Host "SONUÇ: $($script:failures.Count) denetim BAŞARISIZ ($($script:passed) geçti):"
$script:failures | ForEach-Object { Write-Host "  - $_" }
exit 1
