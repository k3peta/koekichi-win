from __future__ import annotations

import unittest

from windows_voice_typer.postprocess import default_instructions
from windows_voice_typer.postprocess import normalize_transcript_artifacts
from windows_voice_typer.postprocess import postprocess
from windows_voice_typer.postprocess import prompt_for_mode


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

    def test_collapses_adjacent_duplicate_sentence_with_punctuation(self) -> None:
        text = "ブラウザで入力できるようになりました。ブラウザで入力できるようになりました。"

        self.assertEqual(
            normalize_transcript_artifacts(text),
            "ブラウザで入力できるようになりました。",
        )

    def test_collapses_adjacent_duplicate_phrase_with_comma_separator(self) -> None:
        text = "これは修正しないといけないかもしれません、これは修正しないといけないかもしれません"

        self.assertEqual(
            normalize_transcript_artifacts(text),
            "これは修正しないといけないかもしれません",
        )

    def test_keeps_short_intentional_repetition(self) -> None:
        text = "まだまだ確認します"

        self.assertEqual(normalize_transcript_artifacts(text), text)

    def test_removes_trailing_video_closing_hallucination_with_punctuation(self) -> None:
        text = "今日はここまでです。ご視聴ありがとうございました。"

        self.assertEqual(normalize_transcript_artifacts(text), "今日はここまでです")

    def test_removes_video_closing_even_when_postprocess_is_off(self) -> None:
        result = postprocess("今日はここまでです。ご視聴ありがとうございました。", {"postprocess_mode": "off"})

        self.assertEqual(result.text, "今日はここまでです")

    def test_ai_prompts_forbid_video_closing_hallucination(self) -> None:
        phrase = "ご視聴ありがとうございました"

        self.assertIn(phrase, default_instructions(rewrite=True))
        self.assertIn(phrase, default_instructions(rewrite=False))
        self.assertIn(phrase, prompt_for_mode("今日はここまでです", rewrite=True))
        self.assertIn(phrase, prompt_for_mode("今日はここまでです", rewrite=False))

    def test_normalizes_gohenkan_misrecognition(self) -> None:
        self.assertEqual(
            normalize_transcript_artifacts("今回もご変換がありますね"),
            "今回も誤変換がありますね",
        )

    def test_collapses_restart_prefix_fragment(self) -> None:
        self.assertEqual(
            normalize_transcript_artifacts("それらを追い、それらを追いかけて確認します"),
            "それらを追いかけて確認します",
        )

    def test_normalizes_contextual_ongaku_to_taisaku(self) -> None:
        self.assertEqual(
            normalize_transcript_artifacts("何らかの対策を取り、音楽を取りたいと思います"),
            "何らかの対策を取りたいと思います",
        )

    def test_normalizes_current_observed_error_sentence(self) -> None:
        text = "毎回何らかの誤入力があったり、ご変換があったりするので、それらを追い、それらを追いかけて、何らかの対策を取り、音楽を取りたいと思います"

        self.assertEqual(
            normalize_transcript_artifacts(text),
            "毎回何らかの誤入力があったり、誤変換があったりするので、それらを追いかけて、何らかの対策を取りたいと思います",
        )


if __name__ == "__main__":
    unittest.main()
