from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VisualReferenceStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_chat_records_keep_last_visual_reference(self):
        db = self.read("web/static/js/db.js")

        self.assertIn("lastVisualReference: null", db)
        self.assertIn("extra.lastVisualReference", db)
        self.assertIn("cacheLastVisualReferenceForChat", db)

    def test_generation_reuses_previous_visual_reference(self):
        generation = self.read("web/static/js/generation.js")

        self.assertIn("function getConversationVisualReferenceForPrompt", generation)
        self.assertIn("function buildPromptWithVisualReference", generation)
        self.assertIn("rememberVisualReferenceForChat", generation)
        self.assertIn("style_ref: effectiveStyleRef", generation)
        self.assertIn("sourcePrompt: prompt", generation)

    def test_reference_prompt_keeps_user_visible_prompt_separate(self):
        generation = self.read("web/static/js/generation.js")

        self.assertIn("const generationPrompt = buildPromptWithVisualReference(prompt, conversationVisualReference)", generation)
        self.assertIn("prompt: generationPrompt", generation)
        self.assertIn("addMessageTxt2Img(prompt, modifiedImage", generation)


if __name__ == "__main__":
    unittest.main()
