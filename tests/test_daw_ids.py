"""Track and clip ids are stable, lookups go by id, and tracks carry a type.

The pure rules live in app.backend.daw_state (stdlib only). The server-level
tests import app.backend.server with tiny stand-ins for fastapi and pydantic
when those are not installed, and call the endpoint functions directly. No
HTTP request is made.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

os.environ.setdefault("TK80_UPLOADS", tempfile.mkdtemp(prefix="tk80_uploads_"))

from app.backend import audio, daw_state  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402


def _stub_modules():
    """Minimal fastapi/pydantic stand-ins, enough to import server.py."""
    fa = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FastAPI:
        def __init__(self, *a, **k):
            pass

        def add_middleware(self, *a, **k):
            pass

        def _route(self, *a, **k):
            return lambda f: f

        get = post = put = patch = delete = _route

    fa.FastAPI = FastAPI
    fa.HTTPException = HTTPException
    fa.File = fa.Form = lambda *a, **k: None
    fa.UploadFile = object
    mw = types.ModuleType("fastapi.middleware")
    cors = types.ModuleType("fastapi.middleware.cors")
    cors.CORSMiddleware = object
    resp = types.ModuleType("fastapi.responses")
    resp.FileResponse = object

    pd = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kw):
            for k in type(self).__annotations__:
                setattr(self, k, kw.get(k, getattr(type(self), k, None)))

        def model_dump(self, exclude_none=False):
            d = {k: getattr(self, k) for k in type(self).__annotations__}
            return {k: v for k, v in d.items() if not (exclude_none and v is None)}

    pd.BaseModel = BaseModel
    return {
        "fastapi": fa,
        "fastapi.middleware": mw,
        "fastapi.middleware.cors": cors,
        "fastapi.responses": resp,
        "pydantic": pd,
    }


def _import_server():
    try:
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        from app.backend import server
        return server
    except ImportError:
        pass
    stubs = _stub_modules()
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        from app.backend import server
        return server
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


server = _import_server()


# ---------------------------------------------------------------- pure rules


class IdCounterRules(unittest.TestCase):
    def test_after_starts_above_highest_id(self):
        c = IdCounter.after([{"id": 0}, {"id": 7}, {"id": 3}])
        self.assertEqual(c.next_id(), 8)

    def test_after_empty_starts_at_zero(self):
        self.assertEqual(IdCounter.after([]).next_id(), 0)

    def test_never_reuses_and_never_goes_back(self):
        c = IdCounter.after([{"id": 5}])
        seen = {c.next_id() for _ in range(50)}
        self.assertEqual(len(seen), 50)
        c.observe([{"id": 1}])  # lower id must not move it back
        self.assertNotIn(c.next_id(), seen)


class LookupRules(unittest.TestCase):
    def test_find_by_id_not_position(self):
        items = [{"id": 4}, {"id": 9}]
        self.assertIs(daw_state.find_by_id(items, 9), items[1])
        self.assertIsNone(daw_state.find_by_id(items, 1))

    def test_remove_track_in_place_keeps_other_ids(self):
        tracks = [{"id": 0}, {"id": 1}, {"id": 2}]
        clips = [{"id": 0, "track_id": 0}, {"id": 1, "track_id": 1}, {"id": 2, "track_id": 2}]
        tref, cref = tracks, clips
        self.assertTrue(daw_state.remove_track(tracks, clips, 1))
        self.assertIs(tracks, tref)
        self.assertIs(clips, cref)
        self.assertEqual([t["id"] for t in tracks], [0, 2])
        self.assertEqual([c["id"] for c in clips], [0, 2])
        self.assertFalse(daw_state.remove_track(tracks, clips, 1))

    def test_restore_drops_snapshot_for_deleted_track(self):
        clips = []
        self.assertEqual(
            daw_state.restore_clip_snapshot(clips, [{"id": 0}], {"id": 3, "track_id": 5}),
            "dropped",
        )
        self.assertEqual(clips, [])

    def test_restore_replaces_and_appends(self):
        tracks = [{"id": 0}]
        clips = [{"id": 2, "track_id": 0, "gain": 2.0}]
        self.assertEqual(
            daw_state.restore_clip_snapshot(clips, tracks, {"id": 2, "track_id": 0, "gain": 1.0}),
            "replaced",
        )
        self.assertEqual(clips[0]["gain"], 1.0)
        self.assertEqual(
            daw_state.restore_clip_snapshot(clips, tracks, {"id": 9, "track_id": None}),
            "appended",
        )

    def test_track_type_check(self):
        self.assertEqual(daw_state.TRACK_TYPES, ("audio", "instrument"))
        self.assertEqual(daw_state.DEFAULT_TRACK_TYPE, "audio")
        self.assertEqual(daw_state.check_track_type("instrument"), "instrument")
        with self.assertRaises(ValueError):
            daw_state.check_track_type("midi")
        self.assertEqual(audio.make_track(0, "T")["type"], "audio")
        self.assertEqual(audio.make_track(0, "T", track_type="instrument")["type"], "instrument")
        self.assertEqual(audio.make_track(0, "T", track_type="bogus")["type"], "audio")


# ---------------------------------------------------------- server endpoints


class ServerIds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "c.wav"
        self.file.write_bytes(b"")
        server._audio_tracks = [audio.make_track(i, f"Audio {i + 1}") for i in range(4)]
        server._audio_clips = []
        server._undo_stack.clear()
        server._track_ids = IdCounter.after(server._audio_tracks)
        server._clip_ids = IdCounter.after(server._audio_clips)

    def tearDown(self):
        self.tmp.cleanup()

    def _clip(self, track_id, name):
        return server.add_clip(name=name, path=str(self.file), track_id=track_id)

    def _status(self, fn, *args, **kwargs):
        with self.assertRaises(Exception) as cm:
            fn(*args, **kwargs)
        return getattr(cm.exception, "status_code", None)

    def test_new_track_after_delete_gets_fresh_id(self):
        server.delete_track(1)
        t = server.create_track(name="New")
        ids = [x["id"] for x in server._audio_tracks]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(t["id"], 4)

    def test_track_ids_never_reused(self):
        made = {server.create_track(name="A")["id"]}
        for _ in range(5):
            last = server.create_track(name="B")
            server.delete_track(last["id"])
            self.assertNotIn(last["id"], made)
            made.add(last["id"])

    def test_clip_ids_never_reused_after_track_delete(self):
        self._clip(0, "a")
        self._clip(1, "b")
        server.delete_track(0)
        c = self._clip(1, "c")
        ids = [x["id"] for x in server._audio_clips]
        self.assertEqual(len(ids), len(set(ids)), ids)
        self.assertEqual(c["id"], 2)

    def test_clip_edit_after_track_delete_hits_right_clip(self):
        self._clip(0, "a")
        b = self._clip(1, "b")
        c = self._clip(2, "c")
        server.delete_track(0)
        server.clip_gain(server.ClipGainRequest(clip_id=c["id"], gain=2.0))
        by_name = {x["name"]: x for x in server._audio_clips}
        self.assertEqual(by_name["c"]["gain"], 2.0)
        self.assertEqual(by_name["b"]["gain"], 1.0)
        server.clip_mute(server.ClipMuteRequest(clip_id=b["id"], mute=True))
        self.assertTrue(by_name["b"]["mute"])
        self.assertFalse(by_name["c"]["mute"])

    def test_split_after_track_delete_gets_fresh_id(self):
        self._clip(0, "a")
        b = server.add_clip(name="b", duration=2.0, track_id=1)
        server.delete_track(0)
        server.clip_split(server.ClipSplitRequest(clip_id=b["id"], at=1.0))
        ids = [x["id"] for x in server._audio_clips]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_unknown_ids_give_404(self):
        self._clip(0, "a")
        self.assertEqual(self._status(server.clip_gain, server.ClipGainRequest(clip_id=99, gain=1.0)), 404)
        self.assertEqual(self._status(server.update_track, 99, server.TrackUpdate(name="x")), 404)
        self.assertEqual(self._status(server.delete_track, 99), 404)

    def test_undo_does_not_resurrect_clip_on_deleted_track(self):
        a = self._clip(1, "a")
        server.edit_audio(server.AudioEditRequest(clip_id=a["id"], action="position", position=3.0))
        server.delete_track(1)
        result = server._dispatch_tool("undo", {"track_id": 0})
        self.assertEqual(server._audio_clips, [])
        self.assertEqual(result.get("restored"), "dropped")

    def test_undo_still_restores_live_clip(self):
        a = self._clip(1, "a")
        server.edit_audio(server.AudioEditRequest(clip_id=a["id"], action="position", position=3.0))
        server._dispatch_tool("undo", {"track_id": 0})
        live = [c for c in server._audio_clips if c["id"] == a["id"]]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["position"], 0.0)

    def test_track_type_default_update_and_validation(self):
        for t in server.list_tracks()["tracks"]:
            self.assertEqual(t["type"], "audio")
        self.assertEqual(server.create_track(name="I", type="instrument")["type"], "instrument")
        self.assertEqual(self._status(server.create_track, name="X", type="midi"), 400)
        updated = server.update_track(0, server.TrackUpdate(type="instrument"))
        self.assertEqual(updated["type"], "instrument")
        self.assertEqual(self._status(server.update_track, 0, server.TrackUpdate(type="midi")), 400)
        self.assertEqual(daw_state.find_by_id(server._audio_tracks, 0)["type"], "instrument")


if __name__ == "__main__":
    unittest.main()
