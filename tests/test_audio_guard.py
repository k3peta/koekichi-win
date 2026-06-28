from __future__ import annotations

import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from windows_voice_typer.audio_guard import should_skip_low_activity_audio
from windows_voice_typer.audio_guard import wav_activity_summary


class AudioGuardTests(unittest.TestCase):
    def test_skips_silent_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "silent.wav"
            _write_wav(path, [0] * 16000)

            summary = wav_activity_summary(path)
            decision = should_skip_low_activity_audio(summary, {})

        self.assertTrue(decision.skip)
        self.assertIn("quiet", decision.reason)

    def test_keeps_audible_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tone.wav"
            samples = [int(0.08 * 32767 * math.sin(2 * math.pi * 440 * index / 16000)) for index in range(16000)]
            _write_wav(path, samples)

            summary = wav_activity_summary(path)
            decision = should_skip_low_activity_audio(summary, {})

        self.assertFalse(decision.skip)
        self.assertGreater(summary.active_seconds, 0.5)


def _write_wav(path: Path, samples: list[int]) -> None:
    pcm = array("h", samples)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm.tobytes())


if __name__ == "__main__":
    unittest.main()
