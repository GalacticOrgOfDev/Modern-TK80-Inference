"""A make_vst prompt in chat comes back as a tool error, not a failed request.

When the model's reply holds a make_vst call with a prompt, the tool raises
501 (prompt design does not exist). /api/chat returns that message as the
tool result so the chat turn still answers. The make_vst tool description no
longer offers prompt design. A last block records what make_vst does with a
free-text effect, which is what the agent drawer in app.js sends. Uses the
same fastapi/pydantic stand-ins as test_daw_ids and calls the functions
directly. No HTTP request is made.
"""

import ast
import tempfile
import unittest
from pathlib import Path

from app.backend import tools, vst
from tests.test_daw_ids import _import_server

server = _import_server()

_PROMPT_CALL = 'tool: make_vst {"name": "Verb", "effect": "reverb", "prompt": "warm plate reverb"}'
_PLAIN_CALL = 'tool: make_vst {"name": "Verb", "effect": "reverb"}'


class _FakeIc:
    """Stands in for the Interconnector: one loaded llm die with a fixed reply."""

    def __init__(self, reply):
        self.reply = reply

    def loaded_dies(self):
        return [0]

    def modality_of(self, die):
        return "llm"

    def generate(self, request, die=None):
        return self.reply


class _ChatCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="tk80_vst_")
        self._saved_dir = vst.VST_DIR
        self._saved_lib = list(vst._LIBRARY)
        self._saved_ic = server._ic
        self._saved_chat = list(server._chat)
        vst.VST_DIR = Path(self._tmp.name)

    def tearDown(self):
        vst.VST_DIR = self._saved_dir
        vst._LIBRARY[:] = self._saved_lib
        server._ic = self._saved_ic
        server._chat[:] = self._saved_chat
        self._tmp.cleanup()

    def _chat(self, reply, user="hello there"):
        server._ic = _FakeIc(reply)
        body = server.ChatRequest(messages=[server.ChatMessage(role="user", content=user)])
        return server.chat(body)

    def _written(self):
        return sorted(p.name for p in Path(self._tmp.name).iterdir())


class ChatVstPrompt(_ChatCase):
    def test_prompt_call_does_not_fail_the_request(self):
        try:
            out = self._chat(_PROMPT_CALL)
        except server.HTTPException as e:
            self.fail(f"/api/chat failed the whole request: {e.status_code} {e.detail}")
        self.assertIn("prompt design", str(out["tool"]["error"]).lower())
        self.assertIn("Tool error:", out["result"])
        self.assertIn("prompt design", out["result"].lower())
        self.assertEqual(out["history"][-1]["content"], out["result"])
        self.assertEqual(self._written(), [])

    def test_plain_call_unchanged(self):
        out = self._chat(_PLAIN_CALL)
        self.assertEqual(out["tool"]["effect"], "reverb")
        self.assertEqual(out["tool"]["name"], "make_vst")
        self.assertEqual(len(self._written()), 1)

    def test_other_tool_errors_still_raise(self):
        with self.assertRaises(server.HTTPException) as ctx:
            self._chat('tool: set_bpm {"bpm": 999}')
        self.assertEqual(ctx.exception.status_code, 400)


class MakeVstDescription(unittest.TestCase):
    def test_description_says_prompt_design_unavailable(self):
        spec = tools.TOOLS["make_vst"]
        text = spec["description"].lower()
        self.assertNotIn("free-form", text)
        self.assertIn("prompt design", text)
        self.assertIn("unavailable", text)
        self.assertNotIn("prompt", spec["args"])

    def test_advertised_args_match_real_options(self):
        args = tools.TOOLS["make_vst"]["args"]
        self.assertEqual(set(args["plugin_type"].split("|")), set(vst.PLUGIN_TYPES))
        self.assertEqual(set(args["effect"].split("|")), set(vst.EFFECT_PRESETS))


class AgentDrawerFreeTextEffect(_ChatCase):
    """Records current behaviour only. Nothing here is a fix.

    The agent drawer in app.js posts {name: "AgentInstrument", effect: <free
    text>, plugin_type: "instrument"} with no prompt to /api/vst/make.
    """

    def test_no_api_vst_make_route_exists(self):
        src = Path(server.__file__).read_text(encoding="utf-8")
        paths = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                        paths.add(dec.args[0].value)
        self.assertIn("/api/audio/vst", paths)
        self.assertNotIn("/api/vst/make", paths)

    def test_free_text_effect_falls_back_to_custom(self):
        result = vst.make_vst("AgentInstrument", "instrument", "warm reverb with long tail")
        self.assertEqual(result["effect"], "custom")
        self.assertEqual(result["type"], "instrument")
        self.assertEqual(result["params"], {"gain": 1.0})

    def test_route_free_text_effect_falls_back_to_custom(self):
        body = server.VstRequest(name="AgentInstrument", plugin_type="instrument", effect="warm reverb with long tail")
        result = server.create_vst(body)
        self.assertEqual(result["effect"], "custom")
        self.assertEqual(result["type"], "instrument")


if __name__ == "__main__":
    unittest.main()
