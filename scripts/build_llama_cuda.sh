#!/usr/bin/env bash
# Build llama-cpp-python with CUDA support for Tesla K80 (sm_37).
# Requires CUDA 11.8 toolkit (see ../cuda/download_cuda_11.8.sh).
#
# Usage:
#   export CUDA_HOME=/usr/local/cuda-11.8
#   export PATH=$CUDA_HOME/bin:$PATH
#   export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
#   ./scripts/build_llama_cuda.sh

set -euo pipefail

if ! command -v nvcc >/dev/null 2>&1; then
  echo "ERROR: nvcc not found. Install CUDA 11.8 and set CUDA_HOME/PATH."
  exit 1
fi

echo "nvcc version:"
nvcc --version

# Warn if the toolkit does not look like 11.8
if ! nvcc --version | grep -q "release 11.8"; then
  echo "WARNING: nvcc does not report CUDA 11.8. K80 (sm_37) requires CUDA 11.x."
fi

echo
echo "Building llama-cpp-python with CMAKE_CUDA_ARCHITECTURES=37 (Tesla K80)"

export CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=37 -DGGML_CUDA_FORCE_MMQ=ON"
export FORCE_CMAKE=1

python -m pip install --upgrade pip
python -m pip install --force-reinstall --no-binary llama-cpp-python llama-cpp-python

echo
echo "Build complete. Verify with:"
echo "  python -c 'from llama_cpp import Llama; print(Llama)'"
