"""
Gestion des modeles IA (inpainting + video)

Model loading functions and pipeline utilities.
Constants, model dictionaries, and download functions are in model_registry.py.
VRAM management functions are in vram_manager.py.
"""
import os
import platform
import warnings
import subprocess
import sys

# === DESINSTALLER XFORMERS SI PRESENT ===
# xformers est incompatible avec triton-windows (necessaire pour SageAttention)
# SageAttention est plus rapide que xformers donc on le remplace
try:
    import importlib.util
    if importlib.util.find_spec("xformers") is not None:
        print("[STARTUP] xformers detecte - desinstallation (incompatible avec SageAttention)...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "xformers", "-y", "-q"],
                      capture_output=True, timeout=60)
        print("[STARTUP] xformers desinstalle - SageAttention sera utilise a la place (plus rapide)")
except Exception:
    pass  # Ignorer les erreurs, pas critique

import torch
import gc
import torch._dynamo

# Import everything from model_registry (constants, model dicts, download functions)
from core.models.registry import (
    # Constants
    PROJECT_DIR, custom_cache, AI_NAME,
    IS_MAC, IS_WINDOWS,
    USE_TORCH_COMPILE, COMPILE_MODE,
    VRAM_GB, USE_CPU_OFFLOAD, IS_HIGH_END_GPU,
    WARMUP_SIZES, snap_to_warmup_size,
    SUPPORTS_BF16, TORCH_DTYPE, DTYPE_NAME,
    USE_QUANTIZATION,
    GPU_MODEL_CONFIG, GPU_TIER,
    get_generation_time_estimates,
    # Model dictionaries
    MODELS, SINGLE_FILE_MODELS, MODEL_QUANT, FLUX_MODELS, FLUX_FILL_NF4_REPO, FLUX_DEV_NF4_REPO, FLUX_KONTEXT_MODELS,
    TEXT2IMG_MODELS, VIDEO_MODELS, ALL_MODELS, AUXILIARY_MODELS,
    _refresh_imported_model_registries,
    # Download functions
    download_status,
    check_model_downloaded, delete_model_from_cache,
    get_all_models_status, get_model_total_size, get_cache_folder_size,
    download_model_background, download_model_async,
    get_model_download_status, get_download_progress,
    # GPU config
    _get_gpu_tier,
    HF_TOKEN,
)
from core.infra.packs import get_pack_model_sources


def get_flux_kontext_uncensored_lora_spec() -> tuple[str, str]:
    """Resolve Flux Kontext advanced LoRA metadata from the active local pack."""
    model_sources = get_pack_model_sources("adult")
    flux_kontext = model_sources.get("flux_kontext", {}) if isinstance(model_sources, dict) else {}
    repo_id = str(flux_kontext.get("uncensored_lora_repo", "") or "").strip()
    filename = str(flux_kontext.get("uncensored_lora_file", "") or "").strip()
    return repo_id, filename


FLUX_KONTEXT_UNCENSORED_LORA, FLUX_KONTEXT_UNCENSORED_LORA_FILE = get_flux_kontext_uncensored_lora_spec()

# Import VRAM management from vram_manager
from core.models.vram import (
    clear_vram,
    prepare_for_image_generation,
    after_image_generation,
    get_vram_status,
    log_vram_status,
    unload_all_image_models,
    unload_caption_model,
    unload_zoe_detector,
    unload_outpaint_pipeline,
    unload_video_model,
    prepare_for_video_generation,
    video_generation_done,
    is_video_generating,
    get_current_loaded_models,
    smart_unload_for_vram,
    video_generating,
)


# ========================== OPTIMIZATION CHECKS ==========================

def check_optimization_dependencies():
    """Verifie les dependances d'optimisation disponibles (silencieux)"""
    status = {
        "xformers": False,
        "tensorrt": False,
        "torch_compile": False,
        "cuda": False,
        "mps": False,
        "sdpa": False,
    }

    if torch.cuda.is_available():
        status["cuda"] = True
    elif IS_MAC and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        status["mps"] = True

    if status["cuda"]:
        try:
            import xformers
            import xformers.ops
            status["xformers"] = True
        except Exception:
            pass

        try:
            import tensorrt
            status["tensorrt"] = True
        except Exception:
            pass

    if hasattr(torch, 'compile'):
        status["torch_compile"] = True

    try:
        from diffusers.models.attention_processor import AttnProcessor2_0
        status["sdpa"] = True
    except Exception:
        pass

    return status

