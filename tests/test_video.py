"""Video safe-name and split-audio guard tests."""

from pathlib import Path

import pytest

from app.backend.video import _safe_name, split_audio


def test_safe_name():
    assert _safe_name("My Effect!") == "my_effect_"
    assert _safe_name("") == "custom"


def test_split_audio_rejects_non_video(tmp_path):
    bad = tmp_path / "note.txt"
    bad.write_text("x")
    with pytest.raises(ValueError):
        split_audio(bad)
