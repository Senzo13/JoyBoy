"""Background jobs for CyberAtlas audits and AI interpretation."""

from __future__ import annotations

import threading
from typing import Any, Dict

from core.audit_modules.jobs import build_audit_job_id, update_module_progress
from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso

from .engine import run_site_audit
from .llm_adapter import generate_interpretation
from .storage import get_cyberatlas_storage


def _job_id(prefix: str, audit_id: str) -> str:
    return build_audit_job_id("cyberatlas", prefix, audit_id)


def _update_progress(job_id: str, phase: str, progress: float, message: str) -> None:
    update_module_progress(job_id, "cyberatlas", phase, progress, message)


def _estimate_audit_seconds(options: Dict[str, Any], ai_config: Dict[str, Any]) -> int:
    try:
        max_pages = max(1, int(options.get("max_pages") or 8))
    except (TypeError, ValueError):
        max_pages = 8
    try:
        max_endpoints = max(1, int(options.get("max_endpoints") or 32))
    except (TypeError, ValueError):
        max_endpoints = 32
    crawl_seconds = 10 + min(max_pages, 24) * 2
    probe_seconds = 10 + min(max_endpoints, 80) * 0.18
    tls_seconds = 5
    level = str(ai_config.get("level") or "basic_summary").strip().lower()
    ai_seconds = {
        "no_ai": 0,
        "basic_summary": 20,
        "full_expert_analysis": 50,
        "ai_remediation_pack": 75,
    }.get(level, 40)
    return int(max(28, min(900, crawl_seconds + probe_seconds + tls_seconds + ai_seconds)))


