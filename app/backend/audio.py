"""Audio studio helpers: tracks, clips, sample rate, Scarlett profiles.

Modern-TK80 is a Windows desktop app. Audio I/O is native ASIO
(PortAudio / Focusrite USB ASIO), not a browser media device.

Clip edits rewrite the WAV. Mixdown respects mute, solo, gain, channel,
and timeline position.
"""

from __future__ import annotations

import os
import struct
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

UPLOAD_DIR = Path(os.environ.get("TK80_UPLOADS", "uploads/audio"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHANNELS = ("stereo", "left", "right")
DEFAULT_SAMPLE_RATE = 44100
COMMON_RATES = (44100, 48000, 88200, 96000, 176400, 192000)

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


def _read_wav(path: Path) -> Tuple[int, int, int, bytes]:
    """Return rate, channels, sampwidth, frames."""
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())


def _write_wav(path: Path, pcm: bytes, rate: int, channels: int, sampwidth: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def wav_duration(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def wav_peaks(path: Path, buckets: int = 64) -> List[float]:
    """True 16-bit absolute peak per bucket, normalized 0..1."""
    try:
        rate, channels, width, raw = _read_wav(path)
        if width != 2 or not raw:
            return [0.0] * buckets
        # Interleaved int16. Peak of the loudest sample in each bucket.
        frames = len(raw) // (2 * max(1, channels))
        if frames == 0:
            return [0.0] * buckets
        bucket_frames = max(1, frames // buckets)
        peaks: List[float] = []
        for b in range(buckets):
            start = b * bucket_frames * channels * 2
            end = min(len(raw), (b + 1) * bucket_frames * channels * 2)
            chunk = raw[start:end]
            peak = 0
            for i in range(0, len(chunk) - 1, 2):
                sample = abs(struct.unpack_from("<h", chunk, i)[0])
                if sample > peak:
                    peak = sample
            peaks.append(round(peak / 32767.0, 3))
        return peaks
    except Exception:
        return [0.0] * buckets


def make_clip(
    clip_id: int,
    name: str,
    path: Optional[Path] = None,
    duration: float = 0.0,
    track_id: Optional[int] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    position: float = 0.0,
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
        "position": round(max(0.0, position), 3),
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
        "asio_index": None,
        "device_label": None,
        "sample_rate": sample_rate,
        "scarlett": None,
    }


def _samples(pcm: bytes) -> List[int]:
    return [struct.unpack_from("<h", pcm, i)[0] for i in range(0, len(pcm) - 1, 2)]


def _pack(samples: List[int]) -> bytes:
    out = bytearray()
    for s in samples:
        out += struct.pack("<h", max(-32768, min(32767, int(s))))
    return bytes(out)


def process_clip(
    path: Path,
    action: str,
    start: float = 0.0,
    end: Optional[float] = None,
    gain: float = 1.0,
    out_name: str = "",
) -> Path:
    """Rewrite a WAV for trim, reverse, or gain. Returns the new path."""
    rate, channels, width, raw = _read_wav(path)
    if width != 2:
        raise ValueError("only 16-bit WAV is supported")
    samples = _samples(raw)
    frame_size = max(1, channels)
    frames = len(samples) // frame_size

    if action == "trim":
        i0 = max(0, int(start * rate))
        i1 = frames if end is None else max(i0, int(end * rate))
        i1 = min(frames, i1)
        samples = samples[i0 * frame_size : i1 * frame_size]
    elif action == "reverse":
        frames_list = [samples[i * frame_size : (i + 1) * frame_size] for i in range(frames)]
        frames_list.reverse()
        samples = [s for frame in frames_list for s in frame]
    elif action == "gain":
        samples = [int(s * gain) for s in samples]
    elif action == "silence":
        samples = [0 for _ in samples]
    else:
        raise ValueError(f"unknown action: {action}")

    name = out_name or f"{path.stem}_{action}.wav"
    dest = UPLOAD_DIR / name
    if dest.exists():
        dest = UPLOAD_DIR / f"{path.stem}_{action}_{frames}.wav"
    return _write_wav(dest, _pack(samples), rate, channels)


def mix_arrangement(
    clips: List[Dict[str, Any]],
    tracks: List[Dict[str, Any]],
    rate: int = DEFAULT_SAMPLE_RATE,
    out_name: str = "mix.wav",
) -> Path:
    """Bounce the arrangement to a stereo WAV.

    Solo wins: if any track is solo, only solo tracks are mixed.
    Muted tracks are skipped. Clip and track gain multiply.
    Channel mode selects left, right, or both.
    Clips are placed at their timeline position.
    """
    track_by_id = {t["id"]: t for t in tracks}
    any_solo = any(t.get("solo") for t in tracks)

    # Find arrangement length.
    length = 0.0
    active: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for clip in clips:
        track = track_by_id.get(clip.get("track_id"))
        if track is None:
            continue
        if any_solo and not track.get("solo"):
            continue
        if not any_solo and track.get("mute"):
            continue
        if not clip.get("path"):
            continue
        end = float(clip.get("position", 0)) + float(clip.get("duration", 0))
        if end > length:
            length = end
        active.append((clip, track))

    if length <= 0 or not active:
        # Empty mix.
        dest = UPLOAD_DIR / out_name
        return _write_wav(dest, b"", rate, 2)

    total = int(length * rate) + 1
    left = [0.0] * total
    right = [0.0] * total

    for clip, track in active:
        try:
            c_rate, c_ch, c_w, raw = _read_wav(Path(clip["path"]))
        except Exception:
            continue
        if c_w != 2 or c_rate != rate:
            continue
        samples = _samples(raw)
        frame_size = max(1, c_ch)
        gain = float(clip.get("gain", 1.0)) * float(track.get("gain", 1.0))
        channel = track.get("channel", "stereo")
        pos = int(float(clip.get("position", 0)) * rate)
        frames = len(samples) // frame_size
        for i in range(frames):
            idx = pos + i
            if idx >= total:
                break
            base = i * frame_size
            l = samples[base] / 32767.0 * gain
            r = samples[base + 1] / 32767.0 * gain if frame_size > 1 else l
            if channel == "left":
                r = 0.0
            elif channel == "right":
                l = 0.0
            left[idx] += l
            right[idx] += r

    out = bytearray()
    for i in range(total):
        ls = int(max(-1.0, min(1.0, left[i])) * 32767)
        rs = int(max(-1.0, min(1.0, right[i])) * 32767)
        out += struct.pack("<hh", ls, rs)

    dest = UPLOAD_DIR / out_name
    if dest.exists():
        dest = UPLOAD_DIR / f"mix_{total}.wav"
    return _write_wav(dest, bytes(out), rate, 2)
