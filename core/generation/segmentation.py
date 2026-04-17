"""
Segmentation - Module de segmentation d'images (Smart Router edition)

Modèles gardés:
- SCHP: Self-Correction Human Parsing (82% mIoU, défaut)
- SegFormer FASHN: Couteau suisse (toutes classes: hair, shoes, background, clothes, etc.)
- GroundingDINO: Ciblage texte pour objets non-humains
- MediaPipe: Exclusion visage, orientation corps

Modèles supprimés: SAM, rembg (remplacés par SegFormer)
"""

from __future__ import annotations

import os
import numpy as np
from PIL import Image
from pathlib import Path
import threading

# cv2 lazy import with DLL error handling
_cv2 = None
_cv2_checked = False

def _get_cv2():
    """Import cv2 with graceful DLL failure handling."""
    global _cv2, _cv2_checked
    if _cv2_checked:
        return _cv2
    _cv2_checked = True
    try:
        import cv2
        _cv2 = cv2
    except (ImportError, OSError) as e:
        print(f"[SEG] WARNING: cv2 unavailable ({e}), using numpy fallbacks")
        _cv2 = None
    return _cv2

def _dilate_fallback(mask, kernel_size, iterations=1):
    """numpy fallback for cv2.dilate using max_filter."""
    from scipy.ndimage import maximum_filter
    result = mask.copy()
    for _ in range(iterations):
        result = maximum_filter(result, size=kernel_size)
    return result

# Global state pour les modeles
_grounding_dino_model = None
_clothes_segmenter_b5 = None  # SegFormer (B4 ou B2) — mode single
_sapiens_segmenter = None     # Sapiens 1B (Meta)
_schp_segmenter = None        # SCHP (Self-Correction Human Parsing)

# Cache fusion — B2 et B4 restent chargés (~150MB, GPU si VRAM >= 6GB)
_fusion_b2_cache = None   # {'model': ..., 'processor': ...}
_fusion_b4_cache = None   # {'model': ..., 'processor': ...}

# Verrou pour éviter les race conditions pendant le chargement
_grounding_dino_lock = threading.Lock()
_segmentation_cuda_cpu_policy_logged = False


def _materialize_meta_tensors(module):
    """Remplace les meta tensors par des zéros sur CPU.

    from_pretrained + low_cpu_mem_usage peut laisser des meta tensors
    sur certaines versions de transformers. Doit être appelé AVANT .to(device).
    Accès direct aux dicts _parameters/_buffers pour gérer les tied weights.
    """
    import torch
    fixed = 0
    for _, submod in module.named_modules():
        for pname, p in list(submod._parameters.items()):
            if p is not None and p.is_meta:
                submod._parameters[pname] = torch.nn.Parameter(
                    torch.zeros(p.shape, dtype=p.dtype, device="cpu"),
                    requires_grad=p.requires_grad
                )
                fixed += 1
        for bname, b in list(submod._buffers.items()):
            if b is not None and b.is_meta:
                submod._buffers[bname] = torch.zeros(b.shape, dtype=b.dtype, device="cpu")
                fixed += 1
    if fixed > 0:
        print(f"[SEG] Fixed {fixed} meta tensors in {type(module).__name__}")

# Cache de segmentation par hash image + stratégie (~2s saved)
_seg_cache = {}
_SEG_CACHE_MAX = 8

def _image_hash(image: Image.Image) -> str:
    import hashlib
    thumb = image.copy()
    thumb.thumbnail((16, 16), Image.BILINEAR)
    return hashlib.md5(thumb.tobytes()).hexdigest()

# GroundingDINO checkpoints
GROUNDING_DINO_CONFIG = "GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"
GROUNDING_DINO_CHECKPOINT_URL = "https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth"
GROUNDING_DINO_CHECKPOINT_NAME = "groundingdino_swint_ogc.pth"

# Dossier pour les checkpoints
CHECKPOINTS_DIR = Path(__file__).parent.parent.parent / "checkpoints"


# ============================================================
# SMART MASK - Point d'entrée unique
# ============================================================

def create_smart_mask(
    image: Image.Image,
    strategy: str,
    classes: list = None,
    target_prompt: str = None,
    exclude_face: bool = True,
    brush_mask: Image.Image = None,
    adjacent_classes: list = None,
    tight: bool = False
) -> Image.Image:
    """
    Point d'entrée unique pour la création de masques.
    Utilisé par le Smart Router.

    Args:
        image: Image source PIL
        strategy: "clothes", "hair", "background", "person", "target:X",
                  "full", "brush_only", "brush+clothes", etc.
        classes: Override SegFormer classes si besoin (list of int)
        target_prompt: Prompt pour GroundingDINO (quand strategy=target:X)
        exclude_face: Exclure le visage du masque
        brush_mask: Masque pinceau optionnel (union avec auto-mask)

    Returns:
        Masque grayscale (L) - blanc = zone à modifier
    """
    from core.log_utils import header, row, row2, footer, text
    global _seg_cache

    if image.mode != "RGB":
        image = image.convert("RGB")

    # Cache: même image + stratégie → skip segmentation
    _cache_key = (_image_hash(image), strategy, tuple(classes) if classes else None, tight)
    if _cache_key in _seg_cache and brush_mask is None:
        print(f"[SEG] Cache hit → skip segmentation ({strategy})")
        return _seg_cache[_cache_key].copy()

    cv2 = _get_cv2()
    header("SEGMENTATION")
    row("Strategy", strategy)

    if strategy == "brush_only":
        row("Model", "none (brush mask)")
        footer()
        if brush_mask is not None:
            return brush_mask
        return Image.new("L", image.size, 255)

    if strategy == "full":
        if brush_mask is not None:
            # L'utilisateur a brush → utiliser son masque, pas un full white
            row("Model", "none (brush mask override)")
            footer()
            return brush_mask
        row("Model", "none (full white mask)")
        footer()
        return Image.new("L", image.size, 255)

    if strategy.startswith("target:"):
        # GroundingDINO pour objets spécifiques
        target = strategy.split(":", 1)[1]
        try:
            mask = segment_grounding_dino(image, target)
            # Dilater légèrement
            mask_array = np.array(mask)
            if cv2 is not None:
                kernel = np.ones((10, 10), np.uint8)
                mask_array = cv2.dilate(mask_array, kernel, iterations=1)
            else:
                mask_array = _dilate_fallback(mask_array, 10, iterations=1)
            return Image.fromarray(mask_array, mode="L")
        except Exception as e:
            print(f"[MASK] GroundingDINO failed ({e}), falling back to full mask")
            return Image.new("L", image.size, 255)

    if strategy.startswith("brush+"):
        # Union brush + auto-mask
        auto_strategy = strategy.split("+", 1)[1]
        auto_mask = _segformer_mask(image, auto_strategy, classes, exclude_face, adjacent_classes=adjacent_classes, double_pass=tight)
        if brush_mask is not None:
            # Debug: sauvegarder les masques individuels
            try:
                output_dir = Path("output")
                output_dir.mkdir(exist_ok=True)

                # Convertir brush_mask en L si nécessaire
                brush_l = brush_mask.convert("L") if brush_mask.mode != "L" else brush_mask

                # Stats sur le brush mask
                brush_arr = np.array(brush_l)
                brush_coverage = (brush_arr > 128).sum() / brush_arr.size * 100
                print(f"[BRUSH DEBUG] Brush mask: {brush_mask.size}, mode={brush_mask.mode}, coverage={brush_coverage:.1f}%")

                brush_l.save(output_dir / "debug_brush_mask.png")
                auto_mask.save(output_dir / "debug_auto_mask.png")

                combined = _union_masks(brush_l, auto_mask)
                combined.save(output_dir / "debug_combined_mask.png")
                print(f"[BRUSH DEBUG] Masques sauvegardés dans output/")
                return combined
            except Exception as e:
                print(f"[BRUSH DEBUG] Erreur: {e}")
                return _union_masks(brush_mask.convert("L"), auto_mask)
        return auto_mask

    # SegFormer pour tout le reste (clothes, hair, shoes, hat, background, person)
    mask = _segformer_mask(image, strategy, classes, exclude_face, adjacent_classes=adjacent_classes, double_pass=tight)

    # Dilatation + flou pour blend naturel
    mask_array = np.array(mask)
    from PIL import ImageFilter

    if tight:
        # Mode tight (nudity): close pour combler les trous + légère dilation
        # PAS de blur — processing.py gère le masque (dilation 12px + max_pool2d + fooocus_fill)
        # Un blur ici créerait des bords mous → fooocus_fill propage du blanc/gris
        if cv2 is not None:
            kernel_small = np.ones((3, 3), np.uint8)
            mask_array = cv2.morphologyEx(mask_array, cv2.MORPH_CLOSE, kernel_small)
            kernel_med = np.ones((5, 5), np.uint8)
            mask_array = cv2.dilate(mask_array, kernel_med, iterations=3)
        else:
            from scipy.ndimage import binary_closing
            mask_array = (binary_closing(mask_array > 127, structure=np.ones((3, 3))) * 255).astype(np.uint8)
            mask_array = _dilate_fallback(mask_array, 5, iterations=3)
        mask = Image.fromarray(mask_array, mode="L")
        row("Dilate", "3x3 close + 5x5 x3 [tight, binaire]")
    else:
        # Mode normal: dilation pour couvrir les bords imprécis
        # PAS de blur — même raison
        if cv2 is not None:
            kernel_small = np.ones((3, 3), np.uint8)
            mask_array = cv2.dilate(mask_array, kernel_small, iterations=2)
            kernel_big = np.ones((7, 7), np.uint8)
            mask_array = cv2.dilate(mask_array, kernel_big, iterations=2)
        else:
            mask_array = _dilate_fallback(mask_array, 3, iterations=2)
            mask_array = _dilate_fallback(mask_array, 7, iterations=2)
        mask = Image.fromarray(mask_array, mode="L")
        row("Dilate", "3x3 x2 + 7x7 x2 [binaire]")

    # When clothing segmentation returns an empty/tiny mask on minimal outfits,
    # local-pack body-reveal edits would otherwise run with no useful pixels.
    # Tight mode is only used by that workflow, so keep normal clothing edits
    # conservative and fallback only there.
    coverage_pct = float(np.sum(np.array(mask) > 127) / (image.width * image.height) * 100)
    if strategy == "clothes" and tight and coverage_pct < 1.0:
        row("Fallback", f"clothes trop faible ({coverage_pct:.1f}%) → body")
        body_mask = _segformer_mask(
            image,
            "body",
            classes=None,
            exclude_face=exclude_face,
            adjacent_classes=adjacent_classes,
            double_pass=False,
        )
        body_arr = np.array(body_mask)
        if cv2 is not None:
            body_arr = cv2.morphologyEx(body_arr, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            body_arr = cv2.dilate(body_arr, np.ones((5, 5), np.uint8), iterations=2)
        else:
            body_arr = _dilate_fallback(body_arr, 5, iterations=2)
        mask = Image.fromarray(body_arr, mode="L")
        coverage_pct = float(np.sum(body_arr > 127) / body_arr.size * 100)
        row("Fallback mask", f"{coverage_pct:.1f}% body")

    # Hair strategy: soustraire le visage (class 11) pour éviter de le modifier
    # La dilation du masque cheveux déborde sur le visage → on le protège
    if strategy == 'hair' and exclude_face:
        try:
            face_mask = _segformer_mask(image, 'person', classes=[11], exclude_face=False, double_pass=False)
            face_arr = np.array(face_mask)
            mask_arr = np.array(mask)
            # Dilater légèrement le masque visage pour une marge de sécurité
            if cv2 is not None:
                face_arr = cv2.dilate(face_arr, np.ones((5, 5), np.uint8), iterations=2)
            mask_arr[face_arr > 127] = 0
            mask = Image.fromarray(mask_arr, mode="L")
            row("Face", "soustrait du masque cheveux (protection visage)")
        except Exception as e:
            row("Face", f"skip soustraction ({e})")

    footer()

    # Cache: stocker le résultat
    if brush_mask is None:
        if len(_seg_cache) >= _SEG_CACHE_MAX:
            _seg_cache.pop(next(iter(_seg_cache)))
        _seg_cache[_cache_key] = mask.copy()

    # Debug: sauvegarder masque + overlay
    try:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        mask.save(output_dir / "last_final_mask.png")

        # Overlay: masque rouge semi-transparent sur l'image originale
        overlay = image.copy().convert("RGBA")
        red_layer = Image.new("RGBA", image.size, (255, 0, 0, 100))
        mask_bool = np.array(mask) > 128
        # Appliquer le rouge uniquement sur les zones masquées
        overlay_array = np.array(overlay)
        red_array = np.array(red_layer)
        overlay_array[mask_bool] = (
            overlay_array[mask_bool] * 0.5 + red_array[mask_bool] * 0.5
        ).astype(np.uint8)
        Image.fromarray(overlay_array).save(output_dir / "last_mask_overlay.png")
        print(f"[DEBUG] Overlay masque → output/last_mask_overlay.png")
    except Exception:
        pass

    return mask


def _segformer_mask(
    image: Image.Image,
    strategy: str,
    classes: list = None,
    exclude_face: bool = True,
    adjacent_classes: list = None,
    double_pass: bool = False
) -> Image.Image:
    """Segmentation avec le modèle actif (SegFormer ou Sapiens)."""
    # Si le router a passé des classes explicites, les utiliser en priorité
    # Sinon, utiliser les classes de la stratégie du variant actif
    if classes is None:
        variant_classes = get_classes_for_strategy(strategy)
        if variant_classes is not None:
            classes = variant_classes
        else:
            classes = get_classes_for_strategy('clothes')

    # Router vers le bon moteur
    vinfo = SEGFORMER_VARIANT_CLASSES.get(_active_segformer_variant, SEGFORMER_VARIANT_CLASSES['schp'])
    engine = vinfo.get('engine', 'segformer')

    if engine == 'fusion':
        mask = segment_fusion(image, strategy=strategy, include_classes_override=classes, save_debug=True)
    elif engine == 'schp':
        mask = segment_schp(image, include_classes=classes, double_pass=double_pass)
    elif engine == 'sapiens':
        mask = segment_sapiens(image, include_classes=classes)
        _unload_sapiens()
    else:
        mask = segment_clothes_auto(image, include_classes=classes, adjacent_classes=adjacent_classes, double_pass=double_pass)

    # NOTE SUR LE FACE EXCLUSION (MediaPipe) :
    # Tous les modèles (B2, B4, SCHP) ont une classe visage séparée qui n'est PAS
    # dans les classes "clothes". Donc quand strategy='clothes', le visage n'est
    # JAMAIS dans le masque → MediaPipe face exclusion est inutile.
    # MediaPipe ne serait utile que pour strategy='person' (qui inclut cheveux/chapeau),
    # mais le smart router corrige déjà person→clothes pour le nudity.
    # On skip pour schp et fusion car testé et confirmé : l'ellipse MediaPipe
    # (chin_bottom=0.3*face_h) mange le haut du masque (bra/top) → résultat pire.
    # TODO: envisager de skip pour TOUS les engines quand strategy='clothes'.
    if exclude_face and strategy != 'background' and engine in ('schp', 'fusion'):
        from core.log_utils import row
        row("Face", f"skip ({engine} sépare déjà le visage)")
    elif exclude_face and strategy != 'background':
        # Debug: sauvegarder le masque AVANT exclusion tête
        try:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")
            os.makedirs(output_dir, exist_ok=True)
            mask.save(os.path.join(output_dir, "debug_mask_before_face.png"))
            print(f"[DEBUG] Masque avant exclusion → output/debug_mask_before_face.png")
        except Exception:
            pass

        mask = _exclude_face_from_mask(image, mask)

        # Debug: sauvegarder le masque APRÈS exclusion tête
        try:
            mask.save(os.path.join(output_dir, "debug_mask_after_face.png"))
            print(f"[DEBUG] Masque après exclusion → output/debug_mask_after_face.png")
        except Exception:
            pass

    return mask


def _union_masks(mask_a: Image.Image, mask_b: Image.Image) -> Image.Image:
    """Combine deux masques avec OR (union)."""
    # Redimensionner si nécessaire
    if mask_a.size != mask_b.size:
        mask_b = mask_b.resize(mask_a.size, Image.LANCZOS)

    arr_a = np.array(mask_a.convert("L"))
    arr_b = np.array(mask_b.convert("L"))
    combined = np.maximum(arr_a, arr_b)
    return Image.fromarray(combined, mode="L")


# ============================================================
# BODY ORIENTATION (gardé)
# ============================================================

def _detect_orientation_core(image: Image.Image) -> dict:
    """Coeur de la détection orientation/pose (sans log, sans retry flip)."""
    import mediapipe as mp

    img_rgb = np.array(image.convert("RGB"))
    h, w = img_rgb.shape[:2]

    face_detected = False
    face_confidence = 0
    face_box = None
    orientation = 'unknown'
    confidence = 0.3
    details = "pas de visage"
    pose = 'standing'

    # === Détection de visage ===
    try:
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python import BaseOptions
        import urllib.request

        models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "mediapipe")
        os.makedirs(models_dir, exist_ok=True)
        model_path = os.path.join(models_dir, "blaze_face_short_range.tflite")

        if not os.path.exists(model_path):
            model_url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
            urllib.request.urlretrieve(model_url, model_path)

        base_options = BaseOptions(model_asset_path=model_path)
        options = vision.FaceDetectorOptions(base_options=base_options, min_detection_confidence=0.3)

        with vision.FaceDetector.create_from_options(options) as detector:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
            results = detector.detect(mp_image)

            if results.detections and len(results.detections) > 0:
                best_detection = max(results.detections, key=lambda d: d.categories[0].score)
                face_confidence = best_detection.categories[0].score
                face_detected = True

                bbox = best_detection.bounding_box
                face_box = {
                    'x': bbox.origin_x / w,
                    'y': bbox.origin_y / h,
                    'width': bbox.width / w,
                    'height': bbox.height / h
                }
    except Exception as e:
        print(f"[ORIENTATION] Erreur FaceDetection: {e}")

    # === Orientation ===
    if face_detected and face_confidence > 0.5:
        if face_box:
            face_center_x = face_box['x'] + face_box['width'] / 2
            if face_center_x < 0.2 or face_center_x > 0.8:
                orientation = 'side'
                confidence = face_confidence * 0.8
                details = f"visage décentré x={face_center_x:.2f}, conf={face_confidence:.2f}"
            else:
                orientation = 'front'
                confidence = face_confidence
                details = f"visage détecté conf={face_confidence:.2f}"
        else:
            orientation = 'front'
            confidence = face_confidence
            details = f"visage détecté conf={face_confidence:.2f}"
    elif face_detected and face_confidence > 0.3:
        orientation = 'side'
        confidence = face_confidence
        details = f"visage partiel conf={face_confidence:.2f}"

    # === Pose (debout/allongé) ===
    try:
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python import BaseOptions
        import urllib.request

        models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "mediapipe")
        os.makedirs(models_dir, exist_ok=True)
        model_path = os.path.join(models_dir, "pose_landmarker_lite.task")

        if not os.path.exists(model_path):
            model_url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
            urllib.request.urlretrieve(model_url, model_path)

        base_options = BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(base_options=base_options, num_poses=1)

        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
            pose_results = landmarker.detect(mp_image)

            if pose_results.pose_landmarks and len(pose_results.pose_landmarks) > 0:
                landmarks = pose_results.pose_landmarks[0]

                if orientation == 'unknown':
                    orientation = 'back'
                    confidence = 0.85
                    details = "pas de visage, corps détecté -> de dos"

                left_shoulder_y = landmarks[11].y
                right_shoulder_y = landmarks[12].y
                left_hip_y = landmarks[23].y
                right_hip_y = landmarks[24].y

                shoulder_y = (left_shoulder_y + right_shoulder_y) / 2
                hip_y = (left_hip_y + right_hip_y) / 2
                vertical_diff = abs(hip_y - shoulder_y)

                left_shoulder_x = landmarks[11].x
                right_shoulder_x = landmarks[12].x
                left_hip_x = landmarks[23].x
                right_hip_x = landmarks[24].x
                shoulder_x = (left_shoulder_x + right_shoulder_x) / 2
                hip_x = (left_hip_x + right_hip_x) / 2
                horizontal_diff = abs(hip_x - shoulder_x)

                head_x = landmarks[0].x

                if vertical_diff < 0.15 and horizontal_diff > 0.1:
                    if head_x < hip_x:
                        pose = 'lying_left'
                        details += ", allonge tete a gauche"
                    else:
                        pose = 'lying_right'
                        details += ", allonge tete a droite"
                elif vertical_diff < 0.08:
                    if head_x < hip_x:
                        pose = 'lying_left'
                        details += ", allonge tete a gauche"
                    elif head_x > hip_x:
                        pose = 'lying_right'
                        details += ", allonge tete a droite"
                    else:
                        pose = 'lying'
                        details += ", allonge"
                else:
                    pose = 'standing'
            else:
                if orientation == 'unknown':
                    details = "ni visage ni corps detecte"

    except Exception as e:
        if orientation == 'unknown':
            details = f"erreur pose: {e}"

    return {
        'orientation': orientation,
        'pose': pose,
        'confidence': confidence,
        'details': details
    }


