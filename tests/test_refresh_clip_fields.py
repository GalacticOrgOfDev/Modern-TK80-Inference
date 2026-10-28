"""Applying an effect keeps the clip's play fields; baking edits reset what they bake.

apply_effect reads the whole source file and writes a processed copy of
the same length (effects.py apply_effect; every effect loops over the
existing samples), so trim_in/trim_out (source offsets), reversed,
silenced, gain, mute, position and track still mean the same thing on the
new file and must be kept. Before, _refresh_clip rebuilt the clip with
make_clip and kept only mute, effects, position and track_id: gain was
read but never written back, and trim, reversed and silenced were dropped.

/api/audio/edit trim writes only the [start, end) window, and reverse
writes the whole file reversed, so the old trim offsets no longer point at
the same audio: those two reset trim_in/trim_out. Reverse keeps the
reversed flag as it was instead of also toggling it (the file already
holds the reversal; toggling as well made the mix play it forwards).
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
FRAMES = 200


def _write(path, values):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", v) for v in values))
    return path


def _read(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return [struct.unpack_from("<h", raw, i)[0] for i in range(0, len(raw), 2)]


class _Base(unittest.TestCase):
    _SAVED = ("_audio_tracks", "_audio_clips", "_sample_rate", "_track_ids", "_clip_ids")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.dir
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        server._undo_stack.clear()
        server._audio_tracks = [audio.make_track(0, "T1"), audio.make_track(1, "T2")]
        server._sample_rate = RATE
        src = _write(self.dir / "src.wav", [(i % 50) * 100 for i in range(FRAMES)])
        clip = audio.make_clip(1, "src.wav", src, track_id=1, sample_rate=RATE, position=2.5)
        clip.update({"trim_in": 0.05, "trim_out": 0.15, "reversed": True, "silenced": True,
                     "gain": 0.5, "mute": True})
        server._audio_clips = [clip]
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)
        self.clip = clip
        self.src = src

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        server._undo_stack.clear()
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()


class EffectKeepsPlayFields(_Base):
    KEPT = {"trim_in": 0.05, "trim_out": 0.15, "reversed": True, "silenced": True,
            "gain": 0.5, "mute": True, "position": 2.5, "track_id": 1, "id": 1}

    def test_effect_bakes_the_full_source_same_length(self):
        out = server.clip_effect(server.EffectRequest(clip_id=1, kind="normalize", params={"target": 0.5}))
        self.assertNotEqual(out["path"], str(self.src))
        self.assertEqual(len(_read(Path(out["path"]))), FRAMES)
        self.assertEqual(out["duration"], round(FRAMES / RATE, 3))

    def test_effect_keeps_trim_reverse_silence_gain_mute_position_track(self):
        for kind, params in (("normalize", {"target": 0.5}), ("compress", {}), ("delay", {}), ("reverb", {})):
            with self.subTest(kind=kind):
                out = server.clip_effect(server.EffectRequest(clip_id=1, kind=kind, params=params))
                for k, v in self.KEPT.items():
                    self.assertEqual(out.get(k), v, k)
                self.assertTrue(out["effects"][kind]["enabled"])
                self.assertIs(out, server._audio_clips[0])

    def test_file_fields_follow_the_new_file(self):
        out = server.clip_effect(server.EffectRequest(clip_id=1, kind="normalize", params={"target": 0.5}))
        new = Path(out["path"])
        self.assertTrue(new.exists())
        self.assertEqual(out["name"], new.name)
        self.assertEqual(out["peaks"], audio.wav_peaks(new))
        self.assertEqual(out["end"], out["duration"])


class BakingEditsReset(_Base):
    def test_edit_trim_resets_the_trim_window_and_keeps_the_rest(self):
        out = server.edit_audio(server.AudioEditRequest(clip_id=1, action="trim", start=0.05, end=0.1))
        self.assertEqual(len(_read(Path(out["path"]))), 50)
        self.assertNotIn("trim_in", out)
        self.assertNotIn("trim_out", out)
        for k, v in {"reversed": True, "silenced": True, "gain": 0.5, "mute": True, "position": 2.5}.items():
            self.assertEqual(out.get(k), v, k)

    def test_edit_reverse_bakes_once_and_keeps_the_flag(self):
        before = _read(self.src)
        out = server.edit_audio(server.AudioEditRequest(clip_id=1, action="reverse"))
        self.assertEqual(_read(Path(out["path"])), before[::-1])
        self.assertTrue(out["reversed"])  # unchanged; not toggled on top of the baked reversal
        self.assertNotIn("trim_in", out)
        self.assertEqual(out["gain"], 0.5)

    def test_edit_gain_keeps_play_fields(self):
        out = server.edit_audio(server.AudioEditRequest(clip_id=1, action="gain", gain=0.5))
        for k, v in EffectKeepsPlayFields.KEPT.items():
            self.assertEqual(out.get(k), v, k)


if __name__ == "__main__":
    unittest.main()
