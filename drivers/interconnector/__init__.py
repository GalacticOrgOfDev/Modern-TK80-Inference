"""K80 Custom Interconnector.

Remastering layer that presents a modern interface to the Tesla K80
while running on the last supported R470 driver + CUDA 11.8 baseline.
"""

from .core import Interconnector, InterconnectorError
from .devices import K80Die, discover_dies
from .translate import translate_request, messages_to_prompt
from .cluster import advertise
from .monitor import read_die_metrics, PerfTimer

__all__ = [
    "Interconnector",
    "InterconnectorError",
    "K80Die",
    "discover_dies",
    "translate_request",
    "messages_to_prompt",
    "advertise",
    "read_die_metrics",
    "PerfTimer",
]
