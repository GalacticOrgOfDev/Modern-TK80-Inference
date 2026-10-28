"""scripts/scarlett_check.py runs without hardware against a fake library.

The fake stands in for sounddevice: query_hostapis/query_devices, raw
input/output/duplex streams that call the callback synchronously on
start(), CallbackStop and get_portaudio_version. It records what was
opened so the rate x buffer matrix can be checked, and can refuse given
(rate, buffer) pairs with an exception whose text must reach the report.
"""

import contextlib
import importlib.util
import io
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "scarlett_check.py"
_spec = importlib.util.spec_from_file_location("scarlett_check", _PATH)
sc = importlib.util.module_from_spec(_spec)
sys.modules["scarlett_check"] = sc
_spec.loader.exec_module(sc)


class _CallbackStop(Exception):
    pass


class FakeSD:
    __version__ = "fake-1.0"
    CallbackStop = _CallbackStop

    def __init__(self, hosts=None, devices=None, refuse=(), loop=None, input_value=0.25):
        self.hosts = hosts or [{"name": "MME", "devices": [0, 1]}, {"name": "ASIO", "devices": [2]}]
        self.devices = devices or [
            {"name": "Microsoft Sound Mapper", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 44100.0},
            {"name": "Focusrite USB (MME)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
            {"name": "Focusrite USB ASIO", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
        ]
        self.refuse = set(refuse)  # {(rate, buffer)}
        self.loop = loop  # None or (out_ch_index, in_ch_index): copy output col to input col
        self.input_value = input_value
        self.opened = []
        sd = self

        class _Stream:
            def __init__(self, kind, device=None, channels=None, samplerate=None, blocksize=None, dtype=None, callback=None):
                if (samplerate, blocksize) in sd.refuse:
                    raise RuntimeError(f"Error opening {kind}: Invalid sample rate [PaErrorCode -9997]")
                self.kind, self.channels, self.samplerate = kind, channels, samplerate
                self.blocksize, self.dtype, self.callback = blocksize, dtype, callback
                self.latency = blocksize / float(samplerate)
                sd.opened.append((kind, device, channels, samplerate, blocksize, dtype))

            def _in_block(self, n, ch, played=None):
                w = sc.WIDTH[self.dtype]
                frames = []
                for i in range(n):
                    row = [sd.input_value if sd.loop is None else 0.0] * ch
                    if sd.loop is not None and played is not None:
                        oc, ic = sd.loop
                        row[ic] = played[i][oc] if i < len(played) else 0.0
                    frames.append(row)
                return bytearray(sc.encode(frames, self.dtype)) if w else b""

            def start(self):
                if self.callback is None:
                    return
                n = self.blocksize or 256
                for _ in range(100000):
                    try:
                        if self.kind == "input":
                            self.callback(self._in_block(n, self.channels), n, None, None)
                        elif self.kind == "output":
                            out = bytearray(n * self.channels * sc.WIDTH[self.dtype])
                            self.callback(out, n, None, None)
                        else:
                            ic, oc = self.channels
                            out = bytearray(n * oc * sc.WIDTH[self.dtype])
                            # A fake cable: the previous block's output comes back in.
                            inb = self._in_block(n, ic, getattr(self, "_prev", None))
                            self.callback(inb, out, n, None, None)
                            self._prev = [list(f) for f in zip(*sc.decode(bytes(out), self.dtype, oc))]
                    except _CallbackStop:
                        return

            def stop(self):
                pass

            def close(self):
                pass

        self.RawInputStream = lambda **kw: _Stream("input", **kw)
        self.RawOutputStream = lambda **kw: _Stream("output", **kw)
        self.RawStream = lambda **kw: _Stream("duplex", **kw)

    def query_hostapis(self, index=None):
        return self.hosts if index is None else self.hosts[index]

    def query_devices(self):
        return self.devices

    def get_portaudio_version(self):
        return (1, "PortAudio fake")


def _args(*argv):
    return sc.build_parser().parse_args(list(argv))


def _status(rep, name):
    return next(s for s in rep.steps if s.name == name).status


class ToneDetection(unittest.TestCase):
    RATE = 48000

    def test_generated_tone_is_detected_at_its_level(self):
        tone = [0.1 * math.sin(2 * math.pi * 1000 * i / self.RATE) for i in range(self.RATE)]
        r = sc.detect_tone(tone, self.RATE)
        self.assertTrue(r["detected"])
        self.assertAlmostEqual(r["level_dbfs"], -20.0, delta=0.05)
        self.assertGreater(r["fraction"], 0.99)
        self.assertLessEqual(r["onset_frame"], 5)  # sin reaches half amplitude at 1/12 period = 4 frames

    def test_silence_is_not_detected(self):
        r = sc.detect_tone([0.0] * self.RATE, self.RATE)
        self.assertFalse(r["detected"])
        self.assertIsNone(r["level_dbfs"])
        self.assertIsNone(r["rms_dbfs"])
        self.assertEqual(sc.detect_tone([], self.RATE)["detected"], False)

    def test_other_frequency_and_tiny_tone_are_not_detected(self):
        other = [0.5 * math.sin(2 * math.pi * 440 * i / self.RATE) for i in range(self.RATE)]
        self.assertFalse(sc.detect_tone(other, self.RATE)["detected"])
        tiny = [1e-4 * math.sin(2 * math.pi * 1000 * i / self.RATE) for i in range(self.RATE)]
        r = sc.detect_tone(tiny, self.RATE)
        self.assertAlmostEqual(r["level_dbfs"], -80.0, delta=0.1)
        self.assertFalse(r["detected"])


class Samples(unittest.TestCase):
    def test_round_trip_and_widths(self):
        frames = [[1.0, -1.0], [0.0, 0.5]]
        for dtype in ("int16", "int24", "int32", "float32"):
            raw = sc.encode(frames, dtype)
            self.assertEqual(len(raw), 4 * sc.WIDTH[dtype])
            left, right = sc.decode(raw, dtype, 2)
            self.assertAlmostEqual(left[0], 1.0, delta=1e-4)
            self.assertAlmostEqual(right[0], -1.0, delta=1e-4)
            self.assertAlmostEqual(right[1], 0.5, delta=1e-4)
        self.assertEqual(sc.decode_ints(b"\xff\xff\x7f\x00\x00\x80", "int24"), [8388607, -8388608])

    def test_low_byte_count(self):
        raw = struct.pack("<i", 0x100)[:3] + struct.pack("<i", 0x101)[:3]
        self.assertEqual(sc.low_byte_nonzero(raw, "int24"), (1, 2))


class Matrix(unittest.TestCase):
    def test_every_pair_is_tried_and_refusals_carry_the_exception(self):
        sd = FakeSD(refuse={(88200, 64)})
        dev = sc.list_devices(sd)[2]
        rows = sc.probe_matrix(sd, dev, [44100, 88200], [64, 128])
        self.assertEqual([(r["rate"], r["buffer"]) for r in rows], [(44100, 64), (44100, 128), (88200, 64), (88200, 128)])
        bad = rows[2]
        self.assertEqual(bad["input"]["status"], sc.FAIL)
        self.assertIn("PaErrorCode -9997", bad["input"]["error"])
        self.assertEqual(rows[0]["input"]["status"], sc.PASS)
        self.assertAlmostEqual(rows[0]["input"]["latency"], 64 / 44100)
        self.assertEqual(sc.matrix_summary(rows), (sc.FAIL, "6 of 8 stream opens accepted"))
        opened = [o for o in sd.opened if o[0] == "input"]
        self.assertTrue(all(o[1] == 2 and o[2] == 2 and o[5] == "int16" for o in opened))

    def test_side_without_channels_is_skipped(self):
        sd = FakeSD()
        dev = sc.list_devices(sd)[0]  # inputs only
        rows = sc.probe_matrix(sd, dev, [44100], [64])
        self.assertEqual(rows[0]["output"]["status"], sc.SKIPPED)
        self.assertEqual(sc.matrix_summary(rows), (sc.PASS, "1 of 1 stream opens accepted"))

    def test_device_pick(self):
        devs = sc.list_devices(FakeSD())
        self.assertEqual(sc.pick_device(devs, None)[0]["index"], 2)
        self.assertEqual(sc.pick_device(devs, "1")[0]["index"], 1)
        self.assertEqual(sc.pick_device(devs, "focusrite")[0]["index"], 2)
        self.assertIsNone(sc.pick_device(devs, "99")[0])
        self.assertIsNone(sc.pick_device(devs[:2], None)[0])


class FullRun(unittest.TestCase):
    def test_missing_library_fails_cleanly(self):
        rep = sc.run_check(_args(), loader=lambda asio: (None, "ModuleNotFoundError: No module named 'sounddevice'"))
        self.assertEqual(rep.steps[0].status, sc.FAIL)
        self.assertIn("pip install sounddevice", rep.steps[0].detail)
        self.assertTrue(all(s.status == sc.SKIPPED for s in rep.steps[1:]))
        text = sc.render_report(rep)
        self.assertIn("No module named 'sounddevice'", text)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.md"
            with contextlib.redirect_stdout(io.StringIO()):
                code = sc.main(["--report", str(out)], loader=lambda asio: (None, "ModuleNotFoundError: x"))
            self.assertEqual(code, 2)
            self.assertIn("FAIL", out.read_text())

    def test_full_run_without_loopback(self):
        sd = FakeSD(refuse={(96000, 64)})
        rep = sc.run_check(_args("--rates", "48000,96000", "--buffers", "64", "--seconds", "0.05"), loader=lambda asio: (sd, None))
        self.assertEqual(_status(rep, "Pick device"), sc.PASS)
        self.assertEqual(_status(rep, "Rate x buffer matrix"), sc.FAIL)
        for bits, dtype in ((16, "int16"), (24, "int24"), (32, "int32")):
            self.assertEqual(_status(rep, f"Record {bits}-bit ({dtype})"), sc.PASS)
        rec24 = next(r for r in rep.records if r["label"] == "Record 24-bit (int24)")
        self.assertEqual(rec24["bytes per sample received"], 3.0)
        self.assertEqual(rec24["frames received"], 2400)
        self.assertEqual(_status(rep, "Play test tone"), sc.PASS)
        self.assertEqual(_status(rep, "Loopback tone"), sc.SKIPPED)
        text = sc.render_report(rep)
        self.assertIn("physical cable", text)
        self.assertIn("PaErrorCode -9997", text)
        self.assertIn("| Rate | Buffer | Input |", text)
        self.assertIn("Focusrite USB ASIO", text)

    def test_loopback_detects_the_tone_through_a_fake_cable(self):
        sd = FakeSD(loop=(0, 0))
        rep = sc.run_check(_args("--rates", "48000", "--buffers", "256", "--seconds", "0.5", "--no-play", "--loopback"),
                           loader=lambda asio: (sd, None))
        self.assertEqual(_status(rep, "Play test tone"), sc.SKIPPED)
        self.assertEqual(_status(rep, "Loopback tone"), sc.PASS)
        rec = next(r for r in rep.records if r["label"] == "Loopback tone")
        self.assertIn("-20.", rec["1 kHz level (after the first 0.2 s)"])

    def test_loopback_without_cable_fails_not_detected(self):
        sd = FakeSD(input_value=0.0)
        rep = sc.run_check(_args("--rates", "48000", "--buffers", "256", "--seconds", "0.3", "--no-play", "--loopback"),
                           loader=lambda asio: (sd, None))
        step = next(s for s in rep.steps if s.name == "Loopback tone")
        self.assertEqual(step.status, sc.FAIL)
        self.assertIn("not detected", step.detail)

    def test_list_only_and_dry_run(self):
        sd = FakeSD()
        rep = sc.run_check(_args("--list-only"), loader=lambda asio: (sd, None))
        self.assertEqual(_status(rep, "List host APIs and devices"), sc.PASS)
        self.assertEqual(_status(rep, "Rate x buffer matrix"), sc.SKIPPED)
        self.assertEqual(sd.opened, [])
        called = []
        rep = sc.run_check(_args("--dry-run"), loader=lambda asio: called.append(asio))
        self.assertEqual(called, [])
        self.assertTrue(all(s.status == sc.SKIPPED for s in rep.steps))

    def test_no_asio_host_is_noted_and_default_pick_skips(self):
        sd = FakeSD(hosts=[{"name": "MME", "devices": [0]}],
                    devices=[{"name": "Focusrite USB", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000.0}])
        rep = sc.run_check(_args(), loader=lambda asio: (sd, None))
        self.assertIn("no ASIO host", rep.steps[1].detail)
        self.assertEqual(_status(rep, "Pick device"), sc.SKIPPED)
        self.assertTrue(any("No ASIO host API" in n for n in rep.notes))

    def test_report_path_inside_uploads_is_refused(self):
        self.assertIsNotNone(sc.check_report_path(sc.REPO / "uploads" / "r.md"))
        self.assertIsNone(sc.check_report_path(Path(tempfile.gettempdir()) / "r.md"))


class Formatting(unittest.TestCase):
    def test_report_sections_and_escaping(self):
        rep = sc.Report(started="2026-10-28T14:00:00-04:00")
        rep.add("A | B", sc.PASS, "ok")
        rep.add("Broken", sc.FAIL, "it failed", "RuntimeError: boom\nline 2")
        text = sc.render_report(rep)
        self.assertIn("Run at 2026-10-28T14:00:00-04:00.", text)
        self.assertIn("| A \\| B | PASS | ok |", text)
        self.assertIn("| Broken | FAIL | it failed |", text)
        self.assertIn("```\nRuntimeError: boom\nline 2\n```", text)
        self.assertNotIn("## Devices", text)
        self.assertEqual(sc.fmt_db(None), "-inf dBFS")
        self.assertEqual(sc.fmt_ms(0.0015), "1.50 ms")


if __name__ == "__main__":
    unittest.main()
