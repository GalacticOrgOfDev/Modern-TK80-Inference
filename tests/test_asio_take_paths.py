"""Two ASIO takes on the same track must not share a file.

asio_start used the fixed path UPLOAD_DIR / f"asio_track{id}.wav" and
AsioRecorder.start opens it with wave.open(..., "wb"), which truncates, so
the second take overwrote the first take's audio while the first clip
still pointed at it. No hardware: a fake recorder stands in for
AsioRecorder and writes known bytes to whatever path it is given, the way
wave.open(path, "wb") would.
"""

import tempfile
import unittest
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402


class FakeRecorder:
    def __init__(self, fail_with=None):
        self.recording = False
        self.path = None
        self.take = 0
        self.fail_with = fail_with

    def start(self, path, sample_rate, buffer, channels=2, device_index=None):
        if self.fail_with is not None:
            raise self.fail_with
        self.take += 1
        Path(path).write_bytes(b"take-%d" % self.take)  # "wb": truncates
        self.path = Path(path)
        self.recording = True
        return {"ok": True, "device": {"index": 0, "name": "Fake"}, "sample_rate": sample_rate,
                "buffer": buffer, "channels": channels, "latency_ms": 1.0, "path": str(path)}

    def stop(self):
        self.recording = False
        return {"ok": True, "path": str(self.path), "sample_rate": 48000, "buffer": 64,
                "device": {"index": 0, "name": "Fake"}}

    def levels(self):
        return {"levels": [], "peak": 0.0}


class _Base(unittest.TestCase):
    _SAVED = ("_audio_tracks", "_audio_clips", "_track_ids", "_clip_ids", "_asio_recorder",
              "_asio_enabled", "_asio_track_id", "_sample_rate")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        track = audio.make_track(0, "Vox")
        track["armed"] = True
        server._audio_tracks = [track]
        server._audio_clips = []
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)
        server._asio_enabled = True
        server._asio_track_id = None
        server._sample_rate = 48000
        self.track_id = track["id"]

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()

    def _take(self):
        server.asio_start(server.AsioStartRequest(track_id=self.track_id))
        return server.asio_stop()


class TwoTakesSameTrack(_Base):
    def test_second_take_does_not_overwrite_the_first(self):
        server._asio_recorder = FakeRecorder()
        first = self._take()
        second = self._take()
        p1, p2 = Path(first["clip"]["path"]), Path(second["clip"]["path"])
        self.assertNotEqual(p1, p2)
        self.assertEqual(p1.read_bytes(), b"take-1")
        self.assertEqual(p2.read_bytes(), b"take-2")
        tid = self.track_id
        self.assertEqual(p1.name, f"asio_track{tid}.wav")
        self.assertEqual(p2.name, f"asio_track{tid}_1.wav")  # reserve_unique's suffix
        self.assertEqual(p1.parent, self.dir)

    def test_response_fields_unchanged(self):
        server._asio_recorder = FakeRecorder()
        out = server.asio_start(server.AsioStartRequest(track_id=self.track_id))
        for key in ("ok", "device", "sample_rate", "buffer", "channels", "latency_ms", "path"):
            self.assertIn(key, out)
        stop = server.asio_stop()
        self.assertTrue(stop["clip"]["asio"])

    def test_a_file_left_from_an_earlier_session_is_kept(self):
        old = self.dir / f"asio_track{self.track_id}.wav"
        old.write_bytes(b"earlier")
        server._asio_recorder = FakeRecorder()
        out = self._take()
        self.assertEqual(old.read_bytes(), b"earlier")
        self.assertNotEqual(Path(out["clip"]["path"]), old)


class FailedOpen(_Base):
    def test_failed_start_is_a_400_and_removes_the_empty_reservation(self):
        server._asio_recorder = FakeRecorder(fail_with=RuntimeError("no ASIO input device found"))
        with self.assertRaises(Exception) as cm:
            server.asio_start(server.AsioStartRequest(track_id=self.track_id))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual(list(self.dir.glob("asio_track*")), [])


if __name__ == "__main__":
    unittest.main()
