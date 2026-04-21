"""Shared prompt additions for human pose controls.

These presets are composition helpers. They must stay neutral in the public
core: a pose preset can guide body layout, but it should never imply nudity or
adult output by itself.
"""

from __future__ import annotations


POSE_ALIASES = {
    "lying_down": "lying_face_up",
}


POSE_PROMPTS = {
    "standing_spread": (
        "standing wide stance, feet apart, arms at sides, full body front view, balanced standing pose",
        "sitting, lying down, kneeling, crouching, legs together, legs crossed",
    ),
    "legs_up": (
        "reclined seated pose leaning back with both legs raised, knees bent, low angle foreshortened perspective, feet closer to viewer, full body visible",
        "standing, kneeling, lying flat, overhead view, top-down view, bird eye view, upside down, head at bottom, legs together, legs closed, legs down, side view",
    ),
    "on_all_fours": (
        "hands and knees on the ground, quadruped support pose, neutral tabletop posture, front view",
        "standing, sitting, lying flat, raised legs, kneeling upright",
    ),
    "lying_face_up": (
        "lying on back face up, supine position, arms spread to the sides, legs straight, full body top-down view, laying down",
        "standing, sitting, kneeling, face down, prone, quadruped support pose",
    ),
    "lying_on_stomach": (
        "lying face down on stomach, prone position, arms spread, head turned to side, full body view from above",
        "standing, sitting, kneeling, face up, supine, quadruped support pose",
    ),
    "sitting": (
        "sitting down, relaxed seated position, full body front view",
        "standing, lying down, kneeling, quadruped support pose, walking",
    ),
    "kneeling": (
        "kneeling on both knees, upright torso, arms at sides, full body front view, kneeling position",
        "standing, sitting, lying down, quadruped support pose, walking",
    ),
}


HUMAN_POSE_SAFE_POSITIVE = (
    "fully clothed adult person, opaque everyday clothing, non-explicit presentation"
)


HUMAN_POSE_SAFE_NEGATIVE = (
    "nude, naked, nudity, topless, bare chest, exposed breasts, exposed nipples, "
    "exposed genitals, explicit sexual content, erotic, pornographic, lingerie, "
    "underwear, transparent clothing, see-through clothing"
)


def normalize_pose_name(pose_name: str | None) -> str:
    pose = str(pose_name or "none")
    return POSE_ALIASES.get(pose, pose)


def get_pose_prompts(pose_name: str | None) -> tuple[str | None, str | None]:
    prompts = POSE_PROMPTS.get(normalize_pose_name(pose_name))
    if prompts is None:
        return None, None
    return prompts


def should_force_safe_human_pose(
    prompt: str,
    pose_name: str | None,
    *,
    adult_runtime_available: bool | None = None,
) -> bool:
    """Return True when a human pose preset needs the public-core safety default.

    The rule is intentionally semantic at the product boundary:
    - unknown/no pose: no change
    - adult pack unavailable: never let a pose preset imply adult output
    - adult pack available: still require an explicit adult request
    """
    if normalize_pose_name(pose_name) not in POSE_PROMPTS:
        return False

    if adult_runtime_available is None:
        try:
            from core.infra.packs import is_adult_runtime_available

            adult_runtime_available = is_adult_runtime_available()
        except Exception:
            adult_runtime_available = False

    if not adult_runtime_available:
        return True

    try:
        from core.ai.edit_directives import is_adult_request_heuristic

        return not is_adult_request_heuristic(prompt or "")
    except Exception:
        return True


def build_human_pose_safety_additions(
    prompt: str,
    pose_name: str | None,
    *,
    adult_runtime_available: bool | None = None,
) -> tuple[str | None, str | None]:
    if not should_force_safe_human_pose(
        prompt,
        pose_name,
        adult_runtime_available=adult_runtime_available,
    ):
        return None, None
    return HUMAN_POSE_SAFE_POSITIVE, HUMAN_POSE_SAFE_NEGATIVE


def append_negative_prompt(negative_prompt: str | None, addition: str | None) -> str | None:
    if not addition:
        return negative_prompt
    if negative_prompt:
        return f"{negative_prompt}, {addition}"
    return addition
