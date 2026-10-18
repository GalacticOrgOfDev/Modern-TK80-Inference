# Modern-TK80-Inference

Modern NVIDIA Tesla K80 inference engine and drivers.

## Overview

This repository develops a modern inference engine optimized for the NVIDIA Tesla K80 (Kepler, compute capability 3.7 / `sm_37`). The K80 presents as two independent 12 GB GPUs.

**Last CUDA Toolkit:** 11.8 (see [`cuda/`](./cuda/))

## Backends

- **llama.cpp** (via llama-cpp-python) — GGUF models, CUDA build targeting `sm_37`
- **PyTorch** — Hugging Face models (FP32 recommended)

## Quick Start

1. Install CUDA 11.8:
   ```bash
   ./cuda/download_cuda_11.8.sh
   # then run the installer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   # PyTorch cu118:
   pip install torch --index-url https://download.pytorch.org/whl/cu118
   ```

3. Build llama-cpp-python for K80:
   ```bash
   export CUDA_HOME=/usr/local/cuda-11.8
   export PATH=$CUDA_HOME/bin:$PATH
   ./scripts/build_llama_cuda.sh
   ```

4. Run:
   ```bash
   python main.py --status
   python main.py --model /path/to/model.gguf --backend llama --prompt "Hello from K80"
   ```

## Goals

- Efficient inference on dual K80 dies
- Modern model support (GGUF + HF) within 12 GB per die
- Extensible for custom CUDA kernels

## Status

Foundational engine with llama.cpp and PyTorch backends. Development ongoing.
