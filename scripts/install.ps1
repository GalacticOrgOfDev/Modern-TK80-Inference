# Install Modern-TK80 dependencies on Windows.
# Run from the repo root: powershell -ExecutionPolicy Bypass -File scripts/install.ps1
$ErrorActionPreference = "Stop"
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }

Write-Host "Using: $(& $py --version)"

& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt

Write-Host "Core and modality packages installed."
Write-Host "Torch and llama-cpp need Python 3.11-3.14. On 3.15 they are skipped."
file_path="/workspace/artifacts/Modern-TK80-Inference/scripts/install.ps1"