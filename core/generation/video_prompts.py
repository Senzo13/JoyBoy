"""Small prompt helpers for video backends.

Keep this module dependency-light so CI and docs tests can validate prompt
behavior without importing GPU libraries from the full video pipeline.
"""

from __future__ import annotations

import re


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
    "Photoreal coherent movement, stable details, clear full-speed progression."
)


def _build_framepack_prompt(prompt: str, *, fast: bool = False) -> tuple[str, bool]:
    """Build FramePack's positive prompt without leaking negative concepts.

    Avoid phrases such as "no slow motion" in the positive prompt: diffusion
    video models can still latch onto the forbidden concept token. Keep the
    positive prompt purely affirmative and put bad states only in the negative
    prompt.
    """
    base_prompt = (prompt.strip() if prompt else FRAMEPACK_MOTION_DEFAULT).rstrip(". ")
    prompt_word_budget = 28 if fast else 34
    base_prompt, was_trimmed = _clip_safe_words(base_prompt, max_words=prompt_word_budget)
    return f"{base_prompt}. {FRAMEPACK_QUALITY_SUFFIX}", was_trimmed
