#!/usr/bin/env bash
# Install the Steinberg VST3 SDK for Modern-TK80.
# The SDK is proprietary. This script clones the official public repo
# only after you accept the Steinberg license. It does not redistribute
# the SDK. Default location: ./sdk/vst3sdk
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SDK_DIR="${TK80_VST3_SDK:-$ROOT/sdk/vst3sdk}"
REPO="https://github.com/steinbergmedia/vst3sdk.git"

if [[ -d "$SDK_DIR/.git" ]]; then
  echo "VST3 SDK already present at $SDK_DIR"
  exit 0
fi

echo "Steinberg VST3 SDK license applies."
echo "See https://github.com/steinbergmedia/vst3sdk for terms."
read -r -p "Accept the Steinberg VST3 SDK license and clone? [y/N] " ans
if [[ "${ans,,}" != "y" ]]; then
  echo "Aborted."
  exit 1
fi

mkdir -p "$(dirname "$SDK_DIR")"
git clone --recursive "$REPO" "$SDK_DIR"
echo "VST3 SDK installed at $SDK_DIR"
echo "Set TK80_VST3_SDK=$SDK_DIR if you move it."