_opt_status = check_optimization_dependencies()
XFORMERS_AVAILABLE = _opt_status["xformers"]


# ========================== GLOBAL STATE (LEGACY) ==========================

inpaint_pipe = None
video_pipe = None
upscale_model = None
caption_model = None
caption_processor = None
outpaint_pipe = None
zoe_detector = None
current_model = None
text2img_pipe = None
current_text2img_model = None
current_video_model = None


# ========================== PIPELINE UTILITIES ==========================

def get_model_loading_kwargs():
    """
    Retourne les kwargs optimaux pour charger un modele diffusers.
    local_files_only=True: skip le HEAD request réseau de HuggingFace.
    Les modèles sont pré-téléchargés par preload.py au startup.
    Si le modèle n'est pas en cache, from_pretrained lève OSError
    → l'appelant doit retry sans local_files_only.
    """
    if IS_MAC:
        return {
            "torch_dtype": torch.float16,
            "use_safetensors": True,
            "low_cpu_mem_usage": False,
            "cache_dir": custom_cache,
            "local_files_only": True,
        }
    else:
        return {
            "torch_dtype": TORCH_DTYPE,
            "variant": "fp16",
            "use_safetensors": True,
            "low_cpu_mem_usage": True,
            "cache_dir": custom_cache,
            "local_files_only": True,
        }

def move_to_device(pipe, name="pipeline", quantized=False):
    """
    Deplace le pipeline sur le bon device selon le profil GPU.
    """
    from core.models.gpu_profile import get_offload_strategy

    if IS_MAC:
        pipe.to("mps")
        return

    if not torch.cuda.is_available():
        pipe.to("cpu")
        return

    offload = get_offload_strategy('sdxl')
    vram = round(VRAM_GB)
    q_str = " (quantifie)" if quantized else ""

    if offload == "none" or quantized:
        # GPU direct: profil dit "none" (assez de VRAM) ou modèle quantifié (petit)
        try:
            pipe.to("cuda")
            print(f"[MM] {name}: GPU direct{q_str} ({vram}GB)")
        except (NotImplementedError, RuntimeError):
            pipe.enable_model_cpu_offload()
            print(f"[MM] {name}: fallback CPU offload ({vram}GB)")
    elif offload == "model_cpu_offload":
        pipe.enable_model_cpu_offload()
        print(f"[MM] {name}: model CPU offload ({vram}GB)")
    else:
        pipe.enable_model_cpu_offload()
        print(f"[MM] {name}: CPU offload ({vram}GB)")


def move_video_to_device(pipe, name="video", vram_needed_gb=8, force_model_cpu_offload=False):
    """
    Deplace un pipeline video sur le bon device selon la VRAM disponible.
    """
    if IS_MAC:
        pipe.to("mps")
    elif torch.cuda.is_available():
        vram = VRAM_GB
        if vram >= vram_needed_gb + 1.5:
            pipe.to("cuda")
            print(f"[VIDEO] {name}: GPU direct ({vram:.1f}GB VRAM)")
        elif force_model_cpu_offload:
            try:
                pipe.enable_model_cpu_offload()
                print(f"[VIDEO] {name}: model CPU offload (INT8 compatible) ({vram:.1f}GB VRAM)")
            except Exception:
                pipe.enable_sequential_cpu_offload()
                print(f"[VIDEO] {name}: sequential CPU offload fallback ({vram:.1f}GB VRAM)")
        else:
            try:
                from diffusers.hooks import apply_group_offloading
                onload = torch.device("cuda")
                offload = torch.device("cpu")

                main_model = getattr(pipe, 'transformer', None) or getattr(pipe, 'unet', None)
                if main_model is not None:
                    try:
                        main_model.enable_group_offload(
                            onload_device=onload, offload_device=offload,
                            offload_type="leaf_level", use_stream=True,
                            record_stream=True, low_cpu_mem_usage=True
                        )
                    except TypeError:
                        main_model.enable_group_offload(
                            onload_device=onload, offload_device=offload,
                            offload_type="leaf_level", use_stream=True, record_stream=True
                        )

                if hasattr(pipe, 'vae') and pipe.vae is not None:
                    try:
                        pipe.vae.enable_group_offload(
                            onload_device=onload, offload_device=offload,
                            offload_type="leaf_level", use_stream=True,
                            low_cpu_mem_usage=True
                        )
                    except TypeError:
                        pipe.vae.enable_group_offload(
                            onload_device=onload, offload_device=offload,
                            offload_type="leaf_level", use_stream=True
                        )

                for enc_name in ('text_encoder', 'text_encoder_2'):
                    enc = getattr(pipe, enc_name, None)
                    if enc is not None:
                        apply_group_offloading(
                            enc, onload_device=onload,
                            offload_type="block_level", num_blocks_per_group=4
                        )

                if hasattr(pipe, 'image_encoder') and pipe.image_encoder is not None:
                    apply_group_offloading(
                        pipe.image_encoder, onload_device=onload,
                        offload_type="block_level", num_blocks_per_group=4
                    )

                print(f"[VIDEO] {name}: group offload + CUDA streams ({vram:.1f}GB VRAM)")
            except Exception as e:
                print(f"[VIDEO] Group offload failed: {e}, trying model_cpu_offload...")
                try:
                    pipe.enable_model_cpu_offload()
                    print(f"[VIDEO] {name}: model CPU offload fallback ({vram:.1f}GB VRAM)")
                except Exception:
                    pipe.enable_sequential_cpu_offload()
                    print(f"[VIDEO] {name}: sequential CPU offload fallback ({vram:.1f}GB VRAM)")
    else:
        pipe.to("cpu")


