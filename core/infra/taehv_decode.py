"""
TAEHV (Tiny AutoEncoder for Video) -- decodage rapide des latents video.
Remplace le VAE complet (~15-20GB intermediaires) par un mini-VAE (<0.5GB).
Decodage en quelques secondes au lieu de 10+ minutes sur GPU limite.

Modeles supportes:
- Wan 2.2 5B / FastWan -> taew2_2.pth (48 channels, patch_size=2)
- LTX-Video 2B (base + distille 0.9.8) -> taeltx_2.pth (128 channels, patch_size=4)
"""
import sys
import time
from pathlib import Path

# Singletons TAEHV (un par modele, charge une seule fois)
_taehv_wan_instance = None
_taehv_wan_device = None
_taehv_ltx_instance = None
_taehv_ltx_device = None

TAEHV_DIR = Path(__file__).parent.parent.parent / "ext_weights" / "taehv"

TAEHV_URLS = {
    "taew2_2.pth": "https://github.com/madebyollin/taehv/raw/refs/heads/main/taew2_2.pth",
    "taeltx_2.pth": "https://github.com/madebyollin/taehv/raw/refs/heads/main/taeltx_2.pth",
    "taehv.py": "https://github.com/madebyollin/taehv/raw/refs/heads/main/taehv.py",
}


def _ensure_taehv_files(weights_filename="taew2_2.pth", label="TAEHV"):
    """Download taehv.py module and model weights if absent.

    Args:
        weights_filename: name of the weights file (key in TAEHV_URLS)
        label: log prefix for print messages
    """
    TAEHV_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure taehv.py module is present
    module_path = TAEHV_DIR / "taehv.py"
    if not module_path.exists():
        import urllib.request
        print(f"[{label}] Telechargement du module taehv.py...")
        urllib.request.urlretrieve(TAEHV_URLS["taehv.py"], str(module_path))

    weights_path = TAEHV_DIR / weights_filename
    if not weights_path.exists():
        import urllib.request
        print(f"[{label}] Telechargement du mini-VAE ({weights_filename})...")
        urllib.request.urlretrieve(TAEHV_URLS[weights_filename], str(weights_path))
        print(f"[{label}] Poids telecharges ({weights_path.stat().st_size / 1e6:.1f} MB)")


def _import_taehv_class():
    """Import TAEHV class from ext_weights/taehv/."""
    taehv_module_path = str(TAEHV_DIR)
    if taehv_module_path not in sys.path:
        sys.path.insert(0, taehv_module_path)
    from taehv import TAEHV
    return TAEHV


def _decode_latents(latents, taehv_model, label="TAEHV"):
    """Decode latents with a TAEHV model and convert to PIL frames.

    Args:
        latents: tensor NTCHW on device, float16
        taehv_model: loaded TAEHV model instance
        label: log prefix

    Returns:
        list[PIL.Image] -- decoded frames
    """
    import torch
    import numpy as np
    from PIL import Image

    n_frames = latents.shape[1]
    print(f"[{label}] Decodage de {n_frames} frames...")

    with torch.no_grad():
        decoded = taehv_model.decode_video(latents, parallel=False, show_progress_bar=True)
    # decoded: NTCHW, [0, 1]

    frames = []
    for i in range(decoded.shape[1]):
        frame = decoded[0, i].permute(1, 2, 0).cpu().float().numpy()
        frame = (frame * 255).clip(0, 255).astype(np.uint8)
        frames.append(Image.fromarray(frame))

    return frames


# ============================================================
# Wan 2.2 5B / FastWan
# ============================================================

def _get_taehv_wan(device="cuda"):
    """Charge et cache le modele TAEHV Wan singleton."""
    global _taehv_wan_instance, _taehv_wan_device
    import torch

    if _taehv_wan_instance is not None and _taehv_wan_device == device:
        return _taehv_wan_instance

    _ensure_taehv_files("taew2_2.pth", "TAEHV")
    TAEHV = _import_taehv_class()

    weights_path = str(TAEHV_DIR / "taew2_2.pth")
    print(f"[TAEHV] Chargement du mini-VAE Wan sur {device}...")
    t0 = time.time()
    _taehv_wan_instance = TAEHV(checkpoint_path=weights_path).to(device, torch.float16)
    _taehv_wan_instance.eval()
    print(f"[TAEHV] Mini-VAE Wan pret ({time.time() - t0:.1f}s, <0.5GB VRAM)")

    _taehv_wan_device = device
    return _taehv_wan_instance


