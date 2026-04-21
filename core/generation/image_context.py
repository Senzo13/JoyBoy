"""Shared image understanding helpers for chat and generation routes."""

from __future__ import annotations

import re
from typing import Any


def build_image_context(image: Any, message: str = "") -> str:
    """Return compact visual context for an image-aware answer."""
    if image is None:
        return ""

    description = ""
    try:
        from core.florence import describe_image

        description = describe_image(image, task="<CAPTION>")
        if description:
            print(f"[IMAGE-CONTEXT] Florence: {description[:120]}")
    except Exception as exc:
        print(f"[IMAGE-CONTEXT] Florence unavailable: {exc}")

    food_result = None
    try:
        from core.food_vision import analyze_food_image, format_food_context, should_run_foodextract

        if should_run_foodextract(description, user_message=message):
            print("[FOODEXTRACT] Food/drink context requested")
            food_result = analyze_food_image(image)
            if food_result.success:
                print(
                    f"[FOODEXTRACT] is_food={food_result.is_food} "
                    f"foods={len(food_result.food_items)} drinks={len(food_result.drink_items)}"
                )
            else:
                print(f"[FOODEXTRACT] unavailable: {food_result.error}")
            return "\n\n" + format_food_context(description, food_result)
    except Exception as exc:
        print(f"[FOODEXTRACT] skipped: {exc}")

    if not description:
        return ""

    return (
        "\n\n=== IMAGE CONTEXT ===\n"
        f"Florence caption: {description}\n"
        "Use this image context to answer the user. Do not claim certainty beyond what is visible."
    )


def answer_image_question(
    image: Any,
    message: str,
    *,
    chat_model: str | None = None,
    locale: str = "fr",
) -> dict[str, Any]:
    """Answer a read-only question about an image without entering diffusion."""
    context = build_image_context(image, message)
    lang = _normalize_locale(locale)

    answer = ""
    if context and chat_model:
        try:
            from core.ai.text_model_router import call_text_model

            answer = call_text_model(
                [
                    {"role": "system", "content": _analysis_system_prompt(lang) + context},
                    {"role": "user", "content": message},
                ],
                purpose="image_analysis",
                model=chat_model,
                num_predict=700,
                temperature=0.2,
                timeout=90,
            ) or ""
        except Exception as exc:
            print(f"[IMAGE-ANALYSIS] LLM answer skipped: {exc}")

    if not answer:
        answer = _fallback_answer(context, lang)

    return {
        "response": answer,
        "context": context,
    }


def _normalize_locale(locale: str | None) -> str:
    raw = str(locale or "").split(",", 1)[0].strip().replace("_", "-").lower()
    lang = raw.split("-", 1)[0]
    return lang if lang in {"fr", "en", "es", "it"} else "fr"


def _analysis_system_prompt(lang: str) -> str:
    language = {
        "fr": "French",
        "en": "English",
        "es": "Spanish",
        "it": "Italian",
    }.get(lang, "French")
    return (
        "You answer read-only questions about the provided image context. "
        f"Reply in {language}. Be concise and direct. "
        "Use food/drink specialist details when present. "
        "If something is uncertain, say it is only visible/probable. "
        "Do not offer image generation or editing.\n"
    )


def _fallback_answer(context: str, lang: str) -> str:
    caption = ""
    food_items: list[str] = []
    drink_items: list[str] = []

    for line in str(context or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Florence caption:"):
            caption = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- Food items:"):
            food_items = _split_items(stripped.split(":", 1)[1])
        elif stripped.startswith("- Drink items:"):
            drink_items = _split_items(stripped.split(":", 1)[1])

    items = food_items + drink_items
    if items:
        joined = ", ".join(items)
        return {
            "fr": f"Je vois probablement: {joined}.",
            "en": f"I can probably see: {joined}.",
            "es": f"Probablemente veo: {joined}.",
            "it": f"Probabilmente vedo: {joined}.",
        }.get(lang, f"Je vois probablement: {joined}.")

    if caption:
        return {
            "fr": f"Sur l'image, je vois: {caption}",
            "en": f"In the image, I can see: {caption}",
            "es": f"En la imagen veo: {caption}",
            "it": f"Nell'immagine vedo: {caption}",
        }.get(lang, f"Sur l'image, je vois: {caption}")

    return {
        "fr": "Je n'arrive pas à analyser clairement cette image.",
        "en": "I cannot clearly analyze this image.",
        "es": "No puedo analizar claramente esta imagen.",
        "it": "Non riesco ad analizzare chiaramente questa immagine.",
    }.get(lang, "Je n'arrive pas à analyser clairement cette image.")


def _split_items(value: str) -> list[str]:
    return [item.strip() for item in re.split(r",|;", value or "") if item.strip()]


__all__ = ["answer_image_question", "build_image_context"]
