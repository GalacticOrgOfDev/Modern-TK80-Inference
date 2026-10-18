"""DieFusionCore — treat the two independent K80 dies as one logical device.

Status: foundation. The K80 dies have no unified memory. This module will
eventually own scheduling, data movement, and model placement so callers
can address a single fused device.

Current capabilities:
- Detect whether two dies are available for fusion
- Report fusion readiness and capacity
- Placeholder for future tensor / layer / pipeline fusion strategies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .devices import K80Die

log = logging.getLogger("tk80.interconnector.diefusion")


@dataclass
class FusionPlan:
    """Describes how work will be placed across dies."""

    strategy: str  # "none", "pipeline", "layer", "data"
    dies: List[int]
    capacity_mb: int
    ready: bool
    note: str = ""


class DieFusionCore:
    """Logical fusion of two independent K80 dies."""

    def __init__(self, dies: List[K80Die]):
        self.dies = dies
        self.active = False
        log.info("DieFusionCore initialized with %d die(s)", len(dies))

    def can_fuse(self) -> bool:
        """True if at least two free dies are available."""
        free = [d for d in self.dies if not d.busy]
        return len(free) >= 2

    def status(self) -> Dict[str, Any]:
        free = [d.index for d in self.dies if not d.busy]
        total = sum(d.total_memory_mb for d in self.dies)
        return {
            "active": self.active,
            "die_count": len(self.dies),
            "free_dies": free,
            "can_fuse": self.can_fuse(),
            "aggregate_mb": total,
            "unified_memory": False,
            "strategies": ["pipeline", "layer", "data"],
        }

    def plan(self, strategy: str = "pipeline") -> FusionPlan:
        """Build a fusion plan. Does not move data yet."""
        free = [d.index for d in self.dies if not d.busy]
        if len(free) < 2:
            return FusionPlan(
                strategy="none",
                dies=free,
                capacity_mb=sum(d.total_memory_mb for d in self.dies if d.index in free),
                ready=False,
                note="Need two free dies to fuse",
            )

        selected = free[:2]
        capacity = sum(d.total_memory_mb for d in self.dies if d.index in selected)
        note = {
            "pipeline": "Stage sequential work across dies",
            "layer": "Split model layers across dies (experimental on independent dies)",
            "data": "Split batch or sequence across dies",
        }.get(strategy, "Unknown strategy")

        return FusionPlan(
            strategy=strategy,
            dies=selected,
            capacity_mb=capacity,
            ready=True,
            note=note,
        )

    def activate(self, strategy: str = "pipeline") -> FusionPlan:
        """Mark fusion active and return the plan."""
        plan = self.plan(strategy)
        if not plan.ready:
            raise RuntimeError(plan.note)
        self.active = True
        log.info("DieFusionCore activated: %s on dies %s", strategy, plan.dies)
        return plan

    def deactivate(self) -> None:
        self.active = False
        log.info("DieFusionCore deactivated")
