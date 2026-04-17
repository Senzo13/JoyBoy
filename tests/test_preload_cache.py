import unittest
from unittest.mock import patch

from core.models import preload


class PreloadCacheTests(unittest.TestCase):
    def test_controlnet_ready_requires_quant_cache_and_base_weights(self):
        with patch("core.models.preload.is_quantized_cached", return_value=True), \
             patch("core.models.preload._is_controlnet_base_cached", return_value=False):
            self.assertFalse(preload.is_controlnet_depth_ready())

        with patch("core.models.preload.is_quantized_cached", return_value=True), \
             patch("core.models.preload._is_controlnet_base_cached", return_value=True):
            self.assertTrue(preload.is_controlnet_depth_ready())

    def test_preload_report_does_not_claim_controlnet_ready_with_only_quant_cache(self):
        def fake_quant(name, quant):
            return True

        with patch("core.models.preload._should_preload_image_assets", return_value=True), \
             patch("core.models.preload.is_quantized_cached", side_effect=fake_quant), \
             patch("core.models.preload._is_controlnet_base_cached", return_value=False), \
             patch("core.models.preload._is_hf_file_cached", return_value=True):
            report = preload.get_preload_cache_report()

        controlnet = next(item for item in report["required"] if item["id"] == "controlnet_depth")
        self.assertFalse(controlnet["cached"])
        self.assertEqual(controlnet["kind"], "quantized+download")

    def test_preload_report_skips_heavy_image_assets_without_accelerator(self):
        with patch("core.models.preload._should_preload_image_assets", return_value=False):
            report = preload.get_preload_cache_report()

        self.assertTrue(report["ready"])
        self.assertTrue(report["skipped"])
        self.assertEqual(report["skip_reason"], "no_cuda_or_mps")
        self.assertEqual(report["required"], [])


if __name__ == "__main__":
    unittest.main()
