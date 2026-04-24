"""Native PerfAtlas module routes."""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

from core.audit_modules.model_context import get_audit_model_context
from core.audit_modules.targets import normalize_public_target
from core.perfatlas import (
    get_perfatlas_storage,
    start_perfatlas_ai_compare,
    start_perfatlas_ai_rerun,
    start_perfatlas_audit,
)
from core.perfatlas.providers import get_perfatlas_provider_status
from core.perfatlas.reporting import build_export_payload, render_pdf_bytes


perfatlas_bp = Blueprint("perfatlas", __name__)

PERFATLAS_DEFAULT_PAGE_BUDGET = 8
PERFATLAS_MAX_PAGE_BUDGET = 20
PERFATLAS_UNLIMITED_PAGE_BUDGET_TOKENS = {"unlimited", "infinity", "infinite", "inf", "∞"}


def _normalize_target(raw_value: str, mode: str) -> Dict[str, Any]:
    return normalize_public_target(raw_value, mode)


def _normalize_max_pages(raw_value: Any) -> int:
    token = str(raw_value or "").strip().lower()
    if token in PERFATLAS_UNLIMITED_PAGE_BUDGET_TOKENS:
        return PERFATLAS_MAX_PAGE_BUDGET
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = PERFATLAS_DEFAULT_PAGE_BUDGET
    return max(1, min(PERFATLAS_MAX_PAGE_BUDGET, parsed))


@perfatlas_bp.route("/api/perfatlas/models/context", methods=["GET"])
def perfatlas_models_context():
    return jsonify({"success": True, **get_audit_model_context()})


@perfatlas_bp.route("/api/perfatlas/providers/status", methods=["GET"])
def perfatlas_provider_status():
    target = str(request.args.get("target") or "").strip()
    mode = str(request.args.get("mode") or "public").strip().lower()
    return jsonify({
        "success": True,
        "providers": get_perfatlas_provider_status(target_url=target, mode=mode),
    })


@perfatlas_bp.route("/api/perfatlas/audits", methods=["GET", "POST"])
def perfatlas_audits():
    storage = get_perfatlas_storage()
    if request.method == "GET":
        limit = request.args.get("limit", 40)
        try:
            limit_value = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            limit_value = 40
        return jsonify({"success": True, "audits": storage.list_audits(limit_value)})

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "public").strip().lower()
    if mode not in {"public", "verified_owner"}:
        return jsonify({"success": False, "error": "invalid mode"}), 400

    try:
        target = _normalize_target(data.get("target", ""), mode)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    options = data.get("options") or {}
    payload = {
        "title": data.get("title") or target["host"],
        "target": target,
        "options": {
            "max_pages": _normalize_max_pages(options.get("max_pages")),
        },
        "ai": data.get("ai") or {},
    }
    started = start_perfatlas_audit(payload)
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@perfatlas_bp.route("/api/perfatlas/audits/<audit_id>", methods=["GET", "DELETE"])
def perfatlas_audit_detail(audit_id: str):
    storage = get_perfatlas_storage()
    if request.method == "DELETE":
        deleted = storage.delete_audit(audit_id)
        if not deleted:
            return jsonify({"success": False, "error": "Audit introuvable"}), 404
        return jsonify({"success": True, "deleted": True, "audit_id": audit_id})

    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    return jsonify({"success": True, "audit": audit})


@perfatlas_bp.route("/api/perfatlas/audits/<audit_id>/rerun-ai", methods=["POST"])
def perfatlas_rerun_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    job = start_perfatlas_ai_rerun(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@perfatlas_bp.route("/api/perfatlas/audits/<audit_id>/compare-ai", methods=["POST"])
def perfatlas_compare_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    if not payload.get("left_model") or not payload.get("right_model"):
        return jsonify({"success": False, "error": "left_model and right_model required"}), 400
    job = start_perfatlas_ai_compare(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@perfatlas_bp.route("/api/perfatlas/audits/<audit_id>/export/<export_format>", methods=["GET"])
def perfatlas_export(audit_id: str, export_format: str):
    storage = get_perfatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404

    export_format = str(export_format or "").strip().lower()
    filename_base = f"perfatlas-{audit_id}"
    if export_format == "pdf":
        try:
            pdf_bytes = render_pdf_bytes(audit)
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 501
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.pdf"',
            },
        )

    try:
        export = build_export_payload(audit, export_format)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    return Response(
        export["content"],
        mimetype=export["mimetype"],
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.{export["extension"]}"',
        },
    )
