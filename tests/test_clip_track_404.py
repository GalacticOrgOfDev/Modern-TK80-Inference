"""A clip created on a track id that does not exist gets a 404.

No track id still means the first track (created if there are none), and
mixdowns still have no track. Uses the fastapi/pydantic stand-ins from
tests.test_daw_ids; endpoint functions are called directly, no HTTP.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402


class _Upload:
    def __init__(self, name, data):
        self.filename = name
        self._data = data

    async def read(self):
        return self._data


class ClipOnMissingTrack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "c.wav"
        self.file.write_bytes(b"")
        server._audio_tracks = [audio.make_track(i, f"Audio {i + 1}") for i in range(4)]
        server._audio_clips = []
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        self.tmp.cleanup()

    def _status(self, fn, *args, **kwargs):
        with self.assertRaises(Exception) as cm:
            fn(*args, **kwargs)
        return getattr(cm.exception, "status_code", None)

    def test_add_clip_on_missing_track_404_and_nothing_added(self):
        self.assertEqual(self._status(server.add_clip, name="x", path=str(self.file), track_id=99), 404)
        self.assertEqual(server._audio_clips, [])

    def test_add_clip_on_deleted_track_404(self):
        server.delete_track(2)
        self.assertEqual(self._status(server.add_clip, name="x", track_id=2), 404)
        self.assertEqual(server._audio_clips, [])

    def test_add_clip_on_existing_track_and_default(self):
        c = server.add_clip(name="a", track_id=3)
        self.assertEqual(c["track_id"], 3)
        server.delete_track(0)
        d = server.add_clip(name="b")  # no id: first remaining track
        self.assertEqual(d["track_id"], 1)

    def test_default_creates_track_when_none(self):
        for t in list(server._audio_tracks):
            server.delete_track(t["id"])
        c = server.add_clip(name="a")
        self.assertEqual(len(server._audio_tracks), 1)
        self.assertEqual(c["track_id"], server._audio_tracks[0]["id"])
        self.assertEqual(c["track_id"], 4)  # fresh id, not a reused 0

    def test_upload_on_missing_track_404_and_no_file_saved(self):
        before = set(audio.UPLOAD_DIR.iterdir()) if audio.UPLOAD_DIR.exists() else set()
        with self.assertRaises(Exception) as cm:
            asyncio.run(server.upload_audio(file=_Upload("u404.wav", b"RIFF"), track_id=99))
        self.assertEqual(getattr(cm.exception, "status_code", None), 404)
        after = set(audio.UPLOAD_DIR.iterdir()) if audio.UPLOAD_DIR.exists() else set()
        self.assertEqual(before, after)
        self.assertEqual(server._audio_clips, [])

    def test_upload_on_existing_track(self):
        c = asyncio.run(server.upload_audio(file=_Upload("ok.wav", b"RIFF"), track_id=1))
        self.assertEqual(c["track_id"], 1)

    def test_generate_tools_on_missing_track_404(self):
        for tool, args in (
            ("generate_instrument", {"instrument": "kick", "duration": 0.05}),
            ("generate_loop", {"style": "basic", "bars": 1}),
            ("render_pattern", {"bars": 1}),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(self._status(server._dispatch_tool, tool, dict(args, track_id=99)), 404)
        self.assertEqual(server._audio_clips, [])

    def test_generate_tools_on_existing_track(self):
        clip = server._dispatch_tool("generate_instrument", {"instrument": "kick", "duration": 0.05, "track_id": 2})["clip"]
        self.assertEqual(clip["track_id"], 2)
        clip = server._dispatch_tool("generate_instrument", {"instrument": "kick", "duration": 0.05})["clip"]
        self.assertEqual(clip["track_id"], 0)

    def test_non_clip_tools_ignore_track_id(self):
        # set_bpm does not create a clip, so a stray track id is not checked.
        self.assertTrue(server._dispatch_tool("set_bpm", {"bpm": 120, "track_id": 99})["ok"])

    def test_mixdown_still_has_no_track(self):
        clip = server.mix_audio()
        self.assertIsNone(clip["track_id"])
        self.assertTrue(clip["mix"])

    def test_detect_bpm_unknown_clip_404(self):
        self.assertEqual(self._status(server.detect_bpm_from_clip, 99), 404)
        self.assertEqual(self._status(server._dispatch_tool, "detect_bpm", {"clip_id": 99}), 404)


if __name__ == "__main__":
    unittest.main()
