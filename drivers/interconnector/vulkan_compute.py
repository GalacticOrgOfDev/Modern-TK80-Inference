"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices via vulkaninfo --summary.
- VulkanTensor holds shape, dtype, and a host buffer. add, mul, and
  reshape run on the host today; the methods are the call shape that
  later shader dispatch will replace.
- ImageGenerator looks for an external Vulkan diffusion binary on PATH.
  When found it is invoked; when not found it raises. No silent CPU
  fallback.

Shader dispatch and device memory are not implemented in this pass.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

log = logging.getLogger("tk80.interconnector.vulkan_compute")

DTYPE_SIZES = {"float32": 4, "float16": 2, "int32": 4, "uint8": 1}


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


class VulkanTensor:
    """Custom tensor backed by a VulkanBuffer.

    Stores shape and dtype. Arithmetic (add, mul) and reshape currently
    execute on the host. The method signatures are the contract that a
    later shader dispatch pass will implement on device.
    """

    def __init__(
        self,
        shape: Sequence[int],
        dtype: str = "float32",
        device_index: int = 0,
        data: Optional[bytes] = None,
    ):
        if dtype not in DTYPE_SIZES:
            raise ValueError(f"unsupported dtype: {dtype}")
        if any(d < 0 for d in shape):
            raise ValueError("shape dimensions must be non-negative")
        self.shape: Tuple[int, ...] = tuple(shape)
        self.dtype = dtype
        self.device_index = device_index
        self.numel = 1
        for d in self.shape:
            self.numel *= d
        self.itemsize = DTYPE_SIZES[dtype]
        self.buffer = VulkanBuffer(self.numel * self.itemsize, device_index)
        if data is not None:
            if len(data) != self.buffer.size_bytes:
                raise ValueError("data length does not match shape and dtype")
            self.buffer.write(data)

    def __repr__(self) -> str:
        return f"VulkanTensor(shape={self.shape}, dtype={self.dtype}, device={self.device_index})"

    def _unpack(self) -> List[float]:
        """Return host values as a flat list of floats."""
        raw = self.buffer.read()
        if self.dtype == "float32":
            count = len(raw) // 4
            return list(struct.unpack(f"<{count}f", raw))
        if self.dtype == "int32":
            count = len(raw) // 4
            return [float(x) for x in struct.unpack(f"<{count}i", raw)]
        if self.dtype == "uint8":
            return [float(b) for b in raw]
        # float16 not unpacked in this pass
        raise NotImplementedError(f"unpack not implemented for {self.dtype}")

    def _pack(self, values: Sequence[float]) -> bytes:
        """Pack a flat list of floats into the tensor dtype."""
        if self.dtype == "float32":
            return struct.pack(f"<{len(values)}f", *values)
        if self.dtype == "int32":
            return struct.pack(f"<{len(values)}i", *[int(v) for v in values])
        if self.dtype == "uint8":
            return bytes(int(max(0, min(255, v))) for v in values)
        raise NotImplementedError(f"pack not implemented for {self.dtype}")

    def add(self, other: Union["VulkanTensor", float]) -> "VulkanTensor":
        """Element-wise add. Returns a new tensor of the same shape and dtype."""
        if isinstance(other, VulkanTensor):
            if other.shape != self.shape or other.dtype != self.dtype:
                raise ValueError("add requires matching shape and dtype")
            a = self._unpack()
            b = other._unpack()
            result = [x + y for x, y in zip(a, b)]
        else:
            a = self._unpack()
            result = [x + float(other) for x in a]
        out = VulkanTensor(self.shape, self.dtype, self.device_index)
        out.buffer.write(self._pack(result))
        return out

    def mul(self, other: Union["VulkanTensor", float]) -> "VulkanTensor":
        """Element-wise multiply. Returns a new tensor of the same shape and dtype."""
        if isinstance(other, VulkanTensor):
            if other.shape != self.shape or other.dtype != self.dtype:
                raise ValueError("mul requires matching shape and dtype")
            a = self._unpack()
            b = other._unpack()
            result = [x * y for x, y in zip(a, b)]
        else:
            a = self._unpack()
            result = [x * float(other) for x in a]
        out = VulkanTensor(self.shape, self.dtype, self.device_index)
        out.buffer.write(self._pack(result))
        return out

    def reshape(self, shape: Sequence[int]) -> "VulkanTensor":
        """Return a new tensor with the same data and a new shape.

        The product of the new dimensions must equal numel.
        """
        new_numel = 1
        for d in shape:
            if d < 0:
                raise ValueError("reshape dimensions must be non-negative")
            new_numel *= d
        if new_numel != self.numel:
            raise ValueError(f"reshape numel mismatch: {new_numel} != {self.numel}")
        out = VulkanTensor(shape, self.dtype, self.device_index)
        out.buffer.write(self.buffer.read())
        return out


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
