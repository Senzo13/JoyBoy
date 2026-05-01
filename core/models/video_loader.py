"""
Video Loader - Video model loading functions extracted from ModelManager.

Contains per-model loading logic for:
- SVD (Stable Video Diffusion)
- CogVideoX 5B / 2B
- Wan 2.1 I2V 14B
- Wan 2.2 I2V A14B (MoE)
- Wan 2.2 TI2V 5B / FastWan
- Wan 2.2 T2V 14B
- HunyuanVideo 1.5
- LTX-Video 2B (distilled 0.9.8)
- FramePack F1 I2V (Diffusers HunyuanVideoFramepackPipeline)
- Wan native backend (5B / 14B)

Each load_* function returns a dict with:
  - pipe: the loaded pipeline
  - extras: optional dict with extra components (ltx_upsampler, ltx_upsample_pipe, native flag, etc.)
"""

import gc
import os
import shutil
import sys
import subprocess
import torch
import types
import warnings
from importlib.machinery import ModuleSpec
from types import MethodType

from core.models import move_video_to_device, VRAM_GB, IS_HIGH_END_GPU, TORCH_DTYPE, DTYPE_NAME


# ============================================================
# UTILITY FUNCTIONS (moved from model_manager.py)
# ============================================================

def _load_no_mmap(filename, device="cpu"):
    """Load safetensors file without mmap.

    On Windows, mmap reserves virtual address space for ALL shards (~47GB).
    This reads bytes directly instead, avoiding virtual memory exhaustion.
    """
    import safetensors.torch
    with open(filename, "rb") as f:
        data = f.read()
    result = safetensors.torch.load(data)
    if device != "cpu":
        result = {k: v.to(device) for k, v in result.items()}
    return result


