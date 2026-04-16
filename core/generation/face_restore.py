"""
Face restoration — restaure les visages dégradés dans les frames vidéo.
Supporte GFPGAN (meilleur pour les yeux IA) et CodeFormer (meilleur pour dégradations fortes).
"""
# Patch compatibilite: basicsr importe torchvision.transforms.functional_tensor
# qui a ete supprime dans torchvision recent (fusionne dans functional)
from utils.compat import _patch_torchvision_compatibility
_patch_torchvision_compatibility()

import time
from pathlib import Path

# ========== SINGLETONS ==========
_codeformer_net = None
_gfpgan_restorer = None
_gfpgan_device = None
_codeformer_device = None

WEIGHTS_DIR = Path(__file__).parent.parent.parent / "ext_weights"
CODEFORMER_URL = "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth"
GFPGAN_URL = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth"


# ========== GFPGAN ==========

def _ensure_gfpgan():
    """Installe gfpgan si absent."""
    try:
        import gfpgan
    except ImportError:
        import subprocess, sys
        print("[FACE] Installation de gfpgan...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gfpgan", "-q"])


def _download_gfpgan_weights():
    """Télécharge les poids GFPGAN v1.4 si absents."""
    gfpgan_dir = WEIGHTS_DIR / "gfpgan"
    gfpgan_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = gfpgan_dir / "GFPGANv1.4.pth"
    if not ckpt_path.exists():
        import urllib.request
        print(f"[FACE] Téléchargement GFPGAN v1.4 (~350 MB)...")
        urllib.request.urlretrieve(GFPGAN_URL, str(ckpt_path))
        print(f"[FACE] Poids téléchargés ({ckpt_path.stat().st_size / 1e6:.0f} MB)")
    return str(ckpt_path)


def _get_gfpgan(device="cuda"):
    """Charge et cache GFPGAN singleton."""
    global _gfpgan_restorer, _gfpgan_device
    import torch

    if _gfpgan_restorer is not None and _gfpgan_device == device:
        return _gfpgan_restorer

    _ensure_gfpgan()
    ckpt_path = _download_gfpgan_weights()

    from gfpgan import GFPGANer

    print(f"[FACE] Chargement GFPGAN v1.4 sur {device}...")
    t0 = time.time()

    _gfpgan_restorer = GFPGANer(
        model_path=ckpt_path,
        upscale=1,
        arch='clean',
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )

    _gfpgan_device = device
    print(f"[FACE] GFPGAN prêt ({time.time() - t0:.1f}s)")
    return _gfpgan_restorer


