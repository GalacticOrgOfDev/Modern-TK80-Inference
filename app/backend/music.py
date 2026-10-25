"""Music tools for the Modern-TK80 Windows app.

BPM, step sequencer, instrument generator, and loop/sample generation.
Generation is local and deterministic so the model can call it without
a heavy model load. Output is 16-bit WAV at the studio rate.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any, Dict, List

from .audio import DEFAULT_SAMPLE_RATE, UPLOAD_DIR

DEFAULT_BPM = 120
STEPS = 16
INSTRUMENTS = ("kick", "snare", "hat", "bass", "lead", "pad")


def _sine(freq: float, i: int, rate: int) -> float:
    """sine."""
    return math.sin(2.0 * math.pi * freq * i / rate)


def _env(i: int, n: int, attack: float = 0.01, release: float = 0.2) -> float:
    """env."""
    t = i / float(n)
    if t < attack:
        return t / attack
    if t > 1.0 - release:
        return max(0.0, (1.0 - t) / release)
    return 1.0


def render_instrument(
    name: str,
    duration: float,
    rate: int = DEFAULT_SAMPLE_RATE,
    note: int = 60,
) -> bytes:
    """Render a short instrument hit or tone to 16-bit mono PCM."""
    n = max(1, int(duration * rate))
    freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
    out = bytearray()
    for i in range(n):
        e = _env(i, n)
        if name == "kick":
            f = 80.0 * (1.0 - i / n) + 40.0
            s = _sine(f, i, rate) * e
        elif name == "snare":
            noise = ((i * 1103515245 + 12345) & 0x7FFFFFFF) / 0x7FFFFFFF * 2.0 - 1.0
            s = (noise * 0.6 + _sine(180.0, i, rate) * 0.4) * e
        elif name == "hat":
            noise = ((i * 1664525 + 1013904223) & 0x7FFFFFFF) / 0x7FFFFFFF * 2.0 - 1.0
            s = noise * _env(i, n, 0.001, 0.05)
        elif name == "bass":
            s = (_sine(freq / 2.0, i, rate) + 0.3 * _sine(freq, i, rate)) * e
        elif name == "lead":
            s = (_sine(freq, i, rate) + 0.2 * _sine(freq * 2.0, i, rate)) * e
        else:  # pad
            s = (_sine(freq, i, rate) + 0.5 * _sine(freq * 1.5, i, rate)) * e * 0.6
        sample = int(max(-1.0, min(1.0, s)) * 32767)
        out += struct.pack("<h", sample)
    return bytes(out)


def write_wav(path: Path, pcm: bytes, rate: int, channels: int = 1) -> Path:
    """write wav."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


def detect_bpm(path: Path) -> Dict[str, Any]:
    """Estimate BPM from onset energy peaks. Returns bpm and confidence."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            raw = w.readframes(w.getnframes())
    except Exception as e:
        return {"bpm": DEFAULT_BPM, "confidence": 0.0, "error": str(e)}

    if len(raw) < 4:
        return {"bpm": DEFAULT_BPM, "confidence": 0.0}

    window = max(1, rate // 100)
    energies: List[float] = []
    for i in range(0, len(raw) - 1, window * 2):
        chunk = raw[i : i + window * 2]
        if len(chunk) < 2:
            break
        total = 0
        for j in range(0, len(chunk) - 1, 2):
            total += abs(struct.unpack_from("<h", chunk, j)[0])
        energies.append(total / max(1, len(chunk) // 2))

    if len(energies) < 8:
        return {"bpm": DEFAULT_BPM, "confidence": 0.0}

    avg = sum(energies) / len(energies)
    peaks = [i for i, e in enumerate(energies) if e > avg * 1.4]
    if len(peaks) < 2:
        return {"bpm": DEFAULT_BPM, "confidence": 0.1}

    gaps = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
    gaps = [g for g in gaps if 2 <= g <= 200]
    if not gaps:
        return {"bpm": DEFAULT_BPM, "confidence": 0.1}

    median = sorted(gaps)[len(gaps) // 2]
    bpm = 60.0 * 100.0 / max(1, median)
    bpm = max(40.0, min(220.0, bpm))
    confidence = min(1.0, len(gaps) / 16.0)
    return {"bpm": round(bpm, 1), "confidence": round(confidence, 2)}


def make_pattern(steps: int = STEPS) -> Dict[str, List[int]]:
    """Return a default step-sequencer pattern."""
    return {name: [0] * steps for name in INSTRUMENTS}


def render_pattern(
    pattern: Dict[str, List[int]],
    bpm: float,
    rate: int = DEFAULT_SAMPLE_RATE,
    bars: int = 1,
) -> bytes:
    """Render a step pattern to mono PCM."""
    if not pattern:
        return b""
    steps = max((len(v) for v in pattern.values()), default=STEPS)
    if steps < 1:
        steps = STEPS
    step_samples = max(1, int(rate * 60.0 / max(1.0, bpm) / 4.0))
    total = step_samples * steps * max(1, bars)
    mix: List[float] = [0.0] * total

    for name, steps_on in pattern.items():
        if name not in INSTRUMENTS:
            continue
        hit = render_instrument(name, 0.2, rate)
        hit_n = len(hit) // 2
        for bar in range(max(1, bars)):
            for s, on in enumerate(steps_on):
                if not on:
                    continue
                start = (bar * steps + s) * step_samples
                for i in range(hit_n):
                    if start + i >= total:
                        break
                    mix[start + i] += float(struct.unpack_from("<h", hit, i * 2)[0]) / 32767.0

    out = bytearray()
    for sample_f in mix:
        sample = int(max(-1.0, min(1.0, sample_f * 0.4)) * 32767)
        out += struct.pack("<h", sample)
    return bytes(out)


def generate_loop(
    bpm: float,
    bars: int = 1,
    rate: int = DEFAULT_SAMPLE_RATE,
    style: str = "basic",
) -> bytes:
    """Generate a short loop. style picks a preset pattern."""
    pattern = make_pattern()
    if style == "basic":
        pattern["kick"] = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
        pattern["snare"] = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
        pattern["hat"] = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    elif style == "syncopated":
        pattern["kick"] = [1, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        pattern["snare"] = [0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0]
        pattern["hat"] = [1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1]
    else:
        pattern["bass"] = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
        pattern["pad"] = [1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
    return render_pattern(pattern, bpm, rate, bars)


def save_pcm(name: str, pcm: bytes, rate: int) -> Path:
    """Write PCM to a WAV file and return its path."""
    path = UPLOAD_DIR / name
    return write_wav(path, pcm, rate)
