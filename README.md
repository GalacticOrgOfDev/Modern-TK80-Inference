# Modern-TK80-Inference

Modern NVIDIA Tesla K80 inference engine, drivers, and custom interconnector.

## Overview

This repository is remastering the Tesla K80 (Kepler, compute capability 3.7 / `sm_37`) so it can participate in modern inference.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver branch. The custom interconnector presents a modern interface while running on that baseline.

**Hybrid use:** K80 dies serve as a dedicated backend; newer GPUs in the same cluster handle other workloads.

## Interconnector

The remastering layer lives in [`drivers/interconnector/`](./drivers/interconnector/).

It provides:
- Die discovery and tracking (never assumes unified 24 GB)
- Translation of modern request formats
- Explicit dual-die split modes (`single`, `dual`, `layer`)
- Hybrid cluster advertisement
- Thermal and performance monitoring
- Modality routing: LLM, image, voice, agent (video placeholder)

```bash
python -m drivers.interconnector.cli --status
```

See the interconnector README for the full Python API and modality examples.

## Drivers

Last official support is the R470 branch. See [`drivers/`](./drivers/).

## CUDA Baseline

CUDA 11.8 is the last toolkit that can target `sm_37`. See [`cuda/`](./cuda/).

## Backends

- llama.cpp (CUDA build for `sm_37`)
- PyTorch (FP32, single die)
- diffusers (image, optional)
- transformers (voice, optional)

## Quick Start

1. Install R470 driver and CUDA 11.8.
2. Build llama-cpp-python: `./scripts/build_llama_cuda.sh`
3. Use the interconnector CLI or Python API.

## Status

Single-die support for LLM, image, voice, and a basic agentic loop. Dual-die unification planned for later. Video remains a placeholder.
