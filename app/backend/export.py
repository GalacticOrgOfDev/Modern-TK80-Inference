"""Studio exporters for Modern-TK80.

Central place for timeline, animation, and audio export. JSON is the
native format. Other formats are staged with a clear header so a later
encoder (ffmpeg, glTF writer, etc.) can replace the body.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .video import ANIM_FORMATS, UPLOAD_DIR, _safe_name


def export_timeline(
    clips: List[Dict[str, Any]],
    texts: Optional[List[Dict[str, Any]]] = None,
    objects_3d: Optional[List[Dict[str, Any]]] = None,
    name: str = "timeline",
) -> Dict[str, Any]:
    """Write a full timeline manifest including clips, text, and 3D objects."""
    texts = texts or []
    objects_3d = objects_3d or []
    total = sum(c.get("duration", 1.0) for c in clips)
    manifest = {
        "name": name,
        "clips": clips,
        "texts": texts,
        "objects_3d": objects_3d,
        "total_duration": round(total, 3),
        "note": "JSON manifest. Encode to mp4 later.",
    }
    dest = UPLOAD_DIR / f"{name}.json"
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["path"] = str(dest)
    return manifest


def export_animation(obj: Dict[str, Any], fmt: str = "json") -> Dict[str, Any]:
    """Write an animation file. json is complete; other formats are staged."""
    fmt = fmt if fmt in ANIM_FORMATS else "json"
    name = _safe_name(obj.get("content") or obj.get("kind") or "anim")
    dest = UPLOAD_DIR / f"{name}.{fmt}"
    if fmt == "json":
        dest.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    else:
        header = (
            f"# Modern-TK80 staged {fmt} animation\n"
            f"# name: {name}\n"
            f"# replace this body with a real {fmt} writer later\n"
        )
        dest.write_text(header, encoding="utf-8")
    return {"path": str(dest), "format": fmt, "name": name}


def export_audio_note(path: Path, fmt: str = "wav") -> Dict[str, Any]:
    """Record an audio export. wav is the native mix output."""
    return {"path": str(path), "format": fmt, "note": "WAV bounce from mix_arrangement"}
