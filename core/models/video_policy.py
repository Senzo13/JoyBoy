"""Runtime policy for video model selection.

The goal is not to hide advanced models, but to prevent known-bad low-VRAM
paths from silently hanging the app. Heavy experimental backends remain
available behind explicit environment overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


LOW_VRAM_LIMIT_GB = 10.0
LOW_VRAM_SAFE_DEFAULT = "svd"
MISSING_VIDEO_BACKEND_MODELS = set()
LOW_VRAM_BLOCKED_MODELS = {
    "cogvideox",
    "cogvideox-q4",
    "cogvideox-2b",
    "fastwan",
    "framepack",
    "framepack-fast",
    "hunyuan",
    "ltx",
    "ltx2",
    "ltx2_fp8",
    "wan",
    "wan22",
    "wan22-5b",
    "wan22-t2v-14b",
    "wan-native-5b",
    "wan-native-14b",
}
EXPERIMENTAL_VIDEO_ENV = "JOYBOY_ALLOW_EXPERIMENTAL_VIDEO"
EXPERIMENTAL_COGVIDEO_ENV = "JOYBOY_ALLOW_EXPERIMENTAL_COGVIDEO_8GB"

LOW_VRAM_DEFAULT_OVERRIDES: dict[str, dict[str, Any]] = {
    # SVD is the only always-on 8GB I2V path in JoyBoy today. Keep it compact
    # enough to stay GPU-direct; CPU offload fits in memory but is painfully slow.
    "svd": {"default_frames": 18, "default_steps": 10, "default_fps": 8},
    # LTX can be very fast with the dedicated Q8 stack, but JoyBoy's current
    # Diffusers loader is not that stack. If forced, cap it hard.
    "ltx": {"default_frames": 41, "default_steps": 8, "default_fps": 8},
    # FramePack is now wired through Diffusers. On 8GB, expose honest presets:
    # normal keeps motion quality; fast is a quick 5s smoke test.
    "framepack": {"default_frames": 90, "default_steps": 9, "default_fps": 18},
    "framepack-fast": {"default_frames": 60, "default_steps": 7, "default_fps": 12},
}


@dataclass(frozen=True)
class VideoModelDecision:
    requested_model: str
    model: str
    changed: bool = False
    warning: str | None = None


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def allow_experimental_video(explicit: bool = False) -> bool:
    """Return True when the user explicitly opts into experimental video paths."""
    return bool(explicit) or _env_enabled(EXPERIMENTAL_VIDEO_ENV) or _env_enabled(EXPERIMENTAL_COGVIDEO_ENV)


def is_low_vram(vram_gb: float | int | None) -> bool:
    return bool(vram_gb and 0 < float(vram_gb) <= LOW_VRAM_LIMIT_GB)


def resolve_video_model_for_runtime(
    requested_model: str | None,
    *,
    vram_gb: float | int | None,
    allow_experimental: bool = False,
) -> VideoModelDecision:
    """Resolve the model JoyBoy should actually run for the current machine.

    A backend may technically fit in 8GB VRAM and still be a bad default if it
    depends on CPU offload, long decode paths, or optional kernels we do not
    ship. Keep these paths opt-in until JoyBoy has a proven low-VRAM loader for
    them.
    """
    requested = (requested_model or LOW_VRAM_SAFE_DEFAULT).strip() or LOW_VRAM_SAFE_DEFAULT

    if requested in MISSING_VIDEO_BACKEND_MODELS:
        return VideoModelDecision(
            requested_model=requested,
            model=LOW_VRAM_SAFE_DEFAULT,
            changed=True,
            warning=(
                f"{requested} est visible dans la roadmap, mais le moteur JoyBoy natif "
                f"n'est pas encore integre. Ce modele n'est donc pas lancable pour "
                f"l'instant. JoyBoy utilise {LOW_VRAM_SAFE_DEFAULT} a la place."
            ),
        )

    if is_low_vram(vram_gb) and requested in LOW_VRAM_BLOCKED_MODELS and not allow_experimental_video(allow_experimental):
        return VideoModelDecision(
            requested_model=requested,
            model=LOW_VRAM_SAFE_DEFAULT,
            changed=True,
            warning=(
                f"{requested} est masque sur <= {LOW_VRAM_LIMIT_GB:.0f}GB VRAM: ce backend JoyBoy "
                f"n'a pas encore un profil rapide et fiable sur 8GB. JoyBoy utilise "
                f"{LOW_VRAM_SAFE_DEFAULT} a la place. "
                f"Pour forcer quand meme: {EXPERIMENTAL_VIDEO_ENV}=1."
            ),
        )

    return VideoModelDecision(requested_model=requested, model=requested)


def _launch_status(model_id: str, meta: dict[str, Any], category: str) -> str:
    """Return a stable frontend state for whether the model can be launched."""
    if meta.get("backend_status") == "adapter_required":
        return "missing_backend"
    if category == "try" and model_id in LOW_VRAM_BLOCKED_MODELS:
        return "manual_test"
    return "ready"


def _public_model_entry(
    model_id: str,
    meta: dict[str, Any],
    category: str,
    *,
    experimental_enabled: bool = False,
) -> dict[str, Any]:
    launch_status = _launch_status(model_id, meta, category)
    requires_experimental_env = launch_status == "manual_test"
    return {
        "id": model_id,
        "name": meta.get("name", model_id),
        "description": meta.get("description", ""),
        "vram": meta.get("vram", ""),
        "category": category,
        "supports_prompt": bool(meta.get("supports_prompt", False)),
        "supports_image": bool(meta.get("supports_image", False)),
        "default_frames": int(meta.get("default_frames", 32)),
        "default_steps": int(meta.get("default_steps", 20)),
        "default_fps": int(meta.get("default_fps", 8)),
        "quant": meta.get("quant"),
        "experimental_low_vram": bool(meta.get("experimental_low_vram", False)),
        "backend_status": meta.get("backend_status", "ready"),
        "launch_status": launch_status,
        "requires_experimental_env": requires_experimental_env,
        "experimental_enabled": bool(experimental_enabled),
        "override_required": requires_experimental_env and not experimental_enabled,
    }


def _apply_low_vram_defaults(model_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of model metadata with conservative <=10GB defaults."""
    override = LOW_VRAM_DEFAULT_OVERRIDES.get(model_id)
    if not override:
        return meta
    return {**meta, **override}


