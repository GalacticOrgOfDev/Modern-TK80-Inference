"""Music tools the model (or chat) can call.

Each tool takes a dict of arguments and returns a dict the studio
can turn into a clip or a state change. The dispatcher is the single
entry point so chat and the agent modality share one path.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from .music import INSTRUMENTS

ToolFn = Callable[[Dict[str, Any]], Dict[str, Any]]

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
}


def list_tools() -> List[Dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "args": spec["args"]}
        for name, spec in TOOLS.items()
    ]


def parse_intent(text: str) -> Dict[str, Any] | None:
    """Very small intent parser so chat can trigger a tool without a model."""
    if not text:
        return None
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

    return None
