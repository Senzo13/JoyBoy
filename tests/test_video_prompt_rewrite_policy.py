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

    def test_high_vram_promotes_utility_model_to_deepseek(self):
        call_utility = Mock(return_value="PROMPT: continue the scene with natural visible motion")
        fake_utility = types.SimpleNamespace(_call_utility=call_utility)
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"core.utility_ai": fake_utility}):
            result = video_routes._rewrite_video_prompt_for_high_vram(
                "continue the scene naturally",
                chat_model="qwen3.5:2b",
                vram_gb=94,
            )

        self.assertEqual(result, "continue the scene with natural visible motion")
        self.assertEqual(call_utility.call_args.kwargs["model"], "deepseek-r1:14b")

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

    def test_refusal_or_meta_rewrite_falls_back_to_original_prompt(self):
        original = "continue the scene naturally"
        call_utility = Mock(
            return_value=(
                "The user is requesting an image-to-video model to generate content. "
                "To comply with ethical guidelines, I cannot fulfill this request."
            )
        )
        fake_utility = types.SimpleNamespace(_call_utility=call_utility)
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"core.utility_ai": fake_utility}):
            result = video_routes._rewrite_video_prompt_for_high_vram(
                original,
                chat_model="deepseek-r1:14b",
                vram_gb=94,
            )

        self.assertEqual(result, original)

    def test_high_end_wan_native_prefers_downloaded_lightx2v(self):
        models = {
            "wan-native-14b": {"name": "Wan Native"},
            "lightx2v-wan22-i2v-4step": {"backend": "lightx2v"},
        }
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(video_routes, "_video_model_downloaded", return_value=True):
            result = video_routes._prefer_lightx2v_high_end_model(
                "wan-native-14b",
                video_models=models,
                cache_dir="/tmp/cache",
                vram_gb=80,
            )

        self.assertEqual(result, "lightx2v-wan22-i2v-4step")

    def test_high_end_wan_repo_alias_prefers_downloaded_lightx2v(self):
        models = {
            "wan-native-14b": {"name": "Wan Native"},
            "lightx2v-wan22-i2v-4step": {"backend": "lightx2v"},
        }
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(video_routes, "_video_model_downloaded", return_value=True):
            result = video_routes._prefer_lightx2v_high_end_model(
                "Wan-AI/Wan2.2-I2V-A14B",
                video_models=models,
                cache_dir="/tmp/cache",
                vram_gb=80,
            )

        self.assertEqual(result, "lightx2v-wan22-i2v-4step")

    def test_high_end_wan_native_stays_native_when_lightx2v_missing(self):
        models = {
            "wan-native-14b": {"name": "Wan Native"},
            "lightx2v-wan22-i2v-4step": {"backend": "lightx2v"},
        }
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(video_routes, "_video_model_downloaded", return_value=False):
            result = video_routes._prefer_lightx2v_high_end_model(
                "wan-native-14b",
                video_models=models,
                cache_dir="/tmp/cache",
                vram_gb=80,
            )

        self.assertEqual(result, "wan-native-14b")


if __name__ == "__main__":
    unittest.main()
