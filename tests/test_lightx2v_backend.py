import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from PIL import Image

from core.models import lightx2v_backend as backend
from core.models import video_loader
from web.routes import video as video_routes


class FakeLightX2VProcess:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.returncode = 0
        self.stdout = io.StringIO("step 1/4\nstep 4/4\n")
        output_path = Path(cmd[cmd.index("--save_result_path") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake mp4 bytes")

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15


class LightX2VBackendTests(unittest.TestCase):
    def _write_repo_config(self, repo_dir: Path, rel_path: str, payload: dict) -> None:
        target = repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")

    def _meta(self) -> dict:
        return {
            "id": "Wan-AI/Wan2.2-I2V-A14B",
            "hf_repos": ["Wan-AI/Wan2.2-I2V-A14B", "lightx2v/Wan2.2-Distill-Models"],
            "lightx2v_base_repo": "Wan-AI/Wan2.2-I2V-A14B",
            "lightx2v_distill_repo": "lightx2v/Wan2.2-Distill-Models",
            "lightx2v_model_cls": "wan2.2_moe_distill",
            "lightx2v_task": "i2v",
            "lightx2v_config": "configs/distill/wan22/safe.json",
            "lightx2v_turbo_config": "configs/distill/wan22/turbo.json",
            "default_steps": 4,
            "default_fps": 16,
        }

    def test_install_uses_minimal_deps_and_no_lightx2v_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            repo_dir.mkdir(parents=True)
            (repo_dir / ".git").mkdir()
            (repo_dir / "lightx2v").mkdir()
            (repo_dir / "lightx2v" / "infer.py").write_text("", encoding="utf-8")

            pip_calls = []

            with (
                patch.object(backend, "get_lightx2v_pack_dir", return_value=Path(tmp)),
                patch.object(backend, "get_lightx2v_repo_dir", return_value=repo_dir),
                patch.object(backend, "_run_checked") as run_checked,
                patch.object(backend, "_pip_install", side_effect=lambda args: pip_calls.append(list(args))),
                patch.object(backend, "get_lightx2v_backend_status", return_value={"ready": True}),
            ):
                status = backend.install_lightx2v_backend(upgrade=True)

        self.assertTrue(status["ready"])
        self.assertGreaterEqual(run_checked.call_count, 2)
        flat_packages = [item for call in pip_calls for item in call]
        self.assertNotIn("torch", flat_packages)
        self.assertNotIn("torchvision", flat_packages)
        self.assertNotIn("torchaudio", flat_packages)
        self.assertNotIn("requirements.txt", " ".join(flat_packages))
        self.assertIn("gguf", flat_packages)
        self.assertIn("pyzmq", flat_packages)
        self.assertNotIn("decord", pip_calls[0])
        self.assertIn(["decord"], pip_calls)
        self.assertTrue(any(call[:1] == ["--no-deps"] and "-e" in call for call in pip_calls))

    def test_import_checks_include_gguf_for_lightx2v_cli_startup(self):
        self.assertEqual(backend.LIGHTX2V_IMPORT_CHECKS["gguf"], "gguf")
        self.assertEqual(backend.LIGHTX2V_IMPORT_CHECKS["zmq"], "pyzmq")
        self.assertNotIn("decord", backend.LIGHTX2V_IMPORT_CHECKS)

    def test_runtime_repair_maps_zmq_to_pyzmq(self):
        logs = [
            "Traceback (most recent call last):",
            "ModuleNotFoundError: No module named 'zmq'",
        ]
        with patch.object(backend, "_pip_install") as pip_install:
            repaired = backend._repair_missing_lightx2v_dependency(logs)

        self.assertEqual(repaired, "pyzmq")
        pip_install.assert_called_once_with(["pyzmq"])

    def test_load_lightx2v_repairs_missing_minimal_dependency(self):
        with (
            patch("core.models.lightx2v_backend.get_lightx2v_backend_status", return_value={
                "ready": False,
                "missing_python_package": "gguf",
            }),
            patch("core.models.lightx2v_backend.install_lightx2v_backend", return_value={
                "ready": True,
                "repo_dir": "/tmp/lightx2v",
            }) as install_backend,
        ):
            result = video_loader.load_lightx2v("lightx2v-wan22-i2v-4step", "C:/cache")

        install_backend.assert_called_once()
        self.assertEqual(result["extras"]["external_backend"], "lightx2v")

    def test_command_uses_lightx2v_module_and_image_for_i2v(self):
        cmd = backend.build_lightx2v_command(
            "lightx2v-wan22-i2v-4step",
            self._meta(),
            "C:/cache",
            config_path="C:/cfg.json",
            output_path="C:/out.mp4",
            image_path="C:/input.png",
            prompt="move slowly",
            negative_prompt="oversaturated",
            frames=82,
        )

        self.assertEqual(cmd[:3], [sys.executable, "-m", "lightx2v.infer"])
        self.assertIn("wan2.2_moe_distill", cmd)
        self.assertIn("i2v", cmd)
        self.assertIn("--image_path", cmd)
        self.assertIn("C:/input.png", cmd)
        self.assertIn("81", cmd)
        self.assertNotIn("requirements.txt", cmd)

    def test_lightx2v_subprocess_stubs_torchaudio_for_wan_tasks(self):
        base_cmd = [
            sys.executable,
            "-m",
            "lightx2v.infer",
            "--save_result_path",
            "C:/out.mp4",
        ]

        wrapped = backend._lightx2v_subprocess_command(base_cmd, self._meta())

        self.assertEqual(wrapped[0], sys.executable)
        self.assertEqual(wrapped[1], "-c")
        self.assertIn("torchaudio", wrapped[2])
        self.assertIn("decord", wrapped[2])
        self.assertIn("ModuleSpec(\"decord\"", wrapped[2])
        self.assertIn("flash_attn", wrapped[2])
        self.assertIn("flash_attn_interface", wrapped[2])
        self.assertEqual(wrapped[3], "lightx2v.infer")
        self.assertIn("--save_result_path", wrapped)

    def test_video_download_helpers_support_multi_repo_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            meta = self._meta()
            first = cache_dir / "Wan-AI--Wan2.2-I2V-A14B"
            second = cache_dir / "lightx2v--Wan2.2-Distill-Models"
            first.mkdir()
            second.mkdir()
            (first / "a.bin").write_bytes(b"12345")
            (second / "b.bin").write_bytes(b"1234567")

            repos = video_routes._video_model_repos(meta)
            size = video_routes._video_model_downloaded_size(meta, str(cache_dir))

        self.assertEqual(repos, ["Wan-AI/Wan2.2-I2V-A14B", "lightx2v/Wan2.2-Distill-Models"])
        self.assertEqual(size, 12)

    def test_lightx2v_downloaded_requires_declared_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            meta = self._meta()
            meta["hf_required_files"] = {
                "lightx2v/Wan2.2-Distill-Models": [
                    "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                    "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
                ],
            }
            base = cache_dir / "Wan-AI--Wan2.2-I2V-A14B"
            distill = cache_dir / "lightx2v--Wan2.2-Distill-Models"
            base.mkdir(parents=True)
            distill.mkdir(parents=True)
            (base / "marker.bin").write_bytes(b"ok")
            (distill / "unrelated.bin").write_bytes(b"old partial download")

            with patch.object(backend, "is_lightx2v_backend_available", return_value=True):
                self.assertFalse(backend.is_lightx2v_model_downloaded(meta, cache_dir))
                (distill / "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors").write_bytes(b"high")
                self.assertFalse(backend.is_lightx2v_model_downloaded(meta, cache_dir))
                (distill / "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors").write_bytes(b"low")
                self.assertTrue(backend.is_lightx2v_model_downloaded(meta, cache_dir))

    def test_lightx2v_download_patterns_filter_distill_repo(self):
        meta = self._meta()
        meta["hf_allow_patterns"] = {
            "lightx2v/Wan2.2-Distill-Models": [
                "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
            ],
        }
        patterns = video_routes._video_repo_allow_patterns(meta, "lightx2v/Wan2.2-Distill-Models")

        self.assertEqual(len(patterns), 2)
        self.assertTrue(video_routes._matches_hf_patterns("wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors", patterns))
        self.assertFalse(video_routes._matches_hf_patterns("wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step.safetensors", patterns))

    def test_video_repo_size_requests_file_metadata_and_filters_patterns(self):
        class Sibling:
            def __init__(self, name, size):
                self.rfilename = name
                self.size = size

        class FakeApi:
            def __init__(self):
                self.kwargs = None

            def repo_info(self, **kwargs):
                self.kwargs = kwargs
                return type("Info", (), {
                    "siblings": [
                        Sibling("keep.safetensors", 10),
                        Sibling("skip.safetensors", 99),
                    ]
                })()

        fake_api = FakeApi()
        with patch("huggingface_hub.HfApi", return_value=fake_api):
            size = video_routes._video_repo_size("owner/repo", ["keep.safetensors"])

        self.assertTrue(fake_api.kwargs["files_metadata"])
        self.assertEqual(size, 10)

    def test_delete_video_repo_artifacts_removes_local_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            local_dir = cache_dir / "owner--repo"
            local_dir.mkdir()
            (local_dir / "weights.bin").write_bytes(b"123")

            with patch("core.models.delete_model_from_cache", return_value=False):
                deleted = video_routes._delete_video_repo_artifacts("owner/repo", str(cache_dir))

            self.assertTrue(deleted)
            self.assertFalse(local_dir.exists())

    def test_delete_video_repo_artifacts_refuses_outside_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            cache_dir.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "weights.bin").write_bytes(b"123")

            deleted = video_routes._safe_rmtree_under(str(outside), str(cache_dir))

            self.assertFalse(deleted)
            self.assertTrue(outside.exists())

    def test_missing_video_session_file_returns_404(self):
        app = Flask(__name__)
        app.register_blueprint(video_routes.video_bp)

        with tempfile.TemporaryDirectory() as tmp:
            missing_path = str(Path(tmp) / "missing.mp4")
            with patch("core.generation.video_sessions.load_video_session", return_value={"video_path": missing_path}):
                response = app.test_client().get("/videos/session/vid_missing")

        self.assertEqual(response.status_code, 404)

    def test_video_download_space_error_mentions_pack_for_multi_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk_usage = type("Usage", (), {"free": 512 * 1024 ** 2})()
            with patch.object(video_routes.shutil, "disk_usage", return_value=disk_usage):
                error = video_routes._download_model_space_error(self._meta(), tmp, 8 * 1024 ** 3)

        self.assertIsNotNone(error)
        self.assertIn("pack vidéo", error)

    def test_config_keeps_safe_sdpa_when_turbo_kernel_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_dir = root / "repo"
            runtime_dir = root / "runtime"
            cache_dir = root / "cache"
            self._write_repo_config(
                repo_dir,
                "configs/distill/wan22/safe.json",
                {
                    "infer_steps": 9,
                    "dit_quantized": True,
                    "t5_quantized": True,
                    "high_noise_quantized_ckpt": "unused.safetensors",
                    "low_noise_quantized_ckpt": "unused.safetensors",
                },
            )
            self._write_repo_config(
                repo_dir,
                "configs/distill/wan22/turbo.json",
                {"turbo_marker": True, "dit_quantized": True},
            )

            with (
                patch.object(backend, "get_lightx2v_repo_dir", return_value=repo_dir),
                patch.object(backend, "_select_attention", return_value="torch_sdpa"),
                patch.dict(os.environ, {"JOYBOY_LIGHTX2V_TURBO": "1"}, clear=False),
            ):
                config_path, attention, offload = backend._build_lightx2v_config(
                    "lightx2v-wan22-i2v-4step",
                    self._meta(),
                    cache_dir,
                    width=832,
                    height=480,
                    frames=82,
                    steps=4,
                    fps=16,
                    quality="720p",
                    runtime_dir=runtime_dir,
                )

            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(attention, "torch_sdpa")
            self.assertEqual(offload, "block")
            self.assertNotIn("turbo_marker", config)
            self.assertNotIn("dit_quantized", config)
            self.assertNotIn("t5_quantized", config)
            self.assertEqual(config["rope_type"], "torch")
            self.assertTrue(config["rope_chunk"])
            self.assertEqual(config["target_video_length"], 81)
            self.assertTrue(
                config["high_noise_original_ckpt"].endswith(
                    "lightx2v--Wan2.2-Distill-Models\\wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors"
                )
                or config["high_noise_original_ckpt"].endswith(
                    "lightx2v--Wan2.2-Distill-Models/wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors"
                )
            )

    def test_config_injects_active_video_loras_for_lightx2v(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_dir = root / "repo"
            runtime_dir = root / "runtime"
            cache_dir = root / "cache"
            lora_path = root / "NSFW-22-L-e8.safetensors"
            lora_path.write_bytes(b"fake")
            self._write_repo_config(repo_dir, "configs/distill/wan22/safe.json", {"lora_configs": []})

            active_loras = [{
                "id": "video-lora-nsfw",
                "file_path": str(lora_path),
                "scale": 0.8,
                "compatible_models": ["lightx2v-wan22-i2v-4step"],
                "enabled": True,
                "exists": True,
            }]

            with (
                patch.object(backend, "get_lightx2v_repo_dir", return_value=repo_dir),
                patch.object(backend, "_select_attention", return_value="torch_sdpa"),
                patch("core.infra.model_imports.get_active_video_loras", return_value=active_loras) as active,
            ):
                config_path, _, _ = backend._build_lightx2v_config(
                    "lightx2v-wan22-i2v-4step",
                    self._meta(),
                    cache_dir,
                    width=832,
                    height=480,
                    frames=81,
                    steps=4,
                    fps=16,
                    quality="480p",
                    runtime_dir=runtime_dir,
                )

            active.assert_called_once_with("lightx2v-wan22-i2v-4step")
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["lora_configs"], [{
                "path": str(lora_path),
                "strength": 0.8,
                "models": ["low_noise_model"],
            }])

    def test_run_generation_fake_subprocess_returns_mp4_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_dir = root / "repo"
            runtime_dir = root / "runtime"
            cache_dir = root / "cache"
            for rel in ("Wan-AI--Wan2.2-I2V-A14B", "lightx2v--Wan2.2-Distill-Models"):
                path = cache_dir / rel
                path.mkdir(parents=True)
                (path / "marker.txt").write_text("ok", encoding="utf-8")
            self._write_repo_config(repo_dir, "configs/distill/wan22/safe.json", {})
            (repo_dir / "lightx2v").mkdir()
            (repo_dir / "lightx2v" / "infer.py").write_text("", encoding="utf-8")

            progress = []
            image = Image.new("RGB", (64, 64), color=(20, 30, 40))

            with (
                patch.object(backend, "is_lightx2v_backend_available", return_value=True),
                patch.object(backend, "get_lightx2v_repo_dir", return_value=repo_dir),
                patch.object(backend, "get_lightx2v_runtime_dir", return_value=runtime_dir),
                patch.object(backend.subprocess, "Popen", FakeLightX2VProcess),
            ):
                result = backend.run_lightx2v_generation(
                    "lightx2v-wan22-i2v-4step",
                    self._meta(),
                    cache_dir,
                    image=image,
                    prompt="subtle motion",
                    negative_prompt="",
                    width=64,
                    height=64,
                    frames=82,
                    steps=4,
                    fps=16,
                    progress_callback=lambda step, total, message: progress.append((step, total, message)),
                )

            self.assertTrue(result.video_path.exists())
            self.assertEqual(result.frames, 81)
            self.assertIn((4, 4, "LightX2V terminé"), progress)


if __name__ == "__main__":
    unittest.main()
