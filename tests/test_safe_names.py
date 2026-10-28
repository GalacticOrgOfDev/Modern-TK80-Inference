"""Bounce, upload, generated renders and VST output never overwrite a file,
never write outside their root, and the uploads root is one absolute path.

Uses the fastapi/pydantic stand-ins from tests.test_daw_ids; endpoint
functions are called directly, no HTTP. Every write goes to a temporary
directory patched in as audio.UPLOAD_DIR (or vst.VST_DIR).
"""

import asyncio
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio, effects, vst  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RATE = 44100

TRAVERSAL_NAMES = (
    "../../evil.wav",
    "..\\..\\evil.wav",
    "/etc/evil.wav",
    "C:\\Windows\\evil.wav",
    "C:evil.wav",
    "sub/dir/evil.wav",
)


class _Upload:
    def __init__(self, name, data):
        self.filename = name
        self._data = data

    async def read(self):
        return self._data


def _write_tone(path: Path, frames: int = 400) -> None:
    pcm = b"".join(struct.pack("<hh", (i % 50) * 100, -(i % 50) * 100) for i in range(frames))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


class _RootCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tk80_s5_")
        self.root = Path(self.tmp.name) / "audio"
        self.root.mkdir()
        self.outside = Path(self.tmp.name)
        self._saved = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.root
        server._audio_tracks = [audio.make_track(i, f"Audio {i + 1}") for i in range(2)]
        server._audio_clips = []
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        audio.UPLOAD_DIR = self._saved
        self.tmp.cleanup()

    def assertInsideRoot(self, path, root=None):
        root = Path(root or self.root).resolve()
        p = Path(path)
        self.assertEqual(p.resolve().parent, root, f"{p} is not directly in {root}")
        self.assertNotIn("\\", p.name)
        self.assertNotIn("/", p.name)
        self.assertNotIn(p.name, ("", ".", ".."))
        self.assertTrue(p.is_file(), f"{p} was not written")

    def assertNothingOutside(self):
        stray = sorted(p.name for p in self.outside.iterdir() if p != self.root)
        self.assertEqual(stray, [], "a file was written outside the uploads root")

    def _add_source_clip(self):
        src = self.root / "src.wav"
        _write_tone(src)
        clip = audio.make_clip(server._clip_ids.next_id(), "src.wav", src, track_id=0, sample_rate=RATE)
        server._audio_clips.append(clip)
        return clip


class UploadsRoot(unittest.TestCase):
    def _root_from(self, env_extra, module="audio", attr="UPLOAD_DIR"):
        env = {k: v for k, v in os.environ.items() if k not in ("TK80_UPLOADS", "TK80_VST")}
        env.update(env_extra)
        env["PYTHONPATH"] = str(REPO)
        with tempfile.TemporaryDirectory() as cwd:
            out = subprocess.run(
                [sys.executable, "-c",
                 f"from app.backend import {module}; print({module}.{attr})"],
                cwd=cwd, env=env, capture_output=True, text=True, check=True,
            ).stdout.strip()
            leaked = sorted(p.name for p in Path(cwd).iterdir())
        return Path(out), leaked

    def test_default_uploads_root_is_absolute_and_anchored_to_the_repo(self):
        root, leaked = self._root_from({})
        self.assertTrue(root.is_absolute(), root)
        self.assertEqual(root, (REPO / "uploads" / "audio").resolve())
        self.assertEqual(leaked, [], "importing audio created folders in the working directory")

    def test_env_absolute_root_is_used_as_is(self):
        with tempfile.TemporaryDirectory() as d:
            root, _ = self._root_from({"TK80_UPLOADS": d})
            self.assertEqual(root, Path(d).resolve())

    def test_default_vst_root_is_absolute_and_anchored_to_the_repo(self):
        root, leaked = self._root_from({}, module="vst", attr="VST_DIR")
        self.assertTrue(root.is_absolute(), root)
        self.assertEqual(root, (REPO / "uploads" / "vst").resolve())
        self.assertEqual(leaked, [])