def _patch_ftfy_encoding(pipeline_module_path):
    """Ensure ftfy is installed and injected into a Wan pipeline module.

    Args:
        pipeline_module_path: dotted import path, e.g. 'diffusers.pipelines.wan.pipeline_wan_i2v'
    """
    try:
        import ftfy
    except ImportError:
        print("[MM] Installation de ftfy...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'ftfy'], check=True)
        import ftfy

    try:
        import importlib
        _wan_module = importlib.import_module(pipeline_module_path)
        if not hasattr(_wan_module, 'ftfy'):
            _wan_module.ftfy = ftfy
            print("[MM]   ftfy injecte dans le pipeline Wan")
    except Exception:
        pass


def _ensure_framepack_dependency_versions():
    """Fail early if FramePack dependencies are too old for Hunyuan tokenizers."""
    try:
        from packaging.version import Version
        import tokenizers
        import transformers
    except Exception as exc:
        raise RuntimeError(
            "FramePack nécessite transformers/tokenizers modernes. Lance le setup ou installe: "
            "pip install -U \"transformers>=4.53.3,<5\" \"tokenizers>=0.21,<0.23\""
        ) from exc

    min_transformers = Version("4.53.3")
    min_tokenizers = Version("0.21.0")
    current_transformers = Version(transformers.__version__)
    current_tokenizers = Version(tokenizers.__version__)

    if current_transformers < min_transformers or current_tokenizers < min_tokenizers:
        raise RuntimeError(
            "FramePack ne peut pas charger le tokenizer Hunyuan avec ces dépendances "
            f"(transformers={transformers.__version__}, tokenizers={tokenizers.__version__}). "
            "Lance le setup ou installe: pip install -U "
            "\"transformers>=4.53.3,<5\" \"tokenizers>=0.21,<0.23\""
        )


def _run_pip_install(args, *, optional=False):
    command = [sys.executable, "-m", "pip", "install", *args]
    try:
        subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        if optional:
            print(f"[MM] Dépendance optionnelle indisponible ({' '.join(args)}): {exc}")
            return False
        raise


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _install_wan_native_packages(packages):
    """Install Wan runtime dependencies while isolating package failures."""
    try:
        _run_pip_install(packages)
        return
    except subprocess.CalledProcessError as exc:
        print(f"[MM] Installation groupée des dépendances Wan échouée: {exc}")
        print("[MM] Réessai paquet par paquet pour isoler la dépendance fautive...")

    for package in packages:
        _run_pip_install([package])


def _ensure_wan_native_import_shims():
    """Provide tiny shims for optional Wan imports that are not needed for I2V/T2V.

    Wan's package import eagerly imports speech-to-video modules. On some cloud
    images (notably ARM64/GH200), `decord` has no compatible wheel, but I2V/T2V
    do not need it. The shim lets `import wan` complete and raises only if the
    unavailable speech/video reader path is actually used.
    """
    try:
        import decord  # noqa: F401
        return
    except Exception:
        pass

    if "decord" in sys.modules:
        return

    def _decord_unavailable(*_args, **_kwargs):
        raise ImportError(
            "decord is unavailable in this environment; Wan speech/video-reader "
            "features are disabled, but I2V/T2V generation can continue."
        )

    fake_decord = types.ModuleType("decord")
    fake_decord.__spec__ = ModuleSpec("decord", None)

    class _UnavailableVideoReader:
        def __init__(self, *_args, **_kwargs):
            _decord_unavailable()

    fake_decord.VideoReader = _UnavailableVideoReader
    fake_decord.cpu = _decord_unavailable
    fake_decord.gpu = _decord_unavailable
    fake_decord.bridge = types.SimpleNamespace(set_bridge=lambda *_args, **_kwargs: None)
    sys.modules["decord"] = fake_decord
    print("[MM] decord absent: shim Wan activé (speech/video-reader désactivé, I2V/T2V OK).")


def _install_wan_native_backend():
    """Install the official Wan backend without requiring flash-attn.

    The upstream package declares flash-attn as a dependency. Building it during
    a first video request can consume enough RAM to make the OS kill JoyBoy, so
    the default path installs the backend with explicit runtime dependencies.
    """
    print("[MM] Installation du backend natif Wan...")
    cuda_toolkit_available = bool(os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH") or shutil.which("nvcc"))
    install_flash_attn = _env_flag("JOYBOY_WAN_NATIVE_INSTALL_FLASH_ATTN")
    _run_pip_install(["wheel"], optional=True)
    if install_flash_attn and cuda_toolkit_available:
        print("[MM] JOYBOY_WAN_NATIVE_INSTALL_FLASH_ATTN=1: tentative flash_attn optionnelle.")
        _run_pip_install(["--no-build-isolation", "flash_attn"], optional=True)
    elif install_flash_attn:
        print("[MM] flash_attn demandé mais CUDA toolkit absent (nvcc/CUDA_HOME). Installation sans flash_attn.")
    else:
        print("[MM] flash_attn ignoré par défaut pour éviter une compilation lourde au démarrage.")

    print("[MM] Installation Wan sans dépendance flash_attn obligatoire...")
    required_packages = [
        "dashscope",
        "easydict",
        "einops",
        "ftfy",
        "imageio-ffmpeg",
        "librosa",
        "peft",
    ]
    optional_packages = [
        # Decord has no wheel on some ARM64/GH200 images. Wan imports it via
        # speech2video at package import time, so JoyBoy installs it when
        # possible and otherwise injects a narrow import shim for I2V/T2V.
        "decord",
    ]
    install_backend_command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "git+https://github.com/Wan-Video/Wan2.2.git",
    ]

    _install_wan_native_packages(required_packages)
    for package in optional_packages:
        _run_pip_install([package], optional=True)
    _ensure_wan_native_import_shims()
    subprocess.run(install_backend_command, check=True)


def _patch_wan_native_attention_fallback() -> bool:
    """Use Wan's torch SDPA attention path when FlashAttention is unavailable.

    Upstream Wan imports ``flash_attention`` directly into ``wan.modules.model``.
    The generic ``attention`` helper has a PyTorch SDPA fallback, but the direct
    model symbol still asserts when flash-attn is not installed. Patching both
    symbols keeps native Wan usable on ARM/GH200 images where flash-attn wheels
    are not available.
    """
    try:
        from wan.modules import attention as attention_module
        from wan.modules import model as model_module
    except Exception as exc:
        print(f"[MM] Wan attention fallback non appliqué: {exc}")
        return False

    has_flash = bool(
        getattr(attention_module, "FLASH_ATTN_2_AVAILABLE", False)
        or getattr(attention_module, "FLASH_ATTN_3_AVAILABLE", False)
    )
    if has_flash:
        return False

    fallback = getattr(attention_module, "attention", None)
    if fallback is None:
        return False

    attention_module.flash_attention = fallback
    model_module.flash_attention = fallback
    warnings.filterwarnings(
        "ignore",
        message=r"Padding mask is disabled when using scaled_dot_product_attention\..*",
        category=UserWarning,
        module=r"wan\.modules\.attention",
    )
    print("[MM] Wan natif: flash_attn absent, fallback PyTorch SDPA activé.")
    return True


# ============================================================
# PER-MODEL LOADERS
# ============================================================

def load_svd(custom_cache):
    """Load Stable Video Diffusion XT 1.1.

    Returns:
        dict with 'pipe' key
    """
    from diffusers import StableVideoDiffusionPipeline
    from core.models import XFORMERS_AVAILABLE

    pipe = StableVideoDiffusionPipeline.from_pretrained(
        "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        torch_dtype=torch.float16, variant="fp16", cache_dir=custom_cache,
    )

    def _current_svd_vae_input_dtype(self, fallback=torch.float32):
        encoder = getattr(self.vae, "encoder", None)
        conv_in = getattr(encoder, "conv_in", None)
        for tensor in (getattr(conv_in, "bias", None), getattr(conv_in, "weight", None)):
            dtype = getattr(tensor, "dtype", None)
            if dtype in (torch.float16, torch.float32, torch.bfloat16):
                return dtype
        return fallback

    def _encode_vae_image_with_dtype(self, image, device, num_videos_per_prompt, do_classifier_free_guidance):
        # SVD + Accelerate offload can move/restore the VAE with a different dtype
        # than the pipeline load dtype. Match the live conv input, then retry once
        # if a hook changes the weights between inspection and forward.
        vae_dtype = _current_svd_vae_input_dtype(self)
        image = image.to(device=device, dtype=vae_dtype)
        print(f"[VIDEO] SVD VAE encode dtype: image={image.dtype}, vae={vae_dtype}")
        try:
            image_latents = self.vae.encode(image).latent_dist.mode()
        except RuntimeError as exc:
            message = str(exc)
            if "Input type" not in message or "bias type" not in message:
                raise
            retry_dtype = torch.float32 if image.dtype != torch.float32 else torch.float16
            print(f"[VIDEO] SVD VAE dtype retry: {image.dtype} -> {retry_dtype}")
            image = image.to(device=device, dtype=retry_dtype)
            image_latents = self.vae.encode(image).latent_dist.mode()
        image_latents = image_latents.repeat(num_videos_per_prompt, 1, 1, 1)
        if do_classifier_free_guidance:
            image_latents = torch.cat([torch.zeros_like(image_latents), image_latents])
        return image_latents

    pipe._encode_vae_image = MethodType(_encode_vae_image_with_dtype, pipe)
    print("[VIDEO] SVD VAE input dtype patch active")

    if XFORMERS_AVAILABLE:
        try:
            pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass
    else:
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pass
    pipe.unet.enable_forward_chunking()
    if 0 < float(VRAM_GB or 0) <= 10:
        force_cpu_offload = os.environ.get("JOYBOY_SVD_CPU_OFFLOAD", "").strip().lower() in {"1", "true", "yes", "on"}
        if force_cpu_offload:
            pipe.enable_model_cpu_offload()
            print(f"[VIDEO] SVD 1.1: CPU offload forcé ({VRAM_GB:.1f}GB VRAM)")
        else:
            pipe.to("cuda")
            print(f"[VIDEO] SVD 1.1: GPU direct compact mode ({VRAM_GB:.1f}GB VRAM)")
    else:
        move_video_to_device(pipe, "SVD 1.1", vram_needed_gb=10)
    return {"pipe": pipe}


def load_cogvideox(custom_cache):
    """Load CogVideoX 5B I2V.

    Returns:
        dict with 'pipe' key
    """
    from core.models.video_policy import assert_cogvideox_allowed_on_low_vram

    assert_cogvideox_allowed_on_low_vram("cogvideox", vram_gb=VRAM_GB)

    from diffusers import CogVideoXImageToVideoPipeline, CogVideoXDPMScheduler
    from core.generation.video_optimizations import apply_fp8_quantization, apply_sageattention

    pipe = CogVideoXImageToVideoPipeline.from_pretrained(
        "THUDM/CogVideoX-5b-I2V", torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True, cache_dir=custom_cache,
    )
    pipe.scheduler = CogVideoXDPMScheduler.from_config(
        pipe.scheduler.config,
        timestep_spacing="trailing"
    )
    # PAS de VAE tiling a 480p -- cause des artefacts couleur/vagues
    pipe.vae.enable_slicing()

    opt_labels = []
    # Runtime FP8 can save VRAM, but it adds a long first-run quantization pause.
    # Keep it opt-in until we have a native pre-quantized CogVideoX loader.
    runtime_quant = os.environ.get("JOYBOY_COGVIDEO_RUNTIME_QUANT", "").lower() in {"1", "true", "yes", "on"}
    if runtime_quant and not IS_HIGH_END_GPU:
        transformer = getattr(pipe, "transformer", None)
        if transformer is not None:
            fp8_ok = apply_fp8_quantization(transformer, method="layerwise")
            if not fp8_ok:
                fp8_ok = apply_fp8_quantization(transformer, method="torchao")
            if fp8_ok:
                opt_labels.append("FP8")
    elif not IS_HIGH_END_GPU:
        print("[VIDEO] CogVideoX runtime quantization skip (pré-quantifié préféré; set JOYBOY_COGVIDEO_RUNTIME_QUANT=1 pour forcer)")

    move_video_to_device(pipe, "CogVideoX 5B", vram_needed_gb=20)

    try:
        if apply_sageattention(pipe, model_type="cogvideo"):
            opt_labels.append("SageAttn")
    except Exception as exc:
        print(f"[OPT] SageAttention CogVideoX skip: {exc}")

    if opt_labels:
        print(f"[VIDEO] CogVideoX 5B optimisé: {', '.join(opt_labels)} + offload auto")
    else:
        print("[VIDEO] CogVideoX 5B: offload auto (quantification indisponible)")
    return {"pipe": pipe}


def load_cogvideox_q4(custom_cache):
    """Load CogVideoX 5B I2V with a 4-bit transformer.

    This is intentionally separate from the BF16 loader. Diffusers cannot load the
    community GGUF-Q4 safetensors as a regular `from_pretrained` pipeline, so this
    path uses the supported BitsAndBytes 4-bit quantization flow instead.

    Returns:
        dict with 'pipe' key
    """
    from core.models.video_policy import assert_cogvideox_allowed_on_low_vram

    assert_cogvideox_allowed_on_low_vram("cogvideox-q4", vram_gb=VRAM_GB)

    from diffusers import (
        BitsAndBytesConfig,
        CogVideoXDPMScheduler,
        CogVideoXImageToVideoPipeline,
        CogVideoXTransformer3DModel,
    )
    from core.generation.video_optimizations import apply_sageattention

    model_id = "THUDM/CogVideoX-5b-I2V"

    try:
        import bitsandbytes as _bnb  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "CogVideoX Q4 requires bitsandbytes. Install/update bitsandbytes or set "
            "JOYBOY_COGVIDEO_BF16=1 to use the slower BF16/offload loader."
        ) from exc

    compute_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    qconfig = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )

    max_memory = {
        0: "7400MiB",
        "cpu": "28GiB",
    }

    print("[VIDEO] Loading CogVideoX 5B transformer in BitsAndBytes Q4 (GPU pinned)...")
    transformer = CogVideoXTransformer3DModel.from_pretrained(
        model_id,
        subfolder="transformer",
        quantization_config=qconfig,
        torch_dtype=compute_dtype,
        device_map={"": 0},
        max_memory=max_memory,
        low_cpu_mem_usage=True,
        cache_dir=custom_cache,
    )

    pipe = CogVideoXImageToVideoPipeline.from_pretrained(
        model_id,
        transformer=transformer,
        torch_dtype=compute_dtype,
        device_map="balanced",
        max_memory=max_memory,
        low_cpu_mem_usage=True,
        cache_dir=custom_cache,
    )
    pipe.scheduler = CogVideoXDPMScheduler.from_config(
        pipe.scheduler.config,
        timestep_spacing="trailing"
    )
    # Slicing is safer than tiling for CogVideoX; tiling can introduce color waves.
    pipe.vae.enable_slicing()

    opt_labels = ["BNB-Q4"]
    if os.environ.get("JOYBOY_COGVIDEO_Q4_SAGE", "").lower() in {"1", "true", "yes", "on"}:
        try:
            if apply_sageattention(pipe, model_type="cogvideo"):
                opt_labels.append("SageAttn")
        except Exception as exc:
            print(f"[OPT] SageAttention CogVideoX Q4 skip: {exc}")
    else:
        print("[OPT] SageAttention CogVideoX Q4 skip (set JOYBOY_COGVIDEO_Q4_SAGE=1 to force)")

    print(f"[VIDEO] CogVideoX 5B Q4 prêt: {', '.join(opt_labels)} + device_map balanced")
    return {"pipe": pipe}


