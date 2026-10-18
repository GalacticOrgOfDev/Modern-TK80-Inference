# Modern-TK80-Inference

Modern NVIDIA Tesla K80 inference engine, drivers, and custom interconnector.

## Overview

This repository is remastering the Tesla K80 (Kepler, compute capability 3.7 / `sm_37`) so it can participate in modern inference.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver branch. The custom interconnector presents a modern interface while running on that baseline.

**Hybrid use:** K80 dies serve as a dedicated backend; newer GPUs in the same cluster handle other workloads.

## Interconnector

The remastering layer lives in [`drivers/interconnector/`](./drivers/interconnector/).

It owns:
- Die discovery and tracking (never assumes unified 24 GB)
- Explicit model placement on a chosen die
- Routing to llama.cpp or PyTorch backends
- Status reporting for hybrid cluster use

```bash
# Status
python -m drivers.interconnector.cli --status

# Load and generate on die 0
python -m drivers.interconnector.cli --load ./model.gguf --die 0 --prompt "Hello from K80"
```

See the interconnector README for the Python API.

## Drivers

Last official support is the R470 branch. See [`drivers/`](./drivers/).

## CUDA Baseline

CUDA 11.8 is the last toolkit that can target `sm_37`. See [`cuda/`](./cuda/).

## Backends

- llama.cpp (CUDA build for `sm_37`)
- PyTorch (FP32, single die)

## Quick Start

1. Install R470 driver and CUDA 11.8.
2. Build llama-cpp-python: `./scripts/build_llama_cuda.sh`
3. Use the interconnector CLI or Python API.

## Status

Interconnector core (discovery, placement, routing, status) is implemented. Translation layer and hybrid cluster hooks are next.
