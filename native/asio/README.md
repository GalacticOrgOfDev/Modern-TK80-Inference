# Native ASIO (Windows)

Modern-TK80 is a Windows desktop app. Audio I/O is native, not browser.

## Current path

Python + PortAudio ASIO host via `sounddevice`.

- Driver: Focusrite USB ASIO
- Device selection: PortAudio device index stored on the track
- Recording: `app/backend/asio.py` opens an InputStream and writes WAV

## Why not the browser

`navigator.mediaDevices` uses WASAPI. It cannot open the ASIO driver
and its device ids do not map to PortAudio indices. The app enumerates
ASIO devices from the backend and arms a specific index.

## C++ path (later)

A small C++ helper can sit under this folder if we need direct ASIO SDK
access (channel mapping, exclusive open, or lower latency than PortAudio).
The Python layer stays the studio API either way.
