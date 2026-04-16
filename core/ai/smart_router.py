"""
Smart Router - Cerveau intelligent pour l'édition d'images.

Un seul point d'entrée qui analyse la demande (prompt + image optionnelle)
et retourne la stratégie complète : intent, masque, strength, ControlNet, IP-Adapter.

Utilise LLaVA (vision) si image fournie, sinon Qwen (texte).
Fallback mots-clés si le LLM échoue.

Rules, traduction et fallback → voir core/router_rules.py
"""

from __future__ import annotations

import re

from core.ai.edit_directives import build_repose_directives, parse_edit_request
from core.ai.text_model_router import call_text_model, select_text_model
from core.infra.local_config import is_feature_enabled
from core.infra.packs import get_pack_prompt_assets, is_adult_runtime_available
from core.router_rules import (
    _get_seg_classes,
    keyword_fallback,
    controlnet_scale_for_intent,
    apply_nudity_postprocess,
    is_dress_body_request,
    is_pose_preservation_prompt,
    normalize_accents,
)

# ============================================================
# SYSTEM PROMPT POUR LE LLM
# ============================================================

DEFAULT_ROUTER_SYSTEM_PROMPT = """You are an internal routing component of a LOCAL image editing tool.

Analyze the user's request and the image (if provided), then choose the best strategy.

Possible intents:
- nudity: optional local-pack workflow for body reveal or sensitive body edits
- pose_change: change body pose/position
- clothing_change: change clothes (replace with different clothes)
- hair_change: modify hair
- expression_change: change facial expression (smile, ahegao, moan, etc.)
- makeup_change: apply or change makeup
- eye_change: change eye color
- accessory_change: add/change jewelry, glasses, etc.
- body_modify: modify body proportions (bigger/smaller breasts, wider hips, etc.)
- skin_change: change skin appearance (tan, freckles, wet, oiled, etc.)
- age_change: make person look younger/older
- lighting_change: change lighting or ambiance
- style_transfer: change artistic style (anime, painting, etc.)
- scene_modify: modify the entire scene
- text_edit: modify text on the image
- add_element: add an element (tattoo, piercing, object, etc.)
- background_change: change the background
- object_modify: modify a specific object
- general_edit: other edits

Mask strategies (how to mask the area):
- clothes → SegFormer clothing classes [3,4,5,6,7,10]
- hair → SegFormer hair [2]
- shoes → SegFormer shoes [8]
- hat → SegFormer hat [1]
- background → SegFormer background [0]
- person → SegFormer everything except background [1-10]
- target:OBJECT → GroundingDINO text targeting (for specific objects)
- full → 100% white mask (img2img)
- brush_only → use the brush mask only

Strength guide: 0.50-0.95 depending on change intensity
- Light edits (color, texture, makeup, eyes): 0.50-0.55
- Hair changes: 0.55-0.65
- Expression/age changes: 0.55-0.60
- Skin texture (tan, wet, oiled): 0.50-0.55
- Background changes: 0.60-0.70
- Body modifications: 0.65-0.75
- Lighting/style transfer: 0.50-0.75
- Clothing replacement: 0.75-0.85
- Nudity: 0.85-0.90
- Pose changes: 0.80-0.90

ControlNet Depth: for clothing changes, pose changes, and optional local-pack workflows (preserves body structure)
IP-Adapter: for preserving face identity during high-strength edits

CRITICAL PROMPT RULES:
- For sensitive body workflows, describe what should APPEAR instead of only describing what to remove.
- For clothing: describe the NEW clothes in detail
- Always write prompts that DESCRIBE what should APPEAR in the image, not what to remove
- Keep prompts SHORT and focused. No need for 10 synonyms.

Reply ONLY in this exact format (one field per line):
INTENT: <intent>
MASK: <strategy>
STRENGTH: <float>
CONTROLNET: <yes/no>
IPADAPTER: <yes/no>
PROMPT: <optimized prompt in English for Stable Diffusion>
NEGATIVE: <negative prompt>"""


def _get_router_system_prompt() -> str:
    pack_prompt = str(get_pack_prompt_assets().get("router_system_prompt", "") or "").strip()
    return pack_prompt or DEFAULT_ROUTER_SYSTEM_PROMPT


