"""Clip and master effects for the Modern-TK80 DAW.

Normalize, compressor, and a morph envelope that reshapes clip amplitude.
All operate on 16-bit PCM and return a new WAV path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from .audio import UPLOAD_DIR, _pack, _read_wav, _samples, _write_wav


def _peak(samples: List[int]) -> int:
    peak = 0
    for s in samples:
        a = abs(s)
        if a > peak:
            peak = a
    return peak


def normalize(samples: List[int], target: float = 0.95) -> List[int]:
    """Scale so the peak reaches target (0..1)."""
    peak = _peak(samples)
    if peak == 0:
        return samples
    scale = (target * 32767.0) / peak
    return [int(max(-32768, min(32767, s * scale))) for s in samples]


def compress(
    samples: List[int],
    threshold: float = 0.5,
    ratio: float = 4.0,
    makeup: float = 1.0,
) -> List[int]:
    """Simple peak compressor. threshold and ratio are linear.

    Samples above threshold are reduced by ratio. makeup is applied after.
    """
    thresh = max(0.0, min(1.0, threshold)) * 32767.0
    ratio = max(1.0, ratio)
    out: List[int] = []
    for s in samples:
        a = abs(s)
        if a <= thresh:
            v = s
        else:
            over = a - thresh
            a = thresh + over / ratio
            v = a if s >= 0 else -a
        v *= makeup
        out.append(int(max(-32768, min(32767, v))))
    return out


def morph(samples: List[int], points: List[Tuple[float, float]], channels: int) -> List[int]:
    """Reshape amplitude with an envelope of (t, gain) points.

    t is 0..1 across the clip. gain is linear. Points are sorted by t.
    """
    if not points:
        return samples
    pts = sorted(points, key=lambda p: p[0])
    if pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1]))
    if pts[-1][0] < 1:
        pts.append((1.0, pts[-1][1]))

    frame_size = max(1, channels)
    frames = len(samples) // frame_size
    out: List[int] = []
    for i in range(frames):
        t = i / max(1, frames - 1)
        gain = _interp(pts, t)
        base = i * frame_size
        for c in range(frame_size):
            v = samples[base + c] * gain
            out.append(int(max(-32768, min(32767, v))))
    return out


def _interp(points: List[Tuple[float, float]], t: float) -> float:
    for i in range(len(points) - 1):
        t0, g0 = points[i]
        t1, g1 = points[i + 1]
        if t0 <= t <= t1:
            if t1 == t0:
                return g1
            u = (t - t0) / (t1 - t0)
            return g0 + (g1 - g0) * u
    return points[-1][1]


def delay(
    samples: List[int],
    rate: int,
    channels: int,
    time: float = 0.25,
    feedback: float = 0.4,
    mix: float = 0.5,
) -> List[int]:
    """Simple delay. time in seconds, feedback and mix are 0..1."""
    frame_size = max(1, channels)
    delay_frames = max(1, int(time * rate))
    buf = [0] * (delay_frames * frame_size)
    out: List[int] = []
    for i in range(0, len(samples), frame_size):
        frame = samples[i : i + frame_size]
        delayed = buf[:frame_size]
        new_frame = []
        for c in range(frame_size):
            dry = frame[c] if c < len(frame) else 0
            wet = delayed[c] if c < len(delayed) else 0
            mixed = int(dry * (1 - mix) + wet * mix)
            new_frame.append(max(-32768, min(32767, mixed)))
            buf.append(int(dry + wet * feedback))
        buf = buf[frame_size:]
        out.extend(new_frame)
    return out


def eq_simple(samples: List[int], low: float = 1.0, mid: float = 1.0, high: float = 1.0) -> List[int]:
    """Very simple three-band gain. Not a real filter; scales by band estimate."""
    out: List[int] = []
    for s in samples:
        a = abs(s)
        if a < 8000:
            g = low
        elif a < 20000:
            g = mid
        else:
            g = high
        out.append(int(max(-32768, min(32767, s * g))))
    return out


def reverb_simple(samples: List[int], rate: int, channels: int, room: float = 0.4, mix: float = 0.3) -> List[int]:
    """Short comb-style reverb stub."""
    frame_size = max(1, channels)
    delay = max(1, int(0.03 * rate))
    buf = [0] * (delay * frame_size)
    out: List[int] = []
    for i in range(0, len(samples), frame_size):
        frame = samples[i : i + frame_size]
        wet = buf[:frame_size]
        new_frame = []
        for c in range(frame_size):
            dry = frame[c] if c < len(frame) else 0
            w = wet[c] if c < len(wet) else 0
            mixed = int(dry * (1 - mix) + w * mix * room)
            new_frame.append(max(-32768, min(32767, mixed)))
            buf.append(int(dry * 0.5 + w * 0.5))
        buf = buf[frame_size:]
        out.extend(new_frame)
    return out


def apply_effect(
    path: Path,
    kind: str,
    params: Dict[str, Any] | None = None,
    out_name: str = "",
) -> Path:
    """Apply normalize, compress, or morph and write a new WAV."""
    params = params or {}
    rate, channels, width, raw = _read_wav(path)
    if width != 2:
        raise ValueError("only 16-bit WAV is supported")
    samples = _samples(raw)

    if kind == "normalize":
        samples = normalize(samples, float(params.get("target", 0.95)))
    elif kind == "compress":
        samples = compress(
            samples,
            threshold=float(params.get("threshold", 0.5)),
            ratio=float(params.get("ratio", 4.0)),
            makeup=float(params.get("makeup", 1.0)),
        )
    elif kind == "morph":
        raw_pts = params.get("points") or [(0.0, 1.0), (1.0, 1.0)]
        points = [(float(p[0]), float(p[1])) for p in raw_pts]
        samples = morph(samples, points, channels)
    elif kind == "delay":
        samples = delay(
            samples,
            rate,
            channels,
            time=float(params.get("time", 0.25)),
            feedback=float(params.get("feedback", 0.4)),
            mix=float(params.get("mix", 0.5)),
        )
    elif kind == "eq":
        samples = eq_simple(
            samples,
            low=float(params.get("low", 1.0)),
            mid=float(params.get("mid", 1.0)),
            high=float(params.get("high", 1.0)),
        )
    elif kind == "reverb":
        samples = reverb_simple(
            samples,
            rate,
            channels,
            room=float(params.get("room", 0.4)),
            mix=float(params.get("mix", 0.3)),
        )
    else:
        raise ValueError(f"unknown effect: {kind}")

    name = out_name or f"{path.stem}_{kind}.wav"
    dest = UPLOAD_DIR / name
    if dest.exists():
        dest = UPLOAD_DIR / f"{path.stem}_{kind}_{len(samples)}.wav"
    return _write_wav(dest, _pack(samples), rate, channels)
