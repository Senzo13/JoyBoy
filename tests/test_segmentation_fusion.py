import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from core.generation import segmentation as segmentation_mod
from core.generation.segmentation import _filter_fusion_outliers


def _mask_with_pixels(count: int, size: int = 100) -> np.ndarray:
    mask = np.zeros((size,), dtype=np.uint8)
    mask[:count] = 255
    return mask.reshape((10, 10))


def _fusion_result(name: str, active: bool = True):
    mask = np.zeros((4, 4), dtype=np.uint8)
    if active:
        mask[0, 0] = 255
    empty = np.zeros((4, 4), dtype=np.uint8)
    return name, mask, 6.25 if active else 0.0, empty, empty, None


class _FakeCv2:
    @staticmethod
    def dilate(mask, _kernel, iterations=1):
        return mask


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

    def test_segment_fusion_uses_partial_results_after_timeout(self):
        import time

        def slow_b4(*_args, **_kwargs):
            time.sleep(0.2)
            return _fusion_result("b4", active=True)

        image = Image.new("RGB", (4, 4), "black")

        with patch.object(segmentation_mod, "_get_cv2", return_value=_FakeCv2()), \
             patch.object(segmentation_mod, "_publish_asset_download_progress"), \
             patch.object(segmentation_mod, "get_device", return_value="cpu"), \
             patch.object(segmentation_mod, "_run_b2", return_value=_fusion_result("b2", active=True)), \
             patch.object(segmentation_mod, "_run_b4", side_effect=slow_b4), \
             patch.object(segmentation_mod, "_run_schp", return_value=_fusion_result("schp", active=True)), \
             patch("core.models.runtime_env.get_segmentation_fusion_timeout_seconds", return_value=0.05):
            mask = segmentation_mod.segment_fusion(image, strategy="clothes", save_debug=False)

        self.assertGreater(np.array(mask).sum(), 0)

    def test_segment_fusion_falls_back_to_full_mask_when_all_workers_fail(self):
        def fail_worker(*_args, **_kwargs):
            raise RuntimeError("boom")

        image = Image.new("RGB", (4, 4), "black")

        with patch.object(segmentation_mod, "_get_cv2", return_value=_FakeCv2()), \
             patch.object(segmentation_mod, "_publish_asset_download_progress"), \
             patch.object(segmentation_mod, "get_device", return_value="cpu"), \
             patch.object(segmentation_mod, "_run_b2", side_effect=fail_worker), \
             patch.object(segmentation_mod, "_run_b4", side_effect=fail_worker), \
             patch.object(segmentation_mod, "_run_schp", side_effect=fail_worker):
            mask = segmentation_mod.segment_fusion(image, strategy="clothes", save_debug=False)

        self.assertTrue(np.all(np.array(mask) == 255))


if __name__ == "__main__":
    unittest.main()