def _get_nudity_regex():
    keywords = get_pack_prompt_assets().get("nudity_shortcuts", [])
    if not isinstance(keywords, list):
        return None

    normalized = []
    for keyword in keywords:
        value = normalize_accents(str(keyword or "").lower().strip())
        if value:
            escaped = re.escape(value)
            if value.replace(" ", "").isalpha():
                escaped += r"\b"
            normalized.append(escaped)

    if not normalized:
        return None

    return re.compile(r"(?:^|\b)(?:" + "|".join(normalized) + r")", re.IGNORECASE)


# ============================================================
# LLM ANALYSIS
# ============================================================

def _find_text_model() -> str | None:
    """Trouve le meilleur modèle texte déjà installé pour le router."""
    choice = select_text_model("router", auto_pull=True)
    if not choice:
        return None
    print(f"[ROUTER] Text model: {choice.name} ({choice.source})")
    return choice.name


def _call_llm(prompt: str, image_b64: str = None, model: str = None, timeout: int = 90) -> str | None:
    """Appelle le LLM (vision ou texte) et retourne la réponse brute."""
    if not model:
        return None

    messages = [
        {"role": "system", "content": _get_router_system_prompt()},
    ]

    user_msg = {"role": "user", "content": prompt}
    if image_b64:
        if ',' in image_b64:
            image_b64 = image_b64.split(',')[1]
        user_msg["images"] = [image_b64]

    messages.append(user_msg)

    return call_text_model(
        messages,
        purpose="router",
        model=model,
        num_predict=200,
        temperature=0.2,
        timeout=timeout,
    )


