"""Clip split respects an existing trim.

A clip plays the source window [trim_in, trim_out) at its timeline position
(audio._clip_window). Splitting at timeline time `at` cuts that window at
`into = at - position` seconds, so the two halves together play exactly what
the clip played before. Uses the stand-ins from tests.test_daw_ids.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (stubs fastapi, sets TK80_UPLOADS)
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

RATE = 8000  # every split point below is a whole number of frames


def _ramp_wav(path: Path, seconds: float) -> None:
    n = int(seconds * RATE)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", (i % 2000) * 10 - 10000) for i in range(n)))


def _mix_frames(clips, tracks):
    path = audio.mix_arrangement(clips, tracks, RATE, "split_test_mix.wav")
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return list(struct.unpack("<%dh" % (len(raw) // 2), raw))


class ClipSplitTrim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "ramp.wav"
        _ramp_wav(self.file, 1.0)
        server._audio_tracks = [audio.make_track(0, "Audio 1", "stereo", RATE)]
        server._audio_clips = []
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        self.tmp.cleanup()

    def _new_clip(self, position=0.0):
        return server.add_clip(name="c", path=str(self.file), track_id=0, position=position)

    def _split(self, clip, at):
        server.clip_split(server.ClipSplitRequest(clip_id=clip["id"], at=at))
        return sorted(server._audio_clips, key=lambda c: c["position"])

    @staticmethod
    def _window(clip):
        """(source start, source end) the clip plays, as _clip_window reads it."""
        trim_in = float(clip.get("trim_in") or 0.0)
        trim_out = float(clip.get("trim_out") or 0.0)
        return round(trim_in, 6), round(trim_out if trim_out > 0 else 1.0, 6)

    def _assert_rebuilds(self, before):
        """Mix of the current clips equals the mix of `before` (a list of clip copies)."""
        tracks = server._audio_tracks
        want = _mix_frames(before, tracks)
        got = _mix_frames(server._audio_clips, tracks)
        n = min(len(want), len(got))
        self.assertEqual(got[:n], want[:n])
        self.assertTrue(all(v == 0 for v in want[n:]) and all(v == 0 for v in got[n:]))
        self.assertTrue(any(want), "test mix is silent")

    def test_split_untrimmed_clip_unchanged_behaviour(self):
        c = self._new_clip(position=0.5)
        before = [dict(c)]
        left, right = self._split(c, 0.75)
        self.assertEqual(self._window(left), (0.0, 0.25))
        self.assertAlmostEqual(left["duration"], 0.25)
        self.assertAlmostEqual(left["position"], 0.5)
        self.assertEqual(self._window(right), (0.25, 1.0))
        self.assertAlmostEqual(right["position"], 0.75)
        self.assertAlmostEqual(right["duration"], 0.75)
        self.assertNotEqual(left["id"], right["id"])
        self._assert_rebuilds(before)

    def test_split_already_trimmed_clip(self):
        c = self._new_clip(position=1.0)
        server.clip_trim(server.ClipTrimRequest(clip_id=c["id"], trim_in=0.25, trim_out=0.75))
        before = [dict(c)]
        left, right = self._split(c, 1.125)  # 0.125 s into the window
        self.assertEqual(self._window(left), (0.25, 0.375))
        self.assertAlmostEqual(left["position"], 1.0)
        self.assertAlmostEqual(left["duration"], 0.125)
        self.assertEqual(self._window(right), (0.375, 0.75))
        self.assertAlmostEqual(right["position"], 1.125)
        self.assertAlmostEqual(right["duration"], 0.375)
        self._assert_rebuilds(before)

    def test_split_right_half_again(self):
        c = self._new_clip(position=0.0)
        server.clip_trim(server.ClipTrimRequest(clip_id=c["id"], trim_in=0.125, trim_out=0.875))
        before = [dict(c)]
        _, right = self._split(c, 0.25)
        a, b, r2 = self._split(right, 0.5)
        self.assertEqual(self._window(a), (0.125, 0.375))
        self.assertEqual(self._window(b), (0.375, 0.625))
        self.assertAlmostEqual(b["position"], 0.25)
        self.assertAlmostEqual(b["duration"], 0.25)
        self.assertEqual(self._window(r2), (0.625, 0.875))
        self.assertAlmostEqual(r2["position"], 0.5)
        self.assertAlmostEqual(r2["duration"], 0.25)
        self.assertEqual(len({x["id"] for x in (a, b, r2)}), 3)
        self._assert_rebuilds(before)

    def test_split_untrimmed_right_half_again(self):
        c = self._new_clip(position=0.0)
        before = [dict(c)]
        _, right = self._split(c, 0.5)
        self._split(right, 0.75)
        self._assert_rebuilds(before)

    def test_split_reversed_trimmed_clip_rebuilds(self):
        c = self._new_clip(position=0.0)
        server.clip_trim(server.ClipTrimRequest(clip_id=c["id"], trim_in=0.25, trim_out=0.75))
        c["reversed"] = True
        before = [dict(c)]
        left, right = self._split(c, 0.125)
        # Reversed: the timeline-left half plays the end of the window.
        self.assertEqual(self._window(left), (0.625, 0.75))
        self.assertEqual(self._window(right), (0.25, 0.625))
        self._assert_rebuilds(before)

    def test_split_outside_window_is_noop(self):
        c = self._new_clip(position=0.0)
        server.clip_trim(server.ClipTrimRequest(clip_id=c["id"], trim_in=0.25, trim_out=0.75))
        for at in (0.0, 0.5, 0.625, -1.0):
            with self.subTest(at=at):
                self._split(c, at)
                self.assertEqual(len(server._audio_clips), 1)
        self.assertEqual(self._window(c), (0.25, 0.75))


if __name__ == "__main__":
    unittest.main()
