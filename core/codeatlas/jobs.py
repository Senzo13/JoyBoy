"""Background jobs for CodeAtlas audits."""

from __future__ import annotations

import threading
from typing import Any, Dict

from core.audit_modules.jobs import build_audit_job_id, update_module_progress
from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso

from .engine import run_codeatlas_audit
from .storage import get_codeatlas_storage


def _job_id(prefix: str, audit_id: str) -> str:
    return build_audit_job_id("codeatlas", prefix, audit_id)


def _update(job_id: str, phase: str, progress: float, message: str) -> None:
    update_module_progress(job_id, "codeatlas", phase, progress, message)


def _previous_audit_for_path(normalized_path: str, exclude_id: str) -> Dict[str, Any] | None:
    storage = get_codeatlas_storage()
    for item in storage.list_audits(120):
        if item.get("id") == exclude_id:
            continue
        audit = storage.get_audit(str(item.get("id") or ""))
        if not audit or audit.get("status") != "done":
            continue
        target = audit.get("target") or {}
        if target.get("normalized_path") == normalized_path:
            return audit
    return None


def _run_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_codeatlas_storage()
    manager = get_job_manager()
    audit = storage.get_audit(audit_id)
    if not audit:
        manager.fail(job_id, "CodeAtlas audit not found")
        return
    try:
        storage.update_audit(audit_id, status="running")
        _update(job_id, "scan", 18, "Scanning project structure")
        project_path = str((audit.get("target") or {}).get("normalized_path") or payload.get("project_path") or "")
        previous = _previous_audit_for_path(project_path, audit_id)
        _update(job_id, "audit", 54, "Scoring backend, frontend and regression risk")
        result = run_codeatlas_audit(project_path, previous=previous)
        if manager.is_cancel_requested(job_id):
            storage.update_audit(audit_id, status="cancelled")
            manager.cancel(job_id, "CodeAtlas audit cancelled")
            return
        updated = storage.get_audit(audit_id) or audit
        updated.update(
            target=result["target"],
            summary=result["summary"],
            snapshot=result["snapshot"],
            findings=result["findings"],
            scores=result["scores"],
            remediation_items=result["remediation_items"],
            status="done",
            updated_at=utc_now_iso(),
        )
        storage.save_audit(updated)
        manager.complete(
            job_id,
            artifact={"module_id": "codeatlas", "audit_id": audit_id, "title": updated.get("title")},
            message="CodeAtlas audit complete",
        )
    except Exception as exc:
        storage.update_audit(audit_id, status="error", metadata={"error": str(exc)})
        manager.fail(job_id, str(exc))


def start_codeatlas_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    from core.audit_modules.workspace_scan import normalize_workspace_target

    storage = get_codeatlas_storage()
    target = normalize_workspace_target(str(payload.get("project_path") or payload.get("target") or ""))
    title = str(payload.get("title") or target.get("host") or "CodeAtlas audit")
    audit = storage.create_audit_stub(
        target=target,
        title=title,
        options=payload.get("options") or {},
        metadata={"module_id": "codeatlas", "estimated_seconds": 20},
    )
    job_id = _job_id("audit", audit["id"])
    job = get_job_manager().create(
        "codeatlas",
        job_id=job_id,
        prompt=target["normalized_path"],
        metadata={"module_id": "codeatlas", "audit_id": audit["id"], "estimated_seconds": 20},
    )
    thread = threading.Thread(target=_run_job, args=(job_id, audit["id"], payload), daemon=True)
    thread.start()
    return {"audit": audit, "job": job}
