"""
Body Estimation Module - DWPose + proportions

Estime les proportions du corps depuis une image habillée
pour générer une depth map réaliste du corps nu.

Pipeline:
1. DWPose → squelette + keypoints
2. Analyse proportions (épaules, hanches, poitrine)
3. Génération depth map corps estimé
4. Retourne proportions + depth pour ControlNet
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
import numpy as np
from PIL import Image

# State global
_dwpose_model = None
_dwpose_processor = None


def _publish_pose_progress(phase: str, step: int = 0, total: int = 100, message: str = ""):
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase(phase, step=step, total=total, message=message)
    except Exception:
        pass


def _ensure_controlnet_aux():
    """Vérifie que controlnet_aux est installé.

    Note: on n'importe PAS controlnet_aux directement car son __init__.py
    importe mediapipe_face qui crash sur Python 3.12 (mediapipe.solutions absent).
    On vérifie juste que le package existe via importlib.
    """
    try:
        import importlib.util
        spec = importlib.util.find_spec('controlnet_aux')
        if spec is not None:
            return True
    except Exception:
        pass

    print("[BODY] Installation de controlnet_aux...")
    _publish_pose_progress("install_pose_tools", 5, 100, "Installation controlnet_aux...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "controlnet_aux"],
            check=True, capture_output=True
        )
        return True
    except Exception as e:
        print(f"[BODY] Erreur installation: {e}")
        return False


def _block_broken_mediapipe():
    """Bloque mediapipe cassé (Python 3.12) pour que controlnet_aux ne crash pas.

    mediapipe s'installe sur Python 3.12 mais mediapipe.solutions n'existe pas.
    controlnet_aux.mediapipe_face fait `import mediapipe` dans un try/except ImportError,
    mais mediapipe s'importe sans ImportError (c'est .solutions qui crash avec AttributeError).

    Fix: si mediapipe est cassé, le remplacer dans sys.modules par None.
    Ça force `import mediapipe` → `mp = None` dans le except ImportError de controlnet_aux.
    On n'a pas besoin de mediapipe — on utilise OpenposeDetector (CMU OpenPose).
    """
    import sys as _sys

    # Vérifier si mediapipe est cassé
    _mp = _sys.modules.get('mediapipe')
    if _mp is not None and not hasattr(_mp, 'solutions'):
        # Supprimer mediapipe et tous ses sous-modules
        _to_remove = [k for k in _sys.modules if k == 'mediapipe' or k.startswith('mediapipe.')]
        for k in _to_remove:
            del _sys.modules[k]
        # Bloquer le re-import en mettant None (import → ImportError)
        _sys.modules['mediapipe'] = None
        print(f"[BODY] mediapipe cassé (Python 3.12) — bloqué ({len(_to_remove)} modules)")
        return True

    # Si pas encore importé, tester
    if 'mediapipe' not in _sys.modules:
        try:
            import mediapipe as _mp2
            if not hasattr(_mp2, 'solutions'):
                _to_remove = [k for k in _sys.modules if k == 'mediapipe' or k.startswith('mediapipe.')]
                for k in _to_remove:
                    del _sys.modules[k]
                _sys.modules['mediapipe'] = None
                print(f"[BODY] mediapipe cassé (Python 3.12) — bloqué")
                return True
        except ImportError:
            pass  # Pas installé → pas de problème
    return False


def load_dwpose():
    """Charge un détecteur de pose. OpenposeDetector d'abord (pas de mediapipe), DWPose en fallback."""
    global _dwpose_model

    if _dwpose_model is not None:
        return _dwpose_model

    if not _ensure_controlnet_aux():
        _dwpose_model = "simple"
        return _dwpose_model

    # Purger mediapipe cassé (Python 3.12) avant tout import controlnet_aux.*
    _block_broken_mediapipe()

    # Essai 1: OpenposeDetector (CMU OpenPose, ~180MB, PAS besoin de mediapipe)
    try:
        _block_broken_mediapipe()
        from controlnet_aux.open_pose import OpenposeDetector
        import torch
        print("[BODY] Chargement OpenposeDetector (~180MB)...")
        _publish_pose_progress("load_pose_detector", 25, 100, "Chargement OpenPose detector...")
        _dwpose_model = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
        _dwpose_model.to(torch.float32)
        print("[BODY] OpenposeDetector prêt (CMU OpenPose, float32)")
        _publish_pose_progress("load_pose_detector", 100, 100, "OpenPose detector prêt")
        return _dwpose_model
    except Exception as e:
        print(f"[BODY] OpenposeDetector indisponible ({e})")

    # Essai 2: DWPose
    try:
        _block_broken_mediapipe()
        from controlnet_aux.dwpose import DWposeDetector
        print("[BODY] Chargement DWPose (fallback)...")
        _publish_pose_progress("load_pose_detector", 55, 100, "Chargement DWPose fallback...")
        _dwpose_model = DWposeDetector.from_pretrained(
            "yolox_l.onnx", "dw-ll_ucoco_384.onnx"
        )
        print("[BODY] DWPose prêt")
        _publish_pose_progress("load_pose_detector", 100, 100, "DWPose prêt")
        return _dwpose_model
    except Exception as e:
        print(f"[BODY] DWPose indisponible ({e})")

    # Fallback: pas de détecteur de pose
    print("[BODY] Aucun détecteur de pose disponible")
    _dwpose_model = "simple"
    return _dwpose_model


