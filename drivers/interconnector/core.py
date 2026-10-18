"""Core interconnector for the Tesla K80 remaster.

Provides a modern interface:
- Device discovery and die tracking
- Explicit model placement and dual-die split modes
- Translation of modern request formats
- Thermal and performance monitoring
- Hybrid cluster advertisement

Runs on top of the R470 driver + CUDA 11.8 baseline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from tk80.backends import create_backend

from .cluster import advertise
from .devices import K80Die, discover_dies
from .monitor import PerfTimer, read_all_metrics
from .split import plan_split
from .translate import translate_request

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
        self._last_perf: Dict[int, Dict[str, Any]] = {}
        log.info("Interconnector ready with %d die(s)", len(self.dies))
        for d in self.dies:
            log.info("  %s", d)

    def status(self) -> Dict[str, Any]:
        """Return a snapshot suitable for hybrid cluster monitoring."""
        metrics = read_all_metrics([d.index for d in self.dies])
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
            "metrics": metrics,
            "models_loaded": list(self._models.keys()),
            "last_perf": self._last_perf,
        }

    def advertise(self, node_name: str = "") -> Dict[str, Any]:
        """Hybrid cluster advertisement."""
        return advertise(self.dies, list(self._models.keys()), node_name=node_name)

    def load(
        self,
        model: str,
        backend: str = "llama",
        die: Optional[int] = None,
        split: str = "single",
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
    ) -> None:
        """Load a model. split is 'single', 'dual', or 'layer'."""
        free = self.free_dies()
        if die is not None:
            free = [die] if die in free else []

        plan = plan_split(split, free, backend)

        for target in plan["dies"]:
            if target in self._models:
                raise InterconnectorError(f"Die {target} already has a model loaded")

            kwargs: Dict[str, Any] = {}
            if backend == "llama":
                kwargs["main_gpu"] = target
                kwargs["n_gpu_layers"] = n_gpu_layers
                kwargs["n_ctx"] = n_ctx
                if plan["mode"] == "layer":
                    # Experimental: signal multi-GPU intent; actual split depends on llama.cpp build
                    kwargs["split_mode"] = 1
            elif backend == "pytorch":
                kwargs["device"] = f"cuda:{target}"
            else:
                raise InterconnectorError(f"Unknown backend: {backend}")

            log.info("Loading %s on die %d via %s (mode=%s)", model, target, backend, plan["mode"])
            self._models[target] = create_backend(backend, model, **kwargs)

            for d in self.dies:
                if d.index == target:
                    d.busy = True
                    break

        log.info("Model loaded (mode=%s, dies=%s)", plan["mode"], plan["dies"])

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
        request: Union[str, Dict[str, Any]],
        die: Optional[int] = None,
    ) -> str:
        """Generate text from a plain prompt or modern request dict."""
        if not self._models:
            raise InterconnectorError("No models loaded")

        translated = translate_request(request)
        prompt = translated["prompt"]
        max_tokens = translated["max_tokens"]
        temperature = translated["temperature"]

        if die is None:
            if len(self._models) != 1:
                raise InterconnectorError("Multiple models loaded; specify die")
            die = next(iter(self._models))

        if die not in self._models:
            raise InterconnectorError(f"No model on die {die}")

        timer = PerfTimer()
        timer.begin()
        backend = self._models[die]
        result = backend.generate(prompt, max_tokens=max_tokens, temperature=temperature)
        # Approximate token count for performance reporting
        approx_tokens = max(1, len(result.split()))
        timer.end(tokens=approx_tokens)
        self._last_perf[die] = timer.report()
        log.info("Die %d: %s", die, self._last_perf[die])

        return result

    def free_dies(self) -> List[int]:
        """Return indices of dies that do not currently have a model."""
        return [d.index for d in self.dies if d.index not in self._models]
