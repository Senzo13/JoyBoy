"""Defensive web and API security auditing for CyberAtlas."""

from __future__ import annotations

import json
import re
import socket
import ssl
import ipaddress
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.audit_modules.targets import normalize_public_target

from .scoring import score_findings


ProgressCallback = Optional[Callable[[str, float, str], None]]
CancelCheck = Optional[Callable[[], bool]]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JoyBoy CyberAtlas/1.0; +https://joyboy.local)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}

SECURITY_HEADER_KEYS = (
    "strict-transport-security",
    "content-security-policy",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
)

SAFE_EXPOSURE_PATHS = (
    "/.well-known/security.txt",
    "/security.txt",
    "/robots.txt",
    "/sitemap.xml",
    "/openapi.json",
    "/swagger.json",
    "/api-docs",
    "/swagger/v1/swagger.json",
    "/.git/HEAD",
    "/.env",
    "/config.json",
    "/phpinfo.php",
    "/server-status",
    "/debug",
    "/admin",
    "/login",
)

SENSITIVE_PATHS = {
    "/.git/HEAD": "public_git_metadata",
    "/.env": "environment_file_exposed",
    "/config.json": "public_config_file",
    "/phpinfo.php": "phpinfo_exposed",
    "/server-status": "server_status_exposed",
    "/debug": "debug_endpoint_exposed",
}

SWAGGER_PATHS = (
    "/openapi.json",
    "/swagger.json",
    "/api-docs",
    "/swagger/v1/swagger.json",
    "/swagger/v2/swagger.json",
    "/swagger/v3/swagger.json",
    "/api/swagger.json",
    "/api/openapi.json",
    "/docs/swagger.json",
    "/docs/openapi.json",
    "/v1/openapi.json",
    "/v2/openapi.json",
    "/v3/openapi.json",
)

API_DISCOVERY_PATHS = (
    "/api",
    "/api/v1",
    "/api/v2",
    "/api/v3",
    "/api/auth",
    "/api/login",
    "/api/session",
    "/api/users",
    "/api/user",
    "/api/me",
    "/api/admin",
    "/api/debug",
    "/api/health",
    "/api/status",
    "/api/config",
    "/api/search",
    "/api/upload",
    "/api/files",
    "/api/graphql",
    "/graphql",
    "/graphiql",
    "/graphql/playground",
    "/playground",
    "/socket.io",
    "/ws",
    "/wss",
    "/realtime",
    "/admin",
    "/login",
    "/auth",
    "/dashboard",
    "/wp-json",
    "/.well-known/openid-configuration",
)

AUTH_ENDPOINT_HINTS = (
    "auth",
    "login",
    "session",
    "signin",
    "signup",
    "oauth",
    "password",
    "token",
)

SENSITIVE_ENDPOINT_HINTS = (
    "admin",
    "debug",
    "config",
    "secret",
    "token",
    "user",
    "users",
    "account",
    "payment",
    "billing",
    "upload",
    "files",
    "export",
    "dump",
)

API_REFERENCE_RE = re.compile(
    r"""(?P<url>(?:https?:)?//[^\s"'<>`{}|\\]+|/(?:api|graphql|graphiql|playground|socket\.io|ws|wss|realtime|v\d+)[^\s"'<>`{}|\\]*)""",
    re.IGNORECASE,
)
SOURCE_MAP_RE = re.compile(r"sourceMappingURL=([^\s*]+)", re.IGNORECASE)
SECRET_NAME_RE = re.compile(
    r"\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|private[_-]?key|password|passwd|mongodb_uri|database_url)\b",
    re.IGNORECASE,
)

ERROR_PATTERNS = (
    "traceback (most recent call last)",
    "stack trace",
    "uncaught exception",
    "syntaxerror",
    "typeerror:",
    "referenceerror:",
    "sql syntax",
    "mysql_fetch",
    "postgresql",
    "mongodb",
    "prisma client",
    "django debug",
    "laravel exception",
    "express error",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(progress_callback: ProgressCallback, phase: str, progress: float, message: str) -> None:
    if callable(progress_callback):
        progress_callback(phase, progress, message)


def _cancelled(cancel_check: CancelCheck) -> bool:
    if not callable(cancel_check):
        return False
    try:
        return bool(cancel_check())
    except Exception:
        return False


def _same_host(left: str, right: str) -> bool:
    return str(left or "").strip().lower().rstrip(".") == str(right or "").strip().lower().rstrip(".")


def _normalize_url(url: str, base_url: str) -> str:
    resolved = urljoin(base_url, url or "")
    parsed = urlparse(resolved)
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    return parsed._replace(fragment="", params="").geturl()


def _dedupe_rows(rows: Iterable[Dict[str, Any]], key: str = "url", limit: int = 80) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for row in rows:
        marker = str(row.get(key) or row.get("path") or "").strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        output.append(row)
        if len(output) >= limit:
            break
    return output


def _is_private_hostname(hostname: str) -> bool:
    host = str(hostname or "").strip().lower().strip("[]")
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def _extract_api_references(text: str, base_url: str, host: str, source: str = "html") -> List[Dict[str, Any]]:
    references: List[Dict[str, Any]] = []
    if not text:
        return references
    for match in API_REFERENCE_RE.finditer(text[:350_000]):
        raw = str(match.group("url") or "").strip().rstrip(").,;")
        if not raw or len(raw) > 260:
            continue
        if raw.startswith("//"):
            raw = f"{urlparse(base_url).scheme or 'https'}:{raw}"
        normalized = _normalize_url(raw, base_url)
        if not normalized:
            continue
        parsed = urlparse(normalized)
        path = parsed.path or "/"
        lower_path = path.lower()
        kind = "api"
        if "graphql" in lower_path or "graphiql" in lower_path or "playground" in lower_path:
            kind = "graphql"
        elif "socket.io" in lower_path or lower_path in {"/ws", "/wss", "/realtime"}:
            kind = "realtime"
        references.append({
            "url": normalized,
            "path": path,
            "host": parsed.hostname or "",
            "same_origin": _same_host(parsed.hostname or "", host),
            "private_host": _is_private_hostname(parsed.hostname or ""),
            "kind": kind,
            "source": source,
        })
    return _dedupe_rows(references, key="url", limit=80)


def _extract_source_maps(text: str, base_url: str) -> List[str]:
    maps: List[str] = []
    for match in SOURCE_MAP_RE.finditer(text or ""):
        raw = str(match.group(1) or "").strip().strip("'\"")
        normalized = _normalize_url(raw, base_url)
        if normalized:
            maps.append(normalized)
    return sorted(set(maps))[:30]


def _secret_name_hints(text: str) -> List[str]:
    return sorted(set(match.group(0).lower() for match in SECRET_NAME_RE.finditer(text or "")))[:30]


def _header_dict(headers: Any) -> Dict[str, str]:
    return {str(k).lower(): str(v) for k, v in (headers or {}).items()}


def _interesting_headers(headers: Any) -> Dict[str, str]:
    lower = _header_dict(headers)
    keep = set(SECURITY_HEADER_KEYS) | {
        "server",
        "x-powered-by",
        "access-control-allow-origin",
        "access-control-allow-credentials",
        "set-cookie",
        "content-type",
        "cache-control",
        "x-robots-tag",
    }
    return {key: lower[key] for key in sorted(keep) if key in lower}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_text(response: requests.Response, limit: int = 220_000) -> str:
    try:
        content = response.content[:limit]
        return content.decode(response.encoding or "utf-8", errors="replace")
    except Exception:
        return ""


def _make_finding(
    *,
    finding_id: str,
    title: str,
    severity: str,
    confidence: str,
    bucket: str,
    category: str,
    scope: str,
    evidence: Iterable[str],
    diagnostic: str,
    recommended_fix: str,
    acceptance_criteria: str,
    probable_cause: str = "",
    expected_impact: str = "",
    dev_prompt: str = "",
    root_cause: bool = False,
    evidence_mode: str = "public_probe",
) -> Dict[str, Any]:
    return {
        "id": finding_id,
        "title": title,
        "severity": severity,
        "confidence": confidence,
        "bucket": bucket,
        "category": category,
        "scope": scope,
        "evidence": [str(item) for item in evidence if str(item).strip()],
        "diagnostic": diagnostic,
        "probable_cause": probable_cause or diagnostic,
        "recommended_fix": recommended_fix,
        "acceptance_criteria": acceptance_criteria,
        "expected_impact": expected_impact or severity.title(),
        "dev_prompt": dev_prompt or recommended_fix,
        "root_cause": root_cause,
        "evidence_mode": evidence_mode,
        "relationship_summary": diagnostic,
    }


def _profile_settings(max_pages: int, max_endpoints: int) -> Dict[str, Any]:
    if max_pages <= 3:
        return {
            "label": "basic",
            "page_budget": max(1, min(3, max_pages)),
            "endpoint_budget": max(6, min(12, max_endpoints)),
            "probe_budget": 8,
        }
    if max_pages <= 8:
        return {
            "label": "elevated",
            "page_budget": max(3, min(8, max_pages)),
            "endpoint_budget": max(12, min(32, max_endpoints)),
            "probe_budget": 12,
        }
    return {
        "label": "ultra",
        "page_budget": max(8, min(24, max_pages)),
        "endpoint_budget": max(24, min(80, max_endpoints)),
        "probe_budget": len(SAFE_EXPOSURE_PATHS),
    }


def _collect_tls(host: str, port: int = 443, timeout: int = 5) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "available": False,
        "host": host,
        "port": port,
        "protocol": "",
        "issuer": "",
        "subject": "",
        "not_after": "",
        "days_remaining": None,
        "error": "",
    }
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                not_after = cert.get("notAfter") or ""
                days_remaining = None
                if not_after:
                    expires = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    days_remaining = int((expires - datetime.now(timezone.utc)).total_seconds() // 86400)
                issuer = " / ".join("=".join(part) for group in cert.get("issuer", []) for part in group)
                subject = " / ".join("=".join(part) for group in cert.get("subject", []) for part in group)
                result.update({
                    "available": True,
                    "protocol": tls.version() or "",
                    "issuer": issuer,
                    "subject": subject,
                    "not_after": not_after,
                    "days_remaining": days_remaining,
                })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _fetch_page(session: requests.Session, url: str, depth: int, host: str) -> Tuple[Optional[Dict[str, Any]], List[str], str]:
    response = session.get(url, timeout=12, allow_redirects=True)
    text = _safe_text(response)
    content_type = str(response.headers.get("Content-Type") or "")
    soup = BeautifulSoup(text or "", "html.parser")
    final_url = response.url or url
    forms = []
    for form in soup.select("form"):
        fields = []
        for field in form.select("input, textarea, select"):
            fields.append({
                "name": str(field.get("name") or "").strip(),
                "type": str(field.get("type") or field.name or "").strip().lower(),
                "autocomplete": str(field.get("autocomplete") or "").strip().lower(),
            })
        forms.append({
            "action": _normalize_url(form.get("action") or final_url, final_url),
            "method": str(form.get("method") or "get").strip().upper(),
            "field_count": len(fields),
            "has_password": any(item.get("type") == "password" for item in fields),
            "field_names": [item.get("name") for item in fields if item.get("name")][:16],
            "fields": fields[:24],
        })
    internal_links: List[str] = []
    external_hosts = set()
    for anchor in soup.select("a[href]"):
        href = _normalize_url(anchor.get("href") or "", final_url)
        if not href:
            continue
        parsed = urlparse(href)
        if _same_host(parsed.hostname or "", host):
            internal_links.append(href)
        elif parsed.hostname:
            external_hosts.add(str(parsed.hostname).lower())
    assets = []
    for tag, attr, kind in (
        ("script[src]", "src", "script"),
        ("link[href]", "href", "link"),
        ("img[src]", "src", "image"),
        ("iframe[src]", "src", "iframe"),
    ):
        for node in soup.select(tag):
            asset_url = _normalize_url(node.get(attr) or "", final_url)
            if asset_url:
                asset = {"url": asset_url, "kind": kind}
                if kind == "script":
                    asset.update({
                        "integrity": str(node.get("integrity") or "").strip(),
                        "crossorigin": str(node.get("crossorigin") or "").strip(),
                        "async": node.has_attr("async"),
                        "defer": node.has_attr("defer"),
                    })
                if kind == "link":
                    asset["rel"] = " ".join(str(item) for item in (node.get("rel") or []))
                    asset["integrity"] = str(node.get("integrity") or "").strip()
                assets.append(asset)
    page = {
        "url": url,
        "final_url": final_url,
        "status_code": int(response.status_code),
        "depth": depth,
        "content_type": content_type,
        "title": str(soup.title.string or "").strip() if soup.title and soup.title.string else "",
        "headers": _interesting_headers(response.headers),
        "redirect_count": len(response.history or []),
        "body_excerpt": re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:600],
        "body_error_indicators": [pat for pat in ERROR_PATTERNS if pat in text.lower()][:8],
        "form_count": len(forms),
        "password_form_count": len([item for item in forms if item.get("has_password")]),
        "forms": forms,
        "assets": assets[:80],
        "script_count": len([item for item in assets if item.get("kind") == "script"]),
        "script_without_sri_count": len([
            item for item in assets
            if item.get("kind") == "script"
            and not _same_host(urlparse(str(item.get("url") or "")).hostname or "", host)
            and not item.get("integrity")
        ]),
        "mixed_content_count": len([
            item for item in assets
            if final_url.startswith("https://") and str(item.get("url") or "").startswith("http://")
        ]),
        "body_api_hints": _extract_api_references(text, final_url, host, source="html")[:40],
        "source_map_hints": _extract_source_maps(text, final_url),
        "secret_name_hints": _secret_name_hints(text),
        "external_hosts": sorted(external_hosts)[:20],
        "internal_links": sorted(set(internal_links))[:120],
    }
    if "html" not in content_type.lower() and not text.lstrip().lower().startswith(("<!doctype", "<html")):
        return page, [], text
    return page, page["internal_links"], text


