"""/api/audio/edit reverse must reverse what the bounce plays exactly once.

A rising ramp makes the direction readable from the bounced samples. The
suspected bug (D2): the route reverses the file on disk and then also sets
the clip's reversed flag, so the mix reverses it a second time and the clip
plays forwards.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

RATE = 1000
N = 100


def _write_ramp(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", 100 + i * 100) for i in range(N)))
    return path


def _left(path):
    with wave.open(str(path), "rb") as w:
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    vals = [struct.unpack_from("<h", raw, i)[0] for i in range(0, len(raw), 2)]
    return vals[::ch]


class EditReverseOnce(unittest.TestCase):
    _SAVED = ("_audio_tracks", "_audio_clips", "_sample_rate", "_track_ids", "_clip_ids")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        server._undo_stack.clear()
        server._audio_tracks = [audio.make_track(0, "T1")]
        server._sample_rate = RATE
        src = _write_ramp(self.dir / "ramp.wav")
        server._audio_clips = [audio.make_clip(1, "ramp.wav", src, track_id=server._audio_tracks[0]["id"],
                                               sample_rate=RATE, position=0.0)]
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        server._undo_stack.clear()
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()

    def _bounced(self):
        out = server.bounce_audio(server.BounceRequest(name="rev_check.wav"))
        vals = [v for v in _left(Path(out["path"])) if v != 0]
        self.assertEqual(len(vals), N)
        return vals

    def test_bounce_before_edit_rises(self):
        vals = self._bounced()
        self.assertTrue(all(a < b for a, b in zip(vals, vals[1:])))

    def test_edit_reverse_bounces_falling(self):
        server.edit_audio(server.AudioEditRequest(clip_id=1, action="reverse"))
        vals = self._bounced()
        self.assertTrue(all(a > b for a, b in zip(vals, vals[1:])), vals[:5])

    def test_edit_reverse_on_a_reversed_clip_bounces_rising(self):
        server._audio_clips[0]["reversed"] = True
        self.assertTrue(all(a > b for a, b in zip(self._bounced(), self._bounced()[1:])))
        server._audio_clips = [c for c in server._audio_clips if not c.get("mix")]
        server.edit_audio(server.AudioEditRequest(clip_id=1, action="reverse"))
        vals = self._bounced()
        self.assertTrue(all(a < b for a, b in zip(vals, vals[1:])), vals[:5])


if __name__ == "__main__":
    unittest.main()