class Bounce(_RootCase):
    def _bounce(self, name):
        return server.bounce_audio(server.BounceRequest(name=name))

    def test_first_time_name_is_unchanged(self):
        self._add_source_clip()
        self.assertEqual(self._bounce("song.wav")["name"], "song.wav")
        self.assertEqual(self._bounce("take")["name"], "take.wav")

    def test_bounce_never_overwrites_an_existing_file(self):
        self._add_source_clip()
        (self.root / "mix.wav").write_bytes(b"KEEP")
        names = [self._bounce("mix.wav")["name"] for _ in range(3)]
        self.assertEqual(len(set(names)), 3, names)
        self.assertNotIn("mix.wav", names)
        self.assertEqual((self.root / "mix.wav").read_bytes(), b"KEEP")
        for n in names:
            self.assertInsideRoot(self.root / n)

    def test_empty_bounce_never_overwrites(self):
        (self.root / "mix.wav").write_bytes(b"KEEP")
        clip = self._bounce("mix.wav")
        self.assertNotEqual(clip["name"], "mix.wav")
        self.assertEqual((self.root / "mix.wav").read_bytes(), b"KEEP")

    def test_returned_name_matches_the_file_written(self):
        self._add_source_clip()
        self._bounce("mix.wav")
        clip = self._bounce("mix.wav")
        self.assertEqual(Path(clip["path"]).name, clip["name"])
        self.assertTrue(Path(clip["path"]).is_file())

    def test_mix_endpoint_never_overwrites(self):
        self._add_source_clip()
        a = server.mix_audio()
        b = server.mix_audio()
        self.assertNotEqual(a["path"], b["path"])
        self.assertTrue(Path(a["path"]).is_file() and Path(b["path"]).is_file())

    def test_traversal_names_stay_in_the_root(self):
        self._add_source_clip()
        for name in TRAVERSAL_NAMES + ("..", ".", ""):
            with self.subTest(name=name):
                clip = self._bounce(name)
                self.assertInsideRoot(clip["path"])
                self.assertTrue(clip["name"].endswith(".wav"))
        self.assertNothingOutside()


class Upload(_RootCase):
    def _upload(self, name, data=b"RIFF"):
        return asyncio.run(server.upload_audio(file=_Upload(name, data), track_id=0))

    def test_first_time_name_is_unchanged(self):
        self.assertEqual(self._upload("vocal take.wav")["name"], "vocal take.wav")

    def test_upload_never_overwrites(self):
        a = self._upload("v.wav", b"ONE")
        b = self._upload("v.wav", b"TWO")
        self.assertNotEqual(a["name"], b["name"])
        self.assertEqual(Path(a["path"]).read_bytes(), b"ONE")
        self.assertEqual(Path(b["path"]).read_bytes(), b"TWO")
        self.assertEqual(Path(b["path"]).name, b["name"])

    def test_traversal_names_stay_in_the_root(self):
        for name in TRAVERSAL_NAMES + ("..", ".", ""):
            with self.subTest(name=name):
                clip = self._upload(name)
                self.assertInsideRoot(clip["path"])
                self.assertEqual(Path(clip["path"]).name, clip["name"])
        self.assertNothingOutside()


