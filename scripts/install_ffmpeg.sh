#!/usr/bin/env bash
# Ensure ffmpeg is available for Modern-TK80 audio/video processing.
# On Windows, install via winget or chocolatey if missing.
# On Linux, use the distro package manager.
set -euo pipefail

if command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg already present: $(command -v ffmpeg)"
  ffmpeg -version | head -n 1
  exit 0
fi

echo "ffmpeg not found. Attempting install..."

if command -v winget >/dev/null 2>&1; then
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
elif command -v choco >/dev/null 2>&1; then
  choco install ffmpeg -y
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update && sudo apt-get install -y ffmpeg
elif command -v brew >/dev/null 2>&1; then
  brew install ffmpeg
else
  echo "No supported package manager found."
  echo "Install ffmpeg manually and ensure it is on PATH."
  exit 1
fi

echo "ffmpeg install finished. Open a new shell if the command is not yet visible."
"""
file_path="/workspace/artifacts/Modern-TK80-Inference/scripts/install_ffmpeg.sh"