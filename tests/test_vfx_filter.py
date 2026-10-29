"""render_vfx maps a prompt to an ffmpeg filter through _filter_for.

No ffmpeg runs here: shutil.which and subprocess.run are patched, and
VFX_DIR is a temporary folder. TK80_VIDEO and TK80_VFX point at that
folder before app.backend.video is imported, in case this module is the
first to import it, so the repository's uploads/ is not touched.

The expected filters are copied from the table in app/backend/video.py.
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="tk80_test_vfx_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ.setdefault("TK80_VIDEO", os.path.join(_TMP, "video"))
os.environ.setdefault("TK80_VFX", os.path.join(_TMP, "vfx"))

from app.backend import video  # noqa: E402

TABLE = {
    "tv static": "noise=alls=20:allf=t+u",
    "fire hand": "noise=alls=12:allf=t,eq=saturation=2:gamma_r=1.4",
    "lightning": "noise=alls=30:allf=t,eq=brightness=0.4:contrast=1.5",
    "slow fade": "fade=t=in:st=0:d=0.5,fade=t=out:st=1.5:d=0.5",
    "zoom in": "zoompan=z='min(zoom+0.002,1.5)':d=60:s=640x360",
    "glitch": "noise=alls=40:allf=t,eq=contrast=1.8",
}
UNKNOWN = "noise=alls=10:allf=t,eq=saturation=1.2"


class FilterForTest(unittest.TestCase):
    def test_known_keywords_return_the_table_filter(self):
        for prompt, filt in TABLE.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(video._filter_for(prompt), filt)

    def test_unknown_prompt_returns_the_table_fallback(self):
        self.assertEqual(video._filter_for("purple elephant"), UNKNOWN)


class RenderVfxTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tk80_vfx_render_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _render(self, name, prompt):
        with mock.patch.object(video, "VFX_DIR", self.dir), \
             mock.patch("shutil.which", return_value="/fake/ffmpeg"), \
             mock.patch("subprocess.run") as run:
            dest = video.render_vfx(name, 2.0, prompt=prompt)
        return dest, run

    def test_render_passes_the_table_filter_to_ffmpeg(self):
        dest, run = self._render("fire", "fire hand")
        self.assertEqual(run.call_count, 1)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertEqual(cmd[cmd.index("-vf") + 1], TABLE["fire hand"])
        self.assertEqual(cmd[-1], str(self.dir / "fire.mp4"))
        self.assertEqual(dest, self.dir / "fire.mp4")

    def test_render_unknown_prompt_uses_the_fallback(self):
        _, run = self._render("odd", "purple elephant")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-vf") + 1], UNKNOWN)

    def test_render_without_ffmpeg_raises_value_error(self):
        with mock.patch.object(video, "VFX_DIR", self.dir), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run") as run:
            with self.assertRaises(ValueError):
                video.render_vfx("fire", 2.0, prompt="fire")
        run.assert_not_called()


class DesignVfxUnchangedTest(unittest.TestCase):
    """design_vfx keeps its own table and fallback (video.py), unchanged."""

    def test_static_prompt(self):
        self.assertEqual(
            video.design_vfx("tv static"),
            {"prompt": "tv static", "filter": "noise=alls=20:allf=t+u",
             "layers": ["noise=alls=20:allf=t+u"]},
        )

    def test_unknown_prompt_uses_design_fallback(self):
        self.assertEqual(
            video.design_vfx("purple elephant")["layers"],
            ["noise=alls=10:allf=t,eq=saturation=1.3"],
        )


if __name__ == "__main__":
    unittest.main()
