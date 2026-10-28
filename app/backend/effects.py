"""Clip and master effects for the Modern-TK80 DAW.

Normalize, compressor, and a morph envelope that reshapes clip amplitude.
All operate on 16-bit PCM and return a new WAV path.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .audio import UPLOAD_DIR, _pack, _read_wav, _samples, _write_wav


def _peak(samples: List[int]) -> int:
    """peak."""
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
        amp = float(abs(s))
        if amp <= thresh:
            val = float(s)
        else:
            over = amp - thresh
            amp = thresh + over / ratio
            val = amp if s >= 0 else -amp
        val *= makeup
        out.append(int(max(-32768, min(32767, val))))
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
    """interp."""
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


EQ_BANDS = 30
EQ_LOW = 100.0
EQ_HIGH = 20000.0


def eq_frequencies() -> List[float]:
    """30 log-spaced center frequencies from 100 Hz to 20 kHz."""
    if EQ_BANDS == 1:
        return [EQ_LOW]
    ratio = (EQ_HIGH / EQ_LOW) ** (1.0 / (EQ_BANDS - 1))
    return [EQ_LOW * (ratio ** i) for i in range(EQ_BANDS)]


# Bandwidth of one band in octaves: the spacing between neighbouring centres.
EQ_OCTAVES = math.log2(EQ_HIGH / EQ_LOW) / (EQ_BANDS - 1) if EQ_BANDS > 1 else 1.0
# RBJ cookbook Q for that bandwidth, so neighbouring bands meet near their -3 dB points.
EQ_Q = math.sqrt(2.0 ** EQ_OCTAVES) / (2.0 ** EQ_OCTAVES - 1.0)
# Lowest linear gain accepted (-60 dB), the same floor the DAW page uses for dB labels.
EQ_MIN_GAIN = 0.001


def _clean_gains(gains: List[float] | None) -> List[float]:
    """Return 30 linear gains. Missing or bad values are flat (1.0); <= 0 floors to -60 dB."""
    clean: List[float] = []
    for g in list(gains or [])[:EQ_BANDS]:
        try:
            v = float(g)
        except (TypeError, ValueError):
            v = 1.0
        if not math.isfinite(v):
            v = 1.0
        clean.append(max(EQ_MIN_GAIN, v))
    while len(clean) < EQ_BANDS:
        clean.append(1.0)
    return clean


def peaking_coeffs(f0: float, gain: float, rate: int, q: float = EQ_Q) -> Tuple[float, float, float, float, float]:
    """RBJ Audio EQ Cookbook peaking filter, normalised so a0 = 1.

    gain is linear (2.0 = +6.02 dB at f0). Returns (b0, b1, b2, a1, a2).
    """
    a = math.sqrt(gain)  # A = 10 ** (dBgain / 40)
    w0 = 2.0 * math.pi * f0 / rate
    alpha = math.sin(w0) / (2.0 * q)
    cw = math.cos(w0)
    a0 = 1.0 + alpha / a
    return (
        (1.0 + alpha * a) / a0,
        (-2.0 * cw) / a0,
        (1.0 - alpha * a) / a0,
        (-2.0 * cw) / a0,
        (1.0 - alpha / a) / a0,
    )


def eq_bands_active(rate: int, gains: List[float] | None) -> List[Tuple[float, float, float, float, float]]:
    """Biquad coefficients for each band that changes the sound.

    Flat bands (gain 1.0) and bands at or above Nyquist are skipped.
    """
    out = []
    if rate <= 0:
        return out
    for f0, g in zip(eq_frequencies(), _clean_gains(gains)):
        if g == 1.0 or f0 >= rate / 2.0:
            continue
        out.append(peaking_coeffs(f0, g, rate))
    return out


def _cascade_ir(coeffs: List[Tuple[float, float, float, float, float]]) -> "Any":
    """Impulse response of the biquad cascade, long enough that the tail is below 1e-10.

    Built from the exact transfer function on a dense FFT grid. The grid is at
    least twice the decay length, so time aliasing is below 1e-20.
    """
    import numpy as np

    rmax = 0.0
    for _b0, _b1, _b2, a1, a2 in coeffs:
        rmax = max(rmax, float(np.max(np.abs(np.roots([1.0, a1, a2])))))
    if rmax >= 1.0:
        raise ValueError("EQ band is unstable")
    decay = int(math.ceil(math.log(1e-10) / math.log(rmax))) if rmax > 0 else 1
    m = 1024
    while m < 2 * decay:
        m *= 2
    z1 = np.exp(-2j * np.pi * np.arange(m // 2 + 1) / m)  # z^-1 on the grid
    z2 = z1 * z1
    h = np.ones_like(z1)
    for b0, b1, b2, a1, a2 in coeffs:
        h *= (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return np.fft.irfft(h, m)[:decay]


def _convolve(x: "Any", ir: "Any") -> "Any":
    """Causal linear convolution of x with ir, cut to len(x) (overlap-add, bounded memory)."""
    import numpy as np

    n = len(x)
    m = len(ir)
    size = 1 << 15
    while size < 2 * m:
        size *= 2
    block = size // 2  # tail of each block (m - 1 samples) fits in the next block
    nblocks = -(-n // block)
    padded = np.zeros(nblocks * block + block, dtype=np.float64)
    padded[:n] = x
    out = np.zeros_like(padded)
    spec = np.fft.rfft(ir, size)
    step = max(1, (1 << 22) // size)  # blocks per batch, about 4M samples
    for k0 in range(0, nblocks, step):
        k1 = min(nblocks, k0 + step)
        chunk = padded[k0 * block : k1 * block].reshape(k1 - k0, block)
        y = np.fft.irfft(np.fft.rfft(chunk, size, axis=1) * spec, size, axis=1)
        out[k0 * block : k1 * block] += y[:, :block].reshape(-1)
        out[(k0 + 1) * block : (k1 + 1) * block] += y[:, block:].reshape(-1)
    return out[:n]


def eq_30(
    samples: List[int],
    rate: int,
    channels: int,
    gains: List[float] | None = None,
) -> List[int]:
    """30-band EQ from 100 Hz to 20 kHz.

    gains is a list of 30 linear gains (1.0 = flat). Missing or bad values default to 1.0.
    Each band is an RBJ peaking biquad at eq_frequencies()[i] with Q = EQ_Q.
    Flat bands and bands at or above Nyquist are skipped. Channels are filtered
    independently. Output is rounded and clamped to 16-bit.
    """
    coeffs = eq_bands_active(rate, gains)
    if not coeffs or not samples:
        return list(samples)

    import numpy as np

    frame_size = max(1, channels)
    frames = len(samples) // frame_size
    data = np.asarray(samples, dtype=np.float64)
    body = data[: frames * frame_size].reshape(frames, frame_size)
    ir = _cascade_ir(coeffs)
    for c in range(frame_size):
        body[:, c] = _convolve(body[:, c], ir)
    # Any trailing partial frame is passed through unchanged.
    return np.clip(np.rint(data), -32768, 32767).astype(np.int64).tolist()


def biquad_reference(samples: List[float], coeffs: List[Tuple[float, float, float, float, float]]) -> List[float]:
    """Direct-form I biquad cascade, one sample at a time. Slow; used by tests to check eq_30."""
    out = [float(s) for s in samples]
    for b0, b1, b2, a1, a2 in coeffs:
        x1 = x2 = y1 = y2 = 0.0
        for i, x0 in enumerate(out):
            y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, x0, y1, y0
            out[i] = y0
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
        raw_gains = params.get("gains") or params.get("bands") or [1.0] * EQ_BANDS
        if not isinstance(raw_gains, list):
            raw_gains = [1.0] * EQ_BANDS
        samples = eq_30(samples, rate, channels, raw_gains)  # eq_30 cleans bad values
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
