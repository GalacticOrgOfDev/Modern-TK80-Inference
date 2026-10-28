"""Format catalog and audio gain tests."""

from pathlib import Path

from app.backend.audio import clamp_gain
from app.backend.formats import AUDIO_STORE, is_audio, is_processable_audio


def test_clamp_gain_bounds():
    assert clamp_gain(1.0) == 1.0
    assert clamp_gain(-1) == 0.0
    assert clamp_gain(9) == 4.0
    assert clamp_gain("bad") == 1.0


def test_audio_formats():
    assert is_audio(Path("a.wav"))
    assert is_audio(Path("a.mp3"))
    assert is_processable_audio(Path("a.flac"))
    assert ".wma" in AUDIO_STORE
