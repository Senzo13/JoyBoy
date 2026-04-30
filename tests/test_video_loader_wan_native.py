import os
import subprocess
import unittest
from unittest.mock import patch

from core.models import video_loader


class WanNativeInstallTests(unittest.TestCase):
    def _pip_commands(self, run_mock):
        return [call.args[0] for call in run_mock.call_args_list]

    def test_wan_native_install_skips_flash_attn_by_default_even_with_cuda_toolkit(self):
        with patch.dict(os.environ, {"CUDA_HOME": "/usr/local/cuda"}, clear=True), \
                patch("core.models.video_loader.shutil.which", return_value="/usr/local/cuda/bin/nvcc"), \
                patch("core.models.video_loader.subprocess.run") as run_mock:
            video_loader._install_wan_native_backend()

        commands = self._pip_commands(run_mock)
        joined = "\n".join(" ".join(command) for command in commands)

        self.assertNotIn("flash_attn", joined)
        self.assertIn("--no-deps git+https://github.com/Wan-Video/Wan2.2.git", joined)
        self.assertNotIn("--no-build-isolation git+https://github.com/Wan-Video/Wan2.2.git", joined)

    def test_wan_native_install_can_opt_into_flash_attn_without_full_wan_deps(self):
        with patch.dict(
            os.environ,
            {"CUDA_HOME": "/usr/local/cuda", "JOYBOY_WAN_NATIVE_INSTALL_FLASH_ATTN": "1"},
            clear=True,
        ), patch("core.models.video_loader.shutil.which", return_value="/usr/local/cuda/bin/nvcc"), \
                patch("core.models.video_loader.subprocess.run") as run_mock:
            video_loader._install_wan_native_backend()

        commands = self._pip_commands(run_mock)
        joined = "\n".join(" ".join(command) for command in commands)

        self.assertIn("--no-build-isolation flash_attn", joined)
        self.assertIn("--no-deps git+https://github.com/Wan-Video/Wan2.2.git", joined)
        self.assertNotIn("--no-build-isolation git+https://github.com/Wan-Video/Wan2.2.git", joined)

    def test_wan_native_install_continues_when_optional_flash_attn_fails(self):
        def fake_run(command, check):
            if "flash_attn" in command:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)

        with patch.dict(
            os.environ,
            {"CUDA_HOME": "/usr/local/cuda", "JOYBOY_WAN_NATIVE_INSTALL_FLASH_ATTN": "1"},
            clear=True,
        ), patch("core.models.video_loader.shutil.which", return_value="/usr/local/cuda/bin/nvcc"), \
                patch("core.models.video_loader.subprocess.run", side_effect=fake_run) as run_mock:
            video_loader._install_wan_native_backend()

        commands = self._pip_commands(run_mock)
        joined = "\n".join(" ".join(command) for command in commands)

        self.assertIn("--no-build-isolation flash_attn", joined)
        self.assertIn("--no-deps git+https://github.com/Wan-Video/Wan2.2.git", joined)


if __name__ == "__main__":
    unittest.main()
