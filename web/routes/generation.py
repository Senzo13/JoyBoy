"""
Blueprint pour les routes de génération d'images (generate, fix-details, preview, cancel, upscale, xray, expand).
"""
from flask import Blueprint, request, jsonify
from PIL import Image, ImageFilter
import json
import re
import unicodedata
import uuid

generation_bp = Blueprint('generation', __name__)


# ─── Preload guard: prevents stale preload threads from blocking new generations ───
# When user cancels and starts a new gen, old preload becomes stale.
# The preload function checks this ID at key points and bails out early if stale.
import threading as _threading
_preload_lock = _threading.Lock()
_preload_gen_id = None  # generation_id of the current active preload


_ADULT_MODE_LOCKED_MESSAGE = (
    "Cette demande nécessite un pack local adulte actif. Active le pack dans "
    "Paramètres > Modèles, puis réessaie."
)


def _adult_mode_locked_response(error_response):
    return error_response(
        _ADULT_MODE_LOCKED_MESSAGE,
        status=403,
        code="adult_mode_locked",
        featureBlocked="adult_mode",
        userMessageKey="generation.adultModeLocked",
    )


def _normalize_face_ref_payload(data, limit=5):
    """Accept legacy `face_ref` plus new `face_refs` list, capped to 1-5 images."""
    values = []
    refs = data.get("face_refs")
    if isinstance(refs, list):
        values.extend(refs)
    elif isinstance(refs, str):
        values.append(refs)

    legacy_ref = data.get("face_ref")
    if isinstance(legacy_ref, str) and legacy_ref:
        values.insert(0, legacy_ref)

    deduped = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
        if len(deduped) >= limit:
            break
    return deduped


# ─── Helper: lazy imports from web.app to avoid circular imports ───

def _get_state():
    from web.app import state
    return state

def _get_active_generations():
    from web.app import active_generations
    return active_generations

def _get_generations_lock():
    from web.app import generations_lock
    return generations_lock

def _get_generation_pipeline():
    from web.app import generation_pipeline
    return generation_pipeline

def _is_generation_cancelled():
    from web.app import generation_cancelled
    return generation_cancelled

def _set_generation_cancelled(value):
    import web.app as app_module
    app_module.generation_cancelled = value

def _set_chat_stream_cancelled(value):
    import web.app as app_module
    app_module.chat_stream_cancelled = value

def _base64_to_pil(b64_string):
    from web.app import base64_to_pil
    return base64_to_pil(b64_string)

def _pil_to_base64(img):
    from web.app import pil_to_base64
    return pil_to_base64(img)

def _get_image_hash(img):
    from web.app import get_image_hash
    return get_image_hash(img)


# ─── Repose helpers ───

def _normalize_repose_text(text):
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text.lower()).strip()


def _last_phrase_position(text, phrases):
    last = -1
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text):
            last = max(last, match.start())
    return last


def _has_any_phrase(text, phrases):
    return any(phrase in text for phrase in phrases)


def _dedupe_phrases(values):
    seen = set()
    out = []
    for value in values:
        cleaned = (value or '').strip().strip(', ')
        key = cleaned.lower()
        if cleaned and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out


def _join_prompt_parts(parts, max_chars=240):
    joined = []
    total = 0
    for part in _dedupe_phrases(parts):
        candidate_len = len(part) if not joined else total + 2 + len(part)
        if joined and candidate_len > max_chars:
            continue
        if not joined and len(part) > max_chars:
            joined.append(part[:max_chars].rstrip(', '))
            break
        joined.append(part)
        total = candidate_len
    return ', '.join(joined)


def _compact_repose_appearance(florence_desc):
    """Réduit la description Florence à l'apparence utile du sujet."""
    if not florence_desc:
        return ""

    desc = re.sub(r'\s+', ' ', florence_desc).strip()
    desc_lower = desc.lower()

    subject = ""
    subject_match = re.search(r'\b(?:a|the)\s+(woman|man|girl|boy|person)\b', desc_lower)
    if subject_match:
        subject = subject_match.group(1)

    wearing = ""
    wearing_match = re.search(
        r'\b(?:she|he|they|the woman|the man|the person)\s+is wearing\s+([^.;]+)',
        desc,
        re.IGNORECASE
    )
    if wearing_match:
        wearing = wearing_match.group(1).strip()
        wearing = re.split(
            r'\b(?:and is holding|holding|standing|sitting|in front of|next to|beside|with a|with an)\b',
            wearing,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0].strip(', ')

    hair = ""
    hair_match = re.search(r'\b(?:with|has)\s+([^.;,]*hair[^.;,]*)', desc, re.IGNORECASE)
    if hair_match:
        hair = hair_match.group(1).strip()

    parts = []
    if subject and hair:
        parts.append(f"{subject} with {hair}")
    elif subject:
        parts.append(subject)
    elif hair:
        parts.append(hair)

    if wearing:
        parts.append(f"wearing {wearing}")

    if not parts:
        return ""

    compact = ', '.join(_dedupe_phrases(parts))
    return compact[:100].rstrip(', ')


def _compact_repose_user_hint(user_prompt):
    """Garde seulement un hint court du prompt utilisateur s'il reste utile."""
    if isinstance(user_prompt, dict):
        parsed_request = user_prompt
        user_prompt = parsed_request.get('raw_prompt', '')
    else:
        parsed_request = None

    if parsed_request and parsed_request.get('clean_prompt_en'):
        hint = re.sub(r'\s+', ' ', parsed_request['clean_prompt_en']).strip().strip(', ')
        if 2 < len(hint.split()) <= 20 and len(hint) <= 90:
            return hint

    if not user_prompt:
        return ""

    hint = re.sub(r'\s+', ' ', user_prompt).strip().strip(', ')
    cleaned_hint = hint
    generic_patterns = (
        r'\bchange sa position\b', r'\bchanger sa position\b', r'\bchange de position\b',
        r'\bchange la position\b', r'\bchange position\b',
        r'\bmove the person\b', r'\bmove her\b', r'\bmove him\b',
    )
    for pattern in generic_patterns:
        cleaned_hint = re.sub(pattern, '', cleaned_hint, flags=re.IGNORECASE)

    cleaned_hint = re.sub(r'\s+', ' ', cleaned_hint).strip().strip(', ')

    if len(cleaned_hint.split()) <= 2:
        return ""

    if len(cleaned_hint) > 90:
        return ""

    return cleaned_hint


def _extract_mask_bbox(person_mask):
    import numpy as np
    mask_np = np.array(person_mask.convert('L'))
    coords = np.where(mask_np > 127)
    if len(coords[0]) == 0:
        return None
    y_min, y_max = int(coords[0].min()), int(coords[0].max())
    x_min, x_max = int(coords[1].min()), int(coords[1].max())
    return x_min, y_min, x_max, y_max


def _compute_repose_target_geometry(person_mask, image_size, prompt):
    bbox = _extract_mask_bbox(person_mask)
    directives = _parse_repose_directives(prompt)
    if bbox is None:
        return None, directives

    x_min, y_min, x_max, y_max = bbox
    img_w, img_h = image_size
    box_w = max(1.0, float((x_max - x_min) + 1))
    box_h = max(1.0, float((y_max - y_min) + 1))
    center_x = (x_min + x_max) / 2.0
    center_y = (y_min + y_max) / 2.0

    anchor_x = directives['anchor_x']
    target_center_x = img_w * anchor_x if anchor_x is not None else center_x
    target_center_y = img_h * directives['anchor_y'] if directives['anchor_y'] is not None else center_y
    target_center_y += directives['y_shift'] * img_h
    target_center_y = min(max(target_center_y, box_h * 0.35), img_h - box_h * 0.20)

    target_w = max(1.0, box_w * directives['scale_mult'] * directives['box_scale_x'])
    target_h = max(1.0, box_h * directives['scale_mult'] * directives['box_scale_y'])
    margin_x = max(24, int(target_w * 0.20))
    margin_y = max(24, int(target_h * 0.18))

    target_x1 = int(round(target_center_x - (target_w / 2.0)))
    target_y1 = int(round(target_center_y - (target_h / 2.0)))
    target_x2 = int(round(target_center_x + (target_w / 2.0)))
    target_y2 = int(round(target_center_y + (target_h / 2.0)))

    if target_x2 <= target_x1 or target_y2 <= target_y1:
        return None, directives

    x1 = max(0, target_x1 - margin_x)
    y1 = max(0, target_y1 - margin_y)
    x2 = min(img_w, target_x2 + margin_x)
    y2 = min(img_h, target_y2 + margin_y)
    if x2 <= x1 or y2 <= y1:
        return None, directives

    return {
        'orig_bbox': (x_min, y_min, x_max, y_max),
        'target_bbox': (
            max(0, target_x1),
            max(0, target_y1),
            min(img_w, target_x2),
            min(img_h, target_y2),
        ),
        'mask_bbox': (x1, y1, x2, y2),
    }, directives


def _parse_repose_directives(prompt):
    from core.ai.edit_directives import build_repose_directives

    return build_repose_directives(prompt, image_present=True, has_brush_mask=False)


def _build_repose_target_mask(person_mask, image_size, prompt):
    """Construit une zone cible pour repositionner la personne dans l'image."""
    import numpy as np

    geometry, directives = _compute_repose_target_geometry(person_mask, image_size, prompt)
    if geometry is None:
        return person_mask, directives

    img_w, img_h = image_size
    x1, y1, x2, y2 = geometry['mask_bbox']
    expanded = np.zeros((img_h, img_w), dtype=np.uint8)
    expanded[y1:y2, x1:x2] = 255
    return Image.fromarray(expanded, mode='L'), directives


def _build_relocated_person_base(original_img, clean_bg, person_mask, prompt, refine_mask_source=None):
    """Déplace le vrai cutout de la personne avant tout refine génératif."""
    import numpy as np

    geometry, directives = _compute_repose_target_geometry(person_mask, original_img.size, prompt)
    if geometry is None:
        fallback_mask, directives = _build_repose_target_mask(person_mask, original_img.size, prompt)
        return clean_bg, fallback_mask, directives

    x_min, y_min, x_max, y_max = geometry['orig_bbox']
    target_x1, target_y1, target_x2, target_y2 = geometry['target_bbox']
    crop_box = (x_min, y_min, x_max + 1, y_max + 1)

    cutout_rgb = original_img.convert('RGBA').crop(crop_box)
    cutout_alpha = person_mask.convert('L').crop(crop_box).filter(ImageFilter.GaussianBlur(radius=4))
    cutout_rgb.putalpha(cutout_alpha)

    target_w = max(1, target_x2 - target_x1)
    target_h = max(1, target_y2 - target_y1)
    moved_cutout = cutout_rgb.resize((target_w, target_h), Image.LANCZOS)
    moved_alpha = cutout_alpha.resize((target_w, target_h), Image.LANCZOS)

    base_rgba = clean_bg.convert('RGBA')
    overlay = Image.new('RGBA', original_img.size, (0, 0, 0, 0))
    overlay.paste(moved_cutout, (target_x1, target_y1), moved_cutout)
    pasted = Image.alpha_composite(base_rgba, overlay).convert('RGB')

    refine_alpha = moved_alpha
    if refine_mask_source is not None:
        refine_crop = refine_mask_source.convert('L').crop(crop_box)
        refine_alpha = refine_crop.resize((target_w, target_h), Image.LANCZOS)

    target_mask = Image.new('L', original_img.size, 0)
    target_mask.paste(refine_alpha, (target_x1, target_y1))
    target_mask = target_mask.filter(ImageFilter.GaussianBlur(radius=6))
    target_mask_np = np.array(target_mask)
    target_mask_np = np.where(target_mask_np > 18, 255, 0).astype(np.uint8)
    target_mask = Image.fromarray(target_mask_np, mode='L').filter(ImageFilter.MaxFilter(31))

    pose_expanding_flags = {'lying', 'all_fours', 'bending', 'kneeling', 'sitting'}
    if any(flag in pose_expanding_flags for flag in directives.get('debug_flags', [])):
        expand_x = max(18, int(target_w * 0.10))
        expand_y = max(18, int(target_h * 0.10))
        support_x1 = max(0, target_x1 - expand_x)
        support_y1 = max(0, target_y1 - expand_y)
        support_x2 = min(original_img.size[0], target_x2 + expand_x)
        support_y2 = min(original_img.size[1], target_y2 + expand_y)
        support_mask = Image.new('L', original_img.size, 0)
        support_mask.paste(255, (support_x1, support_y1, support_x2, support_y2))
        final_mask = Image.fromarray(
            np.maximum(np.array(support_mask, dtype=np.uint8), np.array(target_mask, dtype=np.uint8)),
            mode='L'
        )
    else:
        final_mask = target_mask

    return pasted, final_mask, directives


