"""Modality backends for smaller models that fit on one K80 die (12 GB FP32).

Supported now (single-die):
- image: Stable Diffusion 1.5-class via diffusers
- voice: Whisper-small-class ASR
- agent: tool-calling loop on top of an LLM backend

Video is acknowledged but left as a constrained placeholder; most video models
exceed a single 12 GB die.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("tk80.interconnector.modalities")

ToolRunner = Callable[[str, Dict[str, Any]], Dict[str, Any]]


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
        """future docstring"""
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as exc:
            raise RuntimeError("diffusers + torch required for image backend") from exc

        self.device = device
        log.info("Loading image model on %s: %s", device, model_name_or_path)
        self.pipe = StableDiffusionPipeline.from_pretrained(
            model_name_or_path,
            torch_dtype=getattr(torch, "float32"),
            safety_checker=None,
        ).to(device)

    def generate(self, prompt: str, **kwargs: Any) -> Any:
        """future docstring"""
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
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_name_or_path,
            device=dev_idx,
            torch_dtype=getattr(torch, "float32"),
        )

    def generate(self, audio_path: str, **kwargs: Any) -> str:
        """future docstring"""
        if not audio_path:
            raise ValueError("voice generate requires an audio path")
        result = self.pipe(audio_path, **kwargs)
        return result.get("text", str(result)) if isinstance(result, dict) else str(result)


class AgentBackend:
    """Tool-calling loop over an already-loaded LLM backend.

    The model emits `tool: <name> {json}` or `Final: <answer>`.
    A tool_runner callback executes the call and the result is fed back.
    """

    def __init__(self, llm_backend: Any, max_steps: int = 4):
        """future docstring"""
        self.llm = llm_backend
        self.max_steps = max_steps

    def run(
        self,
        goal: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_runner: Optional[ToolRunner] = None,
        tool_prompt: str = "",
    ) -> Dict[str, Any]:
        """future docstring"""
        if not goal:
            raise ValueError("agent run requires a goal")
        tools = tools or []
        tool_desc = tool_prompt or "\n".join(
            f"- {t.get('name', 'unnamed')}: {t.get('description', '')}" for t in tools
        )
        history = [f"Goal: {goal}"]
        if tool_desc:
            history.append(tool_desc)

        steps: List[Dict[str, Any]] = []
        final = ""
        for _ in range(self.max_steps):
            prompt = "\n".join(history) + "\n\nNext (tool: name {json} or Final: answer):"
            reply = self.llm.generate(prompt, max_tokens=256, temperature=0.3)
            step: Dict[str, Any] = {"reply": reply}
            steps.append(step)
            history.append(reply)

            if "Final:" in reply or "final:" in reply.lower():
                final = reply
                break

            call = _extract_call(reply)
            if call and tool_runner is not None:
                try:
                    result = tool_runner(call["name"], call.get("args", {}))
                except Exception as e:  # pragma: no cover
                    result = {"error": str(e)}
                step["tool"] = call
                step["result"] = result
                history.append(f"Tool result: {result}")
            elif call is None:
                # No tool and no Final: stop to avoid spinning.
                final = reply
                break

        return {
            "goal": goal,
            "steps": steps,
            "result": final or (steps[-1]["reply"] if steps else ""),
        }


def _extract_call(text: str) -> Optional[Dict[str, Any]]:
    """Local extractor so the interconnector does not import the app package."""
    import json
    import re

    match = re.search(r"tool\s*:\s*([a-z_]+)\s*(\{.*\})?", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    name = match.group(1).strip().lower()
    raw = match.group(2)
    args: Dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                args = parsed
        except Exception:
            args = {}
    return {"name": name, "args": args}


class VideoBackend:
    """Placeholder. Most video models exceed one 12 GB K80 die."""

    def __init__(self, *args: Any, **kwargs: Any):
        """future docstring"""
        raise NotImplementedError(
            "Video models generally exceed a single 12 GB K80 die. "
            "Smaller frame-by-frame or latent models can be added later."
        )
