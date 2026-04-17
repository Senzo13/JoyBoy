"""
Image transforms: upscale, reframe (zoom out), expand (outpaint).
Depends on: state.py, preview.py, compositing.py
"""
from __future__ import annotations

from PIL import Image, ImageFilter, ImageDraw, ImageEnhance
import numpy as np
import time
import random
from pathlib import Path

from core.generation.state import _state, clear_preview, set_phase
from core.generation.compositing import composite_with_original, fooocus_fill, morphological_open, _pixel_composite
from core.infra.gallery_metadata import save_gallery_metadata


def _resolve_expand_layout(orig_w: int, orig_h: int, ratio: float) -> tuple[float, float, bool]:
    """Return a safe fill ratio for one-pass outpainting.

    Tiny or modest images tend to be interpreted by SDXL as a photo pasted on a
    new canvas when the extension is too large. For those inputs, expand less in
    one pass so users can repeat the action instead of getting a framed image.
    """
    try:
        requested_ratio = float(ratio)
    except (TypeError, ValueError):
        requested_ratio = 1.5

    requested_ratio = max(1.10, min(requested_ratio, 1.65))

    area = max(1, orig_w * orig_h)
    small_source = max(orig_w, orig_h) < 900 or area < 750_000
    effective_ratio = min(requested_ratio, 1.28) if small_source else requested_ratio

    fill_ratio = 1.0 / effective_ratio
    fill_ratio = max(0.60, min(fill_ratio, 0.86))
    return fill_ratio, effective_ratio, small_source


def _snap_canvas_size(value: float, multiple: int = 64) -> int:
    """Snap generated canvas sizes to diffusion-friendly multiples."""
    return max(multiple, int(round(value / multiple)) * multiple)


