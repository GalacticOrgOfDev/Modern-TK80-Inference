"""FastAPI server wrapping the K80 interconnector and DieFusionCore.

Modern-TK80 is a Windows desktop app. Audio devices are native ASIO
(PortAudio indices), not browser media device ids.
"""

from __future__ import annotations

import math
import logging
from pathlib import Path
import json as _json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from drivers.interconnector import Interconnector, InterconnectorError
from drivers.interconnector.diefusion import DieFusionCore

from .formats import catalog as format_catalog
from .asio import (
    ASIO_BUFFERS,
    DEFAULT_BUFFER,
    AsioRecorder,
    asio_profile,
    list_asio_devices,
    probe_asio,
)
from . import audio as _audio_mod
from .paths import reserve_unique, safe_filename
from .audio import (
    COMMON_RATES,
    DEFAULT_SAMPLE_RATE,
    SCARLETT_PROFILES,
    default_master,
    detect_scarlett,
    make_clip,
    make_track,
    mix_arrangement,
    UnmixableClipError,
    process_clip,
    save_upload,
)
from .daw_state import (
    DEFAULT_TRACK_TYPE,
    IdCounter,
    check_track_type,
    find_by_id,
    remove_track,
    restore_clip_snapshot,
)
from .effects import apply_effect
from .vst import make_vst, PLUGIN_TYPES, EFFECT_PRESETS, PromptDesignUnavailable, list_library
from .vst_ui import (
    OBJECT_TYPES,
    add_object,
    add_parameter,
    bind_object,
    default_project,
    export_project,
    list_presets,
)
from .export import encode_mp4, export_animation, export_timeline as export_full_timeline
from .video import (
    ANIM_FORMATS,
    BUILTIN_VFX,
    add_animation,
    add_text_vfx,
    apply_vfx,
    is_supported_video,
    make_3d,
    make_clip as make_video_clip,
    make_text,
    make_text_scene,
    make_vfx,
    reorder,
    render_vfx,
    save_video,
    set_text_style,
    set_transition,
    split_audio,
)
from .vst_press import press_vst, sdk_path
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
from .tools import list_tools, parse_intent, parse_tool_call, tool_prompt

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
_audio_tracks: List[Dict[str, Any]] = [
    make_track(i, f"Audio {i + 1}", "stereo", 44100) for i in range(4)
]
_audio_clips: List[Dict[str, Any]] = []
# Ids come from counters, never from list length or position, so a deleted
# track or clip id is never reused. Undo does not touch the counters.
_track_ids = IdCounter.after(_audio_tracks)
_clip_ids = IdCounter.after(_audio_clips)
_undo_stack: List[Dict[str, Any]] = []
_MAX_UNDO = 20
_video_frames: List[Dict[str, Any]] = []
_text_objects: List[Dict[str, Any]] = []
_objects_3d: List[Dict[str, Any]] = []
_video_tracks: List[Dict[str, Any]] = [{"id": 0, "name": "Video 1", "kind": "video"}]
_video_audio_tracks: List[Dict[str, Any]] = [{"id": 0, "name": "Audio 1", "kind": "audio"}]
_sample_rate: int = DEFAULT_SAMPLE_RATE
_asio_enabled: bool = False
_asio_buffer: int = DEFAULT_BUFFER
_asio_recorder = AsioRecorder()
_asio_track_id: Optional[int] = None
_bpm: float = DEFAULT_BPM
_pattern: Dict[str, List[int]] = make_pattern()
_master: Dict[str, Any] = default_master()
_vst_project: Dict[str, Any] = default_project()


def get_ic() -> Interconnector:
    """Return the shared Interconnector, creating it on first use.

Raises:
    HTTPException: Interconnector construction fails."""
    global _ic, _fusion
    if _ic is None:
        try:
            _ic = Interconnector()
            _fusion = DieFusionCore(_ic.dies)
        except InterconnectorError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
    return _ic


def get_fusion() -> DieFusionCore:
    """Return the DieFusionCore, creating the Interconnector if needed."""
    get_ic()
    assert _fusion is not None
    return _fusion


def _push_undo(kind: str, data: Dict[str, Any]) -> None:
    """Keep a short undo stack for audio edits. Stores a snapshot."""
    _undo_stack.append({"kind": kind, "data": dict(data)})
    if len(_undo_stack) > _MAX_UNDO:
        _undo_stack.pop(0)


def _restore_undo(entry: Dict[str, Any]) -> str:
    """Restore a clip from an undo snapshot.

Returns "replaced", "appended", or "dropped". A snapshot for a clip whose
track has been deleted is dropped rather than brought back."""
    return restore_clip_snapshot(_audio_clips, _audio_tracks, entry.get("data") or {})


