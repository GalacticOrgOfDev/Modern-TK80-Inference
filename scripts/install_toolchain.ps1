# Install the VST toolchain and Steinberg VST3 SDK on Windows.
# Run: powershell -ExecutionPolicy Bypass -File scripts/install_toolchain.ps1
$ErrorActionPreference = "Stop"

Write-Host "Installing CMake..."
winget install --id Kitware.CMake -e --accept-source-agreements --accept-package-agreements

Write-Host "Installing Visual Studio Build Tools (C++ toolchain)..."
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --accept-source-agreements --accept-package-agreements --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools"

Write-Host "Cloning Steinberg VST3 SDK..."
$root = Split-Path -Parent $PSScriptRoot
$sdk = Join-Path $root "sdk\vst3sdk"
if (-not (Test-Path "$sdk\.git")) {
    New-Item -ItemType Directory -Force -Path (Split-Path $sdk) | Out-Null
    git clone --recursive https://github.com/steinbergmedia/vst3sdk.git $sdk
}
Write-Host "SDK at $sdk"
Write-Host "Accept the Steinberg license at https://github.com/steinbergmedia/vst3sdk"
Write-Host "Toolchain install complete."
