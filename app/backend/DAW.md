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
- Formats accepted for storage: WAV, MP3, FLAC, OGG, AIFF, M4A, AAC
- Only WAV is processable for edits and mix

## Effects

Applied per clip and written back to a new WAV:

- normalize (target peak)
- compressor (threshold, ratio, makeup)
- morph envelope (time/gain points)
- delay (time, feedback, mix)
- simple EQ (low / mid / high gain)
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

- VST maker generates VST3/JUCE source for reverb, subpump, autotune, noise suppression, delay, distortion, or custom
- VST UI builder: drag-and-drop knobs, sliders, buttons, labels; bind to parameters; export source plus layout

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