def optimize_pipeline(pipe, name="pipeline"):
    """
    Applique TOUTES les optimisations pour vitesse MAXIMALE.
    """
    if torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    xformers_ok = False
    if XFORMERS_AVAILABLE:
        try:
            pipe.enable_xformers_memory_efficient_attention()
            xformers_ok = True
        except Exception:
            pass

    if not xformers_ok:
        try:
            from diffusers.models.attention_processor import AttnProcessor2_0
            pipe.unet.set_attn_processor(AttnProcessor2_0())
        except Exception:
            pass

    try:
        pipe.unet = pipe.unet.to(memory_format=torch.channels_last)
        if hasattr(pipe, 'vae'):
            pipe.vae = pipe.vae.to(memory_format=torch.channels_last)
    except Exception:
        pass

    if USE_TORCH_COMPILE and not IS_HIGH_END_GPU and hasattr(torch, 'compile'):
        try:
            pipe.unet = torch.compile(
                pipe.unet,
                mode=COMPILE_MODE,
                backend="inductor",
                fullgraph=False,
            )
        except Exception:
            pass

    return pipe


def optimize_flux_pipeline(pipe, name="Flux"):
    """
    Optimisations pour Flux (transformer-based, pas UNet).
    """
    if torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    if USE_TORCH_COMPILE and not IS_HIGH_END_GPU and hasattr(torch, 'compile') and hasattr(pipe, 'transformer'):
        try:
            pipe.transformer = torch.compile(
                pipe.transformer,
                mode=COMPILE_MODE,
                backend="inductor",
                fullgraph=False,
            )
            print(f"[OPT] {name}: torch.compile active")
        except Exception as e:
            print(f"[OPT] {name}: torch.compile skip ({e})")
    elif IS_HIGH_END_GPU:
        print(f"[OPT] {name}: skip torch.compile (high-end GPU)")

    return pipe


# ========================== MODEL LOADING FUNCTIONS ==========================

