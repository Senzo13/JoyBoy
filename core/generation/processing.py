"""
Traitement d'images: masques, segmentation, generation.
Hub module — re-exports from submodules for backward compatibility.
Keeps process_image() (main inpainting pipeline).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import numpy as np
import torch
import time
import random
from pathlib import Path

from core.models import MODELS, snap_to_warmup_size, WARMUP_SIZES
from core.infra.gallery_metadata import save_gallery_metadata

# ======================================================================
# Re-exports from submodules — backward compat for:
#   from core.processing import X  (via _AliasModule in core/__init__.py)
#   from core.generation.processing import X
# ======================================================================

# state.py — Generation state, exceptions, progress wrappers, context
from core.generation.state import (
    GenerationCancelledException,
    GenerationState,
    _state,
    _prompt_embed_cache,
    _PROMPT_CACHE_MAX,
    MAX_HISTORY,
    get_video_progress,
    update_video_progress,
    clear_video_progress,
    get_current_preview,
    get_current_preview_status,
    clear_preview,
    set_phase,
    set_progress_phase,
    get_current_images,
    get_video_info,
    reset_video,
    delete_video_for_chat,
    get_context_summary,
    clear_context,
)

# compositing.py — Fill, blend, crop, color matching
from core.generation.compositing import (
    _box_blur,
    fooocus_fill,
    morphological_open,
    _pixel_composite,
    _estimate_image_quality,
    _harmonize_quality,
    _compute_inpaint_crop,
    _detect_skin_pixels,
    _save_color_debug,
    match_colors,
    laplacian_pyramid_blend,
    composite_with_original,
)

# preview.py — TAESD/TAEF1 previews, face detector, dimension helpers
from core.generation.preview import (
    face_cascade,
    _taesd,
    _taesd_loading,
    _taef1,
    _taef1_loading,
    make_cancel_callback,
    _get_taesd,
    _get_taef1,
    _unpack_flux_latents,
    make_preview_callback,
    load_face_detector,
    adjust_to_multiple_of_8,
)

# callbacks.py — Soft inpaint, Fooocus clamp, adaptive CFG, quality harmonize
from core.generation.callbacks import (
    SOFT_INPAINT_FEATHER_RADIUS,
    SOFT_INPAINT_BLEND_POWER,
    SOFT_INPAINT_BLEND_SCALE,
    SOFT_INPAINT_DETAIL,
    FOOOCUS_SHARPNESS,
    ADM_SCALER_END,
    ADM_SMALL_IMAGE_THRESH,
    ADM_POS_SCALE,
    ADM_NEG_SCALE,
    QUALITY_SHARPNESS_RATIO,
    COMPOSITE_RADIUS_BRUSH,
    COMPOSITE_RADIUS_SEG,
    _magnitude_preserving_blend,
    make_soft_inpaint_callback,
    make_fooocus_clamp_callback,
    make_adaptive_cfg_callback,
    _harmonize_upscaler,
    _quality_harmonize,
)

# video.py — MMAudio + generate_video
from core.generation.video import (
    _mmaudio_loaded,
    _mmaudio_net,
    _mmaudio_feature_utils,
    _mmaudio_config,
    add_audio_to_video,
    unload_mmaudio,
    generate_video,
)

# text2img.py — Text-to-image styles, format detection, generation
from core.generation.text2img import (
    _TXT2IMG_STYLES,
    _TXT2IMG_RATIOS,
    _detect_text2img_format,
    generate_from_text,
)

# transforms.py — Upscale, reframe, expand
from core.generation.transforms import (
    REFRAME_SCALES,
    DEFAULT_REFRAME_SCALE,
    _detect_reframe_scale,
    upscale_image,
    reframe_person,
    expand_image,
)


# ======================================================================
# Dtype guards
# ======================================================================

def _infer_ip_adapter_embed_dim(projection_layer, default: int = 512) -> int:
    """Return the raw image-embedding width expected by an IP-Adapter layer.

    Diffusers projection modules are not uniform: classic IP-Adapter exposes
    image_embed_dim, but FaceID does not store it after construction. When no
    face is detected we still need a correctly shaped zero embedding so the
    already-loaded adapter does not crash the generation path.
    """
    for attr in ("image_embed_dim", "clip_embeddings_dim", "id_embeddings_dim", "embed_dim"):
        value = getattr(projection_layer, attr, None)
        if isinstance(value, int) and value > 0:
            return value

    for _, param in projection_layer.named_parameters(recurse=True):
        shape = getattr(param, "shape", None)
        if shape is not None and len(shape) == 2:
            in_features = int(shape[1])
            if 0 < in_features <= 8192:
                return in_features

    return default


def _make_ip_adapter_zero_embeds(pipe) -> list:
    """Build zero embeds for every loaded IP-Adapter projection layer.

    Keep this as a helper instead of inline shape guessing. We have already hit
    regressions where FaceID and standard IP-Adapter expose different attrs;
    the generation code should only ask for neutral embeds and move on.

    Diffusers expects precomputed IP-Adapter embeds as [negative, positive]
    when classifier-free guidance is active. A single zero embed crashes later
    in prepare_ip_adapter_image_embeds() because it tries to chunk the batch.
    """
    unet = getattr(pipe, "unet", None)
    projection = getattr(unet, "encoder_hid_proj", None)
    layers = list(getattr(projection, "image_projection_layers", []) or [])
    if not layers and projection is not None:
        layers = [projection]

    dtype = getattr(unet, "dtype", torch.float16)
    if not layers:
        layers = [None]

    embeds = []
    for layer in layers:
        embed_dim = _infer_ip_adapter_embed_dim(layer) if layer is not None else 512
        embeds.append(torch.zeros(2, 1, embed_dim, device="cpu", dtype=dtype))
    return embeds

def _align_text_encoder_dtypes(pipe, preferred_dtype=None, force=False):
    """Ré-aligne les text encoders SDXL si des poids/adapters restent en float32.

    Avec BF16 sur GPU >= 16GB, certains adapters/LoRAs peuvent rester en float32
    alors que les couches CLIP de base sont en bf16. Le résiduel devient alors
    float32 et plante au layer_norm suivant ("expected scalar type BFloat16 but found Float").
    """
    repaired = []

    for enc_name in ("text_encoder", "text_encoder_2"):
        enc = getattr(pipe, enc_name, None)
        if enc is None:
            continue

        floating_dtypes = set()
        for tensor in enc.parameters():
            if tensor is not None and tensor.is_floating_point():
                floating_dtypes.add(tensor.dtype)
        for tensor in enc.buffers():
            if tensor is not None and tensor.is_floating_point():
                floating_dtypes.add(tensor.dtype)

        if not floating_dtypes:
            continue

        if preferred_dtype is not None and (force or preferred_dtype in floating_dtypes):
            target_dtype = preferred_dtype
        elif torch.bfloat16 in floating_dtypes:
            target_dtype = torch.bfloat16
        elif torch.float16 in floating_dtypes:
            target_dtype = torch.float16
        else:
            target_dtype = next(iter(floating_dtypes))

        needs_cast = force or len(floating_dtypes) > 1 or target_dtype not in floating_dtypes
        if not needs_cast:
            continue

        try:
            enc.to(dtype=target_dtype)
            repaired.append(
                f"{enc_name}: {','.join(sorted(str(dt).replace('torch.', '') for dt in floating_dtypes))} -> "
                f"{str(target_dtype).replace('torch.', '')}"
            )
        except Exception as e:
            print(f"[DTYPE] {enc_name} cast skip: {e}")

    if repaired:
        print(f"[DTYPE] Text encoders realigned: {' | '.join(repaired)}")

    return repaired


_GALLERY_META_EXPLICIT_KEYS = {
    "asset_type", "source", "model", "prompt", "final_prompt", "negative_prompt",
    "intent", "steps", "strength", "width", "height", "original_prompt",
}


def _gallery_extra_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    return {k: v for k, v in metadata.items() if k not in _GALLERY_META_EXPLICIT_KEYS}


# ======================================================================
# process_image — main inpainting pipeline (stays in hub)
# ======================================================================

def process_image(image: Image.Image, prompt: str, strength: float, model_name: str,
                   mask: Image.Image = None, enhance: bool = False, steps: int = 40,
                   cancel_check=None, negative_prompt: str = None, pipe=None,
                   control_image=None, controlnet_conditioning_scale: float = 0.5,
                   ip_adapter_image_embeds=None, skip_auto_refine: bool = False,
                   guidance_scale: float = None, ip_adapter_scale: float = 0.6,
                   brush_mode: bool = False, composite_radius: int = None,
                   enable_controlnet: bool = True,
                   intent: str = None, metadata: dict = None):
    """
    Pipeline de génération inpainting.
    Le masque est pré-calculé par app.py via Smart Router + create_smart_mask.

    Retourne: (image_result, original_image, status, generation_time)

    Args:
        image: Image source
        prompt: Prompt final (déjà enhanced par app.py)
        strength: Force d'inpainting (0.0-1.0)
        model_name: Nom du modèle
        mask: Masque pré-calculé (blanc = zone à modifier). Si None, masque blanc complet.
        enhance: Non utilisé (prompt déjà enhanced par app.py), gardé pour compat
        steps: Nombre d'étapes
        cancel_check: callable pour annulation
        negative_prompt: Negative prompt
        pipe: Pipeline inpainting (injecté par ModelManager)
        control_image: Image de pose ControlNet (optionnel)
        controlnet_conditioning_scale: Force du ControlNet (0.0-1.0)
    """
    if image is None:
        return None, None, "Upload une photo", 0

    if not prompt.strip():
        return None, None, "Ecris ce que tu veux", 0

    full_prompt = prompt
    neg = negative_prompt if negative_prompt else "blurry, low quality, distorted, deformed"

    # Fooocus Sharp prompt template — "film grain, grainy, shot on kodak" are critical
    # for realistic skin texture (pores, grain, micro-detail). Without them, skin looks plastic.
    # Anime/manga prompts must not use this photo wrapper or a negative that bans anime.
    _FOOOCUS_SHARP = "cinematic still {prompt}, maintaining exact pose and body proportions . harmonious, 4k epic detailed, shot on kodak, 35mm photo, sharp focus, high budget, natural lighting, even skin tone, epic, gorgeous, film grain, grainy"
    _FOOOCUS_SHARP_NEG = "anime, cartoon, graphic, (blur, blurry, bokeh), text, painting, crayon, graphite, abstract, glitch, deformed, mutated, ugly, disfigured, changed pose, different proportions"
    _ANIME_QUALITY = "{prompt}, original anime style, detailed manga art, clean line art, soft shading, vibrant colors, high quality"
    _ANIME_NEG = "blurry, low quality, deformed, bad anatomy, text, watermark, extra limbs, missing limbs, changed pose, different proportions"
    _is_flux_model = model_name and ('flux' in model_name.lower() or 'kontext' in model_name.lower())
    _prompt_probe = f"{full_prompt}".lower()
    _model_probe = f"{model_name or ''}".lower()
    _prompt_requests_photo = any(word in _prompt_probe for word in (
        "photo", "photorealistic", "realistic", "raw", "35mm", "kodak", "cinematic",
    ))
    _prompt_requests_anime = any(word in _prompt_probe for word in (
        "anime", "manga", "2d animation", "2d style", "toon", "cel shading", "line art",
    ))
    _model_is_anime_family = any(word in _model_probe for word in (
        "illustrious", "pony", "animagine",
    ))
    _is_anime_style = _prompt_requests_anime or (_model_is_anime_family and not _prompt_requests_photo)
    _is_pose_change = intent == 'pose_change'
    _is_fix_details = intent == 'fix_details'
    _is_repose = intent in ('repose', 'background_fill')
    if _is_fix_details:
        # ADetailer: minimal wrapping, preserve identity. Prompt already contains
        # the original gen prompt + face detail suffix from generation.py.
        # Low strength (0.30) + same prompt = enhance details without changing face.
        if not _is_flux_model:
            full_prompt = f"{full_prompt}, same person, same identity, 4k detailed, sharp focus, film grain"
            neg = f"different person, different face, {neg}"
    elif _is_repose:
        # Repose/background_fill: prompt already built by generation.py, skip Fooocus wrapping
        # Just add minimal quality suffix without pose/clothing constraints
        if not _is_flux_model:
            if _is_anime_style:
                full_prompt = _ANIME_QUALITY.replace("{prompt}", full_prompt)
                _repose_neg = _ANIME_NEG
            else:
                full_prompt = f"cinematic still {full_prompt} . harmonious, 4k epic detailed, sharp focus, natural lighting, film grain, grainy"
                _repose_neg = "anime, cartoon, graphic, (blur, blurry, bokeh), text, painting, abstract, glitch, deformed, mutated, ugly, disfigured"
            neg = f"{_repose_neg}, {neg}" if neg else _repose_neg
    elif _is_pose_change:
        # Pose change: quality wrap but NO "maintaining pose" (counterproductive)
        # Ajouter "same clothing, same color" seulement si le user ne mentionne pas de vêtements
        import re as _re_pose
        _CLOTHING_WORDS = _re_pose.compile(
            r'\b(robe|dress|jupe|skirt|pantalon|pants|jean|short|bikini|lingerie|'
            r'top|shirt|chemise|veste|jacket|coat|manteau|nude|naked|nue?|'
            r'maillot|swimsuit|underwear|bra|string|tenue|outfit|habit|vêtement|'
            r'rouge|bleu|vert|noir|blanc|rose|jaune|red|blue|green|black|white|pink)\b',
            _re_pose.IGNORECASE
        )
        _has_clothing = bool(_CLOTHING_WORDS.search(full_prompt))
        _clothing_suffix = "" if _has_clothing else ", same clothing, same color, same appearance"
        _neg_clothing = "" if _has_clothing else ", different clothing, different color"
        if _is_anime_style:
            full_prompt = f"{full_prompt}{_clothing_suffix}, original anime style, clean line art, high quality"
            _pose_neg = f"{_ANIME_NEG}, different person{_neg_clothing}"
        else:
            full_prompt = f"cinematic still {full_prompt}{_clothing_suffix} . harmonious, 4k epic detailed, sharp focus, high budget, natural lighting, even skin tone, film grain, grainy"
            _pose_neg = f"anime, cartoon, graphic, (blur, blurry, bokeh), text, painting, abstract, glitch, deformed, mutated, ugly, disfigured, different person{_neg_clothing}"
        neg = f"{_pose_neg}, {neg}" if neg else _pose_neg
    elif not _is_flux_model:
        if _is_anime_style:
            full_prompt = _ANIME_QUALITY.replace("{prompt}", full_prompt)
            neg = _ANIME_NEG
        else:
            full_prompt = _FOOOCUS_SHARP.replace("{prompt}", full_prompt)
            neg = _FOOOCUS_SHARP_NEG

    try:
        from core.infra.model_imports import apply_imported_model_prompt_hooks
        full_prompt, neg = apply_imported_model_prompt_hooks(model_name, full_prompt, neg)
    except Exception as exc:
        print(f"[PROMPT] Imported model hooks skipped: {exc}")

    print(f"\n{'='*60}")
    print(f"  IMAGE GENERATION")
    print(f"{'='*60}")
    print(f"  Model:    {model_name}")
    print(f"  Prompt:   {full_prompt}")
    print(f"  Negative: {neg}")
    print(f"  Image:    {image.size[0]}x{image.size[1]} mode={image.mode}")
    print(f"  Mask:     {'OUI' if mask is not None else 'NON (masque blanc)'}")
    print(f"  Strength: {strength}")
    print(f"  Steps:    {steps}")
    if control_image:
        print(f"  ControlNet Depth: OUI (scale={controlnet_conditioning_scale})")
    print(f"{'='*60}")

    # Sauvegarder l'original
    _state.original_image = image.copy()
    original_size = image.size
    w, h = image.size

    # Le pipe est injecté par l'appelant (ModelManager via generation_pipeline)
    if pipe is None:
        raise ValueError("pipe must be provided (injected by ModelManager)")

    # Détecter si c'est Flux Fill ou Kontext AVANT tout resize
    pipe_class = type(pipe).__name__
    is_flux = "Flux" in pipe_class or "FluxFill" in pipe_class
    is_kontext = "Edit" in pipe_class or "Kontext" in pipe_class

    # Detect 4-ch early (needed for warmup snap decision)
    _is_4ch_model = hasattr(pipe, 'unet') and pipe.unet.config.in_channels == 4
    # background_fill: skip ALL Fooocus features (InpaintHead, crop-to-mask, pre-fill, SDE)
    # Fooocus conditions on original content → recreates person instead of filling background
    _skip_fooocus = intent == 'background_fill'
    if _skip_fooocus:
        print(f"[BACKGROUND_FILL] Fooocus features disabled (remove person, not preserve)")
    # Crop-to-mask: 4-ch model with a mask → the crop area gets its own dimensions
    # via shape_ceil, so warmup snap on the full image is useless and DESTROYS resolution.
    # Example: 856x1280 → snap 640x896 → crop 427x593 instead of cropping from 856x1280.
    _preserve_mask_geometry = brush_mode and mask is not None
    _will_crop_to_mask = _is_4ch_model and mask is not None and not _skip_fooocus and not _preserve_mask_geometry

    # Ajuster dimensions - snap à une taille warmup pour éviter recompilation CUDA
    # SAUF pour Kontext, crop-to-mask et brush manuel: ces modes doivent garder
    # un repère pixel stable entre image, masque, preview et composite final.
    if not is_kontext and not _will_crop_to_mask and not _preserve_mask_geometry:
        target_w, target_h = snap_to_warmup_size(w, h)
        if (target_w, target_h) != (w, h):
            print(f"[WARMUP] Snap {w}x{h} → {target_w}x{target_h} (taille warmup)")
            image = image.resize((target_w, target_h), Image.LANCZOS)
            w, h = target_w, target_h
    elif _will_crop_to_mask:
        print(f"[WARMUP] Skip snap (crop-to-mask active, keeping {w}x{h})")
    elif brush_mode and _is_4ch_model and mask is not None:
        print(f"[WARMUP] Brush mode: crop-to-mask disabled, keeping mask geometry stable")

    # S'assurer que l'image est en RGB
    if image.mode != "RGB":
        image = image.convert("RGB")

    w, h = image.size

    # Masque pré-calculé par app.py (Smart Router)
    if mask is None:
        mask = Image.new("L", (w, h), 255)
        print(f"[MASK] Pas de masque fourni → masque blanc (toute l'image)")
    else:
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.BILINEAR)
        if mask.mode != "L":
            mask = mask.convert("L")

    # Flux Fill : dimensions doivent être multiples de 16 (pas 8)
    # SAUF Kontext qui gère ça en interne et doit garder la taille exacte
    if is_flux and not is_kontext:
        align = 16
        w_new = (w // align) * align
        h_new = (h // align) * align
        if w_new != w or h_new != h:
            image = image.resize((w_new, h_new), Image.LANCZOS)
            if mask is not None:
                mask = mask.resize((w_new, h_new), Image.BILINEAR)
            w, h = w_new, h_new
            print(f"[FLUX] Alignement {original_size[0]}x{original_size[1]} → {w}x{h} (multiples de 16)")

    # Vérifier annulation avant génération
    if cancel_check and cancel_check():
        raise GenerationCancelledException("Génération annulée")

    # Ajuster num_inference_steps pour que steps effectifs = steps demandés par l'utilisateur
    # Diffusers: effective = int(num_inference_steps * strength), on skip les premiers steps
    # On veut: effective = steps → num_inference_steps = ceil(steps / strength)
    import math
    clear_preview()
    set_progress_phase("prepare_generation", 0, steps)
    if strength < 1.0 and not is_kontext and not is_flux:
        adjusted_steps = math.ceil(steps / strength)
    else:
        adjusted_steps = steps
    _state.total_steps = steps  # Preview affiche ce que l'utilisateur a réglé

    # Pré-charger TAESD AVANT la génération (évite le chargement pendant le denoising)
    _get_taesd()

    # Créer le callback avec preview (resize à la taille originale)
    # Passer h/w pour unpack des latents Flux (3D→4D)
    callback = make_preview_callback(cancel_check, preview_every=5, target_size=original_size, image_height=h, image_width=w)

    generation_start_time = time.time()

    if is_kontext:
        # Flux Kontext — editing intelligent via prompt
        # Issue GitHub #11886: prompts simples ignorés, besoin guidance élevé
        # Prompt format: "In this picture... [description]. [instruction]"
        kontext_steps = max(steps, 28)  # Minimum 28 pour Kontext

        pipe_kwargs = dict(
            prompt=full_prompt,
            image=image,
            height=h,  # Garder la taille originale
            width=w,
            num_inference_steps=kontext_steps,
            guidance_scale=4.5,  # 4.5 recommandé pour meilleurs résultats (issue #11886)
            callback_on_step_end=callback,
        )
        print(f"[KONTEXT] Flux Kontext editing {w}x{h} (steps={kontext_steps}, guidance=4.5)")
    elif is_flux:
        # Flux Fill 12B — pas de strength, pas de negative_prompt
        pipe_kwargs = dict(
            prompt=full_prompt,
            image=image,
            mask_image=mask,
            height=h,
            width=w,
            guidance_scale=30.0,
            num_inference_steps=steps,
            max_sequence_length=512,
            callback_on_step_end=callback,
        )
        print(f"[INPAINT] Flux Fill 12B (guidance=30, steps={steps})")
    else:
        # SDXL / SD 1.5 — pipeline classique
        # adjusted_steps compense le strength pour que l'utilisateur voie ses steps exacts
        # guidance_scale: model_behaviors.json (défaut 5.0 pour SDXL, recommandé par epiCRealism)
        sdxl_guidance = guidance_scale or 5.0

        # === PROMPT EMBEDDING CACHE (monkey-patch) ===
        # Intercepte encode_prompt INSIDE le pipeline.__call__ pour cacher les résultats.
        # 1ère gen: encode normalement via group offload, cache sur CPU.
        # 2ème gen+: cache hit → retourne embeddings sans toucher aux text encoders → skip ~3s.
        if not getattr(pipe, '_encode_prompt_patched', False):
            _orig_encode = pipe.encode_prompt
            def _make_cached_encode(_orig):
                def _cached_encode_prompt(*args, **kwargs):
                    _p = kwargs.get('prompt', args[0] if args else '')
                    _n = kwargs.get('negative_prompt', '')
                    _key = (_p, _n)
                    if _key in _prompt_embed_cache:
                        _dev = kwargs.get('device', torch.device('cuda'))
                        _dtype = kwargs.get('dtype', None)
                        _cached = _prompt_embed_cache[_key]
                        print(f"[PERF] Prompt cache hit → skip text encoders")
                        return tuple(t.to(device=_dev, dtype=_dtype) if _dtype else t.to(device=_dev) for t in _cached)
                    _t_enc = time.time()
                    _result = _orig(*args, **kwargs)
                    _prompt_embed_cache[_key] = tuple(t.detach().cpu().clone() for t in _result)
                    if len(_prompt_embed_cache) > _PROMPT_CACHE_MAX:
                        _prompt_embed_cache.pop(next(iter(_prompt_embed_cache)))
                    print(f"[PERF] Prompt encoded + cached ({time.time() - _t_enc:.2f}s)")
                    return _result
                return _cached_encode_prompt
            pipe.encode_prompt = _make_cached_encode(_orig_encode)
            pipe._encode_prompt_patched = True

        # === SOFT INPAINTING: encoder l'image originale et préparer le masque soft ===
        # Active pour tous les modèles SDXL (4-ch et 9-ch)
        # Pour 4-ch: mask=all-white (notre callback gère le blend)
        # Pour 9-ch: mask=feathered (le UNet voit la transition douce)
        num_unet_ch = pipe.unet.config.in_channels if hasattr(pipe, 'unet') else 4
        is_4ch = (num_unet_ch == 4)
        print(f"[SOFT] UNet channels: {num_unet_ch} ({'4-ch soft inpainting' if is_4ch else '9-ch pipeline masking'})")

        # Fooocus 4-ch defaults: strength=1.0 (pure noise start) + CFG=7.0
        # Fooocus ALWAYS starts from pure noise — the callback handles blending.
        # strength < 1.0 gives the model less freedom → smoother/flatter skin texture.
        FOOOCUS_CFG = 7.0
        if is_4ch and mask is not None and not _skip_fooocus:
            if strength < 1.0:
                strength = 1.0
                adjusted_steps = steps  # No compensation at strength=1.0
                print(f"[FOOOCUS] Strength forced to 1.0 (pure noise start, callback handles blend)")
            sdxl_guidance = FOOOCUS_CFG
            print(f"[FOOOCUS] CFG forced to {FOOOCUS_CFG} (Fooocus default)")

        _saved_scheduler = None  # Will be set if we switch to SDE

        # Extra dilation DISABLED — segmentation already dilates (5x5 x3 tight mode)
        # and max_pool2d(8,8) in latent space handles VAE block alignment.
        # Adding more dilation makes the mask cover too much skin area.

        # Fooocus-style crop-to-mask: crop around mask area, upscale to ~1 Mpx
        # Uses geometric mean (shape_ceil) like Fooocus, NOT just long side = 1024.
        # Old method (long side 1024): 507x791 → 656x1024 = 0.67 Mpx (detail loss!)
        # New method (shape_ceil 1024): 507x791 → 832x1280 = 1.07 Mpx (SDXL optimal)
        # SDXL trained on ~1 Mpx — giving it less = quality/detail loss.
        _inpaint_crop = None
        _pre_crop_image = None
        _pre_crop_mask = None
        _pre_crop_w, _pre_crop_h = w, h
        if is_4ch and mask is not None and not _skip_fooocus:
            set_progress_phase("prepare_region", 0, steps)
            _mask_for_crop = np.array(mask.convert('L').resize((w, h), Image.BILINEAR))
            _inpaint_crop = _compute_inpaint_crop(_mask_for_crop)
            if _inpaint_crop is not None:
                _crop_a, _crop_b, _crop_c, _crop_d = _inpaint_crop
                # Save pre-crop state for uncropping later
                _pre_crop_image = image.resize((w, h), Image.LANCZOS)
                _pre_crop_mask = mask
                # Crop image and mask (both at (w, h) resolution)
                image = _pre_crop_image.crop((_crop_c, _crop_a, _crop_d, _crop_b))
                _mask_wh = mask.convert('L').resize((w, h), Image.BILINEAR)
                mask = Image.fromarray(np.array(_mask_wh.crop((_crop_c, _crop_a, _crop_d, _crop_b))), mode='L')
                # Crop control_image if present
                if control_image is not None:
                    _ctrl_wh = control_image.resize((w, h), Image.LANCZOS)
                    control_image = _ctrl_wh.crop((_crop_c, _crop_a, _crop_d, _crop_b))
                # Fooocus-style shape_ceil: target ~1 Mpx (geometric mean = 1024)
                # This is much more aggressive than just scaling the long side to 1024px.
                # Example: 507x791 crop → 832x1280 (1.06 Mpx) instead of 656x1024 (0.67 Mpx)
                import math
                _crop_target = 1024  # geometric mean target
                _crop_pw = _crop_d - _crop_c
                _crop_ph = _crop_b - _crop_a
                _shape_ceil = math.ceil(math.sqrt(_crop_pw * _crop_ph) / 64) * 64
                if _shape_ceil < _crop_target:
                    _scale = float(_crop_target) / _shape_ceil
                    w = int(round(_crop_pw * _scale / 64)) * 64
                    h = int(round(_crop_ph * _scale / 64)) * 64
                else:
                    _scale = 1.0
                    w = int(round(_crop_pw / 64)) * 64
                    h = int(round(_crop_ph / 64)) * 64
                w = max(w, 64)
                h = max(h, 64)

                # ESRGAN 2x neural upscale BEFORE resize to target dims.
                # crop → ESRGAN 2x → LANCZOS to target = sharper than LANCZOS alone.
                # Skip when upscale ratio < 1.3 (LANCZOS alone is fine).
                _esrgan_used = False
                _min_esrgan_ratio = 1.3
                if _shape_ceil < _crop_target and _scale >= _min_esrgan_ratio:
                    try:
                        _t_esr = time.time()
                        from core.models.manager import ModelManager
                        _mgr = ModelManager.get()
                        _mgr._load_upscale()
                        _upscaler = _mgr._upscale_model
                        # PIL RGB → numpy BGR → ESRGAN → numpy BGR → PIL RGB
                        _crop_np = np.array(image)[:, :, ::-1]  # RGB→BGR
                        _esr_out, _ = _upscaler.enhance(_crop_np, outscale=2)
                        image = Image.fromarray(_esr_out[:, :, ::-1])  # BGR→RGB
                        _esrgan_used = True
                        print(f"[ESRGAN] {_crop_pw}x{_crop_ph} → {image.size[0]}x{image.size[1]} ({time.time() - _t_esr:.1f}s)")
                        # Free VRAM for SDXL pipeline
                        del _mgr._upscale_model
                        _mgr._upscale_model = None
                        torch.cuda.empty_cache()
                    except Exception as _e:
                        print(f"[ESRGAN] Unavailable ({_e}), LANCZOS fallback")
                elif _shape_ceil < _crop_target:
                    print(f"[ESRGAN] Skipped (scale {_scale:.2f}x < {_min_esrgan_ratio}x, LANCZOS only)")

                # Resize to target pipeline dimensions
                image = image.resize((w, h), Image.LANCZOS)
                mask = mask.resize((w, h), Image.BILINEAR)
                if control_image is not None:
                    control_image = control_image.resize((w, h), Image.LANCZOS)
                _method = "ESRGAN 2x + LANCZOS" if _esrgan_used else "LANCZOS"
                print(f"[CROP-TO-MASK] ({_crop_c},{_crop_a})-({_crop_d},{_crop_b}) → {_crop_pw}x{_crop_ph} upscaled to {w}x{h} ({_scale:.2f}x, {w*h/1e6:.2f} Mpx, {_method})")

        # Callback preview TAESD — créé APRÈS le crop pour pouvoir recoller dans l'original
        _uncrop_info = None
        if _inpaint_crop is not None and _pre_crop_image is not None:
            _uncrop_info = {'crop': _inpaint_crop, 'base_image': _pre_crop_image}
        preview_cb = make_preview_callback(
            cancel_check, preview_every=5, target_size=original_size,
            image_height=h, image_width=w, uncrop_info=_uncrop_info
        )

        # Fooocus-style pre-fill : remplir la zone masquée avec les couleurs voisines
        # Fait AVANT l'encodage latent pour que le callback blend vers les couleurs fill
        # SKIP pour background_fill (on ne veut PAS conditionner sur le contenu original)
        if is_4ch and mask is not None and strength > 0.5 and not _skip_fooocus:
            set_progress_phase("prefill_inpaint", 0, steps)
            print(f"[INPAINT] Fooocus pre-fill en cours ({w}x{h})...")
            _t_fill = time.time()
            _mask_for_fill = np.array(mask.convert('L').resize((w, h), Image.BILINEAR))
            _filled_np = fooocus_fill(np.array(image), _mask_for_fill)
            _filled_image = Image.fromarray(_filled_np)
            print(f"[INPAINT] Fooocus pre-fill OK ({time.time() - _t_fill:.1f}s)")
        else:
            _filled_image = image

        if is_4ch and not _skip_fooocus:
            # 4-channel Fooocus-style: callback gère masking + x0 blend
            # Encoder le FILL (pas l'original) pour le blend — Fooocus blend vers
            # les couleurs pré-blurrées, pas les textures vêtements de l'original.
            with torch.no_grad():
                _device = "cuda" if torch.cuda.is_available() else "cpu"
                _fill_t = pipe.image_processor.preprocess(_filled_image, height=h, width=w)
                _fill_t = _fill_t.to(device=_device, dtype=pipe.vae.dtype)
                # Move VAE to CUDA if needed (skip if group offloaded — hooks handle it)
                _vae_moved = False
                try:
                    _vae_dev = next(pipe.vae.parameters()).device
                    if _vae_dev.type != 'cuda':
                        pipe.vae.to(_device)
                        _vae_moved = True
                except Exception:
                    pass  # Group offload or meta tensor — encode() handles device placement
                _fill_latents = pipe.vae.encode(_fill_t).latent_dist.mode()
                _fill_latents = _fill_latents * pipe.vae.config.scaling_factor
                if _vae_moved:
                    pipe.vae.to('cpu')
                    torch.cuda.empty_cache()

            # Masque BINAIRE en espace latent — Fooocus-style max_pool2d
            # max_pool2d(8,8) : si un SEUL pixel d'un bloc VAE 8x8 est masqué,
            # tout le bloc latent est masqué → empêche les textures vêtements
            # de fuiter dans l'espace latent aux bords du masque.
            _mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0
            _mask_t = torch.from_numpy(_mask_np).unsqueeze(0).unsqueeze(0)
            _mask_fullres = torch.nn.functional.interpolate(
                _mask_t, size=(_fill_latents.shape[2] * 8, _fill_latents.shape[3] * 8),
                mode='bilinear'
            ).round()
            _binary_mask_latent = torch.nn.functional.max_pool2d(
                _mask_fullres, (8, 8)
            ).round().to(device=_fill_latents.device, dtype=_fill_latents.dtype)

            _gen_seed = random.randint(0, 2**32 - 1)
            fooocus_cb = make_fooocus_clamp_callback(
                _fill_latents, None, _binary_mask_latent,
                preview_callback=preview_cb, cancel_check=cancel_check,
                seed=_gen_seed
            )
            _pipeline_mask = Image.new("L", (w, h), 255)
            _active_cb = fooocus_cb
            _cb_inputs = ["latents", "add_time_ids"]

            # Switch scheduler to SDE-DPMSolver++ (stochastic) — matches Fooocus's dpmpp_2m_sde_gpu
            # The stochastic noise helps the model break free from input structure (prevents clothing recreation)
            _saved_scheduler = pipe.scheduler
            try:
                from diffusers import DPMSolverMultistepScheduler as _DPMS
                pipe.scheduler = _DPMS.from_config(
                    pipe.scheduler.config,
                    algorithm_type="sde-dpmsolver++",
                    use_karras_sigmas=True, lower_order_final=True,
                )
                print(f"[INPAINT] SDXL 4-ch Fooocus double blend (binary mask, SDE scheduler)")
            except Exception as _e:
                print(f"[INPAINT] SDE scheduler failed ({_e}), using default")
                _saved_scheduler = None
                print(f"[INPAINT] SDXL 4-ch Fooocus double blend (binary mask, no feather)")
        else:
            # 9-channel: le UNet voit mask+image en input, gère le blend en interne
            # PAS de callback de blend (sinon ça annule la génération en re-blendant vers l'original)
            # Utiliser le masque de segmentation directement (déjà dilated + blur(10) par segmentation)
            # PAS de double blur — le masque a déjà des bords doux
            _pipeline_mask = mask.resize((w, h), Image.BILINEAR)
            _active_cb = callback  # preview + cancel seulement
            _cb_inputs = None
            print(f"[INPAINT] SDXL 9-ch pipeline masking (mask from segmentation, no extra blur)")

        # Fooocus InpaintHead: pre-compute features (fill latent + mask → 320ch)
        # Pass the FILLED image — Fooocus feeds fill colors to InpaintHead for proper
        # skin tone conditioning. Gray-masking was wrong (trained with fill colors).
        # SKIP pour background_fill (InpaintHead conditionne sur le contenu → recrée la personne)
        if not _skip_fooocus:
            try:
                from core.generation.fooocus_patch import prepare_inpaint_head
                prepare_inpaint_head(pipe, _filled_image, mask.resize((w, h), Image.BILINEAR))
            except Exception as e:
                print(f"[FOOOCUS] InpaintHead prep error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[BACKGROUND_FILL] InpaintHead SKIPPED (no original content conditioning)")

        # NOTE: Adaptive CFG DÉSACTIVÉ — incompatible avec le Fooocus patch.
        # Notre implémentation réduisait le CFG de 5.0→3.0, ce qui affaiblissait
        # le prompt en fin de génération. Le modèle Fooocus-patché a un biais contextuel
        # fort (InpaintHead) → avec CFG bas, il recrée les vêtements au lieu de suivre le prompt.
        # Le vrai Fooocus utilise rescale_cfg (ajuste magnitude, PAS la force du prompt).

        # ADM Scaling: Fooocus default 1.5x positive, 0.8x negative
        # Always active — Fooocus applies this regardless of image size
        _adm_factor = ADM_POS_SCALE
        _adm_pos_size = (int(h * _adm_factor), int(w * _adm_factor))
        print(f"[FOOOCUS] ADM scaling {_adm_factor}x (original {original_size[0]}x{original_size[1]}, {'< ' if _adm_factor == 1.0 else '>= '}{ADM_SMALL_IMAGE_THRESH}px)")

        pipe_kwargs = dict(
            prompt=full_prompt,
            negative_prompt=neg,
            image=_filled_image,
            mask_image=_pipeline_mask,
            height=h,
            width=w,
            strength=strength,
            guidance_scale=sdxl_guidance,
            num_inference_steps=adjusted_steps,
            callback_on_step_end=_active_cb,
            original_size=_adm_pos_size,
            negative_original_size=(int(h * ADM_NEG_SCALE), int(w * ADM_NEG_SCALE)),
        )
        if _cb_inputs:
            pipe_kwargs["callback_on_step_end_tensor_inputs"] = _cb_inputs

        # ControlNet Depth handling
        is_controlnet_pipe = hasattr(pipe, 'controlnet') and pipe.controlnet is not None

        if is_controlnet_pipe:
            if not enable_controlnet:
                controlnet_conditioning_scale = 0.0
                print(f"[INPAINT] ControlNet pipe réutilisé mais désactivé par le router (scale=0)")
            if control_image is None:
                if enable_controlnet:
                    print(f"[INPAINT] ControlNet détecté sans depth map -> génération fallback gris")
                control_image = Image.new('RGB', (w, h), (128, 128, 128))
            ctrl_img = control_image.resize((w, h), Image.LANCZOS)
            pipe_kwargs['control_image'] = ctrl_img
            pipe_kwargs['controlnet_conditioning_scale'] = controlnet_conditioning_scale
            print(f"[INPAINT] ControlNet Depth activé (scale={controlnet_conditioning_scale})")

        # IP-Adapter FaceID: passer les embeddings du visage
        if ip_adapter_image_embeds is not None:
            pipe.set_ip_adapter_scale(ip_adapter_scale)
            pipe_kwargs['ip_adapter_image_embeds'] = [ip_adapter_image_embeds]
            print(f"[INPAINT] IP-Adapter FaceID activé (scale={ip_adapter_scale})")
        elif hasattr(pipe, 'unet') and getattr(pipe.unet.config, 'encoder_hid_dim_type', None) == 'ip_image_proj':
            # IP-Adapter chargé mais pas d'embeds: zero-embeds neutralise l'adapter
            # sans dépendre d'attributs diffusers qui changent selon FaceID/standard.
            _zero_embeds = _make_ip_adapter_zero_embeds(pipe)
            pipe.set_ip_adapter_scale(0.0)
            pipe_kwargs['ip_adapter_image_embeds'] = _zero_embeds
            _dims = ",".join(str(int(embed.shape[-1])) for embed in _zero_embeds)
            print(f"[INPAINT] IP-Adapter zero-embeds (loaded but no face, dims={_dims}, scale=0.0)")

    # VAE tiling toujours activé — quasi invisible, évite OOM au décodage
    pipe.enable_vae_tiling()

    # Dtype guard: certains adapters/LoRAs PEFT restent en float32 alors que
    # les text encoders SDXL sont en bf16/fp16, ce qui casse CLIP au layer_norm.
    _preferred_text_dtype = getattr(getattr(pipe, "unet", None), "dtype", None)
    _align_text_encoder_dtypes(pipe, preferred_dtype=_preferred_text_dtype)

    _t_pipe = time.time()
    set_progress_phase("diffusion", 0, steps)
    try:
        result = pipe(**pipe_kwargs).images[0]
    except RuntimeError as e:
        _err = str(e)
        _is_dtype_mismatch = (
            "expected scalar type BFloat16 but found Float" in _err or
            "expected scalar type Half but found Float" in _err
        )
        if not _is_dtype_mismatch:
            raise

        print(f"[DTYPE] Prompt encoding mismatch detected, retrying after forced text encoder cast...")
        _align_text_encoder_dtypes(pipe, preferred_dtype=_preferred_text_dtype, force=True)
        result = pipe(**pipe_kwargs).images[0]
    _t_pipe_done = time.time()

    # Libérer la VRAM fragmentée après chaque génération (WDDM)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    generation_time = _t_pipe_done - generation_start_time
    print(f"[PERF] Pipeline call: {_t_pipe_done - _t_pipe:.2f}s | Total gen: {generation_time:.2f}s")

    # NE PAS clear_preview() ici — le fine tuning doit prendre le relais
    # Le frontend arrêterait de poll si step retombe à 0 entre les deux phases

    # Clear InpaintHead features after generation
    try:
        from core.generation.fooocus_patch import clear_inpaint_head
        clear_inpaint_head(pipe)
    except Exception:
        pass

    # Restore original scheduler if we switched to SDE for Fooocus
    # Create a FRESH instance to ensure no stale monkey-patches (x0 blend, preview wraps)
    try:
        if _saved_scheduler is not None:
            pipe.scheduler = type(_saved_scheduler).from_config(_saved_scheduler.config)
    except NameError:
        pass

    # Uncrop: paste generated crop back into full image with feathered edges
    UNCROP_FEATHER = 24  # px de feather au bord du crop pour éviter la coupure visible
    try:
        if _inpaint_crop is not None and _pre_crop_image is not None:
            import cv2
            _crop_a, _crop_b, _crop_c, _crop_d = _inpaint_crop
            _crop_pw = _crop_d - _crop_c
            _crop_ph = _crop_b - _crop_a
            # Get full image dimensions for boundary check
            _full_h, _full_w = np.array(_pre_crop_image).shape[:2]
            # Resize result back to crop pixel dimensions
            result = result.resize((_crop_pw, _crop_ph), Image.LANCZOS)
            # Feathered blend: only feather the TOP edge (body extends naturally to other edges)
            _feather_mask = np.ones((_crop_ph, _crop_pw), dtype=np.float32)
            _f = min(UNCROP_FEATHER, _crop_ph // 4)
            _at_top = (_crop_a <= _f)  # Skip if crop starts at image top
            if _f > 1 and not _at_top:
                for i in range(_f):
                    alpha = float(i) / _f
                    _feather_mask[i, :] = np.minimum(_feather_mask[i, :], alpha)
                _feather_mask = cv2.GaussianBlur(_feather_mask, (5, 5), 0)
            print(f"[UNCROP] Top feather: {'skip (at image edge)' if _at_top else f'{_f}px'}")
            # Blend crop into full image
            _full_result_np = np.array(_pre_crop_image).astype(np.float32)
            _crop_np = np.array(result).astype(np.float32)
            _region = _full_result_np[_crop_a:_crop_b, _crop_c:_crop_d]
            _feather_3ch = _feather_mask[:, :, np.newaxis]
            _blended = _region * (1 - _feather_3ch) + _crop_np * _feather_3ch
            _full_result_np[_crop_a:_crop_b, _crop_c:_crop_d] = _blended
            result = Image.fromarray(_full_result_np.astype(np.uint8))
            # Restore original mask and dimensions for compositing
            mask = _pre_crop_mask
            w, h = _pre_crop_w, _pre_crop_h
            print(f"[CROP-TO-MASK] Uncropped: feathered ({_crop_pw}x{_crop_ph}) at ({_crop_c},{_crop_a}) into {w}x{h} (feather={_f}px)")
    except NameError:
        pass

    # ========== AUTO-REFINE (passe rapide à strength 0.3, 12 steps) ==========
    # Skip pour: Flux (pas de negative_prompt/strength), Kontext (editing intelligent), refine manuel
    if skip_auto_refine or is_flux:
        clear_preview()
        print(f"[SIZE] result={result.size} original={original_size}")
        if result.size != original_size:
            result = result.resize(original_size, Image.LANCZOS)
            print(f"[SIZE] Resized → {result.size}")

        # Fooocus-style pixel compositing: paste generated into ORIGINAL
        # Preserves perfect quality in non-mask areas (no VAE round-trip degradation)
        if mask is not None and _state.original_image is not None:
            try:
                _orig_for_comp = _state.original_image
                if _orig_for_comp.size == result.size:
                    _comp_radius = composite_radius if composite_radius is not None else (COMPOSITE_RADIUS_BRUSH if brush_mode else COMPOSITE_RADIUS_SEG)
                    _mask_for_comp = np.array(mask.convert('L').resize(result.size, Image.BILINEAR))
                    _result_rgb = np.array(result.convert('RGB'))
                    _orig_rgb = np.array(_orig_for_comp.convert('RGB'))
                    result = Image.fromarray(
                        _pixel_composite(_result_rgb, _orig_rgb, _mask_for_comp, _comp_radius)
                    )
                    print(f"[COMPOSITE] Pixel compositing avec original (morphological_open {_comp_radius}px)")
            except Exception as _e:
                print(f"[COMPOSITE] Skip: {_e}")

        # Quality harmonization: DISABLED (testing Fooocus parity)
        # if not is_kontext and not is_flux and mask is not None:
        #     try:
        #         result = _quality_harmonize(result, mask, _state.original_image, brush_mode=brush_mode, composite_radius=composite_radius)
        #     except Exception as _e:
        #         print(f"[HARMONIZE] Skip: {_e}")
            finally:
                clear_preview()

        # Sauvegarder dans output/images/ (même sans auto-refine)
        _state.current_image = result
        _state.context_history.append({"prompt": prompt, "image": result, "type": "inpaint"})
        if len(_state.context_history) > MAX_HISTORY:
            _state.context_history.pop(0)
        from datetime import datetime as _dt_save
        _save_dir = Path("output") / "images"
        _save_dir.mkdir(parents=True, exist_ok=True)
        _ts = _dt_save.now().strftime("%Y%m%d_%H%M%S")
        _image_path = _save_dir / f"image_{_ts}.png"
        result.save(_image_path)
        result.save(Path("output") / "last_image.png")
        _meta = metadata or {}
        save_gallery_metadata(
            _image_path,
            asset_type="image",
            source="modified",
            model=model_name,
            prompt=_meta.get("original_prompt") or prompt,
            final_prompt=prompt,
            negative_prompt=neg,
            intent=intent,
            steps=steps,
            strength=strength,
            width=result.size[0],
            height=result.size[1],
            **_gallery_extra_metadata(_meta),
        )
        if mask is not None:
            mask.save(Path("output") / "last_mask.png")

        return result, _state.original_image, "success", generation_time

    if is_kontext:
        # Crop + resize pour matcher l'original sans déformer
        if result.size != original_size:
            out_w, out_h = result.size
            orig_w, orig_h = original_size
            orig_ratio = orig_w / orig_h
            out_ratio = out_w / out_h

            # Crop au centre pour matcher le ratio original
            if out_ratio > orig_ratio:
                # Output trop large, crop horizontalement
                new_w = int(out_h * orig_ratio)
                left = (out_w - new_w) // 2
                result = result.crop((left, 0, left + new_w, out_h))
            elif out_ratio < orig_ratio:
                # Output trop haut, crop verticalement
                new_h = int(out_w / orig_ratio)
                top = (out_h - new_h) // 2
                result = result.crop((0, top, out_w, top + new_h))

            # Puis resize à la taille exacte
            result = result.resize(original_size, Image.LANCZOS)
            print(f"[KONTEXT] Crop+resize: {out_w}x{out_h} → {orig_w}x{orig_h}")

        # Sauvegarder l'image Kontext
        from datetime import datetime
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"kontext_{timestamp}.png"
        result.save(image_path)
        result.save(output_dir / "last_image.png")
        _meta = metadata or {}
        save_gallery_metadata(
            image_path,
            asset_type="image",
            source="modified",
            model=model_name,
            prompt=_meta.get("original_prompt") or prompt,
            final_prompt=prompt,
            negative_prompt=neg,
            intent=intent or "kontext",
            steps=steps,
            strength=strength,
            width=result.size[0],
            height=result.size[1],
            **_gallery_extra_metadata(_meta),
        )
        print(f"[KONTEXT] Image sauvegardée: kontext_{timestamp}.png")
        clear_preview()
        return result, _state.original_image, "success", generation_time

    try:
        refine_steps = 6
        refine_strength = 0.30
        effective_steps = max(int(refine_steps * refine_strength), 2)
        print(f"[AUTO-REFINE] Passe légère (strength={refine_strength}, steps={refine_steps}, effective={effective_steps})...")
        refine_start = time.time()

        # Changer la phase pour le feedback UI (afficher les steps effectifs)
        set_phase("fine_tuning", effective_steps)

        # Callback avec preview pour le fine tuning (resize à la taille originale)
        refine_callback = make_preview_callback(cancel_check, preview_every=5, target_size=original_size)

        # Prompt refine : même prompt que la génération (pas de sharpening artificiel)
        refine_prompt = full_prompt
        refine_neg = neg or ""

        # Dilater légèrement le masque pour le refine (gratter un peu plus de peau aux bords)
        import cv2 as _cv2
        refine_mask_np = np.array(mask)
        _refine_kernel = np.ones((5, 5), np.uint8)
        refine_mask_np = _cv2.dilate(refine_mask_np, _refine_kernel, iterations=1)
        refine_mask = Image.fromarray(refine_mask_np, mode="L")

        # Préparer les kwargs pour le refine
        refine_guidance = FOOOCUS_CFG if is_4ch else (guidance_scale or 5.0)
        refine_kwargs = dict(
            prompt=refine_prompt,
            negative_prompt=refine_neg,
            image=result,
            mask_image=refine_mask,
            height=h,
            width=w,
            strength=refine_strength,
            guidance_scale=refine_guidance,
            num_inference_steps=refine_steps,
            callback_on_step_end=refine_callback,
        )

        # Ajouter ControlNet si actif (neutralized for 4-ch Fooocus mode)
        if control_image is not None:
            ctrl_img = control_image.resize((w, h), Image.LANCZOS)
            refine_kwargs['control_image'] = ctrl_img
            _refine_ctrl_scale = 0.0 if is_4ch else controlnet_conditioning_scale * 0.5
            refine_kwargs['controlnet_conditioning_scale'] = _refine_ctrl_scale

        # IP-Adapter: si chargé, passer les embeddings (sinon crash encoder_hid_dim_type)
        if ip_adapter_image_embeds is not None:
            refine_kwargs['ip_adapter_image_embeds'] = [ip_adapter_image_embeds]

        # Lancer le refine
        refined = pipe(**refine_kwargs).images[0]

        # Pas de composite — le pipeline inpainting gère le masque en interne
        result = refined

        refine_time = time.time() - refine_start
        print(f"[AUTO-REFINE] Terminé en {refine_time:.1f}s")
    except Exception as e:
        print(f"[AUTO-REFINE] Skip (erreur: {e})")
    finally:
        # Remettre la phase normale et nettoyer la preview
        clear_preview()

    # Remettre taille originale
    print(f"[SIZE] result={result.size} original={original_size}")
    if result.size != original_size:
        result = result.resize(original_size, Image.LANCZOS)
        print(f"[SIZE] Resized → {result.size}")

    # Fooocus-style pixel compositing: paste generated result into ORIGINAL image
    # This preserves perfect quality in non-mask areas (no VAE round-trip degradation)
    if mask is not None and _state.original_image is not None:
        try:
            _orig_for_comp = _state.original_image
            if _orig_for_comp.size == result.size:
                _comp_radius = composite_radius if composite_radius is not None else (COMPOSITE_RADIUS_BRUSH if brush_mode else COMPOSITE_RADIUS_SEG)
                _mask_for_comp = np.array(mask.convert('L').resize(result.size, Image.BILINEAR))
                _result_rgb = np.array(result.convert('RGB'))
                _orig_rgb = np.array(_orig_for_comp.convert('RGB'))
                result = Image.fromarray(
                    _pixel_composite(_result_rgb, _orig_rgb, _mask_for_comp, _comp_radius)
                )
                print(f"[COMPOSITE] Pixel compositing avec original (morphological_open {_comp_radius}px)")
        except Exception as _e:
            print(f"[COMPOSITE] Skip: {_e}")

    # Quality harmonization: DISABLED (testing Fooocus parity)
    # if not is_kontext and not is_flux and mask is not None:
    #     try:
    #         result = _quality_harmonize(result, mask, _state.original_image)
    #     except Exception as _e:
    #         print(f"[HARMONIZE] Skip: {_e}")
    #     finally:
    #         clear_preview()
    clear_preview()

    _state.current_image = result

    # Ajouter au contexte
    _state.context_history.append({
        "prompt": prompt,
        "image": result,
        "type": "inpaint"
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
    image_path = images_dir / f"image_{timestamp}.png"
    result.save(image_path)
    result.save(output_dir / "last_image.png")
    _meta = metadata or {}
    save_gallery_metadata(
        image_path,
        asset_type="image",
        source="modified",
        model=model_name,
        prompt=_meta.get("original_prompt") or prompt,
        final_prompt=prompt,
        negative_prompt=neg,
        intent=intent,
        steps=steps,
        strength=strength,
        width=result.size[0],
        height=result.size[1],
        **_gallery_extra_metadata(_meta),
    )
    mask.save(output_dir / "last_mask.png")

    return result, _state.original_image, "OK", generation_time