def _parse_llm_response(response: str, original_prompt: str) -> dict | None:
    """Parse la réponse structurée du LLM."""
    if not response:
        return None

    result = {
        'intent': 'general_edit',
        'mask_strategy': 'full',
        'segformer_classes': None,
        'strength': 0.75,
        'needs_controlnet': False,
        'needs_ip_adapter': False,
        'prompt_rewrite': original_prompt,
        'negative_prompt': 'blurry, low quality, deformed, bad anatomy',
        'adjacent_classes': None,
        'reason': 'LLM analysis'
    }

    valid_intents = [
        'nudity', 'pose_change', 'clothing_change', 'hair_change',
        'expression_change', 'makeup_change', 'eye_change', 'accessory_change',
        'body_modify', 'skin_change', 'age_change', 'lighting_change', 'style_transfer',
        'scene_modify', 'text_edit', 'add_element', 'background_change',
        'object_modify', 'general_edit', 'reframe', 'repose'
    ]

    valid_masks = [
        'clothes', 'hair', 'shoes', 'hat', 'background', 'person',
        'body', 'full', 'brush_only'
    ]

    parsed_fields = 0

    for line in response.split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.upper().startswith('INTENT:'):
            value = line.split(':', 1)[1].strip().lower()
            if value in valid_intents:
                result['intent'] = value
                parsed_fields += 1

        elif line.upper().startswith('MASK:'):
            raw_value = line.split(':', 1)[1].strip().lower()
            first_token = raw_value.split()[0].rstrip('→,;:()') if raw_value else ''
            if first_token.startswith('target:') or first_token.startswith('brush+'):
                value = first_token
            elif first_token in valid_masks:
                value = first_token
            else:
                value = None
                for vm in valid_masks:
                    if vm in raw_value.split()[0:3]:
                        value = vm
                        break
                if not value:
                    value = first_token
            if value in valid_masks or value.startswith('target:') or value.startswith('brush+'):
                result['mask_strategy'] = value
                parsed_fields += 1
                seg_classes = _get_seg_classes(value)
                if seg_classes is not None:
                    result['segformer_classes'] = seg_classes

        elif line.upper().startswith('STRENGTH:'):
            raw_value = line.split(':', 1)[1].strip()
            try:
                if '-' in raw_value and not raw_value.startswith('-'):
                    parts = raw_value.split('-')
                    values = [float(p.strip()) for p in parts if p.strip()]
                    value = max(v for v in values if 0.0 <= v <= 1.0)
                else:
                    value = float(re.match(r'[\d.]+', raw_value).group())
                if 0.0 <= value <= 1.0:
                    result['strength'] = value
                    parsed_fields += 1
            except (ValueError, AttributeError):
                pass

        elif line.upper().startswith('CONTROLNET:'):
            value = line.split(':', 1)[1].strip().lower()
            result['needs_controlnet'] = value in ('yes', 'true', 'oui')
            parsed_fields += 1

        elif line.upper().startswith('IPADAPTER:'):
            value = line.split(':', 1)[1].strip().lower()
            result['needs_ip_adapter'] = value in ('yes', 'true', 'oui')
            parsed_fields += 1

        elif line.upper().startswith('PROMPT:'):
            value = line.split(':', 1)[1].strip().strip('"\'')
            if value and len(value) > 3:
                result['prompt_rewrite'] = value
                parsed_fields += 1

        elif line.upper().startswith('NEGATIVE:'):
            value = line.split(':', 1)[1].strip().strip('"\'')
            if value and len(value) > 3:
                result['negative_prompt'] = value
                parsed_fields += 1

    # Need at least 3 parsed fields to consider it valid
    if parsed_fields >= 3:
        # Post-process nudity: mask correction + prompt cleanup
        if result['intent'] == 'nudity':
            result['adjacent_classes'] = [16]
            if result['mask_strategy'] != 'brush_only' and result['mask_strategy'] != 'clothes':
                old_strategy = result['mask_strategy']
                result['mask_strategy'] = 'clothes'
                result['segformer_classes'] = None
                print(f"[ROUTER] Nudity: mask corrigé {old_strategy} → clothes (nudity = toujours masquer les vêtements)")

            prompt_lower = result['prompt_rewrite'].lower()
            explicit_words = ['nude', 'naked', 'topless']
            has_explicit = any(w in prompt_lower for w in explicit_words)
            if not has_explicit:
                result['prompt_rewrite'] = "nude body, bare skin, natural anatomy"
                print(f"[ROUTER] Nudity prompt was too vague, replaced with descriptive prompt")

        # Post-process clothing_change: force mask to 'clothes' (not 'full')
        # Full mask regenerates the entire image (face, background, etc.)
        if result['intent'] == 'clothing_change':
            if result['mask_strategy'] not in ('brush_only', 'clothes', 'shoes', 'hat'):
                old_strategy = result['mask_strategy']
                result['mask_strategy'] = 'clothes'
                result['segformer_classes'] = None
                print(f"[ROUTER] Clothing: mask corrigé {old_strategy} → clothes (clothing_change = masquer les vêtements)")

        # Post-process pose_change: force mask to 'body' (not 'person')
        # 'body' = clothes + limbs (arms, legs) WITHOUT face and hair
        # 'person' includes hair → hair gets regenerated = bad
        if result['intent'] == 'pose_change':
            if result['mask_strategy'] not in ('brush_only',):
                old_strategy = result['mask_strategy']
                result['mask_strategy'] = 'body'
                result['segformer_classes'] = None
                print(f"[ROUTER] Pose: mask corrigé {old_strategy} → body (pose = corps+membres, sans visage/cheveux)")

        # Post-process hair_change: force mask to 'hair' (not 'full')
        # Only the hair should be regenerated, not the face/body/background
        if result['intent'] == 'hair_change':
            if result['mask_strategy'] not in ('brush_only', 'hair'):
                old_strategy = result['mask_strategy']
                result['mask_strategy'] = 'hair'
                result['segformer_classes'] = None
                print(f"[ROUTER] Hair: mask corrigé {old_strategy} → hair (hair_change = masquer les cheveux uniquement)")

        # ControlNet, IP-Adapter, réalisme nudity, controlnet_scale
        apply_nudity_postprocess(result, original_prompt)

        result['reason'] = f'LLM analysis ({parsed_fields} fields parsed)'
        return result

    return None


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def _make_repose_result(prompt: str, reason: str, edit_directives: dict | None = None) -> dict:
    """Construit la stratégie 2-pass "repose" pour déplacer/regénérer une personne."""
    return {
        'intent': 'repose',
        'mask_strategy': 'person',
        'segformer_classes': None,
        'strength': 0.95,
        'needs_controlnet': True,
        'needs_ip_adapter': True,
        'ip_adapter_scale': 0.35,
        'prompt_rewrite': prompt,
        'negative_prompt': 'multiple people, duplicate person, blur, deformed, bad anatomy, extra limbs, missing limbs',
        'adjacent_classes': None,
        'controlnet_scale': 0.2,
        'edit_directives': edit_directives,
        'reason': reason,
    }

def _apply_adult_mode_guard(result: dict, prompt: str, parsed_request: dict | None = None) -> dict:
    """Bloque proprement les intents adultes si le mode adulte local est désactivé."""
    adult_enabled = is_adult_runtime_available()
    parsed_request = parsed_request or parse_edit_request(prompt, image_present=False, has_brush_mask=False)

    adult_requested = bool(
        result.get('intent') == 'nudity'
        or parsed_request.get('adult_request_detected')
    )

    result['adult_mode_enabled'] = adult_enabled
    result['adult_request_detected'] = adult_requested

    if adult_enabled or not adult_requested:
        return result

    result['blocked_by_feature'] = 'adult_mode'
    result['reason'] = f"{result.get('reason', 'router')} (adult mode disabled)"
    return result


