"""Background deployment jobs for DeployAtlas."""

from __future__ import annotations

import threading
import time
from typing import Any

from core.runtime import get_job_manager
from core.runtime.storage import utc_now_iso

from .analyzer import suggested_app_slug
from .security import redact_text, sanitize_value
from .ssh_client import DeployAtlasSshClient
from .storage import get_deployatlas_storage


DEPLOY_PHASES = [
    ("connect", 8, "Connexion au serveur"),
    ("fingerprint", 15, "Validation fingerprint SSH"),
    ("upload", 25, "Préparation du paquet projet"),
    ("analyze", 38, "Analyse stack et manifeste"),
    ("plan", 52, "Construction du plan de déploiement"),
    ("runtime", 66, "Préparation runtime serveur"),
    ("service", 78, "Configuration service et reverse proxy"),
    ("ssl", 88, "Préparation HTTPS"),
    ("healthcheck", 96, "Healthcheck et rollback snapshot"),
]


def build_deployatlas_job_id(deployment_id: str) -> str:
    return f"deployatlas-deploy-{deployment_id}"


def _deployment_plan(deployment: dict[str, Any]) -> dict[str, Any]:
    analysis = deployment.get("project_analysis") or {}
    options = deployment.get("options") or {}
    server = deployment.get("server") or {}
    app_slug = options.get("app_slug") or suggested_app_slug(analysis)
    release_id = deployment.get("id")
    strategy = analysis.get("strategy") or "static"
    domain = options.get("domain") or server.get("domain") or ""
    ssl_enabled = bool(options.get("ssl_enabled") or server.get("ssl_enabled"))
    remote_root = f"/opt/joyboy/apps/{app_slug}"
    commands = [
        f"mkdir -p {remote_root}/releases/{release_id}",
        f"tar -xzf /tmp/{app_slug}-{release_id}.tar.gz -C {remote_root}/releases/{release_id}",
        f"ln -sfn {remote_root}/releases/{release_id} {remote_root}/current",
    ]
    if strategy == "docker-compose":
        commands.append(f"cd {remote_root}/current && docker compose up -d --build")
    elif strategy == "docker":
        commands.append(f"cd {remote_root}/current && docker build -t joyboy-{app_slug}:{release_id} .")
    elif strategy == "systemd-node":
        commands.extend([
            f"cd {remote_root}/current && npm install --omit=dev",
            f"cd {remote_root}/current && npm run build --if-present",
            f"systemctl restart joyboy-{app_slug}.service",
        ])
    elif strategy == "systemd-python":
        commands.extend([
            f"cd {remote_root}/current && python3 -m venv .venv",
            f"cd {remote_root}/current && .venv/bin/pip install -r requirements.txt",
            f"systemctl restart joyboy-{app_slug}.service",
        ])
    else:
        commands.append(f"caddy reload --config /etc/caddy/Caddyfile")
    if domain and ssl_enabled:
        commands.append(f"caddy validate --config /etc/caddy/Caddyfile # HTTPS auto pour {domain}")
    return {
        "app_slug": app_slug,
        "release_id": release_id,
        "strategy": strategy,
        "remote_root": remote_root,
        "domain": domain,
        "ssl_enabled": ssl_enabled,
        "proxy": "caddy" if ssl_enabled else "none",
        "commands": commands,
        "mode": "guided-execution",
        "notes": [
            "Les secrets ne sont pas transmis à l’IA.",
            "Les commandes destructives restent à confirmer avant exécution réelle.",
            "Caddy est prioritaire pour HTTPS automatique; Certbot reste fallback si Caddy n’est pas retenu.",
        ],
    }


def _update_job(job_id: str, deployment_id: str, phase: str, progress: float, message: str) -> None:
    storage = get_deployatlas_storage()
    storage.update_deployment(deployment_id, status="running", phase=phase, progress=progress)
    storage.append_log(deployment_id, message, phase=phase)
    get_job_manager().update(
        job_id,
        status="running",
        phase=phase,
        progress=progress,
        message=message,
        metadata={"module_id": "deployatlas", "deployment_id": deployment_id},
    )


def _cancel_requested(job_id: str) -> bool:
    job = get_job_manager().get(job_id)
    return bool(job and job.get("cancel_requested"))


def _run_deployment(job_id: str, deployment_id: str, payload: dict[str, Any]) -> None:
    storage = get_deployatlas_storage()
    manager = get_job_manager()
    try:
        deployment = storage.get_deployment(deployment_id)
        if not deployment:
            manager.fail(job_id, "Déploiement introuvable")
            return

        credentials = payload.get("credentials") or {}
        execute_remote = bool((payload.get("options") or {}).get("execute_remote"))
        trusted_host = bool((payload.get("options") or {}).get("trust_host_key"))

        for phase, progress, message in DEPLOY_PHASES:
            if _cancel_requested(job_id):
                storage.update_deployment(deployment_id, status="cancelled", phase="cancelled", progress=progress)
                manager.cancel(job_id, "Déploiement annulé")
                return

            _update_job(job_id, deployment_id, phase, progress, message)
            time.sleep(0.35)

            if phase == "connect" and execute_remote:
                ssh = DeployAtlasSshClient(deployment.get("server") or {}, credentials)
                result = ssh.connect(require_trusted_host=True, trust_host_key=trusted_host)
                try:
                    ssh.close()
                finally:
                    storage.append_log(deployment_id, result.message, phase=phase, level="info" if result.success else "error")
                if result.status == "requires_trust":
                    storage.update_deployment(deployment_id, status="blocked", phase="fingerprint", progress=progress)
                    manager.fail(job_id, f"Fingerprint SSH à valider: {result.fingerprint}")
                    return
                if not result.success:
                    storage.update_deployment(deployment_id, status="error", phase=phase, progress=progress)
                    manager.fail(job_id, result.message)
                    return

        deployment = storage.get_deployment(deployment_id) or deployment
        plan = _deployment_plan(deployment)
        storage.update_deployment(
            deployment_id,
            status="done",
            phase="done",
            progress=100,
            plan=sanitize_value(plan),
            finished_at=utc_now_iso(),
        )
        storage.append_log(
            deployment_id,
            "Plan DeployAtlas prêt. Active l’exécution distante réelle uniquement après validation du runbook.",
            phase="done",
        )
        manager.complete(
            job_id,
            artifact={"module_id": "deployatlas", "deployment_id": deployment_id},
            message="Plan DeployAtlas prêt",
        )
    except Exception as exc:
        message = redact_text(str(exc))
        storage.update_deployment(deployment_id, status="error", phase="error")
        storage.append_log(deployment_id, message, phase="error", level="error")
        manager.fail(job_id, message)


def start_deployatlas_deployment(payload: dict[str, Any]) -> dict[str, Any]:
    storage = get_deployatlas_storage()
    deployment = storage.create_deployment(payload)
    job_id = build_deployatlas_job_id(deployment["id"])
    job = get_job_manager().create(
        "deployatlas",
        job_id=job_id,
        prompt=deployment.get("title", "DeployAtlas"),
        model=str((payload.get("options") or {}).get("model") or ""),
        metadata={"module_id": "deployatlas", "deployment_id": deployment["id"]},
    )
    thread = threading.Thread(
        target=_run_deployment,
        args=(job_id, deployment["id"], payload),
        daemon=True,
    )
    thread.start()
    return {"deployment": deployment, "job": job}
