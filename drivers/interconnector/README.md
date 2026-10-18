# K80 Custom Interconnector

Remastering layer that presents a modern interface to the Tesla K80 while running on the last supported R470 driver + CUDA 11.8 baseline.

## What it does

- Discovers the two independent dies (never treats them as one 24 GB pool)
- Places a model explicitly on one die
- Routes generate calls to the chosen die/backend
- Reports status for hybrid cluster use

## Usage

```python
from drivers.interconnector import Interconnector

ic = Interconnector()                  # all dies
# or Interconnector(die_indices=[0])   # only die 0

print(ic.status())

ic.load("./model.gguf", backend="llama", die=0)
ic.load("./other.gguf", backend="llama", die=1)  # second die

print(ic.generate("Hello from K80", die=0))

ic.unload(0)
```

## Backends

- `llama` — llama-cpp-python built for `sm_37` (see `scripts/build_llama_cuda.sh`)
- `pytorch` — Hugging Face models, FP32, single die

## Status

Core placement and routing implemented. Translation layer for modern request formats and hybrid cluster hooks come next.
