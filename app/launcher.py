#!/usr/bin/env python3
"""Launch the Modern-TK80 custom app.

Starts the FastAPI backend and opens a native window (pywebview) or browser.
"""

from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from app.backend.server import app as fastapi_app

HOST = "127.0.0.1"
PORT = 8765
FRONTEND = Path(__file__).parent / "frontend"


def _mount_frontend() -> None:
    from fastapi.staticfiles import StaticFiles

    if FRONTEND.exists():
        fastapi_app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


def _run_server() -> None:
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="info")


def main() -> None:
    _mount_frontend()
    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()
    time.sleep(1.2)

    url = f"http://{HOST}:{PORT}"
    try:
        import webview

        webview.create_window("Modern-TK80", url, width=1100, height=760)
        webview.start()
    except ImportError:
        print(f"pywebview not installed. Opening browser: {url}")
        webbrowser.open(url)
        thread.join()


if __name__ == "__main__":
    main()
