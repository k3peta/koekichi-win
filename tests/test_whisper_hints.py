from __future__ import annotations

import unittest

from windows_voice_typer.config import DEFAULT_CONFIG
from windows_voice_typer.dictionary import DEFAULT_DICTIONARY
from windows_voice_typer.whisper_hints import build_whisper_hints
from windows_voice_typer.whisper_hints import collect_whisper_hint_terms
from windows_voice_typer.whisper_hints import compose_whisper_hotwords
from windows_voice_typer.whisper_hints import compose_whisper_prompt


class WhisperHintsTests(unittest.TestCase):
    def test_collects_short_unique_terms_from_dictionary(self) -> None:
        terms = collect_whisper_hint_terms(DEFAULT_DICTIONARY, max_terms=40)
        self.assertIn("OpenAI", terms)
        self.assertIn("Whisper", terms)
        self.assertIn("声吉", terms)
        self.assertIn("ChatGPT", terms)
        self.assertIn("note", terms)
        self.assertNotIn("5認識", terms)
        self.assertNotIn("オープンAI", terms)
        self.assertNotIn("チャットジーピーティー", terms)
        self.assertEqual(len(terms), len({term.casefold() for term in terms}))

    def test_prompt_respects_user_text_and_appends_short_hints(self) -> None:
        prompt = compose_whisper_prompt("ユーザー指定", ["OpenAI", "Whisper", "声吉"], enabled=True, max_terms=2)
        self.assertTrue(prompt.startswith("ユーザー指定"))
        self.assertIn("補助語:", prompt)
        self.assertIn("OpenAI", prompt)
        self.assertIn("Whisper", prompt)
        self.assertNotIn("声吉", prompt)

    def test_hotwords_default_off(self) -> None:
        hotwords = compose_whisper_hotwords(["OpenAI", "Whisper"], enabled=False, max_terms=20)
        self.assertIsNone(hotwords)

    def test_build_bundle_uses_config_defaults(self) -> None:
        config = dict(DEFAULT_CONFIG)
        config["whisper_prompt"] = "まず正しく"
        bundle = build_whisper_hints(config, DEFAULT_DICTIONARY)
        self.assertTrue(bundle.prompt.startswith("まず正しく"))
        self.assertIsNone(bundle.hotwords)
        self.assertGreater(len(bundle.terms), 0)


if __name__ == "__main__":
    unittest.main()
