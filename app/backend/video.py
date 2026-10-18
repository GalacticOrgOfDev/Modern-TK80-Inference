"""Movie and VFX studio helpers for Modern-TK80.

Timeline clips can carry a VFX. Built-in effects are fade, zoom, pan,
color_grade, and overlay. Models can also invent a custom effect by name
(tv_static, fire_hand, lightning, etc.). Custom effects are stored on the
clip and a starter shader/process stub is written so the effect can be
expanded later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_DIR = Path(os.environ.get("TK80_VIDEO", "uploads/video"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VFX_DIR = Path(os.environ.get("TK80_VFX", "uploads/vfx"))
VFX_DIR.mkdir(parents=True, exist_ok=True)

BUILTIN_VFX = ("none", "fade", "zoom", "pan", "color_grade", "overlay")
SUPPORTED_VIDEO = (".mp4", ".mov", ".webm")


def is_supported_video(path: Path) -> bool:
    """True if the file is an MP4 (or related) we can store."""
    return path.suffix.lower() in SUPPORTED_VIDEO


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.strip().lower()) or "custom"


def save_video(filename: str, data: bytes) -> Path:
    """Save an uploaded video file (MP4 preferred)."""
    safe = Path(filename).name
    dest = UPLOAD_DIR / safe
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = UPLOAD_DIR / f"{stem}_{i}{suffix}"
            i += 1
    dest.write_bytes(data)
    return dest


def make_clip(
    clip_id: int,
    prompt: str = "",
    duration: float = 1.0,
    path: Optional[str] = None,
    vfx: str = "none",
) -> Dict[str, Any]:
    """Create a timeline clip. vfx may be a built-in or a custom name."""
    return {
        "id": clip_id,
        "prompt": prompt,
        "duration": max(0.1, float(duration)),
        "path": path or "",
        "vfx": _safe_name(vfx) if vfx else "none",
        "params": {},
        "custom": False,
    }


def make_vfx(name: str, description: str = "") -> Dict[str, Any]:
    """Create a custom VFX by name and write a starter stub.

    Returns the effect record. The stub is a short Python process outline
    that later encode or shader stages can expand.
    """
    safe = _safe_name(name)
    desc = description.strip() or f"Custom VFX: {safe}"
    stub = (
        f"# VFX stub: {safe}\n"
        f"# {desc}\n"
        f"# process(frame):\n"
        f"#   return apply_{safe}(frame)\n"
    )
    dest = VFX_DIR / f"{safe}.py"
    if dest.exists():
        i = 1
        while dest.exists():
            dest = VFX_DIR / f"{safe}_{i}.py"
            i += 1
    dest.write_text(stub, encoding="utf-8")
    return {
        "name": safe,
        "description": desc,
        "path": str(dest),
        "builtin": safe in BUILTIN_VFX,
    }


def apply_vfx(
    clip: Dict[str, Any],
    vfx: str,
    params: Optional[Dict[str, Any]] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Attach a VFX to a clip. Custom names are accepted and stubbed."""
    safe = _safe_name(vfx)
    clip["vfx"] = safe
    clip["params"] = dict(params or {})
    clip["custom"] = safe not in BUILTIN_VFX
    if clip["custom"]:
        info = make_vfx(safe, description)
        clip["vfx_path"] = info["path"]
        clip["vfx_description"] = info["description"]
    else:
        clip.pop("vfx_path", None)
        clip.pop("vfx_description", None)
    return clip


def reorder(clips: List[Dict[str, Any]], new_order: List[int]) -> List[Dict[str, Any]]:
    """Reorder clips by id. Unknown ids are ignored."""
    by_id = {c["id"]: c for c in clips}
    return [by_id[i] for i in new_order if i in by_id]


def export_manifest(clips: List[Dict[str, Any]], name: str = "timeline") -> Dict[str, Any]:
    """Write a JSON manifest of the current timeline."""
    total = sum(c.get("duration", 1.0) for c in clips)
    manifest = {
        "name": name,
        "clips": clips,
        "total_duration": round(total, 3),
        "note": "Manifest staged. Full movie encode (ffmpeg) comes later.",
    }
    dest = UPLOAD_DIR / f"{name}.json"
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["path"] = str(dest)
    return manifest