def detect_body_orientation(image: Image.Image) -> dict:
    """
    Détecte l'orientation du corps: front, back, side.
    Détecte aussi la pose: standing, lying.
    Si rien détecté, retente avec l'image retournée 180° (photo à l'envers).
    """
    result = _detect_orientation_core(image)

    # Si rien détecté, retenter retournée 180°
    flipped = False
    if result['orientation'] == 'unknown' and result['confidence'] <= 0.3:
        flipped_result = _detect_orientation_core(image.rotate(180))
        if flipped_result['confidence'] > 0.5:
            result = flipped_result
            result['details'] += " (image retournée 180°)"
            flipped = True

    result['flipped'] = flipped

    from core.log_utils import row
    flip_str = " [FLIPPED]" if flipped else ""
    row("Orient.", f"{result['orientation']}/{result['pose']} ({result['confidence']*100:.0f}%){flip_str}")

    return result


# ============================================================
# UTILITAIRES
# ============================================================

def get_device():
    """Retourne le device optimal pour les modèles de segmentation.

    Sur petites VRAM CUDA, les modèles de segmentation restent CPU par défaut:
    le preload SDXL/ControlNet peut sinon se battre avec B2/B4/SCHP et bloquer
    la requête. Override local: JOYBOY_SEGMENTATION_CUDA_LOW_VRAM=1.
    """
    global _segmentation_cuda_cpu_policy_logged
    import torch
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        try:
            from core.models.runtime_env import should_run_segmentation_on_cuda
            use_cuda = should_run_segmentation_on_cuda(vram_gb)
        except Exception:
            use_cuda = vram_gb > 10
        if use_cuda:
            return "cuda"
        if vram_gb >= 6 and not _segmentation_cuda_cpu_policy_logged:
            print(
                f"[SEG] CUDA {vram_gb:.1f}GB détectée: segmentation sur CPU "
                "(évite les blocages low VRAM avec SDXL/ControlNet)"
            )
            _segmentation_cuda_cpu_policy_logged = True
        return "cpu"
    return "cpu"


def _publish_asset_download_progress(phase: str, step: int, total: int, message: str = ""):
    """Best-effort UI progress for first-run asset downloads."""
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase(phase, step=step, total=total, message=message)
    except Exception:
        pass


