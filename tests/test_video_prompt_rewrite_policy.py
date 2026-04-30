import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from web.routes import video as video_routes


class VideoPromptRewritePolicyTests(unittest.TestCase):
    def test_low_vram_does_not_call_llm(self):
        call_utility = Mock()
        fake_utility = types.SimpleNamespace(_call_utility=call_utility)
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"core.utility_ai": fake_utility}):
            result = video_routes._rewrite_video_prompt_for_high_vram(
                "continue the scene naturally",
                chat_model="qwen3.5:2b",
                vram_gb=8,
            )

        self.assertEqual(result, "continue the scene naturally")
        call_utility.assert_not_called()

    def test_high_vram_uses_selected_chat_model(self):
        call_utility = Mock(return_value="PROMPT: continue the scene with natural visible motion")
        fake_utility = types.SimpleNamespace(_call_utility=call_utility)
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"core.utility_ai": fake_utility}):
            result = video_routes._rewrite_video_prompt_for_high_vram(
                "continue the scene naturally",
                chat_model="llama3.3:70b-instruct-q8_0",
                vram_gb=94,
            )

        self.assertEqual(result, "continue the scene with natural visible motion")
        self.assertEqual(call_utility.call_args.kwargs["model"], "llama3.3:70b-instruct-q8_0")

    def test_rewrite_can_be_disabled(self):
        call_utility = Mock()
        fake_utility = types.SimpleNamespace(_call_utility=call_utility)
        with patch.dict(os.environ, {"JOYBOY_VIDEO_PROMPT_REWRITE": "0"}, clear=True), \
                patch.dict(sys.modules, {"core.utility_ai": fake_utility}):
            result = video_routes._rewrite_video_prompt_for_high_vram(
                "continue the scene naturally",
                chat_model="llama3.3:70b-instruct-q8_0",
                vram_gb=94,
            )

        self.assertEqual(result, "continue the scene naturally")
        call_utility.assert_not_called()


if __name__ == "__main__":
    unittest.main()
