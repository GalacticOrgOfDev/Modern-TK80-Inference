"""Movie and VFX studio helpers for Modern-TK80.

A simple timeline of clips (image or generated frames) with optional
VFX layers. Export is staged as a manifest; full encode can be added later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_DIR = Path(os.environ.get("TK80_VIDEO", "uploads/video"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

VFX_TYPES = ("none", "fade", "zoom", "pan", "color_grade", "overlay")


def make_clip(
    clip_id: int,
    prompt: str = "",
    duration: float = 1.0,
    path: Optional[str] = None,
    vfx: str = "none",
) -> Dict[str, Any]:
    """Create a timeline clip. vfx is one of the supported effect names."""
    if vfx not in VFX_TYPES:
        vfx = "none"
    return {
        "id": clip_id,
        "prompt": prompt,
        "duration": max(0.1, float(duration)),
        "path": path or "",
        "vfx": vfx,
        "params": {},
    }


def apply_vfx(clip: Dict[str, Any], vfx: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Attach a VFX effect to a clip. Replaces any previous effect."""
    if vfx not in VFX_TYPES:
        raise ValueError(f"vfx must be one of {VFX_TYPES}")
    clip["vfx"] = vfx
    clip["params"] = dict(params or {})
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