def unload_dwpose():
    """Décharge DWPose."""
    global _dwpose_model
    if _dwpose_model is not None:
        del _dwpose_model
        _dwpose_model = None


def detect_pose(image: Image.Image) -> Tuple[Optional[Image.Image], Optional[Dict]]:
    """
    Détecte la pose et les keypoints du corps.

    Returns:
        (pose_image, keypoints_dict) ou (None, None) si échec
    """
    model = load_dwpose()
    if model is None:
        return None, None

    # Mode simple: pas de pose detector, juste retourner None
    # L'estimation sera faite directement depuis l'image
    if model == "simple":
        print("[BODY] Mode simple: estimation depuis l'image directement")
        return None, None

    try:
        # DWPose retourne une image de pose
        pose_image = model(image)

        # Extraire les keypoints si disponibles
        keypoints = None
        if hasattr(model, 'last_keypoints'):
            keypoints = model.last_keypoints

        return pose_image, keypoints

    except Exception as e:
        print(f"[BODY] Erreur détection pose: {e}")
        return None, None


def estimate_body_proportions(
    image: Image.Image,
    keypoints: Optional[Dict] = None
) -> Dict:
    """
    Estime les proportions du corps depuis l'image et les keypoints.

    Returns:
        Dict avec les proportions estimées:
        - bust_size: 'small', 'medium', 'large', 'very_large'
        - waist: 'slim', 'average', 'wide'
        - hips: 'narrow', 'average', 'wide', 'very_wide'
        - body_type: 'slim', 'average', 'athletic', 'curvy', 'plus_size'
        - height_ratio: ratio hauteur/largeur
    """
    proportions = {
        'bust_size': 'medium',
        'waist': 'average',
        'hips': 'average',
        'body_type': 'average',
        'height_ratio': 1.0,
        'attributes': []  # Liste de mots-clés pour le prompt
    }

    if keypoints is None:
        # Sans keypoints, analyser l'image directement
        return _estimate_from_image(image, proportions)

    # Avec keypoints, calcul plus précis
    return _estimate_from_keypoints(keypoints, proportions)


