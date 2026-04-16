"""
Turbo-VAED — décodeur VAE distillé rapide pour LTX-Video 2B.
2.9x plus rapide que le VAE standard, 97% de la qualité originale.
169MB vs ~1GB (VAE standard) vs 23MB (TAEHV).

Source: https://github.com/hustvl/Turbo-VAED
Poids: https://huggingface.co/hustvl/Turbo-VAED
"""
import sys
import time
import json
from pathlib import Path

_turbo_vaed_ltx_instance = None
_turbo_vaed_ltx_device = None

TURBO_VAED_DIR = Path(__file__).parent.parent.parent / "ext_weights" / "turbo_vaed"
WEIGHTS_FILE = "Turbo-VAED-LTX.pth"
CONFIG_FILE = "Turbo-VAED-LTX.json"


GITHUB_RAW_BASE = "https://raw.githubusercontent.com/hustvl/Turbo-VAED/main"
MODULE_FILE = "autoencoder_kl_turbo_vaed.py"


def _ensure_turbo_vaed_files():
    """Télécharge tous les fichiers Turbo-VAED-LTX si absents (poids HF + code/config GitHub)."""
    TURBO_VAED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Poids (169MB depuis HuggingFace)
    weights_path = TURBO_VAED_DIR / WEIGHTS_FILE
    if not weights_path.exists():
        from huggingface_hub import hf_hub_download
        import shutil
        print("[Turbo-VAED] Téléchargement des poids (169 MB)...")
        downloaded = hf_hub_download(
            repo_id="hustvl/Turbo-VAED",
            filename=WEIGHTS_FILE,
        )
        shutil.copy2(downloaded, str(weights_path))
        print(f"[Turbo-VAED] Poids téléchargés ({weights_path.stat().st_size / 1e6:.1f} MB)")

    # 2. Config JSON (depuis GitHub)
    config_path = TURBO_VAED_DIR / CONFIG_FILE
    if not config_path.exists():
        import urllib.request
        url = f"{GITHUB_RAW_BASE}/configs/{CONFIG_FILE}"
        print(f"[Turbo-VAED] Téléchargement config {CONFIG_FILE}...")
        urllib.request.urlretrieve(url, str(config_path))
        print(f"[Turbo-VAED] Config téléchargée")

    # 3. Module Python (depuis GitHub diffusers_vae fork)
    module_path = TURBO_VAED_DIR / MODULE_FILE
    if not module_path.exists():
        import urllib.request
        url = f"{GITHUB_RAW_BASE}/diffusers_vae/src/diffusers/models/autoencoders/{MODULE_FILE}"
        print(f"[Turbo-VAED] Téléchargement module {MODULE_FILE}...")
        urllib.request.urlretrieve(url, str(module_path))
        print(f"[Turbo-VAED] Module téléchargé")

    # Patcher les imports relatifs → absolus
    # from ...X → from diffusers.X  (3 dots = remonte à diffusers/)
    # from ..X  → from diffusers.models.X  (2 dots = remonte à models/)
    # from .X   → from diffusers.models.autoencoders.X  (1 dot = même dossier)
    import re
    code = module_path.read_text(encoding='utf-8')
    if 'from .' in code:
        code = re.sub(r'from \.\.\.(\w)', r'from diffusers.\1', code)
        code = re.sub(r'from \.\.(\w)', r'from diffusers.models.\1', code)
        code = re.sub(r'from \.(\w)', r'from diffusers.models.autoencoders.\1', code)
        module_path.write_text(code, encoding='utf-8')
        print(f"[Turbo-VAED] Imports relatifs patchés → absolus")


def _get_turbo_vaed_ltx(device="cuda"):
    """Charge et cache le modèle Turbo-VAED LTX singleton."""
    global _turbo_vaed_ltx_instance, _turbo_vaed_ltx_device
    import torch

    if _turbo_vaed_ltx_instance is not None and _turbo_vaed_ltx_device == device:
        return _turbo_vaed_ltx_instance

    _ensure_turbo_vaed_files()

    # Import la classe depuis ext_weights/turbo_vaed/
    turbo_vaed_path = str(TURBO_VAED_DIR)
    if turbo_vaed_path not in sys.path:
        sys.path.insert(0, turbo_vaed_path)
    from autoencoder_kl_turbo_vaed import AutoencoderKLTurboVAED

    # Config sans projection heads (inference only, pas besoin de timm)
    config_path = TURBO_VAED_DIR / CONFIG_FILE
    with open(config_path, 'r') as f:
        config = json.load(f)
    # Désactiver les projection heads (seulement pour le training/distillation)
    config["aligned_feature_projection_mode"] = None
    config["aligned_feature_projection_dim"] = None
    config["aligned_blks_indices"] = None

    weights_path = TURBO_VAED_DIR / WEIGHTS_FILE

    print(f"[Turbo-VAED] Chargement du décodeur LTX sur {device}...")
    t0 = time.time()

    model = AutoencoderKLTurboVAED.from_config(config)
    checkpoint = torch.load(str(weights_path), map_location="cpu", weights_only=True)
    model.decoder.load_state_dict(checkpoint, strict=False)
    model = model.to(device, dtype=torch.float16)
    model.eval()

    elapsed = time.time() - t0
    print(f"[Turbo-VAED] Décodeur LTX prêt ({elapsed:.1f}s, ~0.5GB VRAM)")

    _turbo_vaed_ltx_instance = model
    _turbo_vaed_ltx_device = device
    return model


