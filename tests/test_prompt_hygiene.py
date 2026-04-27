import unittest

from core.ai.prompt_ai import _preprocess_french_prompt, build_full_prompt
from core.generation import text2img
from core.generation.pose_skeletons import get_pose_prompts
from core.generation.pose_prompts import build_human_pose_safety_additions


class PromptHygieneTests(unittest.TestCase):
    def test_pose_prompts_do_not_inject_literal_camera_object(self):
        for pose in ("legs_up", "on_all_fours"):
            text2img_positive, _ = text2img._POSE_PROMPTS[pose]
            skeleton_positive, _ = get_pose_prompts(pose)

            self.assertNotIn("looking at camera", text2img_positive.lower())
            self.assertNotIn("looking at camera", skeleton_positive.lower())

    def test_pose_prompt_aliases_stay_available(self):
        lying_down_positive, lying_down_negative = get_pose_prompts("lying_down")

        self.assertIn("supine", lying_down_positive.lower())
        self.assertIn("standing", lying_down_negative.lower())

    def test_human_pose_defaults_to_clothed_when_adult_pack_missing(self):
        positive, negative = build_human_pose_safety_additions(
            "Generate it for me",
            "legs_up",
            adult_runtime_available=False,
        )

        self.assertIn("fully clothed", positive.lower())
        self.assertIn("non-explicit", positive.lower())
        self.assertIn("nude", negative.lower())
        self.assertIn("exposed genitals", negative.lower())

    def test_human_pose_runtime_pack_relaxes_public_core_safety(self):
        positive, negative = build_human_pose_safety_additions(
            "Generate it for me",
            "legs_up",
            adult_runtime_available=True,
        )

        self.assertIsNone(positive)
        self.assertIsNone(negative)

    def test_explicit_adult_pose_requires_runtime_before_safety_is_relaxed(self):
        blocked_positive, blocked_negative = build_human_pose_safety_additions(
            "completely nude adult person",
            "legs_up",
            adult_runtime_available=False,
        )
        allowed_positive, allowed_negative = build_human_pose_safety_additions(
            "completely nude adult person",
            "legs_up",
            adult_runtime_available=True,
        )

        self.assertIn("fully clothed", blocked_positive.lower())
        self.assertIn("nude", blocked_negative.lower())
        self.assertIsNone(allowed_positive)
        self.assertIsNone(allowed_negative)

    def test_default_text2img_suppresses_visible_capture_devices(self):
        self.assertTrue(
            text2img._should_suppress_visible_capture_devices(
                "portrait photo", None, None
            )
        )
        self.assertFalse(
            text2img._should_suppress_visible_capture_devices(
                "phone selfie portrait", None, None
            )
        )

    def test_pose_distance_prompts_do_not_name_literal_camera(self):
        for positive, negative in text2img._POSE_DISTANCE_PROMPTS.values():
            combined = f"{positive}, {negative}".lower()
            self.assertNotIn("camera", combined)

        for positive, negative in text2img._POSE_ORIENTATION_PROMPTS.values():
            combined = f"{positive}, {negative}".lower()
            self.assertNotIn("camera", combined)

    def test_very_close_distance_removes_full_body_pose_conflict(self):
        legs_up, _ = get_pose_prompts("legs_up")
        adapted = text2img._adapt_pose_prompt_for_distance(legs_up, "very_close")

        self.assertIn("feet closer to viewer", adapted.lower())
        self.assertNotIn("full body visible", adapted.lower())

    def test_text2img_detects_preformatted_photo_prompt(self):
        self.assertTrue(
            text2img._looks_preformatted_text2img_prompt(
                "RAW photo, photorealistic, a train in motion"
            )
        )
        self.assertFalse(
            text2img._looks_preformatted_text2img_prompt(
                "imagine a train in motion"
            )
        )

    def test_text2img_keeps_photo_negative_for_stylized_model_without_style_request(self):
        negative = text2img._build_text2img_negative_prompt(
            "portrait photo of a woman",
            "Babes Illustrious By Stable Yogi (v5.5 FP16)",
        )

        self.assertIn("anime", negative.lower())
        self.assertIn("worst quality", negative.lower())

    def test_text2img_stylized_prompt_only_removes_conflicting_medium_terms(self):
        negative = text2img._build_text2img_negative_prompt(
            "a cosplay girl, hentai like, 3d anime",
            "Babes Illustrious By Stable Yogi (v5.5 FP16)",
        )

        self.assertNotIn("anime", negative.lower())
        self.assertNotIn("3d render", negative.lower())
        self.assertIn("worst quality", negative.lower())
        self.assertIn("bad anatomy", negative.lower())

    def test_french_camera_look_translation_uses_viewer_wording(self):
        translated = _preprocess_french_prompt("regarde vers la camera, vue de face")
        self.assertIn("looking toward the viewer", translated)
        self.assertIn("front-facing view", translated)
        self.assertNotIn("looking at the camera", translated)
        self.assertNotIn("facing camera", translated)

    def test_realistic_text2img_train_does_not_get_human_skin_tags(self):
        prompt, negative = build_full_prompt(
            "imagine a train in motion",
            "realistic",
            for_inpainting=False,
        )

        self.assertNotIn("natural skin", prompt.lower())
        self.assertNotIn("visible pores", prompt.lower())
        self.assertNotIn("matte skin", prompt.lower())
        self.assertNotIn("plastic skin", negative.lower())
        self.assertIn("photorealistic", prompt.lower())

    def test_realistic_model_train_is_not_treated_as_human_model(self):
        prompt, _ = build_full_prompt(
            "a detailed model train on rails",
            "realistic",
            for_inpainting=False,
        )

        self.assertNotIn("natural skin", prompt.lower())
        self.assertNotIn("visible pores", prompt.lower())

    def test_realistic_human_prompt_keeps_skin_texture_tags(self):
        prompt, negative = build_full_prompt(
            "portrait of a woman in soft light",
            "realistic",
            for_inpainting=False,
        )

        self.assertIn("natural skin texture", prompt.lower())
        self.assertIn("visible pores", prompt.lower())
        self.assertIn("plastic skin", negative.lower())


if __name__ == "__main__":
    unittest.main()