def _get_clip(clip_id: Any) -> Dict[str, Any]:
    """Return the clip with this id.

Raises:
    HTTPException: 404 when no clip has the id."""
    clip = find_by_id(_audio_clips, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return clip


def _get_track(track_id: Any) -> Dict[str, Any]:
    """Return the track with this id.

Raises:
    HTTPException: 404 when no track has the id."""
    track = find_by_id(_audio_tracks, track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="track not found")
    return track


def _ensure_track() -> int:
    """Return the id of the first audio track, creating one if none exist."""
    if not _audio_tracks:
        _audio_tracks.append(make_track(_track_ids.next_id(), "Track 1", "stereo", _sample_rate))
    return _audio_tracks[0]["id"]


def _track_for_new_clip(track_id: Optional[int]) -> int:
    """Return the track id a new clip should go on.

None means the first track (created if there are none). A supplied id must
name an existing track.

Raises:
    HTTPException: 404 when a supplied track id has no track."""
    if track_id is None:
        return _ensure_track()
    return _get_track(track_id)["id"]


def _validate_rate_for_track(track: Dict[str, Any], rate: int) -> None:
    """Raise if the track Scarlett profile does not support the rate.

Args:
    track: Track dict.
    rate: Sample rate in Hz."""
    scar = track.get("scarlett")
    if scar and rate not in scar.get("rates", []):
        raise HTTPException(
            status_code=400,
            detail=f"{scar['name']} does not support {rate} Hz",
        )


def _refresh_clip(clip: Dict[str, Any], path: Path, reset: tuple = ()) -> None:
    """Point a clip at a rewritten file, in place.

The file-derived fields (path, name, duration, start, end, peaks) are
rebuilt from the new file by make_clip. Every other field (gain, mute,
position, track_id, effects, trim_in, trim_out, reversed, silenced, ...)
is kept, because apply_effect writes the whole source processed at the same
length, so they still mean the same thing. Keys in `reset` are removed:
callers that bake a window or a reversal pass ("trim_in", "trim_out").

Args:
    clip: Existing clip dict.
    path: New audio file path.
    reset: Clip keys to drop because the new file already bakes them."""
    fresh = make_clip(
        clip["id"],
        path.name,
        path,
        track_id=clip.get("track_id"),
        sample_rate=clip.get("sample_rate", _sample_rate),
        position=clip.get("position", 0.0),
    )
    for key in ("path", "name", "duration", "start", "end", "peaks"):
        clip[key] = fresh[key]
    if not clip.get("effects"):
        clip["effects"] = fresh["effects"]
    for key in reset:
        clip.pop(key, None)


def _dispatch_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a named creator tool and return its result dict.

Args:
    name: Tool name.
    args: Tool arguments.

Raises:
    HTTPException: Unknown tool or bad arguments."""
    global _bpm
    track_id = args.get("track_id")
    if track_id is None:
        track_id = _ensure_track()

    if name == "set_bpm":
        bpm = float(args.get("bpm", _bpm))
        if bpm < 40 or bpm > 220:
            raise HTTPException(status_code=400, detail="bpm out of range")
        _bpm = bpm
        return {"ok": True, "name": name, "bpm": _bpm}

    if name == "generate_instrument":
        instrument = str(args.get("instrument", "kick"))
        if instrument not in INSTRUMENTS:
            raise HTTPException(status_code=400, detail="unknown instrument")
        note = int(args.get("note", 60))
        duration = float(args.get("duration", 0.4))
        _get_track(track_id)
        pcm = render_instrument(instrument, duration, _sample_rate, note)
        clip_id = _clip_ids.next_id()
        path = save_pcm(f"{instrument}_{clip_id}.wav", pcm, _sample_rate)
        clip = make_clip(clip_id, path.name, path, track_id=track_id, sample_rate=_sample_rate)
        clip["instrument"] = instrument
        clip["note"] = note
        _audio_clips.append(clip)
        return {"ok": True, "name": name, "clip": clip}

    if name == "generate_loop":
        style = str(args.get("style", "basic"))
        bars = int(args.get("bars", 1))
        _get_track(track_id)
        pcm = generate_loop(_bpm, bars, _sample_rate, style)
        clip_id = _clip_ids.next_id()
        path = save_pcm(f"loop_{style}_{clip_id}.wav", pcm, _sample_rate)
        clip = make_clip(clip_id, path.name, path, track_id=track_id, sample_rate=_sample_rate)
        clip["bpm"] = _bpm
        clip["style"] = style
        _audio_clips.append(clip)
        return {"ok": True, "name": name, "clip": clip}

    if name == "render_pattern":
        bars = int(args.get("bars", 1))
        _get_track(track_id)
        pcm = render_pattern(_pattern, _bpm, _sample_rate, bars)
        clip_id = _clip_ids.next_id()
        path = save_pcm(f"pattern_{clip_id}.wav", pcm, _sample_rate)
        clip = make_clip(clip_id, path.name, path, track_id=track_id, sample_rate=_sample_rate)
        clip["bpm"] = _bpm
        _audio_clips.append(clip)
        return {"ok": True, "name": name, "clip": clip}

    if name == "detect_bpm":
        raw_id = args.get("clip_id")
        if raw_id is None:
            if not _audio_clips:
                raise HTTPException(status_code=404, detail="clip not found")
            raw_id = _audio_clips[-1]["id"]
        raw_path = _get_clip(int(raw_id)).get("path")
        if not raw_path:
            raise HTTPException(status_code=400, detail="clip has no file")
        result = detect_bpm(Path(str(raw_path)))
        if result.get("confidence", 0) > 0.2:
            _bpm = result["bpm"]
        result["applied"] = _bpm
        result["name"] = name
        return result

    if name == "make_vst":
        plugin_name = str(args.get("name", "GeneratedPlugin"))
        effect = str(args.get("effect", "custom"))
        plugin_type = str(args.get("plugin_type", "effect"))
        prompt = str(args.get("prompt", ""))
        if plugin_type not in PLUGIN_TYPES:
            plugin_type = "effect"
        try:
            result = make_vst(plugin_name, plugin_type, effect, prompt=prompt)
        except PromptDesignUnavailable as e:
            raise HTTPException(status_code=501, detail=str(e)) from e
        result["name"] = "make_vst"
        return result

    if name == "vst_add_param":
        pname = str(args.get("name", "param"))
        default = float(args.get("default", 0.5))
        try:
            param = add_parameter(_vst_project, pname, default)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "name": name, "parameter": param}

    if name == "vst_add_object":
        kind = str(args.get("kind", "knob"))
        if kind not in OBJECT_TYPES:
            raise HTTPException(status_code=400, detail=f"kind must be one of {OBJECT_TYPES}")
        obj = add_object(
            _vst_project,
            kind,
            x=float(args.get("x", 20)),
            y=float(args.get("y", 20)),
            w=float(args.get("w", 60)),
            h=float(args.get("h", 60)),
            label=str(args.get("label", kind)),
            bind=args.get("bind"),
        )
        return {"ok": True, "name": name, "object": obj}

    if name == "vst_bind":
        try:
            obj = bind_object(_vst_project, int(args.get("object_id", 0)), str(args.get("param", "")))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "name": name, "object": obj}

    if name == "vst_export":
        result = export_project(_vst_project)
        result["name"] = "vst_export"
        return result

    if name == "vfx_add":
        clip = make_video_clip(
            len(_video_frames),
            str(args.get("prompt", "")),
            float(args.get("duration", 1.0)),
            vfx=str(args.get("vfx", "none")),
        )
        if args.get("description"):
            apply_vfx(clip, clip["vfx"], description=str(args.get("description")))
        _video_frames.append(clip)
        return {"ok": True, "name": name, "clip": clip}

    if name == "vfx_apply":
        frame_id = int(args.get("frame_id", -1))
        vfx = str(args.get("vfx", "none"))
        desc = str(args.get("description", ""))
        for f in _video_frames:
            if f["id"] == frame_id:
                apply_vfx(f, vfx, args.get("params"), desc)
                return {"ok": True, "name": name, "clip": f}
        raise HTTPException(status_code=404, detail="frame not found")

    if name == "vfx_make":
        info = make_vfx(str(args.get("name", "custom")), str(args.get("description", "")))
        return {"ok": True, "name": name, "vfx": info}

    if name == "text_add":
        obj = make_text(
            len(_text_objects),
            str(args.get("content", "text")),
            float(args.get("position", 0.0)),
            float(args.get("duration", 2.0)),
            str(args.get("texture", "plain")),
            float(args.get("x", 0.5)),
            float(args.get("y", 0.5)),
        )
        _text_objects.append(obj)
        return {"ok": True, "name": name, "text": obj}

    if name == "text_scene":
        steps = args.get("steps") or []
        if isinstance(steps, str):
            steps = [s.strip() for s in steps.split(",") if s.strip()]
        obj = make_text_scene(
            len(_text_objects),
            str(args.get("content", "text")),
            str(args.get("texture", "plain")),
            steps,
            float(args.get("position", 0.0)),
            float(args.get("duration", 3.0)),
        )
        _text_objects.append(obj)
        return {"ok": True, "name": name, "text": obj}

    if name == "text_vfx":
        text_id = int(args.get("text_id", -1))
        for t in _text_objects:
            if t["id"] == text_id:
                add_text_vfx(t, str(args.get("vfx", "none")), str(args.get("description", "")))
                return {"ok": True, "name": name, "text": t}
        raise HTTPException(status_code=404, detail="text not found")

    if name == "video_transition":
        index = int(args.get("index", 0))
        kind = str(args.get("kind", "cut"))
        try:
            clip = set_transition(_video_frames, index, kind)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "name": name, "clip": clip}

    if name == "text_style":
        text_id = int(args.get("text_id", -1))
        for t in _text_objects:
            if t["id"] == text_id:
                set_text_style(
                    t,
                    float(args.get("size", 48)),
                    str(args.get("color", "#ffffff")),
                    str(args.get("align", "center")),
                )
                return {"ok": True, "name": name, "text": t}
        raise HTTPException(status_code=404, detail="text not found")

    if name == "make_3d":
        obj = make_3d(
            len(_objects_3d),
            str(args.get("kind", "text")),
            str(args.get("content", "")),
            str(args.get("model_path", "")),
            float(args.get("position", 0.0)),
            float(args.get("duration", 2.0)),
        )
        _objects_3d.append(obj)
        return {"ok": True, "name": name, "object": obj}

    if name == "add_animation":
        target = str(args.get("target", "3d"))
        obj_id = int(args.get("id", -1))
        pool = _objects_3d if target == "3d" else _text_objects
        for o in pool:
            if o["id"] == obj_id:
                add_animation(
                    o,
                    str(args.get("name", "anim")),
                    float(args.get("start", 0.0)),
                    float(args.get("end", 1.0)),
                    str(args.get("format", "json")),
                )
                return {"ok": True, "name": name, "object": o}
        raise HTTPException(status_code=404, detail="object not found")

    if name == "export_anim":
        target = str(args.get("target", "3d"))
        obj_id = int(args.get("id", -1))
        fmt = str(args.get("format", "json"))
        pool = _objects_3d if target == "3d" else _text_objects
        for o in pool:
            if o["id"] == obj_id:
                result = export_animation(o, fmt)
                result["name"] = name
                return result
        raise HTTPException(status_code=404, detail="object not found")

    if name == "undo":
        if not _undo_stack:
            return {"ok": False, "name": name, "note": "nothing to undo"}
        entry = _undo_stack.pop()
        outcome = _restore_undo(entry)
        return {"ok": True, "name": name, "undone": entry, "restored": outcome}

    raise HTTPException(status_code=400, detail=f"unknown tool: {name}")


def _tool_summary(result: Dict[str, Any]) -> str:
    """Return a one-line summary of a tool result.

Args:
    result: Tool result dict."""
    if "clip" in result:
        return f"Created {result['clip']['name']} on track {result['clip']['track_id']}."
    if "bpm" in result:
        return f"BPM set to {result['bpm']}."
    if "error" in result:
        return f"Tool error: {result['error']}"
    return "Tool ran."


class LoadRequest(BaseModel):
    """Request body for loading a model."""
    model: str
    backend: str = "llama"
    modality: str = "llm"
    die: int = 0
    split: str = "single"


class GenerateRequest(BaseModel):
    """Request body for a generate call."""
    request: Any
    die: Optional[int] = None


class ChatMessage(BaseModel):
    """One chat message."""
    role: str
    content: str


class ChatRequest(BaseModel):
    """Request body for a chat completion."""
    messages: List[ChatMessage]
    die: Optional[int] = None
    max_tokens: int = 256
    temperature: float = 0.7


class AudioEditRequest(BaseModel):
    """Request body for an audio clip edit."""
    clip_id: int
    action: str
    start: Optional[float] = None
    end: Optional[float] = None
    gain: Optional[float] = None
    position: Optional[float] = None


class TrackUpdate(BaseModel):
    """Partial update for an audio track."""
    name: Optional[str] = None
    channel: Optional[str] = None
    gain: Optional[float] = None
    mute: Optional[bool] = None
    solo: Optional[bool] = None
    armed: Optional[bool] = None
    asio_index: Optional[int] = None
    device_label: Optional[str] = None
    sample_rate: Optional[int] = None
    type: Optional[str] = None  # "audio" or "instrument"; "instrument" shows the sequencer
    pan: Optional[float] = None  # -1 (left) .. 0 (centre) .. 1 (right); applied in mix and bounce


class AudioSettingsRequest(BaseModel):
    """AudioSettingsRequest."""
    sample_rate: Optional[int] = None
    asio: Optional[bool] = None
    buffer: Optional[int] = None


class AsioStartRequest(BaseModel):
    """AsioStartRequest."""
    track_id: int


class BpmRequest(BaseModel):
    """BpmRequest."""
    bpm: float


class PatternRequest(BaseModel):
    """PatternRequest."""
    pattern: Dict[str, List[int]]


class InstrumentRequest(BaseModel):
    """InstrumentRequest."""
    instrument: str
    note: int = 60
    duration: float = 0.4
    track_id: Optional[int] = None


class LoopRequest(BaseModel):
    """LoopRequest."""
    style: str = "basic"
    bars: int = 1
    track_id: Optional[int] = None


class ToolRequest(BaseModel):
    """ToolRequest."""
    name: str
    args: Dict[str, Any] = {}


class BounceRequest(BaseModel):
    """BounceRequest."""
    name: str = "mix.wav"


class VstRequest(BaseModel):
    """VstRequest."""
    name: str
    plugin_type: str = "effect"
    effect: str = "custom"
    channels: int = 2
    params: Dict[str, Any] = {}
    prompt: str = ""


class MasterRequest(BaseModel):
    """MasterRequest."""
    gain: Optional[float] = None
    mute: Optional[bool] = None
    compressor: Optional[Dict[str, Any]] = None


class EffectRequest(BaseModel):
    """EffectRequest."""
    clip_id: int
    kind: str
    params: Dict[str, Any] = {}


class ClipMuteRequest(BaseModel):
    """ClipMuteRequest."""
    clip_id: int
    mute: bool


class VideoEditRequest(BaseModel):
    """VideoEditRequest."""
    action: str
    frame_id: Optional[int] = None
    prompt: Optional[str] = None
    duration: Optional[float] = None
    path: Optional[str] = None
    vfx: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    new_order: Optional[List[int]] = None
    name: Optional[str] = None


@app.get("/api/formats")
def list_formats() -> Dict[str, Any]:
    """list formats."""
    return format_catalog()


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    """Return die status. Works without a K80 installed."""
    try:
        return get_ic().status()
    except Exception:
        return {"dies": [], "note": "no accelerator detected", "ready": False}


@app.get("/api/advertise")
def get_advertise() -> Dict[str, Any]:
    """get advertise."""
    return get_ic().advertise()


@app.get("/api/fusion")
def fusion_status() -> Dict[str, Any]:
    """fusion status."""
    return get_fusion().status()


@app.post("/api/fusion/activate")
def fusion_activate(strategy: str = "pipeline") -> Dict[str, Any]:
    """fusion activate."""
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
    """fusion deactivate."""
    get_fusion().deactivate()
    return {"ok": "deactivated"}


@app.post("/api/load")
def load_model(body: LoadRequest) -> Dict[str, str]:
    """load model."""
    try:
        get_ic().load(body.model, backend=body.backend, modality=body.modality, die=body.die, split=body.split)
    except (InterconnectorError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "loaded"}


@app.post("/api/unload")
def unload_model(die: int) -> Dict[str, str]:
    """unload model."""
    try:
        get_ic().unload(die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": "unloaded"}


@app.post("/api/generate")
def generate(body: GenerateRequest) -> Dict[str, Any]:
    """generate."""
    try:
        result = get_ic().generate(body.request, die=body.die)
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not isinstance(result, (str, dict, list, int, float, bool, type(None))):
        result = str(result)
    return {"result": result}


@app.post("/api/chat")
def chat(body: ChatRequest) -> Dict[str, Any]:
    """chat."""
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    _chat.clear()
    _chat.extend(messages)

    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    intent = parse_intent(last_user)
    tool_result: Optional[Dict[str, Any]] = None

    if intent and not parse_tool_call(last_user):
        tool_result = _dispatch_tool(intent["name"], intent.get("args", {}))
        text = _tool_summary(tool_result)
        _chat.append({"role": "assistant", "content": text})
        return {"result": text, "history": _chat, "tool": tool_result}

    ic = get_ic()
    die = body.die
    if die is None:
        loaded = ic.loaded_dies()
        die = loaded[0] if loaded else None
    modality = ic.modality_of(die) if die is not None else None

    if modality == "agent":
        result = ic.generate(
            {
                "goal": last_user,
                "tools": list_tools(),
                "tool_prompt": tool_prompt(),
                "tool_runner": _dispatch_tool,
            },
            die=die,
        )
        text = result.get("result", "") if isinstance(result, dict) else str(result)
        tools_used = [
            s.get("tool") for s in (result.get("steps") or []) if isinstance(result, dict) and s.get("tool")
        ]
        _chat.append({"role": "assistant", "content": text})
        return {
            "result": text,
            "history": _chat,
            "steps": result.get("steps") if isinstance(result, dict) else [],
            "tools": tools_used,
        }

    try:
        result = ic.generate(
            {"messages": messages, "max_tokens": body.max_tokens, "temperature": body.temperature},
            die=die,
        )
    except InterconnectorError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    text = result if isinstance(result, str) else str(result)

    call = parse_tool_call(text)
    if call:
        try:
            tool_result = _dispatch_tool(call["name"], call.get("args", {}))
        except HTTPException as e:
            # A 501 (e.g. a make_vst prompt) is the tool's answer, not a failed chat turn.
            if e.status_code != 501:
                raise
            tool_result = {"name": call["name"], "error": e.detail}
        text = f"{text}\n\n{_tool_summary(tool_result)}"

    _chat.append({"role": "assistant", "content": text})
    return {"result": text, "history": _chat, "tool": tool_result}


@app.get("/api/chat/history")
def chat_history() -> Dict[str, Any]:
    """chat history."""
    return {"history": _chat}


@app.post("/api/chat/clear")
def chat_clear() -> Dict[str, str]:
    """chat clear."""
    _chat.clear()
    return {"ok": "cleared"}



SETTINGS_PATH = Path(__file__).resolve().parents[2] / "uploads" / "settings.json"


def _load_settings() -> None:
    """Load saved settings from disk if present."""
    global _sample_rate, _asio_enabled, _asio_buffer, _bpm
    if not SETTINGS_PATH.exists():
        return
    try:
        data = _json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return
    if data.get("sample_rate") in COMMON_RATES:
        _sample_rate = data["sample_rate"]
    if "asio" in data:
        _asio_enabled = bool(data["asio"])
    if data.get("buffer") in ASIO_BUFFERS:
        _asio_buffer = data["buffer"]
    if data.get("bpm"):
        _bpm = float(data["bpm"])


def _save_settings() -> None:
    """Write the current settings to disk."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(_json.dumps({
        "sample_rate": _sample_rate,
        "asio": _asio_enabled,
        "buffer": _asio_buffer,
        "bpm": _bpm,
    }))


