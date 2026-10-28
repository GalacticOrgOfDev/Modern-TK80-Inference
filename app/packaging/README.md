# Packaging

Target artifact: `Modern-TK80.exe` installed by `MTK80Setup.msi`.

## What the MSI does

1. Installs `Modern-TK80.exe` to `Program Files\Modern-TK80`.
2. Bundles the frontend next to the exe.
3. Runs the dependency installer (`scripts/install.ps1`) so fastapi, uvicorn, pywebview, and the rest of `requirements.txt` are present.
4. Creates a Start Menu shortcut.

## Build steps

1. PyInstaller the launcher:
   ```
   pyinstaller --name Modern-TK80 --windowed app/launcher.py
   ```
2. Copy `app/frontend` next to the exe.
3. WiX or a similar tool builds `MTK80Setup.msi` from `packaging/Product.wxs`.

## Requirements on the target

- Windows 10 or later
- For K80 inference: R470 driver and CUDA 11.8
- For non-WAV audio and video split: ffmpeg (installer can call `scripts/install_ffmpeg.sh`)

## Status

The WiX skeleton is in `Product.wxs`. It is not a signed production MSI yet.
