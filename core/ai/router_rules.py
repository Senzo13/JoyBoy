"""
Router Rules — Règles de routage par mots-clés, traduction FR→EN, fallback.

Fichier séparé pour garder smart_router.py propre.
Charge les méthodes depuis router_methods.json (externalisé).

Contient :
- _load_methods_json() : charge et parse router_methods.json
- KEYWORD_RULES : règles de matching (chargées depuis JSON)
- normalize_accents() : normalisation des accents FR pour matching flexible
- translate_pose() : traduction FR → EN des prompts de pose/interaction
- controlnet_scale_for_intent() : scale ControlNet adapté par intent
- ip_adapter_scale_for_intent() : scale IP-Adapter adapté par méthode JSON
- apply_nudity_postprocess() : post-traitement nudity/clothing/pose
- keyword_fallback() : fallback complet quand le LLM échoue
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
import re
import unicodedata

from core.infra.packs import get_pack_router_rules, is_adult_runtime_available

# ============================================================
# LOAD JSON CONFIG
# ============================================================

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts")
_METHODS_JSON_PATH = os.path.join(_PROMPTS_DIR, "router_methods.json")
_BEHAVIORS_JSON_PATH = os.path.join(_PROMPTS_DIR, "model_behaviors.json")
_DRESS_BODY_KEYWORDS = (
    "dress the person",
    "dress person",
    "dress her",
    "dress him",
    "add clothes",
    "put clothes",
    "fully dressed",
    "cover torso",
    "cover hips",
    "habille",
    "habiller",
    "habille la personne",
    "habille le personnage",
    "mets lui une tenue",
    "mettre une tenue",
    "ajoute une tenue",
    "ajouter une tenue",
    "vetir",
    "vêtir",
    "vestir",
    "vestire",
)
_POSE_PRESERVATION_PHRASES = (
    "keep original pose",
    "keep the original pose",
    "keep pose unchanged",
    "keep the pose unchanged",
    "same pose",
    "same body pose",
    "pose unchanged",
    "unchanged pose",
    "maintain exact pose",
    "maintaining exact pose",
    "preserve pose",
    "preserve the pose",
    "do not change pose",
    "do not change the pose",
    "don't change pose",
    "dont change pose",
    "garde la pose",
    "garder la pose",
    "conserve la pose",
    "conserver la pose",
    "meme pose",
    "même pose",
    "pose identique",
    "pose inchangee",
    "pose inchangée",
    "mantener la pose",
    "misma pose",
    "posa uguale",
    "stessa posa",
)
_POSE_CHANGE_PHRASES = (
    "change pose",
    "change the pose",
    "change her pose",
    "change his pose",
    "different pose",
    "new pose",
    "change sa pose",
    "changer sa pose",
    "change de pose",
    "changer de pose",
    "autre pose",
    "pose differente",
    "pose différente",
    "cambiar la pose",
    "cambia la pose",
    "cambiare posa",
    "altra posa",
)
_CLOTHING_PRESERVATION_PHRASES = (
    "keep clothing unchanged",
    "keep clothes unchanged",
    "keep outfit unchanged",
    "keep the clothing unchanged",
    "keep the clothes unchanged",
    "keep the outfit unchanged",
    "same clothing",
    "same clothes",
    "same outfit",
    "clothing unchanged",
    "clothes unchanged",
    "outfit unchanged",
    "keep clothing and pose unchanged",
    "garde les vetements",
    "garde les vêtements",
    "garder les vetements",
    "garder les vêtements",
    "meme tenue",
    "même tenue",
    "mismos ropa",
    "misma ropa",
    "stessi vestiti",
    "stesso outfit",
)
_CLOTHING_CHANGE_PHRASES = _DRESS_BODY_KEYWORDS + (
    "change clothes",
    "change clothing",
    "change outfit",
    "different outfit",
    "new outfit",
    "replace clothes",
    "replace clothing",
    "wearing a",
    "wearing the",
    "change ses habits",
    "change d habit",
    "change d'habit",
    "changer ses habits",
    "changer d habit",
    "changer d'habit",
    "change sa tenue",
    "changer sa tenue",
)

# Cache loaded data
_methods_data = None
_behaviors_data = None
_ADULT_PROMPT_CONSTANT_KEYS = {"nudity_negative", "nudity_realism_suffix"}


def _sanitize_core_methods_payload(data: dict) -> dict:
    payload = deepcopy(data or {})
    payload["methods"] = [
        method for method in payload.get("methods", [])
        if not bool(method.get("nsfw"))
    ]

    prompt_constants = dict(payload.get("prompt_constants", {}) or {})
    for key in _ADULT_PROMPT_CONSTANT_KEYS:
        prompt_constants.pop(key, None)
    payload["prompt_constants"] = prompt_constants

    payload["controlnet_intents"] = [
        intent for intent in payload.get("controlnet_intents", [])
        if intent != "nudity"
    ]

    controlnet_scales = dict(payload.get("controlnet_scales", {}) or {})
    controlnet_scales.pop("nudity", None)
    payload["controlnet_scales"] = controlnet_scales

    return payload


def _merge_router_payload(base: dict, override: dict) -> dict:
    merged = deepcopy(base or {})
    if not isinstance(override, dict) or not override:
        return merged

    if isinstance(override.get("prompt_constants"), dict):
        merged.setdefault("prompt_constants", {}).update(override["prompt_constants"])

    if isinstance(override.get("controlnet_scales"), dict):
        merged.setdefault("controlnet_scales", {}).update(override["controlnet_scales"])

    merged_methods = list(merged.get("methods", []) or [])
    override_methods = override.get("methods", [])
    if isinstance(override_methods, list):
        merged_methods.extend(method for method in override_methods if isinstance(method, dict))
    merged["methods"] = merged_methods

    merged.setdefault("controlnet_intents", [])
    for intent in override.get("controlnet_intents", []) or []:
        if intent not in merged["controlnet_intents"]:
            merged["controlnet_intents"].append(intent)

    merged.setdefault("physical_attributes", [])
    for attr in override.get("physical_attributes", []) or []:
        if attr not in merged["physical_attributes"]:
            merged["physical_attributes"].append(attr)

    if "nsfw_enabled" in override:
        merged["nsfw_enabled"] = bool(override.get("nsfw_enabled"))

    return merged


def _load_methods_json():
    """Charge router_methods.json et retourne les données."""
    global _methods_data
    if _methods_data is not None:
        return _methods_data
    try:
        with open(_METHODS_JSON_PATH, 'r', encoding='utf-8') as f:
            base_data = json.load(f)
        core_data = _sanitize_core_methods_payload(base_data)
        pack_overrides = get_pack_router_rules()
        _methods_data = _merge_router_payload(core_data, pack_overrides)
        print(f"[ROUTER] Loaded {len(_methods_data['methods'])} methods from router_methods.json")
    except Exception as e:
        print(f"[ROUTER] ERREUR chargement router_methods.json: {e}")
        _methods_data = {"methods": [], "prompt_constants": {}, "controlnet_scales": {}, "physical_attributes": []}
    return _methods_data


def load_model_behaviors():
    """Charge model_behaviors.json et retourne les données."""
    global _behaviors_data
    if _behaviors_data is not None:
        return _behaviors_data
    try:
        with open(_BEHAVIORS_JSON_PATH, 'r', encoding='utf-8') as f:
            _behaviors_data = json.load(f)
        families = list(_behaviors_data.get('model_families', {}).keys())
        print(f"[ROUTER] Loaded {len(families)} model families: {', '.join(families)}")
    except Exception as e:
        print(f"[ROUTER] ERREUR chargement model_behaviors.json: {e}")
        _behaviors_data = {"model_families": {}}
    return _behaviors_data


def get_model_behavior(model_name: str) -> dict | None:
    """Retourne le comportement pipeline pour un modèle donné.

    Matche model_name contre les patterns de chaque famille.
    Retourne None si aucun match (= comportement par défaut SDXL).
    """
    data = load_model_behaviors()
    if not model_name:
        return data['model_families'].get('sdxl')

    for family_id, family in data.get('model_families', {}).items():
        for pattern in family.get('match_patterns', []):
            if pattern.lower() in model_name.lower():
                return family

    # Default: SDXL behavior
    return data['model_families'].get('sdxl')


# ============================================================
# PROMPT CONSTANTS — chargées depuis JSON, avec fallback hardcodé
# ============================================================

_data = _load_methods_json()
_constants = _data.get('prompt_constants', {})

DEFAULT_NEGATIVE = _constants.get('default_negative', "blurry, low quality, deformed, bad anatomy")
POSE_NEGATIVE = _constants.get('pose_negative', f"{DEFAULT_NEGATIVE}, extra limbs, missing limbs, missing hands, missing fingers")
NUDITY_NEGATIVE = _constants.get('nudity_negative', "clothing, clothes, fabric, dressed, seams, stitching, cloth texture, clothing traces, tan lines from clothes, wrinkles from fabric, blurry, deformed")
NUDITY_REALISM_SUFFIX = _constants.get('nudity_realism_suffix', ", natural breasts with slight sag, realistic body")

# Map de noms de negative → valeur réelle (pour résolution des refs JSON)
_NEGATIVE_MAP = {
    'default_negative': DEFAULT_NEGATIVE,
    'pose_negative': POSE_NEGATIVE,
    'nudity_negative': NUDITY_NEGATIVE,
    'style_negative': _constants.get('style_negative', DEFAULT_NEGATIVE),
}

# Intents qui forcent ControlNet Depth — depuis JSON
CONTROLNET_INTENTS = tuple(_data.get('controlnet_intents', ['nudity', 'clothing_change', 'pose_change']))

# Scales ControlNet par intent — depuis JSON
_CN_SCALES = _data.get('controlnet_scales', {})

# Attributs physiques à préserver — depuis JSON
_PHYSICAL_ATTRS = _data.get('physical_attributes', [])


# ============================================================
# KEYWORD RULES — construites depuis JSON methods
# ============================================================

def _iter_keyword_methods(data: dict | None = None) -> list[dict]:
    """Return valid keyword-route methods from core + optional packs."""
    data = data or _load_methods_json()
    nsfw_enabled = data.get('nsfw_enabled', True) and is_adult_runtime_available()
    methods = []
    for method in data.get('methods', []) or []:
        if not isinstance(method, dict):
            continue
        if not nsfw_enabled and method.get('nsfw', False):
            continue
        keywords = method.get('keywords')
        if not isinstance(keywords, list) or not keywords:
            continue
        if not method.get('intent') or not method.get('mask_strategy'):
            continue
        methods.append(method)
    return methods


def _build_keyword_rules():
    """Convertit les methods JSON en tuples KEYWORD_RULES (backward compat)."""
    data = _load_methods_json()
    rules = []
    for method in _iter_keyword_methods(data):
        rules.append((
            method['keywords'],
            method['intent'],
            method['mask_strategy'],
            method.get('segformer_classes'),
            method.get('strength', 0.75),
            method.get('controlnet', False),
            method.get('ip_adapter', False),
        ))
    return rules


KEYWORD_RULES = _build_keyword_rules()


# ============================================================
# SEGFORTER CLASSES - dynamique selon le variant actif
# ============================================================

def _get_seg_classes(strategy):
    """Récupère les classes pour une stratégie depuis le variant actif."""
    try:
        from core.segmentation import get_classes_for_strategy
        return get_classes_for_strategy(strategy)
    except Exception:
        return None


# ============================================================
# ACCENTS & TRANSLATION
# ============================================================

def normalize_accents(text: str) -> str:
    """Normalise les accents français pour un matching plus flexible.

    "baissé" → "baisse", "penchée" → "penchee", etc.
    """
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.category(c).startswith('M'))


def is_dress_body_request(prompt: str) -> bool:
    """Detect requests that add clothing to the person/body itself.

    Replacing visible clothes should keep the clothes mask. Dressing an
    unclothed or barely clothed person needs a body/person mask, otherwise the
    clothes segment can be empty and the edit silently does nothing.
    """
    prompt_lower = str(prompt or "").lower()
    prompt_norm = normalize_accents(prompt_lower)
    return any(
        keyword in prompt_lower or normalize_accents(keyword) in prompt_norm
        for keyword in _DRESS_BODY_KEYWORDS
    )


def is_pose_preservation_prompt(prompt: str) -> bool:
    """Detect "keep same pose" guardrails that must not route to pose_change."""
    prompt_lower = str(prompt or "").lower()
    prompt_norm = normalize_accents(prompt_lower)
    has_preserve = any(normalize_accents(phrase) in prompt_norm for phrase in _POSE_PRESERVATION_PHRASES)
    has_change = any(normalize_accents(phrase) in prompt_norm for phrase in _POSE_CHANGE_PHRASES)
    return bool(has_preserve and not has_change)


def is_clothing_preservation_prompt(prompt: str) -> bool:
    """Detect clothing words used only as "keep clothing unchanged" guardrails."""
    prompt_lower = str(prompt or "").lower()
    prompt_norm = normalize_accents(prompt_lower)
    has_preserve = any(normalize_accents(phrase) in prompt_norm for phrase in _CLOTHING_PRESERVATION_PHRASES)
    has_change = any(normalize_accents(phrase) in prompt_norm for phrase in _CLOTHING_CHANGE_PHRASES)
    return bool(has_preserve and not has_change)


def translate_pose(prompt: str) -> str:
    """Traduction FR → EN pour Stable Diffusion.

    Approche: strip les préfixes FR, puis matcher le cœur de la phrase
    contre un dictionnaire. Retourne une phrase EN complète.
    """
    text = prompt.lower().strip()
    text = normalize_accents(text)

    # 1. Strip les préfixes courants pour isoler l'action
    prefixes = [
        'je veux qu\'elle ', 'je veux qu\'il ', 'je veux quelle ', 'je veux quil ',
        'fais en sorte qu\'elle ', 'fais en sorte quelle ', 'fait en sorte qu\'elle ',
        'elle devrait ', 'il devrait ',
        'elle doit ', 'il doit ',
        'elle va ', 'il va ',
        'fais la ', 'fais le ',
        'elle ', 'il ',
    ]
    core = text
    for p in prefixes:
        p_norm = normalize_accents(p)
        if core.startswith(p_norm):
            core = core[len(p_norm):]
            break

    # 2. Strip le "se" / "s'" réflexif
    if core.startswith('se '):
        core = core[3:]
    elif core.startswith('s\'') or core.startswith('s '):
        core = core[2:]

    core = core.strip()

    # 3. Dictionnaire: phrase FR (sans préfixe/réflexif) → action EN
    # Ordre: plus spécifique en premier
    actions = [
        # Bras
        ('lever les bras', 'raising both arms up'),
        ('leve les bras', 'raising both arms up'),
        ('lever le bras', 'raising one arm up'),
        ('leve le bras', 'raising one arm up'),
        ('baisser les bras', 'lowering both arms down'),
        ('baisse les bras', 'lowering both arms down'),
        ('bras en l\'air', 'arms raised up'),
        ('bras leve', 'arms raised up'),
        ('bras baisse', 'arms lowered down'),
        # Tête
        ('tourner la tete', 'turning her head to the side'),
        ('tourne la tete', 'turning her head to the side'),
        # Jambes
        ('ecarter les jambes', 'spreading her legs apart'),
        ('ecarte les jambes', 'spreading her legs apart'),
        ('ecarter les cuisses', 'spreading her thighs apart'),
        ('ecarte les cuisses', 'spreading her thighs apart'),
        ('ouvrir les jambes', 'opening her legs wide'),
        ('ouvre les jambes', 'opening her legs wide'),
        # Seins / poitrine
        ('pincer le teton', 'pinching her own nipple with her fingers'),
        ('pince le teton', 'pinching her own nipple with her fingers'),
        ('pincer les tetons', 'pinching her own nipples with her fingers'),
        ('pince les tetons', 'pinching her own nipples with her fingers'),
        ('toucher les seins', 'touching her own breasts with her hands'),
        ('touche les seins', 'touching her own breasts with her hands'),
        ('toucher ses seins', 'touching her own breasts with her hands'),
        ('touche ses seins', 'touching her own breasts with her hands'),
        ('toucher sa poitrine', 'touching her own chest with her hands'),
        ('touche sa poitrine', 'touching her own chest with her hands'),
        ('toucher la poitrine', 'touching her own chest with her hands'),
        ('main sur sa poitrine', 'placing her hand on her own chest'),
        ('mains sur sa poitrine', 'placing both hands on her own chest'),
        ('main sur les seins', 'placing her hand on her breasts'),
        ('main sur le sein', 'placing her hand on her breast'),
        ('couvrir ses seins', 'covering her breasts with her hands'),
        ('couvre ses seins', 'covering her breasts with her hands'),
        # Bas du corps
        ('doigt dans le vagin', 'inserting a finger in her pussy'),
        ('mettre un doigt', 'inserting a finger'),
        ('masturber', 'masturbating with her hand between her legs'),
        ('masturbe', 'masturbating with her hand between her legs'),
        ('toucher son vagin', 'touching her pussy with her hand'),
        ('touche son vagin', 'touching her pussy with her hand'),
        ('toucher sa chatte', 'touching her pussy with her hand'),
        ('touche sa chatte', 'touching her pussy with her hand'),
        ('toucher entre', 'touching between her legs with her hand'),
        ('touche entre', 'touching between her legs with her hand'),
        ('main entre les jambes', 'placing her hand between her legs'),
        ('main entre les cuisses', 'placing her hand between her thighs'),
        # Culotte
        ('baisser sa culotte', 'pulling her panties down with one hand, panties around thighs'),
        ('baisse sa culotte', 'pulling her panties down with one hand, panties around thighs'),
        ('baisse la culotte', 'pulling her panties down with one hand, panties around thighs'),
        ('baisser la culotte', 'pulling her panties down with one hand, panties around thighs'),
        ('culotte baissee', 'with her panties pulled down around her thighs'),
        ('enlever sa culotte', 'removing her panties with her hands'),
        ('enleve sa culotte', 'removing her panties with her hands'),
        # Caresses
        ('caresser', 'caressing herself with her hand on her body'),
        ('caresse', 'caressing herself with her hand on her body'),
        ('frotter', 'rubbing herself'),
        ('frotte', 'rubbing herself'),
        ('toucher', 'touching herself with her hands'),
        ('touche', 'touching herself with her hands'),
        # Poses complètes
        ('a quatre pattes', 'getting on all fours'),
        ('quatre pattes', 'getting on all fours'),
        ('a genoux', 'kneeling down'),
        ('agenouiller', 'kneeling down'),
        ('agenouille', 'kneeling down'),
        ('allonger', 'lying down'),
        ('allongee', 'lying down'),
        ('allonge', 'lying down'),
        ('sur le dos', 'lying on her back'),
        ('de dos', 'seen from behind, back view'),
        ('retourner', 'turning around, showing her back'),
        ('retourne', 'turning around, showing her back'),
        ('pencher', 'bending forward'),
        ('penchee', 'bending forward'),
        ('penche', 'bending forward'),
        ('asseoir', 'sitting down'),
        ('assise', 'sitting down'),
        ('assis', 'sitting down'),
        ('debout', 'standing up'),
    ]

    for fr, en in actions:
        fr_norm = normalize_accents(fr)
        if fr_norm in core:
            return f"she is {en}"

    # 4. Fallback: retourner le texte nettoyé tel quel
    return f"she is {core}" if core else prompt


# ============================================================
# CONTROLNET SCALE
# ============================================================

def controlnet_scale_for_intent(intent: str) -> float:
    """Retourne le controlnet_conditioning_scale optimal par intent."""
    return _CN_SCALES.get(intent, _CN_SCALES.get('_default', 0.50))


def ip_adapter_scale_for_intent(method_id: str) -> float:
    """Retourne le ip_adapter_scale depuis la méthode JSON matchée.

    Chaque méthode peut définir son propre ip_adapter_scale optimal.
    Fallback: 0.6 (scale par défaut).
    """
    data = _load_methods_json()
    for method in data.get('methods', []):
        if method.get('id') == method_id:
            return method.get('ip_adapter_scale', 0.6)
    return 0.6


# ============================================================
# NUDITY POST-PROCESSING — réutilisé par keyword_fallback et smart_router
# ============================================================

def apply_nudity_postprocess(result: dict, original_prompt: str) -> dict:
    """
    Post-traitement commun pour les intents nudity/clothing_change/pose_change.

    - Force ControlNet pour CONTROLNET_INTENTS
    - IP-Adapter: respecte le flag JSON/LLM (pas d'override)
    - Ajoute réalisme nudity (suffix + attributs physiques préservés)
    - Set le negative prompt nudity
    - Set le controlnet_scale
    """
    intent = result['intent']

    # Forcer ControlNet Depth pour les intents qui en ont besoin
    # Sauf si brush_only : l'user a ciblé une zone précise, pas besoin de ControlNet/IP-Adapter
    # Note: needs_ip_adapter est respecté tel que défini par le JSON/LLM (pas d'override)
    is_brush = result.get('mask_strategy') == 'brush_only'
    if intent in CONTROLNET_INTENTS and not is_brush:
        result['needs_controlnet'] = True
        print(f"[ROUTER] ControlNet Depth forcé pour {intent}")
    elif is_brush and intent == 'pose_change':
        # Brush + "pose_change" = probablement une erreur du LLM, downgrade
        result['intent'] = 'general_edit'
        result['needs_controlnet'] = False
        result['needs_ip_adapter'] = False
        print(f"[ROUTER] pose_change + brush → downgrade to general_edit")

    # Nudity-specific: réalisme + negative + préservation attributs
    if intent == 'nudity':
        # Préserver les attributs physiques du prompt original
        original_lower = original_prompt.lower()
        rewrite_lower = result['prompt_rewrite'].lower()
        preserved = [attr for attr in _PHYSICAL_ATTRS
                     if attr in original_lower and attr not in rewrite_lower]
        if preserved:
            result['prompt_rewrite'] = f"{result['prompt_rewrite']}, {', '.join(preserved)}"
            print(f"[ROUTER] Attributs préservés: {', '.join(preserved)}")

        result['prompt_rewrite'] += NUDITY_REALISM_SUFFIX
        result['negative_prompt'] = NUDITY_NEGATIVE
        print(f"[ROUTER] Réalisme nudity ajouté (natural sag)")

    # Clothing change: réalisme peau visible + préservation attributs
    if intent == 'clothing_change':
        original_lower = original_prompt.lower()
        rewrite_lower = result['prompt_rewrite'].lower()
        preserved = [attr for attr in _PHYSICAL_ATTRS
                     if attr in original_lower and attr not in rewrite_lower]
        if preserved:
            result['prompt_rewrite'] = f"{result['prompt_rewrite']}, {', '.join(preserved)}"
            print(f"[ROUTER] Attributs préservés: {', '.join(preserved)}")
        result['prompt_rewrite'] += NUDITY_REALISM_SUFFIX
        result['negative_prompt'] = NUDITY_NEGATIVE
        print(f"[ROUTER] Réalisme clothing_change ajouté")

    result['controlnet_scale'] = controlnet_scale_for_intent(intent)
    return result


# ============================================================
# KEYWORD FALLBACK
# ============================================================

def _resolve_negative(ref: str | None) -> str:
    """Résout une référence negative_prompt (nom → valeur)."""
    if not ref:
        return DEFAULT_NEGATIVE
    return _NEGATIVE_MAP.get(ref, ref)


def keyword_fallback(prompt: str, has_brush_mask: bool = False) -> dict:
    """
    Fallback par mots-clés quand le LLM échoue.
    Retourne la stratégie basée sur les mots-clés détectés dans le prompt.
    """
    prompt_lower = prompt.lower().strip()
    # Version sans accents pour matching flexible (baissé = baisse = baissee)
    prompt_normalized = normalize_accents(prompt_lower)

    # Charger les méthodes JSON pour accéder aux champs étendus (prompt_template, etc.)
    data = _load_methods_json()
    methods = _iter_keyword_methods(data)

    # Vérifier chaque règle dans l'ordre (la première qui matche gagne)
    # Word boundary au début (\b) empêche de matcher au milieu d'un mot
    # (ex: "position" ne matche plus "composition")
    for method in methods:
        keywords = method.get('keywords', [])
        intent = method.get('intent')
        mask_strategy = method.get('mask_strategy')
        classes = method.get('segformer_classes')
        strength = method.get('strength', 0.75)
        controlnet = method.get('controlnet', False)
        ipadapter = method.get('ip_adapter', False)
        matched_kw = None
        for kw in keywords:
            kw_lower = kw.lower()
            kw_norm = normalize_accents(kw_lower)
            pattern = r'\b' + re.escape(kw_lower)
            pattern_norm = r'\b' + re.escape(kw_norm)
            if re.search(pattern, prompt_lower) or re.search(pattern_norm, prompt_normalized):
                matched_kw = kw
                break
        if matched_kw:
            if (
                intent == 'pose_change'
                and method.get('id') == 'pose_full'
                and is_pose_preservation_prompt(prompt)
            ):
                print(f"[KEYWORD] Ignored pose preservation phrase for '{matched_kw}'")
                continue
            if intent == 'clothing_change' and is_clothing_preservation_prompt(prompt):
                print(f"[KEYWORD] Ignored clothing preservation phrase for '{matched_kw}'")
                continue
            print(f"[KEYWORD] Matched '{matched_kw}' → {intent}")
            # Si brush mask fourni, utiliser JUSTE le brush
            if has_brush_mask and mask_strategy not in ('full', 'brush_only'):
                mask_strategy = 'brush_only'
                ipadapter = False

            prompt_template = method.get('prompt_template')
            neg_ref = method.get('negative_prompt')

            # Prompt et negative par défaut selon l'intent
            if intent == 'nudity':
                template = prompt_template or "bare skin, natural anatomy"
                # Garder le prompt user + ajouter le template en suffixe
                rewrite = f"{prompt}, {template}"
                neg = NUDITY_NEGATIVE
            elif intent == 'clothing_change':
                if is_dress_body_request(prompt):
                    mask_strategy = 'body'
                    classes = None
                    ipadapter = False
                template = prompt_template or "detailed fabric texture, realistic skin"
                # Garder le prompt user (description de la tenue) + template qualité
                rewrite = f"{prompt}, {template}"
                neg = _resolve_negative(neg_ref)
            elif intent == 'pose_change':
                rewrite = translate_pose(prompt)
                rewrite += ", detailed hands with five fingers, same framing as original image, do not crop, do not zoom"
                neg = POSE_NEGATIVE
            else:
                rewrite = prompt_template or prompt
                neg = _resolve_negative(neg_ref)

            cn_scale = controlnet_scale_for_intent(intent)
            adjacent = method.get('adjacent_classes')
            ipa_scale = method.get('ip_adapter_scale', 0.6)

            return {
                'intent': intent,
                'mask_strategy': mask_strategy,
                'segformer_classes': classes,
                'strength': strength,
                'needs_controlnet': controlnet,
                'controlnet_scale': cn_scale,
                'needs_ip_adapter': ipadapter,
                'ip_adapter_scale': ipa_scale,
                'prompt_rewrite': rewrite,
                'negative_prompt': neg,
                'adjacent_classes': adjacent,
                'reason': f'Keyword fallback: {intent}'
            }

    # Défaut si rien ne matche
    mask = 'brush_only' if has_brush_mask else 'full'
    return {
        'intent': 'general_edit',
        'mask_strategy': mask,
        'segformer_classes': None,
        'strength': 0.75,
        'needs_controlnet': has_brush_mask,
        'needs_ip_adapter': False,
        'prompt_rewrite': prompt,
        'negative_prompt': DEFAULT_NEGATIVE,
        'reason': f'Default: {mask} (no keyword match)'
    }
