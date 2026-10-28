# Modern-TK80-Inference

Windows 10+ creator app and Tesla K80 inference backend.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver. The interconnector presents a modern interface on that baseline. Newer GPUs in the same cluster can run other workloads.

## App

Native window via FastAPI and pywebview. Not a browser tab.

| Studio | What ships today | What is staged |
|--------|------------------|----------------|
| Chat | Multi-turn chat, tool indicator, direct commands | K80 inference when a die is connected |
| DAW | Tracks, clips, ASIO record, sequencer, instruments, mix, bounce, undo | VST binary compile needs the SDK on the machine. 30-band EQ: UI and plumbing exist, processing is not yet frequency-selective |
| Video | Timeline, clips, text, VFX render (ffmpeg), audio split, MP4 encode | Validated glTF/FBX/BVH binaries |
| Fusion | Status and plan | Dual-die data movement |
| Fusion | Status and activation plan | Real dual-die data movement |

Launch:

```bash
python -m app.launcher
```

Requires `pywebview`. Install with `scripts/install.sh` or `pip install -r requirements.txt`.

## DAW

Ships:

- Tracks with stereo / left / right, level, mute, solo, arm
- Master bus with level, mute, compressor
- ASIO recording (sounddevice). Scarlett 2i2 Gen 1/2 profile when the device name matches
- Sample rate default 44100 Hz
- Instruments: kick, snare, hat, bass, lead, pad
- 16-step sequencer, BPM set/detect, loop generation
- Clip edits rewrite WAV: trim, reverse, gain, silence, fade
- Effects: normalize, compress, morph, delay, simple reverb
- Undo (20 steps)
- Play mix and bounce to stereo WAV
- Stored formats: WAV, MP3, FLAC, OGG, AIFF, M4A, AAC, WMA. Non-WAV converts via ffmpeg before edit.

Staged:

- VST maker writes `.cpp` for VST3/JUCE. Binary `.vst3` requires the Steinberg SDK and a C++ toolchain on the machine (`scripts/install_vst3sdk.sh`, then press).
- VST UI builder: drag-and-drop knobs, sliders, buttons, labels; bind to parameters; export source plus layout JSON. Same SDK requirement for a binary.
- 30-band EQ (100 Hz–20 kHz): UI and plumbing exist, but processing is not yet frequency-selective (boosting one band raises 200 Hz, 1 kHz and 5 kHz equally). Moves to Ships once frequency-selective tests pass.

## Video / VFX

Ships:

- Timeline of clips with prompt, duration, and path
- Built-in VFX names: none, fade, zoom, pan, color_grade, overlay
- Custom VFX from any prompt (`POST /api/vfx/render?prompt=...`). Keywords map to ffmpeg filters; unknown prompts still produce a playable clip.
- Animation writers: JSON, glTF 2.0, BVH, and text FBX.
- Text objects with texture name, position, style
- `text_scene` stores a sequence of VFX names on a text object
- Transitions: cut, crossfade, wipe, dissolve (kind and duration stored)
- 3D object records (text mesh or model path)
- Animation clip records
- Export timeline as JSON manifest
- Split audio from a video file via ffmpeg (`POST /api/video/split`)
- Encode timeline to MP4 via ffmpeg (`POST /api/video/encode`)
- Video store: MP4, MOV, WebM, AVI, MKV, MPEG, WMV

Staged:

- Animation export: JSON, glTF 2.0, BVH, and text FBX.
- Full MP4 encode is not implemented.
- Custom VFX stubs are not rendered.

## Tools

The model or a direct chat command can call the tools in `app/backend/tools.py`. Direct commands run without a loaded model. Agent modality runs a tool loop. LLM modality runs one tool call if the reply contains one.

## Interconnector

`drivers/interconnector/`:

- Die discovery (never assumes unified 24 GB)
- Request translation
- Split modes: single, dual, layer
- Hybrid cluster advertisement
- Thermal and performance monitoring
- Modality routing: LLM, image, voice, agent

## Install

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

The script installs Python 3.12 if it is missing, then fastapi, uvicorn, python-multipart, pywebview, sounddevice, diffusers, transformers, pynvml, torch, and llama-cpp-python.

Linux/macOS:

```bash
scripts/install.sh
```

Torch and llama-cpp need Python 3.11-3.14.

## Packaging

Target: `Modern-TK80.exe` installed by `MTK80Setup.msi`.

See `app/packaging/README.md`. The MSI installs the app and its Python dependencies.

## Tests

```bash
python -m pytest tests/
```

## Status

- App launches without a K80. Connect is a button.
- DAW mix and bounce produce WAV.
- Video encode and real VFX rendering are staged.
- Dual-die fusion is a plan, not a runtime.
file_path="/workspace/artifacts/Modern-TK80-Inference/README.md"