# Modern-TK80 App

Custom desktop application for Windows 10 and later.

Three studios on top of the K80 interconnector:

- **LLM** — chat / generate interface
- **Audio** — mini studio (load voice model, transcribe, simple controls)
- **Video** — mini studio (timeline placeholder + image/video path; full video models still constrained by the 12 GB die)

## Architecture

```
app/
  backend/          FastAPI server wrapping the interconnector
  frontend/         Custom HTML/CSS/JS UI
  launcher.py       Starts the server and opens a native window
```

## Run (development)

```bash
pip install fastapi uvicorn pywebview
python -m app.launcher
```

Opens a native window (pywebview). Falls back to the default browser if pywebview is unavailable.

## Windows install (Windows 10+)

1. Build the backend with PyInstaller.
2. Bundle the frontend static files.
3. Package with Inno Setup or MSIX for a proper installer.

See `packaging/README.md` for the planned steps.

## Notes

- Tkinter GUI in `gui/` is deprecated for this use.
- Video studio is a shell ready for smaller models or frame-by-frame work; large video models still exceed one K80 die.
