"""Core interconnector for Modern-TK80-Inference.

Provides a modern interface:
- Device discovery (Vulkan, CUDA, CPU)
- Explicit model placement
- Translation of modern request formats
- Modality routing: LLM, image, voice, agent

Device selection uses drivers.interconnector.devices.preferred_device so
an AMD RX 6700 (Vulkan) or any other reported GPU can be used for a
demo. Creator tools do not require a model.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Union

from tk80.backends import create_backend

from .cluster import advertise
from .devices import Device, discover_devices, preferred_device
from .modalities import AgentBackend, ImageBackend, VoiceBackend
from .monitor import PerfTimer, read_all_metrics
from .split import plan_split
from .translate import translate_request

log = logging.getLogger("tk80.interconnector")

_IMAGE_KEYS = {"num_inference_steps", "guidance_scale", "height", "width", "negative_prompt", "num_images_per_prompt"}


class InterconnectorError(Exception):
    """Base error for the interconnector."""


class Interconnector:
    """Modern interface to the devices reported on this machine."""

    def __init__(self, die_indices: Optional[List[int]] = None):
        """Discover devices and optionally restrict to a subset of indexes.

        Raises InterconnectorError only when no devices at all are reported
        (should not occur because CPU is always present).
        """
        self.devices: List[Device] = discover_devices()
        if not self.devices:
            raise InterconnectorError("No devices reported.")

        if die_indices is not None:
            valid = {d.index for d in self.devices}
            missing = [i for i in die_indices if i not in valid]
            if missing:
                raise InterconnectorError(f"Requested device indexes not present: {missing}")
            self.devices = [d for d in self.devices if d.index in die_indices]

        self.preferred = preferred_device(self.devices)
        self._models: Dict[int, Any] = {}  # device index -> backend instance
        self._modality: Dict[int, str] = {}  # device index -> modality name
        self._last_perf: Dict[int, Dict[str, Any]] = {}
        log.info("Interconnector ready. Preferred device: %s", self.preferred)
        for d in self.devices:
            log.info("  %s", d)

    def loaded_dies(self) -> List[int]:
        """Indexes of devices that currently have a model."""
        return list(self._models.keys())

    def modality_of(self, die: int) -> Optional[str]:
        """Return the modality loaded on a device index, or None."""
        return self._modality.get(die)

    def status(self) -> Dict[str, Any]:
        """Return a snapshot suitable for monitoring."""
        indexes = [d.index for d in self.devices]
        metrics = read_all_metrics(indexes)
        return {
            "devices": [
                {
                    "index": d.index,
                    "name": d.name,
                    "backend": d.backend,
                    "total_mb": d.total_memory_mb,
                    "free_mb": d.free_memory_mb,
                    "device_string": d.device_string,
                    "model_loaded": d.index in self._models,
                    "modality": self._modality.get(d.index),
                }
                for d in self.devices
            ],
            "preferred": self.preferred,
            "metrics": metrics,
            "models_loaded": list(self._models.keys()),
            "last_perf": self._last_perf,
        }

    def advertise(self, node_name: str = "") -> Dict[str, Any]:
        """Cluster advertisement."""
        base = advertise(self.devices, list(self._models.keys()), node_name=node_name)
        base["capabilities"]["modalities"] = ["llm", "image", "voice", "agent"]
        base["preferred_device"] = self.preferred
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
        """Load a model onto the preferred device or an explicit index.

        device_string from discovery is forwarded so a Vulkan build can
        offload to an AMD GPU. Creator tools do not call this method.
        """
        free = self.free_dies()
        if die is not None:
            free = [die] if die in free else []

        if modality != "llm" and split == "layer":
            raise InterconnectorError("layer split is only supported for LLM modality")

        plan = plan_split(split, free, backend)

        # Layer split: one llama instance, both targets marked busy.
        if plan["mode"] == "layer":
            primary = plan["dies"][0]
            if primary in self._models:
                raise InterconnectorError(f"Device {primary} already has a model loaded")
            kwargs = {
                "device_string": self.preferred,
                "n_gpu_layers": n_gpu_layers,
                "n_ctx": n_ctx,
                "split_mode": 1,
            }
            log.info("Loading %s as layer-split LLM (primary %d, device %s)", model, primary, self.preferred)
            instance = create_backend("llama", model, **kwargs)
            for target in plan["dies"]:
                self._models[target] = instance
                self._modality[target] = "llm"
            log.info("Layer-split model loaded on %s", plan["dies"])
            return

        for target in plan["dies"]:
            if target in self._models:
                raise InterconnectorError(f"Device {target} already has a model loaded")

            device_string = self.preferred
            loaded: Any = None

            if modality == "llm":
                load_kwargs: Dict[str, Any] = {"device_string": device_string}
                if backend == "llama":
                    load_kwargs["n_gpu_layers"] = n_gpu_layers
                    load_kwargs["n_ctx"] = n_ctx
                    load_kwargs["split_mode"] = 0
                loaded = create_backend(backend, model, **load_kwargs)

            elif modality == "image":
                loaded = ImageBackend(model, device=device_string)

            elif modality == "voice":
                loaded = VoiceBackend(model, device=device_string)

            elif modality == "agent":
                if backend == "pytorch":
                    llm = create_backend("pytorch", model, device_string=device_string)
                else:
                    llm = create_backend(
                        "llama",
                        model,
                        device_string=device_string,
                        n_gpu_layers=n_gpu_layers,
                        n_ctx=n_ctx,
                        split_mode=0,
                    )
                loaded = AgentBackend(llm)

            else:
                raise InterconnectorError(f"Unknown modality: {modality}")

            log.info("Loading %s on device %d (modality=%s, device=%s)", model, target, modality, device_string)
            self._models[target] = loaded
            self._modality[target] = modality

        log.info("Model loaded (mode=%s, devices=%s, modality=%s)", plan["mode"], plan["dies"], modality)

    def unload(self, die: int) -> None:
        """Unload the model from a device index.

        If the same instance is shared (layer split), all indexes holding
        that instance are cleared.
        """
        if die not in self._models:
            raise InterconnectorError(f"No model on device {die}")

        instance = self._models[die]
        shared = [idx for idx, m in self._models.items() if m is instance]

        for idx in shared:
            del self._models[idx]
            self._modality.pop(idx, None)

        log.info("Unloaded model from device(s) %s", shared)

    def generate(
        self,
        request: Union[str, Dict[str, Any]],
        die: Optional[int] = None,
    ) -> Any:
        """Route to the correct modality on the chosen device."""
        if not self._models:
            raise InterconnectorError("No models loaded")

        if die is None:
            if len(self._models) != 1:
                raise InterconnectorError("Multiple models loaded; specify die")
            die = next(iter(self._models))

        if die not in self._models:
            raise InterconnectorError(f"No model on device {die}")

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
        log.info("Device %d (%s): %s", die, modality, self._last_perf[die])
        return result

    def free_dies(self) -> List[int]:
        """Return indexes of devices that do not currently have a model."""
        return [d.index for d in self.devices if d.index not in self._models]
