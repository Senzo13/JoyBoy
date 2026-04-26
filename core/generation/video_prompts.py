"""Small prompt helpers for video backends.

Keep this module dependency-light so CI and docs tests can validate prompt
behavior without importing GPU libraries from the full video pipeline.
"""

from __future__ import annotations

import re


FAST_MOTION_INTENT_WORDS = (
    "fast", "quick", "rapid", "rapidly", "speed", "speed up", "quickly",
    "run", "running", "jump", "jumping", "dance", "dancing", "energetic",
    "vite", "rapidement", "rapide", "bouge vite", "accelere", "accélère",
    "courir", "court", "danse", "saut", "saute",
)


def _clip_safe_words(text: str, max_words: int) -> tuple[str, bool]:
    """Trim long text before CLIP truncates the important motion suffix."""
    clean = " ".join((text or "").split())
    if not clean:
        return "", False
    words = re.findall(r"\S+", clean)
    if len(words) <= max_words:
        return clean, False
    return " ".join(words[:max_words]).rstrip(" ,;:"), True


FRAMEPACK_MOTION_DEFAULT = "Natural visible movement with subtle camera parallax and clear subject action."
FRAMEPACK_QUALITY_SUFFIX = (
    "Preserve identity, outfit, scene, lighting, anatomy. "
    "Coherent movement, stable details, clear full-speed progression."
)
VISUAL_SOURCE_FIDELITY_SUFFIX = (
    "Match the source image/video look and quality as closely as possible: preserve the original exposure, contrast, "
    "color grade, sharpness, grain/noise, compression artifacts, skin texture, lens/camera feel, and detail level. "
    "Use restrained, slow, natural motion by default; preserve the source motion speed unless faster movement is explicitly requested. "
    "Do not beautify, upscale, denoise, over-sharpen, relight, color-correct, make more cinematic, or improve the source unless explicitly requested."
)
VISUAL_SOURCE_FIDELITY_NEGATIVE = (
    "oversaturated colors, boosted saturation, high contrast, crushed shadows, blown highlights, HDR look, "
    "cinematic color grading, vivid colors, glossy skin, oily skin, wet skin, harsh specular highlights, "
    "strong skin reflections, artificial beauty filter, relit scene, denoised source, over-sharpened details, source quality drift"
)
VISUAL_SOURCE_MOTION_NEGATIVE = (
    "rapid motion, hyperactive movement, fast body movement, jerky movement, exaggerated motion, sudden pose change, "
    "violent camera movement, motion speed drift"
)


def _allows_fast_motion(text: str = "") -> bool:
    lower = f" {str(text or '').lower()} "
    return any(word in lower for word in FAST_MOTION_INTENT_WORDS)


def _append_visual_source_fidelity(prompt: str, *, has_visual_source: bool = True) -> str:
    """Ask video models to preserve the source quality instead of improving it."""
    base = (prompt or "").strip()
    if not base or not has_visual_source:
        return base
    lower = base.lower()
    if "match the source image/video look" in lower or "preserve the original exposure" in lower:
        return base
    return f"{base.rstrip('. ')}. {VISUAL_SOURCE_FIDELITY_SUFFIX}"


def _build_video_prompt(prompt: str, default_prompt: str, *, has_visual_source: bool = True) -> str:
    base_prompt = (prompt or default_prompt or "").strip()
    return _append_visual_source_fidelity(base_prompt, has_visual_source=has_visual_source)


def _build_video_negative_prompt(
    negative_prompt: str = "",
    *,
    has_visual_source: bool = True,
    user_prompt: str = "",
) -> str:
    base = (negative_prompt or "").strip()
    if not has_visual_source:
        return base
    additions = [VISUAL_SOURCE_FIDELITY_NEGATIVE]
    if not _allows_fast_motion(user_prompt):
        additions.append(VISUAL_SOURCE_MOTION_NEGATIVE)
    result = base
    for addition in additions:
        lower = result.lower()
        if addition.split(",", 1)[0].lower() in lower:
            continue
        result = addition if not result else f"{result.rstrip(' ,')}, {addition}"
    return result


def _build_framepack_prompt(prompt: str, *, fast: bool = False, has_visual_source: bool = True) -> tuple[str, bool]:
    """Build FramePack's positive prompt without leaking negative concepts.

    Avoid phrases such as "no slow motion" in the positive prompt: diffusion
    video models can still latch onto the forbidden concept token. Keep the
    positive prompt purely affirmative and put bad states only in the negative
    prompt.
    """
    base_prompt = (prompt.strip() if prompt else FRAMEPACK_MOTION_DEFAULT).rstrip(". ")
    prompt_word_budget = 28 if fast else 34
    base_prompt, was_trimmed = _clip_safe_words(base_prompt, max_words=prompt_word_budget)
    final_prompt = f"{base_prompt}. {FRAMEPACK_QUALITY_SUFFIX}"
    return _append_visual_source_fidelity(final_prompt, has_visual_source=has_visual_source), was_trimmed
