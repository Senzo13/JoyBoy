import unittest

from core.generation.video_prompts import _build_framepack_prompt


class FramePackPromptTests(unittest.TestCase):
    def test_default_prompt_does_not_inject_slow_motion(self):
        prompt, trimmed = _build_framepack_prompt("", fast=False)

        self.assertFalse(trimmed)
        self.assertNotIn("slow motion", prompt.lower())
        self.assertNotIn("no ", prompt.lower())

    def test_user_prompt_keeps_budget_and_active_motion_suffix(self):
        prompt, trimmed = _build_framepack_prompt(
            "elle leve la jambe gauche et tourne legerement la camera autour du sujet",
            fast=True,
        )

        self.assertFalse(trimmed)
        self.assertIn("full-speed progression", prompt)
        self.assertNotIn("slow motion", prompt.lower())


if __name__ == "__main__":
    unittest.main()
