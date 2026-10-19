"""Thermal and performance monitoring for K80 dies."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("tk80.interconnector.monitor")


def read_die_metrics(die_index: int) -> Dict[str, Any]:
    """Read temperature, utilization, and memory for one die if available."""
    metrics: Dict[str, Any] = {"index": die_index}

    try:
        import torch
    except ImportError:
        return metrics

    if not torch.cuda.is_available():
        return metrics

    try:
        free, total = torch.cuda.mem_get_info(die_index)
        metrics["free_mb"] = free // (1024 * 1024)
        metrics["total_mb"] = total // (1024 * 1024)
    except Exception:
        pass

    # Temperature and utilization require nvidia-ml-py or similar; best-effort.
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(die_index)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        power = pynvml.nvmlDeviceGetPowerUsage(handle)  # mW
        metrics["temp_c"] = temp
        metrics["util_gpu"] = util.gpu
        metrics["util_mem"] = util.memory
        metrics["power_w"] = power / 1000.0
    except Exception:
        # pynvml not installed or no permission — leave metrics partial
        pass

    return metrics


def read_all_metrics(die_indices: List[int]) -> List[Dict[str, Any]]:
    """future docstring"""
    return [read_die_metrics(i) for i in die_indices]


class PerfTimer:
    """Simple wall-clock timer for inference performance."""

    def __init__(self) -> None:
        """future docstring"""
        self.start: Optional[float] = None
        self.elapsed: float = 0.0
        self.tokens: int = 0

    def begin(self) -> None:
        """future docstring"""
        self.start = time.perf_counter()

    def end(self, tokens: int = 0) -> None:
        """future docstring"""
        if self.start is not None:
            self.elapsed = time.perf_counter() - self.start
            self.tokens = tokens
            self.start = None

    def tokens_per_sec(self) -> float:
        """future docstring"""
        if self.elapsed <= 0 or self.tokens <= 0:
            return 0.0
        return self.tokens / self.elapsed

    def report(self) -> Dict[str, Any]:
        """future docstring"""
        return {
            "elapsed_s": round(self.elapsed, 3),
            "tokens": self.tokens,
            "tokens_per_sec": round(self.tokens_per_sec(), 2),
        }