def restore_face_gfpgan(frame_pil, weight=0.5):
    """
    Restaure les visages avec GFPGAN.

    Args:
        frame_pil: PIL.Image (RGB)
        weight: 0.0=max restauration, 0.5=équilibré, 1.0=original

    Returns:
        PIL.Image restaurée
    """
    import torch
    import cv2
    import numpy as np
    from PIL import Image

    device = "cuda" if torch.cuda.is_available() else "cpu"
    restorer = _get_gfpgan(device)

    img_np = np.array(frame_pil)
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    with torch.no_grad():
        _, _, restored_img = restorer.enhance(
            img_bgr,
            has_aligned=False,
            only_center_face=False,
            paste_back=True,
            weight=weight,
        )

    if restored_img is None:
        return frame_pil

    restored_rgb = cv2.cvtColor(restored_img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(restored_rgb)


# ========== CODEFORMER ==========

def _ensure_codeformer_deps():
    """Installe basicsr et facexlib si absents."""
    try:
        import basicsr
        import facexlib
    except ImportError:
        import subprocess, sys
        print("[FACE] Installation des dépendances (basicsr, facexlib)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "basicsr", "facexlib", "-q"])


def _download_codeformer_weights():
    """Télécharge les poids CodeFormer si absents."""
    cf_dir = WEIGHTS_DIR / "codeformer"
    cf_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = cf_dir / "codeformer.pth"
    if not ckpt_path.exists():
        import urllib.request
        print(f"[FACE] Téléchargement CodeFormer (~360 MB)...")
        urllib.request.urlretrieve(CODEFORMER_URL, str(ckpt_path))
        print(f"[FACE] Poids téléchargés ({ckpt_path.stat().st_size / 1e6:.0f} MB)")
    return str(ckpt_path)


def _get_codeformer(device="cuda"):
    """Charge et cache CodeFormer singleton."""
    global _codeformer_net, _codeformer_device
    import torch

    if _codeformer_net is not None and _codeformer_device == device:
        return _codeformer_net

    _ensure_codeformer_deps()
    ckpt_path = _download_codeformer_weights()

    from basicsr.utils.registry import ARCH_REGISTRY

    print(f"[FACE] Chargement CodeFormer sur {device}...")
    t0 = time.time()

    # basicsr récent renomme "CodeFormer" → "CodeFormer_basicsr"
    try:
        arch_cls = ARCH_REGISTRY.get("CodeFormer")
    except (KeyError, ValueError):
        arch_cls = ARCH_REGISTRY.get("CodeFormer_basicsr")

    _codeformer_net = arch_cls(
        dim_embd=512,
        codebook_size=1024,
        n_head=8,
        n_layers=9,
        connect_list=["32", "64", "128", "256"],
    ).to(device)

    checkpoint = torch.load(ckpt_path, map_location=device, weights_only=True)
    if "params_ema" in checkpoint:
        _codeformer_net.load_state_dict(checkpoint["params_ema"])
    elif "params" in checkpoint:
        _codeformer_net.load_state_dict(checkpoint["params"])
    else:
        _codeformer_net.load_state_dict(checkpoint)

    _codeformer_net.eval()
    _codeformer_device = device
    print(f"[FACE] CodeFormer prêt ({time.time() - t0:.1f}s)")
    return _codeformer_net


def restore_face_codeformer(frame_pil, fidelity_weight=0.7):
    """
    Restaure les visages avec CodeFormer.

    Args:
        frame_pil: PIL.Image (RGB)
        fidelity_weight: 0.0=max restauration, 0.7=subtil, 1.0=original

    Returns:
        PIL.Image restaurée
    """
    import torch
    import cv2
    import numpy as np
    from PIL import Image
    from torchvision.transforms.functional import normalize
    from basicsr.utils import img2tensor, tensor2img
    from facexlib.utils.face_restoration_helper import FaceRestoreHelper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = _get_codeformer(device)

    img_np = np.array(frame_pil)
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

    face_helper = FaceRestoreHelper(
        upscale_factor=1,
        face_size=512,
        crop_ratio=(1, 1),
        det_model="retinaface_resnet50",
        save_ext="png",
        use_parse=True,
        device=device,
    )

    face_helper.read_image(img_bgr)
    num_faces = face_helper.get_face_landmarks_5(
        only_center_face=False, resize=640, eye_dist_threshold=5
    )

    if num_faces == 0:
        return frame_pil

    face_helper.align_warp_face()

    for cropped_face in face_helper.cropped_faces:
        cropped_face_t = img2tensor(cropped_face / 255., bgr2rgb=True, float32=True)
        normalize(cropped_face_t, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5), inplace=True)
        cropped_face_t = cropped_face_t.unsqueeze(0).to(device)

        with torch.no_grad():
            output = net(cropped_face_t, w=fidelity_weight, adain=True)[0]

        restored_face = tensor2img(output, rgb2bgr=True, min_max=(-1, 1))
        restored_face = restored_face.astype("uint8")
        face_helper.add_restored_face(restored_face, cropped_face)

    face_helper.get_inverse_affine(None)
    restored_bgr = face_helper.paste_faces_to_input_image()

    restored_rgb = cv2.cvtColor(restored_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(restored_rgb)


# ========== API UNIFIÉE ==========

def restore_faces_in_frames(frames, method="gfpgan", fidelity_weight=0.5):
    """
    Restaure les visages dans une liste de frames PIL.

    Args:
        frames: list[PIL.Image]
        method: "gfpgan" ou "codeformer"
        fidelity_weight: 0.0=max restauration, 0.5=équilibré, 1.0=original

    Returns:
        list[PIL.Image]
    """
    if not frames:
        return frames

    method = method.lower()
    print(f"[FACE] Restauration {method.upper()} ({len(frames)} frames, weight={fidelity_weight})...")
    t0 = time.time()

    if method == "gfpgan":
        restore_fn = lambda f: restore_face_gfpgan(f, weight=fidelity_weight)
    else:
        restore_fn = lambda f: restore_face_codeformer(f, fidelity_weight=fidelity_weight)

    restored = []
    for i, frame in enumerate(frames):
        restored.append(restore_fn(frame))
        if (i + 1) % 10 == 0:
            print(f"[FACE]   {i + 1}/{len(frames)} frames traitées...")

    elapsed = time.time() - t0
    fps_rate = len(frames) / elapsed if elapsed > 0 else 0
    print(f"[FACE] Restauration terminée: {len(frames)} frames en {elapsed:.1f}s ({fps_rate:.1f} fps)")
    return restored


# ========== ALIASES (rétro-compatibilité) ==========

def restore_face_in_frame(frame_pil, fidelity_weight=0.7):
    """Alias rétro-compatible → CodeFormer."""
    return restore_face_codeformer(frame_pil, fidelity_weight)


def unload_face_restore():
    """Libère tous les modèles de restauration faciale."""
    global _codeformer_net, _gfpgan_restorer, _gfpgan_device, _codeformer_device
    import torch
    if _codeformer_net is not None:
        del _codeformer_net
        _codeformer_net = None
        _codeformer_device = None
        print("[FACE] CodeFormer déchargé")
    if _gfpgan_restorer is not None:
        del _gfpgan_restorer
        _gfpgan_restorer = None
        _gfpgan_device = None
        print("[FACE] GFPGAN déchargé")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
