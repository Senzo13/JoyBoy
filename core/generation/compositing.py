"""
Compositing, pre-fill, blending, color matching, crop-to-mask.
Zero internal dependencies (leaf module, PIL/numpy/cv2 only).
"""
from PIL import Image, ImageFilter
import numpy as np


def _box_blur(img_np, k):
    """Box blur matching Fooocus — uses PIL ImageFilter.BoxBlur(k) where k is RADIUS."""
    return np.array(Image.fromarray(img_np).filter(ImageFilter.BoxBlur(k)))


def fooocus_fill(image_np, mask_np):
    """
    Pré-remplit la zone masquée avec les couleurs environnantes.
    Multi-scale box blur : les couleurs voisines sont propagées vers l'intérieur
    du masque, des plus grosses échelles aux plus fines.

    Résultat : le diffusion démarre avec des couleurs déjà cohérentes
    → pas besoin de correction couleur post-processing.
    """
    current = image_np.copy()
    original = image_np.copy()
    # Pixels hors masque (à restaurer après chaque blur)
    outside = mask_np < 127

    for k, repeats in [(512, 2), (256, 2), (128, 4), (64, 4), (33, 8), (15, 8), (5, 16), (3, 16)]:
        for _ in range(repeats):
            current = _box_blur(current, k)
            current[outside] = original[outside]

    return current


def morphological_open(mask_np, radius=32):
    """
    Crée un gradient autour du masque (Fooocus-style).
    Pas de Gaussian blur : itérations de max_filter(3x3) - step.
    Le résultat est un masque avec un fade linéaire de 256→0 sur ~radius px.
    """
    import cv2

    step = 256 // radius
    x = np.zeros_like(mask_np, dtype=np.int16)
    x[mask_np > 127] = 256

    for _ in range(radius):
        dilated = cv2.dilate(x.astype(np.uint16).astype(np.float32),
                             np.ones((3, 3), np.uint8)).astype(np.int16)
        dilated = dilated - step
        x = np.maximum(dilated, x)

    return np.clip(x, 0, 255).astype(np.uint8)


def _pixel_composite(result_np, original_np, mask_np, radius):
    """
    Fooocus-style pixel compositing : alpha-blend result into original.

    Args:
        result_np: Image générée (H, W, 3) float32 ou uint8
        original_np: Image originale (H, W, 3) float32 ou uint8
        mask_np: Masque binaire (H, W) uint8 (255=zone générée)
        radius: Rayon du morphological_open gradient
    Returns:
        Image composited (H, W, 3) uint8
    """
    soft_mask = morphological_open(mask_np, radius=radius)
    alpha = soft_mask.astype(np.float32) / 255.0
    alpha_3ch = np.stack([alpha] * 3, axis=-1)

    orig_f = original_np.astype(np.float32) if original_np.dtype != np.float32 else original_np
    result_f = result_np.astype(np.float32) if result_np.dtype != np.float32 else result_np

    blended = orig_f * (1 - alpha_3ch) + result_f * alpha_3ch

    return np.clip(blended, 0, 255).astype(np.uint8)


def _estimate_image_quality(image_np, mask_np=None):
    """
    Estime la qualité de l'image source (0.0 = très dégradée, 1.0 = excellente).

    Mesure le bruit et la netteté HORS du masque (zone originale non modifiée).
    Utilisé pour adapter résolution de crop et prompts à la qualité source,
    évitant un écart de qualité visible avec la zone inpaintée.
    """
    import cv2

    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY) if image_np.ndim == 3 else image_np

    if mask_np is not None:
        outside = mask_np < 127
        if np.sum(outside) < 500:
            return 0.7  # Pas assez de référence → qualité décente par défaut
    else:
        outside = np.ones(gray.shape, dtype=bool)

    # Bruit (MAD du Laplacien → estimateur robuste de sigma)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    noise_sigma = np.median(np.abs(lap[outside])) * 1.4826

    # Netteté (variance du Laplacien)
    sharpness = np.var(lap[outside])

    # Résolution effective (plus petit côté)
    min_dim = min(image_np.shape[0], image_np.shape[1])

    # Normalisation 0-1
    noise_score = float(np.clip(1.0 - noise_sigma / 30.0, 0.0, 1.0))
    sharp_score = float(np.clip(sharpness / 500.0, 0.0, 1.0))
    res_score = float(np.clip(min_dim / 1080.0, 0.0, 1.0))  # 1080p+ = 1.0, 540p = 0.5

    quality = 0.4 * noise_score + 0.3 * sharp_score + 0.3 * res_score
    return quality


