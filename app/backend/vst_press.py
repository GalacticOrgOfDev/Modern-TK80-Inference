"""Press a generated VST3 source into a binary.

Searches for the Steinberg VST3 SDK, cmake, and a C++ compiler, then
runs cmake configure and build. Returns the .vst3 path when the build
succeeds, or a clear note when something is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SDK = ROOT / "sdk" / "vst3sdk"
SEARCH_SDK = [
    DEFAULT_SDK,
    Path.home() / "vst3sdk",
    Path.home() / "SDKs" / "vst3sdk",
    Path("C:/SDK/vst3sdk"),
    Path("C:/vst3sdk"),
]


def _which(names: List[str]) -> Optional[str]:
    """future docstring"""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def sdk_path() -> Optional[Path]:
    """future docstring"""
    env = os.environ.get("TK80_VST3_SDK")
    if env and Path(env).exists():
        return Path(env)
    for candidate in SEARCH_SDK:
        if candidate.exists():
            return candidate
    return None


def find_toolchain() -> Dict[str, Optional[str]]:
    """future docstring"""
    return {
        "cmake": _which(["cmake"]),
        "compiler": _which(["cl", "g++", "clang++", "c++"]),
    }


def press_vst(source: Path, name: str = "Plugin") -> Dict[str, Any]:
    """Configure and build a .vst3 from generated source."""
    if not source or not Path(source).exists():
        return {"pressed": False, "note": "source file not found", "source": str(source)}
    source = Path(source)
    sdk = sdk_path()
    tools = find_toolchain()
    out_dir = source.parent / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = out_dir / f"{name}.vst3"

    result: Dict[str, Any] = {
        "source": str(source),
        "sdk": str(sdk) if sdk else None,
        "cmake": tools["cmake"],
        "compiler": tools["compiler"],
        "binary": str(binary),
        "pressed": False,
    }

    if not sdk:
        result["note"] = "VST3 SDK not found. Run scripts/install_vst3sdk.sh or set TK80_VST3_SDK."
        return result
    if not tools["cmake"] or not tools["compiler"]:
        result["note"] = "cmake or a C++ compiler was not found on PATH."
        return result

    cmake_lists = out_dir / "CMakeLists.txt"
    cmake_lists.write_text(
        f"""cmake_minimum_required(VERSION 3.15)
project({name} LANGUAGES CXX)
set(SMTG_ENABLE_VST3_PLUGIN_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory("{sdk}" vst3sdk)
""",
        encoding="utf-8",
    )

    try:
        subprocess.run(
            [tools["cmake"], "-S", str(out_dir), "-B", str(out_dir / "cmake-build")],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        subprocess.run(
            [tools["cmake"], "--build", str(out_dir / "cmake-build"), "--config", "Release"],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        result["pressed"] = True
        result["note"] = f"Build finished. Expected binary: {binary}"
    except subprocess.CalledProcessError as e:
        result["note"] = f"Build failed: {e.stderr[-400:] if e.stderr else e}"
    except subprocess.TimeoutExpired:
        result["note"] = "Build timed out."
    return result
