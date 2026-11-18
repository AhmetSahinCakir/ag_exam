<#
.SYNOPSIS
    ffmpeg.exe dosyasını indirir. Öğrenci ajanı (SinavAjan.exe) ekranı ffmpeg ile yayınlar;
    ffmpeg.exe depoya konmaz, bu betikle indirilir ve ajanın yanına yerleştirilir.

.DESCRIPTION
    Sürüm sabittir (aşağıdaki $Version). İndirilen arşivin SHA-256 özeti doğrulanır.
    İnternet gerekir; sınavdan ÖNCE çalıştırın.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\fetch-ffmpeg.ps1
    powershell -ExecutionPolicy Bypass -File scripts\fetch-ffmpeg.ps1 -OutDir publish\SinavAjan
#>
[CmdletBinding()]
param(
    # ffmpeg.exe dosyasının konacağı klasör (varsayılan: agent\)
    [string]$OutDir = (Join-Path $PSScriptRoot '..\agent'),
    # ffmpeg.exe zaten varsa yeniden indir
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # ilerleme çubuğu Windows PowerShell'de indirmeyi çok yavaşlatır
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# ---- Sabitlenmiş sürüm ------------------------------------------------------
# gyan.dev "essentials" derlemesi: gdigrab (ekran yakalama) ve libx264 içerir.
# Sürümü değiştirirseniz $Sha256 değerini de güncelleyin ve docs\PROVA.md'deki
# yayın testlerini yeniden yapın.
$Version = '7.1.1'
$ZipName = "ffmpeg-$Version-essentials_build.zip"
$Url     = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/$ZipName"
$Sha256  = ''
# -----------------------------------------------------------------------------

$target = Join-Path $OutDir 'ffmpeg.exe'
if ((Test-Path $target) -and -not $Force) {
    Write-Host "ffmpeg.exe zaten var: $target  (yeniden indirmek için -Force)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$work = Join-Path ([IO.Path]::GetTempPath()) ('sinav-ffmpeg-' + [Guid]::NewGuid().ToString('N'))
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

    Expand-Archive -Path $zip -DestinationPath $work -Force
    $exe = Get-ChildItem -Path $work -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
    if (-not $exe) { throw 'Arşivin içinde ffmpeg.exe bulunamadı.' }
    Copy-Item -Path $exe.FullName -Destination $target -Force

    Write-Host "Tamam: $target  (ffmpeg $Version)"
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
