"""Audio studio helpers: tracks, clips, upload storage, waveform peaks."""

from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_DIR = Path(os.environ.get("TK80_UPLOADS", "uploads/audio"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHANNELS = ("stereo", "left", "right")


def save_upload(filename: str, data: bytes) -> Path:
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


def wav_duration(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def wav_peaks(path: Path, buckets: int = 64) -> List[float]:
    try:
        with wave.open(str(path), "rb") as w:
            n = w.getnframes()
            if n == 0:
                return [0.0] * buckets
            raw = w.readframes(n)
            step = max(1, len(raw) // buckets)
            peaks = []
            for i in range(buckets):
                chunk = raw[i * step : (i + 1) * step]
                if not chunk:
                    peaks.append(0.0)
                    continue
                peaks.append(round(max(chunk) / 255.0, 3))
            return peaks
    except Exception:
        return [0.2] * buckets


def make_clip(
    clip_id: int,
    name: str,
    path: Optional[Path] = None,
    duration: float = 0.0,
    track_id: Optional[int] = None,
) -> Dict[str, Any]:
    dur = duration
    peaks: List[float] = []
    rel = ""
    if path is not None:
        measured = wav_duration(path)
        if measured is not None:
            dur = measured
        peaks = wav_peaks(path)
        rel = str(path)
    return {
        "id": clip_id,
        "name": name,
        "duration": round(dur, 3),
        "path": rel,
        "gain": 1.0,
        "start": 0.0,
        "end": round(dur, 3),
        "reversed": False,
        "peaks": peaks,
        "track_id": track_id,
    }


def make_track(track_id: int, name: str, channel: str = "stereo") -> Dict[str, Any]:
    if channel not in CHANNELS:
        channel = "stereo"
    return {
        "id": track_id,
        "name": name,
        "channel": channel,
        "gain": 1.0,
        "mute": False,
        "solo": False,
        "armed": False,
        "device_id": None,
        "device_label": None,
    }
