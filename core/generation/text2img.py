"""
Text-to-image generation: styles, format detection, generate_from_text.
Depends on: state.py, preview.py
"""
from __future__ import annotations

from PIL import Image
import numpy as np
import torch
import time
import random
import re
from pathlib import Path

from core.generation.state import (
    _state, GenerationCancelledException,
    clear_preview, set_phase, set_progress_phase, MAX_HISTORY,
    _prompt_embed_cache, _PROMPT_CACHE_MAX,
)
from core.generation.preview import make_preview_callback, _get_taesd, _get_taef1
from core.generation.pose_prompts import (
    POSE_PROMPTS as _POSE_PROMPTS,
    append_negative_prompt,
    build_human_pose_safety_additions,
    get_pose_prompts,
)
from core.infra.gallery_metadata import save_gallery_metadata

# Import des fonctions du module utility_ai
from core.utility_ai import enhance_prompt as enhance_prompt_with_ai, build_full_prompt


# ===== TEXT2IMG FORMAT DETECTION (résolution + style) =====
# Chaque format: (width, height, style_prefix, style_suffix)
# style_prefix remplace le "RAW photo, photorealistic" par défaut
# style_suffix s'ajoute après le prompt utilisateur
_TXT2IMG_STYLES = {
    # Phone / Snapchat — social phone-photo framing, grain, full-body visibility.
    "snapchat": (768, 1344,
        "amateur phone photo, smartphone camera, full body visible in frame",
        "casual snapshot, slightly grainy, phone camera quality, low light, natural imperfections, real amateur photo, not professional"),
    "snap": (768, 1344,
        "amateur phone photo, smartphone camera, full body visible in frame",
        "casual snapshot, slightly grainy, phone camera quality, low light, natural imperfections, real amateur photo, not professional"),
    "selfie": (768, 1344,
        "phone selfie, smartphone front camera, close angle",
        "casual selfie, phone camera quality, slightly grainy, mirror selfie, natural lighting, amateur photo"),
    "telephone": (768, 1344,
        "amateur phone photo, smartphone camera",
        "phone camera quality, slightly grainy, casual snapshot, real photo"),
    "téléphone": (768, 1344,
        "amateur phone photo, smartphone camera",
        "phone camera quality, slightly grainy, casual snapshot, real photo"),
    "phone": (768, 1344,
        "amateur phone photo, smartphone camera",
        "phone camera quality, slightly grainy, casual snapshot, real photo"),
    "tiktok": (768, 1344,
        "phone video screenshot, vertical frame, full body",
        "phone camera, ring light, slightly overexposed, social media aesthetic"),

    # Webcam / Omegle — qualité webcam laptop, grain, angle plongée
    "omegle": (1344, 768,
        "webcam capture, laptop webcam, low resolution webcam",
        "grainy webcam quality, slightly washed out colors, harsh laptop screen lighting, looking at camera, webcam angle from above, real webcam screenshot"),
    "webcam": (1344, 768,
        "webcam capture, laptop webcam photo",
        "grainy webcam quality, washed out, harsh screen lighting, webcam angle, real webcam capture"),
    "cam": (1344, 768,
        "webcam capture",
        "webcam quality, grainy, harsh lighting, looking at camera"),

    # Instagram — carré, esthétique soignée
    "instagram": (1024, 1024,
        "instagram photo, curated aesthetic",
        "warm filter, soft lighting, instagram aesthetic, slightly edited"),
    "insta": (1024, 1024,
        "instagram photo, curated aesthetic",
        "warm filter, soft lighting, instagram aesthetic, slightly edited"),

    # Cinéma / Paysage — pas de style spécial, juste le format
    "cinematic":  (1344, 768, "cinematic film still, movie scene", "cinematic lighting, film grain, shallow depth of field, anamorphic"),
    "cinema":     (1344, 768, "cinematic film still, movie scene", "cinematic lighting, film grain, shallow depth of field"),
    "widescreen": (1344, 768, None, None),
    "landscape":  (1216, 832, None, None),
    "paysage":    (1216, 832, None, None),
    "portrait":   (832, 1216, None, None),
    "vertical":   (768, 1344, None, None),
    "horizontal": (1344, 768, None, None),
    "carré":      (1024, 1024, None, None),
    "square":     (1024, 1024, None, None),
}

# Ratios supportés → (width, height)
_TXT2IMG_RATIOS = {
    "1:1":   (1024, 1024),
    "9:16":  (768, 1344),
    "16:9":  (1344, 768),
    "3:4":   (896, 1152),
    "4:3":   (1152, 896),
    "2:3":   (832, 1216),
    "3:2":   (1216, 832),
}

