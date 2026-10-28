# Mini DAW

The Modern-TK80 mini DAW is a native Windows desktop studio. Audio I/O is ASIO (PortAudio / Focusrite), not a browser media device.

## Tracks

- Layered tracks with stereo / left / right channeling
- Per-track gain, mute, and solo
- Per-track pan, -1 (left) to 1 (right), a balance control: centre leaves both sides as they are, panning scales the far side down. Applied in mix and bounce after the stereo / left / right channeling; the clip preview player does not pan
- Arm a track for a detected ASIO input
- Scarlett 2i2 Gen 1/2 profile detection and rate limits
- Sample rate default 44100 Hz; common rates up to 192 kHz

## Clips

- Clips live on a track with timeline position, gain, and mute
- Clip gain, reverse, silence and trim (`/api/audio/clips/gain`, `/reverse`, `/silence`, `/trim`; server.py:1367-1409) and split (`/api/audio/clips/split`, server.py:1417-1449) only set clip fields; the source WAV is not rewritten. Split makes two clips that share the source and divide its trim window (server.py:1436-1447). Mix and bounce (`mix_arrangement`, audio.py:415, called from server.py:1034 and 1050) apply the fields: silenced clips are skipped but still count toward the mix length (audio.py:475, 513), each clip plays its [trim_in, trim_out) window, backwards if reversed (`_clip_window`, audio.py:516, 561-587), and clip gain multiplies track gain (audio.py:518)
- Legacy `/api/audio/edit` (server.py:1482-1518) still rewrites: trim, gain, reverse and silence each write a new 16-bit WAV with `process_clip` (audio.py:362-397; 16-bit only, audio.py:373) and point the clip at it (`_refresh_clip`, server.py:233-260). Trim and reverse also clear trim_in/trim_out, because the new file bakes them; the reversed flag is left as it was; gain and silence keep every clip field (server.py:1513-1517). Its `position` and `mute` actions change only the clip fields (server.py:1490-1493, 1505-1507)
- Effect and EQ Apply (`/api/audio/clips/effect`, server.py:1460-1479) still writes a new WAV of the whole source (`apply_effect`, effects.py:313-366) and points the clip at it, keeping gain, trim, reverse, silence, mute and position (`_refresh_clip`, server.py:233-260)
- Per-clip level fader and mute toggle
- Waveform peaks from 16-bit WAV, and from 24- and 32-bit integer PCM after the same 16-bit conversion the mix uses
## Formats

Shared catalog in `formats.py`. Endpoint: `GET /api/formats`.

- Audio store and process: WAV, MP3, FLAC, OGG, AIFF, M4A, AAC, WMA
- Non-WAV files are converted to 16-bit WAV via ffmpeg before edit (not before mix)
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
- Respects track mute/solo/gain/pan, clip mute/gain, channel, position, and master bus
- Master bus has gain, mute, and compressor
- Every clip that plays must be a 16-, 24- or 32-bit integer PCM WAV at the project sample rate (mono or stereo). 24- and 32-bit are converted to 16-bit before mixing: round to nearest, ties to even, clamped, no dither. The mix output is 16-bit stereo. 8-bit WAV and 32-bit float WAV are refused (float gets its own reason). If a clip cannot be mixed, or its file is missing or unreadable, mix and bounce return 400 naming each clip and why, and write nothing. Mute the clip to mix without it. A muted master still writes silence without checking clips.

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

Agent drawer "Generate instrument": does not work yet. It posts to `/api/vst/make`, which does not exist (the real route is `/api/audio/vst`). Even with the route fixed, free text in `effect` silently falls back to a plain gain stub.

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

- Clip edits (`/api/audio/edit`) and effects (`/api/audio/clips/effect`, including EQ) are 16-bit PCM WAV only; a 24- or 32-bit clip gets a 400 "only 16-bit WAV is supported". Mix, bounce, waveform peaks and BPM detect read 16-, 24- and 32-bit integer PCM
- ASIO recording writes 16-bit WAV only (`asio.py` opens the stream as int16)
- Non-WAV formats are stored; edit decodes them via ffmpeg, mix does not (a non-WAV clip fails the mix as unreadable)
- No VST host yet; the maker produces source
- No multi-level undo UI; the stack is tool-driven
