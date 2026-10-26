# Create .venv and install core deps so the app can launch for testing.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3.12 -m venv .venv
} else {
    python -m venv .venv
}

$pip = Join-Path $root ".venv\Scripts\pip.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"

& $python -m pip install --upgrade pip
& $pip install -r requirements-core.txt

Write-Host ""
Write-Host "venv ready. Activate and launch:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python -m app.launcher"
