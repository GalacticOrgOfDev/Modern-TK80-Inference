"""The 30-band EQ filters by frequency.

Each band is a peaking biquad (RBJ Audio EQ Cookbook) centred on one of the
30 log-spaced frequencies from effects.eq_frequencies(). Gains stay linear
(1.0 = flat), as the DAW page sends them. These tests feed sine waves through
eq_30 and measure the change in RMS level, so they check the frequency
response, not how anything sounds.
"""

import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from app.backend import effects
from app.backend.effects import EQ_BANDS, eq_30, eq_frequencies

RATE = 44100
FREQS = eq_frequencies()


def _sine(freq, seconds=1.0, amp=4000.0, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return np.rint(amp * np.sin(2 * math.pi * freq * t)).astype(np.int64)


def _rms_db(x):
    x = np.asarray(x, dtype=np.float64)
    # Skip the first and last 0.2 s so filter start-up and tail don't count.
    skip = int(0.2 * RATE)
    core = x[skip:-skip] if len(x) > 2 * skip else x
    return 20 * math.log10(math.sqrt(float(np.mean(core * core))) + 1e-12)


def _change_db(freq, gains):
    src = _sine(freq)
    out = eq_30(src.tolist(), RATE, 1, gains)
    return _rms_db(out) - _rms_db(src)


def _one_band(band, gain):
    gains = [1.0] * EQ_BANDS
    gains[band] = gain
    return gains


def _nearest(freq):
    return min(range(EQ_BANDS), key=lambda b: abs(math.log(FREQS[b] / freq)))


class BandSelectivity(unittest.TestCase):
    def test_boost_at_centre_and_flat_far_away(self):
        probes = (200.0, 1000.0, 5000.0)
        for target in probes:
            band = _nearest(target)
            gains = _one_band(band, 2.0)  # +6.02 dB
            set_db = 20 * math.log10(2.0)
            with self.subTest(band=band, centre=round(FREQS[band], 1)):
                got = _change_db(FREQS[band], gains)
                self.assertAlmostEqual(got, set_db, delta=1.0)
            for far in probes:
                if far == target:
                    continue
                with self.subTest(band=band, far=far):
                    self.assertLess(abs(_change_db(far, gains)), 0.5)

    def test_cut_at_centre(self):
        band = _nearest(1000.0)
        got = _change_db(FREQS[band], _one_band(band, 0.5))  # -6.02 dB
        self.assertAlmostEqual(got, 20 * math.log10(0.5), delta=1.0)

    def test_full_range_boost_and_cut(self):
        # The page's sliders run 0.25..4 (about -12..+12 dB).
        band = _nearest(5000.0)
        for gain in (0.25, 4.0):
            with self.subTest(gain=gain):
                got = _change_db(FREQS[band], _one_band(band, gain))
                self.assertAlmostEqual(got, 20 * math.log10(gain), delta=1.0)


class FlatAndEdges(unittest.TestCase):
    def test_flat_gains_return_input_unchanged(self):
        src = _sine(1000.0, 0.1).tolist()
        self.assertEqual(eq_30(src, RATE, 1, [1.0] * EQ_BANDS), src)
        self.assertEqual(eq_30(src, RATE, 1, None), src)
        self.assertEqual(eq_30(src, RATE, 1, []), src)

    def test_bands_at_or_above_nyquist_are_skipped(self):
        rate = 8000  # Nyquist 4 kHz
        src = _sine(1000.0, 0.5, rate=rate).tolist()
        above = [b for b in range(EQ_BANDS) if FREQS[b] >= rate / 2]
        self.assertTrue(above)
        gains = [1.0] * EQ_BANDS
        for b in above:
            gains[b] = 4.0
        self.assertEqual(eq_30(src, rate, 1, gains), src)
        # All 30 set still runs and stays in range.
        out = eq_30(src, rate, 1, [2.0] * EQ_BANDS)
        self.assertEqual(len(out), len(src))
        self.assertTrue(all(-32768 <= v <= 32767 for v in out))

    def test_bad_values_default_to_flat(self):
        src = _sine(1000.0, 0.1).tolist()
        self.assertEqual(eq_30(src, RATE, 1, ["x", None] + [1.0] * 28), src)

    def test_empty_input(self):
        self.assertEqual(eq_30([], RATE, 2, [2.0] * EQ_BANDS), [])


class Channels(unittest.TestCase):
    def test_stereo_channels_filtered_independently(self):
        band = _nearest(1000.0)
        left = _sine(FREQS[band])
        right = _sine(5000.0)
        inter = np.empty(2 * len(left), dtype=np.int64)
        inter[0::2] = left
        inter[1::2] = right
        out = np.asarray(eq_30(inter.tolist(), RATE, 2, _one_band(band, 2.0)))
        self.assertEqual(len(out), len(inter))
        self.assertAlmostEqual(_rms_db(out[0::2]) - _rms_db(left), 20 * math.log10(2.0), delta=1.0)
        self.assertLess(abs(_rms_db(out[1::2]) - _rms_db(right)), 0.5)

    def test_mono_length_and_type(self):
        src = _sine(440.0, 0.3).tolist()
        out = eq_30(src, RATE, 1, _one_band(_nearest(440.0), 1.5))
        self.assertEqual(len(out), len(src))
        self.assertTrue(all(isinstance(v, int) for v in out))


class Clipping(unittest.TestCase):
    def test_output_clamps_instead_of_wrapping(self):
        band = _nearest(1000.0)
        src = _sine(FREQS[band], 0.5, amp=30000.0)
        out = np.asarray(eq_30(src.tolist(), RATE, 1, _one_band(band, 4.0)))
        self.assertEqual(int(out.max()), 32767)
        self.assertEqual(int(out.min()), -32768)
        # A wrapped sample would flip sign at the peaks.
        skip = int(0.2 * RATE)
        peaks = np.where(src[skip:] > 25000)[0] + skip
        self.assertTrue(np.all(out[peaks] > 0))
        troughs = np.where(src[skip:] < -25000)[0] + skip
        self.assertTrue(np.all(out[troughs] < 0))


class ApplyEffect(unittest.TestCase):
    def test_apply_effect_eq_writes_filtered_stereo_wav(self):
        band = _nearest(1000.0)
        left = _sine(FREQS[band], 0.6)
        right = _sine(200.0, 0.6)
        inter = np.empty(2 * len(left), dtype="<i2")
        inter[0::2] = left
        inter[1::2] = right
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.wav"
            with wave.open(str(src), "wb") as w:
                w.setnchannels(2)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(inter.tobytes())
            with mock.patch.object(effects, "UPLOAD_DIR", Path(d)):
                dest = effects.apply_effect(src, "eq", {"gains": _one_band(band, 2.0)})
            with wave.open(str(dest), "rb") as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (2, 2, RATE))
                got = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.int64)
        self.assertEqual(len(got), len(inter))
        self.assertAlmostEqual(_rms_db(got[0::2]) - _rms_db(left), 20 * math.log10(2.0), delta=1.0)
        self.assertLess(abs(_rms_db(got[1::2]) - _rms_db(right)), 0.5)


