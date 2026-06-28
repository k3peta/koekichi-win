from __future__ import annotations

import datetime as _datetime
import unittest

from windows_voice_typer.history_guard import is_recent_duplicate_history


class HistoryGuardTests(unittest.TestCase):
    def test_detects_recent_duplicate_output(self) -> None:
        now = _datetime.datetime(2026, 6, 28, 21, 0, 0)
        history = [{"time": "2026-06-28 20:58:30", "out": "同じ本文"}]

        self.assertTrue(is_recent_duplicate_history(history, "同じ本文", now=now, window_seconds=180))

    def test_allows_old_duplicate_output(self) -> None:
        now = _datetime.datetime(2026, 6, 28, 21, 0, 0)
        history = [{"time": "2026-06-28 20:00:00", "out": "同じ本文"}]

        self.assertFalse(is_recent_duplicate_history(history, "同じ本文", now=now, window_seconds=180))

    def test_allows_different_output(self) -> None:
        now = _datetime.datetime(2026, 6, 28, 21, 0, 0)
        history = [{"time": "2026-06-28 20:59:30", "out": "前の本文"}]

        self.assertFalse(is_recent_duplicate_history(history, "新しい本文", now=now, window_seconds=180))


if __name__ == "__main__":
    unittest.main()