def _harmonize_quality(orig_np, result_np, mask_np):
    """
    Dégrade légèrement la zone inpaintée pour matcher la qualité de l'original.

    Mesure le bruit et la netteté de l'original hors masque, puis applique
    un bruit/flou similaire (atténué) dans la zone masquée. L'inpaint reste
    meilleur que l'original, mais l'écart est réduit pour un rendu harmonieux.
    """
    import cv2

    orig_gray = cv2.cvtColor(orig_np, cv2.COLOR_RGB2GRAY)
    outside = mask_np < 127

    if np.sum(outside) < 500:
        return result_np

    # Mesure du bruit original
    lap = cv2.Laplacian(orig_gray, cv2.CV_64F)
    noise_sigma = np.median(np.abs(lap[outside])) * 1.4826
    sharpness = np.var(lap[outside])

    MIN_NOISE = 5.0
    MIN_SHARP = 300.0

    if noise_sigma < MIN_NOISE and sharpness > MIN_SHARP:
        return result_np

    print(f"[QUALITY] Harmonisation (noise={noise_sigma:.1f}, sharpness={sharpness:.0f})")

    modified = result_np.astype(np.float32)
    mask_f = (mask_np.astype(np.float32) / 255.0)[:, :, np.newaxis]

    # Ajout de bruit (40% du delta — assez pour harmoniser, pas trop pour garder la qualité)
    if noise_sigma >= MIN_NOISE:
        add_sigma = (noise_sigma - 3.0) * 0.4
        noise = np.random.normal(0, add_sigma, modified.shape).astype(np.float32)
        modified += noise * mask_f
        print(f"[QUALITY]   + Bruit sigma={add_sigma:.1f}")

    # Flou léger si l'original est soft
    if sharpness < MIN_SHARP:
        blur_sigma = max(0.3, 1.0 * (1.0 - sharpness / MIN_SHARP))
        ksize = max(3, int(blur_sigma * 4) | 1)
        blurred = cv2.GaussianBlur(modified, (ksize, ksize), blur_sigma)
        modified = modified * (1.0 - mask_f) + blurred * mask_f
        print(f"[QUALITY]   + Flou sigma={blur_sigma:.2f}")

    return np.clip(modified, 0, 255).astype(np.uint8)


def _compute_inpaint_crop(mask_np, k=0.618, padding=32):
    """
    Fooocus-style crop-to-mask: compute crop region around mask with golden ratio padding.

    1. Finds bounding box of mask pixels
    2. Adds padding (for uncrop feathering — so feather falls OUTSIDE mask area)
    3. Expands to at least k fraction of each image dimension (default 0.618 = golden ratio)
    4. Centers on the mask center, clamped to image bounds

    Returns (top, bottom, left, right) or None if mask is empty or covers >80% of image.
    """
    H, W = mask_np.shape
    indices = np.where(mask_np > 127)
    if len(indices[0]) == 0:
        return None

    # Bounding box of mask
    a = int(np.min(indices[0]))
    b = int(np.max(indices[0])) + 1
    c = int(np.min(indices[1]))
    d = int(np.max(indices[1])) + 1

    # If mask bbox covers > 80% of image area, cropping won't help much
    mask_area = (b - a) * (d - c)
    if mask_area > 0.80 * H * W:
        return None

    # Add padding around bbox so uncrop feather falls outside mask area
    a = max(0, a - padding)
    b = min(H, b + padding)
    c = max(0, c - padding)
    d = min(W, d + padding)

    # Expand to at least k fraction of each dimension
    target_h = max(b - a, int(H * k))
    target_w = max(d - c, int(W * k))

    # Center the crop on the mask center
    center_y = (a + b) // 2
    center_x = (c + d) // 2

    a = center_y - target_h // 2
    b = a + target_h
    c = center_x - target_w // 2
    d = c + target_w

    # Clamp to image bounds (shift instead of clip to preserve size)
    if a < 0:
        b -= a
        a = 0
    if b > H:
        a -= (b - H)
        b = H
        a = max(0, a)
    if c < 0:
        d -= c
        c = 0
    if d > W:
        c -= (d - W)
        d = W
        c = max(0, c)

    return (a, b, c, d)


