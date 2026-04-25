import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QueueStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_prompt_queue_is_docked_to_composer_not_floating(self):
        state_js = self.read("web/static/js/state.js")
        components_css = self.read("web/static/css/components.css")
        responsive_css = self.read("web/static/css/components-responsive.css")

        self.assertIn("function getActiveQueueComposerTarget()", state_js)
        self.assertIn("anchor.insertBefore(container, anchor.firstChild)", state_js)
        self.assertIn("function orientQueueItem(id)", state_js)
        self.assertIn("normalizeQueueImageSrc", state_js)
        self.assertNotIn("bubble.id = 'queue-bubble'", state_js)
        self.assertNotIn("queueMinimized", state_js)
        self.assertNotIn("function minimizeQueue", state_js)
        self.assertIn("PROMPT QUEUE — composer dock", components_css)
        self.assertIn("margin: 0 auto -10px;", components_css)
        self.assertIn("transform: translateY(2px);", components_css)
        self.assertIn("border-bottom-color: transparent;", components_css)
        self.assertIn(".chat-input-bar > .input-bar", components_css)
        self.assertIn(".queue-item.has-image", components_css)
        self.assertIn(".queue-thumb", components_css)
        self.assertIn("bottom: 8px;", components_css)
        self.assertIn("margin-bottom: -10px;", responsive_css)
        self.assertNotIn(".queue-bubble {", components_css)
        self.assertNotIn(".queue-bubble {", responsive_css)


if __name__ == "__main__":
    unittest.main()
