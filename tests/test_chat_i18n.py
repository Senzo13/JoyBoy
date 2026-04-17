import unittest

from web.routes.chat import _chat_copy, _normalize_chat_locale


class ChatI18nTests(unittest.TestCase):
    def test_image_generate_pending_copy_uses_requested_locale(self):
        self.assertEqual(_chat_copy("image_generate_pending", "fr"), "Je génère cette image pour toi...")
        self.assertEqual(_chat_copy("image_generate_pending", "en"), "I'm generating this image for you...")
        self.assertEqual(_chat_copy("image_generate_pending", "es"), "Estoy generando esta imagen para ti...")
        self.assertEqual(_chat_copy("image_generate_pending", "it"), "Sto generando questa immagine per te...")

    def test_chat_locale_normalizes_browser_values(self):
        self.assertEqual(_normalize_chat_locale("en-US,en;q=0.9"), "en")
        self.assertEqual(_normalize_chat_locale("es_ES"), "es")
        self.assertEqual(_normalize_chat_locale("de-DE,de;q=0.9"), "fr")
        self.assertEqual(_normalize_chat_locale(""), "fr")


if __name__ == "__main__":
    unittest.main()
