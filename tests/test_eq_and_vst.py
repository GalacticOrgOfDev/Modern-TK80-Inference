"""VST preset and EQ frequency tests."""

from app.backend.effects import EQ_BANDS, eq_frequencies
from app.backend.vst import EFFECT_PRESETS


def test_eq_band_count_and_range():
    freqs = eq_frequencies()
    assert len(freqs) == EQ_BANDS == 30
    assert abs(freqs[0] - 100.0) < 1
    assert abs(freqs[-1] - 20000.0) < 1


def test_vst_presets_include_core():
    for name in ("reverb", "delay", "eq", "compressor", "custom"):
        assert name in EFFECT_PRESETS
