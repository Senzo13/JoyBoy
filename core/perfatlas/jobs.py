"""Background jobs for PerfAtlas audits and AI interpretation."""

from __future__ import annotations

import threading
from typing import Any, Dict

from core.audit_modules.jobs import build_audit_job_id, update_module_progress
from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso

from .engine import run_site_audit
from .intelligence import build_regression_summary
from .llm_adapter import generate_interpretation
from .storage import get_perfatlas_storage


def _job_id(prefix: str, audit_id: str) -> str:
    return build_audit_job_id("perfatlas", prefix, audit_id)


def _update_progress(job_id: str, phase: str, progress: float, message: str) -> None:
    update_module_progress(job_id, "perfatlas", phase, progress, message)


def _estimate_audit_seconds(options: Dict[str, Any], ai_config: Dict[str, Any]) -> int:
    try:
        max_pages = max(1, int(options.get("max_pages") or 8))
    except (TypeError, ValueError):
        max_pages = 8
    crawl_seconds = 10 + min(max_pages, 20) * 4
    field_seconds = 8
    if max_pages <= 3:
        lab_probe_runs = 1
    elif max_pages <= 8:
        lab_probe_runs = 3
    else:
        lab_probe_runs = 7
    lab_seconds = lab_probe_runs * 10
    owner_seconds = 6
    level = str(ai_config.get("level") or "basic_summary").strip().lower()
    ai_seconds = {
        "no_ai": 0,
        "basic_summary": 18,
        "full_expert_analysis": 45,
        "ai_remediation_pack": 70,
    }.get(level, 35)
    return int(max(35, min(900, crawl_seconds + field_seconds + lab_seconds + owner_seconds + ai_seconds)))


def _run_audit_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_perfatlas_storage()
    manager = get_job_manager()
    audit = storage.get_audit(audit_id)
    if not audit:
        manager.fail(job_id, "PerfAtlas audit not found")
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
            progress_callback=lambda phase, progress, message: _update_progress(job_id, phase, progress, message),
            cancel_check=cancel_check,
        )
        if cancel_check():
            storage.update_audit(audit_id, status="cancelled")
            manager.cancel(job_id, "PerfAtlas audit cancelled")
            return

        updated = storage.get_audit(audit_id) or audit
        updated.update(
            summary=result["summary"],
            snapshot=result["snapshot"],
            findings=result["findings"],
            scores=result["scores"],
            remediation_items=result["remediation_items"],
            owner_context=result["owner_context"],
            status="done",
            updated_at=utc_now_iso(),
        )
        previous = storage.find_previous_completed_audit(
            host=str((updated.get("target") or {}).get("host") or ""),
            exclude_id=audit_id,
        )
        regression = build_regression_summary(updated, previous)
        updated.setdefault("snapshot", {})["regression"] = regression
        updated.setdefault("summary", {})["regression_risk"] = regression.get("risk") or "unknown"
        updated.setdefault("summary", {})["previous_audit_id"] = regression.get("previous_audit_id") or ""

        ai_config = payload.get("ai") or {}
        if ai_config.get("level") and str(ai_config.get("level")).lower() != "no_ai":
            _update_progress(job_id, "ai", 92, "Generating AI interpretation")
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
                "module_id": "perfatlas",
                "audit_id": audit_id,
                "title": updated.get("title"),
            },
            message="PerfAtlas audit complete",
        )
    except Exception as exc:
        storage.update_audit(audit_id, status="error", metadata={"error": str(exc)})
        manager.fail(job_id, str(exc))


def start_perfatlas_audit(payload: Dict[str, Any]) -> Dict[str, Any]:
    storage = get_perfatlas_storage()
    target = payload.get("target") or {}
    title = payload.get("title") or (target.get("host") or target.get("normalized_url") or "PerfAtlas audit")
    options = payload.get("options") or {}
    ai_config = payload.get("ai") or {}
    estimated_seconds = _estimate_audit_seconds(options, ai_config)
    audit = storage.create_audit_stub(
        target=target,
        title=title,
        options=options,
        metadata={
            "module_id": "perfatlas",
            "ai": ai_config,
            "estimated_seconds": estimated_seconds,
        },
    )
    job_id = _job_id("audit", audit["id"])
    job = get_job_manager().create(
        "perfatlas",
        job_id=job_id,
        prompt=audit["target"]["normalized_url"],
        metadata={
            "module_id": "perfatlas",
            "audit_id": audit["id"],
            "estimated_seconds": estimated_seconds,
            "requested_max_pages": options.get("max_pages"),
            "ai_level": ai_config.get("level") or "",
        },
    )
    thread = threading.Thread(target=_run_audit_job, args=(job_id, audit["id"], payload), daemon=True)
    thread.start()
    return {"audit": audit, "job": job}


def _run_rerun_ai_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_perfatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        get_job_manager().fail(job_id, "PerfAtlas audit not found")
        return
    try:
        _update_progress(job_id, "ai", 30, "Preparing deterministic audit excerpt")
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
            artifact={"module_id": "perfatlas", "audit_id": audit_id},
            message="PerfAtlas AI interpretation ready",
        )
    except Exception as exc:
        get_job_manager().fail(job_id, str(exc))


def start_perfatlas_ai_rerun(audit_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = _job_id("ai", audit_id)
    job = get_job_manager().create(
        "perfatlas",
        job_id=job_id,
        prompt=f"PerfAtlas AI rerun {audit_id}",
        metadata={"module_id": "perfatlas", "audit_id": audit_id},
    )
    thread = threading.Thread(target=_run_rerun_ai_job, args=(job_id, audit_id, payload), daemon=True)
    thread.start()
    return {"job": job}


def _run_compare_ai_job(job_id: str, audit_id: str, payload: Dict[str, Any]) -> None:
    storage = get_perfatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        get_job_manager().fail(job_id, "PerfAtlas audit not found")
        return
    try:
        left_model = str(payload.get("left_model") or "")
        right_model = str(payload.get("right_model") or "")
        level = str(payload.get("level") or "full_expert_analysis")
        preset = str(payload.get("preset") or "expert")
        _update_progress(job_id, "ai", 24, "Generating first interpretation")
        left = generate_interpretation(audit, model=left_model, level=level, preset=preset, mode="compare-left")
        _update_progress(job_id, "ai", 72, "Generating second interpretation")
        right = generate_interpretation(audit, model=right_model, level=level, preset=preset, mode="compare-right")
        audit.setdefault("interpretations", []).extend([left, right])
        audit["metadata"] = dict(audit.get("metadata") or {}, compare_pair={"left": left_model, "right": right_model})
        audit["updated_at"] = utc_now_iso()
        storage.save_audit(audit)
        get_job_manager().complete(
            job_id,
            artifact={
                "module_id": "perfatlas",
                "audit_id": audit_id,
                "compare": {"left_model": left_model, "right_model": right_model},
            },
            message="PerfAtlas model comparison ready",
        )
    except Exception as exc:
        get_job_manager().fail(job_id, str(exc))


def start_perfatlas_ai_compare(audit_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = _job_id("compare", audit_id)
    job = get_job_manager().create(
        "perfatlas",
        job_id=job_id,
        prompt=f"PerfAtlas compare AI {audit_id}",
        metadata={"module_id": "perfatlas", "audit_id": audit_id},
    )
    thread = threading.Thread(target=_run_compare_ai_job, args=(job_id, audit_id, payload), daemon=True)
    thread.start()
    return {"job": job}