def _build_audit_comparison(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    previous_summary = previous.get("summary") or {}
    current_summary = current.get("summary") or {}

    def number_delta(key: str) -> float:
        try:
            return round(float(current_summary.get(key) or 0) - float(previous_summary.get(key) or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    previous_findings = previous.get("findings") or []
    current_findings = current.get("findings") or []
    previous_ids = {str(item.get("id") or "") for item in previous_findings if item.get("id")}
    current_ids = {str(item.get("id") or "") for item in current_findings if item.get("id")}
    new_ids = current_ids - previous_ids
    fixed_ids = previous_ids - current_ids
    score_delta = number_delta("global_score")
    high_delta = int(number_delta("high_count"))
    critical_delta = int(number_delta("critical_count"))
    if critical_delta > 0 or high_delta > 1 or score_delta <= -5:
        status = "regressed"
    elif critical_delta < 0 or high_delta < 0 or score_delta >= 5 or fixed_ids:
        status = "improved"
    else:
        status = "stable"
    return {
        "previous_audit_id": previous.get("id") or "",
        "previous_updated_at": previous.get("updated_at") or previous.get("created_at") or "",
        "status": status,
        "score_delta": score_delta,
        "critical_delta": critical_delta,
        "high_delta": high_delta,
        "endpoint_delta": int(number_delta("endpoint_count")),
        "public_sensitive_delta": int(number_delta("public_sensitive_endpoint_count")),
        "source_map_delta": int(number_delta("source_map_count")),
        "new_finding_ids": sorted(new_ids)[:20],
        "fixed_finding_ids": sorted(fixed_ids)[:20],
    }


def _latest_completed_audit_for_target(storage: Any, current_audit: Dict[str, Any]) -> Dict[str, Any]:
    target = current_audit.get("target") or {}
    host = str(target.get("host") or "").strip().lower()
    current_id = str(current_audit.get("id") or "")
    if not host:
        return {}
    for record in storage.list_audits(limit=120):
        if str(record.get("id") or "") == current_id:
            continue
        if str(record.get("status") or "").lower() != "done":
            continue
        if str(record.get("host") or "").strip().lower() != host:
            continue
        previous = storage.get_audit(str(record.get("id") or ""))
        if previous:
            return previous
    return {}


def _run_audit_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_cyberatlas_storage()
    manager = get_job_manager()
    audit = storage.get_audit(audit_id)
    if not audit:
        manager.fail(job_id, "CyberAtlas audit not found")
        return

    try:
        storage.update_audit(audit_id, status="running")
        options = audit.get("options") or {}

        def cancel_check() -> bool:
            return manager.is_cancel_requested(job_id)

        result = run_site_audit(
            audit["target"]["normalized_url"],
            mode=str(audit.get("target", {}).get("mode") or "public"),
            max_pages=int(options.get("max_pages") or 8),
            max_endpoints=int(options.get("max_endpoints") or 32),
            active_checks=bool(options.get("active_checks")),
            progress_callback=lambda phase, progress, message: _update_progress(job_id, phase, progress, message),
            cancel_check=cancel_check,
        )
        if cancel_check():
            storage.update_audit(audit_id, status="cancelled")
            manager.cancel(job_id, "CyberAtlas audit cancelled")
            return

        updated = storage.get_audit(audit_id) or audit
        updated.update(
            summary=result["summary"],
            snapshot=result["snapshot"],
            findings=result["findings"],
            scores=result["scores"],
            remediation_items=result["remediation_items"],
            recommendations=result.get("recommendations") or [],
            action_plan=result.get("action_plan") or [],
            owner_verification_plan=result.get("owner_verification_plan") or [],
            attack_paths=result.get("attack_paths") or [],
            coverage=result.get("coverage") or {},
            standard_map=result.get("standard_map") or [],
            security_tickets=result.get("security_tickets") or [],
            evidence_graph=result.get("evidence_graph") or {},
            owner_context=result["owner_context"],
            status="done",
            updated_at=utc_now_iso(),
        )
        previous = _latest_completed_audit_for_target(storage, updated)
        updated["comparison"] = _build_audit_comparison(previous, updated) if previous else {
            "status": "baseline",
            "previous_audit_id": "",
            "score_delta": 0,
            "critical_delta": 0,
            "high_delta": 0,
            "endpoint_delta": 0,
            "public_sensitive_delta": 0,
            "source_map_delta": 0,
            "new_finding_ids": [],
            "fixed_finding_ids": [],
        }

        ai_config = payload.get("ai") or {}
        if ai_config.get("level") and str(ai_config.get("level")).lower() != "no_ai":
            _update_progress(job_id, "ai", 92, "Generating defensive AI interpretation")
            interpretation = generate_interpretation(
                updated,
                model=str(ai_config.get("model") or ""),
                level=str(ai_config.get("level") or "basic_summary"),
                preset=str(ai_config.get("preset") or "balanced"),
                mode="initial",
            )
            updated["interpretations"] = [interpretation]

        storage.save_audit(updated)
        manager.complete(
            job_id,
            artifact={
                "module_id": "cyberatlas",
                "audit_id": audit_id,
                "title": updated.get("title"),
            },
            message="CyberAtlas audit complete",
        )
    except Exception as exc:
        storage.update_audit(audit_id, status="error", metadata={"error": str(exc)})
        manager.fail(job_id, str(exc))


def start_cyberatlas_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    storage = get_cyberatlas_storage()
    target = payload.get("target") or {}
    title = payload.get("title") or (target.get("host") or target.get("normalized_url") or "CyberAtlas audit")
    options = payload.get("options") or {}
    ai_config = payload.get("ai") or {}
    estimated_seconds = _estimate_audit_seconds(options, ai_config)
    audit = storage.create_audit_stub(
        target=target,
        title=title,
        options=options,
        metadata={
            "module_id": "cyberatlas",
            "ai": ai_config,
            "estimated_seconds": estimated_seconds,
            "safe_scope": "defensive_http_evidence",
        },
    )
    job_id = _job_id("audit", audit["id"])
    job = get_job_manager().create(
        "cyberatlas",
        job_id=job_id,
        prompt=audit["target"]["normalized_url"],
        metadata={
            "module_id": "cyberatlas",
            "audit_id": audit["id"],
            "estimated_seconds": estimated_seconds,
            "requested_max_pages": options.get("max_pages"),
            "requested_max_endpoints": options.get("max_endpoints"),
            "active_checks": bool(options.get("active_checks")),
            "ai_level": ai_config.get("level") or "",
        },
    )
    thread = threading.Thread(target=_run_audit_job, args=(job_id, audit["id"], payload), daemon=True)
    thread.start()
    return {"audit": audit, "job": job}


def _run_rerun_ai_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_cyberatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        get_job_manager().fail(job_id, "CyberAtlas audit not found")
        return
    try:
        _update_progress(job_id, "ai", 30, "Preparing defensive audit excerpt")
        interpretation = generate_interpretation(
            audit,
            model=str(payload.get("model") or ""),
            level=str(payload.get("level") or "basic_summary"),
            preset=str(payload.get("preset") or "balanced"),
            mode="rerun",
        )
        audit.setdefault("interpretations", []).append(interpretation)
        audit["updated_at"] = utc_now_iso()
        storage.save_audit(audit)
        get_job_manager().complete(
            job_id,
            artifact={"module_id": "cyberatlas", "audit_id": audit_id},
            message="CyberAtlas AI interpretation ready",
        )
    except Exception as exc:
        get_job_manager().fail(job_id, str(exc))


def start_cyberatlas_ai_rerun(audit_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = _job_id("ai", audit_id)
    job = get_job_manager().create(
        "cyberatlas",
        job_id=job_id,
        prompt=f"CyberAtlas AI rerun {audit_id}",
        metadata={"module_id": "cyberatlas", "audit_id": audit_id},
    )
    thread = threading.Thread(target=_run_rerun_ai_job, args=(job_id, audit_id, payload), daemon=True)
    thread.start()
    return {"job": job}


def _run_compare_ai_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_cyberatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        get_job_manager().fail(job_id, "CyberAtlas audit not found")
        return
    try:
        left_model = str(payload.get("left_model") or "")
        right_model = str(payload.get("right_model") or "")
        level = str(payload.get("level") or "full_expert_analysis")
        preset = str(payload.get("preset") or "expert")
        _update_progress(job_id, "ai", 24, "Generating first defensive interpretation")
        left = generate_interpretation(audit, model=left_model, level=level, preset=preset, mode="compare-left")
        _update_progress(job_id, "ai", 72, "Generating second defensive interpretation")
        right = generate_interpretation(audit, model=right_model, level=level, preset=preset, mode="compare-right")
        audit.setdefault("interpretations", []).extend([left, right])
        audit["metadata"] = dict(audit.get("metadata") or {}, compare_pair={"left": left_model, "right": right_model})
        audit["updated_at"] = utc_now_iso()
        storage.save_audit(audit)
        get_job_manager().complete(
            job_id,
            artifact={
                "module_id": "cyberatlas",
                "audit_id": audit_id,
                "compare": {"left_model": left_model, "right_model": right_model},
            },
            message="CyberAtlas model comparison ready",
        )
    except Exception as exc:
        get_job_manager().fail(job_id, str(exc))


def start_cyberatlas_ai_compare(audit_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = _job_id("compare", audit_id)
    job = get_job_manager().create(
        "cyberatlas",
        job_id=job_id,
        prompt=f"CyberAtlas compare AI {audit_id}",
        metadata={"module_id": "cyberatlas", "audit_id": audit_id},
    )
    thread = threading.Thread(target=_run_compare_ai_job, args=(job_id, audit_id, payload), daemon=True)
    thread.start()
    return {"job": job}
