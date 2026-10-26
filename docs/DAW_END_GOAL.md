# DAW end goal

Summary of the arrangement view. Implementation follows this document one pass at a time.

## Done

- Master pinned at the bottom. Four child tracks on open. + adds another.
- Each track has mute, solo, level with a live dB readout, pan with L/C/R, FX, and arm.
- Right-click menu opens. Reverse, normalize, and gain rewrite the clip file.
- Scarlett / Focusrite devices are listed from any host. Badge shows the name.
- Library holds stock instruments. Generate instrument sends a prompt to the VST maker.
- Playback cache-busts so an edited file is what plays.

## Remaining, in order

1. Gain control with measurement. Right-click Gain currently applies a fixed +6 dB. The menu needs a control that shows the current clip gain in dB and steps it up or down by a chosen amount (for example 1 dB or 3 dB). The applied value is written into the clip and the readout updates.
2. Equalizer wired to the clip. The 30-band EQ panel must send its band gains to the effect endpoint and rewrite the clip. An empty gains list does nothing.
3. Track reorder by drag. Drag a child track header to a new index. Master stays last.
4. Clip drag on the timeline. Drag a clip along its lane to a new start position.
5. Lane lines. Horizontal lines across the timeline at the top and bottom of every track lane.
6. Column width handle. Drag the edge between the track column and the timeline to set the column width.
7. Track height handle. Drag the top or bottom edge of a track row to set that track's height. The matching lane grows with it.
8. Recording waveform. While recording, a waveform grows in the armed track's lane as samples arrive.

## Effect wiring rule

An effect is wired when it has named parameters, a visible control for each parameter, a unit (dB, ms, ratio), and a call that writes the result into the clip file. A label in a list is not wired.

## Out of scope

- Using or copying third-party plugin binaries.
- VST binary compile (needs the Steinberg SDK on the machine).
