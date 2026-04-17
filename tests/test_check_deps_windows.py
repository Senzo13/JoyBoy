import unittest

from scripts import check_deps


class CheckDepsWindowsTests(unittest.TestCase):
    def test_pytorch_cuda_index_matches_supported_driver_ranges(self):
        original_has_cuda = check_deps.HAS_CUDA
        try:
            check_deps.HAS_CUDA = True
            self.assertEqual(
                check_deps.get_pytorch_cuda_index("12.6"),
                "https://download.pytorch.org/whl/cu124",
            )
            self.assertEqual(
                check_deps.get_pytorch_cuda_index("12.1"),
                "https://download.pytorch.org/whl/cu121",
            )
            self.assertEqual(
                check_deps.get_pytorch_cuda_index("11.8"),
                "https://download.pytorch.org/whl/cu118",
            )
        finally:
            check_deps.HAS_CUDA = original_has_cuda

    def test_pytorch_cuda_index_is_none_without_nvidia_gpu(self):
        original_has_cuda = check_deps.HAS_CUDA
        try:
            check_deps.HAS_CUDA = False
            self.assertIsNone(check_deps.get_pytorch_cuda_index("12.6"))
        finally:
            check_deps.HAS_CUDA = original_has_cuda


if __name__ == "__main__":
    unittest.main()