class GeneratedRenders(_RootCase):
    def test_renders_land_in_the_patched_uploads_root(self):
        for tool, args in (
            ("generate_instrument", {"instrument": "kick", "duration": 0.05}),
            ("generate_loop", {"style": "basic", "bars": 1}),
            ("render_pattern", {"bars": 1}),
        ):
            with self.subTest(tool=tool):
                clip = server._dispatch_tool(tool, args)["clip"]
                self.assertInsideRoot(clip["path"])

    def test_first_time_render_names_are_unchanged(self):
        clip = server._dispatch_tool("generate_instrument", {"instrument": "kick", "duration": 0.05})["clip"]
        self.assertEqual(clip["name"], f"kick_{clip['id']}.wav")

    def test_render_never_overwrites(self):
        # After a server restart clip ids start again, so kick_<id>.wav may exist.
        next_id = server._clip_ids.peek()
        for n in range(next_id, next_id + 3):
            (self.root / f"kick_{n}.wav").write_bytes(b"KEEP")
            (self.root / f"pattern_{n}.wav").write_bytes(b"KEEP")
        a = server._dispatch_tool("generate_instrument", {"instrument": "kick", "duration": 0.05})["clip"]
        b = server._dispatch_tool("render_pattern", {"bars": 1})["clip"]
        for n in range(next_id, next_id + 3):
            self.assertEqual((self.root / f"kick_{n}.wav").read_bytes(), b"KEEP")
            self.assertEqual((self.root / f"pattern_{n}.wav").read_bytes(), b"KEEP")
        for c in (a, b):
            self.assertEqual(Path(c["path"]).name, c["name"])
            self.assertInsideRoot(c["path"])

    def test_loop_style_cannot_escape_the_root(self):
        for style in ("../../evil", "..\\..\\evil", "/etc/evil"):
            with self.subTest(style=style):
                clip = server._dispatch_tool("generate_loop", {"style": style, "bars": 1})["clip"]
                self.assertInsideRoot(clip["path"])
        self.assertNothingOutside()


class EditsAndEffects(_RootCase):
    def test_clip_edit_never_overwrites(self):
        clip = self._add_source_clip()
        frames = 400
        for name in ("src_gain.wav", f"src_gain_{frames}.wav"):
            (self.root / name).write_bytes(b"KEEP")
        server.edit_audio(server.AudioEditRequest(clip_id=clip["id"], action="gain", gain=0.5))
        for name in ("src_gain.wav", f"src_gain_{frames}.wav"):
            self.assertEqual((self.root / name).read_bytes(), b"KEEP")
        self.assertInsideRoot(clip["path"])

    def test_effect_never_overwrites(self):
        src = self.root / "src.wav"
        _write_tone(src)
        for name in ("src_normalize.wav", "src_normalize_800.wav"):
            (self.root / name).write_bytes(b"KEEP")
        saved = effects.UPLOAD_DIR
        effects.UPLOAD_DIR = self.root
        try:
            dest = effects.apply_effect(src, "normalize", {})
        finally:
            effects.UPLOAD_DIR = saved
        for name in ("src_normalize.wav", "src_normalize_800.wav"):
            self.assertEqual((self.root / name).read_bytes(), b"KEEP")
        self.assertInsideRoot(dest)


class VstOutput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tk80_vst_")
        self._saved = vst.VST_DIR
        self._lib = list(vst._LIBRARY)
        vst.VST_DIR = Path(self.tmp.name)

    def tearDown(self):
        vst.VST_DIR = self._saved
        vst._LIBRARY[:] = self._lib
        self.tmp.cleanup()

    def test_first_time_name_is_unchanged(self):
        r = vst.make_vst("Warm Verb", "effect", "reverb")
        self.assertEqual(Path(r["path"]).name, "Warm_Verb.cpp")
        self.assertEqual(r["name"], "Warm_Verb")
        self.assertEqual(r["file_name"], "Warm_Verb.cpp")

    def test_never_overwrites_and_reports_the_real_file(self):
        (Path(self.tmp.name) / "Verb.cpp").write_text("KEEP")
        r = vst.make_vst("Verb", "effect", "reverb")
        self.assertEqual((Path(self.tmp.name) / "Verb.cpp").read_text(), "KEEP")
        self.assertNotEqual(Path(r["path"]).name, "Verb.cpp")
        self.assertEqual(r["file_name"], Path(r["path"]).name)
        self.assertTrue(Path(r["path"]).is_file())

    def test_traversal_names_stay_in_the_root(self):
        for name in TRAVERSAL_NAMES + ("..", ""):
            with self.subTest(name=name):
                r = vst.make_vst(name, "effect", "reverb")
                self.assertEqual(Path(r["path"]).resolve().parent, Path(self.tmp.name).resolve())


if __name__ == "__main__":
    unittest.main()
