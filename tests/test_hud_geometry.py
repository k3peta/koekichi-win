from __future__ import annotations

import unittest

from windows_voice_typer.hud_geometry import choose_hud_position_near_rect


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


if __name__ == "__main__":
    unittest.main()
