"""Shared target validation for public web audit modules."""

from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlparse


PUBLIC_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def is_valid_public_host(hostname: str) -> bool:
    clean = str(hostname or "").strip().lower().rstrip(".")
    if not clean or "." not in clean:
        return False
    labels = [label for label in clean.split(".") if label]
    if len(labels) < 2:
        return False
    if len(labels[-1]) < 2 or labels[-1].isdigit():
        return False
    return all(PUBLIC_HOST_LABEL_RE.fullmatch(label) for label in labels)


def normalize_public_target(raw_value: str, mode: str) -> Dict[str, Any]:
    value = str(raw_value or "").strip()
    if not value:
        raise ValueError("target required")
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("invalid target url")
    if parsed.username or parsed.password:
        raise ValueError("invalid target url")
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname or not is_valid_public_host(hostname):
        raise ValueError("invalid target url")
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    normalized = parsed._replace(netloc=netloc, path=parsed.path or "/", params="", query="", fragment="").geturl()
    return {
        "raw": raw_value,
        "normalized_url": normalized,
        "host": netloc,
        "mode": str(mode or "public").strip().lower() or "public",
    }
