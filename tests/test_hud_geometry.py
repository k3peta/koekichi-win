from __future__ import annotations

import unittest

from windows_voice_typer.hud_geometry import choose_hud_position_near_rect
from windows_voice_typer.hud_geometry import is_reasonable_text_target_rect


class HudGeometryTests(unittest.TestCase):
    def test_uses_virtual_screen_bounds_with_negative_origin(self) -> None:
        bounds = (-1920, 0, 1920, 1080)
        rect = (-1850, 120, -1848, 140)

        x, y = choose_hud_position_near_rect(rect, 150, 34, bounds)

        self.assertLess(x, 0)
        self.assertGreaterEqual(x, -1912)
        self.assertGreaterEqual(y, 8)

    def test_clamps_to_nearest_candidate_instead_of_top_left(self) -> None:
        bounds = (0, 0, 500, 300)
        rect = (455, 250, 458, 270)

        self.assertEqual(
            choose_hud_position_near_rect(rect, 150, 34, bounds),
            (287, 206),
        )

    def test_accepts_caret_sized_text_rect(self) -> None:
        self.assertTrue(
            is_reasonable_text_target_rect(
                (320, 180, 322, 202),
                (0, 0, 1920, 1080),
                window_rect=(100, 100, 900, 700),
            )
        )

    def test_rejects_window_sized_text_rect(self) -> None:
        self.assertFalse(
            is_reasonable_text_target_rect(
                (110, 110, 890, 690),
                (0, 0, 1920, 1080),
                window_rect=(100, 100, 900, 700),
            )
        )

    def test_rejects_offscreen_text_rect(self) -> None:
        self.assertFalse(is_reasonable_text_target_rect((2200, 100, 2300, 150), (0, 0, 1920, 1080)))

    def test_rejects_tiny_rect_at_window_origin(self) -> None:
        self.assertFalse(
            is_reasonable_text_target_rect(
                (100, 100, 102, 118),
                (0, 0, 1920, 1080),
                window_rect=(100, 100, 900, 700),
            )
        )


if __name__ == "__main__":
    unittest.main()
