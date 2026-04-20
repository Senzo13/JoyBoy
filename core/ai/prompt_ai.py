"""
Prompt AI - Prompt enhancement and image prompt generation.

Extracted from utility_ai.py for separation of concerns.

Contains:
- enhance_prompt() - Improve prompts for image generation
- build_full_prompt() - Build final prompt with style/quality tags
- extract_image_prompt() / generate_image_prompt() - Extract image prompts from user messages
- translate_to_english() - Translate prompts to English
- French preprocessing helpers (_preprocess_french_prompt, _is_mostly_english, etc.)
"""

from __future__ import annotations

import re

from core.utility_ai import _call_utility, _load_enhance_prompt


def translate_to_english(prompt: str, model: str = None) -> str:
    """
    Traduit le prompt en anglais si necessaire (pour Flux Kontext).
    Si deja en anglais, retourne tel quel.
    """
    if not prompt:
        return prompt

    french_words = ['le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'et', 'ou',
                    'elle', 'il', 'qui', 'que', 'pour', 'avec', 'sur', 'dans',
                    'est', 'sont', 'fait', 'faire', 'met', 'enleve', 'retire',
                    'nu', 'nue', 'bras', 'jambe', 'corps', 'tete', 'cheveux']

    prompt_lower = prompt.lower()
    is_french = any(f' {word} ' in f' {prompt_lower} ' for word in french_words)

    has_accents = any(c in prompt for c in 'àâäéèêëïîôùûüç')

    if not is_french and not has_accents:
        return prompt

    print(f"[TRANSLATE] Detection francais, traduction...")

    messages = [
        {
            "role": "system",
            "content": "You are a translator. Translate the user's text to English. Reply with ONLY the translation, nothing else."
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    result = _call_utility(messages, num_predict=200, temperature=0.1, timeout=15, model=model)

    if result:
        print(f"[TRANSLATE] -> {result}")
        return result
    else:
        return prompt


def _preprocess_french_prompt(text: str) -> str:
    """
    Pre-traitement regex des termes francais critiques -> anglais.
    """
    import re
    subs = [
        # ---- Poses / positions ----
        (r"allongee?\s+sur\s+le\s+dos", "lying on her back"),
        (r"allongee?\s+sur\s+le\s+ventre", "lying face down"),
        (r"couchee?\s+sur\s+le\s+dos", "lying on her back"),
        (r"couchee?\s+sur\s+le\s+ventre", "lying face down"),
        (r"(?:a|a)\s+quatre\s+pattes", "on all fours"),
        (r"(?:a|a)\s+genoux", "kneeling"),
        (r"agenouillee?", "kneeling"),
        (r"accroupie?", "squatting"),
        (r"penchee?\s+en\s+avant", "bent forward"),
        (r"cambr(?:ee?|ant)", "arching her back"),
        (r"\bdebout\b", "standing"),
        (r"\bassise?\b", "sitting"),
        (r"\bde\s+dos\b", "from behind"),
        # ---- Direction du visage (AVANT "de profil" generique) ----
        (r"(?:le\s+)?visage\s+(?:de\s+|en\s+)?profil", "face turned to the side"),
        (r"(?:la\s+)?t(?:e|e)te\s+(?:de\s+|en\s+)?profil", "face turned to the side"),
        (r"(?:le\s+)?visage\s+(?:tourn(?:e|e)\s+)?(?:de\s+)?c(?:o|o)t(?:e|e)", "face turned to the side"),
        (r"(?:le\s+)?visage\s+tourn(?:e|e)", "face turned to the side"),
        (r"(?:la\s+)?t(?:e|e)te\s+tourn(?:ee?|e)", "head turned to the side"),
        # ---- Direction du regard ----
        (r"regard(?:e|ant)?\s+(?:vers\s+)?(?:la\s+)?cam(?:e|e)ra", "looking toward the viewer"),
        (r"regard(?:e|ant)?\s+(?:vers\s+)?le\s+haut", "looking up"),
        (r"regard(?:e|ant)?\s+(?:vers\s+)?le\s+bas", "looking down"),
        (r"yeux\s+ferm(?:e|e)s", "eyes closed"),
        (r"yeux\s+mi-clos", "half-closed eyes"),
        (r"bouche\s+ouverte", "mouth open"),
        # ---- Actions ----
        (r"(?:qui\s+)?(?:se\s+)?touch(?:e|er?|ant)\s+(?:le\s+)?vagin", "touching her pussy"),
        (r"(?:qui\s+)?(?:se\s+)?touch(?:e|er?|ant)\s+(?:la\s+)?(?:chatte|vulve)", "touching her pussy"),
        (r"(?:qui\s+)?(?:se\s+)?touch(?:e|er?|ant)\s+(?:les?\s+)?seins?", "touching her breasts"),
        (r"(?:qui\s+)?(?:se\s+)?touch(?:e|er?|ant)\s+(?:le\s+)?clitoris", "touching her clit"),
        (r"(?:qui\s+)?(?:se\s+)?caress(?:e|er?|ant)", "caressing herself"),
        (r"(?:qui\s+)?(?:se\s+)?masturb(?:e|er?|ant)", "masturbating"),
        (r"(?:qui\s+)?(?:s['\s])?ecarte\s+les\s+jambes", "spreading her legs"),
        (r"(?:les?\s+)?jambes?\s+(?:e|e)cart(?:e|e)(?:e?s)?", "legs spread apart"),
        (r"(?:les?\s+)?bras\s+lev(?:e|e)s", "arms raised"),
        (r"(?:les?\s+)?jambes\s+(?:en\s+)?l['\s]air", "legs in the air"),
        (r"(?:les?\s+)?jambes\s+(?:pli(?:e|e)(?:e?s)?|repli(?:e|e)(?:e?s)?)", "legs bent"),
        (r"(?:les?\s+)?genoux\s+(?:pli(?:e|e)(?:e?s)?|repli(?:e|e)(?:e?s)?)", "knees bent"),
        # ---- Angles de vue ----
        (r"vue\s+de\s+face", "front-facing view"),
        (r"vue\s+de\s+profil", "side view"),
        (r"vue\s+de\s+dos", "rear view, from behind"),
        (r"vue\s+(?:du\s+)?dessus", "top-down view"),
        (r"vue\s+(?:du\s+)?dessous", "low angle view"),
        (r"(?:en\s+)?gros\s+plan", "close-up"),
        (r"(?:en\s+)?plan\s+large", "wide shot"),
        # ---- Corps / anatomie ----
        (r"jeune\s+femme\s+adulte", "young adult woman"),
        (r"jeune\s+femme", "young woman"),
        (r"(?:de\s+|des\s+)?gros\s+seins?", "large breasts"),
        (r"(?:de\s+|des\s+)?(?:tres\s+)?gros\s+seins?", "very large breasts"),
        (r"(?:de\s+|des\s+)?(?:petits?|petites?)\s+seins?", "small breasts"),
        (r"(?:de\s+|des\s+)?seins?\s+moyens?", "medium breasts"),
        (r"(?:de?s?\s+)?t(?:e|e)t(?:on|in)s?\s+ros(?:e|e)s?", "pink nipples"),
        (r"(?:de?s?\s+)?t(?:e|e)t(?:on|in)s?\s+(?:brun|marron|fonc(?:e|e))s?", "dark nipples"),
        (r"(?:de?s?\s+)?t(?:e|e)t(?:on|in)s?\s+(?:dur|point)s?", "erect nipples"),
        (r"grain(?:s)?\s+de\s+beaut(?:e|e)", "beauty marks"),
        (r"vagin\s+(?:bien\s+)?poilu(?:s|e)?", "hairy pussy"),
        (r"(?:pubis|minou|chatte)\s+(?:bien\s+)?poilu(?:s|e)?", "hairy pussy"),
        (r"fesses?\s+(?:ronde|rebondie)s?", "round butt"),
        (r"(?:de\s+)?(?:long(?:ue)?s?\s+)?cheveux?\s+bruns?", "long brown hair"),
        (r"(?:de\s+)?(?:long(?:ue)?s?\s+)?cheveux?\s+blonds?", "long blonde hair"),
        (r"(?:de\s+)?(?:long(?:ue)?s?\s+)?cheveux?\s+noirs?", "long black hair"),
        (r"(?:de\s+)?(?:long(?:ue)?s?\s+)?cheveux?\s+roux", "long red hair"),
        (r"(?:de\s+)?cheveux?\s+courts?", "short hair"),
        # ---- Sujets generiques (APRES les variantes specifiques) ----
        (r"\bfemme\b", "woman"),
        (r"\bhomme\b", "man"),
        (r"\bfille\b", "girl"),
        (r"\bgar(?:c|c)on\b", "boy"),
        (r"\bbelle\b", "beautiful"),
        (r"\bbeau\b", "handsome"),
        (r"\bsexy\b", "sexy"),
        (r"\bsensuelle?\b", "sensual"),
        (r"\bbrune?\b", "brunette"),
        (r"\bblonde?\b", "blonde"),
        (r"\brousse?\b", "redhead"),
        (r"\bmince\b", "slim"),
        (r"\bpulpeuse?\b", "curvy"),
        (r"\bmusculee?\b", "muscular"),
        (r"\btatouee?\b", "tattooed"),
        (r"\bpercee?\b", "pierced"),
        (r"\bseins?\b", "breasts"),
        (r"\bvagin\b", "pussy"),
        (r"\bchatte\b", "pussy"),
        (r"\bvulve\b", "pussy"),
        (r"\bfesses?\b", "butt"),
        (r"\bcuisses?\b", "thighs"),
        (r"\bventre\b", "belly"),
        (r"\bnombril\b", "navel"),
        # ---- Nudite ----
        (r"elle\s+est\s+nue", "she is completely nude"),
        (r"(?:il|elle)\s+est\s+nu(?:e)?", "completely nude"),
        (r"toute?\s+nu(?:e|d)", "completely nude"),
        (r"enti(?:e|e)rement\s+nu(?:e|d)", "completely nude"),
        (r"\bnu(?:e|d)?\b", "nude"),
        # ---- Lieux ----
        (r"(?:sur\s+(?:un\s+)?)?lit\b", "on a bed"),
        (r"(?:sur\s+(?:un\s+)?)?canap(?:e|e)", "on a couch"),
        (r"(?:dans\s+(?:la\s+)?)?salle\s+de\s+bain", "in the bathroom"),
        (r"(?:dans\s+(?:la\s+)?)?(?:une?\s+)?chambre", "in a bedroom"),
        (r"(?:dans\s+(?:la\s+)?)?douche", "in the shower"),
        (r"(?:dans\s+(?:la\s+)?)?piscine", "in a pool"),
        (r"(?:sur\s+(?:la\s+)?)?plage", "on the beach"),
        (r"(?:a\s+)?l['\s]ext(?:e|e)rieur", "outdoors"),
        (r"sur\s+la\s+peau", "on her skin"),
        (r"(?:la\s+)?peau\b", "skin"),
        # ---- Expressions ----
        (r"air\s+(?:sensuel|sexy)", "sensual expression"),
        (r"air\s+(?:coqu(?:in|ine))", "playful expression"),
        (r"air\s+(?:innocent|timide)", "innocent expression"),
        (r"(?:un\s+)?sourire", "smiling"),
    ]
    result = text
    for pattern, replacement in subs:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Nettoyer les connecteurs francais orphelins
    fr_connectors = [
        (r"\bqui\s+(?=\w)", ""),
        (r"\belle\s+a\s+", ", "),
        (r"\bil\s+a\s+", ", "),
        (r"\bet\s+(?:a|a)\s+", ", "),
        (r"\bet\s+(?:des?|un(?:e)?)\s+", ", "),
        (r"\bet\s+", ", "),
        (r"\bavec\s+", ", "),
        (r"\bune?\s+(?=\w+\s+\w+)", ""),
        (r"\bdes?\s+(?=\w+\s+\w+)", ""),
        (r"\bles?\s+(?=\w+)", ""),
        (r"\bla\s+(?=\w+)", ""),
        (r"\belle\s+(?=\w)", ""),
        (r"\bil\s+(?=\w)", ""),
    ]
    for pattern, replacement in fr_connectors:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    result = re.sub(r',\s*,', ',', result)
    result = re.sub(r'\s+', ' ', result)
    result = result.strip(' ,')

    return result


def _strip_image_prefix(message: str) -> str:
    """Strip les prefixes de demande d'image pour garder le prompt pur."""
    import re
    prefixes = [
        r"g[eé]n[eè]re[\s-]*moi\s+une\s+image\s+d[e\']\s*:?\s*",
        r"g[eé]n[eè]re[\s-]*moi\s+une\s+image\s+de\s+",
        r"g[eé]n[eè]re[\s-]*moi\s+une\s+photo\s+d[e\']\s*:?\s*",
        r"g[eé]n[eè]re[\s-]*moi\s+",
        r"g[eé]n[eè]re\s+une\s+image\s+d[e\']\s*:?\s*",
        r"g[eé]n[eè]re\s+",
        r"imagine[\s-]*moi\s+",
        r"imagine[,:\s]+",
        r"dessine[\s-]*moi\s+",
        r"dessine\s+",
        r"montre[\s-]*moi\s+",
        r"fais[\s-]*moi\s+une\s+image\s+d[e\']\s*:?\s*",
        r"fais\s+une\s+image\s+d[e\']\s*:?\s*",
        r"cr[eé][eé]\s+une\s+image\s+d[e\']\s*:?\s*",
        r"generate\s+an?\s+image\s+of\s+",
        r"generate\s+an?\s+photo\s+of\s+",
        r"generate\s+",
        r"create\s+an?\s+image\s+of\s+",
        r"make\s+an?\s+image\s+of\s+",
        r"draw\s+",
        r"show\s+me\s+",
        r"picture\s+of\s+",
        r"une\s+image\s+d[e\']\s*:?\s*",
        r"une\s+photo\s+d[e\']\s*:?\s*",
        r"image\s+d[e\']\s*:?\s*",
    ]
    text = message.strip()
    for p in prefixes:
        text = re.sub(r'^' + p, '', text, flags=re.IGNORECASE).strip()
    return text


def _is_mostly_english(text: str) -> bool:
    """Local-only shortcut: true only for prompts that are obviously English."""
    text_lower = text.lower()
    padded = f' {text_lower} '
    en_markers = [
        ' the ', ' a ', ' an ', ' with ', ' on ', ' in ', ' her ', ' his ',
        ' she ', ' is ', ' are ', ' from ', ' and ', ' but ', ' this ',
        ' same ', ' no ', ' full', ' nude', ' naked', ' cloth',
        ' woman', ' man ', ' girl', ' boy ', ' eyes', ' hair',
        ' wearing', ' lying', ' sitting', ' standing', ' remove',
        ' close', ' camera', ' photo', ' style', ' quality',
        ' bedroom', ' breast', ' body', ' face', ' make ',
    ]
    en_count = sum(1 for m in en_markers if m in padded)
    if en_count >= 1:
        return True
    return False


def _is_cloud_text_model(model: str = None) -> bool:
    if not model:
        return False
    try:
        from core.agent_runtime import is_cloud_model_name
        return is_cloud_model_name(model)
    except Exception:
        return False


def enhance_prompt(prompt: str, for_inpainting: bool = True, model: str = None) -> tuple[str, str]:
    """
    Utilise le utility model pour ameliorer un prompt de generation d'image.

    Returns:
        tuple(enhanced_prompt, style) ou style est "realistic" ou "artistic"
    """
    mode = 'inpainting' if for_inpainting else 'text2img'
    print(f"[ENHANCE] \"{prompt[:50]}...\" ({mode})")
    use_cloud_model = _is_cloud_text_model(model)

    if use_cloud_model:
        working_prompt = prompt
        print(f"[ENHANCE] Cloud rewrite via {model}")
    elif _is_mostly_english(prompt):
        print(f"[ENHANCE] Anglais detecte, skip LLM")
        return prompt, "realistic"
    else:
        working_prompt = _preprocess_french_prompt(prompt)
        print(f"[ENHANCE] Pre-traite FR->EN: \"{working_prompt[:60]}...\"")

        if _is_mostly_english(working_prompt):
            print(f"[ENHANCE] Pre-traitement suffisant, skip LLM")
            return working_prompt, "realistic"

    system_prompt = _load_enhance_prompt('inpainting' if for_inpainting else 'text2img')

    user_content = f"""Rewrite or translate this text into a clean ENGLISH prompt for image generation:
"{working_prompt}"

Write your response in ENGLISH. Keep the user's intent. Do not write French."""

    response = _call_utility(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        num_predict=200 if use_cloud_model else 150,
        temperature=0.3,
        timeout=30 if use_cloud_model else 10,
        model=model,
    )

    if response:
        style = "realistic"
        enhanced = None

        for line in response.split('\n'):
            line = line.strip()
            if line.upper().startswith("STYLE:"):
                style_value = line.split(":", 1)[1].strip().lower()
                style = "artistic" if "artistic" in style_value else "realistic"
            elif line.upper().startswith("PROMPT:"):
                enhanced = line.split(":", 1)[1].strip().strip('"\'')

        import re
        if enhanced:
            cleaned = re.sub(r'[^\x00-\x7F]+', '', enhanced)
            if cleaned != enhanced:
                print(f"[ENHANCE] Nettoye caracteres non-ASCII du prompt")
                enhanced = cleaned.strip(' ,')

        if enhanced is None:
            clean_response = response.strip().strip('"\'')
            french_chars = ['é', 'è', 'ê', 'à', 'ù', 'ç', 'ô', 'î', 'û', 'ë', 'ï']
            is_french = any(c in clean_response.lower() for c in french_chars)

            if not is_french and len(clean_response) > 5:
                enhanced = clean_response
            else:
                enhanced = working_prompt
                print(f"[ENHANCE] Fallback: reponse FR/invalide")

        if enhanced:
            cleaned = re.sub(r'[^\x00-\x7F]+', '', enhanced)
            if cleaned != enhanced:
                print(f"[ENHANCE] Nettoye caracteres non-ASCII: \"{enhanced[:60]}\" -> \"{cleaned[:60]}\"")
                enhanced = cleaned.strip(' ,')

        print(f"[ENHANCE] -> \"{enhanced[:60]}...\" ({style})")
        return enhanced, style

    print(f"[ENHANCE] Fallback: pas de reponse AI")
    return working_prompt, "realistic"


_HUMAN_SUBJECT_RE = re.compile(
    r"\b("
    r"person|people|human|man|woman|girl|boy|lady|guy|adult|portrait|face|headshot|"
    r"body|skin|nude|naked|boobs?|breasts?|chest|torso|hips?|butt|ass|vulva|penis|"
    r"clothing|clothes|outfit|dress|shirt|pants|bikini|lingerie|underwear|"
    r"personne|humain|homme|femme|fille|garcon|garçon|visage|corps|peau|nu|nue|"
    r"seins?|poitrine|fesses?|vetement|vêtement|vetements|vêtements|habit|robe|chemise|pantalon"
    r")\b",
    re.IGNORECASE,
)


def _has_human_subject(prompt: str) -> bool:
    """True when human-specific skin/body quality tags make sense."""
    return bool(_HUMAN_SUBJECT_RE.search(prompt or ""))


def build_full_prompt(enhanced_prompt: str, style: str, for_inpainting: bool = True, orientation: str = None, pose: str = None) -> tuple[str, str]:
    """
    Construit le prompt final et le negative prompt base sur le style.
    """
    import re

    inpainting_negative = "extra limbs, added body parts, changed pose, different angle, new elements, invented details, repositioned"

    prompt_lower = enhanced_prompt.lower()
    nudity_keywords = ['nude', 'naked', 'bare skin', 'body', 'skin', 'undress', 'clothing', 'clothes', 'x-ray', 'see-through', 'transparent']
    is_nudity_prompt = any(k in prompt_lower for k in nudity_keywords)

    orientation_positive = ""
    orientation_negative = ""
    if orientation and is_nudity_prompt:
        if orientation == "front":
            orientation_positive = ", front-facing view"
            orientation_negative = ", from behind, back view, rear"
        elif orientation == "back":
            orientation_positive = ", from behind, back view, showing back"
            orientation_negative = ", frontal view, front-facing view"
        elif orientation == "side":
            orientation_positive = ", side view, profile"
            orientation_negative = ", frontal view, back view"

    pose_positive = ""
    pose_negative = ""
    if pose and is_nudity_prompt:
        if pose == 'lying_left':
            pose_positive = ", lying down, head on left side, horizontal body"
            pose_negative = ", standing, sitting, upright"
        elif pose == 'lying_right':
            pose_positive = ", lying down, head on right side, horizontal body"
            pose_negative = ", standing, sitting, upright"
        elif pose == 'lying':
            pose_positive = ", lying down, horizontal body"
            pose_negative = ", standing, sitting, upright"

    duplicates_to_remove = [
        'raw photo', '8k uhd', '8k', 'uhd', 'high quality', 'natural skin texture', 'natural skin', 'matte skin',
        'preserve original pose', 'seamless blend', 'same framing', 'keep original',
        'original composition', 'body proportions', 'professional photography',
        'natural lighting', 'detailed', 'vibrant colors', 'digital art', 'masterpiece'
    ]

    clean_prompt = enhanced_prompt
    for dup in duplicates_to_remove:
        pattern = re.compile(re.escape(dup) + r',?\s*', re.IGNORECASE)
        clean_prompt = pattern.sub('', clean_prompt)

    clean_prompt = re.sub(r',\s*,', ',', clean_prompt)
    clean_prompt = re.sub(r'\s+', ' ', clean_prompt)
    clean_prompt = clean_prompt.strip(' ,')

    framing_instructions = ""
    framing_negative = ""
    intimate_details = ""
    user_specified_breast_size = False

    if is_nudity_prompt and for_inpainting:
        framing_instructions = ", same framing"
        framing_negative = ", cropped, zoomed, different framing"

        no_hair_keywords = ['shaved', 'hairless', 'smooth', 'bald', 'waxed', 'rase', 'epile', 'sans poil', 'glabre']
        wants_no_hair = any(k in prompt_lower for k in no_hair_keywords)

        breast_size_keywords = ['small breast', 'medium breast', 'large breast', 'big breast', 'tiny breast', 'huge breast']
        user_specified_breast_size = any(k in prompt_lower for k in breast_size_keywords)

        if user_specified_breast_size:
            proportion_instruction = ""
        else:
            proportion_instruction = ", same body proportions"

        if orientation == "back":
            intimate_details = ", bare back, buttocks"
        elif orientation == "side":
            intimate_details = ", side profile"
        else:
            if not wants_no_hair:
                intimate_details = f", bare chest, vulva, pubic hair{proportion_instruction}"
            else:
                intimate_details = f", bare chest, vulva, smooth skin{proportion_instruction}"

    body_desc_prompt = ""

    if style == "realistic":
        has_human_subject = _has_human_subject(clean_prompt)
        if has_human_subject:
            quality = "RAW photo, natural skin texture with visible pores, matte skin, soft natural lighting, shot on kodak, 35mm photo, film grain, grainy"
            texture_negative = "plastic skin, airbrushed, porcelain skin, wax skin, doll-like, shiny skin, oily skin, glossy skin"
            structure_negative = "deformed, bad anatomy, extra limbs, mutated"
        else:
            quality = "RAW photo, photorealistic, soft natural lighting, shot on kodak, 35mm photo, film grain, grainy"
            texture_negative = "airbrushed, overly smooth, plastic-looking, waxy, toy-like, fake texture"
            structure_negative = "distorted, deformed, warped geometry, broken structure, mutated"
        if for_inpainting:
            full_prompt = f"{clean_prompt}{body_desc_prompt}, {quality}, preserve original pose, seamless blend{framing_instructions}{orientation_positive}{pose_positive}{intimate_details}"
            negative = f"cartoon, anime, CGI, 3D render, {texture_negative}, {structure_negative}, blurry, {inpainting_negative}{framing_negative}{orientation_negative}{pose_negative}"
        else:
            full_prompt = f"{clean_prompt}, {quality}, professional photography"
            negative = f"cartoon, illustration, anime, painting, CGI, 3D render, {texture_negative}, {structure_negative}, blurry, low quality"
    else:
        quality = "detailed, vibrant colors, digital art"
        if for_inpainting:
            full_prompt = f"{clean_prompt}, {quality}, preserve original pose, coherent style{framing_instructions}{orientation_positive}{pose_positive}"
            negative = f"blurry, deformed, bad anatomy, {inpainting_negative}{framing_negative}{orientation_negative}{pose_negative}"
        else:
            full_prompt = f"{clean_prompt}, {quality}, masterpiece"
            negative = "blurry, low quality, deformed, bad anatomy, ugly, amateur, poorly drawn"

    return full_prompt, negative


def extract_image_prompt(user_message: str, chat_model: str = None, model: str = None) -> str | None:
    """
    Genere un prompt d'image en anglais base sur la demande utilisateur.
    Utilise APRES que check_image_request() a retourne True.

    Returns:
        Le prompt d'image en anglais, ou None si erreur
    """
    if not user_message:
        return None

    clean_prompt = _strip_image_prefix(user_message)
    use_model = model or chat_model
    use_cloud_model = _is_cloud_text_model(use_model)

    if use_cloud_model:
        preprocessed = clean_prompt or user_message
        print(f"[IMAGE-PROMPT] Cloud rewrite via {use_model}: \"{preprocessed[:80]}...\"")
    elif clean_prompt and _is_mostly_english(clean_prompt):
        print(f"[IMAGE-PROMPT] Direct (anglais detecte): \"{clean_prompt[:80]}...\"")
        return clean_prompt
    else:
        preprocessed = _preprocess_french_prompt(clean_prompt or user_message)
        print(f"[IMAGE-PROMPT] Pre-traite: \"{preprocessed[:80]}...\"")

        if _is_mostly_english(preprocessed):
            print(f"[IMAGE-PROMPT] Pre-traitement suffisant (anglais detecte)")
            return preprocessed

    system_prompt = """You are a Stable Diffusion prompt translator. Convert the partially-translated description into a clean, structured English prompt.

RULES:
- Output ONE line, English only, no explanations
- Structure: subject, pose/position, body details, face/expression, setting
- Keep ALL details from the input, translate remaining French words
- Under 50 words
- Do NOT add details that aren't in the input
- NEVER use brackets [] or parentheses () in the output"""

    user_content = f"""Clean up and structure this image prompt:
"{preprocessed}"

Prompt:"""

    response = _call_utility(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        num_predict=120,
        temperature=0.3,
        timeout=15,
        model=use_model
    )

    if response:
        image_prompt = response.replace('"', '').replace("'", "").replace('[', '').replace(']', '').strip()
        for prefix in ("prompt:", "english prompt:", "english:"):
            if image_prompt.lower().startswith(prefix):
                image_prompt = image_prompt[len(prefix):].strip()

        if image_prompt and len(image_prompt) > 5:
            print(f"[IMAGE-PROMPT] Traduit: \"{image_prompt[:80]}...\"")
            return image_prompt

    print(f"[IMAGE-PROMPT] Fallback (LLM indisponible)")
    return clean_prompt or user_message


# Alias
generate_image_prompt = extract_image_prompt
