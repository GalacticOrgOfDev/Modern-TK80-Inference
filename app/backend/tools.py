"""Music tools the model (or chat) can call.

Each tool takes a dict of arguments and returns a dict the studio
can turn into a clip or a state change. The dispatcher is the single
entry point so chat and the agent modality share one path.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .music import INSTRUMENTS

TOOLS: Dict[str, Dict[str, Any]] = {
    "set_bpm": {
        "description": "Set the studio BPM (40-220).",
        "args": {"bpm": "float"},
    },
    "generate_instrument": {
        "description": "Render an instrument hit or tone to a clip.",
        "args": {
            "instrument": "kick|snare|hat|bass|lead|pad",
            "note": "int MIDI",
            "duration": "float seconds",
        },
    },
    "generate_loop": {
        "description": "Generate a short loop at the current BPM.",
        "args": {"style": "basic|syncopated|pad", "bars": "int"},
    },
    "render_pattern": {
        "description": "Bounce the current step pattern to a clip.",
        "args": {"bars": "int"},
    },
    "detect_bpm": {
        "description": "Estimate BPM from a clip.",
        "args": {"clip_id": "int"},
    },
    "make_vst": {
        "description": "Generate a VST3 effect or instrument plugin source (reverb, subpump, autotune, noise_suppression, delay, distortion, custom).",
        "args": {
            "name": "string",
            "effect": "reverb|subpump|autotune|noise_suppression|delay|distortion|custom",
            "plugin_type": "effect|instrument",
        },
    },
    "vst_add_param": {
        "description": "Add a parameter to the current VST UI project.",
        "args": {"name": "string", "default": "float"},
    },
    "vst_add_object": {
        "description": "Place a UI object (knob, vslider, hslider, button, label) on the VST canvas.",
        "args": {"kind": "knob|vslider|hslider|button|label", "x": "float", "y": "float", "label": "string", "bind": "string"},
    },
    "vst_bind": {
        "description": "Bind an existing UI object to a parameter by name.",
        "args": {"object_id": "int", "param": "string"},
    },
    "vst_export": {
        "description": "Export the current VST UI project to VST3 source plus layout.",
        "args": {},
    },
    "vfx_add": {
        "description": "Add a clip to the movie timeline. vfx can be a built-in or any custom name (tv_static, fire_hand, lightning, etc.).",
        "args": {"prompt": "string", "duration": "float", "vfx": "string", "description": "string"},
    },
    "vfx_apply": {
        "description": "Apply a VFX effect to an existing timeline clip. Accepts any name.",
        "args": {"frame_id": "int", "vfx": "string", "description": "string"},
    },
    "vfx_make": {
        "description": "Create a custom VFX by name and write a starter stub (tv_static, fire_hand, lightning, etc.).",
        "args": {"name": "string", "description": "string"},
    },
    "text_add": {
        "description": "Create a text object on the timeline with optional texture and position.",
        "args": {"content": "string", "texture": "string", "position": "float", "duration": "float"},
    },
    "text_scene": {
        "description": "Create a text object and apply a sequence of VFX steps (e.g. fall, impact_rubble, lightning_wrap).",
        "args": {"content": "string", "texture": "string", "steps": "list of strings"},
    },
    "text_vfx": {
        "description": "Attach a VFX to an existing text object.",
        "args": {"text_id": "int", "vfx": "string", "description": "string"},
    },
    "video_transition": {
        "description": "Set the transition after a clip (cut, crossfade, wipe, dissolve).",
        "args": {"index": "int", "kind": "cut|crossfade|wipe|dissolve"},
    },
    "text_style": {
        "description": "Set size, color, and alignment on a text object.",
        "args": {"text_id": "int", "size": "float", "color": "string", "align": "left|center|right"},
    },
    "make_3d": {
        "description": "Create a 3D text or model object on the timeline.",
        "args": {"kind": "text|model", "content": "string", "model_path": "string"},
    },
    "add_animation": {
        "description": "Add an animation clip to a 3D or text object.",
        "args": {"target": "3d|text", "id": "int", "name": "string", "start": "float", "end": "float", "format": "json|gltf|fbx|bvh"},
    },
    "export_anim": {
        "description": "Export an animation file for a 3D or text object.",
        "args": {"target": "3d|text", "id": "int", "format": "json|gltf|fbx|bvh"},
    },
    "undo": {
        "description": "Undo the last audio edit.",
        "args": {},
    },
}

# Model emits: tool: name {"arg": value}
_CALL_RE = re.compile(
    r"tool\s*:\s*([a-z_]+)\s*(\{.*\})?",
    re.IGNORECASE | re.DOTALL,
)


def list_tools() -> List[Dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "args": spec["args"]}
        for name, spec in TOOLS.items()
    ]


def tool_prompt() -> str:
    """Short prompt the agent prepends so the model knows how to call."""
    lines = ["Available tools. Emit exactly one line: tool: <name> {json args}"]
    for name, spec in TOOLS.items():
        lines.append(f"- {name}: {spec['description']} args={spec['args']}")
    lines.append("When done, emit: Final: <answer>")
    return "\n".join(lines)


def parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Extract a tool call from model text. Returns {name, args} or None."""
    if not text:
        return None
    match = _CALL_RE.search(text)
    if not match:
        return None
    name = match.group(1).strip().lower()
    if name not in TOOLS:
        return None
    raw = match.group(2)
    args: Dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                args = parsed
        except Exception:
            args = {}
    return {"name": name, "args": args}


