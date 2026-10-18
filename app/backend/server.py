"""FastAPI server wrapping the K80 interconnector and DieFusionCore."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from drivers.interconnector import Interconnector, InterconnectorError
from drivers.interconnector.diefusion import DieFusionCore

log = logging.getLogger("tk80.app")

app = FastAPI(title="Modern-TK80 App")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ic: Optional[Interconnector] = None
_fusion: Optional[DieFusionCore] = None

# In-memory creator state (starter setup)
_chat: List[Dict[str, str]] = []
_audio_clips: List[Dict[str, Any]] = []
_video_frames: List[Dict[str, Any]] = []


def get_ic() -> Interconnector:
    global _ic, _fusion
    if _ic is None:
        try:
            _ic = Interconnector()
            _fusion = DieFusionCore(_ic.dies)
        except InterconnectorError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    return _ic


def get_fusion() -> DieFusionCore:
    get_ic()
    assert _fusion is not None
    return _fusion


class LoadRequest(BaseModel):
    model: str
    backend: str = "llama"
    modality: str = "llm"
    die: int = 0
    split: str = "single"


class GenerateRequest(BaseModel):
    request: Any
    die: Optional[int] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    die: Optional[int] = None
    max_tokens: int = 256
    temperature: float = 0.7


class AudioEditRequest(BaseModel):
    clip_id: int
    action: str  # trim, gain, reverse, silence
    start: Optional[float] = None
    end: Optional[float] = None
    gain: Optional[float] = None


class VideoEditRequest(BaseModel):
    action: str  # add_frame, delete_frame, reorder, set_duration
    frame_id: Optional[int] = None
    prompt: Optional[str] = None
    duration: Optional[float] = None
    new_order: Optional[List[int]] = None


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    ic = get_ic()
    return ic.status()


@app.get("/api/advertise")
def get_advertise() -> Dict[str, Any]:
    ic = get_ic()
    return ic.advertise()


@app.get("/api/fusion")
def fusion_status() -> Dict[str, Any]:
    return get_fusion().status()


@app.post("/api/fusion/activate")
def fusion_activate(strategy: str = "pipeline") -> Dict[str, Any]:
    try:
        plan = get_fusion().activate(strategy)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "strategy": plan.strategy,
        "dies": plan.dies,
        "capacity_mb": plan.capacity_mb,
        "ready": plan.ready,
        "note": plan.note,
    }


@app.post("/api/fusion/deactivate")
def fusion_deactivate() -> Dict[str, str]:
    get_fusion().deactivate()
    return {"ok": "deactivated"}


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
    if not isinstance(result, (str, dict, list, int, float, bool, type(None))):
        result = str(result)
    return {"result": result}


@app.post("/api/chat")
def chat(body: ChatRequest) -> Dict[str, Any]:
    """Multi-turn chat. Stores history server-side."""
    ic = get_ic()
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    _chat.clear()
    _chat.extend(messages)
    try:
        result = ic.generate(
            {
                "messages": messages,
                "max_tokens": body.max_tokens,
                "temperature": body.temperature,
            },
            die=body.die,
        )
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    text = result if isinstance(result, str) else str(result)
    _chat.append({"role": "assistant", "content": text})
    return {"result": text, "history": _chat}


@app.get("/api/chat/history")
def chat_history() -> Dict[str, Any]:
    return {"history": _chat}


@app.post("/api/chat/clear")
def chat_clear() -> Dict[str, str]:
    _chat.clear()
    return {"ok": "cleared"}


@app.get("/api/audio/clips")
def list_clips() -> Dict[str, Any]:
    return {"clips": _audio_clips}


@app.post("/api/audio/clips")
def add_clip(name: str, duration: float = 0.0, path: str = "") -> Dict[str, Any]:
    clip = {
        "id": len(_audio_clips),
        "name": name,
        "duration": duration,
        "path": path,
        "gain": 1.0,
        "start": 0.0,
        "end": duration,
    }
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/edit")
def edit_audio(body: AudioEditRequest) -> Dict[str, Any]:
    if body.clip_id < 0 or body.clip_id >= len(_audio_clips):
        raise HTTPException(status_code=404, detail="clip not found")
    clip = _audio_clips[body.clip_id]
    if body.action == "trim":
        if body.start is not None:
            clip["start"] = body.start
        if body.end is not None:
            clip["end"] = body.end
    elif body.action == "gain":
        if body.gain is not None:
            clip["gain"] = body.gain
    elif body.action == "reverse":
        clip["reversed"] = not clip.get("reversed", False)
    elif body.action == "silence":
        clip["gain"] = 0.0
    else:
        raise HTTPException(status_code=400, detail="unknown action")
    return clip


@app.get("/api/video/frames")
def list_frames() -> Dict[str, Any]:
    return {"frames": _video_frames}


@app.post("/api/video/edit")
def edit_video(body: VideoEditRequest) -> Dict[str, Any]:
    if body.action == "add_frame":
        frame = {
            "id": len(_video_frames),
            "prompt": body.prompt or "",
            "duration": body.duration or 1.0,
        }
        _video_frames.append(frame)
        return {"frames": _video_frames}
    if body.action == "delete_frame" and body.frame_id is not None:
        _video_frames[:] = [f for f in _video_frames if f["id"] != body.frame_id]
        return {"frames": _video_frames}
    if body.action == "reorder" and body.new_order is not None:
        by_id = {f["id"]: f for f in _video_frames}
        _video_frames[:] = [by_id[i] for i in body.new_order if i in by_id]
        return {"frames": _video_frames}
    if body.action == "set_duration" and body.frame_id is not None and body.duration is not None:
        for f in _video_frames:
            if f["id"] == body.frame_id:
                f["duration"] = body.duration
                break
        return {"frames": _video_frames}
    raise HTTPException(status_code=400, detail="unknown or incomplete action")


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