def _fetch_probe(session: requests.Session, base_url: str, path: str) -> Dict[str, Any]:
    target = urljoin(base_url, path)
    try:
        response = session.get(target, timeout=8, allow_redirects=True, stream=False)
        body = _safe_text(response, 80_000)
        content_type = str(response.headers.get("Content-Type") or "")
        textish = any(
            marker in content_type.lower()
            for marker in ("text", "json", "xml", "javascript", "html")
        )
        parsed_json: Optional[Any] = None
        if response.ok and len(response.content or b"") <= 250_000 and any(
            marker in content_type.lower() for marker in ("json", "openapi", "swagger")
        ):
            try:
                parsed_json = response.json()
            except Exception:
                parsed_json = None
        body_sample = body[:1000] if textish else ""
        return {
            "path": path,
            "url": target,
            "final_url": response.url or target,
            "status_code": int(response.status_code),
            "content_type": content_type,
            "content_length": _safe_int(response.headers.get("Content-Length"), len(response.content or b"")),
            "headers": _interesting_headers(response.headers),
            "body_sample": body_sample,
            "json": parsed_json,
            "exists": int(response.status_code) < 400,
        }
    except Exception as exc:
        return {
            "path": path,
            "url": target,
            "status_code": None,
            "content_type": "",
            "content_length": 0,
            "headers": {},
            "body_sample": "",
            "exists": False,
            "error": str(exc),
        }


def _discover_openapi(probes: List[Dict[str, Any]], endpoint_budget: int) -> Dict[str, Any]:
    spec_probe = next((
        item for item in probes
        if item.get("exists") and str(item.get("path") or "").lower() in set(SWAGGER_PATHS)
    ), None)
    if not spec_probe:
        return {"available": False, "endpoint_count": 0, "endpoints": [], "unauthenticated_count": 0, "source_url": ""}
    spec = spec_probe.get("json")
    if not isinstance(spec, dict):
        return {
            "available": True,
            "parse_error": True,
            "endpoint_count": 0,
            "endpoints": [],
            "unauthenticated_count": 0,
            "source_url": spec_probe.get("final_url") or spec_probe.get("url") or "",
        }
    paths = spec.get("paths") or {}
    global_security = spec.get("security") or []
    endpoints: List[Dict[str, Any]] = []
    unauthenticated = 0
    state_changing = 0
    state_changing_without_security = 0
    sensitive_parameters = 0
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            clean_method = str(method or "").upper()
            if clean_method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            op = operation if isinstance(operation, dict) else {}
            security = op.get("security", global_security)
            if not security:
                unauthenticated += 1
            if clean_method in {"POST", "PUT", "PATCH", "DELETE"}:
                state_changing += 1
                if not security:
                    state_changing_without_security += 1
            parameter_names = []
            for param in op.get("parameters") or []:
                if isinstance(param, dict):
                    name = str(param.get("name") or "")
                    if name:
                        parameter_names.append(name)
            request_body = op.get("requestBody") if isinstance(op.get("requestBody"), dict) else {}
            if request_body:
                parameter_names.append("requestBody")
            sensitive_param_names = [
                name for name in parameter_names
                if any(token in name.lower() for token in ("token", "password", "secret", "email", "user", "account", "admin"))
            ]
            sensitive_parameters += len(sensitive_param_names)
            endpoints.append({
                "method": clean_method,
                "path": str(path),
                "summary": str(op.get("summary") or op.get("operationId") or "")[:160],
                "security_declared": bool(security),
                "parameter_names": parameter_names[:20],
                "sensitive_parameter_names": sensitive_param_names[:12],
            })
            if len(endpoints) >= endpoint_budget:
                break
        if len(endpoints) >= endpoint_budget:
            break
    return {
        "available": True,
        "parse_error": False,
        "source_url": spec_probe.get("final_url") or spec_probe.get("url") or "",
        "endpoint_count": len(endpoints),
        "unauthenticated_count": unauthenticated,
        "state_changing_count": state_changing,
        "state_changing_without_security_count": state_changing_without_security,
        "sensitive_parameter_count": sensitive_parameters,
        "endpoints": endpoints,
        "title": str((spec.get("info") or {}).get("title") or ""),
        "version": str((spec.get("info") or {}).get("version") or ""),
    }


def _collect_frontend_code_hints(session: requests.Session, pages: List[Dict[str, Any]], host: str, script_budget: int = 6) -> Dict[str, Any]:
    references: List[Dict[str, Any]] = []
    source_maps: List[str] = []
    secret_names = set()
    scripts_seen = set()
    script_samples: List[Dict[str, Any]] = []
    third_party_script_count = 0
    third_party_script_without_sri_count = 0

    for page in pages:
        references.extend(page.get("body_api_hints") or [])
        source_maps.extend(page.get("source_map_hints") or [])
        secret_names.update(page.get("secret_name_hints") or [])
        for asset in page.get("assets") or []:
            if asset.get("kind") != "script":
                continue
            script_url = str(asset.get("url") or "")
            parsed = urlparse(script_url)
            if not _same_host(parsed.hostname or "", host):
                third_party_script_count += 1
                if not asset.get("integrity"):
                    third_party_script_without_sri_count += 1
                continue
            if script_url in scripts_seen:
                continue
            scripts_seen.add(script_url)
            if len(scripts_seen) > script_budget:
                continue
            try:
                response = session.get(script_url, timeout=8, allow_redirects=True)
                body = _safe_text(response, 260_000)
            except Exception as exc:
                script_samples.append({
                    "url": script_url,
                    "status_code": None,
                    "error": str(exc),
                    "api_reference_count": 0,
                    "secret_name_hints": [],
                    "source_maps": [],
                })
                continue
            refs = _extract_api_references(body, script_url, host, source="script")
            maps = _extract_source_maps(body, script_url)
            names = _secret_name_hints(body)
            references.extend(refs)
            source_maps.extend(maps)
            secret_names.update(names)
            script_samples.append({
                "url": response.url or script_url,
                "status_code": int(response.status_code),
                "content_type": str(response.headers.get("Content-Type") or ""),
                "content_length": _safe_int(response.headers.get("Content-Length"), len(response.content or b"")),
                "api_reference_count": len(refs),
                "secret_name_hints": names[:12],
                "source_maps": maps[:8],
            })

    references = _dedupe_rows(references, key="url", limit=120)
    source_map_urls = sorted(set(source_maps))[:40]
    source_map_records: List[Dict[str, Any]] = []
    for map_url in source_map_urls[:8]:
        try:
            response = session.get(map_url, timeout=6, allow_redirects=True, stream=True)
            source_map_records.append({
                "url": response.url or map_url,
                "status_code": int(response.status_code),
                "reachable": int(response.status_code) < 400,
                "content_type": str(response.headers.get("Content-Type") or ""),
                "content_length": _safe_int(response.headers.get("Content-Length"), 0),
            })
        except Exception as exc:
            source_map_records.append({
                "url": map_url,
                "status_code": None,
                "reachable": False,
                "content_type": "",
                "content_length": 0,
                "error": str(exc),
            })
    backend_hosts = sorted({
        str(item.get("host") or "").lower()
        for item in references
        if item.get("host") and not item.get("same_origin")
    })[:30]
    private_backend_hosts = sorted({
        str(item.get("host") or "").lower()
        for item in references
        if item.get("private_host")
    })[:30]
    return {
        "api_references": references,
        "api_reference_count": len(references),
        "backend_hosts": backend_hosts,
        "private_backend_hosts": private_backend_hosts,
        "source_maps": source_map_urls,
        "source_map_records": source_map_records,
        "source_map_count": len(source_map_urls),
        "reachable_source_map_count": len([item for item in source_map_records if item.get("reachable")]),
        "secret_name_hints": sorted(secret_names)[:30],
        "script_samples": script_samples,
        "scripts_sampled": len(script_samples),
        "third_party_script_count": third_party_script_count,
        "third_party_script_without_sri_count": third_party_script_without_sri_count,
    }


