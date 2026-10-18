#!/usr/bin/env python3
"""
Modern-TK80-Inference Engine

Entry point for a modern inference engine targeting the NVIDIA Tesla K80.

Hardware notes:
- Architecture: Kepler (GK210)
- Compute capability: 3.7 (sm_37)
- Dual independent GPUs (12 GB GDDR5 each, not unified)
- Last supported CUDA Toolkit: 11.8
- No Tensor Cores; FP32 preferred

Backends:
- llama-cpp-python (CUDA build targeting sm_37) for GGUF models
- PyTorch (cu118) for Hugging Face models

Inspired by PoliSim's core.inference patterns (engine + device selection)
but adapted for CUDA / dual K80 dies.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, List, Optional

from tk80.backends import create_backend

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
    """Discover CUDA devices via PyTorch."""
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
        log.warning("PyTorch not installed. Device discovery limited.")

    return devices


def validate_k80(devices: List[K80Device]) -> bool:
    """Return True if at least one K80 (or sm_37) device is present."""
    k80s = [d for d in devices if d.is_k80]
    if not k80s:
        log.warning("No Tesla K80 / compute capability 3.7 devices detected.")
        if devices:
            for d in devices:
                log.info("  %s", d)
        return False

    log.info("Detected %d K80-compatible device(s):", len(k80s))
    for d in k80s:
        log.info("  %s", d)
    return True


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class TK80InferenceEngine:
    """Inference engine for Tesla K80 with llama.cpp and PyTorch backends."""

    def __init__(self, devices: List[K80Device], device_ids: Optional[List[int]] = None):
        self.devices = devices
        self.active_ids = device_ids if device_ids is not None else [d.index for d in devices]
        self.backend: Any = None
        log.info("Engine initialized with device IDs: %s", self.active_ids)

    def load_model(self, model_path: str, backend: str = "llama", main_gpu: int = 0) -> None:
        """Load a model using the requested backend."""
        if backend == "llama" and not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        kwargs = {}
        if backend == "llama":
            kwargs["main_gpu"] = main_gpu
            kwargs["n_gpu_layers"] = -1
        elif backend == "pytorch":
            kwargs["device"] = f"cuda:{main_gpu}"

        self.backend = create_backend(backend, model_path, **kwargs)
        log.info("Model loaded with %s backend", backend)

    def infer(self, prompt: str, max_tokens: int = 128, temperature: float = 0.7) -> str:
        if self.backend is None:
            return "[no model loaded]"
        return self.backend.generate(prompt, max_tokens=max_tokens, temperature=temperature)

    def status(self) -> None:
        log.info("--- TK80 Inference Engine Status ---")
        log.info("Active devices: %s", self.active_ids)
        for d in self.devices:
            if d.index in self.active_ids:
                log.info("  %s", d)
        log.info("Backend loaded: %s", self.backend is not None)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Modern-TK80-Inference — Tesla K80 inference engine"
    )
    parser.add_argument("--devices", type=str, default=None, help="Comma-separated CUDA device indices")
    parser.add_argument("--model", type=str, default=None, help="Path to GGUF or Hugging Face model")
    parser.add_argument("--backend", type=str, default="llama", choices=["llama", "pytorch"], help="Backend to use")
    parser.add_argument("--main-gpu", type=int, default=0, help="Primary GPU index for the model")
    parser.add_argument("--prompt", type=str, default=None, help="Prompt to run")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    log.info("Modern-TK80-Inference starting")
    log.info("Target: NVIDIA Tesla K80 (Kepler sm_37) | CUDA 11.8")

    devices = discover_devices()
    if not devices:
        log.error("No CUDA devices found. Install CUDA 11.8 + PyTorch cu118.")
        return 1

    validate_k80(devices)

    selected: Optional[List[int]] = None
    if args.devices:
        try:
            selected = [int(x.strip()) for x in args.devices.split(",") if x.strip()]
        except ValueError:
            log.error("Invalid --devices value.")
            return 1

    engine = TK80InferenceEngine(devices, selected)

    if args.status and not args.model:
        engine.status()
        return 0

    if args.model:
        try:
            engine.load_model(args.model, backend=args.backend, main_gpu=args.main_gpu)
        except Exception as e:
            log.error("Failed to load model: %s", e)
            return 1

    if args.prompt:
        result = engine.infer(args.prompt, max_tokens=args.max_tokens, temperature=args.temperature)
        print(result)
        return 0

    engine.status()
    log.info("Engine ready. Use --prompt to run inference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
