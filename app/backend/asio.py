"""ASIO compatibility for the Modern-TK80 audio studio.

ASIO is a Windows-only low-latency path (Steinberg). The Scarlett 2i2
Gen 1 and Gen 2 use the Focusrite USB ASIO driver.

This module probes for a native ASIO host (PortAudio via sounddevice)
and can open an input stream on the Focusrite driver to record WAV.
"""

from __future__ import annotations

import platform
import threading
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BUFFER = 128
ASIO_BUFFERS = (64, 128, 256, 512, 1024)
FOCUSRITE_ASIO_DRIVER = "Focusrite USB ASIO"


def platform_supports_asio() -> bool:
    return platform.system() == "Windows"


def _sd():
    """Import sounddevice or return None."""
    try:
        import sounddevice as sd  # type: ignore

        return sd
    except Exception:
        return None


def probe_asio() -> Dict[str, Any]:
    """Report whether a native ASIO host is importable. Does not open a device."""
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
    """List input devices on the ASIO host. Empty if ASIO is not present."""
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
    """Prefer a device whose name contains Focusrite or Scarlett."""
    items = devices if devices is not None else list_asio_devices()
    for d in items:
        name = str(d.get("name", "")).lower()
        if "focusrite" in name or "scarlett" in name:
            return d
    return items[0] if items else None


def asio_profile(sample_rate: int, buffer: int) -> Dict[str, Any]:
    if buffer not in ASIO_BUFFERS:
        buffer = DEFAULT_BUFFER
    latency_ms = round((buffer / float(sample_rate)) * 1000.0, 2)
    return {
        "driver": FOCUSRITE_ASIO_DRIVER,
        "sample_rate": sample_rate,
        "buffer": buffer,
        "latency_ms": latency_ms,
        "notes": (
            "Install the Focusrite driver. Select ASIO and "
            "'Focusrite USB ASIO'. 128 samples at 44100 Hz is a safe start. "
            "Raise the buffer if you hear clicks."
        ),
    }


class AsioRecorder:
    """Open the Focusrite ASIO input and write a WAV."""

    def __init__(self) -> None:
        self._stream = None
        self._wave: Optional[wave.Wave_write] = None
        self._lock = threading.Lock()
        self.path: Optional[Path] = None
        self.device: Optional[Dict[str, Any]] = None
        self.sample_rate = 44100
        self.channels = 2
        self.buffer = DEFAULT_BUFFER
        self.error: Optional[str] = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(
        self,
        path: Path,
        sample_rate: int,
        buffer: int,
        channels: int = 2,
        device_index: Optional[int] = None,
    ) -> Dict[str, Any]:
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
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)

        def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
            if status:
                self.error = str(status)
            with self._lock:
                if self._wave is not None:
                    self._wave.writeframes(indata.tobytes())

        stream = sd.InputStream(
            device=device["index"],
            channels=channels,
            samplerate=sample_rate,
            blocksize=buffer,
            dtype="int16",
            callback=callback,
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
        return {
            "ok": True,
            "device": device,
            "sample_rate": sample_rate,
            "buffer": buffer,
            "channels": channels,
            "path": str(path),
        }

    def stop(self) -> Dict[str, Any]:
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
        }