def _resolve_expand_overlap_px(image_w: int, image_h: int) -> int:
    """Return how much of the source edge should be regenerated.

    Outpainting needs a real overlap between the original pixels and the new
    canvas. If the keep-mask starts exactly on the source rectangle, SDXL tends
    to preserve the rectangle as an inset photo/frame instead of continuing the
    scene.
    """
    shortest = max(1, min(image_w, image_h))
    overlap = int(round(shortest * 0.10))
    overlap = max(40, min(overlap, 96))
    return min(overlap, max(8, shortest // 4))


def _resolve_expand_feather_px(overlap_px: int) -> int:
    """Return a soft-composite feather radius derived from source overlap."""
    return max(48, min(96, overlap_px + 16))


def _build_expand_binary_mask(
    target_w: int,
    target_h: int,
    paste_x: int,
    paste_y: int,
    image_w: int,
    image_h: int,
) -> tuple[Image.Image, int]:
    """Build an outpaint mask where white is generated and black is preserved."""
    overlap_px = _resolve_expand_overlap_px(image_w, image_h)
    keep_x0 = paste_x + overlap_px
    keep_y0 = paste_y + overlap_px
    keep_x1 = paste_x + image_w - overlap_px
    keep_y1 = paste_y + image_h - overlap_px

    if keep_x1 <= keep_x0 or keep_y1 <= keep_y0:
        keep_x0 = paste_x + max(1, image_w // 4)
        keep_y0 = paste_y + max(1, image_h // 4)
        keep_x1 = paste_x + image_w - max(1, image_w // 4)
        keep_y1 = paste_y + image_h - max(1, image_h // 4)

    mask = Image.new("L", (target_w, target_h), 255)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((keep_x0, keep_y0, keep_x1, keep_y1), fill=0)
    return mask, overlap_px


def _paste_with_edge_feather(
    canvas: Image.Image,
    source: Image.Image,
    xy: tuple[int, int],
    overlap_px: int,
) -> None:
    """Paste source into canvas with a soft edge to avoid a visible rectangle."""
    width, height = source.size
    edge = min(overlap_px, max(1, width // 4), max(1, height // 4))
    if edge <= 1:
        canvas.paste(source, xy)
        return

    y_idx, x_idx = np.ogrid[:height, :width]
    dist_x = np.minimum(x_idx + 1, width - x_idx)
    dist_y = np.minimum(y_idx + 1, height - y_idx)
    dist = np.minimum(dist_x, dist_y)
    alpha_np = np.clip(dist / float(edge), 0.0, 1.0) * 255.0
    alpha = Image.fromarray(alpha_np.astype(np.uint8), "L")
    canvas.paste(source, xy, alpha)


def _build_expand_prompts(
    image_description: str,
    prompt: str = "",
    enhanced_prompt: str | None = None,
) -> tuple[str, str]:
    """Build outpaint prompts without poisoning CLIP with frame/border tokens."""
    desc_words = (image_description or "").split()[:34]
    short_desc = " ".join(desc_words) or "photorealistic scene, natural lighting"
    continuity_prefix = (
        "full-bleed photorealistic scene extension, continuous background from "
        "the existing image edges, same camera perspective, same lens, same "
        "lighting, coherent natural environment"
    )

    if prompt.strip():
        user_prompt = (enhanced_prompt or prompt).strip()
        full_prompt = f"{continuity_prefix}, {user_prompt}, {short_desc}"
    else:
        full_prompt = f"{continuity_prefix}, {short_desc}"

    negative = (
        "painting, oil painting, illustration, artistic, watercolor, drawing, "
        "cartoon, anime, 3d render, blurry, low quality, distorted, artifacts, "
        "ugly, different style, color mismatch, inconsistent lighting, picture "
        "frame, photo frame, border, white border, gray border, black border, "
        "matting, matte, pasted image, inset image, image within image, collage, "
        "hard rectangular edge, visible seam, outline, vignette, poster, postcard"
    )
    return full_prompt, negative


def _resolve_expand_canvas(
    orig_w: int,
    orig_h: int,
    ratio: float,
    max_canvas_side: int = 1024,
) -> tuple[int, int, int, int, float, bool]:
    """Return aspect-aware canvas and source sizes for outpainting.

    The old outpaint path always used a square 1024x1024 canvas. Portrait or
    landscape images then looked like an inset photo, especially when small.
    Keeping the canvas close to the source aspect ratio gives the model a much
    clearer task: continue the existing edges instead of inventing a frame.
    """
    _, effective_ratio, small_source = _resolve_expand_layout(orig_w, orig_h, ratio)

    raw_target_w = orig_w * effective_ratio
    raw_target_h = orig_h * effective_ratio
    scale = min(1.0, max_canvas_side / max(raw_target_w, raw_target_h))

    target_w = _snap_canvas_size(raw_target_w * scale)
    target_h = _snap_canvas_size(raw_target_h * scale)

    # Keep the original at native size whenever it fits. If the requested
    # canvas had to be capped, scale the source by the same factor so the
    # visible expansion ratio stays coherent.
    image_w = int(round(orig_w * scale))
    image_h = int(round(orig_h * scale))

    # The target must always leave at least a little room to generate on both
    # axes. If snapping rounded too low, grow the canvas instead of shrinking
    # the photo into an inset.
    min_pad = 32
    if target_w < image_w + min_pad * 2:
        target_w = _snap_canvas_size(image_w + min_pad * 2)
    if target_h < image_h + min_pad * 2:
        target_h = _snap_canvas_size(image_h + min_pad * 2)

    target_w = max(64, target_w)
    target_h = max(64, target_h)
    image_w = min(image_w, target_w - min_pad * 2)
    image_h = min(image_h, target_h - min_pad * 2)

    return target_w, target_h, image_w, image_h, effective_ratio, small_source


def _looks_like_realesrgan(obj) -> bool:
    """Return True for Real-ESRGAN style upsamplers."""
    return obj is not None and callable(getattr(obj, "enhance", None))


def _looks_like_diffusion_pipe(obj) -> bool:
    """Return True for Diffusers-style pipelines."""
    return obj is not None and callable(obj) and not _looks_like_realesrgan(obj)


def _postprocess_upscaled_image(image: Image.Image) -> Image.Image:
    """Apply a conservative final polish after neural upscaling."""
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=55, threshold=3))
    image = ImageEnhance.Contrast(image).enhance(1.03)
    image = ImageEnhance.Sharpness(image).enhance(1.04)
    return image


def upscale_image(
    image: Image.Image,
    scale: int = 2,
    model_name: str = "epiCRealism XL (Moyen)",
    refine: bool = True,
    pipe=None,
    upscaler=None,
    release_refine_pipe=None,
):
    """
    Améliore la qualité d'une image :
    1. Refine optionnel à faible denoise avec un vrai pipeline Diffusers
    2. Décharge le refine pour libérer la VRAM
    3. Upscale avec Real-ESRGAN (super-resolution non-latente)
    4. Polish léger local (netteté/contraste, sans réinventer l'image)

    Retourne: (image_upscaled, status)
    """
    import cv2

    if image is None:
        return None, "Pas d'image"

    print(f"\n{'='*60}")
    print(f"🔍 [UPSCALE] Refine + Real-ESRGAN x{scale}...")
    print(f"{'='*60}")
    orig_w, orig_h = image.size
    print(f"Taille originale: {orig_w}x{orig_h}")

    try:
        # Backward compatibility guard: older route code passed RealESRGANer as
        # `pipe`, which made the refine path call the upsampler like a Diffusers
        # pipeline. Treat enhance()-style objects as the upscaler instead.
        if upscaler is None and _looks_like_realesrgan(pipe):
            upscaler = pipe
            pipe = None
            print("[UPSCALE] Real-ESRGAN détecté dans pipe → refine SD ignoré")

        if pipe is not None and not _looks_like_diffusion_pipe(pipe):
            print(f"[UPSCALE] Refine ignoré: pipeline non compatible ({type(pipe).__name__})")
            pipe = None

        # Convertir en RGB
        if image.mode != "RGB":
            image = image.convert("RGB")

        # ===== ÉTAPE 1: REFINE AVEC IMG2IMG =====
        if refine and pipe is not None:
            try:
                print("[UPSCALE] Étape 1: refinement SD léger (img2img/inpaint)...")

                # Redimensionner si trop grand (max 1024 pour SDXL)
                max_dim = 1024
                w, h = image.size
                refine_source = image
                if max(w, h) > max_dim:
                    ratio = max_dim / max(w, h)
                    new_w = max(64, (int(w * ratio) // 8) * 8)
                    new_h = max(64, (int(h * ratio) // 8) * 8)
                    refine_source = image.resize((new_w, new_h), Image.LANCZOS)
                    print(f"[UPSCALE] Redimensionné pour refine: {new_w}x{new_h}")

                w, h = refine_source.size
                # Ajuster aux multiples de 8
                w = max(64, (w // 8) * 8)
                h = max(64, (h // 8) * 8)
                refine_source = refine_source.resize((w, h), Image.LANCZOS)

                # Masque gris = refinement doux sur toute l'image. Les visages
                # sont encore moins touchés pour éviter l'effet identité fondue.
                mask = Image.new("L", (w, h), 192)

                try:
                    from core.generation import preview as preview_module
                    if preview_module.face_cascade is None:
                        preview_module.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

                    img_cv = cv2.cvtColor(np.array(refine_source), cv2.COLOR_RGB2GRAY)
                    faces = preview_module.face_cascade.detectMultiScale(img_cv, 1.1, 4)

                    if len(faces) > 0:
                        draw = ImageDraw.Draw(mask)
                        for (x, y, fw, fh) in faces:
                            margin = int(max(fw, fh) * 0.25)
                            x1 = max(0, x - margin)
                            y1 = max(0, y - margin)
                            x2 = min(w, x + fw + margin)
                            y2 = min(h, y + fh + margin)
                            draw.ellipse([x1, y1, x2, y2], fill=112)
                        print(f"[UPSCALE] {len(faces)} visage(s) protégé(s) pendant le refine")
                except Exception as e:
                    print(f"[UPSCALE] Détection visage ignorée: {e}")

                prompt = (
                    "subtle photo restoration, crisp natural details, realistic texture, "
                    "preserve exact composition, preserve identity, natural skin pores, "
                    "clean edges, high quality"
                )
                neg = (
                    "blurry, low quality, artifacts, noise, pixelated, oversaturated, "
                    "smooth skin, plastic skin, airbrushed, wax skin, changed face, "
                    "changed identity, changed pose, deformed"
                )

                steps = 16
                clear_preview()
                _state.total_steps = steps
                from core.generation.preview import make_preview_callback
                callback = make_preview_callback(None, preview_every=4)

                refined = pipe(
                    prompt=prompt,
                    negative_prompt=neg,
                    image=refine_source,
                    mask_image=mask,
                    height=h,
                    width=w,
                    strength=0.14,
                    guidance_scale=5.5,
                    num_inference_steps=steps,
                    callback_on_step_end=callback,
                ).images[0]

                clear_preview()

                # Remettre à la taille originale si redimensionné
                if refined.size != (orig_w, orig_h):
                    refined = refined.resize((orig_w, orig_h), Image.LANCZOS)

                image = refined
                print("[UPSCALE] Refinement SD terminé")
            except Exception as e:
                clear_preview()
                print(f"[UPSCALE] Refinement SD échoué, fallback Real-ESRGAN seul: {e}")
            finally:
                if release_refine_pipe is not None:
                    try:
                        print("[UPSCALE] Déchargement refine SD avant Real-ESRGAN...")
                        release_refine_pipe()
                    except Exception as e:
                        print(f"[UPSCALE] Déchargement refine ignoré: {e}")

        # ===== ÉTAPE 2: UPSCALE AVEC REAL-ESRGAN =====
        print(f"[UPSCALE] Étape 2: Real-ESRGAN x{scale}...")

        if not _looks_like_realesrgan(upscaler):
            return None, "Real-ESRGAN non disponible. Installe: pip install realesrgan basicsr"

        # Convertir PIL -> numpy BGR (format OpenCV)
        img_np = np.array(image)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        # Upscale avec Real-ESRGAN
        output, _ = upscaler.enhance(img_bgr, outscale=scale)

        # Convertir BGR -> RGB -> PIL
        output_rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        result = Image.fromarray(output_rgb)
        result = _postprocess_upscaled_image(result)

        new_w, new_h = result.size
        print(f"[UPSCALE] Polish final léger appliqué")
        print(f"✅ [UPSCALE] Terminé! {new_w}x{new_h}")

        # Sauvegarder (historique + last pour le frontend)
        from datetime import datetime
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"upscale_{timestamp}.png"
        result.save(image_path)
        result.save(output_dir / "last_upscaled.png")
        save_gallery_metadata(
            image_path,
            asset_type="image",
            source="modified",
            model=model_name,
            prompt="Upscale",
            operation="upscale",
            scale=scale,
            width=result.size[0],
            height=result.size[1],
        )

        return result, f"OK - {new_w}x{new_h}"

    except Exception as e:
        print(f"[UPSCALE] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return None, f"Erreur: {e}"


# ============================================================
# REFRAME PERSON — Zoom out in-place
# ============================================================

# Scale keywords: prompt analysis → person scale ratio
REFRAME_SCALES = [
    (['un peu', 'slightly', 'a bit', 'a little'], 0.80),
    (['beaucoup', 'very far', 'tres loin', 'très loin', 'way back', 'far away'], 0.50),
]
DEFAULT_REFRAME_SCALE = 0.65  # "en entier", "full body", default


def _detect_reframe_scale(prompt: str) -> float:
    """Analyse le prompt pour déterminer le ratio de réduction de la personne."""
    prompt_lower = prompt.lower()
    for keywords, scale in REFRAME_SCALES:
        for kw in keywords:
            if kw in prompt_lower:
                return scale
    return DEFAULT_REFRAME_SCALE


def reframe_person(image: Image.Image, prompt: str = "", pipe=None):
    """
    Reframe (zoom out in-place) : réduit la personne dans l'image pour la montrer en entier.
    Même taille de sortie, personne réduite, scène complétée par inpainting.

    Pipeline en 5 étapes :
    1. Segmenter la personne
    2. Nettoyer le fond (retirer la personne via inpainting)
    3. Réduire le cutout personne
    4. Replacer le cutout sur le fond propre
    5. Compléter les parties manquantes (jambes/pieds si croppés)

    Retourne: (image_result, status)
    """
    from PIL import ImageOps
    from core.segmentation import create_smart_mask
    from core.florence import describe_image
    from core.model_manager import ModelManager
    import cv2

    if image is None:
        return None, "Pas d'image"

    if pipe is None:
        raise ValueError("pipe must be provided (injected by ModelManager)")

    print(f"\n{'='*60}")
    print(f"[REFRAME] Zoom out in-place")
    print(f"{'='*60}")

    orig_w, orig_h = image.size
    scale = _detect_reframe_scale(prompt)
    print(f"[REFRAME] Taille: {orig_w}x{orig_h}, scale personne: {scale}")

    try:
        image_rgb = image.convert("RGB")

        # ===== ÉTAPE 1 : SEGMENTER LA PERSONNE =====
        # Approche: segmenter le FOND (classe 0) puis INVERSER → tout ce qui n'est pas fond = personne
        # Bien plus robuste que strategy="person" qui rate la peau nue (classes vêtements uniquement)
        print("[REFRAME] Étape 1/5 : Segmentation personne (via fond inversé)...")
        bg_mask = create_smart_mask(image_rgb, strategy="background", exclude_face=False)
        bg_mask_np = np.array(bg_mask)
        # Inverser: fond blanc → personne blanche
        person_mask_np = 255 - bg_mask_np
        # Re-dilater : create_smart_mask dilate le fond → l'inversion réduit la personne
        # On re-dilate pour récupérer les bords perdus + ajouter une marge de sécurité
        kernel_recover = np.ones((15, 15), np.uint8)
        person_mask_np = cv2.dilate(person_mask_np, kernel_recover, iterations=2)

        # Vérifier qu'on a trouvé une personne
        person_pixels = np.sum(person_mask_np > 128)
        total_pixels = person_mask_np.shape[0] * person_mask_np.shape[1]
        person_ratio = person_pixels / total_pixels
        print(f"[REFRAME] Personne détectée: {person_ratio*100:.1f}%")
        if person_ratio < 0.05:
            print("[REFRAME] Pas assez de personne détectée, abandon")
            return None, "Pas de personne détectée dans l'image"

        # Extraire le cutout RGBA de la personne
        person_mask_pil = Image.fromarray(person_mask_np, mode="L")
        cutout = image_rgb.copy()
        cutout.putalpha(person_mask_pil)

        # Détecter si la personne est croppée en bas
        bottom_rows = person_mask_np[-20:, :]  # 20 dernières lignes
        person_touches_bottom = np.sum(bottom_rows > 128) > (bottom_rows.size * 0.10)
        print(f"[REFRAME] Personne croppée en bas: {'OUI' if person_touches_bottom else 'NON'}")

        # ===== ÉTAPE 2 : NETTOYER LE FOND =====
        print("[REFRAME] Étape 2/5 : Nettoyage fond (inpainting)...")

        # Analyser l'image avec Florence pour le prompt fond
        image_description = describe_image(image_rgb, task="<DETAILED_CAPTION>")
        if not image_description:
            image_description = "photorealistic scene, natural lighting, coherent background"
        print(f"[REFRAME] Description: {image_description[:100]}...")

        # Dilater MASSIVEMENT le masque pour effacer toute trace de silhouette humaine
        # Sans ça le modèle "voit" la forme de la personne et en hallucine une nouvelle
        # Dilatation en 2 passes: kernel moyen x4 + kernel gros x2 pour couvrir ombres/reflets
        kernel_med = np.ones((25, 25), np.uint8)
        kernel_big = np.ones((35, 35), np.uint8)
        dilated_mask_np = cv2.dilate(person_mask_np, kernel_med, iterations=4)
        dilated_mask_np = cv2.dilate(dilated_mask_np, kernel_big, iterations=2)
        inpaint_mask = Image.fromarray(dilated_mask_np, mode="L")
        # Gros blur pour transition très douce (pas de bord net = pas de silhouette)
        inpaint_mask = inpaint_mask.filter(ImageFilter.GaussianBlur(radius=30))
        dilated_pct = np.sum(dilated_mask_np > 128) / dilated_mask_np.size * 100
        print(f"[REFRAME] Masque inpaint fond: {dilated_pct:.1f}% (dilaté 25x25 x4 + 35x35 x2 + blur 30)")

        # Travailler à 1024x1024 pour l'inpainting
        target_size = 1024
        image_1024 = image_rgb.resize((target_size, target_size), Image.LANCZOS)
        mask_1024 = inpaint_mask.resize((target_size, target_size), Image.BILINEAR)

        # Prompt fond: extraire UNIQUEMENT la description du background
        # Florence produit souvent "... In the background, ..." → on prend cette partie
        bg_desc = ""
        desc_lower = image_description.lower()
        for marker in ['in the background', 'background', 'behind']:
            if marker in desc_lower:
                idx = desc_lower.index(marker) + len(marker)
                bg_desc = image_description[idx:].strip(',.: ')
                break

        # Filtrer agressivement tout mot lié à une personne/corps
        PERSON_WORDS = {
            'woman', 'man', 'girl', 'boy', 'person', 'people', 'she', 'he', 'her', 'his',
            'nude', 'naked', 'standing', 'sitting', 'posing', 'body', 'face', 'hair',
            'breast', 'breasts', 'chest', 'legs', 'arms', 'hand', 'hands', 'foot', 'feet',
            'skin', 'belly', 'waist', 'hip', 'hips', 'thigh', 'thighs', 'shoulder', 'shoulders',
            'figure', 'model', 'looking', 'wearing', 'front', 'topless', 'bottomless',
        }
        source_text = bg_desc if bg_desc else image_description
        desc_words = source_text.split()[:25]
        filtered_desc = ' '.join(w for w in desc_words if w.lower().strip(',.;:!') not in PERSON_WORDS)
        bg_prompt = f"empty scene, no people, no person, only background, {filtered_desc}, seamless, natural lighting, photorealistic"
        bg_neg = "person, human, figure, body, face, silhouette, shadow of person, mannequin, statue, blurry, artifacts"

        clear_preview()
        bg_steps = 25
        _state.total_steps = bg_steps
        from core.generation.preview import make_preview_callback
        callback = make_preview_callback(None, preview_every=5)

        # Inpainting du fond
        bg_kwargs = dict(
            prompt=bg_prompt,
            negative_prompt=bg_neg,
            image=image_1024,
            mask_image=mask_1024,
            height=target_size,
            width=target_size,
            strength=0.95,
            guidance_scale=7.5,
            num_inference_steps=bg_steps,
            callback_on_step_end=callback,
        )

        # ControlNet depth si disponible
        has_controlnet = hasattr(pipe, 'controlnet') and pipe.controlnet is not None
        if has_controlnet:
            model_manager = ModelManager.get()
            depth_bg = model_manager.extract_depth(image_1024)
            if depth_bg is not None:
                bg_kwargs['control_image'] = depth_bg.resize((target_size, target_size), Image.LANCZOS)
                bg_kwargs['controlnet_conditioning_scale'] = 0.3
            else:
                bg_kwargs['control_image'] = Image.new("RGB", (target_size, target_size), (128, 128, 128))
                bg_kwargs['controlnet_conditioning_scale'] = 0.0

        print("[REFRAME] Inpainting fond...")
        clean_bg_1024 = pipe(**bg_kwargs).images[0]

        # Composite : garder le fond original hors masque, généré dans le masque
        clean_bg_1024 = composite_with_original(image_1024, clean_bg_1024, mask_1024, feather_pixels=8, color_match=True)

        # Revenir à la taille originale
        clean_bg = clean_bg_1024.resize((orig_w, orig_h), Image.LANCZOS)
        print(f"[REFRAME] Fond nettoyé: {clean_bg.size}")

        # ===== ÉTAPE 3 : RÉDUIRE LA PERSONNE =====
        print(f"[REFRAME] Étape 3/5 : Réduction personne ({int(scale*100)}%)...")

        # Bounding box de la personne dans le masque
        rows = np.any(person_mask_np > 128, axis=1)
        cols = np.any(person_mask_np > 128, axis=0)
        if not np.any(rows) or not np.any(cols):
            return None, "Erreur: masque personne vide"
        y_min, y_max = np.where(rows)[0][[0, -1]]
        x_min, x_max = np.where(cols)[0][[0, -1]]

        # Cropper le cutout à la bounding box (avec un peu de marge)
        margin = 5
        crop_x1 = max(0, x_min - margin)
        crop_y1 = max(0, y_min - margin)
        crop_x2 = min(orig_w, x_max + margin + 1)
        crop_y2 = min(orig_h, y_max + margin + 1)
        cutout_cropped = cutout.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        crop_w, crop_h = cutout_cropped.size

        # Réduire
        new_w = int(crop_w * scale)
        new_h = int(crop_h * scale)
        cutout_small = cutout_cropped.resize((new_w, new_h), Image.LANCZOS)
        print(f"[REFRAME] Cutout: {crop_w}x{crop_h} → {new_w}x{new_h}")

        # ===== ÉTAPE 4 : REPLACER LA PERSONNE =====
        print("[REFRAME] Étape 4/5 : Placement personne...")

        # Position : centré horizontalement, centré verticalement sur la position originale
        # Garder le centre de masse de la personne à sa position d'origine
        # → la personne "recule" naturellement (pieds remontent, plus d'espace autour)
        paste_x = (orig_w - new_w) // 2
        orig_center_y = (crop_y1 + crop_y2) // 2
        paste_y = orig_center_y - new_h // 2

        if person_touches_bottom:
            # Personne croppée en bas (jambes/pieds manquants) :
            # Limiter la remontée pour que le gap sous la personne reste raisonnable
            # (~20% de l'image max pour la complétion des jambes)
            max_feet_gap = int(orig_h * 0.20)
            min_paste_y = orig_h - new_h - max_feet_gap
            paste_y = max(paste_y, min_paste_y)

        # Clamp : ne pas dépasser les bords
        paste_y = max(0, min(orig_h - new_h, paste_y))

        # Coller le cutout réduit sur le fond propre
        result = clean_bg.copy()
        result.paste(cutout_small, (paste_x, paste_y), cutout_small.split()[3])  # Alpha as mask
        print(f"[REFRAME] Personne placée à ({paste_x}, {paste_y})")

        # ===== ÉTAPE 5 : COMPLÉTER LES PARTIES MANQUANTES =====
        print("[REFRAME] Étape 5/5 : Complétion parties manquantes...")

        # Masque des zones à compléter :
        # - Bords du cutout collé (zone de blend ~10px)
        # - Bas de la personne si elle était croppée (jambes/pieds)
        completion_mask = np.zeros((orig_h, orig_w), dtype=np.uint8)

        # Zone de blend autour du cutout collé
        cutout_alpha = np.array(cutout_small.split()[3])
        # Créer le masque du cutout à sa position dans l'image
        full_alpha = np.zeros((orig_h, orig_w), dtype=np.uint8)
        y1 = paste_y
        y2 = min(paste_y + new_h, orig_h)
        x1 = paste_x
        x2 = min(paste_x + new_w, orig_w)
        alpha_h = y2 - y1
        alpha_w = x2 - x1
        full_alpha[y1:y2, x1:x2] = cutout_alpha[:alpha_h, :alpha_w]

        # Dilater puis soustraire = bord du cutout
        kernel_blend = np.ones((12, 12), np.uint8)
        dilated_alpha = cv2.dilate(full_alpha, kernel_blend, iterations=1)
        blend_border = dilated_alpha.astype(np.int16) - full_alpha.astype(np.int16)
        blend_border = np.clip(blend_border, 0, 255).astype(np.uint8)
        completion_mask = np.maximum(completion_mask, blend_border)

        # Si la personne était croppée en bas, compléter les jambes/pieds sous le cutout
        if person_touches_bottom:
            # Zone sous le cutout : overlap avec le bas du cutout + tout l'espace jusqu'au sol
            feet_overlap = max(15, int(new_h * 0.05))  # 5% du cutout ou 15px min
            feet_zone_top = min(paste_y + new_h - feet_overlap, orig_h)
            feet_zone_bottom = orig_h
            if feet_zone_top < feet_zone_bottom:
                # Zone élargie horizontalement pour les pieds/ombre
                feet_x1 = max(0, paste_x - 30)
                feet_x2 = min(orig_w, paste_x + new_w + 30)
                completion_mask[feet_zone_top:feet_zone_bottom, feet_x1:feet_x2] = 255
            feet_gap = feet_zone_bottom - feet_zone_top
            print(f"[REFRAME] Zone pieds: y={feet_zone_top}→{feet_zone_bottom} ({feet_gap}px)")

        # Vérifier qu'on a effectivement des zones à compléter
        completion_pixels = np.sum(completion_mask > 128)
        if completion_pixels > 100:
            completion_mask_pil = Image.fromarray(completion_mask, mode="L")
            completion_mask_pil = completion_mask_pil.filter(ImageFilter.GaussianBlur(radius=6))

            # Préparer pour inpainting
            result_1024 = result.resize((target_size, target_size), Image.LANCZOS)
            comp_mask_1024 = completion_mask_pil.resize((target_size, target_size), Image.BILINEAR)

            # Prompt pour compléter (PAS de description Florence complète → risque d'halluciner)
            comp_prompt = "full body, complete legs, feet on ground, natural pose, photorealistic"
            comp_neg = "blurry, artifacts, extra limbs, missing limbs, deformed, cut off, extra person, two people"

            # Adapter les paramètres à la taille de la zone à compléter
            comp_ratio = completion_pixels / (orig_h * orig_w)
            set_phase("fine_tuning", 8)
            # Grande zone → plus de steps + strength pour que le modèle génère correctement
            comp_steps = 25 if comp_ratio > 0.10 else 20
            comp_strength = 0.90 if comp_ratio > 0.10 else 0.75
            print(f"[REFRAME] Complétion: {comp_ratio*100:.1f}% de l'image, steps={comp_steps}, strength={comp_strength}")
            effective_steps = max(int(comp_steps * comp_strength), 3)
            _state.total_steps = effective_steps
            from core.generation.preview import make_preview_callback
            comp_callback = make_preview_callback(None, preview_every=5)

            comp_kwargs = dict(
                prompt=comp_prompt,
                negative_prompt=comp_neg,
                image=result_1024,
                mask_image=comp_mask_1024,
                height=target_size,
                width=target_size,
                strength=comp_strength,
                guidance_scale=7.5,
                num_inference_steps=comp_steps,
                callback_on_step_end=comp_callback,
            )

            if has_controlnet:
                depth_result = ModelManager.get().extract_depth(result_1024)
                if depth_result is not None:
                    comp_kwargs['control_image'] = depth_result.resize((target_size, target_size), Image.LANCZOS)
                    comp_kwargs['controlnet_conditioning_scale'] = 0.5
                else:
                    comp_kwargs['control_image'] = Image.new("RGB", (target_size, target_size), (128, 128, 128))
                    comp_kwargs['controlnet_conditioning_scale'] = 0.0

            print(f"[REFRAME] Inpainting complétion ({completion_pixels} pixels)...")
            completed_1024 = pipe(**comp_kwargs).images[0]

            # Composite : garder les zones intactes, blender les zones complétées
            completed_1024 = composite_with_original(result_1024, completed_1024, comp_mask_1024, feather_pixels=6, color_match=True)

            result = completed_1024.resize((orig_w, orig_h), Image.LANCZOS)
        else:
            print("[REFRAME] Pas de zones à compléter")

        # Nettoyer la preview
        clear_preview()

        print(f"[REFRAME] Terminé! {result.size[0]}x{result.size[1]}")

        # Sauvegarder
        from datetime import datetime
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"reframe_{timestamp}.png"
        result.save(image_path)
        result.save(output_dir / "last_reframed.png")
        save_gallery_metadata(
            image_path,
            asset_type="image",
            source="modified",
            prompt=prompt or "Reframe",
            operation="reframe",
            width=result.size[0],
            height=result.size[1],
        )

        return result, f"OK - {result.size[0]}x{result.size[1]}"

    except Exception as e:
        print(f"[REFRAME] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return None, f"Erreur: {e}"


def expand_image(image: Image.Image, ratio: float = 1.5, prompt: str = "", model_name: str = "epiCRealism XL (Moyen)", pipe=None):
    """
    Expand/Outpaint une image avec inpainting simple (rapide et léger)
    Utilise le modèle d'inpainting déjà disponible

    Retourne: (image_expanded, status)
    """
    from PIL import ImageOps

    if image is None:
        return None, "Pas d'image"

    print(f"\n{'='*60}")
    print(f"[EXPAND] Outpainting (inpainting simple)...")
    print(f"{'='*60}")

    orig_w, orig_h = image.size
    print(f"Taille originale: {orig_w}x{orig_h}")

    try:
        # S'assurer que l'image est en RGBA pour la transparence
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        # ===== ÉTAPE 1: ANALYSER L'IMAGE AVEC FLORENCE =====
        print("[EXPAND] Analyse de l'image avec Florence-2...")
        from core.florence import describe_image
        image_rgb = image.convert("RGB")
        image_description = describe_image(image_rgb, task="<DETAILED_CAPTION>")
        if not image_description:
            image_description = "photorealistic scene, natural lighting, coherent background"
        print(f"[EXPAND] Description: {image_description[:120]}...")

        # ===== ÉTAPE 2: PRÉPARER UN CANVAS ADAPTÉ AU FORMAT =====
        # Garder le ratio portrait/paysage de la source évite l'effet
        # "photo posée dans un cadre" qui arrivait avec le canvas carré.
        target_w, target_h, new_w, new_h, effective_ratio, small_source = _resolve_expand_canvas(
            orig_w,
            orig_h,
            ratio,
        )
        if small_source:
            print(
                f"[EXPAND] Petite image détectée: extension limitée à "
                f"{effective_ratio:.2f}x pour éviter l'effet cadre"
            )
        else:
            print(f"[EXPAND] Extension demandée: {effective_ratio:.2f}x")

        # Redimensionner l'image
        resized_img = image.resize((new_w, new_h), Image.LANCZOS)

        # Position centrée
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2

        # Canvas avec mirror-pad: refléter les bords de l'image vers l'extérieur
        # Beaucoup mieux qu'une couleur moyenne pour donner du contexte au modèle
        resized_rgb = resized_img.convert("RGB")
        img_array = np.array(resized_rgb)

        # Calculer le padding nécessaire de chaque côté
        pad_top = paste_y
        pad_bottom = target_h - paste_y - new_h
        pad_left = paste_x
        pad_right = target_w - paste_x - new_w

        # Mirror-pad (reflect) l'image pour remplir le canvas
        canvas_array = np.pad(
            img_array,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            mode='reflect'
        )
        canvas = Image.fromarray(canvas_array)
        # Flouter le mirror-pad pour éviter des artefacts de répétition trop nets
        # On floute tout, puis on recolle l'image nette par-dessus
        canvas_blurred = canvas.filter(ImageFilter.GaussianBlur(radius=20))
        canvas = canvas_blurred

        print(f"[EXPAND] Canvas: {target_w}x{target_h}, image: {new_w}x{new_h}")

        # ===== ÉTAPE 3: CRÉER LE MASQUE (avec érosion interne) =====
        # Masque blanc = zones à générer, noir = zones à garder
        # On mord franchement dans l'image originale pour que les bords soient
        # régénérés, sinon le modèle conserve un rectangle net façon cadre.
        binary_mask, overlap_px = _build_expand_binary_mask(
            target_w,
            target_h,
            paste_x,
            paste_y,
            new_w,
            new_h,
        )
        feather_px = _resolve_expand_feather_px(overlap_px)
        print(f"[EXPAND] Overlap anti-cadre: {overlap_px}px, feather={feather_px}px")

        # Coller la source avec un bord doux dans le canvas d'amorçage. Le
        # centre reste net, mais le modèle ne voit plus une photo rectangulaire
        # posée sur un fond flouté.
        _paste_with_edge_feather(canvas, resized_rgb, (paste_x, paste_y), overlap_px)

        # Morphological open gradient (Fooocus-style) au lieu de Gaussian blur.
        # On conserve aussi le masque binaire pour le clamp latent/composite.
        mask_np = np.array(binary_mask)
        mask_np = morphological_open(mask_np, radius=feather_px)
        mask = Image.fromarray(mask_np)

        # ===== ÉTAPE 3b: FOOOCUS PRE-FILL =====
        # Propager les couleurs des bords de l'image dans les zones masquées
        # → le diffusion démarre avec des couleurs déjà cohérentes
        _t_fill = time.time()
        canvas_np = np.array(canvas)
        _mask_for_fill = np.array(mask)
        canvas_np = fooocus_fill(canvas_np, _mask_for_fill)
        canvas = Image.fromarray(canvas_np)
        # Re-paste source with a feathered edge, not a hard rectangle.
        _paste_with_edge_feather(canvas, resized_rgb, (paste_x, paste_y), overlap_px)
        print(f"[EXPAND] Fooocus pre-fill OK ({time.time() - _t_fill:.1f}s)")

        # ===== ÉTAPE 4: CONSTRUIRE LE PROMPT =====
        # CLIP = 77 tokens max → instructions importantes EN PREMIER, description tronquée après
        # Important: ne pas mettre "no frame/no border" dans le positif. CLIP
        # garde les concepts "frame/border" même si on les nie.
        from core.utility_ai import enhance_prompt as enhance_prompt_with_ai

        if prompt.strip():
            user_prompt = enhance_prompt_with_ai(prompt)
            full_prompt, neg = _build_expand_prompts(
                image_description,
                prompt=prompt,
                enhanced_prompt=user_prompt,
            )
        else:
            full_prompt, neg = _build_expand_prompts(image_description)

        print(f"[EXPAND] Prompt: {full_prompt}")

        # ===== ÉTAPE 5: GÉNÉRATION AVEC INPAINTING (Fooocus pipeline) =====
        if pipe is None:
            raise ValueError("pipe must be provided (injected by ModelManager)")

        import torch

        # Initialiser preview
        steps = 30
        FOOOCUS_CFG = 7.0
        clear_preview()
        _state.total_steps = steps
        from core.generation.preview import make_preview_callback
        preview_cb = make_preview_callback(None, preview_every=5)

        # --- Encode fill en latents + masque binaire latent (pattern processing.py) ---
        with torch.no_grad():
            _device = "cuda" if torch.cuda.is_available() else "cpu"
            _fill_t = pipe.image_processor.preprocess(canvas, height=target_h, width=target_w)
            _fill_t = _fill_t.to(device=_device, dtype=pipe.vae.dtype)
            _vae_moved = False
            try:
                _vae_dev = next(pipe.vae.parameters()).device
                if _vae_dev.type != 'cuda':
                    pipe.vae.to(_device)
                    _vae_moved = True
            except Exception:
                pass
            _fill_latents = pipe.vae.encode(_fill_t).latent_dist.mode()
            _fill_latents = _fill_latents * pipe.vae.config.scaling_factor
            if _vae_moved:
                pipe.vae.to('cpu')
                torch.cuda.empty_cache()

        # Masque BINAIRE en espace latent — max_pool2d(8,8) comme Fooocus
        _mask_np_raw = np.array(binary_mask).astype(np.float32) / 255.0
        _mask_t = torch.from_numpy(_mask_np_raw).unsqueeze(0).unsqueeze(0)
        _mask_fullres = torch.nn.functional.interpolate(
            _mask_t, size=(_fill_latents.shape[2] * 8, _fill_latents.shape[3] * 8),
            mode='bilinear'
        ).round()
        _binary_mask_latent = torch.nn.functional.max_pool2d(
            _mask_fullres, (8, 8)
        ).round().to(device=_fill_latents.device, dtype=_fill_latents.dtype)

        # Fooocus clamping callback (double blend per step + anisotropic sharpness)
        _gen_seed = random.randint(0, 2**32 - 1)
        from core.generation.callbacks import make_fooocus_clamp_callback
        fooocus_cb = make_fooocus_clamp_callback(
            _fill_latents, None, _binary_mask_latent,
            preview_callback=preview_cb, seed=_gen_seed
        )

        # Switch scheduler to SDE-DPMSolver++ (stochastic) — matches Fooocus
        _saved_scheduler = pipe.scheduler
        try:
            from diffusers import DPMSolverMultistepScheduler as _DPMS
            pipe.scheduler = _DPMS.from_config(
                pipe.scheduler.config,
                algorithm_type="sde-dpmsolver++",
                use_karras_sigmas=True, lower_order_final=True,
            )
            print(f"[EXPAND] SDE scheduler + Fooocus double blend active")
        except Exception as _e:
            print(f"[EXPAND] SDE scheduler failed ({_e}), using default")
            _saved_scheduler = None

        # Pipeline: full white mask (clamping callback handles the real mask)
        _pipeline_mask = Image.new("L", (target_w, target_h), 255)

        # Si le pipeline a un ControlNet, extraire la vraie depth et l'étendre
        has_controlnet = hasattr(pipe, 'controlnet') and pipe.controlnet is not None
        pipe_kwargs = dict(
            prompt=full_prompt,
            negative_prompt=neg,
            image=canvas,
            mask_image=_pipeline_mask,
            height=target_h,
            width=target_w,
            strength=0.95,
            guidance_scale=FOOOCUS_CFG,
            num_inference_steps=steps,
            callback_on_step_end=fooocus_cb,
            callback_on_step_end_tensor_inputs=["latents", "add_time_ids"],
        )
        if has_controlnet:
            # Extraire la depth de l'image originale redimensionnée
            from core.model_manager import ModelManager; model_manager = ModelManager.get()
            depth_orig = model_manager.extract_depth(resized_rgb)
            if depth_orig is not None:
                # Créer un canvas depth avec la depth étendue par mirror-pad
                depth_array = np.array(depth_orig)
                depth_padded = np.pad(
                    depth_array,
                    ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
                    mode='reflect'
                )
                # Flouter la depth étendue pour transition douce
                depth_canvas = Image.fromarray(depth_padded)
                depth_canvas = depth_canvas.filter(ImageFilter.GaussianBlur(radius=15))
                # Recoller la depth avec le même feather anti-cadre que l'image.
                _paste_with_edge_feather(depth_canvas, depth_orig, (paste_x, paste_y), overlap_px)
                pipe_kwargs['control_image'] = depth_canvas
                pipe_kwargs['controlnet_conditioning_scale'] = 0.4
                print(f"[EXPAND] ControlNet Depth activé (scale=0.4, depth étendue)")
            else:
                # Fallback: depth neutre si extraction échoue
                pipe_kwargs['control_image'] = Image.new("RGB", (target_w, target_h), (128, 128, 128))
                pipe_kwargs['controlnet_conditioning_scale'] = 0.0
                print("[EXPAND] ControlNet Depth → fallback neutre")

        # Fooocus InpaintHead (if available)
        try:
            from core.generation.fooocus_patch import prepare_inpaint_head
            prepare_inpaint_head(pipe, canvas, mask.resize((target_w, target_h), Image.BILINEAR))
        except Exception as e:
            print(f"[EXPAND] InpaintHead prep skipped: {e}")

        print("[EXPAND] Génération (Fooocus pipeline)...")
        result = pipe(**pipe_kwargs).images[0]

        # Restore scheduler — create a FRESH instance to ensure no stale
        # monkey-patches (Fooocus x0 blend, preview wraps) from main pass
        if _saved_scheduler is not None:
            pipe.scheduler = type(_saved_scheduler).from_config(_saved_scheduler.config)

        # Clear InpaintHead features
        try:
            from core.generation.fooocus_patch import clear_inpaint_head
            clear_inpaint_head(pipe)
        except Exception:
            pass

        # Free VRAM
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # ===== PIXEL COMPOSITING (Fooocus-style) =====
        # Blend original centre into result avec morphological_open gradient
        # Le masque inversé (0=zone originale à préserver, 255=zone générée)
        original_canvas = Image.new("RGB", (target_w, target_h), (128, 128, 128))
        original_canvas.paste(resized_rgb, (paste_x, paste_y))

        # Masque binaire pour le compositing: noir=original, blanc=généré
        _comp_mask = np.array(binary_mask)
        result_np = np.array(result)
        original_canvas_np = np.array(original_canvas)
        result = Image.fromarray(_pixel_composite(result_np, original_canvas_np, _comp_mask, radius=feather_px))
        print(f"[EXPAND] Fooocus pixel composite OK")

        # Fine-tuning pass removed: pixel compositing above is sufficient
        # for blending transitions. The old re-inpainting with 3 effective steps
        # at strength=0.30 was causing a painterly/oil-painting artifact.

        # Nettoyer la preview
        clear_preview()

        print(f"[EXPAND] Terminé! {result.size[0]}x{result.size[1]}")

        # Sauvegarder (historique + last pour le frontend)
        from datetime import datetime
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"expand_{timestamp}.png"
        result.save(image_path)
        result.save(output_dir / "last_expanded.png")
        mask.save(output_dir / "last_expand_mask.png")
        save_gallery_metadata(
            image_path,
            asset_type="image",
            source="modified",
            model=model_name,
            prompt=prompt or "Outpaint / expand",
            operation="expand",
            width=result.size[0],
            height=result.size[1],
        )

        return result, f"OK - {result.size[0]}x{result.size[1]}"

    except Exception as e:
        clear_preview()
        print(f"[EXPAND] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return None, f"Erreur: {e}"
