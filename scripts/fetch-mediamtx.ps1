<#
.SYNOPSIS
    MediaMTX'i (mediamtx.exe) indirir ve mediamtx\ klasörüne koyar.

.DESCRIPTION
    Sürüm sabittir (aşağıdaki $Version); mediamtx\mediamtx.yml bu sürümün anahtar adlarıyla
    yazılmıştır. Arşivle gelen örnek mediamtx.yml KULLANILMAZ; depodaki dosyaya dokunulmaz.
    İnternet gerekir; sınavdan ÖNCE çalıştırın. (start-teacher.bat ilk çalıştırmada bu betiği
    kendisi çağırır.)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\fetch-mediamtx.ps1
#>
[CmdletBinding()]
param(
    # mediamtx.exe dosyasının konacağı klasör (varsayılan: mediamtx\)
    [string]$OutDir = '',
    # mediamtx.exe zaten varsa yeniden indir
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Varsayılan klasör burada hesaplanır, param() içinde değil: Windows PowerShell 5.1,
# -File ile çalıştırılan betikte param() varsayılanlarını hesaplarken $PSScriptRoot'u boş
# verir (gövdede doludur).
if (-not $OutDir) {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $here) { throw 'Betiğin klasörü bulunamadı; -OutDir ile hedef klasörü verin.' }
    $OutDir = Join-Path $here '..\mediamtx'
}
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# ---- Sabitlenmiş sürüm ------------------------------------------------------
# Sürümü yükseltirseniz: $Sha256 değerini güncelleyin (sürüm sayfasındaki
# checksums.sha256) ve mediamtx\mediamtx.yml dosyasını yeni sürümle gelen örnek
# mediamtx.yml ile karşılaştırın; anahtar adları sürümler arasında değişebilir.
$Version = 'v1.21.4'
$ZipName = "mediamtx_${Version}_windows_amd64.zip"
$Url     = "https://github.com/bluenviron/mediamtx/releases/download/$Version/$ZipName"
$Sha256  = '835645b2700ffce4d2b6cb04bfa0aadce95335da6dfc0d7c2114e6da585734f8'
# -----------------------------------------------------------------------------

$target = Join-Path $OutDir 'mediamtx.exe'
if ((Test-Path $target) -and -not $Force) {
    Write-Host "mediamtx.exe zaten var: $target  (yeniden indirmek için -Force)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$work = Join-Path ([IO.Path]::GetTempPath()) ('sinav-mediamtx-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $zip = Join-Path $work $ZipName
    Write-Host "İndiriliyor: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing

    $hash = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLowerInvariant()
    Write-Host "SHA-256: $hash"
    if ($Sha256 -and ($hash -ne $Sha256.ToLowerInvariant())) {
        throw "SHA-256 uyuşmuyor. Beklenen: $Sha256  Bulunan: $hash  (indirme bozuk ya da dosya değişmiş)"
    }

    $extract = Join-Path $work 'x'
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $exe = Get-ChildItem -Path $extract -Recurse -Filter 'mediamtx.exe' | Select-Object -First 1
    if (-not $exe) { throw 'Arşivin içinde mediamtx.exe bulunamadı.' }
    Copy-Item -Path $exe.FullName -Destination $target -Force
    $license = Join-Path $exe.DirectoryName 'LICENSE'
    if (Test-Path $license) { Copy-Item -Path $license -Destination (Join-Path $OutDir 'LICENSE') -Force }

    Write-Host "Tamam: $target  (MediaMTX $Version)"
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
