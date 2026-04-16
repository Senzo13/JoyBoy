import unittest

import numpy as np

from core.generation.segmentation import _filter_fusion_outliers


def _mask_with_pixels(count: int, size: int = 100) -> np.ndarray:
    mask = np.zeros((size,), dtype=np.uint8)
    mask[:count] = 255
    return mask.reshape((10, 10))


class SegmentationFusionTests(unittest.TestCase):
    def test_zero_b4_does_not_discard_positive_clothing_masks(self):
        logs = []
        masks = {
            "b2": _mask_with_pixels(12),
            "schp": _mask_with_pixels(18),
            "b4": _mask_with_pixels(0),
        }

        filtered, pcts = _filter_fusion_outliers(masks, row=lambda *args: logs.append(args))

        self.assertIn("b2", filtered)
        self.assertIn("schp", filtered)
        self.assertNotIn("b4", filtered)
        self.assertEqual(pcts["b4"], 0.0)
        self.assertTrue(any("B4" in entry[0] for entry in logs))

    def test_b2_can_still_be_removed_when_b4_has_real_signal(self):
        masks = {
            "b2": _mask_with_pixels(20),
            "schp": _mask_with_pixels(5),
            "b4": _mask_with_pixels(5),
        }

        filtered, _pcts = _filter_fusion_outliers(masks, row=lambda *_args: None)

        self.assertNotIn("b2", filtered)
        self.assertIn("schp", filtered)
        self.assertIn("b4", filtered)


if __name__ == "__main__":
    unittest.main()
