from __future__ import annotations

import unittest

import torch

from core.models.runtime_env import (
    apply_mps_pipeline_optimizations,
    configure_huggingface_env,
    decode_sdxl_latents_with_mps_fallback,
    ensure_mps_sdxl_vae_ready_for_call,
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
                self.device = torch.device("cpu")
                self.config = type("Config", (), {"force_upcast": False})()

            def register_to_config(self, **kwargs) -> None:
                for key, value in kwargs.items():
                    setattr(self.config, key, value)

            def to(self, device=None, dtype=None):
                if device is not None:
                    self.device = torch.device(device)
                if dtype is not None:
                    self.dtype = dtype
                return self

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()
                self._execution_device = torch.device("mps")
                self.partial_upcast_called = False

            def upcast_vae(self) -> None:
                self.partial_upcast_called = True

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake", log_skip=False)
        pipe.upcast_vae()

        self.assertTrue(enabled)
        self.assertFalse(pipe.partial_upcast_called)
        self.assertEqual(pipe.vae.device.type, "mps")
        self.assertIs(pipe.vae.dtype, torch.float32)
        self.assertTrue(pipe.vae.config.force_upcast)
        self.assertTrue(pipe._joyboy_mps_full_vae_fp32_decode)

    def test_ensure_mps_sdxl_vae_ready_for_call_aligns_cpu_vae(self) -> None:
        class FakeParam:
            def __init__(self, device: str) -> None:
                self.device = torch.device(device)

        class FakeModule:
            def __init__(self, device: str, dtype=torch.float16) -> None:
                self.param = FakeParam(device)
                self.dtype = dtype

            def parameters(self):
                yield self.param

            def to(self, device=None, dtype=None):
                if device is not None:
                    self.param.device = torch.device(device)
                if dtype is not None:
                    self.dtype = dtype
                return self

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeModule("cpu")
                self.unet = FakeModule("mps")

        pipe = FakePipe()

        changed = ensure_mps_sdxl_vae_ready_for_call(pipe, "fake")

        self.assertTrue(changed)
        self.assertEqual(pipe.vae.param.device.type, "mps")
        self.assertIs(pipe.vae.dtype, torch.float32)

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

    def test_mps_pipeline_optimizations_upcast_attention_modules(self) -> None:
        class FakeAttention:
            def __init__(self) -> None:
                self.upcast_attention = False
                self.upcast_softmax = False

        class FakeUnet:
            def __init__(self) -> None:
                self.attn = FakeAttention()

            def modules(self):
                return [self.attn]

        class FakePipe:
            def __init__(self) -> None:
                self.vae = None
                self.unet = FakeUnet()

        pipe = FakePipe()

        enabled = apply_mps_pipeline_optimizations(pipe, "fake", log_skip=False)

        self.assertTrue(enabled)
        self.assertTrue(pipe.unet.attn.upcast_attention)
        self.assertTrue(pipe.unet.attn.upcast_softmax)
        self.assertTrue(pipe.unet._joyboy_mps_attention_upcast)

    def test_mps_sdxl_latent_decode_uses_fp32_scaling(self) -> None:
        class FakeProcessor:
            def postprocess(self, image, *args, **kwargs):
                return [image]

        class FakeVae:
            def __init__(self) -> None:
                self.param = torch.zeros(1, dtype=torch.float16)
                self.config = type("Config", (), {"scaling_factor": 0.5})()
                self.dtype = torch.float16

            def parameters(self):
                yield self.param

            def to(self, device=None, dtype=None):
                if dtype is not None:
                    self.dtype = dtype
                    self.param = self.param.to(dtype=dtype)
                return self

            def decode(self, latents, return_dict=False):
                return (latents.clone(),)

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()
                self.image_processor = FakeProcessor()

        pipe = FakePipe()
        result = decode_sdxl_latents_with_mps_fallback(pipe, torch.ones(1, 4, 2, 2), "fake")

        self.assertTrue(torch.isfinite(result).all().item())
        self.assertEqual(result.dtype, torch.float32)
        self.assertEqual(result[0, 0, 0, 0].item(), 2.0)
        self.assertEqual(pipe.vae.dtype, torch.float16)

    def test_mps_sdxl_latent_decode_retries_cpu_when_first_decode_is_non_finite(self) -> None:
        class FakeProcessor:
            def postprocess(self, image, *args, **kwargs):
                return [image]

        class FakeVae:
            def __init__(self) -> None:
                self.param = torch.zeros(1, dtype=torch.float16)
                self.config = type("Config", (), {"scaling_factor": 1.0})()
                self.dtype = torch.float16
                self.decode_calls = 0

            def parameters(self):
                yield self.param

            def to(self, device=None, dtype=None):
                if dtype is not None:
                    self.dtype = dtype
                    self.param = self.param.to(dtype=dtype)
                return self

            def decode(self, latents, return_dict=False):
                self.decode_calls += 1
                if self.decode_calls == 1:
                    return (torch.full_like(latents, float("nan")),)
                return (latents.clone(),)

        class FakePipe:
            def __init__(self) -> None:
                self.vae = FakeVae()
                self.image_processor = FakeProcessor()

        pipe = FakePipe()
        result = decode_sdxl_latents_with_mps_fallback(pipe, torch.ones(1, 4, 2, 2), "fake")

        self.assertEqual(pipe.vae.decode_calls, 2)
        self.assertTrue(torch.isfinite(result).all().item())
        self.assertEqual(pipe.vae.dtype, torch.float16)


if __name__ == "__main__":
    unittest.main()
