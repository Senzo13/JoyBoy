"""Shared job helpers for native audit modules."""

from __future__ import annotations

from core.runtime import get_job_manager


def build_audit_job_id(module_id: str, prefix: str, audit_id: str) -> str:
    clean_module = str(module_id or "").strip().lower() or "audit"
    clean_prefix = str(prefix or "job").strip().lower() or "job"
    clean_audit_id = str(audit_id or "").strip()
    return f"{clean_module}-{clean_prefix}-{clean_audit_id}"


def update_module_progress(job_id: str, module_id: str, phase: str, progress: float, message: str) -> None:
    get_job_manager().update(
        job_id,
        status="running",
        phase=phase,
        progress=progress,
        message=message,
        metadata={"module_id": str(module_id or "").strip().lower() or "audit"},
    )