def download_checkpoint(url: str, filename: str, *, progress_label: str = None,
                        progress_phase: str = "download_assets") -> Path:
    """Telecharge un checkpoint avec barre de progression"""
    import sys
    import urllib.request

    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path = CHECKPOINTS_DIR / filename

    if checkpoint_path.exists():
        return checkpoint_path

    label = progress_label or filename
    print(f"[SEG] Telechargement {filename}...")
    _publish_asset_download_progress(
        progress_phase,
        1,
        100,
        f"Téléchargement {label}...",
    )

    try:
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            block_size = 8192
            last_percent = -1
            last_unknown_mb = -1

            with open(str(checkpoint_path), 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)

                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        if percent != last_percent:
                            bar_width = 30
                            filled = int(bar_width * percent / 100)
                            bar = "=" * filled + "-" * (bar_width - filled)
                            size_mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            sys.stdout.write(f"\r[SEG] [{bar}] {percent}% ({size_mb:.0f}/{total_mb:.0f} MB)")
                            sys.stdout.flush()
                            last_percent = percent
                            _publish_asset_download_progress(
                                progress_phase,
                                max(1, min(percent, 99)),
                                100,
                                f"Téléchargement {label} {percent}% ({size_mb:.0f}/{total_mb:.0f} MB)",
                            )
                    else:
                        # Some mirrors do not expose Content-Length, which used
                        # to make the UI look frozen during first-run downloads.
                        size_mb = int(downloaded / (1024 * 1024))
                        if size_mb >= last_unknown_mb + 5:
                            last_unknown_mb = size_mb
                            pseudo_percent = min(95, max(1, size_mb // 3))
                            _publish_asset_download_progress(
                                progress_phase,
                                pseudo_percent,
                                100,
                                f"Téléchargement {label} ({size_mb} MB reçus)",
                            )

            print()
            print(f"[SEG] {filename} telecharge")
            _publish_asset_download_progress(
                progress_phase,
                100,
                100,
                f"{label} téléchargé",
            )

    except Exception as e:
        print(f"\n[SEG] Erreur telechargement: {e}")
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        raise

    return checkpoint_path


# ============================================================
# SEGFORMER FASHN - Détection de toutes les classes
# ============================================================


# Mapping des classes par variant
SEGFORMER_VARIANT_CLASSES = {
    'schp': {
        'model': 'SCHP-ATR',
        'label': 'SCHP (82% mIoU)',
        'engine': 'schp',
        'input_size': [512, 512],
        'checkpoint_url': 'https://huggingface.co/levihsu/OOTDiffusion/resolve/main/checkpoints/humanparsing/exp-schp-201908301523-atr.pth',
        'checkpoint_file': 'exp-schp-201908301523-atr.pth',
        # ATR 18 classes — mêmes que SegFormer B2
        'strategies': {
            'background': [0],
            'hat': [1],
            'hair': [2],
            'top': [4],
            'dress': [7],
            'skirt': [5],
            'pants': [6],
            'belt': [8],
            'shoes': [9, 10],
            'bag': [16],
            'scarf': [17],
            'clothes': [4, 5, 6, 7, 8, 17],
            'body': [4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 17],
            'person': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        },
        'class_names': {
            0: "fond", 1: "chapeau", 2: "cheveux", 3: "lunettes", 4: "haut",
            5: "jupe", 6: "pantalon", 7: "robe", 8: "ceinture",
            9: "chaussure G", 10: "chaussure D", 11: "visage",
            12: "jambe G", 13: "jambe D", 14: "bras G", 15: "bras D",
            16: "sac", 17: "echarpe"
        }
    },
    'b4': {
        'model': 'fashn-ai/fashn-human-parser',
        'label': 'FASHN SegFormer B4',
        'engine': 'segformer',
        # 18 classes (0-17): https://huggingface.co/fashn-ai/fashn-human-parser
        'strategies': {
            'background': [0],
            'hat': [9],
            'hair': [2],
            'top': [3],
            'dress': [4],
            'skirt': [5],
            'pants': [6],
            'belt': [7],
            'shoes': [15],       # feet
            'bag': [8],
            'scarf': [10],
            'clothes': [3, 4, 5, 6, 7, 10],
            'body': [3, 4, 5, 6, 7, 10, 12, 13, 14, 15, 16, 17],
            'person': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        },
        'class_names': {
            0: "fond", 1: "visage", 2: "cheveux", 3: "haut", 4: "robe",
            5: "jupe", 6: "pantalon", 7: "ceinture", 8: "sac",
            9: "chapeau", 10: "echarpe", 11: "lunettes", 12: "bras",
            13: "mains", 14: "jambes", 15: "pieds", 16: "torse", 17: "bijoux"
        }
    },
    'b2': {
        'model': 'mattmdjaga/segformer_b2_clothes',
        'label': 'SegFormer B2 Clothes',
        'engine': 'segformer',
        # Strategies (nom → list of class IDs)
        'strategies': {
            'background': [0],
            'hat': [1],
            'hair': [2],
            'top': [4],
            'dress': [7],
            'skirt': [5],
            'pants': [6],
            'belt': [8],
            'shoes': [9, 10],
            'bag': [16],
            'scarf': [17],
            'clothes': [4, 5, 6, 7, 8, 17],
            'body': [4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 17],
            'person': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        },
        'class_names': {
            0: "fond", 1: "chapeau", 2: "cheveux", 3: "lunettes", 4: "haut",
            5: "jupe", 6: "pantalon", 7: "robe", 8: "ceinture",
            9: "chaussure G", 10: "chaussure D", 11: "visage",
            12: "jambe G", 13: "jambe D", 14: "bras G", 15: "bras D",
            16: "sac", 17: "echarpe"
        }
    },
    'sapiens_1b': {
        'model': 'facebook/sapiens-seg-1b-torchscript',
        'model_file': 'sapiens_1b_goliath_best_goliath_mIoU_7994_epoch_151_torchscript.pt2',
        'label': 'Meta Sapiens 1B (28 classes)',
        'engine': 'sapiens',
        'input_size': (1024, 768),  # H x W
        # Strategies (nom → list of class IDs)
        'strategies': {
            'background': [0],
            'hat': [],  # Pas de classe chapeau dans Sapiens
            'hair': [3],
            'top': [22],  # Upper_Clothing
            'dress': [22, 12],  # Upper + Lower
            'skirt': [12],  # Lower_Clothing
            'pants': [12],  # Lower_Clothing
            'belt': [1],  # Apparel (accessoires)
            'shoes': [8, 17],  # Left_Shoe, Right_Shoe
            'bag': [1],  # Apparel
            'scarf': [1],  # Apparel
            'clothes': [1, 12, 22],  # Apparel + Lower_Clothing + Upper_Clothing
            'body': [1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
            'person': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
        },
        'class_names': {
            0: "fond", 1: "accessoire", 2: "visage/cou", 3: "cheveux",
            4: "pied G", 5: "main G", 6: "avant-bras G", 7: "mollet G",
            8: "chaussure G", 9: "chaussette G", 10: "bras G", 11: "cuisse G",
            12: "bas", 13: "pied D", 14: "main D", 15: "avant-bras D",
            16: "mollet D", 17: "chaussure D", 18: "chaussette D",
            19: "bras D", 20: "cuisse D", 21: "torse",
            22: "haut", 23: "lèvre inf", 24: "lèvre sup",
            25: "dents inf", 26: "dents sup", 27: "langue"
        }
    },
    'fusion': {
        'model': 'B2 + B4 + SCHP',
        'label': 'Fusion (B2+B4+SCHP)',
        'engine': 'fusion',
        # Les strategies sont ignorées car fusion utilise celles de chaque modèle
        'strategies': {
            'background': [0],
            'hat': [1],
            'hair': [2],
            'top': [4],
            'dress': [7],
            'skirt': [5],
            'pants': [6],
            'belt': [8],
            'shoes': [9, 10],
            'bag': [16],
            'scarf': [17],
            'clothes': [4, 5, 6, 7, 8, 17],
            'body': [4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 17],
            'person': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17],
        },
        'class_names': {}  # Pas utilisé
    }
}

# Variant actif (peut être changé via les settings)
_active_segformer_variant = 'fusion'


def set_segformer_variant(variant: str):
    """Change le variant actif (schp, b2, b4, sapiens_1b, fusion).
    Garde SCHP et fusion cache en RAM (légers CPU ~230MB).
    Décharge Sapiens (lourd GPU) et le single-slot SegFormer (doit matcher le variant actif)."""
    global _active_segformer_variant, _clothes_segmenter_b5, _sapiens_segmenter
    if variant not in SEGFORMER_VARIANT_CLASSES:
        return
    if variant != _active_segformer_variant:
        # _clothes_segmenter_b5 = single slot, doit correspondre au variant actif
        if _clothes_segmenter_b5 is not None:
            del _clothes_segmenter_b5
            _clothes_segmenter_b5 = None
            print("[SEG] SegFormer single déchargé")
        # Sapiens = lourd (GPU), toujours décharger
        if _sapiens_segmenter is not None:
            del _sapiens_segmenter
            _sapiens_segmenter = None
            print("[SEG] Sapiens déchargé")
        # SCHP + fusion B2/B4 : gardés en RAM (rechargement coûteux, ~230MB CPU)
        import gc, torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _active_segformer_variant = variant


def get_segformer_variant():
    return _active_segformer_variant


def get_classes_for_strategy(strategy: str) -> list | None:
    """Retourne les class IDs pour une stratégie donnée, selon le variant actif."""
    vinfo = SEGFORMER_VARIANT_CLASSES.get(_active_segformer_variant, SEGFORMER_VARIANT_CLASSES['schp'])
    return vinfo['strategies'].get(strategy)


def load_clothes_segmenter(variant: str = None):
    """
    Charge le modèle SegFormer pour la segmentation.
    Supporte B4 (FASHN) et B2 (mattmdjaga).
    """
    global _clothes_segmenter_b5

    if _clothes_segmenter_b5 is not None:
        return _clothes_segmenter_b5

    if variant is None:
        variant = _active_segformer_variant

    vinfo = SEGFORMER_VARIANT_CLASSES.get(variant, SEGFORMER_VARIANT_CLASSES['schp'])
    model_name = vinfo['model']

    try:
        from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
        import torch

        device = get_device()
        _publish_asset_download_progress(
            "download_segmentation",
            5,
            100,
            f"Préparation segmentation {variant}...",
        )

        try:
            processor = AutoImageProcessor.from_pretrained(model_name, local_files_only=True)
        except OSError:
            _publish_asset_download_progress(
                "download_segmentation",
                10,
                100,
                f"Téléchargement segmentation {variant}...",
            )
            processor = AutoImageProcessor.from_pretrained(model_name)
        try:
            model = AutoModelForSemanticSegmentation.from_pretrained(
                model_name, torch_dtype=torch.float32,
                device_map=None, low_cpu_mem_usage=False, local_files_only=True,
            )
        except OSError:
            _publish_asset_download_progress(
                "download_segmentation",
                30,
                100,
                f"Téléchargement poids segmentation {variant}...",
            )
            model = AutoModelForSemanticSegmentation.from_pretrained(
                model_name, torch_dtype=torch.float32,
                device_map=None, low_cpu_mem_usage=False,
            )

        # Quantification int8 si GPU disponible
        quantized = False
        if device != "cpu":
            try:
                from optimum.quanto import quantize, freeze, qint8
                quantize(model, weights=qint8)
                freeze(model)
                quantized = True
            except Exception:
                pass

        model = model.to(device)
        model.eval()

        _clothes_segmenter_b5 = {
            'processor': processor,
            'model': model,
            'device': device,
            'variant': variant
        }
        _publish_asset_download_progress(
            "download_segmentation",
            100,
            100,
            f"Segmentation {variant} prête",
        )

        q_str = " (int8)" if quantized else ""
        print(f"[SEG] {vinfo['label']} loaded on {device}{q_str}")
        return _clothes_segmenter_b5

    except Exception as e:
        print(f"[SEG] Erreur chargement SegFormer: {e}")
        print("[SEG] Installation: pip install transformers")
        raise


def segment_clothes_auto(image: Image.Image, include_classes: list = None, adjacent_classes: list = None, double_pass: bool = False) -> Image.Image:
    """
    Segmente avec SegFormer selon les classes demandées (variant-aware).

    Args:
        image: Image PIL
        include_classes: Liste des classes à inclure (défaut: clothes du variant actif)
        adjacent_classes: Classes supplémentaires à inclure UNIQUEMENT si adjacentes
                         aux classes principales (ex: [16] torse pour nudity sur B4)
        double_pass: Si True, deuxième passe sur les probabilités softmax pour capter
                     les vêtements que l'argmax a ratés (pixels incertains)

    Returns:
        Masque grayscale (L) où les zones sélectionnées sont blanches
    """
    cv2 = _get_cv2()
    if cv2 is None:
        print("[SEG] cv2 unavailable, returning full mask (clothes_auto)")
        return Image.new("L", image.size, 255)
    import torch
    import torch.nn.functional as F

    segmenter = load_clothes_segmenter()
    processor = segmenter['processor']
    model = segmenter['model']
    device = segmenter['device']

    if include_classes is None:
        include_classes = get_classes_for_strategy('clothes')

    # Convertir en RGB si nécessaire (RGBA, P, L, etc.)
    if image.mode != "RGB":
        image = image.convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    inputs = {k: v.to(device=device, dtype=torch.float32) if v.is_floating_point() else v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits

    upsampled = F.interpolate(
        logits,
        size=image.size[::-1],
        mode='bilinear',
        align_corners=False
    )

    pred = upsampled.argmax(dim=1).squeeze().cpu().numpy()

    # Debug: voir toutes les classes détectées
    unique_classes = np.unique(pred)
    vinfo = SEGFORMER_VARIANT_CLASSES.get(_active_segformer_variant, SEGFORMER_VARIANT_CLASSES['schp'])
    class_names = vinfo['class_names']
    detected = [f"{int(c)}:{class_names.get(int(c), str(c))}" for c in unique_classes]
    print(f"[SEGFORMER DEBUG] Image: {image.size}, Logits: {logits.shape}, Pred: {pred.shape}")
    print(f"[SEGFORMER DEBUG] Classes détectées: {detected}")
    print(f"[SEGFORMER DEBUG] Classes demandées: {include_classes}")
    for c in unique_classes:
        count = np.sum(pred == c)
        pct = count / pred.size * 100
        if pct > 0.5:
            print(f"[SEGFORMER DEBUG]   {int(c)}:{class_names.get(int(c), str(c))} = {pct:.1f}%")

    # === PASSE 1: Argmax strict ===
    mask = np.zeros(pred.shape, dtype=np.uint8)
    for class_id in include_classes:
        mask[pred == class_id] = 255

    found_classes = []
    for class_id in include_classes:
        if np.any(pred == class_id):
            found_classes.append(class_names.get(class_id, str(class_id)))

    pass1_pixels = np.sum(mask > 0)
    pass1_pct = pass1_pixels / pred.size * 100
    print(f"[SEG] Passe 1 (argmax): {', '.join(found_classes) if found_classes else 'aucun'} ({pass1_pct:.1f}%)")

    # === PASSE 2: Vérification softmax — capter les vêtements que l'argmax a ratés ===
    if double_pass and np.any(mask > 0):
        probs = F.softmax(upsampled, dim=1).squeeze().cpu().numpy()  # (num_classes, H, W)

        # Somme des probabilités de toutes les classes vêtement
        clothes_prob = np.zeros(pred.shape, dtype=np.float32)
        for class_id in include_classes:
            if class_id < probs.shape[0]:
                clothes_prob += probs[class_id]

        # Pixels incertains : prob vêtement > 25% mais argmax dit autre chose
        uncertain = (clothes_prob > 0.25) & (mask == 0)

        # Ne garder que les pixels adjacents au masque passe 1 (pas les faux positifs isolés)
        adj_kernel = np.ones((20, 20), np.uint8)
        clothes_zone = cv2.dilate(mask, adj_kernel, iterations=1)
        adjacent_uncertain = uncertain & (clothes_zone > 0)

        n_added = np.sum(adjacent_uncertain)
        if n_added > 0:
            mask[adjacent_uncertain] = 255
            added_pct = n_added / pred.size * 100
            print(f"[SEG] Passe 2 (softmax): +{n_added} pixels récupérés ({added_pct:.1f}%) — vêtements incertains adjacents")
        else:
            print(f"[SEG] Passe 2 (softmax): rien de plus à récupérer")

    # Adjacent classes: inclure les pixels de ces classes UNIQUEMENT s'ils touchent le masque principal
    # Ex: B4 nudity → torse (16) adjacent aux vêtements = soutif mal classifié
    if adjacent_classes and np.any(mask > 0):
        adj_kernel = np.ones((40, 40), np.uint8)
        clothes_zone = cv2.dilate(mask, adj_kernel, iterations=2)
        adj_added = []
        for adj_class in adjacent_classes:
            adj_pixels = (pred == adj_class).astype(np.uint8) * 255
            overlap = cv2.bitwise_and(adj_pixels, clothes_zone)
            n_overlap = np.sum(overlap > 0)
            if n_overlap > 0:
                mask = cv2.bitwise_or(mask, overlap)
                adj_name = class_names.get(adj_class, str(adj_class))
                adj_pct = n_overlap / pred.size * 100
                adj_added.append(f"{adj_name} ({adj_pct:.1f}%)")
        if adj_added:
            print(f"[SEG] Adjacent → ajouté: {', '.join(adj_added)}")

    # Stats finales
    clothes_pixels = np.sum(mask > 0)
    total_pixels = mask.shape[0] * mask.shape[1]
    ratio = clothes_pixels / total_pixels * 100

    from core.log_utils import row, row2
    row("Model", vinfo['label'])
    row("Classes", f"{', '.join(found_classes) if found_classes else 'aucun'} ({ratio:.1f}%)")

    # Légère dilatation pour couvrir les bords
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)

    return Image.fromarray(mask, mode="L")


# ============================================================
# META SAPIENS - Segmentation haute précision (28 classes)
# ============================================================

def load_sapiens_segmenter():
    """Charge le modèle Sapiens via TorchScript depuis HuggingFace."""
    global _sapiens_segmenter

    if _sapiens_segmenter is not None:
        return _sapiens_segmenter

    import torch

    vinfo = SEGFORMER_VARIANT_CLASSES['sapiens_1b']
    repo_id = vinfo['model']
    filename = vinfo['model_file']

    try:
        from huggingface_hub import hf_hub_download

        print(f"[SEG] Téléchargement Sapiens 1B (~4.5GB)...")
        model_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename
        )

        device = get_device()
        print(f"[SEG] Chargement Sapiens 1B sur {device}...")
        model = torch.jit.load(model_path)
        model = model.eval().to(device)

        _sapiens_segmenter = {
            'model': model,
            'device': device,
        }

        print(f"[SEG] Meta Sapiens 1B loaded on {device}")
        return _sapiens_segmenter

    except Exception as e:
        print(f"[SEG] Erreur chargement Sapiens: {e}")
        raise


def segment_sapiens(image: Image.Image, include_classes: list = None) -> Image.Image:
    """
    Segmente avec Meta Sapiens 1B (28 classes, haute précision).

    Args:
        image: Image PIL
        include_classes: Liste des classes à inclure (défaut: clothes [1, 12, 22])

    Returns:
        Masque grayscale (L)
    """
    cv2 = _get_cv2()
    if cv2 is None:
        print("[SEG] cv2 unavailable, returning full mask (sapiens)")
        return Image.new("L", image.size, 255)
    import torch
    import torch.nn.functional as F
    from torchvision import transforms

    segmenter = load_sapiens_segmenter()
    model = segmenter['model']
    device = segmenter['device']
    class_names = SEGFORMER_VARIANT_CLASSES.get('sapiens_1b', {}).get('class_names', {})

    if include_classes is None:
        include_classes = get_classes_for_strategy('clothes')

    # Garantir RGB
    if image.mode != "RGB":
        image = image.convert("RGB")

    original_size = image.size  # (W, H)

    # Préprocessing Sapiens: resize 1024x768, normalisation ImageNet
    preprocess = transforms.Compose([
        transforms.Resize((1024, 768)),
        transforms.ToTensor(),
        transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ])

    input_tensor = preprocess(image).unsqueeze(0).to(device)

    with torch.inference_mode():
        output = model(input_tensor)

    if isinstance(output, (tuple, list)):
        # Prendre le dernier élément (la tête principale, pas les auxiliaires)
        output = output[-1]

    # Upsample vers la taille originale
    result = output.cpu()
    upsampled = F.interpolate(
        result.unsqueeze(0) if result.dim() == 3 else result,
        size=(original_size[1], original_size[0]),  # (H, W)
        mode='bilinear',
        align_corners=False
    )

    pred = upsampled.argmax(dim=1).squeeze().numpy()

    mask = np.zeros(pred.shape, dtype=np.uint8)
    for class_id in include_classes:
        mask[pred == class_id] = 255

    # Stats
    clothes_pixels = np.sum(mask > 0)
    total_pixels = mask.shape[0] * mask.shape[1]
    ratio = clothes_pixels / total_pixels * 100

    found_classes = []
    for class_id in include_classes:
        if np.any(pred == class_id):
            found_classes.append(class_names.get(class_id, str(class_id)))

    from core.log_utils import row
    row("Model", "Meta Sapiens 1B")
    row("Classes", f"{', '.join(found_classes) if found_classes else 'aucun'} ({ratio:.1f}%)")

    # Légère dilatation pour couvrir les bords
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)

    return Image.fromarray(mask, mode="L")


