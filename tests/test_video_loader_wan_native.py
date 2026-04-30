import os
import subprocess
import sys
import types
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

    def test_wan_native_patches_attention_fallback_without_flash_attn(self):
        original = object()
        fallback = object()
        wan_module = types.ModuleType("wan")
        wan_modules = types.ModuleType("wan.modules")
        attention_module = types.ModuleType("wan.modules.attention")
        model_module = types.ModuleType("wan.modules.model")
        attention_module.FLASH_ATTN_2_AVAILABLE = False
        attention_module.FLASH_ATTN_3_AVAILABLE = False
        attention_module.flash_attention = original
        attention_module.attention = fallback
        model_module.flash_attention = original

        with patch.dict(sys.modules, {
            "wan": wan_module,
            "wan.modules": wan_modules,
            "wan.modules.attention": attention_module,
            "wan.modules.model": model_module,
        }):
            patched = video_loader._patch_wan_native_attention_fallback()

        self.assertTrue(patched)
        self.assertIs(attention_module.flash_attention, fallback)
        self.assertIs(model_module.flash_attention, fallback)

    def test_wan_native_keeps_flash_attention_when_available(self):
        original = object()
        fallback = object()
        wan_module = types.ModuleType("wan")
        wan_modules = types.ModuleType("wan.modules")
        attention_module = types.ModuleType("wan.modules.attention")
        model_module = types.ModuleType("wan.modules.model")
        attention_module.FLASH_ATTN_2_AVAILABLE = True
        attention_module.FLASH_ATTN_3_AVAILABLE = False
        attention_module.flash_attention = original
        attention_module.attention = fallback
        model_module.flash_attention = original

        with patch.dict(sys.modules, {
            "wan": wan_module,
            "wan.modules": wan_modules,
            "wan.modules.attention": attention_module,
            "wan.modules.model": model_module,
        }):
            patched = video_loader._patch_wan_native_attention_fallback()

        self.assertFalse(patched)
        self.assertIs(attention_module.flash_attention, original)
        self.assertIs(model_module.flash_attention, original)

    def test_ltx_openimageio_installs_when_missing(self):
        fake_openimageio = types.ModuleType("OpenImageIO")
        imports = {"count": 0}

        def fake_import(name, *args, **kwargs):
            if name == "OpenImageIO":
                imports["count"] += 1
                if imports["count"] == 1:
                    raise ImportError(name)
                return fake_openimageio
            return real_import(name, *args, **kwargs)

        real_import = __import__
        with patch.dict(sys.modules, {}, clear=False), \
                patch("builtins.__import__", side_effect=fake_import), \
                patch("core.models.video_loader.subprocess.check_call") as check_call:
            available = video_loader._ensure_ltx_openimageio_importable()

        self.assertTrue(available)
        check_call.assert_called_once()

    def test_ltx_openimageio_uses_import_shim_when_install_fails(self):
        def fake_import(name, *args, **kwargs):
            if name == "OpenImageIO":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        real_import = __import__
        with patch.dict(sys.modules, {}, clear=False), \
                patch("builtins.__import__", side_effect=fake_import), \
                patch("core.models.video_loader.subprocess.check_call", side_effect=RuntimeError("no wheel")):
            available = video_loader._ensure_ltx_openimageio_importable()
            self.assertIn("OpenImageIO", sys.modules)

        self.assertFalse(available)


if __name__ == "__main__":
    unittest.main()
