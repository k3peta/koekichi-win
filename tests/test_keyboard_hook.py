from __future__ import annotations

import queue
import time
import unittest

from windows_voice_typer.keyboard_hook import AltActivationHook
from windows_voice_typer.keyboard_hook import WM_KEYDOWN
from windows_voice_typer.keyboard_hook import WM_KEYUP


class AltActivationHookTests(unittest.TestCase):
    def test_ignores_stray_alt_keyup(self) -> None:
        hook = AltActivationHook(
            interval_seconds=0.45,
            get_target=lambda: (1, 2),
            on_double_tap=lambda _hwnd, _focus: None,
        )

        hook._handle_alt_event(WM_KEYUP)

        with self.assertRaises(queue.Empty):
            hook._callback_queue.get_nowait()

    def test_double_tap_queues_activation(self) -> None:
        hook = AltActivationHook(
            interval_seconds=0.45,
            get_target=lambda: (1, 2),
            on_double_tap=lambda _hwnd, _focus: None,
        )

        hook._handle_alt_event(WM_KEYDOWN)
        hook._handle_alt_event(WM_KEYUP)
        hook._handle_alt_event(WM_KEYDOWN)
        hook._handle_alt_event(WM_KEYUP)

        self.assertEqual(hook._callback_queue.get_nowait(), ("double_tap", (0, 0)))

    def test_hold_queues_start_and_stop(self) -> None:
        hook = AltActivationHook(
            interval_seconds=0.45,
            get_target=lambda: (1, 2),
            hold_start_delay_seconds=0.01,
            on_hold_start=lambda: None,
            on_hold_stop=lambda: None,
        )

        hook._handle_alt_event(WM_KEYDOWN)
        time.sleep(0.05)
        hook._handle_alt_event(WM_KEYUP)

        self.assertEqual(hook._callback_queue.get_nowait(), ("hold_start", None))
        self.assertEqual(hook._callback_queue.get_nowait(), ("hold_stop", None))


if __name__ == "__main__":
    unittest.main()
