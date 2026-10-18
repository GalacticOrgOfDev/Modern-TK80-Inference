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

    return None
