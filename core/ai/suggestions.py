"""
Contextual image suggestions for JoyBoy.

Suggestions are intentionally neutral and action-oriented. Florence describes
what is visible; this module turns that description into prompts that route well
through the existing image editor instead of surfacing vague/style-only presets.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from core.infra.packs import get_pack_prompt_assets


SUPPORTED_LOCALES = {"fr", "en", "es", "it"}

PERSON_WORDS = {
    "person", "people", "woman", "man", "girl", "boy", "lady", "guy", "female", "male",
    "child", "teen", "model", "portrait", "face", "body", "hair", "skin",
}
WOMAN_WORDS = {"woman", "female", "girl", "lady", "she", "her"}
MAN_WORDS = {"man", "male", "boy", "guy", "he", "him"}
ANIMAL_WORDS = {"cat", "dog", "horse", "bird", "animal", "kitten", "puppy"}
VEHICLE_WORDS = {"car", "vehicle", "motorcycle", "bike", "truck", "road"}
FOOD_WORDS = {"food", "plate", "meal", "dish", "cake", "drink", "coffee"}
INTERIOR_WORDS = {"room", "bed", "sofa", "kitchen", "bathroom", "indoor", "table", "chair"}
WATER_WORDS = {"water", "pool", "sea", "ocean", "beach", "swimming", "underwater", "lake"}
NATURE_WORDS = {"tree", "forest", "mountain", "garden", "grass", "sky", "field", "outdoor"}
CITY_WORDS = {"street", "city", "building", "urban", "sidewalk", "road"}
MINIMAL_CLOTHING_WORDS = {
    "nude", "naked", "topless", "bare", "shirtless", "underwear", "lingerie",
    "bikini", "swimsuit", "swimwear", "bra", "panties", "shorts",
}
CLOTHING_WORDS = {
    "dress", "shirt", "pants", "jeans", "jacket", "coat", "skirt", "suit",
    "uniform", "robe", "outfit", "clothes", "clothing", "wearing",
}

STABILITY_SUFFIX = (
    "same framing as original image, do not crop, do not zoom, keep original composition, "
    "keep original pose and body proportions, realistic lighting"
)


LABELS = {
    "fr": {
        "dress_person": "Habiller la personne",
        "casual_outfit": "Tenue casual",
        "elegant_outfit": "Tenue habillée",
        "sport_outfit": "Tenue sport",
        "change_background": "Changer le décor",
        "sunset_beach": "Plage coucher soleil",
        "studio_light": "Lumière studio",
        "hair_style": "Changer les cheveux",
        "clean_background": "Fond propre",
        "cinematic_light": "Ambiance cinéma",
        "nature_scene": "Décor nature",
        "city_scene": "Décor ville",
        "product_light": "Photo produit",
        "warm_colors": "Couleurs chaudes",
        "vintage_photo": "Photo vintage",
        "animal_portrait": "Portrait animal",
    },
    "en": {
        "dress_person": "Dress person",
        "casual_outfit": "Casual outfit",
        "elegant_outfit": "Elegant outfit",
        "sport_outfit": "Sports outfit",
        "change_background": "Change scenery",
        "sunset_beach": "Sunset beach",
        "studio_light": "Studio lighting",
        "hair_style": "Change hair",
        "clean_background": "Clean background",
        "cinematic_light": "Cinematic mood",
        "nature_scene": "Nature scene",
        "city_scene": "City scene",
        "product_light": "Product photo",
        "warm_colors": "Warm colors",
        "vintage_photo": "Vintage photo",
        "animal_portrait": "Animal portrait",
    },
    "es": {
        "dress_person": "Vestir persona",
        "casual_outfit": "Ropa casual",
        "elegant_outfit": "Ropa elegante",
        "sport_outfit": "Ropa deportiva",
        "change_background": "Cambiar fondo",
        "sunset_beach": "Playa atardecer",
        "studio_light": "Luz de estudio",
        "hair_style": "Cambiar pelo",
        "clean_background": "Fondo limpio",
        "cinematic_light": "Ambiente cine",
        "nature_scene": "Escena natural",
        "city_scene": "Escena urbana",
        "product_light": "Foto producto",
        "warm_colors": "Colores cálidos",
        "vintage_photo": "Foto vintage",
        "animal_portrait": "Retrato animal",
    },
    "it": {
        "dress_person": "Vestire persona",
        "casual_outfit": "Look casual",
        "elegant_outfit": "Look elegante",
        "sport_outfit": "Look sportivo",
        "change_background": "Cambiare sfondo",
        "sunset_beach": "Spiaggia tramonto",
        "studio_light": "Luce studio",
        "hair_style": "Cambiare capelli",
        "clean_background": "Sfondo pulito",
        "cinematic_light": "Atmosfera cinema",
        "nature_scene": "Scenario natura",
        "city_scene": "Scenario città",
        "product_light": "Foto prodotto",
        "warm_colors": "Colori caldi",
        "vintage_photo": "Foto vintage",
        "animal_portrait": "Ritratto animale",
    },
}


@dataclass(frozen=True)
class SuggestionContext:
    description: str
    words: set[str]
    content_type: str
    scene_type: str
    clothing_state: str
    locale: str


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def _has_any(words: set[str], candidates: Iterable[str]) -> bool:
    return any(candidate in words for candidate in candidates)


def normalize_locale(locale: str | None) -> str:
    lang = _norm(locale or "").split("-", 1)[0]
    return lang if lang in SUPPORTED_LOCALES else "fr"


def _label(key: str, locale: str) -> str:
    return LABELS.get(locale, LABELS["fr"]).get(key) or LABELS["fr"].get(key) or key


def _suggest(label_key: str, prompt: str, locale: str, *, kind: str = "edit") -> dict:
    return {
        "label": _label(label_key, locale),
        "prompt": prompt,
        "kind": kind,
        "labelKey": label_key,
    }


def _classify_scene(words: set[str]) -> str:
    if _has_any(words, WATER_WORDS):
        return "water"
    if _has_any(words, CITY_WORDS):
        return "city"
    if _has_any(words, INTERIOR_WORDS):
        return "interior"
    if _has_any(words, NATURE_WORDS):
        return "nature"
    return "generic"


def _classify_clothing(words: set[str]) -> str:
    if _has_any(words, MINIMAL_CLOTHING_WORDS):
        return "minimal"
    if _has_any(words, CLOTHING_WORDS):
        return "clothed"
    return "unknown"


def classify_content_type(description: str) -> str:
    words = _words(description)
    is_woman = _has_any(words, WOMAN_WORDS)
    is_man = _has_any(words, MAN_WORDS) and not is_woman
    if is_woman:
        return "woman"
    if is_man:
        return "man"
    if _has_any(words, PERSON_WORDS):
        return "person"
    if _has_any(words, ANIMAL_WORDS):
        return "animal"
    if _has_any(words, VEHICLE_WORDS):
        return "vehicle"
    if _has_any(words, FOOD_WORDS):
        return "food"
    return "generic"


def build_context(description: str, locale: str | None = None) -> SuggestionContext:
    words = _words(description)
    content_type = classify_content_type(description)
    return SuggestionContext(
        description=str(description or ""),
        words=words,
        content_type=content_type,
        scene_type=_classify_scene(words),
        clothing_state=_classify_clothing(words),
        locale=normalize_locale(locale),
    )


def _person_suggestions(ctx: SuggestionContext) -> list[dict]:
    suggestions: list[dict] = []

    if ctx.clothing_state in {"minimal", "unknown"}:
        suggestions.append(_suggest(
            "dress_person",
            f"dress the person in a tasteful casual outfit covering torso and hips, realistic fabric, natural fit, {STABILITY_SUFFIX}",
            ctx.locale,
        ))

    suggestions.extend([
        _suggest(
            "casual_outfit",
            f"change clothes to a clean modern casual outfit, realistic fabric texture, natural fit, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
        _suggest(
            "elegant_outfit",
            f"change clothes to an elegant evening outfit, refined fabric, polished styling, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
        _suggest(
            "sport_outfit",
            f"change clothes to practical sportswear, realistic fabric seams, comfortable athletic styling, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
        _suggest(
            "hair_style",
            f"change hair style subtly, natural hair texture, keep same face identity, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
    ])

    if ctx.scene_type == "water":
        suggestions.append(_suggest(
            "sunset_beach",
            f"change background to a warm sunset beach, natural reflections, same subject lighting, {STABILITY_SUFFIX}",
            ctx.locale,
        ))
    elif ctx.scene_type == "city":
        suggestions.append(_suggest(
            "city_scene",
            f"change background to a clean modern city street, realistic perspective, matching light, {STABILITY_SUFFIX}",
            ctx.locale,
        ))
    elif ctx.scene_type == "interior":
        suggestions.append(_suggest(
            "studio_light",
            f"studio lighting, soft key light, subtle background blur, keep subject unchanged, {STABILITY_SUFFIX}",
            ctx.locale,
        ))
    else:
        suggestions.append(_suggest(
            "nature_scene",
            f"change background to a natural outdoor landscape, realistic depth, matching light, {STABILITY_SUFFIX}",
            ctx.locale,
        ))

    suggestions.extend([
        _suggest(
            "cinematic_light",
            f"cinematic lighting, richer contrast, natural skin tones, keep clothing and pose unchanged, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
        _suggest(
            "clean_background",
            f"clean studio background, remove visual clutter, keep the subject unchanged, {STABILITY_SUFFIX}",
            ctx.locale,
        ),
    ])
    return suggestions


def _animal_suggestions(ctx: SuggestionContext) -> list[dict]:
    return [
        _suggest(
            "animal_portrait",
            f"turn this into a clean animal portrait photo, detailed fur, soft natural light, same composition as original",
            ctx.locale,
        ),
        _suggest(
            "nature_scene",
            f"change background to a natural outdoor scene, realistic depth, same animal pose and framing",
            ctx.locale,
        ),
        _suggest(
            "cinematic_light",
            f"cinematic lighting, warm highlights, natural colors, same animal and composition",
            ctx.locale,
        ),
    ]


def _generic_suggestions(ctx: SuggestionContext) -> list[dict]:
    suggestions = [
        _suggest(
            "change_background",
            f"change background to a clean realistic environment, keep main subject unchanged, same composition as original",
            ctx.locale,
        ),
        _suggest(
            "cinematic_light",
            f"cinematic lighting, natural contrast, realistic photo style, same composition as original",
            ctx.locale,
        ),
        _suggest(
            "warm_colors",
            f"warm color grading, natural tones, realistic photo, same composition as original",
            ctx.locale,
        ),
        _suggest(
            "vintage_photo",
            f"vintage film photo look, subtle grain, warm faded colors, same composition as original",
            ctx.locale,
        ),
    ]
    if ctx.content_type in {"food", "vehicle"}:
        suggestions.insert(0, _suggest(
            "product_light",
            f"clean product photo lighting, sharp details, natural reflections, same composition as original",
            ctx.locale,
        ))
    return suggestions


def _get_pack_suggestions(content_type: str) -> list[dict]:
    """Return only public-safe pack suggestions.

    Local packs can extend suggestions, but they must opt in with
    ``"public_safe": true``. This prevents private/adult prompt assets from
    leaking into the normal suggestion strip just because the pack is installed.
    """
    prompt_assets = get_pack_prompt_assets()
    suggestions = prompt_assets.get("suggestions", {})
    if not isinstance(suggestions, dict):
        return []

    entries = suggestions.get(content_type, [])
    if not isinstance(entries, list):
        return []

    return [
        entry for entry in entries
        if (
            isinstance(entry, dict)
            and entry.get("public_safe") is True
            and entry.get("label")
            and entry.get("prompt")
        )
    ]


def get_suggestions_for_description(
    description: str,
    adult_runtime_enabled: bool = False,
    locale: str | None = None,
) -> dict:
    ctx = build_context(description, locale)

    if ctx.content_type in {"woman", "man", "person"}:
        suggestions = _person_suggestions(ctx)
        suggestion_mode = "contextual_person"
    elif ctx.content_type == "animal":
        suggestions = _animal_suggestions(ctx)
        suggestion_mode = "contextual_animal"
    else:
        suggestions = _generic_suggestions(ctx)
        suggestion_mode = "contextual_generic"

    # Keep pack extension legal/neutral by default. Adult local suggestions are
    # still possible from packs, but only if the pack explicitly marks them safe.
    pack_suggestions = _get_pack_suggestions(ctx.content_type)
    if pack_suggestions:
        suggestions.extend(pack_suggestions)
        suggestion_mode = f"{suggestion_mode}+pack_safe"

    return {
        "content_type": ctx.content_type,
        "scene_type": ctx.scene_type,
        "clothing_state": ctx.clothing_state,
        "suggestion_mode": suggestion_mode,
        "suggestions": suggestions[:8],
    }


__all__ = [
    "build_context",
    "classify_content_type",
    "get_suggestions_for_description",
    "normalize_locale",
]