_load_settings()


@app.get("/api/audio/settings")
def audio_settings() -> Dict[str, Any]:
    """audio settings."""
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
        "master": _master,
    }


@app.post("/api/audio/settings")
def set_audio_settings(body: AudioSettingsRequest) -> Dict[str, Any]:
    """set audio settings."""
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
    _save_settings()
    return {
        "sample_rate": _sample_rate,
        "asio": _asio_enabled,
        "buffer": _asio_buffer,
        "asio_profile": asio_profile(_sample_rate, _asio_buffer),
        "asio_probe": probe_asio(),
        "bpm": _bpm,
        "master": _master,
    }


@app.get("/api/audio/master")
def get_master() -> Dict[str, Any]:
    """get master."""
    return _master


@app.post("/api/audio/master")
def set_master(body: MasterRequest) -> Dict[str, Any]:
    """set master."""
    if body.gain is not None:
        _master["gain"] = max(0.0, body.gain)
    if body.mute is not None:
        _master["mute"] = body.mute
    if body.compressor is not None:
        comp = _master.setdefault("compressor", {})
        comp.update(body.compressor)
    return _master


@app.get("/api/audio/asio/devices")
def asio_devices() -> Dict[str, Any]:
    """asio devices."""
    return {"devices": list_asio_devices(), "probe": probe_asio()}


