"""VST interface builder for the Modern-TK80 mini DAW.

Stores a VST project: named plugin, list of parameters, and a canvas of
UI objects (knobs, vertical/horizontal sliders, buttons, labels) that
users or models can place and bind to parameters.

Export produces the VST source plus a simple layout description the
generated processor can read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .vst import make_vst
from .vst_press import press_vst

UI_DIR = Path(os.environ.get("TK80_VST_UI", "uploads/vst_ui"))
UI_DIR.mkdir(parents=True, exist_ok=True)

OBJECT_TYPES = ("knob", "vslider", "hslider", "button", "label", "meter", "xy")


def list_presets() -> Dict[str, Any]:
    """Return the full preset and category catalog for the UI and models."""
    from .vst import EFFECT_CATEGORIES, EFFECT_PRESETS, PLUGIN_TYPES
    return {
        "types": list(PLUGIN_TYPES),
        "presets": list(EFFECT_PRESETS),
        "categories": {k: list(v) for k, v in EFFECT_CATEGORIES.items()},
        "objects": list(OBJECT_TYPES),
    }


def default_project(name: str = "MyPlugin") -> Dict[str, Any]:
    """future docstring"""
    return {
        "name": name,
        "effect": "custom",
        "plugin_type": "effect",
        "parameters": [],
        "objects": [],
        "next_id": 1,
    }


def add_parameter(project: Dict[str, Any], name: str, default: float = 0.5) -> Dict[str, Any]:
    """Add a parameter the UI can bind to. Rejects duplicate names."""
    name = name.strip() or "param"
    if any(p["name"] == name for p in project["parameters"]):
        raise ValueError(f"parameter '{name}' already exists")
    pid = project["next_id"]
    project["next_id"] = pid + 1
    param = {"id": pid, "name": name, "default": float(default)}
    project["parameters"].append(param)
    return param


def add_object(
    project: Dict[str, Any],
    kind: str,
    x: float = 20.0,
    y: float = 20.0,
    w: float = 60.0,
    h: float = 60.0,
    label: str = "",
    bind: Optional[str] = None,
) -> Dict[str, Any]:
    """Place a UI object on the canvas and optionally bind it to a parameter."""
    if kind not in OBJECT_TYPES:
        raise ValueError(f"kind must be one of {OBJECT_TYPES}")
    oid = project["next_id"]
    project["next_id"] = oid + 1
    obj = {
        "id": oid,
        "kind": kind,
        "x": float(x),
        "y": float(y),
        "w": float(w),
        "h": float(h),
        "label": label or kind,
        "bind": bind,
    }
    project["objects"].append(obj)
    return obj


def bind_object(project: Dict[str, Any], object_id: int, param_name: str) -> Dict[str, Any]:
    """Tie an existing object to a parameter by name."""
    obj = next((o for o in project["objects"] if o["id"] == object_id), None)
    if obj is None:
        raise ValueError("object not found")
    if not any(p["name"] == param_name for p in project["parameters"]):
        raise ValueError("parameter not found")
    obj["bind"] = param_name
    return obj


def export_project(project: Dict[str, Any]) -> Dict[str, Any]:
    """Generate the VST source and a layout file from the current project."""
    params = {p["name"]: p["default"] for p in project["parameters"]}
    result = make_vst(
        project["name"],
        project.get("plugin_type", "effect"),
        project.get("effect", "custom"),
        params=params,
    )
    layout = {
        "name": project["name"],
        "effect": project.get("effect"),
        "parameters": project["parameters"],
        "objects": project["objects"],
    }
    layout_path = UI_DIR / f"{project['name']}_layout.json"
    layout_path.write_text(json.dumps(layout, indent=2), encoding="utf-8")
    result["layout"] = str(layout_path)
    result["object_count"] = len(project["objects"])
    result["parameter_count"] = len(project["parameters"])
    result["press"] = press_vst(Path(result["path"]), project["name"])
    return result