def turbo_vaed_decode_ltx(latents, vae, skip_denorm=False):
    """
    Décode les latents LTX-Video 2B avec Turbo-VAED (décodeur distillé).

    Args:
        latents: tensor BCTHW (normalized, from pipeline output_type="latent")
        vae: le modèle VAE original (AutoencoderKLLTXVideo) — pour latents_mean/std
        skip_denorm: Si True, passe les latents tels quels (Turbo-VAED peut attendre des latents raw)

    Returns:
        list[PIL.Image] — frames décodées
    """
    import torch
    from PIL import Image

    t0 = time.time()

    # 1. Dé-normaliser les latents selon le type de VAE
    #    - LTX-Video: latents / scaling_factor + shift_factor
    #    - Wan/Hunyuan: latents * latents_std / scaling_factor + latents_mean
    if not skip_denorm:
        scaling_factor = getattr(vae.config, 'scaling_factor', 1.0)
        shift_factor = getattr(vae.config, 'shift_factor', None)
        latents_mean = getattr(vae, 'latents_mean', None)
        latents_std = getattr(vae, 'latents_std', None)

        if shift_factor is not None:
            # LTX-Video: utilise shift_factor
            latents = latents / scaling_factor + shift_factor
            print(f"[Turbo-VAED] Denorm LTX: /scaling({scaling_factor}) +shift({shift_factor})")
        elif latents_mean is not None and latents_std is not None:
            # Wan/Hunyuan: utilise mean/std
            latents_mean = latents_mean.view(1, -1, 1, 1, 1).to(latents.device, latents.dtype)
            latents_std = latents_std.view(1, -1, 1, 1, 1).to(latents.device, latents.dtype)
            latents = latents * latents_std / scaling_factor + latents_mean
            print(f"[Turbo-VAED] Denorm Wan: *std /scaling({scaling_factor}) +mean")
        else:
            if scaling_factor != 1.0:
                latents = latents / scaling_factor
                print(f"[Turbo-VAED] Denorm fallback: /scaling({scaling_factor})")
    else:
        print("[Turbo-VAED] Skip denorm (raw latents)")

    # 2. Charger Turbo-VAED LTX
    device = "cuda" if torch.cuda.is_available() else "cpu"
    turbo_vaed = _get_turbo_vaed_ltx(device)

    # 3. Decode — latents sont déjà en BCTHW, pas de transpose nécessaire
    latents = latents.to(device, torch.float16)
    n_latent_frames = latents.shape[2]
    print(f"[Turbo-VAED] Décodage de {n_latent_frames} latent frames...")

    with torch.no_grad():
        decoded = turbo_vaed.decode(latents, return_dict=False)[0]
    # decoded: [B, 3, T, H, W], range [-1, 1]

    # 4. Convertir tensor → list[PIL.Image]
    decoded = torch.clamp(decoded, -1.0, 1.0)
    frames = []
    for i in range(decoded.shape[2]):  # itérer sur T
        frame = decoded[0, :, i].permute(1, 2, 0).cpu().float()  # CHW → HWC
        frame = ((frame + 1.0) * 127.5).clamp(0, 255).to(torch.uint8).numpy()
        frames.append(Image.fromarray(frame))

    elapsed = time.time() - t0
    print(f"[Turbo-VAED] Décodage terminé: {len(frames)} frames en {elapsed:.1f}s")
    return frames


def unload_turbo_vaed():
    """Libère le modèle Turbo-VAED de la mémoire."""
    global _turbo_vaed_ltx_instance, _turbo_vaed_ltx_device
    if _turbo_vaed_ltx_instance is not None:
        del _turbo_vaed_ltx_instance
        _turbo_vaed_ltx_instance = None
        _turbo_vaed_ltx_device = None
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[Turbo-VAED] Décodeur LTX déchargé")


def is_turbo_vaed_available():
    """Vérifie si Turbo-VAED LTX peut être utilisé."""
    weights_path = TURBO_VAED_DIR / WEIGHTS_FILE
    module_path = TURBO_VAED_DIR / "autoencoder_kl_turbo_vaed.py"
    config_path = TURBO_VAED_DIR / CONFIG_FILE
    return weights_path.exists() and module_path.exists() and config_path.exists()
