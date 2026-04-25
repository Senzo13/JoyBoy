"""Native CyberAtlas module routes."""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, Response, jsonify, request

from core.audit_modules.model_context import get_audit_model_context
from core.audit_modules.targets import normalize_public_target
from core.cyberatlas import (
    get_cyberatlas_storage,
    start_cyberatlas_ai_compare,
    start_cyberatlas_ai_rerun,
    start_cyberatlas_audit,
)
from core.cyberatlas.reporting import build_export_payload, render_pdf_bytes


cyberatlas_bp = Blueprint("cyberatlas", __name__)

CYBERATLAS_DEFAULT_PAGE_BUDGET = 8
CYBERATLAS_MAX_PAGE_BUDGET = 24
CYBERATLAS_DEFAULT_ENDPOINT_BUDGET = 32
CYBERATLAS_MAX_ENDPOINT_BUDGET = 80
CYBERATLAS_UNLIMITED_TOKENS = {"unlimited", "infinity", "infinite", "inf", "∞"}


def _normalize_target(raw_value: str, mode: str) -> Dict[str, Any]:
    return normalize_public_target(raw_value, mode)


def _normalize_budget(raw_value: Any, *, default: int, maximum: int) -> int:
    token = str(raw_value or "").strip().lower()
    if token in CYBERATLAS_UNLIMITED_TOKENS:
        return maximum
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


@cyberatlas_bp.route("/api/cyberatlas/models/context", methods=["GET"])
def cyberatlas_models_context():
    return jsonify({"success": True, **get_audit_model_context()})


@cyberatlas_bp.route("/api/cyberatlas/providers/status", methods=["GET"])
def cyberatlas_provider_status():
    return jsonify({
        "success": True,
        "providers": [
            {
                "id": "safe_http_evidence",
                "name": "Safe HTTP evidence",
                "status": "configured",
                "configured": True,
                "detail": "CyberAtlas uses defensive HTTP evidence, TLS metadata, safe exposure probes, and OpenAPI parsing.",
            }
        ],
    })


@cyberatlas_bp.route("/api/cyberatlas/audits", methods=["GET", "POST"])
def cyberatlas_audits():
    storage = get_cyberatlas_storage()
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
    active_checks = bool(options.get("active_checks")) and mode == "verified_owner"
    payload = {
        "title": data.get("title") or target["host"],
        "target": target,
        "options": {
            "max_pages": _normalize_budget(
                options.get("max_pages"),
                default=CYBERATLAS_DEFAULT_PAGE_BUDGET,
                maximum=CYBERATLAS_MAX_PAGE_BUDGET,
            ),
            "max_endpoints": _normalize_budget(
                options.get("max_endpoints"),
                default=CYBERATLAS_DEFAULT_ENDPOINT_BUDGET,
                maximum=CYBERATLAS_MAX_ENDPOINT_BUDGET,
            ),
            "active_checks": active_checks,
        },
        "ai": data.get("ai") or {},
    }
    started = start_cyberatlas_audit(payload)
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@cyberatlas_bp.route("/api/cyberatlas/audits/<audit_id>", methods=["GET", "DELETE"])
def cyberatlas_audit_detail(audit_id: str):
    storage = get_cyberatlas_storage()
    if request.method == "DELETE":
        deleted = storage.delete_audit(audit_id)
        if not deleted:
            return jsonify({"success": False, "error": "Audit introuvable"}), 404
        return jsonify({"success": True, "deleted": True, "audit_id": audit_id})

    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    return jsonify({"success": True, "audit": audit})


@cyberatlas_bp.route("/api/cyberatlas/audits/<audit_id>/rerun-ai", methods=["POST"])
def cyberatlas_rerun_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    job = start_cyberatlas_ai_rerun(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@cyberatlas_bp.route("/api/cyberatlas/audits/<audit_id>/compare-ai", methods=["POST"])
def cyberatlas_compare_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    if not payload.get("left_model") or not payload.get("right_model"):
        return jsonify({"success": False, "error": "left_model and right_model required"}), 400
    job = start_cyberatlas_ai_compare(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@cyberatlas_bp.route("/api/cyberatlas/audits/<audit_id>/export/<export_format>", methods=["GET"])
def cyberatlas_export(audit_id: str, export_format: str):
    storage = get_cyberatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404

    export_format = str(export_format or "").strip().lower()
    filename_base = f"cyberatlas-{audit_id}"
    if export_format == "pdf":
        try:
            pdf_bytes = render_pdf_bytes(audit)
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 501
        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.pdf"'},
        )

    try:
        export = build_export_payload(audit, export_format)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    return Response(
        export["content"],
        mimetype=export["mimetype"],
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.{export["extension"]}"'},
    )
