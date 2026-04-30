"""Background jobs and safe file application for AgentGuide."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

from core.audit_modules.jobs import build_audit_job_id, update_module_progress
from core.audit_modules.workspace_scan import normalize_workspace_target
from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso

from .engine import generate_agentguide
from .storage import get_agentguide_storage


def _job_id(prefix: str, audit_id: str) -> str:
    return build_audit_job_id("agentguide", prefix, audit_id)


def _update(job_id: str, phase: str, progress: float, message: str) -> None:
    update_module_progress(job_id, "agentguide", phase, progress, message)


def _run_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_agentguide_storage()
    manager = get_job_manager()
    audit = storage.get_audit(audit_id)
    if not audit:
        manager.fail(job_id, "AgentGuide audit not found")
        return
    try:
        storage.update_audit(audit_id, status="running")
        project_path = str((audit.get("target") or {}).get("normalized_path") or payload.get("project_path") or "")
        _update(job_id, "scan", 20, "Scanning project conventions and existing agent files")
        result = generate_agentguide(project_path)
        _update(job_id, "generate", 78, "Generating AGENTS.md and CLAUDE.md proposals")
        if manager.is_cancel_requested(job_id):
            storage.update_audit(audit_id, status="cancelled")
            manager.cancel(job_id, "AgentGuide cancelled")
            return
        updated = storage.get_audit(audit_id) or audit
        updated.update(
            target=result["target"],
            summary=result["summary"],
            snapshot=result["snapshot"],
            findings=result["findings"],
            scores=result["scores"],
            remediation_items=result["remediation_items"],
            metadata={**dict(updated.get("metadata") or {}), "generated_files": result["generated_files"]},
            status="done",
            updated_at=utc_now_iso(),
        )
        storage.save_audit(updated)
        manager.complete(
            job_id,
            artifact={"module_id": "agentguide", "audit_id": audit_id, "title": updated.get("title")},
            message="AgentGuide proposals ready",
        )
    except Exception as exc:
        storage.update_audit(audit_id, status="error", metadata={"error": str(exc)})
        manager.fail(job_id, str(exc))


def start_agentguide_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    storage = get_agentguide_storage()
    target = normalize_workspace_target(str(payload.get("project_path") or payload.get("target") or ""))
    title = str(payload.get("title") or f"AgentGuide - {target.get('host')}")
    audit = storage.create_audit_stub(
        target=target,
        title=title,
        options=payload.get("options") or {},
        metadata={"module_id": "agentguide", "estimated_seconds": 12, "generated_files": []},
    )
    job_id = _job_id("audit", audit["id"])
    job = get_job_manager().create(
        "agentguide",
        job_id=job_id,
        prompt=target["normalized_path"],
        metadata={"module_id": "agentguide", "audit_id": audit["id"], "estimated_seconds": 12},
    )
    thread = threading.Thread(target=_run_job, args=(job_id, audit["id"], payload), daemon=True)
    thread.start()
    return {"audit": audit, "job": job}


def apply_agentguide_files(audit_id: str, file_paths: List[str] | None = None) -> Dict[str, Any]:
    storage = get_agentguide_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        raise ValueError("Audit AgentGuide introuvable.")
    target = audit.get("target") or {}
    root = Path(str(target.get("normalized_path") or "")).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Dossier projet introuvable.")
    generated = list((audit.get("metadata") or {}).get("generated_files") or [])
    allowed = {str(path).strip() for path in (file_paths or []) if str(path).strip()}
    applied = []
    for item in generated:
        rel = str(item.get("path") or "").strip().replace("\\", "/")
        if not rel or (allowed and rel not in allowed):
            continue
        destination = (root / rel).resolve()
        if not destination.is_relative_to(root):
            raise ValueError(f"Chemin refusé: {rel}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if destination.exists():
            backup = destination.with_suffix(destination.suffix + f".bak-{audit_id[:8]}")
            backup.write_text(destination.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        destination.write_text(str(item.get("content") or ""), encoding="utf-8")
        applied.append({"path": rel, "backup": str(backup) if backup else ""})
    audit.setdefault("metadata", {})["applied_files"] = applied
    audit["updated_at"] = utc_now_iso()
    storage.save_audit(audit)
    return {"applied": applied, "audit": audit}
