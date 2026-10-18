"""Explicit dual-die split support.

K80 dies are independent. Supported modes:
- none: whole model on one die (default, safest)
- layer: attempt layer split across two dies (llama.cpp only, best-effort)
- dual: same model loaded independently on both dies (for parallel requests)
"""

from __future__ import annotations

from typing import Any, Dict, List


def plan_split(
    mode: str,
    available_dies: List[int],
    backend: str,
) -> Dict[str, Any]:
    """Return a placement plan for the requested split mode."""
    if mode == "none" or mode == "single":
        if not available_dies:
            raise ValueError("No free dies for single placement")
        return {"mode": "single", "dies": [available_dies[0]], "backend": backend}

    if mode == "dual":
        if len(available_dies) < 2:
            raise ValueError("dual mode requires two free dies")
        return {"mode": "dual", "dies": available_dies[:2], "backend": backend}

    if mode == "layer":
        if backend != "llama":
            raise ValueError("layer split is only supported with the llama backend")
        if len(available_dies) < 2:
            raise ValueError("layer split requires two free dies")
        # Best-effort: llama.cpp can use tensor_split or multi-GPU if built with it.
        # On K80 we document it as experimental because dies are independent.
        return {
            "mode": "layer",
            "dies": available_dies[:2],
            "backend": backend,
            "note": "experimental on independent K80 dies",
        }

    raise ValueError(f"Unknown split mode: {mode}")
