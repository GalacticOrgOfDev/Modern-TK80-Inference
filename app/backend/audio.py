"""Audio studio helpers: tracks, clips, sample rate, Scarlett profiles."""

from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_DIR = Path(os.environ.get("TK80_UPLOADS", "uploads/audio"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHANNELS = ("stereo", "left", "right")
DEFAULT_SAMPLE_RATE = 44100
COMMON_RATES = (44100, 48000, 88200, 96000, 176400, 192000)

# Focusrite Scarlett 2i2 profiles.
# Gen 1: up to 96 kHz. Gen 2: up to 192 kHz.
# Detection is by device label; generation is best-effort from label text.
SCARLETT_PROFILES = {
    "scarlett_2i2_gen1": {
        "name": "Focusrite Scarlett 2i2 Gen 1",
        "rates": [44100, 48000, 88200, 96000],
        "bit_depth": 24,
        "inputs": 2,
        "outputs": 2,
        "notes": "USB-B. Prefer 44100 or 48000 for lowest latency. Max 96 kHz.",
    },
    "scarlett_2i2_gen2": {
        "name": "Focusrite Scarlett 2i2 Gen 2",
        "rates": [44100, 48000, 88200, 96000, 176400, 192000],
        "bit_depth": 24,
        "inputs": 2,
        "outputs": 2,
        "notes": "USB-B. Prefer 44100 or 48000 for lowest latency. Supports up to 192 kHz.",
    },
}


def detect_scarlett(label: str) -> Optional[Dict[str, Any]]:
    """Return a Scarlett profile if the device label matches 2i2 Gen 1 or Gen 2."""
    if not label:
        return None
    text = label.lower()
    if "scarlett" not in text and "focusrite" not in text:
        return None
    if "2i2" not in text:
        return None

    # Gen 2 labels often include "2nd" or "gen 2". Gen 1 is the default 2i2 match.
    if "2nd" in text or "gen 2" in text or "generation 2" in text:
        key = "scarlett_2i2_gen2"
    else:
        key = "scarlett_2i2_gen1"

    profile = dict(SCARLETT_PROFILES[key])
    profile["id"] = key
    profile["matched_label"] = label
    return profile


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
    sample_rate: int = DEFAULT_SAMPLE_RATE,
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
        "sample_rate": sample_rate,
    }


def make_track(
    track_id: int,
    name: str,
    channel: str = "stereo",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> Dict[str, Any]:
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
        "sample_rate": sample_rate,
        "scarlett": None,
    }
