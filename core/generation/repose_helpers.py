"""Prompt and mask helpers for person repositioning workflows."""

from __future__ import annotations

import re
import unicodedata

from PIL import Image, ImageFilter


def normalize_repose_text(text):
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text.lower()).strip()


def last_phrase_position(text, phrases):
    last = -1
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text):
            last = max(last, match.start())
    return last


def has_any_phrase(text, phrases):
    return any(phrase in text for phrase in phrases)


def dedupe_phrases(values):
    seen = set()
    out = []
    for value in values:
        cleaned = (value or '').strip().strip(', ')
        key = cleaned.lower()
        if cleaned and key not in seen:
            out.append(cleaned)
            seen.add(key)
    return out


def join_prompt_parts(parts, max_chars=240):
    joined = []
    total = 0
    for part in dedupe_phrases(parts):
        candidate_len = len(part) if not joined else total + 2 + len(part)
        if joined and candidate_len > max_chars:
            continue
        if not joined and len(part) > max_chars:
            joined.append(part[:max_chars].rstrip(', '))
            break
        joined.append(part)
        total = candidate_len
    return ', '.join(joined)


def compact_repose_appearance(florence_desc):
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

    compact = ', '.join(dedupe_phrases(parts))
    return compact[:100].rstrip(', ')


def compact_repose_user_hint(user_prompt):
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


def extract_mask_bbox(person_mask):
    import numpy as np

    mask_np = np.array(person_mask.convert('L'))
    coords = np.where(mask_np > 127)
    if len(coords[0]) == 0:
        return None
    y_min, y_max = int(coords[0].min()), int(coords[0].max())
    x_min, x_max = int(coords[1].min()), int(coords[1].max())
    return x_min, y_min, x_max, y_max


def compute_repose_target_geometry(person_mask, image_size, prompt):
    bbox = extract_mask_bbox(person_mask)
    directives = parse_repose_directives(prompt)
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


def parse_repose_directives(prompt):
    from core.ai.edit_directives import build_repose_directives

    return build_repose_directives(prompt, image_present=True, has_brush_mask=False)


def build_repose_target_mask(person_mask, image_size, prompt):
    import numpy as np

    geometry, directives = compute_repose_target_geometry(person_mask, image_size, prompt)
    if geometry is None:
        return person_mask, directives

    img_w, img_h = image_size
    x1, y1, x2, y2 = geometry['mask_bbox']
    expanded = np.zeros((img_h, img_w), dtype=np.uint8)
    expanded[y1:y2, x1:x2] = 255
    return Image.fromarray(expanded, mode='L'), directives


def build_relocated_person_base(original_img, clean_bg, person_mask, prompt, refine_mask_source=None):
    import numpy as np

    geometry, directives = compute_repose_target_geometry(person_mask, original_img.size, prompt)
    if geometry is None:
        fallback_mask, directives = build_repose_target_mask(person_mask, original_img.size, prompt)
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


def build_repose_prompt(user_prompt, florence_desc, directives=None):
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
    user_hint = compact_repose_user_hint(directives.get('parsed_request') or user_prompt)
    appearance_hint = "" if has_clothing else compact_repose_appearance(florence_desc)
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
    return join_prompt_parts(parts, max_chars=240)


def build_repose_negative_prompt(directives=None):
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
    return ', '.join(dedupe_phrases(parts))


def background_fill_cv2(image, mask):
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
