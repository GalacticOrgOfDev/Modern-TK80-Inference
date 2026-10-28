# Packaging

Target artifact: `Modern-TK80.exe` installed by `MTK80Setup.msi`.

## What the MSI does today

Per `Product.wxs` (the only WiX source):

1. Installs one file, `Modern-TK80.exe`, to `Program Files\Modern-TK80` (`Product.wxs:14-15`, `Product.wxs:22-25`).
2. That is all. There is no custom action, no Python, no wheels, no frontend files and no shortcut component. A `ProgramMenuFolder\Modern-TK80` directory is declared (`Product.wxs:17-19`) but nothing is installed into it.

The MSI does not run `scripts/install.ps1`. That script is a developer bootstrap: run by hand from the repo root, it installs Python 3.12 through winget if missing, then pip-installs the dependencies (`scripts/install.ps1:26-54`).

## Planned (not built)

The MSI is meant to be a separate, self-contained installer that bundles Python and the dependency wheels, so the target machine needs no pip step. Earlier text here also said the MSI bundles the frontend and creates a Start Menu shortcut; neither is in `Product.wxs` yet. Nothing in this section is in `Product.wxs` yet.

## Build steps

1. PyInstaller the launcher:
   ```
   pyinstaller --name Modern-TK80 --windowed app/launcher.py
   ```
2. Copy `app/frontend` next to the exe.
3. WiX or a similar tool builds `MTK80Setup.msi` from `app/packaging/Product.wxs`. Step 2 is not picked up by the current `Product.wxs`, which lists only the exe.

## Requirements on the target

- Windows 10 or later
- For K80 inference: R470 driver and CUDA 11.8
- For non-WAV audio and video split: ffmpeg (the MSI does not install it; `scripts/install_ffmpeg.sh` is a separate script)

## Status

The WiX skeleton is in `Product.wxs`. It is not a signed production MSI yet.
