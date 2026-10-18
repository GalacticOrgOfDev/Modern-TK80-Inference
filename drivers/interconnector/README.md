# K80 Custom Interconnector

Placeholder for the remastering layer.

## Purpose

Bridge the Tesla K80 (last supported by R470 driver + CUDA 11.8) to modern inference workloads.

## Design notes

- Dual independent dies (12 GB each). Treat as two devices, not one 24 GB pool.
- Prefer FP32. No Tensor Cores.
- Interconnector owns:
  - Device discovery and die assignment
  - Model placement (single die or explicit split)
  - Translation between modern request formats and the K80 runtime
  - Hybrid cluster hooks so K80 nodes can sit beside newer GPUs

## Status

Scaffold only. Implementation follows.
