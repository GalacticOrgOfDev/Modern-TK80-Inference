"""Movie and VFX studio helpers for Modern-TK80.

Timeline clips can carry a VFX. Built-in effects are fade, zoom, pan,
color_grade, and overlay. Models can also invent a custom effect by name
(tv_static, fire_hand, lightning, etc.). Custom effects are stored on the
clip and a starter shader/process stub is written so the effect can be
expanded later.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .formats import ANIM_FORMATS, MODEL_STORE, VIDEO_STORE, is_model, is_video

UPLOAD_DIR = Path(os.environ.get("TK80_VIDEO", "uploads/video"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VFX_DIR = Path(os.environ.get("TK80_VFX", "uploads/vfx"))
VFX_DIR.mkdir(parents=True, exist_ok=True)

BUILTIN_VFX = ("none", "fade", "zoom", "pan", "color_grade", "overlay")
TRANSITIONS = ("none", "cut", "crossfade", "wipe", "dissolve")
SUPPORTED_VIDEO = VIDEO_STORE
SUPPORTED_MODELS = MODEL_STORE


def is_supported_video(path: Path) -> bool:
    """True if the file is a video format we can store."""
    return is_video(path)


def split_audio(path: Path) -> Dict[str, Any]:
    """Split the audio track out of a video file via ffmpeg.

    Returns the original video path and the extracted audio path.
    """
    import shutil
    import subprocess
    if not is_video(path):
        raise ValueError("not a supported video file")
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required to split audio")
    audio_path = path.with_suffix(".wav")
    if audio_path.exists():
        audio_path = path.with_name(f"{path.stem}_audio.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-vn", "-acodec", "pcm_s16le", str(audio_path)],
        check=True,
        capture_output=True,
    )
    return {"video": str(path), "audio": str(audio_path)}


def is_supported_model(path: Path) -> bool:
    """True if the file is a 3D model we can store."""
    return is_model(path)


def _safe_name(name: str) -> str:
    """Sanitize a name for files and identifiers."""
    if not name:
        return "custom"
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(name).strip().lower())
    return cleaned or "custom"


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


def make_3d(
    obj_id: int,
    kind: str = "text",
    content: str = "",
    model_path: str = "",
    position: float = 0.0,
    duration: float = 2.0,
) -> Dict[str, Any]:
    """Create a 3D object. kind is 'text' or 'model'.

    Text becomes a 3D text mesh. Model references an uploaded .obj/.gltf/.glb/.fbx.
    """
    kind = kind if kind in ("text", "model") else "text"
    return {
        "id": obj_id,
        "type": "3d",
        "kind": kind,
        "content": content,
        "model_path": model_path,
        "position": max(0.0, float(position)),
        "duration": max(0.1, float(duration)),
        "animation": [],
    }


def add_animation(
    obj: Dict[str, Any],
    name: str,
    start: float = 0.0,
    end: float = 1.0,
    fmt: str = "json",
) -> Dict[str, Any]:
    """Attach an animation clip to a 3D object or text object."""
    fmt = fmt if fmt in ANIM_FORMATS else "json"
    entry = {
        "name": _safe_name(name),
        "start": max(0.0, float(start)),
        "end": max(float(start), float(end)),
        "format": fmt,
    }
    obj.setdefault("animation", []).append(entry)
    return obj


def make_text(
    text_id: int,
    content: str,
    position: float = 0.0,
    duration: float = 2.0,
    texture: str = "plain",
    x: float = 0.5,
    y: float = 0.5,
) -> Dict[str, Any]:
    """Create a text object that lives on the timeline.

    texture can be plain, stone, metal, wood, fire, or any custom name.
    x/y are normalized 0..1 positions on the frame.
    """
    return {
        "id": text_id,
        "type": "text",
        "content": content,
        "position": max(0.0, float(position)),
        "duration": max(0.1, float(duration)),
        "texture": _safe_name(texture) if texture else "plain",
        "x": max(0.0, min(1.0, float(x))),
        "y": max(0.0, min(1.0, float(y))),
        "vfx": [],
    }


def set_text_style(
    text_obj: Dict[str, Any],
    size: float = 48.0,
    color: str = "#ffffff",
    align: str = "center",
) -> Dict[str, Any]:
    """Set simple style fields on a text object."""
    text_obj["size"] = max(8.0, float(size))
    text_obj["color"] = color or "#ffffff"
    text_obj["align"] = align if align in ("left", "center", "right") else "center"
    return text_obj


def add_text_vfx(text_obj: Dict[str, Any], vfx: str, description: str = "") -> Dict[str, Any]:
    """Attach a VFX (built-in or custom) to a text object."""
    safe = _safe_name(vfx)
    entry = {"name": safe, "description": description}
    if safe not in BUILTIN_VFX:
        info = make_vfx(safe, description)
        entry["path"] = info["path"]
    text_obj.setdefault("vfx", []).append(entry)
    return text_obj


def make_text_scene(
    text_id: int,
    content: str,
    texture: str = "plain",
    steps: Optional[List[str]] = None,
    position: float = 0.0,
    duration: float = 3.0,
) -> Dict[str, Any]:
    """Build a text object and apply a sequence of VFX steps.

    Example steps: ["fall", "impact_rubble", "lightning_wrap"].
    Each step becomes a custom VFX stub attached in order.
    """
    obj = make_text(text_id, content, position, duration, texture)
    for step in steps or []:
        add_text_vfx(obj, step, f"{content} {step}")
    return obj


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


def make_vfx(name: str, description: str = "", params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a custom VFX by name and write a starter stub with parameters.

    Returns the effect record. The stub is a short Python process outline
    that later encode or shader stages can expand.
    """
    safe = _safe_name(name)
    desc = description.strip() or f"Custom VFX: {safe}"
    params = params or {}
    stub = (
        f"# VFX stub: {safe}\n"
        f"# {desc}\n"
        f"# params: {params}\n"
        f"# process(frame):\n"
        f"#   return apply_{safe}(frame, params)\n"
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
        "params": params,
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


def set_transition(clips: List[Dict[str, Any]], index: int, kind: str = "cut", duration: float = 0.5) -> Dict[str, Any]:
    """Set the transition that plays after the clip at index."""
    if index < 0 or index >= len(clips):
        raise ValueError("clip index out of range")
    kind = _safe_name(kind)
    if kind not in TRANSITIONS:
        kind = "cut"
    clips[index]["transition"] = {"kind": kind, "duration": max(0.0, float(duration))}
    return clips[index]


def export_manifest(clips: List[Dict[str, Any]], texts: Optional[List[Dict[str, Any]]] = None, name: str = "timeline") -> Dict[str, Any]:
    """Deprecated. Use export.export_timeline instead."""
    from .export import export_timeline
    return export_timeline(clips, texts, name=name)