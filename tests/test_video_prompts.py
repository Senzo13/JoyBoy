import unittest

from core.generation.video_prompts import _build_video_negative_prompt


class VideoPromptTests(unittest.TestCase):
    def test_default_video_negative_blocks_stylized_look(self):
        negative = _build_video_negative_prompt(user_prompt="realistic handheld adult video")

        self.assertIn("anime", negative)
        self.assertIn("manga", negative)
        self.assertIn("cartoon", negative)

    def test_explicit_anime_video_prompt_does_not_block_anime(self):
        negative = _build_video_negative_prompt(user_prompt="anime manga style character animation")

        self.assertNotIn("anime, manga", negative)
        self.assertNotIn("cartoon, toon", negative)


if __name__ == "__main__":
    unittest.main()
