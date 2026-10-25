#!/usr/bin/env python3
"""Launch the Modern-TK80 custom app.

Starts the FastAPI backend and opens a native window (pywebview) or browser.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import uvicorn

from app.backend.server import app as fastapi_app

HOST = "127.0.0.1"
PORT = 8765
FRONTEND = Path(__file__).parent / "frontend"


def _mount_frontend() -> None:
    """Mount the frontend directory at / if it exists.

    StaticFiles serves index.html for directory requests.
    """
    from fastapi.staticfiles import StaticFiles

    if FRONTEND.exists():
        fastapi_app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


def _run_server() -> None:
    """Run the FastAPI app with uvicorn on HOST:PORT.

    Blocks the calling thread.
    """
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="info")


def main() -> None:
    """Start the backend and open a native Windows window.

    pywebview is required. There is no browser fallback.
    """
    _mount_frontend()
    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()
    time.sleep(1.2)

    url = f"http://{HOST}:{PORT}"
    try:
        import webview
    except ImportError as e:
        raise SystemExit(
            "pywebview is required for the native window. "
            "Install it with: pip install pywebview"
        ) from e

    webview.create_window("Modern-TK80", url, width=1280, height=800)
    webview.start()


if __name__ == "__main__":
    main()
