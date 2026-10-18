"""FastAPI server wrapping the K80 interconnector and DieFusionCore."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from drivers.interconnector import Interconnector, InterconnectorError
from drivers.interconnector.diefusion import DieFusionCore

from .audio import (
    COMMON_RATES,
    DEFAULT_SAMPLE_RATE,
    SCARLETT_PROFILES,
    detect_scarlett,
    make_clip,
    make_track,
    save_upload,
)

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

_chat: List[Dict[str, str]] = []
_audio_tracks: List[Dict[str, Any]] = []
_audio_clips: List[Dict[str, Any]] = []
_video_frames: List[Dict[str, Any]] = []
_sample_rate: int = DEFAULT_SAMPLE_RATE


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


def _ensure_track() -> int:
    if not _audio_tracks:
        _audio_tracks.append(make_track(0, "Track 1", "stereo", _sample_rate))
    return _audio_tracks[0]["id"]


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
    action: str
    start: Optional[float] = None
    end: Optional[float] = None
    gain: Optional[float] = None


class TrackUpdate(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    gain: Optional[float] = None
    mute: Optional[bool] = None
    solo: Optional[bool] = None
    armed: Optional[bool] = None
    device_id: Optional[str] = None
    device_label: Optional[str] = None
    sample_rate: Optional[int] = None


class SampleRateRequest(BaseModel):
    sample_rate: int


class VideoEditRequest(BaseModel):
    action: str
    frame_id: Optional[int] = None
    prompt: Optional[str] = None
    duration: Optional[float] = None
    new_order: Optional[List[int]] = None


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    return get_ic().status()


@app.get("/api/advertise")
def get_advertise() -> Dict[str, Any]:
    return get_ic().advertise()


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
    try:
        get_ic().load(body.model, backend=body.backend, modality=body.modality, die=body.die, split=body.split)
    except (InterconnectorError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "loaded"}


@app.post("/api/unload")
def unload_model(die: int) -> Dict[str, str]:
    try:
        get_ic().unload(die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "unloaded"}


@app.post("/api/generate")
def generate(body: GenerateRequest) -> Dict[str, Any]:
    try:
        result = get_ic().generate(body.request, die=body.die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not isinstance(result, (str, dict, list, int, float, bool, type(None))):
        result = str(result)
    return {"result": result}


@app.post("/api/chat")
def chat(body: ChatRequest) -> Dict[str, Any]:
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    _chat.clear()
    _chat.extend(messages)
    try:
        result = get_ic().generate(
            {"messages": messages, "max_tokens": body.max_tokens, "temperature": body.temperature},
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


# ---- Studio audio settings ----
@app.get("/api/audio/settings")
def audio_settings() -> Dict[str, Any]:
    return {
        "sample_rate": _sample_rate,
        "default_sample_rate": DEFAULT_SAMPLE_RATE,
        "common_rates": list(COMMON_RATES),
        "scarlett_profiles": SCARLETT_PROFILES,
    }


@app.post("/api/audio/settings")
def set_audio_settings(body: SampleRateRequest) -> Dict[str, Any]:
    global _sample_rate
    if body.sample_rate not in COMMON_RATES:
        raise HTTPException(status_code=400, detail=f"unsupported rate: {body.sample_rate}")
    _sample_rate = body.sample_rate
    return {"sample_rate": _sample_rate}


# ---- Tracks ----
@app.get("/api/audio/tracks")
def list_tracks() -> Dict[str, Any]:
    return {"tracks": _audio_tracks}


@app.post("/api/audio/tracks")
def create_track(name: str = "Track", channel: str = "stereo") -> Dict[str, Any]:
    track = make_track(len(_audio_tracks), name, channel, _sample_rate)
    _audio_tracks.append(track)
    return track


@app.post("/api/audio/tracks/{track_id}")
def update_track(track_id: int, body: TrackUpdate) -> Dict[str, Any]:
    track = next((t for t in _audio_tracks if t["id"] == track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="track not found")
    data = body.model_dump(exclude_none=True)
    if "channel" in data and data["channel"] not in ("stereo", "left", "right"):
        raise HTTPException(status_code=400, detail="channel must be stereo, left, or right")
    if "sample_rate" in data and data["sample_rate"] not in COMMON_RATES:
        raise HTTPException(status_code=400, detail="unsupported sample rate")
    if data.get("armed") is True:
        for t in _audio_tracks:
            if t["id"] != track_id:
                t["armed"] = False
    track.update(data)
    # Attach Scarlett profile when a matching device is armed
    label = track.get("device_label") or ""
    track["scarlett"] = detect_scarlett(label) if track.get("armed") else None
    return track


# ---- Clips ----
@app.get("/api/audio/clips")
def list_clips() -> Dict[str, Any]:
    return {"clips": _audio_clips}


@app.post("/api/audio/clips")
def add_clip(name: str, duration: float = 0.0, path: str = "", track_id: Optional[int] = None) -> Dict[str, Any]:
    if track_id is None:
        track_id = _ensure_track()
    clip = make_clip(len(_audio_clips), name, Path(path) if path else None, duration, track_id, _sample_rate)
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/upload")
async def upload_audio(
    file: UploadFile = File(...),
    track_id: Optional[int] = Form(None),
) -> Dict[str, Any]:
    if track_id is None:
        track_id = _ensure_track()
    data = await file.read()
    dest = save_upload(file.filename or "clip.wav", data)
    clip = make_clip(len(_audio_clips), dest.name, dest, track_id=track_id, sample_rate=_sample_rate)
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/record")
async def save_recording(
    file: UploadFile = File(...),
    track_id: int = Form(...),
) -> Dict[str, Any]:
    track = next((t for t in _audio_tracks if t["id"] == track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="track not found")
    if not track.get("armed"):
        raise HTTPException(status_code=400, detail="track is not armed")
    data = await file.read()
    dest = save_upload(file.filename or "recording.webm", data)
    rate = track.get("sample_rate") or _sample_rate
    clip = make_clip(len(_audio_clips), dest.name, dest, track_id=track_id, sample_rate=rate)
    _audio_clips.append(clip)
    return clip


@app.get("/api/audio/file/{clip_id}")
def audio_file(clip_id: int):
    if clip_id < 0 or clip_id >= len(_audio_clips):
        raise HTTPException(status_code=404, detail="clip not found")
    path = _audio_clips[clip_id].get("path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path)


@app.post("/api/audio/edit")
def edit_audio(body: AudioEditRequest) -> Dict[str, Any]:
    if body.clip_id < 0 or body.clip_id >= len(_audio_clips):
        raise HTTPException(status_code=404, detail="clip not found")
    clip = _audio_clips[body.clip_id]
    if body.action == "trim":
        if body.start is not None:
            clip["start"] = max(0.0, body.start)
        if body.end is not None:
            clip["end"] = min(clip["duration"], body.end)
        if clip["end"] < clip["start"]:
            clip["end"] = clip["start"]
    elif body.action == "gain":
        if body.gain is not None:
            clip["gain"] = max(0.0, body.gain)
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
        frame = {"id": len(_video_frames), "prompt": body.prompt or "", "duration": body.duration or 1.0}
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
