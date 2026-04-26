from __future__ import annotations

"""
Preload & Quantization Cache System
Pré-charge les modèles au démarrage et nettoie les caches obsolètes.
"""

import os
import sys
import torch
import threading
from pathlib import Path
from typing import Generator, Callable

from core.infra.paths import get_models_dir

# Cache directory
QUANTIZED_CACHE_DIR = get_models_dir() / "quantized"
QUANTIZED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_INPAINT_CACHE_KEY = "john6666_epicrealism-xl-vxvii-crystal-clear-realism-sdxl_fooocus"
FOOOCUS_REPO = "lllyasviel/fooocus_inpaint"
FOOOCUS_HEAD_FILENAME = "fooocus_inpaint_head.pth"
FOOOCUS_PATCH_FILENAME = "inpaint_v26.fooocus.patch"
CONTROLNET_DEPTH_REPO = "diffusers/controlnet-depth-sdxl-1.0-small"
CONTROLNET_DEPTH_WEIGHT_FILES = (
    "diffusion_pytorch_model.safetensors",
    "diffusion_pytorch_model.bin",
)

REQUIRED_PRELOAD_CACHE_TARGETS = [
    ("inpaint_pipe", "epiCRealism XL + Fooocus", CURRENT_INPAINT_CACHE_KEY, "int8"),
    ("controlnet_depth", "ControlNet Depth", "controlnet_depth", "int8"),
]

OPTIONAL_PRELOAD_DOWNLOADS = [
    ("inpaint_repo", "epiCRealism XL", "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl", "model_index.json"),
    ("fooocus_head", "Fooocus head", FOOOCUS_REPO, FOOOCUS_HEAD_FILENAME),
    ("fooocus_patch", "Fooocus patch", FOOOCUS_REPO, FOOOCUS_PATCH_FILENAME),
    ("depth_anything", "Depth Anything V2", "depth-anything/Depth-Anything-V2-Small-hf", "config.json"),
    ("segformer_b2", "SegFormer B2 clothes", "mattmdjaga/segformer_b2_clothes", "config.json"),
    ("florence_2", "Florence-2 Base", "microsoft/Florence-2-base", "preprocessor_config.json"),
]

# Repos HF obsolètes (anciens modèles remplacés, peuvent être supprimés)
DEPRECATED_HF_REPOS = [
    "dkjym/epiCRealism-XL-Inpainting",          # remplacé par CrystalClear (John6666)
    "stablediffusionapi/epicrealism-xl",          # remplacé par CrystalClear
    "krnl/epicrealism-xl-v8kiss-sdxl",              # remplacé par CrystalClear (John6666)
    "jgdickman/juggernaut-xl-inpainting",         # remplacé par RunDiffusion/Juggernaut-XL-v9
    "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",  # ancien SDXL inpaint base
    "OzzyGT/RealVisXL_V4.0_inpainting",          # ancien modèle plus utilisé
    "WaterKnight/diffusion-models",               # ancien modèle plus utilisé
    "stabilityai/stable-diffusion-xl-base-1.0",   # remplacé par krnl repo
    "kandinsky-community/kandinsky-2-2-prior",     # Kandinsky non utilisé
    "kandinsky-community/kandinsky-2-2-decoder-inpaint",  # Kandinsky non utilisé
    "runwayml/stable-diffusion-v1-5",             # SD 1.5 non utilisé
    "runwayml/stable-diffusion-inpainting",        # SD 1.5 inpainting non utilisé
    "SG161222/Realistic_Vision_V6.0_B1_noVAE",   # ancien modèle plus utilisé
    "guoyww/animatediff-motion-adapter-v1-5-3",   # AnimateDiff non utilisé
    "google/flan-t5-base",                         # non utilisé
    "andro-flock/lustify-sdxl-nsfw-checkpoint-v2-0-inpainting",  # ancien Lustify inpaint
]

# Status tracking
_preload_status = {
    "current_step": "",
    "progress": 0,
    "total_steps": 0,
    "done": False,
    "error": None
}
_preload_lock = threading.Lock()
_preload_callbacks = []


def get_status():
    """Retourne le status actuel du préchargement."""
    with _preload_lock:
        return _preload_status.copy()


def add_status_callback(callback: Callable):
    """Ajoute un callback appelé à chaque changement de status."""
    _preload_callbacks.append(callback)


