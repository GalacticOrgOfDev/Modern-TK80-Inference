# K80 Custom Interconnector

Remastering layer that presents a modern interface to the Tesla K80 while running on the last supported R470 driver + CUDA 11.8 baseline.

Single-die models for now. Dual-die unification comes later.

## Modalities

| Modality | Status | Typical model class | Notes |
|----------|--------|---------------------|-------|
| LLM | Ready | GGUF or HF causal LM | llama.cpp or PyTorch |
| Image | Ready | SD 1.5-class | diffusers, FP32, one die |
| Voice | Ready | Whisper-small class | ASR via transformers |
| Agent | Ready | Wraps an LLM | Simple multi-step loop |
| Video | Placeholder | — | Most models exceed 12 GB/die |

## Features

- Die discovery and tracking (two independent 12 GB dies)
- Translation layer for modern request formats
- Explicit dual-die split modes: `single`, `dual`, `layer`
- Hybrid cluster advertisement (includes modalities)
- Thermal and performance monitoring
- Modality routing

## Usage

```python
from drivers.interconnector import Interconnector

ic = Interconnector()

# LLM
ic.load("./model.gguf", modality="llm", die=0)
print(ic.generate({"messages": [{"role": "user", "content": "Hello"}]}))

# Image (small diffusion model)
ic.load("runwayml/stable-diffusion-v1-5", modality="image", die=0)
img = ic.generate("a red cube on a white background")

# Voice (ASR)
ic.load("openai/whisper-small", modality="voice", die=1)
text = ic.generate({"audio": "./clip.wav"}, die=1)

# Agent (wraps an LLM)
ic.load("./model.gguf", modality="agent", die=0)
result = ic.generate({"goal": "Summarize the K80 remaster", "tools": []})

print(ic.advertise())
print(ic.status())
```

## Status

LLM, image, voice, and a basic agentic loop are available on a single die. Video remains a placeholder. Dual-die unification is planned for later.
