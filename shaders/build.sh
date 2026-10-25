#!/bin/sh
# Compile GLSL compute shaders to SPIR-V.
# Requires glslangValidator or glslc on PATH.
set -e
cd "$(dirname "$0")"
if command -v glslangValidator >/dev/null 2>&1; then
  glslangValidator -V matmul.comp -o matmul.spv
elif command -v glslc >/dev/null 2>&1; then
  glslc matmul.comp -o matmul.spv
else
  echo "No SPIR-V compiler found. Install glslangValidator or glslc." >&2
  exit 1
fi
echo "Wrote matmul.spv"
