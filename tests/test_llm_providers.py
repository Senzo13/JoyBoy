from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from unittest.mock import Mock, patch


class LLMProviderCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("JOYBOY_HOME")
        self.saved_env = {
            key: os.environ.get(key)
            for key in (
                "OPENAI_API_KEY",
                "OPENROUTER_API_KEY",
                "DEEPSEEK_API_KEY",
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
                "MOONSHOT_API_KEY",
                "VOLCENGINE_API_KEY",
                "ZHIPU_API_KEY",
                "VLLM_API_KEY",
                "GLM_BASE_URL",
                "VLLM_BASE_URL",
            )
        }
        os.environ["JOYBOY_HOME"] = self.temp_home.name
        for key in self.saved_env:
            os.environ.pop(key, None)

        import core.infra.local_config as local_config
        import core.agent_runtime.model_client as model_client

        self.local_config = importlib.reload(local_config)
        self.model_client = importlib.reload(model_client)

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("JOYBOY_HOME", None)
        else:
            os.environ["JOYBOY_HOME"] = self.previous_home
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import core.infra.local_config as local_config
        import core.agent_runtime.model_client as model_client

        importlib.reload(local_config)
        importlib.reload(model_client)
        self.temp_home.cleanup()

    def test_cloud_prefix_does_not_capture_ollama_colon_models(self) -> None:
        provider_id, provider_model = self.model_client.split_cloud_model_name("qwen3.5:2b")

        self.assertIsNone(provider_id)
        self.assertEqual(provider_model, "qwen3.5:2b")

    def test_cloud_prefix_detects_known_provider(self) -> None:
        provider_id, provider_model = self.model_client.split_cloud_model_name("openai:gpt-test")

        self.assertEqual(provider_id, "openai")
        self.assertEqual(provider_model, "gpt-test")

        provider_id, provider_model = self.model_client.split_cloud_model_name("glm:glm-5.1")
        self.assertEqual(provider_id, "glm")
        self.assertEqual(provider_model, "glm-5.1")

    def test_provider_catalog_marks_env_key_configured(self) -> None:
        catalog = self.model_client.get_llm_provider_catalog()
        openai = next(provider for provider in catalog if provider["id"] == "openai")
        self.assertFalse(openai["configured"])

        os.environ["OPENAI_API_KEY"] = "sk-test"
        catalog = self.model_client.get_llm_provider_catalog()
        openai = next(provider for provider in catalog if provider["id"] == "openai")

        self.assertTrue(openai["configured"])

    def test_provider_status_marks_asset_and_llm_scopes(self) -> None:
        providers = self.local_config.get_provider_status()
        by_key = {provider["key"]: provider for provider in providers}

        self.assertEqual(by_key["HF_TOKEN"]["scope"], "assets")
        self.assertEqual(by_key["CIVITAI_API_KEY"]["scope"], "assets")
        self.assertEqual(by_key["OPENAI_API_KEY"]["scope"], "llm")
        self.assertEqual(by_key["OPENROUTER_API_KEY"]["scope"], "llm")
        self.assertEqual(by_key["ZHIPU_API_KEY"]["scope"], "llm")
        self.assertIn("api-keys", by_key["OPENAI_API_KEY"]["key_url"])
        self.assertIn("models", by_key["OPENAI_API_KEY"]["models_url"])

    def test_provider_status_exposes_access_modes(self) -> None:
        providers = self.local_config.get_provider_status()
        by_key = {provider["key"]: provider for provider in providers}

        openai = by_key["OPENAI_API_KEY"]
        self.assertEqual(openai["provider_id"], "openai")
        self.assertEqual(openai["auth_mode"], "api_key")
        self.assertTrue(openai["auth_uses_api_key"])
        self.assertIn("api_key", {mode["id"] for mode in openai["auth_modes"]})
        self.assertIn("codex_cli", {mode["id"] for mode in openai["auth_modes"]})

    def test_subscription_access_mode_blocks_direct_api_fallback(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        self.local_config.set_provider_auth_mode("openai", "codex_cli")

        catalog = self.model_client.get_llm_provider_catalog()
        openai = next(provider for provider in catalog if provider["id"] == "openai")

        self.assertFalse(openai["configured"])
        self.assertEqual(openai["auth_mode"], "codex_cli")
        self.assertFalse(openai["auth_uses_api_key"])

        with patch("core.agent_runtime.model_client.requests.post") as post:
            with self.assertRaises(self.model_client.CloudModelError) as raised:
                self.model_client.chat_with_cloud_model(
                    "openai:gpt-test",
                    messages=[{"role": "user", "content": "hi"}],
                )

        post.assert_not_called()
        self.assertIn("will not use OPENAI_API_KEY", str(raised.exception))

    def test_terminal_model_profiles_include_configured_cloud_ids(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"

        profiles = self.model_client.get_terminal_model_profiles(configured_only=True)
        profile_ids = {profile["id"] for profile in profiles}

        self.assertIn("qwen3.5:2b", profile_ids)
        self.assertIn("openai:gpt-5.4-mini", profile_ids)
        self.assertIn("openai:gpt-5.4", profile_ids)
        self.assertIn("openai:gpt-5.2-codex", profile_ids)

        os.environ["ANTHROPIC_API_KEY"] = "anthropic-test"
        os.environ["GEMINI_API_KEY"] = "gemini-test"
        os.environ["ZHIPU_API_KEY"] = "zhipu-test"
        profiles = self.model_client.get_terminal_model_profiles(configured_only=True)
        profile_ids = {profile["id"] for profile in profiles}

        self.assertIn("anthropic:claude-sonnet-4-5", profile_ids)
        self.assertIn("gemini:gemini-2.0-flash", profile_ids)
        self.assertIn("glm:glm-5.1", profile_ids)

    def test_terminal_model_profiles_can_discover_remote_openai_models(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "data": [
                {"id": "text-embedding-3-large"},
                {"id": "gpt-5.2-codex"},
                {"id": "gpt-5.4"},
                {"id": "gpt-image-1"},
            ]
        }

        with patch("core.agent_runtime.model_client.requests.get", return_value=fake_response) as get:
            profiles = self.model_client.get_terminal_model_profiles(
                configured_only=True,
                discover_remote=True,
            )

        openai_profiles = [profile for profile in profiles if profile["provider"] == "openai"]
        self.assertEqual([profile["model"] for profile in openai_profiles], ["gpt-5.4", "gpt-5.2-codex"])
        self.assertTrue(all(profile["discovered"] for profile in openai_profiles))
        self.assertEqual(openai_profiles[0]["model_source"], "remote")
        self.assertEqual(get.call_args.args[0], "https://api.openai.com/v1/models")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test")

    def test_terminal_model_profiles_limit_discovered_models_by_family(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "data": [
                {"id": "gpt-4.1-mini"},
                {"id": "gpt-5.4"},
                {"id": "gpt-5.4-mini", "created": 500},
                {"id": "gpt-5.3", "created": 400},
                {"id": "gpt-5.2", "created": 300},
                {"id": "gpt-5.1", "created": 200},
                {"id": "gpt-5.0", "created": 100},
                {"id": "gpt-5-old", "created": 1},
                {"id": "gpt-5.2-codex", "created": 600},
                {"id": "gpt-5.1-codex-mini", "created": 500},
                {"id": "text-embedding-3-large", "created": 999},
            ]
        }

        with patch("core.agent_runtime.model_client.requests.get", return_value=fake_response):
            profiles = self.model_client.get_terminal_model_profiles(
                configured_only=True,
                discover_remote=True,
            )

        openai_models = [profile["model"] for profile in profiles if profile["provider"] == "openai"]
        gpt_5_models = [model for model in openai_models if model.startswith("gpt-5") and "codex" not in model]

        self.assertEqual(len(gpt_5_models), 5)
        self.assertIn("gpt-5.4-mini", gpt_5_models)
        self.assertNotIn("gpt-5-old", gpt_5_models)
        self.assertIn("gpt-5.2-codex", openai_models)
        self.assertNotIn("text-embedding-3-large", openai_models)

    def test_terminal_model_profiles_fall_back_when_discovery_fails(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_response = Mock()
        fake_response.status_code = 401
        fake_response.text = "bad key"
        fake_response.reason = "Unauthorized"

        with patch("core.agent_runtime.model_client.requests.get", return_value=fake_response):
            profiles = self.model_client.get_terminal_model_profiles(
                configured_only=True,
                discover_remote=True,
            )

        openai_profiles = [profile for profile in profiles if profile["provider"] == "openai"]
        profile_ids = {profile["id"] for profile in openai_profiles}
        self.assertIn("openai:gpt-5.4", profile_ids)
        self.assertIn("openai:gpt-5.4-mini", profile_ids)
        self.assertTrue(all(not profile["discovered"] for profile in openai_profiles))
        self.assertTrue(any("401" in profile["discovery_error"] for profile in openai_profiles))

    def test_cloud_model_requires_key(self) -> None:
        with self.assertRaises(self.model_client.CloudModelError):
            self.model_client.chat_with_cloud_model(
                "openai:gpt-test",
                messages=[{"role": "user", "content": "hi"}],
            )

    def test_openai_compatible_chat_normalizes_tool_calls(self) -> None:
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "README.md"},
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }

        with patch("core.agent_runtime.model_client.requests.post", return_value=fake_response) as post:
            result = self.model_client.chat_with_cloud_model(
                "openai:gpt-test",
                messages=[{"role": "user", "content": "hi"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            )

        self.assertEqual(result["message"]["content"], "")
        self.assertEqual(result["message"]["tool_calls"][0]["id"], "call_123")
        self.assertEqual(result["prompt_eval_count"], 12)
        self.assertEqual(result["eval_count"], 5)
        request_kwargs = post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(request_kwargs["json"]["tools"][0]["function"]["name"], "read_file")

    def test_anthropic_chat_translates_tools_and_tool_results(self) -> None:
        os.environ["ANTHROPIC_API_KEY"] = "anthropic-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "content": [
                {"type": "text", "text": "Je vais lire."},
                {"type": "tool_use", "id": "toolu_123", "name": "read_file", "input": {"path": "README.md"}},
            ],
            "usage": {"input_tokens": 20, "output_tokens": 7},
        }

        with patch("core.agent_runtime.model_client.requests.post", return_value=fake_response) as post:
            result = self.model_client.chat_with_cloud_model(
                "anthropic:claude-sonnet-4-5",
                messages=[
                    {"role": "system", "content": "You are JoyBoy."},
                    {"role": "user", "content": "read"},
                    {"role": "tool", "tool_call_id": "toolu_prev", "tool_name": "list_files", "content": "README.md"},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "description": "Read a file",
                            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                        },
                    }
                ],
            )

        request_kwargs = post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["x-api-key"], "anthropic-test")
        self.assertEqual(request_kwargs["json"]["system"], "You are JoyBoy.")
        self.assertEqual(request_kwargs["json"]["tools"][0]["input_schema"]["type"], "object")
        self.assertEqual(request_kwargs["json"]["messages"][-1]["content"][0]["type"], "tool_result")
        self.assertIn("Je vais lire.", result["message"]["content"])
        self.assertEqual(result["message"]["tool_calls"][0]["id"], "toolu_123")
        self.assertEqual(result["prompt_eval_count"], 20)
        self.assertEqual(result["eval_count"], 7)

    def test_gemini_chat_translates_function_calls(self) -> None:
        os.environ["GEMINI_API_KEY"] = "gemini-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Je regarde."},
                            {"functionCall": {"name": "list_files", "args": {"path": "."}}},
                        ]
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 5},
        }

        with patch("core.agent_runtime.model_client.requests.post", return_value=fake_response) as post:
            result = self.model_client.chat_with_cloud_model(
                "gemini:gemini-2.0-flash",
                messages=[
                    {"role": "system", "content": "You are JoyBoy."},
                    {"role": "user", "content": "list"},
                    {"role": "tool", "tool_name": "read_file", "content": "hello"},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "description": "List files",
                            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                        },
                    }
                ],
            )

        request_kwargs = post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["x-goog-api-key"], "gemini-test")
        self.assertIn("/models/gemini-2.0-flash:generateContent", post.call_args.args[0])
        self.assertEqual(request_kwargs["json"]["tools"][0]["functionDeclarations"][0]["name"], "list_files")
        self.assertEqual(request_kwargs["json"]["contents"][-1]["parts"][0]["functionResponse"]["name"], "read_file")
        self.assertIn("Je regarde.", result["message"]["content"])
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["name"], "list_files")
        self.assertEqual(result["prompt_eval_count"], 11)
        self.assertEqual(result["eval_count"], 5)

    def test_glm_uses_openai_compatible_zhipu_endpoint(self) -> None:
        os.environ["ZHIPU_API_KEY"] = "zhipu-test"
        fake_response = Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }

        with patch("core.agent_runtime.model_client.requests.post", return_value=fake_response) as post:
            result = self.model_client.chat_with_cloud_model(
                "glm:glm-5.1",
                messages=[{"role": "user", "content": "hi"}],
            )

        self.assertEqual(post.call_args.args[0], "https://open.bigmodel.cn/api/paas/v4/chat/completions")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer zhipu-test")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "glm-5.1")
        self.assertEqual(result["message"]["content"], "ok")


if __name__ == "__main__":
    unittest.main()
