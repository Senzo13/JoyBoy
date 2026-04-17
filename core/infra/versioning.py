"""JoyBoy version and update status helpers.

The app should not treat every commit as a user-facing release, but local git
checkouts are common for this project. This module reports both signals:
published GitHub releases for normal users, and origin/main drift for dev
checkouts.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


PROJECT_DIR = Path(__file__).resolve().parents[2]
VERSION_FILE = PROJECT_DIR / "VERSION"
DEFAULT_REPOSITORY = "Senzo13/JoyBoy"
DEFAULT_BRANCH = "main"
GITHUB_API_BASE = "https://api.github.com"

_CACHE: Dict[str, Any] = {"timestamp": 0.0, "payload": None}
_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?([0-9A-Za-z.-]+))?$")


def read_local_version() -> str:
    try:
        value = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    return value or "0.0.0-dev"


def normalize_tag(tag_or_version: str) -> str:
    value = str(tag_or_version or "").strip()
    return value if value.startswith("v") else f"v{value}"


def strip_version_prefix(tag_or_version: str) -> str:
    return str(tag_or_version or "").strip().lstrip("v")


def _pre_release_key(pre_release: Optional[str]) -> Tuple[int, Tuple[Tuple[int, Any], ...]]:
    if not pre_release:
        return (9, ())

    aliases = {
        "dev": 0,
        "a": 1,
        "alpha": 1,
        "b": 2,
        "beta": 2,
        "preview": 3,
        "pre": 3,
        "rc": 4,
    }
    parts: List[Tuple[int, Any]] = []
    for raw_part in re.split(r"[.-]+", pre_release.lower()):
        if not raw_part:
            continue
        if raw_part.isdigit():
            parts.append((1, int(raw_part)))
        else:
            parts.append((0, aliases.get(raw_part, 5), raw_part))
    return (parts[0][1] if parts and parts[0][0] == 0 else 5, tuple(parts))


def parse_version(value: str) -> Optional[Tuple[int, int, int, Tuple[int, Tuple[Tuple[int, Any], ...]]]]:
    match = _VERSION_RE.match(str(value or "").strip())
    if not match:
        return None
    major, minor, patch, pre_release = match.groups()
    return (
        int(major),
        int(minor or 0),
        int(patch or 0),
        _pre_release_key(pre_release),
    )


def is_version_newer(candidate: str, current: str) -> bool:
    candidate_key = parse_version(candidate)
    current_key = parse_version(current)
    if candidate_key is None or current_key is None:
        return strip_version_prefix(candidate) != strip_version_prefix(current)
    return candidate_key > current_key


def _run_git(args: List[str], timeout: float = 2.5) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _repo_from_remote(remote_url: str) -> str:
    remote_url = (remote_url or "").strip()
    patterns = [
        r"github\.com[:/](?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote_url)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return ""


def get_update_repository() -> str:
    configured = os.environ.get("JOYBOY_UPDATE_REPO", "").strip()
    if configured:
        return configured
    return _repo_from_remote(_run_git(["config", "--get", "remote.origin.url"])) or DEFAULT_REPOSITORY


def get_git_state() -> Dict[str, Any]:
    is_checkout = (PROJECT_DIR / ".git").exists()
    if not is_checkout:
        return {"is_git_checkout": False}

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    local_commit = _run_git(["rev-parse", "HEAD"])
    remote_url = _run_git(["config", "--get", "remote.origin.url"])
    target_branch = os.environ.get("JOYBOY_UPDATE_BRANCH", DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    remote_ref = f"refs/heads/{target_branch}"
    remote_output = _run_git(["ls-remote", "origin", remote_ref], timeout=4.0)
    latest_commit = remote_output.split()[0] if remote_output else ""
    dirty = bool(_run_git(["status", "--porcelain"], timeout=2.0))

    return {
        "is_git_checkout": True,
        "branch": branch,
        "target_branch": target_branch,
        "commit": local_commit,
        "short_commit": local_commit[:7] if local_commit else "",
        "remote_url": remote_url,
        "latest_commit": latest_commit,
        "latest_short_commit": latest_commit[:7] if latest_commit else "",
        "behind_remote": bool(local_commit and latest_commit and local_commit != latest_commit),
        "dirty": dirty,
    }


def _fetch_json(url: str, timeout: float = 5.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "JoyBoy-update-checker",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_release_from_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, list):
        return None

    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "").strip()
        if not tag:
            continue
        return {
            "tag": tag,
            "version": strip_version_prefix(tag),
            "name": item.get("name") or tag,
            "url": item.get("html_url") or "",
            "published_at": item.get("published_at") or "",
            "prerelease": bool(item.get("prerelease")),
        }
    return None


def fetch_latest_release(
    repository: str,
    fetch_json: Callable[[str], Any] = _fetch_json,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    url = f"{GITHUB_API_BASE}/repos/{repository}/releases?per_page=10"
    try:
        latest_release = _latest_release_from_payload(fetch_json(url))
        return latest_release, None if latest_release else "no_releases"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, "no_releases"
        return None, f"github_http_{exc.code}"
    except Exception as exc:
        return None, str(exc)


def build_version_status(
    current_version: str,
    repository: str,
    latest_release: Optional[Dict[str, Any]],
    git_state: Optional[Dict[str, Any]],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    git_state = git_state or {}
    release_url = f"https://github.com/{repository}/releases"
    target_branch = git_state.get("target_branch") or DEFAULT_BRANCH
    commit_url = f"https://github.com/{repository}/commits/{target_branch}"
    current_commit = str(git_state.get("commit") or "").strip()
    latest_commit = str(git_state.get("latest_commit") or "").strip()
    compare_url = (
        f"https://github.com/{repository}/compare/{current_commit}...{latest_commit}"
        if current_commit and latest_commit and current_commit != latest_commit
        else commit_url
    )
    latest_version = (latest_release or {}).get("version", "")

    update = {
        "available": False,
        "kind": "none",
        "status": "up_to_date",
        "url": release_url,
        "error": error or "",
    }

    if latest_release and is_version_newer(str(latest_version), current_version):
        update.update({
            "available": True,
            "kind": "release",
            "status": "release_available",
            "url": latest_release.get("url") or release_url,
        })
    elif git_state.get("behind_remote") and git_state.get("branch") == git_state.get("target_branch"):
        update.update({
            "available": True,
            "kind": "commit",
            "status": "commit_available",
            "url": compare_url,
        })
    elif latest_release is None and error == "no_releases":
        update.update({
            "status": "no_releases",
            "url": release_url,
        })
    elif error:
        update.update({
            "status": "unknown",
            "url": release_url,
        })

    return {
        "success": True,
        "repository": repository,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "version": current_version,
            "tag": normalize_tag(current_version),
        },
        "latest_release": latest_release,
        "git": git_state,
        "links": {
            "repository": f"https://github.com/{repository}",
            "releases": release_url,
            "commits": commit_url,
            "compare": compare_url,
        },
        "update": update,
    }


def _cache_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("JOYBOY_UPDATE_CACHE_SECONDS", "86400")))
    except ValueError:
        return 86400


def get_app_version_status(force_refresh: bool = False) -> Dict[str, Any]:
    if os.environ.get("JOYBOY_UPDATE_CHECK", "").strip().lower() in {"0", "false", "no", "off"}:
        return build_version_status(read_local_version(), get_update_repository(), None, get_git_state(), "disabled")

    now = time.time()
    cached_payload = _CACHE.get("payload")
    if not force_refresh and cached_payload and now - float(_CACHE.get("timestamp") or 0) < _cache_ttl_seconds():
        payload = copy.deepcopy(cached_payload)
        payload["cached"] = True
        return payload

    repository = get_update_repository()
    latest_release, error = fetch_latest_release(repository)
    payload = build_version_status(
        current_version=read_local_version(),
        repository=repository,
        latest_release=latest_release,
        git_state=get_git_state(),
        error=error,
    )
    payload["cached"] = False
    _CACHE["timestamp"] = now
    _CACHE["payload"] = copy.deepcopy(payload)
    return payload


__all__ = [
    "build_version_status",
    "fetch_latest_release",
    "get_app_version_status",
    "is_version_newer",
    "normalize_tag",
    "parse_version",
    "read_local_version",
]