def _prefer_keyword_route_when_llm_is_vague(llm_result: dict, prompt: str, has_brush_mask: bool = False) -> dict:
    """Let explicit router keywords correct vague LLM routes.

    Small utility LLMs sometimes return a structurally valid but destructive
    route like general_edit/full for obvious local edits ("change d'habit").
    In that case, keep the LLM's nicer prompt rewrite, but trust the keyword
    router for the mask/pipeline selection.
    """
    llm_intent = llm_result.get('intent')
    llm_mask = llm_result.get('mask_strategy')
    llm_is_vague = llm_intent == 'general_edit' or (llm_intent != 'reframe' and llm_mask == 'full')
    if not llm_is_vague:
        return llm_result

    keyword_result = keyword_fallback(prompt, has_brush_mask)
    if keyword_result.get('intent') == 'general_edit':
        return llm_result

    corrected = dict(keyword_result)
    llm_prompt = str(llm_result.get('prompt_rewrite') or '').strip()
    if llm_prompt and normalize_accents(llm_prompt.lower()) != normalize_accents(prompt.lower()):
        corrected['prompt_rewrite'] = llm_prompt

    corrected['reason'] = (
        f"{llm_result.get('reason', 'LLM analysis')} "
        f"+ keyword route override: {keyword_result.get('intent')}"
    )
    print(
        "[ROUTER] LLM route corrigée par mots-clés: "
        f"{llm_intent}/{llm_mask} → {corrected.get('intent')}/{corrected.get('mask_strategy')}"
    )
    return corrected


def _correct_pose_preservation_route(llm_result: dict, prompt: str, has_brush_mask: bool = False) -> dict:
    """Prevent "keep original pose" from becoming a pose/repose edit."""
    if not is_pose_preservation_prompt(prompt):
        return llm_result
    if llm_result.get('intent') not in ('pose_change', 'repose'):
        return llm_result

    keyword_result = keyword_fallback(prompt, has_brush_mask)
    if keyword_result.get('intent') not in ('pose_change', 'general_edit'):
        keyword_result['reason'] = (
            f"{llm_result.get('reason', 'LLM analysis')} "
            f"+ pose preservation guard → {keyword_result.get('intent')}"
        )
        print(
            "[ROUTER] Pose preservation corrected route: "
            f"{llm_result.get('intent')} → {keyword_result.get('intent')}"
        )
        return keyword_result

    corrected = dict(llm_result)
    corrected['intent'] = 'general_edit'
    corrected['mask_strategy'] = 'brush_only' if has_brush_mask else 'full'
    corrected['segformer_classes'] = None
    corrected['needs_controlnet'] = False
    corrected['needs_ip_adapter'] = False
    corrected['controlnet_scale'] = 0.0
    corrected['strength'] = min(float(corrected.get('strength', 0.65) or 0.65), 0.65)
    corrected['reason'] = f"{llm_result.get('reason', 'LLM analysis')} + pose preservation guard"
    print("[ROUTER] Pose preservation downgraded pose route → general_edit/full")
    return corrected


