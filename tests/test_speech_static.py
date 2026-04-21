from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SpeechStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_read_aloud_buttons_are_toggle_controls(self):
        chat = self.read("web/static/js/chat.js")

        self.assertIn("data-speak-target=", chat)
        self.assertIn("speakText('${msgId}', this)", chat)
        self.assertIn("speakText('chat-${msgId}', this)", chat)
        self.assertIn('aria-pressed="false"', chat)

    def test_speech_synthesis_can_be_cancelled(self):
        ui = self.read("web/static/js/ui.js")

        self.assertIn("let currentSpeechTargetId = null", ui)
        self.assertIn("function stopSpeaking", ui)
        self.assertIn("window.speechSynthesis.cancel()", ui)
        self.assertIn("currentSpeechTargetId === elementId", ui)
        self.assertIn("resetSpeechState", ui)
        self.assertIn("utterance.onend", ui)


if __name__ == "__main__":
    unittest.main()
