"""Split and undo must deep-copy a clip (D3).

clip_split built the right half with dict(clip), and _push_undo /
restore_clip_snapshot stored and restored dict(snapshot): shallow copies,
so the nested "effects" dict (and its per-effect slots) and the "peaks"
list were shared. Applying an effect to one half then also marked it on the
other half, and the effect route's in-place slot update rewrote the undo
snapshot taken just before it. A per-clip fx list would be shared the same
way.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter, restore_clip_snapshot  # noqa: E402

RATE = 1000


class _Base(unittest.TestCase):
    _SAVED = ("_audio_tracks", "_audio_clips", "_sample_rate", "_track_ids", "_clip_ids")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        server._undo_stack.clear()
        src = self.dir / "s.wav"
        with wave.open(str(src), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", (i % 40) * 200) for i in range(1000)))
        server._audio_tracks = [audio.make_track(0, "T1")]
        clip = audio.make_clip(1, "s.wav", src, track_id=server._audio_tracks[0]["id"], sample_rate=RATE)
        clip["fx"] = [{"id": 1, "type": "eq", "enabled": True, "params": {"bands": [0.0, 1.0]}}]
        server._audio_clips = [clip]
        server._sample_rate = RATE
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        server._undo_stack.clear()
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()


def _shared(a, b, path=""):
    """Names of mutable containers that a and b share (same object)."""
    out = []
    if isinstance(a, (dict, list)) and a is b:
        out.append(path or "<root>")
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                out += _shared(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            out += _shared(x, y, f"{path}[{i}]")
    return out


class Split(_Base):
    def test_halves_share_no_list_or_dict(self):
        server.clip_split(server.ClipSplitRequest(clip_id=1, at=0.4))
        left, right = server._audio_clips
        self.assertEqual(_shared(left, right), [])

    def test_fx_list_on_one_half_does_not_change_the_other(self):
        server.clip_split(server.ClipSplitRequest(clip_id=1, at=0.4))
        left, right = server._audio_clips
        left["fx"].append({"id": 2, "type": "delay", "enabled": True, "params": {}})
        left["fx"][0]["params"]["bands"][0] = 6.0
        self.assertEqual(len(right["fx"]), 1)
        self.assertEqual(right["fx"][0]["params"]["bands"], [0.0, 1.0])

    def test_effect_on_left_half_is_not_marked_on_the_right(self):
        server.clip_split(server.ClipSplitRequest(clip_id=1, at=0.4))
        left, right = server._audio_clips
        server.clip_effect(server.EffectRequest(clip_id=left["id"], kind="normalize", params={"target": 0.5}))
        self.assertTrue(left["effects"]["normalize"]["enabled"])
        self.assertFalse(right["effects"]["normalize"]["enabled"])


class Undo(_Base):
    def test_snapshot_shares_nothing_with_the_live_clip(self):
        clip = server._audio_clips[0]
        server._push_undo("x", clip)
        self.assertEqual(_shared(server._undo_stack[-1]["data"], clip), [])

    def test_effect_undo_restores_the_effect_flags(self):
        server.clip_effect(server.EffectRequest(clip_id=1, kind="normalize", params={"target": 0.5}))
        self.assertTrue(server._audio_clips[0]["effects"]["normalize"]["enabled"])
        server._dispatch_tool("undo", {})
        self.assertFalse(server._audio_clips[0]["effects"]["normalize"]["enabled"])

    def test_restored_clip_shares_nothing_with_the_snapshot(self):
        snap = dict(server._audio_clips[0], id=1)
        restore_clip_snapshot(server._audio_clips, server._audio_tracks, snap)
        self.assertEqual(_shared(server._audio_clips[0], snap), [])
        snap2 = dict(server._audio_clips[0], id=99)
        restore_clip_snapshot(server._audio_clips, server._audio_tracks, snap2)
        self.assertEqual(_shared(server._audio_clips[-1], snap2), [])


if __name__ == "__main__":
    unittest.main()
