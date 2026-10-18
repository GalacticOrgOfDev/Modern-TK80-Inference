"""Core interconnector for the Tesla K80 remaster.

Provides a modern interface:
- Device discovery and die tracking
- Explicit model placement on one die (or future split)
- generate() that routes to the chosen backend
- Status reporting for hybrid cluster use

Runs on top of the R470 driver + CUDA 11.8 baseline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from tk80.backends import create_backend

from .devices import K80Die, discover_dies

log = logging.getLogger("tk80.interconnector")


class InterconnectorError(Exception):
    """Base error for the interconnector."""


class Interconnector:
    """Modern interface to one or more Tesla K80 dies."""

    def __init__(self, die_indices: Optional[List[int]] = None):
        self.dies: List[K80Die] = discover_dies()
        if not self.dies:
            raise InterconnectorError("No CUDA devices found. Install R470 driver + CUDA 11.8.")

        if die_indices is not None:
            valid = {d.index for d in self.dies}
            missing = [i for i in die_indices if i not in valid]
            if missing:
                raise InterconnectorError(f"Requested dies not present: {missing}")
            self.dies = [d for d in self.dies if d.index in die_indices]

        self._models: Dict[int, Any] = {}  # die index -> backend instance
        log.info("Interconnector ready with %d die(s)", len(self.dies))
        for d in self.dies:
            log.info("  %s", d)

    def status(self) -> Dict[str, Any]:
        """Return a snapshot suitable for hybrid cluster monitoring."""
        return {
            "dies": [
                {
                    "index": d.index,
                    "name": d.name,
                    "total_mb": d.total_memory_mb,
                    "free_mb": d.free_memory_mb,
                    "cc": f"{d.compute_capability[0]}.{d.compute_capability[1]}",
                    "busy": d.busy,
                    "model_loaded": d.index in self._models,
                }
                for d in self.dies
            ],
            "models_loaded": list(self._models.keys()),
        }

    def load(
        self,
        model: str,
        backend: str = "llama",
        die: int = 0,
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
    ) -> None:
        """Load a model onto a specific die."""
        if die not in {d.index for d in self.dies}:
            raise InterconnectorError(f"Die {die} is not managed by this interconnector")

        if die in self._models:
            raise InterconnectorError(f"Die {die} already has a model loaded")

        kwargs: Dict[str, Any] = {}
        if backend == "llama":
            kwargs["main_gpu"] = die
            kwargs["n_gpu_layers"] = n_gpu_layers
            kwargs["n_ctx"] = n_ctx
        elif backend == "pytorch":
            kwargs["device"] = f"cuda:{die}"
        else:
            raise InterconnectorError(f"Unknown backend: {backend}")

        log.info("Loading %s on die %d via %s", model, die, backend)
        self._models[die] = create_backend(backend, model, **kwargs)

        for d in self.dies:
            if d.index == die:
                d.busy = True
                break

        log.info("Model loaded on die %d", die)

    def unload(self, die: int) -> None:
        """Unload the model from a die."""
        if die not in self._models:
            raise InterconnectorError(f"No model on die {die}")

        del self._models[die]
        for d in self.dies:
            if d.index == die:
                d.busy = False
                break
        log.info("Unloaded model from die %d", die)

    def generate(
        self,
        prompt: str,
        die: Optional[int] = None,
        max_tokens: int = 128,
        temperature: float = 0.7,
    ) -> str:
        """Generate text. Uses the only loaded model if die is None."""
        if not self._models:
            raise InterconnectorError("No models loaded")

        if die is None:
            if len(self._models) != 1:
                raise InterconnectorError("Multiple models loaded; specify die")
            die = next(iter(self._models))

        if die not in self._models:
            raise InterconnectorError(f"No model on die {die}")

        backend = self._models[die]
        return backend.generate(prompt, max_tokens=max_tokens, temperature=temperature)

    def free_dies(self) -> List[int]:
        """Return indices of dies that do not currently have a model."""
        return [d.index for d in self.dies if d.index not in self._models]
