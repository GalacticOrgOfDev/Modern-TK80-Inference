"""FastAPI server wrapping the K80 interconnector and DieFusionCore.

Modern-TK80 is a Windows desktop app. Audio devices are native ASIO
(PortAudio indices), not browser media device ids.
"""

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

from .asio import (
    ASIO_BUFFERS,
    DEFAULT_BUFFER,
    AsioRecorder,
    asio_profile,
    list_asio_devices,
    probe_asio,
)
from .audio import (
    COMMON_RATES,
    DEFAULT_SAMPLE_RATE,
    SCARLETT_PROFILES,
    UPLOAD_DIR,
    detect_scarlett,
    make_clip,
    make_track,
    save_upload,
)
from .music import (
    DEFAULT_BPM,
    INSTRUMENTS,
    detect_bpm,
    generate_loop,
    make_pattern,
    render_instrument,
    render_pattern,
    save_pcm,
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
_asio_enabled: bool = False
_asio_buffer: int = DEFAULT_BUFFER
_asio_recorder = AsioRecorder()
_asio_track_id: Optional[int] = None
_bpm: float = DEFAULT_BPM
_pattern: Dict[str, List[int]] = make_pattern()


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


def _validate_rate_for_track(track: Dict[str, Any], rate: int) -> None:
    scar = track.get("scarlett")
    if scar and rate not in scar.get("rates", []):
        raise HTTPException(
            status_code=400,
            detail=f"{scar['name']} does not support {rate} Hz",
        )


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
    asio_index: Optional[int] = None
    device_label: Optional[str] = None
    sample_rate: Optional[int] = None


class AudioSettingsRequest(BaseModel):
    sample_rate: Optional[int] = None
    asio: Optional[bool] = None
    buffer: Optional[int] = None


class AsioStartRequest(BaseModel):
    track_id: int


class BpmRequest(BaseModel):
    bpm: float


class PatternRequest(BaseModel):
    pattern: Dict[str, List[int]]


class InstrumentRequest(BaseModel):
    instrument: str
    note: int = 60
    duration: float = 0.4
    track_id: Optional[int] = None


class LoopRequest(BaseModel):
    style: str = "basic"
    bars: int = 1
    track_id: Optional[int] = None


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


@app.get("/api/audio/settings")
def audio_settings() -> Dict[str, Any]:
    return {
        "sample_rate": _sample_rate,
        "default_sample_rate": DEFAULT_SAMPLE_RATE,
        "common_rates": list(COMMON_RATES),
        "scarlett_profiles": SCARLETT_PROFILES,
        "asio": _asio_enabled,
        "buffer": _asio_buffer,
        "buffers": list(ASIO_BUFFERS),
        "asio_probe": probe_asio(),
        "asio_profile": asio_profile(_sample_rate, _asio_buffer),
        "asio_recording": _asio_recorder.recording,
        "bpm": _bpm,
    }


@app.post("/api/audio/settings")
def set_audio_settings(body: AudioSettingsRequest) -> Dict[str, Any]:
    global _sample_rate, _asio_enabled, _asio_buffer
    if body.sample_rate is not None:
        if body.sample_rate not in COMMON_RATES:
            raise HTTPException(status_code=400, detail=f"unsupported rate: {body.sample_rate}")
        _sample_rate = body.sample_rate
    if body.asio is not None:
        _asio_enabled = body.asio
    if body.buffer is not None:
        if body.buffer not in ASIO_BUFFERS:
            raise HTTPException(status_code=400, detail=f"unsupported buffer: {body.buffer}")
        _asio_buffer = body.buffer
    return {
        "sample_rate": _sample_rate,
        "asio": _asio_enabled,
        "buffer": _asio_buffer,
        "asio_profile": asio_profile(_sample_rate, _asio_buffer),
        "asio_probe": probe_asio(),
        "bpm": _bpm,
    }


@app.get("/api/audio/asio/devices")
def asio_devices() -> Dict[str, Any]:
    return {"devices": list_asio_devices(), "probe": probe_asio()}


@app.post("/api/audio/asio/start")
def asio_start(body: AsioStartRequest) -> Dict[str, Any]:
    global _asio_track_id
    if not _asio_enabled:
        raise HTTPException(status_code=400, detail="ASIO is not enabled")
    track = next((t for t in _audio_tracks if t["id"] == body.track_id), None)
    if track is None:
        raise HTTPException(status_code=404, detail="track not found")
    if not track.get("armed"):
        raise HTTPException(status_code=400, detail="track is not armed")
    if _asio_recorder.recording:
        raise HTTPException(status_code=400, detail="already recording")

    rate = track.get("sample_rate") or _sample_rate
    _validate_rate_for_track(track, rate)
    channels = 2 if track.get("channel") == "stereo" else 1
    path = UPLOAD_DIR / f"asio_track{track['id']}.wav"
    try:
        info = _asio_recorder.start(
            path,
            sample_rate=rate,
            buffer=_asio_buffer,
            channels=channels,
            device_index=track.get("asio_index"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _asio_track_id = track["id"]
    return info


@app.post("/api/audio/asio/stop")
def asio_stop() -> Dict[str, Any]:
    global _asio_track_id
    if not _asio_recorder.recording:
        raise HTTPException(status_code=400, detail="not recording")
    try:
        info = _asio_recorder.stop()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    track_id = _asio_track_id
    _asio_track_id = None
    path = Path(info["path"]) if info.get("path") else None
    clip = make_clip(
        len(_audio_clips),
        path.name if path else "asio.wav",
        path,
        track_id=track_id,
        sample_rate=info.get("sample_rate", _sample_rate),
    )
    clip["asio"] = True
    clip["buffer"] = info.get("buffer")
    clip["device"] = info.get("device")
    _audio_clips.append(clip)
    info["clip"] = clip
    return info


# ---- Music: BPM, sequencer, instruments, loops ----
@app.get("/api/music/state")
def music_state() -> Dict[str, Any]:
    return {
        "bpm": _bpm,
        "pattern": _pattern,
        "instruments": list(INSTRUMENTS),
        "sample_rate": _sample_rate,
    }


@app.post("/api/music/bpm")
def set_bpm(body: BpmRequest) -> Dict[str, Any]:
    global _bpm
    if body.bpm < 40 or body.bpm > 220:
        raise HTTPException(status_code=400, detail="bpm out of range")
    _bpm = body.bpm
    return {"bpm": _bpm}


@app.post("/api/music/bpm/detect")
def detect_bpm_from_clip(clip_id: int) -> Dict[str, Any]:
    global _bpm
    if clip_id < 0 or clip_id >= len(_audio_clips):
        raise HTTPException(status_code=404, detail="clip not found")
    path = _audio_clips[clip_id].get("path")
    if not path:
        raise HTTPException(status_code=400, detail="clip has no file")
    result = detect_bpm(Path(path))
    if result.get("confidence", 0) > 0.2:
        _bpm = result["bpm"]
    result["applied"] = _bpm
    return result


@app.get("/api/music/pattern")
def get_pattern() -> Dict[str, Any]:
    return {"pattern": _pattern, "bpm": _bpm}


@app.post("/api/music/pattern")
def set_pattern(body: PatternRequest) -> Dict[str, Any]:
    global _pattern
    clean: Dict[str, List[int]] = {}
    for name in INSTRUMENTS:
        steps = body.pattern.get(name, [0] * 16)
        clean[name] = [1 if int(s) else 0 for s in steps[:16]]
        while len(clean[name]) < 16:
            clean[name].append(0)
    _pattern = clean
    return {"pattern": _pattern}


@app.post("/api/music/instrument")
def generate_instrument(body: InstrumentRequest) -> Dict[str, Any]:
    if body.instrument not in INSTRUMENTS:
        raise HTTPException(status_code=400, detail="unknown instrument")
    track_id = body.track_id if body.track_id is not None else _ensure_track()
    pcm = render_instrument(body.instrument, body.duration, _sample_rate, body.note)
    path = save_pcm(f"{body.instrument}_{len(_audio_clips)}.wav", pcm, _sample_rate)
    clip = make_clip(len(_audio_clips), path.name, path, track_id=track_id, sample_rate=_sample_rate)
    clip["instrument"] = body.instrument
    clip["note"] = body.note
    _audio_clips.append(clip)
    return clip


@app.post("/api/music/loop")
def generate_loop_clip(body: LoopRequest) -> Dict[str, Any]:
    track_id = body.track_id if body.track_id is not None else _ensure_track()
    pcm = generate_loop(_bpm, body.bars, _sample_rate, body.style)
    path = save_pcm(f"loop_{body.style}_{len(_audio_clips)}.wav", pcm, _sample_rate)
    clip = make_clip(len(_audio_clips), path.name, path, track_id=track_id, sample_rate=_sample_rate)
    clip["bpm"] = _bpm
    clip["style"] = body.style
    _audio_clips.append(clip)
    return clip


@app.post("/api/music/render")
def render_current_pattern(track_id: Optional[int] = None, bars: int = 1) -> Dict[str, Any]:
    if track_id is None:
        track_id = _ensure_track()
    pcm = render_pattern(_pattern, _bpm, _sample_rate, bars)
    path = save_pcm(f"pattern_{len(_audio_clips)}.wav", pcm, _sample_rate)
    clip = make_clip(len(_audio_clips), path.name, path, track_id=track_id, sample_rate=_sample_rate)
    clip["bpm"] = _bpm
    _audio_clips.append(clip)
    return clip


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

    arming = data.pop("armed", None)
    track.update(data)
    label = track.get("device_label") or ""
    track["scarlett"] = detect_scarlett(label)

    if "sample_rate" in data:
        _validate_rate_for_track(track, data["sample_rate"])
    else:
        _validate_rate_for_track(track, track.get("sample_rate") or _sample_rate)

    if arming is True:
        for t in _audio_tracks:
            if t["id"] != track_id:
                t["armed"] = False
        track["armed"] = True
        track["sample_rate"] = _sample_rate
    elif arming is False:
        track["armed"] = False
        track["scarlett"] = None
    return track


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
