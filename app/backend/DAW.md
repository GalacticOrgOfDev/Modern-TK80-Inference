# Mini DAW

The Modern-TK80 mini DAW is a native Windows desktop studio. Audio I/O is ASIO (PortAudio / Focusrite), not a browser media device.

## Tracks

- Layered tracks with stereo / left / right channeling
- Per-track gain, mute, and solo
- Arm a track for a detected ASIO input
- Scarlett 2i2 Gen 1/2 profile detection and rate limits
- Sample rate default 44100 Hz; common rates up to 192 kHz

## Clips

- Clips live on a track with timeline position, gain, and mute
- Edits rewrite the WAV: trim, reverse, gain, silence
- Per-clip level fader and mute toggle
- True 16-bit peaks for the waveform
## Formats

Shared catalog in `formats.py`. Endpoint: `GET /api/formats`.

- Audio store and process: WAV, MP3, FLAC, OGG, AIFF, M4A, AAC, WMA
- Non-WAV files are converted to 16-bit WAV via ffmpeg before edit or mix
- ffmpeg is required for non-WAV processing
- Video store: MP4, MOV, WebM, AVI, MKV, MPEG, WMV
- Model store: OBJ, glTF, GLB, FBX
- Animation: json, gltf, fbx, bvh

## Effects

Applied per clip and written back to a new WAV:

- normalize (target peak)
- compressor (threshold, ratio, makeup)
- morph envelope (time/gain points)
- delay (time, feedback, mix)
- 30-band EQ (100 Hz–20 kHz, log-spaced). UI has a vertical slider per band. Hover shows the current ±dB for that band. Apply sends the 30 gains. Each band is an RBJ peaking biquad (`effects.py`); bands at or above Nyquist are skipped. 16-bit WAV only. Verified by measurement (sine-wave level tests), not yet judged by ear. Applying it to a 3-minute 44.1 kHz stereo track takes about 7 seconds end to end (measured 7.39 s with 3 bands, 7.37 s with all 30; the EQ step alone 3.6 to 4.3 s). Earlier builds were not frequency-selective: boosting one band raised 200 Hz, 1 kHz and 5 kHz equally.
- simple reverb (room, mix)

## Mix and bounce

- Play mix and bounce the arrangement to a stereo WAV
- Respects track mute/solo/gain, clip mute/gain, channel, position, and master bus
- Master bus has gain, mute, and compressor

## Instruments and sequencer

- Instrument generator: kick, snare, hat, bass, lead, pad
- 16-step sequencer
- BPM detect and set (40–220)
- Loop and sample generation

## Undo

- Audio edits and effects push a clip snapshot onto a 20-step stack
- `undo` tool restores the previous snapshot

## VST

Extensive VST3/JUCE source generator and UI builder.

Presets (by category):

- Space: reverb, delay
- Dynamics: compressor, limiter, gate, subpump
- Tone: eq, filter, distortion, bitcrush
- Modulation: chorus, flanger, phaser, tremolo
- Pitch: autotune
- Cleanup: noise suppression
- Custom

Each preset writes a `.cpp` with parameters and a starter DSP stub. Compile against the Steinberg VST3 SDK or a JUCE AudioPlugin project.

UI builder objects: knob, vertical slider, horizontal slider, button, label, meter, xy pad. Models can add parameters and objects; users bind objects to parameters and export source plus layout.

Catalog endpoint: `GET /api/vst/presets`.

VST prompt design: broken since the first commit; returns 501. A non-empty `prompt` on `POST /api/audio/vst` or the `make_vst` tool is refused. Use an effect preset.

Pressing a binary:

- `scripts/install_vst3sdk.sh` clones the official Steinberg VST3 SDK after you accept the license.
- Press searches common SDK paths and PATH for cmake and a C++ compiler.
- When both are found it runs cmake configure and build automatically.
- The expected output is a `.vst3` under the source's `build/` folder.

## Recording

- Native ASIO path. Prefer 64-sample buffer at 44100 Hz (~1.5 ms)
- Live waveform on the armed track while recording
- Low-latency focus for the Scarlett 2i2

## Tools the model can call

| Tool | Purpose |
|------|---------|
| `set_bpm` | Set studio BPM |
| `generate_instrument` | Render a hit or tone to a clip |
| `generate_loop` | Generate a short loop |
| `render_pattern` | Bounce the step pattern |
| `detect_bpm` | Estimate BPM from a clip |
| `make_vst` | Generate VST3 source |
| `undo` | Restore the last clip snapshot |

## Limits

- Processing is 16-bit PCM WAV only
- Non-WAV formats are stored but not decoded for mix or edit
- No VST host yet; the maker produces source
- No multi-level undo UI; the stack is tool-driven
"""
file_path="/workspace/artifacts/Modern-TK80-Inference/app/backend/DAW.md"