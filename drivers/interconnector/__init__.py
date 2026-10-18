"""K80 Custom Interconnector.

Remastering layer that presents a modern interface to the Tesla K80
while running on the last supported R470 driver + CUDA 11.8 baseline.
"""

from .core import Interconnector, InterconnectorError
from .devices import K80Die, discover_dies

__all__ = [
    "Interconnector",
    "InterconnectorError",
    "K80Die",
    "discover_dies",
]
