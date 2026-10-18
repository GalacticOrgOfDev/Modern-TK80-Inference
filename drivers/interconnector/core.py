"""Core interconnector for the Tesla K80 remaster.

Provides a modern interface:
- Device discovery and die tracking
- Explicit model placement and dual-die split modes
- Translation of modern request formats
- Thermal and performance monitoring
- Hybrid cluster advertisement
- Modality routing: LLM, image, voice, agent (video placeholder)

Runs on top of the R470 driver + CUDA 11.8 baseline.
Single-die models for now; dual-die unification later.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Union

from tk80.backends import create_backend

from .cluster import advertise
from .devices import K80Die, discover_dies
from .modalities import AgentBackend, ImageBackend, VoiceBackend
from .monitor import PerfTimer, read_all_metrics
from .split import plan_split
from .translate import translate_request

log = logging.getLogger("tk80.interconnector")

_IMAGE_KEYS = {"num_inference_steps", "guidance_scale", "height", "width", "negative_prompt", "num_images_per_prompt"}


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
        self._modality: Dict[int, str] = {}  # die index -> modality name
        self._last_perf: Dict[int, Dict[str, Any]] = {}
        log.info("Interconnector ready with %d die(s)", len(self.dies))
        for d in self.dies:
            log.info("  %s", d)

    def loaded_dies(self) -> List[int]:
        """Indices of dies that currently have a model."""
        return list(self._models.keys())

    def modality_of(self, die: int) -> Optional[str]:
        """Return the modality loaded on a die, or None."""
        return self._modality.get(die)

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
                    "modality": self._modality.get(d.index),
                }
                for d in self.dies
            ],
            "metrics": metrics,
            "models_loaded": list(self._models.keys()),
            "last_perf": self._last_perf,
        }

    def advertise(self, node_name: str = "") -> Dict[str, Any]:
        """Hybrid cluster advertisement."""
        base = advertise(self.dies, list(self._models.keys()), node_name=node_name)
        base["capabilities"]["modalities"] = ["llm", "image", "voice", "agent"]
        return base

    def load(
        self,
        model: str,
        backend: str = "llama",
        modality: str = "llm",
        die: Optional[int] = None,
        split: str = "single",
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
    ) -> None:
        """Load a model. modality is llm, image, voice, or agent."""
        free = self.free_dies()
        if die is not None:
            free = [die] if die in free else []

        if modality != "llm" and split == "layer":
            raise InterconnectorError("layer split is only supported for LLM modality")

        plan = plan_split(split, free, backend)

        # Layer split: one llama instance, both dies marked busy.
        if plan["mode"] == "layer":
            primary = plan["dies"][0]
            if primary in self._models:
                raise InterconnectorError(f"Die {primary} already has a model loaded")
            kwargs = {
                "main_gpu": primary,
                "n_gpu_layers": n_gpu_layers,
                "n_ctx": n_ctx,
                "split_mode": 1,
            }
            log.info("Loading %s as layer-split LLM (primary die %d)", model, primary)
            instance = create_backend("llama", model, **kwargs)
            for target in plan["dies"]:
                self._models[target] = instance
                self._modality[target] = "llm"
                for d in self.dies:
                    if d.index == target:
                        d.busy = True
                        break
            log.info("Layer-split model loaded on dies %s", plan["dies"])
            return

        for target in plan["dies"]:
            if target in self._models:
                raise InterconnectorError(f"Die {target} already has a model loaded")

            device = f"cuda:{target}"
            loaded: Any = None

            if modality == "llm":
                load_kwargs: Dict[str, Any] = {}
                if backend == "llama":
                    load_kwargs["main_gpu"] = target
                    load_kwargs["n_gpu_layers"] = n_gpu_layers
                    load_kwargs["n_ctx"] = n_ctx
                    load_kwargs["split_mode"] = 0
                elif backend == "pytorch":
                    load_kwargs["device"] = device
                else:
                    raise InterconnectorError(f"unknown backend: {backend}")
                loaded = create_backend(backend, model, **load_kwargs)

            elif modality == "image":
                loaded = ImageBackend(model, device=device)

            elif modality == "voice":
                loaded = VoiceBackend(model, device=device)

            elif modality == "agent":
                if backend == "pytorch":
                    llm = create_backend("pytorch", model, device=device)
                else:
                    llm = create_backend(
                        "llama",
                        model,
                        main_gpu=target,
                        n_gpu_layers=n_gpu_layers,
                        n_ctx=n_ctx,
                        split_mode=0,
                    )
                loaded = AgentBackend(llm)

            else:
                raise InterconnectorError(f"Unknown modality: {modality}")

            log.info("Loading %s on die %d (modality=%s)", model, target, modality)
            self._models[target] = loaded
            self._modality[target] = modality

            for d in self.dies:
                if d.index == target:
                    d.busy = True
                    break

        log.info("Model loaded (mode=%s, dies=%s, modality=%s)", plan["mode"], plan["dies"], modality)

    def unload(self, die: int) -> None:
        """Unload the model from a die.

        If the same instance is shared across dies (layer split), all dies
        holding that instance are cleared.
        """
        if die not in self._models:
            raise InterconnectorError(f"No model on die {die}")

        instance = self._models[die]
        shared = [idx for idx, m in self._models.items() if m is instance]

        for idx in shared:
            del self._models[idx]
            self._modality.pop(idx, None)
            for d in self.dies:
                if d.index == idx:
                    d.busy = False
                    break

        log.info("Unloaded model from die(s) %s", shared)

    def generate(
        self,
        request: Union[str, Dict[str, Any]],
        die: Optional[int] = None,
    ) -> Any:
        """Route to the correct modality on the chosen die."""
        if not self._models:
            raise InterconnectorError("No models loaded")

        if die is None:
            if len(self._models) != 1:
                raise InterconnectorError("Multiple models loaded; specify die")
            die = next(iter(self._models))

        if die not in self._models:
            raise InterconnectorError(f"No model on die {die}")

        modality = self._modality.get(die, "llm")
        backend = self._models[die]

        timer = PerfTimer()
        timer.begin()

        if modality == "llm":
            translated = translate_request(request)
            result = backend.generate(
                translated["prompt"],
                max_tokens=translated["max_tokens"],
                temperature=translated["temperature"],
            )
            approx = max(1, len(str(result).split()))

        elif modality == "image":
            prompt = request if isinstance(request, str) else request.get("prompt", "")
            extra = {}
            if isinstance(request, dict):
                extra = {k: v for k, v in request.items() if k in _IMAGE_KEYS}
            result = backend.generate(prompt, **extra)
            approx = 1

        elif modality == "voice":
            audio = request if isinstance(request, str) else request.get("audio", request.get("path", ""))
            result = backend.generate(audio)
            approx = max(1, len(str(result).split()))

        elif modality == "agent":
            goal = request if isinstance(request, str) else request.get("goal", request.get("prompt", ""))
            tools = request.get("tools") if isinstance(request, dict) else None
            runner: Optional[Callable[..., Any]] = None
            tool_prompt = ""
            if isinstance(request, dict):
                runner = request.get("tool_runner")
                tool_prompt = request.get("tool_prompt", "")
            result = backend.run(goal, tools=tools, tool_runner=runner, tool_prompt=tool_prompt)
            approx = 1

        else:
            raise InterconnectorError(f"Unsupported modality: {modality}")

        timer.end(tokens=approx)
        self._last_perf[die] = timer.report()
        log.info("Die %d (%s): %s", die, modality, self._last_perf[die])
        return result

    def free_dies(self) -> List[int]:
        """Return indices of dies that do not currently have a model."""
        return [d.index for d in self.dies if d.index not in self._models]
