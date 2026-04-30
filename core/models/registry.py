"""
Model Registry - Centralized model definitions, constants, and download management.

Contains:
- GPU detection and constants (VRAM_GB, IS_HIGH_END_GPU, TORCH_DTYPE, etc.)
- Model dictionaries (ALL_MODELS, SINGLE_FILE_MODELS, VIDEO_MODELS, etc.)
- Model download functions (check_model_downloaded, download_model_async, etc.)
- GPU config tables (GPU_MODEL_CONFIG, GPU_TIER)
- Warmup sizes and generation time estimates
"""

import os
import sys
import platform
import warnings
import subprocess
import torch
import gc
import torch._dynamo
from core.infra.paths import get_huggingface_cache_dir, get_models_dir
from core.models.runtime_env import configure_huggingface_env, get_huggingface_hub_cache_dir

# Supprimer les FutureWarning de diffusers et autres
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*clean_up_tokenization_spaces.*")

# Stocker les modeles dans le dossier du projet
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config for AI name
try:
    sys.path.insert(0, PROJECT_DIR)
    from config import AI_NAME
except ImportError:
    AI_NAME = "JoyBoy"
MODELS_DIR = str(get_models_dir())
custom_cache = str(get_huggingface_cache_dir())
os.makedirs(custom_cache, exist_ok=True)
from config import HF_TOKEN

# Detection OS
_SYSTEM_NAME = platform.system()
IS_MAC = _SYSTEM_NAME == "Darwin"
IS_WINDOWS = _SYSTEM_NAME == "Windows"
configure_huggingface_env(custom_cache, HF_TOKEN, system_name=_SYSTEM_NAME)

# torch.compile: desactive sur Windows (pas de Triton) et Mac (MPS incompatible)
USE_TORCH_COMPILE = not IS_WINDOWS and not IS_MAC
COMPILE_MODE = "reduce-overhead"
torch._dynamo.config.suppress_errors = True

# Detection VRAM
VRAM_GB = 0
if torch.cuda.is_available():
    VRAM_GB = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"[STARTUP] GPU detected: {torch.cuda.get_device_name(0)} ({VRAM_GB:.1f}GB VRAM)")

# Seuils VRAM: -2GB vs nominal pour compenser la VRAM réelle
# (ex: GPU 20GB reporte ~18.1GB, GPU 40GB reporte ~38GB)
USE_CPU_OFFLOAD = VRAM_GB <= 8

# HIGH-END MODE: 36GB+ VRAM (nominalement 40GB+)
IS_HIGH_END_GPU = VRAM_GB >= 36

# WARMUP SIZES
WARMUP_SIZES = [
    (384, 512),
    (512, 384),
    (512, 512),
    (512, 768),
    (768, 512),
    (768, 768),
    (896, 640),
    (640, 896),
    (1024, 512),  # portrait extrême (~1:2)
    (512, 1024),  # paysage extrême (~2:1)
]

