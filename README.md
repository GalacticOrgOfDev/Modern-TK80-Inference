# Modern-TK80-Inference

Windows 10+ creator app and Tesla K80 inference backend.

The K80 is two independent 12 GB dies. Official support ended with CUDA 11.x and the R470 driver. The interconnector presents a modern interface on that baseline. Newer GPUs in the same cluster can run other workloads.

## App

Native window via FastAPI and pywebview. Not a browser tab.

| Studio | What ships today | What is staged |
|--------|------------------|----------------|
| Chat | Multi-turn chat, tool indicator, direct commands | K80 inference when a die is connected |
| DAW | Tracks, clips, ASIO record, sequencer, instruments, mix, bounce, undo, 30-band EQ | VST binary compile needs the SDK on the machine. VST prompt design is broken since the first commit (returns 501) |
| Video | Timeline, clips, text, VFX render (ffmpeg), audio split | Validated glTF/FBX/BVH binaries. MP4 encode: a function exists but no route calls it (see Staged below) |
| Fusion | Status, plan, and an activate/deactivate switch that only sets a flag; no data is moved (`drivers/interconnector/diefusion.py:99-111`) | Dual-die data movement |

Launch:

```bash
python -m app.launcher
```

Requires `pywebview`. Install with `scripts/install.sh` or `pip install -r requirements.txt`.

## DAW

Ships:

- Tracks with stereo / left / right, level, pan (mix and bounce only), mute, solo, arm
- Master bus with level, mute, compressor
- ASIO recording (sounddevice). Scarlett 2i2 Gen 1/2 profile when the device name matches
- Sample rate default 44100 Hz
- Instruments: kick, snare, hat, bass, lead, pad
- 16-step sequencer, BPM set/detect, loop generation
- Clip gain, reverse, silence, mute and trim from the clip and track menus are stored as clip fields and applied at mix and bounce time; the source file is not rewritten, and each can be stepped back or toggled off. Gain steps in 1 dB from -24 to +12 dB with a dB readout in the clip menu (stored as a 0 to 4 linear factor). Live playback of these in the app was not checked in a browser; the preview player's volume is capped at 1, so gain above 0 dB is heard only in the mix. By `docs/DAW_END_GOAL.md` these are not done yet: it asks for the changes to be live on the playing clip, and that is unverified
- `/api/audio/edit` (trim, gain, reverse, silence) still rewrites the WAV. No button in the current UI calls it. Its trim and reverse clear the clip's trim window (the new file bakes it); other clip fields are kept
- No fade yet: there is no fade endpoint or control
- Effects: normalize, compress, morph, delay, simple reverb. Apply writes a new WAV of the whole source and points the clip at it, keeping the clip's gain, trim, reverse, silence, mute and position; removable only through undo
- 30-band EQ: real filters, but Apply still writes a new file, so it is not done by `docs/DAW_END_GOAL.md` (band gains must drive playback). RBJ peaking biquads, 30 log-spaced bands from 100 Hz to 20 kHz; bands at or above Nyquist are skipped. 16-bit WAV only. Verified by measurement (sine-wave level tests), not yet judged by ear. Applying it to a 3-minute 44.1 kHz stereo track takes about 7 seconds end to end (measured 7.39 s with 3 bands, 7.37 s with all 30; the EQ step alone 3.6 to 4.3 s). Earlier builds were not frequency-selective: boosting one band raised 200 Hz, 1 kHz and 5 kHz equally.
- Undo (20 steps)
- Play mix and bounce to 16-bit stereo WAV. Clips may be 16-, 24- or 32-bit integer PCM WAV (24/32-bit rounded to 16-bit, no dither); 8-bit and 32-bit float WAV are refused with a 400. Clip edits and effects are still 16-bit only
- Stored formats: WAV, MP3, FLAC, OGG, AIFF, M4A, AAC, WMA. Non-WAV converts via ffmpeg before edit.

Staged:

- VST maker writes `.cpp` for VST3/JUCE. Binary `.vst3` requires the Steinberg SDK and a C++ toolchain on the machine (`scripts/install_vst3sdk.sh`, then press).
- VST UI builder: drag-and-drop knobs, sliders, buttons, labels; bind to parameters; export source plus layout JSON. Same SDK requirement for a binary.
- VST prompt design: broken since the first commit; returns 501. A non-empty `prompt` on `POST /api/audio/vst` or the `make_vst` tool is refused. Use an effect preset.
- Agent drawer "Generate instrument": does not work yet (`docs/DAW_END_GOAL.md` lists "Generate instrument sends a prompt" under Done; the code says otherwise). It posts to `/api/vst/make`, which does not exist (the real route is `/api/audio/vst`). Even with the route fixed, free text in `effect` silently falls back to a plain gain stub.

Scarlett hardware check (not run on hardware yet): `python scripts\scarlett_check.py` on the Windows PC lists host APIs and devices, tries rate x buffer combinations, records at 16/24/32-bit, plays a test tone and, with `--loopback` and a cable from an output to an input, looks for the tone. It writes `scarlett_report.md` with only what it measured. See `scripts/README.md`. Scarlett support stays unverified until that report exists.

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
- Video store: MP4, MOV, WebM, AVI, MKV, MPEG, WMV

Staged:

- Animation export: JSON, glTF 2.0, BVH, and text FBX.
- MP4 encode is not reachable from the app. `encode_mp4()` exists (`app/backend/export.py:41-70`): it needs ffmpeg on PATH and raises `ValueError("ffmpeg is required to encode MP4")` without it (`export.py:54-55`), then concatenates existing clip files or writes one black segment, with libx264 (`export.py:59-69`). `app/backend/server.py:67` imports it, but no route calls it: there is no `/api/video/encode`, and the frontend never asks for an encode. Whether its output plays is unverified; it has not been run.
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

See `app/packaging/README.md`. Today `app/packaging/Product.wxs` installs only `Modern-TK80.exe` to `Program Files\Modern-TK80` (`Product.wxs:22-25`): no custom action, no Python, no wheels. Planned, not built: a separate, self-contained MSI that bundles Python and the wheels. `scripts/install.ps1` is a developer bootstrap run by hand, not part of the MSI.

## Tests

```bash
python -m pytest tests/
```

pytest was not installed where the counts below were taken, so this command has not been run for them. Results at commit `64b87f7`, Python 3.13, Linux, no GPU or audio hardware:

- `python3 -m unittest discover -s tests -t .` ran 177 and reported `FAILED (errors=1)`. The 177 are 176 real test methods plus one failed import: `tests/test_video.py` imports pytest, which was missing. All 176 test methods passed.
- A local harness script (not in the repo) imports each test module, runs its unittest cases and also calls its plain `test_` functions, which unittest discovery does not collect. It reported 180 run, 0 failed: the same 176 plus 4 plain functions (2 in `tests/test_formats.py`, 2 in `tests/test_eq_and_vst.py`). It skips `tests/test_video.py` for the same missing pytest, so that file's 2 tests did not run.

## Status

- App launches without a K80. Connect is a button.
- DAW mix and bounce produce WAV.
- Video encode and real VFX rendering are staged.
- Dual-die fusion is a plan, not a runtime.
