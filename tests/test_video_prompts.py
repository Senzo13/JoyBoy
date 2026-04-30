import unittest

from core.generation.video_prompts import _build_ltx2_negative_prompt, _build_video_negative_prompt


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

    def test_text_to_video_also_gets_realism_style_negative(self):
        negative = _build_video_negative_prompt(
            user_prompt="realistic handheld adult video",
            has_visual_source=False,
        )

        self.assertIn("anime", negative)
        self.assertIn("plastic skin", negative)

    def test_ltx2_gets_realism_style_negative_by_default(self):
        negative = _build_ltx2_negative_prompt(user_prompt="realistic person turning head")

        self.assertIn("still image", negative)
        self.assertIn("anime", negative)
        self.assertIn("plastic skin", negative)

    def test_ltx2_explicit_anime_prompt_does_not_block_anime(self):
        negative = _build_ltx2_negative_prompt(user_prompt="anime manga character motion")

        self.assertIn("still image", negative)
        self.assertNotIn("anime, manga", negative)


if __name__ == "__main__":
    unittest.main()
