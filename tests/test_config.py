from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from windows_voice_typer.config import ensure_config
from windows_voice_typer.config import load_config


class ConfigTests(unittest.TestCase):
    def test_new_config_starts_with_initial_settings_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            ensure_config(path)

            config = load_config(path)

        self.assertFalse(config["initial_settings_completed"])

    def test_existing_config_without_initial_settings_flag_is_treated_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"language": "ja", "dictionary_path": "auto"}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertTrue(config["initial_settings_completed"])


if __name__ == "__main__":
    unittest.main()