def _fetch_options(session: requests.Session, url: str) -> Dict[str, Any]:
    try:
        response = session.options(url, timeout=6, allow_redirects=True)
        headers = _interesting_headers(response.headers)
        allow = str(response.headers.get("Allow") or response.headers.get("Access-Control-Allow-Methods") or "")
        methods = sorted({item.strip().upper() for item in re.split(r"[, ]+", allow) if item.strip()})
        return {
            "status_code": int(response.status_code),
            "allowed_methods": methods,
            "headers": headers,
        }
    except Exception as exc:
        return {"status_code": None, "allowed_methods": [], "headers": {}, "error": str(exc)}


def _is_endpoint_alive(status: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return 200 <= code < 400 or code in {401, 403, 405, 429}


def _is_sensitive_endpoint_path(path: str) -> bool:
    lower = str(path or "").lower()
    return any(token in lower for token in SENSITIVE_ENDPOINT_HINTS)


def _is_auth_endpoint_path(path: str) -> bool:
    lower = str(path or "").lower()
    return any(token in lower for token in AUTH_ENDPOINT_HINTS)


def _discover_endpoint_inventory(
    session: requests.Session,
    entry_url: str,
    frontend_hints: Dict[str, Any],
    endpoint_budget: int,
    active_checks: bool,
) -> Dict[str, Any]:
    candidates: List[str] = list(API_DISCOVERY_PATHS)
    for ref in frontend_hints.get("api_references") or []:
        if not ref.get("same_origin"):
            continue
        path = str(ref.get("path") or "")
        if path and path not in candidates:
            candidates.append(path)

    budget = max(8, min(80 if active_checks else 32, int(endpoint_budget or 32)))
    records: List[Dict[str, Any]] = []
    for path in candidates[:budget]:
        probe = _fetch_probe(session, entry_url, path)
        status = probe.get("status_code")
        if not _is_endpoint_alive(status):
            continue
        final_url = str(probe.get("final_url") or probe.get("url") or urljoin(entry_url, path))
        options = _fetch_options(session, final_url) if len(records) < (18 if active_checks else 8) else {"allowed_methods": []}
        content_type = str(probe.get("content_type") or "")
        response_type = "json" if "json" in content_type.lower() else "html" if "html" in content_type.lower() else "other"
        records.append({
            "path": path,
            "url": final_url,
            "status_code": status,
            "response_type": response_type,
            "requires_auth": int(status or 0) in {401, 403},
            "rate_limited": int(status or 0) == 429,
            "sensitive": _is_sensitive_endpoint_path(path),
            "auth_related": _is_auth_endpoint_path(path),
            "content_type": content_type,
            "content_length": probe.get("content_length", 0),
            "allowed_methods": options.get("allowed_methods") or [],
            "options_status": options.get("status_code"),
        })

    return {
        "endpoint_count": len(records),
        "auth_protected_count": len([item for item in records if item.get("requires_auth")]),
        "sensitive_count": len([item for item in records if item.get("sensitive")]),
        "public_sensitive_count": len([item for item in records if item.get("sensitive") and not item.get("requires_auth")]),
        "rate_limited_count": len([item for item in records if item.get("rate_limited")]),
        "auth_related_count": len([item for item in records if item.get("auth_related")]),
        "endpoints": records,
    }


def _detect_protections(headers: Dict[str, str], probes: List[Dict[str, Any]], pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_headers: Dict[str, str] = {}
    for source in [headers] + [page.get("headers") or {} for page in pages] + [probe.get("headers") or {} for probe in probes]:
        all_headers.update({str(k).lower(): str(v) for k, v in (source or {}).items()})
    combined = " ".join(f"{key}:{value}" for key, value in all_headers.items()).lower()
    body_samples = " ".join(str(probe.get("body_sample") or "")[:1000].lower() for probe in probes)
    cdn = []
    if "cloudflare" in combined or "cf-ray" in all_headers:
        cdn.append("Cloudflare")
    if "x-vercel-id" in all_headers or "vercel" in combined:
        cdn.append("Vercel")
    if "x-nf-request-id" in all_headers or "netlify" in combined:
        cdn.append("Netlify")
    if "cloudfront" in combined:
        cdn.append("AWS CloudFront")
    if "akamai" in combined:
        cdn.append("Akamai")
    if "fastly" in combined:
        cdn.append("Fastly")
    waf_signals = [
        label for label in ("sucuri", "imperva", "incapsula", "akamai", "cloudflare", "x-waf", "bot management")
        if label in combined or label in body_samples
    ]
    rate_limit_headers = sorted([
        key for key in all_headers
        if "ratelimit" in key or key in {"retry-after", "x-rate-limit-limit", "x-ratelimit-limit"}
    ])
    return {
        "cdn": sorted(set(cdn)),
        "waf_signals": sorted(set(waf_signals)),
        "waf_detected": bool(waf_signals),
        "rate_limit_headers": rate_limit_headers,
        "rate_limit_detected": bool(rate_limit_headers) or any(int(probe.get("status_code") or 0) == 429 for probe in probes),
        "captcha_or_challenge": "captcha" in body_samples or "challenge" in body_samples or "cf-chl" in combined,
        "server_fingerprints": {
            key: all_headers.get(key)
            for key in ("server", "x-powered-by", "x-aspnet-version", "x-generator")
            if all_headers.get(key)
        },
    }


def _infer_framework(pages: List[Dict[str, Any]], protections: Dict[str, Any]) -> str:
    fingerprints = " ".join(str(value).lower() for value in (protections.get("server_fingerprints") or {}).values())
    asset_urls = " ".join(
        str(asset.get("url") or "").lower()
        for page in pages
        for asset in (page.get("assets") or [])
    )
    text = f"{fingerprints} {asset_urls}"
    checks = [
        ("Next.js", ("/_next/", "next.js", "x-nextjs")),
        ("Nuxt", ("/_nuxt/", "nuxt")),
        ("WordPress", ("wp-content", "wp-json", "wordpress")),
        ("Laravel", ("laravel", "x-powered-by: php")),
        ("Django", ("django", "csrftoken")),
        ("Ruby on Rails", ("rails", "ruby")),
        ("ASP.NET", ("asp.net", "x-aspnet")),
        ("Express", ("express",)),
        ("Vite", ("/assets/", "vite")),
    ]
    for label, tokens in checks:
        if any(token in text for token in tokens):
            return label
    return ""


def _build_recon_summary(
    pages: List[Dict[str, Any]],
    probes: List[Dict[str, Any]],
    openapi: Dict[str, Any],
    api_inventory: Dict[str, Any],
    frontend_hints: Dict[str, Any],
    protections: Dict[str, Any],
) -> Dict[str, Any]:
    combined_parts: List[str] = []
    for page in pages:
        combined_parts.append(" ".join(page.get("body_error_indicators") or []))
    combined_parts.append(" ".join(str(item.get("path") or "") for item in api_inventory.get("endpoints") or []))
    combined_parts.append(" ".join(frontend_hints.get("secret_name_hints") or []))
    combined_text = " ".join(combined_parts).lower()
    db_type = "Unknown"
    if any(token in combined_text for token in ("mongodb", "mongo", "nosql", "mongoose")):
        db_type = "NoSQL"
    elif any(token in combined_text for token in ("mysql", "postgres", "sqlite", "mssql", "sql syntax", "prisma")):
        db_type = "SQL"
    auth_surface_count = int(api_inventory.get("auth_related_count") or 0) + len([
        form for page in pages for form in (page.get("forms") or []) if form.get("has_password")
    ])
    return {
        "framework": _infer_framework(pages, protections),
        "database_type": db_type,
        "cdn": protections.get("cdn") or [],
        "waf_detected": bool(protections.get("waf_detected")),
        "rate_limit_detected": bool(protections.get("rate_limit_detected")),
        "auth_surface_count": auth_surface_count,
        "auth_protected_endpoint_count": int(api_inventory.get("auth_protected_count") or 0),
        "sensitive_public_endpoint_count": int(api_inventory.get("public_sensitive_count") or 0),
        "frontend_api_reference_count": int(frontend_hints.get("api_reference_count") or 0),
        "frontend_backend_host_count": len(frontend_hints.get("backend_hosts") or []),
        "private_backend_host_count": len(frontend_hints.get("private_backend_hosts") or []),
        "source_map_count": int(frontend_hints.get("source_map_count") or 0),
        "openapi_state_changing_without_security_count": int(openapi.get("state_changing_without_security_count") or 0),
        "graphql_public": any("graphql" in str(item.get("path") or "").lower() and not item.get("requires_auth") for item in api_inventory.get("endpoints") or []),
        "realtime_public": any(any(token in str(item.get("path") or "").lower() for token in ("socket.io", "/ws", "/wss", "realtime")) for item in api_inventory.get("endpoints") or []),
    }


def _header_findings(url: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    csp = headers.get("content-security-policy", "")
    hsts = headers.get("strict-transport-security", "")
    xfo = headers.get("x-frame-options", "")
    xcto = headers.get("x-content-type-options", "")
    referrer = headers.get("referrer-policy", "")
    permissions = headers.get("permissions-policy", "")
    coop = headers.get("cross-origin-opener-policy", "")
    server = headers.get("server", "")
    powered = headers.get("x-powered-by", "")
    acao = headers.get("access-control-allow-origin", "")
    acac = headers.get("access-control-allow-credentials", "")

    if url.startswith("https://") and not hsts:
        findings.append(_make_finding(
            finding_id="missing-hsts",
            title="HSTS is missing on the HTTPS entry response",
            severity="high",
            confidence="Confirmed",
            bucket="transport_tls",
            category="transport",
            scope=url,
            evidence=["Strict-Transport-Security header is absent."],
            diagnostic="Browsers are not instructed to pin HTTPS for this origin.",
            recommended_fix="Send Strict-Transport-Security with a long max-age after verifying all subdomains support HTTPS.",
            acceptance_criteria="The final HTTPS response includes a reviewed HSTS policy.",
            root_cause=True,
        ))
    if not csp:
        findings.append(_make_finding(
            finding_id="missing-csp",
            title="Content Security Policy is missing",
            severity="high",
            confidence="Confirmed",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=["Content-Security-Policy header is absent."],
            diagnostic="The browser has no policy-level guardrail against script injection or unsafe embedding.",
            recommended_fix="Deploy a nonce/hash-based CSP in report-only mode first, then enforce it once violations are clean.",
            acceptance_criteria="A production CSP is present, monitored, and does not rely on broad wildcards for scripts.",
            root_cause=True,
        ))
    elif "unsafe-inline" in csp or "script-src *" in csp or "default-src *" in csp:
        findings.append(_make_finding(
            finding_id="weak-csp",
            title="Content Security Policy is present but weak",
            severity="medium",
            confidence="Strong signal",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=[f"CSP: {csp[:220]}"],
            diagnostic="The policy still allows broad script execution paths that reduce XSS protection value.",
            recommended_fix="Replace broad script allowances with nonces, hashes, and explicit trusted origins.",
            acceptance_criteria="The enforced CSP removes unsafe inline script execution from the critical path.",
        ))
    if not xfo and "frame-ancestors" not in csp:
        findings.append(_make_finding(
            finding_id="missing-clickjacking-control",
            title="Clickjacking protection is not declared",
            severity="medium",
            confidence="Confirmed",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=["No X-Frame-Options header and no CSP frame-ancestors directive."],
            diagnostic="The site does not declare who may embed it in frames.",
            recommended_fix="Set CSP frame-ancestors to the exact allowed origins, or DENY/SAMEORIGIN where appropriate.",
            acceptance_criteria="Embedding policy is explicit on all HTML entry responses.",
        ))
    if xcto.lower() != "nosniff":
        findings.append(_make_finding(
            finding_id="missing-nosniff",
            title="MIME sniffing protection is missing",
            severity="low",
            confidence="Confirmed",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=[f"X-Content-Type-Options: {xcto or 'absent'}"],
            diagnostic="Browsers may attempt content sniffing when resources are mislabeled.",
            recommended_fix="Send X-Content-Type-Options: nosniff on HTML and asset responses.",
            acceptance_criteria="All sampled first-party responses include nosniff where compatible.",
        ))
    if not referrer:
        findings.append(_make_finding(
            finding_id="missing-referrer-policy",
            title="Referrer policy is not explicit",
            severity="low",
            confidence="Confirmed",
            bucket="session_privacy",
            category="privacy",
            scope=url,
            evidence=["Referrer-Policy header is absent."],
            diagnostic="Outbound navigations may leak more URL context than intended.",
            recommended_fix="Set a deliberate Referrer-Policy such as strict-origin-when-cross-origin.",
            acceptance_criteria="A reviewed referrer policy is present on HTML responses.",
        ))
    if not permissions:
        findings.append(_make_finding(
            finding_id="missing-permissions-policy",
            title="Permissions Policy is missing",
            severity="low",
            confidence="Confirmed",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=["Permissions-Policy header is absent."],
            diagnostic="Browser capabilities are not explicitly constrained for this origin.",
            recommended_fix="Declare a minimal Permissions-Policy for camera, microphone, geolocation, payment, and similar APIs.",
            acceptance_criteria="A minimal permissions policy is shipped and reviewed against product needs.",
        ))
    if not coop:
        findings.append(_make_finding(
            finding_id="missing-coop",
            title="Origin isolation header COOP is missing",
            severity="low",
            confidence="Confirmed",
            bucket="browser_hardening",
            category="browser_security",
            scope=url,
            evidence=["Cross-Origin-Opener-Policy header is absent."],
            diagnostic="The site has no explicit opener isolation boundary.",
            recommended_fix="Evaluate Cross-Origin-Opener-Policy: same-origin for app surfaces where compatible.",
            acceptance_criteria="COOP is either intentionally configured or documented as incompatible.",
        ))
    if server or powered:
        evidence = []
        if server:
            evidence.append(f"Server: {server}")
        if powered:
            evidence.append(f"X-Powered-By: {powered}")
        findings.append(_make_finding(
            finding_id="technology-fingerprint-leak",
            title="Technology fingerprinting headers are exposed",
            severity="low",
            confidence="Confirmed",
            bucket="app_exposure",
            category="information_disclosure",
            scope=url,
            evidence=evidence,
            diagnostic="Infrastructure or framework details are visible to every client.",
            recommended_fix="Remove or minimize framework/server disclosure headers at the edge or app layer.",
            acceptance_criteria="Sampled responses no longer expose unnecessary technology fingerprints.",
        ))
    if acao == "*" and acac.lower() == "true":
        findings.append(_make_finding(
            finding_id="cors-wildcard-with-credentials",
            title="CORS allows wildcard origin with credentials",
            severity="critical",
            confidence="Confirmed",
            bucket="app_exposure",
            category="cors",
            scope=url,
            evidence=["Access-Control-Allow-Origin: *", "Access-Control-Allow-Credentials: true"],
            diagnostic="Credentialed cross-origin reads may be dangerously over-permissive.",
            recommended_fix="Replace wildcard CORS with an allowlist and never combine wildcard origins with credentials.",
            acceptance_criteria="Credentialed CORS responses only allow trusted origins.",
            root_cause=True,
        ))
    return findings


def _tls_findings(entry_url: str, tls: Dict[str, Any]) -> List[Dict[str, Any]]:
    if entry_url.startswith("http://"):
        return [_make_finding(
            finding_id="http-entrypoint",
            title="Audit target uses HTTP as the entrypoint",
            severity="high",
            confidence="Confirmed",
            bucket="transport_tls",
            category="transport",
            scope=entry_url,
            evidence=["The normalized target URL starts with http://."],
            diagnostic="Traffic can be observed or modified before any redirect policy is considered.",
            recommended_fix="Use HTTPS as the canonical entrypoint and redirect HTTP to HTTPS at the edge.",
            acceptance_criteria="Canonical links, internal links, and public entrypoints use HTTPS directly.",
            root_cause=True,
        )]
    findings: List[Dict[str, Any]] = []
    if not tls.get("available"):
        findings.append(_make_finding(
            finding_id="tls-handshake-unavailable",
            title="TLS handshake could not be verified",
            severity="medium",
            confidence="Estimated",
            bucket="transport_tls",
            category="transport",
            scope=entry_url,
            evidence=[tls.get("error") or "TLS probe failed."],
            diagnostic="CyberAtlas could not independently validate the certificate and negotiated TLS version.",
            recommended_fix="Verify certificate chain, SNI, and edge TLS configuration from a trusted external environment.",
            acceptance_criteria="A follow-up audit can validate certificate metadata and TLS protocol.",
        ))
        return findings
    days = tls.get("days_remaining")
    if isinstance(days, int) and days < 0:
        severity = "critical"
        title = "TLS certificate is expired"
    elif isinstance(days, int) and days < 14:
        severity = "high"
        title = "TLS certificate is close to expiry"
    elif isinstance(days, int) and days < 30:
        severity = "medium"
        title = "TLS certificate expiry window is short"
    else:
        return findings
    findings.append(_make_finding(
        finding_id="tls-certificate-expiry-risk",
        title=title,
        severity=severity,
        confidence="Confirmed",
        bucket="transport_tls",
        category="transport",
        scope=entry_url,
        evidence=[f"Certificate days remaining: {days}", f"Not after: {tls.get('not_after') or 'unknown'}"],
        diagnostic="The production TLS certificate lifecycle needs attention.",
        recommended_fix="Renew or rotate the certificate and verify automated renewal health.",
        acceptance_criteria="Certificate has a healthy renewal window and monitoring for future expiry.",
        root_cause=severity in {"critical", "high"},
    ))
    return findings


def _cookie_findings(url: str, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    seen = set()
    for page in pages:
        set_cookie = str((page.get("headers") or {}).get("set-cookie") or "")
        if not set_cookie:
            continue
        for cookie in re.split(r", (?=[^;,=]+=[^;,]+)", set_cookie):
            name = cookie.split("=", 1)[0].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            lower = cookie.lower()
            missing = []
            if "secure" not in lower:
                missing.append("Secure")
            if "httponly" not in lower:
                missing.append("HttpOnly")
            if "samesite" not in lower:
                missing.append("SameSite")
            if not missing:
                continue
            findings.append(_make_finding(
                finding_id=f"cookie-flags-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}",
                title=f"Cookie {name} is missing security attributes",
                severity="medium" if "HttpOnly" in missing or "Secure" in missing else "low",
                confidence="Confirmed",
                bucket="session_privacy",
                category="session",
                scope=page.get("final_url") or url,
                evidence=[f"Missing: {', '.join(missing)}"],
                diagnostic="Session or state cookies should declare explicit browser handling constraints.",
                recommended_fix="Set Secure, HttpOnly where JavaScript access is not needed, and an explicit SameSite policy.",
                acceptance_criteria="All sensitive cookies include the expected attributes in production responses.",
            ))
    return findings


def _page_findings(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for page in pages:
        url = page.get("final_url") or page.get("url") or ""
        if page.get("body_error_indicators"):
            findings.append(_make_finding(
                finding_id=f"error-disclosure-{len(findings)}",
                title="Application error details are visible in the response body",
                severity="high",
                confidence="Strong signal",
                bucket="app_exposure",
                category="information_disclosure",
                scope=url,
                evidence=[", ".join(page.get("body_error_indicators") or [])],
                diagnostic="The sampled response contains stack, framework, database, or exception indicators.",
                recommended_fix="Disable debug output in production and return generic error pages with server-side correlation IDs.",
                acceptance_criteria="Public responses no longer reveal stack traces, framework exceptions, or database errors.",
                root_cause=True,
            ))
        if page.get("mixed_content_count", 0) > 0:
            findings.append(_make_finding(
                finding_id=f"mixed-content-{len(findings)}",
                title="HTTPS page references insecure HTTP resources",
                severity="medium",
                confidence="Confirmed",
                bucket="transport_tls",
                category="transport",
                scope=url,
                evidence=[f"{page.get('mixed_content_count')} HTTP asset(s) referenced from an HTTPS page."],
                diagnostic="Mixed content can weaken transport guarantees and break modern browser protections.",
                recommended_fix="Serve all first-party and third-party resources over HTTPS and update hardcoded asset URLs.",
                acceptance_criteria="No sampled HTTPS page references HTTP subresources.",
            ))
        for form in page.get("forms") or []:
            if not form.get("has_password"):
                continue
            action = str(form.get("action") or url)
            field_names = " ".join(str(name).lower() for name in (form.get("field_names") or []))
            if action.startswith("http://"):
                findings.append(_make_finding(
                    finding_id=f"insecure-password-form-{len(findings)}",
                    title="Password form posts to an insecure HTTP action",
                    severity="critical",
                    confidence="Confirmed",
                    bucket="session_privacy",
                    category="session",
                    scope=url,
                    evidence=[f"Form action: {action}"],
                    diagnostic="Credentials can be exposed if a password form submits over HTTP.",
                    recommended_fix="Force the form action to HTTPS and verify all redirects preserve HTTPS before credentials are sent.",
                    acceptance_criteria="Password forms submit directly to HTTPS endpoints.",
                    root_cause=True,
                ))
            if not any(token in field_names for token in ("csrf", "_token", "authenticity", "xsrf")):
                findings.append(_make_finding(
                    finding_id=f"csrf-token-not-observed-{len(findings)}",
                    title="Password form does not expose an obvious CSRF token field",
                    severity="medium",
                    confidence="Estimated",
                    bucket="session_privacy",
                    category="session",
                    scope=url,
                    evidence=[f"Observed form fields: {', '.join(form.get('field_names') or []) or 'none'}"],
                    diagnostic="CyberAtlas could not confirm an anti-CSRF field in a sensitive form.",
                    recommended_fix="Verify CSRF protection server-side and include a clear token mechanism for state-changing authenticated forms.",
                    acceptance_criteria="Sensitive forms use verified CSRF protection and tests cover missing/invalid token rejection.",
                ))
    return findings


def _probe_findings(base_url: str, probes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    seen_security_txt = any(item.get("exists") and str(item.get("path") or "").endswith("security.txt") for item in probes)
    for probe in probes:
        path = str(probe.get("path") or "")
        if not probe.get("exists"):
            continue
        if path in SENSITIVE_PATHS:
            body = str(probe.get("body_sample") or "").lower()
            if path == "/.env" and not any(key in body for key in ("=", "secret", "key", "token", "password")):
                continue
            findings.append(_make_finding(
                finding_id=SENSITIVE_PATHS[path],
                title=f"Sensitive path appears publicly reachable: {path}",
                severity="critical" if path in {"/.env", "/.git/HEAD"} else "high",
                confidence="Confirmed",
                bucket="app_exposure",
                category="exposure",
                scope=probe.get("final_url") or probe.get("url") or base_url,
                evidence=[
                    f"HTTP status: {probe.get('status_code')}",
                    f"Content-Type: {probe.get('content_type') or 'unknown'}",
                    f"Sample: {str(probe.get('body_sample') or '')[:180]}",
                ],
                diagnostic="A path commonly associated with sensitive runtime or server information is publicly accessible.",
                recommended_fix="Block this path at the edge/app layer, remove the artifact from the deployment, and rotate any secrets if exposure is confirmed.",
                acceptance_criteria=f"{path} returns 404/403 without sensitive content from the public internet.",
                root_cause=True,
            ))
        if path in set(SWAGGER_PATHS):
            findings.append(_make_finding(
                finding_id=f"public-api-docs-{path.strip('/').replace('/', '-') or 'root'}",
                title="Public API documentation surface is exposed",
                severity="medium",
                confidence="Strong signal",
                bucket="api_surface",
                category="api_surface",
                scope=probe.get("final_url") or probe.get("url") or base_url,
                evidence=[f"Path {path} returned HTTP {probe.get('status_code')}"],
                diagnostic="OpenAPI/Swagger surfaces are useful for developers but also make API enumeration easier.",
                recommended_fix="Keep public API docs only when intentional; otherwise require authentication, restrict by environment, or publish a sanitized spec.",
                acceptance_criteria="API docs exposure is documented and access-controlled or intentionally public.",
            ))
    if not seen_security_txt:
        findings.append(_make_finding(
            finding_id="security-txt-missing",
            title="security.txt was not found",
            severity="low",
            confidence="Confirmed",
            bucket="operational_resilience",
            category="security_operations",
            scope=base_url,
            evidence=["/.well-known/security.txt and /security.txt were not found in the safe probe set."],
            diagnostic="Security researchers and users have no standard contact path for responsible disclosure.",
            recommended_fix="Publish a reviewed /.well-known/security.txt with contact, policy, and expiration metadata.",
            acceptance_criteria="security.txt is reachable and kept current.",
        ))
    return findings


def _openapi_findings(openapi: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not openapi.get("available"):
        return []
    findings: List[Dict[str, Any]] = []
    endpoint_count = int(openapi.get("endpoint_count") or 0)
    unauthenticated = int(openapi.get("unauthenticated_count") or 0)
    if endpoint_count >= 20:
        findings.append(_make_finding(
            finding_id="large-public-api-surface",
            title="Large public API surface discovered from OpenAPI",
            severity="medium",
            confidence="Strong signal",
            bucket="api_surface",
            category="api_surface",
            scope=openapi.get("source_url") or "openapi",
            evidence=[f"{endpoint_count} endpoint(s) parsed from the public spec."],
            diagnostic="A large public endpoint map increases review and abuse-resistance requirements.",
            recommended_fix="Review all public operations, hide internal endpoints from public specs, and keep the spec aligned with auth policy.",
            acceptance_criteria="The public spec exposes only intentional endpoints and auth expectations are reviewed.",
        ))
    if unauthenticated:
        findings.append(_make_finding(
            finding_id="openapi-operations-without-security",
            title="OpenAPI operations without declared security were found",
            severity="medium" if unauthenticated < 10 else "high",
            confidence="Estimated",
            bucket="api_surface",
            category="api_surface",
            scope=openapi.get("source_url") or "openapi",
            evidence=[f"{unauthenticated} operation(s) have no security declaration in the parsed spec."],
            diagnostic="The OpenAPI contract does not clearly declare authentication expectations for every operation.",
            recommended_fix="Add explicit security requirements or document intentionally public operations in the OpenAPI spec.",
            acceptance_criteria="Every state-changing or sensitive operation has an explicit security declaration.",
        ))
    if int(openapi.get("state_changing_without_security_count") or 0) > 0:
        findings.append(_make_finding(
            finding_id="openapi-state-changing-without-security",
            title="State-changing OpenAPI operations lack declared security",
            severity="high",
            confidence="Strong signal",
            bucket="api_surface",
            category="api_contract",
            scope=openapi.get("source_url") or "openapi",
            evidence=[f"{openapi.get('state_changing_without_security_count')} POST/PUT/PATCH/DELETE operation(s) have no declared security."],
            diagnostic="Operations that can mutate state need explicit authentication and authorization expectations in the contract.",
            recommended_fix="Declare security requirements on every state-changing operation, or document why a route is intentionally public.",
            acceptance_criteria="OpenAPI validation shows zero state-changing operations without an explicit security declaration.",
        ))
    if int(openapi.get("sensitive_parameter_count") or 0) > 0 and unauthenticated > 0:
        findings.append(_make_finding(
            finding_id="openapi-sensitive-parameters-with-unauthenticated-ops",
            title="OpenAPI exposes sensitive parameter names on unauthenticated operations",
            severity="medium",
            confidence="Estimated",
            bucket="api_surface",
            category="api_contract",
            scope=openapi.get("source_url") or "openapi",
            evidence=[f"{openapi.get('sensitive_parameter_count')} sensitive-looking parameter name(s) were observed."],
            diagnostic="The API contract appears to expose identity, token, account, or password-related fields on operations without declared security.",
            recommended_fix="Review the affected operations, add security declarations, and avoid exposing unnecessary sensitive field names in public docs.",
            acceptance_criteria="Sensitive operations have security declarations and public schemas reveal only necessary fields.",
        ))
    return findings


def _frontend_findings(frontend_hints: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    source_maps = frontend_hints.get("source_maps") or []
    if source_maps:
        reachable_count = int(frontend_hints.get("reachable_source_map_count") or 0)
        findings.append(_make_finding(
            finding_id="frontend-source-maps-public",
            title="Frontend source maps appear publicly discoverable",
            severity="high" if reachable_count else "medium",
            confidence="Confirmed" if reachable_count else "Strong signal",
            bucket="app_exposure",
            category="information_disclosure",
            scope=source_maps[0],
            evidence=[
                f"{len(source_maps)} source map reference(s) detected.",
                f"{reachable_count} source map URL(s) responded below HTTP 400 during safe verification.",
            ] + [str(item) for item in source_maps[:4]],
            diagnostic="Public source maps can expose original source structure, internal comments, endpoint names, and implementation details.",
            recommended_fix="Disable public production source maps or restrict access to authenticated internal debugging environments.",
            acceptance_criteria="Production JS bundles no longer expose reachable sourceMappingURL references.",
        ))
    if int(frontend_hints.get("third_party_script_without_sri_count") or 0) > 0:
        findings.append(_make_finding(
            finding_id="third-party-scripts-without-sri",
            title="Third-party scripts are loaded without Subresource Integrity",
            severity="medium",
            confidence="Strong signal",
            bucket="browser_hardening",
            category="supply_chain",
            scope="frontend script tags",
            evidence=[
                f"{frontend_hints.get('third_party_script_without_sri_count')} third-party script tag(s) lack integrity attributes.",
                f"{frontend_hints.get('third_party_script_count')} third-party script tag(s) observed in sampled pages.",
            ],
            diagnostic="Compromised third-party scripts can execute in the page without browser-level integrity checks.",
            recommended_fix="Add integrity/crossorigin attributes for static third-party scripts, self-host trusted assets where appropriate, and keep CSP script-src tight.",
            acceptance_criteria="Sampled third-party scripts either use SRI or are explicitly documented as dynamic/non-SRI-compatible with compensating CSP controls.",
        ))
    private_hosts = frontend_hints.get("private_backend_hosts") or []
    if private_hosts:
        findings.append(_make_finding(
            finding_id="frontend-private-backend-reference",
            title="Frontend code references private or local backend hosts",
            severity="high",
            confidence="Strong signal",
            bucket="app_exposure",
            category="information_disclosure",
            scope=", ".join(private_hosts[:3]),
            evidence=[f"Private host hint: {host}" for host in private_hosts[:6]],
            diagnostic="Client-side code should not reference localhost, private IPs, or internal hostnames in production.",
            recommended_fix="Move environment-specific backend URLs to server-side configuration and verify production bundles are rebuilt cleanly.",
            acceptance_criteria="Production frontend bundles contain only public intended API origins.",
            root_cause=True,
        ))
    secret_names = frontend_hints.get("secret_name_hints") or []
    if secret_names:
        findings.append(_make_finding(
            finding_id="frontend-secret-like-identifiers",
            title="Frontend bundle contains secret-like identifier names",
            severity="low",
            confidence="Estimated",
            bucket="app_exposure",
            category="information_disclosure",
            scope="frontend bundles",
            evidence=[f"Identifier hint: {name}" for name in secret_names[:8]],
            diagnostic="This does not prove a secret value leaked, but secret-like identifiers in client bundles deserve review.",
            recommended_fix="Verify no real secrets are bundled client-side and move sensitive configuration to server-only environment variables.",
            acceptance_criteria="Client bundles contain no real secret values and secret-like names are intentional public config only.",
        ))
    return findings


def _api_inventory_findings(api_inventory: Dict[str, Any], protections: Dict[str, Any], pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    endpoints = api_inventory.get("endpoints") or []
    public_sensitive = [item for item in endpoints if item.get("sensitive") and not item.get("requires_auth")]
    if public_sensitive:
        findings.append(_make_finding(
            finding_id="public-sensitive-api-endpoints",
            title="Sensitive-looking API endpoints are publicly reachable",
            severity="high",
            confidence="Strong signal",
            bucket="api_surface",
            category="api_exposure",
            scope=", ".join(str(item.get("path") or "") for item in public_sensitive[:4]),
            evidence=[f"{item.get('path')} returned HTTP {item.get('status_code')}" for item in public_sensitive[:8]],
            diagnostic="Endpoints with admin, user, config, token, upload, or export semantics need explicit access review.",
            recommended_fix="Confirm these endpoints are intentionally public; otherwise require authentication and authorization before response generation.",
            acceptance_criteria="Sensitive API endpoints return 401/403 when unauthenticated, or are documented as intentionally public.",
            root_cause=True,
        ))
    graphql_public = [item for item in endpoints if "graphql" in str(item.get("path") or "").lower() and not item.get("requires_auth")]
    if graphql_public:
        findings.append(_make_finding(
            finding_id="public-graphql-surface",
            title="GraphQL surface is publicly reachable",
            severity="medium",
            confidence="Strong signal",
            bucket="api_surface",
            category="api_exposure",
            scope=", ".join(str(item.get("path") or "") for item in graphql_public[:4]),
            evidence=[f"{item.get('path')} returned HTTP {item.get('status_code')}" for item in graphql_public[:6]],
            diagnostic="Public GraphQL endpoints can make schema and authorization mistakes easier to enumerate if introspection, playgrounds, or weak auth are enabled.",
            recommended_fix="Disable public playgrounds/introspection unless explicitly required, enforce resolver-level authorization, depth limits, and rate limits.",
            acceptance_criteria="GraphQL endpoints expose only intended public operations and reject unauthorized sensitive queries.",
        ))
    trace_enabled = [
        item for item in endpoints
        if "TRACE" in {str(method).upper() for method in (item.get("allowed_methods") or [])}
    ]
    if trace_enabled:
        findings.append(_make_finding(
            finding_id="http-trace-method-enabled",
            title="HTTP TRACE appears enabled on a public endpoint",
            severity="high",
            confidence="Strong signal",
            bucket="app_exposure",
            category="http_methods",
            scope=", ".join(str(item.get("path") or "") for item in trace_enabled[:4]),
            evidence=[f"{item.get('path')} allowed methods: {', '.join(item.get('allowed_methods') or [])}" for item in trace_enabled[:6]],
            diagnostic="TRACE is rarely needed on public applications and can increase cross-site tracing and debugging exposure risk.",
            recommended_fix="Disable TRACE at the edge, reverse proxy, or application server.",
            acceptance_criteria="OPTIONS responses and direct verification show TRACE is not allowed publicly.",
        ))
    auth_surface = int(api_inventory.get("auth_related_count") or 0) + len([
        form for page in pages for form in (page.get("forms") or []) if form.get("has_password")
    ])
    if auth_surface and not protections.get("rate_limit_detected"):
        findings.append(_make_finding(
            finding_id="auth-surface-without-rate-limit-signal",
            title="Authentication surface has no visible rate-limit signal",
            severity="medium",
            confidence="Estimated",
            bucket="operational_resilience",
            category="abuse_resistance",
            scope="authentication routes/forms",
            evidence=[f"{auth_surface} auth-related route/form signal(s) found.", "No rate-limit or Retry-After header was observed in sampled responses."],
            diagnostic="This does not prove rate limiting is absent, but public auth surfaces should expose or enforce clear throttling.",
            recommended_fix="Apply account/IP/device-aware throttling, lockout/backoff, bot defenses, and response monitoring on login and token routes.",
            acceptance_criteria="Abuse tests in a controlled environment confirm throttling and monitoring on authentication endpoints.",
        ))
    return findings


def _recon_findings(recon: Dict[str, Any], protections: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if recon.get("realtime_public") and not protections.get("rate_limit_detected"):
        findings.append(_make_finding(
            finding_id="public-realtime-surface-without-rate-limit-signal",
            title="Realtime endpoint surface is public without a visible rate-limit signal",
            severity="medium",
            confidence="Estimated",
            bucket="operational_resilience",
            category="abuse_resistance",
            scope="realtime endpoints",
            evidence=["Socket/WebSocket-like paths were reachable and no rate-limit header was observed."],
            diagnostic="Realtime transports need connection throttling, authentication rules, and abuse monitoring.",
            recommended_fix="Add connection quotas, namespace authorization, heartbeat limits, and monitoring for realtime endpoints.",
            acceptance_criteria="Controlled abuse tests confirm connection throttling and namespace authorization.",
        ))
    if not protections.get("waf_detected") and not protections.get("rate_limit_detected") and int(recon.get("auth_surface_count") or 0) > 0:
        findings.append(_make_finding(
            finding_id="no-visible-edge-abuse-protection",
            title="No visible WAF or rate-limit protection on auth-facing surface",
            severity="low",
            confidence="Estimated",
            bucket="operational_resilience",
            category="edge_protection",
            scope="edge responses",
            evidence=["No WAF/CDN challenge or rate-limit headers were observed in sampled evidence."],
            diagnostic="CyberAtlas cannot prove protections are absent, but the sampled public evidence does not show an edge abuse-control layer.",
            recommended_fix="Verify WAF, bot filtering, and rate limits are configured for auth and write-heavy endpoints.",
            acceptance_criteria="Owner-side checks or safe follow-up tests confirm active abuse protections on sensitive routes.",
        ))
    return findings


def _build_remediation_items(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "finding_id": item.get("id"),
            "scope": item.get("scope"),
            "category": item.get("category"),
            "severity": item.get("severity"),
            "confidence": item.get("confidence"),
            "diagnostic": item.get("diagnostic"),
            "probable_cause": item.get("probable_cause"),
            "recommended_fix": item.get("recommended_fix"),
            "acceptance_criteria": item.get("acceptance_criteria"),
            "dev_prompt": item.get("dev_prompt"),
        }
        for item in findings
    ]


def _risk_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(str(item.get("severity") or "info").lower() for item in findings)
    return {key: int(counts.get(key, 0)) for key in ("critical", "high", "medium", "low", "info")}


def _security_grade(global_score: Any, counts: Dict[str, int]) -> str:
    try:
        score = float(global_score)
    except (TypeError, ValueError):
        score = 0.0
    if counts.get("critical", 0) > 0 or score < 45:
        return "F"
    if counts.get("high", 0) >= 3 or score < 60:
        return "D"
    if counts.get("high", 0) > 0 or counts.get("medium", 0) >= 5 or score < 75:
        return "C"
    if counts.get("medium", 0) > 0 or score < 90:
        return "B"
    return "A"


def _priority_rank(priority: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(str(priority or "").lower(), 0)


def _surface_status(ok: bool, weak: bool = False) -> str:
    if weak:
        return "review"
    return "ok" if ok else "weak"


def _build_surface_matrix(
    *,
    tls: Dict[str, Any],
    entry_headers: Dict[str, str],
    missing_headers: List[str],
    probes: List[Dict[str, Any]],
    openapi: Dict[str, Any],
    api_inventory: Dict[str, Any],
    frontend_hints: Dict[str, Any],
    protections: Dict[str, Any],
    recon_summary: Dict[str, Any],
    pages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    sensitive_exposures = [
        item for item in probes
        if item.get("exists") and str(item.get("path") or "") in SENSITIVE_PATHS
    ]
    cookie_header_count = len([
        page for page in pages
        if (page.get("headers") or {}).get("set-cookie")
    ])
    auth_surface_count = int(recon_summary.get("auth_surface_count") or 0)
    public_sensitive = int(api_inventory.get("public_sensitive_count") or 0)
    source_maps = int(frontend_hints.get("source_map_count") or 0)
    reachable_source_maps = int(frontend_hints.get("reachable_source_map_count") or 0)
    third_party_without_sri = int(frontend_hints.get("third_party_script_without_sri_count") or 0)
    return [
        {
            "id": "transport_tls",
            "label": "Transport & TLS",
            "status": _surface_status(bool(tls.get("available")) and not missing_headers.count("strict-transport-security")),
            "signals": [
                f"TLS available: {bool(tls.get('available'))}",
                f"Protocol: {tls.get('protocol') or 'unknown'}",
                f"HSTS present: {bool(entry_headers.get('strict-transport-security'))}",
            ],
            "next_action": "Validate HTTPS canonicalization, HSTS scope, and certificate automation.",
        },
        {
            "id": "browser_hardening",
            "label": "Browser hardening",
            "status": _surface_status(len(missing_headers) == 0, bool(missing_headers)),
            "signals": [
                f"{len(missing_headers)} security header(s) missing.",
                f"CSP present: {bool(entry_headers.get('content-security-policy'))}",
                f"Third-party scripts without SRI: {third_party_without_sri}",
            ],
            "next_action": "Ship CSP, framing, MIME, referrer, permissions and origin-isolation controls deliberately.",
        },
        {
            "id": "session_auth",
            "label": "Session & authentication",
            "status": _surface_status(auth_surface_count == 0 or bool(protections.get("rate_limit_detected")), auth_surface_count > 0),
            "signals": [
                f"Auth surface signals: {auth_surface_count}",
                f"Auth-protected endpoint signals: {api_inventory.get('auth_protected_count', 0)}",
                f"Pages setting cookies: {cookie_header_count}",
                f"Rate-limit visible: {bool(protections.get('rate_limit_detected'))}",
            ],
            "next_action": "Verify auth middleware, cookie flags, CSRF protection, and account/IP/device throttling.",
        },
        {
            "id": "api_contract",
            "label": "API contract",
            "status": _surface_status(public_sensitive == 0 and int(openapi.get("state_changing_without_security_count") or 0) == 0, int(api_inventory.get("endpoint_count") or 0) > 0),
            "signals": [
                f"OpenAPI endpoints: {openapi.get('endpoint_count', 0)}",
                f"Discovered endpoint signals: {api_inventory.get('endpoint_count', 0)}",
                f"Sensitive-looking public endpoints: {public_sensitive}",
                f"State-changing operations without declared security: {openapi.get('state_changing_without_security_count', 0)}",
            ],
            "next_action": "Review every sensitive and state-changing route against auth, authorization, rate limits, and schema validation.",
        },
        {
            "id": "frontend_bundle",
            "label": "Frontend bundle hygiene",
            "status": _surface_status(source_maps == 0 and not frontend_hints.get("private_backend_hosts"), source_maps > 0 or third_party_without_sri > 0),
            "signals": [
                f"API references in frontend: {frontend_hints.get('api_reference_count', 0)}",
                f"Private backend references: {len(frontend_hints.get('private_backend_hosts') or [])}",
                f"Source map references: {source_maps}",
                f"Reachable source maps: {reachable_source_maps}",
            ],
            "next_action": "Remove private origins and production source maps from client bundles; verify no secrets ship client-side.",
        },
        {
            "id": "public_exposure",
            "label": "Public exposure hygiene",
            "status": _surface_status(len(sensitive_exposures) == 0, len(sensitive_exposures) > 0),
            "signals": [
                f"Reachable exposure probes: {len([item for item in probes if item.get('exists')])}",
                f"Sensitive exposure probes: {len(sensitive_exposures)}",
                f"security.txt reachable: {any(item.get('exists') and str(item.get('path') or '').endswith('security.txt') for item in probes)}",
            ],
            "next_action": "Block sensitive deployment artifacts and publish a maintained security.txt contact path.",
        },
        {
            "id": "edge_abuse",
            "label": "Edge & abuse resistance",
            "status": _surface_status(bool(protections.get("waf_detected")) or bool(protections.get("rate_limit_detected")), not protections.get("waf_detected") and auth_surface_count > 0),
            "signals": [
                f"CDN signals: {', '.join(protections.get('cdn') or []) or 'none'}",
                f"WAF signal: {bool(protections.get('waf_detected'))}",
                f"Rate-limit signal: {bool(protections.get('rate_limit_detected'))}",
                f"Realtime public: {bool(recon_summary.get('realtime_public'))}",
            ],
            "next_action": "Confirm WAF/bot filtering, auth throttles, realtime quotas, logging, and alerting from owner-side controls.",
        },
    ]


def _build_recommendations(
    *,
    findings: List[Dict[str, Any]],
    summary: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> List[Dict[str, Any]]:
    finding_ids = {str(item.get("id") or "") for item in findings}
    categories = {str(item.get("category") or "") for item in findings}
    buckets = {str(item.get("bucket") or "") for item in findings}
    recon = snapshot.get("recon_summary") or {}
    frontend = snapshot.get("frontend_hints") or {}
    openapi = snapshot.get("openapi") or {}
    recommendations = [
        {
            "id": "fix-critical-and-high-first",
            "priority": "critical" if int(summary.get("critical_count") or 0) else "high",
            "title": "Fix the highest-confidence security risks first",
            "description": "Start with confirmed critical/high findings before cosmetic hardening, because those are the most likely to reduce real exposure.",
            "triggered": int(summary.get("critical_count") or 0) > 0 or int(summary.get("high_count") or 0) > 0,
            "evidence": [f"{summary.get('critical_count', 0)} critical, {summary.get('high_count', 0)} high finding(s)."],
            "action": "Patch root-cause findings, redeploy, then rerun CyberAtlas to confirm the severity mix drops.",
            "validation": "No critical findings remain and high findings are either fixed or explicitly accepted with owner sign-off.",
        },
        {
            "id": "browser-security-header-baseline",
            "priority": "high",
            "title": "Ship a complete browser security header baseline",
            "description": "Missing or weak browser headers leave the app exposed to XSS blast radius, framing, sniffing, and origin-isolation gaps.",
            "triggered": "browser_hardening" in buckets,
            "evidence": [item.get("title", "") for item in findings if item.get("bucket") == "browser_hardening"][:6],
            "action": "Deploy CSP, HSTS, frame-ancestors/XFO, nosniff, referrer-policy, permissions-policy, and COOP where compatible.",
            "validation": "All sampled HTML responses include the expected headers and CSP violation telemetry is clean.",
        },
        {
            "id": "api-access-control-review",
            "priority": "high",
            "title": "Review API access control endpoint by endpoint",
            "description": "Sensitive-looking public routes, OpenAPI operations without security, and large endpoint surfaces need explicit auth/authorization review.",
            "triggered": int(summary.get("public_sensitive_endpoint_count") or 0) > 0 or int(openapi.get("unauthenticated_count") or 0) > 0,
            "evidence": [
                f"Public sensitive endpoint signals: {summary.get('public_sensitive_endpoint_count', 0)}",
                f"OpenAPI operations without declared security: {openapi.get('unauthenticated_count', 0)}",
            ],
            "action": "Map each sensitive/state-changing route to auth, authorization policy, input schema, rate limit, and audit logging.",
            "validation": "Unauthenticated requests to protected routes return 401/403 and OpenAPI security declarations match production behavior.",
        },
        {
            "id": "auth-abuse-protection",
            "priority": "medium",
            "title": "Verify throttling and abuse controls on authentication surfaces",
            "description": "Login, token, password, realtime, and upload surfaces should resist brute force, enumeration, and automated abuse.",
            "triggered": int(recon.get("auth_surface_count") or 0) > 0 and not bool(summary.get("rate_limit_detected")),
            "evidence": [
                f"Auth surface signals: {recon.get('auth_surface_count', 0)}",
                f"Rate-limit detected: {summary.get('rate_limit_detected')}",
            ],
            "action": "Add account/IP/device throttles, backoff, lockout signals, bot filtering, and monitoring for suspicious auth bursts.",
            "validation": "Controlled owner-side tests show throttling/alerts without degrading normal login flows.",
        },
        {
            "id": "frontend-bundle-exposure-cleanup",
            "priority": "medium",
            "title": "Clean frontend bundle exposure",
            "description": "Frontend bundles can accidentally reveal private origins, source maps, endpoint maps, or secret-like implementation details.",
            "triggered": int(frontend.get("source_map_count") or 0) > 0 or bool(frontend.get("private_backend_hosts")) or int(frontend.get("third_party_script_without_sri_count") or 0) > 0,
            "evidence": [
                f"Source maps: {frontend.get('source_map_count', 0)}",
                f"Private backends: {len(frontend.get('private_backend_hosts') or [])}",
                f"Third-party scripts without SRI: {frontend.get('third_party_script_without_sri_count', 0)}",
            ],
            "action": "Disable production source maps, remove private origins from public bundles, verify no real secrets ship client-side, and add SRI/CSP controls.",
            "validation": "A fresh production build contains no private hosts, no reachable source maps, and reviewed third-party script integrity controls.",
        },
        {
            "id": "public-artifact-exposure-cleanup",
            "priority": "critical" if any(item in finding_ids for item in {"environment_file_exposed", "public_git_metadata"}) else "high",
            "title": "Remove public deployment artifacts and sensitive files",
            "description": "Public .env, .git, config, debug, server-status, and phpinfo-style surfaces can leak secrets or implementation details.",
            "triggered": any(item in finding_ids for item in SENSITIVE_PATHS.values()),
            "evidence": [item.get("title", "") for item in findings if item.get("category") == "exposure"][:6],
            "action": "Block sensitive paths at the edge/app layer, remove artifacts from deployments, and rotate credentials if exposure is confirmed.",
            "validation": "Sensitive paths return 404/403 without content and secret rotation is completed where needed.",
        },
        {
            "id": "graphql-realtime-hardening",
            "priority": "medium",
            "title": "Harden GraphQL and realtime surfaces",
            "description": "Public GraphQL and websocket-like paths need resolver/namespace authorization, quotas, and introspection/playground policy.",
            "triggered": bool(recon.get("graphql_public")) or bool(recon.get("realtime_public")),
            "evidence": [
                f"GraphQL public: {bool(recon.get('graphql_public'))}",
                f"Realtime public: {bool(recon.get('realtime_public'))}",
            ],
            "action": "Disable public playgrounds unless intentional, enforce resolver/namespace auth, depth limits, connection quotas, and structured monitoring.",
            "validation": "Unauthorized sensitive GraphQL/realtime operations are rejected and quotas are confirmed in owner-side tests.",
        },
        {
            "id": "session-cookie-hardening",
            "priority": "medium",
            "title": "Harden cookies and CSRF handling",
            "description": "Session cookies and sensitive forms should have Secure, HttpOnly, SameSite, and verified CSRF behavior where relevant.",
            "triggered": "session" in categories or "session_privacy" in buckets,
            "evidence": [item.get("title", "") for item in findings if item.get("bucket") == "session_privacy"][:6],
            "action": "Set explicit cookie attributes, review SameSite behavior for auth flows, and test invalid/missing CSRF tokens.",
            "validation": "Sampled cookies carry expected attributes and sensitive form/API CSRF checks fail closed.",
        },
        {
            "id": "security-operations-loop",
            "priority": "low",
            "title": "Close the security operations loop",
            "description": "A strong posture needs a contact path, repeatable evidence exports, CI gates, and owner-side validation for checks that public probes cannot prove.",
            "triggered": True,
            "evidence": ["CyberAtlas public mode intentionally avoids exploit, brute-force, and stress behavior."],
            "action": "Publish security.txt, export the security gate payload into CI, and schedule owner-verified follow-up checks after major releases.",
            "validation": "Security contact, CI gate, and rerun cadence are documented and owned.",
        },
    ]
    recommendations.sort(key=lambda item: (_priority_rank(item.get("priority", "")), bool(item.get("triggered"))), reverse=True)
    return recommendations


def _build_action_plan(recommendations: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    triggered = [item for item in recommendations if item.get("triggered")]
    fallback = [item for item in recommendations if not item.get("triggered")]
    items = (triggered + fallback)[:limit]
    return [
        {
            **item,
            "order": index + 1,
        }
        for index, item in enumerate(items)
    ]


def run_site_audit(
    target_url: str,
    *,
    mode: str = "public",
    max_pages: int = 8,
    max_endpoints: int = 32,
    active_checks: bool = False,
    progress_callback: ProgressCallback = None,
    cancel_check: CancelCheck = None,
) -> Dict[str, Any]:
    normalized = normalize_public_target(target_url, mode)
    entry_url = normalized["normalized_url"]
    host = normalized["host"].split(":", 1)[0]
    started_at = _utc_now()
    profile = _profile_settings(max_pages, max_endpoints)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    _emit(progress_callback, "tls", 8, "Validating TLS and canonical entrypoint")
    tls = _collect_tls(host) if entry_url.startswith("https://") else {"available": False, "error": "HTTP entrypoint"}

    _emit(progress_callback, "crawl", 18, "Sampling public pages and forms")
    queue: List[Tuple[str, int]] = [(entry_url, 0)]
    visited: set[str] = set()
    pages: List[Dict[str, Any]] = []
    all_forms: List[Dict[str, Any]] = []
    while queue and len(pages) < profile["page_budget"]:
        if _cancelled(cancel_check):
            break
        current_url, depth = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)
        try:
            _emit(progress_callback, "crawl", 18 + (len(pages) * 28 / max(1, profile["page_budget"])), f"Sampling {current_url}")
            page, links, _body = _fetch_page(session, current_url, depth, host)
            if page:
                pages.append(page)
                all_forms.extend(page.get("forms") or [])
            if depth < 2:
                for link in links:
                    if link not in visited and len(queue) < profile["page_budget"] * 5:
                        queue.append((link, depth + 1))
        except Exception:
            continue

    if not pages:
        raise RuntimeError("CyberAtlas could not fetch a usable public response from the target.")

    _emit(progress_callback, "headers", 48, "Analyzing security headers and browser hardening")
    entry_headers = pages[0].get("headers") or {}

    _emit(progress_callback, "exposure", 62, "Running safe public exposure probes")
    probe_paths = list(SAFE_EXPOSURE_PATHS[: int(profile["probe_budget"])])
    swagger_budget = len(SWAGGER_PATHS) if active_checks else 8
    for path in SWAGGER_PATHS[:swagger_budget]:
        if path not in probe_paths:
            probe_paths.append(path)
    if not active_checks:
        probe_paths = [path for path in probe_paths if path not in {"/debug", "/server-status", "/admin", "/login"}]
    probes = [_fetch_probe(session, entry_url, path) for path in probe_paths]

    _emit(progress_callback, "api", 70, "Extracting frontend API and stack hints")
    frontend_hints = _collect_frontend_code_hints(
        session,
        pages,
        host,
        script_budget=8 if active_checks else 4,
    )

    _emit(progress_callback, "api", 74, "Parsing OpenAPI and API surface signals")
    openapi = _discover_openapi(probes, int(profile["endpoint_budget"]))
    api_inventory = _discover_endpoint_inventory(
        session,
        entry_url,
        frontend_hints,
        int(profile["endpoint_budget"]),
        active_checks=active_checks,
    )
    protections = _detect_protections(entry_headers, probes + api_inventory.get("endpoints", []), pages)
    recon_summary = _build_recon_summary(pages, probes, openapi, api_inventory, frontend_hints, protections)

    findings: List[Dict[str, Any]] = []
    findings.extend(_tls_findings(entry_url, tls))
    findings.extend(_header_findings(entry_url, entry_headers))
    findings.extend(_cookie_findings(entry_url, pages))
    findings.extend(_page_findings(pages))
    findings.extend(_probe_findings(entry_url, probes))
    findings.extend(_openapi_findings(openapi))
    findings.extend(_frontend_findings(frontend_hints))
    findings.extend(_api_inventory_findings(api_inventory, protections, pages))
    findings.extend(_recon_findings(recon_summary, protections))
    findings.sort(
        key=lambda item: (
            {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}.get(str(item.get("severity") or "").lower(), 0),
            {"Confirmed": 4, "Strong signal": 3, "Estimated": 2, "Unknown": 1}.get(str(item.get("confidence") or ""), 1),
        ),
        reverse=True,
    )

    _emit(progress_callback, "score", 86, "Scoring defensive security posture")
    scores = score_findings(
        findings,
        pages_analyzed=len(pages),
        page_budget=int(profile["page_budget"]),
        endpoint_count=max(int(openapi.get("endpoint_count") or 0), int(api_inventory.get("endpoint_count") or 0)),
    )
    counts = _risk_counts(findings)
    blocking_risk = scores.get("blocking_risk") or {}
    risk_level = blocking_risk.get("level") or "Low"
    exposed = [item for item in probes if item.get("exists")]
    missing_headers = [key for key in SECURITY_HEADER_KEYS if not entry_headers.get(key)]
    security_grade = _security_grade(scores.get("global_score"), counts)
    surface_matrix = _build_surface_matrix(
        tls=tls,
        entry_headers=entry_headers,
        missing_headers=missing_headers,
        probes=probes,
        openapi=openapi,
        api_inventory=api_inventory,
        frontend_hints=frontend_hints,
        protections=protections,
        recon_summary=recon_summary,
        pages=pages,
    )

    summary = {
        "target": entry_url,
        "mode": mode,
        "profile": profile["label"],
        "global_score": scores.get("global_score"),
        "security_grade": security_grade,
        "risk_level": risk_level,
        "top_risk": findings[0].get("title") if findings else "",
        "pages_crawled": len(pages),
        "pages_discovered": len(visited),
        "page_budget": profile["page_budget"],
        "endpoint_count": max(int(openapi.get("endpoint_count") or 0), int(api_inventory.get("endpoint_count") or 0)),
        "openapi_endpoint_count": int(openapi.get("endpoint_count") or 0),
        "discovered_endpoint_count": int(api_inventory.get("endpoint_count") or 0),
        "unauthenticated_endpoint_count": int(openapi.get("unauthenticated_count") or 0),
        "public_sensitive_endpoint_count": int(api_inventory.get("public_sensitive_count") or 0),
        "exposure_count": len(exposed),
        "source_map_count": int(frontend_hints.get("source_map_count") or 0),
        "reachable_source_map_count": int(frontend_hints.get("reachable_source_map_count") or 0),
        "frontend_api_reference_count": int(frontend_hints.get("api_reference_count") or 0),
        "third_party_script_without_sri_count": int(frontend_hints.get("third_party_script_without_sri_count") or 0),
        "waf_detected": bool(protections.get("waf_detected")),
        "rate_limit_detected": bool(protections.get("rate_limit_detected")),
        "security_headers_present": len([key for key in SECURITY_HEADER_KEYS if entry_headers.get(key)]),
        "security_headers_missing": len(missing_headers),
        "critical_count": counts["critical"],
        "high_count": counts["high"],
        "medium_count": counts["medium"],
        "low_count": counts["low"],
        "blocking_risk": blocking_risk,
        "safe_mode": not active_checks,
    }
    snapshot = {
        "started_at": started_at,
        "finished_at": _utc_now(),
        "entry_url": entry_url,
        "tls": tls,
        "security_headers": entry_headers,
        "missing_security_headers": missing_headers,
        "pages": pages,
        "forms": all_forms[:40],
        "exposure_probes": probes,
        "openapi": openapi,
        "api_inventory": api_inventory,
        "frontend_hints": frontend_hints,
        "protections": protections,
        "recon_summary": recon_summary,
        "surface_matrix": surface_matrix,
        "safe_scope": {
            "active_checks": bool(active_checks),
            "note": "CyberAtlas v1 performs defensive HTTP evidence collection and safe exposure probes only; it does not exploit or brute-force targets.",
        },
    }
    _emit(progress_callback, "score", 90, "Building remediation action plan")
    recommendations = _build_recommendations(findings=findings, summary=summary, snapshot=snapshot)
    action_plan = _build_action_plan(recommendations)
    return {
        "summary": summary,
        "snapshot": snapshot,
        "findings": findings,
        "scores": scores["categories"],
        "remediation_items": _build_remediation_items(findings),
        "recommendations": recommendations,
        "action_plan": action_plan,
        "owner_context": {},
    }
