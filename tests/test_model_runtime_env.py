from __future__ import annotations

import unittest

from core.models.runtime_env import (
    apply_mps_pipeline_optimizations,
    configure_huggingface_env,
    should_enable_hf_parallel_loading,
)


class ModelRuntimeEnvTest(unittest.TestCase):
    def test_parallel_loading_disabled_on_macos(self) -> None:
        self.assertFalse(should_enable_hf_parallel_loading("Darwin"))

    def test_parallel_loading_enabled_elsewhere(self) -> None:
        self.assertTrue(should_enable_hf_parallel_loading("Windows"))
        self.assertTrue(should_enable_hf_parallel_loading("Linux"))

    def test_configure_huggingface_env_sets_platform_policy(self) -> None:
        env: dict[str, str] = {}

        configure_huggingface_env("cache-dir", "token", system_name="Darwin", environ=env)

        self.assertEqual(env["HF_HOME"], "cache-dir")
        self.assertEqual(env["HF_TOKEN"], "token")
        self.assertEqual(env["HF_ENABLE_PARALLEL_LOADING"], "NO")

    def test_mps_pipeline_optimizations_enable_attention_slicing(self) -> None:
        class FakePipe:
            def __init__(self) -> None:
                self.attention_slicing_enabled = False

            def enable_attention_slicing(self) -> None:
                self.attention_slicing_enabled = True

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake")

        self.assertTrue(enabled)
        self.assertTrue(pipe.attention_slicing_enabled)

    def test_mps_pipeline_optimizations_handle_missing_hook(self) -> None:
        enabled = apply_mps_pipeline_optimizations(object(), "fake", log_skip=False)

        self.assertFalse(enabled)


if __name__ == "__main__":
    unittest.main()
