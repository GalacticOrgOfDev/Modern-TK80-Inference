#!/usr/bin/env bash
# Install every Modern-TK80 dependency so imports resolve.
# Torch and llama-cpp need a Python that has wheels (3.11-3.14).
# On 3.15, core packages install and torch is skipped with a note.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python}"

echo "Using: $($PY --version)"

# Core app
$PY -m pip install fastapi uvicorn python-multipart pydantic pyyaml numpy pywebview sounddevice

# Modalities and monitoring
$PY -m pip install diffusers transformers pynvml

# Torch: only if a wheel exists for this Python
if $PY -m pip install "torch>=2.0.0" --index-url https://download.pytorch.org/whl/cu118; then
  echo "torch installed"
else
  echo "torch has no wheel for this Python. Use 3.11-3.14 for inference."
fi

# llama-cpp: source build for K80
if [[ -x "$ROOT/scripts/build_llama_cuda.sh" ]]; then
  echo "For llama-cpp with CUDA, run: scripts/build_llama_cuda.sh"
fi

echo "Install pass complete."
file_path="/workspace/artifacts/Modern-TK80-Inference/scripts/install.sh"