def _estimate_from_image(image: Image.Image, proportions: Dict) -> Dict:
    """Estimation basique depuis l'image (sans keypoints)."""
    import cv2

    # Convertir en numpy
    img_np = np.array(image)
    if len(img_np.shape) == 2:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
    elif img_np.shape[2] == 4:
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)

    h, w = img_np.shape[:2]
    proportions['height_ratio'] = h / w

    # Zones plus précises:
    # - Épaules: 15-25% de la hauteur
    # - Buste/poitrine: 25-40% de la hauteur
    # - Taille: 40-55% de la hauteur
    # - Hanches: 55-75% de la hauteur

    shoulder_region = img_np[int(h*0.15):int(h*0.25), :]
    bust_region = img_np[int(h*0.25):int(h*0.40), :]
    waist_region = img_np[int(h*0.40):int(h*0.55), :]
    hip_region = img_np[int(h*0.55):int(h*0.75), :]

    # Détecter les largeurs
    shoulder_width = _estimate_body_width(shoulder_region)
    bust_width = _estimate_body_width(bust_region)
    waist_width = _estimate_body_width(waist_region)
    hip_width = _estimate_body_width(hip_region)

    # Analyser la protrusion du buste (silhouette)
    bust_protrusion = _analyze_bust_protrusion(bust_region)

    print(f"[BODY] Largeurs détectées - épaules:{shoulder_width:.0f}, buste:{bust_width:.0f}, taille:{waist_width:.0f}, hanches:{hip_width:.0f}")

    # Calculer les ratios - on compare le buste aux ÉPAULES, pas à la taille
    # Une poitrine volumineuse = buste plus large que épaules ou protrusion visible
    if shoulder_width > 10 and waist_width > 10:  # Minimum 10px pour être valide
        # Ratio buste/épaules (si > 1, la poitrine dépasse les épaules)
        bust_shoulder_ratio = bust_width / shoulder_width if shoulder_width > 0 else 1.0
        # Ratio hanches/taille
        hip_waist_ratio = hip_width / waist_width if waist_width > 0 else 1.0

        print(f"[BODY] Ratios - buste/épaules: {bust_shoulder_ratio:.2f}, hanches/taille: {hip_waist_ratio:.2f}, protrusion: {bust_protrusion:.2f}")

        # Classifier la taille de poitrine
        # La protrusion est le facteur principal (indique volume visible de profil/face)
        # Le ratio buste/épaules est secondaire
        if bust_protrusion > 0.25 or bust_shoulder_ratio > 1.15:
            proportions['bust_size'] = 'very_large'
            proportions['attributes'].append('very large breasts')
        elif bust_protrusion > 0.15 or bust_shoulder_ratio > 1.08:
            proportions['bust_size'] = 'large'
            proportions['attributes'].append('large breasts')
        elif bust_protrusion > 0.08 or bust_shoulder_ratio > 1.0:
            proportions['bust_size'] = 'medium'
            # Medium = pas d'attribut spécial
        else:
            proportions['bust_size'] = 'small'
            proportions['attributes'].append('small breasts')

        # Hanches
        if hip_waist_ratio > 1.35:
            proportions['hips'] = 'very_wide'
            proportions['attributes'].append('wide hips')
        elif hip_waist_ratio > 1.2:
            proportions['hips'] = 'wide'
            proportions['attributes'].append('curvy hips')
        elif hip_waist_ratio < 0.95:
            proportions['hips'] = 'narrow'
            proportions['attributes'].append('narrow hips')

        # Analyser la corpulence globale (slim vs average vs plus-size)
        body_coverage = _estimate_body_coverage(img_np)
        print(f"[BODY] Body coverage: {body_coverage:.2f} (portion de l'image)")

        # Classification corpulence basée sur coverage + ratio taille
        # Coverage < 0.25 = très mince, > 0.45 = plus-size
        waist_ratio = waist_width / w if w > 0 else 0.5

        if body_coverage < 0.25 or waist_ratio < 0.25:
            proportions['build'] = 'slim'
            proportions['attributes'].append('slim body')
            proportions['waist'] = 'slim'
        elif body_coverage > 0.45 or waist_ratio > 0.45:
            proportions['build'] = 'plus_size'
            proportions['waist'] = 'wide'
        else:
            proportions['build'] = 'average'

        # Body type - basé sur la silhouette générale
        if proportions['bust_size'] in ('large', 'very_large') and proportions['hips'] in ('wide', 'very_wide'):
            proportions['body_type'] = 'curvy'
            proportions['attributes'].append('curvy body')
        elif waist_width < shoulder_width * 0.75 and waist_width < hip_width * 0.75:
            proportions['body_type'] = 'hourglass'
            proportions['attributes'].append('hourglass figure')
        elif shoulder_width > hip_width * 1.15:
            proportions['body_type'] = 'inverted_triangle'
        elif hip_width > shoulder_width * 1.15:
            proportions['body_type'] = 'pear'
            proportions['attributes'].append('pear shaped body')
        elif proportions.get('build') == 'slim':
            proportions['body_type'] = 'slim'
        else:
            proportions['body_type'] = 'average'

    return proportions