def load_cogvideox_2b(custom_cache):
    """Load CogVideoX 2B text-to-video.

    Returns:
        dict with 'pipe' key
    """
    from diffusers import CogVideoXPipeline

    pipe = CogVideoXPipeline.from_pretrained(
        "THUDM/CogVideoX-2b", torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True, cache_dir=custom_cache,
    )
    # PAS de VAE tiling a 480p -- cause des artefacts couleur/vagues
    pipe.vae.enable_slicing()
    move_video_to_device(pipe, "CogVideoX 2B", vram_needed_gb=12)
    return {"pipe": pipe}


def load_wan_21_14b(custom_cache):
    """Load Wan 2.1 I2V 14B (480P).

    Returns:
        dict with 'pipe' key
    """
    from diffusers import WanImageToVideoPipeline, AutoencoderKLWan, WanTransformer3DModel
    from transformers import CLIPVisionModel, UMT5EncoderModel
    import safetensors.torch
    from core.generation.video_optimizations import optimize_video_pipeline

    _patch_ftfy_encoding('diffusers.pipelines.wan.pipeline_wan_i2v')

    model_id = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"

    cache_marker = os.path.join(custom_cache, "models--Wan-AI--Wan2.1-I2V-14B-480P-Diffusers")
    if os.path.exists(cache_marker):
        print(f"[MM] Loading Wan 2.1 I2V 14B (480P) -- depuis le cache disque")
    else:
        print(f"[MM] Loading Wan 2.1 I2V 14B (480P) -- premier telechargement")

    # PATCH: Desactiver mmap globalement pour safetensors
    _original_load_file = safetensors.torch.load_file
    safetensors.torch.load_file = _load_no_mmap
    print(f"[MM]   mmap desactive (lecture directe bytes)")

    try:
        # 1. TRANSFORMER (~28GB bf16) - quantification INT4 appliquee apres assemblage
        print(f"[MM]   -> Transformer...")
        transformer = WanTransformer3DModel.from_pretrained(
            model_id, subfolder="transformer", torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )
        gc.collect()

        # 2. Text encoder (~9GB bf16)
        print(f"[MM]   -> Text encoder...")
        text_encoder = UMT5EncoderModel.from_pretrained(
            model_id, subfolder="text_encoder", torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )
        gc.collect()

        # 3. VAE en float32 (meilleure qualite de decodage)
        print(f"[MM]   -> VAE (float32)...")
        vae = AutoencoderKLWan.from_pretrained(
            model_id, subfolder="vae", torch_dtype=torch.float32,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )

        # 4. Image encoder (CLIP)
        print(f"[MM]   -> Image encoder...")
        image_encoder = CLIPVisionModel.from_pretrained(
            model_id, subfolder="image_encoder", torch_dtype=torch.float32,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )
        gc.collect()

        # 5. Assemblage pipeline
        print(f"[MM]   -> Assemblage pipeline...")
        pipe = WanImageToVideoPipeline.from_pretrained(
            model_id,
            transformer=transformer,
            text_encoder=text_encoder,
            vae=vae,
            image_encoder=image_encoder,
            torch_dtype=torch.bfloat16,
            cache_dir=custom_cache,
        )

    finally:
        # TOUJOURS restaurer load_file original apres chargement
        safetensors.torch.load_file = _original_load_file

    # FIX CRITIQUE: Forcer VAE en float32 APRES assemblage pipeline
    # Le pipeline avec torch_dtype=bfloat16 peut ecraser le dtype du VAE
    pipe.vae.to(dtype=torch.float32)

    # VAE slicing: decode frame par frame (evite OOM, pas d'artefacts contrairement a tiling)
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pass

    # OPTIMISATIONS: offload strategy seulement
    # SageAttention DESACTIVE - monkey-patch global corrompt le VAE decoder (meme fix que Wan 2.2 5B)
    opt_result = optimize_video_pipeline(
        pipe, VRAM_GB,
        enable_sageattention=False,
        enable_fp8=False,
        model_type="wan",
    )
    gc.collect()
    opt_str = []
    if opt_result.get("fp8"):
        opt_str.append("FP8")
    if opt_result.get("sageattention"):
        opt_str.append("SageAttn")
    opt_str.append(opt_result.get("offload_strategy", ""))
    print(f"[MM]   -> Pret! Wan 2.1 14B [{', '.join(opt_str)}] | VRAM: {VRAM_GB:.0f}GB")

    return {"pipe": pipe}


def load_wan22_a14b(custom_cache):
    """Load Wan 2.2 I2V A14B (MoE).

    Returns:
        dict with 'pipe' key
    """
    from diffusers import WanImageToVideoPipeline
    from core.generation.video_optimizations import optimize_video_pipeline

    model_id = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"

    cache_marker = os.path.join(custom_cache, "models--Wan-AI--Wan2.2-I2V-A14B-Diffusers")
    if os.path.exists(cache_marker):
        print(f"[MM] Loading Wan 2.2 I2V A14B (MoE) -- depuis le cache disque")
    else:
        print(f"[MM] Loading Wan 2.2 I2V A14B (MoE) -- premier telechargement (~30GB)")

    # Chargement simplifie comme exemple officiel (pas de composants separes)
    print(f"[MM]   -> Pipeline complet (auto-load tous composants)...")
    pipe = WanImageToVideoPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        cache_dir=custom_cache,
    )

    # FIX: VAE float32 APRES assemblage pipeline (bf16 ecrase le dtype sinon)
    pipe.vae.to(dtype=torch.float32)
    print(f"[MM]   -> VAE float32 applique")

    # VAE slicing pour eviter OOM au decode
    pipe.vae.enable_slicing()
    print(f"[MM]   -> VAE slicing active")

    # OPTIMISATIONS: offload seulement (SageAttention/FP8 desactives pour debug)
    opt_result = optimize_video_pipeline(
        pipe, VRAM_GB,
        enable_sageattention=False,
        enable_fp8=False
    )
    gc.collect()
    print(f"[MM]   -> Pret! MoE 27B [{opt_result.get('offload_strategy', '')}] | VRAM: {VRAM_GB:.0f}GB")

    return {"pipe": pipe}


