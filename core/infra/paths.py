"""Shared filesystem paths for JoyBoy runtime data.

The repository remains the default storage root in dev mode, while packaged
launchers can redirect heavy/user-owned data through environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def get_joyboy_home() -> Path:
    return _env_path("JOYBOY_HOME") or Path("~/.joyboy").expanduser()


def get_models_dir() -> Path:
    return _env_path("JOYBOY_MODELS_DIR") or (PROJECT_DIR / "models")


def get_huggingface_cache_dir() -> Path:
    return _env_path("JOYBOY_HF_CACHE_DIR") or (get_models_dir() / "huggingface")


def get_packs_dir() -> Path:
    return _env_path("JOYBOY_PACKS_DIR") or (get_joyboy_home() / "packs")


def get_output_dir() -> Path:
    return _env_path("JOYBOY_OUTPUT_DIR") or (PROJECT_DIR / "output")
