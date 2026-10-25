"""Device discovery for Modern-TK80-Inference.

Reports the compute devices present on the machine so later backends can
select a usable target. Detection reads only real sources and never
guesses a device that is not reported.

Sources, in order:

* Vulkan GPUs via ``vulkaninfo --summary`` when the tool is on PATH.
  Discrete and integrated GPUs are kept; CPU, virtual, and other devices
  are skipped. Vendor is taken from the PCI vendor ID (0x1002 AMD,
  0x10de NVIDIA, 0x8086 Intel, 0x106b Apple). Memory is not present in
  the summary; a later full ``vulkaninfo`` pass can add heaps when
  required.
* CUDA devices via ``torch.cuda`` when PyTorch is installed and CUDA is
  available. Each device reports name, total memory, and free memory
  when ``mem_get_info`` exists.
* CPU is always included as a fallback with no VRAM figure.

The returned device string is ``vulkan:N``, ``cuda:N``, or ``cpu``.
``N`` is the index suitable for a Vulkan-enabled llama.cpp build or for
``torch.cuda`` respectively.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("tk80.interconnector.devices")

PCI_VENDOR_IDS = {
    0x1002: "amd",
    0x10DE: "nvidia",
    0x8086: "intel",
    0x106B: "apple",
}

LLAMA_VULKAN_DEVICE_TYPES = frozenset(
    {"PHYSICAL_DEVICE_TYPE_DISCRETE_GPU", "PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU"}
)


@dataclass
class Device:
    """One compute device reported by a real source.

    Args:
        index: Stable index for this backend (Vulkan device number or
            CUDA device number).
        name: Name reported by the source, or "CPU" for the fallback.
        vendor: "amd", "nvidia", "intel", "apple", or None.
        backend: "vulkan", "cuda", or "cpu".
        total_memory_mb: Dedicated memory in MiB, or None for CPU.
        free_memory_mb: Free memory in MiB when known, else None.
        device_string: The string a backend should receive ("vulkan:0",
            "cuda:1", "cpu").
    """

    index: int
    name: str
    vendor: Optional[str]
    backend: str
    total_memory_mb: Optional[int]
    free_memory_mb: Optional[int]
    device_string: str

    def __str__(self) -> str:
        free = (
            f"{self.free_memory_mb} MB free"
            if self.free_memory_mb is not None
            else "free unknown"
        )
        total = (
            f"{self.total_memory_mb} MB"
            if self.total_memory_mb is not None
            else "no VRAM"
        )
        return (
            f"{self.backend}:{self.index} {self.name} | {total} | {free} | "
            f"{self.device_string}"
        )


def _run_vulkaninfo_summary(timeout: float = 10.0) -> Optional[str]:
    """Return stdout of ``vulkaninfo --summary`` or None if unavailable."""
    if shutil.which("vulkaninfo") is None:
        return None
    try:
        result = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
        log.warning("vulkaninfo --summary exited %s", result.returncode)
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("vulkaninfo --summary failed: %s", exc)
        return None


def _parse_vulkaninfo_summary(text: str) -> List[Device]:
    """Parse ``vulkaninfo --summary`` into Vulkan Device records.

    Only discrete and integrated GPUs are kept. Later devices that share
    a deviceUUID are dropped so one physical GPU is not listed twice.
    """
    devices: List[Device] = []
    seen_uuids: List[str] = []
    pattern = r"^\s*GPU(\d+):\s*\n(.*?)(?=^\s*GPU\d+:\s*$|\Z)"
    for index_text, block in re.findall(pattern, text, flags=re.MULTILINE | re.DOTALL):
        fields = dict(
            re.findall(r"^\s*(\w+)\s*=\s*(.+?)\s*$", block, flags=re.MULTILINE)
        )
        if fields.get("deviceType") not in LLAMA_VULKAN_DEVICE_TYPES:
            continue
        uuid = fields.get("deviceUUID")
        if uuid is not None and uuid in seen_uuids:
            continue
        if uuid is not None:
            seen_uuids.append(uuid)
        index = int(index_text)
        raw = fields.get("vendorID")
        vendor_id = (
            int(raw, 16)
            if raw and re.fullmatch(r"0x[0-9a-fA-F]+", raw)
            else None
        )
        vendor = PCI_VENDOR_IDS.get(vendor_id) if vendor_id is not None else None
        name = fields.get("deviceName") or f"Vulkan GPU {index}"
        devices.append(
            Device(
                index=index,
                name=name,
                vendor=vendor,
                backend="vulkan",
                total_memory_mb=None,
                free_memory_mb=None,
                device_string=f"vulkan:{index}",
            )
        )
    return devices


def _discover_cuda() -> List[Device]:
    """Return CUDA devices when torch.cuda is available, else empty."""
    devices: List[Device] = []
    try:
        import torch
    except ImportError:
        return devices
    if not torch.cuda.is_available():
        return devices
    count = torch.cuda.device_count()
    log.info("Discovered %d CUDA device(s)", count)
    for i in range(count):
        props = torch.cuda.get_device_properties(i)
        free, total = (
            torch.cuda.mem_get_info(i)
            if hasattr(torch.cuda, "mem_get_info")
            else (None, None)
        )
        devices.append(
            Device(
                index=i,
                name=props.name,
                vendor="nvidia",
                backend="cuda",
                total_memory_mb=props.total_memory // (1024 * 1024),
                free_memory_mb=free // (1024 * 1024) if free is not None else None,
                device_string=f"cuda:{i}",
            )
        )
    return devices


def discover_devices() -> List[Device]:
    """Discover Vulkan GPUs, CUDA devices, and a CPU fallback.

    Vulkan devices are listed first when ``vulkaninfo`` succeeds, so an
    AMD RX 6700 (or any other Vulkan GPU) appears even when CUDA is
    absent. CUDA devices follow. CPU is always present.

    Returns:
        List of Device records. Empty only if every probe failed and the
        CPU entry could not be built (never expected).
    """
    devices: List[Device] = []

    summary = _run_vulkaninfo_summary()
    if summary:
        vulkan_devs = _parse_vulkaninfo_summary(summary)
        devices.extend(vulkan_devs)
        log.info("Discovered %d Vulkan GPU(s)", len(vulkan_devs))
    else:
        log.info("vulkaninfo unavailable; Vulkan devices not listed")

    devices.extend(_discover_cuda())

    devices.append(
        Device(
            index=0,
            name="CPU",
            vendor=None,
            backend="cpu",
            total_memory_mb=None,
            free_memory_mb=None,
            device_string="cpu",
        )
    )
    return devices


def preferred_device(devices: Optional[List[Device]] = None) -> str:
    """Return the preferred device string for inference.

    Preference order: first Vulkan device, else first CUDA device, else
    CPU. Pass a pre-computed list or leave None to discover.
    """
    if devices is None:
        devices = discover_devices()
    for d in devices:
        if d.backend == "vulkan":
            return d.device_string
    for d in devices:
        if d.backend == "cuda":
            return d.device_string
    return "cpu"


# Backward-compatible name used by older call sites.
def discover_dies() -> List[Device]:
    """Alias for discover_devices. Existing K80 call sites continue to work."""
    return discover_devices()
