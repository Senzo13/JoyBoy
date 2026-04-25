"""Local non-git storage for CyberAtlas audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.audit_modules.storage import AuditModuleStorage


class CyberAtlasStorage(AuditModuleStorage):
    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__("cyberatlas", root=root)

    def _build_index_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        record = super()._build_index_record(audit)
        summary = audit.get("summary") or {}
        latest = (audit.get("interpretations") or [])[-1] if (audit.get("interpretations") or []) else None
        configured_ai = ((audit.get("metadata") or {}).get("ai") or {})
        record.update({
            "risk_level": summary.get("risk_level") or "unknown",
            "critical_count": summary.get("critical_count", 0),
            "high_count": summary.get("high_count", 0),
            "endpoint_count": summary.get("endpoint_count", 0),
            "exposure_count": summary.get("exposure_count", 0),
            "report_model_label": str((latest or {}).get("model") or configured_ai.get("model") or ""),
            "report_model_state": "generated" if latest else ("planned" if configured_ai.get("model") else "none"),
        })
        return record


_STORAGE: Optional[CyberAtlasStorage] = None


def get_cyberatlas_storage() -> CyberAtlasStorage:
    global _STORAGE
    if _STORAGE is None:
        _STORAGE = CyberAtlasStorage()
    return _STORAGE
