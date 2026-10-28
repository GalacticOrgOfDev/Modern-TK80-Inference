# Modern-TK80 App

Windows 10+ creator app. Native window via pywebview.

## Studios

| Tab | Ships | Staged |
|-----|-------|--------|
| Chat | History, tool indicator, direct commands | K80 inference on Connect |
| Audio | Tracks, clips, ASIO, sequencer, effects, mix, bounce, 30-band EQ | VST binary needs SDK |
| Video | Timeline, text, VFX stubs, audio split, JSON export | MP4 encode (`encode_mp4()` in `backend/export.py:41-70` exists, but no route calls it; output unverified), real VFX render |
| Fusion | Status and plan | Dual-die data movement |

## Layout

```
app/
  backend/     FastAPI
  frontend/    HTML/CSS/JS
  launcher.py  pywebview window
  packaging/   MSI notes
```

## Run

```bash
pip install -r requirements.txt
python -m app.launcher
```

Connect is manual. The DAW does not need a GPU.

## Packaging

`Modern-TK80.exe` via `MTK80Setup.msi`. See `packaging/README.md`.
