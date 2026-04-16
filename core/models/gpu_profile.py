"""
GPU Profile Loader — loads the matching gpu_profiles/*.json based on detected VRAM.

Chaque profil définit la stratégie par type de modèle (sdxl, flux_fill, etc.):
  - quantization: "none" / "int8" / "int4"
  - offload_strategy: "none" (GPU direct) / "model_cpu_offload"
"""
import json
import os

from core.models.registry import VRAM_GB

_PROFILES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'gpu_profiles')
_active_profile = None


def get_active_profile():
    """Load and cache the GPU profile matching the detected VRAM."""
    global _active_profile
    if _active_profile is not None:
        return _active_profile

    for fname in sorted(os.listdir(_PROFILES_DIR)):
        if not fname.endswith('.json'):
            continue
        path = os.path.join(_PROFILES_DIR, fname)
        with open(path, encoding='utf-8') as f:
            profile = json.load(f)
        vmin, vmax = profile.get('_vram_range', [0, 0])
        if vmin <= VRAM_GB <= vmax:
            _active_profile = profile
            print(f"[GPU_PROFILE] Loaded {fname} for {VRAM_GB:.1f}GB VRAM")
            return profile

    # Fallback to 8gb
    fallback = os.path.join(_PROFILES_DIR, '8gb.json')
    with open(fallback, encoding='utf-8') as f:
        _active_profile = json.load(f)
    print(f"[GPU_PROFILE] Fallback to 8gb.json for {VRAM_GB:.1f}GB VRAM")
    return _active_profile


def get_config(section: str) -> dict:
    """Retourne la config d'une section du profil GPU actif.

    Sections: 'general', 'sdxl', 'flux_fill', 'flux_kontext', 'video', 'image', 'ollama'
    """
    return get_active_profile().get(section, {})


def should_quantize(section: str, model_quant: str) -> tuple:
    """Détermine si on doit quantifier, basé sur le profil ET la variante du modèle.

    Args:
        section: 'sdxl', 'flux_fill', etc.
        model_quant: override par variante (MODEL_QUANT), ex: "none" pour Normal

    Returns:
        (do_quantize: bool, quant_type: str)
        quant_type est "int4", "int8", ou "none"
    """
    # La variante du modèle peut forcer "none" (ex: epiCRealism Normal)
    if model_quant == "none":
        return False, "none"
    cfg = get_config(section)
    profile_quant = cfg.get('quantization', 'int8')
    if profile_quant == "none":
        return False, "none"
    # Le profil dit de quantifier — utiliser le type du profil ou celui du modèle
    # model_quant peut demander "int4" même si le profil dit "int8" → prendre le modèle
    quant = model_quant if model_quant in ("int4", "int8") else profile_quant
    return True, quant


def get_offload_strategy(section: str) -> str:
    """Retourne la stratégie d'offload pour une section.

    Returns: "none", "model_cpu_offload", "group_offload", etc.
    """
    cfg = get_config(section)
    return cfg.get('offload_strategy', 'model_cpu_offload')
