# DAW end goal

Summary of the arrangement view. Implementation follows this document one pass at a time.

## Track column

- Master is always the last row, pinned at the bottom.
- At least four child tracks exist on open. A + button under the last child adds another.
- Each child track has: mute, solo, level slider with a live dB readout, pan slider with an L/C/R label, an FX button, and an arm dropdown.
- Right-click on a track opens a context menu (trim, gain, reverse, silence, mute clip, open FX).
- Tracks can be dragged by their header to reorder the child list. Master stays last.
- The left edge of the arrangement (the boundary between the track column and the timeline) is a grab handle. Dragging it sets the track-column width.
- The top and bottom edge of a track row is a grab handle. Dragging it sets that track's height. The matching timeline lane grows with it.

## Timeline

- Horizontal lines run across the timeline at the top and bottom of every track lane, aligned with the track rows.
- Clips can be clicked and dragged along their lane to a new start position.
- While recording, a waveform grows in the lane of the armed track, left to right, as samples arrive.

## Drawers

- Bottom tabs: Project, Sound, Mixer, Library, Agent.
- Library holds the stock instruments (kick, snare, hat, bass, lead, pad) and any generated instruments.
- Generate instrument takes a text prompt and sends it to the VST maker as an instrument. It does not pick from the stock list.

## Devices

- Any input whose name contains Focusrite or Scarlett is listed, including WASAPI names such as "Analogue 1 + 2 (Focusrite USB Audio)".
- The Scarlett badge shows the device name when one is present.

## Out of scope for this document

- VST binary compile (needs the Steinberg SDK on the machine).
- Validated glTF/FBX/BVH export.
