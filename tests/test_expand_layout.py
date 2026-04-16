import unittest

from core.generation.transforms import _resolve_expand_canvas, _resolve_expand_layout


class ExpandLayoutTests(unittest.TestCase):
    def test_small_images_are_expanded_conservatively(self):
        fill_ratio, effective_ratio, small_source = _resolve_expand_layout(560, 800, 1.5)

        self.assertTrue(small_source)
        self.assertEqual(effective_ratio, 1.28)
        self.assertGreaterEqual(fill_ratio, 0.78)

    def test_large_images_keep_requested_ratio(self):
        fill_ratio, effective_ratio, small_source = _resolve_expand_layout(1024, 1024, 1.5)

        self.assertFalse(small_source)
        self.assertEqual(effective_ratio, 1.5)
        self.assertAlmostEqual(fill_ratio, 1 / 1.5)

    def test_small_portrait_canvas_keeps_portrait_layout(self):
        target_w, target_h, image_w, image_h, effective_ratio, small_source = _resolve_expand_canvas(
            608,
            808,
            1.5,
        )

        self.assertTrue(small_source)
        self.assertEqual(effective_ratio, 1.28)
        self.assertLess(target_w, target_h)
        self.assertGreaterEqual(target_w, image_w + 64)
        self.assertGreaterEqual(target_h, image_h + 64)
        self.assertNotEqual(target_w, target_h)


if __name__ == "__main__":
    unittest.main()
