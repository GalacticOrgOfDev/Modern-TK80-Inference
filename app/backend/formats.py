"""Shared file-type handling for Modern-TK80.

One place for audio, video, model, and animation formats. Callers use
these helpers instead of scattering suffix checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

AUDIO_STORE = (".wav", ".mp3", ".flac", ".ogg", ".aiff", ".m4a", ".aac", ".wma")
AUDIO_PROCESS = AUDIO_STORE
VIDEO_STORE = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".mpeg", ".wmv")
MODEL_STORE = (".obj", ".gltf", ".glb", ".fbx")
ANIM_FORMATS = ("json", "gltf", "fbx", "bvh")


def suffix(path: Path | str) -> str:
    return Path(path).suffix.lower()


def is_audio(path: Path | str) -> bool:
    return suffix(path) in AUDIO_STORE


def is_processable_audio(path: Path | str) -> bool:
    return suffix(path) in AUDIO_PROCESS


def is_video(path: Path | str) -> bool:
    return suffix(path) in VIDEO_STORE


def is_model(path: Path | str) -> bool:
    return suffix(path) in MODEL_STORE


def is_anim(fmt: str) -> bool:
    return fmt.lower() in ANIM_FORMATS


def catalog() -> Dict[str, List[str]]:
    return {
        "audio_store": list(AUDIO_STORE),
        "audio_process": list(AUDIO_PROCESS),
        "video_store": list(VIDEO_STORE),
        "model_store": list(MODEL_STORE),
        "anim": list(ANIM_FORMATS),
    }
