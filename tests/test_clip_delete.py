"""DELETE /api/audio/clips/{clip_id} removes one clip and keeps its track.

Uses the fastapi/pydantic stand-ins from tests.test_daw_ids; the endpoint
function is called directly, no HTTP request is made, so the HTTP layer
(routing, status codes on the wire) is not exercised here.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402


class ClipDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.patch = mock.patch.object(audio, "UPLOAD_DIR", tmp)
        self.patch.start()
        self.file = tmp / "c.wav"
        self.file.write_bytes(b"RIFF")
        server._audio_tracks = [audio.make_track(i, f"Audio {i + 1}") for i in range(2)]
        server._audio_clips = [
            audio.make_clip(0, "a.wav", self.file, track_id=0, position=1.0),
            audio.make_clip(1, "b.wav", self.file, track_id=0, position=3.0),
        ]
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_removes_only_that_clip_and_keeps_track_and_file(self):
        out = server.delete_clip(0)
        self.assertEqual([c["id"] for c in server._audio_clips], [1])
        self.assertEqual(out, {"clips": server._audio_clips})
        self.assertEqual([t["id"] for t in server._audio_tracks], [0, 1])
        self.assertTrue(self.file.exists())

    def test_missing_clip_is_404_and_changes_nothing(self):
        with self.assertRaises(server.HTTPException) as cm:
            server.delete_clip(99)
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(len(server._audio_clips), 2)
        self.assertEqual(server._undo_stack, [])

    def test_one_undo_snapshot_and_undo_brings_it_back(self):
        before = dict(server._audio_clips[0])
        server.delete_clip(0)
        self.assertEqual(len(server._undo_stack), 1)
        self.assertEqual(server._undo_stack[0]["data"], before)
        res = server._dispatch_tool("undo", {})
        self.assertEqual(res["restored"], "appended")
        self.assertEqual(server._undo_stack, [])
        self.assertEqual(sorted(c["id"] for c in server._audio_clips), [0, 1])
        self.assertEqual(server.find_by_id(server._audio_clips, 0)["position"], 1.0)


if __name__ == "__main__":
    unittest.main()
