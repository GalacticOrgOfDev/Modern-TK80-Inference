"""Mixdown honours the flag-only clip edits (trim, split, reverse, silence)."""

import os
import struct
import tempfile
import unittest
import wave
from pathlib import Path

os.environ.setdefault("TK80_UPLOADS", tempfile.mkdtemp(prefix="tk80_uploads_"))

from app.backend import audio  # noqa: E402

RATE = 1000
FRAMES = 1000  # one second


def _write_source(path: Path) -> None:
    """Stereo 16-bit ramp: frame i is (i + 1, -(i + 1))."""
    pcm = b"".join(struct.pack("<hh", i + 1, -(i + 1)) for i in range(FRAMES))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def _read_left(path: Path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return [struct.unpack_from("<h", raw, i)[0] for i in range(0, len(raw), 4)]


class DawMixClipFlags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old_dir = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self.src = self.dir / "src.wav"
        _write_source(self.src)
        self.tracks = [audio.make_track(0, "T1")]

    def tearDown(self):
        audio.UPLOAD_DIR = self._old_dir
        self.tmp.cleanup()

    def _clip(self, **extra):
        clip = audio.make_clip(0, "src.wav", self.src, track_id=0, sample_rate=RATE)
        clip.update(extra)
        return clip

    def _mix(self, clips, name="mix.wav"):
        return _read_left(audio.mix_arrangement(clips, self.tracks, RATE, name))

    def assertNear(self, got, want):
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            self.assertLessEqual(abs(g - w), 1, f"sample {i}: {g} != {w}")

    def test_unflagged_clip_unchanged(self):
        out = self._mix([self._clip()])
        self.assertNear(out[:FRAMES], [i + 1 for i in range(FRAMES)])

    def test_silenced_clip_is_silent(self):
        out = self._mix([self._clip(silenced=True)])
        self.assertTrue(out)
        self.assertEqual(max(abs(s) for s in out), 0)

    def test_trim_window_plays_right_samples(self):
        # trim_in 0.2 s, trim_out 0.5 s -> source frames 200..499 at position 0.
        out = self._mix([self._clip(trim_in=0.2, trim_out=0.5)])
        self.assertNear(out[:300], [i + 1 for i in range(200, 500)])
        self.assertEqual(max(abs(s) for s in out[300:]), 0)

    def test_split_right_half_starts_at_offset(self):
        # Mirror server.clip_split at 0.4 s on a clip at position 0.
        left = self._clip(trim_out=0.4, duration=0.4)
        right = self._clip(position=0.4, trim_in=0.4, duration=0.6)
        right["id"] = 1
        out = self._mix([left, right])
        # Back to back, the two halves rebuild the original ramp.
        self.assertNear(out[:FRAMES], [i + 1 for i in range(FRAMES)])
        only_right = self._mix([right], "right.wav")
        self.assertEqual(max(abs(s) for s in only_right[:400]), 0)
        self.assertNear(only_right[400:FRAMES], [i + 1 for i in range(400, FRAMES)])

    def test_reversed_clip_is_reversed(self):
        out = self._mix([self._clip(reversed=True)])
        self.assertNear(out[:FRAMES], [FRAMES - i for i in range(FRAMES)])

    def test_reversed_trim_reverses_the_window(self):
        out = self._mix([self._clip(trim_in=0.2, trim_out=0.5, reversed=True)])
        self.assertNear(out[:300], [500 - i for i in range(300)])


if __name__ == "__main__":
    unittest.main()
