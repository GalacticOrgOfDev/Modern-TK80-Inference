# Modern-TK80-Inference

Modern NVIDIA Tesla K80 inference engine, drivers, and custom interconnector.

## Overview

This repository remasters the Tesla K80 (Kepler, compute capability 3.7 / `sm_37`) so it can participate in modern inference.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver branch. The custom interconnector presents a modern interface while running on that baseline.

**Hybrid use:** K80 dies serve as a dedicated backend; newer GPUs in the same cluster handle other workloads.

## Custom App (Windows 10+)

The primary interface is the custom app in [`app/`](./app/):

- **Chat** — LLM or agent modality, with a tool indicator
- **Mini DAW** — layered tracks, ASIO recording, sequencer, instruments, loops, mix, bounce
- **Mini video studio** — frame timeline (image models)
- **DieFusionCore** — future dual-die unification

```bash
pip install fastapi uvicorn pywebview
python -m app.launcher
```

Opens a native window. Packaging notes for a Windows installer are in `app/packaging/`.

## Mini DAW

- Layered tracks with stereo / left / right channeling, per-track level faders, mute, and solo
- Master bus with level, mute, and compressor (threshold / ratio / makeup)
- Arm a track for a detected ASIO input
- Sample rate (default 44100 Hz) with Focusrite Scarlett 2i2 Gen 1/2 profile detection
- Native ASIO path (sounddevice / PortAudio). Prefer 64-sample buffer at 44100 Hz (~1.5 ms)
- Live waveform on the armed track while recording
- Instrument generator (kick, snare, hat, bass, lead, pad)
- 16-step sequencer, BPM detect/set, loop/sample generation
- Clip edits rewrite the WAV: trim, reverse, gain, silence
- Per-clip level fader and mute toggle (inline on the clip list)
- Per-clip effect channels: normalize, compressor, morphable envelope (time/gain points reshape the wave)
- VST maker: generate VST3 source that targets the Steinberg VST3 SDK / JUCE. Models can call `make_vst` to produce reverb, subpump, autotune, noise suppression, delay, distortion, or custom effects. Output is a `.cpp` file with a starter DSP stub ready to compile.
- Timeline position per clip
- True 16-bit peaks for the waveform
- Play mix and bounce the arrangement to a stereo WAV (respects track mute/solo/gain, clip mute/gain, channel, position, and master bus)

## Mini Video Studio (staged)

- Frame timeline with prompt and duration
- Load image model and generate frames
- Export timeline (JSON stage; full encode later)
- Ready for further expansion once the DAW is locked

## Music tools

The model (or a direct chat command) can call:

| Tool | Purpose |
|------|---------|
| `set_bpm` | Set studio BPM (40–220) |
| `generate_instrument` | Render a hit or tone to a clip |
| `generate_loop` | Generate a short loop at the current BPM |
| `render_pattern` | Bounce the step pattern to a clip |
| `detect_bpm` | Estimate BPM from a clip |
| `make_vst` | Generate VST3 source for reverb, subpump, autotune, noise_suppression, delay, distortion, or custom |

Chat routes by modality:

- Direct command (“make a kick”) runs immediately, no model required
- Agent modality runs a tool loop: model emits `tool: name {json}`, studio runs it, result is fed back (up to 4 steps)
- LLM modality runs a single tool call if the reply contains one

The chat pane shows the tool that just ran.

## Other entry points

- `python main.py` — CLI over the interconnector
- `python -m drivers.interconnector.cli` — same surface
- Python API: `from drivers.interconnector import Interconnector`

The Tkinter GUI in `gui/` is deprecated in favor of the custom app.

## Interconnector

Lives in [`drivers/interconnector/`](./drivers/interconnector/).

It provides:

- Die discovery and tracking (never assumes unified 24 GB)
- Translation of modern request formats
- Explicit dual-die split modes (`single`, `dual`, `layer`)
- Hybrid cluster advertisement
- Thermal and performance monitoring
- Modality routing: LLM, image, voice, agent (video placeholder)
- Tool-calling loop for the agent modality

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
3. Launch the custom app: `python -m app.launcher`

## Status

Custom Windows app is in place with chat, mini DAW (ASIO, Scarlett, sequencer, instruments, loops, live waveform, real clip edits, timeline position, mix/bounce), mini video studio, and DieFusionCore scaffolding. Agent tool-calling is wired. Image/video studio expansion is next after the DAW is locked. Packaging for a proper installer comes after that.