def load_inpaint_model(model_name: str = "epiCRealism XL (Moyen)"):
    """Charge le modele d'inpainting"""
    global inpaint_pipe, current_model

    INPAINT_MAPPING = {
        "epiCRealism XL": "epiCRealism XL (Moyen)",
        "epiCRealism XL Inpaint": "epiCRealism XL (Moyen)",
        "Juggernaut XL v9": "Juggernaut XL Inpaint",
        "Fluently XL v3": "Fluently XL v3 Inpaint",
        "SDXL Turbo": "epiCRealism XL (Moyen)",
    }

    if model_name in INPAINT_MAPPING:
        mapped_name = INPAINT_MAPPING[model_name]
        print(f"[INPAINT] Mapping: {model_name} -> {mapped_name}")
        model_name = mapped_name

    if "Automatique" in model_name or (model_name not in MODELS and model_name not in SINGLE_FILE_MODELS):
        model_name = "epiCRealism XL (Moyen)"

    if model_name in SINGLE_FILE_MODELS:
        model_id = model_name
    else:
        model_id = MODELS[model_name]

    if inpaint_pipe is not None and current_model == model_id:
        return inpaint_pipe

    if inpaint_pipe is not None:
        print("[VRAM] Unloading previous inpaint model...")
        del inpaint_pipe
        inpaint_pipe = None
        clear_vram()

    print(f"Loading: {model_name}...")

    from diffusers import StableDiffusionInpaintPipeline, StableDiffusionXLInpaintPipeline, DPMSolverMultistepScheduler

    sdxl_keywords = ["SDXL", "Fluently", "Juggernaut", "epiCRealism", "LUSTIFY"]
    model_quant = "int8"
    if any(kw in model_name for kw in sdxl_keywords):
        if model_name in SINGLE_FILE_MODELS:
            from huggingface_hub import hf_hub_download

            sfm = SINGLE_FILE_MODELS[model_name]
            repo_id, filename = sfm[0], sfm[1]
            model_quant = sfm[2] if len(sfm) > 2 else "int8"

            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

            model_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                resume_download=True,
            )

            inpaint_pipe = StableDiffusionXLInpaintPipeline.from_single_file(
                model_path,
                torch_dtype=TORCH_DTYPE,
            )
        else:
            load_kwargs = get_model_loading_kwargs()

            try:
                inpaint_pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
                    model_id,
                    **load_kwargs,
                )
            except ValueError as e:
                if "variant=fp16" in str(e) or "variant" in str(e):
                    print(f"[{model_name}] Pas de variant fp16, chargement standard...")
                    load_kwargs.pop("variant", None)
                    inpaint_pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
                        model_id,
                        **load_kwargs,
                    )
                else:
                    raise
        inpaint_pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            inpaint_pipe.scheduler.config,
            algorithm_type="dpmsolver++",
            solver_order=2,
            use_karras_sigmas=True,
        )

        inpaint_pipe.enable_vae_slicing()
        inpaint_pipe.enable_vae_tiling()

        inpaint_pipe = optimize_pipeline(inpaint_pipe, f"inpaint ({model_name})")

        if model_quant != "none" and not IS_MAC:
            try:
                from optimum.quanto import quantize, freeze, qint8, qint4
                quant_weight = qint4 if model_quant == "int4" else qint8
                quant_name = "int4" if model_quant == "int4" else "int8"
                print(f"[{model_name}] Quantification UNet ({quant_name})...")
                quantize(inpaint_pipe.unet, weights=quant_weight)
                freeze(inpaint_pipe.unet)
                print(f"[{model_name}] UNet quantifie ({quant_name})")
            except Exception as e:
                print(f"[{model_name}] Quantification skip: {e}")

        move_to_device(inpaint_pipe, f"inpaint ({model_name})")

    else:
        inpaint_pipe = StableDiffusionInpaintPipeline.from_pretrained(
            model_id,
            torch_dtype=TORCH_DTYPE,
            safety_checker=None,
            requires_safety_checker=False,
            cache_dir=custom_cache,
        )
        inpaint_pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            inpaint_pipe.scheduler.config,
            algorithm_type="dpmsolver++",
            solver_order=2,
        )
        inpaint_pipe.enable_vae_slicing()
        inpaint_pipe.enable_vae_tiling()
        inpaint_pipe = optimize_pipeline(inpaint_pipe, f"inpaint SD ({model_name})")
        move_to_device(inpaint_pipe, f"inpaint SD ({model_name})")

    current_model = model_id
    print(f"Ready: {model_name} (optimized)")
    return inpaint_pipe


