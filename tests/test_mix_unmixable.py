"""A clip the mixdown cannot use is an error, never a silent drop.

Before this, mix_arrangement skipped a clip whose file was missing or
unreadable, was not 16-bit, or did not match the project sample rate, and
/api/audio/mix and /api/audio/bounce returned a silent (or empty) mix as
if nothing had gone wrong. Now mix_arrangement raises UnmixableClipError
(a ValueError) naming every such clip and why, before it writes a file,
and both endpoints turn that into a 400 whose detail the front end shows.
Mono and stereo 16-bit clips at the project rate mix exactly as before.
Uses the fastapi/pydantic stand-ins from tests.test_daw_ids; endpoint
functions are called directly, no HTTP.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

RATE = 1000
FRAMES = 100


def _write(path: Path, channels=2, width=2, rate=RATE, value=1000) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            frame = b"".join(struct.pack("<h", value + c) for c in range(channels))
        else:
            frame = b"\x40" * (width * channels)
        w.writeframes(frame * FRAMES)
    return path


def _read(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        return w.getnchannels(), [struct.unpack_from("<h", raw, i)[0] for i in range(0, len(raw), 2)]


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"
        self.out.mkdir()
        self._old_dir = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.out
        self.tracks = [audio.make_track(0, "T1")]

    def tearDown(self):
        audio.UPLOAD_DIR = self._old_dir
        self.tmp.cleanup()

    def clip(self, cid, path, **extra):
        c = audio.make_clip(cid, path.name, path if path.exists() else None, track_id=0, sample_rate=RATE)
        if not path.exists():
            c["path"] = str(path)
            c["duration"] = FRAMES / RATE
        c.update(extra)
        return c

    def bad_clip(self, kind, cid=7):
        if kind == "missing":
            return self.clip(cid, self.dir / "gone.wav")
        if kind == "unreadable":
            p = self.dir / "junk.wav"
            p.write_bytes(b"this is not a wav file")
            return self.clip(cid, p)
        if kind == "8bit":
            return self.clip(cid, _write(self.dir / "b8.wav", width=1))
        if kind == "24bit":
            return self.clip(cid, _write(self.dir / "b24.wav", width=3))
        if kind == "rate":
            return self.clip(cid, _write(self.dir / "r2k.wav", rate=2 * RATE))
        raise AssertionError(kind)


class MixArrangementRaises(_Base):
    REASONS = {
        "missing": "missing",
        "unreadable": "unreadable",
        "8bit": "8-bit",
        "24bit": "24-bit",
        "rate": "2000 Hz",
    }

    def test_each_unmixable_clip_raises_naming_clip_and_reason(self):
        for kind, reason in self.REASONS.items():
            with self.subTest(kind=kind):
                clip = self.bad_clip(kind)
                with self.assertRaises(audio.UnmixableClipError) as cm:
                    audio.mix_arrangement([clip], self.tracks, RATE, "mix.wav")
                err = cm.exception
                self.assertIsInstance(err, ValueError)
                self.assertEqual([p["clip_id"] for p in err.problems], [7])
                self.assertEqual(err.problems[0]["name"], clip["name"])
                self.assertIn(reason, err.problems[0]["reason"])
                self.assertIn("#7", str(err))
                self.assertIn(clip["name"], str(err))
                self.assertIn(reason, str(err))

    def test_nothing_written_when_a_clip_is_unmixable(self):
        good = self.clip(1, _write(self.dir / "ok.wav"))
        with self.assertRaises(audio.UnmixableClipError):
            audio.mix_arrangement([good, self.bad_clip("24bit")], self.tracks, RATE, "mix.wav")
        self.assertEqual(list(self.out.iterdir()), [])

    def test_every_bad_clip_is_listed(self):
        clips = [self.bad_clip("missing", 3), self.bad_clip("rate", 4), self.clip(5, _write(self.dir / "ok.wav"))]
        with self.assertRaises(audio.UnmixableClipError) as cm:
            audio.mix_arrangement(clips, self.tracks, RATE, "mix.wav")
        self.assertEqual([p["clip_id"] for p in cm.exception.problems], [3, 4])

    def test_skipped_clips_are_not_checked(self):
        """Muted, silenced, muted-track and non-solo clips are not played, so not an error."""
        tracks = [audio.make_track(0, "T1"), audio.make_track(1, "T2")]
        ok = self.clip(1, _write(self.dir / "ok.wav"))
        muted = self.bad_clip("missing", 2)
        muted["mute"] = True
        silenced = self.bad_clip("24bit", 3)
        silenced["silenced"] = True
        audio.mix_arrangement([ok, muted, silenced], tracks, RATE, "a.wav")
        tracks[1]["mute"] = True
        on_muted_track = self.bad_clip("rate", 4)
        on_muted_track["track_id"] = 1
        audio.mix_arrangement([ok, on_muted_track], tracks, RATE, "b.wav")
        tracks[1]["mute"] = False
        tracks[0]["solo"] = True
        audio.mix_arrangement([ok, on_muted_track], tracks, RATE, "c.wav")

    def test_master_mute_is_still_silent_not_an_error(self):
        master = audio.default_master()
        master["mute"] = True
        path = audio.mix_arrangement([self.bad_clip("missing")], self.tracks, RATE, "m.wav", master)
        self.assertEqual(_read(path), (2, []))


class NormalClipsUnchanged(_Base):
    def test_stereo_16bit_mixes_sample_exact(self):
        clip = self.clip(1, _write(self.dir / "st.wav", channels=2, value=1000))
        ch, samples = _read(audio.mix_arrangement([clip], self.tracks, RATE, "mix.wav"))
        self.assertEqual(ch, 2)
        self.assertEqual(len(samples), 2 * (FRAMES + 1))
        for i in range(FRAMES):
            self.assertLessEqual(abs(samples[2 * i] - 1000), 1)
            self.assertLessEqual(abs(samples[2 * i + 1] - 1001), 1)
        self.assertEqual(samples[-2:], [0, 0])

    def test_mono_16bit_goes_to_both_sides(self):
        clip = self.clip(1, _write(self.dir / "mono.wav", channels=1, value=2000))
        ch, samples = _read(audio.mix_arrangement([clip], self.tracks, RATE, "mix.wav"))
        self.assertEqual(ch, 2)
        for i in range(FRAMES):
            self.assertLessEqual(abs(samples[2 * i] - 2000), 1)
            self.assertLessEqual(abs(samples[2 * i + 1] - 2000), 1)


class EndpointsReport400(_Base):
    _SAVED = ("_audio_tracks", "_audio_clips", "_sample_rate", "_master", "_track_ids", "_clip_ids")

    def setUp(self):
        super().setUp()
        self._saved = {k: getattr(server, k) for k in self._SAVED}
        server._audio_tracks = [audio.make_track(0, "T1")]
        server._sample_rate = RATE
        server._master = audio.default_master()
        server._undo_stack.clear()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(server, k, v)
        super().tearDown()

    def _set_clips(self, clips):
        server._audio_clips = clips
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def _calls(self):
        return {
            "mix": server.mix_audio,
            "bounce": lambda: server.bounce_audio(server.BounceRequest(name="b.wav")),
        }

    def test_mix_and_bounce_400_name_the_clip(self):
        for ep, call in self._calls().items():
            for kind, reason in MixArrangementRaises.REASONS.items():
                with self.subTest(ep=ep, kind=kind):
                    bad = self.bad_clip(kind)
                    self._set_clips([bad])
                    with self.assertRaises(Exception) as cm:
                        call()
                    self.assertEqual(getattr(cm.exception, "status_code", None), 400)
                    detail = str(getattr(cm.exception, "detail", ""))
                    self.assertIn("#7", detail)
                    self.assertIn(bad["name"], detail)
                    self.assertIn(reason, detail)
                    self.assertEqual(server._audio_clips, [bad])
                    self.assertEqual(list(self.out.iterdir()), [])

    def test_good_mix_response_fields_unchanged(self):
        for ep, call in self._calls().items():
            with self.subTest(ep=ep):
                good = self.clip(1, _write(self.dir / f"ok_{ep}.wav"))
                self._set_clips([good])
                result = call()
                self.assertEqual(set(result), set(audio.make_clip(0, "x")) | {"mix"})
                self.assertTrue(result["mix"])
                self.assertIsNone(result["track_id"])
                self.assertEqual(len(server._audio_clips), 2)


if __name__ == "__main__":
    unittest.main()
