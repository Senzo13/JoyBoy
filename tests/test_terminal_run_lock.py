import os
import unittest

from web.routes.terminal import _terminal_run_key


class TerminalRunLockTests(unittest.TestCase):
    def test_terminal_run_key_prefers_chat_id(self):
        self.assertEqual(_terminal_run_key("chat-1", "C:/repo"), "terminal:chat:chat-1")

    def test_terminal_run_key_falls_back_to_workspace(self):
        key = _terminal_run_key(None, ".")

        self.assertEqual(key, f"terminal:workspace:{os.path.normcase(os.path.abspath('.'))}")


if __name__ == "__main__":
    unittest.main()