def load_hunyuan(custom_cache):
    """Load HunyuanVideo 1.5 I2V.

    Returns:
        dict with 'pipe' key
    """
    from diffusers import HunyuanVideo15ImageToVideoPipeline
    from core.models import VIDEO_MODELS
    from core.generation.video_optimizations import optimize_video_pipeline

    # Hugging Face Hub kernels are optional and can conflict with the pinned
    # transformers/diffusers stack. Keep them opt-in so video loading cannot
    # break the main JoyBoy process by installing `kernels` globally.
    if os.environ.get("JOYBOY_ALLOW_HUB_KERNELS", "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            import kernels  # noqa: F401
        except Exception as exc:
            print(f"[MM] Hub kernels indisponibles, fallback PyTorch ({exc.__class__.__name__})")

    model_id = VIDEO_MODELS["hunyuan"]["id"]
    display_name = VIDEO_MODELS["hunyuan"]["name"]

    cache_marker = os.path.join(custom_cache, f"models--{model_id.replace('/', '--')}")
    if os.path.exists(cache_marker):
        print(f"[MM] Loading {display_name} -- depuis le cache disque")
    else:
        print(f"[MM] Loading {display_name} -- premier telechargement")

    pipe = HunyuanVideo15ImageToVideoPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        cache_dir=custom_cache,
    )

    # NOUVELLES OPTIMISATIONS: FP8 + Group Offload + SageAttention
    opt_result = optimize_video_pipeline(
        pipe, VRAM_GB,
        enable_sageattention=True,
        enable_fp8=True
    )
    # VAE slicing: decode frame par frame (evite OOM, pas d'artefacts contrairement a tiling)
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pass
    gc.collect()
    opt_str = []
    if opt_result.get("fp8"):
        opt_str.append("FP8")
    if opt_result.get("sageattention"):
        opt_str.append("SageAttn")
    opt_str.append(opt_result.get("offload_strategy", ""))
    print(f"[MM]   -> Pret! {display_name} (8.3B) [{', '.join(opt_str)}] | VRAM: {VRAM_GB:.0f}GB")

    return {"pipe": pipe}


def load_wan22_5b(model_name, custom_cache):
    """Load Wan 2.2 TI2V 5B or FastWan (distilled DMD).

    Args:
        model_name: "wan22-5b" or "fastwan"

    Returns:
        dict with 'pipe' key
    """
    from diffusers import WanImageToVideoPipeline, AutoencoderKLWan, WanTransformer3DModel
    from diffusers.schedulers import UniPCMultistepScheduler
    import safetensors.torch
    from core.models import VIDEO_MODELS
    from core.generation.video_optimizations import optimize_video_pipeline

    _patch_ftfy_encoding('diffusers.pipelines.wan.pipeline_wan_i2v')

    model_id = VIDEO_MODELS[model_name]["id"]
    display_name = VIDEO_MODELS[model_name]["name"]

    # Pour FastWan, le transformer vient de FastVideo mais les autres
    # composants (VAE, image_encoder, text_encoder) du modele standard Wan 2.2 5B
    base_model_id = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"

    cache_marker = os.path.join(custom_cache, f"models--{model_id.replace('/', '--')}")
    if os.path.exists(cache_marker):
        print(f"[MM] Loading {display_name} -- depuis le cache disque")
    else:
        print(f"[MM] Loading {display_name} -- premier telechargement (~10GB)")

    # PATCH: Desactiver mmap sur Windows
    _original_load_file = safetensors.torch.load_file
    safetensors.torch.load_file = _load_no_mmap
    print(f"[MM]   mmap desactive (lecture directe bytes)")

    try:
        # CHARGEMENT SIMPLIFIE (comme exemple officiel HuggingFace)
        # 1. VAE en float32 (obligatoire pour qualite)
        vae_source = base_model_id if model_name == "fastwan" else model_id
        print(f"[MM]   -> VAE (float32)...")
        vae = AutoencoderKLWan.from_pretrained(
            vae_source, subfolder="vae", torch_dtype=torch.float32,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )
        gc.collect()

        # 2. Pipeline complet avec VAE custom (laisser diffusers charger le reste)
        print(f"[MM]   -> Pipeline complet...")
        pipe = WanImageToVideoPipeline.from_pretrained(
            model_id,
            vae=vae,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            cache_dir=custom_cache,
        )

    finally:
        safetensors.torch.load_file = _original_load_file

    # Scheduler UniPC avec flow_shift=5.0 (720p par defaut, ajuste a la generation)
    pipe.scheduler = UniPCMultistepScheduler.from_config(
        pipe.scheduler.config,
        flow_shift=5.0
    )

    # VAE slicing: necessaire sinon OOM au decode
    pipe.vae.enable_slicing()
    print(f"[MM]   -> VAE slicing active")

    # FIX CRITIQUE: Forcer VAE en float32 APRES assemblage pipeline
    # Le pipeline avec torch_dtype=bfloat16 ecrase le dtype du VAE passe en parametre
    # Sans float32, la video est floue/corrompue (artefacts de precision)
    # Ref: https://github.com/Wan-Video/Wan2.2/issues/211
    pipe.vae.to(dtype=torch.float32)
    print(f"[MM]   -> VAE force float32 (fix qualite)")

    # TAEHV: telecharge le mini-VAE si absent (utilise au decodage dans processing.py)
    try:
        from core.taehv_decode import _ensure_taehv_files
        _ensure_taehv_files()
        print(f"[MM]   -> TAEHV (mini-VAE) disponible pour decodage rapide")
    except Exception as e:
        print(f"[MM]   -> TAEHV indisponible ({e}), le VAE standard sera utilise")

    # OPTIMISATIONS: offload strategy seulement
    # SageAttention DESACTIVE - monkey-patch global corrompt le VAE decoder
    opt_result = optimize_video_pipeline(
        pipe, VRAM_GB,
        enable_sageattention=False,
        enable_fp8=False
    )
    gc.collect()
    suffix = "distille DMD" if model_name == "fastwan" else "dense"
    opt_str = []
    if opt_result.get("fp8"):
        opt_str.append("FP8")
    if opt_result.get("sageattention"):
        opt_str.append("SageAttn")
    opt_str.append(opt_result.get("offload_strategy", ""))
    print(f"[MM]   -> Pret! {display_name} (5B {suffix}) [{', '.join(opt_str)}] | VRAM: {VRAM_GB:.0f}GB")

    return {"pipe": pipe}


def load_wan22_t2v_14b(custom_cache):
    """Load Wan 2.2 T2V 14B MoE (text-to-video only, no image input).

    Returns:
        dict with 'pipe' key
    """
    from diffusers import WanPipeline, AutoencoderKLWan
    from diffusers.schedulers import UniPCMultistepScheduler
    import safetensors.torch
    from core.models import VIDEO_MODELS
    from core.generation.video_optimizations import optimize_video_pipeline

    _patch_ftfy_encoding('diffusers.pipelines.wan.pipeline_wan')

    model_id = VIDEO_MODELS["wan22-t2v-14b"]["id"]  # "Wan-AI/Wan2.2-T2V-A14B-Diffusers"
    display_name = VIDEO_MODELS["wan22-t2v-14b"]["name"]

    cache_marker = os.path.join(custom_cache, f"models--{model_id.replace('/', '--')}")
    if os.path.exists(cache_marker):
        print(f"[MM] Loading {display_name} -- depuis le cache disque")
    else:
        print(f"[MM] Loading {display_name} -- premier telechargement (~15GB)")

    # PATCH: Desactiver mmap sur Windows
    _original_load_file = safetensors.torch.load_file
    safetensors.torch.load_file = _load_no_mmap
    print(f"[MM]   mmap desactive (lecture directe bytes)")

    try:
        # 1. VAE en float32 (obligatoire pour qualite)
        print(f"[MM]   -> VAE (float32)...")
        vae = AutoencoderKLWan.from_pretrained(
            model_id, subfolder="vae", torch_dtype=torch.float32,
            low_cpu_mem_usage=True, cache_dir=custom_cache,
        )
        gc.collect()

        # 2. Pipeline T2V complet (WanPipeline, pas WanImageToVideoPipeline)
        print(f"[MM]   -> Pipeline T2V complet...")
        pipe = WanPipeline.from_pretrained(
            model_id,
            vae=vae,
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            cache_dir=custom_cache,
        )

    finally:
        safetensors.torch.load_file = _original_load_file

    # Scheduler UniPC avec flow_shift=5.0
    pipe.scheduler = UniPCMultistepScheduler.from_config(
        pipe.scheduler.config,
        flow_shift=5.0
    )

    # VAE slicing: necessaire sinon OOM au decode
    pipe.vae.enable_slicing()
    print(f"[MM]   -> VAE slicing active")

    # FIX CRITIQUE: Forcer VAE en float32 APRES assemblage pipeline
    pipe.vae.to(dtype=torch.float32)
    print(f"[MM]   -> VAE force float32 (fix qualite)")

    # OPTIMISATIONS
    opt_result = optimize_video_pipeline(
        pipe, VRAM_GB,
        enable_sageattention=False,
        enable_fp8=False
    )
    gc.collect()
    opt_str = []
    if opt_result.get("fp8"):
        opt_str.append("FP8")
    if opt_result.get("sageattention"):
        opt_str.append("SageAttn")
    opt_str.append(opt_result.get("offload_strategy", ""))
    print(f"[MM]   -> Pret! {display_name} (14B MoE) [{', '.join(opt_str)}] | VRAM: {VRAM_GB:.0f}GB")

    return {"pipe": pipe}