@app.get("/api/audio/asio/levels")
def asio_levels() -> Dict[str, Any]:
    """asio levels."""
    return _asio_recorder.levels()


@app.post("/api/audio/asio/start")
def asio_start(body: AsioStartRequest) -> Dict[str, Any]:
    """asio start."""
    global _asio_track_id
    if not _asio_enabled:
        raise HTTPException(status_code=400, detail="ASIO is not enabled")
    track = _get_track(body.track_id)
    if not track.get("armed"):
        raise HTTPException(status_code=400, detail="track is not armed")
    if _asio_recorder.recording:
        raise HTTPException(status_code=400, detail="already recording")

    rate = track.get("sample_rate") or _sample_rate
    _validate_rate_for_track(track, rate)
    channels = 2 if track.get("channel") == "stereo" else 1
    # Each take gets its own file (asio_track<ID>.wav, then _1, _2, ...);
    # the recorder's wave.open(path, "wb") would truncate a shared one.
    path = reserve_unique(_audio_mod.UPLOAD_DIR, f"asio_track{track['id']}.wav")
    try:
        info = _asio_recorder.start(
            path,
            sample_rate=rate,
            buffer=_asio_buffer,
            channels=channels,
            device_index=track.get("asio_index"),
        )
    except BaseException as e:
        # This call created the file; drop it if the take never started.
        try:
            path.unlink()
        except OSError:
            pass
        if isinstance(e, RuntimeError):
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise
    _asio_track_id = track["id"]
    return info


