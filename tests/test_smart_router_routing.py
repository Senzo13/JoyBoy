import unittest
import re
from unittest.mock import patch

from core.ai.text_model_router import invalidate_text_model_cache
from core.ai.smart_router import _find_text_model, analyze_request


class SmartRouterRoutingTests(unittest.TestCase):
    def setUp(self):
        invalidate_text_model_cache()

    def test_find_text_model_prefers_small_current_generation_router_model(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "models": [
                        {"name": "qwen2.5:1.5b"},
                        {"name": "qwen2.5:7b"},
                        {"name": "qwen3.5:2b"},
                    ]
                }

        with patch("core.ai.text_model_router.requests.get", return_value=FakeResponse()):
            self.assertEqual(_find_text_model(), "qwen3.5:2b")

    def test_find_text_model_does_not_auto_pick_7b_for_router(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "models": [
                        {"name": "qwen3.5:2b"},
                        {"name": "qwen2.5-coder:7b"},
                    ]
                }

        with patch("core.ai.text_model_router.requests.get", return_value=FakeResponse()):
            self.assertEqual(_find_text_model(), "qwen3.5:2b")

    def test_find_text_model_returns_qwen35_utility_instead_of_legacy_qwen25(self):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "models": [
                        {"name": "qwen2.5:1.5b"},
                        {"name": "qwen2.5:3b"},
                    ]
                }

        with patch("core.ai.text_model_router.requests.get", return_value=FakeResponse()):
            with patch("core.ai.text_model_router.pull_text_model", return_value=False):
                self.assertEqual(_find_text_model(), "qwen3.5:2b")

    def test_vague_llm_clothing_result_is_corrected_by_keyword_route(self):
        llm_response = "\n".join(
            [
                "INTENT: general_edit",
                "MASK: full",
                "STRENGTH: 0.95",
                "CONTROLNET: no",
                "IPADAPTER: no",
                "PROMPT: woman wearing a bikini outfit, same person, realistic clothing",
                "NEGATIVE: blurry, low quality",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "change d'habit, elle doit etre en bikini tres sexy",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "clothing_change")
        self.assertEqual(result["mask_strategy"], "clothes")
        self.assertTrue(result["needs_controlnet"])
        self.assertIn("bikini outfit", result["prompt_rewrite"])

    def test_dress_body_request_forces_opaque_clothing_pass(self):
        llm_response = "\n".join(
            [
                "INTENT: general_edit",
                "MASK: full",
                "STRENGTH: 0.78",
                "CONTROLNET: no",
                "IPADAPTER: no",
                "PROMPT: tasteful casual outfit covering torso and hips",
                "NEGATIVE: blurry, low quality",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "dress the person in a tasteful casual outfit covering torso and hips",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "clothing_change")
        self.assertEqual(result["mask_strategy"], "body")
        self.assertGreaterEqual(result["strength"], 0.86)
        self.assertLessEqual(result["controlnet_scale"], 0.45)
        self.assertFalse(result["needs_ip_adapter"])
        self.assertIn("opaque real fabric", result["prompt_rewrite"])
        self.assertIn("covered torso", result["prompt_rewrite"])
        self.assertIn("nude", result["negative_prompt"])
        self.assertIn("painted-on clothing", result["negative_prompt"])

    def test_regular_clothing_change_does_not_use_nudity_negative(self):
        llm_response = "\n".join(
            [
                "INTENT: clothing_change",
                "MASK: clothes",
                "STRENGTH: 0.78",
                "CONTROLNET: yes",
                "IPADAPTER: yes",
                "PROMPT: woman wearing a red dress, realistic fabric",
                "NEGATIVE: blurry, low quality",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "change outfit to a red dress",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "clothing_change")
        self.assertEqual(result["mask_strategy"], "clothes")
        self.assertNotIn("clothing, clothes, fabric", result["negative_prompt"])
        self.assertIn("red dress", result["prompt_rewrite"])

    def test_nudity_shortcut_beats_repose_heuristic(self):
        with patch(
            "core.ai.edit_directives._llm_extract_prompt",
            return_value={
                "_provided": {"subject_reference", "pose_flags", "size"},
                "subject_reference": True,
                "pose_flags": ["all_fours"],
                "size": "smaller",
            },
        ):
            with patch("core.ai.smart_router._get_nudity_regex", return_value=re.compile(r"nude\b")):
                with patch("core.ai.smart_router.is_adult_runtime_available", return_value=True):
                    result = analyze_request(
                        "completely nude",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "nudity")
        self.assertEqual(result["mask_strategy"], "clothes")
        self.assertEqual(result["reason"], "nudity regex shortcut")

    def test_background_prompt_with_pose_preservation_routes_to_background(self):
        llm_response = "\n".join(
            [
                "INTENT: general_edit",
                "MASK: body",
                "STRENGTH: 0.95",
                "CONTROLNET: yes",
                "IPADAPTER: yes",
                "PROMPT: change background to a natural outdoor landscape",
                "NEGATIVE: blurry, low quality",
            ]
        )

        with patch(
            "core.ai.edit_directives._llm_extract_prompt",
            return_value={
                "_provided": {"subject_reference", "pose_flags", "size"},
                "subject_reference": True,
                "pose_flags": ["arms_down", "hands_chest"],
                "size": "smaller",
            },
        ):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "change background to a natural outdoor landscape, realistic depth, keep original pose unchanged",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "background_change")
        self.assertEqual(result["mask_strategy"], "background")
        self.assertFalse(result["needs_ip_adapter"])

    def test_lighting_prompt_with_keep_pose_routes_to_lighting(self):
        llm_response = "\n".join(
            [
                "INTENT: pose_change",
                "MASK: person",
                "STRENGTH: 0.95",
                "CONTROLNET: yes",
                "IPADAPTER: yes",
                "PROMPT: cinematic lighting, richer contrast",
                "NEGATIVE: blurry, low quality",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "cinematic lighting, richer contrast, natural skin tones, keep clothing and pose unchanged",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "lighting_change")
        self.assertEqual(result["mask_strategy"], "full")
        self.assertFalse(result["needs_ip_adapter"])

    def test_llm_can_route_read_only_image_analysis(self):
        llm_response = "\n".join(
            [
                "INTENT: image_analysis",
                "MASK: none",
                "STRENGTH: 0.0",
                "CONTROLNET: no",
                "IPADAPTER: no",
                "PROMPT: identify visible food and drink items",
                "NEGATIVE: none",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "quel nourriture tu vois sur l'image ?",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "image_analysis")
        self.assertEqual(result["mask_strategy"], "none")
        self.assertEqual(result["strength"], 0.0)
        self.assertFalse(result["needs_controlnet"])
        self.assertFalse(result["needs_ip_adapter"])

    def test_zero_strength_general_edit_is_not_sent_to_diffusion(self):
        llm_response = "\n".join(
            [
                "INTENT: general_edit",
                "MASK: full",
                "STRENGTH: 0.0",
                "CONTROLNET: no",
                "IPADAPTER: no",
                "PROMPT: analyze the image and identify visible food items",
                "NEGATIVE: none",
            ]
        )

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=llm_response):
                    result = analyze_request(
                        "quel nourriture tu vois sur l'image ?",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "image_analysis")
        self.assertEqual(result["mask_strategy"], "none")
        self.assertEqual(result["strength"], 0.0)

    def test_structured_llm_dict_routes_clothing_change(self):
        structured_response = {
            "intent": "clothing_change",
            "mask_strategy": "clothes",
            "strength": 0.82,
            "needs_controlnet": True,
            "needs_ip_adapter": True,
            "prompt_rewrite": "woman wearing a fitted red dress with realistic fabric folds",
            "negative_prompt": "blurry, low quality, deformed",
        }

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=structured_response):
                    result = analyze_request(
                        "change outfit to a fitted red dress",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "clothing_change")
        self.assertEqual(result["mask_strategy"], "clothes")
        self.assertTrue(result["needs_controlnet"])
        self.assertTrue(result["needs_ip_adapter"])
        self.assertIn("fitted red dress", result["prompt_rewrite"])
        self.assertIn("JSON schema validated", result["reason"])

    def test_structured_llm_json_string_routes_read_only_analysis(self):
        structured_response = """```json
{
  "intent": "image_analysis",
  "mask_strategy": "none",
  "strength": 0.0,
  "needs_controlnet": false,
  "needs_ip_adapter": false,
  "prompt_rewrite": "identify visible food and drink items",
  "negative_prompt": "none"
}
```"""

        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            with patch("core.ai.smart_router._find_text_model", return_value="fake-router"):
                with patch("core.ai.smart_router._call_llm", return_value=structured_response):
                    result = analyze_request(
                        "dis moi ce que tu vois a manger sur l'image",
                        image_b64="data:image/png;base64,abc",
                        has_brush_mask=False,
                    )

        self.assertEqual(result["intent"], "image_analysis")
        self.assertEqual(result["mask_strategy"], "none")
        self.assertEqual(result["strength"], 0.0)
        self.assertFalse(result["needs_controlnet"])
        self.assertFalse(result["needs_ip_adapter"])
        self.assertIn("JSON schema validated", result["reason"])


if __name__ == "__main__":
    unittest.main()
