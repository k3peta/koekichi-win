from __future__ import annotations

import unittest

from windows_voice_typer.gemini_transcriber import DEFAULT_GEMINI_PROMPT
from windows_voice_typer.gemini_transcriber import GeminiAudioTranscriber
from windows_voice_typer.gemini_transcriber import sanitize_gemini_transcript


class GeminiTranscriberTests(unittest.TestCase):
    def test_default_prompt_forbids_video_closing_hallucination(self) -> None:
        self.assertIn("ご視聴ありがとうございました", DEFAULT_GEMINI_PROMPT)
        self.assertIn("do not output", DEFAULT_GEMINI_PROMPT.casefold())

    def test_custom_prompt_gets_forbidden_video_closing_instruction(self) -> None:
        transcriber = GeminiAudioTranscriber(
            model="dummy",
            api_key_env="DUMMY",
            endpoint="https://example.test",
            timeout_seconds=1.0,
            max_inline_audio_bytes=1,
            prompt="日本語で文字起こししてください。",
        )

        self.assertIn("日本語で文字起こししてください。", transcriber.prompt)
        self.assertIn("ご視聴ありがとうございました", transcriber.prompt)

    def test_sanitize_removes_trailing_video_closing_hallucination(self) -> None:
        self.assertEqual(
            sanitize_gemini_transcript("今日はここまでです。ご視聴ありがとうございました。"),
            "今日はここまでです",
        )


if __name__ == "__main__":
    unittest.main()
