# Modern-TK80-Inference

Modern NVIDIA Tesla K80 inference engine, drivers, and custom interconnector.

## Overview

This repository is remastering the Tesla K80 (Kepler, compute capability 3.7 / `sm_37`) so it can participate in modern inference.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver branch. The goal is a custom interconnector that lets the K80 run modern model formats and runtimes while remaining compatible with the last supported official stack.

**Hybrid use:** K80 dies serve as a dedicated backend; newer GPUs in the same cluster handle other workloads.

## Current Goal

K80 remastering via custom interconnector:
- Baseline on last official R470 drivers + CUDA 11.8
- Custom layer that presents a modern interface to the K80
- Dual-die awareness and efficient use of the two independent GPUs
- Path to hybrid cluster operation

## Drivers

Last official support is the R470 branch (Kepler / Tesla K80).

See [`drivers/`](./drivers/) for:
- Official baseline notes and download pointers
- Placeholder for the custom interconnector

## CUDA Baseline

CUDA 11.8 is the last toolkit that can target `sm_37`.

See [`cuda/`](./cuda/).

## Backends (interim)

While the interconnector is built:
- llama.cpp (CUDA build for `sm_37`)
- PyTorch (FP32, single-die)

## Quick Start (baseline)

1. Install last supported driver (R470) and CUDA 11.8.
2. Build llama-cpp-python for the K80 (`./scripts/build_llama_cuda.sh`).
3. Run `python main.py --status`.

## Status

Remastering phase. Custom interconnector is the active goal.
