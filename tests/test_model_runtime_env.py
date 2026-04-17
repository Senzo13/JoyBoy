from __future__ import annotations

import unittest

import torch

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
                self.vae = None

            def enable_attention_slicing(self) -> None:
                self.attention_slicing_enabled = True

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake")

        self.assertTrue(enabled)
        self.assertTrue(pipe.attention_slicing_enabled)

    def test_mps_pipeline_optimizations_handle_missing_hook(self) -> None:
        enabled = apply_mps_pipeline_optimizations(object(), "fake", log_skip=False)

        self.assertFalse(enabled)

    def test_mps_pipeline_optimizations_enable_vae_force_upcast(self) -> None:
        class FakeVae:
            def __init__(self) -> None:
                self.config = type("Config", (), {"force_upcast": False})()

            def register_to_config(self, **kwargs) -> None:
                for key, value in kwargs.items():
                    setattr(self.config, key, value)

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake", log_skip=False)

        self.assertTrue(enabled)
        self.assertTrue(pipe.vae.config.force_upcast)

    def test_mps_pipeline_optimizations_patch_full_vae_fp32_upcast(self) -> None:
        class FakeVae:
            def __init__(self) -> None:
                self.dtype = torch.float16
                self.config = type("Config", (), {"force_upcast": False})()

            def register_to_config(self, **kwargs) -> None:
                for key, value in kwargs.items():
                    setattr(self.config, key, value)

            def to(self, dtype=None):
                self.dtype = dtype
                return self

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()
                self.partial_upcast_called = False

            def upcast_vae(self) -> None:
                self.partial_upcast_called = True

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake", log_skip=False)
        pipe.upcast_vae()

        self.assertTrue(enabled)
        self.assertFalse(pipe.partial_upcast_called)
        self.assertIs(pipe.vae.dtype, torch.float32)
        self.assertTrue(pipe.vae.config.force_upcast)
        self.assertTrue(pipe._joyboy_mps_full_vae_fp32_decode)

    def test_mps_pipeline_optimizations_sanitize_non_finite_postprocess_pixels(self) -> None:
        class FakeProcessor:
            def postprocess(self, image, *args, **kwargs):
                return image

        class FakeVae:
            def __init__(self) -> None:
                self.config = type("Config", (), {"force_upcast": False})()

            def register_to_config(self, **kwargs) -> None:
                for key, value in kwargs.items():
                    setattr(self.config, key, value)

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()
                self.image_processor = FakeProcessor()

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake", log_skip=False)
        result = pipe.image_processor.postprocess(torch.tensor([float("nan"), float("inf"), -float("inf"), 0.5]))

        self.assertTrue(enabled)
        self.assertTrue(torch.isfinite(result).all().item())
        self.assertEqual(result.tolist(), [0.0, 1.0, -1.0, 0.5])


if __name__ == "__main__":
    unittest.main()
