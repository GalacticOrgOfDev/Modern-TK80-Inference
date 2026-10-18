#!/usr/bin/env bash
# Download CUDA 11.8.0 toolkit (last version supporting Tesla K80 / sm_37)
# Official NVIDIA installer — does not redistribute the binary from this repo.

set -euo pipefail

URL="https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run"
OUT="cuda_11.8.0_520.61.05_linux.run"

echo "Downloading CUDA 11.8.0 toolkit (~4.3 GB)..."
echo "Source: $URL"

wget -c -O "$OUT" "$URL"

chmod +x "$OUT"

echo
echo "Download complete: $OUT"
echo
echo "To install (toolkit only, interactive):"
echo "  sudo sh $OUT"
echo
echo "Silent toolkit-only install example:"
echo "  sudo sh $OUT --toolkit --silent --override"
echo
echo "After install, set:"
echo "  export PATH=/usr/local/cuda-11.8/bin:\$PATH"
echo "  export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:\$LD_LIBRARY_PATH"
