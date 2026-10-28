# scripts

## scarlett_check.py

A hardware check for the Scarlett (or any ASIO device) on the Windows PC.
It needs only Python and `sounddevice` (already in `requirements.txt`);
without `sounddevice` it writes a report that says so and exits with 2.

```
python scripts\scarlett_check.py --list-only     # host APIs and devices only
python scripts\scarlett_check.py                 # full check on the first ASIO Scarlett/Focusrite device
python scripts\scarlett_check.py --device 12 --loopback --loop-out 1 --loop-in 1
```

It writes `scarlett_report.md` in the current folder (`--report PATH` to
change it; a path inside `uploads/` is refused). Steps: list devices, try
44100/48000/88200/96000 Hz x 64/128/256/512/1024 buffers (open and close
only), record 1 s at 16-, 24- and 32-bit, play a 1 kHz tone at -20 dBFS
(turn monitors down; `--no-play` skips it), and, only with `--loopback`,
play the tone out and look for it on an input. Loopback needs a physical
cable from an output to an input; with no cable, leave `--loopback` off.
With `--loopback` it first prints a warning (turn the Scarlett's monitor and
output volume down; a cable from output to input can cause feedback or a loud
tone) and runs the loopback only after you type `yes` at the prompt or pass
`--confirm-loopback`; otherwise that step is SKIPPED.
Each step is PASS, FAIL or SKIPPED with the raw exception text. It sets
`SD_ENABLE_ASIO` before importing `sounddevice` so pip's ASIO PortAudio DLL
is loaded; `--no-asio-dll` turns that off. `--dry-run` touches no audio.
