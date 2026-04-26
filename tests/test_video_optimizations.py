import unittest
from unittest.mock import patch

from core.generation.video_optimizations import (
    apply_optimized_offload,
    is_cuda_oom_error,
    temporary_env,
)


class WanImageToVideoPipeline:
    def __init__(self, transformer_2=None):
        self.transformer = None
        self.transformer_2 = transformer_2
        self.device = None
        self.cpu_offload = False

    def to(self, device):
        self.device = device
        return self

    def enable_model_cpu_offload(self):
        self.cpu_offload = True


class VideoOptimizationTests(unittest.TestCase):
    def test_empty_secondary_transformer_uses_gpu_direct_on_high_vram(self):
        pipe = WanImageToVideoPipeline(transformer_2=None)

        with patch.dict("os.environ", {"JOYBOY_VIDEO_FORCE_CPU_OFFLOAD": "", "JOYBOY_FASTWAN_FORCE_OFFLOAD": ""}):
            strategy = apply_optimized_offload(pipe, 39.5)

        self.assertEqual(strategy, "gpu_direct")
        self.assertEqual(pipe.device, "cuda")
        self.assertFalse(pipe.cpu_offload)

    def test_active_secondary_transformer_uses_offload_on_high_vram(self):
        pipe = WanImageToVideoPipeline(transformer_2=object())

        with patch.dict("os.environ", {"JOYBOY_VIDEO_FORCE_CPU_OFFLOAD": "", "JOYBOY_FASTWAN_FORCE_OFFLOAD": ""}):
            strategy = apply_optimized_offload(pipe, 39.5)

        self.assertEqual(strategy, "model_cpu_offload")
        self.assertTrue(pipe.cpu_offload)

    def test_fastwan_uses_gpu_direct_on_a100_40gb_class(self):
        pipe = WanImageToVideoPipeline(transformer_2=None)

        with patch.dict("os.environ", {"JOYBOY_FASTWAN_FORCE_OFFLOAD": "", "JOYBOY_FASTWAN_GPU_DIRECT": ""}):
            strategy = apply_optimized_offload(pipe, 39.5, model_type="fastwan")

        self.assertEqual(strategy, "gpu_direct")
        self.assertEqual(pipe.device, "cuda")

    def test_fastwan_uses_offload_below_40gb_class(self):
        pipe = WanImageToVideoPipeline(transformer_2=None)

        with patch.dict("os.environ", {"JOYBOY_FASTWAN_FORCE_OFFLOAD": "", "JOYBOY_FASTWAN_GPU_DIRECT": ""}):
            strategy = apply_optimized_offload(pipe, 38.5, model_type="fastwan")

        self.assertEqual(strategy, "model_cpu_offload")
        self.assertTrue(pipe.cpu_offload)

    def test_fastwan_offload_can_be_forced(self):
        pipe = WanImageToVideoPipeline(transformer_2=None)

        with patch.dict("os.environ", {"JOYBOY_FASTWAN_FORCE_OFFLOAD": "1"}):
            strategy = apply_optimized_offload(pipe, 39.5, model_type="fastwan")

        self.assertEqual(strategy, "model_cpu_offload")
        self.assertTrue(pipe.cpu_offload)

    def test_fastwan_gpu_direct_can_be_forced(self):
        pipe = WanImageToVideoPipeline(transformer_2=None)

        with patch.dict("os.environ", {"JOYBOY_FASTWAN_GPU_DIRECT": "1"}):
            strategy = apply_optimized_offload(pipe, 39.5, model_type="fastwan")

        self.assertEqual(strategy, "gpu_direct")
        self.assertEqual(pipe.device, "cuda")

    def test_cuda_oom_detection_matches_pytorch_message(self):
        exc = RuntimeError("CUDA out of memory. Tried to allocate 18.00 MiB.")

        self.assertTrue(is_cuda_oom_error(exc))
        self.assertFalse(is_cuda_oom_error(RuntimeError("regular failure")))

    def test_temporary_env_restores_values(self):
        with patch.dict("os.environ", {"JOYBOY_TEST_ENV": "old"}):
            with temporary_env({"JOYBOY_TEST_ENV": "new", "JOYBOY_TEMP_ENV": "1"}):
                import os
                self.assertEqual(os.environ["JOYBOY_TEST_ENV"], "new")
                self.assertEqual(os.environ["JOYBOY_TEMP_ENV"], "1")
            self.assertEqual(os.environ["JOYBOY_TEST_ENV"], "old")
            self.assertNotIn("JOYBOY_TEMP_ENV", os.environ)


if __name__ == "__main__":
    unittest.main()
