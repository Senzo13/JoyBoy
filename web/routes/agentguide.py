"""Native AgentGuide module routes."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from core.agentguide import (
    apply_agentguide_files,
    build_export_payload,
    get_agentguide_storage,
    start_agentguide_audit,
)


agentguide_bp = Blueprint("agentguide", __name__)


@agentguide_bp.route("/api/agentguide/audits", methods=["GET", "POST"])
def agentguide_audits():
    storage = get_agentguide_storage()
    if request.method == "GET":
        try:
            limit = max(1, min(200, int(request.args.get("limit", 40))))
        except Exception:
            limit = 40
        return jsonify({"success": True, "audits": storage.list_audits(limit)})

    payload = request.get_json(silent=True) or {}
    try:
        started = start_agentguide_audit(payload)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@agentguide_bp.route("/api/agentguide/audits/<audit_id>", methods=["GET", "DELETE"])
def agentguide_audit_detail(audit_id: str):
    storage = get_agentguide_storage()
    if request.method == "DELETE":
        deleted = storage.delete_audit(audit_id)
        if not deleted:
            return jsonify({"success": False, "error": "Audit introuvable"}), 404
        return jsonify({"success": True, "deleted": True, "audit_id": audit_id})
    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    return jsonify({"success": True, "audit": audit})


@agentguide_bp.route("/api/agentguide/audits/<audit_id>/apply", methods=["POST"])
def agentguide_apply(audit_id: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = apply_agentguide_files(audit_id, payload.get("files") or None)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, **result})


@agentguide_bp.route("/api/agentguide/audits/<audit_id>/export/<export_format>", methods=["GET"])
def agentguide_export(audit_id: str, export_format: str):
    audit = get_agentguide_storage().get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    try:
        export = build_export_payload(audit, export_format)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return Response(
        export["content"],
        mimetype=export["mimetype"],
        headers={"Content-Disposition": f'attachment; filename="agentguide-{audit_id}.{export["extension"]}"'},
    )
