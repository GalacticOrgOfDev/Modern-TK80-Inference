"""Tesla K80 die discovery and management.

The K80 is two independent GPUs (12 GB each). This module treats them
as separate dies and never assumes unified memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("tk80.interconnector.devices")


@dataclass
class K80Die:
    """One die of a Tesla K80 (or compatible Kepler device)."""

    index: int
    name: str
    total_memory_mb: int
    free_memory_mb: Optional[int]
    compute_capability: tuple[int, int]
    busy: bool = False

    @property
    def is_k80(self) -> bool:
        """future docstring"""
        return "K80" in self.name.upper() or self.compute_capability == (3, 7)

    def __str__(self) -> str:
        """future docstring"""
        cc = f"{self.compute_capability[0]}.{self.compute_capability[1]}"
        free = f"{self.free_memory_mb} MB free" if self.free_memory_mb is not None else "free unknown"
        state = "BUSY" if self.busy else "free"
        return f"Die {self.index}: {self.name} | {self.total_memory_mb} MB | {free} | CC {cc} | {state}"


def discover_dies() -> List[K80Die]:
    """Discover CUDA devices and return them as K80Die objects."""
    dies: List[K80Die] = []

    try:
        import torch
    except ImportError:
        log.warning("PyTorch not available; device discovery skipped")
        return dies

    if not torch.cuda.is_available():
        log.warning("CUDA not available")
        return dies

    count = torch.cuda.device_count()
    log.info("Discovered %d CUDA device(s)", count)

    for i in range(count):
        props = torch.cuda.get_device_properties(i)
        free, total = torch.cuda.mem_get_info(i) if hasattr(torch.cuda, "mem_get_info") else (None, None)
        dies.append(
            K80Die(
                index=i,
                name=props.name,
                total_memory_mb=props.total_memory // (1024 * 1024),
                free_memory_mb=free // (1024 * 1024) if free is not None else None,
                compute_capability=(props.major, props.minor),
            )
        )

    return dies
