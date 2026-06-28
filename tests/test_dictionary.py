from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from windows_voice_typer.dictionary import DEFAULT_DICTIONARY
from windows_voice_typer.dictionary import VoiceDictionary


class VoiceDictionaryTests(unittest.TestCase):
    def test_corrects_dictionary_punctuation_word_misrecognitions(self) -> None:
        dictionary = VoiceDictionary("unused.json")
        dictionary.data = json.loads(json.dumps(DEFAULT_DICTIONARY, ensure_ascii=False))

        self.assertEqual(dictionary.process("苦闘点を見直す"), "句読点を見直す")
        self.assertEqual(dictionary.process("句読店を見直す"), "句読点を見直す")

    def test_load_adds_missing_default_replacements_to_existing_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dictionary.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "replacements": [{"from": "オープンAI", "to": "OpenAI", "mode": "literal"}],
                        "urls": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            dictionary = VoiceDictionary(path)
            dictionary.load()

        self.assertEqual(dictionary.process("句頭点"), "句読点")
        self.assertEqual(dictionary.process("苦闘点"), "句読点")


if __name__ == "__main__":
    unittest.main()
