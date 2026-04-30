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


DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT = (
    "Animate only the visible source crop with slow, subtle, natural motion. "
    "Preserve the original framing, composition, visible shapes, textures, and details."
)
DEFAULT_SCENE_VIDEO_PROMPT = "The visible source content comes alive with natural, smooth motion."
LTX2_MOTION_DEFAULT = (
    "Animate the visible source with continuous natural motion across the whole clip. "
    "Create clear, coherent movement instead of a still image."
)
FRAMEPACK_MOTION_DEFAULT = "Natural visible movement of the visible source content with subtle camera parallax."
FRAMEPACK_QUALITY_SUFFIX = (
    "Preserve the visible subject/object, outfit/materials, scene, lighting, structure, and framing. "
    "Coherent movement, stable details, clear full-speed progression."
)
VISUAL_SOURCE_FIDELITY_SUFFIX = (
    "Match the source image/video look and quality as closely as possible: preserve the original exposure, contrast, "
    "color grade, sharpness, grain/noise, compression artifacts, skin texture, lens/camera feel, and detail level. "
    "Use restrained, slow, natural motion by default; preserve the source motion speed unless faster movement is explicitly requested. "
    "Preserve the original crop, framing, composition, and visible content only. "
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
LTX2_VISUAL_SOURCE_MOTION_SUFFIX = (
    "Preserve the source identity, outfit/materials, framing, lighting, color grade, texture, and detail level, "
    "but generate continuous visible motion throughout the entire clip. The subject or visible content should not stay frozen; "
    "use coherent pose, gesture, body, head, object, clothing, hair, and camera micro-movement when relevant."
)
LTX2_MOTION_NEGATIVE = (
    "still image, frozen frame, motionless subject, no visible motion, identical frames, slideshow, pose locked, "
    "static image, static shot, frozen body, frozen hands, frozen face, temporal stutter, repeated frame"
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


def _build_ltx2_motion_prompt(prompt: str, *, has_visual_source: bool = True) -> str:
    """Build an LTX-2 prompt that keeps source fidelity without freezing motion."""
    base = (prompt or LTX2_MOTION_DEFAULT or "").strip()
    if not has_visual_source:
        return base
    lower = base.lower()
    if "continuous visible motion" in lower or "should not stay frozen" in lower:
        return base
    return f"{base.rstrip('. ')}. {LTX2_VISUAL_SOURCE_MOTION_SUFFIX}"


def _build_ltx2_negative_prompt(negative_prompt: str = "", *, has_visual_source: bool = True) -> str:
    """Negative prompt tuned for LTX-2 I2V: avoid frozen outputs without overblocking style."""
    base = (negative_prompt or "").strip()
    additions = [LTX2_MOTION_NEGATIVE]
    if has_visual_source:
        additions.append(VISUAL_SOURCE_FIDELITY_NEGATIVE)
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