def _update_status(step: str, progress: int = None, total: int = None, done: bool = False, error: str = None):
    """Met à jour le status et notifie les callbacks."""
    with _preload_lock:
        _preload_status["current_step"] = step
        if progress is not None:
            _preload_status["progress"] = progress
        if total is not None:
            _preload_status["total_steps"] = total
        _preload_status["done"] = done
        _preload_status["error"] = error

    # Notifier les callbacks
    for cb in _preload_callbacks:
        try:
            cb(_preload_status.copy())
        except Exception:
            pass

    print(f"[PRELOAD] {step}")


def is_quantized_cached(model_name: str, quant_type: str) -> bool:
    """Vérifie si un modèle quantifié est déjà en cache."""
    cache_file = QUANTIZED_CACHE_DIR / f"{model_name}_{quant_type}.pt"
    return cache_file.exists()


def get_quantized_cache_path(model_name: str, quant_type: str) -> Path:
    """Retourne le chemin du cache pour un modèle quantifié."""
    return QUANTIZED_CACHE_DIR / f"{model_name}_{quant_type}.pt"


def _should_preload_image_assets() -> bool:
    """Only preload heavy image assets when a local image accelerator exists."""
    try:
        if torch.cuda.is_available():
            return True
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        return bool(mps and mps.is_available())
    except Exception:
        return False


def _is_hf_file_cached(repo_id: str, filename: str, *, cache_dir: str | Path | None = None) -> bool:
    """Retourne True si un fichier HF ciblé est déjà présent dans le cache local."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False

    try:
        kwargs = {"cache_dir": str(cache_dir)} if cache_dir else {}
        cached = try_to_load_from_cache(repo_id, filename, **kwargs)
    except Exception:
        return False

    return isinstance(cached, str) and bool(cached)


def _is_controlnet_base_cached() -> bool:
    """ControlNet quant cache alone is not enough; Diffusers still needs config + base weights."""
    try:
        from core.models import custom_cache
    except Exception:
        custom_cache = None

    has_config = _is_hf_file_cached(CONTROLNET_DEPTH_REPO, "config.json", cache_dir=custom_cache)
    has_weights = any(
        _is_hf_file_cached(CONTROLNET_DEPTH_REPO, filename, cache_dir=custom_cache)
        for filename in CONTROLNET_DEPTH_WEIGHT_FILES
    )
    return has_config and has_weights


def is_controlnet_depth_ready() -> bool:
    """Returns True only when both the quantized cache and base HF weights are usable."""
    return is_quantized_cached("controlnet_depth", "int8") and _is_controlnet_base_cached()


def get_preload_cache_report() -> dict:
    """Construit un état de cache lisible pour le preload UI."""
    required = []
    optional = []
    preload_image_assets = _should_preload_image_assets()

    if preload_image_assets:
        for target_id, label, model_name, quant_type in REQUIRED_PRELOAD_CACHE_TARGETS:
            if target_id == "controlnet_depth":
                cached = is_controlnet_depth_ready()
                kind = "quantized+download"
            else:
                cached = is_quantized_cached(model_name, quant_type)
                kind = "quantized"
            required.append({
                "id": target_id,
                "label": label,
                "cached": cached,
                "kind": kind,
            })

        for target_id, label, repo_id, filename in OPTIONAL_PRELOAD_DOWNLOADS:
            optional.append({
                "id": target_id,
                "label": label,
                "cached": _is_hf_file_cached(repo_id, filename),
                "kind": "download",
            })

    cached_required = sum(1 for item in required if item["cached"])
    missing_required = len(required) - cached_required
    cached_optional = sum(1 for item in optional if item["cached"])

    return {
        "ready": missing_required == 0,
        "skipped": not preload_image_assets,
        "skip_reason": None if preload_image_assets else "no_cuda_or_mps",
        "required": required,
        "optional": optional,
        "counts": {
            "required_total": len(required),
            "required_cached": cached_required,
            "required_missing": missing_required,
            "optional_total": len(optional),
            "optional_cached": cached_optional,
        },
    }


def preload_all(force: bool = False) -> Generator[dict, None, None]:
    """
    Générateur qui pré-charge tous les modèles et yield le status.

    Args:
        force: Si True, re-quantifie même si le cache existe

    Yields:
        dict avec current_step, progress, total_steps, done
    """
    if not _should_preload_image_assets():
        _update_status("Profil CPU/non-CUDA: préchargement image lourd ignoré", 1, 1, done=True)
        yield get_status()
        return

    steps = [
        ("Nettoyage caches obsolètes...", _cleanup_deprecated_hf_repos),
        ("Analyse du cache local...", _check_cache),
        ("Préparation du modèle inpainting...", _preload_inpaint_download),
        ("Préparation du patch Fooocus...", _preload_fooocus_patch),
        ("Préparation de ControlNet Depth...", lambda: _preload_controlnet(force)),
        ("Préparation de Depth Anything V2...", lambda: _preload_depth_estimator(force)),
        ("Préparation de SegFormer (vêtements)...", lambda: _preload_segformer(force)),
        ("Préparation de Florence-2 (vision)...", lambda: _preload_florence(force)),
        ("Nettoyage mémoire GPU...", _cleanup_vram),
    ]

    total = len(steps) * 2  # Chaque étape a 2 phases: démarrage + fin
    _update_status("Démarrage du préchargement...", 0, total)
    yield get_status()

    for i, (step_name, step_func) in enumerate(steps):
        # Phase 1: Démarrage de l'étape
        _update_status(step_name, i * 2, total)
        yield get_status()

        try:
            step_func()
        except Exception as e:
            print(f"[PRELOAD] Erreur {step_name}: {e}")
            # Continue malgré les erreurs

        # Phase 2: Fin de l'étape (progression intermédiaire)
        _update_status(f"✓ {step_name.replace('...', '')} OK", i * 2 + 1, total)
        yield get_status()

    _update_status("Prêt !", total, total, done=True)
    yield get_status()


def _cleanup_deprecated_hf_repos():
    """Supprime les repos HF obsolètes du cache local pour libérer de l'espace."""
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()

        hashes_to_delete = []
        repos_found = []
        total_size = 0

        for repo in cache_info.repos:
            if repo.repo_id in DEPRECATED_HF_REPOS:
                repos_found.append(repo.repo_id)
                total_size += repo.size_on_disk
                for rev in repo.revisions:
                    hashes_to_delete.append(rev.commit_hash)

        if not hashes_to_delete:
            print(f"[PRELOAD] Aucun cache HF obsolète trouvé")
            return

        size_gb = total_size / 1024**3
        print(f"[PRELOAD] Suppression de {len(repos_found)} repos obsolètes ({size_gb:.1f} GB)...")
        for repo_id in repos_found:
            print(f"[PRELOAD]   - {repo_id}")

        strategy = cache_info.delete_revisions(*hashes_to_delete)
        strategy.execute()
        print(f"[PRELOAD] {size_gb:.1f} GB libérés !")

    except Exception as e:
        print(f"[PRELOAD] Nettoyage HF cache: {e}")


