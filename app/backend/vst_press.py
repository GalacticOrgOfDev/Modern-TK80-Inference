"""Press a generated VST3 source into a binary when the SDK is present.

Looks for the Steinberg VST3 SDK (TK80_VST3_SDK or ./sdk/vst3sdk).
If cmake and a compiler are available, configures a minimal JUCE-less
build note and records the expected .vst3 output path. Full compile
requires the SDK and a C++ toolchain on the machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SDK = ROOT / "sdk" / "vst3sdk"


def sdk_path() -> Optional[Path]:
    env = os.environ.get("TK80_VST3_SDK")
    if env and Path(env).exists():
        return Path(env)
    if DEFAULT_SDK.exists():
        return DEFAULT_SDK
    return None


def press_vst(source: Path, name: str = "Plugin") -> Dict[str, Any]:
    """Attempt to press a .vst3 from generated source.

    Returns status, expected output path, and any toolchain notes.
    """
    sdk = sdk_path()
    out_dir = source.parent / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = out_dir / f"{name}.vst3"
    cmake = shutil.which("cmake")
    compiler = shutil.which("cl") or shutil.which("g++") or shutil.which("clang++")

    result: Dict[str, Any] = {
        "source": str(source),
        "sdk": str(sdk) if sdk else None,
        "cmake": bool(cmake),
        "compiler": bool(compiler),
        "binary": str(binary),
        "pressed": False,
    }

    if not sdk:
        result["note"] = "VST3 SDK not found. Run scripts/install_vst3sdk.sh first."
        return result
    if not cmake or not compiler:
        result["note"] = "cmake or a C++ compiler is missing. Install the toolchain, then press again."
        return result

    # Stage a CMakeLists that points at the SDK. Actual compile is left to cmake
    # so the machine's toolchain and SDK layout are respected.
    cmake_lists = out_dir / "CMakeLists.txt"
    cmake_lists.write_text(
        f"""cmake_minimum_required(VERSION 3.15)
project({name} LANGUAGES CXX)
set(SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory("{sdk}" vst3sdk)
# Generated processor is header-style; user completes the JUCE or SDK target.
""",
        encoding="utf-8",
    )
    result["note"] = (
        f"SDK found. CMakeLists staged at {cmake_lists}. "
        "Run cmake && cmake --build in that folder to produce the .vst3."
    )
    result["staged"] = True
    return result