# ============================================================
# SCHP - Self-Correction for Human Parsing (82% mIoU)
# ============================================================

SCHP_DIR = Path(__file__).parent.parent.parent / "ext_weights" / "schp"

def _ensure_schp_files():
    """Crée les fichiers Python SCHP sur disque s'ils n'existent pas."""
    SCHP_DIR.mkdir(parents=True, exist_ok=True)

    modules_path = SCHP_DIR / "schp_modules.py"
    if not modules_path.exists():
        print("[SEG] Création schp_modules.py...")
        modules_path.write_text('''"""Pure Python InPlaceABNSync replacement for SCHP (no C++ extensions)."""
import torch
import torch.nn as nn
from torch.nn import functional as F

class InPlaceABNSync(nn.Module):
    def __init__(self, num_features, eps=1e-5, momentum=0.1, affine=True,
                 activation="leaky_relu", slope=0.01):
        super().__init__()
        self.num_features = num_features
        self.affine = affine
        self.eps = eps
        self.momentum = momentum
        self.activation = activation
        self.slope = slope
        if self.affine:
            self.weight = nn.Parameter(torch.ones(num_features))
            self.bias = nn.Parameter(torch.zeros(num_features))
        else:
            self.register_parameter("weight", None)
            self.register_parameter("bias", None)
        self.register_buffer("running_mean", torch.zeros(num_features))
        self.register_buffer("running_var", torch.ones(num_features))

    def forward(self, x):
        x = F.batch_norm(x, self.running_mean, self.running_var,
                         self.weight, self.bias, self.training, self.momentum, self.eps)
        if self.activation == "leaky_relu":
            return F.leaky_relu(x, negative_slope=self.slope, inplace=True)
        elif self.activation == "relu":
            return F.relu(x, inplace=True)
        elif self.activation == "elu":
            return F.elu(x, inplace=True)
        return x
''', encoding='utf-8')

    transforms_path = SCHP_DIR / "schp_transforms.py"
    if not transforms_path.exists():
        print("[SEG] Création schp_transforms.py...")
        transforms_path.write_text('''"""Affine transform utilities for SCHP."""
import numpy as np
import cv2

def get_affine_transform(center, scale, rot, output_size,
                         shift=np.array([0, 0], dtype=np.float32), inv=0):
    if not isinstance(scale, np.ndarray) and not isinstance(scale, list):
        scale = np.array([scale, scale])
    scale_tmp = scale
    src_w = scale_tmp[0]
    dst_w = output_size[1]
    dst_h = output_size[0]
    rot_rad = np.pi * rot / 180
    sn, cs = np.sin(rot_rad), np.cos(rot_rad)
    src_dir = [0 * cs - (src_w * -0.5) * sn, 0 * sn + (src_w * -0.5) * cs]
    dst_dir = np.array([0, (dst_w - 1) * -0.5], np.float32)
    src = np.zeros((3, 2), dtype=np.float32)
    dst = np.zeros((3, 2), dtype=np.float32)
    src[0, :] = center + scale_tmp * shift
    src[1, :] = center + np.array(src_dir, dtype=np.float32) + scale_tmp * shift
    dst[0, :] = [(dst_w - 1) * 0.5, (dst_h - 1) * 0.5]
    dst[1, :] = np.array([(dst_w - 1) * 0.5, (dst_h - 1) * 0.5]) + dst_dir
    direct_s = src[0, :] - src[1, :]
    src[2, :] = src[1, :] + np.array([-direct_s[1], direct_s[0]], dtype=np.float32)
    direct_d = dst[0, :] - dst[1, :]
    dst[2, :] = dst[1, :] + np.array([-direct_d[1], direct_d[0]], dtype=np.float32)
    if inv:
        trans = cv2.getAffineTransform(np.float32(dst), np.float32(src))
    else:
        trans = cv2.getAffineTransform(np.float32(src), np.float32(dst))
    return trans

def transform_logits(logits, center, scale, width, height, input_size):
    trans = get_affine_transform(center, scale, 0, input_size, inv=1)
    channel = logits.shape[2]
    target_logits = []
    for i in range(channel):
        target_logit = cv2.warpAffine(logits[:, :, i], trans, (int(width), int(height)),
                                      flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0))
        target_logits.append(target_logit)
    return np.stack(target_logits, axis=2)
''', encoding='utf-8')

    network_path = SCHP_DIR / "schp_network.py"
    if not network_path.exists():
        print("[SEG] Création schp_network.py...")
        network_path.write_text('''"""SCHP AugmentCE2P network (ResNet-101 + PSP + Edge + Decoder)."""
import functools
import torch
import torch.nn as nn
from torch.nn import functional as F
from schp_modules import InPlaceABNSync

BatchNorm2d = functools.partial(InPlaceABNSync, activation="none")

def conv3x3(in_planes, out_planes, stride=1):
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride, padding=1, bias=False)

class Bottleneck(nn.Module):
    expansion = 4
    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None, fist_dilation=1, multi_grid=1):
        super().__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=stride,
                               padding=dilation * multi_grid, dilation=dilation * multi_grid, bias=False)
        self.bn2 = BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = BatchNorm2d(planes * 4)
        self.relu = nn.ReLU(inplace=False)
        self.relu_inplace = nn.ReLU(inplace=True)
        self.downsample = downsample
    def forward(self, x):
        residual = x
        out = self.relu(self.bn1(self.conv1(x)))
        out = self.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        if self.downsample is not None:
            residual = self.downsample(x)
        return self.relu_inplace(out + residual)

class PSPModule(nn.Module):
    def __init__(self, features, out_features=512, sizes=(1, 2, 3, 6)):
        super().__init__()
        self.stages = nn.ModuleList([self._make_stage(features, out_features, s) for s in sizes])
        self.bottleneck = nn.Sequential(
            nn.Conv2d(features + len(sizes) * out_features, out_features, kernel_size=3, padding=1, bias=False),
            InPlaceABNSync(out_features))
    def _make_stage(self, features, out_features, size):
        return nn.Sequential(nn.AdaptiveAvgPool2d((size, size)),
                             nn.Conv2d(features, out_features, kernel_size=1, bias=False),
                             InPlaceABNSync(out_features))
    def forward(self, feats):
        h, w = feats.size(2), feats.size(3)
        priors = [F.interpolate(s(feats), size=(h, w), mode="bilinear", align_corners=True) for s in self.stages] + [feats]
        return self.bottleneck(torch.cat(priors, 1))

class Edge_Module(nn.Module):
    def __init__(self, in_fea=[256, 512, 1024], mid_fea=256, out_fea=2):
        super().__init__()
        self.conv1 = nn.Sequential(nn.Conv2d(in_fea[0], mid_fea, 1, bias=False), InPlaceABNSync(mid_fea))
        self.conv2 = nn.Sequential(nn.Conv2d(in_fea[1], mid_fea, 1, bias=False), InPlaceABNSync(mid_fea))
        self.conv3 = nn.Sequential(nn.Conv2d(in_fea[2], mid_fea, 1, bias=False), InPlaceABNSync(mid_fea))
        self.conv4 = nn.Conv2d(mid_fea, out_fea, 3, padding=1, bias=True)
        self.conv5 = nn.Conv2d(out_fea * 3, out_fea, 1, bias=True)
    def forward(self, x1, x2, x3):
        _, _, h, w = x1.size()
        e1_fea = self.conv1(x1); e1 = self.conv4(e1_fea)
        e2_fea = self.conv2(x2); e2 = self.conv4(e2_fea)
        e3_fea = self.conv3(x3); e3 = self.conv4(e3_fea)
        e2_fea = F.interpolate(e2_fea, (h, w), mode="bilinear", align_corners=True)
        e3_fea = F.interpolate(e3_fea, (h, w), mode="bilinear", align_corners=True)
        e2 = F.interpolate(e2, (h, w), mode="bilinear", align_corners=True)
        e3 = F.interpolate(e3, (h, w), mode="bilinear", align_corners=True)
        edge = self.conv5(torch.cat([e1, e2, e3], 1))
        edge_fea = torch.cat([e1_fea, e2_fea, e3_fea], 1)
        return edge, edge_fea

class Decoder_Module(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        self.conv1 = nn.Sequential(nn.Conv2d(512, 256, 1, bias=False), InPlaceABNSync(256))
        self.conv2 = nn.Sequential(nn.Conv2d(256, 48, 1, bias=False), InPlaceABNSync(48))
        self.conv3 = nn.Sequential(nn.Conv2d(304, 256, 1, bias=False), InPlaceABNSync(256),
                                   nn.Conv2d(256, 256, 1, bias=False), InPlaceABNSync(256))
        self.conv4 = nn.Conv2d(256, num_classes, 1, bias=True)
    def forward(self, xt, xl):
        _, _, h, w = xl.size()
        xt = F.interpolate(self.conv1(xt), (h, w), mode="bilinear", align_corners=True)
        xl = self.conv2(xl)
        x = self.conv3(torch.cat([xt, xl], 1))
        return self.conv4(x), x

class ResNet(nn.Module):
    def __init__(self, block, layers, num_classes):
        self.inplanes = 128
        super().__init__()
        self.conv1 = conv3x3(3, 64, stride=2)
        self.bn1 = BatchNorm2d(64)
        self.relu1 = nn.ReLU(inplace=False)
        self.conv2 = conv3x3(64, 64)
        self.bn2 = BatchNorm2d(64)
        self.relu2 = nn.ReLU(inplace=False)
        self.conv3 = conv3x3(64, 128)
        self.bn3 = BatchNorm2d(128)
        self.relu3 = nn.ReLU(inplace=False)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=1, dilation=2, multi_grid=(1, 1, 1))
        self.context_encoding = PSPModule(2048, 512)
        self.edge = Edge_Module()
        self.decoder = Decoder_Module(num_classes)
        self.fushion = nn.Sequential(nn.Conv2d(1024, 256, 1, bias=False), InPlaceABNSync(256),
                                     nn.Dropout2d(0.1), nn.Conv2d(256, num_classes, 1, bias=True))
    def _make_layer(self, block, planes, blocks, stride=1, dilation=1, multi_grid=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(nn.Conv2d(self.inplanes, planes * block.expansion, 1, stride=stride, bias=False),
                                       BatchNorm2d(planes * block.expansion))
        layers = []
        mg = lambda idx, g: g[idx % len(g)] if isinstance(g, tuple) else 1
        layers.append(block(self.inplanes, planes, stride, dilation=dilation, downsample=downsample, multi_grid=mg(0, multi_grid)))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, dilation=dilation, multi_grid=mg(i, multi_grid)))
        return nn.Sequential(*layers)
    def forward(self, x):
        x = self.relu1(self.bn1(self.conv1(x)))
        x = self.relu2(self.bn2(self.conv2(x)))
        x = self.relu3(self.bn3(self.conv3(x)))
        x = self.maxpool(x)
        x2 = self.layer1(x)
        x3 = self.layer2(x2)
        x4 = self.layer3(x3)
        x5 = self.layer4(x4)
        x = self.context_encoding(x5)
        parsing_result, parsing_fea = self.decoder(x, x2)
        edge_result, edge_fea = self.edge(x2, x3, x4)
        x = torch.cat([parsing_fea, edge_fea], 1)
        fusion_result = self.fushion(x)
        return [[parsing_result, fusion_result], [edge_result]]

def init_schp_model(num_classes=18):
    return ResNet(Bottleneck, [3, 4, 23, 3], num_classes)
''', encoding='utf-8')

    print("[SEG] Fichiers SCHP prêts")


