#!/usr/bin/env python3
"""Scarlett / ASIO hardware check for Modern-TK80.

Run on the Windows PC with the interface plugged in. It uses the same
audio library as app/backend/asio.py (sounddevice, i.e. PortAudio) and the
standard library only; numpy is not needed.

It lists host APIs and devices, tries sample rate x buffer size
combinations on one device, records at 16-, 24- and 32-bit, plays a test
tone, and (only with --loopback and a cable) checks that the tone comes
back on an input. It writes a Markdown report with PASS / FAIL / SKIPPED
per step and the raw exception text. The report holds only values the
library returned or that were measured from captured samples.

    python scripts/scarlett_check.py --list-only
    python scripts/scarlett_check.py
    python scripts/scarlett_check.py --device 12 --loopback --loop-out 1 --loop-in 1

See scripts/README.md for the options.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import platform
import struct
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"
DEFAULT_RATES = (44100, 48000, 88200, 96000)
DEFAULT_BUFFERS = (64, 128, 256, 512, 1024)
# (sounddevice dtype, bits, bytes per sample)
DEPTHS = (("int16", 16, 2), ("int24", 24, 3), ("int32", 32, 4))
WIDTH = {"int16": 2, "int24": 3, "int32": 4, "float32": 4}
TONE_HZ = 1000.0
TONE_AMPLITUDE = 0.1  # of full scale, -20 dBFS
# Detection rule for the loopback (script settings, not measurements):
# the 1 kHz component must be at least DETECT_MIN_DBFS and carry at least
# DETECT_MIN_FRACTION of the captured signal power.
DETECT_MIN_DBFS = -50.0
DETECT_MIN_FRACTION = 0.5
SKIP_LEAD_SECONDS = 0.2  # ignore the start of a loopback capture (latency)

REPO = Path(__file__).resolve().parents[1]

LOOPBACK_HELP = (
    "Loopback needs a physical cable from an output of the interface to one "
    "of its inputs (for example line out 1 to input 1). With no cable the "
    "tone cannot come back, so this step is skipped unless you pass "
    "--loopback. If you have no cable, leave it off: the record and play "
    "steps still run. With a cable, turn the input gain down first and pass "
    "--loopback --loop-out N --loop-in M (channel numbers start at 1)."
)


# ---------------------------------------------------------------- report


@dataclass
class Step:
    name: str
    status: str
    detail: str = ""
    error: str = ""


@dataclass
class Report:
    started: str = ""
    environment: Dict[str, str] = field(default_factory=dict)
    steps: List[Step] = field(default_factory=list)
    hostapis: List[Dict[str, Any]] = field(default_factory=list)
    devices: List[Dict[str, Any]] = field(default_factory=list)
    chosen: Optional[Dict[str, Any]] = None
    matrix: List[Dict[str, Any]] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", error: str = "") -> Step:
        step = Step(name, status, detail, error)
        self.steps.append(step)
        return step

    @property
    def failed(self) -> bool:
        return any(s.status == FAIL for s in self.steps)


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> List[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for r in rows:
        out.append("| " + " | ".join(_cell(v) for v in r) + " |")
    return out


def fmt_db(value: Optional[float]) -> str:
    return "-inf dBFS" if value is None else f"{value:.1f} dBFS"


def fmt_ms(seconds: Optional[float]) -> str:
    return "" if seconds is None else f"{seconds * 1000.0:.2f} ms"


def render_report(rep: Report) -> str:
    """Markdown for the report. Only fields that were filled in are shown."""
    lines = ["# Modern-TK80 Scarlett hardware check", ""]
    lines.append(f"Run at {rep.started}.")
    lines.append("")
    lines.append(
        "Every value below was returned by the audio library or measured from "
        "captured samples on this run. Nothing is filled in from a spec sheet. "
        "A SKIPPED step says why it did not run."
    )
    lines.append("")
    if rep.environment:
        lines += ["## Environment", ""]
        lines += [f"- {k}: {v}" for k, v in rep.environment.items()]
        lines.append("")
    lines += ["## Steps", ""]
    lines += _table(["Step", "Result", "Detail"], [(s.name, s.status, s.detail) for s in rep.steps])
    lines.append("")
    if rep.hostapis:
        lines += ["## Host APIs", ""]
        lines += _table(
            ["Index", "Name", "Devices", "ASIO"],
            [(h["index"], h["name"], h["device_count"], "yes" if h["asio"] else "") for h in rep.hostapis],
        )
        lines.append("")
    if rep.devices:
        lines += ["## Devices", ""]
        lines += _table(
            ["Index", "Name", "Host API", "Inputs", "Outputs", "Default rate", "ASIO", "Scarlett/Focusrite"],
            [
                (
                    d["index"], d["name"], d["host"], d["inputs"], d["outputs"], d["default_rate"],
                    "yes" if d["asio"] else "", "yes" if d["scarlett"] else "",
                )
                for d in rep.devices
            ],
        )
        lines.append("")
    if rep.chosen:
        c = rep.chosen
        lines += ["## Device under test", "", f"#{c['index']} {c['name']} ({c['host']})", ""]
    if rep.matrix:
        lines += ["## Sample rate x buffer size", ""]
        lines.append(
            "Accepted means the library opened and closed a stream with these "
            "settings. Reported latency and block size are what the opened "
            "stream returned; a driver may use its own buffer size."
        )
        lines.append("")
        lines += _table(
            ["Rate", "Buffer", "Input", "Input latency", "Output", "Output latency"],
            [
                (
                    m["rate"], m["buffer"], m["input"]["status"], fmt_ms(m["input"].get("latency")),
                    m["output"]["status"], fmt_ms(m["output"].get("latency")),
                )
                for m in rep.matrix
            ],
        )
        errs = [
            (m["rate"], m["buffer"], side, m[side]["error"])
            for m in rep.matrix
            for side in ("input", "output")
            if m[side].get("error")
        ]
        if errs:
            lines += ["", "Errors:", ""]
            lines += _table(["Rate", "Buffer", "Side", "Exception"], errs)
        lines.append("")
    if rep.records:
        lines += ["## Recordings", ""]
        for r in rep.records:
            lines.append(f"### {r['label']}")
            lines.append("")
            for k, v in r.items():
                if k != "label":
                    lines.append(f"- {k}: {v}")
            lines.append("")
    errors = [s for s in rep.steps if s.error]
    if errors:
        lines += ["## Raw exception text", ""]
        for s in errors:
            lines += [f"### {s.name}", "", "```", s.error, "```", ""]
    if rep.notes:
        lines += ["## Notes", ""]
        lines += [f"- {n}" for n in rep.notes]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- samples


def encode(frames: Sequence[Sequence[float]], dtype: str) -> bytes:
    """Interleaved frames of floats in -1..1 to raw bytes (round to nearest)."""
    out = bytearray()
    for frame in frames:
        for x in frame:
            x = max(-1.0, min(1.0, float(x)))
            if dtype == "int16":
                out += struct.pack("<h", max(-32768, min(32767, round(x * 32767))))
            elif dtype == "int24":
                v = max(-8388608, min(8388607, round(x * 8388607)))
                out += struct.pack("<i", v)[:3]
            elif dtype == "int32":
                out += struct.pack("<i", max(-2147483648, min(2147483647, round(x * 2147483647))))
            elif dtype == "float32":
                out += struct.pack("<f", x)
            else:
                raise ValueError(f"unknown dtype {dtype}")
    return bytes(out)


def decode_ints(raw: bytes, dtype: str) -> List[int]:
    """Raw little-endian samples to ints (int dtypes only)."""
    w = WIDTH[dtype]
    n = len(raw) // w
    if dtype == "int16":
        return list(struct.unpack(f"<{n}h", raw[: n * 2]))
    if dtype == "int32":
        return list(struct.unpack(f"<{n}i", raw[: n * 4]))
    if dtype == "int24":
        out = []
        for i in range(0, n * 3, 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            out.append(v - (1 << 24) if v & 0x800000 else v)
        return out
    raise ValueError(f"not an integer dtype: {dtype}")


def decode(raw: bytes, dtype: str, channels: int) -> List[List[float]]:
    """Raw bytes to one list of floats (-1..1) per channel."""
    if dtype == "float32":
        n = len(raw) // 4
        flat = list(struct.unpack(f"<{n}f", raw[: n * 4]))
    else:
        full = {"int16": 32768.0, "int24": 8388608.0, "int32": 2147483648.0}[dtype]
        flat = [v / full for v in decode_ints(raw, dtype)]
    channels = max(1, channels)
    return [flat[c::channels] for c in range(channels)]


def to_db(amplitude: float) -> Optional[float]:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else None


def tone_frames(rate: int, seconds: float, channels: int, on: Sequence[int],
                freq: float = TONE_HZ, amplitude: float = TONE_AMPLITUDE) -> List[List[float]]:
    """A sine on the 0-based channels in `on`, silence on the others."""
    n = int(round(rate * seconds))
    w = 2.0 * math.pi * freq / rate
    frames = []
    for i in range(n):
        s = amplitude * math.sin(w * i)
        frames.append([s if c in on else 0.0 for c in range(channels)])
    return frames


def detect_tone(samples: Sequence[float], rate: int, freq: float = TONE_HZ,
                min_dbfs: float = DETECT_MIN_DBFS, min_fraction: float = DETECT_MIN_FRACTION) -> Dict[str, Any]:
    """Measure a sine at `freq` in `samples` (floats, full scale 1.0).

    Goertzel at the exact frequency gives the sine amplitude; the power
    fraction is that sine's power over the total mean-square power.
    detected is True when the level and the fraction both reach the
    thresholds. onset_frame is the first sample whose magnitude reaches
    half the measured amplitude (None if there is none).
    """
    n = len(samples)
    if n == 0:
        return {"frames": 0, "level_dbfs": None, "rms_dbfs": None, "fraction": 0.0, "detected": False, "onset_frame": None}
    w = 2.0 * math.pi * freq / rate
    coeff = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    total = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
        total += x * x
    power = max(0.0, s1 * s1 + s2 * s2 - coeff * s1 * s2)
    amplitude = 2.0 * math.sqrt(power) / n
    ms = total / n
    fraction = min(1.0, (amplitude * amplitude / 2.0) / ms) if ms > 0 else 0.0
    level = to_db(amplitude)
    detected = level is not None and level >= min_dbfs and fraction >= min_fraction
    onset = None
    if amplitude > 0:
        half = amplitude / 2.0
        onset = next((i for i, x in enumerate(samples) if abs(x) >= half), None)
    return {
        "frames": n,
        "level_dbfs": level,
        "rms_dbfs": to_db(math.sqrt(ms)),
        "fraction": fraction,
        "detected": detected,
        "onset_frame": onset,
    }


# ---------------------------------------------------------------- library


def load_sounddevice(enable_asio: bool = True) -> Tuple[Any, Optional[str]]:
    """Import sounddevice. With enable_asio, set SD_ENABLE_ASIO first.

    pip's Windows wheels of sounddevice carry two PortAudio DLLs and load the
    one without ASIO unless SD_ENABLE_ASIO is set before the import (per the
    sounddevice installation docs). The report states which was requested.
    """
    if enable_asio:
        os.environ.setdefault("SD_ENABLE_ASIO", "1")
    try:
        import sounddevice as sd  # type: ignore

        return sd, None
    except Exception as e:  # ImportError, OSError (PortAudio missing), ...
        return None, f"{type(e).__name__}: {e}"


def _is_asio(host_name: str) -> bool:
    return "asio" in host_name.lower()


def _is_scarlett(name: str) -> bool:
    n = name.lower()
    return "scarlett" in n or "focusrite" in n


def list_hostapis(sd) -> List[Dict[str, Any]]:
    out = []
    for i, h in enumerate(sd.query_hostapis()):
        name = str(h.get("name", ""))
        out.append({"index": i, "name": name, "device_count": len(h.get("devices", []) or []), "asio": _is_asio(name)})
    return out


def list_devices(sd) -> List[Dict[str, Any]]:
    hosts = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        hi = d.get("hostapi")
        host = str(hosts[hi].get("name", "")) if isinstance(hi, int) and 0 <= hi < len(hosts) else ""
        name = str(d.get("name", ""))
        out.append({
            "index": i,
            "name": name,
            "host": host,
            "inputs": int(d.get("max_input_channels", 0)),
            "outputs": int(d.get("max_output_channels", 0)),
            "default_rate": d.get("default_samplerate"),
            "asio": _is_asio(host),
            "scarlett": _is_scarlett(name),
        })
    return out


def pick_device(devices: List[Dict[str, Any]], selector: Optional[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Default: first ASIO device with Scarlett/Focusrite in the name.

    selector may be a device index or a case-insensitive name substring
    (an ASIO match wins over others).
    """
    if selector is None or selector == "":
        for d in devices:
            if d["asio"] and d["scarlett"]:
                return d, "first ASIO device named Scarlett/Focusrite"
        return None, (
            "no ASIO device with Scarlett or Focusrite in its name was found; "
            "pass --device INDEX to test another device"
        )
    if str(selector).strip().lstrip("-").isdigit():
        idx = int(selector)
        for d in devices:
            if d["index"] == idx:
                return d, f"--device {idx}"
        return None, f"no device with index {idx}"
    sub = str(selector).lower()
    matches = [d for d in devices if sub in d["name"].lower()]
    if not matches:
        return None, f"no device name contains {selector!r}"
    matches.sort(key=lambda d: not d["asio"])
    return matches[0], f"--device {selector!r}"


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


