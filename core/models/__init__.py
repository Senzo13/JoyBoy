"""Model management package.

The heavy legacy module imports torch and probes the local GPU at import time.
Keep this package lightweight so pure-Python modules such as video_policy can be
tested in CI without installing the full ML runtime. Runtime callers still use
``from core.models import X``; unknown attributes are resolved lazily from
``core.models._legacy`` on first access.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any


_lazy_legacy_module: ModuleType | None = None


def _load_legacy_module() -> ModuleType:
    global _lazy_legacy_module
    if _lazy_legacy_module is None:
        _lazy_legacy_module = importlib.import_module("core.models._legacy")
    return _lazy_legacy_module


def __getattr__(name: str) -> Any:
    module = _load_legacy_module()
    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(f"module 'core.models' has no attribute {name!r}") from exc
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_load_legacy_module())))