def load_text2img_model(model_name: str = "SDXL (qualite)"):
    """Charge le modele text-to-image"""
    global text2img_pipe, current_text2img_model, inpaint_pipe

    if inpaint_pipe is not None:
        print("[VRAM] Unloading inpaint model...")
        del inpaint_pipe
        inpaint_pipe = None
        clear_vram()

    if "Automatique" in model_name or model_name not in TEXT2IMG_MODELS:
        model_name = "epiCRealism XL"

    model_id = TEXT2IMG_MODELS[model_name]

    if text2img_pipe is not None and current_text2img_model == model_id:
        return text2img_pipe

    if text2img_pipe is not None:
        try:
            del text2img_pipe
        except Exception:
            pass
        text2img_pipe = None
        clear_vram()

    print(f"Loading text2img: {model_name}...")

    from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline, DPMSolverMultistepScheduler

    load_kwargs = get_model_loading_kwargs()

    if "Turbo" in model_name:
        text2img_pipe = StableDiffusionXLPipeline.from_pretrained(
            model_id,
            **load_kwargs,
        )
        text2img_pipe = optimize_pipeline(text2img_pipe, "SDXL Turbo")
        move_to_device(text2img_pipe, "SDXL Turbo")
    elif "SDXL" in model_name or "epiCRealism" in model_name or "Juggernaut" in model_name:
        text2img_pipe = StableDiffusionXLPipeline.from_pretrained(
            model_id,
            **load_kwargs,
        )
        text2img_pipe.scheduler = DPMSolverMultistepScheduler.from_config(text2img_pipe.scheduler.config)
        text2img_pipe.enable_vae_slicing()
        text2img_pipe.enable_vae_tiling()
        text2img_pipe = optimize_pipeline(text2img_pipe, "SDXL")
        move_to_device(text2img_pipe, "SDXL")
    else:
        text2img_pipe = StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=TORCH_DTYPE,
            safety_checker=None,
            requires_safety_checker=False,
            cache_dir=custom_cache,
        )
        text2img_pipe.scheduler = DPMSolverMultistepScheduler.from_config(text2img_pipe.scheduler.config)
        text2img_pipe = optimize_pipeline(text2img_pipe, "SD")
        move_to_device(text2img_pipe, "SD")

    current_text2img_model = model_id
    print(f"Ready: {model_name} (optimized)")
    return text2img_pipe


def _fix_transformers_for_svd():
    """Installe une version compatible de transformers pour SVD (CLIPImageProcessor)"""

    print("\n" + "="*60)
    print("[SVD] Installation de transformers 4.44.0 (compatible SVD)...")
    print("="*60)

    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "transformers==4.44.0", "--progress-bar", "on"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in process.stdout:
            line = line.strip()
            if line:
                print(f"   {line}")

        process.wait()

        if process.returncode == 0:
            print("[SVD] transformers 4.44.0 installe!")
            print("   Redemarrez l'application pour appliquer les changements.")
            return True
        else:
            print("[SVD] Erreur lors de l'installation")
            return False

    except Exception as e:
        print(f"[SVD] Erreur: {e}")
        return False


def load_video_model(model_name: str = "svd"):
    """Charge un modele video (SVD, CogVideoX, etc.)"""
    global video_pipe, current_video_model

    if video_pipe is not None and current_video_model == model_name:
        return video_pipe

    if video_pipe is not None:
        print(f"[VIDEO] Dechargement {current_video_model} pour charger {model_name}...")
        del video_pipe
        video_pipe = None
        clear_vram()

    if model_name == "svd":
        video_pipe = _load_svd()
    elif model_name == "cogvideox":
        video_pipe = _load_cogvideox_5b()
    elif model_name == "cogvideox-2b":
        video_pipe = _load_cogvideox_2b()
    else:
        raise ValueError(f"Modele video inconnu: {model_name}")

    current_video_model = model_name
    return video_pipe


def _load_svd():
    """Charge Stable Video Diffusion 1.1"""
    from diffusers import StableVideoDiffusionPipeline

    print("Loading SVD 1.1 (image-to-video, optimise 8GB)...")

    pipe = StableVideoDiffusionPipeline.from_pretrained(
        "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        torch_dtype=TORCH_DTYPE,
        variant="fp16",
        cache_dir=custom_cache,
    )

    if XFORMERS_AVAILABLE:
        try:
            pipe.enable_xformers_memory_efficient_attention()
            print("[VIDEO] xformers active")
        except Exception:
            pass

    move_video_to_device(pipe, "SVD 1.1", vram_needed_gb=8)
    pipe.unet.enable_forward_chunking()
    print("[VIDEO] SVD 1.1 pret!")
    return pipe


def _load_cogvideox_5b():
    """Charge CogVideoX-5B I2V"""
    from diffusers import CogVideoXImageToVideoPipeline

    print("Loading CogVideoX-5B I2V (telechargement ~10GB si premier lancement)...")

    pipe = CogVideoXImageToVideoPipeline.from_pretrained(
        "THUDM/CogVideoX-5b-I2V",
        torch_dtype=torch.bfloat16,
        cache_dir=custom_cache,
    )

    move_video_to_device(pipe, "CogVideoX-5B", vram_needed_gb=10)
    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()

    print("[VIDEO] CogVideoX-5B pret!")
    return pipe


