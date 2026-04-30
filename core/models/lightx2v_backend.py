"""Optional LightX2V video backend integration.

LightX2V is kept as a local pack under ~/.joyboy/packs so the public core does
not vendor a large third-party repository or model files. This module only owns
the adapter, install/status helpers, and subprocess command construction.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable

from PIL import Image

from core.infra.paths import get_output_dir, get_packs_dir


LIGHTX2V_REPO_URL = "https://github.com/ModelTC/LightX2V.git"
LIGHTX2V_PINNED_COMMIT = "3566cd5e1626965490debf91d36ea5cc11d71c46"
LIGHTX2V_BACKEND_NAME = "lightx2v"

# Safe, dependency-light install set. Do not install LightX2V requirements.txt:
# it pins torch<=2.8.0 and can downgrade JoyBoy's CUDA stack.
LIGHTX2V_MINIMAL_PACKAGES = [
    "loguru",
    "jsonschema",
    "easydict",
    "einops",
    "safetensors",
    "imageio",
    "imageio-ffmpeg",
    "opencv-python-headless",
    "av",
    "gguf",
    "ftfy",
    "prometheus-client",
    "pydantic",
    "scipy",
]

LIGHTX2V_OPTIONAL_PACKAGES = [
    "decord",
]

LIGHTX2V_IMPORT_CHECKS = {
    "loguru": "loguru",
    "jsonschema": "jsonschema",
    "easydict": "easydict",
    "einops": "einops",
    "safetensors": "safetensors",
    "cv2": "opencv-python-headless",
    "av": "av",
    "gguf": "gguf",
    "ftfy": "ftfy",
    "prometheus_client": "prometheus-client",
    "pydantic": "pydantic",
    "scipy": "scipy",
}


@dataclass(frozen=True)
class LightX2VRunResult:
    video_path: Path
    config_path: Path
    output_width: int
    output_height: int
    fps: int
    frames: int
    attention: str
    offload: str


class LightX2VBackend:
    """Lightweight descriptor loaded by ModelManager.

    The heavy model is not imported into the Flask process. Generation is run in
    a subprocess so optional kernels/deps stay isolated and logs remain visible
    in JoyBoy's runtime terminal.
    """

    backend = LIGHTX2V_BACKEND_NAME

    def __init__(self, model_id: str, meta: dict[str, Any], cache_dir: str | Path):
        self.model_id = model_id
        self.meta = dict(meta or {})
        self.cache_dir = Path(cache_dir)

    def generate(
        self,
        *,
        image: Image.Image | None,
        prompt: str,
        negative_prompt: str = "",
        width: int,
        height: int,
        frames: int,
        steps: int,
        fps: int,
        quality: str = "720p",
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int | None, int, str], None] | None = None,
    ) -> LightX2VRunResult:
        return run_lightx2v_generation(
            self.model_id,
            self.meta,
            self.cache_dir,
            image=image,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            frames=frames,
            steps=steps,
            fps=fps,
            quality=quality,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )


def is_lightx2v_model_id(model_id: str | None) -> bool:
    return str(model_id or "").startswith("lightx2v-")


def is_lightx2v_model_meta(meta: dict[str, Any] | None) -> bool:
    return str((meta or {}).get("backend") or "").strip().lower() == LIGHTX2V_BACKEND_NAME


def get_lightx2v_pack_dir() -> Path:
    return get_packs_dir() / "lightx2v"


def get_lightx2v_repo_dir() -> Path:
    return get_lightx2v_pack_dir() / "repo"


def get_lightx2v_runtime_dir() -> Path:
    return get_output_dir() / "videos" / "lightx2v"


def get_lightx2v_repo_specs(meta: dict[str, Any] | None) -> list[str]:
    meta = meta or {}
    repos = meta.get("hf_repos")
    if isinstance(repos, (list, tuple)):
        return [str(repo).strip() for repo in repos if str(repo).strip()]
    repo = str(meta.get("id") or "").strip()
    return [repo] if repo else []


def _repo_local_dir(cache_dir: str | Path, repo_id: str) -> Path:
    return Path(cache_dir) / str(repo_id).replace("/", "--")


def get_lightx2v_repo_local_dirs(meta: dict[str, Any] | None, cache_dir: str | Path) -> list[Path]:
    return [_repo_local_dir(cache_dir, repo_id) for repo_id in get_lightx2v_repo_specs(meta)]


def _required_files_for_repo(meta: dict[str, Any] | None, repo_id: str) -> list[str]:
    required = (meta or {}).get("hf_required_files")
    if not isinstance(required, dict):
        return []
    files = required.get(repo_id) or required.get(str(repo_id).replace("/", "--"))
    if isinstance(files, str):
        return [files]
    if isinstance(files, (list, tuple)):
        return [str(path).strip() for path in files if str(path).strip()]
    return []


def get_lightx2v_missing_paths(meta: dict[str, Any] | None, cache_dir: str | Path) -> list[Path]:
    missing: list[Path] = []
    for repo_id in get_lightx2v_repo_specs(meta):
        repo_dir = _repo_local_dir(cache_dir, repo_id)
        required_files = _required_files_for_repo(meta, repo_id)
        if required_files:
            for rel_path in required_files:
                path = repo_dir / rel_path
                try:
                    if not path.is_file() or path.stat().st_size <= 0:
                        missing.append(path)
                except OSError:
                    missing.append(path)
        elif not _nonempty_dir(repo_dir):
            missing.append(repo_dir)
    return missing


def _nonempty_dir(path: Path) -> bool:
    try:
        return path.exists() and path.is_dir() and any(path.iterdir())
    except Exception:
        return False


def _missing_lightx2v_package() -> str | None:
    for module_name, package_name in LIGHTX2V_IMPORT_CHECKS.items():
        if importlib.util.find_spec(module_name) is None:
            return package_name
    return None


def is_lightx2v_backend_available() -> bool:
    repo_dir = get_lightx2v_repo_dir()
    if not (repo_dir / "lightx2v" / "infer.py").exists():
        return False
    return _missing_lightx2v_package() is None


def get_lightx2v_backend_status() -> dict[str, Any]:
    repo_dir = get_lightx2v_repo_dir()
    missing_package = _missing_lightx2v_package()
    return {
        "backend": LIGHTX2V_BACKEND_NAME,
        "ready": (repo_dir / "lightx2v" / "infer.py").exists() and missing_package is None,
        "repo_dir": str(repo_dir),
        "installed": (repo_dir / "lightx2v" / "infer.py").exists(),
        "pinned_commit": LIGHTX2V_PINNED_COMMIT,
        "missing_python_package": missing_package,
    }


def is_lightx2v_model_downloaded(meta: dict[str, Any] | None, cache_dir: str | Path) -> bool:
    if not is_lightx2v_backend_available():
        return False
    return not get_lightx2v_missing_paths(meta, cache_dir)


def install_lightx2v_backend(*, upgrade: bool = False) -> dict[str, Any]:
    """Clone/pin the LightX2V pack and install only safe adapter deps."""
    pack_dir = get_lightx2v_pack_dir()
    repo_dir = get_lightx2v_repo_dir()
    pack_dir.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and not (repo_dir / ".git").exists():
        raise RuntimeError(f"LightX2V pack path exists but is not a git repo: {repo_dir}")

    if not repo_dir.exists():
        _run_checked(["git", "clone", "--filter=blob:none", LIGHTX2V_REPO_URL, str(repo_dir)], timeout=900)
    elif upgrade:
        _run_checked(["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", LIGHTX2V_PINNED_COMMIT], timeout=300)

    _run_checked(["git", "-C", str(repo_dir), "fetch", "--depth", "1", "origin", LIGHTX2V_PINNED_COMMIT], timeout=300)
    _run_checked(["git", "-C", str(repo_dir), "checkout", "--force", LIGHTX2V_PINNED_COMMIT], timeout=120)

    _pip_install([*LIGHTX2V_MINIMAL_PACKAGES])
    for package in LIGHTX2V_OPTIONAL_PACKAGES:
        try:
            _pip_install([package])
        except Exception as exc:
            print(f"[LIGHTX2V] Dépendance optionnelle indisponible ({package}): {exc}")
    _pip_install(["--no-deps", "-e", str(repo_dir)])

    status = get_lightx2v_backend_status()
    if not status["ready"]:
        raise RuntimeError("LightX2V installé, mais le backend n'est pas importable")
    return status


def _run_checked(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-1200:]
        raise RuntimeError(f"Commande échouée ({' '.join(cmd)}): {tail}")
    return result


def _pip_install(args: list[str]) -> None:
    _run_checked([sys.executable, "-m", "pip", "install", *args], timeout=1800)


def _select_attention(prefer_turbo: bool = False) -> str:
    override = os.environ.get("JOYBOY_LIGHTX2V_ATTENTION", "").strip()
    if override:
        return override
    if prefer_turbo:
        try:
            import sageattention  # noqa: F401
            return "sage_attn2"
        except Exception:
            pass
    return "torch_sdpa"


def _adjust_frames(frames: int) -> int:
    frames = max(5, int(frames or 81))
    if (frames - 1) % 4 != 0:
        frames = ((frames - 1) // 4) * 4 + 1
    return frames


def _repo_file(cache_dir: Path, repo_id: str, relative: str) -> str:
    return str((_repo_local_dir(cache_dir, repo_id) / relative).resolve())


def _lightx2v_lora_role(path: str) -> str:
    name = Path(str(path or "")).name.lower()
    if re.search(r"(^|[_\-. ])(high|highnoise|hnoise|hn)([_\-. ]|$)", name):
        return "high_noise_model"
    if re.search(r"(^|[_\-. ])(low|lownoise|lnoise|ln)([_\-. ]|$)", name):
        return "low_noise_model"
    if re.search(r"(^|[_\-. ])h[_\-. ]", name):
        return "high_noise_model"
    if re.search(r"(^|[_\-. ])l[_\-. ]", name):
        return "low_noise_model"
    return "both"


def _active_lightx2v_lora_configs(model_id: str, *, max_strength: float = 2.0) -> list[dict[str, Any]]:
    try:
        from core.infra.model_imports import get_active_video_loras
    except Exception:
        return []

    configs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in get_active_video_loras(model_id):
        path = str(item.get("file_path") or "").strip()
        if not path or not Path(path).is_file():
            continue
        try:
            strength = float(item.get("scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            strength = 1.0
        strength = max(0.0, min(max_strength, strength))
        role = _lightx2v_lora_role(path)
        targets = ("high_noise_model", "low_noise_model") if role == "both" else (role,)
        for target in targets:
            key = (path, target)
            if key in seen:
                continue
            seen.add(key)
            configs.append({"path": path, "strength": strength, "models": [target]})
    return configs


def _patch_config_paths(config: dict[str, Any], meta: dict[str, Any], cache_dir: Path, model_id: str = "") -> dict[str, Any]:
    """Convert upstream relative checkpoint paths to local HF cache paths."""
    distill_repo = str(meta.get("lightx2v_distill_repo") or "lightx2v/Wan2.2-Distill-Models")
    lora_repo = str(meta.get("lightx2v_lora_repo") or "lightx2v/Wan2.2-Distill-Loras")
    task = str(meta.get("lightx2v_task") or "").strip().lower()

    path_map = {
        "high_noise_original_ckpt": "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
        "low_noise_original_ckpt": "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
        "high_noise_quantized_ckpt": "wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step.safetensors",
        "low_noise_quantized_ckpt": "wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step.safetensors",
    }
    if task == "i2v" and "high_noise_original_ckpt" not in config and "low_noise_original_ckpt" not in config:
        config["high_noise_original_ckpt"] = path_map["high_noise_original_ckpt"]
        config["low_noise_original_ckpt"] = path_map["low_noise_original_ckpt"]

    for key, filename in path_map.items():
        if key in config:
            config[key] = _repo_file(cache_dir, distill_repo, filename)

    if "t5_quantized_ckpt" in config:
        base_repo = str(meta.get("lightx2v_base_repo") or meta.get("id") or "")
        if base_repo:
            config["t5_quantized_ckpt"] = _repo_file(cache_dir, base_repo, "encoders/t5/models_t5_umt5-xxl-enc-fp8.pth")

    lora_configs = config.get("lora_configs")
    if isinstance(lora_configs, list):
        patched = []
        for item in lora_configs:
            if not isinstance(item, dict):
                patched.append(item)
                continue
            raw_path = str(item.get("path") or "")
            filename = raw_path.split("/")[-1]
            if filename:
                patched.append({**item, "path": _repo_file(cache_dir, lora_repo, filename)})
            else:
                patched.append(item)
        config["lora_configs"] = patched

    active_loras = _active_lightx2v_lora_configs(model_id or str(meta.get("id") or ""))
    if active_loras:
        existing = config.get("lora_configs") if isinstance(config.get("lora_configs"), list) else []
        config["lora_configs"] = [*existing, *active_loras]
        labels = [Path(str(item["path"])).name for item in active_loras]
        print(f"[VIDEO-LORA] LightX2V LoRA configs actifs: {', '.join(labels)}")

    return config


def _build_lightx2v_config(
    model_id: str,
    meta: dict[str, Any],
    cache_dir: Path,
    *,
    width: int,
    height: int,
    frames: int,
    steps: int,
    fps: int,
    quality: str,
    runtime_dir: Path,
) -> tuple[Path, str, str]:
    repo_dir = get_lightx2v_repo_dir()
    prefer_turbo = os.environ.get("JOYBOY_LIGHTX2V_TURBO", "").strip().lower() in {"1", "true", "yes", "on"}
    attention = _select_attention(prefer_turbo=prefer_turbo)
    turbo_enabled = prefer_turbo and attention != "torch_sdpa"
    config_rel = str(meta.get("lightx2v_turbo_config") if turbo_enabled and meta.get("lightx2v_turbo_config") else meta.get("lightx2v_config"))
    source_config = repo_dir / config_rel
    if not source_config.exists():
        raise FileNotFoundError(f"Config LightX2V introuvable: {source_config}")

    config = json.loads(source_config.read_text(encoding="utf-8"))
    force_offload = os.environ.get("JOYBOY_LIGHTX2V_FORCE_OFFLOAD", "").strip().lower() in {"1", "true", "yes", "on"}
    low_vram_profile = model_id.endswith("-8gb") or str(meta.get("low_vram_profile", "")).lower() == "lightx2v"
    offload = "block" if (force_offload or low_vram_profile or quality == "480p") else str(config.get("offload_granularity") or "block")

    frames = _adjust_frames(frames)
    config.update({
        "infer_steps": max(1, int(steps or meta.get("default_steps") or config.get("infer_steps") or 4)),
        "target_video_length": frames,
        "target_height": int(height),
        "target_width": int(width),
        "target_fps": int(fps or meta.get("default_fps") or 16),
        "fps": int(fps or meta.get("default_fps") or 16),
        "self_attn_1_type": attention,
        "cross_attn_1_type": attention,
        "cross_attn_2_type": attention,
        "cpu_offload": bool(force_offload or low_vram_profile or config.get("cpu_offload", False)),
        "offload_granularity": offload,
        "t5_cpu_offload": bool(low_vram_profile or config.get("t5_cpu_offload", False)),
        "vae_cpu_offload": bool(low_vram_profile or config.get("vae_cpu_offload", False)),
    })

    if attention == "torch_sdpa":
        # FP8 configs may require extra kernels. Keep the default one-shot path
        # conservative; turbo stays opt-in through JOYBOY_LIGHTX2V_TURBO.
        if not turbo_enabled:
            config.pop("dit_quantized", None)
            config.pop("dit_quant_scheme", None)
            config.pop("t5_quantized", None)
            config.pop("t5_quant_scheme", None)
            config.pop("t5_quantized_ckpt", None)
            config.pop("high_noise_quantized_ckpt", None)
            config.pop("low_noise_quantized_ckpt", None)

    config = _patch_config_paths(config, meta, cache_dir, model_id)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / f"{model_id}_{int(time.time())}.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path, attention, offload


def build_lightx2v_command(
    model_id: str,
    meta: dict[str, Any],
    cache_dir: str | Path,
    *,
    config_path: str | Path,
    output_path: str | Path,
    image_path: str | Path | None = None,
    prompt: str,
    negative_prompt: str = "",
    frames: int,
) -> list[str]:
    base_repo = str(meta.get("lightx2v_base_repo") or meta.get("id") or "").strip()
    if not base_repo:
        raise ValueError(f"{model_id}: lightx2v_base_repo manquant")
    model_path = _repo_local_dir(cache_dir, base_repo)
    task = str(meta.get("lightx2v_task") or "i2v")
    cmd = [
        sys.executable,
        "-m",
        "lightx2v.infer",
        "--model_cls",
        str(meta.get("lightx2v_model_cls") or "wan2.2_moe_distill"),
        "--task",
        task,
        "--model_path",
        str(model_path),
        "--config_json",
        str(config_path),
        "--prompt",
        prompt or "",
        "--negative_prompt",
        negative_prompt or "",
        "--save_result_path",
        str(output_path),
        "--target_video_length",
        str(_adjust_frames(frames)),
    ]
    if image_path and task in {"i2v", "flf2v"}:
        cmd.extend(["--image_path", str(image_path)])
    return cmd


def _lightx2v_task_requires_audio(meta: dict[str, Any]) -> bool:
    task = str(meta.get("lightx2v_task") or "").strip().lower()
    if bool(meta.get("lightx2v_requires_audio")):
        return True
    return task in {"audio", "a2v", "s2v", "speech2video", "t2v_audio", "i2v_audio"}


def _lightx2v_stub_bootstrap() -> str:
    return r'''
import runpy
import sys
import types
import importlib.machinery

module = sys.argv[1]
sys.argv = [module, *sys.argv[2:]]

def _torchaudio_disabled(*args, **kwargs):
    raise RuntimeError("torchaudio is disabled for this LightX2V Wan run; audio models need a torch-matched torchaudio install.")

def _decord_disabled(*args, **kwargs):
    raise RuntimeError("decord is unavailable in this JoyBoy LightX2V Wan run; video-reader tasks need a platform-compatible decord install.")

class _UnavailableAudioOp:
    def __init__(self, *args, **kwargs):
        _torchaudio_disabled()
    def __call__(self, *args, **kwargs):
        _torchaudio_disabled()

def _install_torchaudio_stub():
    torchaudio = types.ModuleType("torchaudio")
    torchaudio.__file__ = "<joyboy-lightx2v-torchaudio-stub>"
    torchaudio.__spec__ = importlib.machinery.ModuleSpec("torchaudio", loader=None, is_package=True)
    torchaudio.__path__ = []
    torchaudio.load = _torchaudio_disabled
    torchaudio.save = _torchaudio_disabled
    torchaudio.info = _torchaudio_disabled

    functional = types.ModuleType("torchaudio.functional")
    functional.__spec__ = importlib.machinery.ModuleSpec("torchaudio.functional", loader=None)
    functional.resample = _torchaudio_disabled

    transforms = types.ModuleType("torchaudio.transforms")
    transforms.__spec__ = importlib.machinery.ModuleSpec("torchaudio.transforms", loader=None)
    transforms.Resample = _UnavailableAudioOp
    transforms.MelSpectrogram = _UnavailableAudioOp
    transforms.Spectrogram = _UnavailableAudioOp
    transforms.AmplitudeToDB = _UnavailableAudioOp

    io = types.ModuleType("torchaudio.io")
    io.__spec__ = importlib.machinery.ModuleSpec("torchaudio.io", loader=None)
    compliance = types.ModuleType("torchaudio.compliance")
    compliance.__spec__ = importlib.machinery.ModuleSpec("torchaudio.compliance", loader=None, is_package=True)
    kaldi = types.ModuleType("torchaudio.compliance.kaldi")
    kaldi.__spec__ = importlib.machinery.ModuleSpec("torchaudio.compliance.kaldi", loader=None)

    torchaudio.functional = functional
    torchaudio.transforms = transforms
    torchaudio.io = io
    torchaudio.compliance = compliance
    compliance.kaldi = kaldi

    sys.modules["torchaudio"] = torchaudio
    sys.modules["torchaudio.functional"] = functional
    sys.modules["torchaudio.transforms"] = transforms
    sys.modules["torchaudio.io"] = io
    sys.modules["torchaudio.compliance"] = compliance
    sys.modules["torchaudio.compliance.kaldi"] = kaldi

def _install_decord_stub():
    decord = types.ModuleType("decord")
    decord.__file__ = "<joyboy-lightx2v-decord-stub>"
    decord.__spec__ = importlib.machinery.ModuleSpec("decord", loader=None, is_package=True)
    decord.__path__ = []
    decord.VideoReader = _UnavailableAudioOp
    decord.AudioReader = _UnavailableAudioOp
    decord.cpu = lambda *args, **kwargs: None
    decord.gpu = lambda *args, **kwargs: None
    bridge = types.ModuleType("decord.bridge")
    bridge.__spec__ = importlib.machinery.ModuleSpec("decord.bridge", loader=None)
    bridge.set_bridge = lambda *args, **kwargs: None
    decord.bridge = bridge
    sys.modules["decord"] = decord
    sys.modules["decord.bridge"] = bridge

_install_torchaudio_stub()
try:
    import decord  # noqa: F401
except Exception:
    _install_decord_stub()
runpy.run_module(module, run_name="__main__", alter_sys=True)
'''.strip()


def _lightx2v_subprocess_command(cmd: list[str], meta: dict[str, Any]) -> list[str]:
    """Wrap `python -m lightx2v.infer` so Wan tasks avoid broken torchaudio imports."""
    if len(cmd) < 3 or cmd[1] != "-m":
        return cmd
    allow_real_torchaudio = os.environ.get("JOYBOY_LIGHTX2V_ALLOW_TORCHAUDIO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if allow_real_torchaudio or _lightx2v_task_requires_audio(meta):
        return cmd
    module = cmd[2]
    return [cmd[0], "-c", _lightx2v_stub_bootstrap(), module, *cmd[3:]]


def _lightx2v_env(repo_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_dir) + (os.pathsep + current_pythonpath if current_pythonpath else "")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    env.setdefault("DTYPE", "BF16")
    env.setdefault("SENSITIVE_LAYER_DTYPE", "None")
    env.setdefault("PROFILING_DEBUG_LEVEL", "2")
    env.setdefault("FFMPEG_LOG_LEVEL", "error")
    return env


def _parse_progress(line: str, total_steps: int) -> int | None:
    patterns = [
        r"step\s*[:=]?\s*(\d+)\s*/\s*(\d+)",
        r"(\d+)\s*/\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if not match:
            continue
        step = int(match.group(1))
        total = int(match.group(2))
        if 0 < step <= max(total, total_steps):
            return min(step, total_steps)
    return None


def _find_output_video(expected_path: Path, runtime_dir: Path) -> Path | None:
    if expected_path.exists() and expected_path.stat().st_size > 0:
        return expected_path
    candidates = sorted(runtime_dir.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def run_lightx2v_generation(
    model_id: str,
    meta: dict[str, Any],
    cache_dir: str | Path,
    *,
    image: Image.Image | None,
    prompt: str,
    negative_prompt: str = "",
    width: int,
    height: int,
    frames: int,
    steps: int,
    fps: int,
    quality: str = "720p",
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int | None, int, str], None] | None = None,
) -> LightX2VRunResult:
    if not is_lightx2v_backend_available():
        raise RuntimeError(
            "Backend LightX2V non installé. Installe le modèle depuis Modèles > Vidéo "
            "pour cloner le pack local ~/.joyboy/packs/lightx2v."
        )

    cache_dir = Path(cache_dir)
    missing = [str(path) for path in get_lightx2v_missing_paths(meta, cache_dir)]
    if missing:
        raise RuntimeError("Artefacts LightX2V manquants: " + ", ".join(missing))

    repo_dir = get_lightx2v_repo_dir()
    runtime_dir = get_lightx2v_runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    frames = _adjust_frames(frames)
    steps = max(1, int(steps or meta.get("default_steps") or 4))
    fps = int(fps or meta.get("default_fps") or 16)

    config_path, attention, offload = _build_lightx2v_config(
        model_id,
        meta,
        cache_dir,
        width=width,
        height=height,
        frames=frames,
        steps=steps,
        fps=fps,
        quality=quality,
        runtime_dir=runtime_dir,
    )

    stamp = int(time.time())
    image_path = None
    if image is not None:
        image_path = runtime_dir / f"{model_id}_{stamp}_input.png"
        image.convert("RGB").save(image_path, "PNG")

    output_path = runtime_dir / f"{model_id}_{stamp}.mp4"
    cmd = build_lightx2v_command(
        model_id,
        meta,
        cache_dir,
        config_path=config_path,
        output_path=output_path,
        image_path=image_path,
        prompt=prompt,
        negative_prompt=negative_prompt,
        frames=frames,
    )

    print(f"[LIGHTX2V] Backend: {repo_dir}")
    print(f"[LIGHTX2V] Attention: {attention} | offload={offload} | steps={steps} | frames={frames}")
    print(f"[LIGHTX2V] Output: {output_path}")
    if progress_callback:
        progress_callback(0, steps, "LightX2V: initialisation")

    process = subprocess.Popen(
        _lightx2v_subprocess_command(cmd, meta),
        cwd=str(repo_dir),
        env=_lightx2v_env(repo_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    last_step = 0
    log_tail: list[str] = []
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if line:
                print(f"[LIGHTX2V] {line}")
                log_tail = (log_tail + [line])[-40:]
            parsed = _parse_progress(line, steps)
            if parsed is not None and parsed > last_step:
                last_step = parsed
                if progress_callback:
                    progress_callback(last_step, steps, f"LightX2V step {last_step}/{steps}")
            elif progress_callback and line:
                progress_callback(last_step or None, steps, "LightX2V en cours")
            if cancel_check and cancel_check():
                process.terminate()
                raise RuntimeError("LightX2V generation cancelled")

        return_code = process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.terminate()

    if return_code != 0:
        raise RuntimeError("LightX2V a échoué: " + "\n".join(log_tail[-10:]))

    final_path = _find_output_video(output_path, runtime_dir)
    if not final_path:
        raise RuntimeError(f"LightX2V terminé sans MP4: {output_path}")

    if progress_callback:
        progress_callback(steps, steps, "LightX2V terminé")

    return LightX2VRunResult(
        video_path=final_path,
        config_path=config_path,
        output_width=int(width),
        output_height=int(height),
        fps=fps,
        frames=frames,
        attention=attention,
        offload=offload,
    )


def remove_lightx2v_backend() -> None:
    """Testing/maintenance helper. Not used by normal runtime."""
    pack_dir = get_lightx2v_pack_dir()
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
