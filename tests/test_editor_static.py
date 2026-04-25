from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class EditorStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_inpaint_edit_paints_skeleton_before_network_request(self):
        editor = self.read("web/static/js/editor.js")

        self.assertIn("function waitForEditorSkeletonPaint()", editor)
        self.assertIn("currentGenerationChatId = editChatId;", editor)
        self.assertIn("const editAbortSignal = editController.signal;", editor)
        self.assertIn("generationId: editGenerationId", editor)

        skeleton_index = editor.index("const editSkeletonId = addSkeletonMessage(")
        wait_index = editor.index("await waitForEditorSkeletonPaint();")
        request_index = editor.index("const result = await apiGeneration.generateEdit({")
        self.assertLess(skeleton_index, wait_index)
        self.assertLess(wait_index, request_index)


if __name__ == "__main__":
    unittest.main()
