# Deckhand launcher: fetches missing models, rebuilds when needed, starts the hidden engine + GUI, explains failures.
param([switch]$NoDialog)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$exe = Join-Path $root 'zig-out\bin\deckhand.exe'
$hotkey = 'ctrl+shift+f12'
$stopHotkey = 'ctrl+shift+f11'  # silences speech even when the echo guard swallows "robot stop talking"
$tmp = $env:TEMP
$startLog = Join-Path $tmp 'deckhand-start.log'
$engineLog = Join-Path $tmp 'deckhand-backend.log'
$engineErr = Join-Path $tmp 'deckhand-backend-error.log'
$quiet = $NoDialog -or ($env:DECKHAND_NO_DIALOG -eq '1')
$required = @('models\vosk-model-small-en-us\conf\model.conf', 'vendor\vosk-api\libvosk.dll', 'vendor\vosk-api\libvosk.lib')
Set-Content $startLog "[$(Get-Date -Format s)] start in $root"

function Log($m) { Add-Content $startLog $m }

function Show-Box($msg, $buttons = 'OK', $icon = 'Error') {
    Log "[$icon] $msg"
    if ($quiet) { if ($env:DECKHAND_ASSUME_YES -eq '1') { return 'Yes' } return 'No' }
    Add-Type -AssemblyName System.Windows.Forms
    $owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true }
    try { return [string][System.Windows.Forms.MessageBox]::Show($owner, $msg, 'Deckhand', $buttons, $icon) }
    finally { $owner.Dispose() }
}

function Fail($msg, $logFile) {
    if ($logFile -and (Test-Path $logFile)) { $msg += "`n`n" + ((Get-Content $logFile -Tail 8) -join "`n") }
    [void](Show-Box $msg)
    exit 1
}

function Find-Zig {
    if ($env:DECKHAND_ZIG -and (Test-Path $env:DECKHAND_ZIG)) { return $env:DECKHAND_ZIG }
    $pkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    # WinGet package folders are hidden, so -Force is required to enumerate them.
    $winget = Get-ChildItem $pkgs -Directory -Force -Filter 'zig.zig_*' -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'zig-x86_64-windows-0.14.1\zig.exe' } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($winget) { return $winget }
    $onPath = Get-Command zig -ErrorAction SilentlyContinue
    if ($onPath -and ((& $onPath.Source version 2>$null) -eq '0.14.1')) { return $onPath.Source }
    return $null
}

function Find-Python {
    foreach ($cand in @(@('py', '-3'), @('python'))) {
        $cmd = Get-Command $cand[0] -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $extra = @($cand | Select-Object -Skip 1)
        $exePath = & $cmd.Source @extra -c "import sys; print(sys.executable) if sys.version_info >= (3, 10) else sys.exit(1)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exePath) { return "$exePath".Trim() }
    }
    return $null
}

# Stop old instances: a running engine locks the exe, owns the hotkeys and holds the pipe.
Get-Process deckhand -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*deckhand_ui.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

# The speech model and Vosk runtime are downloads, not part of the repo; offer to fetch them once.
# Vosk build files are only needed when building; a release zip ships the built exe + DLLs.
$canRun = (Test-Path $exe) -and (Test-Path (Join-Path $root 'zig-out\bin\libvosk.dll'))
$hasSources = Test-Path (Join-Path $root 'backend\src')
$needBuild = -not $canRun
if (-not $needBuild -and $hasSources) {
    $src = @(Get-ChildItem (Join-Path $root 'backend\src') -Recurse -Filter *.zig) + @(Get-Item build.zig, build.zig.zon)
    $newest = ($src | Measure-Object -Property LastWriteTime -Maximum).Maximum
    $needBuild = $newest -gt (Get-Item $exe).LastWriteTime
}
function Get-Missing {
    $want = @($required[0])
    if ($needBuild) { $want += $required[1..2] }
    @($want | Where-Object { -not (Test-Path (Join-Path $root $_)) })
}
$missing = Get-Missing
if ($missing.Count) {
    Log "missing: $($missing -join ', ')"
    $ans = Show-Box ("First-time setup: Deckhand needs its offline speech model and the Vosk runtime " +
        "(a one-time download of about 56 MB).`n`nDownload them now?") 'YesNo' 'Question'
    if ($ans -ne 'Yes') {
        Fail "Deckhand can't hear you without the speech model.`n`nRun start.bat again and choose Yes, or run scripts\fetch_models.ps1."
    }
    $fetch = Join-Path $PSScriptRoot 'fetch_models.ps1'
    Start-Process powershell -Wait -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$fetch`"", '-PauseOnError')
    $missing = Get-Missing
    if ($missing.Count) {
        Fail "The download didn't complete. Still missing:`n$($missing -join "`n")`n`nCheck your internet connection and run start.bat again."
    }
}

