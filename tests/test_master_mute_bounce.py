"""What mix and bounce write and report when the master is muted (J).

Today a muted master (or nothing to play) writes a header-only WAV with
zero frames (audio.py mix_arrangement: _write_wav(dest, b"", rate, 2)),
not silence the length of the arrangement. This checks that the routes
report that file honestly: the returned clip points at the written file
and its duration matches the frames in it (0), and no clip is read.
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


class MasterMute(unittest.TestCase):
    _SAVED = ("_audio_tracks", "_audio_clips", "_sample_rate", "_track_ids", "_clip_ids", "_master")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        src = self.dir / "a.wav"
        with wave.open(str(src), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(struct.pack("<h", 1000) * 2000)
        server._audio_tracks = [audio.make_track(0, "T1")]
        server._audio_clips = [audio.make_clip(1, "a.wav", src, track_id=server._audio_tracks[0]["id"],
                                               sample_rate=RATE, position=1.0)]
        server._sample_rate = RATE
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)
        server._master = dict(audio.default_master(), mute=True)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()

    def _check(self, out):
        path = Path(out["path"])
        self.assertTrue(path.exists())
        with wave.open(str(path), "rb") as w:
            frames, ch, rate = w.getnframes(), w.getnchannels(), w.getframerate()
        self.assertEqual((frames, ch, rate), (0, 2, RATE))  # zero-length, not 3 s of silence
        self.assertEqual(out["duration"], 0)
        self.assertEqual(out["duration"], round(frames / rate, 3))
        self.assertTrue(out["mix"])

    def test_bounce_with_master_muted(self):
        self._check(server.bounce_audio(server.BounceRequest(name="muted.wav")))

    def test_mix_with_master_muted(self):
        self._check(server.mix_audio())

    def test_muted_master_does_not_read_clips(self):
        server._audio_clips[0]["path"] = str(self.dir / "missing.wav")
        self._check(server.mix_audio())


if __name__ == "__main__":
    unittest.main()
