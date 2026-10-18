# GUI

Tkinter interface for the K80 interconnector.

## Run

```bash
python -m gui.app
# or
python gui/app.py
```

Requires the same environment as the interconnector (R470 driver, CUDA 11.8, and the backends you plan to use).

## What it does

- Connects to available K80 dies on startup
- Shows status (dies, metrics, loaded models)
- Load / unload a model (modality, backend, die, split)
- Generate from a prompt (LLM, image prompt, voice path, or agent goal)
- Show cluster advertisement

Image results are shown as their string representation. Save the PIL image from the Python API if you need a file.
