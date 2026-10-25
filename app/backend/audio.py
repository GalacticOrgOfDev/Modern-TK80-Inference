"""Audio studio helpers: tracks, clips, sample rate, Scarlett profiles.

Modern-TK80 is a Windows desktop app. Audio I/O is native ASIO
(PortAudio / Focusrite USB ASIO), not a browser media device.

Clip edits rewrite the WAV. Mixdown respects mute, solo, gain, channel,
timeline position, clip mute, and the master bus.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .formats import AUDIO_PROCESS, AUDIO_STORE, is_audio, is_processable_audio

UPLOAD_DIR = Path(os.environ.get("TK80_UPLOADS", "uploads/audio"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHANNELS = ("stereo", "left", "right")
DEFAULT_SAMPLE_RATE = 44100
COMMON_RATES = (44100, 48000, 88200, 96000, 176400, 192000)
AUDIO_FORMATS = AUDIO_STORE
PROCESSABLE = AUDIO_PROCESS

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


def default_master() -> Dict[str, Any]:
    """Return the default master bus settings."""
    return {
        "gain": 1.0,
        "mute": False,
        "compressor": {"enabled": False, "threshold": 0.5, "ratio": 4.0, "makeup": 1.0},
    }


def detect_scarlett(label: str) -> Optional[Dict[str, Any]]:
    """Detect a Focusrite Scarlett device and return its profile, or None."""
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
    """Save an uploaded audio file. Accepts WAV or MP3; returns the path."""
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


def is_supported_audio(path: Path) -> bool:
    """True if the file is a format we can store."""
    return is_audio(path)


def is_processable(path: Path) -> bool:
    """True if the file can be edited and mixed.

    WAV is native. Other stored formats are processable when ffmpeg is present.
    """
    if is_processable_audio(path):
        return path.suffix.lower() == ".wav" or shutil.which("ffmpeg") is not None
    return False


def _to_wav(path: Path) -> Path:
    """Convert a stored audio file to 16-bit WAV via ffmpeg. Returns the WAV path."""
    if path.suffix.lower() == ".wav":
        return path
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg is required to process non-WAV audio")
    dest = path.with_suffix(".wav")
    if dest.exists():
        dest = path.with_name(f"{path.stem}_conv.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-acodec", "pcm_s16le", str(dest)],
        check=True,
        capture_output=True,
    )
    return dest


def clamp_gain(value: float) -> float:
    """Keep gain in a safe 0..4 range."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(4.0, v))


def apply_fade(samples: List[int], rate: int, channels: int, fade_in: float = 0.0, fade_out: float = 0.0) -> List[int]:
    """Apply linear fade-in and fade-out in seconds. Returns new samples."""
    frame_size = max(1, channels)
    frames = len(samples) // frame_size
    in_frames = int(max(0.0, fade_in) * rate)
    out_frames = int(max(0.0, fade_out) * rate)
    out: List[int] = []
    for i in range(frames):
        gain = 1.0
        if in_frames and i < in_frames:
            gain *= i / max(1, in_frames)
        if out_frames and i > frames - out_frames:
            gain *= max(0.0, (frames - i) / max(1, out_frames))
        base = i * frame_size
        for c in range(frame_size):
            out.append(int(max(-32768, min(32767, samples[base + c] * gain))))
    return out


def _read_wav(path: Path) -> Tuple[int, int, int, bytes]:
    """read wav."""
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())


def _write_wav(path: Path, pcm: bytes, rate: int, channels: int, sampwidth: int = 2) -> Path:
    """write wav."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def wav_duration(path: Path) -> Optional[float]:
    """wav duration."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            return frames / float(rate) if rate else None
    except Exception:
        return None


def wav_peaks(path: Path, buckets: int = 64) -> List[float]:
    """wav peaks."""
    try:
        rate, channels, width, raw = _read_wav(path)
        if width != 2 or not raw:
            return [0.0] * buckets
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


def default_effects() -> Dict[str, Any]:
    """default effects."""
    return {
        "normalize": {"enabled": False, "target": 0.95},
        "compress": {"enabled": False, "threshold": 0.5, "ratio": 4.0, "makeup": 1.0},
        "morph": {"enabled": False, "points": [[0.0, 1.0], [1.0, 1.0]]},
    }


def make_clip(
    clip_id: int,
    name: str,
    path: Optional[Path] = None,
    duration: float = 0.0,
    track_id: Optional[int] = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    position: float = 0.0,
) -> Dict[str, Any]:
    """Build a clip dict from an audio file path."""
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
        "mute": False,
        "start": 0.0,
        "end": round(dur, 3),
        "position": round(max(0.0, position), 3),
        "reversed": False,
        "peaks": peaks,
        "track_id": track_id,
        "sample_rate": sample_rate,
        "effects": default_effects(),
    }


def make_track(
    track_id: int,
    name: str,
    channel: str = "stereo",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> Dict[str, Any]:
    """Build a track dict with the given name, channel, and sample rate."""
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
    """samples."""
    return [struct.unpack_from("<h", pcm, i)[0] for i in range(0, len(pcm) - 1, 2)]


def _pack(samples: List[int]) -> bytes:
    """pack."""
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
    """Apply an edit action to a clip and return the updated clip dict."""
    path = _to_wav(path)
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
    master: Optional[Dict[str, Any]] = None,
) -> Path:
    """Bounce the arrangement to a stereo WAV.

    Solo wins. Muted tracks and muted clips are skipped.
    Clip gain, track gain, and master gain multiply.
    Master compressor is applied to the sum if enabled.
    """
    master = master or default_master()
    track_by_id = {t["id"]: t for t in tracks}
    any_solo = any(t.get("solo") for t in tracks)

    length = 0.0
    active: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for clip in clips:
        if clip.get("mute"):
            continue
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

    if master.get("mute") or length <= 0 or not active:
        dest = UPLOAD_DIR / out_name
        return _write_wav(dest, b"", rate, 2)

    total = int(length * rate) + 1
    left = [0.0] * total
    right = [0.0] * total
    master_gain = float(master.get("gain", 1.0))

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
            left_s = samples[base] / 32767.0 * gain
            right_s = samples[base + 1] / 32767.0 * gain if frame_size > 1 else left_s
            if channel == "left":
                right_s = 0.0
            elif channel == "right":
                left_s = 0.0
            left[idx] += left_s
            right[idx] += right_s

    # Master gain, then optional compressor on the sum.
    comp = master.get("compressor") or {}
    use_comp = bool(comp.get("enabled"))
    thresh = float(comp.get("threshold", 0.5))
    ratio = max(1.0, float(comp.get("ratio", 4.0)))
    makeup = float(comp.get("makeup", 1.0))

    out = bytearray()
    for i in range(total):
        left_s = left[i] * master_gain
        right_s = right[i] * master_gain
        if use_comp:
            left_s = _compress_sample(left_s, thresh, ratio) * makeup
            right_s = _compress_sample(right_s, thresh, ratio) * makeup
        ls = int(max(-1.0, min(1.0, left_s)) * 32767)
        rs = int(max(-1.0, min(1.0, right_s)) * 32767)
        out += struct.pack("<hh", ls, rs)

    dest = UPLOAD_DIR / out_name
    if dest.exists():
        dest = UPLOAD_DIR / f"mix_{total}.wav"
    return _write_wav(dest, bytes(out), rate, 2)


def _compress_sample(v: float, thresh: float, ratio: float) -> float:
    """compress sample."""
    a = abs(v)
    if a <= thresh:
        return v
    over = a - thresh
    a = thresh + over / ratio
    return a if v >= 0 else -a
