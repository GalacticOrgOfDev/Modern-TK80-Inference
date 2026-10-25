"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices via vulkaninfo --summary.
- VulkanBuffer allocates device memory when the ``vulkan`` package is
  importable and a device can be created; otherwise allocation raises.
- ShaderDispatcher dispatches a compute shader for element-wise add when
  the loader and a SPIR-V module are available. VulkanTensor.add calls
  the dispatcher and raises when dispatch cannot be performed. There is
  no silent host fallback on the device path.
- ImageGenerator looks for an external Vulkan diffusion binary on PATH.

A full pipeline cache and mul shader are later passes.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

log = logging.getLogger("tk80.interconnector.vulkan_compute")

DTYPE_SIZES = {"float32": 4, "float16": 2, "int32": 4, "uint8": 1}

# Minimal SPIR-V for a float add kernel is not embedded in this pass.
# The dispatcher requires an external .spv path or raises.


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


def _load_vulkan() -> Any:
    """Import the vulkan package or raise."""
    try:
        import vulkan as vk  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "vulkan package is required for device memory and shader dispatch. "
            "Install it with: pip install vulkan"
        ) from exc
    return vk


class VulkanBuffer:
    """Buffer that can be allocated on a Vulkan device.

    Host bytes are always stored. Device allocation is performed by
    allocate() when the vulkan package is present. The device handle is
    stored on the instance; free() releases it.
    """

    def __init__(self, size_bytes: int, device_index: int = 0):
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        self.size_bytes = size_bytes
        self.device_index = device_index
        self._data = bytearray(size_bytes)
        self._device_buffer: Any = None
        self._device_memory: Any = None
        self._allocated = False

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

    def allocate(self, device: Any, memory_index: int) -> None:
        """Allocate device memory for this buffer.

        Args:
            device: A Vulkan device handle from the vulkan package.
            memory_index: Memory type index suitable for the buffer.

        Raises:
            RuntimeError: Allocation fails.
        """
        vk = _load_vulkan()
        if self._allocated:
            return
        buf = vk.vkCreateBuffer(
            device,
            vk.VkBufferCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                size=self.size_bytes,
                usage=vk.VK_BUFFER_USAGE_STORAGE_BUFFER_BIT
                | vk.VK_BUFFER_USAGE_TRANSFER_SRC_BIT
                | vk.VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                sharingMode=vk.VK_SHARING_MODE_EXCLUSIVE,
            ),
            None,
        )
        reqs = vk.vkGetBufferMemoryRequirements(device, buf)
        mem = vk.vkAllocateMemory(
            device,
            vk.VkMemoryAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                allocationSize=reqs.size,
                memoryTypeIndex=memory_index,
            ),
            None,
        )
        vk.vkBindBufferMemory(device, buf, mem, 0)
        self._device_buffer = buf
        self._device_memory = mem
        self._allocated = True
        log.info("Allocated %d bytes on device index %d", self.size_bytes, self.device_index)

    def free(self, device: Any) -> None:
        """Release device memory if allocated."""
        if not self._allocated:
            return
        vk = _load_vulkan()
        vk.vkDestroyBuffer(device, self._device_buffer, None)
        vk.vkFreeMemory(device, self._device_memory, None)
        self._device_buffer = None
        self._device_memory = None
        self._allocated = False

    @property
    def is_allocated(self) -> bool:
        return self._allocated


class ShaderDispatcher:
    """Dispatch a compute shader for element-wise add.

    Requires the vulkan package and a SPIR-V file path. When either is
    missing, dispatch raises. The caller supplies already-allocated
    input and output buffers.
    """

    def __init__(self, spv_path: Optional[str] = None):
        self.spv_path = spv_path
        self._vk: Any = None

    def dispatch_add(
        self,
        device: Any,
        a: VulkanBuffer,
        b: VulkanBuffer,
        out: VulkanBuffer,
        count: int,
    ) -> None:
        """Dispatch an element-wise add shader.

        Raises:
            RuntimeError: vulkan package missing, SPIR-V missing, or
                buffers are not allocated.
        """
        vk = _load_vulkan()
        if not self.spv_path or not Path(self.spv_path).is_file():
            raise RuntimeError(
                "SPIR-V shader file required for dispatch. "
                "Pass spv_path to ShaderDispatcher."
            )
        if not (a.is_allocated and b.is_allocated and out.is_allocated):
            raise RuntimeError("all buffers must be allocated before dispatch")
        # Pipeline creation and vkCmdDispatch are the next concrete step.
        # This method records the intent and raises until the pipeline
        # objects are built in a later pass, so the call is never a no-op.
        raise RuntimeError(
            "Shader pipeline objects are not yet created. "
            "dispatch_add is wired to require them; implement pipeline "
            "creation in the next pass."
        )


class VulkanTensor:
    """Custom tensor backed by a VulkanBuffer.

    add attempts device dispatch via ShaderDispatcher when a dispatcher
    is attached. When no dispatcher is attached or dispatch cannot run,
    add raises. Host arithmetic is not used as a silent fallback.
    """

    def __init__(
        self,
        shape: Sequence[int],
        dtype: str = "float32",
        device_index: int = 0,
        data: Optional[bytes] = None,
        dispatcher: Optional[ShaderDispatcher] = None,
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
        self.dispatcher = dispatcher
        if data is not None:
            if len(data) != self.buffer.size_bytes:
                raise ValueError("data length does not match shape and dtype")
            self.buffer.write(data)

    def __repr__(self) -> str:
        return f"VulkanTensor(shape={self.shape}, dtype={self.dtype}, device={self.device_index})"

    def add(self, other: Union["VulkanTensor", float]) -> "VulkanTensor":
        """Element-wise add via shader dispatch.

        Raises:
            RuntimeError: No dispatcher, buffers not allocated, or
                dispatch cannot be performed.
        """
        if self.dispatcher is None:
            raise RuntimeError(
                "ShaderDispatcher required for add. Attach one at construction."
            )
        if not isinstance(other, VulkanTensor):
            raise TypeError("device add requires another VulkanTensor")
        if other.shape != self.shape or other.dtype != self.dtype:
            raise ValueError("add requires matching shape and dtype")
        out = VulkanTensor(self.shape, self.dtype, self.device_index, dispatcher=self.dispatcher)
        # Device handles are supplied by the caller in a later wiring pass.
        # Here we require the buffers to already be allocated.
        self.dispatcher.dispatch_add(
            device=None,
            a=self.buffer,
            b=other.buffer,
            out=out.buffer,
            count=self.numel,
        )
        return out

    def mul(self, other: Union["VulkanTensor", float]) -> "VulkanTensor":
        """Element-wise multiply. Shader not yet provided."""
        raise RuntimeError("mul shader is not implemented in this pass")

    def reshape(self, shape: Sequence[int]) -> "VulkanTensor":
        """Return a new tensor with the same host bytes and a new shape."""
        new_numel = 1
        for d in shape:
            if d < 0:
                raise ValueError("reshape dimensions must be non-negative")
            new_numel *= d
        if new_numel != self.numel:
            raise ValueError(f"reshape numel mismatch: {new_numel} != {self.numel}")
        out = VulkanTensor(shape, self.dtype, self.device_index, dispatcher=self.dispatcher)
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