def load_schp_segmenter():
    """Charge le modèle SCHP (ResNet-101 + PSP + Edge + Decoder)."""
    global _schp_segmenter

    if _schp_segmenter is not None:
        return _schp_segmenter

    import torch
    from collections import OrderedDict

    vinfo = SEGFORMER_VARIANT_CLASSES['schp']
    checkpoint_url = vinfo['checkpoint_url']
    checkpoint_file = vinfo['checkpoint_file']

    # S'assurer que les fichiers Python SCHP existent
    _publish_asset_download_progress("prepare_assets", 1, 3, "Préparation des fichiers SCHP...")
    _ensure_schp_files()
    _publish_asset_download_progress("prepare_assets", 3, 3, "Fichiers SCHP prêts")

    # Télécharger le checkpoint si nécessaire
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path = CHECKPOINTS_DIR / checkpoint_file

    if not checkpoint_path.exists():
        print(f"[SEG] Téléchargement SCHP ATR (~267MB)...")
        try:
            download_checkpoint(
                checkpoint_url,
                checkpoint_file,
                progress_label="SCHP ATR",
                progress_phase="download_schp",
            )
            print(f"[SEG] SCHP ATR téléchargé")
        except Exception as e:
            print(f"[SEG] Erreur téléchargement direct: {e}, fallback Hugging Face Hub...")
            _publish_asset_download_progress(
                "download_schp",
                1,
                100,
                "Téléchargement SCHP ATR via Hugging Face...",
            )
            from huggingface_hub import hf_hub_download
            downloaded = hf_hub_download(
                repo_id="levihsu/OOTDiffusion",
                filename="checkpoints/humanparsing/exp-schp-201908301523-atr.pth",
            )
            # Copier du cache HF vers checkpoints/
            import shutil
            shutil.copy2(str(downloaded), str(checkpoint_path))
            _publish_asset_download_progress(
                "download_schp",
                100,
                100,
                "SCHP ATR téléchargé",
            )

    device = get_device()
    print(f"[SEG] Chargement SCHP sur {device}...")

    try:
        import importlib.util
        import sys

        # Charger schp_modules d'abord (dépendance de schp_network)
        mod_spec = importlib.util.spec_from_file_location("schp_modules", str(SCHP_DIR / "schp_modules.py"))
        schp_modules = importlib.util.module_from_spec(mod_spec)
        sys.modules["schp_modules"] = schp_modules
        mod_spec.loader.exec_module(schp_modules)

        # Charger schp_network
        net_spec = importlib.util.spec_from_file_location("schp_network", str(SCHP_DIR / "schp_network.py"))
        schp_network = importlib.util.module_from_spec(net_spec)
        net_spec.loader.exec_module(schp_network)

        model = schp_network.init_schp_model(num_classes=18)

        # Charger les poids (retirer le préfixe 'module.' du DataParallel)
        state_dict = torch.load(str(checkpoint_path), map_location='cpu')
        if 'state_dict' in state_dict:
            state_dict = state_dict['state_dict']
        new_state_dict = OrderedDict()
        for k, v in state_dict.items():
            name = k[7:] if k.startswith('module.') else k
            new_state_dict[name] = v
        # Materialize meta tensors → real (empty) tensors on CPU first.
        # load_state_dict(assign=True) only replaces params IN the dict,
        # but BatchNorm buffers (running_mean/var/num_batches) stay meta → crash on .to().
        # to_empty() materializes ALL params+buffers, then load_state_dict fills the real weights.
        model = model.to_empty(device='cpu')
        model.load_state_dict(new_state_dict, strict=False)
        # Force float32 explicitement (TORCH_DTYPE peut être bf16 sur GPU Ampere+ ≥16GB)
        model = model.to(device=device, dtype=torch.float32)
        model.eval()

        _schp_segmenter = {
            'model': model,
            'device': device,
        }

        print(f"[SEG] SCHP (82% mIoU) loaded on {device}")
        return _schp_segmenter

    except Exception as e:
        print(f"[SEG] Erreur chargement SCHP: {e}")
        import traceback
        traceback.print_exc()
        raise


def segment_schp(image: Image.Image, include_classes: list = None, double_pass: bool = False) -> Image.Image:
    """
    Segmente avec SCHP (Self-Correction Human Parsing, 82% mIoU).

    Args:
        image: Image PIL
        include_classes: Liste des classes à inclure (défaut: clothes)

    Returns:
        Masque grayscale (L)
    """
    cv2 = _get_cv2()
    if cv2 is None:
        print("[SEG] cv2 unavailable, returning full mask (schp)")
        return Image.new("L", image.size, 255)
    import torch
    import torchvision.transforms as transforms

    segmenter = load_schp_segmenter()
    model = segmenter['model']
    device = segmenter['device']
    class_names = SEGFORMER_VARIANT_CLASSES['schp']['class_names']

    if include_classes is None:
        include_classes = get_classes_for_strategy('clothes')

    # Garantir RGB
    if image.mode != "RGB":
        image = image.convert("RGB")

    original_size = image.size  # (W, H)
    w, h = original_size

    # Preprocessing: BGR + affine transform + normalisation
    import importlib.util, sys
    if "schp_transforms" not in sys.modules:
        tr_spec = importlib.util.spec_from_file_location("schp_transforms", str(SCHP_DIR / "schp_transforms.py"))
        schp_tr = importlib.util.module_from_spec(tr_spec)
        sys.modules["schp_transforms"] = schp_tr
        tr_spec.loader.exec_module(schp_tr)
    from schp_transforms import get_affine_transform, transform_logits

    img_bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    input_size = [512, 512]

    # Center-scale affine transform
    aspect_ratio = input_size[1] / input_size[0]
    center = np.array([w / 2, h / 2], dtype=np.float32)
    scale = np.array([w, h], dtype=np.float32)
    if w > aspect_ratio * h:
        scale[1] = w / aspect_ratio
    elif w < aspect_ratio * h:
        scale[0] = h * aspect_ratio

    trans = get_affine_transform(center, scale, 0, input_size)
    input_img = cv2.warpAffine(
        img_bgr, trans, (input_size[1], input_size[0]),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0)
    )

    # Normalisation BGR (ImageNet BGR order)
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.406, 0.456, 0.485], std=[0.225, 0.224, 0.229])
    ])
    input_tensor = transform(input_img).unsqueeze(0)

    # Inference
    with torch.no_grad():
        output = model(input_tensor.to(device))
        # output[0][-1] = fusion result (meilleur), shape [1, num_classes, H/4, W/4]
        upsample = torch.nn.Upsample(size=input_size, mode='bilinear', align_corners=True)
        upsample_output = upsample(output[0][-1][0].unsqueeze(0))
        upsample_output = upsample_output.squeeze().permute(1, 2, 0)  # CHW -> HWC

        logits_np = upsample_output.cpu().numpy()

    # Inverse affine transform pour retrouver la taille originale
    logits = transform_logits(logits_np, center, scale, w, h, input_size=input_size)
    pred = np.argmax(logits, axis=2)  # [H, W], values 0-17

    # === PASSE 1: Argmax strict ===
    mask = np.zeros(pred.shape, dtype=np.uint8)
    for class_id in include_classes:
        mask[pred == class_id] = 255

    found_classes = []
    for class_id in include_classes:
        if np.any(pred == class_id):
            found_classes.append(class_names.get(class_id, str(class_id)))

    pass1_pct = np.sum(mask > 0) / pred.size * 100
    print(f"[SCHP] Passe 1 (argmax): {', '.join(found_classes) if found_classes else 'aucun'} ({pass1_pct:.1f}%)")

    # === PASSE 2: Softmax — capter les vêtements incertains adjacents ===
    if double_pass and np.any(mask > 0):
        from scipy.special import softmax as sp_softmax
        # logits shape: [H, W, num_classes] (déjà transformé en espace image)
        probs = sp_softmax(logits, axis=2)

        # Somme des probabilités de toutes les classes vêtement
        clothes_prob = np.zeros(pred.shape, dtype=np.float32)
        for class_id in include_classes:
            if class_id < probs.shape[2]:
                clothes_prob += probs[:, :, class_id]

        # Pixels incertains : prob vêtement > 25% mais argmax dit autre chose
        uncertain = (clothes_prob > 0.25) & (mask == 0)

        # Ne garder que les pixels adjacents au masque passe 1
        adj_kernel = np.ones((20, 20), np.uint8)
        clothes_zone = cv2.dilate(mask, adj_kernel, iterations=1)
        adjacent_uncertain = uncertain & (clothes_zone > 0)

        n_added = np.sum(adjacent_uncertain)
        if n_added > 0:
            mask[adjacent_uncertain] = 255
            added_pct = n_added / pred.size * 100
            print(f"[SCHP] Passe 2 (softmax): +{n_added} pixels récupérés ({added_pct:.1f}%) — vêtements incertains adjacents")
        else:
            print(f"[SCHP] Passe 2 (softmax): rien de plus à récupérer")

    # Stats finales
    clothes_pixels = np.sum(mask > 0)
    total_pixels = mask.shape[0] * mask.shape[1]
    ratio = clothes_pixels / total_pixels * 100

    from core.log_utils import row
    row("Model", "SCHP (82% mIoU)")
    row("Classes", f"{', '.join(found_classes) if found_classes else 'aucun'} ({ratio:.1f}%)")

    # Légère dilatation pour couvrir les bords
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)

    return Image.fromarray(mask, mode="L")


