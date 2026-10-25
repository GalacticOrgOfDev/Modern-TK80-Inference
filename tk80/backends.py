"""Backends for Modern-TK80-Inference.

Thin wrappers around llama-cpp-python and PyTorch. Device selection comes
from drivers.interconnector.devices: a device_string of "vulkan:N",
"cuda:N", or "cpu". Creator tools (DAW, video, image) do not require a
loaded model; they run through the tool dispatcher and direct commands.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("tk80.backends")


def _parse_device(device_string: Optional[str]) -> tuple[str, int]:
    """Split a device_string into (backend, index).

    "vulkan:1" -> ("vulkan", 1)
    "cuda:0"   -> ("cuda", 0)
    "cpu" or None -> ("cpu", 0)
    Unknown forms fall back to cpu.
    """
    if not device_string or device_string == "cpu":
        return "cpu", 0
    if ":" in device_string:
        kind, idx = device_string.split(":", 1)
        try:
            return kind.lower(), int(idx)
        except ValueError:
            return "cpu", 0
    return "cpu", 0


class LlamaCppBackend:
    """llama-cpp-python backend.

    Accepts a device_string from device discovery. When the string is
    vulkan:N or cuda:N the index is passed as main_gpu and n_gpu_layers
    defaults to -1 (offload all). When the string is cpu, n_gpu_layers is
    forced to 0. The model path may be a local GGUF or a Hugging Face
    repo id that llama.cpp can resolve; no download is performed here.
    """

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
        main_gpu: int = 0,
        split_mode: int = 0,
        device_string: Optional[str] = None,
    ):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "A Vulkan build is required for AMD GPUs; a CUDA build "
                "is required for NVIDIA."
            ) from exc

        backend, index = _parse_device(device_string)
        if backend == "cpu":
            n_gpu_layers = 0
            main_gpu = 0
        else:
            main_gpu = index

        self.model_path = model_path
        self.device_string = device_string or "cpu"
        log.info(
            "Loading GGUF via llama.cpp (%s): %s (gpu_layers=%s, main_gpu=%s)",
            self.device_string,
            model_path,
            n_gpu_layers,
            main_gpu,
        )
        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            main_gpu=main_gpu,
            split_mode=split_mode,
            verbose=False,
        )

    def generate(self, prompt: str, max_tokens: int = 128, temperature: float = 0.7) -> str:
        """Generate text. Returns the first choice text or an empty string."""
        result = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["</s>", "\n\n"],
        )
        choices = result.get("choices") or []
        if not choices:
            return ""
        return choices[0].get("text", "")


class PyTorchBackend:
    """PyTorch causal LM backend.

    device_string selects the torch device. "cuda:N" is used directly.
    "vulkan:N" and "cpu" both map to CPU because this wrapper does not
    implement a Vulkan compute path. Model may be a local path or a
    Hugging Face repo id; from_pretrained is called but no marketplace
    UI is provided here.
    """

    def __init__(self, model_name_or_path: str, device_string: Optional[str] = None):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("PyTorch / transformers not installed. See requirements.txt.") from exc

        backend, index = _parse_device(device_string)
        if backend == "cuda":
            self.device = f"cuda:{index}"
        else:
            self.device = "cpu"

        self.model_name_or_path = model_name_or_path
        self.device_string = device_string or "cpu"
        log.info("Loading PyTorch model on %s: %s", self.device, model_name_or_path)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            torch_dtype=torch.float32,
            device_map=self.device,
        )

    def generate(self, prompt: str, max_tokens: int = 128, temperature: float = 0.7) -> str:
        """Generate text. Returns the decoded string."""
        import torch

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
            )
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)


def create_backend(
    kind: str,
    model: str,
    device_string: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Factory.

    kind is "llama" or "pytorch". device_string is forwarded when present.
    Extra kwargs are passed through for llama (n_gpu_layers, n_ctx, etc.).
    """
    if kind == "llama":
        return LlamaCppBackend(model, device_string=device_string, **kwargs)
    if kind == "pytorch":
        return PyTorchBackend(model, device_string=device_string)
    raise ValueError(f"Unknown backend: {kind}")