def parse_intent(text: str) -> Optional[Dict[str, Any]]:
    """Small intent parser so chat can trigger a tool without a model."""
    if not text:
        return None
    # Prefer an explicit model-style call if present.
    call = parse_tool_call(text)
    if call:
        return call

    t = text.lower().strip()

    if t.startswith("set bpm") or t.startswith("bpm "):
        digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in t)
        parts = [p for p in digits.split() if p]
        if parts:
            return {"name": "set_bpm", "args": {"bpm": float(parts[0])}}

    for name in INSTRUMENTS:
        if name in t and ("generate" in t or "make" in t or "play" in t or "add" in t):
            return {"name": "generate_instrument", "args": {"instrument": name}}

    if "loop" in t and ("generate" in t or "make" in t or "create" in t):
        style = "basic"
        if "sync" in t:
            style = "syncopated"
        elif "pad" in t:
            style = "pad"
        return {"name": "generate_loop", "args": {"style": style, "bars": 1}}

    if "render" in t and "pattern" in t:
        return {"name": "render_pattern", "args": {"bars": 1}}

    if "detect bpm" in t or "bpm detect" in t:
        return {"name": "detect_bpm", "args": {}}

    if any(word in t for word in ("vst", "plugin", "reverb", "subpump", "autotune", "noise")):
        effect = "custom"
        for e in ("reverb", "subpump", "autotune", "noise_suppression", "delay", "distortion"):
            if e.replace("_", " ") in t or e in t:
                effect = e
                break
        return {"name": "make_vst", "args": {"name": "GeneratedPlugin", "effect": effect, "plugin_type": "effect"}}

    if any(word in t for word in ("vfx", "fade", "zoom", "static", "lightning", "fire")):
        vfx = "none"
        for e in ("tv_static", "fire_hand", "lightning", "fade", "zoom", "pan", "color_grade", "overlay"):
            if e.replace("_", " ") in t or e in t:
                vfx = e
                break
        if "make" in t or "create" in t:
            return {"name": "vfx_make", "args": {"name": vfx, "description": text}}
        return {"name": "vfx_add", "args": {"prompt": text, "duration": 1.0, "vfx": vfx}}

    if "text" in t and ("stone" in t or "lightning" in t or "impact" in t or "generate" in t):
        texture = "stone" if "stone" in t else "plain"
        steps = []
        if "fall" in t:
            steps.append("fall")
        if "impact" in t or "rubble" in t:
            steps.append("impact_rubble")
        if "lightning" in t:
            steps.append("lightning_wrap")
        content = "paynmusic" if "paynmusic" in t else "text"
        return {"name": "text_scene", "args": {"content": content, "texture": texture, "steps": steps}}

    return None
