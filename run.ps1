# Start the chess coach on Windows. Runs scripts/setup.py until it finishes once.
# Arguments go to scripts/run.py, for example: .\run.ps1 --no-build
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\.setup-done)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 scripts/setup.py }
    else { python scripts/setup.py }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& .venv\Scripts\python.exe scripts/run.py @args
exit $LASTEXITCODE