def _detect_skin_pixels(image_np: np.ndarray) -> np.ndarray:
    """
    Détecte les pixels de peau dans une image RGB.
    Retourne un masque booléen (True = peau).

    Utilise YCrCb (standard computer vision pour skin detection)
    + HSV en filtre secondaire pour éliminer les faux positifs (portes, murs, etc.)
    """
    import cv2

    # YCrCb — le plus fiable pour la peau (toutes ethnies)
    ycrcb = cv2.cvtColor(image_np, cv2.COLOR_RGB2YCrCb)
    # Cr: 133-173 = rouge chrominance (peau), Cb: 77-127 = bleu chrominance
    mask_ycrcb = cv2.inRange(ycrcb, np.array([60, 133, 77]), np.array([255, 173, 127]))

    # HSV — filtre secondaire (élimine bois, murs beiges, tapis)
    hsv = cv2.cvtColor(image_np, cv2.COLOR_RGB2HSV)
    mask_hsv = cv2.inRange(hsv, np.array([0, 30, 60]), np.array([25, 170, 255]))

    # Intersection = seulement les pixels qui passent les DEUX tests
    skin_mask = cv2.bitwise_and(mask_ycrcb, mask_hsv)

    # Nettoyage morphologique : virer les petits groupes isolés (bruit)
    kernel = np.ones((5, 5), np.uint8)
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel)
    # Combler les petits trous dans la peau détectée
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel)

    return skin_mask > 128


def _save_color_debug(original_np, result_np, mask_np, skin_pixels, ref_mask, target_mask, result_after):
    """Sauvegarde les images de debug dans output/hsv/."""
    import cv2
    from pathlib import Path

    debug_dir = Path("output") / "color_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    h, w = original_np.shape[:2]

    # 1. Image originale brute
    Image.fromarray(original_np).save(debug_dir / "1_original.png")

    # 2. HSV skin detection sur l'original (vert = détecté comme peau)
    overlay_skin = original_np.copy()
    overlay_skin[skin_pixels] = [0, 255, 0]  # vert vif
    blended = (original_np * 0.5 + overlay_skin * 0.5).astype(np.uint8)
    Image.fromarray(blended).save(debug_dir / "2_hsv_skin_detected.png")

    # 3. Le masque (blanc = zone inpaintée)
    mask_vis = (mask_np * 255).astype(np.uint8)
    Image.fromarray(mask_vis, mode="L").save(debug_dir / "3_mask.png")

    # 4. Pixels de référence utilisés (rouge = ce qui sert de référence couleur)
    overlay_ref = original_np.copy()
    overlay_ref[ref_mask] = [255, 0, 0]  # rouge
    blended_ref = (original_np * 0.4 + overlay_ref * 0.6).astype(np.uint8)
    Image.fromarray(blended_ref).save(debug_dir / "4_reference_pixels.png")

    # 5. Pixels cible dans le résultat (bleu = peau détectée dans la zone générée)
    overlay_target = result_np.copy()
    overlay_target[target_mask] = [0, 100, 255]  # bleu
    blended_target = (result_np * 0.4 + overlay_target * 0.6).astype(np.uint8)
    Image.fromarray(blended_target).save(debug_dir / "5_target_pixels.png")

    # 6. Résultat AVANT correction
    Image.fromarray(result_np).save(debug_dir / "6_result_before_correction.png")

    # 7. Résultat APRÈS correction
    Image.fromarray(result_after).save(debug_dir / "7_result_after_correction.png")

    print(f"[COLOR DEBUG] Images sauvegardées dans output/hsv/ (7 fichiers)")