@app.post("/api/audio/asio/stop")
def asio_stop() -> Dict[str, Any]:
    """asio stop."""
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
        _clip_ids.next_id(),
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


@app.post("/api/audio/mix")
def mix_audio() -> Dict[str, Any]:
    """mix audio. 400 naming each clip that cannot be mixed (nothing is written)."""
    try:
        path = mix_arrangement(_audio_clips, _audio_tracks, _sample_rate, "mix.wav", _master)
    except UnmixableClipError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    clip = make_clip(_clip_ids.next_id(), path.name, path, track_id=None, sample_rate=_sample_rate)
    clip["mix"] = True
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/bounce")
def bounce_audio(body: BounceRequest) -> Dict[str, Any]:
    """bounce audio. 400 naming each clip that cannot be mixed (nothing is written)."""
    name = safe_filename(body.name, "mix.wav")
    if not name.endswith(".wav"):
        name += ".wav"
    try:
        path = mix_arrangement(_audio_clips, _audio_tracks, _sample_rate, name, _master)
    except UnmixableClipError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    clip = make_clip(_clip_ids.next_id(), path.name, path, track_id=None, sample_rate=_sample_rate)
    clip["mix"] = True
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/vst")
def create_vst(body: VstRequest) -> Dict[str, Any]:
    """Generate a VST3 source file for the mini DAW."""
    if body.plugin_type not in PLUGIN_TYPES:
        raise HTTPException(status_code=400, detail=f"plugin_type must be one of {PLUGIN_TYPES}")
    prompt = body.prompt or ""
    effect = body.effect
    if effect not in EFFECT_PRESETS:
        effect = "custom"
    try:
        result = make_vst(body.name, body.plugin_type, effect, body.channels, body.params, prompt=prompt)
    except PromptDesignUnavailable as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result


