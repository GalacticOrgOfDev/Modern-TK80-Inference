"""Tests for Modern-TK80.

Every audio write goes under TK80_UPLOADS, read once when app.backend.audio
is imported. `python -m unittest discover` imports the test modules before
any test runs, so the variable is set here, before any test module can
import the backend. It points at a fresh temporary folder, removed at exit,
so a test run never writes into the repository's uploads/audio. Tests that
need their own folder still patch TK80_UPLOADS or audio.UPLOAD_DIR.
"""

import atexit
import os
import shutil
import tempfile

_UPLOADS = tempfile.mkdtemp(prefix="tk80_test_uploads_")
atexit.register(shutil.rmtree, _UPLOADS, ignore_errors=True)
os.environ["TK80_UPLOADS"] = _UPLOADS
