from __future__ import annotations

import unittest

import torch

from core.generation.callbacks import (
    make_fooocus_clamp_callback,
    make_soft_inpaint_callback,
)


class _FakeScheduler:
    def __init__(self) -> None:
        self.timesteps = torch.tensor([10, 5, 0], dtype=torch.int64)
        self.sigmas = torch.tensor([1.0, 0.5, 0.0])
        self.seen_add_noise = []
        self.convert_model_output = self._convert_model_output

    def add_noise(self, latents, noise, timestep):
        self.seen_add_noise.append(
            {
                "latents_device": latents.device,
                "latents_dtype": latents.dtype,
                "noise_device": noise.device,
                "noise_dtype": noise.dtype,
                "timestep_device": timestep.device,
            }
        )
        return latents + noise * 0.0

    def _convert_model_output(self, model_output, timestep=None, sample=None):
        return sample if sample is not None else model_output


class _FakePipe:
    def __init__(self) -> None:
        self.scheduler = _FakeScheduler()


class GenerationCallbackTests(unittest.TestCase):
    def test_fooocus_callback_aligns_captured_tensors_to_live_latents(self) -> None:
        pipe = _FakePipe()
        latents = torch.ones(1, 4, 2, 2, dtype=torch.float32)
        orig_latents = torch.zeros(1, 4, 2, 2, dtype=torch.float64)
        mask_latent = torch.ones(1, 1, 2, 2, dtype=torch.float64)
        callback = make_fooocus_clamp_callback(
            orig_latents,
            torch.zeros_like(orig_latents),
            mask_latent,
            seed=123,
        )

        result = callback(pipe, 0, pipe.scheduler.timesteps[0], {"latents": latents})

        self.assertEqual(result["latents"].dtype, latents.dtype)
        self.assertEqual(result["latents"].device, latents.device)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["latents_dtype"], latents.dtype)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["noise_dtype"], latents.dtype)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["latents_device"], latents.device)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["noise_device"], latents.device)

    def test_fooocus_scheduler_x0_blend_aligns_captured_tensors(self) -> None:
        pipe = _FakePipe()
        latents = torch.ones(1, 4, 2, 2, dtype=torch.float32)
        orig_latents = torch.zeros(1, 4, 2, 2, dtype=torch.float64)
        mask_latent = torch.ones(1, 1, 2, 2, dtype=torch.float64)
        callback = make_fooocus_clamp_callback(
            orig_latents,
            torch.zeros_like(orig_latents),
            mask_latent,
            seed=123,
        )

        callback(pipe, 0, pipe.scheduler.timesteps[0], {"latents": latents})
        x0 = pipe.scheduler.convert_model_output(
            torch.zeros_like(latents),
            pipe.scheduler.timesteps[0],
            sample=latents,
        )

        self.assertEqual(x0.dtype, latents.dtype)
        self.assertEqual(x0.device, latents.device)

    def test_fooocus_callback_keeps_adm_time_ids_on_live_latent_device(self) -> None:
        pipe = _FakePipe()
        latents = torch.ones(1, 4, 2, 2, dtype=torch.float32)
        orig_latents = torch.zeros(1, 4, 2, 2, dtype=torch.float64)
        mask_latent = torch.ones(1, 1, 2, 2, dtype=torch.float64)
        time_ids = torch.zeros(2, 6, dtype=torch.float64)
        callback = make_fooocus_clamp_callback(
            orig_latents,
            torch.zeros_like(orig_latents),
            mask_latent,
            seed=123,
        )

        result = callback(
            pipe,
            1,
            pipe.scheduler.timesteps[1],
            {"latents": latents, "add_time_ids": time_ids},
        )

        self.assertEqual(result["add_time_ids"].device, latents.device)
        self.assertEqual(result["add_time_ids"].dtype, latents.dtype)

    def test_soft_inpaint_callback_aligns_captured_tensors_to_live_latents(self) -> None:
        pipe = _FakePipe()
        latents = torch.ones(1, 4, 2, 2, dtype=torch.float32)
        orig_latents = torch.zeros(1, 4, 2, 2, dtype=torch.float64)
        noise = torch.zeros(1, 4, 2, 2, dtype=torch.float64)
        soft_mask_latent = torch.ones(1, 1, 2, 2, dtype=torch.float64)
        callback = make_soft_inpaint_callback(orig_latents, noise, soft_mask_latent)

        result = callback(pipe, 0, pipe.scheduler.timesteps[0], {"latents": latents})

        self.assertEqual(result["latents"].dtype, latents.dtype)
        self.assertEqual(result["latents"].device, latents.device)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["latents_dtype"], latents.dtype)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["noise_dtype"], latents.dtype)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["latents_device"], latents.device)
        self.assertEqual(pipe.scheduler.seen_add_noise[0]["noise_device"], latents.device)


if __name__ == "__main__":
    unittest.main()
