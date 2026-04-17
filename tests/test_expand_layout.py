import unittest

from core.generation.transforms import (
    _build_expand_binary_mask,
    _build_expand_prompts,
    _paste_with_edge_feather,
    _resolve_expand_canvas,
    _resolve_expand_layout,
)
from PIL import Image


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

    def test_expand_prompt_does_not_poison_positive_with_frame_tokens(self):
        positive, negative = _build_expand_prompts(
            "A woman outdoors with trees and sky in the background.",
        )

        forbidden_positive = ("no border", "no frame", "no inset", "photo frame", "picture frame")
        for token in forbidden_positive:
            self.assertNotIn(token, positive.lower())

        self.assertIn("continuous background", positive)
        self.assertIn("photo frame", negative)
        self.assertIn("hard rectangular edge", negative)

    def test_expand_mask_regenerates_source_edges(self):
        mask, overlap_px = _build_expand_binary_mask(
            target_w=768,
            target_h=1024,
            paste_x=130,
            paste_y=170,
            image_w=507,
            image_h=683,
        )

        self.assertGreaterEqual(overlap_px, 40)
        self.assertEqual(mask.getpixel((130, 170)), 255)
        self.assertEqual(mask.getpixel((130 + overlap_px + 10, 170 + overlap_px + 10)), 0)

    def test_feathered_paste_keeps_center_stronger_than_edge(self):
        canvas = Image.new("RGB", (100, 100), "black")
        source = Image.new("RGB", (60, 60), "white")

        _paste_with_edge_feather(canvas, source, (20, 20), 12)

        self.assertLess(canvas.getpixel((20, 20))[0], canvas.getpixel((50, 50))[0])
        self.assertGreater(canvas.getpixel((50, 50))[0], 240)


if __name__ == "__main__":
    unittest.main()
