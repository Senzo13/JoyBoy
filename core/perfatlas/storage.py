"""Local non-git storage for PerfAtlas audits."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.audit_modules.storage import AuditModuleStorage


class PerfAtlasStorage(AuditModuleStorage):
    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__("perfatlas", root=root)

    def _build_index_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        record = super()._build_index_record(audit)
        summary = audit.get("summary") or {}
        latest = (audit.get("interpretations") or [])[-1] if (audit.get("interpretations") or []) else None
        configured_ai = ((audit.get("metadata") or {}).get("ai") or {})
        record.update({
            "lab_pages_analyzed": summary.get("lab_pages_analyzed", 0),
            "field_data_available": bool(summary.get("field_data_available")),
            "lab_data_available": bool(summary.get("lab_data_available")),
            "runtime_runner": summary.get("runtime_runner") or "",
            "owner_integrations_count": summary.get("owner_integrations_count", 0),
            "report_model_label": str((latest or {}).get("model") or configured_ai.get("model") or ""),
            "report_model_state": "generated" if latest else ("planned" if configured_ai.get("model") else "none"),
        })
        return record

    def find_previous_completed_audit(self, *, host: str, exclude_id: str = "") -> Optional[Dict[str, Any]]:
        clean_host = str(host or "").strip().lower()
        clean_exclude = str(exclude_id or "").strip()
        if not clean_host:
            return None
        for item in self.list_audits(200):
            if str(item.get("id") or "").strip() == clean_exclude:
                continue
            if str(item.get("status") or "").strip().lower() != "done":
                continue
            if str(item.get("host") or "").strip().lower() != clean_host:
                continue
            audit = self.get_audit(str(item.get("id") or ""))
            if audit:
                return audit
        return None


_STORAGE: Optional[PerfAtlasStorage] = None


def get_perfatlas_storage() -> PerfAtlasStorage:
    global _STORAGE
    if _STORAGE is None:
        _STORAGE = PerfAtlasStorage()
    return _STORAGE
