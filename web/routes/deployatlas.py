"""Native DeployAtlas module routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from core.audit_modules.model_context import get_audit_model_context
from core.deployatlas import (
    analyze_project,
    copy_uploaded_files,
    extract_archive,
    get_deployatlas_storage,
    start_deployatlas_deployment,
)
from core.deployatlas.security import sanitize_value
from core.deployatlas.ssh_client import DeployAtlasSshClient, fetch_host_fingerprint, paramiko_available
from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso


deployatlas_bp = Blueprint("deployatlas", __name__)

HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$", re.I)


def _credentials_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    credentials = payload.get("credentials") or {}
    return {
        "password": str(credentials.get("password") or payload.get("password") or ""),
        "private_key": str(credentials.get("private_key") or payload.get("private_key") or ""),
        "passphrase": str(credentials.get("passphrase") or payload.get("passphrase") or ""),
        "sudo_password": str(credentials.get("sudo_password") or payload.get("sudo_password") or ""),
    }


def _server_from_payload(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(existing or {})
    for key in ("name", "host", "port", "username", "auth_type", "sudo_mode", "domain", "ssl_enabled", "host_fingerprint"):
        if key in payload:
            base[key] = payload.get(key)
    return base


def _validate_server(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[dict[str, Any], int] | None]:
    server = _server_from_payload(payload)
    host = str(server.get("host") or "").strip().lower().replace("https://", "").replace("http://", "").split("/", 1)[0]
    username = str(server.get("username") or "").strip()
    try:
        port = int(server.get("port") or 22)
    except Exception:
        port = 22
    if not host or not HOST_RE.match(host) or ".." in host:
        return None, ({"success": False, "error": "Hostname ou IP invalide."}, 400)
    if not username:
        return None, ({"success": False, "error": "Utilisateur SSH requis."}, 400)
    if port < 1 or port > 65535:
        return None, ({"success": False, "error": "Port SSH invalide."}, 400)
    server["host"] = host
    server["port"] = port
    server["username"] = username
    server["auth_type"] = str(server.get("auth_type") or "password").strip().lower()
    return server, None


@deployatlas_bp.route("/api/deployatlas/models/context", methods=["GET"])
def deployatlas_models_context():
    return jsonify({"success": True, **get_audit_model_context()})


@deployatlas_bp.route("/api/deployatlas/providers/status", methods=["GET"])
def deployatlas_provider_status():
    return jsonify({
        "success": True,
        "providers": [
            {
                "id": "ssh_runtime",
                "name": "SSH runtime",
                "status": "configured" if paramiko_available() else "missing",
                "configured": paramiko_available(),
                "detail": "Paramiko SSH/SFTP available" if paramiko_available() else "Install Paramiko to test SSH connections.",
            },
            {
                "id": "caddy_https",
                "name": "Caddy HTTPS",
                "status": "planned",
                "configured": True,
                "detail": "DeployAtlas prepares Caddy-first HTTPS runbooks; Certbot remains a fallback.",
            },
        ],
    })


@deployatlas_bp.route("/api/deployatlas/servers", methods=["GET", "POST"])
def deployatlas_servers():
    storage = get_deployatlas_storage()
    if request.method == "GET":
        return jsonify({"success": True, "servers": storage.list_servers()})

    payload = request.get_json(silent=True) or {}
    server, error = _validate_server(payload)
    if error:
        body, status = error
        return jsonify(body), status
    saved = storage.save_server(server or {})
    return jsonify({"success": True, "server": saved}), 201


@deployatlas_bp.route("/api/deployatlas/servers/<server_id>", methods=["GET", "DELETE"])
def deployatlas_server_detail(server_id: str):
    storage = get_deployatlas_storage()
    if request.method == "DELETE":
        deleted = storage.delete_server(server_id)
        if not deleted:
            return jsonify({"success": False, "error": "Serveur introuvable."}), 404
        return jsonify({"success": True, "deleted": True, "server_id": server_id})
    server = storage.get_server(server_id)
    if not server:
        return jsonify({"success": False, "error": "Serveur introuvable."}), 404
    return jsonify({"success": True, "server": server})


@deployatlas_bp.route("/api/deployatlas/servers/<server_id>/test", methods=["POST"])
def deployatlas_test_server(server_id: str):
    storage = get_deployatlas_storage()
    payload = request.get_json(silent=True) or {}
    existing = storage.get_server(server_id, public=False)
    if not existing and server_id != "new":
        return jsonify({"success": False, "error": "Serveur introuvable."}), 404
    server, error = _validate_server(_server_from_payload(payload, existing))
    if error:
        body, status = error
        return jsonify(body), status
    if not paramiko_available():
        return jsonify({
            "success": False,
            "status": "dependency_missing",
            "error": "Paramiko n’est pas installé côté JoyBoy.",
        }), 501

    trust_host_key = bool(payload.get("trust_host_key"))
    credentials = _credentials_from_payload(payload)
    client = DeployAtlasSshClient(server or {}, credentials)
    result = client.connect(require_trusted_host=True, trust_host_key=trust_host_key)
    client.close()

    if result.fingerprint and (result.success or trust_host_key) and existing:
        storage.update_server(
            server_id,
            host_fingerprint=result.fingerprint,
            remote_os=result.remote_os,
            last_checked_at=utc_now_iso(),
            last_status=result.status,
        )
    return jsonify({"success": result.success, "result": result.to_dict(), "server": storage.get_server(server_id) if existing else sanitize_value(server)})


@deployatlas_bp.route("/api/deployatlas/servers/fingerprint", methods=["POST"])
def deployatlas_server_fingerprint():
    payload = request.get_json(silent=True) or {}
    server, error = _validate_server(payload)
    if error:
        body, status = error
        return jsonify(body), status
    if not paramiko_available():
        return jsonify({"success": False, "error": "Paramiko n’est pas installé côté JoyBoy."}), 501
    try:
        fingerprint = fetch_host_fingerprint(str(server.get("host")), int(server.get("port") or 22))
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "fingerprint": fingerprint})


@deployatlas_bp.route("/api/deployatlas/projects/analyze", methods=["POST"])
def deployatlas_analyze_project():
    storage = get_deployatlas_storage()
    project_name = str(request.form.get("name") or request.args.get("name") or "Projet").strip()
    source_type = str(request.form.get("source_type") or "upload").strip().lower()
    analysis_id = str(request.form.get("analysis_id") or "").strip() or None
    project_dir = storage.create_project_dir(analysis_id)
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    uploads = list(request.files.getlist("files"))
    if not uploads and request.files:
        uploads = list(request.files.values())
    if not uploads:
        return jsonify({"success": False, "error": "Ajoute une archive ou un dossier projet."}), 400

    ingest: dict[str, Any] = {"files_received": len(uploads)}
    try:
        first_name = str(uploads[0].filename or "").lower()
        archive_ext = first_name.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".rar"))
        if len(uploads) == 1 and archive_ext:
            archive_path = project_dir / Path(first_name.replace("\\", "/")).name
            uploads[0].save(archive_path)
            ingest.update(extract_archive(archive_path, source_dir))
        else:
            written = copy_uploaded_files(uploads, source_dir)
            ingest["files_written"] = len(written)
        analysis = analyze_project(source_dir, name=project_name, source_type=source_type, ingest_meta=ingest)
        analysis = storage.save_project_analysis(analysis)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "analysis": analysis})


@deployatlas_bp.route("/api/deployatlas/deployments", methods=["GET", "POST"])
def deployatlas_deployments():
    storage = get_deployatlas_storage()
    if request.method == "GET":
        limit = request.args.get("limit", 40)
        try:
            limit_value = max(1, min(200, int(limit)))
        except Exception:
            limit_value = 40
        return jsonify({"success": True, "deployments": storage.list_deployments(limit_value)})

    payload = request.get_json(silent=True) or {}
    server_id = str(payload.get("server_id") or "").strip()
    server = storage.get_server(server_id, public=False) if server_id else None
    if not server:
        server_payload, error = _validate_server(payload.get("server") or {})
        if error:
            body, status = error
            return jsonify(body), status
        server = server_payload

    analysis = payload.get("project_analysis") or {}
    analysis_id = str(payload.get("analysis_id") or analysis.get("id") or "").strip()
    if analysis_id and not analysis:
        analysis = storage.get_project_analysis(analysis_id) or {}
    if not analysis:
        return jsonify({"success": False, "error": "Analyse projet requise avant déploiement."}), 400

    started = start_deployatlas_deployment({
        "title": payload.get("title") or analysis.get("name") or "DeployAtlas",
        "server_id": server_id,
        "server": server,
        "project_analysis": analysis,
        "options": payload.get("options") or {},
        "credentials": _credentials_from_payload(payload),
    })
    return jsonify({"success": True, "deployment": started["deployment"], "job": started["job"]}), 202


@deployatlas_bp.route("/api/deployatlas/deployments/<deployment_id>", methods=["GET"])
def deployatlas_deployment_detail(deployment_id: str):
    deployment = get_deployatlas_storage().get_deployment(deployment_id)
    if not deployment:
        return jsonify({"success": False, "error": "Déploiement introuvable."}), 404
    return jsonify({"success": True, "deployment": deployment})


@deployatlas_bp.route("/api/deployatlas/deployments/<deployment_id>/cancel", methods=["POST"])
def deployatlas_cancel_deployment(deployment_id: str):
    storage = get_deployatlas_storage()
    deployment = storage.get_deployment(deployment_id)
    if not deployment:
        return jsonify({"success": False, "error": "Déploiement introuvable."}), 404
    job_id = f"deployatlas-deploy-{deployment_id}"
    get_job_manager().request_cancel(job_id)
    storage.update_deployment(deployment_id, status="cancelling", phase="cancelling")
    return jsonify({"success": True, "deployment_id": deployment_id, "job_id": job_id})