# ============================================================
# GroundingDINO - Segmentation par texte (gardé)
# ============================================================

def load_grounding_dino():
    """Charge le modele GroundingDINO"""
    global _grounding_dino_model

    if _grounding_dino_model is not None:
        return _grounding_dino_model

    try:
        import torch

        checkpoint_path = download_checkpoint(
            GROUNDING_DINO_CHECKPOINT_URL,
            GROUNDING_DINO_CHECKPOINT_NAME
        )

        import groundingdino
        package_dir = Path(groundingdino.__file__).parent
        config_path = package_dir / "config" / "GroundingDINO_SwinT_OGC.py"

        if not config_path.exists():
            alt_paths = [
                Path("GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"),
                CHECKPOINTS_DIR / "GroundingDINO_SwinT_OGC.py"
            ]
            for alt in alt_paths:
                if alt.exists():
                    config_path = alt
                    break

        device = get_device()

        from groundingdino.util.slconfig import SLConfig
        from groundingdino.models import build_model
        from groundingdino.util.utils import clean_state_dict

        args = SLConfig.fromfile(str(config_path))
        args.device = "cpu"

        _grounding_dino_model = build_model(args)

        checkpoint = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
        state_dict = clean_state_dict(checkpoint["model"])
        _grounding_dino_model.load_state_dict(state_dict, strict=False, assign=True)

        # Quantification int8 si GPU disponible (~700MB → ~350MB)
        quantized = False
        if device != "cpu":
            try:
                from optimum.quanto import quantize, freeze, qint8
                quantize(_grounding_dino_model, weights=qint8)
                freeze(_grounding_dino_model)
                quantized = True
            except Exception:
                pass

        _grounding_dino_model = _grounding_dino_model.to(device)
        _grounding_dino_model.eval()

        q_str = " (int8)" if quantized else ""
        print(f"[SEG] GroundingDINO loaded on {device}{q_str}")
        return _grounding_dino_model

    except Exception as e:
        print(f"[SEGMENTATION] Erreur chargement GroundingDINO: {e}")
        raise


def _format_grounding_prompt(prompt: str) -> str:
    """Formate le prompt pour GroundingDINO."""
    prompt = prompt.strip().lower()
    for sep in [',', ';', '/', '|', ' and ', ' et ']:
        prompt = prompt.replace(sep, '.')
    while '..' in prompt:
        prompt = prompt.replace('..', '.')
    prompt = prompt.strip('.')
    if prompt and not prompt.endswith('.'):
        prompt = prompt + '.'
    return prompt


