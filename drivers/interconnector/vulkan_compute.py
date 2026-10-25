"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices via vulkaninfo --summary.
- find_host_visible_memory_type returns the first memory type that is
  host-visible and host-coherent. allocate, upload_via_staging, and
  download_via_staging use it when the caller does not supply an index.
- VulkanBuffer allocates device memory. upload and download map host-visible
  memory directly. upload_via_staging and download_via_staging copy through
  a temporary host-visible staging buffer.
- ShaderDispatcher.create_pipeline builds the add pipeline. create_mul_pipeline
  builds the mul pipeline from a second SPIR-V. dispatch_add and dispatch_mul
  upload inputs, submit the dispatch, and download the output.
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
    When memory_index is omitted, find_host_visible_memory_type is used.
    upload and download map host-visible memory. upload_via_staging and
    download_via_staging copy through a temporary host-visible buffer.
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

    def allocate(
        self,
        device: Any,
        memory_index: Optional[int] = None,
        physical_device: Optional[Any] = None,
    ) -> None:
        """Allocate device memory for this buffer.

        If memory_index is None, physical_device must be supplied so a
        host-visible type can be selected.
        """
        vk = _load_vulkan()
        if self._allocated:
            return
        if memory_index is None:
            if physical_device is None:
                raise RuntimeError("physical_device required when memory_index is omitted")
            memory_index = find_host_visible_memory_type(physical_device)
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
        host_visible_index: Optional[int] = None,
        physical_device: Optional[Any] = None,
    ) -> None:
        """Copy host bytes to a staging buffer, then to this device-local buffer."""
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before staging upload")
        if host_visible_index is None:
            if physical_device is None:
                raise RuntimeError("physical_device required when host_visible_index is omitted")
            host_visible_index = find_host_visible_memory_type(physical_device)
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
        host_visible_index: Optional[int] = None,
        physical_device: Optional[Any] = None,
    ) -> None:
        """Copy this device-local buffer to a staging buffer, then to host bytes."""
        if not self._allocated:
            raise RuntimeError("buffer must be allocated before staging download")
        if host_visible_index is None:
            if physical_device is None:
                raise RuntimeError("physical_device required when host_visible_index is omitted")
            host_visible_index = find_host_visible_memory_type(physical_device)
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
