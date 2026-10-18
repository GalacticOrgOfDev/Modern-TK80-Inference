"""Modality backends for smaller models that fit on one K80 die (12 GB FP32).

Supported now (single-die):
- image: Stable Diffusion 1.5-class via diffusers
- voice: Whisper-small-class ASR
- agent: simple multi-step loop on top of an LLM backend

Video is acknowledged but left as a constrained placeholder; most video models
exceed a single 12 GB die.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("tk80.interconnector.modalities")


def _device_index(device: str) -> int:
    """Turn 'cuda:0' into 0. Falls back to 0."""
    if isinstance(device, int):
        return device
    if isinstance(device, str) and device.startswith("cuda:"):
        try:
            return int(device.split(":", 1)[1])
        except (IndexError, ValueError):
            return 0
    return 0


class ImageBackend:
    """Small diffusion model (e.g. SD 1.5) on one die, FP32."""

    def __init__(self, model_name_or_path: str, device: str = "cuda:0"):
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as exc:
            raise RuntimeError("diffusers + torch required for image backend") from exc

        self.device = device
        log.info("Loading image model on %s: %s", device, model_name_or_path)
        self.pipe = StableDiffusionPipeline.from_pretrained(
            model_name_or_path,
            torch_dtype=torch.float32,
            safety_checker=None,
        ).to(device)

    def generate(self, prompt: str, **kwargs: Any) -> Any:
        result = self.pipe(prompt, **kwargs)
        return result.images[0] if hasattr(result, "images") else result


class VoiceBackend:
    """Small ASR (Whisper-class) on one die."""

    def __init__(self, model_name_or_path: str, device: str = "cuda:0"):
        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise RuntimeError("transformers + torch required for voice backend") from exc

        self.device = device
        dev_idx = _device_index(device)
        log.info("Loading voice model on %s (index %d): %s", device, dev_idx, model_name_or_path)
        # transformers pipeline expects an int device index in most versions
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_name_or_path,
            device=dev_idx,
            torch_dtype=torch.float32,
        )

    def generate(self, audio_path: str, **kwargs: Any) -> str:
        if not audio_path:
            raise ValueError("voice generate requires an audio path")
        result = self.pipe(audio_path, **kwargs)
        return result.get("text", str(result)) if isinstance(result, dict) else str(result)


class AgentBackend:
    """Simple agentic loop over an already-loaded LLM backend."""

    def __init__(self, llm_backend: Any, max_steps: int = 4):
        self.llm = llm_backend
        self.max_steps = max_steps

    def run(self, goal: str, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Very small ReAct-style loop. Tools are described in the prompt."""
        if not goal:
            raise ValueError("agent run requires a goal")
        tools = tools or []
        tool_desc = "\n".join(
            f"- {t.get('name', 'unnamed')}: {t.get('description', '')}" for t in tools
        )
        history = [f"Goal: {goal}"]
        if tool_desc:
            history.append(f"Available tools:\n{tool_desc}")

        steps: List[str] = []
        for _ in range(self.max_steps):
            prompt = "\n".join(history) + "\n\nNext action (Thought / Action / or Final):"
            reply = self.llm.generate(prompt, max_tokens=256, temperature=0.3)
            steps.append(reply)
            history.append(reply)
            if "Final:" in reply or "final:" in reply.lower():
                break

        return {"goal": goal, "steps": steps, "result": steps[-1] if steps else ""}


class VideoBackend:
    """Placeholder. Most video models exceed one 12 GB K80 die."""

    def __init__(self, *args: Any, **kwargs: Any):
        raise NotImplementedError(
            "Video models generally exceed a single 12 GB K80 die. "
            "Smaller frame-by-frame or latent models can be added later."
        )