def _load_cogvideox_2b():
    """Charge CogVideoX-2B (text-to-video uniquement, pas d'I2V disponible)"""
    from diffusers import CogVideoXPipeline

    print("Loading CogVideoX-2B text-to-video (telechargement ~5GB si premier lancement)...")

    pipe = CogVideoXPipeline.from_pretrained(
        "THUDM/CogVideoX-2b",
        torch_dtype=TORCH_DTYPE,
        cache_dir=custom_cache,
    )

    move_video_to_device(pipe, "CogVideoX-2B", vram_needed_gb=6)
    pipe.vae.enable_tiling()
    pipe.vae.enable_slicing()

    print("[VIDEO] CogVideoX-2B pret!")
    return pipe


def _patch_torchvision_compatibility():
    """Patch pour la compatibilite basicsr avec torchvision >= 0.18"""
    from utils.compat import _patch_torchvision_compatibility as _patch
    _patch()


def _install_upscale_dependencies():
    """Installe automatiquement basicsr et realesrgan si manquants"""
    packages = ["basicsr>=1.4.2", "realesrgan>=0.3.0"]

    for package in packages:
        try:
            pkg_name = package.split(">=")[0]
            __import__(pkg_name)
        except ImportError:
            print(f"[UPSCALE] Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])
            print(f"[UPSCALE] {pkg_name} installed!")


def load_upscale_model():
    """Charge Real-ESRGAN pour ameliorer la qualite des images"""
    global upscale_model

    if upscale_model is not None:
        return upscale_model

    print("Loading Real-ESRGAN...")

    _patch_torchvision_compatibility()

    try:
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
    except ImportError:
        print("[UPSCALE] Dependencies missing, installing...")
        _install_upscale_dependencies()
        _patch_torchvision_compatibility()
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer

    try:
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)

        upscale_model = RealESRGANer(
            scale=4,
            model_path='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth',
            model=model,
            tile=400,
            tile_pad=10,
            pre_pad=0,
            half=True,
            gpu_id=0
        )

        print("Real-ESRGAN ready!")
        return upscale_model

    except Exception as e:
        print(f"Real-ESRGAN error: {e}")
        import traceback
        traceback.print_exc()
        return None


# Aliases for backward compat
load_blip_model = None  # Will be set below


def load_caption_model(use_4bit=True):
    """Charge BLIP pour decrire les images - 4-bit par defaut"""
    global caption_model, caption_processor

    if caption_model is not None:
        return caption_model, caption_processor

    print("Loading BLIP caption model...")

    from transformers import BlipProcessor, BlipForConditionalGeneration

    caption_processor = BlipProcessor.from_pretrained(
        "Salesforce/blip-image-captioning-base",
        cache_dir=custom_cache,
    )

    if torch.cuda.is_available() and use_4bit:
        try:
            from transformers import BitsAndBytesConfig

            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=TORCH_DTYPE,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )

            caption_model = BlipForConditionalGeneration.from_pretrained(
                "Salesforce/blip-image-captioning-base",
                quantization_config=quantization_config,
                device_map="auto",
                cache_dir=custom_cache,
            )
            print("BLIP ready! (GPU 4-bit)")
            return caption_model, caption_processor

        except Exception as e:
            print(f"[WARNING] BLIP 4-bit failed: {e}, using fp16")

    caption_model = BlipForConditionalGeneration.from_pretrained(
        "Salesforce/blip-image-captioning-base",
        torch_dtype=TORCH_DTYPE,
        cache_dir=custom_cache,
    )

    if torch.cuda.is_available():
        caption_model = caption_model.to("cuda")

    print(f"BLIP ready! (GPU {DTYPE_NAME})")
    return caption_model, caption_processor

# Alias
load_blip_model = load_caption_model


def describe_image(image):
    """Genere une description de l'image avec BLIP"""
    try:
        model, processor = load_caption_model()

        inputs = processor(image, return_tensors="pt")
        if torch.cuda.is_available():
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        out = model.generate(
            **inputs,
            max_length=30,
            min_length=5,
            num_beams=3,
            repetition_penalty=2.0,
            no_repeat_ngram_size=2,
        )
        description = processor.decode(out[0], skip_special_tokens=True)

        print(f"[BLIP] Description: {description}")
        return description

    except Exception as e:
        print(f"[BLIP] Erreur: {e}")
        return "a photo"

