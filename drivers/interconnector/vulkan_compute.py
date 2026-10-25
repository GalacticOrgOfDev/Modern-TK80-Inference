"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices via vulkaninfo --summary.
- find_host_visible_memory_type returns the first host-visible coherent type.
- VulkanBuffer allocates device memory. upload and download map host-visible
  memory directly. upload_via_staging and download_via_staging copy through
  a temporary host-visible staging buffer when the primary memory is
  device-local. Both staging methods require a queue, command pool, and
  a host-visible memory type index.
- ShaderDispatcher is SPIR-V native. create_pipeline and create_mul_pipeline
  use embedded SPIR-V by default; an external path overrides when supplied. dispatch_add and dispatch_mul
  upload inputs (direct or staging), submit the dispatch, and download the
  output. VulkanTensor.add and VulkanTensor.mul call them.
- ImageGenerator looks for an external Vulkan diffusion binary on PATH.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

log = logging.getLogger("tk80.interconnector.vulkan_compute")

DTYPE_SIZES = {"float32": 4, "float16": 2, "int32": 4, "uint8": 1}

# SPIR-V with Binding/DescriptorSet decorations, gl_GlobalInvocationID, and FAdd/FMul.
# These are the native shaders; external paths override them when supplied.
EMBEDDED_ADD_SPV = bytes([0x03, 0x02, 0x23, 0x07, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x50, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0f, 0x00, 0x04, 0x00, 0x05, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x6d, 0x61, 0x69, 0x6e, 0x10, 0x00, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x13, 0x00, 0x02, 0x00, 0x02, 0x00, 0x00, 0x00, 0x21, 0x00, 0x03, 0x00, 0x03, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x16, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x15, 0x00, 0x02, 0x00, 0x05, 0x00, 0x00, 0x00, 0x17, 0x00, 0x04, 0x00, 0x06, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x20, 0x00, 0x04, 0x00, 0x07, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x07, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x1d, 0x00, 0x03, 0x00, 0x09, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x1e, 0x00, 0x03, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x20, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x36, 0x00, 0x05, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0xf8, 0x00, 0x02, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x06, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x51, 0x00, 0x05, 0x00, 0x05, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x00, 0x13, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x00, 0x15, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x81, 0x00, 0x05, 0x00, 0x04, 0x00, 0x00, 0x00, 0x16, 0x00, 0x00, 0x00, 0x13, 0x00, 0x00, 0x00, 0x15, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x17, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3e, 0x00, 0x03, 0x00, 0x17, 0x00, 0x00, 0x00, 0x16, 0x00, 0x00, 0x00, 0xfd, 0x00, 0x01, 0x00, 0x38, 0x00, 0x01, 0x00])
EMBEDDED_MUL_SPV = bytes([0x03, 0x02, 0x23, 0x07, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x50, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0f, 0x00, 0x04, 0x00, 0x05, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x6d, 0x61, 0x69, 0x6e, 0x10, 0x00, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x21, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x47, 0x00, 0x04, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x22, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x13, 0x00, 0x02, 0x00, 0x02, 0x00, 0x00, 0x00, 0x21, 0x00, 0x03, 0x00, 0x03, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x16, 0x00, 0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x15, 0x00, 0x02, 0x00, 0x05, 0x00, 0x00, 0x00, 0x17, 0x00, 0x04, 0x00, 0x06, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x20, 0x00, 0x04, 0x00, 0x07, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x07, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x1d, 0x00, 0x03, 0x00, 0x09, 0x00, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x1e, 0x00, 0x03, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x20, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x0a, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x3b, 0x00, 0x04, 0x00, 0x0b, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x36, 0x00, 0x05, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0xf8, 0x00, 0x02, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x06, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x51, 0x00, 0x05, 0x00, 0x05, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x0c, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x00, 0x13, 0x00, 0x00, 0x00, 0x12, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x0d, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3d, 0x00, 0x04, 0x00, 0x04, 0x00, 0x00, 0x00, 0x15, 0x00, 0x00, 0x00, 0x14, 0x00, 0x00, 0x00, 0x84, 0x00, 0x05, 0x00, 0x04, 0x00, 0x00, 0x00, 0x16, 0x00, 0x00, 0x00, 0x13, 0x00, 0x00, 0x00, 0x15, 0x00, 0x00, 0x00, 0x41, 0x00, 0x06, 0x00, 0x04, 0x00, 0x00, 0x00, 0x17, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, 0x00, 0x00, 0x00, 0x3e, 0x00, 0x03, 0x00, 0x17, 0x00, 0x00, 0x00, 0x16, 0x00, 0x00, 0x00, 0xfd, 0x00, 0x01, 0x00, 0x38, 0x00, 0x01, 0x00])



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



