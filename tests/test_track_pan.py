"""The track pan slider is honoured: stored on update and applied in the mix.

app.js sends {"pan": x} (x in -1..1) to POST /api/audio/tracks/{id} and
renders the slider from track.pan. Before, TrackUpdate had no pan field,
so the value was dropped, the slider snapped back to centre on the next
refresh, and mix/bounce ignored it. Now pan is a track field (default
0.0), validated to -1..1, and the mixdown applies it as a balance
control: centre leaves both sides untouched (mixes are bit-identical to
before), pan < 0 scales the right side by (1 + pan), pan > 0 scales the
left side by (1 - pan). It is applied after the stereo/left/right channel
routing. Uses the fastapi/pydantic stand-ins from tests.test_daw_ids.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio  # noqa: E402

RATE = 1000
FRAMES = 50


def _write(path, channels=2, left=8000, right=4000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frame = struct.pack("<hh", left, right) if channels == 2 else struct.pack("<h", left)
        w.writeframes(frame * FRAMES)
    return path


def _frames(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return [struct.unpack_from("<hh", raw, i) for i in range(0, len(raw), 4)]


class PanStoredOnUpdate(unittest.TestCase):
    def setUp(self):
        self._saved = (server._audio_tracks, server._audio_clips)
        server._audio_tracks = [audio.make_track(0, "T1")]
        server._audio_clips = []

    def tearDown(self):
        server._audio_tracks, server._audio_clips = self._saved

    def test_new_track_is_centred(self):
        self.assertEqual(audio.make_track(3, "x")["pan"], 0.0)

    def test_update_stores_pan(self):
        for value in (-1.0, -0.25, 0.0, 0.6, 1.0):
            with self.subTest(pan=value):
                track = server.update_track(0, server.TrackUpdate(pan=value))
                self.assertEqual(track["pan"], value)
                self.assertEqual(server._audio_tracks[0]["pan"], value)

    def test_other_updates_leave_pan_alone(self):
        server.update_track(0, server.TrackUpdate(pan=-0.5))
        track = server.update_track(0, server.TrackUpdate(gain=0.5))
        self.assertEqual(track["pan"], -0.5)

    def test_out_of_range_pan_is_400_and_unchanged(self):
        server.update_track(0, server.TrackUpdate(pan=0.3))
        for bad in (-1.01, 1.5, float("nan"), float("inf")):
            with self.subTest(pan=bad):
                with self.assertRaises(Exception) as cm:
                    server.update_track(0, server.TrackUpdate(pan=bad, gain=2.0))
                self.assertEqual(getattr(cm.exception, "status_code", None), 400)
                self.assertEqual(server._audio_tracks[0]["pan"], 0.3)
                self.assertEqual(server._audio_tracks[0]["gain"], 1.0)


class PanInMix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir / "out"
        audio.UPLOAD_DIR.mkdir()

    def tearDown(self):
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()

    def _mix(self, pan=None, channels=2, channel="stereo"):
        src = _write(self.dir / f"s{channels}.wav", channels=channels)
        track = audio.make_track(0, "T1", channel=channel)
        if pan is None:
            track.pop("pan", None)
        else:
            track["pan"] = pan
        clip = audio.make_clip(1, src.name, src, track_id=0, sample_rate=RATE)
        return _frames(audio.mix_arrangement([clip], [track], RATE, "mix.wav"))[:FRAMES]

    def assertSide(self, frames, left, right):
        for i, (l, r) in enumerate(frames):
            self.assertLessEqual(abs(l - left), 1, f"frame {i} left {l} != {left}")
            self.assertLessEqual(abs(r - right), 1, f"frame {i} right {r} != {right}")

    def test_centre_and_missing_pan_are_unchanged(self):
        self.assertEqual(self._mix(0.0), self._mix(None))
        self.assertSide(self._mix(0.0), 8000, 4000)

    def test_hard_left_and_right(self):
        self.assertSide(self._mix(-1.0), 8000, 0)
        self.assertSide(self._mix(1.0), 0, 4000)

    def test_partial_pan_scales_the_far_side(self):
        self.assertSide(self._mix(-0.5), 8000, 2000)
        self.assertSide(self._mix(0.25), 6000, 4000)

    def test_mono_clip_pans(self):
        self.assertSide(self._mix(-0.5, channels=1), 8000, 4000)
        self.assertSide(self._mix(1.0, channels=1), 0, 8000)

    def test_applied_after_channel_routing(self):
        self.assertSide(self._mix(0.5, channel="left"), 4000, 0)
        self.assertSide(self._mix(-1.0, channel="right"), 0, 0)


if __name__ == "__main__":
    unittest.main()
