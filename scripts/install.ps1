# Modern-TK80 setup. Installs Python (if needed) and every dependency.
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1
$ErrorActionPreference = "Stop"

function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "E:\program files\python312\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $ver = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($ver) { return $ver.Trim() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    return $null
}

Write-Host "Modern-TK80 setup"
$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.12 not found. Installing via winget..."
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $py = Find-Python
    if (-not $py) {
        Write-Host "Install Python 3.12 from https://www.python.org/downloads/ and re-run."
        exit 1
    }
}
Write-Host "Using: $py"
& $py --version

& $py -m pip install --upgrade pip
& $py -m pip install fastapi uvicorn python-multipart pydantic pyyaml numpy pywebview sounddevice
& $py -m pip install diffusers transformers pynvml

Write-Host "Installing torch (CUDA 11.8 index)..."
& $py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
if ($LASTEXITCODE -ne 0) {
    Write-Host "Torch install failed. Confirm this Python is 3.11-3.14."
}

Write-Host "Installing llama-cpp-python..."
& $py -m pip install llama-cpp-python
if ($LASTEXITCODE -ne 0) {
    Write-Host "llama-cpp failed. For K80 CUDA build, run scripts/build_llama_cuda.sh"
}

Write-Host "Setup complete."
