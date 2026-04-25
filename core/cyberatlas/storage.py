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
        comparison = audit.get("comparison") or {}
        record.update({
            "risk_level": summary.get("risk_level") or "unknown",
            "security_grade": summary.get("security_grade") or "",
            "critical_count": summary.get("critical_count", 0),
            "high_count": summary.get("high_count", 0),
            "endpoint_count": summary.get("endpoint_count", 0),
            "discovered_endpoint_count": summary.get("discovered_endpoint_count", 0),
            "public_sensitive_endpoint_count": summary.get("public_sensitive_endpoint_count", 0),
            "exposure_count": summary.get("exposure_count", 0),
            "source_map_count": summary.get("source_map_count", 0),
            "reachable_source_map_count": summary.get("reachable_source_map_count", 0),
            "third_party_script_without_sri_count": summary.get("third_party_script_without_sri_count", 0),
            "coverage_confidence": summary.get("coverage_confidence", 0),
            "owner_verification_count": summary.get("owner_verification_count", 0),
            "attack_path_count": summary.get("attack_path_count", 0),
            "standard_attention_count": summary.get("standard_attention_count", 0),
            "standard_owner_review_count": summary.get("standard_owner_review_count", 0),
            "security_ticket_count": summary.get("security_ticket_count", 0),
            "evidence_graph_node_count": summary.get("evidence_graph_node_count", 0),
            "dangerous_method_count": summary.get("dangerous_method_count", 0),
            "waf_detected": bool(summary.get("waf_detected")),
            "rate_limit_detected": bool(summary.get("rate_limit_detected")),
            "comparison_status": comparison.get("status") or "",
            "score_delta": comparison.get("score_delta", 0),
            "high_delta": comparison.get("high_delta", 0),
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