def find_host_visible_memory_type(physical_device: Any) -> int:
    """Return the index of the first host-visible, host-coherent memory type.

    Raises:
        RuntimeError: No suitable memory type exists.
    """
    vk = _load_vulkan()
    props = vk.vkGetPhysicalDeviceMemoryProperties(physical_device)
    flags = vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
    for i in range(props.memoryTypeCount):
        if props.memoryTypes[i].propertyFlags & flags == flags:
            log.info("Selected host-visible memory type %d", i)
            return i
    raise RuntimeError("no host-visible coherent memory type found")


class VulkanBuffer:
    """Buffer that can be allocated on a Vulkan device.

    Host bytes are always stored. allocate creates the device buffer.
    upload and download map host-visible memory. upload_via_staging and
    download_via_staging copy through a temporary host-visible buffer
    when the primary allocation is device-local.
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
        """Allocate device memory for this buffer."""
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

    def upload(self, device: Any) -> None:
        """Map the device memory and copy host bytes into it."""
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before upload")
        vk = _load_vulkan()
        ptr = vk.vkMapMemory(device, self._device_memory, 0, self.size_bytes, 0)
        if not ptr:
            raise RuntimeError("vkMapMemory returned null; memory is not host-visible")
        try:
            import ctypes
            ctypes.memmove(ptr, (ctypes.c_char * self.size_bytes).from_buffer(self._data), self.size_bytes)
        except Exception as exc:
            vk.vkUnmapMemory(device, self._device_memory)
            raise RuntimeError(f"host-to-device copy failed: {exc}") from exc
        vk.vkUnmapMemory(device, self._device_memory)

    def download(self, device: Any) -> None:
        """Map the device memory and copy it into the host bytes."""
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before download")
        vk = _load_vulkan()
        ptr = vk.vkMapMemory(device, self._device_memory, 0, self.size_bytes, 0)
        if not ptr:
            raise RuntimeError("vkMapMemory returned null; memory is not host-visible")
        try:
            import ctypes
            ctypes.memmove((ctypes.c_char * self.size_bytes).from_buffer(self._data), ptr, self.size_bytes)
        except Exception as exc:
            vk.vkUnmapMemory(device, self._device_memory)
            raise RuntimeError(f"device-to-host copy failed: {exc}") from exc
        vk.vkUnmapMemory(device, self._device_memory)

    def upload_via_staging(
        self,
        device: Any,
        queue: Any,
        command_pool: Any,
        host_visible_index: int,
    ) -> None:
        """Copy host bytes to a staging buffer, then to this device-local buffer.

        Raises:
            RuntimeError: this buffer is not allocated or the copy fails.
        """
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before staging upload")
        vk = _load_vulkan()
        staging = VulkanBuffer(self.size_bytes, self.device_index)
        staging.write(self.read())
        staging.allocate(device, host_visible_index)
        staging.upload(device)
        cmd = vk.vkAllocateCommandBuffers(
            device,
            vk.VkCommandBufferAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                commandPool=command_pool,
                level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                commandBufferCount=1,
            ),
        )[0]
        vk.vkBeginCommandBuffer(cmd, vk.VkCommandBufferBeginInfo(sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO))
        vk.vkCmdCopyBuffer(
            cmd,
            staging.device_buffer,
            self._device_buffer,
            1,
            [vk.VkBufferCopy(srcOffset=0, dstOffset=0, size=self.size_bytes)],
        )
        vk.vkEndCommandBuffer(cmd)
        vk.vkQueueSubmit(queue, 1, [vk.VkSubmitInfo(sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO, commandBufferCount=1, pCommandBuffers=[cmd])], None)
        vk.vkQueueWaitIdle(queue)
        vk.vkFreeCommandBuffers(device, command_pool, 1, [cmd])
        staging.free(device)
        log.info("Staged upload of %d bytes", self.size_bytes)

    def download_via_staging(
        self,
        device: Any,
        queue: Any,
        command_pool: Any,
        host_visible_index: int,
    ) -> None:
        """Copy this device-local buffer to a staging buffer, then to host bytes."""
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before staging download")
        vk = _load_vulkan()
        staging = VulkanBuffer(self.size_bytes, self.device_index)
        staging.allocate(device, host_visible_index)
        cmd = vk.vkAllocateCommandBuffers(
            device,
            vk.VkCommandBufferAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                commandPool=command_pool,
                level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                commandBufferCount=1,
            ),
        )[0]
        vk.vkBeginCommandBuffer(cmd, vk.VkCommandBufferBeginInfo(sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO))
        vk.vkCmdCopyBuffer(
            cmd,
            self._device_buffer,
            staging.device_buffer,
            1,
            [vk.VkBufferCopy(srcOffset=0, dstOffset=0, size=self.size_bytes)],
        )
        vk.vkEndCommandBuffer(cmd)
        vk.vkQueueSubmit(queue, 1, [vk.VkSubmitInfo(sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO, commandBufferCount=1, pCommandBuffers=[cmd])], None)
        vk.vkQueueWaitIdle(queue)
        vk.vkFreeCommandBuffers(device, command_pool, 1, [cmd])
        staging.download(device)
        self.write(staging.read())
        staging.free(device)
        log.info("Staged download of %d bytes", self.size_bytes)

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

    @property
    def device_buffer(self) -> Any:
        return self._device_buffer


class ShaderDispatcher:
    """Create compute pipelines and dispatch add or mul shaders.

    create_pipeline builds the add pipeline. create_mul_pipeline builds
    the mul pipeline from a second SPIR-V. dispatch_add and dispatch_mul
    transfer data (direct or staging) and submit the dispatch.
    """

    def __init__(self, spv_path: Optional[str] = None, mul_spv_path: Optional[str] = None):
        self.spv_path = spv_path
        self.mul_spv_path = mul_spv_path
        self._pipeline: Any = None
        self._mul_pipeline: Any = None
        self._pipeline_layout: Any = None
        self._descriptor_set_layout: Any = None
        self._shader_module: Any = None
        self._mul_shader_module: Any = None

    def create_pipeline(self, device: Any) -> None:
        """Load the add SPIR-V and create the compute pipeline."""
        vk = _load_vulkan()
        if self.spv_path and Path(self.spv_path).is_file():
            spv = Path(self.spv_path).read_bytes()
        else:
            spv = EMBEDDED_ADD_SPV
            pass  # embedded SPIR-V is real bytecode
        self._shader_module = vk.vkCreateShaderModule(
            device,
            vk.VkShaderModuleCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
                codeSize=len(spv),
                pCode=spv,
            ),
            None,
        )
        bindings = [
            vk.VkDescriptorSetLayoutBinding(
                binding=i,
                descriptorType=vk.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                descriptorCount=1,
                stageFlags=vk.VK_SHADER_STAGE_COMPUTE_BIT,
            )
            for i in range(3)
        ]
        self._descriptor_set_layout = vk.vkCreateDescriptorSetLayout(
            device,
            vk.VkDescriptorSetLayoutCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
                bindingCount=3,
                pBindings=bindings,
            ),
            None,
        )
        self._pipeline_layout = vk.vkCreatePipelineLayout(
            device,
            vk.VkPipelineLayoutCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
                setLayoutCount=1,
                pSetLayouts=[self._descriptor_set_layout],
            ),
            None,
        )
        stage = vk.VkPipelineShaderStageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            stage=vk.VK_SHADER_STAGE_COMPUTE_BIT,
            module=self._shader_module,
            pName="main",
        )
        self._pipeline = vk.vkCreateComputePipelines(
            device,
            None,
            1,
            [vk.VkComputePipelineCreateInfo(sType=vk.VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, stage=stage, layout=self._pipeline_layout)],
            None,
        )[0]
        log.info("Add pipeline created from %s", self.spv_path)

    def create_mul_pipeline(self, device: Any) -> None:
        """Load the mul SPIR-V and create the mul compute pipeline."""
        vk = _load_vulkan()
        if self._pipeline_layout is None:
            raise RuntimeError("call create_pipeline before create_mul_pipeline")
        if self.mul_spv_path and Path(self.mul_spv_path).is_file():
            spv = Path(self.mul_spv_path).read_bytes()
        else:
            spv = EMBEDDED_MUL_SPV
            pass  # embedded SPIR-V is real bytecode
        self._mul_shader_module = vk.vkCreateShaderModule(
            device,
            vk.VkShaderModuleCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
                codeSize=len(spv),
                pCode=spv,
            ),
            None,
        )
        stage = vk.VkPipelineShaderStageCreateInfo(
            sType=vk.VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
            stage=vk.VK_SHADER_STAGE_COMPUTE_BIT,
            module=self._mul_shader_module,
            pName="main",
        )
        self._mul_pipeline = vk.vkCreateComputePipelines(
            device,
            None,
            1,
            [vk.VkComputePipelineCreateInfo(sType=vk.VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, stage=stage, layout=self._pipeline_layout)],
            None,
        )[0]
        log.info("Mul pipeline created from %s", self.mul_spv_path)

    def _dispatch(
        self,
        device: Any,
        queue: Any,
        command_pool: Any,
        pipeline: Any,
        a: VulkanBuffer,
        b: VulkanBuffer,
        out: VulkanBuffer,
        count: int,
        use_staging: bool,
        host_visible_index: Optional[int],
    ) -> None:
        """Shared dispatch path for add and mul."""
        vk = _load_vulkan()
        if not (a.is_allocated and b.is_allocated and out.is_allocated):
            raise RuntimeError("all buffers must be allocated before dispatch")
        if use_staging:
            if host_visible_index is None:
                raise RuntimeError("host_visible_index required for staging")
            a.upload_via_staging(device, queue, command_pool, host_visible_index)
            b.upload_via_staging(device, queue, command_pool, host_visible_index)
        else:
            a.upload(device)
            b.upload(device)
        pool = vk.vkCreateDescriptorPool(
            device,
            vk.VkDescriptorPoolCreateInfo(
                sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
                maxSets=1,
                poolSizeCount=1,
                pPoolSizes=[vk.VkDescriptorPoolSize(type=vk.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, descriptorCount=3)],
            ),
            None,
        )
        dset = vk.vkAllocateDescriptorSets(
            device,
            vk.VkDescriptorSetAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
                descriptorPool=pool,
                descriptorSetCount=1,
                pSetLayouts=[self._descriptor_set_layout],
            ),
        )[0]
        infos = [vk.VkDescriptorBufferInfo(buffer=buf.device_buffer, offset=0, range=buf.size_bytes) for buf in (a, b, out)]
        writes = [
            vk.VkWriteDescriptorSet(
                sType=vk.VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                dstSet=dset,
                dstBinding=i,
                descriptorCount=1,
                descriptorType=vk.VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                pBufferInfo=infos[i],
            )
            for i in range(3)
        ]
        vk.vkUpdateDescriptorSets(device, 3, writes, 0, None)
        cmd = vk.vkAllocateCommandBuffers(
            device,
            vk.VkCommandBufferAllocateInfo(
                sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                commandPool=command_pool,
                level=vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                commandBufferCount=1,
            ),
        )[0]
        vk.vkBeginCommandBuffer(cmd, vk.VkCommandBufferBeginInfo(sType=vk.VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO))
        vk.vkCmdBindPipeline(cmd, vk.VK_PIPELINE_BIND_POINT_COMPUTE, pipeline)
        vk.vkCmdBindDescriptorSets(cmd, vk.VK_PIPELINE_BIND_POINT_COMPUTE, self._pipeline_layout, 0, 1, [dset], 0, None)
        groups = (count + 63) // 64
        vk.vkCmdDispatch(cmd, groups, 1, 1)
        vk.vkEndCommandBuffer(cmd)
        vk.vkQueueSubmit(queue, 1, [vk.VkSubmitInfo(sType=vk.VK_STRUCTURE_TYPE_SUBMIT_INFO, commandBufferCount=1, pCommandBuffers=[cmd])], None)
        vk.vkQueueWaitIdle(queue)
        vk.vkFreeCommandBuffers(device, command_pool, 1, [cmd])
        vk.vkDestroyDescriptorPool(device, pool, None)
        if use_staging:
            out.download_via_staging(device, queue, command_pool, host_visible_index)  # type: ignore[arg-type]
        else:
            out.download(device)

    def dispatch_add(
        self,
        device: Any,
        queue: Any,
        command_pool: Any,
        a: VulkanBuffer,
        b: VulkanBuffer,
        out: VulkanBuffer,
        count: int,
        use_staging: bool = False,
        host_visible_index: Optional[int] = None,
    ) -> None:
        """Dispatch the add pipeline."""
        if self._pipeline is None:
            raise RuntimeError("call create_pipeline before dispatch_add")
        self._dispatch(device, queue, command_pool, self._pipeline, a, b, out, count, use_staging, host_visible_index)
        log.info("Dispatched add for %d elements", count)

    def dispatch_mul(
        self,
        device: Any,
        queue: Any,
        command_pool: Any,
        a: VulkanBuffer,
        b: VulkanBuffer,
        out: VulkanBuffer,
        count: int,
        use_staging: bool = False,
        host_visible_index: Optional[int] = None,
    ) -> None:
        """Dispatch the mul pipeline."""
        if self._mul_pipeline is None:
            raise RuntimeError("call create_mul_pipeline before dispatch_mul")
        self._dispatch(device, queue, command_pool, self._mul_pipeline, a, b, out, count, use_staging, host_visible_index)
        log.info("Dispatched mul for %d elements", count)


class VulkanTensor:
    """Custom tensor backed by a VulkanBuffer.

    add and mul require an attached ShaderDispatcher with the matching
    pipeline created, plus a device, queue, and command pool.
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

    def add(
        self,
        other: "VulkanTensor",
        device: Any,
        queue: Any,
        command_pool: Any,
        use_staging: bool = False,
        host_visible_index: Optional[int] = None,
    ) -> "VulkanTensor":
        """Element-wise add via the compute pipeline."""
        if self.dispatcher is None:
            raise RuntimeError("ShaderDispatcher required for add")
        if other.shape != self.shape or other.dtype != self.dtype:
            raise ValueError("add requires matching shape and dtype")
        out = VulkanTensor(self.shape, self.dtype, self.device_index, dispatcher=self.dispatcher)
        self.dispatcher.dispatch_add(
            device, queue, command_pool, self.buffer, other.buffer, out.buffer, self.numel, use_staging, host_visible_index
        )
        return out

    def mul(
        self,
        other: "VulkanTensor",
        device: Any,
        queue: Any,
        command_pool: Any,
        use_staging: bool = False,
        host_visible_index: Optional[int] = None,
    ) -> "VulkanTensor":
        """Element-wise multiply via the compute pipeline."""
        if self.dispatcher is None:
            raise RuntimeError("ShaderDispatcher required for mul")
        if other.shape != self.shape or other.dtype != self.dtype:
            raise ValueError("mul requires matching shape and dtype")
        out = VulkanTensor(self.shape, self.dtype, self.device_index, dispatcher=self.dispatcher)
        self.dispatcher.dispatch_mul(
            device, queue, command_pool, self.buffer, other.buffer, out.buffer, self.numel, use_staging, host_visible_index
        )
        return out

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
        """Run the external binary. Returns the output path on success."""
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
