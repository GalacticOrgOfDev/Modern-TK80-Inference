#!/bin/sh
# Compile GLSL compute shaders to SPIR-V.
# Requires glslangValidator or glslc on PATH.
set -e
cd "$(dirname "$0")"
compile() {
  src="$1"
  dst="${src%.comp}.spv"
  if command -v glslangValidator >/dev/null 2>&1; then
    glslangValidator -V "$src" -o "$dst"
  elif command -v glslc >/dev/null 2>&1; then
    glslc "$src" -o "$dst"
  else
    echo "No SPIR-V compiler found. Install glslangValidator or glslc." >&2
    exit 1
  fi
  echo "Wrote $dst"
}
compile matmul.comp
compile softmax.comp
compile layernorm.comp
compile rope.comp
compile attention.comp
compile gemv.comp
