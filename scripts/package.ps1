# Builds release\Deckhand-v<Version>.zip laid out like the repo, so start.bat runs it without Zig.
[CmdletBinding()]
param(
    [string]$Version = '2.0.0',
    [switch]$SkipBuild,
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (-not $SkipBuild) {
        # Normal-user build by default; -Elevated only for players who run the game as admin.
        $elevate = if ($Elevated) { 'true' } else { 'false' }
        Write-Host "== zig build -Doptimize=ReleaseFast -Delevate=$elevate ==" -ForegroundColor Cyan
        zig build -Doptimize=ReleaseFast "-Delevate=$elevate"
        if ($LASTEXITCODE -ne 0) { throw 'zig build failed' }
    }

    $bin = Join-Path $root 'zig-out\bin'
    if (-not (Test-Path (Join-Path $bin 'deckhand.exe'))) { throw "Missing zig-out\bin\deckhand.exe" }
    if (-not (Test-Path (Join-Path $bin 'libvosk.dll'))) { throw "zig-out\bin has no libvosk.dll: run scripts\fetch_models.ps1, then build again." }
    $voskDir = Join-Path $root 'models\vosk-model-small-en-us'
    if (-not (Test-Path $voskDir)) { throw "Missing Vosk model. Run scripts\fetch_models.ps1." }

    $stage = Join-Path $root ("release\stage-" + $Version)
    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    New-Item -ItemType Directory -Force -Path (Join-Path $stage 'zig-out\bin'), (Join-Path $stage 'models'), (Join-Path $stage 'scripts') | Out-Null

    Write-Host '== Copying artifacts ==' -ForegroundColor Cyan
    # The exe needs libvosk.dll and its C++ runtime DLLs, which zig build installs beside it.
    Get-ChildItem $bin -File | Where-Object { $_.Extension -in '.exe', '.dll' } | ForEach-Object { Copy-Item $_.FullName (Join-Path $stage 'zig-out\bin') }
    Copy-Item -Recurse -Force $voskDir (Join-Path $stage 'models\vosk-model-small-en-us')
    Copy-Item -Recurse -Force (Join-Path $root 'frontend') (Join-Path $stage 'frontend')
    Copy-Item -Recurse -Force (Join-Path $root 'config') (Join-Path $stage 'config')
    Copy-Item -Recurse -Force (Join-Path $root 'docs') (Join-Path $stage 'docs')
    Copy-Item (Join-Path $root 'scripts\start.ps1'), (Join-Path $root 'scripts\fetch_models.ps1') (Join-Path $stage 'scripts')
    Copy-Item (Join-Path $root 'start.bat'), (Join-Path $root 'README.md'), (Join-Path $root '.env.example') $stage
    Copy-Item (Join-Path $root 'LICENSE'), (Join-Path $root 'THIRD_PARTY_NOTICES.md') $stage
    Copy-Item -Recurse -Force (Join-Path $root 'licenses') (Join-Path $stage 'licenses')

    # Drop caches, tests and local settings from the staged copy.
    Get-ChildItem $stage -Recurse -Force -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    Remove-Item -Recurse -Force (Join-Path $stage 'frontend\tests') -ErrorAction SilentlyContinue
    Remove-Item -Force (Join-Path $stage 'config\ui_settings.json'), (Join-Path $stage 'config\commands.json') -ErrorAction SilentlyContinue

    $zipPath = Join-Path $root ("release\Deckhand-v$Version.zip")
    if (Test-Path $zipPath) { Remove-Item $zipPath }
    Write-Host "== Zipping -> $zipPath ==" -ForegroundColor Cyan
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath
    Remove-Item -Recurse -Force $stage

    Write-Host ''
    Write-Host "Done: $zipPath" -ForegroundColor Green
} finally {
    Pop-Location
}
