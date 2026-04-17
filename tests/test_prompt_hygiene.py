import unittest

from core.ai.prompt_ai import _preprocess_french_prompt
from core.generation import text2img
from core.generation.pose_skeletons import get_pose_prompts


class PromptHygieneTests(unittest.TestCase):
    def test_pose_prompts_do_not_inject_literal_camera_object(self):
        for pose in ("legs_up", "on_all_fours"):
            text2img_positive, _ = text2img._POSE_PROMPTS[pose]
            skeleton_positive, _ = get_pose_prompts(pose)

            self.assertNotIn("looking at camera", text2img_positive.lower())
            self.assertNotIn("looking at camera", skeleton_positive.lower())
            self.assertIn("viewer", text2img_positive.lower())
            self.assertIn("viewer", skeleton_positive.lower())

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

    def test_french_camera_look_translation_uses_viewer_wording(self):
        translated = _preprocess_french_prompt("regarde vers la camera, vue de face")
        self.assertIn("looking toward the viewer", translated)
        self.assertIn("front-facing view", translated)
        self.assertNotIn("looking at the camera", translated)
        self.assertNotIn("facing camera", translated)


if __name__ == "__main__":
    unittest.main()
