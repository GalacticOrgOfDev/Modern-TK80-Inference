# DAW end goal

One pass at a time. An item is done only when it behaves like a real-time
processor: the source file stays, the parameter changes live, and the
effect can be removed.

## Not done

- Gain. Must adjust the playing clip's gain in dB steps, live, without
  writing a new file. The menu must show the current value and step it.
- Reverse, silence, mute, trim. Same rule: non-destructive, removable.
- Equalizer. Band gains must drive playback, not bake a new file.
- Track reorder by drag.
- Clip drag on the timeline.
- Lane lines.
- Column width handle.
- Track height handle.
- Recording waveform that grows while recording.

## Done

- Master at the bottom. Four tracks on open. Scarlett listed.
- Right-click menu opens.
- Library holds instruments. Generate instrument sends a prompt.

## Effect wiring rule

An effect is a processor in the chain. It has named parameters, a visible
control with a unit, and it changes what is heard without replacing the
source file. Writing a new WAV on every click is not wired.
