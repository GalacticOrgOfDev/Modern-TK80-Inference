"""Hybrid cluster hooks.

K80 nodes advertise themselves so they can sit cleanly beside newer GPUs.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, List

from .devices import K80Die


def advertise(
    dies: List[K80Die],
    models_loaded: List[int],
    node_name: str = "",
) -> Dict[str, Any]:
    """Return an advertisement payload for hybrid cluster discovery."""
    if not node_name:
        node_name = socket.gethostname()

    return {
        "node": node_name,
        "type": "k80",
        "arch": "kepler",
        "compute_capability": "3.7",
        "baseline": "R470 + CUDA 11.8",
        "dies": [
            {
                "index": d.index,
                "name": d.name,
                "total_mb": d.total_memory_mb,
                "free_mb": d.free_memory_mb,
                "busy": d.busy,
                "model_loaded": d.index in models_loaded,
            }
            for d in dies
        ],
        "capabilities": {
            "backends": ["llama", "pytorch"],
            "split_modes": ["single", "dual", "layer"],
            "fp32": True,
            "tensor_cores": False,
            "unified_memory": False,
        },
        "ready": any(not d.busy for d in dies),
    }