def _analyze_bust_protrusion(bust_region: np.ndarray) -> float:
    """
    Analyse la protrusion du buste (volume visible de face).

    Cherche des indices de poitrine volumineuse:
    - Courbure convexe dans la silhouette
    - Zone centrale plus large que les bords
    - Ombres/highlights typiques

    Returns:
        Score de protrusion 0.0 (plat) à 1.0 (très volumineux)
    """
    import cv2

    if bust_region.size == 0:
        return 0.0

    h, w = bust_region.shape[:2]
    if h < 10 or w < 10:
        return 0.0

    # Convertir en grayscale
    gray = cv2.cvtColor(bust_region, cv2.COLOR_RGB2GRAY)

    # Détecter les edges pour trouver la silhouette
    edges = cv2.Canny(gray, 30, 100)

    # Analyser la forme de la silhouette
    # Trouver les contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return 0.0

    # Prendre le plus grand contour
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)

    # Convex hull pour mesurer la convexité
    hull = cv2.convexHull(largest)
    hull_area = cv2.contourArea(hull)

    if hull_area == 0:
        return 0.0

    # Ratio solidity (area/convex_area) - une poitrine = plus de convexité
    solidity = area / hull_area

    # Analyser la variation de largeur dans la région
    # Une poitrine = plus large au milieu
    mid_h = h // 2
    top_row = edges[h//4, :]
    mid_row = edges[mid_h, :]
    bot_row = edges[3*h//4, :]

    top_spread = np.sum(top_row > 0)
    mid_spread = np.sum(mid_row > 0)
    bot_spread = np.sum(bot_row > 0)

    # Score de protrusion basé sur:
    # 1. Solidity faible = forme plus complexe/convexe
    # 2. Milieu plus large que haut/bas = renflement
    protrusion_score = 0.0

    # Facteur solidity (inversé car moins solide = plus de protrusion visible)
    if solidity < 0.7:
        protrusion_score += 0.15
    elif solidity < 0.85:
        protrusion_score += 0.08

    # Facteur renflement central
    avg_spread = (top_spread + bot_spread) / 2 if (top_spread + bot_spread) > 0 else 1
    if avg_spread > 0 and mid_spread > avg_spread * 1.2:
        protrusion_score += 0.2 * min((mid_spread / avg_spread - 1), 0.5)

    return min(protrusion_score, 1.0)


def _estimate_body_width(region: np.ndarray) -> float:
    """Estime la largeur du corps dans une région."""
    import cv2

    if region.size == 0:
        return 0

    h, w = region.shape[:2]
    if h < 5 or w < 5:
        return 0

    # Convertir en HSV pour détecter la peau
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)

    # Masque peau (plage élargie)
    lower = np.array([0, 20, 50])
    upper = np.array([25, 200, 255])
    mask = cv2.inRange(hsv, lower, upper)

    # Trouver les contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        # Fallback: utiliser les edges
        gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # Trouver la largeur max des edges
        rows_with_edges = np.any(edges > 0, axis=0)
        if np.any(rows_with_edges):
            indices = np.where(rows_with_edges)[0]
            return indices[-1] - indices[0]
        return 0

    # Trouver le contour le plus large
    max_width = 0
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        max_width = max(max_width, cw)

    return max_width


def _estimate_body_coverage(image: np.ndarray) -> float:
    """
    Estime le pourcentage de l'image occupé par le corps.
    Utile pour différencier slim/average/plus-size.

    Returns:
        Ratio 0.0 à 1.0 (portion de l'image occupée par le corps)
    """
    import cv2

    h, w = image.shape[:2]

    # Détecter la peau
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    lower = np.array([0, 20, 50])
    upper = np.array([25, 200, 255])
    skin_mask = cv2.inRange(hsv, lower, upper)

    # Détecter aussi les vêtements (zones non-peau mais pas background)
    # On utilise une combinaison de saturation et luminosité
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # Seuillage adaptatif pour séparer le sujet du fond
    blur = cv2.GaussianBlur(gray, (21, 21), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Combiner peau + foreground
    combined = cv2.bitwise_or(skin_mask, thresh)

    # Morphologie pour nettoyer
    kernel = np.ones((5, 5), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

    # Trouver le plus grand contour (le corps)
    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return 0.3  # Default

    largest = max(contours, key=cv2.contourArea)
    body_area = cv2.contourArea(largest)
    image_area = h * w

    return body_area / image_area if image_area > 0 else 0.3


def _estimate_from_keypoints(keypoints: Dict, proportions: Dict) -> Dict:
    """Estimation précise depuis les keypoints DWPose."""
    # Points clés typiques:
    # 0: nez, 1: cou, 2: épaule droite, 3: coude droit, 4: poignet droit
    # 5: épaule gauche, 6: coude gauche, 7: poignet gauche
    # 8: hanche droite, 9: genou droit, 10: cheville droite
    # 11: hanche gauche, 12: genou gauche, 13: cheville gauche

    try:
        points = keypoints.get('pose_keypoints_2d', [])
        if len(points) < 14:
            return proportions

        # Calculer les distances
        shoulder_width = _distance(points[2], points[5])
        hip_width = _distance(points[8], points[11])
        torso_height = _distance(points[1], points[8])  # cou à hanche

        if shoulder_width > 0 and hip_width > 0:
            # Ratio épaules/hanches
            sh_ratio = shoulder_width / hip_width

            if sh_ratio > 1.2:
                proportions['body_type'] = 'inverted_triangle'
            elif sh_ratio < 0.85:
                proportions['body_type'] = 'pear'
                proportions['hips'] = 'wide'
                proportions['attributes'].append('wide hips')

            # Estimation poitrine basée sur la position du torse
            # (approximation car pas de keypoint direct pour la poitrine)
            chest_point = points[1]  # cou
            if chest_point and len(chest_point) >= 2:
                # Utiliser la largeur relative des épaules
                if shoulder_width > hip_width * 1.1:
                    proportions['bust_size'] = 'large'
                    proportions['attributes'].append('large breasts')

        # Height ratio
        if torso_height > 0:
            leg_height = _distance(points[8], points[10])  # hanche à cheville
            if leg_height > 0:
                proportions['height_ratio'] = (torso_height + leg_height) / shoulder_width

    except Exception as e:
        print(f"[BODY] Erreur analyse keypoints: {e}")

    return proportions


def _distance(p1, p2) -> float:
    """Calcule la distance entre deux points."""
    if p1 is None or p2 is None:
        return 0
    if len(p1) < 2 or len(p2) < 2:
        return 0
    return np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)


def generate_body_depth_map(
    image: Image.Image,
    proportions: Dict,
    pose_image: Optional[Image.Image] = None
) -> Image.Image:
    """
    Génère une depth map estimée du corps nu.

    Combine la pose détectée avec les proportions estimées
    pour créer une depth map qui guide l'inpainting.
    """
    import cv2

    w, h = image.size

    # Si on a une pose image, l'utiliser comme base
    if pose_image is not None:
        depth = np.array(pose_image.convert('L'))
    else:
        # Créer une depth map basique depuis l'image
        img_np = np.array(image.convert('RGB'))
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # Blur pour simuler la depth
        depth = cv2.GaussianBlur(gray, (21, 21), 0)

    # Ajuster selon les proportions
    bust_size = proportions.get('bust_size', 'medium')

    # Renforcer certaines zones selon les proportions
    third_h = h // 3

    if bust_size in ('large', 'very_large'):
        # Éclaircir la zone poitrine (plus proche = plus clair en depth)
        bust_region = depth[:third_h, :]
        boost = 1.2 if bust_size == 'large' else 1.4
        depth[:third_h, :] = np.clip(bust_region * boost, 0, 255).astype(np.uint8)

    hips = proportions.get('hips', 'average')
    if hips in ('wide', 'very_wide'):
        # Élargir visuellement la zone hanches
        hip_region = depth[2*third_h:, :]
        boost = 1.15 if hips == 'wide' else 1.25
        depth[2*third_h:, :] = np.clip(hip_region * boost, 0, 255).astype(np.uint8)

    # Convertir en RGB (ControlNet attend RGB)
    depth_rgb = np.stack([depth] * 3, axis=-1)

    return Image.fromarray(depth_rgb)


def get_body_prompt_attributes(proportions: Dict) -> str:
    """
    Génère les attributs de prompt basés sur les proportions.

    Returns:
        String d'attributs à ajouter au prompt (ex: "large breasts, curvy body, wide hips")
    """
    attributes = proportions.get('attributes', [])

    if not attributes:
        # Attributs par défaut basés sur les proportions
        bust = proportions.get('bust_size', 'medium')
        if bust == 'large':
            attributes.append('large breasts')
        elif bust == 'very_large':
            attributes.append('very large breasts')
        elif bust == 'small':
            attributes.append('small breasts')

        body = proportions.get('body_type', 'average')
        if body == 'curvy':
            attributes.append('curvy body')
        elif body == 'athletic':
            attributes.append('athletic body')
        elif body == 'slim':
            attributes.append('slim body')

    return ', '.join(attributes) if attributes else ''


def save_debug_scan_image(image: Image.Image, proportions: Dict, output_path: str = None):
    """
    Sauvegarde une image de debug avec les zones colorées.
    Petit label sur chaque zone avec nom + pourcentage.
    """
    import cv2
    from pathlib import Path

    if output_path is None:
        output_path = Path(__file__).parent.parent.parent / "output" / "debug_body_scan.png"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convertir en numpy
    img_np = np.array(image.convert('RGB')).copy()
    h, w = img_np.shape[:2]

    # Couleurs (RGB)
    YELLOW = (255, 220, 50)   # Épaules
    RED = (255, 80, 80)       # Buste
    GREEN = (80, 255, 80)     # Taille
    BLUE = (80, 150, 255)     # Hanches

    # Créer un overlay pour les zones
    overlay = np.zeros_like(img_np)

    # Zones d'analyse avec labels
    zones = [
        (0.15, 0.25, YELLOW, "EPAULES"),
        (0.25, 0.40, RED, "BUSTE"),
        (0.40, 0.55, GREEN, "TAILLE"),
        (0.55, 0.75, BLUE, "HANCHES"),
    ]

    # Dessiner les zones colorées
    for pct_start, pct_end, color, label in zones:
        y_start = int(h * pct_start)
        y_end = int(h * pct_end)
        overlay[y_start:y_end, :] = color

    # Fusionner avec transparence 40%
    alpha = 0.4
    img_np = cv2.addWeighted(overlay, alpha, img_np, 1.0, 0)

    # Ajouter les labels en petit sur chaque zone
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.35
    thickness = 1

    for pct_start, pct_end, color, label in zones:
        y_start = int(h * pct_start)
        y_end = int(h * pct_end)
        y_mid = (y_start + y_end) // 2

        # Pourcentage de la hauteur
        pct = int((pct_end - pct_start) * 100)
        text = f"{label} {pct}%"

        # Position: coin gauche de la zone
        cv2.putText(img_np, text, (3, y_mid + 4), font, font_scale, (255, 255, 255), thickness + 1)  # Outline
        cv2.putText(img_np, text, (3, y_mid + 4), font, font_scale, color, thickness)

    # Lignes de séparation
    for pct_start, pct_end, _, _ in zones:
        y_start = int(h * pct_start)
        y_end = int(h * pct_end)
        cv2.line(img_np, (0, y_start), (w, y_start), (255, 255, 255), 1)

    # Sauvegarder
    cv2.imwrite(str(output_path), cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR))
    print(f"[BODY] Debug scan sauvegardé: {output_path}")

    return str(output_path)


def _isolate_person_segformer(image: Image.Image) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    Isole la personne avec SegFormer (segmentation propre).
    Garde la tête (exclude_face=False).

    Returns:
        (masked_image, bbox) où:
        - masked_image: Image avec fond atténué (personne mise en évidence)
        - bbox: (x1, y1, x2, y2) bounding box de la personne
    """
    import cv2
    from core.segmentation import create_smart_mask

    img_np = np.array(image.convert('RGB'))
    h, w = img_np.shape[:2]

    print("[BODY] Isolation personne via SegFormer (exclude_face=False)...")

    try:
        # Utiliser SegFormer pour segmenter la personne AVEC la tête
        person_mask = create_smart_mask(
            image,
            strategy="person",
            exclude_face=False  # GARDER LA TÊTE
        )

        # Convertir en numpy
        mask_np = np.array(person_mask)

        # Trouver le bbox de la personne
        contours, _ = cv2.findContours(mask_np, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            # Prendre le plus grand contour
            largest = max(contours, key=cv2.contourArea)
            x, y, cw, ch = cv2.boundingRect(largest)

            # Petite marge
            margin = 10
            x1 = max(0, x - margin)
            y1 = max(0, y - margin)
            x2 = min(w, x + cw + margin)
            y2 = min(h, y + ch + margin)
        else:
            x1, y1, x2, y2 = 0, 0, w, h

        # Appliquer le masque: personne visible, fond atténué
        mask_3ch = np.stack([mask_np] * 3, axis=-1) / 255.0
        masked = (img_np * mask_3ch + img_np * 0.15 * (1 - mask_3ch)).astype(np.uint8)

        print(f"[BODY] Personne segmentée: bbox=({x1},{y1})-({x2},{y2})")

        return Image.fromarray(masked), (x1, y1, x2, y2)

    except Exception as e:
        print(f"[BODY] Erreur SegFormer: {e}, fallback simple...")
        # Fallback: retourner l'image entière
        return image, (0, 0, w, h)


def _resize_for_analysis(image: Image.Image, max_size: int = 768) -> Tuple[Image.Image, float]:
    """
    Redimensionne l'image pour l'analyse (garde les proportions).

    Returns:
        (resized_image, scale_factor)
    """
    w, h = image.size

    # Si déjà assez petit, pas besoin de resize
    if max(w, h) <= max_size:
        return image, 1.0

    # Calculer le facteur de scale
    scale = max_size / max(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    print(f"[BODY] Image redimensionnée {w}x{h} → {new_w}x{new_h} pour analyse")

    return resized, scale


def analyze_body_for_nudity(image: Image.Image) -> Dict:
    """
    Analyse complète du corps pour le pipeline nudity.

    Returns:
        Dict avec:
        - pose_image: Image de pose pour ControlNet
        - depth_map: Depth map du corps estimé
        - proportions: Dict des proportions
        - prompt_attributes: String d'attributs pour le prompt
        - debug_image_path: Chemin vers l'image de debug
        - success: bool
    """
    result = {
        'pose_image': None,
        'depth_map': None,
        'proportions': {},
        'prompt_attributes': '',
        'debug_image_path': None,
        'success': False
    }

    try:
        # 0. Redimensionner pour cohérence d'analyse (4K → 768px)
        analysis_image, scale = _resize_for_analysis(image, max_size=768)

        # 1. Isoler la personne avec SegFormer (AVEC la tête)
        isolated_image, bbox = _isolate_person_segformer(analysis_image)

        # 2. Détecter la pose
        pose_image, keypoints = detect_pose(isolated_image)
        result['pose_image'] = pose_image

        # 3. Estimer les proportions sur l'image isolée (personne complète avec tête)
        proportions = estimate_body_proportions(isolated_image, keypoints)
        proportions['bbox'] = bbox
        result['proportions'] = proportions

        # 4. Sauvegarder l'image de debug du scan
        try:
            debug_path = save_debug_scan_image(isolated_image, proportions)
            result['debug_image_path'] = debug_path
        except Exception as e:
            print(f"[BODY] Erreur sauvegarde debug: {e}")

        # 5. Générer la depth map (à la taille de l'image originale pour ControlNet)
        depth_map = generate_body_depth_map(image, proportions, pose_image)
        result['depth_map'] = depth_map

        # 6. Générer les attributs de prompt
        result['prompt_attributes'] = get_body_prompt_attributes(proportions)

        result['success'] = True
        print(f"[BODY] Analyse OK: {result['prompt_attributes']}")

    except Exception as e:
        print(f"[BODY] Erreur analyse: {e}")
        import traceback
        traceback.print_exc()

    return result
