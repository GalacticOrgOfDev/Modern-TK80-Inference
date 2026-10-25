"""ASIO compatibility for the Modern-TK80 Windows app.

Low-latency recording path. Prefer 64-sample buffer at 44100 Hz
(~1.5 ms) on the Focusrite USB ASIO driver. Raise the buffer only
if the driver reports underruns.

While recording, a rolling peak buffer is kept so the UI can draw
a live waveform on the armed track without blocking the stream.
"""

from __future__ import annotations

import platform
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BUFFER = 64
ASIO_BUFFERS = (64, 128, 256, 512, 1024)
FOCUSRITE_ASIO_DRIVER = "Focusrite USB ASIO"
LOW_LATENCY_RATE = 44100
LEVEL_BUCKETS = 64


def platform_supports_asio() -> bool:
    """platform supports asio."""
    return platform.system() == "Windows"


def _sd():
    """sd."""
    try:
        import sounddevice as sd  # type: ignore

        return sd
    except Exception:
        return None


def probe_asio() -> Dict[str, Any]:
    """Probe whether an ASIO host is available and return a status dict."""
    if not platform_supports_asio():
        return {
            "available": False,
            "host": None,
            "driver": FOCUSRITE_ASIO_DRIVER,
            "reason": "ASIO is Windows-only",
        }
    sd = _sd()
    if sd is None:
        return {
            "available": False,
            "host": None,
            "driver": FOCUSRITE_ASIO_DRIVER,
            "reason": "sounddevice not installed",
        }
    host = None
    try:
        for h in sd.query_hostapis():
            name = str(h.get("name", ""))
            if "asio" in name.lower():
                host = name
                break
    except Exception as e:  # pragma: no cover
        return {
            "available": False,
            "host": None,
            "driver": FOCUSRITE_ASIO_DRIVER,
            "error": str(e),
        }
    return {
        "available": host is not None,
        "host": host,
        "driver": FOCUSRITE_ASIO_DRIVER,
    }


def list_asio_devices() -> List[Dict[str, Any]]:
    """Return available ASIO input devices, or an empty list if none are present."""
    sd = _sd()
    if sd is None or not platform_supports_asio():
        return []
    devices: List[Dict[str, Any]] = []
    try:
        for i, d in enumerate(sd.query_devices()):
            host = sd.query_hostapis(d["hostapi"])
            if "asio" not in str(host.get("name", "")).lower():
                continue
            if int(d.get("max_input_channels", 0)) < 1:
                continue
            devices.append(
                {
                    "index": i,
                    "name": d.get("name"),
                    "host": host.get("name"),
                    "inputs": int(d.get("max_input_channels", 0)),
                    "default_rate": int(d.get("default_samplerate", 44100)),
                }
            )
    except Exception:
        return []
    return devices


def find_focusrite(devices: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """find focusrite."""
    items = devices if devices is not None else list_asio_devices()
    for d in items:
        name = str(d.get("name", "")).lower()
        if "focusrite" in name or "scarlett" in name:
            return d
    return items[0] if items else None


def asio_profile(sample_rate: int, buffer: int) -> Dict[str, Any]:
    """Return the ASIO buffer and latency profile for the current settings."""
    if buffer not in ASIO_BUFFERS:
        buffer = DEFAULT_BUFFER
    latency_ms = round((buffer / float(sample_rate)) * 1000.0, 2)
    return {
        "driver": FOCUSRITE_ASIO_DRIVER,
        "sample_rate": sample_rate,
        "buffer": buffer,
        "latency_ms": latency_ms,
        "low_latency": buffer <= 64 and sample_rate in (44100, 48000),
        "notes": (
            "Prefer 64 samples at 44100 Hz (~1.5 ms) for tracking. "
            "Raise to 128 if the Focusrite driver clicks. "
            "Keep the app window light; audio runs on its own stream."
        ),
    }


class AsioRecorder:
    """Open the Focusrite ASIO input and write a WAV."""

    def __init__(self) -> None:
        """init."""
        self._stream = None
        self._wave: Optional[wave.Wave_write] = None
        self._lock = threading.Lock()
        self.path: Optional[Path] = None
        self.device: Optional[Dict[str, Any]] = None
        self.sample_rate = LOW_LATENCY_RATE
        self.channels = 2
        self.buffer = DEFAULT_BUFFER
        self.error: Optional[str] = None
        self._levels: deque[float] = deque(maxlen=LEVEL_BUCKETS)
        self._peak: float = 0.0

    @property
    def recording(self) -> bool:
        """recording."""
        return self._stream is not None

    def levels(self) -> Dict[str, Any]:
        """Return recent peak levels while recording."""
        with self._lock:
            peaks = list(self._levels)
            peak = self._peak
        return {
            "recording": self.recording,
            "peaks": peaks,
            "peak": round(peak, 3),
        }

    def start(
        self,
        path: Path,
        sample_rate: int,
        buffer: int,
        channels: int = 2,
        device_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Start ASIO recording on the given device index."""
        if self.recording:
            raise RuntimeError("already recording")
        sd = _sd()
        if sd is None:
            raise RuntimeError("sounddevice not installed")
        if not platform_supports_asio():
            raise RuntimeError("ASIO is Windows-only")

        devices = list_asio_devices()
        device = None
        if device_index is not None:
            device = next((d for d in devices if d["index"] == device_index), None)
        if device is None:
            device = find_focusrite(devices)
        if device is None:
            raise RuntimeError("no ASIO input device found")

        path.parent.mkdir(parents=True, exist_ok=True)
        wf = wave.open(str(path), "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
            if status:
                """callback."""
                self.error = str(status)
            # Peak of this block, normalized 0..1.
            try:
                peak = float(abs(indata).max()) / 32767.0
            except Exception:
                peak = 0.0
            with self._lock:
                if self._wave is not None:
                    self._wave.writeframes(indata.tobytes())
                self._levels.append(round(min(1.0, peak), 3))
                if peak > self._peak:
                    self._peak = peak

        stream = sd.InputStream(
            device=device["index"],
            channels=channels,
            samplerate=sample_rate,
            blocksize=buffer,
            dtype="int16",
            callback=callback,
            latency="low",
        )
        stream.start()

        self._stream = stream
        self._wave = wf
        self.path = path
        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer = buffer
        self.error = None
        with self._lock:
            self._levels.clear()
            self._peak = 0.0
        return {
            "ok": True,
            "device": device,
            "sample_rate": sample_rate,
            "buffer": buffer,
            "channels": channels,
            "latency_ms": round((buffer / float(sample_rate)) * 1000.0, 2),
            "path": str(path),
        }

    def stop(self) -> Dict[str, Any]:
        """Stop recording and return the path of the captured WAV."""
        if not self.recording:
            raise RuntimeError("not recording")
        stream = self._stream
        wf = self._wave
        self._stream = None
        self._wave = None
        try:
            if stream is not None:
                stream.stop()
                stream.close()
        finally:
            if wf is not None:
                wf.close()
        return {
            "ok": True,
            "path": str(self.path) if self.path else "",
            "device": self.device,
            "sample_rate": self.sample_rate,
            "buffer": self.buffer,
            "channels": self.channels,
            "error": self.error,
            "peak": round(self._peak, 3),
        }
