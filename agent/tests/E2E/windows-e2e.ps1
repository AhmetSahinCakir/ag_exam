<#
.SYNOPSIS
    Sınav ajanının GERÇEK Windows üzerinde uçtan uca testi (GitHub Actions'ta çalışır).

.DESCRIPTION
    MediaMTX'i ve Python sunucusunu başlatır, SinavAjan.exe'yi çalıştırır ve arayüzünü
    UI Automation ile bir öğrenci gibi kullanır:

      sınav klasörünün panelden seçilmesi (Kayıtlar + Teslimler) -> sınıf/öğretmen adının panelden
      değiştirilmesi -> keşif -> sınıf/öğretmen onayı -> giriş -> ekran yayını (ffmpeg/gdigrab ->
      MediaMTX) -> sınav dosyasının paylaşılması (sınavın başlaması) -> dosyanın seçilen yere
      indirilmesi -> izinsiz programların kapatılması -> öndeki pencere toleransı -> başka
      masaüstüne geçiş uyarısı -> teslimde dosya seçme ve dosya denetimleri -> teslim klasörü
      denetimi -> elle konan dosyanın teslim sayılması -> ajanın kapanması ve iz bırakmaması
      -> ajan zorla sonlandırıldığında ffmpeg'in de kapanması (Job Object)
      -> ek süre -> sınav bitince programın kapanmaması ve geç teslim -> öğrenci başına uyarı
      dosyaları -> panel penceresi kapanınca çıkan soru ve "Sistemi kapat"

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
using System.Text.RegularExpressions;
using System.Threading;
using System.Collections.Generic;
using System.Runtime.InteropServices;

// Windows' documented virtual desktop interface: is a window on the desktop shown right now?
[ComImport, Guid("a5cd92ff-29be-454c-8d04-d82879fb3f1b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IVirtualDesktopManager
{
    [PreserveSig] int IsWindowOnCurrentVirtualDesktop(IntPtr topLevelWindow, [MarshalAs(UnmanagedType.Bool)] out bool onCurrentDesktop);
    [PreserveSig] int GetWindowDesktopId(IntPtr topLevelWindow, out Guid desktopId);
    [PreserveSig] int MoveWindowToDesktop(IntPtr topLevelWindow, ref Guid desktopId);
}

[ComImport, Guid("aa509086-5ca9-4c25-8f95-589d3c07b48a")]
public class VirtualDesktopManagerClass { }

public static class Desk
{
    // 1 = on the current desktop, 0 = on another desktop, -1 = Windows cannot tell.
    public static int State(IntPtr hwnd)
    {
        try
        {
            var manager = (IVirtualDesktopManager)new VirtualDesktopManagerClass();
            bool on;
            return manager.IsWindowOnCurrentVirtualDesktop(hwnd, out on) == 0 ? (on ? 1 : 0) : -1;
        }
        catch (Exception) { return -1; }
    }
}

public static class Native
{
    public delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] public static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);

    public static bool HasMinimizeBox(IntPtr hwnd)
    {
        return (GetWindowLongPtr(hwnd, -16).ToInt64() & 0x00020000L) != 0;   // GWL_STYLE & WS_MINIMIZEBOX
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr hwnd, StringBuilder name, int max);
    // The standard message box (window class #32770) of a process, or zero.
    public static IntPtr FindMessageBox(uint processId)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hwnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hwnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hwnd, out pid);
            if (pid != processId) return true;
            var name = new StringBuilder(64);
            GetClassName(hwnd, name, 64);
            if (name.ToString() != "#32770") return true;
            found = hwnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    // A real mouse click on the title bar: Windows always activates the clicked window.
    public static void ClickTitleBar(IntPtr hwnd)
    {
        RECT rect;
        if (!GetWindowRect(hwnd, out rect)) return;
        SetCursorPos(rect.Left + 60, rect.Top + 12);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);
    }

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

    public static uint PidOf(IntPtr hwnd)
    {
        uint pid;
        GetWindowThreadProcessId(hwnd, out pid);
        return pid;
    }

    // The first visible top-level window whose title matches the pattern, or zero.
    public static IntPtr FindWindowByTitle(string pattern)
    {
        IntPtr found = IntPtr.Zero;
        var regex = new Regex(pattern);
        EnumWindows(delegate(IntPtr hwnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hwnd)) return true;
            var text = new StringBuilder(300);
            GetWindowText(hwnd, text, 300);
            if (!regex.IsMatch(text.ToString())) return true;
            found = hwnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    // The texts of a window's child controls (buttons, labels), in creation order.
    public static List<string> ChildTexts(IntPtr parent)
    {
        var list = new List<string>();
        EnumChildWindows(parent, delegate(IntPtr hwnd, IntPtr lParam)
        {
            var text = new StringBuilder(600);
            GetWindowText(hwnd, text, 600);
            if (text.Length > 0) list.Add(text.ToString());
            return true;
        }, IntPtr.Zero);
        return list;
    }

    // The child control of a window with exactly this text, or zero.
    public static IntPtr FindChildByText(IntPtr parent, string wanted)
    {
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, delegate(IntPtr hwnd, IntPtr lParam)
        {
            var text = new StringBuilder(600);
            GetWindowText(hwnd, text, 600);
            if (text.ToString() != wanted) return true;
            found = hwnd;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    // Presses the keys in order and releases them in reverse, like a hand on the keyboard
    // (for shortcuts with the Windows key, which SendKeys cannot type).
    public static void KeyCombo(byte[] keys)
    {
        foreach (var key in keys) { keybd_event(key, 0, 0, UIntPtr.Zero); Thread.Sleep(60); }
        for (var i = keys.Length - 1; i >= 0; i--) { keybd_event(keys[i], 0, 2, UIntPtr.Zero); Thread.Sleep(60); }
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

# Reported, but never fails the run: for steps that depend on the test machine itself.
function Note([bool]$condition, [string]$what) {
    if ($condition) { Write-Host "  [OK]   $what" } else { Write-Host "  [BİLGİ] doğrulanamadı: $what" }
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
# The body is sent as UTF-8 bytes: as a string, Windows PowerShell would send Turkish letters as "?".
function Panel-Post([string]$path, [string]$json = '{}') {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$base$path" -TimeoutSec 10 `
            -Headers @{ 'X-Panel' = '1' } -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($json))
        return [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
    } catch {
        return "HATA: $($_.Exception.Message)"
    }
}

# "Klasör seç" in the panel: the request stays open while the folder window is shown.
function Start-FolderPick {
    return Start-Job -ArgumentList "$base/panel/api/pick-folder" -ScriptBlock {
        param($url)
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $url -TimeoutSec 180 `
                -Headers @{ 'X-Panel' = '1' } -ContentType 'application/json' -Body '{}'
            [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
        } catch {
            "HATA: $($_.Exception.Message)"
        }
    }
}

function Wait-FolderWindow {
    return Wait-Until {
        $h = [Native]::FindWindowByTitle('Sınav klasörünü seçin|Browse For Folder|Klasöre Gözat')
        if ($h -ne [IntPtr]::Zero) { $h }
    } 40
}

function Finish-Job($job, [int]$timeoutSec) {
    $finished = Wait-Job $job -Timeout $timeoutSec
    $output = if ($finished) { (Receive-Job $job) -join '' } else { '' }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    return $output
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

# Types a path into the agent's open/save file window like a student would:
# Alt+N = "File name" box, then the path, then Enter.
function Pick-File([string]$path, [string]$shot = '') {
    $dialog = Wait-Until { $h = [Native]::FindMessageBox([uint32]$script:agent.Id); if ($h -ne [IntPtr]::Zero) { $h } } 15
    if (-not $dialog) { throw 'Dosya penceresi açılmadı.' }
    Start-Sleep -Seconds 1
    if ($shot) { Shot $shot }
    Focus-Window $dialog $script:agent.Id
    [System.Windows.Forms.SendKeys]::SendWait('%n')
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait($path)
    Start-Sleep -Milliseconds 600
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    $closed = Wait-Until { [Native]::FindMessageBox([uint32]$script:agent.Id) -ne $dialog } 10 200
    if (-not $closed) { throw "Dosya penceresi kapanmadı (yazılan yol: $path)." }
}

function Focus-Window([IntPtr]$hwnd, [int]$processId) {
    [Native]::Focus($hwnd)
    Start-Sleep -Milliseconds 400
    if ([Native]::ForegroundPid() -ne $processId) {
        [Native]::ClickTitleBar($hwnd)
        Start-Sleep -Milliseconds 400
    }
}

function Set-AgentText([string]$name, [string]$text) {
    $edit = Wait-Until { Find-Agent ('^' + [regex]::Escape($name) + '$') $Types::Edit } 15
    if (-not $edit) { throw "Metin kutusu bulunamadı: $name" }
    $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($text)
}

# The agent's own main window (not the notice popup, which is also a top-level window).
function Get-AgentWindowHandle([string]$titlePattern) {
    $byProcess = New-Object System.Windows.Automation.PropertyCondition($AE::ProcessIdProperty, $script:agent.Id)
    foreach ($window in $AE::RootElement.FindAll($Scope::Children, $byProcess)) {
        try { if ($window.Current.Name -match $titlePattern) { return [IntPtr]$window.Current.NativeWindowHandle } } catch { }
    }
    return [IntPtr]::Zero
}

function Remaining-Minutes {
    foreach ($text in (Agent-Texts)) { if ($text -match '^Kalan süre: (\d+) dk$') { return [int]$Matches[1] } }
    return -1
}

function Dump-Events {
    foreach ($n in @('2021001', '2021002', '2021003', '2021004', '2021005', '')) {
        Write-Host "  olaylar ($n):"
        Get-Events $n | ForEach-Object { Write-Host "    [$($_.severity)] $($_.type): $($_.message)" }
    }
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
    # Hide the CI machine's own windows so that the screenshots show what a student sees.
    try { (New-Object -ComObject Shell.Application).MinimizeAll() } catch { }

    $config = Join-Path $OutDir 'config.yaml'
    $yaml = @"
# Sınıf ve öğretmen adı aşağıda PANELDEN değiştirilir; ajanın bunları görmesi beklenir.
sinif_adi: "AYAR-DOSYASI"
ogretmen_adi: "Ayar Dosyası Öğretmeni"
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
    $null = $server.Handle   # keeps the process handle, so that its exit code can be read later
    $ready = Wait-Until { (Curl-Text @('-m', '2', "$base/api/info")) -match 'AYAR-DOSYASI' } 60
    Check ([bool]$ready) 'sunucu yanıt veriyor (/api/info)'
    if (-not $ready) { throw 'Sunucu başlamadı.' }
    $healthy = Wait-Until { $s = Get-Snapshot; $s -and $s.health.mediamtx_ok -and -not $s.health.discovery_error } 20
    Check ([bool]$healthy) 'MediaMTX denetim API''si ve UDP keşif dinleyicisi çalışıyor'

    # ------------------------------------------------------- panel: before the exam
    Step 'Panel: sınıf ve öğretmen adı'
    $identity = Panel-Post '/panel/api/identity' (@{ sinif_adi = 'CI-101'; ogretmen_adi = 'E2E Öğretmen' } | ConvertTo-Json -Compress)
    Check ($identity -match 'CI-101' -and $identity -match 'E2E Öğretmen') "sınıf ve öğretmen adı panelden değiştirildi ($identity)"
    Check ((Curl-Text @('-m', '2', "$base/api/info")) -match 'CI-101') 'öğrencilerin gördüğü ad güncellendi (/api/info)'

    Step 'Panel: sınav klasörü'
    $refused = Panel-Post '/panel/api/start'
    Check ($refused -match 'HATA') 'klasör seçilmeden sınav dosyası paylaşılamıyor'

    # "Klasör seç" opens the folder window of Windows on this (the teacher's) computer.
    $pick = Start-FolderPick
    $folderWindow = Wait-FolderWindow
    Check ([bool]$folderWindow) '"Klasör seç": Windows''un klasör seçme penceresi açılıyor'
    Start-Sleep -Seconds 1
    Shot 'klasor-penceresi'
    if ($folderWindow) { [Native]::PostMessage($folderWindow, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }   # WM_CLOSE
    $picked = Finish-Job $pick 30
    Check ($picked -match '"cancelled":\s*true') "pencere kapatılınca klasör seçilmiş sayılmıyor ($picked)"

    # Choosing a folder in that window (typed like a user would). Depends on the dialog of this
    # Windows version, so it is reported but does not fail the run.
    $typedFolder = Join-Path $OutDir 'pencereden-secilen'
    New-Item -ItemType Directory -Force -Path $typedFolder | Out-Null
    $pick = Start-FolderPick
    $folderWindow = Wait-FolderWindow
    if ($folderWindow) {
        # Go to the folder through the address bar (Alt+D), then press the dialog's own
        # "Select Folder" button (dialog item 1 = OK, whatever the language of Windows).
        Focus-Window $folderWindow ([int][Native]::PidOf($folderWindow))
        [System.Windows.Forms.SendKeys]::SendWait('%d')
        Start-Sleep -Milliseconds 500
        [System.Windows.Forms.SendKeys]::SendWait($typedFolder)
        Start-Sleep -Milliseconds 600
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
        Start-Sleep -Seconds 2
        Shot 'klasor-penceresi-secim'
        try {
            $dialogElement = $AE::FromHandle($folderWindow)
            $isButton = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $Types::Button)
            $isOk = New-Object System.Windows.Automation.PropertyCondition($AE::AutomationIdProperty, '1')
            $select = $dialogElement.FindFirst($Scope::Descendants, (New-Object System.Windows.Automation.AndCondition($isButton, $isOk)))
            if ($select) {
                Write-Host "  klasör penceresindeki onay düğmesi: $($select.Current.Name)"
                $select.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
            } else {
                [Native]::PostMessage($folderWindow, 0x0111, [IntPtr]1, [IntPtr]::Zero) | Out-Null
            }
        } catch { Write-Host "  (klasör penceresi düğmesine basılamadı: $($_.Exception.Message))" }
    }
    $picked = Finish-Job $pick 20
    Note ($picked -match 'pencereden-secilen' -and (Test-Path (Join-Path $typedFolder 'Teslimler'))) "pencereden seçilen klasör kullanıldı ($picked)"
    $leftover = [Native]::FindWindowByTitle('Sınav klasörünü seçin|Browse For Folder|Klasöre Gözat')
    if ($leftover -ne [IntPtr]::Zero) { [Native]::PostMessage($leftover, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null; Start-Sleep -Seconds 1 }

    # The folder used for the rest of the test: Turkish letters and a space in its name.
    $examFolder = Join-Path $OutDir 'Sınav Klasörü'
    $chosen = Panel-Post '/panel/api/exam-folder' (@{ path = $examFolder } | ConvertTo-Json -Compress)
    Check ($chosen -match 'Sınav Klasörü') "sınav klasörü seçildi ($chosen)"
    $recordingsDir = Join-Path $examFolder 'Kayıtlar'
    $submissionsDir = Join-Path $examFolder 'Teslimler'
    Check ((Test-Path $recordingsDir) -and (Test-Path $submissionsDir)) 'klasörün içinde "Kayıtlar" ve "Teslimler" klasörleri açıldı'
    $chosenState = Get-Snapshot
    Check ($chosenState -and $chosenState.exam.folder -eq $examFolder) "panel sınav klasörünü gösteriyor ($($chosenState.exam.folder))"

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
    $ffmpegIds = @($ffmpeg | ForEach-Object { "$($_.Id)" })
    $consoleWindows = @([Native]::Windows() | Where-Object { $ffmpegIds -contains $_.Split('|', 2)[0] })
    Check ($consoleWindows.Count -eq 0) 'ffmpeg görünür pencere açmıyor (öğrenci komut penceresi görmez)'
    Check ([bool](Wait-AgentText '^Bağlı — ekranınız öğretmene aktarılıyor$' 10)) 'ajan ekranında "Bağlı — ekranınız öğretmene aktarılıyor"'
    Check ($student -and (Get-Student $numara).status -ne 'lost') 'kutu kırmızı değil'
    Shot 'bekleme'

    # During WAITING nothing is closed: Notepad must survive.
    $survivor = Start-Process notepad.exe -PassThru
    Start-Sleep -Seconds 4
    Check ((Count-Events $numara 'process_killed') -eq 0) 'bekleme aşamasında hiçbir program kapatılmıyor'
    Get-Process -Name notepad -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    # --------------------------------------------------------------- exam start
    Step 'Sınavı başlat (başlangıç saati, süre, ekran kaydı)'
    Start-Sleep -Seconds 3
    $before = Get-Snapshot
    Check ($before -and -not $before.health.recording -and -not (Get-ChildItem $recordingsDir -Recurse -File)) 'sınav başlamadan önce ekranlar kaydedilmiyor'
    $noFile = Panel-Post '/panel/api/start' '{"duration_min": 30}'
    Check ($noFile -match 'HATA') 'sınav dosyası yüklenmeden sınav başlatılamıyor'
    $exam = Join-Path $OutDir 'sinav.pka'
    [IO.File]::WriteAllBytes($exam, [Text.Encoding]::ASCII.GetBytes(('PKA-E2E-SINAV-DOSYASI ' * 400)))
    $upload = Curl-Text @('-m', '10', '-H', 'X-Panel: 1', '-F', "file=@$exam", "$base/panel/api/exam-file")
    Check ($upload -match 'sha256') 'sınav dosyası yüklendi'

    # A start planned for later: the student sees the time; cancelling removes it.
    $later = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 900
    $planned = Panel-Post '/panel/api/start' (@{ start_at = $later; duration_min = 30; record = $true } | ConvertTo-Json -Compress)
    Check ($planned -match 'WAITING' -and $planned -match 'scheduled') "sınav ileri bir saat için planlanabiliyor ($planned)"
    Check ([bool](Wait-AgentText '^Sınav saat \d\d:\d\d için planlandı\.$' 8)) 'ajan bekleme ekranında planlanan başlangıç saatini gösteriyor'
    Shot 'bekleme-planlandi'
    $cancelled = Panel-Post '/panel/api/cancel-start'
    Check ($cancelled -match 'WAITING') 'planlanan başlangıç iptal edilebiliyor'
    Check ([bool](Wait-Until { -not (Agent-Texts | Where-Object { $_ -match 'için planlandı' }) } 8)) 'iptal edilince ajandaki saat yazısı kalkıyor'

    $start = Panel-Post '/panel/api/start' (@{ duration_min = 30; record = $true } | ConvertTo-Json -Compress)
    Check ($start -match 'RUNNING') "sınav başladı: 30 dakika, ekran kaydı açık ($start)"
    if ($start -notmatch 'RUNNING') { throw 'Sınav başlatılamadı; kalan adımlar anlamsız.' }
    $recordingOn = Wait-Until { $s = Get-Snapshot; if ($s -and $s.health.recording) { $s } } 10
    Check ([bool]$recordingOn) 'sınav başlayınca MediaMTX ekran kaydı sınav klasörüne açıldı'

    $countdown = Wait-AgentText 'Sınav başlıyor' 8
    Check ([bool]$countdown) 'ajan: "Sınav başlıyor." uyarısı ve geri sayım'
    Shot 'geri-sayim'
    $running = Wait-AgentText '^Sınav sürüyor$' 20
    Check ([bool]$running) 'geri sayımdan sonra sınav paneli: "Sınav sürüyor"'
    Check ([bool](Wait-AgentText '^Kalan süre: (29|30) dk$' 6)) 'süre verildiği için öğrenci panelinde kalan süre yazıyor ("Kalan süre: 30 dk")'
    Check ([bool](Wait-Until { (Count-Events $numara 'enforcement_started') -ge 1 } 10)) 'olay: uygulama denetimi başladı'
    Check (-not (Find-Agent '^Teslim et$' $Types::Button)) 'dosya indirilmeden "Teslim et" görünmüyor'
    Shot 'panel-indirmeden-once'

    Step 'Sınav dosyasını indir (kayıt yerini öğrenci seçer)'
    $studentFolder = Join-Path $OutDir 'ogrencinin-sectigi-klasor'
    New-Item -ItemType Directory -Force -Path $studentFolder | Out-Null
    $pka = Join-Path $studentFolder 'benim-sinavim.pka'
    Click-Agent '^Sınav dosyasını indir$'
    $saveDialog = Wait-Until { $h = [Native]::FindMessageBox([uint32]$script:agent.Id); if ($h -ne [IntPtr]::Zero) { $h } } 15
    Check ([bool]$saveDialog) '"Sınav dosyasını indir" kayıt yerini soran pencereyi açıyor'
    Start-Sleep -Seconds 1
    Shot 'kayit-yeri'
    if ($saveDialog) {
        # Type the location like a student would: Alt+N = "File name" box, then the path, then Enter.
        Focus-Window $saveDialog $script:agent.Id
        [System.Windows.Forms.SendKeys]::SendWait('%n')
        Start-Sleep -Milliseconds 400
        [System.Windows.Forms.SendKeys]::SendWait($pka)
        Start-Sleep -Milliseconds 600
        Shot 'kayit-yeri-yazildi'
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    }
    $downloaded = Wait-Until { Test-Path $pka } 15
    if (-not $downloaded) {
        # The typed path was not taken: accept whatever the dialog offers so the test can go on.
        $still = [Native]::FindMessageBox([uint32]$script:agent.Id)
        if ($still -ne [IntPtr]::Zero) { [Native]::PostMessage($still, 0x0111, [IntPtr]1, [IntPtr]::Zero) | Out-Null }
        Start-Sleep -Seconds 4
    }
    # The agent remembers where the student saved the file; that file is what gets submitted.
    $noteFile = Join-Path $localDir "$numara\sinav.json"
    $savedPath = ''
    if (Test-Path $noteFile) { $savedPath = (Get-Content $noteFile -Raw -Encoding UTF8 | ConvertFrom-Json).path }
    Check ($savedPath -eq $pka) "sınav dosyası öğrencinin seçtiği yere indirildi ($savedPath)"
    if ($savedPath) { $pka = $savedPath }
    if (Test-Path $pka) {
        Check ((Get-FileHash $pka).Hash -eq (Get-FileHash $exam).Hash) 'indirilen dosya yüklenenle aynı'
    }
    Check ([bool](Wait-Until { (Count-Events $numara 'exam_file_ready') -ge 1 } 10)) 'olay: sınav dosyası indirildi'
    Check ([bool](Wait-Until { Find-Agent '^Teslim et$' $Types::Button } 10)) 'dosya indirilince "Teslim et" düğmesi çıkıyor'
    Check (-not (Get-Process | Where-Object { $_.ProcessName -like 'OpenWith*' })) 'dosya kendiliğinden açılmıyor (yalnızca indiriliyor)'
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
    # The panel title is "Sınav" (the other windows are titled "Sınav Ajanı").
    $agentWindow = Wait-Until { $h = Get-AgentWindowHandle '^Sınav$'; if ($h -ne [IntPtr]::Zero) { $h } } 10
    Check ([bool]$agentWindow) 'sınav paneli bulundu (pencere başlığı "Sınav")'
    if ($agentWindow) {
        Check ([Native]::HasMinimizeBox($agentWindow)) 'sınav panelinde simge durumuna küçültme düğmesi var'
        [Native]::ShowWindow($agentWindow, 6) | Out-Null      # SW_MINIMIZE
        Start-Sleep -Milliseconds 700
        Check ([Native]::IsIconic($agentWindow)) 'sınav paneli simge durumuna küçültülebiliyor'
        Shot 'panel-kucultulmus'
        [Native]::ShowWindow($agentWindow, 9) | Out-Null      # SW_RESTORE
        Start-Sleep -Milliseconds 700
        Check (-not [Native]::IsIconic($agentWindow)) 'sınav paneli geri açılabiliyor'
    }
    $winver = Start-Process winver.exe -PassThru   # C:\Windows altında: kapatılmaz, yalnızca izlenir
    $winverWindow = Wait-Until { $winver.Refresh(); if ($winver.MainWindowHandle -ne [IntPtr]::Zero) { $winver.MainWindowHandle } } 10
    Check ([bool]$winverWindow) 'winver penceresi açıldı (C:\Windows altı)'
    if ($winverWindow -and $agentWindow) {
        Focus-Window $agentWindow $script:agent.Id; Start-Sleep -Seconds 2
        Check ([Native]::ForegroundPid() -eq $script:agent.Id) 'ajan paneli öne alınabildi'
        $foreignBefore = Count-Events $numara 'foreign_foreground'

        Focus-Window $winverWindow $winver.Id; Start-Sleep -Milliseconds 2200
        $wasWinver = [Native]::ForegroundPid() -eq $winver.Id
        Focus-Window $agentWindow $script:agent.Id; Start-Sleep -Seconds 3
        Check $wasWinver 'winver öne alınabildi'
        Check ((Count-Events $numara 'foreign_foreground') -eq $foreignBefore) 'yaklaşık 2,5 sn süren geçiş uyarı üretmedi'

        Focus-Window $winverWindow $winver.Id
        $warned = Wait-Until { (Count-Events $numara 'foreign_foreground' 'winver') -ge 1 } 12
        Check ([bool]$warned) '5 sn''den uzun önde kalınca "Packet Tracer dışında bir pencere önde: winver.exe" uyarısı'
        Check (-not $winver.HasExited) 'C:\Windows altındaki program kapatılmadı'
        Focus-Window $agentWindow $script:agent.Id
        Check ([bool](Wait-Until { (Count-Events $numara 'foreground_restored') -ge 1 } 8)) 'izinli pencere öne dönünce olay kaydı'
    }
    if (-not $winver.HasExited) { $winver.Kill() }
    Check ((Count-Events $numara 'foreground_change') -ge 2) 'öndeki pencere değişimleri olay kaydına yazılıyor'

    # --------------------------------------------------------- virtual desktops
    Step 'Başka masaüstüne geçiş'
    if ($agentWindow -and [Desk]::State($agentWindow) -eq 1) {
        [Native]::KeyCombo([byte[]](0x5B, 0x11, 0x44))      # Win+Ctrl+D: new desktop, and switch to it
        $away = Wait-Until { [Desk]::State($agentWindow) -eq 0 } 6 300
        if (-not $away) {
            Write-Host '  [ATLANDI] bu test makinesinde yeni sanal masaüstü açılamadı (Win+Ctrl+D etkisiz).'
        } else {
            $switched = Wait-Until { (Count-Events $numara 'desktop_switch') -ge 1 } 10
            Check ([bool]$switched) 'başka masaüstüne geçince öğretmene "Başka bir masaüstüne geçti" uyarısı gidiyor'
            Note ([bool](Wait-AgentText '^Başka bir masaüstündesiniz$' 4)) 'öğrenciye "Başka bir masaüstündesiniz" bildirimi gösterildi'
            Shot 'baska-masaustu'
            [Native]::KeyCombo([byte[]](0x5B, 0x11, 0x73))  # Win+Ctrl+F4: close that desktop, go back
            $back = Wait-Until { [Desk]::State($agentWindow) -eq 1 } 6 300
            if (-not $back) {
                [Native]::KeyCombo([byte[]](0x5B, 0x11, 0x25))   # Win+Ctrl+Left
                $back = Wait-Until { [Desk]::State($agentWindow) -eq 1 } 6 300
            }
            if (-not $back) { throw 'Sınav masaüstüne geri dönülemedi; kalan adımlar güvenilir olmaz.' }
            Check ([bool](Wait-Until { (Count-Events $numara 'desktop_return') -ge 1 } 10)) 'sınav masaüstüne dönünce olay kaydı'
            Check ((Get-Student $numara).status -eq 'warn') 'panelde kutu sarı'
        }
    } else {
        Write-Host '  [ATLANDI] bu Windows sürümü sanal masaüstü bilgisini vermiyor.'
    }

    # -------------------------------------------------------------------- submit
    Step 'Teslim: öğrenci dosyayı açılan pencereden seçer'
    # 1) The exam file exactly as it was downloaded: the student is warned before anything is sent.
    Click-Agent '^Teslim et$'
    Pick-File $pka 'teslim-dosya-sec'
    $same = Wait-AgentText 'sınav dosyasının aynısı' 10
    Check ([bool]$same) 'değiştirilmemiş sınav dosyası seçilince uyarı: "… indirdiğiniz sınav dosyasının aynısı …"'
    Check ([bool](Find-Agent '^Dosyada değişiklik yok$')) 'uyarı ajanın kendi penceresinde, başlığıyla gösteriliyor ("Dosyada değişiklik yok")'
    Check (-not ([Native]::FindMessageBox([uint32]$script:agent.Id) -ne [IntPtr]::Zero)) 'Windows''un standart ileti kutusu kullanılmıyor'
    Start-Sleep -Milliseconds 500
    Shot 'teslim-ayni-dosya'
    Click-Agent '^Vazgeç$'
    Start-Sleep -Seconds 1

    # 2) A file that was last saved before the exam file was downloaded: most likely a wrong file.
    $oldFile = Join-Path $studentFolder 'eski-odev.pka'
    [IO.File]::WriteAllText($oldFile, 'gecen haftanin odevi')
    (Get-Item $oldFile).LastWriteTime = (Get-Date).AddDays(-2)
    Click-Agent '^Teslim et$'
    Pick-File $oldFile
    $stale = Wait-AgentText 'indirmenizden önce kaydedilmiş' 10
    Check ([bool]$stale) 'sınavdan önce kaydedilmiş dosya seçilince uyarı: "… indirmenizden önce kaydedilmiş …"'
    Start-Sleep -Milliseconds 500
    Shot 'teslim-eski-dosya'
    Click-Agent '^Vazgeç$'
    Start-Sleep -Seconds 1

    # 3) Not a Packet Tracer file at all (typed by name, past the *.pka filter).
    $textFile = Join-Path $studentFolder 'notlar.txt'
    [IO.File]::WriteAllText($textFile, 'bu bir sinav dosyasi degil')
    Click-Agent '^Teslim et$'
    Pick-File $textFile
    $wrongType = Wait-AgentText 'bir Packet Tracer dosyası değil' 10
    Check ([bool]$wrongType) '.pka olmayan dosya teslim edilemiyor'
    Start-Sleep -Milliseconds 500
    Shot 'teslim-reddedildi'
    Click-Agent '^Tamam$'
    Start-Sleep -Seconds 1
    Check (-not (Get-ChildItem $submissionsDir -Filter *.pka)) 'reddedilen seçimlerden hiçbiri öğretmene gönderilmedi'
    Check ((Get-Student $numara).status -ne 'done') 'öğrenci hâlâ teslim etmemiş görünüyor'

    # 4) The saved work.
    [IO.File]::AppendAllText($pka, "`ncozum-$numara")   # "Ctrl+S": the file changes on disk
    $localHash = (Get-FileHash $pka -Algorithm SHA256).Hash.ToLowerInvariant()
    Click-Agent '^Teslim et$'
    Pick-File $pka
    $confirm = Wait-AgentText '^Teslim edilsin mi\?$' 10
    Check ([bool]$confirm) 'onay penceresi: "Teslim edilsin mi?"'
    $confirmTexts = (Agent-Texts) -join "`n"
    Check ($confirmTexts -match 'Dosya: benim-sinavim\.pka' -and $confirmTexts -match 'Son kayıt: \d\d:\d\d') 'onayda seçilen dosyanın adı ve son kayıt saati gösteriliyor'
    Check ($confirmTexts -notmatch 'ogrencinin-sectigi-klasor' -and $confirmTexts -notmatch 'Klasör') 'öğrenciye klasör yolu gösterilmiyor'
    Start-Sleep -Milliseconds 500
    Shot 'teslim-onay'
    Click-Agent '^Evet, teslim et$'

    $done = Wait-AgentText 'Teslim alındı' 20
    Check ([bool]$done) '"Teslim alındı" penceresi'
    Shot 'teslim-alindi'
    $texts = (Agent-Texts) -join "`n"
    Check ($texts -notmatch $localHash -and $texts -notmatch 'SHA') 'öğrenciye SHA gösterilmiyor'
    Check (-not (Find-Agent 'sil' $Types::Button)) 'son pencerede "dosyaları sil" seçeneği yok'
    Click-Agent '^Kapat'

    $exited = $script:agent.WaitForExit(20000)
    Check $exited 'ajan teslimden sonra kapandı'
    Start-Sleep -Seconds 2
    Check (-not (Get-Process ffmpeg -ErrorAction SilentlyContinue)) 'ajan kapanınca ffmpeg.exe de kapandı'
    $submitted = Join-Path $submissionsDir '2021001_SukruCagriIsik.pka'
    Check (Test-Path $submitted) 'teslim dosyası sınav klasöründeki "Teslimler"e Türkçe karakterler çevrilerek kaydedildi (2021001_SukruCagriIsik.pka)'
    if (Test-Path $submitted) {
        Check ((Get-FileHash $submitted -Algorithm SHA256).Hash.ToLowerInvariant() -eq $localHash) 'klasördeki dosya öğrencinin kaydettiğiyle birebir aynı'
    }
    Check ((Get-Student $numara).status -eq 'done') 'panelde kutu gri (teslim etti)'
    $original = Get-Events $numara | Where-Object { $_.type -eq 'submit' } | Select-Object -First 1
    Check ($original -and $original.details.original -eq 'benim-sinavim.pka') 'olay kaydında öğrencinin seçtiği dosyanın adı var'
    Check (-not (Get-Events $numara | Where-Object { $_.type -in @('unchanged_submission', 'stale_submission') })) 'doğru dosya için dosya uyarısı yok'
    $stopped = Wait-Until { $s = Get-Student $numara; if ($s -and -not $s.stream_ready) { $s } } 10
    Check ([bool]$stopped) 'teslim eden öğrencinin ekran yayını durdu'

    Step 'Teslim klasörü denetimi'
    # The student counts as "teslim etti" only while the file is really in the folder.
    $aside = Join-Path $OutDir 'kenarda.pka'
    Move-Item $submitted $aside
    $missing = Wait-Until { $s = Get-Student $numara; if ($s -and $s.status -eq 'nofile') { $s } } 10
    Check ([bool]$missing) 'dosya klasörden kaldırılınca öğrenci artık "teslim etti" görünmüyor'
    Check ((Count-Events $numara 'submission_missing') -eq 1) 'öğretmene "Teslim dosyası klasörde bulunamıyor" uyarısı'
    Move-Item $aside $submitted
    $present = Wait-Until { $s = Get-Student $numara; if ($s -and $s.status -eq 'done') { $s } } 10
    Check ([bool]$present) 'dosya geri konunca yeniden "teslim etti"'

    Step 'Klasöre elle konan dosya teslim sayılıyor ve yayın duruyor'
    $third = '2021003'
    Start-Agent
    Login-Agent $third 'Elden' 'Teslim'
    Check ([bool](Wait-AgentText '^Sınav sürüyor$' 40)) 'üçüncü öğrenci sınavda'
    $streaming = Wait-Until { $s = Get-Student $third; if ($s -and $s.stream_ready) { $s } } 40
    Check ([bool]$streaming) 'üçüncü öğrencinin yayını geldi'
    $byHand = Join-Path $submissionsDir "${third}_usbden.pka"
    [IO.File]::WriteAllBytes($byHand, [Text.Encoding]::ASCII.GetBytes(('PKA-E2E-SINAV-DOSYASI ' * 400) + 'usb'))
    (Get-Item $byHand).LastWriteTime = (Get-Date).AddMinutes(-1)
    $taken = Wait-Until { $s = Get-Student $third; if ($s -and $s.status -eq 'done') { $s } } 15
    Check ([bool]$taken) 'klasöre konan dosya öğrencinin teslimi olarak görüldü'
    if ($taken) { Check ($taken.submission.filename -eq "${third}_usbden.pka") "panelde teslim dosyası: $($taken.submission.filename)" }
    Check ([bool](Wait-AgentText 'Teslim alındı' 15)) 'ajan kendiliğinden "Teslim alındı" diyor'
    Click-Agent '^Kapat'
    Check ($script:agent.WaitForExit(20000)) 'ajan kapandı'
    Start-Sleep -Seconds 2
    Check (-not (Get-Process ffmpeg -ErrorAction SilentlyContinue)) 'ffmpeg.exe kapandı (yayın durdu)'
    $stopped = Wait-Until { $s = Get-Student $third; if ($s -and -not $s.stream_ready) { $s } } 10
    Check ([bool]$stopped) 'MediaMTX''te bu öğrencinin yayını kalmadı'

    Step 'İz bırakmama'
    $run = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue | Out-String
    Check ($run -notmatch 'SinavAjan') 'başlangıç (Run) kayıtlarında ajan yok'
    Check (-not (Get-Service | Where-Object { $_.Name -match 'Sinav' -or $_.DisplayName -match 'Sinav' })) 'ajana ait servis yok'
    Check (-not (Get-ScheduledTask | Where-Object { $_.TaskName -match 'Sinav' })) 'ajana ait zamanlanmış görev yok'
    Check (-not (Get-Process SinavAjan -ErrorAction SilentlyContinue)) 'SinavAjan.exe çalışmıyor'
    Check (Test-Path $pka) 'öğrencinin indirdiği dosya yerinde duruyor (silinmiyor)'
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

    # ------------------------------------------------ extra time, end of exam, late submission
    Step 'Ek süre; sınav bitince program kapanmıyor, geç teslim alınıyor'
    $fourth = '2021004'
    Start-Agent
    Login-Agent $fourth 'Geç' 'Kalan'
    Check ([bool](Wait-AgentText '^Sınav sürüyor$' 40)) 'dördüncü öğrenci sınavda'
    $latePka = Join-Path $studentFolder 'gec-kalan.pka'
    Click-Agent '^Sınav dosyasını indir$'
    Pick-File $latePka
    Check ([bool](Wait-Until { Test-Path $latePka } 15)) 'dördüncü öğrenci sınav dosyasını indirdi'
    Check ([bool](Wait-Until { Find-Agent '^Teslim et$' $Types::Button } 10)) '"Teslim et" düğmesi çıktı'
    [IO.File]::AppendAllText($latePka, "`ncozum-$fourth")

    # "Sınavı bitir" penceresindeki "Ek süre ver".
    $remainingBefore = Remaining-Minutes
    $extended = Panel-Post '/panel/api/extend' '{"minutes": 10}'
    Check ($extended -match 'ends_at') "ek süre verildi ($extended)"
    $grown = Wait-Until { $now = Remaining-Minutes; if ($now -ge $remainingBefore + 9) { $now } } 10
    Check ([bool]$grown) "öğrencideki kalan süre 10 dakika arttı ($remainingBefore dk -> $grown dk)"

    $end = Panel-Post '/panel/api/end'
    $endedAt = Get-Date
    Check ($end -match 'ENDED') 'sınav bitirildi'
    Check ([bool](Wait-AgentText '^Sınav bitti$' 10)) 'sınav bitince öğrenci programı kapanmıyor: panelde "Sınav bitti"'
    Check ([bool](Wait-AgentText 'geç olarak kaydedilecek' 5)) 'öğrenciye teslimin geç sayılacağı söyleniyor'
    Check (-not $script:agent.HasExited -and [bool](Find-Agent '^Teslim et$' $Types::Button)) 'program açık, "Teslim et" düğmesi duruyor'
    Check (-not (Find-Agent 'indir' $Types::Button)) 'sınav bittikten sonra dosya indirilemiyor'
    Start-Sleep -Seconds 1
    Shot 'sinav-bitti-panel'
    $st = Get-Student $fourth
    Check ($st.status -eq 'nosubmit' -and $st.stream_ready) 'panelde "Teslim yok", ekranı hâlâ izleniyor'
    $before = Count-Events $fourth 'process_killed' 'notepad'
    Start-Process notepad.exe | Out-Null
    Check ([bool](Wait-Until { (Count-Events $fourth 'process_killed' 'notepad') -gt $before } 10)) 'teslim edene kadar izinsiz programlar kapatılmaya devam ediyor'

    # A file that was already on its way when the exam ended is not late; wait past that.
    $wait = 13 - ((Get-Date) - $endedAt).TotalSeconds
    if ($wait -gt 0) { Start-Sleep -Seconds ([int][Math]::Ceiling($wait)) }
    Click-Agent '^Teslim et$'
    Pick-File $latePka
    Check ([bool](Wait-AgentText '^Teslim edilsin mi\?$' 10)) 'sınav bittikten sonra da teslim edilebiliyor'
    Check ([bool](Wait-AgentText 'geç teslim olarak kaydedilecek' 5)) 'onayda "geç teslim olarak kaydedilecek" yazıyor'
    Start-Sleep -Milliseconds 500
    Shot 'gec-teslim-onay'
    Click-Agent '^Evet, teslim et$'
    Check ([bool](Wait-AgentText 'geç teslim olarak kaydedildi' 20)) '"Teslim alındı — geç teslim olarak kaydedildi"'
    Shot 'gec-teslim-alindi'
    Click-Agent '^Kapat'
    Check ($script:agent.WaitForExit(20000)) 'ajan teslimden sonra kapandı'
    $st = Get-Student $fourth
    Check ($st.status -eq 'done' -and $st.submission.late) 'panelde teslim geç olarak işaretli'
    Check ((Count-Events $fourth 'late_submission') -eq 1) 'öğretmene "Geç teslim" uyarısı'
    Check (Test-Path (Join-Path $submissionsDir '2021004_GecKalan.pka')) 'geç teslim dosyası Teslimler klasöründe'

    Step 'Uyarılar öğrenci öğrenci ayrı dosyada'
    $alertsDir = Join-Path $examFolder 'Uyarılar'
    $lateFile = Join-Path $alertsDir '2021004_GecKalan.csv'
    Check ((Test-Path $lateFile) -and ((Get-Content $lateFile -Raw -Encoding UTF8) -match 'Geç teslim')) 'Uyarılar\2021004_GecKalan.csv içinde geç teslim uyarısı'
    $firstFile = Join-Path $alertsDir '2021001_SukruCagriIsik.csv'
    $firstText = if (Test-Path $firstFile) { Get-Content $firstFile -Raw -Encoding UTF8 } else { '' }
    Check ($firstText -match 'kapatıldı' -and $firstText -match 'Packet Tracer dışında bir pencere önde') 'Uyarılar\2021001_SukruCagriIsik.csv içinde o öğrencinin uyarıları'
    $fileNames = @(Get-ChildItem $alertsDir -Filter *.csv | ForEach-Object { $_.Name })
    Write-Host "  Uyarılar klasörü: $($fileNames -join ', ')"
    Check (@($fileNames | Where-Object { $_ -notmatch '^\d+_[A-Za-z]+\.csv$' }).Count -eq 0) 'uyarı dosyalarının adı <numara>_<AdSoyad>.csv biçiminde'

    Step 'Kayıtlar'
    $recordings = @(Get-ChildItem (Join-Path $recordingsDir $numara) -Filter *.mp4 -ErrorAction SilentlyContinue)
    Check ($recordings.Count -ge 1 -and ($recordings | Measure-Object Length -Sum).Sum -gt 20000) "ekran kaydı sınav klasöründe: Kayıtlar\$numara ($($recordings.Count) dosya)"
    Check (Test-Path (Join-Path $examFolder 'olay-kaydi.csv')) 'olay kaydı sınav klasörüne yazıldı (olay-kaydi.csv)'
    Check (Test-Path (Join-Path $submissionsDir 'index.csv')) 'teslim dökümü: Teslimler\index.csv'
    Write-Host '  sınav klasörü:'
    Get-ChildItem -Recurse -File $examFolder | ForEach-Object { Write-Host "    $($_.FullName.Substring($examFolder.Length + 1))  ($($_.Length) bayt)" }

    # ------------------------------------- new exam without recording; closing the system
    Step 'Yeni sınav: ekran kaydı seçilmeden'
    Dump-Events
    $reset = Panel-Post '/panel/api/reset'
    Check ($reset -match 'WAITING') 'yeni sınav hazırlandı'
    Check (Test-Path $lateFile) 'yeni sınav hazırlanınca önceki sınavın dosyaları yerinde duruyor'
    $secondFolder = Join-Path $OutDir 'İkinci Sınav'
    Panel-Post '/panel/api/exam-folder' (@{ path = $secondFolder } | ConvertTo-Json -Compress) | Out-Null
    Curl-Text @('-m', '10', '-H', 'X-Panel: 1', '-F', "file=@$exam", "$base/panel/api/exam-file") | Out-Null
    $start = Panel-Post '/panel/api/start' (@{ record = $false } | ConvertTo-Json -Compress)
    Check ($start -match 'RUNNING') "ikinci sınav süresiz ve kayıtsız başladı ($start)"
    $fifth = '2021005'
    Start-Agent
    Login-Agent $fifth 'Son' 'Öğrenci'
    Check ([bool](Wait-AgentText '^Sınav sürüyor$' 40)) 'beşinci öğrenci sınavda'
    Check ((Remaining-Minutes) -eq -1) 'süre verilmeyen sınavda öğrenci süre görmüyor'
    $streaming = Wait-Until { $s = Get-Student $fifth; if ($s -and $s.stream_ready) { $s } } 40
    Check ([bool]$streaming) 'ekranı öğretmene aktarılıyor'
    $lastPka = Join-Path $studentFolder 'son-ogrenci.pka'
    Click-Agent '^Sınav dosyasını indir$'
    Pick-File $lastPka
    Check ([bool](Wait-Until { Test-Path $lastPka } 15)) 'beşinci öğrenci sınav dosyasını indirdi'
    [IO.File]::AppendAllText($lastPka, "`ncozum-$fifth")
    Start-Sleep -Seconds 4
    $state = Get-Snapshot
    Check (-not $state.health.recording -and -not (Get-ChildItem (Join-Path $secondFolder 'Kayıtlar') -Recurse -File)) '"Ekranları kaydet" seçilmeyince ekranlar diske yazılmıyor (canlı izleme sürüyor)'

    Step 'Panel penceresi kapanınca soru; "Sistemi kapat"'
    # The panel page keeps a live connection like this one; ending it is closing the window.
    $panelPage = Start-Process -FilePath 'curl.exe' -ArgumentList @('-s', '-N', "$base/panel/api/stream") `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $OutDir 'panel-akisi.txt')
    Start-Sleep -Seconds 4
    Check (-not ([Native]::FindWindowByTitle('^Sınav İzleme$') -ne [IntPtr]::Zero)) 'panel açıkken soru çıkmıyor'
    Stop-Process -Id $panelPage.Id -Force
    $question = Wait-Until { $h = [Native]::FindWindowByTitle('^Sınav İzleme$'); if ($h -ne [IntPtr]::Zero) { $h } } 30
    Check ([bool]$question) 'panel penceresi kapanınca masaüstünde "sistem mi, pencere mi?" sorusu çıkıyor'
    Start-Sleep -Seconds 1
    Shot 'pencere-kapandi-sorusu'
    if (-not $question) { throw 'Kapanış sorusu çıkmadı; kalan adımlar yapılamaz.' }
    $choices = @([Native]::ChildTexts($question))
    Check (($choices -contains 'Arka planda çalışsın') -and ($choices -contains 'Paneli yeniden aç') -and ($choices -contains 'Sistemi kapat')) 'seçenekler: Arka planda çalışsın / Paneli yeniden aç / Sistemi kapat'
    Check (-not $server.HasExited -and -not $script:agent.HasExited) 'soru yanıtlanana kadar sistem çalışmaya devam ediyor'
    $shutdownButton = [Native]::FindChildByText($question, 'Sistemi kapat')
    if ($shutdownButton -eq [IntPtr]::Zero) { throw "Kapanış sorusunda 'Sistemi kapat' düğmesi bulunamadı (bulunanlar: $($choices -join ' | '))." }
    [Native]::PostMessage($shutdownButton, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null   # BM_CLICK
    # The exam is running: a second question makes sure.
    $questionPid = [Native]::PidOf($question)
    $sure = Wait-Until { $h = [Native]::FindMessageBox($questionPid); if ($h -ne [IntPtr]::Zero) { $h } } 10
    Check ([bool]$sure) 'sınav sürerken "Sistem kapatılsın mı?" diye bir kez daha soruluyor'
    Start-Sleep -Milliseconds 500
    Shot 'sistemi-kapat-onay'
    if ($sure) { [Native]::PostMessage($sure, 0x0111, [IntPtr]6, [IntPtr]::Zero) | Out-Null }   # Yes

    Check ([bool](Wait-AgentText '^Sınav kapatıldı$' 25)) 'öğrenci programı "Sınav kapatıldı" diyor'
    Check ([bool](Wait-AgentText 'otomatik olarak teslim edildi' 5)) 'teslim etmemiş öğrencinin son kaydettiği dosya otomatik alındı'
    Shot 'sinav-kapatildi'
    Click-Agent '^Kapat'
    Check ($script:agent.WaitForExit(20000)) 'öğrenci programı kapandı'
    Check ($server.WaitForExit(30000)) 'sunucu kendiliğinden kapandı'
    if ($server.HasExited) { Check ($server.ExitCode -eq 10) "sunucu çıkış kodu 10 (başlatma penceresi de kapanır): $($server.ExitCode)" }
    $collected = Join-Path $secondFolder 'Teslimler\2021005_SonOgrenci.pka'
    Check (Test-Path $collected) 'otomatik alınan dosya ikinci sınavın Teslimler klasöründe'
    if (Test-Path $collected) {
        Check ((Get-FileHash $collected).Hash -eq (Get-FileHash $lastPka).Hash) 'otomatik alınan dosya öğrencinin son kaydettiğiyle aynı'
    }
    $secondLog = Join-Path $secondFolder 'olay-kaydi.csv'
    Check ((Test-Path $secondLog) -and ((Get-Content $secondLog -Raw -Encoding UTF8) -match 'Sistem kapatıldı')) 'olay kaydında "Sistem kapatıldı"'
    Check (-not (Get-Process ffmpeg -ErrorAction SilentlyContinue)) 'ffmpeg.exe kalmadı'
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
        if ($server -and -not $server.HasExited) { Dump-Events }
        else { Write-Host '  (sunucu kapalı; olaylar yukarıda ve olay-kaydi.csv dosyalarında)' }
    } catch { Write-Host "  (olaylar okunamadı: $($_.Exception.Message))" }
    foreach ($leftover in @('^Sınav İzleme$')) {
        $h = [Native]::FindWindowByTitle($leftover)
        if ($h -ne [IntPtr]::Zero) { [Native]::PostMessage($h, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null }
    }
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