def load_lightx2v(model_name, custom_cache):
    """Load a lightweight LightX2V backend descriptor.

    The actual LightX2V model is launched in a subprocess during generation.
    This keeps optional kernels and third-party globals out of JoyBoy's long
    running Flask process.
    """
    from core.models import VIDEO_MODELS
    from core.models.lightx2v_backend import LightX2VBackend, get_lightx2v_backend_status, install_lightx2v_backend

    meta = VIDEO_MODELS.get(model_name)
    if not meta:
        raise ValueError(f"Modele LightX2V inconnu: {model_name}")

    status = get_lightx2v_backend_status()
    if not status.get("ready"):
        missing = status.get("missing_python_package")
        reason = f" (dépendance manquante: {missing})" if missing else ""
        print(f"[MM] LightX2V backend incomplet{reason}. Réparation automatique...")
        try:
            status = install_lightx2v_backend()
        except Exception as exc:
            raise RuntimeError(
                "Backend LightX2V non prêt. Relance le téléchargement depuis Modèles > Vidéo "
                f"ou installe la dépendance manquante ({missing or 'pack LightX2V'})."
            ) from exc
        print(f"[MM] LightX2V backend réparé: {status.get('repo_dir')}")
    else:
        print(f"[MM] LightX2V backend prêt: {status.get('repo_dir')}")
    return {
        "pipe": LightX2VBackend(model_name, meta, custom_cache),
        "extras": {"external_backend": "lightx2v"},
    }


def load_ltx(custom_cache):
    """Load LTX-Video 2B (distilled 0.9.8 with fallback to base 0.9.0).

    Returns:
        dict with 'pipe' and 'extras' keys.
        extras may contain 'ltx_upsampler' and 'ltx_upsample_pipe'.
    """
    from core.models import VIDEO_MODELS, IS_MAC
    from core.generation.video_optimizations import apply_sageattention, is_sageattention_available, can_triton_compile

    model_id = VIDEO_MODELS["ltx"]["id"]  # "Lightricks/LTX-Video"
    display_name = VIDEO_MODELS["ltx"]["name"]
    print(f"[MM] Loading {display_name}...")

    pipe = None
    ltx_upsampler = None
    ltx_upsample_pipe = None
    low_vram = 0 < float(VRAM_GB or 0) <= 10
    force_multiscale = os.environ.get("JOYBOY_LTX_LOW_VRAM_MULTISCALE", "").strip().lower() in {"1", "true", "yes", "on"}
    force_sage = os.environ.get("JOYBOY_LTX_LOW_VRAM_SAGE", "").strip().lower() in {"1", "true", "yes", "on"}

    try:
        # Pipeline moderne (diffusers 0.32+) + modele 2B distille 0.9.8
        from diffusers import LTXConditionPipeline, LTXVideoTransformer3DModel, AutoencoderKLLTXVideo
        from huggingface_hub import hf_hub_download

        # 1. Telecharger le safetensors distille (6.34 GB, une seule fois)
        print(f"[MM]   -> Telechargement 2B distille 0.9.8 (6.34 GB)...")
        distilled_path = hf_hub_download(
            repo_id=model_id,
            filename="ltxv-2b-0.9.8-distilled.safetensors",
            cache_dir=custom_cache,
        )

        # 2. Charger transformer + VAE depuis le single file
        print(f"[MM]   -> Transformer + VAE (from single file)...")
        transformer = LTXVideoTransformer3DModel.from_single_file(
            distilled_path, torch_dtype=torch.bfloat16,
        )
        vae = AutoencoderKLLTXVideo.from_single_file(
            distilled_path, torch_dtype=torch.bfloat16,
        )
        gc.collect()

        # 3. Assembler pipeline (T5 + tokenizer + scheduler depuis le repo)
        print(f"[MM]   -> Assemblage pipeline (T5-XXL + tokenizer depuis repo)...")
        pipe = LTXConditionPipeline.from_pretrained(
            model_id,
            transformer=transformer,
            vae=vae,
            torch_dtype=torch.bfloat16,
            cache_dir=custom_cache,
        )
        # Le scheduler du repo a use_dynamic_shifting=True mais le pipeline
        # utilise linear_quadratic_schedule et ne passe pas mu -> crash
        # Il faut recreer le scheduler car config est un FrozenDict
        from diffusers.schedulers import FlowMatchEulerDiscreteScheduler
        pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(
            pipe.scheduler.config,
            use_dynamic_shifting=False,
        )
        print(f"[MM]   -> LTXConditionPipeline (2B distille 0.9.8)")

        # 4. Charger le spatial upscaler pour multi-scale (500MB).
        # Sur 8GB, c'est la combinaison upscaler + double passe qui rend le
        # chemin Diffusers trop fragile. Le vrai profil rapide 8GB est le stack
        # Q8 dédié, pas ce multi-scale générique.
        if low_vram and not force_multiscale:
            print("[MM]   -> Spatial upscaler skip (<=10GB VRAM): single-pass low-VRAM")
        else:
            try:
                from diffusers.pipelines.ltx.modeling_latent_upsampler import LTXLatentUpsamplerModel
                from diffusers import LTXLatentUpsamplePipeline

                print(f"[MM]   -> Telechargement spatial upscaler (500 MB)...")
                ltx_upsampler = LTXLatentUpsamplerModel.from_pretrained(
                    "a-r-r-o-w/LTX-0.9.8-Latent-Upsampler",
                    torch_dtype=torch.bfloat16,
                    cache_dir=custom_cache,
                )
                ltx_upsample_pipe = LTXLatentUpsamplePipeline(
                    vae=pipe.vae,
                    latent_upsampler=ltx_upsampler,
                ).to(torch.bfloat16)
                print(f"[MM]   -> Spatial upscaler pret (multi-scale active)")
            except Exception as e_up:
                print(f"[MM]   Spatial upscaler indispo ({e_up}), single-pass uniquement")
                ltx_upsampler = None
                ltx_upsample_pipe = None

    except (ImportError, Exception) as e:
        # Fallback: ancien pipeline avec modele base 0.9.0
        print(f"[MM]   -> Distille indispo ({e}), fallback modele base...")
        from diffusers import LTXImageToVideoPipeline

        pipe = LTXImageToVideoPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.bfloat16,
            cache_dir=custom_cache,
        )
        print(f"[MM]   -> LTXImageToVideoPipeline (2B base 0.9.0)")

    # Activer le decodage VAE frame par frame (beaucoup plus rapide, moins de VRAM)
    # https://github.com/huggingface/diffusers/pull/10488
    if hasattr(pipe.vae, 'use_framewise_decoding'):
        pipe.vae.use_framewise_decoding = True
        print(f"[MM]   -> VAE framewise decoding active")

    # OPTIMISATIONS LTX: FP8 + model_cpu_offload + SageAttention
    # NOTE: LTX utilise T5-XXL qui ne supporte PAS group offload (embeddings CPU/CUDA mismatch)
    # On force model_cpu_offload pour LTX, meme avec beaucoup de VRAM
    if IS_MAC:
        pipe.to("mps")
        print(f"[VIDEO] {display_name}: MPS")
        opt_result = {"fp8": False, "sageattention": False, "offload_strategy": "mps"}
    else:
        opt_result = {"fp8": False, "sageattention": False, "offload_strategy": "model_cpu_offload"}

        # FP8 sur le transformer (avant offload)
        transformer = getattr(pipe, 'transformer', None)
        if transformer:
            from core.generation.video_optimizations import apply_fp8_quantization
            opt_result["fp8"] = apply_fp8_quantization(transformer, method="layerwise")

        # model_cpu_offload (PAS group offload - T5 incompatible)
        if VRAM_GB >= 24:
            pipe.to("cuda")
            opt_result["offload_strategy"] = "gpu_direct"
            print(f"[OPT] GPU direct ({VRAM_GB:.1f}GB VRAM)")
        else:
            pipe.enable_model_cpu_offload()
            print(f"[OPT] model_cpu_offload ({VRAM_GB:.1f}GB VRAM) - T5 incompatible avec group offload")

        # SageAttention est rapide quand le stack compile proprement, mais reste
        # expérimental avec LTX + CPU offload sur petites cartes Windows/Shadow.
        if low_vram and not force_sage:
            print("[OPT] SageAttention LTX skip (<=10GB VRAM; set JOYBOY_LTX_LOW_VRAM_SAGE=1 to force)")
            opt_result["sageattention"] = False
        elif is_sageattention_available() and can_triton_compile():
            opt_result["sageattention"] = apply_sageattention(pipe)
        else:
            print(f"[OPT] SageAttention desactive (Triton ne peut pas compiler)")
            opt_result["sageattention"] = False

    # Placement GPU pour le upscale pipe
    # NOTE: Si group offload est actif sur le pipeline principal, les composants partages
    # (transformer, vae) ont deja group offload - on ne peut pas ajouter model_cpu_offload
    if ltx_upsample_pipe is not None:
        uses_group_offload = opt_result.get("offload_strategy", "").startswith("group_offload")
        if IS_MAC:
            ltx_upsample_pipe.to("mps")
        elif torch.cuda.is_available():
            if VRAM_GB >= 24:
                ltx_upsample_pipe.to("cuda")
            elif not uses_group_offload:
                # Seulement si le pipeline principal n'utilise pas group offload
                ltx_upsample_pipe.enable_model_cpu_offload()
            # Si group offload est actif, les composants partages sont deja configures

    gc.collect()
    if not IS_MAC:
        opt_str = []
        if opt_result.get("fp8"):
            opt_str.append("FP8")
        if opt_result.get("sageattention"):
            opt_str.append("SageAttn")
        opt_str.append(opt_result.get("offload_strategy", ""))
        print(f"[MM]   -> Pret! {display_name} [{', '.join(opt_str)}] | VRAM: {VRAM_GB:.0f}GB")
    else:
        print(f"[MM]   -> Pret! {display_name} | MPS")

    return {
        "pipe": pipe,
        "extras": {
            "ltx_upsampler": ltx_upsampler,
            "ltx_upsample_pipe": ltx_upsample_pipe,
        }
    }