class MatchesRecursiveBiquads(unittest.TestCase):
    """The fast path must equal a plain sample-by-sample RBJ biquad cascade."""

    def _check(self, gains, rate, seconds):
        rng = np.random.default_rng(7)
        src = np.rint(rng.uniform(-6000, 6000, int(seconds * rate))).astype(np.int64).tolist()
        ref = effects.biquad_reference(src, effects.eq_bands_active(rate, gains))
        want = [max(-32768, min(32767, int(round(v)))) for v in ref]
        got = eq_30(src, rate, 1, gains)
        self.assertEqual(len(got), len(want))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(got, want)), 1)

    def test_few_bands(self):
        gains = [1.0] * EQ_BANDS
        gains[0], gains[13], gains[27] = 3.0, 0.4, 1.8
        self._check(gains, RATE, 0.25)

    def test_all_bands(self):
        gains = [0.6 + 0.1 * (b % 7) for b in range(EQ_BANDS)]
        self._check(gains, 48000, 0.25)

    def test_q_from_band_spacing(self):
        octaves = math.log2(FREQS[1] / FREQS[0])
        self.assertAlmostEqual(effects.EQ_Q, math.sqrt(2 ** octaves) / (2 ** octaves - 1), places=9)


if __name__ == "__main__":
    unittest.main()