# Alias
caption_image = describe_image


def load_zoe_detector():
    """Charge le detecteur de profondeur ZoeDepth"""
    global zoe_detector

    if zoe_detector is not None:
        return zoe_detector

    print("Loading ZoeDepth detector...")

    old_low_cpu = os.environ.get("LOW_CPU_MEM_USAGE", None)
    os.environ["LOW_CPU_MEM_USAGE"] = "0"

    from controlnet_aux import ZoeDetector

    if torch.cuda.is_available():
        device = "cuda"
    elif IS_MAC:
        device = "mps"
    else:
        device = "cpu"

    try:
        zoe_detector = ZoeDetector.from_pretrained(
            "lllyasviel/Annotators",
            cache_dir=custom_cache,
        )
        zoe_detector = zoe_detector.to(device)
    finally:
        if old_low_cpu is not None:
            os.environ["LOW_CPU_MEM_USAGE"] = old_low_cpu
        elif "LOW_CPU_MEM_USAGE" in os.environ:
            del os.environ["LOW_CPU_MEM_USAGE"]

    print(f"ZoeDepth ready! (on {device})")
    return zoe_detector

# Alias
load_zoe_depth = load_zoe_detector


def load_outpaint_pipeline():
    """Charge le pipeline d'outpainting avec ControlNets"""
    global outpaint_pipe, inpaint_pipe

    if outpaint_pipe is not None:
        return outpaint_pipe

    if inpaint_pipe is not None:
        del inpaint_pipe
        inpaint_pipe = None
        clear_vram()

    print("Loading Outpainting pipeline (Inpaint ControlNet)...")

    from diffusers import ControlNetModel, StableDiffusionXLControlNetPipeline, AutoencoderKL

    load_kwargs = get_model_loading_kwargs()
    cn_kwargs = {"torch_dtype": TORCH_DTYPE, "cache_dir": custom_cache}
    if not IS_MAC:
        cn_kwargs["variant"] = "fp16"

    print("[OUTPAINT] Loading ControlNet Inpaint Dreamer...")
    try:
        controlnet_inpaint = ControlNetModel.from_pretrained(
            "destitech/controlnet-inpaint-dreamer-sdxl",
            **cn_kwargs
        )
    except Exception:
        controlnet_inpaint = ControlNetModel.from_pretrained(
            "destitech/controlnet-inpaint-dreamer-sdxl",
            torch_dtype=TORCH_DTYPE,
            cache_dir=custom_cache,
        )

    print("[OUTPAINT] Loading VAE...")
    vae = AutoencoderKL.from_pretrained(
        "madebyollin/sdxl-vae-fp16-fix",
        torch_dtype=TORCH_DTYPE,
        cache_dir=custom_cache,
    )

    print("[OUTPAINT] Loading epiCRealism XL pipeline...")
    outpaint_pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
        "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
        **load_kwargs,
        controlnet=controlnet_inpaint,
        vae=vae
    )

    outpaint_pipe.enable_vae_slicing()
    move_to_device(outpaint_pipe, "Outpaint")

    print("Outpainting pipeline ready!")
    return outpaint_pipe


def upscale_image(image):
    """Upscale une image avec Real-ESRGAN (alias pour backward compat)"""
    model = load_upscale_model()
    if model is None:
        return image

    import numpy as np
    img_np = np.array(image)
    output, _ = model.enhance(img_np, outscale=4)
    from PIL import Image
    return Image.fromarray(output)


# ========================== BACKWARD COMPATIBILITY RE-EXPORTS ==========================
# These ensure that any file importing from core.models still works

# From model_registry (already imported above, re-exported via module namespace)
# ALL_MODELS, SINGLE_FILE_MODELS, VIDEO_MODELS, AUXILIARY_MODELS
# VRAM_GB, IS_HIGH_END_GPU, TORCH_DTYPE, DEFAULT_DEVICE (DEFAULT_DEVICE not used, skip)
# check_model_downloaded, get_model_download_status, get_all_models_status

# From vram_manager (already imported above, re-exported via module namespace)
# clear_vram, prepare_for_image_generation, after_image_generation
# get_vram_status, log_vram_status, unload_all_image_models, etc.

# Additional backward compat aliases
DEFAULT_DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if IS_MAC else "cpu")
