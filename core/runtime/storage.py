"""Shared storage paths for JoyBoy local runtime state."""

from __future__ import annotations

import os
from pathlib import Path


def get_runtime_root() -> Path:
    """Return the local, non-git runtime data directory."""
    configured = os.environ.get("JOYBOY_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".joyboy"
    path = root / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
