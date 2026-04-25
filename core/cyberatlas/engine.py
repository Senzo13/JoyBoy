"""Defensive web and API security auditing for CyberAtlas."""

from __future__ import annotations

import json
import re
import socket
import ssl
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
                assets.append({"url": asset_url, "kind": kind})
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
        "mixed_content_count": len([
            item for item in assets
            if final_url.startswith("https://") and str(item.get("url") or "").startswith("http://")
        ]),
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
        if item.get("exists") and str(item.get("path") or "").lower() in {"/openapi.json", "/swagger.json", "/swagger/v1/swagger.json"}
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
            endpoints.append({
                "method": clean_method,
                "path": str(path),
                "summary": str(op.get("summary") or op.get("operationId") or "")[:160],
                "security_declared": bool(security),
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
        "endpoints": endpoints,
        "title": str((spec.get("info") or {}).get("title") or ""),
        "version": str((spec.get("info") or {}).get("version") or ""),
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
        if path in {"/openapi.json", "/swagger.json", "/api-docs", "/swagger/v1/swagger.json"}:
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
    if not active_checks:
        probe_paths = [path for path in probe_paths if path not in {"/debug", "/server-status", "/admin", "/login"}]
    probes = [_fetch_probe(session, entry_url, path) for path in probe_paths]

    _emit(progress_callback, "api", 74, "Parsing OpenAPI and API surface signals")
    openapi = _discover_openapi(probes, int(profile["endpoint_budget"]))

    findings: List[Dict[str, Any]] = []
    findings.extend(_tls_findings(entry_url, tls))
    findings.extend(_header_findings(entry_url, entry_headers))
    findings.extend(_cookie_findings(entry_url, pages))
    findings.extend(_page_findings(pages))
    findings.extend(_probe_findings(entry_url, probes))
    findings.extend(_openapi_findings(openapi))
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
        endpoint_count=int(openapi.get("endpoint_count") or 0),
    )
    counts = _risk_counts(findings)
    blocking_risk = scores.get("blocking_risk") or {}
    risk_level = blocking_risk.get("level") or "Low"
    exposed = [item for item in probes if item.get("exists")]
    missing_headers = [key for key in SECURITY_HEADER_KEYS if not entry_headers.get(key)]

    summary = {
        "target": entry_url,
        "mode": mode,
        "profile": profile["label"],
        "global_score": scores.get("global_score"),
        "risk_level": risk_level,
        "top_risk": findings[0].get("title") if findings else "",
        "pages_crawled": len(pages),
        "pages_discovered": len(visited),
        "page_budget": profile["page_budget"],
        "endpoint_count": int(openapi.get("endpoint_count") or 0),
        "unauthenticated_endpoint_count": int(openapi.get("unauthenticated_count") or 0),
        "exposure_count": len(exposed),
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
        "safe_scope": {
            "active_checks": bool(active_checks),
            "note": "CyberAtlas v1 performs defensive HTTP evidence collection and safe exposure probes only; it does not exploit or brute-force targets.",
        },
    }
    return {
        "summary": summary,
        "snapshot": snapshot,
        "findings": findings,
        "scores": scores["categories"],
        "remediation_items": _build_remediation_items(findings),
        "owner_context": {},
    }
