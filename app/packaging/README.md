# Packaging for Windows 10+

Goal: a single installer that does not require the user to install Python.

## Planned steps

1. **Backend binary**  
   PyInstaller the FastAPI server + interconnector + required DLLs (CUDA, llama.cpp).

2. **Frontend**  
   Bundle `app/frontend/` as static files next to the binary.

3. **Launcher**  
   A small native launcher (or pywebview) that starts the backend and opens the window.

4. **Installer**  
   Inno Setup or MSIX to produce a Windows 10+ installer.

## Development run

```bash
pip install fastapi uvicorn pywebview
python -m app.launcher
```

## Notes

- CUDA 11.8 and the R470 driver must be present on the target machine for K80 use.
- The installer should detect or document the driver requirement.
- Video studio remains a shell until smaller video models or dual-die unification are ready.