def load_framepack(custom_cache):
    """Load FramePack F1 I2V through the official Diffusers pipeline.

    FramePack is HunyuanVideo-based and needs a custom transformer plus a
    SigLIP image encoder. It is not as fast as SVD on 8GB, but it is now a real
    runnable backend instead of a roadmap placeholder.
    """
    _ensure_framepack_dependency_versions()

    from diffusers import HunyuanVideoFramepackPipeline, HunyuanVideoFramepackTransformer3DModel
    from transformers import SiglipImageProcessor, SiglipVisionModel
    from core.models import VIDEO_MODELS, IS_MAC

    model_id = VIDEO_MODELS["framepack"]["id"]
    display_name = VIDEO_MODELS["framepack"]["name"]
    compute_dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16

    print(f"[MM] Loading {display_name}...")
    print(f"[MM]   -> Transformer FramePack F1 ({model_id})...")
    transformer = HunyuanVideoFramepackTransformer3DModel.from_pretrained(
        model_id,
        torch_dtype=compute_dtype,
        cache_dir=custom_cache,
        low_cpu_mem_usage=True,
    )

    print("[MM]   -> SigLIP image encoder...")
    feature_extractor = SiglipImageProcessor.from_pretrained(
        "lllyasviel/flux_redux_bfl",
        subfolder="feature_extractor",
        cache_dir=custom_cache,
    )
    image_encoder = SiglipVisionModel.from_pretrained(
        "lllyasviel/flux_redux_bfl",
        subfolder="image_encoder",
        torch_dtype=torch.float16,
        cache_dir=custom_cache,
        low_cpu_mem_usage=True,
    )

    print("[MM]   -> HunyuanVideo base components...")
    pipe = HunyuanVideoFramepackPipeline.from_pretrained(
        "hunyuanvideo-community/HunyuanVideo",
        transformer=transformer,
        feature_extractor=feature_extractor,
        image_encoder=image_encoder,
        torch_dtype=torch.float16,
        cache_dir=custom_cache,
        low_cpu_mem_usage=True,
    )

    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass
    try:
        pipe.vae.enable_slicing()
    except Exception:
        pass

    if torch.cuda.is_available():
        force_framepack_offload = os.environ.get("JOYBOY_FRAMEPACK_FORCE_MODEL_CPU_OFFLOAD", "").strip().lower() in {"1", "true", "yes", "on"}
        force_framepack_direct = os.environ.get("JOYBOY_FRAMEPACK_GPU_DIRECT", "").strip().lower() in {"1", "true", "yes", "on"}
        framepack_gpu_direct = IS_HIGH_END_GPU and (float(VRAM_GB or 0) >= 48 or force_framepack_direct)
        if force_framepack_offload:
            pipe.enable_model_cpu_offload()
            print(f"[MM]   -> FramePack model_cpu_offload forcé ({VRAM_GB:.1f}GB VRAM)")
        elif not framepack_gpu_direct:
            try:
                from diffusers.hooks import apply_group_offloading

                onload_device = torch.device("cuda")
                offload_device = torch.device("cpu")
                low_cpu_mem_usage = 0 < float(VRAM_GB or 0) <= 10
                for component in (pipe.text_encoder, pipe.text_encoder_2, pipe.transformer):
                    if component is None:
                        continue
                    apply_group_offloading(
                        component,
                        onload_device,
                        offload_device,
                        offload_type="leaf_level",
                        use_stream=True,
                        low_cpu_mem_usage=low_cpu_mem_usage,
                    )
                pipe.image_encoder.to(onload_device)
                pipe.vae.to(onload_device)
                print(f"[MM]   -> FramePack group offload actif ({VRAM_GB:.1f}GB VRAM)")
            except Exception as exc:
                print(f"[MM]   -> Group offload indisponible ({exc}), fallback model_cpu_offload")
                pipe.enable_model_cpu_offload()
        elif IS_HIGH_END_GPU:
            pipe.to("cuda")
            print("[MM]   -> FramePack GPU direct")
        else:
            pipe.enable_model_cpu_offload()
            print("[MM]   -> FramePack model_cpu_offload")
    elif IS_MAC:
        pipe.to("mps")

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print(f"[MM]   -> Pret! {display_name} [{DTYPE_NAME}/FramePack]")
    return {"pipe": pipe}


