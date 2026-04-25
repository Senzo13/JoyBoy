"""Local non-git storage for DeployAtlas servers and deployments."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.runtime.storage import get_runtime_root, utc_now_iso

from .security import public_server_record, sanitize_value


def _slug(value: str, fallback: str = "app") -> str:
    clean = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    clean = "-".join(part for part in clean.split("-") if part)
    return clean[:64] or fallback


class DeployAtlasStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or (get_runtime_root() / "deployatlas"))
        self.projects_dir = self.root / "projects"
        self.servers_path = self.root / "servers.json"
        self.deployments_path = self.root / "deployments.json"
        self._lock = threading.RLock()
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return deepcopy(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else deepcopy(default)
        except Exception as exc:
            print(f"[DEPLOYATLAS] Ignored store {path.name}: {exc}")
            return deepcopy(default)

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _servers_locked(self) -> dict[str, Any]:
        data = self._load_json(self.servers_path, {"version": 1, "servers": {}})
        data.setdefault("version", 1)
        data.setdefault("servers", {})
        return data

    def _deployments_locked(self) -> dict[str, Any]:
        data = self._load_json(self.deployments_path, {"version": 1, "deployments": {}})
        data.setdefault("version", 1)
        data.setdefault("deployments", {})
        return data

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._servers_locked()
            items = [public_server_record(server) for server in data.get("servers", {}).values()]
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def get_server(self, server_id: str, *, public: bool = True) -> dict[str, Any] | None:
        with self._lock:
            server = self._servers_locked().get("servers", {}).get(str(server_id or "").strip())
        if not server:
            return None
        return public_server_record(server) if public else deepcopy(server)

    def save_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        server_id = str(payload.get("id") or uuid.uuid4())
        record = {
            "id": server_id,
            "name": str(payload.get("name") or "").strip()[:80],
            "host": str(payload.get("host") or "").strip(),
            "port": int(payload.get("port") or 22),
            "username": str(payload.get("username") or "").strip(),
            "auth_type": str(payload.get("auth_type") or "password").strip().lower(),
            "sudo_mode": str(payload.get("sudo_mode") or "ask").strip().lower(),
            "domain": str(payload.get("domain") or "").strip().lower(),
            "ssl_enabled": bool(payload.get("ssl_enabled")),
            "remote_os": str(payload.get("remote_os") or "").strip(),
            "host_fingerprint": str(payload.get("host_fingerprint") or "").strip(),
            "last_checked_at": payload.get("last_checked_at") or "",
            "last_status": payload.get("last_status") or "saved",
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        }
        if not record["name"]:
            record["name"] = record["host"] or "VPS"
        with self._lock:
            data = self._servers_locked()
            previous = data["servers"].get(server_id) or {}
            record["created_at"] = previous.get("created_at") or record["created_at"]
            if not record["host_fingerprint"]:
                record["host_fingerprint"] = previous.get("host_fingerprint", "")
            data["servers"][server_id] = record
            self._save_json(self.servers_path, data)
        return public_server_record(record)

    def update_server(self, server_id: str, **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            data = self._servers_locked()
            server = data.get("servers", {}).get(str(server_id or "").strip())
            if not server:
                return None
            server.update({key: value for key, value in updates.items() if value is not None})
            server["updated_at"] = utc_now_iso()
            data["servers"][server["id"]] = server
            self._save_json(self.servers_path, data)
            return public_server_record(server)

    def delete_server(self, server_id: str) -> bool:
        clean_id = str(server_id or "").strip()
        with self._lock:
            data = self._servers_locked()
            existed = clean_id in data.get("servers", {})
            data.get("servers", {}).pop(clean_id, None)
            self._save_json(self.servers_path, data)
        return existed

    def create_project_dir(self, analysis_id: str | None = None) -> Path:
        project_id = _slug(analysis_id or str(uuid.uuid4()), "project")
        path = self.projects_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_project_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        analysis = sanitize_value(analysis or {})
        analysis_id = str(analysis.get("id") or uuid.uuid4())
        analysis["id"] = analysis_id
        analysis["updated_at"] = utc_now_iso()
        path = self.projects_dir / _slug(analysis_id, "project") / "analysis.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        return analysis

    def get_project_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        path = self.projects_dir / _slug(analysis_id, "project") / "analysis.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create_deployment(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        deployment_id = str(uuid.uuid4())
        title = str(payload.get("title") or payload.get("app_name") or "Deployment").strip()
        record = {
            "id": deployment_id,
            "title": title[:120] or "Deployment",
            "server_id": str(payload.get("server_id") or "").strip(),
            "server": public_server_record(payload.get("server") or {}),
            "project_analysis": sanitize_value(payload.get("project_analysis") or {}),
            "options": sanitize_value(payload.get("options") or {}),
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "logs": [],
            "plan": {},
            "created_at": now,
            "updated_at": now,
            "finished_at": "",
        }
        with self._lock:
            data = self._deployments_locked()
            data["deployments"][deployment_id] = record
            self._save_json(self.deployments_path, data)
        return deepcopy(record)

    def update_deployment(self, deployment_id: str, **updates: Any) -> dict[str, Any] | None:
        clean_id = str(deployment_id or "").strip()
        with self._lock:
            data = self._deployments_locked()
            record = data.get("deployments", {}).get(clean_id)
            if not record:
                return None
            for key, value in updates.items():
                record[key] = sanitize_value(value)
            record["updated_at"] = utc_now_iso()
            if str(record.get("status") or "").lower() in {"done", "error", "cancelled"}:
                record["finished_at"] = record.get("finished_at") or utc_now_iso()
            data["deployments"][clean_id] = record
            self._save_json(self.deployments_path, data)
            return deepcopy(record)

    def append_log(self, deployment_id: str, message: str, *, phase: str = "", level: str = "info") -> None:
        record = self.get_deployment(deployment_id)
        if not record:
            return
        logs = list(record.get("logs") or [])
        logs.append({
            "at": utc_now_iso(),
            "phase": str(phase or record.get("phase") or ""),
            "level": str(level or "info"),
            "message": str(message or ""),
        })
        self.update_deployment(deployment_id, logs=logs[-240:])

    def get_deployment(self, deployment_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._deployments_locked().get("deployments", {}).get(str(deployment_id or "").strip())
        return deepcopy(record) if record else None

    def list_deployments(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._deployments_locked().get("deployments", {}).values())
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return deepcopy(items[: max(1, min(int(limit or 40), 200))])


_STORAGE: DeployAtlasStorage | None = None


def get_deployatlas_storage() -> DeployAtlasStorage:
    global _STORAGE
    if _STORAGE is None:
        _STORAGE = DeployAtlasStorage()
    return _STORAGE