_REPOSE_CLOTHING_RE = None

def _build_repose_prompt(user_prompt, florence_desc, directives=None):
    """Construit le prompt pour la régénération de la personne.

    Si le user mentionne des vêtements/couleurs → skip Florence description.
    Sinon → ajouter la description Florence pour préserver l'apparence.
    """
    global _REPOSE_CLOTHING_RE
    if _REPOSE_CLOTHING_RE is None:
        _REPOSE_CLOTHING_RE = re.compile(
            r'\b(robe|dress|jupe|skirt|pantalon|pants|jean|short|bikini|lingerie|'
            r'top|shirt|chemise|veste|jacket|coat|manteau|nude|naked|nue?|'
            r'maillot|swimsuit|underwear|bra|string|tenue|outfit|habit|'
            r'rouge|bleu|vert|noir|blanc|rose|jaune|red|blue|green|black|white|pink)\b',
            re.IGNORECASE
        )
    has_clothing = bool(_REPOSE_CLOTHING_RE.search(user_prompt))
    directives = directives or {}
    prompt_terms = list(directives.get('prompt_terms', []))
    user_hint = _compact_repose_user_hint(directives.get('parsed_request') or user_prompt)
    appearance_hint = "" if has_clothing else _compact_repose_appearance(florence_desc)
    if directives.get('debug_flags'):
        user_hint = ""
    if 'back_view' not in directives.get('debug_flags', []):
        prompt_terms.append('same face angle as original')
        prompt_terms.append('same viewpoint as original')

    priority_markers = (
        'positioned', 'repositioned', 'farther', 'closer',
        'arms relaxed', 'different body pose', 'standing upright', 'sitting', 'kneeling',
        'lying', 'back view', 'bending', 'all fours',
        'touching her face', 'both hands touching the face', 'touching her upper chest',
        'both hands resting on the upper chest',
    )
    priority_terms = [term for term in prompt_terms if any(marker in term for marker in priority_markers)]
    support_terms = [term for term in prompt_terms if term not in priority_terms]

    parts = []
    parts.extend(priority_terms)
    if user_hint:
        parts.append(user_hint)
    parts.extend(['same clothing', 'same hairstyle'])
    if appearance_hint:
        parts.append(appearance_hint)
    parts.extend(support_terms)
    parts.extend(['realistic photo', 'natural lighting'])
    return _join_prompt_parts(parts, max_chars=240)


def _build_repose_negative_prompt(directives=None):
    directives = directives or {}
    parts = [
        'multiple people',
        'duplicate person',
        'blur',
        'deformed',
        'bad anatomy',
        'extra limbs',
        'missing limbs',
        'cropped body',
        'cut off feet',
        'cut off hands',
    ]
    if 'back_view' not in directives.get('debug_flags', []):
        parts.extend(['side profile', 'extreme profile view'])
    parts.extend(directives.get('negative_terms', []))
    return ', '.join(_dedupe_phrases(parts))


def _background_fill_cv2(image, mask):
    """Remplit le trou laissé par la personne avec OpenCV inpaint pour éviter les nappes grises."""
    import numpy as np
    try:
        import cv2
    except (ImportError, OSError):
        return None

    rgb = np.array(image.convert('RGB'))
    mask_np = np.array(mask.convert('L'))
    mask_bin = np.where(mask_np > 16, 255, 0).astype(np.uint8)
    if mask_bin.max() == 0:
        return image.convert('RGB')

    filled = cv2.inpaint(rgb, mask_bin, 9, cv2.INPAINT_TELEA)
    return Image.fromarray(filled, mode='RGB')


# ─── Routes ───

