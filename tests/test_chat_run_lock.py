import unittest

from web.routes.chat import _chat_run_key


class ChatRunLockTests(unittest.TestCase):
    def test_chat_run_key_uses_conversation_id(self):
        self.assertEqual(_chat_run_key("chat-1"), "chat:chat-1")

    def test_chat_run_key_has_global_fallback(self):
        self.assertEqual(_chat_run_key(""), "chat:global")


if __name__ == "__main__":
    unittest.main()
