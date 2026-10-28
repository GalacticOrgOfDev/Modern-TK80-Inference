"""The mix reads 16-, 24- and 32-bit integer PCM WAV; float WAV is refused.

A Scarlett records 24-bit (and DAWs often save 32-bit), and before this
mix_arrangement refused anything but 16-bit. Now 24- and 32-bit integer
PCM are converted to the mix's internal 16-bit samples by rounding to the
nearest 16-bit step, ties to even, and clamping, so +full scale lands on
32767 and -full scale on -32768 with no wraparound. No dither. 8-bit stays
an error, and 32-bit float WAV (format code 3, or WAVE_FORMAT_EXTENSIBLE
with the float subformat) gets its own reason instead of a guess.
Uses the fastapi/pydantic stand-ins from tests.test_daw_ids.
"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tests.test_daw_ids import server  # noqa: E402  (sets TK80_UPLOADS, stubs fastapi)
from app.backend import audio  # noqa: E402
from app.backend.daw_state import IdCounter  # noqa: E402

RATE = 1000
FLOAT_REASON = "32-bit float WAV; only integer PCM can be mixed"

FULL = {2: (32767, -32768), 3: (8388607, -8388608), 4: (2147483647, -2147483648)}
# (source value, expected 16-bit value) per width: +full, -full, zero, mid
# values including both tie directions (ties go to the even 16-bit step).
CASES = {
    2: [(32767, 32767), (-32768, -32768), (0, 0), (4660, 4660), (-4660, -4660)],
    3: [
        (8388607, 32767), (-8388608, -32768), (0, 0),
        (0x123480, 0x1234), (0x123580, 0x1236), (0x123481, 0x1235), (0x12347F, 0x1234),
        (-0x123480, -0x1234), (-0x123580, -0x1236), (-129, -1), (-128, 0), (-127, 0),
        (8388480, 32767), (8388479, 32767), (8388223, 32766),
    ],
    4: [
        (2147483647, 32767), (-2147483648, -32768), (0, 0),
        (0x12348000, 0x1234), (0x12358000, 0x1236), (0x12348001, 0x1235),
        (-0x12348000, -0x1234), (-0x12358000, -0x1236),
    ],
}


def _pack(values, width):
    if width == 2:
        return b"".join(struct.pack("<h", v) for v in values)
    if width == 3:
        return b"".join(struct.pack("<i", v)[:3] for v in values)
    return b"".join(struct.pack("<i", v) for v in values)


def _write_pcm(path, values, width, channels=1, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(_pack(values, width))
    return path


def _write_float(path, values, extensible=False, channels=1, rate=RATE):
    data = b"".join(struct.pack("<f", v) for v in values)
    if extensible:
        guid = struct.pack("<H", 3) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt = struct.pack("<HHIIHH", 0xFFFE, channels, rate, rate * 4 * channels, 4 * channels, 32)
        fmt += struct.pack("<HHI", 22, 32, 0) + guid
    else:
        fmt = struct.pack("<HHIIHH", 3, channels, rate, rate * 4 * channels, 4 * channels, 32)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def _read(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        return w.getnchannels(), [struct.unpack_from("<h", raw, i)[0] for i in range(0, len(raw), 2)]


class Conversion(unittest.TestCase):
    def test_full_scale_zero_and_mid_values_round_to_nearest_even(self):
        for width, cases in CASES.items():
            with self.subTest(width=width):
                src = [s for s, _ in cases]
                want = [e for _, e in cases]
                got = audio._samples(audio.pcm_to_int16(_pack(src, width), width))
                self.assertEqual(got, want)

    def test_no_wraparound_sign_is_kept(self):
        for width, (hi, lo) in FULL.items():
            with self.subTest(width=width):
                got = audio._samples(audio.pcm_to_int16(_pack([hi, lo, hi - 1, lo + 1], width), width))
                self.assertTrue(all(v > 0 for v in (got[0], got[2])), got)
                self.assertTrue(all(v < 0 for v in (got[1], got[3])), got)
                self.assertEqual((got[0], got[1]), (32767, -32768))

    def test_16bit_bytes_pass_through_unchanged(self):
        raw = _pack([1, -1, 32767, -32768], 2)
        self.assertEqual(audio.pcm_to_int16(raw, 2), raw)

    def test_other_widths_are_refused(self):
        for width in (1, 5):
            with self.assertRaises(ValueError):
                audio.pcm_to_int16(b"\x00" * width * 2, width)


class _Dir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"
        self.out.mkdir()
        self._old = audio.UPLOAD_DIR
        audio.UPLOAD_DIR = self.out
        self.tracks = [audio.make_track(0, "T1")]

    def tearDown(self):
        audio.UPLOAD_DIR = self._old
        self.tmp.cleanup()

    def clip(self, cid, path):
        return audio.make_clip(cid, path.name, path, track_id=0, sample_rate=RATE)


class MixReadsWideIntegerPcm(_Dir):
    def test_wide_mix_equals_the_mix_of_the_converted_16bit_file(self):
        for width, cases in CASES.items():
            with self.subTest(width=width):
                src = [s for s, _ in cases] * 4
                want = [e for _, e in cases] * 4
                wide = _write_pcm(self.dir / f"w{width}.wav", src, width)
                ref = _write_pcm(self.dir / f"ref{width}.wav", want, 2)
                a = audio.mix_arrangement([self.clip(1, wide)], self.tracks, RATE, f"a{width}.wav")
                b = audio.mix_arrangement([self.clip(1, ref)], self.tracks, RATE, f"b{width}.wav")
                self.assertEqual(a.read_bytes()[44:], b.read_bytes()[44:])
                ch, out = _read(a)
                self.assertEqual(ch, 2)
                self.assertEqual(out[0], 32767)  # +full stays at the top, not wrapped
                self.assertLess(out[2], -32000)  # -full stays at the bottom
                self.assertEqual(out[4], 0)

    def test_stereo_24bit_keeps_channels(self):
        src = [8388607, -8388608] * 10
        p = _write_pcm(self.dir / "st24.wav", src, 3, channels=2)
        ch, out = _read(audio.mix_arrangement([self.clip(1, p)], self.tracks, RATE, "m.wav"))
        self.assertEqual(ch, 2)
        self.assertEqual(out[0], 32767)
        self.assertLess(out[1], -32000)

    def test_24bit_clip_has_real_waveform_peaks(self):
        p = _write_pcm(self.dir / "pk24.wav", [0x400000] * 128, 3)
        ref = _write_pcm(self.dir / "pk16.wav", [0x4000] * 128, 2)
        self.assertEqual(audio.wav_peaks(p), audio.wav_peaks(ref))
        self.assertGreater(max(audio.wav_peaks(p)), 0.4)


class BpmDetectReadsWidePcm(_Dir):
    def test_detect_bpm_on_24bit_matches_the_16bit_equivalent(self):
        from app.backend import music
        rate = 8000
        beat = ([0x600000] * 200 + [0] * 3800) * 8  # a click every 0.5 s
        p24 = _write_pcm(self.dir / "beat24.wav", beat, 3, rate=rate)
        p16 = _write_pcm(self.dir / "beat16.wav", [0x6000 if v else 0 for v in beat], 2, rate=rate)
        self.assertEqual(music.detect_bpm(p24), music.detect_bpm(p16))


class EditAndEffectsStill16BitOnly(_Dir):
    """Documented limit (DAW.md Limits): edits and effects refuse 24-bit with a clear message."""

    def test_edit_and_effect_refuse_24bit(self):
        from app.backend import effects
        p = _write_pcm(self.dir / "e24.wav", [0x100000] * 100, 3)
        with self.assertRaisesRegex(ValueError, "only 16-bit WAV is supported"):
            audio.process_clip(p, "gain", gain=0.5)
        with self.assertRaisesRegex(ValueError, "only 16-bit WAV is supported"):
            effects.apply_effect(p, "normalize")
        self.assertEqual(list(self.out.iterdir()), [])


class FloatAndEightBitRefused(_Dir):
    def test_float_wav_is_refused_with_its_own_reason(self):
        for ext in (False, True):
            with self.subTest(extensible=ext):
                p = _write_float(self.dir / f"f{int(ext)}.wav", [0.5] * 50, extensible=ext)
                with self.assertRaises(audio.UnmixableClipError) as cm:
                    audio.mix_arrangement([self.clip(7, p)], self.tracks, RATE, "m.wav")
                self.assertEqual(cm.exception.problems[0]["reason"], FLOAT_REASON)
                self.assertIn(FLOAT_REASON, str(cm.exception))
                self.assertEqual(list(self.out.iterdir()), [])

    def test_8bit_still_refused(self):
        p = self.dir / "b8.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(RATE)
            w.writeframes(b"\x80" * 50)
        with self.assertRaises(audio.UnmixableClipError) as cm:
            audio.mix_arrangement([self.clip(7, p)], self.tracks, RATE, "m.wav")
        self.assertIn("8-bit", cm.exception.problems[0]["reason"])

    def test_endpoints_400_on_float(self):
        saved = {k: getattr(server, k) for k in ("_audio_tracks", "_audio_clips", "_sample_rate", "_master", "_track_ids", "_clip_ids")}
        try:
            server._audio_tracks = [audio.make_track(0, "T1")]
            server._sample_rate = RATE
            server._master = audio.default_master()
            p = _write_float(self.dir / "f.wav", [0.25] * 50)
            server._audio_clips = [self.clip(7, p)]
            server._track_ids = IdCounter.after(server._audio_tracks)
            server._clip_ids = IdCounter.after(server._audio_clips)
            for call in (server.mix_audio, lambda: server.bounce_audio(server.BounceRequest(name="b.wav"))):
                with self.assertRaises(Exception) as cm:
                    call()
                self.assertEqual(getattr(cm.exception, "status_code", None), 400)
                self.assertIn(FLOAT_REASON, str(cm.exception.detail))
                self.assertIn("#7", str(cm.exception.detail))
        finally:
            for k, v in saved.items():
                setattr(server, k, v)


if __name__ == "__main__":
    unittest.main()