@generation_bp.route('/generate', methods=['POST'])
@generation_bp.route('/generate-edit', methods=['POST'])
def unified_generate():
    """Endpoint unifie pour toutes les generations (text2img, inpaint, edit avec brush)."""
    _set_generation_cancelled(False)  # Reset au debut de chaque generation

    state = _get_state()
    active_generations = _get_active_generations()
    generations_lock = _get_generations_lock()
    generation_pipeline = _get_generation_pipeline()
    base64_to_pil = _base64_to_pil
    pil_to_base64 = _pil_to_base64
    get_image_hash = _get_image_hash

    from core.api_helpers import success_response, error_response, cancelled_response, validation_error, image_response
    from core.processing import process_image, generate_from_text, GenerationCancelledException
    from core.processing import clear_preview, set_progress_phase
    from core.processing import reframe_person

    try:
        data = request.json
        image_b64 = data.get('image')
        brush_mask_b64 = data.get('mask')  # Masque pinceau (mode edition)
        prompt = data.get('prompt', '')
        model = data.get('model') or 'epiCRealism XL (Moyen)'
        strength_override = data.get('strength')  # Frontend peut override
        nsfw_strength = data.get('nsfw_strength')  # NSFW slider override
        enhance = data.get('enhance', True)
        enhance_mode = data.get('enhance_mode', 'light')
        steps = data.get('steps', 40)
        chat_id = data.get('chatId')
        generation_id = data.get('generationId') or str(uuid.uuid4())
        skip_enhance = data.get('skip_enhance', False)
        skip_auto_refine = data.get('skip_auto_refine', False)
        controlnet_depth_override = data.get('controlnet_depth')  # Settings slider override
        composite_radius_override = data.get('composite_radius')  # Settings slider override (None=auto)
        crop_inpaint = data.get('crop_inpaint', True)
        face_ref_b64s = _normalize_face_ref_payload(data)  # 1-5 visages de référence pour IP-Adapter FaceID
        text2img_guidance = data.get('text2img_guidance', 7.5)
        face_ref_scale = data.get('face_ref_scale', 0.35)
        style_ref_b64 = data.get('style_ref')  # Base64 de l'image de style pour IP-Adapter CLIP
        style_ref_scale = data.get('style_ref_scale', 0.55)
        # Export settings (text2img defaults)
        export_settings = {
            'format': data.get('export_format', 'auto'),
            'width': int(data.get('export_width', 768)),
            'height': int(data.get('export_height', 1344)),
            'view': data.get('export_view', 'auto'),
            'pose': data.get('export_pose', 'none'),
            'pose_strength': float(data.get('pose_strength', 0.5)),
            'presets': json.loads(data.get('export_presets', '{}')),
        }
        # LoRA settings from frontend (desactives par defaut)
        lora_nsfw_enabled = data.get('lora_nsfw_enabled', False)
        lora_nsfw_strength = data.get('lora_nsfw_strength', 0.3)
        lora_skin_enabled = data.get('lora_skin_enabled', False)
        lora_skin_strength = data.get('lora_skin_strength', 0.3)
        lora_breasts_enabled = data.get('lora_breasts_enabled', False)
        lora_breasts_strength = data.get('lora_breasts_strength', 0.4)
        from core.infra.packs import is_adult_runtime_available
        adult_mode_enabled = is_adult_runtime_available()
        if not adult_mode_enabled:
            nsfw_strength = None
            lora_nsfw_enabled = False
            lora_skin_enabled = False
            lora_breasts_enabled = False
        # Log LoRAs actifs
        active_loras = []
        if lora_nsfw_enabled: active_loras.append(f"nsfw({lora_nsfw_strength})")
        if lora_skin_enabled: active_loras.append(f"skin({lora_skin_strength})")
        if lora_breasts_enabled: active_loras.append(f"breasts({lora_breasts_strength})")
        # Custom LoRAs (pending ou chargés)
        from core.model_manager import ModelManager
        _mgr = ModelManager.get()
        for cname, cscale in _mgr._pending_custom_loras.items():
            active_loras.append(f"custom:{cname}({cscale})")
        for cname, cloaded in _mgr._loras_loaded.items():
            if cloaded and cname not in ('nsfw', 'skin', 'breasts'):
                cscale = _mgr._lora_scales.get(cname, 0.8)
                active_loras.append(f"custom:{cname}({cscale})")
        if active_loras:
            print(f"[LORA] Actifs: {', '.join(active_loras)}")
        else:
            print(f"[LORA] Aucun LoRA activé")

        if skip_enhance:
            enhance = False

        if not prompt:
            return validation_error('Pas de prompt')

        if not adult_mode_enabled:
            from core.ai.edit_directives import is_adult_request_heuristic
            if is_adult_request_heuristic(prompt):
                print("[ADULT_GUARD] Pack adulte inactif: génération bloquée avant preload")
                return _adult_mode_locked_response(error_response)

        is_inpainting = bool(image_b64)
        has_brush = bool(brush_mask_b64)
        mode_str = "edit+brush" if has_brush else ("inpainting" if is_inpainting else "text2img")
        print(f"[MODEL] Frontend sent: '{model}'")

        # Enregistrer cette generation IMMEDIATEMENT (avant router/enhance)
        # pour que /cancel-all puisse la marquer comme annulee
        with generations_lock:
            active_generations[generation_id] = {"cancelled": False, "chat_id": chat_id}

        from core.runtime import get_job_manager, get_conversation_store
        runtime_jobs = get_job_manager()
        runtime_conversations = get_conversation_store()
        job_kind = 'inpaint' if is_inpainting else 'text2img'
        runtime_jobs.create(
            job_id=generation_id,
            kind=job_kind,
            model=model,
            prompt=prompt,
            conversation_id=chat_id,
            metadata={
                "mode": mode_str,
                "steps": steps,
                "has_image": is_inpainting,
                "has_brush": has_brush,
                "enhance": enhance,
                "enhance_mode": enhance_mode,
            },
        )
        runtime_jobs.update(generation_id, phase='preload', progress=2, message='Préparation du moteur image')
        if chat_id:
            runtime_conversations.ensure(chat_id)
            runtime_conversations.attach_job(chat_id, generation_id)

        def mark_job_update(**kwargs):
            runtime_jobs.update(generation_id, **kwargs)

        def mark_job_done(result_type='image', **metadata):
            runtime_jobs.complete(
                generation_id,
                artifact={"type": result_type, **metadata},
                message='Génération terminée',
            )

        def mark_job_failed(message):
            runtime_jobs.fail(generation_id, message)

        def mark_job_cancelled(message='Génération annulée'):
            runtime_jobs.cancel(generation_id, message)

        # ========== PRELOAD PIPELINE + LoRAs IMMÉDIAT (avant router/segmentation) ==========
        # Lire le model_behaviors.json pour savoir si ControlNet/LoRAs sont supportés
        # (lecture JSON rapide, pas d'attente sur le router)
        from core.router_rules import get_model_behavior
        _early_behavior = get_model_behavior(model)
        _early_pipeline = _early_behavior.get('pipeline', {}) if _early_behavior else {}
        _preload_controlnet = _early_pipeline.get('uses_controlnet', True)
        _preload_loras = _early_pipeline.get('uses_loras', True)

        _preload_future = None
        _preload_executor = None
        if is_inpainting:
            from concurrent.futures import ThreadPoolExecutor
            from core.model_manager import ModelManager
            _preload_is_single_file = False
            try:
                from core.models import SINGLE_FILE_MODELS, _refresh_imported_model_registries
                _refresh_imported_model_registries()
                _preload_is_single_file = model in SINGLE_FILE_MODELS
            except Exception as _preload_registry_error:
                print(f"[PRELOAD] Registry check skipped: {_preload_registry_error}")

            _lora_nsfw = lora_nsfw_enabled and _preload_loras
            _lora_skin = lora_skin_enabled and _preload_loras
            _lora_breasts = lora_breasts_enabled and _preload_loras
            _cn = _preload_controlnet

            # Register this generation as the active preload target.
            # Any older preload still running will detect it's stale and bail out.
            _my_gen_id = generation_id
            with _preload_lock:
                global _preload_gen_id
                _preload_gen_id = _my_gen_id

            def _preload_pipeline_and_loras():
                import time as _t
                _t0 = _t.time()
                mgr = None
                try:
                    # Check if still the active preload before heavy work
                    with _preload_lock:
                        if _preload_gen_id != _my_gen_id:
                            print(f"[PRELOAD] Stale (new gen started), skipping")
                            return
                    # Also check global cancellation (user hit cancel-all)
                    if _is_generation_cancelled():
                        print(f"[PRELOAD] Cancelled before load, skipping")
                        return

                    mgr = ModelManager.get()
                    print(f"[PRELOAD] load_for_task start...")
                    # The smart router may still be using Ollama while this
                    # background preload starts. Do not unload the text model
                    # from the preload thread; the main generation path unloads
                    # it explicitly after routing/enhance.
                    mgr.load_for_task(
                        'inpaint',
                        model_name=model,
                        needs_controlnet=_cn,
                        preserve_ollama=True,
                    )

                    # Check staleness + cancellation after model load
                    with _preload_lock:
                        if _preload_gen_id != _my_gen_id:
                            print(f"[PRELOAD] Stale after model load, skipping LoRAs")
                            return
                    if _is_generation_cancelled():
                        print(f"[PRELOAD] Cancelled after model load, skipping LoRAs")
                        return

                    print(f"[PRELOAD] Model ready ({_t.time() - _t0:.1f}s)")
                    # Charger les LoRAs dans le pipeline (besoin que le pipe soit prêt)
                    if _lora_nsfw:
                        mgr.ensure_lora_loaded("nsfw")
                    if _lora_skin:
                        mgr.ensure_lora_loaded("skin")
                    if _lora_breasts:
                        mgr.ensure_lora_loaded("breasts")
                    print(f"[PRELOAD] Done ({_t.time() - _t0:.1f}s)")
                except Exception as e:
                    print(f"[PRELOAD] ERROR: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    if mgr is not None:
                        try:
                            print("[PRELOAD] Cleaning partial image pipeline after error...")
                            mgr._unload_diffusers()
                            mgr._clear_memory(aggressive=True)
                        except Exception as cleanup_error:
                            print(f"[PRELOAD] Cleanup after error failed: {cleanup_error}")
                    raise

            if _preload_is_single_file:
                with _preload_lock:
                    if _preload_gen_id == _my_gen_id:
                        _preload_gen_id = None
                print(f"[PRELOAD] Skipped for imported single-file model ({model}); direct load after segmentation")
            else:
                _preload_executor = ThreadPoolExecutor(max_workers=1)
                _preload_future = _preload_executor.submit(_preload_pipeline_and_loras)
                parts = [model]
                if _cn: parts.append("ControlNet")
                loras_str = []
                if _lora_nsfw: loras_str.append("nsfw")
                if _lora_skin: loras_str.append("skin")
                if _lora_breasts: loras_str.append("breasts")
                if loras_str: parts.append(f"LoRAs({','.join(loras_str)})")
                print(f"[PRELOAD] {' + '.join(parts)} lancé IMMÉDIATEMENT")

        def is_cancelled():
            if runtime_jobs.is_cancel_requested(generation_id):
                return True
            if _is_generation_cancelled():
                return True
            with generations_lock:
                gen = active_generations.get(generation_id, {})
                return gen.get("cancelled", False)

        # ===== LOG =====
        from core.log_utils import big
        big(f"GENERATION | {mode_str.upper()} | {model}")
        print(f"  Mode:     {mode_str}")
        print(f"  Model:    {model}")
        print(f"  Prompt:   {prompt if prompt else '(vide)'}")
        print(f"  Image:    {'OUI (' + str(len(image_b64) // 1024) + 'KB)' if image_b64 else 'NON (text2img)'}")
        print(f"  Brush:    {'OUI' if has_brush else 'NON'}")
        print(f"  Enhance:  {enhance} ({enhance_mode})")
        print(f"  Steps:    {steps}")
        print(f"  Strength: {strength_override if strength_override else 'auto (router)'}")
        print(f"  ChatID:   {chat_id}")
        print(f"{'='*60}")
        mark_job_update(phase='routing', progress=8, message='Analyse de la demande')

        # ========== 1. SMART ROUTER — LE CERVEAU ==========
        # Skip le router pour text2img (pas d'image a analyser, on genere de zero)
        if not image_b64:
            analysis = {
                'intent': 'text2img',
                'mask_strategy': 'full',
                'strength': 1.0,
                'needs_controlnet': False,
                'needs_ip_adapter': False,
                'prompt_rewrite': prompt,
                'negative_prompt': 'blurry, low quality, distorted, deformed',
                'reason': 'text2img (no image, skip router)'
            }
        else:
            from core.smart_router import analyze_request
            analysis = analyze_request(
                prompt=prompt,
                image_b64=image_b64,
                has_brush_mask=has_brush
            )

            # Décharger TOUS les LLM Ollama après le routing pour libérer la VRAM
            # Le chat (qwen3.5:2b) + le router (UTILITY_MODEL) prennent de la VRAM
            # SYNCHRONE: sur 8GB, SDXL charge juste après → faut que le unload finisse AVANT
            try:
                from core.ollama_service import get_loaded_models, unload_model
                _loaded = get_loaded_models()
                if _loaded:
                    print(f"   \u251c\u2500 Déchargement {', '.join(_loaded)}...")
                    for _m in _loaded:
                        unload_model(_m)
            except Exception:
                pass

        # Cancel check apres ROUTER
        if is_cancelled():
            print(f"[CANCEL] Cancelled after SMART ROUTER")
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        if analysis.get('blocked_by_feature') == 'adult_mode':
            with generations_lock:
                active_generations.pop(generation_id, None)
            return _adult_mode_locked_response(error_response)

        # ========== REFRAME REDIRECT ==========
        # Si le router detecte un intent "reframe" (reculer, zoom out, full body, etc.)
        if analysis['intent'] == 'reframe' and image_b64:
            import time as _time
            print(f"[ROUTER->REFRAME] Intent reframe detecte, redirection vers reframe_person")
            start_time = _time.time()
            with generation_pipeline('expand', generation_id, model_name=model) as mgr:
                img = base64_to_pil(image_b64)
                pipe = mgr.get_pipeline('expand')
                result, status = reframe_person(img, prompt=prompt, pipe=pipe)
                generation_time = _time.time() - start_time
                if result:
                    state.modified_image = result
                    print(f"[REFRAME] Termine en {generation_time:.1f}s")
                    with generations_lock:
                        active_generations.pop(generation_id, None)
                    return image_response(pil_to_base64(result), status=status, generation_time=generation_time)
                else:
                    with generations_lock:
                        active_generations.pop(generation_id, None)
                    return error_response(status)

        # ========== REPOSE REDIRECT ==========
        # 2-pass pipeline: remove person → clean background → regenerate in new pose
        # IMPORTANT: on réutilise le preload (needs_controlnet=True) pour les 2 passes
        # dans un seul context manager. Recharger le modèle avec une config différente
        # crashe (quanto INT8 + Fooocus patch = références extra sur les poids).
        if analysis['intent'] == 'repose' and image_b64:
            import time as _time
            print(f"[ROUTER->REPOSE] Intent repose detecte, pipeline 2 passes")
            start_time = _time.time()

            img = base64_to_pil(image_b64)
            if img.mode != 'RGB':
                img = img.convert('RGB')
                print(f"[REPOSE] Image convertie en RGB")

            # Cancel check
            if is_cancelled():
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            # 0. Florence → description de la personne (avant suppression)
            person_desc = ""
            directives_prompt = prompt or analysis.get('prompt_rewrite', prompt)
            base_repose_directives = analysis.get('edit_directives') or _parse_repose_directives(directives_prompt)
            do_relocation = bool(base_repose_directives.get('explicit_relocation'))
            print(f"[REPOSE] Mode: {'relocation' if do_relocation else 'local pose edit'}")
            try:
                from core.generation.florence import describe_image
                person_desc = describe_image(img, task="<DETAILED_CAPTION>")
                print(f"[REPOSE] Florence description: {person_desc[:120]}...")
            except Exception as _e:
                print(f"[REPOSE] Florence failed ({_e}), continuing without description")

            # 1. Masque de travail
            from core.segmentation import create_smart_mask
            body_refine_mask = None
            if do_relocation:
                person_mask = create_smart_mask(img, strategy='person', exclude_face=False)
                print(f"[REPOSE] Person mask created")
                body_refine_mask = create_smart_mask(img, strategy='body', exclude_face=True)
                print(f"[REPOSE] Body refine mask created")
            else:
                person_mask = create_smart_mask(img, strategy='body', exclude_face=True)
                print(f"[REPOSE] Body mask created (face preserved)")

            # Cancel check
            if is_cancelled():
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            # Libérer segmentation VRAM avant génération
            from core.models import IS_HIGH_END_GPU
            if not IS_HIGH_END_GPU:
                from core.segmentation import unload_segmentation_models
                unload_segmentation_models()

            # Dilater le masque
            import numpy as np
            import cv2 as _cv2_repose
            _person_np = np.array(person_mask.convert('L'))
            _max_dim = max(img.size)
            _dilate_ratio = 0.03 if do_relocation else 0.015
            _dilate_min = 30 if do_relocation else 14
            _dilate_px = max(_dilate_min, int(_max_dim * _dilate_ratio))
            _kernel_size = _dilate_px * 2 + 1
            _kernel = _cv2_repose.getStructuringElement(_cv2_repose.MORPH_ELLIPSE, (_kernel_size, _kernel_size))
            _person_np = _cv2_repose.dilate(_person_np, _kernel, iterations=1)
            person_mask_dilated = Image.fromarray(_person_np, mode='L')
            print(f"[REPOSE] Mask dilated by {_dilate_px}px (image {_max_dim}px)")

            from core.processing import process_image, GenerationCancelledException, set_phase, clear_preview

            try:
                # UN SEUL context manager pour les 2 passes (évite reload du modèle quantifié)
                # needs_controlnet=True: réutilise le preload, le controlnet est juste ignoré en pass 1
                # needs_ip_adapter=False: PAS d'IP-Adapter pour pass 1 (sinon VRAM saturée → 20s/step)
                # IP-Adapter sera chargé entre pass 1 et pass 2
                with generation_pipeline('inpaint', generation_id,
                                         preload_future=_preload_future,
                                         model_name=model,
                                         needs_controlnet=True,
                                         needs_ip_adapter=False) as mgr:
                    pipe = mgr.get_pipeline('inpaint')
                    clean_bg = img
                    time_bg = 0.0
                    result = None
                    original = img
                    status = ""
                    gen_time = 0.0

                    if do_relocation:
                        # ===== PASS 1: Supprimer la personne → fond propre =====
                        print(f"[REPOSE] === PASS 1: Background fill ===")
                        set_phase("generation", 25)

                        clean_bg = _background_fill_cv2(img, person_mask_dilated)
                        if clean_bg is None:
                            # Fallback diffusion si OpenCV indisponible
                            clean_bg, _, status_bg, time_bg = process_image(
                                img, "empty background, same environment, no person, same lighting",
                                strength=1.0, model_name=model,
                                mask=person_mask_dilated, steps=25,
                            negative_prompt="person, human, body, face, limbs, figure, silhouette",
                            pipe=pipe,
                            skip_auto_refine=True,
                            intent='background_fill',
                            metadata={
                                "original_prompt": prompt,
                                "router_intent": analysis.get("intent"),
                                "internal_pass": "repose_background_fill",
                            },
                        )

                            if clean_bg is None:
                                with generations_lock:
                                    active_generations.pop(generation_id, None)
                                return error_response(f"Repose pass 1 failed: {status_bg}")
                        else:
                            print(f"[REPOSE] Background fill via OpenCV inpaint")

                        print(f"[REPOSE] Pass 1 done in {time_bg:.1f}s — background clean")
                    else:
                        print(f"[REPOSE] Pass 1 skipped — local pose edit keeps original photo")

                    # Cancel check between passes
                    if is_cancelled():
                        raise GenerationCancelledException("Cancelled between passes")

                    # ===== Entre pass 1 et pass 2: charger IP-Adapter + face embedding =====
                    import torch as _torch
                    _torch.cuda.empty_cache()

                    # Charger IP-Adapter FaceID sur le pipe (ajoute projection layers, ne touche pas aux poids quantifiés)
                    mgr._load_ip_adapter_face()

                    # Extraire face embedding depuis l'image ORIGINALE (avant suppression)
                    face_embeds = None
                    if mgr._ip_adapter_loaded:
                        face_embeds = mgr.extract_face_embedding(img)
                        if face_embeds is not None:
                            print(f"[REPOSE] Face embedding extracted for IP-Adapter")
                        else:
                            print(f"[REPOSE] No face detected, IP-Adapter will use zero embeds")

                    # Libérer InsightFace de la VRAM (5 modèles ONNX ~500MB)
                    if mgr._face_analyzer is not None:
                        mgr._face_analyzer = None
                        _torch.cuda.empty_cache()
                        print(f"[REPOSE] InsightFace freed from VRAM")

                    # ===== PASS 2: Régénérer la personne dans la nouvelle pose =====
                    # 3. Construire le masque final
                    user_prompt = analysis.get('prompt_rewrite', prompt)
                    pose_refine_flags = {
                        'pose_change', 'arms_down', 'hands_face', 'hands_chest', 'standing', 'sitting', 'kneeling',
                        'all_fours', 'lying', 'back_view', 'bending',
                    }
                    if do_relocation:
                        relocated_base, repose_mask, repose_directives = _build_relocated_person_base(
                            img, clean_bg, person_mask, directives_prompt, refine_mask_source=body_refine_mask
                        )
                    else:
                        relocated_base = img
                        repose_mask = person_mask_dilated
                        repose_directives = dict(base_repose_directives)
                    print(
                        "[REPOSE] Target directives: "
                        f"{', '.join(repose_directives.get('debug_flags', [])) or 'default'}"
                    )
                    needs_pose_refine = any(flag in pose_refine_flags for flag in repose_directives.get('debug_flags', []))
                    relocation_ip_scale = max(0.75, float(analysis.get('ip_adapter_scale', 0.75))) if do_relocation else float(analysis.get('ip_adapter_scale', 0.5))
                    relocation_strength = 0.42 if do_relocation else 0.72

                    # 4. Construire le prompt final
                    final_repose_prompt = _build_repose_prompt(user_prompt, person_desc, repose_directives)
                    final_negative_prompt = _build_repose_negative_prompt(repose_directives)
                    print(f"[REPOSE] Final prompt: {final_repose_prompt[:120]}...")

                    if do_relocation and not needs_pose_refine:
                        result = relocated_base
                        original = img
                        status = "Person moved from original cutout"
                        gen_time = 0.0
                        print(f"[REPOSE] Pass 2 skipped — relocation uses original cutout only")
                    else:
                        print(f"[REPOSE] === PASS 2: Regenerate person ===")
                        set_phase("generation", steps)

                        # Depth map légère pour guider les proportions
                        depth_source = relocated_base if do_relocation else img
                        depth_image = mgr.extract_depth(depth_source)
                        controlnet_kwargs = {}
                        if depth_image is not None:
                            controlnet_kwargs['control_image'] = depth_image
                            controlnet_kwargs['controlnet_conditioning_scale'] = 0.16 if do_relocation else 0.18
                            print(
                                f"[REPOSE] Depth ControlNet enabled "
                                f"(scale={controlnet_kwargs['controlnet_conditioning_scale']})"
                            )

                        result, original, status, gen_time = process_image(
                            relocated_base if do_relocation else img, final_repose_prompt,
                            strength=relocation_strength, model_name=model,
                            mask=repose_mask, steps=steps,
                            negative_prompt=final_negative_prompt,
                            pipe=pipe,
                            ip_adapter_image_embeds=face_embeds,
                            ip_adapter_scale=relocation_ip_scale,
                            skip_auto_refine=do_relocation,
                            intent='repose' if do_relocation else 'pose_change',
                            metadata={
                                "original_prompt": user_prompt,
                                "router_intent": analysis.get("intent"),
                                "directives": repose_directives,
                            },
                            **controlnet_kwargs
                        )

            except GenerationCancelledException:
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            total_time = _time.time() - start_time

            with generations_lock:
                active_generations.pop(generation_id, None)

            if result:
                state.original_image = img
                state.modified_image = result
                state.current_prompt = prompt
                state.last_original_image = img
                state.last_modified_image = result

                from core.log_utils import big as log_big
                log_big(f"REPOSE DONE in {total_time:.1f}s (pass1={time_bg:.1f}s + pass2={gen_time:.1f}s)")

                mark_job_done(
                    result_type='image',
                    mode='repose',
                    generation_time=total_time,
                )
                return success_response(
                    mode='inpaint',
                    original=pil_to_base64(img),
                    modified=pil_to_base64(result),
                    generation_time=total_time,
                    generation_id=generation_id,
                    prompt=prompt
                )
            else:
                err = f"Repose pass 2 failed: {status}"
                mark_job_failed(err)
                return error_response(err)

        # Strength: NSFW override (nudity only) > user override > router decision
        if analysis['intent'] == 'nudity' and nsfw_strength and isinstance(nsfw_strength, (int, float)) and 0.0 < nsfw_strength <= 1.0:
            strength = float(nsfw_strength)
            print(f"  NSFW strength override: {strength}")
        elif strength_override and isinstance(strength_override, (int, float)) and 0.0 < strength_override <= 1.0:
            strength = float(strength_override)
        else:
            strength = analysis['strength']

        # ========== 2. ENHANCE PROMPT ==========
        enhanced_prompt = prompt
        style = "realistic"

        # Si le keyword pre-check ou un fast shortcut (pose:, nudity regex) a matche,
        # le prompt_rewrite est pret → skip l'enhance LLM (lent + charge LLM inutilement)
        _skip_enhance = (
            analysis.get('reason', '').startswith('Keyword pre-check:')
            or analysis.get('reason', '').startswith('pose:')
            or analysis.get('reason', '').startswith('nudity regex')
        )
        if _skip_enhance:
            enhanced_prompt = analysis.get('prompt_rewrite', prompt)
            print(f"[ENHANCE] Skip LLM ({analysis.get('reason', 'fast shortcut')})")
        elif enhance:
            from core.utility_ai import enhance_prompt as ai_enhance
            enhanced_prompt, style = ai_enhance(prompt, for_inpainting=is_inpainting)
            # Décharger le LLM après enhance pour libérer la VRAM avant diffusion
            try:
                from core.ollama_service import get_loaded_models, unload_model
                _loaded_after_enhance = get_loaded_models()
                if _loaded_after_enhance:
                    print(f"   \u251c\u2500 Déchargement post-enhance: {', '.join(_loaded_after_enhance)}...")
                    for _m in _loaded_after_enhance:
                        unload_model(_m)
            except Exception:
                pass

        # Cancel check apres ENHANCE
        if is_cancelled():
            print(f"[CANCEL] Cancelled after ENHANCE")
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        # ========== 3. TEXT-TO-IMAGE (pas d'image) ==========
        if not image_b64:
            clear_preview()
            set_progress_phase("prepare_text2img", 0, 100)

            # Décharger TOUS les LLM Ollama pour libérer la VRAM avant la diffusion (8GB OOM sinon)
            # Le chat utilise qwen3.5:2b, le router utilise UTILITY_MODEL — les deux prennent de la VRAM
            # SYNCHRONE: sur 8GB, SDXL charge juste après → faut que le unload finisse AVANT
            try:
                from core.ollama_service import get_loaded_models, unload_model
                _loaded = get_loaded_models()
                if _loaded:
                    print(f"[TEXT2IMG] Déchargement LLM avant génération: {', '.join(_loaded)}")
                    for _ollama_model in _loaded:
                        unload_model(_ollama_model)
            except Exception:
                pass

            if is_cancelled():
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            is_flux_model = model and 'flux' in model.lower()
            if is_flux_model:
                # Flux: prompt direct, pas de negative, pas de build_full_prompt SDXL
                final_prompt = prompt
                neg_prompt = None
            elif enhance:
                from core.utility_ai import build_full_prompt
                final_prompt, neg_prompt = build_full_prompt(enhanced_prompt, style, for_inpainting=False)
            else:
                final_prompt = prompt
                neg_prompt = None

            from core.log_utils import header as log_header, row as log_row, footer as log_footer
            log_header("TEXT2IMG")
            log_row("Prompt", final_prompt)
            if neg_prompt:
                log_row("Negative", neg_prompt)
            log_footer()

            try:
                # Style ref = init image pure (img2img). Face ref = IP-Adapter FaceID.
                from core.generation.face_reference import (
                    merge_faceid_embeddings,
                    resolve_text2img_face_reference_policy,
                )

                face_embeds = None
                style_init_img = None
                has_style = style_ref_b64 is not None

                # ControlNet pose: OpenPose for explicit poses, Depth for style ref extraction
                _export_pose = export_settings.get('pose', 'none')
                _pose_strength = export_settings.get('pose_strength', 0.5)
                _has_explicit_pose = _export_pose != 'none'
                needs_cn_pose = not is_flux_model and (
                    _has_explicit_pose
                    or (has_style and _pose_strength > 0)
                )
                # CN scale: direct from slider (0.0-1.5), min 0.3 quand actif
                _cn_scale = max(0.3, _pose_strength) if needs_cn_pose else 0.0
                # Style ref sans pose explicite → ControlNet Depth (meilleur pour poses complexes)
                _use_depth_cn = needs_cn_pose and not _has_explicit_pose and has_style
                _face_policy = resolve_text2img_face_reference_policy(
                    final_prompt,
                    face_ref_scale,
                    has_style_ref=has_style,
                    has_pose_control=needs_cn_pose,
                    reference_count=len(face_ref_b64s),
                )
                face_ref_scale = _face_policy.scale
                needs_face = bool(face_ref_b64s) and face_ref_scale > 0
                if face_ref_b64s and _face_policy.was_adjusted:
                    print(
                        "[TEXT2IMG] Face reference scale auto-cap "
                        f"{_face_policy.requested_scale:.2f} → {face_ref_scale:.2f} "
                        f"({_face_policy.reason})"
                    )

                set_progress_phase("load_text2img_model", 0, 100)
                with generation_pipeline('text2img', generation_id, model_name=model,
                                         needs_ip_adapter=needs_face,
                                         needs_controlnet=needs_cn_pose,
                                         use_depth_controlnet=_use_depth_cn) as mgr:
                    pipe = mgr.get_pipeline('text2img')
                    if needs_face:
                        valid_face_embeds = []
                        for idx, face_ref_b64_item in enumerate(face_ref_b64s[:5], start=1):
                            try:
                                face_ref_img = base64_to_pil(face_ref_b64_item)
                                face_embed = mgr.extract_face_embedding(face_ref_img)
                            except Exception as _face_ref_err:
                                print(f"[TEXT2IMG] Face reference {idx}/5 ignorée ({_face_ref_err})")
                                face_embed = None
                            if face_embed is not None:
                                valid_face_embeds.append(face_embed)
                        face_embeds = merge_faceid_embeddings(valid_face_embeds)
                        if face_embeds is not None:
                            print(
                                f"[TEXT2IMG] Face reference → IP-Adapter FaceID "
                                f"activé ({len(valid_face_embeds)}/{len(face_ref_b64s)} refs, "
                                f"scale={face_ref_scale:.2f}, policy={_face_policy.reason})"
                            )
                        else:
                            print(f"[TEXT2IMG] Aucun visage détecté dans les références, ignoré")
                    if has_style:
                        set_progress_phase("prepare_text2img", 20, 100)
                        style_init_img = base64_to_pil(style_ref_b64)
                        if style_init_img is not None:
                            print(f"[TEXT2IMG] Style ref → init image (img2img, scale={style_ref_scale})")

                    # Pick ControlNet model: Depth for style ref, OpenPose for explicit poses
                    _cn_depth_image = None
                    if _use_depth_cn:
                        _cn_model = mgr._controlnet_depth
                        # Pre-extract depth map from style ref
                        if style_init_img is not None:
                            _cn_depth_image = mgr.extract_depth(style_init_img)
                            if _cn_depth_image:
                                print(f"[TEXT2IMG] ControlNet Depth activé (style ref → depth map, scale={_cn_scale})")
                            else:
                                print(f"[TEXT2IMG] Depth extraction failed, CN désactivé")
                                _cn_model = None
                    elif needs_cn_pose:
                        _cn_model = mgr._controlnet_openpose
                    else:
                        _cn_model = None
                    _cn_pose = _export_pose if _has_explicit_pose else None

                    if _cn_model is not None and not _use_depth_cn:
                        set_progress_phase("prepare_pose_control", 0, 100)
                        _cn_src = f"pose '{_export_pose}'" if _has_explicit_pose else "style ref extraction"
                        print(f"[TEXT2IMG] ControlNet OpenPose activé ({_cn_src}, scale={_cn_scale})")

                    # LoRAs: charger/décharger selon les settings utilisateur
                    if lora_nsfw_enabled:
                        set_progress_phase("load_loras", 0, 100)
                        if mgr.ensure_lora_loaded("nsfw"):
                            mgr.set_lora_scale("nsfw", lora_nsfw_strength)
                            print(f"[TEXT2IMG] LoRA NSFW active (scale={lora_nsfw_strength})")
                    elif mgr._loras_loaded.get("nsfw"):
                        mgr.unload_lora("nsfw")
                    if lora_skin_enabled:
                        set_progress_phase("load_loras", 35, 100)
                        if mgr.ensure_lora_loaded("skin"):
                            mgr.set_lora_scale("skin", lora_skin_strength)
                            print(f"[TEXT2IMG] LoRA Skin active (scale={lora_skin_strength})")
                    elif mgr._loras_loaded.get("skin"):
                        mgr.unload_lora("skin")
                    if lora_breasts_enabled:
                        set_progress_phase("load_loras", 70, 100)
                        if mgr.ensure_lora_loaded("breasts"):
                            mgr.set_lora_scale("breasts", lora_breasts_strength)
                            print(f"[TEXT2IMG] LoRA Breasts active (scale={lora_breasts_strength})")
                    elif mgr._loras_loaded.get("breasts"):
                        mgr.unload_lora("breasts")

                    # Injecter les trigger words des LoRAs actifs dans le prompt
                    final_prompt = mgr.prepare_prompt_with_lora_triggers(final_prompt)

                    mark_job_update(phase='generating', progress=35, message='Génération image')
                    result, status, generation_time = generate_from_text(
                        final_prompt, model, enhance=False, steps=steps,
                        cancel_check=is_cancelled, pipe=pipe,
                        ip_adapter_image_embeds=face_embeds,
                        ip_adapter_scale=face_ref_scale,
                        style_ref_scale=style_ref_scale,
                        style_init_image=style_init_img,
                        guidance_override=text2img_guidance,
                        export_settings=export_settings,
                        controlnet_model=_cn_model,
                        controlnet_pose=_cn_pose,
                        controlnet_scale=_cn_scale,
                        controlnet_depth_image=_cn_depth_image,
                    )
            except GenerationCancelledException:
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            if is_cancelled():
                with generations_lock:
                    active_generations.pop(generation_id, None)
                mark_job_cancelled()
                return cancelled_response()

            with generations_lock:
                active_generations.pop(generation_id, None)

            if result:
                state.original_image = None
                state.modified_image = result
                state.current_prompt = prompt

                from core.log_utils import big as log_big
                log_big(f"DONE in {round(generation_time, 1)}s")

                # Récupérer la seed utilisée
                from core.generation.processing import _state as gen_state
                seed = getattr(gen_state, 'last_seed', None)
                mark_job_done(
                    result_type='image',
                    mode='txt2img',
                    generation_time=generation_time,
                    seed=seed,
                )
                return success_response(
                    mode='txt2img',
                    original=None,
                    modified=pil_to_base64(result),
                    generation_time=generation_time,
                    generation_id=generation_id,
                    prompt=prompt,
                    seed=seed
                )
            else:
                mark_job_failed(status)
                return error_response(status)

        # ========== 4. INPAINTING / EDIT ==========
        if is_cancelled():
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        img = base64_to_pil(image_b64)
        print(f"[INPUT] Image recue: {img.size[0]}x{img.size[1]} mode={img.mode}")

        # Charger le comportement pipeline du modele depuis model_behaviors.json
        from core.router_rules import get_model_behavior
        model_behavior = get_model_behavior(model)
        model_pipeline = model_behavior.get('pipeline', {}) if model_behavior else {}
        is_kontext = not model_pipeline.get('uses_mask', True)

        # needs_controlnet/needs_ip_adapter (le preload a déjà assumé controlnet=True)
        needs_controlnet = analysis.get('needs_controlnet', False) and model_pipeline.get('uses_controlnet', True)
        needs_ip_adapter = analysis.get('needs_ip_adapter', False) and model_pipeline.get('uses_ip_adapter', True)
        if not model_pipeline.get('uses_mask', True):
            needs_controlnet = False
            needs_ip_adapter = False

        # ========== 4c. DETECTION ORIENTATION (avant segmentation) ==========
        # On detecte tot pour savoir si l'image est a l'envers
        # MediaPipe est leger (~5ms), pas de cout notable
        body_orientation = None
        body_pose = None
        was_flipped = False
        is_brush_only = analysis['mask_strategy'] == 'brush_only'
        needs_body_info = analysis['intent'] in ('nudity', 'clothing_change', 'pose_change')

        if needs_body_info:
            try:
                from core.segmentation import detect_body_orientation
                orientation_result = detect_body_orientation(img)
                if orientation_result.get('flipped') and not is_brush_only:
                    was_flipped = True
                    img = img.rotate(180)
                    print(f"[FLIP] Image retournee 180 (detection upside-down)")
                elif orientation_result.get('flipped') and is_brush_only:
                    print("[FLIP] Skip auto-rotate (brush_only: conserve image + masque utilisateur)")
                if orientation_result['confidence'] > 0.4:
                    body_orientation = orientation_result['orientation']
                    body_pose = orientation_result.get('pose', 'standing')
            except (ImportError, Exception) as e:
                print(f"[WARN] Body orientation skipped: {e}")

        # ========== 5. CREER LE MASQUE (Smart Router decide) ==========
        # SKIP si le modele ne supporte pas la segmentation (ex: Flux Kontext)
        if not model_pipeline.get('uses_segmentation', True):
            print(f"[{model_behavior.get('architecture', '?').upper()}] Skip segmentation — model behavior")
            mask = None
            brush_mask = None
        else:
            from core.segmentation import create_smart_mask
            brush_mask = base64_to_pil(brush_mask_b64) if brush_mask_b64 else None

            # Si masque pinceau fourni, le sauvegarder et appliquer dilatation + blur
            if brush_mask is not None:
                import numpy as np
                from scipy import ndimage
                from PIL import ImageFilter
                import os
                from datetime import datetime

                # Sauvegarder le masque brut dans output
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                mask_raw_path = f"output/mask_raw_{timestamp}.png"
                os.makedirs("output", exist_ok=True)
                brush_mask.save(mask_raw_path)
                print(f"[MASK] Masque brut sauvegarde: {mask_raw_path}")

                # Convertir en array numpy pour traitement
                mask_arr = np.array(brush_mask.convert('L'))

                # Binariser le masque (seuil 128)
                mask_binary = (mask_arr > 128).astype(np.uint8) * 255

                # Dilatation legere (3 pixels) pour elargir la zone
                dilate_iterations = 3
                mask_dilated = ndimage.binary_dilation(
                    mask_binary > 0,
                    iterations=dilate_iterations
                ).astype(np.uint8) * 255

                # Convertir en PIL pour le blur
                mask_dilated_pil = Image.fromarray(mask_dilated, mode='L')

                # Blur gaussien sur les bords (cree un degrade)
                blur_radius = 5
                mask_blurred = mask_dilated_pil.filter(ImageFilter.GaussianBlur(radius=blur_radius))

                # Fusionner: garder le centre solide, bords en degrade
                # On prend le max entre le masque dilate et le masque blurre
                mask_final_arr = np.maximum(mask_dilated, np.array(mask_blurred))
                brush_mask = Image.fromarray(mask_final_arr, mode='L')

                # Sauvegarder le masque traite
                mask_processed_path = f"output/mask_processed_{timestamp}.png"
                brush_mask.save(mask_processed_path)
                print(f"[MASK] Masque traite (dilate +{dilate_iterations}px, blur {blur_radius}px): {mask_processed_path}")

                # Sauvegarder pour l'effet X-Ray Ghost (utiliser masque utilisateur au lieu de SegFormer)
                # On associe le masque a l'image originale via son hash
                img_hash = get_image_hash(img)
                state.brush_masks[img_hash] = brush_mask.copy()
                print(f"[MASK] Masque sauvegarde pour X-Ray Ghost (hash: {img_hash}, total: {len(state.brush_masks)})")

            # Si brush_only, pas besoin d'exclure le visage (l'utilisateur a dessine ce qu'il veut)
            should_exclude_face = (
                analysis['intent'] in ('nudity', 'clothing_change', 'hair_change') and
                analysis['mask_strategy'] != 'brush_only'
            )

            mask = create_smart_mask(
                image=img,
                strategy=analysis['mask_strategy'],
                classes=analysis.get('segformer_classes'),
                exclude_face=should_exclude_face,
                brush_mask=brush_mask,
                adjacent_classes=analysis.get('adjacent_classes'),
                tight=(analysis['intent'] == 'nudity')
            )

        # Cancel check apres SEGMENTATION
        if is_cancelled():
            print(f"[CANCEL] Cancelled after SEGMENTATION")
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        # ========== 6. BODY ORIENTATION — deja fait en 4b (avant segmentation) ==========

        # ========== 7. CONSTRUIRE LE PROMPT FINAL ==========
        # Si le modele n'utilise pas l'enhance LLM (ex: Kontext = instruction directe)
        if not model_pipeline.get('uses_enhance', True):
            from core.utility_ai import translate_to_english
            final_prompt = translate_to_english(prompt)
            neg_prompt = None if not model_pipeline.get('uses_negative_prompt', True) else analysis.get('negative_prompt')
            arch = model_behavior.get('architecture', '?').upper()
            print(f"[{arch}] Prompt (traduit): {final_prompt}")

        elif enhance_mode == 'none' or (not enhance and enhance_mode != 'light'):
            base_prompt = analysis.get('prompt_rewrite', prompt)
            final_prompt = base_prompt
            neg_prompt = analysis.get('negative_prompt')

        elif enhance_mode == 'light':
            base_prompt = analysis.get('prompt_rewrite', prompt)
            # No framing additions — ControlNet Depth + IP-Adapter handle pose/composition
            # Every extra token risks CLIP truncation (77 token limit in diffusers)
            final_prompt = base_prompt
            neg_prompt = analysis.get('negative_prompt')

        else:
            from core.utility_ai import build_full_prompt
            final_prompt, neg_prompt = build_full_prompt(enhanced_prompt, style, for_inpainting=True, orientation=body_orientation, pose=body_pose)

        # Flux: pas de negative prompt → positive reframing pour nudity
        # IMPORTANT: jamais de "no X" dans le prompt Flux (le modèle génère ce qu'il lit)
        # Flux Fill = inpainting descriptif : décrire ce qu'on VEUT VOIR dans la zone masquée
        if analysis.get('intent') == 'nudity' and not model_pipeline.get('uses_negative_prompt', True):
            # Ajouter skin realism pour Flux nudity
            flux_skin = "realistic skin texture with visible pores, even skin tone, soft natural lighting"
            if flux_skin not in final_prompt:
                final_prompt = f"{final_prompt}, {flux_skin}"
                print(f"[FLUX] Ajout skin realism au prompt")

        # ========== 7. LIBERER VRAM (SegFormer + utils plus necessaires) ==========
        # Skip sur gros GPU (40GB+) - tout peut rester en VRAM
        from core.models import IS_HIGH_END_GPU
        if not IS_HIGH_END_GPU:
            from core.segmentation import unload_segmentation_models
            unload_segmentation_models()

        # ========== 8. GENERATION ==========
        # needs_controlnet/needs_ip_adapter déjà calculés en 4b (avant segmentation, pour le preload)

        # Si le modele ne supporte pas les masques, forcer mask=None
        if not model_pipeline.get('uses_mask', True):
            mask = None
            arch = model_behavior.get('architecture', '?').upper()
            print(f"[{arch}] Skip mask/ControlNet/IP-Adapter — model behavior")

        # Appliquer min/max steps depuis le JSON
        gen_config = model_behavior.get('generation', {}) if model_behavior else {}
        min_steps = gen_config.get('min_steps', 20)
        max_steps = gen_config.get('max_steps', 50)
        default_steps = gen_config.get('default_steps', 35)

        # Si les steps sont en dessous du minimum du modele, ajuster
        if steps < min_steps:
            steps = min_steps
        # Pour les modeles avec un default specifique (ex: Flux Fill 50, Kontext 28)
        if not model_pipeline.get('uses_mask', True):
            steps = default_steps

        from core.log_utils import header as log_header, row as log_row, row2 as log_row2, row_full as log_row_full, footer as log_footer
        log_header("INPAINTING")
        log_row("Model", model)
        log_row2("Strength", strength, "Steps", steps)
        log_row("Enhance", enhance_mode)
        log_row_full("Prompt", final_prompt)
        if neg_prompt:
            log_row_full("Negative", neg_prompt)
        log_footer()

        # Cancel check avant génération
        if is_cancelled():
            print(f"[CANCEL] Cancelled before generation")
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        try:
            print(f"[INPAINT] Attente chargement modèle ({model})...")
            import time as _time_mod
            _t_wait = _time_mod.time()
            with generation_pipeline('inpaint', generation_id,
                                     preload_future=_preload_future,
                                     model_name=model,
                                     needs_controlnet=needs_controlnet,
                                     needs_ip_adapter=needs_ip_adapter) as mgr:
                print(f"[INPAINT] Modèle prêt ({_time_mod.time() - _t_wait:.1f}s)")
                pipe = mgr.get_pipeline('inpaint')

                # ControlNet Depth: extraire la depth map et passer au pipe (SDXL seulement)
                controlnet_kwargs = {}
                body_attributes = ""
                depth_image = None

                # Description vision : désactivée pour nudity (Florence décrit les vêtements
                # actuels, ce qui contredit l'intent de les enlever)
                # Garder le code pour d'autres intents si besoin futur

                if needs_controlnet:
                    _cn_type = analysis.get('controlnet_type', 'depth')
                    _pose_ok = False

                    if _cn_type == 'openpose':
                        # OpenPose ControlNet: extraire le squelette avec DWPose/OpenposeDetector
                        print("[POSE] Extraction squelette...")
                        try:
                            from core.generation.body_estimation import detect_pose, unload_dwpose
                            _pose_img, _pose_kp = detect_pose(img)
                            if _pose_img is not None:
                                controlnet_kwargs['control_image'] = _pose_img
                                _pose_ok = True
                                # Save debug image
                                try:
                                    import os as _os_dbg
                                    _dbg_dir = _os_dbg.path.join(_os_dbg.path.dirname(_os_dbg.path.dirname(_os_dbg.path.dirname(__file__))), "output")
                                    _os_dbg.makedirs(_dbg_dir, exist_ok=True)
                                    _pose_img.save(_os_dbg.path.join(_dbg_dir, "debug_openpose.png"))
                                except Exception:
                                    pass
                                print(f"[POSE] Squelette extrait ({_pose_img.size[0]}x{_pose_img.size[1]})")
                            else:
                                print("[POSE] Aucun détecteur de pose disponible, fallback depth")
                            # Free DWPose VRAM (~300MB) before SDXL generation
                            unload_dwpose()
                            import torch as _torch_pose
                            _torch_pose.cuda.empty_cache()
                        except Exception as _e:
                            print(f"[POSE] Erreur extraction pose ({_e}), fallback depth")

                    _is_pose_intent = analysis.get('intent') == 'pose_change'

                    # Si OpenPose OK, swap ControlNet
                    if _cn_type == 'openpose' and _pose_ok:
                        mgr.swap_controlnet('openpose')
                        controlnet_kwargs['controlnet_conditioning_scale'] = analysis.get('controlnet_scale', 0.4)
                    else:
                        # Depth ControlNet (default ou fallback si OpenPose a échoué)
                        if _cn_type == 'openpose':
                            print("[POSE] Fallback: utilisation depth ControlNet au lieu d'openpose")
                            _cn_type = 'depth'
                        if mgr._active_controlnet_type != 'depth':
                            mgr.swap_controlnet('depth')
                        if depth_image is None:
                            depth_image = mgr.extract_depth(img)
                        if depth_image is None:
                            from PIL import Image as PILImage
                            depth_image = PILImage.new('RGB', img.size, (128, 128, 128))
                            print("[MM] Depth fallback: image grise (impact minimal)")
                        controlnet_kwargs['control_image'] = depth_image
                        if _is_pose_intent:
                            # Pose change + depth fallback: scale modéré pour garder les
                            # proportions du corps (trop bas = jambes/bras trop longs)
                            # tout en laissant un peu de marge pour la nouvelle pose
                            _pose_depth_scale = 0.35
                            controlnet_kwargs['controlnet_conditioning_scale'] = _pose_depth_scale
                            print(f"[POSE] Depth scale pose: {_pose_depth_scale} (compromis proportions/liberté)")
                        elif controlnet_depth_override is not None:
                            controlnet_kwargs['controlnet_conditioning_scale'] = float(controlnet_depth_override)
                        else:
                            controlnet_kwargs['controlnet_conditioning_scale'] = analysis.get('controlnet_scale', 0.54)

                # LoRA: charger à la demande seulement si activé par l'user
                # Route automatique SDXL/Flux via ensure_lora_loaded() + set_lora_scale()
                # (skin → clothes_off sur Flux, nsfw → FLUX NSFW Unlock sur Flux)
                if analysis['intent'] == 'nudity':
                    # NSFW LoRA — lazy load si activé, unload si désactivé
                    if lora_nsfw_enabled:
                        if mgr.ensure_lora_loaded("nsfw"):
                            mgr.set_lora_scale("nsfw", lora_nsfw_strength)
                            print(f"[MM] LoRA NSFW active (scale={lora_nsfw_strength})")
                    elif mgr._loras_loaded.get("nsfw"):
                        mgr.unload_lora("nsfw")

                    # Skin LoRA — SDXL: Skin Realism, Flux: Clothes Remover
                    if lora_skin_enabled:
                        if mgr.ensure_lora_loaded("skin"):
                            mgr.set_lora_scale("skin", lora_skin_strength)
                            print(f"[MM] LoRA Skin active (scale={lora_skin_strength})")
                    elif mgr._loras_loaded.get("skin"):
                        mgr.unload_lora("skin")

                    # Breasts LoRA — SDXL: Real Breasts Style, Flux: Realistic Nipples
                    if lora_breasts_enabled:
                        if mgr.ensure_lora_loaded("breasts"):
                            mgr.set_lora_scale("breasts", lora_breasts_strength)
                            print(f"[MM] LoRA Breasts active (scale={lora_breasts_strength})")
                    elif mgr._loras_loaded.get("breasts"):
                        mgr.unload_lora("breasts")
                else:
                    # Désactiver les LoRAs si pas nudity
                    if mgr._loras_loaded.get("nsfw"):
                        mgr.unload_lora("nsfw")
                    if mgr._loras_loaded.get("skin"):
                        mgr.unload_lora("skin")
                    if mgr._loras_loaded.get("breasts"):
                        mgr.unload_lora("breasts")

                # Ajouter les attributs corporels detectes au prompt
                if body_attributes:
                    final_prompt = f"{final_prompt}, {body_attributes}"
                    print(f"[BODY] Prompt enrichi avec: {body_attributes}")

                # Injecter les trigger words des LoRAs actifs dans le prompt
                final_prompt = mgr.prepare_prompt_with_lora_triggers(final_prompt)

                # IP-Adapter FaceID: extraire le face embedding
                face_embeds = None
                if needs_ip_adapter and mgr._ip_adapter_loaded:
                    face_embeds = mgr.extract_face_embedding(img)

                # Check cancellation before starting (pipe may be None after unload-all)
                if is_cancelled():
                    raise GenerationCancelledException("Annulee avant generation")

                mark_job_update(phase='generating', progress=35, message='Inpainting en cours')
                result, original, status, generation_time = process_image(
                    img, final_prompt, strength, model,
                    mask=mask,
                    enhance=False, steps=steps,
                    cancel_check=is_cancelled,
                    negative_prompt=neg_prompt,
                    pipe=pipe,
                    ip_adapter_image_embeds=face_embeds,
                    ip_adapter_scale=analysis.get('ip_adapter_scale', 0.6),
                    skip_auto_refine=skip_auto_refine,
                    guidance_scale=gen_config.get('guidance_scale'),
                    brush_mode=has_brush,
                    composite_radius=int(composite_radius_override) if composite_radius_override is not None else None,
                    enable_controlnet=needs_controlnet,
                    intent=analysis.get('intent'),
                    metadata={
                        "original_prompt": prompt,
                        "router_intent": analysis.get('intent'),
                        "mask_strategy": analysis.get('mask_strategy'),
                    },
                    **controlnet_kwargs
                )
        except GenerationCancelledException:
            with generations_lock:
                active_generations.pop(generation_id, None)
            # Swap back to depth if openpose was used
            if mgr._active_controlnet_type == 'openpose':
                mgr.swap_controlnet('depth')
            mark_job_cancelled()
            return cancelled_response()

        # Swap back to depth ControlNet if openpose was used
        if mgr._active_controlnet_type == 'openpose':
            mgr.swap_controlnet('depth')

        if is_cancelled():
            with generations_lock:
                active_generations.pop(generation_id, None)
            mark_job_cancelled()
            return cancelled_response()

        with generations_lock:
            active_generations.pop(generation_id, None)

        if result:
            # Si l'image etait a l'envers, remettre le resultat dans l'orientation originale
            if was_flipped:
                result = result.rotate(180)
                original = original.rotate(180)
                if mask:
                    mask = mask.rotate(180)
                print(f"[FLIP] Resultat remis dans l'orientation originale")

            state.original_image = original
            state.modified_image = result
            state.current_prompt = prompt
            state.last_original_image = original
            state.last_modified_image = result
            state.last_mask = mask
            state.last_prompt = final_prompt
            state.last_model = model
            # Sauvegarder la depth map pour refine avec ControlNet
            state.last_control_image = controlnet_kwargs.get('control_image')

            from core.log_utils import big as log_big
            log_big(f"DONE in {round(generation_time, 1)}s")

            # Sauvegarder le log de generation dans output/
            try:
                import os
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "last_generation_log.txt")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write(f"{'='*60}\n")
                    f.write(f"  GENERATION LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"{'='*60}\n\n")

                    # Analyse du prompt original
                    f.write(f"[1. ANALYSE DU PROMPT]\n")
                    f.write(f"  Prompt original:  \"{prompt}\"\n")
                    f.write(f"  -> Le systeme a detecte l'intention: {analysis.get('intent', 'N/A').upper()}\n")
                    if analysis.get('intent') == 'nudity':
                        f.write(f"  -> Mode NUDITY active: ControlNet + IP-Adapter + LoRAs\n")
                    f.write(f"\n")

                    # Decisions du Smart Router
                    f.write(f"[2. DECISIONS SMART ROUTER]\n")
                    f.write(f"  Strategie masque: {analysis.get('mask_strategy', 'N/A')}\n")
                    if analysis.get('mask_strategy') == 'clothes':
                        f.write(f"  -> Ciblage automatique des vetements via SegFormer\n")
                    f.write(f"  Force inpainting: {analysis.get('strength', 'N/A')}\n")
                    f.write(f"  ControlNet Depth: {'OUI (preserve la pose)' if analysis.get('needs_controlnet') else 'NON'}\n")
                    f.write(f"  IP-Adapter Face:  {'OUI (preserve le visage)' if analysis.get('needs_ip_adapter') else 'NON'}\n")
                    f.write(f"\n")

                    # Body Description (via vision model)
                    f.write(f"[3. DESCRIPTION CORPORELLE]\n")
                    if body_attributes:
                        f.write(f"  Attributs: {body_attributes}\n")
                        f.write(f"  -> Ajoutes au prompt via qwen3.5:2b\n")
                    else:
                        f.write(f"  Status: Non disponible\n")
                    f.write(f"\n")

                    # LoRAs
                    nsfw_lora = lora_nsfw_strength if lora_nsfw_enabled else 0.0
                    skin_lora = lora_skin_strength if lora_skin_enabled else 0.0
                    is_flux_log = mgr._is_flux_pipeline()
                    nsfw_label = "NSFW Unlock Flux" if is_flux_log else "NSFW XL v2.1"
                    skin_label = "Clothes Remover Flux" if is_flux_log else "Skin Realism"
                    f.write(f"[4. LORAS ACTIVES]\n")
                    f.write(f"  {nsfw_label}:     {nsfw_lora} {'(ACTIF)' if nsfw_lora > 0 else '(desactive)'}\n")
                    skin_suffix = '(ACTIF)' if is_flux_log else '(ACTIF) + trigger word'
                    f.write(f"  {skin_label}:     {skin_lora} {skin_suffix if skin_lora > 0 else '(desactive)'}\n")
                    if nsfw_lora > 0 or skin_lora > 0:
                        f.write(f"  -> Les LoRAs ameliorent le realisme de la peau et du corps\n")
                    f.write(f"\n")

                    # Prompt final
                    f.write(f"[5. PROMPT FINAL ENVOYE AU MODELE]\n")
                    f.write(f"  {final_prompt}\n")
                    f.write(f"\n")
                    f.write(f"  Negative prompt:\n")
                    f.write(f"  {neg_prompt}\n")
                    f.write(f"\n")

                    # Resultat
                    f.write(f"[6. RESULTAT]\n")
                    f.write(f"  Modele:           {model}\n")
                    f.write(f"  Steps:            {steps}\n")
                    f.write(f"  Temps generation: {round(generation_time, 1)}s\n")
                    f.write(f"  Status:           SUCCESS\n")
                    f.write(f"\n{'='*60}\n")
                    f.write(f"  Ce fichier est ecrase a chaque generation.\n")
                    f.write(f"  Chemin: output/last_generation_log.txt\n")
                    f.write(f"{'='*60}\n")
                print(f"[LOG] Saved to output/last_generation_log.txt")
            except Exception as log_err:
                print(f"[LOG] Erreur sauvegarde log: {log_err}")

            print(f"[RESPONSE] original={original.size} modified={result.size}")
            mark_job_done(
                result_type='image',
                mode='inpaint',
                generation_time=generation_time,
                router_intent=analysis.get('intent'),
                mask_strategy=analysis.get('mask_strategy'),
            )
            return success_response(
                mode='inpaint',
                original=pil_to_base64(original),
                modified=pil_to_base64(result),
                generation_time=generation_time,
                generation_id=generation_id,
                prompt=prompt
            )
        else:
            mark_job_failed(status)
            return error_response(status)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            mark_job_failed(str(e))
        except Exception:
            pass
        return error_response(str(e))


# ─── ADetailer-style detail refinement ───
ADETAILER_FACE_CLASSES = [11]
ADETAILER_FACE_STRENGTH = 0.28  # Low strength = preserve identity/style, just clean details
ADETAILER_FACE_STEPS = 22
ADETAILER_FACE_DILATION = 14  # px
ADETAILER_HAND_STRENGTH = 0.38  # Hands usually need a bit more denoise than faces
ADETAILER_HAND_STEPS = 24
ADETAILER_HAND_DILATION = 10  # px
ADETAILER_MIN_REGION_AREA = 400  # ~20x20px minimum
ADETAILER_MAX_FACE_REGIONS = 4
ADETAILER_MAX_HAND_REGIONS = 4
ADETAILER_FACE_SUFFIX = ", same identity, matching original style, clean facial details, sharp symmetrical eyes, detailed pupils, natural facial proportions"
ADETAILER_FACE_NEG = "changed identity, different face, blurry face, melted face, deformed eyes, crossed eyes, asymmetrical eyes, extra eyes, bad anatomy"
ADETAILER_HAND_SUFFIX = ", matching original style, detailed natural hands, five fingers on each hand, clean finger anatomy, natural fingernails, matching lighting"
ADETAILER_HAND_NEG = "extra fingers, missing fingers, fused fingers, malformed hands, broken wrists, deformed hands, blurry hands, bad anatomy"


def _split_detail_regions(mask, dilation_px=0, min_area=ADETAILER_MIN_REGION_AREA, max_regions=4):
    """Split a binary mask into dilated connected-component masks, largest first."""
    import numpy as np
    import cv2

    mask_np = np.array(mask.convert('L'))
    binary = (mask_np > 127).astype(np.uint8)
    num_labels, labels = cv2.connectedComponents(binary)

    regions = []
    for label_id in range(1, num_labels):  # skip background (0)
        region_mask = (labels == label_id).astype(np.uint8) * 255
        area = int(np.sum(region_mask > 0))
        if area < min_area:
            continue

        if dilation_px > 0:
            kernel_size = dilation_px * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            region_mask = cv2.dilate(region_mask, kernel, iterations=1)

        regions.append((area, Image.fromarray(region_mask, mode='L')))

    regions.sort(key=lambda x: x[0], reverse=True)
    return [region for _, region in regions[:max_regions]]


def _extract_face_regions(image):
    """Extract individual face masks from an image using SCHP segmentation.

    Args:
        image: PIL Image (RGB)

    Returns:
        list[PIL.Image mode L] — one mask per face, sorted by area descending.
        Each mask is dilated by ADETAILER_FACE_DILATION px, regions < ADETAILER_MIN_REGION_AREA filtered out.
    """
    from core.segmentation import create_smart_mask

    # Get combined face mask (class 11 = face in SCHP)
    face_mask = create_smart_mask(
        image, strategy='person',
        classes=ADETAILER_FACE_CLASSES,
        exclude_face=False, tight=True
    )
    return _split_detail_regions(
        face_mask,
        dilation_px=ADETAILER_FACE_DILATION,
        min_area=ADETAILER_MIN_REGION_AREA,
        max_regions=ADETAILER_MAX_FACE_REGIONS,
    )


def _extract_hand_regions(image):
    """Extract hand masks from the B4 parser when available.

    B4 has a dedicated hands class (13). SCHP/B2 class 13 means something else,
    so this intentionally avoids fusion/class overrides for hand detailing.
    """
    from pathlib import Path
    from PIL import Image as PILImage
    import torch

    try:
        from core.generation import segmentation as seg

        device = "cuda" if torch.cuda.is_available() else "cpu"
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        _, hand_array, pct, _, _, _ = seg._run_b4(
            image, "person", [13], device, output_dir, True
        )
        if pct <= 0:
            return []

        hand_mask = PILImage.fromarray(hand_array, mode="L")
        return _split_detail_regions(
            hand_mask,
            dilation_px=ADETAILER_HAND_DILATION,
            min_area=ADETAILER_MIN_REGION_AREA,
            max_regions=ADETAILER_MAX_HAND_REGIONS,
        )
    except Exception as e:
        print(f"[ADETAILER] Hand detection skipped: {e}")
        return []


@generation_bp.route('/fix-details', methods=['POST'])
def fix_details():
    """
    ADetailer-style refinement: detects small detail regions (faces/hands), then
    re-inpaints each region at high resolution using crop-to-mask + Fooocus.
    """
    _set_generation_cancelled(False)

    state = _get_state()
    active_generations = _get_active_generations()
    generations_lock = _get_generations_lock()
    generation_pipeline = _get_generation_pipeline()
    base64_to_pil = _base64_to_pil
    pil_to_base64 = _pil_to_base64

    from core.api_helpers import success_response, error_response, cancelled_response, validation_error
    from core.processing import GenerationCancelledException

    try:
        data = request.json
        generation_id = data.get('generationId') or str(uuid.uuid4())
        image_param = data.get('image')  # URL or base64
        target = (data.get('target') or 'auto').strip().lower()

        # Load the image
        if image_param:
            if image_param.startswith('data:'):
                img = base64_to_pil(image_param)
            elif image_param.startswith('/output/') or image_param.startswith('output/'):
                from pathlib import Path
                img_path = Path(image_param.lstrip('/'))
                if img_path.exists():
                    img = Image.open(img_path).convert('RGB')
                else:
                    return validation_error(f'Image non trouvee: {image_param}')
            else:
                img = state.last_modified_image
        else:
            img = state.last_modified_image

        if img is None:
            return validation_error('Aucune image disponible')

        from core.log_utils import big
        big(f"FIX DETAILS (ADetailer) | {target}")

        model = state.last_model or 'epiCRealism XL (Moyen)'

        # Register this generation
        with generations_lock:
            active_generations[generation_id] = {"cancelled": False}

        def is_cancelled():
            if _is_generation_cancelled():
                return True
            with generations_lock:
                gen = active_generations.get(generation_id, {})
                return gen.get("cancelled", False)

        # 1. Extract detail regions. Keep faces first, then hands.
        face_masks = []
        hand_masks = []
        if target in ('auto', 'all', 'face', 'faces'):
            face_masks = _extract_face_regions(img)
        if target in ('auto', 'all', 'hand', 'hands'):
            hand_masks = _extract_hand_regions(img)

        # Free segmentation VRAM before generation
        from core.models import IS_HIGH_END_GPU
        if not IS_HIGH_END_GPU:
            from core.segmentation import unload_segmentation_models
            unload_segmentation_models()

        if not face_masks and not hand_masks:
            with generations_lock:
                active_generations.pop(generation_id, None)
            return validation_error('Aucun visage ou main detecte')

        print(f"[ADETAILER] {len(face_masks)} face(s), {len(hand_masks)} hand region(s) detected")

        # Cancel check after segmentation
        if is_cancelled():
            with generations_lock:
                active_generations.pop(generation_id, None)
            return cancelled_response()

        # Build prompt: use ORIGINAL generation prompt + face detail suffix
        # This preserves identity (same subject/style) while adding detail keywords
        base_prompt = (state.last_prompt or "").strip()
        if not base_prompt:
            base_prompt = "same subject, matching original image style and lighting"
        face_prompt = base_prompt + ADETAILER_FACE_SUFFIX
        hand_prompt = base_prompt + ADETAILER_HAND_SUFFIX
        print(f"[ADETAILER] Face prompt: {face_prompt}")
        if hand_masks:
            print(f"[ADETAILER] Hand prompt: {hand_prompt}")

        detail_regions = [
            {
                "kind": "face",
                "mask": face_mask,
                "prompt": face_prompt,
                "negative": ADETAILER_FACE_NEG,
                "strength": ADETAILER_FACE_STRENGTH,
                "steps": ADETAILER_FACE_STEPS,
            }
            for face_mask in face_masks
        ] + [
            {
                "kind": "hand",
                "mask": hand_mask,
                "prompt": hand_prompt,
                "negative": ADETAILER_HAND_NEG,
                "strength": ADETAILER_HAND_STRENGTH,
                "steps": ADETAILER_HAND_STEPS,
            }
            for hand_mask in hand_masks
        ]

        import time as _time
        start_time = _time.time()
        working_image = img
        faces_fixed = 0
        hands_fixed = 0

        try:
            with generation_pipeline('inpaint', generation_id, model_name=model) as mgr:
                pipe = mgr.get_pipeline('inpaint')

                from core.processing import process_image, set_phase, clear_preview

                # 2. Process regions sequentially (largest faces first, then hands).
                for i, region in enumerate(detail_regions):
                    if is_cancelled():
                        raise GenerationCancelledException("Cancelled during detail fix")

                    kind = region["kind"]
                    print(f"[ADETAILER] Processing {kind} {i+1}/{len(detail_regions)}")
                    clear_preview()
                    set_phase("generation", region["steps"])

                    result, _, status, gen_time = process_image(
                        working_image,
                        region["prompt"],
                        region["strength"],
                        model,
                        mask=region["mask"],
                        enhance=False,
                        steps=region["steps"],
                        cancel_check=is_cancelled,
                        negative_prompt=region["negative"],
                        pipe=pipe,
                        skip_auto_refine=True,
                        intent='fix_details',
                        metadata={
                            "original_prompt": base_prompt,
                            "router_intent": "fix_details",
                            "detail_kind": kind,
                        },
                    )

                    if result is None:
                        print(f"[ADETAILER] {kind} {i+1} failed: {status}")
                        continue

                    working_image = result
                    if kind == "hand":
                        hands_fixed += 1
                    else:
                        faces_fixed += 1
                    print(f"[ADETAILER] {kind} {i+1} done in {gen_time:.1f}s")

        except GenerationCancelledException:
            with generations_lock:
                active_generations.pop(generation_id, None)
            return cancelled_response()

        total_time = _time.time() - start_time

        with generations_lock:
            active_generations.pop(generation_id, None)

        details_fixed = faces_fixed + hands_fixed
        if details_fixed > 0:
            state.modified_image = working_image
            state.last_modified_image = working_image

            from core.log_utils import big as log_big
            log_big(f"FIX DETAILS DONE | {faces_fixed} face(s), {hands_fixed} hand(s) | {total_time:.1f}s")

            return success_response(
                mode='fix_details',
                original=pil_to_base64(img),
                modified=pil_to_base64(working_image),
                generation_time=total_time,
                generation_id=generation_id,
                prompt=face_prompt if faces_fixed else hand_prompt,
                faces_fixed=faces_fixed,
                hands_fixed=hands_fixed,
                details_fixed=details_fixed,
            )
        else:
            return error_response('Aucun detail n\'a pu etre corrige')

    except Exception as e:
        print(f"Fix details error: {e}")
        import traceback
        traceback.print_exc()
        return error_response(str(e))


@generation_bp.route('/generate/preview')
def get_generation_preview():
    """Retourne la preview de generation en cours (long polling)"""
    import time

    try:
        from core.processing import get_current_preview_status

        # Long polling: attendre qu'un nouveau step soit disponible
        last_step = request.args.get('last_step', 0, type=int)
        timeout = 10  # Max 10 secondes d'attente
        start_time = time.time()

        last_phase = request.args.get('last_phase', 'generation')

        while time.time() - start_time < timeout:
            status = get_current_preview_status()
            preview = status.get('preview')
            step = status.get('step', 0)
            total = status.get('total', 0)
            phase = status.get('phase', 'generation')
            message = status.get('message', '')

            # Si nouveau step disponible, retourner immediatement
            if step > last_step:
                return jsonify({
                    'preview': preview,
                    'step': step,
                    'total': total,
                    'phase': phase,
                    'message': message,
                })

            # Changement de phase: retourner meme sans preview pour afficher les
            # etapes longues de premier lancement (downloads SCHP, assets, etc.).
            if phase != last_phase:
                if preview is not None:
                    return jsonify({
                        'preview': preview,
                        'step': step,
                        'total': total,
                        'phase': phase,
                        'message': message,
                    })
                # Si pas de preview, juste notifier le changement de phase sans image
                return jsonify({
                    'preview': None,
                    'step': step,
                    'total': total,
                    'phase': phase,
                    'message': message,
                    'phase_changed': True
                })

            # Si on est en fine_tuning/refine et qu'il y a un nouveau step avec preview
            if phase in ('fine_tuning', 'refine') and step > 0 and preview is not None:
                return jsonify({
                    'preview': preview,
                    'step': step,
                    'total': total,
                    'phase': phase,
                    'message': message,
                })

            # Si generation terminee (step 0 apres avoir eu des steps ET phase normale)
            # Ne PAS retourner done si on est en fine_tuning/refine
            if last_step > 0 and step == 0 and phase == 'generation' and last_phase not in ('fine_tuning', 'refine'):
                return jsonify({'preview': None, 'step': 0, 'total': 0, 'done': True, 'phase': 'generation'})

            # Attendre un peu avant de re-verifier
            time.sleep(0.3)

        # Timeout - retourner l'etat actuel
        status = get_current_preview_status()
        return jsonify({
            'preview': status.get('preview'),
            'step': status.get('step', 0),
            'total': status.get('total', 0),
            'phase': status.get('phase', 'generation'),
            'message': status.get('message', ''),
            'timeout': True
        })
    except Exception as e:
        return jsonify({'preview': None, 'error': str(e)})


@generation_bp.route('/cancel-generation', methods=['POST'])
def cancel_generation():
    """
    Annule une generation en cours.

    Le flag 'cancelled' est verifie par le callback de generation.
    Pour un arret immediat, le frontend appelle ensuite /models/unload-image
    qui force le dechargement du modele et libere la VRAM.
    """
    active_generations = _get_active_generations()
    generations_lock = _get_generations_lock()
    from core.model_manager import ModelManager

    data = request.json
    generation_id = data.get('generationId')
    chat_id = data.get('chatId')
    force_unload = data.get('forceUnload', False)

    cancelled_count = 0
    try:
        from core.runtime import get_job_manager
        runtime_jobs = get_job_manager()
    except Exception:
        runtime_jobs = None

    # Clear preview immédiatement pour éviter que la prochaine gen affiche l'ancien step
    from core.processing import clear_preview
    clear_preview()

    with generations_lock:
        if generation_id and generation_id in active_generations:
            active_generations[generation_id]["cancelled"] = True
            cancelled_count += 1
            if runtime_jobs:
                runtime_jobs.request_cancel(generation_id)
            print(f"[CANCEL] Generation {generation_id} cancelled")

        # Annuler aussi par chat_id (si on change de conversation)
        if chat_id:
            for gen_id, gen_info in list(active_generations.items()):
                if gen_info.get("chat_id") == chat_id and not gen_info.get("cancelled"):
                    gen_info["cancelled"] = True
                    cancelled_count += 1
                    if runtime_jobs:
                        runtime_jobs.request_cancel(gen_id)
                    print(f"[CANCEL] Generation {gen_id} cancelled (chat {chat_id})")

    # Si force_unload, decharger immediatement tous les modeles
    if force_unload and cancelled_count > 0:
        print(f"[CANCEL] Force unload requested, clearing VRAM...")
        try:
            ModelManager.get().unload_all()
        except Exception as e:
            print(f"[CANCEL] Unload error: {e}")

    return jsonify({'success': True, 'cancelled': cancelled_count})


@generation_bp.route('/cancel-all', methods=['POST'])
def cancel_all():
    """Annule TOUT: chat stream + toutes les generations image/video en cours"""
    _set_chat_stream_cancelled(True)
    _set_generation_cancelled(True)

    # Invalidate any running preload so it bails out early
    with _preload_lock:
        global _preload_gen_id
        _preload_gen_id = None

    # Clear preview immédiatement
    from core.processing import clear_preview
    clear_preview()

    active_generations = _get_active_generations()
    generations_lock = _get_generations_lock()

    # Aussi marquer toutes les generations actives comme annulees
    try:
        from core.runtime import get_job_manager
        runtime_jobs = get_job_manager()
    except Exception:
        runtime_jobs = None

    with generations_lock:
        for gen_id, gen_info in active_generations.items():
            gen_info["cancelled"] = True
            if runtime_jobs:
                runtime_jobs.request_cancel(gen_id)

    print(f"[CANCEL] ===== ALL CANCELLED by user =====")
    return jsonify({'success': True})


@generation_bp.route('/upscale', methods=['POST'])
def upscale():
    """Upscale x2 avec Real-ESRGAN"""
    import time

    state = _get_state()
    generation_pipeline = _get_generation_pipeline()
    base64_to_pil = _base64_to_pil
    pil_to_base64 = _pil_to_base64

    from core.api_helpers import error_response, validation_error, image_response
    from core.processing import upscale_image

    try:
        data = request.json
        image_b64 = data.get('image')
        model = data.get('model', 'epiCRealism XL (Moyen)')  # Modele selectionne par l'utilisateur
        chat_model = data.get('chat_model', 'qwen3.5:2b')

        if not image_b64:
            return validation_error('Image requise')

        # ===== LOG: Debut =====
        print(f"\n{'---'*17}")
        print(f"UPSCALE | Real-ESRGAN x2 | Refine: {model}")
        print(f"{'---'*17}")

        start_time = time.time()

        generation_id = str(uuid.uuid4())

        with generation_pipeline('upscale', generation_id) as mgr:
            img = base64_to_pil(image_b64)
            upscaler = mgr.get_pipeline('upscale')
            result, status = upscale_image(img, scale=2, model_name=model, pipe=upscaler)

            generation_time = time.time() - start_time

            if result:
                state.modified_image = result

                print(f"[UPSCALE] Termine en {generation_time:.1f}s")
                print(f"{'='*50}\n")

                return image_response(pil_to_base64(result), status=status, generation_time=generation_time)
            else:
                print(f"[UPSCALE] Erreur: {status}")
                return error_response(status)

    except Exception as e:
        print(f"[UPSCALE] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return error_response(str(e))


@generation_bp.route('/xray-mask', methods=['POST'])
def xray_mask():
    """
    Genere un masque X-Ray des vetements.
    Utilise le masque dessine a la main si disponible pour cette image, sinon SegFormer.
    Retourne les vetements de l'image originale en PNG transparent.
    """
    state = _get_state()
    base64_to_pil = _base64_to_pil
    pil_to_base64 = _pil_to_base64
    get_image_hash = _get_image_hash

    try:
        data = request.json
        image_b64 = data.get('image')

        if not image_b64:
            return jsonify({'success': False, 'error': 'Image requise'})

        import numpy as np

        original = base64_to_pil(image_b64)

        # Chercher un masque dessine a la main pour cette image via son hash
        img_hash = get_image_hash(original)
        brush_mask = state.brush_masks.get(img_hash)

        if brush_mask is not None:
            print(f"\n[X-RAY] Masque utilisateur trouve pour hash {img_hash}")
            # Redimensionner le masque si necessaire
            if brush_mask.size != original.size:
                brush_mask = brush_mask.resize(original.size, Image.LANCZOS)
            mask_array = np.array(brush_mask.convert('L'))
            source = "masque utilisateur"
        else:
            # Fallback: SegFormer pour detecter les vetements
            print(f"\n[X-RAY] Pas de masque utilisateur (hash {img_hash}), utilisation SegFormer...")
            from core.segmentation import create_smart_mask

            # Convertir en RGB pour SegFormer (RGBA/autres formats causent des erreurs)
            if original.mode != 'RGB':
                original_rgb = original.convert('RGB')
            else:
                original_rgb = original

            # Obtenir le masque des vetements avec SegFormer via Smart Mask
            clothes_mask = create_smart_mask(original_rgb, strategy='clothes', exclude_face=False)
            mask_array = np.array(clothes_mask)
            source = "SegFormer"

        # Appliquer le masque pour extraire les vetements de l'original
        original_rgba = original.convert("RGBA")

        # Binariser le masque (bords nets, pas de semi-transparence)
        mask_binary = np.where(mask_array > 127, 255, 0).astype(np.uint8)

        # Creer une image avec transparence (vetements visibles, reste transparent)
        result_array = np.array(original_rgba)
        result_array[:, :, 3] = mask_binary  # Alpha binaire = bords nets

        result = Image.fromarray(result_array, mode="RGBA")

        # Compter les pixels
        clothes_pixels = np.sum(mask_binary > 0)
        total_pixels = mask_array.shape[0] * mask_array.shape[1]
        ratio = clothes_pixels / total_pixels * 100

        print(f"[X-RAY] Masque genere ({source}): {ratio:.1f}% zone couverte (total masques en memoire: {len(state.brush_masks)})")

        return jsonify({
            'success': True,
            'mask': pil_to_base64(result),
            'coverage': ratio
        })

    except Exception as e:
        print(f"[X-RAY] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@generation_bp.route('/expand', methods=['POST'])
def expand():
    """Expand/Outpainting - agrandit l'image avec generation"""
    import time

    state = _get_state()
    generation_pipeline = _get_generation_pipeline()
    base64_to_pil = _base64_to_pil
    pil_to_base64 = _pil_to_base64

    from core.api_helpers import error_response, validation_error, image_response
    from core.processing import expand_image

    try:
        data = request.json
        image_b64 = data.get('image')
        ratio = data.get('ratio', 1.5)
        prompt = data.get('prompt', '')
        model = data.get('model', 'epiCRealism XL (Moyen)')
        chat_model = data.get('chat_model', 'qwen3.5:2b')

        if not image_b64:
            return validation_error('Image requise')

        # ===== LOG: Debut =====
        print(f"\n{'---'*17}")
        print(f"EXPAND | Outpainting | {model}")
        print(f"{'---'*17}")
        if prompt:
            print(f"   Prompt: \"{prompt}\"")
        print(f"{'---'*17}")

        start_time = time.time()
        generation_id = str(uuid.uuid4())

        with generation_pipeline('expand', generation_id, model_name=model) as mgr:
            img = base64_to_pil(image_b64)
            pipe = mgr.get_pipeline('expand')
            result, status = expand_image(img, ratio=ratio, prompt=prompt, model_name=model, pipe=pipe)

            generation_time = time.time() - start_time

            if result:
                state.modified_image = result

                print(f"[EXPAND] Termine en {generation_time:.1f}s")
                print(f"{'='*50}\n")

                return image_response(pil_to_base64(result), status=status, generation_time=generation_time)
            else:
                print(f"[EXPAND] Erreur: {status}")
                return error_response(status)

    except Exception as e:
        print(f"[EXPAND] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return error_response(str(e))
