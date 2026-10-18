# Modern-TK80 App

Starter creator setup for Windows 10 and later.

## Studios

- **Chat** — multi-turn LLM conversation with history
- **Audio** — mini studio: add clips, trim, gain, reverse, silence, transcribe
- **Video** — mini studio: add / generate / delete frames, set duration, timeline
- **Fusion** — DieFusionCore status and activation

## Architecture

```
app/
  backend/          FastAPI (chat, audio edit, video edit, fusion)
  frontend/         Custom HTML/CSS/JS
  launcher.py       Native window via pywebview
```

## Run

```bash
pip install fastapi uvicorn pywebview
python -m app.launcher
```

## DieFusionCore

Foundation for treating the two independent K80 dies as one logical device.
See `drivers/interconnector/diefusion.py` and the Fusion tab.

Strategies planned: pipeline, layer, data. Data movement comes next.
