"""POST /api/audio/clips/move sets a clip's timeline position in seconds.

Uses the fastapi/pydantic stand-ins from tests.test_daw_ids; the endpoint
function is called directly, no HTTP request is made, so the HTTP layer
(routing, body parsing, status codes on the wire) is not exercised here.
The mix check renders through server.mix_audio into a temp uploads dir.
"""

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio, daw_state  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

RATE = 44100


def _write_tone(path, seconds=0.1, value=10000):
    frames = int(seconds * RATE)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<%dh" % frames, *([value] * frames)))


def _first_loud_frame(path):
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        ch = w.getnchannels()
        data = struct.unpack("<%dh" % (n * ch), w.readframes(n))
    for i in range(n):
        if data[i * ch] != 0:
            return i, n
    return None, n


class PositionRule(unittest.TestCase):
    def test_accepts_finite_non_negative_numbers(self):
        self.assertEqual(daw_state.check_clip_position(0), 0.0)
        self.assertEqual(daw_state.check_clip_position(2.5), 2.5)
        self.assertEqual(daw_state.check_clip_position(7), 7.0)

    def test_rejects_bad_values(self):
        for bad in (-0.001, -3, math.nan, math.inf, -math.inf, "1.5", "abc", None, True, [1]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    daw_state.check_clip_position(bad)


class ClipMove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patch = mock.patch.object(audio, "UPLOAD_DIR", tmp)
        self.patch.start()
        self.file = tmp / "tone.wav"
        _write_tone(self.file)
        self.saved = (server._sample_rate, server._master)
        server._sample_rate = RATE
        server._master = audio.default_master()
        server._audio_tracks = [audio.make_track(i, f"Audio {i + 1}") for i in range(2)]
        server._audio_clips = [audio.make_clip(0, "tone.wav", self.file, track_id=0, sample_rate=RATE)]
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        server._sample_rate, server._master = self.saved
        self.patch.stop()
        self.tmp.cleanup()

    def _move(self, clip_id, position):
        return server.move_clip(server.ClipMoveRequest(clip_id=clip_id, position=position))

    def test_sets_position_as_given_and_returns_clip(self):
        out = self._move(0, 1.2345)
        self.assertIs(out, server._audio_clips[0])
        self.assertEqual(out["position"], 1.2345)
        self.assertEqual(out["track_id"], 0)

    def test_bad_position_is_400_and_changes_nothing(self):
        for bad in (-1, math.nan, math.inf, "abc", None):
            with self.subTest(bad=bad):
                with self.assertRaises(server.HTTPException) as cm:
                    self._move(0, bad)
                self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(server._audio_clips[0]["position"], 0.0)
        self.assertEqual(server._undo_stack, [])

    def test_missing_clip_is_404(self):
        with self.assertRaises(server.HTTPException) as cm:
            self._move(99, 1.0)
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(server._undo_stack, [])

    def test_one_undo_snapshot_and_undo_moves_it_back(self):
        self._move(0, 2.0)
        self.assertEqual(len(server._undo_stack), 1)
        self.assertEqual(server._undo_stack[0]["data"]["position"], 0.0)
        res = server._dispatch_tool("undo", {})
        self.assertEqual(res["restored"], "replaced")
        self.assertEqual(server._audio_clips[0]["position"], 0.0)

    def test_mix_renders_clip_at_new_position(self):
        before = server.mix_audio()
        first, frames = _first_loud_frame(before["path"])
        self.assertEqual(first, 0)
        self.assertEqual(frames, int(0.1 * RATE) + 1)
        server._audio_clips[:] = [c for c in server._audio_clips if not c.get("mix")]

        self._move(0, 0.5)
        after = server.mix_audio()
        first, frames = _first_loud_frame(after["path"])
        self.assertEqual(first, int(0.5 * RATE))
        self.assertEqual(frames, int(0.6 * RATE) + 1)


if __name__ == "__main__":
    unittest.main()