def match_colors(original: Image.Image, result: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Color match + composite seamless en une opération.

    Shift LAB UNIFORME (moyenne seulement, pas std) → gradient constant × masque
    = transition parfaitement lisse, pas de banding.
    Masque érodé + blurré → fondu INTERNE (ne saigne jamais dans le fond).
    """
    import cv2

    original_np = np.array(original).astype(np.uint8)
    result_np = np.array(result).astype(np.uint8)
    mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

    # Masques binaires pour stats
    inside_mask = mask_np > 0.5
    outside_mask = mask_np < 0.5

    # Référence = peau visible HORS masque dans l'original
    skin_pixels = _detect_skin_pixels(original_np)
    ref_mask = outside_mask & skin_pixels

    if np.sum(ref_mask) < 500:
        all_skin = _detect_skin_pixels(original_np)
        ref_mask = all_skin
        if np.sum(ref_mask) < 500:
            print(f"[COLOR] Skip: aucune peau détectée ({np.sum(all_skin)} pixels)")
            return result
        print(f"[COLOR] Fallback: {np.sum(ref_mask)} pixels peau totale")

    # Cible = peau dans la zone masquée du résultat
    result_skin = _detect_skin_pixels(result_np)
    target_mask = inside_mask & result_skin
    if np.sum(target_mask) < 100:
        target_mask = inside_mask

    original_lab = cv2.cvtColor(original_np, cv2.COLOR_RGB2LAB).astype(np.float32)
    result_lab = cv2.cvtColor(result_np, cv2.COLOR_RGB2LAB).astype(np.float32)

    # Shift UNIFORME : delta = ref_mean - target_mean (par canal LAB)
    # C'est une constante → multiplié par le masque gradient = transition parfaite
    for ch in range(3):
        ref_mean = np.mean(original_lab[:, :, ch][ref_mask])
        gen_mean = np.mean(result_lab[:, :, ch][target_mask])
        delta = ref_mean - gen_mean
        ch_name = ['L', 'A', 'B'][ch]
        print(f"[COLOR] {ch_name}: ref={ref_mean:.1f} gen={gen_mean:.1f} delta={delta:+.1f}")
        # Appliquer le shift à toute l'image résultat
        result_lab[:, :, ch] = np.clip(result_lab[:, :, ch] + delta, 0, 255)

    corrected_rgb = cv2.cvtColor(result_lab.astype(np.uint8), cv2.COLOR_LAB2RGB)

    # Masque = segmentation brut (déjà dilated + blur(10) par segmentation.py)
    # Pas d'érosion ni de blur supplémentaire — la transition de ~20px est naturelle
    soft_mask = mask_np

    # Composite : original hors masque, résultat corrigé dans masque
    m3 = np.stack([soft_mask] * 3, axis=-1)
    original_f = original_np.astype(np.float32)
    corrected_f = corrected_rgb.astype(np.float32)
    final = original_f * (1 - m3) + corrected_f * m3

    return Image.fromarray(np.clip(final, 0, 255).astype(np.uint8))


def laplacian_pyramid_blend(original: Image.Image, result: Image.Image, mask: Image.Image, levels: int = 4) -> Image.Image:
    """
    Composite seamless via Laplacian pyramid blending (Burt & Adelson 1983).

    Basse fréquence (couleur/luminosité) blendée sur zone large → pas de seam.
    Haute fréquence (texture/détail) blendée sur zone étroite → bords nets.

    Contrairement à Poisson, ne tire PAS les couleurs des bords du masque vers
    l'intérieur (safe pour nudify où les bords = vêtements).
    """
    import cv2

    orig_np = np.array(original).astype(np.float64)
    res_np = np.array(result).astype(np.float64)
    mask_np = np.array(mask.convert('L')).astype(np.float64) / 255.0
    mask_3ch = np.stack([mask_np] * 3, axis=-1)

    h, w = orig_np.shape[:2]

    # Cap levels pour que le niveau le plus grossier reste >= 8px
    max_levels = int(np.floor(np.log2(min(h, w)))) - 3
    levels = min(levels, max(1, max_levels))

    # Dimensions doivent être divisibles par 2^levels
    factor = 2 ** levels
    pad_h = (factor - h % factor) % factor
    pad_w = (factor - w % factor) % factor
    if pad_h or pad_w:
        orig_np = np.pad(orig_np, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
        res_np = np.pad(res_np, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
        mask_3ch = np.pad(mask_3ch, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')

    # Gaussian pyramids
    def _gauss_pyr(img, n):
        gp = [img]
        for _ in range(n):
            img = cv2.pyrDown(img)
            gp.append(img)
        return gp

    gp_orig = _gauss_pyr(orig_np, levels)
    gp_res = _gauss_pyr(res_np, levels)
    gp_mask = _gauss_pyr(mask_3ch, levels)

    # Laplacian pyramids
    def _lap_pyr(gp):
        lp = []
        for i in range(len(gp) - 1):
            expanded = cv2.pyrUp(gp[i + 1], dstsize=(gp[i].shape[1], gp[i].shape[0]))
            lp.append(gp[i] - expanded)
        lp.append(gp[-1])
        return lp

    lp_orig = _lap_pyr(gp_orig)
    lp_res = _lap_pyr(gp_res)

    # Blend chaque niveau avec le masque au même niveau
    lp_blend = []
    for i in range(len(lp_orig)):
        m = gp_mask[i]
        lp_blend.append(lp_orig[i] * (1.0 - m) + lp_res[i] * m)

    # Collapse (reconstruit depuis le niveau le plus grossier)
    blended = lp_blend[-1]
    for i in range(len(lp_blend) - 2, -1, -1):
        blended = cv2.pyrUp(blended, dstsize=(lp_blend[i].shape[1], lp_blend[i].shape[0]))
        blended = blended + lp_blend[i]

    # Retirer le padding
    if pad_h or pad_w:
        blended = blended[:h, :w]

    blended = np.clip(blended, 0, 255).astype(np.uint8)
    return Image.fromarray(blended)


def composite_with_original(original: Image.Image, result: Image.Image, mask: Image.Image, feather_pixels: int = 12, color_match: bool = True) -> Image.Image:
    """
    Composite le résultat avec l'original via alpha blending avec feathering amélioré.

    Expand le masque de quelques pixels pour couvrir les bords de la zone générée,
    puis applique un Gaussian blur large pour une transition douce entre
    zone VAE et pixels originaux. Pas de Poisson blending (casse les couleurs
    sur les gros masques).
    """
    import cv2
    from scipy.ndimage import gaussian_filter

    original_np = np.array(original).astype(np.uint8)
    result_np = np.array(result).astype(np.uint8)
    mask_np = np.array(mask.convert('L'))

    # Binariser
    mask_binary = (mask_np > 128).astype(np.uint8) * 255

    # Expand le masque de quelques pixels pour que la zone générée
    # déborde légèrement dans la transition (évite les bords nets)
    expand_px = max(2, feather_pixels // 4)
    kernel = np.ones((expand_px * 2 + 1, expand_px * 2 + 1), np.uint8)
    mask_expanded = cv2.dilate(mask_binary, kernel, iterations=1)

    # Gaussian blur large pour transition douce
    mask_float = mask_expanded.astype(np.float32) / 255.0
    sigma = max(8, feather_pixels * 1.5)
    mask_feathered = gaussian_filter(mask_float, sigma=sigma)
    mask_feathered = np.clip(mask_feathered, 0.0, 1.0)

    # Alpha blending
    mask_3ch = np.stack([mask_feathered] * 3, axis=-1)
    composited = original_np.astype(np.float32) * (1 - mask_3ch) + result_np.astype(np.float32) * mask_3ch
    composited = np.clip(composited, 0, 255).astype(np.uint8)

    return Image.fromarray(composited)
