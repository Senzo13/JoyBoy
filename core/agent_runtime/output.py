"""Output hygiene helpers for agent tools."""

from __future__ import annotations

import os
from typing import Any, Optional


def truncate_middle(text: Any, max_chars: int = 8000, marker: Optional[str] = None) -> str:
    """Truncate long tool output while preserving the useful head and tail."""
    value = "" if text is None else str(text)
    try:
        limit = int(max_chars)
    except Exception:
        limit = 8000
    if limit <= 0 or len(value) <= limit:
        return value

    notice = marker or "\n... output truncated ...\n"
    if len(notice) >= limit:
        return value[:limit]

    available = limit - len(notice)
    head_chars = max(1, int(available * 0.58))
    tail_chars = max(0, available - head_chars)
    return value[:head_chars] + notice + value[-tail_chars:]


def mask_workspace_paths(text: Any, workspace_path: str, virtual_root: str = "/workspace") -> str:
    """Replace host workspace paths before tool output reaches the model/UI."""
    value = "" if text is None else str(text)
    if not value or not workspace_path:
        return value

    try:
        root = os.path.realpath(os.path.abspath(workspace_path))
    except Exception:
        root = os.path.abspath(str(workspace_path))

    variants = {
        root,
        root.replace("\\", "/"),
        root.replace("/", "\\"),
    }

    try:
        norm = os.path.normpath(root)
        variants.add(norm)
        variants.add(norm.replace("\\", "/"))
        variants.add(norm.replace("/", "\\"))
    except Exception:
        pass

    masked = value
    for variant in sorted((item for item in variants if item), key=len, reverse=True):
        masked = masked.replace(variant, virtual_root)
    return masked
