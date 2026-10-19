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
        "note": "JSON manifest. Use /api/video/encode for MP4.",
    }
    dest = UPLOAD_DIR / f"{name}.json"
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["path"] = str(dest)
    return manifest


def encode_mp4(
    clips: List[Dict[str, Any]],
    out_name: str = "timeline.mp4",
    width: int = 1280,
    height: int = 720,
) -> Dict[str, Any]:
    """Encode the timeline to an MP4 via ffmpeg.

    Existing video files are concatenated. If none exist, a black segment
    is written. Returns the output path.
    """
    import shutil
    import subprocess
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required to encode MP4")
    dest = UPLOAD_DIR / out_name
    if dest.suffix.lower() != ".mp4":
        dest = dest.with_suffix(".mp4")
    existing = [str(Path(c["path"])) for c in clips if c.get("path") and Path(c["path"]).exists()]
    if existing:
        list_file = UPLOAD_DIR / "concat.txt"
        list_file.write_text("\n".join(f"file '{p}'" for p in existing), encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    else:
        dur = max(1.0, sum(float(c.get("duration", 1.0)) for c in clips) or 1.0)
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:d={dur}",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)
    return {"path": str(dest), "encoded": True, "clips": len(clips)}


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
