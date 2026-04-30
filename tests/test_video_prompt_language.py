import unittest

from core.generation.video_prompts import _normalize_video_prompt_language


class VideoPromptLanguageTests(unittest.TestCase):
    def test_french_motion_prompt_is_normalized_to_english(self):
        prompt, changed = _normalize_video_prompt_language("elle bouge les bras et tourne la tete")

        self.assertTrue(changed)
        self.assertIn("she moves", prompt)
        self.assertIn("arms", prompt)
        self.assertIn("turns", prompt)
        self.assertIn("head", prompt)
        self.assertNotIn("elle", prompt.lower())
        self.assertNotIn(" les ", f" {prompt.lower()} ")

    def test_english_prompt_is_left_unchanged(self):
        prompt, changed = _normalize_video_prompt_language("she moves her arms and turns her head")

        self.assertFalse(changed)
        self.assertEqual(prompt, "she moves her arms and turns her head")


if __name__ == "__main__":
    unittest.main()