def taehv_decode_wan22(latents, vae_config):
    """
    Decode les latents Wan 2.2 5B avec TAEHV (mini-VAE).

    Args:
        latents: tensor NCTHW (normalized, from pipeline output_type="latent")
        vae_config: config du VAE original (pour latents_mean/std)

    Returns:
        list[PIL.Image] -- frames decodees
    """
    import torch

    t0 = time.time()

    # 1. De-normaliser les latents
    z_dim = getattr(vae_config, 'z_dim', len(vae_config.latents_mean))
    latents_mean = torch.tensor(vae_config.latents_mean).view(1, z_dim, 1, 1, 1).to(latents.device, latents.dtype)
    latents_std = torch.tensor(vae_config.latents_std).view(1, z_dim, 1, 1, 1).to(latents.device, latents.dtype)
    latents = latents * latents_std + latents_mean

    # 2. Charger TAEHV
    device = "cuda" if torch.cuda.is_available() else "cpu"
    taehv = _get_taehv_wan(device)

    # 3. Transpose NCTHW -> NTCHW (format TAEHV) et decode
    latents_ntchw = latents.to(device, torch.float16).transpose(1, 2)

    frames = _decode_latents(latents_ntchw, taehv, "TAEHV")

    elapsed = time.time() - t0
    print(f"[TAEHV] Decodage termine: {len(frames)} frames en {elapsed:.1f}s")
    return frames


# ============================================================
# LTX-Video 2B (base + distille 0.9.8)
# ============================================================

def _get_taehv_ltx(device="cuda"):
    """Charge et cache le modele TAEHV LTX singleton."""
    global _taehv_ltx_instance, _taehv_ltx_device
    import torch

    if _taehv_ltx_instance is not None and _taehv_ltx_device == device:
        return _taehv_ltx_instance

    _ensure_taehv_files("taeltx_2.pth", "TAEHV-LTX")
    TAEHV = _import_taehv_class()

    weights_path = str(TAEHV_DIR / "taeltx_2.pth")
    print(f"[TAEHV-LTX] Chargement du mini-VAE LTX sur {device}...")
    t0 = time.time()
    _taehv_ltx_instance = TAEHV(checkpoint_path=weights_path).to(device, torch.float16)
    _taehv_ltx_instance.eval()
    print(f"[TAEHV-LTX] Mini-VAE LTX pret ({time.time() - t0:.1f}s, <0.5GB VRAM)")

    _taehv_ltx_device = device
    return _taehv_ltx_instance


def taehv_decode_ltx(latents, vae_config):
    """
    Decode les latents LTX-Video 2B avec TAEHV (mini-VAE).

    Args:
        latents: tensor BCTHW (normalized, from pipeline output_type="latent")
        vae_config: config du VAE original (pour scaling_factor/shift_factor)

    Returns:
        list[PIL.Image] -- frames decodees
    """
    import torch

    t0 = time.time()

    # 1. De-normaliser les latents
    scaling_factor = getattr(vae_config, 'scaling_factor', 1.0)
    shift_factor = getattr(vae_config, 'shift_factor', 0.0)
    if scaling_factor is not None and scaling_factor != 1.0:
        latents = latents / scaling_factor
        print(f"[TAEHV-LTX] De-normalisation: scaling_factor={scaling_factor}")
    if shift_factor is not None and shift_factor != 0.0:
        latents = latents + shift_factor
        print(f"[TAEHV-LTX] De-normalisation: shift_factor={shift_factor}")

    # 2. Charger TAEHV LTX
    device = "cuda" if torch.cuda.is_available() else "cpu"
    taehv = _get_taehv_ltx(device)

    # 3. Transpose BCTHW -> BTCHW (format TAEHV) et decode
    latents_ntchw = latents.to(device, torch.float16).transpose(1, 2)

    frames = _decode_latents(latents_ntchw, taehv, "TAEHV-LTX")

    elapsed = time.time() - t0
    print(f"[TAEHV-LTX] Decodage termine: {len(frames)} frames en {elapsed:.1f}s")
    return frames


# ============================================================
# Gestion memoire
# ============================================================

def unload_taehv():
    """Libere tous les modeles TAEHV de la memoire."""
    global _taehv_wan_instance, _taehv_wan_device, _taehv_ltx_instance, _taehv_ltx_device
    unloaded = []

    if _taehv_wan_instance is not None:
        del _taehv_wan_instance
        _taehv_wan_instance = None
        _taehv_wan_device = None
        unloaded.append("Wan")

    if _taehv_ltx_instance is not None:
        del _taehv_ltx_instance
        _taehv_ltx_instance = None
        _taehv_ltx_device = None
        unloaded.append("LTX")

    if unloaded:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"[TAEHV] Mini-VAE decharge ({', '.join(unloaded)})")


def is_taehv_available():
    """Verifie si TAEHV Wan peut etre utilise."""
    weights_path = TAEHV_DIR / "taew2_2.pth"
    module_path = TAEHV_DIR / "taehv.py"
    return weights_path.exists() and module_path.exists()


def is_taehv_ltx_available():
    """Verifie si TAEHV LTX peut etre utilise."""
    weights_path = TAEHV_DIR / "taeltx_2.pth"
    module_path = TAEHV_DIR / "taehv.py"
    return weights_path.exists() and module_path.exists()
