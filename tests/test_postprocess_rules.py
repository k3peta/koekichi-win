from __future__ import annotations

import unittest

from windows_voice_typer.postprocess import normalize_transcript_artifacts


class PostprocessRuleTests(unittest.TestCase):
    def test_normalizes_contextual_punctuation_word_misrecognition(self) -> None:
        text = "ただ、現在、行くと、点の入力の関係を見直してください"

        self.assertEqual(
            normalize_transcript_artifacts(text),
            "ただ、現在、句読点の入力の関係を見直してください",
        )

    def test_normalizes_repeated_sukoshi_misrecognition(self) -> None:
        text = "入力の関係が損し荒れているそうし荒れているような気がします"

        self.assertEqual(
            normalize_transcript_artifacts(text),
            "入力の関係が少し荒れているような気がします",
        )


if __name__ == "__main__":
    unittest.main()
