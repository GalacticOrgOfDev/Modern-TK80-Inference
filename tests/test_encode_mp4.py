"""encode_mp4 writes an MP4 with ffmpeg, or raises ValueError without it.

Stdlib only. The encode tests need ffmpeg on PATH and are skipped
otherwise; the ffprobe checks also need ffprobe. The missing-ffmpeg test
patches shutil.which and runs everywhere.

export.py copies UPLOAD_DIR from video.py by value at import, so every
test patches export.UPLOAD_DIR itself with a temporary folder. TK80_VIDEO
and TK80_VFX also point at a temporary folder before the first import, in
case this module is the first to import app.backend.video, so the
repository's uploads/ is not touched.

encode_mp4 is not reachable from the app (no route calls it). These tests
pin only what was measured on the box; they say nothing about Windows.
"""

import atexit
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tk80_test_encode_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ.setdefault("TK80_VIDEO", os.path.join(_TMP, "video"))
os.environ.setdefault("TK80_VFX", os.path.join(_TMP, "vfx"))

from app.backend import export  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,pix_fmt", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)["streams"][0]


class EncodeMp4Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tk80_encode_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patcher = mock.patch.object(export, "UPLOAD_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)


class EncodeMp4NoFfmpegTest(EncodeMp4Base):
    def test_missing_ffmpeg_raises_value_error(self):
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError) as cm:
                export.encode_mp4([{"duration": 1.0}], out_name="x.mp4")
        self.assertIn("ffmpeg is required to encode MP4", str(cm.exception))
        run.assert_not_called()
        self.assertEqual(list(self.dir.iterdir()), [])


@unittest.skipUnless(FFMPEG, "ffmpeg is not on PATH")
class EncodeMp4FfmpegTest(EncodeMp4Base):
    def _check(self, result, name):
        path = Path(result["path"])
        self.assertEqual(path, self.dir / name)
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size, 0)
        self.assertIs(result["encoded"], True)
        return path

    def test_no_clip_files_writes_a_black_segment(self):
        result = export.encode_mp4([{"duration": 1.0}], out_name="black.mp4")
        path = self._check(result, "black.mp4")
        self.assertEqual(result["clips"], 1)
        if FFPROBE:
            self.assertEqual(_probe(path), {"codec_name": "h264", "pix_fmt": "yuv420p"})

    def test_existing_clip_file_is_concatenated(self):
        src = self.dir / "src.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc=duration=1:size=320x240:rate=25",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
            check=True, capture_output=True,
        )
        result = export.encode_mp4([{"path": str(src), "duration": 1.0}], out_name="concat")
        path = self._check(result, "concat.mp4")
        self.assertEqual(result["clips"], 1)
        if FFPROBE:
            self.assertEqual(_probe(path), {"codec_name": "h264", "pix_fmt": "yuv420p"})


if __name__ == "__main__":
    unittest.main()
