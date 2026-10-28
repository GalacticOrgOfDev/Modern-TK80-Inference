"""Running the tests never writes into the repository's uploads/audio.

`python -m unittest discover` imports every test module before any test
runs, and the first one alphabetically imports the backend before
test_daw_ids sets TK80_UPLOADS. The tests package itself points
TK80_UPLOADS at a temporary folder, so whatever imports the backend first,
audio.UPLOAD_DIR is a temporary folder.

The discover check runs in a fresh interpreter with TK80_UPLOADS removed
from its environment, so the modules already imported here do not affect
it. It loads the suite the way discover does, then calls the mix and bounce
endpoint functions and checks that nothing new appears under
<repo>/uploads/audio. Anything the probe does create there is deleted again
before the check fails, so a failing run leaves the repository as it was.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPO_AUDIO = (REPO / "uploads" / "audio").resolve()
TEMP = Path(tempfile.gettempdir()).resolve()

_PROBE = r"""
import json, os, sys, unittest
from pathlib import Path
repo = Path(sys.argv[1])
repo_audio = repo / "uploads" / "audio"
sys.path.insert(0, str(repo))
before = set(os.listdir(repo_audio)) if repo_audio.exists() else set()
unittest.TestLoader().discover(str(repo / "tests"), top_level_dir=str(repo))
from app.backend import audio, paths
from tests.test_daw_ids import server
root = paths.resolve_root("TK80_UPLOADS", "uploads/audio")
mix = server.mix_audio()
bounce = server.bounce_audio(server.BounceRequest(name="tk80_isolation_probe.wav"))
after = set(os.listdir(repo_audio)) if repo_audio.exists() else set()
new = sorted(after - before)
for name in new:
    (repo_audio / name).unlink()
print(json.dumps({
    "upload_dir": str(audio.UPLOAD_DIR.resolve()),
    "paths_root": str(root),
    "env": os.environ.get("TK80_UPLOADS"),
    "new_in_repo": new,
}))
"""


def _run_probe():
    env = {k: v for k, v in os.environ.items() if k != "TK80_UPLOADS"}
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO)],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(f"probe failed:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


class UploadsIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = _run_probe()

    def test_discover_order_upload_dir_is_temporary(self):
        p = self.probe
        self.assertFalse(_inside(p["upload_dir"], REPO_AUDIO), p)
        self.assertTrue(_inside(p["upload_dir"], TEMP), p)

    def test_discover_order_paths_root_is_temporary(self):
        p = self.probe
        self.assertEqual(p["paths_root"], p["upload_dir"], p)
        self.assertFalse(_inside(p["paths_root"], REPO_AUDIO), p)

    def test_mix_and_bounce_write_nothing_into_repo(self):
        self.assertEqual(self.probe["new_in_repo"], [], self.probe)

    def test_this_process_upload_dir_is_not_the_repo(self):
        from app.backend import audio

        self.assertFalse(_inside(audio.UPLOAD_DIR, REPO_AUDIO), audio.UPLOAD_DIR)


if __name__ == "__main__":
    unittest.main()