def try_open(sd, kind: str, device: int, channels: int, rate: int, buffer: int, dtype: str = "int16") -> Dict[str, Any]:
    """Open and close one stream; never starts audio."""
    if channels < 1:
        return {"status": SKIPPED, "error": "", "reason": f"device has no {kind}s"}
    cls = sd.RawInputStream if kind == "input" else sd.RawOutputStream
    try:
        stream = cls(device=device, channels=channels, samplerate=rate, blocksize=buffer, dtype=dtype)
    except Exception as e:
        return {"status": FAIL, "error": _err(e)}
    info: Dict[str, Any] = {"status": PASS, "error": ""}
    try:
        info["latency"] = getattr(stream, "latency", None)
        info["blocksize"] = getattr(stream, "blocksize", None)
        info["samplerate"] = getattr(stream, "samplerate", None)
    finally:
        try:
            stream.close()
        except Exception as e:
            info["status"] = FAIL
            info["error"] = "close failed: " + _err(e)
    return info


def probe_matrix(sd, device: Dict[str, Any], rates: Sequence[int], buffers: Sequence[int],
                 opener: Callable[..., Dict[str, Any]] = try_open) -> List[Dict[str, Any]]:
    """Every rate x buffer pair, input and output, in that order."""
    in_ch = min(2, device["inputs"])
    out_ch = min(2, device["outputs"])
    rows = []
    for rate in rates:
        for buf in buffers:
            rows.append({
                "rate": rate,
                "buffer": buf,
                "input": opener(sd, "input", device["index"], in_ch, rate, buf),
                "output": opener(sd, "output", device["index"], out_ch, rate, buf),
            })
    return rows


