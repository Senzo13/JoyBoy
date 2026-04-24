"""Local non-git storage for SignalAtlas audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.audit_modules.storage import AuditModuleStorage


class SignalAtlasStorage(AuditModuleStorage):
    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__("signalatlas", root=root)

    def _build_index_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        record = super()._build_index_record(audit)
        latest = (audit.get("interpretations") or [])[-1] if (audit.get("interpretations") or []) else None
        configured_ai = ((audit.get("metadata") or {}).get("ai") or {})
        record.update({
            "report_model_label": str((latest or {}).get("model") or configured_ai.get("model") or ""),
            "report_model_state": "generated" if latest else ("planned" if configured_ai.get("model") else "none"),
        })
        return record


_STORAGE: Optional[SignalAtlasStorage] = None


def get_signalatlas_storage() -> SignalAtlasStorage:
    global _STORAGE
    if _STORAGE is None:
        _STORAGE = SignalAtlasStorage()
    return _STORAGE
