"""Where the app writes files, and how it picks names that are safe there.

Stdlib only. Roots are resolved once, at import, to absolute paths. A
relative root (the default, or a relative TK80_* value) is anchored to the
repository directory, never to the process working directory.

Writers reserve their file with reserve_unique(), which creates it
exclusively, so a second writer (or a file left from an earlier session)
is never overwritten: the name gets _1, _2, ... before the suffix instead.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]

_DRIVE = re.compile(r"^[A-Za-z]:")
_SEPARATORS = re.compile(r"[\\/]")


def resolve_root(env_var: str, default: str) -> Path:
    """Absolute directory from env_var, or default, anchored to APP_ROOT."""
    raw = os.environ.get(env_var, "").strip()
    path = Path(raw).expanduser() if raw else Path(default)
    if not path.is_absolute():
        path = APP_ROOT / path
    return path.resolve()


def safe_filename(name: str, default: str) -> str:
    """The last path component of name, with no separators or traversal.

    Forward and back slashes both count as separators and a leading drive
    ("C:") is dropped, whatever the host OS. Control characters are removed.
    An empty result, "." or ".." gives default. Other characters are kept,
    so an ordinary name comes back unchanged.
    """
    text = "".join(c for c in str(name or "") if c >= " " and c != "\x7f")
    text = _SEPARATORS.split(text)[-1]
    text = _DRIVE.sub("", text).strip()
    if text.strip(".") == "":
        return default
    return text


def reserve_unique(directory: Path, name: str) -> Path:
    """Create directory/name exclusively and return it.

    If that name is taken, try stem_1.suffix, stem_2.suffix, ... The file
    is created empty; the caller writes its content over it. Raises
    ValueError if the name would land outside directory.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    stem, suffix = os.path.splitext(name)
    i = 0
    while True:
        candidate = name if i == 0 else f"{stem}_{i}{suffix}"
        dest = directory / candidate
        if dest.resolve().parent != root:
            raise ValueError(f"file name escapes {root}: {name!r}")
        try:
            fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            i += 1
            continue
        os.close(fd)
        return dest
