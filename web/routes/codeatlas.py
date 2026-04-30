"""Native CodeAtlas module routes."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from core.codeatlas import build_export_payload, get_codeatlas_storage, start_codeatlas_audit


codeatlas_bp = Blueprint("codeatlas", __name__)


@codeatlas_bp.route("/api/codeatlas/audits", methods=["GET", "POST"])
def codeatlas_audits():
    storage = get_codeatlas_storage()
    if request.method == "GET":
        try:
            limit = max(1, min(200, int(request.args.get("limit", 40))))
        except Exception:
            limit = 40
        return jsonify({"success": True, "audits": storage.list_audits(limit)})

    payload = request.get_json(silent=True) or {}
    try:
        started = start_codeatlas_audit(payload)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@codeatlas_bp.route("/api/codeatlas/audits/<audit_id>", methods=["GET", "DELETE"])
def codeatlas_audit_detail(audit_id: str):
    storage = get_codeatlas_storage()
    if request.method == "DELETE":
        deleted = storage.delete_audit(audit_id)
        if not deleted:
            return jsonify({"success": False, "error": "Audit introuvable"}), 404
        return jsonify({"success": True, "deleted": True, "audit_id": audit_id})
    audit = storage.get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    return jsonify({"success": True, "audit": audit})


@codeatlas_bp.route("/api/codeatlas/audits/<audit_id>/rerun", methods=["POST"])
def codeatlas_rerun(audit_id: str):
    audit = get_codeatlas_storage().get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    target = audit.get("target") or {}
    try:
        started = start_codeatlas_audit({
            "project_path": target.get("normalized_path") or target.get("raw"),
            "title": audit.get("title") or target.get("host"),
            "options": audit.get("options") or {},
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "audit": started["audit"], "job": started["job"]}), 202


@codeatlas_bp.route("/api/codeatlas/audits/<audit_id>/export/<export_format>", methods=["GET"])
def codeatlas_export(audit_id: str, export_format: str):
    audit = get_codeatlas_storage().get_audit(audit_id)
    if not audit:
        return jsonify({"success": False, "error": "Audit introuvable"}), 404
    try:
        export = build_export_payload(audit, export_format)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return Response(
        export["content"],
        mimetype=export["mimetype"],
        headers={"Content-Disposition": f'attachment; filename="codeatlas-{audit_id}.{export["extension"]}"'},
    )