# Rebuild when the exe is missing, was built without Vosk (no libvosk.dll beside it), or sources are newer.
if ($needBuild) {
    $zig = Find-Zig
    if (-not $zig) {
        Fail ("Zig 0.14.1 is needed to build the Deckhand engine, but it was not found.`n`n" +
            "Install it (winget install zig.zig --version 0.14.1) or set DECKHAND_ZIG to the full path of zig.exe.")
    }
    Log "building with $zig"
    $buildLog = Join-Path $tmp 'deckhand-build.log'
    $b = Start-Process -FilePath $zig -ArgumentList 'build' -WorkingDirectory $root -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $tmp 'deckhand-build.out') -RedirectStandardError $buildLog
    if ($b.ExitCode -ne 0) { Fail "Building the Deckhand engine failed." $buildLog }
}

# GUI needs Python 3.10+ with pywin32 + requests; pythonw keeps it window-only.
$py = Find-Python
if (-not $py) { Fail "Python 3.10 or newer was not found.`n`nInstall it from python.org (tick 'Add python.exe to PATH'), then run start.bat again." }
& $py -c "import win32file, requests" 2>$null
if ($LASTEXITCODE -ne 0) {
    $depsLog = Join-Path $tmp 'deckhand-deps.log'
    Log "installing GUI packages with $py"
    Start-Process -FilePath $py -ArgumentList @('-m', 'pip', 'install', '-r', "`"$root\frontend\requirements.txt`"") -WindowStyle Hidden -Wait `
        -RedirectStandardOutput $depsLog -RedirectStandardError "$depsLog.err"
    & $py -c "import win32file, requests" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "Installing the GUI's Python packages failed." "$depsLog.err" }
}
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
if (-not (Test-Path (Join-Path $root '.env')) -and (Test-Path (Join-Path $root '.env.example'))) {
    Copy-Item (Join-Path $root '.env.example') (Join-Path $root '.env')
}

$p = Start-Process -FilePath $exe -ArgumentList @('--listen', '--hotkey', $hotkey, '--stop-hotkey', $stopHotkey, '--ipc') `
    -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $engineLog -RedirectStandardError $engineErr -PassThru
$p.Id | Set-Content (Join-Path $tmp 'deckhand-backend.pid')
Start-Process -FilePath $pyw -ArgumentList "`"$root\frontend\deckhand_ui.py`"" -WorkingDirectory $root
Log "engine PID $($p.Id); GUI via $pyw"

# If the engine dies right after start, say why instead of leaving the GUI "disconnected".
for ($i = 0; $i -lt 16; $i++) {
    Start-Sleep -Milliseconds 500
    if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) { break }
}
if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) {
    $why = @()
    if (Test-Path $engineLog) { $why += Get-Content $engineLog -Tail 3 }
    if (Test-Path $engineErr) { $why += Get-Content $engineErr -TotalCount 1 }
    Fail ("The Deckhand engine stopped right after starting, so voice commands won't work.`n`n" +
        ($why -join "`n") + "`n`nFull log: $engineLog")
}
Log "[ok] engine running"
exit 0
