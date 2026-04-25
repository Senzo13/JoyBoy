"""Security helpers for DeployAtlas.

DeployAtlas handles deployment credentials and command logs. Keep the redaction
logic centralized so routes, jobs and storage never grow their own secret rules.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable


SECRET_FIELD_NAMES = {
    "password",
    "passphrase",
    "private_key",
    "privatekey",
    "ssh_key",
    "sshkey",
    "token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "cookie",
}

PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passphrase|token|api[_-]?key|secret|authorization|cookie)\s*[:=]\s*([^\s,;]+)"
)


def is_secret_field(key: Any) -> bool:
    clean = str(key or "").strip().lower().replace("-", "_")
    return clean in SECRET_FIELD_NAMES or any(part in SECRET_FIELD_NAMES for part in clean.split("_"))


def redact_text(value: Any, extra_secrets: Iterable[str] | None = None) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = PRIVATE_KEY_RE.sub("[redacted-private-key]", text)
    text = INLINE_SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    for secret in extra_secrets or []:
        secret_text = str(secret or "")
        if len(secret_text) >= 4:
            text = text.replace(secret_text, "[redacted]")
    return text


def sanitize_value(value: Any, extra_secrets: Iterable[str] | None = None) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if is_secret_field(key):
                cleaned[str(key)] = "[redacted]" if item else ""
            else:
                cleaned[str(key)] = sanitize_value(item, extra_secrets)
        return cleaned
    if isinstance(value, list):
        return [sanitize_value(item, extra_secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, extra_secrets)
    return deepcopy(value)


def public_server_record(server: dict[str, Any] | None) -> dict[str, Any]:
    data = sanitize_value(server or {})
    data.pop("password", None)
    data.pop("private_key", None)
    data.pop("passphrase", None)
    data.pop("ssh_key", None)
    data["has_saved_secret"] = False
    return data