def _round_to_64(width, height):
    """Arrondit aux multiples de 64 en gardant le ratio, cible ~640px côté court."""
    if width <= height:
        new_w = max(384, min(width, 640))
        new_w = (new_w // 64) * 64
        new_h = int(new_w * height / width)
        new_h = (new_h // 64) * 64
    else:
        new_h = max(384, min(height, 640))
        new_h = (new_h // 64) * 64
        new_w = int(new_h * width / height)
        new_w = (new_w // 64) * 64
    return new_w, new_h


def snap_to_warmup_size(width, height):
    """
    GPU haute gamme (torch.compile) → snap aux tailles warmup pré-compilées.
    GPU ≤8GB (pas de torch.compile) → arrondi multiples de 64, ratio préservé.
    """
    # Pas de torch.compile sur les petits GPU → juste arrondir, garder le ratio
    if not IS_HIGH_END_GPU:
        return _round_to_64(width, height)

    # GPU haute gamme : snap aux tailles warmup pour torch.compile
    aspect = width / height
    pixels = width * height
    best_size = None
    best_score = float('inf')

    for h, w in WARMUP_SIZES:
        warmup_aspect = w / h
        warmup_pixels = w * h
        aspect_diff = abs(aspect - warmup_aspect)
        size_ratio = warmup_pixels / pixels if pixels > 0 else 1
        size_penalty = abs(size_ratio - 1) * 0.3
        score = aspect_diff + size_penalty
        if score < best_score:
            best_score = score
            best_size = (w, h)

    return best_size  # (width, height)

# BF16 DETECTION
SUPPORTS_BF16 = False
if torch.cuda.is_available():
    try:
        major, minor = torch.cuda.get_device_capability(0)
        SUPPORTS_BF16 = major >= 8
    except Exception:
        pass

if not torch.cuda.is_available() and not IS_MAC:
    TORCH_DTYPE = torch.float32
    DTYPE_NAME = "fp32"
elif SUPPORTS_BF16 and VRAM_GB >= 16:
    TORCH_DTYPE = torch.bfloat16
    DTYPE_NAME = "bf16"
else:
    TORCH_DTYPE = torch.float16
    DTYPE_NAME = "fp16"

# Quantization strategy — seuil 16GB (nominalement 18GB GPUs)
USE_QUANTIZATION = not IS_HIGH_END_GPU and VRAM_GB < 16 and VRAM_GB > 0

if IS_HIGH_END_GPU:
    print(f"[STARTUP] High-end GPU detected: {VRAM_GB:.0f}GB VRAM")
    print(f"[STARTUP]   -> Skip quantization (native {DTYPE_NAME})")
    print(f"[STARTUP]   -> GPU direct (no offload)")
    print(f"[STARTUP]   -> VAE float32 (max quality)")
elif SUPPORTS_BF16 and VRAM_GB >= 16:
    print(f"[STARTUP] Ampere+ GPU ({VRAM_GB:.0f}GB): native {DTYPE_NAME} (no quantization needed)")
elif SUPPORTS_BF16:
    print(f"[STARTUP] Ampere+ GPU ({VRAM_GB:.0f}GB): using fp16 (compatible with INT8 quanto)")
elif VRAM_GB > 0:
    print(f"[STARTUP] GPU ({VRAM_GB:.0f}GB): using fp16")
elif not IS_MAC:
    print("[STARTUP] Profil CPU/non-CUDA: JoyBoy démarre, image/vidéo locale limitée")
    print("[STARTUP] -> Si tu as une NVIDIA RTX/GTX compatible, lance Setup complet pour réparer PyTorch CUDA")

# ========================== GPU MODEL CONFIG ==========================
GPU_MODEL_CONFIG = {
    "sdxl": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "fp16", "quant": "int8", "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "small":    {"dtype": "fp16", "quant": "int8", "offload": "group_offload", "torch_compile": False, "warmup": False,
                     "controlnet_offload": None},
    },
    "flux_kontext": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "fp16", "quant": "int8", "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "small":    {"dtype": "fp16", "quant": "int8", "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "flux_fill": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "fp16", "quant": "int8", "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "small":    {"dtype": "fp16", "quant": "int8", "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "wan_5b": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "small":    {"dtype": "bf16", "quant": None, "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "wan_14b": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "small":    {"dtype": "bf16", "quant": None, "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "ltx_video": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "small":    {"dtype": "bf16", "quant": None, "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "ltx2": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": "fp8", "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "medium":   {"dtype": "bf16", "quant": "fp8", "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "hunyuan_video": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": "fp8", "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "bf16", "quant": "fp8", "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "small":    {"dtype": "bf16", "quant": "fp8", "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "cogvideox": {
        "high_end": {"dtype": "bf16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "bf16", "quant": None, "offload": "cpu_offload", "torch_compile": False, "warmup": False},
        "small":    {"dtype": "bf16", "quant": None, "offload": "sequential", "torch_compile": False, "warmup": False},
    },
    "svd": {
        "high_end": {"dtype": "fp16", "quant": None, "offload": None, "torch_compile": False, "warmup": False},
        "large":    {"dtype": "fp16", "quant": None, "offload": None, "torch_compile": True, "warmup": True},
        "medium":   {"dtype": "fp16", "quant": None, "offload": "cpu_offload", "torch_compile": True, "warmup": True},
        "small":    {"dtype": "fp16", "quant": None, "offload": "group_offload", "torch_compile": False, "warmup": False},
    },
}

def _get_gpu_tier():
    """Return GPU tier string based on VRAM.
    Seuils -2GB vs nominal pour compenser VRAM réelle
    (ex: GPU 20GB → ~18.1GB, GPU 12GB → ~11.2GB)."""
    if VRAM_GB >= 36:       # nominalement 40GB+
        return "high_end"
    elif VRAM_GB >= 16:     # nominalement 18-20GB+
        return "large"
    elif VRAM_GB >= 8:      # nominalement 10-12GB
        return "medium"
    elif VRAM_GB > 0:       # nominalement 8GB
        return "small"
    return "cpu"

GPU_TIER = _get_gpu_tier()


def get_generation_time_estimates():
    """
    Return estimated generation times (seconds) per task based on detected GPU.
    """
    gpu_name = ""
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0).lower()

    gpu_benchmarks = {
        "4090":    {"sdxl_inpaint_35": 8,   "sdxl_txt2img_30": 7,  "flux_kontext_28": 25,  "wan_5b_30": 90,   "wan_14b_30": 300},
        "3090":    {"sdxl_inpaint_35": 12,  "sdxl_txt2img_30": 10, "flux_kontext_28": 40,  "wan_5b_30": 180,  "wan_14b_30": 600},
        "a100":    {"sdxl_inpaint_35": 10,  "sdxl_txt2img_30": 8,  "flux_kontext_28": 30,  "wan_5b_30": 90,   "wan_14b_30": 250},
        "a4500":   {"sdxl_inpaint_35": 19,  "sdxl_txt2img_30": 16, "flux_kontext_28": 55,  "wan_5b_30": 240,  "wan_14b_30": 800},
        "3070 ti": {"sdxl_inpaint_35": 44,  "sdxl_txt2img_30": 38, "flux_kontext_28": 120, "wan_5b_30": 600,  "wan_14b_30": 1800},
        "3070":    {"sdxl_inpaint_35": 50,  "sdxl_txt2img_30": 42, "flux_kontext_28": 140, "wan_5b_30": 700,  "wan_14b_30": 2000},
        "3060":    {"sdxl_inpaint_35": 55,  "sdxl_txt2img_30": 48, "flux_kontext_28": 160, "wan_5b_30": 800,  "wan_14b_30": 2400},
        "4070 ti": {"sdxl_inpaint_35": 15,  "sdxl_txt2img_30": 13, "flux_kontext_28": 45,  "wan_5b_30": 200,  "wan_14b_30": 650},
        "4070":    {"sdxl_inpaint_35": 20,  "sdxl_txt2img_30": 17, "flux_kontext_28": 60,  "wan_5b_30": 280,  "wan_14b_30": 900},
        "4060":    {"sdxl_inpaint_35": 35,  "sdxl_txt2img_30": 30, "flux_kontext_28": 100, "wan_5b_30": 500,  "wan_14b_30": 1500},
        "1080":    {"sdxl_inpaint_35": 60,  "sdxl_txt2img_30": 52, "flux_kontext_28": 180, "wan_5b_30": 900,  "wan_14b_30": 3000},
        "2080":    {"sdxl_inpaint_35": 45,  "sdxl_txt2img_30": 40, "flux_kontext_28": 150, "wan_5b_30": 700,  "wan_14b_30": 2200},
    }

    for pattern, benchmarks in gpu_benchmarks.items():
        if pattern in gpu_name:
            return benchmarks

    tier_fallbacks = {
        "high_end": {"sdxl_inpaint_35": 10,  "sdxl_txt2img_30": 8,  "flux_kontext_28": 30,  "wan_5b_30": 90,   "wan_14b_30": 250},
        "large":    {"sdxl_inpaint_35": 15,  "sdxl_txt2img_30": 13, "flux_kontext_28": 50,  "wan_5b_30": 200,  "wan_14b_30": 700},
        "medium":   {"sdxl_inpaint_35": 45,  "sdxl_txt2img_30": 40, "flux_kontext_28": 130, "wan_5b_30": 650,  "wan_14b_30": 2000},
        "small":    {"sdxl_inpaint_35": 55,  "sdxl_txt2img_30": 48, "flux_kontext_28": 160, "wan_5b_30": 800,  "wan_14b_30": 2500},
    }

    return tier_fallbacks.get(GPU_TIER, tier_fallbacks["medium"])


# ========================== MODEL DICTIONARIES ==========================

# Modeles disponibles (base text2img — Fooocus patch ajoute l'inpainting)
# Tous en diffusers format pour partager le cache HF avec text2img
MODELS = {
    "epiCRealism XL (Fast)": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
    "epiCRealism XL (Moyen)": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
    "epiCRealism XL (Normal)": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
    "Juggernaut XL (Moyen)": "RunDiffusion/Juggernaut-XL-v9",
    "Fluently XL v3 Inpaint": "fluently/Fluently-XL-v3-inpainting",
}

# Quantification par variante (défaut: int8)
MODEL_QUANT = {
    "epiCRealism XL (Fast)": "int4",
    "epiCRealism XL (Normal)": "none",
    "CyberRealistic Pony (Normal)": "none",
}

SINGLE_FILE_MODELS = {
    # HuggingFace: (repo_id, filename, optional_quant)
    "CyberRealistic Pony (Moyen)": ("cyberdelia/CyberRealisticPony", "CyberRealisticPony_V16.0_FP16.safetensors"),
    "CyberRealistic Pony (Normal)": ("cyberdelia/CyberRealisticPony", "CyberRealisticPony_V16.0_FP16.safetensors", "none"),
    # CivitAI: ("civitai:{version_id}", filename, optional_quant) — downloaded via CivitAI API
}


def _refresh_imported_model_registries():
    """Merge user-imported local checkpoints into the runtime registries.

    Imports are stored in ~/.joyboy/config.json so users can add a CivitAI/HF
    model without editing Python files. This function is intentionally cheap and
    idempotent; loaders call it right before resolving a model name.
    """
    try:
        from core.infra.model_imports import get_imported_model_registry_entries
    except Exception:
        return []

    entries = get_imported_model_registry_entries()
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        SINGLE_FILE_MODELS[name] = tuple(entry["single_file"])
        MODEL_QUANT[name] = entry.get("quant", "int8")
        ALL_MODELS[entry["key"]] = {
            "name": name,
            "repo": entry["repo"],
            "size": entry.get("size", "~?"),
            "category": entry.get("category", "image"),
            "desc": entry.get("desc", "Import local"),
            "quant": entry.get("quant", "int8"),
            "capabilities": entry.get("capabilities", ["inpaint", "txt2img"]),
            "imported": True,
        }
    return entries


def resolve_single_file_model(model_name):
    """Résout le chemin local d'un modèle single-file (HuggingFace ou CivitAI).

    Returns: chemin local du fichier safetensors
    """
    if model_name not in SINGLE_FILE_MODELS:
        return None
    sfm = SINGLE_FILE_MODELS[model_name]
    repo_id, filename = sfm[0], sfm[1]

    if repo_id.startswith("local-file:"):
        return repo_id.split(":", 1)[1]
    elif repo_id.startswith("civitai:"):
        return _download_civitai_model(repo_id, filename)
    else:
        from huggingface_hub import hf_hub_download
        return hf_hub_download(repo_id=repo_id, filename=filename, resume_download=True)


def _download_civitai_model(repo_id, filename):
    """Télécharge un modèle depuis CivitAI si pas déjà en cache."""
    version_id = repo_id.split(":")[1]
    cache_dir = os.path.join(MODELS_DIR, "civitai")
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, filename)

    if os.path.exists(local_path):
        return local_path

    try:
        from config import CIVITAI_API_KEY
    except ImportError:
        CIVITAI_API_KEY = ""

    url = f"https://civitai.com/api/download/models/{version_id}"
    if CIVITAI_API_KEY:
        url += f"?token={CIVITAI_API_KEY}"

    print(f"[DOWNLOAD] CivitAI: {filename} (version {version_id})...")
    import urllib.request
    import shutil
    tmp_path = local_path + ".tmp"
    try:
        # Token in query param only — Authorization header breaks CDN redirects (400)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CrockApp/1.0",
        })
        with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 / total
                    print(f"\r[DOWNLOAD] {downloaded / 1e9:.1f}/{total / 1e9:.1f} GB ({pct:.0f}%)", end="", flush=True)
            print()  # newline after progress
        os.rename(tmp_path, local_path)
        size_gb = os.path.getsize(local_path) / 1e9
        print(f"[DOWNLOAD] CivitAI: {filename} OK ({size_gb:.1f}GB)")
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(f"CivitAI download failed: {e}")

    return local_path

FLUX_MODELS = {
    "Flux.1 Fill Dev": "black-forest-labs/FLUX.1-Fill-dev",
    "Flux Fill INT4": "black-forest-labs/FLUX.1-Fill-dev",
    "Flux Fill INT8": "black-forest-labs/FLUX.1-Fill-dev",
}

# Repos pré-quantifiés NF4 (transformer + T5 déjà en 4-bit, ~13GB au lieu de ~30GB)
FLUX_FILL_NF4_REPO = "diffusers/FLUX.1-Fill-dev-nf4"
FLUX_DEV_NF4_REPO = "diffusers/FLUX.1-dev-bnb-4bit"

FLUX_KONTEXT_MODELS = {
    "Flux Kontext": "black-forest-labs/FLUX.1-Kontext-dev",
    "Flux Kontext INT8": "black-forest-labs/FLUX.1-Kontext-dev",
}

TEXT2IMG_MODELS = {
    "Juggernaut XL v9": "RunDiffusion/Juggernaut-XL-v9",
    "epiCRealism XL": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
    "SDXL Turbo": "stabilityai/sdxl-turbo",
    "Flux Dev INT4": "black-forest-labs/FLUX.1-dev",
    "Flux Dev INT8": "black-forest-labs/FLUX.1-dev",
}

VIDEO_MODELS = {
    "wan": {
        "name": "Wan 2.1 I2V 14B",
        "id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "vram": "8GB (offload)",
        "description": "Meilleure qualite, I2V 14B, pack local ready, 480P",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 81,
        "default_steps": 50,
        "default_fps": 16,
    },
    "svd": {
        "name": "SVD 1.1",
        "id": "stabilityai/stable-video-diffusion-img2vid-xt-1-1",
        "vram": "8GB",
        "description": "Image-to-video compact sur 8GB. Mouvement subtil, pas de prompt texte.",
        "supports_prompt": False,
        "supports_image": True,
        "low_vram_tier": "recommended",
        "default_frames": 18,
        "default_steps": 10,
        "default_fps": 8,
    },
    "cogvideox": {
        "name": "CogVideoX-5B I2V",
        "id": "THUDM/CogVideoX-5b-I2V",
        "vram": "12-20GB recommande (experimental <=10GB)",
        "description": "Image-to-video lourd. Sur 8GB JoyBoy bascule vers SVD sauf override experimental.",
        "quant": "bf16/offload",
        "experimental_low_vram": True,
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 49,
        "default_steps": 50,
        "default_fps": 8,
    },
    "cogvideox-q4": {
        "name": "CogVideoX-5B I2V Q4",
        "id": "THUDM/CogVideoX-5b-I2V",
        "vram": "experimental <=10GB",
        "description": "Backend BitsAndBytes 4-bit garde en option avancee; peut rester bloque a 0% sur 8GB.",
        "quant": "bnb-4bit",
        "experimental_low_vram": True,
        "hidden": True,
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 33,
        "default_steps": 50,
        "default_fps": 8,
    },
    "cogvideox-2b": {
        "name": "CogVideoX-2B",
        "id": "THUDM/CogVideoX-2b",
        "vram": "6GB",
        "description": "Plus leger, text-to-video uniquement (pas d'image input)",
        "experimental_low_vram": True,
        "supports_prompt": True,
        "supports_image": False,
        "low_vram_tier": "advanced",
        "default_frames": 49,
        "default_steps": 50,
        "default_fps": 8,
    },
    "wan22": {
        "name": "Wan 2.2 I2V A14B",
        "id": "Wan-AI/Wan2.2-I2V-A14B-Diffusers",
        "vram": "14GB (fp8)",
        "description": "Meilleure qualite, MoE 27B (14B actif), 480P/720P, pack local ready",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 81,
        "default_steps": 40,
        "default_fps": 16,
    },
    "hunyuan": {
        "name": "HunyuanVideo 1.5 I2V",
        "id": "hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v_step_distilled",
        "vram": "14GB",
        "description": "Step-distilled 8.3B, I2V + prompt, 480P, 12 steps, rapide sur 20GB",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 61,
        "default_steps": 12,
        "default_fps": 15,
    },
    "wan22-5b": {
        "name": "Wan 2.2 TI2V 5B",
        "id": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
        "vram": "10GB (offload)",
        "description": "5B dense, I2V + T2V, 720P/480P, 24fps, pack local ready",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 81,
        "default_steps": 30,
        "default_fps": 24,
    },
    "fastwan": {
        "name": "FastWan 2.2 5B",
        "id": "FastVideo/FastWan2.2-TI2V-5B-FullAttn-Diffusers",
        "vram": "10GB (offload)",
        "description": "Distille DMD 3 steps, I2V + T2V, ultra-rapide mais preview/qualité variable",
        "supports_prompt": True,
        "supports_image": True,
        "experimental_low_vram": True,
        "low_vram_tier": "advanced",
        "default_frames": 81,
        "default_steps": 3,
        "default_fps": 24,
    },
    "wan22-t2v-14b": {
        "name": "Wan 2.2 T2V 14B",
        "id": "Wan-AI/Wan2.2-T2V-A14B-Diffusers",
        "vram": "14GB (offload)",
        "description": "14B MoE T2V only, 480P, meilleure qualite text-to-video, pack local ready",
        "supports_prompt": True,
        "supports_image": False,
        "low_vram_tier": "advanced",
        "default_frames": 81,
        "default_steps": 50,
        "default_fps": 24,
    },
    "ltx": {
        "name": "LTX-Video 2B",
        "id": "Lightricks/LTX-Video",
        "vram": "8GB experimental (JoyBoy Diffusers) / Q8 stack requis pour rapide",
        "description": "LTX-Video 2B a des configs distillees rapides, mais le loader Diffusers JoyBoy reste experimental sur 8GB. SVD reste le profil garanti.",
        "experimental_low_vram": True,
        "backend_status": "experimental",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 41,
        "default_steps": 8,
        "default_fps": 8,
    },
    "framepack": {
        "name": "FramePack F1 I2V",
        "id": "lllyasviel/FramePack_F1_I2V_HY_20250503",
        "vram": "6GB VRAM officiel, RAM systeme elevee en Diffusers",
        "description": "FramePack F1 via Diffusers/HunyuanVideo. Peut tourner en offload sur 8GB, mais consomme beaucoup de RAM systeme; presets 5s/90 frames ou 10s/180 frames.",
        "experimental_low_vram": True,
        "backend_status": "experimental",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 90,
        "default_steps": 9,
        "default_fps": 18,
    },
    "framepack-fast": {
        "name": "FramePack F1 rapide",
        "id": "lllyasviel/FramePack_F1_I2V_HY_20250503",
        "vram": "8GB test rapide, RAM systeme elevee",
        "description": "Preset FramePack rapide pour tester un mouvement: 5s reelles, 60 frames, 7 steps, resolution plus compacte.",
        "experimental_low_vram": True,
        "backend_status": "experimental",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 60,
        "default_steps": 7,
        "default_fps": 12,
    },
    "ltx2": {
        "name": "LTX-2 19B",
        "id": "Lightricks/LTX-2",
        "vram": "12GB (offload)",
        "description": "19B, 512P, 40 steps, T2V + I2V, audio sync, pack local ready",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 121,
        "default_steps": 40,
        "default_fps": 24,
    },
    "ltx2_fp8": {
        "name": "LTX-2 19B FP8",
        "id": "Lightricks/LTX-2",
        "vram": "12GB (offload)",
        "description": "19B FP8 pré-quantifié (ltx_pipelines officiel, 20GB dl), T2V + I2V",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "default_frames": 121,
        "default_steps": 40,
        "default_fps": 24,
    },
    "ltx23_fp8": {
        "name": "LTX-2.3 22B FP8",
        "id": "Lightricks/LTX-2.3-fp8",
        "hf_repos": [
            "Lightricks/LTX-2.3-fp8",
            "Lightricks/LTX-2.3",
        ],
        "hf_allow_patterns": {
            "Lightricks/LTX-2.3-fp8": [
                "ltx-2.3-22b-distilled-fp8.safetensors",
            ],
            "Lightricks/LTX-2.3": [
                "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            ],
        },
        "hf_required_files": {
            "Lightricks/LTX-2.3-fp8": [
                "ltx-2.3-22b-distilled-fp8.safetensors",
            ],
            "Lightricks/LTX-2.3": [
                "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            ],
        },
        "vram": "24GB+ / GH200 recommandé",
        "description": "LTX-2.3 FP8 distillé, 8 steps, I2V + T2V + audio natif, meilleur prompt following que LTX-2, backend ltx_pipelines",
        "supports_prompt": True,
        "supports_image": True,
        "low_vram_tier": "advanced",
        "backend_status": "experimental",
        "default_frames": 121,
        "default_steps": 8,
        "default_fps": 24,
    },
    "wan-native-5b": {
        "name": "Wan 2.2 5B (Natif)",
        "id": "Wan-AI/Wan2.2-TI2V-5B",
        "vram": "10GB (offload)",
        "description": "Backend officiel Wan (pas diffusers), I2V + T2V, 720P, stable",
        "supports_prompt": True,
        "supports_image": True,
        "default_frames": 81,
        "default_steps": 50,
        "default_fps": 24,
        "native_backend": True,
    },
    "wan-native-14b": {
        "name": "Wan 2.2 14B (Natif)",
        "id": "Wan-AI/Wan2.2-I2V-A14B",
        "vram": "14GB (offload)",
        "description": "Backend officiel Wan (pas diffusers), MoE 27B, meilleure qualite",
        "supports_prompt": True,
        "supports_image": True,
        "default_frames": 81,
        "default_steps": 40,
        "default_fps": 24,
        "native_backend": True,
    },
    "lightx2v-wan22-i2v-4step": {
        "name": "LightX2V Wan 2.2 I2V 4-step",
        "id": "Wan-AI/Wan2.2-I2V-A14B",
        "hf_repos": [
            "Wan-AI/Wan2.2-I2V-A14B",
            "lightx2v/Wan2.2-Distill-Models",
        ],
        "hf_allow_patterns": {
            "lightx2v/Wan2.2-Distill-Models": [
                "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
            ],
        },
        "hf_required_files": {
            "lightx2v/Wan2.2-Distill-Models": [
                "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
            ],
        },
        "vram": "14GB+ (offload) / 40GB recommande",
        "description": "Wan 2.2 A14B I2V distille LightX2V en 4 steps, rapide + qualite, backend local optionnel",
        "supports_prompt": True,
        "supports_image": True,
        "default_frames": 81,
        "default_steps": 4,
        "default_fps": 16,
        "backend": "lightx2v",
        "backend_status": "optional",
        "lightx2v_base_repo": "Wan-AI/Wan2.2-I2V-A14B",
        "lightx2v_distill_repo": "lightx2v/Wan2.2-Distill-Models",
        "lightx2v_model_cls": "wan2.2_moe_distill",
        "lightx2v_task": "i2v",
        "lightx2v_config": "configs/distill/wan22/wan_moe_i2v_distill_model.json",
        "lightx2v_turbo_config": "configs/distill/wan22/wan_moe_i2v_distill_quant.json",
        "low_vram_tier": "advanced",
    },
    "lightx2v-wan22-t2v-4step": {
        "name": "LightX2V Wan 2.2 T2V 4-step",
        "id": "Wan-AI/Wan2.2-T2V-A14B",
        "hf_repos": [
            "Wan-AI/Wan2.2-T2V-A14B",
            "lightx2v/Wan2.2-Distill-Loras",
        ],
        "hf_allow_patterns": {
            "lightx2v/Wan2.2-Distill-Loras": [
                "wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step_1217.safetensors",
                "wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step_1217.safetensors",
            ],
        },
        "hf_required_files": {
            "lightx2v/Wan2.2-Distill-Loras": [
                "wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step_1217.safetensors",
                "wan2.2_t2v_A14b_low_noise_lora_rank64_lightx2v_4step_1217.safetensors",
            ],
        },
        "vram": "14GB+ (offload) / 40GB recommande",
        "description": "Wan 2.2 A14B text-to-video LightX2V distille LoRA 4 steps",
        "supports_prompt": True,
        "supports_image": False,
        "default_frames": 81,
        "default_steps": 4,
        "default_fps": 16,
        "backend": "lightx2v",
        "backend_status": "optional",
        "lightx2v_base_repo": "Wan-AI/Wan2.2-T2V-A14B",
        "lightx2v_lora_repo": "lightx2v/Wan2.2-Distill-Loras",
        "lightx2v_model_cls": "wan2.2_moe_distill",
        "lightx2v_task": "t2v",
        "lightx2v_config": "configs/distill/wan22/wan_moe_t2v_distill_lora.json",
        "low_vram_tier": "advanced",
    },
    "lightx2v-wan22-i2v-8gb": {
        "name": "LightX2V Wan 2.2 I2V 8GB",
        "id": "Wan-AI/Wan2.2-I2V-A14B",
        "hf_repos": [
            "Wan-AI/Wan2.2-I2V-A14B",
            "lightx2v/Wan2.2-Distill-Models",
        ],
        "hf_allow_patterns": {
            "lightx2v/Wan2.2-Distill-Models": [
                "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
            ],
        },
        "hf_required_files": {
            "lightx2v/Wan2.2-Distill-Models": [
                "wan2.2_i2v_A14b_high_noise_lightx2v_4step.safetensors",
                "wan2.2_i2v_A14b_low_noise_lightx2v_4step.safetensors",
            ],
        },
        "vram": "8GB experimental (offload agressif)",
        "description": "Profil LightX2V low-resource: Wan 2.2 I2V 4 steps avec offload, a tester manuellement sur 8GB",
        "supports_prompt": True,
        "supports_image": True,
        "experimental_low_vram": True,
        "default_frames": 49,
        "default_steps": 4,
        "default_fps": 16,
        "backend": "lightx2v",
        "backend_status": "optional",
        "lightx2v_base_repo": "Wan-AI/Wan2.2-I2V-A14B",
        "lightx2v_distill_repo": "lightx2v/Wan2.2-Distill-Models",
        "lightx2v_model_cls": "wan2.2_moe_distill",
        "lightx2v_task": "i2v",
        "lightx2v_config": "configs/distill/wan22/wan_moe_i2v_distill_4090.json",
        "lightx2v_turbo_config": "configs/distill/wan22/wan_moe_i2v_distill_quant.json",
        "low_vram_profile": "lightx2v",
        "low_vram_tier": "advanced",
    },
}

_VIDEO_CAPABILITY_DEFAULTS = {
    "min_vram_gb": 8,
    "min_ram_gb": 32,
    "supports_i2v": True,
    "supports_t2v": False,
    "supports_continue": True,
    "supports_audio_native": False,
    "continuation_strategy": "last_frame_i2v",
    "recommended_for": [],
}

_VIDEO_CAPABILITY_OVERRIDES = {
    "svd": {
        "min_vram_gb": 6,
        "min_ram_gb": 16,
        "supports_prompt": False,
        "supports_continue": True,
        "recommended_for": ["safe_low_vram"],
        "continuation_strategy": "last_frame_i2v_subtle_motion",
    },
    "cogvideox-2b": {
        "supports_i2v": False,
        "supports_t2v": True,
        "supports_continue": False,
        "continuation_strategy": "text_only",
    },
    "wan22": {
        "min_vram_gb": 14,
        "min_ram_gb": 64,
        "recommended_for": ["high_end_video", "quality_i2v"],
        "continuation_strategy": "last_frame_i2v_wan",
    },
    "wan-native-14b": {
        "min_vram_gb": 24,
        "min_ram_gb": 96,
        "recommended_for": ["high_end_video", "quality_i2v"],
        "continuation_strategy": "last_frame_i2v_wan_native",
    },
    "wan22-t2v-14b": {
        "min_vram_gb": 24,
        "min_ram_gb": 96,
        "supports_i2v": False,
        "supports_t2v": True,
        "supports_continue": False,
        "recommended_for": ["high_end_video", "quality_t2v"],
        "continuation_strategy": "text_only",
    },
    "wan22-5b": {
        "min_vram_gb": 10,
        "min_ram_gb": 48,
        "supports_t2v": True,
        "recommended_for": ["balanced_t2v_i2v"],
        "continuation_strategy": "last_frame_i2v_wan",
    },
    "fastwan": {
        "min_vram_gb": 10,
        "min_ram_gb": 48,
        "supports_t2v": True,
        "recommended_for": ["fast_preview"],
        "continuation_strategy": "last_frame_i2v_wan",
    },
    "wan-native-5b": {
        "min_vram_gb": 10,
        "min_ram_gb": 48,
        "supports_t2v": True,
        "recommended_for": ["balanced_t2v_i2v"],
        "continuation_strategy": "last_frame_i2v_wan_native",
    },
    "ltx2": {
        "min_vram_gb": 20,
        "min_ram_gb": 96,
        "supports_t2v": True,
        "supports_audio_native": True,
        "recommended_for": ["high_end_video", "audio_video"],
        "continuation_strategy": "last_frame_i2v_ltx2",
    },
    "ltx2_fp8": {
        "min_vram_gb": 20,
        "min_ram_gb": 96,
        "supports_t2v": True,
        "supports_audio_native": True,
        "recommended_for": ["high_end_video", "audio_video"],
        "continuation_strategy": "last_frame_i2v_ltx2_fp8",
    },
    "ltx23_fp8": {
        "min_vram_gb": 24,
        "min_ram_gb": 128,
        "supports_t2v": True,
        "supports_audio_native": True,
        "recommended_for": ["high_end_video", "audio_video", "latest_ltx"],
        "continuation_strategy": "last_frame_i2v_ltx23_fp8",
    },
    "framepack": {
        "min_vram_gb": 24,
        "min_ram_gb": 96,
        "recommended_for": ["high_end_video", "long_continue"],
        "continuation_strategy": "last_frame_i2v_long_context",
    },
    "framepack-fast": {
        "min_vram_gb": 12,
        "min_ram_gb": 64,
        "recommended_for": ["fast_preview"],
        "continuation_strategy": "last_frame_i2v_long_context_fast",
    },
    "hunyuan": {
        "min_vram_gb": 16,
        "min_ram_gb": 64,
        "recommended_for": ["high_end_video", "alternative_i2v"],
        "continuation_strategy": "last_frame_i2v_hunyuan",
    },
    "lightx2v-wan22-i2v-4step": {
        "min_vram_gb": 14,
        "min_ram_gb": 64,
        "recommended_for": ["high_end_video", "fast_quality_i2v"],
        "continuation_strategy": "last_frame_i2v_lightx2v",
    },
    "lightx2v-wan22-t2v-4step": {
        "min_vram_gb": 14,
        "min_ram_gb": 64,
        "supports_i2v": False,
        "supports_t2v": True,
        "supports_continue": False,
        "recommended_for": ["high_end_video", "fast_quality_t2v"],
        "continuation_strategy": "text_only",
    },
    "lightx2v-wan22-i2v-8gb": {
        "min_vram_gb": 8,
        "min_ram_gb": 32,
        "recommended_for": ["experimental_low_vram"],
        "continuation_strategy": "last_frame_i2v_lightx2v_low_vram",
    },
}

for _video_id, _video_meta in VIDEO_MODELS.items():
    _supports_image = bool(_video_meta.get("supports_image", False))
    _video_meta.update({
        **_VIDEO_CAPABILITY_DEFAULTS,
        "supports_i2v": _supports_image,
        "supports_continue": _supports_image,
        **_video_meta,
        **_VIDEO_CAPABILITY_OVERRIDES.get(_video_id, {}),
    })

ALL_MODELS = {
    "inpaint_epicrealism_fast": {
        "name": "epiCRealism XL (Fast)",
        "repo": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
        "size": "~2 GB",
        "category": "inpaint",
        "desc": "INT4 - Ultra rapide, qualite reduite",
        "quant": "int4"
    },
    "inpaint_epicrealism": {
        "name": "epiCRealism XL (Moyen)",
        "repo": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
        "size": "~3.5 GB",
        "category": "inpaint",
        "desc": "INT8 - Bon compromis vitesse/qualite",
        "quant": "int8"
    },
    "inpaint_epicrealism_hq": {
        "name": "epiCRealism XL (Normal)",
        "repo": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
        "size": "~6 GB",
        "category": "inpaint",
        "desc": "FP16 - Qualite maximale",
        "quant": "none"
    },
    "inpaint_juggernaut": {
        "name": "Juggernaut XL (Moyen)",
        "repo": "RunDiffusion/Juggernaut-XL-v9",
        "size": "~3.5 GB",
        "category": "inpaint",
        "desc": "INT8 - local pack ready, meilleure anatomie",
        "quant": "int8"
    },
    "inpaint_fluently": {
        "name": "Fluently XL v3 Inpaint",
        "repo": "fluently/Fluently-XL-v3-inpainting",
        "size": "~6 GB",
        "category": "inpaint",
        "desc": "Rapide et polyvalent"
    },
    "inpaint_flux_fill_int4": {
        "name": "Flux Fill INT4",
        "repo": "black-forest-labs/FLUX.1-Fill-dev",
        "size": "~13 GB",
        "category": "inpaint",
        "desc": "Flux Fill 12B NF4 - haute qualité, rapide sur GPU 16GB+",
        "quant": "int4",
    },
    "inpaint_flux_fill_int8": {
        "name": "Flux Fill INT8",
        "repo": "black-forest-labs/FLUX.1-Fill-dev",
        "size": "~18 GB",
        "category": "inpaint",
        "desc": "Flux Fill 12B INT8 - inpainting premium pour grosses configs",
        "quant": "int8",
    },
    "inpaint_flux_fill_dev": {
        "name": "Flux.1 Fill Dev",
        "repo": "black-forest-labs/FLUX.1-Fill-dev",
        "size": "~30 GB",
        "category": "inpaint",
        "desc": "Flux Fill bf16 - qualité maximale, nécessite accès Hugging Face",
        "quant": "none",
        "gated": True,
    },
    "txt2img_juggernaut": {
        "name": "Juggernaut XL v9",
        "repo": "RunDiffusion/Juggernaut-XL-v9",
        "size": "~6 GB",
        "category": "txt2img",
        "desc": "Meilleur global, anatomie parfaite"
    },
    "txt2img_epicrealism": {
        "name": "epiCRealism XL",
        "repo": "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl",
        "size": "~6 GB",
        "category": "txt2img",
        "desc": "Ultra realiste, textures top"
    },
    "txt2img_turbo": {
        "name": "SDXL Turbo",
        "repo": "stabilityai/sdxl-turbo",
        "size": "~5 GB",
        "category": "txt2img",
        "desc": "Tres rapide (4 steps)"
    },
    "txt2img_flux_dev_int4": {
        "name": "Flux Dev INT4",
        "repo": "black-forest-labs/FLUX.1-dev",
        "size": "~13 GB",
        "category": "txt2img",
        "desc": "Flux Dev 12B NF4 - très bon rendu, 40GB-friendly",
        "quant": "int4",
    },
    "txt2img_flux_dev_int8": {
        "name": "Flux Dev INT8",
        "repo": "black-forest-labs/FLUX.1-dev",
        "size": "~18 GB",
        "category": "txt2img",
        "desc": "Flux Dev 12B INT8 - rendu premium pour A100/A6000",
        "quant": "int8",
    },

    "inpaint_cyberrealistic_pony": {
        "name": "CyberRealistic Pony (Moyen)",
        "repo": "cyberdelia/CyberRealisticPony",
        "size": "~7 GB",
        "category": "inpaint",
        "desc": "INT8 - Pony XL v16, réaliste + mignon",
        "quant": "int8"
    },
    "inpaint_cyberrealistic_pony_hq": {
        "name": "CyberRealistic Pony (Normal)",
        "repo": "cyberdelia/CyberRealisticPony",
        "size": "~7 GB",
        "category": "inpaint",
        "desc": "FP16 - Pony XL v16, qualité maximale",
        "quant": "none"
    },
    "caption_blip": {
        "name": "BLIP (Description images)",
        "repo": "Salesforce/blip-image-captioning-base",
        "size": "~1 GB",
        "category": "utils"
    },
}

AUXILIARY_MODELS = {}  # Reserved for future auxiliary model definitions


# ========================== DOWNLOAD MANAGEMENT ==========================

download_status = {}


def _iter_huggingface_scan_cache_dirs():
    """Yield known Hub cache locations used across older and current JoyBoy installs."""
    candidates = [
        custom_cache,
        get_huggingface_hub_cache_dir(custom_cache),
        os.path.expanduser("~/.cache/huggingface"),
        os.path.expanduser("~/.cache/huggingface/hub"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".cache", "huggingface"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".cache", "huggingface", "hub"),
    ]
    seen = set()
    for cache_dir in candidates:
        if not cache_dir:
            continue
        normalized = os.path.abspath(os.path.expanduser(cache_dir))
        if normalized in seen:
            continue
        seen.add(normalized)
        yield normalized


def check_model_downloaded(repo_id):
    """Verifie si un modele est telecharge dans le cache"""
    if str(repo_id or "").startswith("local-file:"):
        return os.path.exists(str(repo_id).split(":", 1)[1])

    from huggingface_hub import scan_cache_dir

    for cache_dir in _iter_huggingface_scan_cache_dirs():
        if not os.path.exists(cache_dir):
            continue
        try:
            cache_info = scan_cache_dir(cache_dir)
            for repo in cache_info.repos:
                if repo.repo_id == repo_id:
                    return True
        except Exception:
            continue

    return False


def delete_model_from_cache(repo_id):
    """Supprime un modele du cache HuggingFace"""
    from huggingface_hub import scan_cache_dir
    import shutil

    if str(repo_id or "").startswith("local-file:"):
        local_path = str(repo_id).split(":", 1)[1]
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                print(f"[DELETE] Fichier local supprimé: {local_path}")
                return True
        except Exception as e:
            print(f"[DELETE] Erreur suppression fichier local: {e}")
        return False

    deleted = False

    for cache_dir in _iter_huggingface_scan_cache_dirs():
        if not os.path.exists(cache_dir):
            continue
        try:
            cache_info = scan_cache_dir(cache_dir)
            for repo in cache_info.repos:
                if repo.repo_id == repo_id:
                    for revision in repo.revisions:
                        try:
                            strategy = cache_info.delete_revisions(revision.commit_hash)
                            strategy.execute()
                            print(f"[DELETE] Supprime revision {revision.commit_hash[:8]} de {repo_id}")
                            deleted = True
                        except Exception as e:
                            print(f"[DELETE] Erreur suppression revision: {e}")
                            try:
                                if revision.snapshot_path and os.path.exists(revision.snapshot_path):
                                    shutil.rmtree(revision.snapshot_path)
                                    deleted = True
                            except Exception as e2:
                                print(f"[DELETE] Erreur suppression manuelle: {e2}")
        except Exception as e:
            print(f"[DELETE] Erreur scan cache {cache_dir}: {e}")
            continue

    if deleted:
        print(f"[DELETE] Modele {repo_id} supprime du cache")
    else:
        print(f"[DELETE] Modele {repo_id} non trouve dans le cache")

    return deleted


def get_model_download_status():
    """Retourne le statut des telechargements en cours"""
    return download_status


def get_all_models_status():
    """Retourne le statut de tous les modeles"""
    _refresh_imported_model_registries()
    try:
        from core.infra.local_config import (
            PROVIDER_META,
            get_provider_for_repo,
            is_provider_configured_for_repo,
        )
    except Exception:
        PROVIDER_META = {}

        def get_provider_for_repo(repo_id):
            if str(repo_id or "").startswith("local-file:"):
                return "local"
            return "civitai" if str(repo_id or "").startswith("civitai:") else "huggingface"

        def is_provider_configured_for_repo(repo_id):
            return str(repo_id or "").startswith("local-file:")

    status = {}
    for key, info in ALL_MODELS.items():
        dl_info = download_status.get(key, {})
        is_downloading = dl_info.get("downloading", False)
        progress = dl_info.get("progress", 0)
        downloaded_size = dl_info.get("downloaded_size", 0)
        total_size = dl_info.get("total_size", 0)
        provider = get_provider_for_repo(info["repo"])
        provider_key = "CIVITAI_API_KEY" if provider == "civitai" else "HF_TOKEN"
        provider_label = "Local" if provider == "local" else PROVIDER_META.get(provider_key, {}).get("label", provider.title())
        provider_hint = (
            "Déjà présent sur cette machine."
            if provider == "local"
            else "Souvent utile pour les téléchargements CivitAI."
            if provider == "civitai"
            else "Optionnel sauf modèles gated ou privés."
        )

        if is_downloading:
            is_downloaded = False
        else:
            is_downloaded = check_model_downloaded(info["repo"])

        status[key] = {
            "name": info["name"],
            "repo": info["repo"],
            "size": info["size"],
            "category": info["category"],
            "desc": info.get("desc", ""),
            "downloaded": is_downloaded,
            "downloading": is_downloading,
            "progress": progress,
            "downloaded_bytes": downloaded_size,
            "total_bytes": total_size,
            "provider": provider,
            "provider_label": provider_label,
            "provider_configured": is_provider_configured_for_repo(info["repo"]),
            "provider_hint": provider_hint,
            "capabilities": info.get("capabilities", []),
            "imported": bool(info.get("imported")),
            "quant": info.get("quant", ""),
        }
    return status


def get_model_total_size(repo_id):
    """Recupere la taille totale d'un modele depuis HuggingFace"""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        repo_info = api.repo_info(repo_id=repo_id, repo_type="model")
        total_size = 0
        for sibling in repo_info.siblings:
            if hasattr(sibling, 'size') and sibling.size:
                total_size += sibling.size
        return total_size
    except Exception as e:
        print(f"[DOWNLOAD] Could not get model size: {e}")
        return None


def get_cache_folder_size(repo_id):
    """Calcule la taille actuelle du dossier cache pour un repo"""
    cache_folder_name = "models--" + repo_id.replace("/", "--")
    cache_path = os.path.join(custom_cache, cache_folder_name)

    if not os.path.exists(cache_path):
        return 0

    total_size = 0
    for dirpath, dirnames, filenames in os.walk(cache_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            try:
                total_size += os.path.getsize(filepath)
            except OSError:
                pass
    return total_size


def download_model_async(model_key):
    """Alias for download_model_background (backward compat)."""
    return download_model_background(model_key)


def download_model_background(model_key):
    """Telecharge un modele en background avec suivi de progression reel"""
    import threading
    _refresh_imported_model_registries()

    if model_key not in ALL_MODELS:
        return False, "Modele inconnu"

    info = ALL_MODELS[model_key]
    repo_id = info["repo"]

    if check_model_downloaded(repo_id):
        print(f"[DOWNLOAD] Already cached: {info['name']}")
        return True, "already_cached"

    if download_status.get(model_key, {}).get("downloading", False):
        return False, "Telechargement deja en cours"

    def download_thread():
        import time
        from huggingface_hub import snapshot_download

        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

        total_size = get_model_total_size(repo_id)
        if total_size is None or total_size == 0:
            total_size = 6.5 * 1024 * 1024 * 1024

        download_status[model_key] = {
            "downloading": True,
            "progress": 0,
            "total_size": total_size,
            "downloaded_size": 0
        }

        print(f"[DOWNLOAD] Starting: {info['name']} ({total_size / (1024**3):.1f} GB)")

        stop_monitoring = threading.Event()

        def monitor_progress():
            while not stop_monitoring.is_set():
                downloaded = get_cache_folder_size(repo_id)
                progress = min(99, int((downloaded / total_size) * 100))
                download_status[model_key].update({
                    "progress": progress,
                    "downloaded_size": downloaded
                })
                time.sleep(1)

        monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
        monitor_thread.start()

        try:
            snapshot_download(
                repo_id=repo_id,
                cache_dir=custom_cache,
                resume_download=True
            )

            stop_monitoring.set()
            download_status[model_key] = {"downloading": False, "progress": 100}
            print(f"[DOWNLOAD] Completed: {info['name']}")

        except Exception as e:
            stop_monitoring.set()
            download_status[model_key] = {"downloading": False, "progress": 0, "error": str(e)}
            print(f"[DOWNLOAD] Error: {e}")

    thread = threading.Thread(target=download_thread, daemon=True)
    thread.start()

    return True, "downloading"


def get_download_progress(model_key=None):
    """Retourne la progression du telechargement d'un modele ou de tous."""
    if model_key:
        return download_status.get(model_key, {})
    return download_status