def segment_grounding_dino(
    image: Image.Image,
    prompt: str,
    box_threshold: float = 0.35,
    text_threshold: float = 0.30
) -> Image.Image:
    """
    Segmente avec GroundingDINO (sans SAM - masque basé sur bounding boxes).

    Returns:
        Masque grayscale (L) ou les zones detectees sont blanches
    """
    from groundingdino.util.inference import predict
    import torch

    dino_model = load_grounding_dino()
    formatted_prompt = _format_grounding_prompt(prompt)

    img_array = np.array(image.convert("RGB"))

    import groundingdino.datasets.transforms as T
    transform = T.Compose([
        T.RandomResize([800], max_size=1333),
        T.ToTensor(),
        T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

    image_transformed, _ = transform(image.convert("RGB"), None)

    boxes, logits, phrases = predict(
        model=dino_model,
        image=image_transformed,
        caption=formatted_prompt,
        box_threshold=box_threshold,
        text_threshold=text_threshold
    )

    if len(boxes) == 0:
        return Image.new("L", image.size, 0)

    h, w = img_array.shape[:2]
    boxes_pixel = boxes * torch.tensor([w, h, w, h])
    boxes_pixel = boxes_pixel.cpu().numpy()

    # Create mask from bounding boxes (filled rectangles with feathering)
    combined_mask = np.zeros((h, w), dtype=np.uint8)

    for i, box in enumerate(boxes_pixel):
        cx, cy, bw, bh = box
        x1 = max(0, int(cx - bw / 2))
        y1 = max(0, int(cy - bh / 2))
        x2 = min(w, int(cx + bw / 2))
        y2 = min(h, int(cy + bh / 2))

        combined_mask[y1:y2, x1:x2] = 255

    return Image.fromarray(combined_mask, mode="L")


# ============================================================
# FACE EXCLUSION (gardé)
# ============================================================

def _exclude_face_from_mask(image: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Exclut le visage du masque en utilisant MediaPipe Face Detection.
    Utilise la nouvelle API MediaPipe Tasks (0.10+).
    """
    from PIL import ImageDraw
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python import BaseOptions
    import urllib.request

    models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "mediapipe")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "blaze_face_short_range.tflite")

    if not os.path.exists(model_path):
        print("[MEDIAPIPE] Telechargement du modele face detection...")
        model_url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
        urllib.request.urlretrieve(model_url, model_path)

    img_rgb = np.array(image.convert("RGB"))
    h, w = img_rgb.shape[:2]

    base_options = BaseOptions(model_asset_path=model_path)
    options = vision.FaceDetectorOptions(base_options=base_options, min_detection_confidence=0.5)

    with vision.FaceDetector.create_from_options(options) as detector:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        results = detector.detect(mp_image)

        if not results.detections:
            from core.log_utils import row
            row("Face", "aucun visage -> Pose fallback")
            return _exclude_head_from_pose(image, mask)

        from core.log_utils import row
        row("Face", f"{len(results.detections)} exclu (MediaPipe)")

        mask = mask.copy()
        draw = ImageDraw.Draw(mask)

        expand_factor_w = 1.6   # Largeur: 1.6x la face (oreilles sans déborder)
        hair_top = 1.2          # Vers le haut: 1.2x face_h (cheveux sans exagérer)
        chin_bottom = 0.3       # Vers le bas: 0.3x face_h sous le menton (cou, pas le buste)

        # Debug: dessiner l'exclusion sur une copie de l'image originale
        debug_img = image.copy().convert("RGBA")
        debug_overlay = Image.new("RGBA", debug_img.size, (0, 0, 0, 0))
        debug_draw = ImageDraw.Draw(debug_overlay)

        for detection in results.detections:
            bbox = detection.bounding_box
            x = bbox.origin_x
            y = bbox.origin_y
            face_w = bbox.width
            face_h = bbox.height

            cx = x + face_w // 2
            face_ratio = face_w / max(face_h, 1)
            new_w = int(face_w * expand_factor_w)

            # Proportions aberrantes → faux positif
            if face_ratio > 2.0:
                print(f"[FACE-EXCL] Bbox ignorée: ratio W/H={face_ratio:.2f} (trop large)")
                debug_draw.rectangle([x, y, x + face_w, y + face_h], outline=(255, 255, 0, 255), width=2)
                continue

            # Calculer la zone d'exclusion candidate
            y1 = max(0, y - int(face_h * hair_top))
            y2 = min(mask.height, y + face_h + int(face_h * chin_bottom))
            x1 = max(0, cx - new_w // 2)
            x2 = min(mask.width, cx + new_w // 2)

            # Validation: vérifier que la zone n'est pas pleine de vêtement
            # Si la zone "visage" chevauche beaucoup le masque, c'est un faux positif
            mask_array = np.array(mask)
            zone = mask_array[y1:y2, x1:x2]
            zone_pixels = zone.size
            if zone_pixels > 0:
                mask_overlap = np.sum(zone > 128) / zone_pixels
                if mask_overlap > 0.25:
                    # Plus de 25% de la zone "visage" est du vêtement → faux positif
                    print(f"[FACE-EXCL] Bbox ignorée: {mask_overlap:.0%} de la zone est du vêtement (faux positif)")
                    debug_draw.rectangle([x, y, x + face_w, y + face_h], outline=(255, 255, 0, 255), width=2)
                    continue

            draw.ellipse([x1, y1, x2, y2], fill=0)

            # Debug: zone rouge semi-transparente + bbox verte de la face originale
            debug_draw.ellipse([x1, y1, x2, y2], fill=(255, 0, 0, 100))
            debug_draw.rectangle([x, y, x + face_w, y + face_h], outline=(0, 255, 0, 255), width=2)

        # Sauvegarder le debug
        debug_img = Image.alpha_composite(debug_img, debug_overlay)
        try:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")
            os.makedirs(output_dir, exist_ok=True)
            debug_path = os.path.join(output_dir, "debug_face_exclusion.png")
            debug_img.save(debug_path)
            print(f"[DEBUG] Face exclusion sauvegardée → {debug_path}")
        except Exception as e:
            print(f"[DEBUG] Erreur sauvegarde face exclusion: {e}")

    return mask


def _exclude_head_from_pose(image: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Exclut la tête du masque en utilisant MediaPipe Pose (pour les personnes de dos).
    """
    from PIL import ImageDraw
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python import BaseOptions
    import urllib.request

    models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", "mediapipe")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, "pose_landmarker_lite.task")

    if not os.path.exists(model_path):
        model_url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
        urllib.request.urlretrieve(model_url, model_path)

    img_rgb = np.array(image.convert("RGB"))
    h, w = img_rgb.shape[:2]

    try:
        base_options = BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(base_options=base_options, num_poses=1)

        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
            results = landmarker.detect(mp_image)

            if not results.pose_landmarks or len(results.pose_landmarks) == 0:
                return mask

            landmarks = results.pose_landmarks[0]

            def lm_to_px(idx):
                lm = landmarks[idx]
                return (int(lm.x * w), int(lm.y * h))

            left_ear = lm_to_px(7)
            right_ear = lm_to_px(8)
            left_shoulder = lm_to_px(11)
            right_shoulder = lm_to_px(12)

            head_center_x = (left_ear[0] + right_ear[0]) // 2
            head_center_y = (left_ear[1] + right_ear[1]) // 2

            ear_distance = abs(right_ear[0] - left_ear[0])
            head_width = int(ear_distance * 3.5)

            shoulder_y = (left_shoulder[1] + right_shoulder[1]) // 2
            ear_to_shoulder = abs(shoulder_y - head_center_y)
            head_height = int(ear_to_shoulder * 5.5)

            min_head_size = int(min(w, h) * 0.15)
            head_width = max(head_width, min_head_size)
            head_height = max(head_height, min_head_size)

            head_center_y = head_center_y - int(head_height * 0.90)

            x1 = max(0, head_center_x - head_width // 2)
            y1 = max(0, head_center_y - head_height // 2)
            x2 = min(w, head_center_x + head_width // 2)
            y2 = min(h, head_center_y + head_height // 2)

            mask = mask.copy()
            draw = ImageDraw.Draw(mask)
            draw.ellipse([x1, y1, x2, y2], fill=0)

            return mask

    except Exception as e:
        print(f"[MEDIAPIPE] Erreur exclusion tete via Pose: {e}")
        return mask


# ============================================================
# GESTION MEMOIRE
# ============================================================

def get_segmentation_status():
    """Retourne le status des modèles de segmentation (RAM CPU)"""
    vinfo = SEGFORMER_VARIANT_CLASSES.get(_active_segformer_variant, SEGFORMER_VARIANT_CLASSES['schp'])
    return {
        'grounding_dino': _grounding_dino_model is not None,
        'segformer_single': _clothes_segmenter_b5 is not None,
        'sapiens': _sapiens_segmenter is not None,
        'schp': _schp_segmenter is not None,
        'fusion_b2': _fusion_b2_cache is not None,
        'fusion_b4': _fusion_b4_cache is not None,
        'segformer_variant': _active_segformer_variant,
        'segformer_label': vinfo['label'],
    }


def get_seg_ram_mb():
    """Retourne l'utilisation RAM des modèles de segmentation en MB (approximatif)."""
    ram = 0
    if _schp_segmenter is not None:
        ram += 80   # SCHP ~80MB
    if _clothes_segmenter_b5 is not None:
        ram += 90   # B2 ou B4 ~90MB
    if _fusion_b2_cache is not None:
        ram += 90   # B2 ~90MB
    if _fusion_b4_cache is not None:
        ram += 60   # B4 ~60MB
    if _grounding_dino_model is not None:
        ram += 170  # GroundingDINO ~170MB
    return ram


def is_grounding_dino_loaded():
    """Vérifie si GroundingDINO est chargé"""
    return _grounding_dino_model is not None


def _unload_sapiens():
    """Décharge Sapiens immédiatement après utilisation (~4.5GB VRAM)."""
    global _sapiens_segmenter
    if _sapiens_segmenter is not None:
        del _sapiens_segmenter
        _sapiens_segmenter = None
        import gc, torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[SEG] Sapiens 1B déchargé (VRAM libérée)")


# ============================================================
# FUSION MULTI-MODELES - Combine B2 + B4 + SCHP
# ============================================================

def _run_b2(image, strategy, classes, device, output_dir, save_debug):
    """Helper: exécute SegFormer B2 (thread-safe, utilise cache global)."""
    import torch
    import torch.nn.functional as F
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

    global _fusion_b2_cache
    try:
        if classes:
            b2_classes = classes
        else:
            b2_classes = SEGFORMER_VARIANT_CLASSES['b2']['strategies'].get(
                strategy, SEGFORMER_VARIANT_CLASSES['b2']['strategies']['clothes'])

        if _fusion_b2_cache is not None:
            model = _fusion_b2_cache['model']
            processor = _fusion_b2_cache['processor']
        else:
            _b2_repo = "mattmdjaga/segformer_b2_clothes"
            _publish_asset_download_progress("download_segmentation", 15, 100, "Préparation SegFormer B2...")
            try:
                processor = AutoImageProcessor.from_pretrained(_b2_repo, local_files_only=True)
            except OSError:
                _publish_asset_download_progress("download_segmentation", 20, 100, "Téléchargement SegFormer B2...")
                processor = AutoImageProcessor.from_pretrained(_b2_repo)
            try:
                model = AutoModelForSemanticSegmentation.from_pretrained(
                    _b2_repo, torch_dtype=torch.float32,
                    low_cpu_mem_usage=False, local_files_only=True,
                )
            except OSError:
                _publish_asset_download_progress("download_segmentation", 35, 100, "Téléchargement poids SegFormer B2...")
                model = AutoModelForSemanticSegmentation.from_pretrained(
                    _b2_repo, torch_dtype=torch.float32,
                    low_cpu_mem_usage=False,
                )
            # Fix meta tensors résiduels (versions transformers récentes)
            _materialize_meta_tensors(model)
            try:
                model = model.to(device=device, dtype=torch.float32).eval()
            except (NotImplementedError, RuntimeError):
                print("[SEG] B2: meta tensors persistants, to_empty fallback")
                sd = {k: v for k, v in model.state_dict().items() if not v.is_meta}
                model.to_empty(device="cpu")
                model.load_state_dict(sd, strict=False)
                model = model.to(device=device, dtype=torch.float32).eval()
            _fusion_b2_cache = {'model': model, 'processor': processor}
            print("[SEG] B2 chargé et mis en cache RAM")
            _publish_asset_download_progress("download_segmentation", 50, 100, "SegFormer B2 prêt")

        inputs = processor(images=image, return_tensors="pt")
        _model_dtype = next(model.parameters()).dtype
        inputs = {
            k: v.to(device=device, dtype=_model_dtype) if v.is_floating_point() else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits

        upsampled = F.interpolate(logits, size=image.size[::-1], mode='bilinear', align_corners=False)
        pred = upsampled.argmax(dim=1).squeeze().cpu().numpy()

        mask_b2 = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in b2_classes:
            mask_b2[pred == class_id] = 255

        # Body parts mask: peau visible (visage, cheveux, bras, jambes)
        # PAS les vêtements — ceux du fond seraient inclus sinon
        body_b2 = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in [2, 11, 12, 13, 14, 15]:  # cheveux, visage, jambes G/D, bras G/D
            body_b2[pred == class_id] = 255

        # Zone lunettes (classe 3) — à soustraire du masque final
        glasses_b2 = np.zeros(pred.shape, dtype=np.uint8)
        glasses_b2[pred == 3] = 255

        pct = np.sum(mask_b2 > 0) / mask_b2.size * 100
        if save_debug:
            Image.fromarray(mask_b2, mode="L").save(output_dir / "mask_b2.png")

        return 'b2', mask_b2, pct, body_b2, glasses_b2, None
    except Exception as e:
        print(f"[SEG] B2 ERREUR: {e}")
        _empty = np.zeros((image.height, image.width), dtype=np.uint8)
        return 'b2', _empty, 0.0, _empty, _empty, None



def _run_b4(image, strategy, classes, device, output_dir, save_debug):
    """Helper: exécute SegFormer B4 FASHN (thread-safe, utilise cache global)."""
    import torch
    import torch.nn.functional as F
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation

    global _fusion_b4_cache
    try:
        if classes:
            b4_classes = classes
        else:
            b4_classes = SEGFORMER_VARIANT_CLASSES['b4']['strategies'].get(
                strategy, SEGFORMER_VARIANT_CLASSES['b4']['strategies']['clothes'])

        if _fusion_b4_cache is not None:
            model = _fusion_b4_cache['model']
            processor = _fusion_b4_cache['processor']
        else:
            _b4_repo = "fashn-ai/fashn-human-parser"
            _publish_asset_download_progress("download_segmentation", 55, 100, "Préparation SegFormer B4...")
            try:
                processor = AutoImageProcessor.from_pretrained(_b4_repo, local_files_only=True)
            except OSError:
                _publish_asset_download_progress("download_segmentation", 60, 100, "Téléchargement SegFormer B4...")
                processor = AutoImageProcessor.from_pretrained(_b4_repo)
            try:
                model = AutoModelForSemanticSegmentation.from_pretrained(
                    _b4_repo, torch_dtype=torch.float32,
                    low_cpu_mem_usage=False, local_files_only=True,
                )
            except OSError:
                _publish_asset_download_progress("download_segmentation", 75, 100, "Téléchargement poids SegFormer B4...")
                model = AutoModelForSemanticSegmentation.from_pretrained(
                    _b4_repo, torch_dtype=torch.float32,
                    low_cpu_mem_usage=False,
                )
            # Fix meta tensors résiduels (versions transformers récentes)
            _materialize_meta_tensors(model)
            try:
                model = model.to(device=device, dtype=torch.float32).eval()
            except (NotImplementedError, RuntimeError):
                print("[SEG] B4: meta tensors persistants, to_empty fallback")
                sd = {k: v for k, v in model.state_dict().items() if not v.is_meta}
                model.to_empty(device="cpu")
                model.load_state_dict(sd, strict=False)
                model = model.to(device=device, dtype=torch.float32).eval()
            _fusion_b4_cache = {'model': model, 'processor': processor}
            print("[SEG] B4 chargé et mis en cache RAM")
            _publish_asset_download_progress("download_segmentation", 90, 100, "SegFormer B4 prêt")

        inputs = processor(images=image, return_tensors="pt")
        _model_dtype = next(model.parameters()).dtype
        inputs = {
            k: v.to(device=device, dtype=_model_dtype) if v.is_floating_point() else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits

        upsampled = F.interpolate(logits, size=image.size[::-1], mode='bilinear', align_corners=False)
        pred = upsampled.argmax(dim=1).squeeze().cpu().numpy()

        mask_b4 = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in b4_classes:
            mask_b4[pred == class_id] = 255

        # Body parts mask: peau visible (visage, cheveux, bras, jambes, torse, pieds, mains)
        body_b4 = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in [1, 2, 12, 13, 14, 15, 16]:  # visage, cheveux, bras, mains, jambes, pieds, torse
            body_b4[pred == class_id] = 255

        # Zone lunettes (classe 11 pour B4)
        glasses_b4 = np.zeros(pred.shape, dtype=np.uint8)
        glasses_b4[pred == 11] = 255

        # Zone mains (classe 13) — pour exclure téléphones tenus en main
        hands_b4 = np.zeros(pred.shape, dtype=np.uint8)
        hands_b4[pred == 13] = 255

        pct = np.sum(mask_b4 > 0) / mask_b4.size * 100
        if save_debug:
            Image.fromarray(mask_b4, mode="L").save(output_dir / "mask_b4.png")

        return 'b4', mask_b4, pct, body_b4, glasses_b4, hands_b4
    except Exception as e:
        print(f"[SEG] B4 ERREUR: {e}")
        _empty = np.zeros((image.height, image.width), dtype=np.uint8)
        return 'b4', _empty, 0.0, _empty, _empty, _empty


def _run_schp(image, strategy, classes, output_dir, save_debug):
    """Helper: exécute SCHP (thread-safe, utilise cache global)."""
    cv2 = _get_cv2()
    if cv2 is None:
        return Image.new("L", image.size, 0)
    import torch

    try:
        if classes:
            schp_classes = classes
        else:
            schp_classes = SEGFORMER_VARIANT_CLASSES['schp']['strategies'].get(
                strategy, SEGFORMER_VARIANT_CLASSES['schp']['strategies']['clothes'])

        segmenter = load_schp_segmenter()
        model = segmenter['model']
        schp_device = segmenter['device']

        import importlib.util, sys
        if "schp_transforms" not in sys.modules:
            tr_spec = importlib.util.spec_from_file_location("schp_transforms", str(SCHP_DIR / "schp_transforms.py"))
            schp_tr = importlib.util.module_from_spec(tr_spec)
            sys.modules["schp_transforms"] = schp_tr
            tr_spec.loader.exec_module(schp_tr)
        from schp_transforms import get_affine_transform, transform_logits

        import torchvision.transforms as transforms

        w, h = image.size
        img_bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        input_size = [512, 512]

        aspect_ratio = input_size[1] / input_size[0]
        center = np.array([w / 2, h / 2], dtype=np.float32)
        scale = np.array([w, h], dtype=np.float32)
        if w > aspect_ratio * h:
            scale[1] = w / aspect_ratio
        elif w < aspect_ratio * h:
            scale[0] = h * aspect_ratio

        trans = get_affine_transform(center, scale, 0, input_size)
        input_img = cv2.warpAffine(img_bgr, trans, (input_size[1], input_size[0]),
                                   flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.406, 0.456, 0.485], std=[0.225, 0.224, 0.229])
        ])
        input_tensor = transform(input_img).unsqueeze(0)

        with torch.no_grad():
            output = model(input_tensor.to(device=schp_device, dtype=torch.float32))
            upsample = torch.nn.Upsample(size=input_size, mode='bilinear', align_corners=True)
            upsample_output = upsample(output[0][-1][0].unsqueeze(0))
            upsample_output = upsample_output.squeeze().permute(1, 2, 0)
            logits_np = upsample_output.cpu().numpy()

        logits = transform_logits(logits_np, center, scale, w, h, input_size=input_size)
        pred = np.argmax(logits, axis=2)

        mask_schp = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in schp_classes:
            mask_schp[pred == class_id] = 255

        # Body parts mask: peau visible (visage, cheveux, bras, jambes)
        body_schp = np.zeros(pred.shape, dtype=np.uint8)
        for class_id in [2, 11, 12, 13, 14, 15]:  # cheveux, visage, jambes G/D, bras G/D
            body_schp[pred == class_id] = 255

        # Zone lunettes (classe 3 pour SCHP/ATR)
        glasses_schp = np.zeros(pred.shape, dtype=np.uint8)
        glasses_schp[pred == 3] = 255

        pct = np.sum(mask_schp > 0) / mask_schp.size * 100
        if save_debug:
            Image.fromarray(mask_schp, mode="L").save(output_dir / "mask_schp.png")

        return 'schp', mask_schp, pct, body_schp, glasses_schp, None
    except Exception as e:
        print(f"[SEG] SCHP ERREUR: {e}")
        _empty = np.zeros((image.height, image.width), dtype=np.uint8)
        return 'schp', _empty, 0.0, _empty, _empty, None


def _filter_fusion_outliers(masks: dict, row=None) -> tuple[dict, dict]:
    """Filtre les sorties incohérentes sans prendre un modèle à 0% comme référence.

    B4 est généralement fiable, mais il peut échouer franchement sur certains
    vêtements discrets. Avant ce garde-fou, un B4 à 0% faisait supprimer B2 et
    SCHP, donnant un masque vide malgré des vêtements détectés.
    """
    log_row = row or (lambda *_args, **_kwargs: None)
    filtered = dict(masks)
    pcts = {
        variant: (np.sum(mask > 0) / mask.size * 100 if mask is not None and mask.size else 0.0)
        for variant, mask in masks.items()
    }

    MIN_SIGNAL = 0.2
    OUTLIER_RATIO = 2.5
    B2_B4_MAX_DIFF = 2.0

    positive_variants = [variant for variant, pct in pcts.items() if pct > MIN_SIGNAL]
    if len(positive_variants) >= 2:
        avg_positive = sum(pcts[v] for v in positive_variants) / len(positive_variants)
        for variant, pct in list(pcts.items()):
            if variant in filtered and pct <= MIN_SIGNAL:
                log_row(variant.upper(), f"IGNORÉ (échec: {pct:.1f}% vs autres {avg_positive:.1f}%)")
                del filtered[variant]

    for variant in list(filtered.keys()):
        pct = pcts.get(variant, 0.0)
        others = [
            pcts[other]
            for other in filtered.keys()
            if other != variant and pcts.get(other, 0.0) > MIN_SIGNAL
        ]
        if len(others) < 2:
            continue
        avg_others = sum(others) / len(others)
        if avg_others > 0 and pct > OUTLIER_RATIO * avg_others:
            log_row(variant.upper(), f"IGNORÉ (hallucine: {pct:.1f}% vs moyenne autres {avg_others:.1f}%)")
            del filtered[variant]

    # B4 est une bonne référence seulement quand il a vraiment détecté quelque chose.
    if (
        'b2' in filtered
        and 'b4' in filtered
        and pcts.get('b4', 0.0) > MIN_SIGNAL
        and pcts.get('b2', 0.0) > pcts.get('b4', 0.0) + B2_B4_MAX_DIFF
    ):
        log_row("B2", f"IGNORÉ (sur-détecte: {pcts['b2']:.1f}% vs B4 {pcts['b4']:.1f}%)")
        del filtered['b2']

    return filtered, pcts


def segment_fusion(image: Image.Image, strategy: str = 'clothes', include_classes_override: list = None, save_debug: bool = True) -> Image.Image:
    """
    Segmentation fusion parallèle: combine B2, B4 et SCHP pour un masque optimal.

    Les 3 modèles tournent en parallèle via ThreadPoolExecutor(3), puis on fusionne (union).
    ~2-3x plus rapide que séquentiel.

    Args:
        image: Image PIL
        strategy: Nom de la stratégie ('clothes', 'person', 'body', etc.)
        include_classes_override: Override des classes (sinon utilise la stratégie de chaque modèle)
        save_debug: Sauvegarder les masques debug (défaut True)

    Returns:
        Masque fusionné et dilaté (L)
    """
    cv2 = _get_cv2()
    if cv2 is None:
        print("[SEG] cv2 unavailable, returning full mask (fusion)")
        return Image.new("L", image.size, 255)
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
    from pathlib import Path
    from core.log_utils import header, row, footer

    header("FUSION SEGMENTATION (parallèle)")
    _publish_asset_download_progress(
        "segment_fusion",
        1,
        4,
        "Fusion segmentation B2/B4/SCHP en cours...",
    )

    if image.mode != "RGB":
        image = image.convert("RGB")

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    device = get_device()
    masks = {}
    body_masks = {}
    glasses_masks = {}
    hands_mask = None
    try:
        from core.models.runtime_env import get_segmentation_fusion_timeout_seconds
        fusion_timeout = get_segmentation_fusion_timeout_seconds()
    except Exception:
        fusion_timeout = 180.0

    # Lancer B2 + B4 + SCHP en parallèle
    # Chaque modèle résout ses propres classes pour la stratégie donnée
    # Restore clean register_parameter before parallel loading (prevents race condition)
    try:
        from core.models.manager import _restore_register_parameter
        _restore_register_parameter()
    except ImportError:
        pass

    completed_count = 0
    executor = ThreadPoolExecutor(max_workers=3)
    try:
        futures = {
            executor.submit(_run_b2, image, strategy, include_classes_override, device, output_dir, save_debug): 'b2',
            executor.submit(_run_b4, image, strategy, include_classes_override, device, output_dir, save_debug): 'b4',
            executor.submit(_run_schp, image, strategy, include_classes_override, output_dir, save_debug): 'schp',
        }

        try:
            for future in as_completed(futures, timeout=fusion_timeout):
                expected_variant = futures.get(future, "?")
                try:
                    variant, mask_array, pct, body_array, glasses_array, hands_array = future.result()
                except Exception as exc:
                    row(expected_variant.upper(), f"ERREUR ({exc})")
                    continue

                masks[variant] = mask_array
                body_masks[variant] = body_array
                glasses_masks[variant] = glasses_array
                if hands_array is not None:
                    hands_mask = hands_array
                completed_count += 1
                row(variant.upper(), f"{pct:.1f}% détecté")
                _publish_asset_download_progress(
                    "segment_fusion",
                    min(3, completed_count + 1),
                    4,
                    f"{variant.upper()} prêt ({completed_count}/3)",
                )
        except FuturesTimeoutError:
            pending = [name.upper() for future, name in futures.items() if not future.done()]
            for future in futures:
                if not future.done():
                    future.cancel()
            pending_text = ", ".join(pending) if pending else "inconnu"
            used_text = ", ".join(name.upper() for name in masks.keys()) or "aucun"
            row("Timeout", f"{fusion_timeout:.0f}s: fallback partiel ({used_text}), pending {pending_text}")
            _publish_asset_download_progress(
                "segment_fusion",
                4,
                4,
                f"Segmentation partielle utilisée ({used_text})",
            )
    finally:
        # Do not wait forever for a stuck HF/CUDA worker. Running threads cannot
        # be killed safely, but the request can continue with partial masks.
        executor.shutdown(wait=False, cancel_futures=True)

    # Restore clean register_parameter after parallel loading
    try:
        from core.models.manager import _restore_register_parameter
        _restore_register_parameter()
    except ImportError:
        pass

    if not masks:
        row("Fallback", "aucun modèle disponible à temps → masque complet")
        _publish_asset_download_progress(
            "segment_fusion",
            4,
            4,
            "Segmentation indisponible, fallback masque complet",
        )
        footer()
        return Image.new("L", image.size, 255)

    # === OUTLIER FILTER ===
    masks, pcts = _filter_fusion_outliers(masks, row=row)

    # === FUSION (union de tous les masques) ===
    _used = ", ".join(k.upper() for k in masks.keys())
    row("Fusion", f"Union {_used}...")

    fused_mask = np.zeros((image.height, image.width), dtype=np.uint8)
    for variant, mask in masks.items():
        fused_mask = np.maximum(fused_mask, mask)

    # === PERSON FILTER (composantes connexes) ===
    # Les vêtements de la personne sont CONNECTÉS à son corps (visage, cheveux, peau).
    # Les vêtements du fond (lit, chaise) sont DÉCONNECTÉS.
    # On garde uniquement les composantes du masque vêtements qui touchent le corps.
    body_zone = np.zeros((image.height, image.width), dtype=np.uint8)
    for variant, body in body_masks.items():
        body_zone = np.maximum(body_zone, body)

    if np.any(body_zone > 0):
        # Dilater le body_zone pour créer un pont entre peau et vêtements portés
        # (~30px suffit — les vêtements touchent le corps)
        _k_body = np.ones((7, 7), np.uint8)
        body_dilated = cv2.dilate(body_zone, _k_body, iterations=4)  # ~28px

        # Composantes connexes du masque vêtements
        _num_labels, _labels = cv2.connectedComponents(fused_mask)
        _before_pct = np.sum(fused_mask > 0) / fused_mask.size * 100
        filtered_mask = np.zeros_like(fused_mask)
        _kept = 0
        _removed_comps = 0

        for label_id in range(1, _num_labels):  # skip 0 (fond)
            component = (_labels == label_id)
            # Garder si la composante touche le body dilaté
            if np.any(component & (body_dilated > 0)):
                filtered_mask[component] = 255
                _kept += 1
            else:
                _removed_comps += 1

        fused_mask = filtered_mask
        _after_pct = np.sum(fused_mask > 0) / fused_mask.size * 100
        _removed_pct = _before_pct - _after_pct
        if _removed_comps > 0:
            row("Person", f"Fond filtré: {_removed_comps} composante(s) retirée(s), -{_removed_pct:.1f}%")
        else:
            row("Person", f"Toutes les {_kept} composantes connectées au corps")
        if save_debug:
            Image.fromarray(body_dilated, mode="L").save(output_dir / "mask_person_zone.png")
    else:
        row("Person", "Pas de corps détecté (skip filtre)")

    # === GLASSES & HANDS EXCLUSION ===
    # Pour 'person' strategy, on veut TOUT inclure (lunettes, mains, sac)
    # Pour 'clothes' et autres, exclure lunettes et mains (téléphones/objets)
    _is_person_strategy = strategy in ('person', 'body')

    if not _is_person_strategy:
        # GLASSES: Soustraire les zones détectées comme lunettes par au moins 1 modèle
        glasses_zone = np.zeros((image.height, image.width), dtype=np.uint8)
        for variant, glasses in glasses_masks.items():
            glasses_zone = np.maximum(glasses_zone, glasses)
        if np.any(glasses_zone > 0):
            _k_gl = np.ones((5, 5), np.uint8)
            glasses_zone = cv2.dilate(glasses_zone, _k_gl, iterations=2)  # ~10px
            _gl_pct = np.sum((fused_mask > 0) & (glasses_zone > 0)) / fused_mask.size * 100
            fused_mask[glasses_zone > 0] = 0
            if _gl_pct > 0.1:
                row("Lunettes", f"Exclues: -{_gl_pct:.1f}%")
            if save_debug:
                Image.fromarray(glasses_zone, mode="L").save(output_dir / "mask_glasses.png")

        # HANDS: Exclut les téléphones tenus en main (misclassifiés comme vêtement)
        if hands_mask is not None and np.any(hands_mask > 0):
            _k_hands = np.ones((5, 5), np.uint8)
            hands_dilated = cv2.dilate(hands_mask, _k_hands, iterations=2)  # ~10px
            _hands_pct = np.sum((fused_mask > 0) & (hands_dilated > 0)) / fused_mask.size * 100
            fused_mask[hands_dilated > 0] = 0
            if _hands_pct > 0.1:
                row("Mains", f"Exclues: -{_hands_pct:.1f}% (téléphones/objets)")
            if save_debug:
                Image.fromarray(hands_dilated, mode="L").save(output_dir / "mask_hands.png")
    else:
        row("Exclusions", "skip (person strategy — tout inclure)")

    pct_fused = np.sum(fused_mask > 0) / fused_mask.size * 100
    row("Résultat", f"{pct_fused:.1f}% fusionné")

    if save_debug:
        Image.fromarray(fused_mask, mode="L").save(output_dir / "mask_fusion.png")

    # Légère dilatation pour combler les trous entre B2/B4/SCHP
    kernel_small = np.ones((3, 3), np.uint8)
    fused_mask = cv2.dilate(fused_mask, kernel_small, iterations=1)

    pct_final = np.sum(fused_mask > 0) / fused_mask.size * 100
    row("Dilaté", f"{pct_final:.1f}% (3x3 x1 hole-fill)")

    if save_debug:
        Image.fromarray(fused_mask, mode="L").save(output_dir / "mask_fusion_dilated.png")
        row("Debug", "output/mask_*.png sauvegardés")

    footer()

    return Image.fromarray(fused_mask, mode="L")


def unload_segmentation_models(force=False):
    """Decharge les modeles de segmentation.

    Par défaut, garde les modèles légers (~230MB total, GPU si VRAM >= 6GB) :
    SCHP (~80MB), B2 (~90MB), B4 (~60MB) — le rechargement est plus coûteux en temps.

    Seuls les modèles lourds (GroundingDINO, Sapiens 1B) sont déchargés.
    force=True décharge TOUT (utilisé par unload_all et delete/reinstall).
    """
    global _grounding_dino_model, _clothes_segmenter_b5, _sapiens_segmenter, _schp_segmenter
    global _fusion_b2_cache, _fusion_b4_cache

    # GroundingDINO et Sapiens: toujours déchargés (lourds, GPU)
    if _grounding_dino_model is not None:
        del _grounding_dino_model
        _grounding_dino_model = None
        print("[SEG] GroundingDINO decharge")

    if _sapiens_segmenter is not None:
        del _sapiens_segmenter
        _sapiens_segmenter = None
        print("[SEG] Sapiens 1B decharge")

    # SCHP, B2, B4: gardés en RAM sauf force=True
    if force:
        if _clothes_segmenter_b5 is not None:
            del _clothes_segmenter_b5
            _clothes_segmenter_b5 = None
            print("[SEG] SegFormer decharge")

        if _schp_segmenter is not None:
            del _schp_segmenter
            _schp_segmenter = None
            print("[SEG] SCHP decharge")

        if _fusion_b2_cache is not None:
            del _fusion_b2_cache
            _fusion_b2_cache = None
            print("[SEG] Fusion B2 decharge")

        if _fusion_b4_cache is not None:
            del _fusion_b4_cache
            _fusion_b4_cache = None
            print("[SEG] Fusion B4 decharge")

    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
