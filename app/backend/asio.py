"""ASIO compatibility for the Modern-TK80 audio studio.

ASIO is a Windows-only low-latency path (Steinberg). The Scarlett 2i2
Gen 1 and Gen 2 use the Focusrite USB ASIO driver.

The webview/browser path uses WASAPI. True ASIO requires a native
backend (PortAudio with the ASIO host, or the Focusrite driver).
This module owns the studio's ASIO preference, buffer, and probe.
"""

from __future__ import annotations

import platform
from typing import Any, Dict, Optional

DEFAULT_BUFFER = 128
ASIO_BUFFERS = (64, 128, 256, 512, 1024)
FOCUSRITE_ASIO_DRIVER = "Focusrite USB ASIO"


def platform_supports_asio() -> bool:
    return platform.system() == "Windows"


def probe_asio() -> Dict[str, Any]:
    """Report whether a native ASIO host is importable.

    Does not open a device. Returns availability and the preferred driver name.
    """
    available = False
    host = None
    error: Optional[str] = None
    if not platform_supports_asio():
        return {
            "available": False,
            "host": None,
            "driver": FOCUSRITE_ASIO_DRIVER,
            "reason": "ASIO is Windows-only",
        }
    try:
        import sounddevice as sd  # type: ignore

        hostapis = sd.query_hostapis()
        for h in hostapis:
            name = str(h.get("name", "")).lower()
            if "asio" in name:
                available = True
                host = h.get("name")
                break
    except Exception as e:  # pragma: no cover
        error = str(e)
    return {
        "available": available,
        "host": host,
        "driver": FOCUSRITE_ASIO_DRIVER,
        "error": error,
    }


def asio_profile(sample_rate: int, buffer: int) -> Dict[str, Any]:
    """Latency estimate and recommended settings for Scarlett + ASIO."""
    if buffer not in ASIO_BUFFERS:
        buffer = DEFAULT_BUFFER
    latency_ms = round((buffer / float(sample_rate)) * 1000.0, 2)
    return {
        "driver": FOCUSRITE_ASIO_DRIVER,
        "sample_rate": sample_rate,
        "buffer": buffer,
        "latency_ms": latency_ms,
        "notes": (
            "Install the Focusrite driver. In DAWs select ASIO and "
            "'Focusrite USB ASIO'. 128 samples at 44100 Hz is a safe start. "
            "Raise the buffer if you hear clicks."
        ),
    }