def _detect_text2img_format(prompt: str, is_turbo: bool = False) -> tuple:
    """
    Détecte résolution + style depuis le prompt.
    Retourne: (width, height, style_prefix, style_suffix)
    style_prefix remplace le prefix par défaut, style_suffix s'ajoute après le prompt.
    """
    prompt_lower = prompt.lower()

    if is_turbo:
        default_w, default_h = 512, 512
    else:
        default_w, default_h = 768, 1344  # Portrait snapchat par défaut

    # 1. Taille explicite: "1080x1920", "768x1344", etc.
    size_match = re.search(r'(\d{3,4})\s*[x×]\s*(\d{3,4})', prompt_lower)
    if size_match:
        w, h = int(size_match.group(1)), int(size_match.group(2))
        w = max(512, min(1536, (w // 8) * 8))
        h = max(512, min(1536, (h // 8) * 8))
        return w, h, None, None

    # 2. Ratio explicite: "9:16", "16:9", "3:4", etc.
    ratio_match = re.search(r'\b(\d{1,2}):(\d{1,2})\b', prompt_lower)
    if ratio_match:
        ratio_str = f"{ratio_match.group(1)}:{ratio_match.group(2)}"
        if ratio_str in _TXT2IMG_RATIOS:
            w, h = _TXT2IMG_RATIOS[ratio_str]
            return w, h, None, None

    # 3. Mots-clés de format + style (word boundary pour éviter "cam" dans "camera")
    for keyword, fmt in _TXT2IMG_STYLES.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', prompt_lower):
            return fmt

    return default_w, default_h, None, None


_VIEW_PROMPTS = {
    'full_body': 'wide shot, full composition visible',
    'upper_body': 'medium shot, main subject framed naturally',
    'portrait_close': 'close-up shot, tight framing on the main subject',
    'low_angle': 'low angle view, looking up, shot from below',
    'high_angle': 'high angle view, looking down, shot from above',
    'from_behind': 'rear view, back-facing viewpoint',
}

_POSE_DISTANCE_PROMPTS = {
    'very_close': (
        'very close framing, subject fills most of the frame, tight near-viewer composition, close foreground perspective',
        'distant wide shot, far away subject, tiny subject in frame, full body wide framing, lots of empty surrounding space',
    ),
    'close': (
        'close framing, subject near the viewer, medium-close composition',
        'far away subject, distant wide shot, tiny subject in frame',
    ),
    'far': (
        'far framing, wide shot, full body visible with surrounding space',
        'close-up, extreme close-up, tight crop, cropped body',
    ),
}

_POSE_ORIENTATION_PROMPTS = {
    'front': (
        'front-facing body orientation, facing the viewer',
        'back view, rear view, from behind, facing away',
    ),
    'back': (
        'back-facing body orientation, rear view, facing away from the viewer',
        'front view, facing viewer, looking toward viewer',
    ),
}

_CAPTURE_DEVICE_NEGATIVE = "camera, photo camera, camera lens, DSLR, camcorder, smartphone, phone, selfie stick, tripod, photographer"
_CAPTURE_DEVICE_STYLE_WORDS = (
    "selfie", "phone", "smartphone", "telephone", "téléphone", "webcam", "omegle",
    "snapchat", "snap", "tiktok", "camera", "camcorder", "dslr", "photographer",
)

_TEXT2IMG_PHOTO_STYLE_NEGATIVE = (
    "painting, drawing, illustration, cartoon, anime, 3d render, cgi, "
    "airbrushed, smooth plastic skin, doll, mannequin"
)
_TEXT2IMG_QUALITY_NEGATIVE = (
    "blurry, low quality, worst quality, lowres, jpeg artifacts, noisy, grainy, "
    "distorted, deformed, ugly, bad anatomy, extra fingers, missing fingers, "
    "extra limbs, bad hands, bad feet, fused toes, duplicate, watermark, text, logo"
)
_TEXT2IMG_STYLIZED_NEGATIVE_TERMS = {
    "painting",
    "drawing",
    "illustration",
    "cartoon",
    "anime",
    "3d render",
    "cgi",
    "airbrushed",
    "smooth plastic skin",
    "doll",
    "mannequin",
}
_TEXT2IMG_STYLIZED_PROMPT_MARKERS = (
    "anime", "manga", "hentai", "manhwa", "webtoon", "cartoon", "toon",
    "illustration", "drawing", "painting", "digital art", "line art",
    "cel shading", "cel-shading", "cgi", "3d", "3d anime", "render",
    "game art", "comic", "2d animation", "3d animation",
)
_TEXT2IMG_STYLIZED_MODEL_MARKERS = (
    "illustrious", "pony", "animagine", "anime", "manga", "hentai", "toon",
    "cartoon", "waifu", "anything-v",
)
_TEXT2IMG_PHOTO_INTENT_MARKERS = (
    "raw photo", "photo", "photorealistic", "realistic photo", "real person",
    "real-life", "dslr", "35mm", "film grain", "cinematic photo",
)


def _is_mps_runtime() -> bool:
    return (
        not torch.cuda.is_available()
        and hasattr(torch.backends, "mps")
        and torch.backends.mps.is_available()
    )


def _apply_mps_sdxl_runtime_policy(pipe, label: str, is_mps_runtime: bool) -> None:
    """Ensure ad-hoc SDXL wrappers get the same MPS decode policy as loaded pipes."""
    if not is_mps_runtime:
        return

    class_name = pipe.__class__.__name__
    if "StableDiffusionXL" not in class_name:
        return

    try:
        from core.models.runtime_env import apply_mps_pipeline_optimizations

        apply_mps_pipeline_optimizations(pipe, label)
    except Exception as exc:
        print(f"[TEXT2IMG] MPS runtime policy skipped ({exc})")


def _run_sdxl_pipeline(pipe, label: str, is_mps_runtime: bool, **kwargs):
    """Run SDXL and decode latents safely on macOS/MPS."""
    use_mps_latent_decode = (
        is_mps_runtime
        and "StableDiffusionXL" in pipe.__class__.__name__
    )
    if use_mps_latent_decode:
        kwargs["output_type"] = "latent"

    output = pipe(**kwargs)

    if not use_mps_latent_decode:
        return output.images[0]

    from core.models.runtime_env import decode_sdxl_latents_with_mps_fallback

    return decode_sdxl_latents_with_mps_fallback(pipe, output.images, label)


def _should_suppress_visible_capture_devices(prompt: str, style_prefix: str | None, style_suffix: str | None) -> bool:
    """Avoid literal cameras unless the user/style explicitly asks for capture-device aesthetics."""
    text = " ".join(part for part in (prompt or "", style_prefix or "", style_suffix or "")).lower()
    return not any(re.search(r'\b' + re.escape(word) + r'\b', text) for word in _CAPTURE_DEVICE_STYLE_WORDS)


def _looks_preformatted_text2img_prompt(prompt: str) -> bool:
    """Detect prompts already expanded by build_full_prompt/upstream routing."""
    text = (prompt or "").strip().lower()
    if not text:
        return False
    preformatted_markers = (
        "raw photo",
        "photorealistic",
        "professional photography",
        "cinematic film still",
        "amateur phone photo",
        "phone selfie",
        "webcam capture",
    )
    return any(marker in text for marker in preformatted_markers)


def _contains_text_marker(text: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if re.search(r'(?<![\w])' + re.escape(marker) + r'(?![\w])', text):
            return True
    return False


def _requests_stylized_text2img(prompt: str, model_name: str | None = None) -> bool:
    """Detect prompts/models that should not receive the default photo wrapper."""
    prompt_text = (prompt or "").lower()
    has_stylized_prompt = _contains_text_marker(prompt_text, _TEXT2IMG_STYLIZED_PROMPT_MARKERS)
    has_photo_intent = _contains_text_marker(prompt_text, _TEXT2IMG_PHOTO_INTENT_MARKERS)

    return has_stylized_prompt and not has_photo_intent


def _adapt_pose_prompt_for_distance(pose_prompt: str | None, pose_distance: str | None) -> str | None:
    """Remove wide/full-body constraints when the user asks for a close framing."""
    if not pose_prompt or pose_distance != "very_close":
        return pose_prompt

    replacements = (
        "full body visible",
        "full body front view",
        "full body top-down view",
        "full body view from above",
        "full body view",
    )
    adapted = pose_prompt
    for phrase in replacements:
        adapted = re.sub(rf"\s*,?\s*{re.escape(phrase)}", "", adapted, flags=re.IGNORECASE)
    adapted = re.sub(r"\s*,\s*,+", ",", adapted).strip(" ,")
    return adapted or pose_prompt


def _build_text2img_negative_prompt(prompt: str, model_name: str | None = None) -> str:
    """Build a negative prompt that does not ban the user's requested medium."""
    if _requests_stylized_text2img(prompt, model_name):
        return _TEXT2IMG_QUALITY_NEGATIVE
    return f"{_TEXT2IMG_PHOTO_STYLE_NEGATIVE}, {_TEXT2IMG_QUALITY_NEGATIVE}"


def _sanitize_negative_for_requested_style(
    negative_prompt: str | None,
    prompt: str,
    model_name: str | None = None,
) -> str | None:
    if not negative_prompt or not _requests_stylized_text2img(prompt, model_name):
        return negative_prompt

    kept_parts = []
    removed_parts = []
    for part in negative_prompt.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", " ", cleaned.lower())
        if normalized in _TEXT2IMG_STYLIZED_NEGATIVE_TERMS:
            removed_parts.append(cleaned)
            continue
        kept_parts.append(cleaned)

    if removed_parts:
        print(f"[TEXT2IMG] Negative stylisé nettoyé: {', '.join(removed_parts)}")
    return ", ".join(kept_parts) if kept_parts else None


def generate_from_text(prompt: str, model_name: str = "Automatique", enhance: bool = True, steps: int = 30, cancel_check=None, pipe=None,
                       ip_adapter_image_embeds=None, ip_adapter_scale=0.35,
                       style_ref_scale=0.55, style_init_image=None,
                       guidance_override=None, export_settings=None,
                       controlnet_model=None, controlnet_pose=None, controlnet_scale=0.6,
                       controlnet_depth_image=None):
    """
    Genere une image a partir du texte uniquement (pas d'image en entree)
    Retourne: (image_result, status)

    Args:
        cancel_check: callable qui retourne True si la génération doit être annulée
        ip_adapter_image_embeds: face embedding pour IP-Adapter FaceID (optionnel)
        ip_adapter_scale: force de l'IP-Adapter FaceID (0.0-1.0)
        style_ref_scale: fidélité à la ref style (0.0-1.0). Haut = plus proche de l'original
        style_init_image: PIL image de référence utilisée comme init (img2img-like, optionnel)
        controlnet_model: ControlNet OpenPose model (loaded, on CPU) for pose enforcement
        controlnet_pose: pose name for hardcoded skeleton (e.g. 'legs_up'), or None to extract from style_init_image
        guidance_override: guidance scale override depuis les settings (optionnel)
    """
    if not prompt.strip():
        return None, "Ecris ce que tu veux generer"

    print(f"\n{'='*60}")
    print(f"  TEXT2IMG GENERATION")
    print(f"{'='*60}")
    print(f"  Model:    {model_name}")
    print(f"  Prompt:   {prompt}")
    print(f"  Enhance:  {enhance}")
    print(f"  Steps:    {steps}")
    print(f"{'='*60}")

    # Le pipe est injecté par l'appelant (ModelManager via generation_pipeline)
    if pipe is None:
        raise ValueError("pipe must be provided (injected by ModelManager)")

    clear_preview()
    set_progress_phase("prepare_text2img", 0, 100)

    # Vérifier annulation
    if cancel_check and cancel_check():
        print(f"[TEXT2IMG] Annulation détectée")
        raise GenerationCancelledException("Génération annulée")

    # Détecter le type de pipeline
    pipe_class = type(pipe).__name__
    pipe_name = str(getattr(pipe, 'name_or_path', pipe_class)).lower()
    is_turbo = 'turbo' in pipe_name
    is_flux = 'Flux' in pipe_class

    if is_turbo:
        steps = 4
        guidance = 0.0  # Turbo n'utilise pas de guidance
        print(f"[TEXT2IMG] Mode TURBO détecté -> {steps} steps, guidance={guidance}")
    elif is_flux:
        guidance = float(guidance_override) if guidance_override is not None else 3.5
        steps = min(steps, 28)  # Flux Dev optimal 20-28 steps
        print(f"[TEXT2IMG] Mode FLUX détecté -> {steps} steps, guidance={guidance}")
    else:
        guidance = float(guidance_override) if guidance_override is not None else 7.5

    # ===== EXPORT SETTINGS — preset keyword + default format/view/pose =====
    if export_settings is None:
        export_settings = {}
    presets = export_settings.get('presets', {})

    # 1. Preset keyword detection — match first keyword found in prompt
    matched_preset = None
    for keyword, config in presets.items():
        if keyword and re.search(r'\b' + re.escape(keyword) + r'\b', prompt, flags=re.IGNORECASE):
            prompt = re.sub(r'\b' + re.escape(keyword) + r'\b', '', prompt, flags=re.IGNORECASE).strip()
            prompt = re.sub(r'\s{2,}', ' ', prompt)  # collapse double spaces
            matched_preset = config
            print(f"[TEXT2IMG] Export preset '{keyword}' matched → {config}")
            # Merge preset config into export_settings (preset overrides defaults)
            export_settings = {**export_settings, **config}
            break
    prompt_before_export_injections = prompt

    # ===== DÉTECTION FORMAT / RÉSOLUTION + STYLE =====
    # Alignement résolution: Flux = multiples de 16, SDXL = multiples de 64
    align = 16 if is_flux else 64
    set_progress_phase("prepare_text2img", 10, 100)

    # 2. Export format — PRIORITAIRE sur la détection prompt (sauf "auto")
    export_fmt = export_settings.get('format', 'auto')
    if export_fmt != 'auto' and style_init_image is None:
        # Export settings définissent directement la taille du canvas
        if export_fmt == 'custom':
            width = int(export_settings.get('width', 768))
            height = int(export_settings.get('height', 1344))
        elif export_fmt in _TXT2IMG_RATIOS:
            width, height = _TXT2IMG_RATIOS[export_fmt]
        else:
            width, height = 768, 1344
        width = max(512, min(1536, (width // align) * align))
        height = max(512, min(1536, (height // align) * align))
        # Style toujours détecté depuis le prompt (pour prefix/suffix)
        _, _, style_prefix, style_suffix = _detect_text2img_format(prompt, is_turbo)
        print(f"[TEXT2IMG] Export format: {export_fmt} → {width}x{height}")
    elif style_init_image is not None:
        src_w, src_h = style_init_image.size
        aspect = src_w / src_h
        import math
        target_pixels = 1024 * 1024
        height = int(math.sqrt(target_pixels / aspect))
        width = int(height * aspect)
        width = max(512, min(1536, (width // align) * align))
        height = max(512, min(1536, (height // align) * align))
        _, _, style_prefix, style_suffix = _detect_text2img_format(prompt, is_turbo)
        print(f"[TEXT2IMG] Résolution depuis style ref: {src_w}x{src_h} → {width}x{height} (~1MP)")
    elif is_flux:
        # Flux: résolution par défaut 1024x1024
        width, height = 1024, 1024
        style_prefix, style_suffix = None, None
    else:
        width, height, style_prefix, style_suffix = _detect_text2img_format(prompt, is_turbo)

    # 3. Inject view + pose into prompt
    inject_parts = []
    view = export_settings.get('view', 'auto')
    pose = export_settings.get('pose', 'none')
    pose_distance = export_settings.get('pose_distance', 'auto')
    pose_orientation = export_settings.get('pose_orientation', 'auto')
    extra = export_settings.get('extraPrompt', '')
    if view != 'auto' and view in _VIEW_PROMPTS:
        inject_parts.append(_VIEW_PROMPTS[view])
    pose_neg = None
    pose_safety_neg = None
    pose_positive, pose_negative = get_pose_prompts(pose)
    if pose != 'none' and pose_positive:
        pose_positive = _adapt_pose_prompt_for_distance(pose_positive, pose_distance)
        pose_safety_prompt, pose_safety_neg = build_human_pose_safety_additions(
            " ".join(part for part in (prompt_before_export_injections, extra) if part),
            pose,
        )
        if pose_safety_prompt:
            inject_parts.append(pose_safety_prompt)
            print("[TEXT2IMG] Human pose safety: clothed neutral default")
        inject_parts.append(pose_positive)
        pose_neg = pose_negative
    distance_positive, distance_negative = _POSE_DISTANCE_PROMPTS.get(pose_distance, (None, None))
    if distance_positive:
        inject_parts.append(distance_positive)
        pose_neg = append_negative_prompt(pose_neg, distance_negative)
    orientation_positive, orientation_negative = _POSE_ORIENTATION_PROMPTS.get(pose_orientation, (None, None))
    if orientation_positive:
        inject_parts.append(orientation_positive)
        pose_neg = append_negative_prompt(pose_neg, orientation_negative)
    if extra:
        inject_parts.append(extra)
    if inject_parts:
        prompt = prompt + ', ' + ', '.join(inject_parts)
        print(f"[TEXT2IMG] Export injected: {', '.join(inject_parts)}")

    # Pose strength: quand une pose est active + style ref, réduire style_ref_scale
    # pour laisser le prompt de pose dominer la composition
    pose_strength = export_settings.get('pose_strength', 0.5)
    if style_init_image is not None and pose_strength > 0:
        # Interpoler: pose_strength=0 → garde style_ref_scale, =1+ → force à 0.05 (95% denoise)
        MIN_STYLE_SCALE = 0.05
        _ps_clamped = min(pose_strength, 1.0)  # slider va jusqu'à 1.5, clamp pour interpolation
        adjusted_scale = style_ref_scale * (1.0 - _ps_clamped) + MIN_STYLE_SCALE * _ps_clamped
        print(f"[TEXT2IMG] Pose strength={pose_strength}: style_ref_scale {style_ref_scale:.2f} → {adjusted_scale:.2f} (img_strength={1.0 - adjusted_scale:.2f})")
        style_ref_scale = adjusted_scale

    # ===== CONSTRUCTION DU PROMPT =====
    set_progress_phase("prepare_prompt", 25, 100)
    neg = None
    if is_flux:
        # Flux: prompt direct, pas de negative prompt, pas de prefix SDXL
        full_prompt = prompt
        print(f"[TEXT2IMG] Flux prompt direct (pas de negative)")
    elif enhance:
        enhanced_prompt, style = enhance_prompt_with_ai(prompt, for_inpainting=False)
        full_prompt, neg = build_full_prompt(enhanced_prompt, style, for_inpainting=False)
    else:
        neg = _build_text2img_negative_prompt(prompt, model_name)
        if style_prefix:
            # Style détecté (snapchat, webcam, etc.) → appliquer prefix + suffix
            full_prompt = f"{style_prefix}, {prompt}"
            if style_suffix:
                full_prompt = f"{full_prompt}, {style_suffix}"
            print(f"[TEXT2IMG] Style détecté → {style_prefix}")
        else:
            # Pas de style détecté → prompt neutre photo réaliste
            if _looks_preformatted_text2img_prompt(prompt):
                full_prompt = prompt
                print(f"[TEXT2IMG] Prompt déjà stylé → pas de wrapper RAW photo")
            elif _requests_stylized_text2img(prompt, model_name):
                full_prompt = f"{prompt}, high quality, detailed, sharp focus"
                print(f"[TEXT2IMG] Style anime/illustration/3D demandé → pas de wrapper RAW photo")
            else:
                full_prompt = f"RAW photo, photorealistic, {prompt}, high quality, detailed, sharp focus"
                print(f"[TEXT2IMG] Style par défaut → RAW photo neutre")

    neg = _sanitize_negative_for_requested_style(neg, prompt, model_name)

    # Append pose-specific negative prompt (SDXL only)
    if not is_flux:
        neg = append_negative_prompt(neg, pose_neg)
        neg = append_negative_prompt(neg, pose_safety_neg)

    # The word "camera" in pose/view helpers can make diffusion models draw a
    # literal device. Default text2img should describe viewpoint, not props.
    if neg and _should_suppress_visible_capture_devices(prompt_before_export_injections, style_prefix, style_suffix):
        neg = f"{neg}, {_CAPTURE_DEVICE_NEGATIVE}"

    try:
        from core.infra.model_imports import apply_imported_model_prompt_hooks
        full_prompt, neg = apply_imported_model_prompt_hooks(model_name, full_prompt, neg)
    except Exception as exc:
        print(f"[TEXT2IMG] Imported model hooks skipped: {exc}")

    print(f"[TEXT2IMG] Prompt: {full_prompt}")
    if neg:
        print(f"[TEXT2IMG] Negative: {neg}")
    print(f"[TEXT2IMG] Résolution: {width}x{height}")

    # Log VRAM avant génération
    from core.models import log_vram_status
    log_vram_status(f"Avant génération | {model_name}")

    # Pré-charger le tiny decoder AVANT la génération (évite le chargement pendant le denoising)
    set_progress_phase("prepare_preview_decoder", 45, 100)
    if is_flux:
        _get_taef1()  # TAEF1 ~2MB, 16 channels (Flux)
    else:
        _get_taesd()  # TAESD ~2MB, 4 channels (SDXL)

    # VAE tiling toujours activé — quasi invisible, évite OOM au décodage
    pipe.enable_vae_tiling()

    # Libérer le cache CUDA avant génération (surtout si IP-Adapter a chargé InsightFace)
    if ip_adapter_image_embeds is not None or style_init_image is not None:
        torch.cuda.empty_cache()
        print(f"[TEXT2IMG] CUDA cache vidé avant génération")

    # Seed: extraire du prompt (seed:12345) ou générer aléatoirement
    seed_match = re.search(r'\bseed[:\s](\d+)\b', prompt, re.IGNORECASE)
    if seed_match:
        seed = int(seed_match.group(1))
        # Retirer le seed du prompt final
        full_prompt = re.sub(r'\bseed[:\s]\d+\b', '', full_prompt, flags=re.IGNORECASE).strip().strip(',').strip()
    else:
        seed = random.randint(0, 2**32 - 1)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    print(f"[TEXT2IMG] Seed: {seed}")
    # Stocker pour le frontend
    _state.last_seed = seed

    print(f"[TEXT2IMG] Génération (steps={steps}, seed={seed})...")

    generation_start_time = time.time()

    # Initialiser les variables de preview sans effacer la phase runtime courante.
    _state.total_steps = steps

    # Créer le callback avec preview (tous les 1 step pour Turbo car peu de steps)
    # Sur macOS/MPS, le decode preview peut dominer le coût du denoising. On garde
    # la progression par step, mais on espace les images preview pour préserver la
    # vitesse de génération.
    # Passer height/width pour unpack des latents Flux (3D packed → 4D)
    is_mps_runtime = _is_mps_runtime()
    _apply_mps_sdxl_runtime_policy(pipe, f"{model_name} text2img runtime", is_mps_runtime)
    preview_every = 1 if is_turbo else (8 if is_mps_runtime else 2)
    callback = make_preview_callback(cancel_check, preview_every=preview_every,
                                     image_height=height, image_width=width,
                                     preview_first_step=not is_mps_runtime or is_turbo)

    # Détecter le type de pipeline
    is_inpaint_pipe = hasattr(pipe, 'mask_processor') or 'Inpaint' in pipe.__class__.__name__

    if is_flux:
        # ===== FLUX DEV TEXT2IMG =====
        # Flux: pas de negative_prompt, pas de width/height (utilise height+width params)
        # Style ref → FluxImg2ImgPipeline on-the-fly
        if style_init_image is not None:
            from diffusers import FluxImg2ImgPipeline
            img2img_pipe = FluxImg2ImgPipeline(**pipe.components)
            init_img = style_init_image.convert('RGB').resize((width, height), Image.LANCZOS)
            img_strength = max(0.05, min(0.9, 1.0 - style_ref_scale))
            print(f"[TEXT2IMG] Flux img2img depuis style ref (strength={img_strength})")
            set_progress_phase("diffusion", 0, steps)
            result = img2img_pipe(
                prompt=full_prompt,
                image=init_img,
                strength=img_strength,
                guidance_scale=guidance,
                num_inference_steps=steps,
                max_sequence_length=512,
                generator=generator,
                callback_on_step_end=callback,
            ).images[0]
        else:
            print(f"[TEXT2IMG] Flux Dev text2img ({width}x{height}, steps={steps})")
            set_progress_phase("diffusion", 0, steps)
            result = pipe(
                prompt=full_prompt,
                guidance_scale=guidance,
                num_inference_steps=steps,
                width=width,
                height=height,
                max_sequence_length=512,
                generator=generator,
                callback_on_step_end=callback,
            ).images[0]

    elif is_inpaint_pipe:
        # Fallback: si un pipeline inpaint est chargé par erreur pour text2img,
        # convertir en StableDiffusionXLPipeline (zero-copy, même composants)
        print(f"[TEXT2IMG] WARNING: pipeline inpaint détecté, conversion en text2img...")
        from diffusers import StableDiffusionXLPipeline
        txt2img_components = {k: v for k, v in pipe.components.items()
                              if k not in ('controlnet', 'image_encoder', 'mask_processor')}
        pipe = StableDiffusionXLPipeline(**txt2img_components)
        _apply_mps_sdxl_runtime_policy(pipe, f"{model_name} converted text2img runtime", is_mps_runtime)

        extra_kwargs = {}
        if ip_adapter_image_embeds is not None:
            pipe.set_ip_adapter_scale(ip_adapter_scale)
            extra_kwargs['ip_adapter_image_embeds'] = [ip_adapter_image_embeds]
            print(f"[TEXT2IMG] IP-Adapter FaceID activé (scale={ip_adapter_scale})")

        if style_init_image is not None:
            from diffusers import StableDiffusionXLImg2ImgPipeline
            img2img_pipe = StableDiffusionXLImg2ImgPipeline(**pipe.components)
            _apply_mps_sdxl_runtime_policy(img2img_pipe, f"{model_name} img2img runtime", is_mps_runtime)
            init_img = style_init_image.convert('RGB').resize((width, height), Image.LANCZOS)
            img_strength = max(0.05, min(0.9, 1.0 - style_ref_scale))
            print(f"[TEXT2IMG] Img2img depuis style ref (strength={img_strength})")
            set_progress_phase("diffusion", 0, steps)
            result = _run_sdxl_pipeline(
                img2img_pipe,
                f"{model_name} converted img2img decode",
                is_mps_runtime,
                prompt=full_prompt,
                negative_prompt=neg,
                image=init_img,
                strength=img_strength,
                guidance_scale=guidance,
                num_inference_steps=steps,
                generator=generator,
                callback_on_step_end=callback,
                **extra_kwargs,
            )
        else:
            print(f"[TEXT2IMG] Pipeline text2img converti ({pipe.__class__.__name__})")
            set_progress_phase("diffusion", 0, steps)
            result = _run_sdxl_pipeline(
                pipe,
                f"{model_name} converted text2img decode",
                is_mps_runtime,
                prompt=full_prompt,
                negative_prompt=neg,
                guidance_scale=guidance,
                num_inference_steps=steps,
                width=width,
                height=height,
                generator=generator,
                callback_on_step_end=callback,
                **extra_kwargs,
            )

    else:
        # Pipeline text2img dédié (StableDiffusionXLPipeline ou Turbo, sans Fooocus patch)
        extra_kwargs = {}
        # IP-Adapter FaceID (si face ref fourni)
        if ip_adapter_image_embeds is not None:
            pipe.set_ip_adapter_scale(ip_adapter_scale)
            extra_kwargs['ip_adapter_image_embeds'] = [ip_adapter_image_embeds]
            print(f"[TEXT2IMG] IP-Adapter FaceID activé (scale={ip_adapter_scale})")

        # ===== ControlNet: determine control image (depth map or skeleton) =====
        cn_control_image = None
        if controlnet_model is not None:
            set_progress_phase("prepare_pose_control", 0, 100)
            if controlnet_depth_image is not None:
                # Pre-extracted depth map from style ref (ControlNet Depth)
                cn_control_image = controlnet_depth_image.resize((width, height), Image.BILINEAR)
                print(f"[TEXT2IMG] ControlNet Depth: depth map {width}x{height}")
            elif controlnet_pose and controlnet_pose != 'none':
                # Explicit export pose → skeleton image (ControlNet OpenPose)
                from core.generation.pose_skeletons import generate_pose_skeleton
                cn_control_image = generate_pose_skeleton(controlnet_pose, width, height)
                if cn_control_image is not None:
                    print(f"[TEXT2IMG] ControlNet OpenPose: squelette '{controlnet_pose}' ({width}x{height})")
                else:
                    print(f"[TEXT2IMG] Pas de squelette pour '{controlnet_pose}' → fallback prompt (CN désactivé)")
            elif style_init_image is not None:
                # Fallback: extract skeleton from style reference (OpenPose)
                try:
                    from core.generation.body_estimation import detect_pose, unload_dwpose
                    _ref_resized = style_init_image.convert('RGB').resize((width, height), Image.LANCZOS)
                    cn_control_image, _ = detect_pose(_ref_resized)
                    unload_dwpose()
                    torch.cuda.empty_cache()
                    if cn_control_image is not None:
                        if cn_control_image.size != (width, height):
                            cn_control_image = cn_control_image.resize((width, height), Image.BILINEAR)
                        print(f"[TEXT2IMG] ControlNet OpenPose: squelette extrait de style ref ({width}x{height})")
                    else:
                        print(f"[TEXT2IMG] Aucune pose détectée dans style ref, CN désactivé")
                except Exception as _e_pose:
                    print(f"[TEXT2IMG] Extraction pose échouée ({_e_pose}), CN désactivé")

            # Save debug control image
            if cn_control_image is not None:
                try:
                    _debug_dir = Path(__file__).resolve().parent.parent.parent / "output"
                    _debug_dir.mkdir(exist_ok=True)
                    _debug_name = "debug_cn_depth.png" if controlnet_depth_image is not None else "debug_cn_skeleton.png"
                    _debug_path = _debug_dir / _debug_name
                    cn_control_image.save(_debug_path)
                    print(f"[TEXT2IMG] Debug control image sauvé: {_debug_path}")
                except Exception as _e_dbg:
                    print(f"[TEXT2IMG] Debug save failed: {_e_dbg}")

        # ===== ControlNet pipeline (zero-copy wrapper) =====
        if cn_control_image is not None and controlnet_model is not None:
            set_progress_phase("prepare_pose_control", 70, 100)
            # Move ControlNet to CUDA for generation
            from core.models import IS_MAC
            _cn_device = "mps" if IS_MAC else "cuda"
            controlnet_model.to(_cn_device)

            # Filter components compatible with CN pipeline
            cn_components = {k: v for k, v in pipe.components.items()
                            if k not in ('controlnet', 'image_encoder', 'mask_processor')}

            if style_init_image is not None:
                # ControlNet + img2img: enforce pose/depth + appearance from style ref
                from diffusers import StableDiffusionXLControlNetImg2ImgPipeline
                cn_pipe = StableDiffusionXLControlNetImg2ImgPipeline(**cn_components, controlnet=controlnet_model)
                _apply_mps_sdxl_runtime_policy(cn_pipe, f"{model_name} ControlNet img2img runtime", is_mps_runtime)
                init_img = style_init_image.convert('RGB').resize((width, height), Image.LANCZOS)
                img_strength = max(0.05, min(0.9, 1.0 - style_ref_scale))
                _cn_type = "Depth" if controlnet_depth_image is not None else "OpenPose"
                print(f"[TEXT2IMG] ControlNet {_cn_type} + img2img (cn_scale={controlnet_scale}, img_strength={img_strength})")
                set_progress_phase("diffusion", 0, steps)
                result = _run_sdxl_pipeline(
                    cn_pipe,
                    f"{model_name} ControlNet img2img decode",
                    is_mps_runtime,
                    prompt=full_prompt,
                    negative_prompt=neg if not is_turbo else None,
                    image=init_img,
                    control_image=cn_control_image,
                    strength=img_strength,
                    controlnet_conditioning_scale=controlnet_scale,
                    guidance_scale=guidance,
                    num_inference_steps=steps,
                    generator=generator,
                    callback_on_step_end=callback,
                    **extra_kwargs,
                )
            else:
                # ControlNet text2img: pose from skeleton, no reference image
                from diffusers import StableDiffusionXLControlNetPipeline
                cn_pipe = StableDiffusionXLControlNetPipeline(**cn_components, controlnet=controlnet_model)
                _apply_mps_sdxl_runtime_policy(cn_pipe, f"{model_name} ControlNet text2img runtime", is_mps_runtime)
                print(f"[TEXT2IMG] ControlNet OpenPose text2img (cn_scale={controlnet_scale})")
                set_progress_phase("diffusion", 0, steps)
                result = _run_sdxl_pipeline(
                    cn_pipe,
                    f"{model_name} ControlNet text2img decode",
                    is_mps_runtime,
                    prompt=full_prompt,
                    negative_prompt=neg if not is_turbo else None,
                    image=cn_control_image,
                    controlnet_conditioning_scale=controlnet_scale,
                    guidance_scale=guidance,
                    num_inference_steps=steps,
                    width=width,
                    height=height,
                    generator=generator,
                    callback_on_step_end=callback,
                    **extra_kwargs,
                )

            # Move ControlNet back to CPU to free VRAM
            controlnet_model.to("cpu")
            torch.cuda.empty_cache()

        elif style_init_image is not None:
            # Si style ref → convertir en img2img pipeline (zero-copy, mêmes composants)
            from diffusers import StableDiffusionXLImg2ImgPipeline
            img2img_pipe = StableDiffusionXLImg2ImgPipeline(**pipe.components)
            _apply_mps_sdxl_runtime_policy(img2img_pipe, f"{model_name} img2img runtime", is_mps_runtime)
            init_img = style_init_image.convert('RGB').resize((width, height), Image.LANCZOS)
            img_strength = max(0.05, min(0.9, 1.0 - style_ref_scale))
            print(f"[TEXT2IMG] Img2img depuis style ref (strength={img_strength}, scale={style_ref_scale})")
            set_progress_phase("diffusion", 0, steps)
            result = _run_sdxl_pipeline(
                img2img_pipe,
                f"{model_name} img2img decode",
                is_mps_runtime,
                prompt=full_prompt,
                negative_prompt=neg if not is_turbo else None,
                image=init_img,
                strength=img_strength,
                guidance_scale=guidance,
                num_inference_steps=steps,
                generator=generator,
                callback_on_step_end=callback,
                **extra_kwargs,
            )
        else:
            print(f"[TEXT2IMG] Pipeline text2img ({pipe.__class__.__name__})")
            set_progress_phase("diffusion", 0, steps)
            result = _run_sdxl_pipeline(
                pipe,
                f"{model_name} text2img decode",
                is_mps_runtime,
                prompt=full_prompt,
                negative_prompt=neg if not is_turbo else None,
                guidance_scale=guidance,
                num_inference_steps=steps,
                width=width,
                height=height,
                generator=generator,
                callback_on_step_end=callback,
                **extra_kwargs,
            )

    # Calculer le temps de génération
    generation_time = time.time() - generation_start_time
    print(f"✅ [TEXT2IMG] Terminé en {generation_time:.1f}s (seed={seed})")

    # Libérer VRAM après génération
    torch.cuda.empty_cache()

    # Nettoyer la preview après génération
    clear_preview()

    _state.current_image = result
    _state.original_image = None  # Pas d'original pour txt2img

    # Ajouter au contexte
    _state.context_history.append({
        "prompt": prompt,
        "image": result,
        "type": "txt2img"
    })
    if len(_state.context_history) > MAX_HISTORY:
        _state.context_history.pop(0)

    # Sauvegarder (historique + last pour le frontend)
    from datetime import datetime
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_path = images_dir / f"txt2img_{timestamp}.png"
    result.save(image_path)
    result.save(output_dir / "last_generated.png")
    save_gallery_metadata(
        image_path,
        asset_type="image",
        source="imagine",
        model=model_name,
        prompt=prompt,
        final_prompt=full_prompt,
        negative_prompt=neg,
        steps=steps,
        width=result.size[0],
        height=result.size[1],
    )

    return result, "OK", generation_time
