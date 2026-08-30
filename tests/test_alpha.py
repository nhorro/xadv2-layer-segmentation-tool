import unittest

import numpy as np

from layer_segmentation.alpha import (
    apply_edge_cleanup,
    clip_to_box,
    compose_alpha,
    crop_rect,
    paint_alpha_disk,
)


class AlphaTests(unittest.TestCase):
    def test_box_clipping_clears_everything_outside_fractional_bounds(self):
        mask = np.ones((6, 8), dtype=bool)
        clipped = clip_to_box(mask, [2.2, 1.8, 5.1, 4.2])
        expected = np.zeros((6, 8), dtype=bool)
        expected[1:5, 2:6] = True
        np.testing.assert_array_equal(clipped, expected)

    def test_manual_override_is_distinct_from_no_override(self):
        sam = np.array([[True, False], [False, True]])
        manual = np.array([[-1, 255], [0, -1]], dtype=np.int16)
        np.testing.assert_array_equal(
            compose_alpha(sam, manual), np.array([[255, 255], [0, 255]], dtype=np.uint8)
        )

    def test_crop_rect_applies_margin_and_clamps(self):
        alpha = np.zeros((8, 10), dtype=np.uint8)
        alpha[1:4, 2:6] = 255
        self.assertEqual(crop_rect(alpha, threshold=10, margin=2), (0, 0, 8, 6))

    def test_cleanup_is_non_destructive_and_erodes(self):
        alpha = np.zeros((7, 7), dtype=np.uint8)
        alpha[1:6, 1:6] = 255
        original = alpha.copy()
        cleaned = apply_edge_cleanup(alpha, erode_px=1)
        np.testing.assert_array_equal(alpha, original)
        self.assertEqual(int(np.count_nonzero(cleaned)), 9)

    def test_soft_brush_writes_partial_alpha_and_preserves_outside(self):
        base = np.full((9, 9), 255, dtype=np.uint8)
        manual = np.full((9, 9), -1, dtype=np.int16)
        paint_alpha_disk(base, manual, 4, 4, radius=4, feather_px=3, target_alpha=0)
        self.assertEqual(int(manual[4, 4]), 0)
        self.assertTrue(0 < int(manual[4, 7]) < 255)
        self.assertEqual(int(manual[0, 0]), -1)

    def test_radius_zero_brush_affects_exactly_one_pixel(self):
        base = np.full((5, 5), 255, dtype=np.uint8)
        manual = np.full((5, 5), -1, dtype=np.int16)
        paint_alpha_disk(base, manual, 2.8, 3.2, radius=0, feather_px=10, target_alpha=0)
        self.assertEqual(int(manual[3, 2]), 0)
        self.assertEqual(int(np.count_nonzero(manual >= 0)), 1)


if __name__ == "__main__":
    unittest.main()