def _check_cache():
    """Vérifie l'état du cache quantifié."""
    cached = []
    missing = []

    models_to_check = [
        (CURRENT_INPAINT_CACHE_KEY, "int8", "epiCRealism XL INT8+Fooocus"),
        ("controlnet_depth", "int8", "ControlNet Depth"),
    ]

    for model, quant, name in models_to_check:
        if is_quantized_cached(model, quant):
            cached.append(name)
        else:
            missing.append(name)

    if cached:
        print(f"[PRELOAD] En cache: {', '.join(cached)}")
    if missing:
        print(f"[PRELOAD] À quantifier au premier lancement: {', '.join(missing)}")
    else:
        print(f"[PRELOAD] Tous les modèles sont en cache!")


def _preload_inpaint_download():
    """Pré-télécharge les fichiers du modèle inpaint (HF cache).

    Ne quantifie PAS — la quantification est faite par manager.py
    avec le Fooocus patch appliqué (les deux doivent être ensemble).
    """
    repo_id = "John6666/epicrealism-xl-vxvii-crystal-clear-realism-sdxl"

    try:
        from huggingface_hub import snapshot_download, try_to_load_from_cache
        # Check if already cached to avoid network hang
        # try_to_load_from_cache returns path if cached, None/_CACHED_NO_EXIST otherwise
        _test = try_to_load_from_cache(repo_id, "model_index.json")
        if _test is not None and isinstance(_test, str):
            print(f"[PRELOAD] {repo_id} déjà en cache (skip réseau)")
            return

        print(f"[PRELOAD] Téléchargement {repo_id}...")
        snapshot_download(repo_id=repo_id, resume_download=True)
        print(f"[PRELOAD] {repo_id} prêt dans le cache HF")

    except Exception as e:
        print(f"[PRELOAD] Erreur téléchargement inpaint: {e}")


def _preload_fooocus_patch():
    """Pré-télécharge les fichiers du Fooocus inpaint patch (1.3GB)."""
    try:
        from core.generation.fooocus_patch import download_fooocus_patch
        print(f"[PRELOAD] Vérification/téléchargement Fooocus patch...")
        download_fooocus_patch()
        print(f"[PRELOAD] Fooocus patch prêt dans le cache HF")

    except Exception as e:
        print(f"[PRELOAD] Erreur téléchargement Fooocus patch: {e}")


