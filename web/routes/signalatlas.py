"""Native SignalAtlas module routes."""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from flask import Blueprint, Response, jsonify, request

from core.audit_modules.model_context import get_audit_model_context
from core.audit_modules.targets import normalize_public_target
from core.signalatlas import (
    get_module_catalog,
    get_signalatlas_storage,
    start_signalatlas_ai_compare,
    start_signalatlas_ai_rerun,
    start_signalatlas_audit,
)
from core.signalatlas.providers import get_signalatlas_provider_status
from core.signalatlas.reporting import build_export_payload, render_pdf_bytes


signalatlas_bp = Blueprint("signalatlas", __name__)

SIGNALATLAS_DEFAULT_PAGE_BUDGET = 12
SIGNALATLAS_MAX_PAGE_BUDGET = 1500
SIGNALATLAS_UNLIMITED_PAGE_BUDGET_TOKENS = {"unlimited", "infinity", "infinite", "inf", "∞"}


def _normalize_target(raw_value: str, mode: str) -> Dict[str, Any]:
    return normalize_public_target(raw_value, mode)


def _normalize_max_pages(raw_value: Any) -> int:
    token = str(raw_value or "").strip().lower()
    if token in SIGNALATLAS_UNLIMITED_PAGE_BUDGET_TOKENS:
        return SIGNALATLAS_MAX_PAGE_BUDGET
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = SIGNALATLAS_DEFAULT_PAGE_BUDGET
    return max(1, min(SIGNALATLAS_MAX_PAGE_BUDGET, parsed))


def _model_context() -> Dict[str, Any]:
    return get_audit_model_context()


@signalatlas_bp.route("/api/modules", methods=["GET"])
def modules_catalog():
    return jsonify({"success": True, "modules": get_module_catalog()})


@signalatlas_bp.route("/api/signalatlas/models/context", methods=["GET"])
def signalatlas_models_context():
    return jsonify({"success": True, **_model_context()})


@signalatlas_bp.route("/api/signalatlas/providers/status", methods=["GET"])
def signalatlas_provider_status():
    target = str(request.args.get("target") or "").strip()
    mode = str(request.args.get("mode") or "public").strip().lower()
    return jsonify({
        "success": True,
        "providers": get_signalatlas_provider_status(target_url=target, mode=mode),
    })


@signalatlas_bp.route("/api/signalatlas/audits", methods=["GET", "POST"])
def signalatlas_audits():
    storage = get_signalatlas_storage()
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
            "render_js": bool(options.get("render_js")),
            "depth": max(1, min(5, int(options.get("depth") or 2))),
        },
        "ai": data.get("ai") or {},
    }
    started = start_signalatlas_audit(payload)
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@signalatlas_bp.route("/api/signalatlas/audits/<audit_id>", methods=["GET", "DELETE"])
def signalatlas_audit_detail(audit_id: str):
    storage = get_signalatlas_storage()
    if request.method == "DELETE":
        deleted = storage.delete_audit(audit_id)
        if not deleted:
            return jsonify({"success": False, "error": "Audit introuvable"}), 404
        return jsonify({"success": True, "deleted": True, "audit_id": audit_id})

    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    return jsonify({"success": True, "audit": audit})


@signalatlas_bp.route("/api/signalatlas/audits/<audit_id>/rerun-ai", methods=["POST"])
def signalatlas_rerun_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    job = start_signalatlas_ai_rerun(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@signalatlas_bp.route("/api/signalatlas/audits/<audit_id>/compare-ai", methods=["POST"])
def signalatlas_compare_ai(audit_id: str):
    payload = request.get_json(silent=True) or {}
    if not payload.get("left_model") or not payload.get("right_model"):
        return jsonify({"success": False, "error": "left_model and right_model required"}), 400
    job = start_signalatlas_ai_compare(audit_id, payload)
    return jsonify({"success": True, **job}), 202


@signalatlas_bp.route("/api/signalatlas/audits/<audit_id>/export/<export_format>", methods=["GET"])
def signalatlas_export(audit_id: str, export_format: str):
    storage = get_signalatlas_storage()
    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404

    export_format = str(export_format or "").strip().lower()
    filename_base = f"signalatlas-{audit_id}"
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