def load_ltx2(custom_cache):
    """Load LTX-2 19B (distilled, 8 steps).

    Returns:
        dict with 'pipe' key.
    """
    from core.models import VIDEO_MODELS, IS_MAC

    model_id = VIDEO_MODELS["ltx2"]["id"]  # "Lightricks/LTX-2"
    display_name = VIDEO_MODELS["ltx2"]["name"]
    print(f"[MM] Loading {display_name}...")

    try:
        from diffusers import LTX2Pipeline, LTX2ImageToVideoPipeline
    except ImportError:
        # Auto-install diffusers depuis git (LTX-2 pas encore dans les releases PyPI)
        print("[MM]   -> LTX2 non trouvé, upgrade diffusers depuis git...")
        import subprocess, sys
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "git+https://github.com/huggingface/diffusers.git", "-q"
        ])
        from diffusers import LTX2Pipeline, LTX2ImageToVideoPipeline

    # Charger text encoder (Gemma 3 12B) séparément en NF4 pour économiser ~18GB RAM
    # bf16 = ~24GB RAM, NF4 = ~6GB RAM
    text_encoder = None
    has_bnb_encoder = False
    try:
        from transformers import Gemma3ForConditionalGeneration, BitsAndBytesConfig
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        print(f"[MM]   -> Chargement Gemma 3 12B en NF4 (int4)...")
        text_encoder = Gemma3ForConditionalGeneration.from_pretrained(
            model_id, subfolder="text_encoder",
            quantization_config=quant_config,
            torch_dtype=torch.bfloat16,
            cache_dir=custom_cache,
        )
        has_bnb_encoder = True
        print(f"[MM]   -> Gemma 3 12B quantifié en NF4 OK")
    except Exception as e:
        print(f"[MM]   -> Quantification NF4 échouée ({e}), Gemma 3 en bf16")
        text_encoder = None

    # Charger le pipeline I2V
    print(f"[MM]   -> Téléchargement/chargement {model_id}...")
    load_kwargs = dict(
        torch_dtype=torch.bfloat16,
        cache_dir=custom_cache,
    )
    if text_encoder is not None:
        load_kwargs["text_encoder"] = text_encoder

    pipe = LTX2ImageToVideoPipeline.from_pretrained(model_id, **load_kwargs)

    # Offload strategy
    # BnB NF4 params sont incompatibles avec sequential_cpu_offload (Params4bit can't move to meta)
    # → toujours model_cpu_offload quand le text encoder est quantifié
    if IS_MAC:
        pipe.to("mps")
        print(f"[VIDEO] {display_name}: MPS")
    elif VRAM_GB >= 36 and not has_bnb_encoder:
        pipe.to("cuda")
        print(f"[OPT] GPU direct ({VRAM_GB:.1f}GB VRAM)")
    else:
        # model_cpu_offload: déplace un module entier à la fois (compatible BnB)
        pipe.enable_model_cpu_offload()
        print(f"[OPT] model_cpu_offload ({VRAM_GB:.1f}GB VRAM)")

    gc.collect()
    print(f"[MM]   -> Prêt! {display_name} | VRAM: {VRAM_GB:.0f}GB")

    return {
        "pipe": pipe,
        "extras": {}
    }


def _hf_local_or_download(repo_id, filename, cache_dir):
    """Prefer JoyBoy's local mirror before asking Hugging Face again."""
    from huggingface_hub import hf_hub_download, try_to_load_from_cache

    local_dir = os.path.join(cache_dir, repo_id.replace("/", "--")) if cache_dir else ""
    local_path = os.path.join(local_dir, filename) if local_dir else ""
    if local_path and os.path.exists(local_path):
        return local_path

    cached = try_to_load_from_cache(repo_id, filename, cache_dir=cache_dir)
    if isinstance(cached, str) and os.path.exists(cached):
        return cached

    cached = try_to_load_from_cache(repo_id, filename)
    if isinstance(cached, str) and os.path.exists(cached):
        return cached

    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        cache_dir=cache_dir,
        resume_download=True,
    )