def _preload_controlnet(force: bool = False):
    """Pré-charge le ControlNet Depth."""
    cache_path = get_quantized_cache_path("controlnet_depth", "int8")
    base_cached = _is_controlnet_base_cached()

    if cache_path.exists() and base_cached and not force:
        print(f"[PRELOAD] ControlNet Depth déjà en cache (skip)")
        return

    if cache_path.exists() and not base_cached:
        print(f"[PRELOAD] ControlNet quantifié présent, mais poids HF manquants")
    print(f"[PRELOAD] Téléchargement/validation ControlNet Depth SDXL (~640MB max)...")
    _update_status("Téléchargement/validation ControlNet Depth...")

    try:
        from diffusers import ControlNetModel

        # local_files_only d'abord (skip réseau si déjà en cache), fallback download
        try:
            controlnet = ControlNetModel.from_pretrained(
                CONTROLNET_DEPTH_REPO, torch_dtype=torch.float16, local_files_only=True,
            )
        except OSError:
            _update_status("Téléchargement ControlNet Depth...")
            controlnet = ControlNetModel.from_pretrained(
                CONTROLNET_DEPTH_REPO, torch_dtype=torch.float16,
            )

        # Quantifier
        _update_status("Quantification ControlNet Depth...")
        from optimum.quanto import quantize, freeze, qint8
        quantize(controlnet, weights=qint8)
        freeze(controlnet)

        # Sauvegarder
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(controlnet.state_dict(), cache_path)
        print(f"[PRELOAD] Sauvegardé: {cache_path}")

        del controlnet
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

    except Exception as e:
        print(f"[PRELOAD] Erreur ControlNet: {e}")


def _preload_depth_estimator(force: bool = False):
    """Pré-charge le Depth Estimator."""
    print(f"[PRELOAD] Vérification Depth Anything V2 Small (~100MB)...")

    try:
        from transformers import AutoModelForDepthEstimation, AutoImageProcessor

        model_id = "depth-anything/Depth-Anything-V2-Small-hf"

        # local_files_only d'abord (skip réseau si déjà en cache)
        try:
            AutoImageProcessor.from_pretrained(model_id, local_files_only=True)
            AutoModelForDepthEstimation.from_pretrained(model_id, torch_dtype=torch.float16, local_files_only=True, low_cpu_mem_usage=False)
        except OSError:
            AutoImageProcessor.from_pretrained(model_id)
            AutoModelForDepthEstimation.from_pretrained(model_id, torch_dtype=torch.float16, low_cpu_mem_usage=False)

        print(f"[PRELOAD] Depth Anything V2 prêt")

    except Exception as e:
        print(f"[PRELOAD] Erreur Depth Estimator: {e}")


def _preload_segformer(force: bool = False):
    """Pré-charge les modèles SegFormer."""
    print(f"[PRELOAD] Vérification SegFormer B2 clothes (~300MB)...")

    try:
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

        _seg_repo = "mattmdjaga/segformer_b2_clothes"
        try:
            SegformerImageProcessor.from_pretrained(_seg_repo, local_files_only=True)
            SegformerForSemanticSegmentation.from_pretrained(_seg_repo, local_files_only=True, low_cpu_mem_usage=False)
        except OSError:
            SegformerImageProcessor.from_pretrained(_seg_repo)
            SegformerForSemanticSegmentation.from_pretrained(_seg_repo, low_cpu_mem_usage=False)

        print(f"[PRELOAD] SegFormer prêt")

    except Exception as e:
        print(f"[PRELOAD] Erreur SegFormer: {e}")


def _preload_florence(force: bool = False):
    """Pré-charge Florence-2."""
    print(f"[PRELOAD] Vérification Florence-2 Base (~500MB)...")

    try:
        from transformers import AutoProcessor, AutoModelForCausalLM

        model_id = "microsoft/Florence-2-base"

        try:
            AutoProcessor.from_pretrained(model_id, trust_remote_code=True, local_files_only=True)
        except OSError:
            AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

        print(f"[PRELOAD] Florence-2 prêt")

    except Exception as e:
        print(f"[PRELOAD] Erreur Florence-2: {e}")


def _cleanup_vram():
    """Nettoie la VRAM après le préchargement."""
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    print(f"[PRELOAD] VRAM nettoyée")


def run_preload_async(force: bool = False):
    """Lance le préchargement en arrière-plan."""
    def _run():
        for _ in preload_all(force):
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