def analyze_request(prompt: str, image_b64: str = None, has_brush_mask: bool = False) -> dict:
    """
    Cerveau unique. Analyse le prompt (et l'image si fournie) pour déterminer
    la stratégie complète de génération.

    Uses LLaVA (vision) if image provided, otherwise Qwen (text).
    Falls back to keyword matching if LLM fails.
    """
    from core.log_utils import header, row, row_full, row2, footer, sep, text

    header("SMART ROUTER")
    row_full("Prompt", prompt)
    row2("Image", "yes" if image_b64 else "no", "Brush", "yes" if has_brush_mask else "no")

    edit_request = parse_edit_request(
        prompt,
        image_present=bool(image_b64),
        has_brush_mask=has_brush_mask,
    )

    # Fast keyword: "repose:" prefix → 2-pass pipeline (remove person + regenerate), skip LLM
    if prompt.strip().lower().startswith('repose:'):
        _repose_prompt = prompt.strip()[7:].strip()
        row("LLM", "skipped (repose: keyword)")
        result = _make_repose_result(
            _repose_prompt if _repose_prompt else prompt,
            'repose: keyword → 2-pass remove+regenerate',
            edit_directives=build_repose_directives(
                _repose_prompt if _repose_prompt else prompt,
                image_present=bool(image_b64),
                has_brush_mask=has_brush_mask,
                parsed_request=edit_request,
            ),
        )
        result = _apply_adult_mode_guard(result, prompt, edit_request)
        sep()
        row("Intent", result['intent'])
        row("Mask", result['mask_strategy'])
        row("Strength", result['strength'])
        row2("CtrlNet", f"depth (scale=0.2)", "IPAdapter", "yes")
        row_full("Prompt", result['prompt_rewrite'])
        row_full("Negative", result['negative_prompt'])
        footer()
        return result

    # Fast keyword: "pose:" prefix → OpenPose ControlNet pipeline, skip LLM
    if prompt.strip().lower().startswith('pose:'):
        _pose_prompt = prompt.strip()[5:].strip()
        if image_b64 and not has_brush_mask:
            row("LLM", "skipped (pose: keyword → repose)")
            result = _make_repose_result(
                _pose_prompt if _pose_prompt else prompt,
                'pose: keyword + image → repose 2-pass',
                edit_directives=build_repose_directives(
                    _pose_prompt if _pose_prompt else prompt,
                    image_present=True,
                    has_brush_mask=False,
                    parsed_request=edit_request,
                ),
            )
            result = _apply_adult_mode_guard(result, prompt, edit_request)
            sep()
            row("Intent", result['intent'])
            row("Mask", result['mask_strategy'])
            row("Strength", result['strength'])
            row2("CtrlNet", f"depth (scale=0.2)", "IPAdapter", "yes")
            row_full("Prompt", result['prompt_rewrite'])
            row_full("Negative", result['negative_prompt'])
            footer()
            return result

        row("LLM", "skipped (pose: keyword)")
        from core.router_rules import POSE_NEGATIVE
        from core.models.gpu_profile import get_config as _gpc
        _pose_cfg = _gpc('pose_controlnet')
        _pose_scale = _pose_cfg.get('scale', 0.4)
        _pose_strength = _pose_cfg.get('strength', 0.75)
        result = {
            'intent': 'pose_change',
            'mask_strategy': 'body',
            'segformer_classes': None,
            'strength': _pose_strength,
            'needs_controlnet': True,
            'controlnet_type': 'openpose',
            'needs_ip_adapter': False,
            'prompt_rewrite': _pose_prompt if _pose_prompt else prompt,
            'negative_prompt': POSE_NEGATIVE,
            'adjacent_classes': None,
            'controlnet_scale': _pose_scale,
            'reason': 'pose: keyword → OpenPose ControlNet'
        }
        sep()
        row("Intent", result['intent'])
        row("Mask", result['mask_strategy'])
        row("Strength", result['strength'])
        row("CtrlNet", f"openpose (scale={_pose_scale})")
        row_full("Prompt", result['prompt_rewrite'])
        row_full("Negative", result['negative_prompt'])
        footer()
        return result

    # Fast regex shortcut: prompt starts with explicit local-pack nudity words → skip LLM
    # This must run before the repose heuristic: the tiny directive normalizer can
    # hallucinate pose/size flags for short prompts such as "completely nude".
    nudity_regex = _get_nudity_regex()
    if nudity_regex and nudity_regex.search(normalize_accents(prompt.lower())):
        row("LLM", "skipped (nudity regex)")
        result = {
            'intent': 'nudity',
            'mask_strategy': 'brush_only' if has_brush_mask else 'clothes',
            'segformer_classes': None,
            'strength': 0.85,
            'needs_controlnet': not has_brush_mask,
            'needs_ip_adapter': False,
            'prompt_rewrite': prompt,
            'negative_prompt': 'blurry, low quality, deformed, bad anatomy',
            'adjacent_classes': [16],
            'reason': 'nudity regex shortcut'
        }
        apply_nudity_postprocess(result, prompt)
        result = _apply_adult_mode_guard(result, prompt, edit_request)
        sep()
        row("Intent", result['intent'])
        row("Mask", result['mask_strategy'])
        row("Strength", result['strength'])
        row2("CtrlNet", "yes" if result['needs_controlnet'] else "no",
             "IPAdapter", "yes" if result['needs_ip_adapter'] else "no")
        row_full("Prompt", result['prompt_rewrite'])
        row_full("Negative", result['negative_prompt'])
        footer()
        return result

    # Heuristic: with an input image, "move/repose the person" works better via 2-pass
    if edit_request.get('should_repose'):
        row("LLM", "skipped (natural repose heuristic)")
        result = _make_repose_result(
            prompt,
            'normalized pose/spatial edit with image → repose 2-pass',
            edit_directives=build_repose_directives(
                prompt,
                image_present=bool(image_b64),
                has_brush_mask=has_brush_mask,
                parsed_request=edit_request,
            ),
        )
        result = _apply_adult_mode_guard(result, prompt, edit_request)
        sep()
        row("Intent", result['intent'])
        row("Mask", result['mask_strategy'])
        row("Strength", result['strength'])
        row2("CtrlNet", f"depth (scale=0.2)", "IPAdapter", "yes")
        row_full("Prompt", result['prompt_rewrite'])
        row_full("Negative", result['negative_prompt'])
        footer()
        return result

    # LLM routing (primary — understands context, not just keywords)
    model = _find_text_model()

    if model:
        row("LLM", f"{model} (text)")
    else:
        row("LLM", "none available")

    llm_result = None
    if model:
        user_prompt = f"User request: \"{prompt}\""
        if has_brush_mask:
            user_prompt += "\nNote: The user has drawn a brush mask on a specific area."

        raw_response = _call_llm(user_prompt, None, model)

        if raw_response:
            llm_result = _parse_llm_response(raw_response, prompt)

    if llm_result:
        llm_result = _correct_pose_preservation_route(llm_result, prompt, has_brush_mask)
        llm_result = _prefer_keyword_route_when_llm_is_vague(llm_result, prompt, has_brush_mask)

        if has_brush_mask:
            strategy = llm_result['mask_strategy']
            if strategy not in ('brush_only', 'full'):
                llm_result['mask_strategy'] = 'brush_only'
                llm_result['segformer_classes'] = None
                llm_result['needs_ip_adapter'] = False
                llm_result['reason'] += ' (brush manuel → skip auto-segmentation)'

        if (
            not has_brush_mask
            and llm_result.get('intent') == 'clothing_change'
            and is_dress_body_request(prompt)
        ):
            llm_result['mask_strategy'] = 'body'
            llm_result['segformer_classes'] = None
            llm_result['needs_ip_adapter'] = False
            llm_result['reason'] += ' (habiller personne → masque body)'

        if image_b64 and not has_brush_mask and llm_result['intent'] in ('pose_change', 'repose'):
            llm_result = _make_repose_result(
                llm_result.get('prompt_rewrite') or prompt,
                f"{llm_result['intent']} + image → repose 2-pass",
                edit_directives=build_repose_directives(
                    llm_result.get('prompt_rewrite') or prompt,
                    image_present=True,
                    has_brush_mask=False,
                    parsed_request=edit_request,
                ),
            )

        llm_result = _apply_adult_mode_guard(llm_result, prompt, edit_request)

        sep()
        classes_str = str(llm_result.get('segformer_classes', '')) if llm_result.get('segformer_classes') else ''
        mask_display = llm_result['mask_strategy']
        if classes_str:
            mask_display += f" {classes_str}"
        row("Intent", llm_result['intent'])
        row("Mask", mask_display)
        row("Strength", llm_result['strength'])
        row2("CtrlNet", "yes" if llm_result['needs_controlnet'] else "no",
             "IPAdapter", "yes" if llm_result['needs_ip_adapter'] else "no")
        row_full("Prompt", llm_result['prompt_rewrite'])
        row_full("Negative", llm_result['negative_prompt'])
        footer()
        return llm_result

    # Fallback to keywords
    sep()
    text("LLM failed -> keyword fallback")
    fallback = keyword_fallback(prompt, has_brush_mask)
    if image_b64 and not has_brush_mask and fallback['intent'] == 'pose_change':
        fallback = _make_repose_result(
            fallback.get('prompt_rewrite') or prompt,
            'keyword pose_change + image → repose 2-pass',
            edit_directives=build_repose_directives(
                fallback.get('prompt_rewrite') or prompt,
                image_present=True,
                has_brush_mask=False,
                parsed_request=edit_request,
            ),
        )
    fallback = _apply_adult_mode_guard(fallback, prompt, edit_request)
    row("Intent", fallback['intent'])
    row("Mask", fallback['mask_strategy'])
    row("Strength", fallback['strength'])
    footer()
    return fallback
