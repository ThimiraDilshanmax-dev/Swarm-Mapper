param(
    [switch]$Lan,
    [switch]$NoBrowser,
    [switch]$Rebuild,
    [int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $workspacePath
try {
    $pythonPath = Join-Path $workspacePath '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $pythonPath)) {
        Write-Host 'Creating the local Python environment...'
        if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
        elseif (Get-Command python -ErrorAction SilentlyContinue) { & python -m venv .venv }
        else { throw 'Install Python 3.11 or newer, then run this launcher again.' }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & $pythonPath -c "import importlib.util,sys; sys.exit(0 if all(importlib.util.find_spec(x) for x in ('fastapi','uvicorn','numpy','scipy','mapper')) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing application dependencies...'
        & $pythonPath -m ensurepip --upgrade
        & $pythonPath -m pip install -r requirements.lock
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry.' }
        & $pythonPath -m pip install --no-deps -e .
        if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
    }
    $indexPath = Join-Path $workspacePath 'frontend\dist\index.html'
    $buildNeeded = $Rebuild -or !(Test-Path -LiteralPath $indexPath)
    if (!$buildNeeded) {
        $indexTime = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc
        $sourceFiles = Get-ChildItem -LiteralPath (Join-Path $workspacePath 'frontend\src') -File -Recurse
        $buildNeeded = @($sourceFiles | Where-Object { $_.LastWriteTimeUtc -gt $indexTime }).Count -gt 0
    }
    if ($buildNeeded) {
        if (!(Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 20.19+ or a current LTS release to build the interface.' }
        Push-Location -LiteralPath (Join-Path $workspacePath 'frontend')
        try {
            if (!(Test-Path -LiteralPath 'node_modules')) {
                & npm.cmd ci --no-audit --no-fund
                if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    $listenAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
    Write-Host ''
    Write-Host "Contour: http://127.0.0.1:$Port" -ForegroundColor Cyan
    Write-Host 'Press Ctrl+C to stop. Motor control also has a firmware-side watchdog.'
    if ($Lan) {
        Write-Host 'LAN mode: connect the ESP32 to this computer''s Wi-Fi IPv4 address.'
        Write-Host 'Allow this application on your private network if Windows Firewall asks.'
    }
    if (!$NoBrowser) {
        # This browser window is the user-requested application.
        Start-Process "http://127.0.0.1:$Port"
    }
    & $pythonPath run.py --host $listenAddress --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Server stopped with an error; check whether the port is already in use.' }
} finally { Pop-Location }
