$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $workspacePath
try {
    & '.\.venv\Scripts\python.exe' -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    Push-Location -LiteralPath 'frontend'
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend checks failed.' }
    } finally { Pop-Location }
    Push-Location -LiteralPath 'firmware'
    try {
        & '..\.venv\Scripts\python.exe' -m platformio run
        if ($LASTEXITCODE -ne 0) { throw 'Firmware build failed.' }
    } finally { Pop-Location }
} finally { Pop-Location }
