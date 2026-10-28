"""A non-empty VST prompt is refused with 501, not a NameError.

Prompt design (design_from_prompt, effect_from_prompt, _safe_name) has never
existed in this repo, so a prompt cannot design a plugin. make_vst raises
NotImplementedError for a prompt, and the server answers 501 on both the
/api/audio/vst route and the make_vst chat tool. Requests without a prompt
keep working. Uses the same fastapi/pydantic stand-ins as test_daw_ids and
calls the functions directly. No HTTP request is made.
"""

import tempfile
import unittest
from pathlib import Path

from app.backend import vst
from tests.test_daw_ids import _import_server

server = _import_server()


class _TmpVstDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tk80_vst_")
        self._saved_dir = vst.VST_DIR
        self._saved_lib = list(vst._LIBRARY)
        vst.VST_DIR = Path(self._tmp.name)

    def tearDown(self):
        vst.VST_DIR = self._saved_dir
        vst._LIBRARY[:] = self._saved_lib
        self._tmp.cleanup()

    def _written(self):
        return sorted(p.name for p in Path(self._tmp.name).iterdir())


class MakeVstPrompt(_TmpVstDir):
    def test_prompt_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            vst.make_vst("Verb", "effect", "reverb", prompt="warm plate reverb")
        self.assertIn("prompt design", str(ctx.exception).lower())
        self.assertEqual(self._written(), [])
        self.assertEqual(len(vst._LIBRARY), len(self._saved_lib))

    def test_empty_prompt_still_writes_source(self):
        result = vst.make_vst("Verb", "effect", "reverb", prompt="")
        self.assertEqual(result["effect"], "reverb")
        self.assertTrue(Path(result["path"]).is_file())

    def test_absent_prompt_still_writes_source(self):
        result = vst.make_vst("Verb", "effect", "reverb")
        self.assertEqual(result["effect"], "reverb")
        self.assertTrue(Path(result["path"]).is_file())


class ServerVstPrompt(_TmpVstDir):
    def _status(self, fn, *args):
        try:
            fn(*args)
        except server.HTTPException as e:
            return e.status_code, e.detail
        return None, None

    def test_route_prompt_returns_501(self):
        body = server.VstRequest(name="Verb", plugin_type="effect", effect="reverb", prompt="warm plate reverb")
        status, detail = self._status(server.create_vst, body)
        self.assertEqual(status, 501)
        self.assertIn("prompt design", str(detail).lower())
        self.assertEqual(self._written(), [])

    def test_route_without_prompt_unchanged(self):
        body = server.VstRequest(name="Verb", plugin_type="effect", effect="reverb", channels=2)
        result = server.create_vst(body)
        self.assertEqual(result["effect"], "reverb")
        self.assertTrue(Path(result["path"]).is_file())

    def test_route_bad_plugin_type_still_400(self):
        body = server.VstRequest(name="Verb", plugin_type="nope", prompt="warm plate reverb")
        status, _ = self._status(server.create_vst, body)
        self.assertEqual(status, 400)

    def test_chat_tool_prompt_returns_501(self):
        args = {"name": "Verb", "effect": "reverb", "plugin_type": "effect", "prompt": "warm plate reverb"}
        status, detail = self._status(server._dispatch_tool, "make_vst", args)
        self.assertEqual(status, 501)
        self.assertIn("prompt design", str(detail).lower())
        self.assertEqual(self._written(), [])

    def test_chat_tool_without_prompt_unchanged(self):
        args = {"name": "GeneratedPlugin", "effect": "reverb", "plugin_type": "effect"}
        result = server._dispatch_tool("make_vst", args)
        self.assertEqual(result["effect"], "reverb")
        self.assertEqual(result["name"], "make_vst")


if __name__ == "__main__":
    unittest.main()
