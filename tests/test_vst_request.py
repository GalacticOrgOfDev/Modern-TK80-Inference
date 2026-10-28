"""POST /api/audio/vst accepts the request body the page sends.

The handler reads ``body.prompt``; the request model must define it, or every
call fails with AttributeError before any source is written. Uses the same
fastapi/pydantic stand-ins as test_daw_ids and calls the endpoint function
directly. No HTTP request is made.
"""

import tempfile
import unittest
from pathlib import Path

from app.backend import vst
from tests.test_daw_ids import _import_server

server = _import_server()


class CreateVstRequest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tk80_vst_")
        self._saved_dir = vst.VST_DIR
        self._saved_lib = list(vst._LIBRARY)
        vst.VST_DIR = Path(self._tmp.name)

    def tearDown(self):
        vst.VST_DIR = self._saved_dir
        vst._LIBRARY[:] = self._saved_lib
        self._tmp.cleanup()

    def test_prompt_defaults_to_empty(self):
        body = server.VstRequest(name="Verb", plugin_type="effect", effect="reverb", channels=2)
        self.assertEqual(body.prompt, "")

    def test_page_body_without_prompt_writes_source(self):
        # Same fields the DAW page's "Make VST" button sends.
        body = server.VstRequest(name="Verb", plugin_type="effect", effect="reverb", channels=2)
        result = server.create_vst(body)
        self.assertEqual(result["effect"], "reverb")
        self.assertEqual(result["type"], "effect")
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, Path(self._tmp.name))

    def test_unknown_effect_falls_back_to_custom(self):
        body = server.VstRequest(name="Agent", plugin_type="instrument", effect="warm pad please")
        result = server.create_vst(body)
        self.assertEqual(result["effect"], "custom")


if __name__ == "__main__":
    unittest.main()
