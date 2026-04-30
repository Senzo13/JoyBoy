import os
import unittest
from unittest.mock import patch

from core.models.video_policy import (
    HIGH_END_VIDEO_LIMIT_GB,
    LOW_VRAM_SAFE_DEFAULT,
    build_video_model_catalog,
    get_runtime_video_defaults,
    resolve_video_model_for_runtime,
)


class VideoPolicyTests(unittest.TestCase):
    def test_cogvideox_reroutes_on_low_vram(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = resolve_video_model_for_runtime("cogvideox", vram_gb=8)

        self.assertEqual(decision.model, LOW_VRAM_SAFE_DEFAULT)
        self.assertTrue(decision.changed)
        self.assertIn("pas encore un profil rapide et fiable", decision.warning)

    def test_cogvideox_can_be_forced_with_env(self):
        with patch.dict(os.environ, {"JOYBOY_ALLOW_EXPERIMENTAL_VIDEO": "1"}, clear=True):
            decision = resolve_video_model_for_runtime("cogvideox", vram_gb=8)

        self.assertEqual(decision.model, "cogvideox")
        self.assertFalse(decision.changed)

    def test_cogvideox_can_be_forced_from_ui(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = resolve_video_model_for_runtime("cogvideox", vram_gb=8, allow_experimental=True)

        self.assertEqual(decision.model, "cogvideox")
        self.assertFalse(decision.changed)

    def test_ltx_reroutes_on_low_vram(self):
        decision = resolve_video_model_for_runtime("ltx", vram_gb=8)

        self.assertEqual(decision.model, LOW_VRAM_SAFE_DEFAULT)
        self.assertTrue(decision.changed)

    def test_framepack_reroutes_on_low_vram_without_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = resolve_video_model_for_runtime("framepack", vram_gb=8)

        self.assertEqual(decision.model, LOW_VRAM_SAFE_DEFAULT)
        self.assertTrue(decision.changed)
        self.assertIn("pas encore un profil rapide et fiable", decision.warning)
        self.assertIn("Pour forcer", decision.warning)

    def test_framepack_can_be_forced_from_ui(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = resolve_video_model_for_runtime("framepack", vram_gb=8, allow_experimental=True)

        self.assertEqual(decision.model, "framepack")
        self.assertFalse(decision.changed)

    def test_catalog_hides_low_vram_advanced_models_by_default(self):
        models = {
            "ltx": {"name": "LTX", "low_vram_tier": "recommended", "supports_image": True},
            "svd": {"name": "SVD", "low_vram_tier": "recommended", "supports_image": True},
            "cogvideox": {"name": "Cog", "experimental_low_vram": True, "supports_image": True},
            "wan": {"name": "Wan", "low_vram_tier": "advanced", "supports_image": True},
        }

        catalog = build_video_model_catalog(models, vram_gb=8)
        visible_ids = {model["id"] for model in catalog["models"]}
        advanced_ids = {model["id"] for model in catalog["advanced_models"]}

        self.assertEqual(visible_ids, {"ltx", "svd"})
        self.assertEqual(advanced_ids, {"cogvideox", "wan"})
        self.assertEqual(catalog["advanced_count"], 2)
        self.assertEqual(catalog["default_model"], LOW_VRAM_SAFE_DEFAULT)

    def test_low_vram_defaults_are_conservative(self):
        catalog = build_video_model_catalog(
            {
                "svd": {
                    "name": "SVD",
                    "low_vram_tier": "recommended",
                    "supports_image": True,
                    "default_frames": 25,
                    "default_steps": 25,
                    "default_fps": 8,
                },
                "ltx": {
                    "name": "LTX",
                    "low_vram_tier": "advanced",
                    "supports_image": True,
                    "default_frames": 97,
                    "default_steps": 30,
                    "default_fps": 24,
                },
            },
            vram_gb=8,
            include_advanced=True,
        )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertEqual(by_id["svd"]["default_frames"], 18)
        self.assertEqual(by_id["svd"]["default_steps"], 10)
        self.assertEqual(by_id["svd"]["default_fps"], 8)
        self.assertEqual(by_id["ltx"]["default_frames"], 41)
        self.assertEqual(by_id["ltx"]["default_steps"], 8)
        self.assertEqual(by_id["ltx"]["default_fps"], 8)

    def test_catalog_marks_framepack_as_manual_test_model(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = build_video_model_catalog(
                {
                    "svd": {"name": "SVD", "low_vram_tier": "recommended", "supports_image": True},
                    "framepack": {
                        "name": "FramePack",
                        "low_vram_tier": "advanced",
                        "supports_image": True,
                        "supports_prompt": True,
                        "experimental_low_vram": True,
                        "backend_status": "experimental",
                    },
                },
                vram_gb=8,
                include_advanced=True,
            )

        visible_ids = {model["id"] for model in catalog["models"]}
        advanced_ids = {model["id"] for model in catalog["advanced_models"]}

        self.assertIn("framepack", visible_ids)
        self.assertIn("framepack", advanced_ids)
        self.assertEqual(catalog["roadmap_count"], 0)
        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertEqual(by_id["framepack"]["category"], "try")
        self.assertEqual(by_id["framepack"]["backend_status"], "experimental")
        self.assertEqual(by_id["framepack"]["launch_status"], "manual_test")
        self.assertTrue(by_id["framepack"]["requires_experimental_env"])
        self.assertTrue(by_id["framepack"]["override_required"])

    def test_catalog_marks_manual_test_models(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = build_video_model_catalog(
                {
                    "svd": {"name": "SVD", "low_vram_tier": "recommended", "supports_image": True},
                    "ltx": {
                        "name": "LTX",
                        "low_vram_tier": "advanced",
                        "supports_image": True,
                        "supports_prompt": True,
                        "experimental_low_vram": True,
                        "backend_status": "experimental",
                    },
                },
                vram_gb=8,
                include_advanced=True,
            )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertEqual(by_id["ltx"]["category"], "try")
        self.assertEqual(by_id["ltx"]["launch_status"], "manual_test")
        self.assertTrue(by_id["ltx"]["requires_experimental_env"])
        self.assertTrue(by_id["ltx"]["override_required"])

    def test_catalog_ui_advanced_enables_manual_test_models(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = build_video_model_catalog(
                {
                    "svd": {"name": "SVD", "low_vram_tier": "recommended", "supports_image": True},
                    "ltx": {
                        "name": "LTX",
                        "low_vram_tier": "advanced",
                        "supports_image": True,
                        "supports_prompt": True,
                        "experimental_low_vram": True,
                        "backend_status": "experimental",
                    },
                },
                vram_gb=8,
                include_advanced=True,
                allow_experimental=True,
            )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertTrue(by_id["ltx"]["experimental_enabled"])
        self.assertFalse(by_id["ltx"]["override_required"])

    def test_runtime_defaults_apply_low_vram_overrides(self):
        defaults = get_runtime_video_defaults(
            "svd",
            {"default_frames": 120, "default_steps": 30, "default_fps": 24},
            vram_gb=8,
        )

        self.assertEqual(defaults, {"default_frames": 18, "default_steps": 10, "default_fps": 8})

    def test_framepack_fast_low_vram_defaults(self):
        defaults = get_runtime_video_defaults(
            "framepack-fast",
            {"default_frames": 90, "default_steps": 9, "default_fps": 18},
            vram_gb=8,
        )

        self.assertEqual(defaults, {"default_frames": 60, "default_steps": 7, "default_fps": 12})

    def test_high_end_catalog_promotes_local_video_models(self):
        catalog = build_video_model_catalog(
            {
                "svd": {"name": "SVD", "supports_image": True},
                "wan-native-14b": {
                    "name": "Wan Native 14B",
                    "supports_image": True,
                    "supports_prompt": True,
                    "supports_i2v": True,
                    "supports_continue": True,
                    "recommended_for": ["high_end_video"],
                    "min_vram_gb": 24,
                    "min_ram_gb": 96,
                },
                "ltx2": {
                    "name": "LTX-2",
                    "supports_image": True,
                    "supports_prompt": True,
                    "supports_t2v": True,
                    "supports_continue": True,
                    "supports_audio_native": True,
                    "recommended_for": ["high_end_video", "audio_video"],
                },
            },
            vram_gb=HIGH_END_VIDEO_LIMIT_GB,
        )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertTrue(catalog["high_end_video"])
        self.assertEqual(catalog["default_model"], "wan-native-14b")
        self.assertEqual(by_id["wan-native-14b"]["category"], "recommended")
        self.assertTrue(by_id["wan-native-14b"]["supports_continue"])
        self.assertTrue(by_id["ltx2"]["supports_t2v"])
        self.assertTrue(by_id["ltx2"]["supports_audio_native"])

    def test_lightx2v_is_optional_and_does_not_take_over_default(self):
        catalog = build_video_model_catalog(
            {
                "wan-native-14b": {
                    "name": "Wan Native 14B",
                    "supports_image": True,
                    "supports_prompt": True,
                    "supports_continue": True,
                    "recommended_for": ["high_end_video"],
                    "min_vram_gb": 24,
                },
                "lightx2v-wan22-i2v-4step": {
                    "name": "LightX2V Wan 2.2 I2V 4-step",
                    "supports_image": True,
                    "supports_prompt": True,
                    "supports_continue": True,
                    "backend": "lightx2v",
                    "backend_status": "optional",
                    "recommended_for": ["high_end_video", "fast_quality_i2v"],
                    "min_vram_gb": 14,
                },
            },
            vram_gb=HIGH_END_VIDEO_LIMIT_GB,
        )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertEqual(catalog["default_model"], "lightx2v-wan22-i2v-4step")
        self.assertEqual(by_id["lightx2v-wan22-i2v-4step"]["launch_status"], "ready")
        self.assertEqual(by_id["lightx2v-wan22-i2v-4step"]["backend_status"], "optional")
        self.assertEqual(by_id["lightx2v-wan22-i2v-4step"]["category"], "recommended")

    def test_lightx2v_low_vram_profile_stays_manual_test_until_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = build_video_model_catalog(
                {
                    "svd": {"name": "SVD", "low_vram_tier": "recommended", "supports_image": True},
                    "lightx2v-wan22-i2v-8gb": {
                        "name": "LightX2V 8GB",
                        "supports_image": True,
                        "supports_prompt": True,
                        "supports_continue": True,
                        "backend": "lightx2v",
                        "backend_status": "optional",
                        "experimental_low_vram": True,
                        "low_vram_tier": "advanced",
                    },
                },
                vram_gb=8,
                include_advanced=True,
            )

        by_id = {model["id"]: model for model in catalog["models"]}
        self.assertEqual(by_id["lightx2v-wan22-i2v-8gb"]["category"], "try")
        self.assertEqual(by_id["lightx2v-wan22-i2v-8gb"]["launch_status"], "manual_test")
        self.assertTrue(by_id["lightx2v-wan22-i2v-8gb"]["override_required"])


if __name__ == "__main__":
    unittest.main()
