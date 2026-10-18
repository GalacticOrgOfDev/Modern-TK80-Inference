"""Audio studio helpers: upload storage, waveform peaks, clip state."""

from __future__ import annotations

import os
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

UPLOAD_DIR = Path(os.environ.get("TK80_UPLOADS", "uploads/audio"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(filename: str, data: bytes) -> Path:
    safe = Path(filename).name
    dest = UPLOAD_DIR / safe
    # Avoid overwrite
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
    """Simple peak envelope for WAV. Returns normalized 0-1 values."""
    try:
        with wave.open(str(path), "rb") as w:
            n = w.getnframes()
            if n == 0:
                return [0.0] * buckets
            sw = w.getsampwidth()
            raw = w.readframes(n)
            # Use absolute byte magnitude as a rough envelope
            step = max(1, len(raw) // buckets)
            peaks = []
            for i in range(buckets):
                chunk = raw[i * step : (i + 1) * step]
                if not chunk:
                    peaks.append(0.0)
                    continue
                peak = max(chunk) / 255.0
                peaks.append(round(peak, 3))
            return peaks
    except Exception:
        return [0.2] * buckets


def make_clip(clip_id: int, name: str, path: Optional[Path] = None, duration: float = 0.0) -> Dict[str, Any]:
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
    }
