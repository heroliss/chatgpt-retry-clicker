import unittest
from pathlib import Path

import cv2
import numpy as np

import retry_clicker as clicker


class BannerDetectionTests(unittest.TestCase):
    def setUp(self):
        self.template = clicker.load_template()
        self.timed_template = clicker.load_image(clicker.TIMED_TEMPLATE_PATH)

    def test_exact_banner_is_detected(self):
        screen = np.full((140, 1000, 3), 7, dtype=np.uint8)
        x, y = 80, 24
        height, width = self.template.shape[:2]
        screen[y : y + height, x : x + width] = self.template

        self.assertEqual(
            clicker.find_banner(screen, self.template, self.timed_template),
            (x, y, clicker.CLICK_OFFSET_X, clicker.CLICK_OFFSET_Y),
        )

    def test_left_text_without_button_is_rejected(self):
        screen = np.full((140, 1000, 3), 7, dtype=np.uint8)
        x, y = 80, 24
        height, width = self.template.shape[:2]
        screen[y : y + height, x : x + clicker.LEFT_MATCH_WIDTH] = self.template[
            :, : clicker.LEFT_MATCH_WIDTH
        ]

        self.assertIsNone(clicker.find_banner(screen, self.template, None))

    def test_dark_message_is_rejected(self):
        screen = np.full((140, 1000, 3), 25, dtype=np.uint8)
        self.assertIsNone(
            clicker.find_banner(screen, self.template, self.timed_template)
        )


if __name__ == "__main__":
    unittest.main()
