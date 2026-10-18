#!/usr/bin/env python3
"""
Modern-TK80-Inference Engine

Entry point for a modern inference engine targeting the NVIDIA Tesla K80.

Hardware notes:
- Architecture: Kepler (GK210)
- Compute capability: 3.7 (sm_37)
- Dual independent GPUs (12 GB GDDR5 each, not unified)
- Last supported CUDA Toolkit: 11.8
- No Tensor Cores; FP32 preferred; limited FP16 via software

This module provides:
- K80 device discovery and validation
- Basic multi-device awareness
- Skeleton for model loading and inference
- Extensible hooks for custom CUDA kernels or llama.cpp / PyTorch backends
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tk80")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class K80Device:
    """Represents one die of a Tesla K80 (or compatible Kepler device)."""

    index: int
    name: str
    total_memory_mb: int
    compute_capability: tuple[int, int]

    @property
    def is_k80(self) -> bool:
        return "K80" in self.name.upper() or self.compute_capability == (3, 7)

    def __str__(self) -> str:
        cc = f"{self.compute_capability[0]}.{self.compute_capability[1]}"
        return f"GPU {self.index}: {self.name} | {self.total_memory_mb} MB | CC {cc}"


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------
def discover_devices() -> List[K80Device]:
    """
    Discover CUDA devices. Prefers PyTorch if available; falls back to a
    warning if the environment is not yet set up.
    """
    devices: List[K80Device] = []

    try:
        import torch

        if not torch.cuda.is_available():
            log.warning("PyTorch reports CUDA is not available.")
            return devices

        count = torch.cuda.device_count()
        log.info("Found %d CUDA device(s) via PyTorch.", count)

        for i in range(count):
            props = torch.cuda.get_device_properties(i)
            devices.append(
                K80Device(
                    index=i,
                    name=props.name,
                    total_memory_mb=props.total_memory // (1024 * 1024),
                    compute_capability=(props.major, props.minor),
                )
            )
    except ImportError:
        log.warning(
            "PyTorch not installed. Install a CUDA 11.8-compatible build "
            "(e.g. torch with cu118) to enable device discovery."
        )

    return devices


def validate_k80(devices: List[K80Device]) -> bool:
    """Return True if at least one K80 (or sm_37) device is present."""
    k80s = [d for d in devices if d.is_k80]
    if not k80s:
        log.warning("No Tesla K80 / compute capability 3.7 devices detected.")
        if devices:
            log.info("Detected devices:")
            for d in devices:
                log.info("  %s", d)
        return False

    log.info("Detected %d K80-compatible device(s):", len(k80s))
    for d in k80s:
        log.info("  %s", d)
    return True


# ---------------------------------------------------------------------------
# Engine skeleton
# ---------------------------------------------------------------------------
class TK80InferenceEngine:
    """
    Core inference engine for Tesla K80.

    Currently a skeleton. Extend with:
    - llama.cpp bindings (compiled for sm_37)
    - PyTorch models (older versions compatible with CUDA 11.8)
    - Custom CUDA kernels targeting sm_37
    - Dual-GPU orchestration (independent or layer-split)
    """

    def __init__(self, devices: List[K80Device], device_ids: Optional[List[int]] = None):
        self.devices = devices
        self.active_ids = device_ids if device_ids is not None else [d.index for d in devices]
        log.info("Engine initialized with device IDs: %s", self.active_ids)

    def load_model(self, model_path: str) -> None:
        """Placeholder for model loading."""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        log.info("Model load requested: %s (stub — implement backend)", model_path)

    def infer(self, prompt: str, max_tokens: int = 128) -> str:
        """Placeholder inference."""
        log.info("Inference requested (stub): prompt length=%d, max_tokens=%d", len(prompt), max_tokens)
        return "[TK80InferenceEngine stub] Implement model backend to produce output."

    def status(self) -> None:
        """Print current engine status."""
        log.info("--- TK80 Inference Engine Status ---")
        log.info("Active devices: %s", self.active_ids)
        for d in self.devices:
            if d.index in self.active_ids:
                log.info("  %s", d)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Modern-TK80-Inference — Tesla K80 inference engine"
    )
    parser.add_argument(
        "--devices",
        type=str,
        default=None,
        help="Comma-separated CUDA device indices to use (default: all detected)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to model file (optional; engine can start without a model)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Run a single inference prompt and exit",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=128,
        help="Maximum tokens to generate (default: 128)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print device and engine status and exit",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    log.info("Modern-TK80-Inference starting")
    log.info("Target: NVIDIA Tesla K80 (Kepler sm_37) | CUDA 11.8")

    devices = discover_devices()
    if not devices:
        log.error("No CUDA devices found. Install CUDA 11.8 and a compatible PyTorch build.")
        return 1

    has_k80 = validate_k80(devices)
    if not has_k80:
        log.warning("Continuing without confirmed K80 hardware (useful for development).")

    # Select devices
    selected: Optional[List[int]] = None
    if args.devices:
        try:
            selected = [int(x.strip()) for x in args.devices.split(",") if x.strip()]
        except ValueError:
            log.error("Invalid --devices value. Use comma-separated integers.")
            return 1

    engine = TK80InferenceEngine(devices, selected)

    if args.status or not args.model:
        engine.status()
        if args.status:
            return 0

    if args.model:
        try:
            engine.load_model(args.model)
        except FileNotFoundError as e:
            log.error(str(e))
            return 1

    if args.prompt:
        result = engine.infer(args.prompt, max_tokens=args.max_tokens)
        print(result)
        return 0

    log.info("Engine ready. No prompt supplied — idle mode.")
    log.info("Use --prompt '...' to run inference once a backend is implemented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
