"""AsioRecorder.start must not leak the WAV handle when the stream fails (F).

start() opens the take with wave.open(path, "wb") before it opens the
input stream. If sd.InputStream(...) or stream.start() raises (busy or
missing device), the wave handle used to stay open: on Windows that keeps
the file locked, so the server cannot remove the empty take. No hardware:
a fake sounddevice module raises from the stream.
"""

import tempfile
import unittest
import wave
from pathlib import Path

from app.backend import asio


class PortAudioError(Exception):
    pass


class _Stream:
    def __init__(self, fail_start, log, **kw):
        self.fail_start = fail_start
        self.log = log

    def start(self):
        if self.fail_start:
            raise PortAudioError("Error starting stream: Device unavailable")

    def stop(self):
        self.log.append("stop")

    def close(self):
        self.log.append("close")


class FakeSD:
    def __init__(self, fail_open=False, fail_start=False):
        self.fail_open, self.fail_start, self.log = fail_open, fail_start, []

    def InputStream(self, **kw):
        if self.fail_open:
            raise PortAudioError("Error opening InputStream: Device unavailable")
        return _Stream(self.fail_start, self.log, **kw)


class OpenFailure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "take.wav"
        self._saved = (asio._sd, asio.platform_supports_asio, asio.list_asio_devices, asio.wave.open)
        asio.platform_supports_asio = lambda: True
        asio.list_asio_devices = lambda: [{"index": 3, "name": "Focusrite USB ASIO", "inputs": 2}]
        self.handles = []
        real_open = self._saved[3]

        def tracking_open(*a, **kw):
            h = real_open(*a, **kw)
            self.handles.append(h)
            return h

        asio.wave.open = tracking_open

    def tearDown(self):
        asio._sd, asio.platform_supports_asio, asio.list_asio_devices, asio.wave.open = self._saved
        self.tmp.cleanup()

    def _start(self, sd):
        asio._sd = lambda: sd
        rec = asio.AsioRecorder()
        with self.assertRaises(PortAudioError):
            rec.start(self.path, sample_rate=48000, buffer=64, channels=1)
        return rec

    def test_stream_open_failure_closes_the_wave_handle(self):
        rec = self._start(FakeSD(fail_open=True))
        self.assertEqual(len(self.handles), 1)
        self.assertIsNone(self.handles[0]._file)  # Wave_write.close() clears _file
        self.assertFalse(rec.recording)

    def test_stream_start_failure_closes_stream_and_wave(self):
        sd = FakeSD(fail_start=True)
        rec = self._start(sd)
        self.assertIsNone(self.handles[0]._file)
        self.assertIn("close", sd.log)
        self.assertFalse(rec.recording)

    def test_file_can_be_removed_after_failure(self):
        self._start(FakeSD(fail_open=True))
        self.path.unlink()
        self.assertFalse(self.path.exists())

    def test_success_keeps_the_handle_open(self):
        asio._sd = lambda: FakeSD()
        rec = asio.AsioRecorder()
        rec.start(self.path, sample_rate=48000, buffer=64, channels=1)
        self.assertIsNotNone(self.handles[0]._file)
        self.assertTrue(rec.recording)
        rec.stop()


if __name__ == "__main__":
    unittest.main()
