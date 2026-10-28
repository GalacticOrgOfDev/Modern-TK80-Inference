"""Stdlib-only helpers for DAW track and clip ids, lookups, and track types.

Kept free of FastAPI so the id rules can be unit-tested without the server.

Id rules:
    Track ids and clip ids come from separate IdCounter instances. A counter
    only moves forward, so an id is never handed out twice, even after the
    track or clip that held it is deleted. Ids are never list positions;
    every lookup goes through find_by_id.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

TRACK_TYPES = ("audio", "instrument")
DEFAULT_TRACK_TYPE = "audio"


class IdCounter:
    """Monotonic id source. next_id() never returns the same value twice."""

    def __init__(self, start: int = 0) -> None:
        self._next = max(0, int(start))

    @classmethod
    def after(cls, items: Iterable[Dict[str, Any]]) -> "IdCounter":
        """Counter that starts above the highest id already in items."""
        counter = cls()
        counter.observe(items)
        return counter

    def observe(self, items: Iterable[Dict[str, Any]]) -> None:
        """Move past every id in items. Never moves backwards."""
        for item in items:
            item_id = item.get("id")
            if isinstance(item_id, int) and item_id >= self._next:
                self._next = item_id + 1

    def peek(self) -> int:
        """The id the next call to next_id() will return."""
        return self._next

    def next_id(self) -> int:
        """Return a fresh id and advance."""
        value = self._next
        self._next += 1
        return value


def find_by_id(items: List[Dict[str, Any]], item_id: Any) -> Optional[Dict[str, Any]]:
    """Return the item whose "id" equals item_id, or None."""
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def remove_track(
    tracks: List[Dict[str, Any]],
    clips: List[Dict[str, Any]],
    track_id: int,
) -> bool:
    """Delete a track and its clips in place. Returns False if the id is unknown.

    The lists are edited in place so other references stay valid, and the
    surviving clips keep their ids.
    """
    if find_by_id(tracks, track_id) is None:
        return False
    tracks[:] = [t for t in tracks if t.get("id") != track_id]
    clips[:] = [c for c in clips if c.get("track_id") != track_id]
    return True


def restore_clip_snapshot(
    clips: List[Dict[str, Any]],
    tracks: List[Dict[str, Any]],
    snapshot: Dict[str, Any],
) -> str:
    """Put an undo snapshot of a clip back. Returns "replaced", "appended" or "dropped".

    A snapshot whose clip belonged to a track that no longer exists is
    dropped, so undo cannot bring back a clip on a deleted track. Clips with
    no track (mixdowns) are restored as before.
    """
    clip_id = snapshot.get("id")
    if clip_id is None:
        return "dropped"
    track_id = snapshot.get("track_id")
    if track_id is not None and find_by_id(tracks, track_id) is None:
        return "dropped"
    for i, clip in enumerate(clips):
        if clip.get("id") == clip_id:
            clips[i] = dict(snapshot)
            return "replaced"
    clips.append(dict(snapshot))
    return "appended"


def check_track_type(value: Any) -> str:
    """Return value if it is an allowed track type, else raise ValueError."""
    if value not in TRACK_TYPES:
        raise ValueError(f"type must be one of {', '.join(TRACK_TYPES)}")
    return value
