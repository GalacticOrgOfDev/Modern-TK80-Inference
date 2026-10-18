# K80 Custom Interconnector

Remastering layer that presents a modern interface to the Tesla K80 while running on the last supported R470 driver + CUDA 11.8 baseline.

## Features

- Die discovery and tracking (two independent 12 GB dies)
- Translation layer: OpenAI-style messages or plain prompts → backend
- Explicit dual-die split modes: `single`, `dual`, `layer` (layer is experimental)
- Hybrid cluster advertisement
- Thermal and performance monitoring (memory, temp/util via pynvml if present, tokens/sec)

## Usage

```python
from drivers.interconnector import Interconnector

ic = Interconnector()

# Modern request format
ic.load("./model.gguf", backend="llama", die=0)
result = ic.generate({
    "messages": [
        {"role": "user", "content": "Hello from K80"}
    ],
    "max_tokens": 64,
    "temperature": 0.7,
})
print(result)

# Dual independent copies
ic.load("./model.gguf", backend="llama", split="dual")

# Cluster advertisement
print(ic.advertise())

# Full status (includes metrics + last performance)
print(ic.status())
```

## Split modes

| Mode   | Behavior                                      |
|--------|-----------------------------------------------|
| single | Whole model on one free die (default)         |
| dual   | Independent copy on each of two free dies     |
| layer  | Experimental layer split (llama backend only) |

## Monitoring

- Memory: always via PyTorch when available
- Temperature / utilization / power: requires `pynvml` (optional)
- Performance: tokens/sec recorded on each generate call

## Status

Translation, split planning, monitoring, and cluster advertisement are implemented.
