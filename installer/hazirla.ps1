<#
.SYNOPSIS
    İki kurulum dosyasını üretir:

      SinavIzleme-Kurulum.exe   sınavı yapan kişinin bilgisayarı (her şey içinde: Python,
                                paketler, MediaMTX, öğrenci programı)
      SinavAjan-Kurulum.exe     öğrenci bilgisayarı

.DESCRIPTION
    Gerekenler: Python 3.11+ (tam kurulum; kopyası kurulumun içine konur), internet (paketler
    ve MediaMTX için), Inno Setup 6 (yoksa Chocolatey ile kurulur) ve derlenmiş SinavAjan.exe.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\hazirla.ps1 -AgentExe publish\SinavAjan.exe
#>
[CmdletBinding()]
param(
    # Derlenmiş öğrenci programı (dotnet publish çıktısı)
    [Parameter(Mandatory = $true)][string]$AgentExe,
    # Kurulum dosyalarının yazılacağı klasör (varsayılan: publish\)
    [string]$OutDir = '',
    [string]$Version = '1.0.1',
    # Kopyası kuruluma konacak Python
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$root = (Resolve-Path (Join-Path $here '..')).Path
if (-not $OutDir) { $OutDir = Join-Path $root 'publish' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path
$AgentExe = (Resolve-Path $AgentExe).Path

function Invoke-Checked([string]$what, [scriptblock]$command) {
    & $command
    if ($LASTEXITCODE -ne 0) { throw "$what başarısız oldu (çıkış kodu $LASTEXITCODE)." }
}

$stage = Join-Path $root 'build\sistem'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# ---- 1) Python: bu bilgisayardaki tam kurulumun kopyası (tkinter dahil) -------------------
$pyHome = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$pyTag = (& $Python -c "import sys; print('%d%d' % sys.version_info[:2])").Trim()
$pyVersion = (& $Python -c "import sys; print(sys.version.split()[0])").Trim()
if (-not (Test-Path (Join-Path $pyHome 'pythonw.exe'))) { throw "Tam bir Python kurulumu bulunamadı: $pyHome" }
Write-Host "Python $pyVersion kopyalanıyor: $pyHome"
$pyStage = Join-Path $stage 'python'
# Gerekmeyenler dışarıda: testler, IDLE, pip, başlık dosyaları, belgeler, eski derlemeler.
robocopy $pyHome $pyStage /E /NFL /NDL /NJH /NJS /NP `
    /XD __pycache__ test tests idlelib turtledemo ensurepip venv Scripts include libs Doc Tools share site-packages `
    /XF *.pyc *.chm *.pdb | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Python kopyalanamadı (robocopy $LASTEXITCODE)." }
$sitePackages = Join-Path $pyStage 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
# Yalıtım: bu Python yalnızca kendi klasörlerini kullanır; bilgisayardaki başka Python
# kurulumları, PYTHONPATH ve kullanıcının kendi paketleri karışmaz.
Set-Content -LiteralPath (Join-Path $pyStage "python$pyTag._pth") -Encoding Ascii -Value @('Lib', 'Lib\site-packages', 'DLLs', '.')

# ---- 2) Paketler ---------------------------------------------------------------------------
Invoke-Checked 'Paket kurulumu' {
    & $Python -m pip install --disable-pip-version-check --no-warn-script-location --no-compile `
        --target $sitePackages -r (Join-Path $root 'server\requirements.txt')
}
Remove-Item -Recurse -Force (Join-Path $sitePackages 'bin') -ErrorAction SilentlyContinue

# ---- 3) Sunucu -----------------------------------------------------------------------------
$serverStage = Join-Path $stage 'server'
New-Item -ItemType Directory -Force -Path (Join-Path $serverStage 'sinav'), (Join-Path $serverStage 'static') | Out-Null
Copy-Item (Join-Path $root 'server\run.py'), (Join-Path $root 'server\config.yaml') -Destination $serverStage
Copy-Item (Join-Path $root 'server\sinav\*.py') -Destination (Join-Path $serverStage 'sinav')
Copy-Item (Join-Path $root 'server\static\*') -Destination (Join-Path $serverStage 'static')

# ---- 4) MediaMTX ---------------------------------------------------------------------------
$mediaStage = Join-Path $stage 'mediamtx'
& (Join-Path $root 'scripts\fetch-mediamtx.ps1') -OutDir $mediaStage
if (-not (Test-Path (Join-Path $mediaStage 'mediamtx.exe'))) { throw 'MediaMTX indirilemedi.' }
Copy-Item (Join-Path $root 'mediamtx\mediamtx.yml') -Destination $mediaStage

# ---- 5) Öğrenci programı: sınav günü sınıf ağından da indirilebilsin ------------------------
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'dist') | Out-Null
Copy-Item -LiteralPath $AgentExe -Destination (Join-Path $stage 'dist\SinavAjan.exe')

# ---- 6) Derlenmiş .pyc dosyaları -------------------------------------------------------------
# Program Files altına yazılamadığı için Python her açılışta yeniden derlemek zorunda kalırdı.
# "unchecked-hash": dosya tarihlerine bakılmaz (kurulum tarihleri değiştirebilir).
$stagedPython = Join-Path $pyStage 'python.exe'
& $stagedPython -m compileall -q --invalidation-mode unchecked-hash (Join-Path $pyStage 'Lib') $serverStage | Out-Null
Write-Host "compileall çıkış kodu: $LASTEXITCODE (derlenemeyen dosya olabilir; zararsızdır)"

# ---- 7) Paketlenen Python çalışıyor mu? ------------------------------------------------------
$check = "import sys; sys.path.insert(0, r'$serverStage'); import tkinter, fastapi, uvicorn, yaml, openpyxl, multipart; " +
         "import sinav.app, sinav.desktopapp; tkinter.Tcl().eval('info patchlevel'); " +
         "assert not any('site-packages' in p and r'$pyStage' not in p for p in sys.path), sys.path; print('paketlenen Python tamam:', sys.version.split()[0])"
Invoke-Checked 'Paketlenen Python denetimi' { & $stagedPython -c $check }

$size = (Get-ChildItem -Recurse -File $stage | Measure-Object Length -Sum).Sum
Write-Host ("Kurulacak dosyalar: {0:N0} MB" -f ($size / 1MB))
Get-ChildItem $stage | ForEach-Object {
    $bytes = (Get-ChildItem -Recurse -File $_.FullName | Measure-Object Length -Sum).Sum
    Write-Host ("  {0,-10} {1,6:N0} MB" -f $_.Name, ($bytes / 1MB))
}

# ---- 8) Inno Setup ---------------------------------------------------------------------------
function Find-Iscc {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) { if (Test-Path $candidate) { return $candidate } }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}
$iscc = Find-Iscc
if (-not $iscc) {
    Write-Host 'Inno Setup bulunamadı; Chocolatey ile kuruluyor...'
    Invoke-Checked 'Inno Setup kurulumu' { choco install innosetup -y --no-progress | Out-Host }
    $iscc = Find-Iscc
}
if (-not $iscc) { throw 'Inno Setup (ISCC.exe) bulunamadı.' }
Write-Host "Inno Setup: $iscc"

Invoke-Checked 'Sistem kurulum dosyası' {
    & $iscc /Qp "/DAppVersion=$Version" "/DSource=$stage" "/DOutputDir=$OutDir" (Join-Path $here 'sistem.iss')
}
Invoke-Checked 'Öğrenci kurulum dosyası' {
    & $iscc /Qp "/DAppVersion=$Version" "/DAgentExe=$AgentExe" "/DOutputDir=$OutDir" (Join-Path $here 'ajan.iss')
}

Get-ChildItem $OutDir -Filter '*-Kurulum.exe' | ForEach-Object { Write-Host ("{0}  {1:N0} MB" -f $_.Name, ($_.Length / 1MB)) }
