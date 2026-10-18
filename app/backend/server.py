"""FastAPI server wrapping the K80 interconnector."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from drivers.interconnector import Interconnector, InterconnectorError

log = logging.getLogger("tk80.app")

app = FastAPI(title="Modern-TK80 App")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ic: Optional[Interconnector] = None


def get_ic() -> Interconnector:
    global _ic
    if _ic is None:
        try:
            _ic = Interconnector()
        except InterconnectorError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    return _ic


class LoadRequest(BaseModel):
    model: str
    backend: str = "llama"
    modality: str = "llm"
    die: int = 0
    split: str = "single"


class GenerateRequest(BaseModel):
    request: Any
    die: Optional[int] = None


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    ic = get_ic()
    return ic.status()


@app.get("/api/advertise")
def get_advertise() -> Dict[str, Any]:
    ic = get_ic()
    return ic.advertise()


@app.post("/api/load")
def load_model(body: LoadRequest) -> Dict[str, str]:
    ic = get_ic()
    try:
        ic.load(
            body.model,
            backend=body.backend,
            modality=body.modality,
            die=body.die,
            split=body.split,
        )
    except (InterconnectorError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "loaded"}


@app.post("/api/unload")
def unload_model(die: int) -> Dict[str, str]:
    ic = get_ic()
    try:
        ic.unload(die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "unloaded"}


@app.post("/api/generate")
def generate(body: GenerateRequest) -> Dict[str, Any]:
    ic = get_ic()
    try:
        result = ic.generate(body.request, die=body.die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Normalize non-JSON results
    if not isinstance(result, (str, dict, list, int, float, bool, type(None))):
        result = str(result)
    return {"result": result}


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
