"""SSH client boundary for DeployAtlas.

Paramiko is optional at import time so JoyBoy can still boot before the user has
installed the deployment extras. Routes report the missing dependency clearly.
"""

from __future__ import annotations

import base64
import hashlib
import io
import socket
from dataclasses import dataclass
from typing import Any

from .security import redact_text, sanitize_value

try:  # pragma: no cover - availability depends on the local install.
    import paramiko  # type: ignore
except Exception:  # pragma: no cover
    paramiko = None  # type: ignore


@dataclass
class SshResult:
    success: bool
    status: str
    message: str
    fingerprint: str = ""
    remote_os: str = ""
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_value({
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "fingerprint": self.fingerprint,
            "remote_os": self.remote_os,
            "detail": self.detail or {},
        })


def paramiko_available() -> bool:
    return paramiko is not None


def fingerprint_sha256(key: Any) -> str:
    raw = key.asbytes()
    digest = hashlib.sha256(raw).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def fetch_host_fingerprint(host: str, port: int = 22, timeout: float = 8.0) -> str:
    if paramiko is None:
        raise RuntimeError("Paramiko n’est pas installé. Installe les dépendances DeployAtlas pour tester SSH.")
    sock = socket.create_connection((host, int(port or 22)), timeout=timeout)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        return fingerprint_sha256(key)
    finally:
        transport.close()


def _private_key_from_text(private_key: str, passphrase: str = "") -> Any:
    if paramiko is None:
        return None
    key_stream = io.StringIO(private_key)
    loaders = [
        paramiko.Ed25519Key.from_private_key,
        paramiko.RSAKey.from_private_key,
        paramiko.ECDSAKey.from_private_key,
        paramiko.DSSKey.from_private_key,
    ]
    last_error: Exception | None = None
    for loader in loaders:
        key_stream.seek(0)
        try:
            return loader(key_stream, password=passphrase or None)
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Clé SSH non lisible: {last_error}")


class DeployAtlasSshClient:
    def __init__(self, server: dict[str, Any], credentials: dict[str, Any] | None = None) -> None:
        self.server = server or {}
        self.credentials = credentials or {}
        self.client = None

    @property
    def host(self) -> str:
        return str(self.server.get("host") or "").strip()

    @property
    def port(self) -> int:
        try:
            return int(self.server.get("port") or 22)
        except Exception:
            return 22

    @property
    def username(self) -> str:
        return str(self.server.get("username") or "").strip()

    def connect(self, *, require_trusted_host: bool = True, trust_host_key: bool = False) -> SshResult:
        if paramiko is None:
            return SshResult(False, "dependency_missing", "Paramiko n’est pas installé côté JoyBoy.")
        if not self.host or not self.username:
            return SshResult(False, "invalid_server", "Hostname et utilisateur SSH requis.")

        try:
            fingerprint = fetch_host_fingerprint(self.host, self.port)
        except Exception as exc:
            return SshResult(False, "fingerprint_failed", redact_text(f"Impossible de lire la fingerprint SSH: {exc}"))

        known = str(self.server.get("host_fingerprint") or "").strip()
        if known and known != fingerprint:
            return SshResult(False, "host_key_changed", "La fingerprint SSH a changé. Connexion bloquée.", fingerprint)
        if require_trusted_host and not known and not trust_host_key:
            return SshResult(False, "requires_trust", "Nouvelle fingerprint SSH à valider avant connexion.", fingerprint)

        password = str(self.credentials.get("password") or "")
        private_key_text = str(self.credentials.get("private_key") or "")
        passphrase = str(self.credentials.get("passphrase") or "")
        if not password and not private_key_text:
            return SshResult(False, "missing_credentials", "Mot de passe ou clé SSH requis pour tester la connexion.", fingerprint)

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: dict[str, Any] = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": 10,
                "banner_timeout": 10,
                "auth_timeout": 14,
                "look_for_keys": False,
                "allow_agent": False,
            }
            if private_key_text:
                connect_kwargs["pkey"] = _private_key_from_text(private_key_text, passphrase)
            else:
                connect_kwargs["password"] = password
            client.connect(**connect_kwargs)
            self.client = client
            remote_os = self.exec("cat /etc/os-release 2>/dev/null | head -n 3; uname -s 2>/dev/null", timeout=8)
            return SshResult(True, "connected", "Connexion SSH validée.", fingerprint, remote_os.strip())
        except Exception as exc:
            return SshResult(False, "auth_failed", redact_text(f"Connexion SSH refusée: {exc}"), fingerprint)

    def exec(self, command: str, *, timeout: int = 60) -> str:
        if self.client is None:
            raise RuntimeError("SSH client is not connected")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        if exit_code != 0:
            raise RuntimeError(redact_text(err or out or f"Remote command failed: {exit_code}"))
        return redact_text(out)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
