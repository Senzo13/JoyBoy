"""
Doctor report for first-run onboarding and public-ready setup checks.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

from core.infra.local_config import LOCAL_DIR, get_local_config_overview, get_provider_status
from core.infra.packs import get_feature_exposure_map, get_pack_index


def _status_from_booleans(ok: bool, warning: bool = False) -> str:
    if ok:
        return "ok"
    if warning:
        return "warning"
    return "error"


def _check_runtime() -> dict:
    py_ok = sys.version_info >= (3, 10)
    return {
        "key": "runtime",
        "label": "Python runtime",
        "status": _status_from_booleans(py_ok),
        "detail": f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} on {platform.system()}",
        "action": None if py_ok else "Utiliser Python 3.10+ avant de lancer JoyBoy.",
    }


def _check_gpu() -> dict:
    try:
        import torch
        from core.models.gpu_profile import get_active_profile

        profile = get_active_profile()
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
            return {
                "key": "gpu",
                "label": "GPU acceleration",
                "status": "ok",
                "detail": f"{gpu_name} · {vram_gb} GB VRAM · profil {profile.get('profile_name', 'auto')}",
                "action": None,
            }
        return {
            "key": "gpu",
            "label": "GPU acceleration",
            "status": "warning",
            "detail": "CUDA indisponible — JoyBoy peut démarrer, mais les workflows image/vidéo seront limités.",
            "action": "Installer les drivers CUDA/NVIDIA ou utiliser une machine GPU pour les workflows lourds.",
        }
    except Exception as exc:
        return {
            "key": "gpu",
            "label": "GPU acceleration",
            "status": "warning",
            "detail": f"Impossible de lire le profil GPU: {exc}",
            "action": "Vérifier PyTorch/CUDA si tu veux des workflows image/vidéo accélérés.",
        }


def _check_ollama() -> dict:
    try:
        from core import ollama_service

        installed = bool(ollama_service.is_ollama_installed())
        running = bool(ollama_service.is_ollama_running()) if installed else False
        if installed and running:
            detail = "Ollama installé et actif."
            status = "ok"
            action = None
        elif installed:
            detail = "Ollama installé mais non démarré."
            status = "warning"
            action = "Lancer Ollama ou laisser JoyBoy le démarrer au besoin."
        else:
            detail = "Ollama non détecté."
            status = "warning"
            action = "Installer Ollama pour activer le chat local et le routing assisté."
        return {
            "key": "ollama",
            "label": "Ollama",
            "status": status,
            "detail": detail,
            "action": action,
        }
    except Exception as exc:
        return {
            "key": "ollama",
            "label": "Ollama",
            "status": "warning",
            "detail": f"Vérification Ollama indisponible: {exc}",
            "action": "Vérifier que le service Ollama est installé et accessible.",
        }


def _check_providers() -> dict:
    providers = get_provider_status()
    configured = [provider["label"] for provider in providers if provider.get("configured")]
    if configured:
        return {
            "key": "providers",
            "label": "Providers",
            "status": "ok",
            "detail": "Configurés: " + ", ".join(configured),
            "action": None,
        }
    return {
        "key": "providers",
        "label": "Providers",
        "status": "warning",
        "detail": "Aucun provider configuré. Les téléchargements gated/privés seront limités.",
        "action": "Ajoute au moins une clé Hugging Face ou CivitAI dans Paramètres > Modèles.",
    }


def _check_storage() -> dict:
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        output_dir = Path(__file__).resolve().parents[2] / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(str(Path.cwd()))
        free_gb = round(disk.free / (1024 ** 3), 1)
        writable = os.access(str(LOCAL_DIR), os.W_OK) and os.access(str(output_dir), os.W_OK)
        status = "ok" if writable and free_gb >= 20 else "warning"
        action = None
        if not writable:
            action = "Vérifier les permissions d’écriture sur ~/.joyboy et le dossier output/."
        elif free_gb < 20:
            action = "Prévoir davantage d’espace disque pour les modèles et sorties."
        return {
            "key": "storage",
            "label": "Storage",
            "status": status,
            "detail": f"{free_gb} GB libres · config locale {get_local_config_overview()['active_source']}",
            "action": action,
        }
    except Exception as exc:
        return {
            "key": "storage",
            "label": "Storage",
            "status": "warning",
            "detail": f"Vérification stockage indisponible: {exc}",
            "action": "Vérifier les permissions disque et les dossiers de travail.",
        }


def _check_models() -> dict:
    try:
        from core.models.registry import get_all_models_status
        from core import ollama_service

        image_models = get_all_models_status()
        installed_image = [model["name"] for model in image_models.values() if model.get("downloaded")]
        ollama_models = ollama_service.get_installed_models(quiet=True)
        installed_text = [model.get("name", "") for model in ollama_models if model.get("name")]

        if installed_image and installed_text:
            detail = f"{len(installed_text)} modèle(s) texte · {len(installed_image)} modèle(s) image en cache"
            status = "ok"
            action = None
        elif installed_text or installed_image:
            detail = f"Texte: {len(installed_text)} · Image: {len(installed_image)}"
            status = "warning"
            action = "Compléter le socle recommandé depuis l’onboarding ou l’onglet Modèles."
        else:
            detail = "Aucun modèle de base détecté."
            status = "warning"
            action = "Installer au moins un modèle texte et un modèle image pour un premier lancement confortable."
        return {
            "key": "models",
            "label": "Models",
            "status": status,
            "detail": detail,
            "action": action,
        }
    except Exception as exc:
        return {
            "key": "models",
            "label": "Models",
            "status": "warning",
            "detail": f"Vérification modèles indisponible: {exc}",
            "action": "Vérifier les providers et les modèles installés depuis l’onglet Modèles.",
        }


def _check_packs() -> dict:
    exposure = get_feature_exposure_map()
    packs = get_pack_index()
    valid_count = len([pack for pack in packs["packs"] if pack.get("valid")])
    adult = exposure.get("adult", {})

    if adult.get("runtime_available"):
        detail = adult.get("reason") or f"{valid_count} pack(s) local(aux) valide(s)"
        return {
            "key": "packs",
            "label": "Local packs",
            "status": "ok",
            "detail": detail,
            "action": None,
        }

    return {
        "key": "packs",
        "label": "Local packs",
        "status": "warning",
        "detail": adult.get("reason") or f"{valid_count} pack(s) valide(s), aucun actif pour les surfaces verrouillées.",
        "action": "Importer un pack local ou activer un pack déjà installé si tu veux déverrouiller les surfaces optionnelles.",
    }


def run_doctor() -> dict:
    checks = [
        _check_runtime(),
        _check_gpu(),
        _check_ollama(),
        _check_providers(),
        _check_storage(),
        _check_models(),
        _check_packs(),
    ]
    errors = [check for check in checks if check["status"] == "error"]
    warnings = [check for check in checks if check["status"] == "warning"]

    overall = "ok"
    if errors:
        overall = "error"
    elif warnings:
        overall = "warning"

    if overall == "ok":
        summary = "JoyBoy est prêt pour un usage local complet."
    elif overall == "warning":
        summary = "JoyBoy peut démarrer, mais quelques points méritent d’être corrigés pour un setup public propre."
    else:
        summary = "JoyBoy a des prérequis bloquants à corriger avant un setup fiable."

    return {
        "success": True,
        "status": overall,
        "ready": overall != "error",
        "summary": summary,
        "checks": checks,
        "feature_exposure": get_feature_exposure_map(),
        "packs": get_pack_index()["packs"],
    }
