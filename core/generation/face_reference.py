"""
Face reference policy helpers.

IP-Adapter FaceID is useful, but it can fight the prompt when a generation is
about full-body composition, action poses, style transfer, or ControlNet. Keep
the face identity hint lighter in those cases and reserve stronger weights for
actual portrait/close-up prompts.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_FACE_FOCUSED_RE = re.compile(
    r"\b("
    r"face|facial|portrait|headshot|head shot|close[- ]?up|closeup|"
    r"avatar|profile picture|profile photo|bust shot|head and shoulders|"
    r"visage|portrait|gros plan|photo de profil|"
    r"rostro|retrato|primer plano|"
    r"viso|ritratto|primo piano"
    r")\b",
    re.IGNORECASE,
)

_FULL_BODY_OR_ACTION_RE = re.compile(
    r"\b("
    r"full[- ]body|entire body|whole body|body shot|feet|bare feet|legs?|arms?|"
    r"standing|sitting|kneeling|lying|reclined|crouching|walking|running|"
    r"pose|posing|dynamic pose|action pose|on all fours|hands and knees|"
    r"corps entier|pieds?|jambes?|bras|debout|assis|assise|agenouille|allonge|pose|"
    r"cuerpo entero|pies|piernas|brazos|de pie|sentad[oa]|arrodillad[oa]|pose|"
    r"corpo intero|piedi|gambe|braccia|in piedi|sedut[oa]|inginocchiat[oa]|posa"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FaceReferencePolicy:
    requested_scale: float
    scale: float
    cap: float
    reason: str
    face_focused: bool
    composition_heavy: bool

    @property
    def was_adjusted(self) -> bool:
        return abs(self.scale - self.requested_scale) > 1e-6


def _clamp_float(value, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def resolve_text2img_face_reference_policy(
    prompt: str,
    requested_scale=0.35,
    *,
    has_style_ref: bool = False,
    has_pose_control: bool = False,
) -> FaceReferencePolicy:
    """Return the safe FaceID scale for a text2img generation.

    Higher scales can be useful for portraits, but on full-body generations they
    often deform anatomy because the face identity signal is injected globally.
    """
    requested = _clamp_float(requested_scale, default=0.35)
    normalized_prompt = prompt or ""
    face_focused = bool(_FACE_FOCUSED_RE.search(normalized_prompt))
    composition_heavy = (
        bool(_FULL_BODY_OR_ACTION_RE.search(normalized_prompt))
        or has_style_ref
        or has_pose_control
    )

    cap = 0.35
    reasons = []

    if not face_focused:
        # Base FaceID SDXL is a weak identity adapter, not a full composition lock.
        cap = min(cap, 0.22)
        reasons.append("general/full-body prompt")

    if composition_heavy:
        cap = min(cap, 0.20)
        reasons.append("composition-heavy prompt")

    if has_style_ref:
        # Style/img2img already anchors the full image, so FaceID should stay a hint.
        cap = min(cap, 0.16)
        reasons.append("style reference active")

    if has_pose_control:
        # ControlNet and FaceID both steer structure; keep FaceID weaker to avoid
        # the face embedding bleeding into body geometry.
        cap = min(cap, 0.14)
        reasons.append("pose/controlnet active")

    scale = min(requested, cap)
    if not reasons:
        reasons.append("portrait/face-focused prompt")

    return FaceReferencePolicy(
        requested_scale=requested,
        scale=scale,
        cap=cap,
        reason=", ".join(reasons),
        face_focused=face_focused,
        composition_heavy=composition_heavy,
    )


def merge_faceid_embeddings(face_embeddings):
    """Average several FaceID embeddings into one normalized identity hint.

    Current FaceID SDXL weights expect a single negative/positive pair shaped
    like [2, 1, 512]. Averaging lets users provide 2-5 clean photos without
    changing the downstream Diffusers call.
    """
    valid = [emb for emb in face_embeddings if emb is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    import torch

    refs = []
    for emb in valid:
        if not hasattr(emb, "shape") or len(emb.shape) != 3 or emb.shape[0] < 2:
            continue
        refs.append(emb[1:2])

    if not refs:
        return None
    if len(refs) == 1:
        neg = torch.zeros_like(refs[0])
        return torch.cat([neg, refs[0]], dim=0)

    merged_ref = torch.stack(refs, dim=0).mean(dim=0)
    merged_ref = merged_ref / merged_ref.norm(dim=-1, keepdim=True).clamp_min(1e-6)
    neg = torch.zeros_like(merged_ref)
    return torch.cat([neg, merged_ref], dim=0)
