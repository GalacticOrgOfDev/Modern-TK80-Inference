"""Backends for Modern-TK80-Inference.

Provides thin wrappers around llama-cpp-python (CUDA, sm_37) and PyTorch.
Simplified and CUDA-focused for the dual-GPU Tesla K80.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("tk80.backends")


class LlamaCppBackend:
    """llama-cpp-python backend compiled for CUDA / sm_37."""

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
        main_gpu: int = 0,
        split_mode: int = 0,
    ):
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is not installed. "
                "Build it with scripts/build_llama_cuda.sh for K80 support."
            ) from exc

        self.model_path = model_path
        log.info(
            "Loading GGUF via llama.cpp (CUDA): %s (gpu_layers=%s, main_gpu=%s, split_mode=%s)",
            model_path,
            n_gpu_layers,
            main_gpu,
            split_mode,
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
        result = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["</s>", "\n\n"],
        )
        return result["choices"][0]["text"]


class PyTorchBackend:
    """Simple PyTorch backend for models that fit on a single K80 die (12 GB)."""

    def __init__(self, model_name_or_path: str, device: str = "cuda:0"):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("PyTorch / transformers not installed. See requirements.txt.") from exc

        self.device = device
        log.info("Loading PyTorch model on %s: %s", device, model_name_or_path)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            torch_dtype=getattr(torch, "float32"),  # K80 prefers FP32; no native Tensor Cores
            device_map=device,
        )

    def generate(self, prompt: str, max_tokens: int = 128, temperature: float = 0.7) -> str:
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


def create_backend(kind: str, model: str, **kwargs: Any) -> Any:
    """Factory. kind is 'llama' or 'pytorch'."""
    if kind == "llama":
        return LlamaCppBackend(model, **kwargs)
    if kind == "pytorch":
        return PyTorchBackend(model, **kwargs)
    raise ValueError(f"Unknown backend: {kind}")