@app.get("/api/vst/library")
def vst_library() -> Dict[str, Any]:
    """Return every VST the maker has generated this session."""
    return {"plugins": list_library()}


@app.get("/api/vst/presets")
def vst_presets() -> Dict[str, Any]:
    """vst presets."""
    return list_presets()


@app.get("/api/vst/sdk")
def vst_sdk_status() -> Dict[str, Any]:
    """vst sdk status."""
    path = sdk_path()
    return {"installed": path is not None, "path": str(path) if path else None}


@app.post("/api/vst/press")
def vst_press(source: str, name: str = "Plugin") -> Dict[str, Any]:
    """vst press."""
    return press_vst(Path(source), name)


@app.get("/api/vst/ui")
def get_vst_ui() -> Dict[str, Any]:
    """get vst ui."""
    return _vst_project


@app.post("/api/vst/ui/reset")
def reset_vst_ui(name: str = "MyPlugin") -> Dict[str, Any]:
    """reset vst ui."""
    global _vst_project
    _vst_project = default_project(name)
    return _vst_project


@app.post("/api/vst/ui/param")
def vst_add_param(name: str, default: float = 0.5) -> Dict[str, Any]:
    """vst add param."""
    try:
        return add_parameter(_vst_project, name, default)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/vst/ui/object")
def vst_add_object_endpoint(
    kind: str,
    x: float = 20,
    y: float = 20,
    w: float = 60,
    h: float = 60,
    label: str = "",
    bind: Optional[str] = None,
) -> Dict[str, Any]:
    """vst add object endpoint."""
    if kind not in OBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"kind must be one of {OBJECT_TYPES}")
    return add_object(_vst_project, kind, x, y, w, h, label, bind)


@app.post("/api/vst/ui/bind")
def vst_bind_endpoint(object_id: int, param: str) -> Dict[str, Any]:
    """vst bind endpoint."""
    try:
        return bind_object(_vst_project, object_id, param)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/vst/ui/export")
def vst_export_endpoint() -> Dict[str, Any]:
    """vst export endpoint."""
    return export_project(_vst_project)


@app.get("/api/music/state")
def music_state() -> Dict[str, Any]:
    """music state."""
    return {
        "bpm": _bpm,
        "pattern": _pattern,
        "instruments": list(INSTRUMENTS),
        "sample_rate": _sample_rate,
        "tools": list_tools(),
    }


@app.get("/api/music/tools")
def music_tools() -> Dict[str, Any]:
    """music tools."""
    return {"tools": list_tools()}


@app.post("/api/music/tool")
def music_tool(body: ToolRequest) -> Dict[str, Any]:
    """music tool."""
    return _dispatch_tool(body.name, body.args)


@app.post("/api/music/bpm")
def set_bpm(body: BpmRequest) -> Dict[str, Any]:
    """set bpm."""
    return _dispatch_tool("set_bpm", {"bpm": body.bpm})


@app.post("/api/music/bpm/detect")
def detect_bpm_from_clip(clip_id: int) -> Dict[str, Any]:
    """detect bpm from clip."""
    return _dispatch_tool("detect_bpm", {"clip_id": clip_id})


@app.get("/api/music/pattern")
def get_pattern() -> Dict[str, Any]:
    """get pattern."""
    return {"pattern": _pattern, "bpm": _bpm}


@app.post("/api/music/pattern")
def set_pattern(body: PatternRequest) -> Dict[str, Any]:
    """set pattern."""
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
    """generate instrument."""
    result = _dispatch_tool(
        "generate_instrument",
        {
            "instrument": body.instrument,
            "note": body.note,
            "duration": body.duration,
            "track_id": body.track_id,
        },
    )
    return result.get("clip", result)


@app.post("/api/music/loop")
def generate_loop_clip(body: LoopRequest) -> Dict[str, Any]:
    """generate loop clip."""
    result = _dispatch_tool(
        "generate_loop",
        {"style": body.style, "bars": body.bars, "track_id": body.track_id},
    )
    return result.get("clip", result)


@app.post("/api/music/render")
def render_current_pattern(track_id: Optional[int] = None, bars: int = 1) -> Dict[str, Any]:
    """render current pattern."""
    result = _dispatch_tool("render_pattern", {"track_id": track_id, "bars": bars})
    return result.get("clip", result)


@app.get("/api/audio/tracks")
def list_tracks() -> Dict[str, Any]:
    """list tracks."""
    return {"tracks": _audio_tracks}