def get_runtime_video_defaults(
    model_id: str,
    meta: dict[str, Any] | None,
    *,
    vram_gb: float | int | None,
) -> dict[str, int]:
    """Return safe generation defaults for a model on the current machine."""
    effective_meta = dict(meta or {})
    if is_low_vram(vram_gb):
        effective_meta = _apply_low_vram_defaults(model_id, effective_meta)
    return {
        "default_frames": int(effective_meta.get("default_frames", 32)),
        "default_steps": int(effective_meta.get("default_steps", 20)),
        "default_fps": int(effective_meta.get("default_fps", 8)),
    }


def _low_vram_category(model_id: str, meta: dict[str, Any]) -> str:
    if meta.get("hidden"):
        return "hidden"
    if meta.get("backend_status") == "adapter_required":
        return "unavailable"
    if meta.get("experimental_low_vram"):
        return "try"
    tier = str(meta.get("low_vram_tier") or "").strip().lower()
    if tier == "advanced":
        return "try"
    if tier in {"recommended", "compatible", "try", "unavailable", "hidden"}:
        return tier
    return "try"


def _normal_vram_category(meta: dict[str, Any]) -> str:
    if meta.get("hidden"):
        return "hidden"
    if meta.get("backend_status") == "adapter_required":
        return "unavailable"
    if meta.get("experimental_low_vram"):
        return "try"
    return "compatible"


def build_video_model_catalog(
    video_models: dict[str, dict[str, Any]],
    *,
    vram_gb: float | int | None,
    include_advanced: bool = False,
    allow_experimental: bool = False,
) -> dict[str, Any]:
    """Return the frontend-ready model list for this machine.

    The UI should not decide hardware compatibility from labels. It consumes
    this catalog and only renders the models the backend marks as visible.
    """
    low_vram = is_low_vram(vram_gb)
    experimental_enabled = allow_experimental_video(allow_experimental)
    visible: list[dict[str, Any]] = []
    advanced: list[dict[str, Any]] = []
    roadmap: list[dict[str, Any]] = []

    for model_id, meta in video_models.items():
        if low_vram:
            meta = _apply_low_vram_defaults(model_id, meta)
        category = _low_vram_category(model_id, meta) if low_vram else _normal_vram_category(meta)
        entry = _public_model_entry(
            model_id,
            meta,
            category,
            experimental_enabled=experimental_enabled,
        )

        if category == "hidden":
            continue
        if category == "unavailable":
            roadmap.append(entry)
            continue
        if category in {"try", "advanced"}:
            advanced.append(entry)
            if not include_advanced:
                continue
        visible.append(entry)

    rank = {"recommended": 0, "compatible": 1, "try": 2, "advanced": 2, "unavailable": 3}
    visible.sort(key=lambda item: (rank.get(item["category"], 9), item["name"].lower()))
    advanced.sort(key=lambda item: item["name"].lower())
    roadmap.sort(key=lambda item: item["name"].lower())

    default_model = LOW_VRAM_SAFE_DEFAULT if low_vram else (visible[0]["id"] if visible else LOW_VRAM_SAFE_DEFAULT)
    if not any(item["id"] == default_model for item in visible) and visible:
        default_model = visible[0]["id"]

    return {
        "vram_gb": float(vram_gb or 0),
        "low_vram": low_vram,
        "default_model": default_model,
        "models": visible,
        "advanced_models": advanced,
        "advanced_count": len(advanced),
        "roadmap_models": roadmap,
        "roadmap_count": len(roadmap),
        "experimental_enabled": experimental_enabled,
        "experimental_override_env": EXPERIMENTAL_VIDEO_ENV,
    }


def assert_cogvideox_allowed_on_low_vram(model_name: str, *, vram_gb: float | int | None) -> None:
    """Guard direct loader calls that bypass the Flask route policy."""
    if is_low_vram(vram_gb) and model_name in LOW_VRAM_BLOCKED_MODELS and not allow_experimental_video():
        raise RuntimeError(
            f"{model_name} est desactive sur <= {LOW_VRAM_LIMIT_GB:.0f}GB VRAM car ce chemin "
            f"Diffusers/Q4 peut rester bloque a 0%. Utilise LTX-Video 2B/SVD, ou force avec "
            f"{EXPERIMENTAL_VIDEO_ENV}=1 si tu veux tester ce backend experimental."
        )