def _ensure_ltx_openimageio_importable() -> bool:
    """Make the optional OpenImageIO import available for ltx_pipelines.

    The LTX pipeline imports its media I/O helpers at package import time. JoyBoy
    feeds images directly and does not need that module for normal generation,
    but the missing import still prevents ``DistilledPipeline`` from loading on
    fresh cloud machines.
    """
    try:
        import OpenImageIO  # noqa: F401
        return True
    except ImportError:
        pass

    print("[MM]   -> Installation OpenImageIO pour ltx_pipelines...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "OpenImageIO", "-q"])
        import OpenImageIO  # noqa: F401
        return True
    except Exception as exc:
        print(f"[MM]   -> OpenImageIO indisponible ({exc.__class__.__name__}); shim import activé.")

    if "OpenImageIO" not in sys.modules:
        fake_openimageio = types.ModuleType("OpenImageIO")
        fake_openimageio.__spec__ = ModuleSpec("OpenImageIO", None)

        def _openimageio_unavailable(*_args, **_kwargs):
            raise ImportError(
                "OpenImageIO is unavailable in this environment; ltx_pipelines "
                "media file helpers are disabled, but direct JoyBoy image/video "
                "generation can continue if those helpers are not used."
            )

        fake_openimageio.ImageInput = types.SimpleNamespace(open=_openimageio_unavailable)
        fake_openimageio.ImageOutput = types.SimpleNamespace(create=_openimageio_unavailable)
        sys.modules["OpenImageIO"] = fake_openimageio
    return False


def _resolve_ltx_gemma_root(cache_dir):
    """Resolve the text encoder root for ltx_pipelines without hitting gated Google repos."""
    from huggingface_hub import snapshot_download, try_to_load_from_cache

    env_root = (os.environ.get("JOYBOY_LTX_GEMMA_ROOT") or "").strip()
    if env_root:
        if os.path.exists(os.path.join(env_root, "config.json")):
            print(f"[MM]   -> Gemma root via JOYBOY_LTX_GEMMA_ROOT: {env_root}")
            return env_root
        raise RuntimeError(
            "JOYBOY_LTX_GEMMA_ROOT pointe vers un dossier invalide: "
            f"{env_root} (config.json introuvable)"
        )

    # Lightricks publishes the QAT Gemma variant used by the official LTX
    # pipelines. Avoid downloading google/gemma-3-12b-it by default because it
    # is gated and crashes fresh cloud installs without a Hugging Face login.
    gemma_model_id = (
        os.environ.get("JOYBOY_LTX_GEMMA_MODEL_ID")
        or "Lightricks/gemma-3-12b-it-qat-q4_0-unquantized"
    ).strip()

    for repo_id in (gemma_model_id, "google/gemma-3-12b-it"):
        cached = try_to_load_from_cache(repo_id, "config.json", cache_dir=cache_dir)
        if not isinstance(cached, str):
            cached = try_to_load_from_cache(repo_id, "config.json")
        if isinstance(cached, str) and os.path.exists(cached):
            root = os.path.dirname(cached)
            print(f"[MM]   -> Gemma trouvé en cache: {repo_id}")
            return root

    print(f"[MM]   -> Téléchargement Gemma LTX: {gemma_model_id}")
    try:
        return snapshot_download(
            gemma_model_id,
            cache_dir=cache_dir,
            resume_download=True,
        )
    except Exception as exc:
        raise RuntimeError(
            "Impossible de préparer le text encoder LTX. Par défaut JoyBoy utilise "
            f"{gemma_model_id}; configure JOYBOY_LTX_GEMMA_ROOT vers un dossier Gemma "
            "déjà accepté/téléchargé, ou JOYBOY_LTX_GEMMA_MODEL_ID vers un repo accessible. "
            f"Erreur originale: {exc}"
        ) from exc


def load_ltx2_fp8(custom_cache, model_name="ltx2_fp8"):
    """Load LTX-2/LTX-2.3 FP8 via ltx_pipelines officiel.

    Utilise le package ltx_pipelines de Lightricks avec le checkpoint fp8 (20GB).
    Pas de quantification runtime → chargement rapide, pas de gaspillage RAM.

    Returns:
        dict with 'pipe' key (TI2VidTwoStagesPipeline or DistilledPipeline),
        and 'extras' with 'ltx2_native': True.
    """
    from core.models import VIDEO_MODELS, IS_MAC
    meta = VIDEO_MODELS.get(model_name, VIDEO_MODELS["ltx2_fp8"])
    display_name = f"{meta.get('name', model_name)} (ltx_pipelines)"
    print(f"[MM] Loading {display_name}...")

    # 1. Auto-install ltx_pipelines si absent
    openimageio_available = _ensure_ltx_openimageio_importable()
    try:
        from ltx_pipelines.distilled import DistilledPipeline
    except (ImportError, OSError) as _e:
        print(f"[MM]   -> ltx_pipelines non disponible ({_e.__class__.__name__}), installation...")
        # --no-deps pour NE PAS écraser torch/torchvision/torchaudio CUDA
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--no-deps",
            "git+https://github.com/Lightricks/LTX-2.git#subdirectory=packages/ltx-core",
            "-q"
        ])
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "--no-deps",
            "git+https://github.com/Lightricks/LTX-2.git#subdirectory=packages/ltx-pipelines",
            "-q"
        ])
        # Installer torchaudio si absent (même version que torch existant)
        try:
            import torchaudio
        except ImportError:
            _torch_ver = torch.__version__.split('+')[0]  # ex: "2.6.0"
            _cuda_tag = ""
            if '+cu' in torch.__version__:
                _cuda_tag = '+' + torch.__version__.split('+')[1]  # ex: "+cu124"
            _ta_spec = f"torchaudio=={_torch_ver}{_cuda_tag}"
            print(f"[MM]   -> Installation torchaudio ({_ta_spec})...")
            _pip_args = [sys.executable, "-m", "pip", "install", _ta_spec, "-q"]
            if _cuda_tag:
                _pip_args += ["--index-url", f"https://download.pytorch.org/whl/{_cuda_tag.lstrip('+')}"]
            subprocess.check_call(_pip_args)
        openimageio_available = _ensure_ltx_openimageio_importable()
        from ltx_pipelines.distilled import DistilledPipeline

    # 2. Télécharger les checkpoints nécessaires via huggingface_hub
    import os

    is_ltx23 = model_name == "ltx23_fp8"
    if is_ltx23:
        repo_id = "Lightricks/LTX-2.3-fp8"
        upsampler_repo_id = "Lightricks/LTX-2.3"
        checkpoint_filename = "ltx-2.3-22b-distilled-fp8.safetensors"
        upsampler_filename = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
        distilled_lora_filename = None
    else:
        repo_id = "Lightricks/LTX-2"
        upsampler_repo_id = repo_id
        checkpoint_filename = "ltx-2-19b-dev-fp8.safetensors"
        upsampler_filename = "ltx-2-spatial-upscaler-x2-1.0.safetensors"
        distilled_lora_filename = "ltx-2-19b-distilled-lora-384.safetensors"

    cache_dir = custom_cache or os.path.join(os.path.dirname(__file__), '..', '..', 'models_cache')

    print("[MM]   -> Checkpoint FP8...")
    checkpoint_path = _hf_local_or_download(repo_id, checkpoint_filename, cache_dir)

    print("[MM]   -> Spatial upsampler...")
    upsampler_path = _hf_local_or_download(upsampler_repo_id, upsampler_filename, cache_dir)

    distilled_lora_path = None
    if distilled_lora_filename:
        print("[MM]   -> Distilled LoRA...")
        distilled_lora_path = _hf_local_or_download(repo_id, distilled_lora_filename, cache_dir)

    # 3. Chemin vers Gemma 3. LTX utilise un text encoder Gemma; la variante
    # Google est gated, donc le défaut JoyBoy passe par le repo Lightricks QAT.
    gemma_root = _resolve_ltx_gemma_root(cache_dir)

    # 4. Construire le pipeline
    print("[MM]   -> Construction pipeline FP8...")
    from ltx_core.loader import LoraPathStrengthAndSDOps
    import inspect

    loras = []
    if distilled_lora_path:
        loras.append(
            LoraPathStrengthAndSDOps(
                path=distilled_lora_path,
                strength=1.0,
                sd_ops=None,
            )
        )

    init_params = inspect.signature(DistilledPipeline).parameters
    pipe_kwargs = {
        "spatial_upsampler_path": upsampler_path,
        "gemma_root": gemma_root,
        "loras": loras,
        "device": torch.device("cuda"),
    }
    if "distilled_checkpoint_path" in init_params:
        pipe_kwargs["distilled_checkpoint_path"] = checkpoint_path
    else:
        pipe_kwargs["checkpoint_path"] = checkpoint_path
    if "checkpoint_path" in init_params and "checkpoint_path" not in pipe_kwargs:
        pipe_kwargs["checkpoint_path"] = checkpoint_path
    if "distilled_checkpoint_path" not in init_params:
        pipe_kwargs.pop("distilled_checkpoint_path", None)
    if "device" not in init_params:
        pipe_kwargs.pop("device", None)
    if "loras" not in init_params:
        pipe_kwargs.pop("loras", None)

    pipe = DistilledPipeline(**pipe_kwargs)

    # Pour GPUs < 24GB: Gemma 3 12B bf16 = ~24GB, dépasse la VRAM
    # 1. Force CPU loading (_target_device → "cpu") pour éviter safetensors OOM
    # 2. Quantifie Gemma 3 en INT8 quanto (~12GB) avant .to("cuda")
    # Le pipeline fait du séquentiel: text_encoder → del → transformer
    if VRAM_GB < 24:
        pipe.model_ledger._target_device = lambda: torch.device("cpu")

        def _quantized_text_encoder():
            from optimum.quanto import quantize, qint8, freeze
            # Build sur CPU (via _target_device patch)
            encoder = pipe.model_ledger.text_encoder_builder.build(
                device=torch.device("cpu"),
                dtype=pipe.model_ledger.dtype,
            ).eval()
            # Quantifier Gemma 3 12B: 24GB bf16 → ~12GB INT8
            print("[MM]   -> Quantification Gemma 3 12B → INT8...")
            quantize(encoder.model, weights=qint8)
            freeze(encoder.model)
            encoder = encoder.to(pipe.model_ledger.device)
            return encoder

        pipe.model_ledger.text_encoder = _quantized_text_encoder
        print(f"[MM]   -> CPU offload + Gemma INT8 activé (VRAM {VRAM_GB:.0f}GB < 24GB)")

    gc.collect()
    print(f"[MM]   -> Prêt! {display_name}")

    return {
        "pipe": pipe,
        "extras": {"ltx2_native": True, "openimageio": openimageio_available}
    }


def load_wan_native(model_name, custom_cache):
    """Load Wan native backend (without diffusers) -- official Wan-Video/Wan2.2 code.

    Args:
        model_name: "wan-native-5b" or "wan-native-14b"

    Returns:
        dict with 'pipe' and 'extras' keys.
        extras contains 'native': True.
    """
    # 1. Installer le package wan si absent
    try:
        import wan
    except ImportError:
        _install_wan_native_backend()
        import wan
    attention_fallback = _patch_wan_native_attention_fallback()

    from huggingface_hub import snapshot_download
    from core.models import VIDEO_MODELS
    from core.generation.video_optimizations import configure_video_torch_runtime

    configure_video_torch_runtime()

    model_info = VIDEO_MODELS[model_name]
    model_id = model_info["id"]
    display_name = model_info["name"]

    print(f"[MM] Loading {display_name} (backend natif)...")

    # 2. Telecharger les checkpoints depuis HuggingFace
    print(f"[MM]   -> Telechargement checkpoints {model_id}...")
    ckpt_dir = snapshot_download(
        repo_id=model_id,
        cache_dir=custom_cache,
        local_dir=os.path.join(custom_cache, model_id.replace("/", "--")),
    )
    print(f"[MM]   -> Checkpoints: {ckpt_dir}")

    # 3. Charger la config appropriee
    if model_name == "wan-native-5b":
        # TI2V 5B config: the official backend uses WanTI2V for this checkpoint.
        # WanI2V expects MoE I2V fields such as "boundary" which do not exist on ti2v-5B.
        from wan.configs import WAN_CONFIGS
        cfg = WAN_CONFIGS["ti2v-5B"]
        task_class = wan.WanTI2V
    else:
        # I2V A14B config (MoE)
        from wan.configs import WAN_CONFIGS
        cfg = WAN_CONFIGS["i2v-A14B"]
        task_class = wan.WanI2V

    # 4. Initialiser le modele natif
    print(f"[MM]   -> Initialisation {display_name}...")
    # offload_model=True pour economiser VRAM, t5_cpu=True pour T5 sur CPU
    pipe = task_class(
        config=cfg,
        checkpoint_dir=ckpt_dir,
        device_id=0,
        rank=0,
        t5_cpu=(VRAM_GB < 24),  # T5 sur CPU si moins de 24GB
        init_on_cpu=True,
        convert_model_dtype=False,
    )
    gc.collect()

    print(f"[MM]   -> Pret! {display_name} (natif) | VRAM: {VRAM_GB:.0f}GB")

    return {
        "pipe": pipe,
        "extras": {"native": True, "attention_fallback": attention_fallback}
    }