@app.post("/api/audio/tracks")
def create_track(name: str = "Track", channel: str = "stereo", type: str = DEFAULT_TRACK_TYPE) -> Dict[str, Any]:
    """Create a track with a fresh id. type is "audio" or "instrument"."""
    try:
        track_type = check_track_type(type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    track = make_track(_track_ids.next_id(), name, channel, _sample_rate, track_type)
    _audio_tracks.append(track)
    return track


@app.delete("/api/audio/tracks/{track_id}")
def delete_track(track_id: int) -> Dict[str, Any]:
    """Delete a track and its clips. Other ids are unchanged."""
    if not remove_track(_audio_tracks, _audio_clips, track_id):
        raise HTTPException(status_code=404, detail="track not found")
    return {"tracks": _audio_tracks}


@app.post("/api/audio/tracks/{track_id}")
def update_track(track_id: int, body: TrackUpdate) -> Dict[str, Any]:
    """update track."""
    track = _get_track(track_id)
    data = body.model_dump(exclude_none=True)
    if "type" in data:
        try:
            check_track_type(data["type"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if "channel" in data and data["channel"] not in ("stereo", "left", "right"):
        raise HTTPException(status_code=400, detail="channel must be stereo, left, or right")
    if "pan" in data and not (math.isfinite(data["pan"]) and -1.0 <= data["pan"] <= 1.0):
        raise HTTPException(status_code=400, detail="pan must be between -1 and 1")
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
    """list clips."""
    return {"clips": _audio_clips}


@app.post("/api/audio/clips")
def add_clip(
    name: str,
    duration: float = 0.0,
    path: str = "",
    track_id: Optional[int] = None,
    position: float = 0.0,
) -> Dict[str, Any]:
    """add clip. A supplied track_id must name an existing track (404 otherwise)."""
    track_id = _track_for_new_clip(track_id)
    clip = make_clip(
        _clip_ids.next_id(),
        name,
        Path(path) if path else None,
        duration,
        track_id,
        _sample_rate,
        position,
    )
    _audio_clips.append(clip)
    return clip


@app.post("/api/audio/upload")
async def upload_audio(
    file: UploadFile = File(...),
    track_id: Optional[int] = Form(None),
) -> Dict[str, Any]:
    """upload audio. A supplied track_id must name an existing track (404 otherwise)."""
    track_id = _track_for_new_clip(track_id)
    data = await file.read()
    dest = save_upload(file.filename or "clip.wav", data)
    clip = make_clip(_clip_ids.next_id(), dest.name, dest, track_id=track_id, sample_rate=_sample_rate)
    _audio_clips.append(clip)
    return clip


@app.get("/api/audio/file/{clip_id}")
def audio_file(clip_id: int):
    """audio file."""
    path = _get_clip(clip_id).get("path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path, headers={"Cache-Control": "no-store"})



class ClipGainRequest(BaseModel):
    clip_id: int
    gain: float


@app.post("/api/audio/clips/gain")
def clip_gain(body: ClipGainRequest) -> Dict[str, Any]:
    """Set a clip's playback gain. Does not rewrite the source file."""
    clip = _get_clip(body.clip_id)
    clip["gain"] = max(0.0, min(4.0, body.gain))
    return clip



class ClipFlagRequest(BaseModel):
    clip_id: int


@app.post("/api/audio/clips/reverse")
def clip_reverse(body: ClipFlagRequest) -> Dict[str, Any]:
    """Toggle a clip's reversed flag. Does not rewrite the source file."""
    clip = _get_clip(body.clip_id)
    clip["reversed"] = not clip.get("reversed", False)
    return clip



@app.post("/api/audio/clips/silence")
def clip_silence(body: ClipFlagRequest) -> Dict[str, Any]:
    """Toggle a clip's silenced flag. Does not rewrite the source file."""
    clip = _get_clip(body.clip_id)
    clip["silenced"] = not clip.get("silenced", False)
    return clip


class ClipTrimRequest(BaseModel):
    clip_id: int
    trim_in: float = 0.0
    trim_out: float = 0.0


@app.post("/api/audio/clips/trim")
def clip_trim(body: ClipTrimRequest) -> Dict[str, Any]:
    """Set a clip's play window. Does not rewrite the source file."""
    clip = _get_clip(body.clip_id)
    clip["trim_in"] = max(0.0, body.trim_in)
    clip["trim_out"] = max(clip["trim_in"], body.trim_out or clip.get("duration", 0))
    return clip


class ClipSplitRequest(BaseModel):
    clip_id: int
    at: float


@app.post("/api/audio/clips/split")
def clip_split(body: ClipSplitRequest) -> Dict[str, Any]:
    """Split a clip at a timeline time into two clips sharing the source.

The clip plays the source window [trim_in, trim_out) at its position (see
audio._clip_window). The cut lands `into` seconds into that window, so the
two halves together play exactly what the clip played. An unset trim_out
means the window ends at trim_in + duration. A reversed clip plays its
window backwards, so its timeline-left half takes the end of the window."""
    clip = _get_clip(body.clip_id)
    start = float(clip.get("position", 0.0))
    trim_in = max(0.0, float(clip.get("trim_in") or 0.0))
    trim_out = float(clip.get("trim_out") or 0.0)
    if trim_out <= 0:
        trim_out = trim_in + float(clip.get("duration", 0.0))
    length = trim_out - trim_in
    into = body.at - start
    if length <= 0 or into <= 0 or into >= length:
        return {"clips": _audio_clips}
    cut = trim_out - into if clip.get("reversed") else trim_in + into
    right = dict(clip)
    right["id"] = _clip_ids.next_id()
    right["position"] = start + into
    right["duration"] = length - into
    clip["duration"] = into
    if clip.get("reversed"):
        clip["trim_in"], clip["trim_out"] = cut, trim_out
        right["trim_in"], right["trim_out"] = trim_in, cut
    else:
        clip["trim_in"], clip["trim_out"] = trim_in, cut
        right["trim_in"], right["trim_out"] = cut, trim_out
    _audio_clips.append(right)
    return {"clips": _audio_clips}


@app.post("/api/audio/clips/mute")
def clip_mute(body: ClipMuteRequest) -> Dict[str, Any]:
    """clip mute."""
    clip = _get_clip(body.clip_id)
    clip["mute"] = body.mute
    return clip


@app.post("/api/audio/clips/effect")
def clip_effect(body: EffectRequest) -> Dict[str, Any]:
    """clip effect."""
    clip = _get_clip(body.clip_id)
    path = clip.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=400, detail="clip has no file")
    if body.kind not in ("normalize", "compress", "morph", "delay", "eq", "reverb"):
        raise HTTPException(status_code=400, detail="unknown effect")
    _push_undo("effect", dict(clip))
    try:
        new_path = apply_effect(Path(path), body.kind, body.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    effects = clip.setdefault("effects", {})
    slot = effects.setdefault(body.kind, {})
    slot["enabled"] = True
    slot.update(body.params)
    _refresh_clip(clip, new_path)
    return clip


@app.post("/api/audio/edit")
def edit_audio(body: AudioEditRequest) -> Dict[str, Any]:
    """edit audio."""
    clip = _get_clip(body.clip_id)
    path = clip.get("path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=400, detail="clip has no file")

    if body.action == "position":
        _push_undo("position", dict(clip))
        clip["position"] = max(0.0, body.position or 0.0)
        return clip

    _push_undo(body.action, dict(clip))
    try:
        if body.action == "trim":
            new_path = process_clip(Path(path), "trim", start=body.start or 0.0, end=body.end)
        elif body.action == "gain":
            new_path = process_clip(Path(path), "gain", gain=body.gain if body.gain is not None else 1.0)
        elif body.action == "reverse":
            new_path = process_clip(Path(path), "reverse")
        elif body.action == "silence":
            new_path = process_clip(Path(path), "silence")
        elif body.action == "mute":
            clip["mute"] = not clip.get("mute", False)
            return clip
        else:
            raise HTTPException(status_code=400, detail="unknown action")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # trim writes only the window and reverse writes the file reversed, so the
    # old trim offsets no longer point at the same audio. The reversed flag is
    # left as it was: the file already holds the reversal.
    baked = ("trim_in", "trim_out") if body.action in ("trim", "reverse") else ()
    _refresh_clip(clip, new_path, reset=baked)
    return clip


@app.get("/api/video/tracks")
def list_video_tracks() -> Dict[str, Any]:
    """list video tracks."""
    return {"video": _video_tracks, "audio": _video_audio_tracks}


@app.post("/api/video/split")
def split_video_audio(path: str) -> Dict[str, Any]:
    """Split the audio track from a video file."""
    try:
        return split_audio(Path(path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/vfx/render")
def render_vfx_endpoint(name: str = "effect", duration: float = 2.0, prompt: str = "") -> Dict[str, Any]:
    """Render a VFX from a name or free-form prompt."""
    try:
        path = render_vfx(name, duration, prompt=prompt or name)
        return {"path": str(path), "name": name, "prompt": prompt or name, "rendered": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/video/frames")
def list_frames() -> Dict[str, Any]:
    """list frames."""
    return {
        "frames": _video_frames,
        "texts": _text_objects,
        "objects_3d": _objects_3d,
        "builtin_vfx": list(BUILTIN_VFX),
        "anim_formats": list(ANIM_FORMATS),
    }


@app.post("/api/video/text")
def add_text_endpoint(
    content: str,
    texture: str = "plain",
    position: float = 0.0,
    duration: float = 2.0,
) -> Dict[str, Any]:
    """add text endpoint."""
    obj = make_text(len(_text_objects), content, position, duration, texture)
    _text_objects.append(obj)
    return obj


@app.post("/api/video/upload")
async def upload_video(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    duration: float = Form(1.0),
    vfx: str = Form("none"),
) -> Dict[str, Any]:
    """Upload an MP4 (or related) and add it as a timeline clip."""
    data = await file.read()
    dest = save_video(file.filename or "clip.mp4", data)
    if not is_supported_video(dest):
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="only mp4, mov, webm are supported")
    clip = make_video_clip(len(_video_frames), prompt, duration, str(dest), vfx)
    _video_frames.append(clip)
    return clip


@app.post("/api/video/export")
def export_timeline(name: str = "timeline") -> Dict[str, Any]:
    """Export the movie timeline as a JSON manifest."""
    if not _video_frames:
        raise HTTPException(status_code=400, detail="no frames to export")
    return export_full_timeline(_video_frames, _text_objects, _objects_3d, name)


@app.post("/api/video/edit")
def edit_video(body: VideoEditRequest) -> Dict[str, Any]:
    """edit video."""
    if body.action == "add_frame":
        clip = make_video_clip(
            len(_video_frames),
            body.prompt or "",
            body.duration or 1.0,
            body.path,
            body.vfx or "none",
        )
        _video_frames.append(clip)
        return {"frames": _video_frames}
    if body.action == "delete_frame" and body.frame_id is not None:
        _video_frames[:] = [f for f in _video_frames if f["id"] != body.frame_id]
        return {"frames": _video_frames}
    if body.action == "reorder" and body.new_order:
        _video_frames[:] = reorder(_video_frames, body.new_order)
        return {"frames": _video_frames}
    if body.action == "set_duration" and body.frame_id is not None and body.duration is not None:
        for f in _video_frames:
            if f["id"] == body.frame_id:
                f["duration"] = max(0.1, body.duration)
                break
        return {"frames": _video_frames}
    if body.action == "set_vfx" and body.frame_id is not None and body.vfx:
        for f in _video_frames:
            if f["id"] == body.frame_id:
                apply_vfx(f, body.vfx, body.params, body.prompt or "")
                break
        return {"frames": _video_frames}
    raise HTTPException(status_code=400, detail="unknown video action")


@app.get("/api/health")
def health() -> Dict[str, str]:
    """health."""
    return {"status": "ok"}
