from __future__ import annotations

import unittest

from windows_voice_typer.polling_input import _vk_codes_for_key


class PollingInputTests(unittest.TestCase):
    def test_alt_polling_checks_generic_and_left_right_alt(self) -> None:
        self.assertEqual(_vk_codes_for_key("alt"), (0x12, 0xA4, 0xA5))

    def test_modifier_polling_checks_left_and_right_variants(self) -> None:
        self.assertEqual(_vk_codes_for_key("ctrl"), (0x11, 0xA2, 0xA3))
        self.assertEqual(_vk_codes_for_key("shift"), (0x10, 0xA0, 0xA1))

    def test_function_key_uses_single_virtual_key(self) -> None:
        self.assertEqual(_vk_codes_for_key("f9"), (0x78,))


if __name__ == "__main__":
    unittest.main()
