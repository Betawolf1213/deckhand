# Downloads the Vosk model + Vosk runtime (and optionally Whisper) for Deckhand; idempotent, -Force re-downloads.
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Whisper,
    [switch]$PauseOnError
)

# Keep the window open on failure when launched by start.ps1, so the error can be read.
trap { Write-Host $_ -ForegroundColor Red; if ($PauseOnError) { Read-Host 'Download failed. Press Enter to close' }; exit 1 }

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$models = Join-Path $root 'models'
New-Item -ItemType Directory -Force -Path $models | Out-Null

function Fetch($url, $dest) {
    if ((Test-Path $dest) -and -not $Force) {
        Write-Host "  [skip] $dest already exists" -ForegroundColor DarkGray
        return
    }
    Write-Host "  [get]  $url" -ForegroundColor Cyan
    $tmp = "$dest.part"
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        # Built-in curl: fast, shows progress, modern TLS on Windows PowerShell 5.1.
        & $curl -L --fail --progress-bar -o $tmp $url
        if ($LASTEXITCODE -ne 0) { throw "Download failed ($LASTEXITCODE): $url" }
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    }
    Move-Item -Force $tmp $dest
}

Write-Host "== Vosk small English model =="
$voskZip = Join-Path $models 'vosk-model-small-en-us-0.15.zip'
$voskDir = Join-Path $models 'vosk-model-small-en-us'
if (-not (Test-Path $voskDir) -or $Force) {
    Fetch 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip' $voskZip
    Write-Host "  [unzip]"
    Expand-Archive -Path $voskZip -DestinationPath $models -Force
    if (Test-Path (Join-Path $models 'vosk-model-small-en-us-0.15')) {
        Remove-Item -Recurse -Force $voskDir -ErrorAction SilentlyContinue
        Rename-Item (Join-Path $models 'vosk-model-small-en-us-0.15') $voskDir
    }
    Remove-Item $voskZip -ErrorAction SilentlyContinue
} else {
    Write-Host "  [skip] $voskDir already exists" -ForegroundColor DarkGray
}

if ($Whisper) {
    Write-Host "== Whisper.cpp tiny English model (optional, unused until Whisper is wired up) =="
    $whisperBin = Join-Path $models 'ggml-tiny.en.bin'
    Fetch 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin' $whisperBin
}

Write-Host "== Vosk Windows binary release (libvosk.dll + vosk_api.h) =="
# Version pinned to the last tested drop. Bump if a newer release is required.
$voskApiVersion = '0.3.45'
$voskApiZip = Join-Path $models "vosk-win64-$voskApiVersion.zip"
$vendorDir = Join-Path $root 'vendor\vosk-api'
if (-not (Test-Path (Join-Path $vendorDir 'libvosk.dll')) -or $Force) {
    Fetch "https://github.com/alphacep/vosk-api/releases/download/v$voskApiVersion/vosk-win64-$voskApiVersion.zip" $voskApiZip
    Write-Host "  [unzip] -> $vendorDir"
    New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
    Expand-Archive -Path $voskApiZip -DestinationPath $models -Force
    $extracted = Join-Path $models "vosk-win64-$voskApiVersion"
    if (Test-Path $extracted) {
        Get-ChildItem $extracted | ForEach-Object { Copy-Item -Force $_.FullName $vendorDir }
        Remove-Item -Recurse -Force $extracted
    }
    if (Test-Path (Join-Path $vendorDir 'libvosk.lib')) {
        # Zig/LLD searches for vosk.lib when the source declares extern "vosk".
        Copy-Item -Force (Join-Path $vendorDir 'libvosk.lib') (Join-Path $vendorDir 'vosk.lib')
    }
    foreach ($runtime in @('libstdc++-6.dll', 'libgcc_s_seh-1.dll', 'libwinpthread-1.dll')) {
        $runtimePath = Join-Path $vendorDir $runtime
        if (-not (Test-Path $runtimePath)) { Write-Warning "$runtime missing from $vendorDir" }
    }
    Remove-Item $voskApiZip -ErrorAction SilentlyContinue
} else {
    Write-Host "  [skip] $vendorDir already populated" -ForegroundColor DarkGray
    if (Test-Path (Join-Path $vendorDir 'libvosk.lib')) {
        Copy-Item -Force (Join-Path $vendorDir 'libvosk.lib') (Join-Path $vendorDir 'vosk.lib')
    }
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
Write-Host "Models in: $models"
Write-Host "Vosk-api in: $vendorDir"
