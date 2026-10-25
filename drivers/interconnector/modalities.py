"""Modality backends for Modern-TK80-Inference.

Supported:
- image: Stable Diffusion 1.5-class via diffusers
- voice: Whisper-class ASR via transformers
- agent: tool-calling loop on top of an already-loaded LLM backend

Device selection uses the same device_string produced by
drivers.interconnector.devices ("vulkan:N", "cuda:N", or "cpu").
CUDA indexes are passed to torch. Vulkan and CPU both map to the CPU
device because diffusers and the transformers pipeline do not implement
a Vulkan compute path in this wrapper. Creator tools do not require
these backends.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("tk80.interconnector.modalities")

ToolRunner = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _torch_device(device_string: Optional[str]) -> str:
    """Map a discovery device_string to a torch device.

    "cuda:1" -> "cuda:1"
    "vulkan:0" or "cpu" or None -> "cpu"
    """
    if not device_string or device_string == "cpu":
        return "cpu"
    if device_string.startswith("cuda:"):
        return device_string
    return "cpu"


class ImageBackend:
    """Small diffusion model (e.g. SD 1.5).

    Accepts a device_string from discovery. Only a cuda:N string is placed
    on a GPU; vulkan:N and cpu run on CPU. The model path may be a local
    directory or a Hugging Face repo id.
    """

    def __init__(self, model_name_or_path: str, device: str = "cpu"):
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as exc:
            raise RuntimeError("diffusers + torch required for image backend") from exc

        self.device = _torch_device(device)
        self.device_string = device or "cpu"
        log.info("Loading image model on %s (requested %s): %s", self.device, self.device_string, model_name_or_path)
        self.pipe = StableDiffusionPipeline.from_pretrained(
            model_name_or_path,
            torch_dtype=torch.float32,
            safety_checker=None,
        ).to(self.device)

    def generate(self, prompt: str, **kwargs: Any) -> Any:
        """Generate an image. Returns the first PIL image or the raw result."""
        result = self.pipe(prompt, **kwargs)
        return result.images[0] if hasattr(result, "images") else result


class VoiceBackend:
    """Small ASR (Whisper-class).

    Accepts a device_string from discovery. Only a cuda:N string is placed
    on a GPU; vulkan:N and cpu run on CPU. The model path may be a local
    directory or a Hugging Face repo id.
    """

    def __init__(self, model_name_or_path: str, device: str = "cpu"):
        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise RuntimeError("transformers + torch required for voice backend") from exc

        self.device = _torch_device(device)
        self.device_string = device or "cpu"
        dev_idx = 0 if self.device == "cpu" else int(self.device.split(":", 1)[1])
        log.info("Loading voice model on %s (requested %s): %s", self.device, self.device_string, model_name_or_path)
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_name_or_path,
            device=dev_idx if self.device != "cpu" else -1,
            torch_dtype=torch.float32,
        )

    def generate(self, audio_path: str, **kwargs: Any) -> str:
        """Transcribe an audio file. Returns the text."""
        if not audio_path:
            raise ValueError("voice generate requires an audio path")
        result = self.pipe(audio_path, **kwargs)
        return result.get("text", str(result)) if isinstance(result, dict) else str(result)


class AgentBackend:
    """Tool-calling loop over an already-loaded LLM backend.

    The model emits `tool: <name> {json}` or `Final: <answer>`.
    A tool_runner callback executes the call and the result is fed back.
    No device selection is performed here; the LLM backend already owns it.
    """

    def __init__(self, llm_backend: Any, max_steps: int = 4):
        self.llm = llm_backend
        self.max_steps = max_steps

    def run(
        self,
        goal: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_runner: Optional[ToolRunner] = None,
        tool_prompt: str = "",
    ) -> Dict[str, Any]:
        """Run the tool loop. Returns a dict with goal, steps, and result."""
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
    """Placeholder. Most video models exceed practical single-device limits."""

    def __init__(self, *args: Any, **kwargs: Any):
        raise NotImplementedError(
            "Video generation models are not implemented in this wrapper. "
            "Use the timeline and ffmpeg encode path in the creator tools."
        )
