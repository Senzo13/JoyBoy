from __future__ import annotations

import unittest
from unittest.mock import patch

import torch

from core.generation import preview


class _FakeMpsBackend:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class PreviewRuntimeTest(unittest.TestCase):
    def test_preview_decoder_prefers_cuda(self) -> None:
        with patch.object(preview.torch.cuda, "is_available", return_value=True):
            device, dtype = preview._get_preview_device_and_dtype()

        self.assertEqual(device, "cuda")
        self.assertIs(dtype, torch.float16)

    def test_preview_decoder_uses_mps_without_cuda(self) -> None:
        with patch.object(preview.torch.cuda, "is_available", return_value=False):
            with patch.object(preview.torch.backends, "mps", _FakeMpsBackend(True), create=True):
                device, dtype = preview._get_preview_device_and_dtype()

        self.assertEqual(device, "mps")
        self.assertIs(dtype, torch.float16)

    def test_preview_decoder_uses_float32_on_cpu(self) -> None:
        with patch.object(preview.torch.cuda, "is_available", return_value=False):
            with patch.object(preview.torch.backends, "mps", _FakeMpsBackend(False), create=True):
                device, dtype = preview._get_preview_device_and_dtype()

        self.assertEqual(device, "cpu")
        self.assertIs(dtype, torch.float32)


if __name__ == "__main__":
    unittest.main()