def matrix_summary(rows: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(status, detail) for the matrix step."""
    tried = [(r, s) for r in rows for s in ("input", "output") if r[s]["status"] != SKIPPED]
    if not tried:
        return SKIPPED, "device has neither inputs nor outputs"
    ok = sum(1 for r, s in tried if r[s]["status"] == PASS)
    status = PASS if ok == len(tried) else FAIL
    return status, f"{ok} of {len(tried)} stream opens accepted"


def run_stream(sd, kind: str, device: int, channels: Any, rate: int, buffer: int, dtype: str,
               frames: int, play: bytes = b"", timeout: Optional[float] = None) -> Dict[str, Any]:
    """Run one callback stream until `frames` frames are captured (input,
    duplex) or `play` is consumed (output). Returns captured bytes, the
    status flags PortAudio reported, and the stream's reported latency."""
    width = WIDTH[dtype]
    in_ch, out_ch = channels if kind == "duplex" else (channels, channels)
    want = frames * width * in_ch
    captured = bytearray()
    statuses: List[str] = []
    pos = [0]
    block = {}
    done = threading.Event()

    def take(indata, n) -> None:
        if "bytes" not in block and n:
            block["bytes"], block["frames"] = len(bytes(indata)), n
        need = want - len(captured)
        if need > 0:
            captured.extend(bytes(indata)[:need])

    def feed(outdata) -> None:
        n = len(outdata)
        chunk = play[pos[0]: pos[0] + n]
        if len(chunk) < n:
            chunk = chunk + b"\x00" * (n - len(chunk))
        outdata[:] = chunk
        pos[0] += n

    def note(status) -> None:
        if status:
            statuses.append(str(status))

    if kind == "input":
        def cb(indata, n, t, status):  # noqa: ARG001
            note(status)
            take(indata, n)
            if len(captured) >= want:
                done.set()
                raise sd.CallbackStop
        cls, kw = sd.RawInputStream, {"channels": in_ch}
    elif kind == "output":
        def cb(outdata, n, t, status):  # noqa: ARG001
            note(status)
            feed(outdata)
            if pos[0] >= len(play):
                done.set()
                raise sd.CallbackStop
        cls, kw = sd.RawOutputStream, {"channels": out_ch}
    else:
        def cb(indata, outdata, n, t, status):  # noqa: ARG001
            note(status)
            take(indata, n)
            feed(outdata)
            if len(captured) >= want:
                done.set()
                raise sd.CallbackStop
        cls, kw = sd.RawStream, {"channels": (in_ch, out_ch)}

    limit = timeout if timeout is not None else frames / float(rate) + 5.0
    stream = cls(device=device, samplerate=rate, blocksize=buffer, dtype=dtype, callback=cb, **kw)
    try:
        latency = getattr(stream, "latency", None)
        stream.start()
        finished = done.wait(limit)
    finally:
        try:
            stream.stop()
        finally:
            stream.close()
    return {
        "captured": bytes(captured),
        "frames": len(captured) // (width * in_ch) if in_ch else 0,
        "played_bytes": min(pos[0], len(play)),
        "statuses": statuses,
        "latency": latency,
        "timed_out": not finished,
        # Size of the first input block the library handed over, as measured.
        "first_block": (block["bytes"], block["frames"]) if block else None,
    }


def low_byte_nonzero(raw: bytes, dtype: str) -> Tuple[int, int]:
    """(samples whose lowest byte is nonzero, samples). For int24/int32 this
    shows whether the captured words carry bits below the top 16 (int24) or
    top 24 (int32)."""
    w = WIDTH[dtype]
    n = len(raw) // w
    return sum(1 for i in range(0, n * w, w) if raw[i] != 0), n


# ---------------------------------------------------------------- steps


def _record_step(rep: Report, sd, dev: Dict[str, Any], rate: int, buffer: int, seconds: float,
                 dtype: str, bits: int) -> None:
    name = f"Record {bits}-bit ({dtype})"
    ch = min(2, dev["inputs"])
    if ch < 1:
        rep.add(name, SKIPPED, "device has no inputs")
        return
    frames = int(round(rate * seconds))
    try:
        res = run_stream(sd, "input", dev["index"], ch, rate, buffer, dtype, frames)
    except Exception as e:
        rep.add(name, FAIL, f"stream at {rate} Hz / {buffer} did not run", _err(e))
        return
    raw = res["captured"]
    per_ch = decode(raw, dtype, ch)
    peaks = [to_db(max((abs(x) for x in c), default=0.0)) for c in per_ch]
    nz, total = low_byte_nonzero(raw, dtype)
    info = {
        "label": name,
        "rate / buffer / channels": f"{rate} Hz / {buffer} / {ch}",
        "frames requested": frames,
        "frames received": res["frames"],
        "bytes per sample received": (
            res["first_block"][0] / float(res["first_block"][1] * ch) if res["first_block"] else "n/a"
        ),
        "first block size from the library (frames)": res["first_block"][1] if res["first_block"] else "n/a",
        "peak per channel": ", ".join(fmt_db(p) for p in peaks),
        "samples with nonzero lowest byte": f"{nz} of {total}",
        "status flags from the library": "; ".join(res["statuses"]) or "none",
        "timed out": res["timed_out"],
    }
    rep.records.append(info)
    ok = res["frames"] == frames and not res["timed_out"]
    rep.add(name, PASS if ok else FAIL, f"{res['frames']} of {frames} frames received")


def _play_step(rep: Report, sd, dev: Dict[str, Any], rate: int, buffer: int, seconds: float) -> None:
    name = "Play test tone"
    ch = min(2, dev["outputs"])
    if ch < 1:
        rep.add(name, SKIPPED, "device has no outputs")
        return
    data = encode(tone_frames(rate, seconds, ch, range(ch)), "int16")
    try:
        res = run_stream(sd, "output", dev["index"], ch, rate, buffer, "int16", 0, play=data)
    except Exception as e:
        rep.add(name, FAIL, f"stream at {rate} Hz / {buffer} did not run", _err(e))
        return
    rep.records.append({
        "label": name,
        "signal": f"{TONE_HZ:.0f} Hz sine at {fmt_db(to_db(TONE_AMPLITUDE))} on outputs 1-{ch}",
        "bytes written / bytes in tone": f"{res['played_bytes']} / {len(data)}",
        "status flags from the library": "; ".join(res["statuses"]) or "none",
        "timed out": res["timed_out"],
        "audible": "not measured; this script cannot hear the speakers",
    })
    ok = res["played_bytes"] == len(data) and not res["timed_out"]
    rep.add(name, PASS if ok else FAIL, "stream consumed the whole tone" if ok else "stream did not consume the whole tone")


def _loopback_step(rep: Report, sd, dev: Dict[str, Any], rate: int, buffer: int, seconds: float,
                   enabled: bool, loop_out: int, loop_in: int) -> None:
    name = "Loopback tone"
    if not enabled:
        rep.add(name, SKIPPED, "not requested (--loopback); needs a physical cable from an output to an input")
        rep.notes.append(LOOPBACK_HELP)
        return
    if loop_out < 1 or loop_out > dev["outputs"] or loop_in < 1 or loop_in > dev["inputs"]:
        rep.add(name, SKIPPED, f"--loop-out {loop_out} / --loop-in {loop_in} outside the device's "
                f"{dev['outputs']} outputs / {dev['inputs']} inputs")
        return
    frames = int(round(rate * seconds))
    play = encode(tone_frames(rate, seconds, loop_out, [loop_out - 1]), "int16")
    try:
        res = run_stream(sd, "duplex", dev["index"], (loop_in, loop_out), rate, buffer, "int16", frames, play=play)
    except Exception as e:
        rep.add(name, FAIL, "duplex stream did not run", _err(e))
        return
    chan = decode(res["captured"], "int16", loop_in)[loop_in - 1]
    skip = min(len(chan), int(round(rate * SKIP_LEAD_SECONDS)))
    found = detect_tone(chan[skip:], rate)
    onset = detect_tone(chan, rate)["onset_frame"] if found["detected"] else None
    rep.records.append({
        "label": name,
        "path": f"output {loop_out} -> input {loop_in}, {rate} Hz / {buffer}",
        "frames captured": f"{res['frames']} of {frames}",
        "1 kHz level (after the first %.1f s)" % SKIP_LEAD_SECONDS: fmt_db(found["level_dbfs"]),
        "total level (RMS)": fmt_db(found["rms_dbfs"]),
        "share of power at 1 kHz": f"{found['fraction'] * 100:.1f}%",
        "detection rule": f"1 kHz level >= {DETECT_MIN_DBFS:.0f} dBFS and share >= {DETECT_MIN_FRACTION * 100:.0f}%",
        "first frame at half the tone level": (
            f"{onset} ({onset * 1000.0 / rate:.1f} ms after the stream started; includes output and input "
            "buffering, approximate)" if onset is not None else "n/a"
        ),
        "status flags from the library": "; ".join(res["statuses"]) or "none",
    })
    if found["detected"]:
        rep.add(name, PASS, f"tone detected at {fmt_db(found['level_dbfs'])}")
    else:
        rep.add(name, FAIL, f"tone not detected (1 kHz at {fmt_db(found['level_dbfs'])}); check the cable, "
                "the channel numbers and the input gain")


# ---------------------------------------------------------------- main


def _ints(text: str) -> List[int]:
    return [int(x) for x in text.replace(" ", "").split(",") if x]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Modern-TK80 Scarlett / ASIO hardware check")
    p.add_argument("--device", help="device index or name substring (default: first ASIO Scarlett/Focusrite)")
    p.add_argument("--report", default="scarlett_report.md", help="Markdown report path (default ./scarlett_report.md)")
    p.add_argument("--rates", default=",".join(map(str, DEFAULT_RATES)))
    p.add_argument("--buffers", default=",".join(map(str, DEFAULT_BUFFERS)))
    p.add_argument("--rate", type=int, help="rate for the record/play/loopback steps (default: device default)")
    p.add_argument("--buffer", type=int, default=256, help="buffer for the record/play/loopback steps")
    p.add_argument("--seconds", type=float, default=1.0, help="length of each record/play/loopback step")
    p.add_argument("--no-play", action="store_true", help="skip the play step (no sound out)")
    p.add_argument("--loopback", action="store_true", help="run the loopback step; needs a cable output -> input")
    p.add_argument("--loop-out", type=int, default=1, help="output channel for loopback (from 1)")
    p.add_argument("--loop-in", type=int, default=1, help="input channel for loopback (from 1)")
    p.add_argument("--no-asio-dll", action="store_true", help="do not set SD_ENABLE_ASIO before importing sounddevice")
    p.add_argument("--list-only", action="store_true", help="only list host APIs and devices")
    p.add_argument("--dry-run", action="store_true", help="touch no audio library; write a report of what would run")
    return p


def check_report_path(path: Path) -> Optional[str]:
    """Refuse a report path inside the repo's uploads folder."""
    try:
        resolved = path.resolve()
        uploads = (REPO / "uploads").resolve()
    except OSError as e:
        return _err(e)
    if resolved == uploads or uploads in resolved.parents:
        return f"refusing to write the report inside {uploads}"
    return None


def run_check(args: argparse.Namespace, loader: Callable[[bool], Tuple[Any, Optional[str]]] = load_sounddevice) -> Report:
    rep = Report(started=_dt.datetime.now().astimezone().isoformat(timespec="seconds"))
    rep.environment = {
        "Python": sys.version.split()[0],
        "Platform": platform.platform(),
        "SD_ENABLE_ASIO requested": "no" if args.no_asio_dll else "yes",
    }
    later = ["List host APIs and devices", "Pick device", "Rate x buffer matrix"]
    later += [f"Record {b}-bit ({d})" for d, b, _w in DEPTHS] + ["Play test tone", "Loopback tone"]
    if args.dry_run:
        rep.add("Load sounddevice", SKIPPED, "--dry-run")
        for s in later:
            rep.add(s, SKIPPED, "--dry-run")
        return rep

    sd, error = loader(not args.no_asio_dll)
    if sd is None:
        rep.add("Load sounddevice", FAIL, "sounddevice could not be imported; install it with "
                "`pip install sounddevice` (it is already in requirements.txt)", error or "")
        for s in later:
            rep.add(s, SKIPPED, "no audio library")
        return rep
    rep.environment["sounddevice"] = str(getattr(sd, "__version__", "unknown"))
    try:
        rep.environment["PortAudio"] = str(sd.get_portaudio_version()[1])
    except Exception as e:
        rep.environment["PortAudio"] = "unknown (" + _err(e) + ")"
    rep.add("Load sounddevice", PASS, rep.environment["sounddevice"])

    try:
        rep.hostapis = list_hostapis(sd)
        rep.devices = list_devices(sd)
    except Exception as e:
        rep.add(later[0], FAIL, "query failed", _err(e))
        for s in later[1:]:
            rep.add(s, SKIPPED, "device listing failed")
        return rep
    asio_hosts = [h["name"] for h in rep.hostapis if h["asio"]]
    scar = [d for d in rep.devices if d["scarlett"]]
    rep.add(later[0], PASS, f"{len(rep.hostapis)} host APIs ({'ASIO present' if asio_hosts else 'no ASIO host'}), "
            f"{len(rep.devices)} devices, {len(scar)} named Scarlett/Focusrite")
    if not asio_hosts:
        rep.notes.append("No ASIO host API was listed by this PortAudio build. "
                         + ("SD_ENABLE_ASIO was not set (--no-asio-dll)." if args.no_asio_dll else
                            "SD_ENABLE_ASIO was set before import; a custom portaudio.dll on PATH or a conda "
                            "install would override it (per the sounddevice docs)."))
    if args.list_only:
        for s in later[1:]:
            rep.add(s, SKIPPED, "--list-only")
        return rep

    dev, why = pick_device(rep.devices, args.device)
    if dev is None:
        rep.add(later[1], SKIPPED if args.device is None else FAIL, why)
        for s in later[2:]:
            rep.add(s, SKIPPED, "no device under test")
        return rep
    rep.chosen = dev
    rep.add(later[1], PASS, f"#{dev['index']} {dev['name']} ({dev['host']}), {why}")

    rep.matrix = probe_matrix(sd, dev, _ints(args.rates), _ints(args.buffers))
    rep.add(later[2], *matrix_summary(rep.matrix))

    rate = args.rate or int(dev["default_rate"] or 0)
    if rate <= 0:
        for s in later[3:]:
            rep.add(s, SKIPPED, "device reports no default rate; pass --rate")
        return rep
    for dtype, bits, _w in DEPTHS:
        _record_step(rep, sd, dev, rate, args.buffer, args.seconds, dtype, bits)
    if args.no_play:
        rep.add("Play test tone", SKIPPED, "--no-play")
    else:
        _play_step(rep, sd, dev, rate, args.buffer, args.seconds)
    _loopback_step(rep, sd, dev, rate, args.buffer, args.seconds, args.loopback, args.loop_out, args.loop_in)
    return rep


def main(argv: Optional[Sequence[str]] = None,
         loader: Callable[[bool], Tuple[Any, Optional[str]]] = load_sounddevice) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.report)
    problem = check_report_path(path)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    rep = run_check(args, loader)
    text = render_report(rep)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    for s in rep.steps:
        print(f"{s.status:8} {s.name}: {s.detail}")
    print(f"Report written to {path.resolve()}")
    if rep.steps and rep.steps[0].name == "Load sounddevice" and rep.steps[0].status == FAIL:
        return 2
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
