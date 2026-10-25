"""Vulkan compute path for Modern-TK80-Inference.

This module is the torch alternative for workloads that must run on an
AMD GPU (RX 6700 and others) without ROCm. It does not wrap PyTorch.

Current contract:
- Discover Vulkan devices via vulkaninfo --summary.
- find_host_visible_memory_type returns the first host-visible coherent type.
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
