"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices the same way devices.py does (vulkaninfo --summary).
- Hold a simple host-side buffer that can be uploaded later.
- ImageGenerator looks for an external Vulkan diffusion binary on PATH
  (stable-diffusion-vulkan, sd-vulkan, or similar). When found it is
  invoked with the prompt and device index. When not found it raises
  a clear error naming the missing binary. No silent CPU fallback.

Later passes can add real shader dispatch or a bundled binary.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("tk80.interconnector.vulkan_compute")


@dataclass
class VulkanDevice:
    """One Vulkan GPU reported by vulkaninfo."""

    index: int
    name: str
    vendor: Optional[str]

    def __str__(self) -> str:
        return f"vulkan:{self.index} {self.name} ({self.vendor or 'unknown'})"


def discover_vulkan_devices() -> List[VulkanDevice]:
    """Return Vulkan GPUs from vulkaninfo --summary, or an empty list."""
    if shutil.which("vulkaninfo") is None:
        log.warning("vulkaninfo not on PATH")
        return []
    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("vulkaninfo failed: %s", exc)
        return []
    if result.returncode != 0:
        return []

    devices: List[VulkanDevice] = []
    # Minimal parse: GPU lines that contain a name.
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("GPU") and ":" in line:
            try:
                idx = int(line.split(":", 1)[0].replace("GPU", ""))
            except ValueError:
                continue
            name = line.split(":", 1)[1].strip() or f"GPU {idx}"
            devices.append(VulkanDevice(index=idx, name=name, vendor=None))
    return devices


class VulkanBuffer:
    """Host-side buffer that records size and an optional device index.

    Real device memory and shader dispatch are not implemented in this
    pass. The object exists so later code can pass buffers without
    changing the call shape.
    """

    def __init__(self, size_bytes: int, device_index: int = 0):
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        self.size_bytes = size_bytes
        self.device_index = device_index
        self._data = bytearray(size_bytes)

    def write(self, data: bytes, offset: int = 0) -> None:
        """Copy host bytes into the buffer."""
        end = offset + len(data)
        if end > self.size_bytes:
            raise ValueError("write exceeds buffer size")
        self._data[offset:end] = data

    def read(self, offset: int = 0, length: Optional[int] = None) -> bytes:
        """Return host bytes from the buffer."""
        if length is None:
            length = self.size_bytes - offset
        end = offset + length
        if end > self.size_bytes:
            raise ValueError("read exceeds buffer size")
        return bytes(self._data[offset:end])


class ImageGenerator:
    """Generate an image via an external Vulkan diffusion binary.

    Looks for one of the known binary names on PATH. When found, runs it
    with --prompt, --device, and --output. When not found, raises
    RuntimeError naming the missing binary. Does not fall back to CPU
    or to torch.
    """

    CANDIDATES = ("stable-diffusion-vulkan", "sd-vulkan", "sd.cpp")

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.binary: Optional[str] = None
        for name in self.CANDIDATES:
            path = shutil.which(name)
            if path:
                self.binary = path
                break
        if self.binary is None:
            log.info("No Vulkan diffusion binary found on PATH")

    def generate(self, prompt: str, output_path: str, steps: int = 20) -> Path:
        """Run the external binary. Returns the output path on success.

        Raises:
            RuntimeError: No binary is available or the process fails.
        """
        if not self.binary:
            raise RuntimeError(
                "No Vulkan diffusion binary on PATH. Install one of: "
                + ", ".join(self.CANDIDATES)
            )
        if not prompt:
            raise ValueError("prompt is required")
        out = Path(output_path)
        cmd = [
            self.binary,
            "--prompt",
            prompt,
            "--device",
            str(self.device_index),
            "--steps",
            str(steps),
            "--output",
            str(out),
        ]
        log.info("Running Vulkan image generator: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Vulkan image generator failed ({result.returncode}): {result.stderr.strip()}"
            )
        if not out.exists():
            raise RuntimeError(f"Generator reported success but {out} is missing")
        return out
