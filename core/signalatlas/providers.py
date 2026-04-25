"""Owner-mode provider status and enrichment for SignalAtlas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from core.infra.local_config import get_signalatlas_provider_settings


GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def _normalize_property_url(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if clean.startswith("sc-domain:"):
        return clean
    parsed = urlparse(clean if "://" in clean else f"https://{clean}")
    return parsed._replace(path=parsed.path or "/", params="", query="", fragment="").geturl()


def _target_host(target_url: str) -> str:
    try:
        parsed = urlparse(target_url if "://" in target_url else f"https://{target_url}")
        return parsed.netloc.lower()
    except Exception:
        return ""


def _host_matches_domain(host: str, domain: str) -> bool:
    clean_host = str(host or "").lower().strip(".")
    clean_domain = str(domain or "").lower().strip(".")
    if not clean_host or not clean_domain:
        return False
    return clean_host == clean_domain or clean_host.endswith(f".{clean_domain}")


def _gsc_provider_config() -> Dict[str, Any]:
    local = get_signalatlas_provider_settings("google_search_console")
    site_url = (
        os.environ.get("SIGNALATLAS_GSC_SITE_URL")
        or local.get("site_url")
        or ""
    )
    service_account_json = (
        os.environ.get("SIGNALATLAS_GSC_SERVICE_ACCOUNT_JSON")
        or local.get("service_account_json")
        or ""
    )
    service_account_file = (
        os.environ.get("SIGNALATLAS_GSC_SERVICE_ACCOUNT_FILE")
        or local.get("service_account_file")
        or ""
    )
    oauth_json = (
        os.environ.get("SIGNALATLAS_GSC_OAUTH_JSON")
        or local.get("oauth_json")
        or ""
    )
    oauth_file = (
        os.environ.get("SIGNALATLAS_GSC_OAUTH_FILE")
        or local.get("oauth_file")
        or ""
    )
    auth_mode = ""
    if service_account_json or service_account_file:
        auth_mode = "service_account"
    elif oauth_json or oauth_file:
        auth_mode = "oauth"

    return {
        "site_url": _normalize_property_url(site_url),
        "service_account_json": str(service_account_json or "").strip(),
        "service_account_file": str(service_account_file or "").strip(),
        "oauth_json": str(oauth_json or "").strip(),
        "oauth_file": str(oauth_file or "").strip(),
        "auth_mode": auth_mode,
        "configured": bool(site_url and auth_mode),
        "source": "env" if any((
            os.environ.get("SIGNALATLAS_GSC_SITE_URL"),
            os.environ.get("SIGNALATLAS_GSC_SERVICE_ACCOUNT_JSON"),
            os.environ.get("SIGNALATLAS_GSC_SERVICE_ACCOUNT_FILE"),
            os.environ.get("SIGNALATLAS_GSC_OAUTH_JSON"),
            os.environ.get("SIGNALATLAS_GSC_OAUTH_FILE"),
        )) else ("local" if any(local.values()) else "missing"),
    }


def _load_json_payload(raw_json: str = "", raw_path: str = "") -> Dict[str, Any]:
    if raw_json:
        try:
            payload = json.loads(raw_json)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}
    if raw_path:
        try:
            payload = json.loads(Path(raw_path).expanduser().read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _google_client_package_state() -> Dict[str, Any]:
    try:
        from google.oauth2 import credentials as oauth_credentials  # noqa: F401
        from google.oauth2 import service_account  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except Exception as exc:
        return {
            "available": False,
            "reason": "google_api_client_missing",
            "detail": str(exc),
        }
    return {
        "available": True,
        "reason": "",
        "detail": "",
    }


def _build_gsc_service() -> tuple[Any, Dict[str, Any]]:
    config = _gsc_provider_config()
    packages = _google_client_package_state()
    if not config["configured"]:
        return None, {
            "configured": False,
            "available": packages["available"],
            "status": "not_configured",
            "site_url": config["site_url"],
            "auth_mode": config["auth_mode"],
            "source": config["source"],
            "detail": "Search Console credentials or property URL are missing.",
        }
    if not packages["available"]:
        return None, {
            "configured": True,
            "available": False,
            "status": "connector_missing",
            "site_url": config["site_url"],
            "auth_mode": config["auth_mode"],
            "source": config["source"],
            "detail": packages["detail"],
        }

    try:
        from google.oauth2.credentials import Credentials as OAuthCredentials
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        from googleapiclient.discovery import build

        if config["auth_mode"] == "service_account":
            payload = _load_json_payload(config["service_account_json"], config["service_account_file"])
            if not payload:
                raise RuntimeError("Invalid or unreadable Search Console service account payload.")
            credentials = ServiceAccountCredentials.from_service_account_info(payload, scopes=[GSC_SCOPE])
        else:
            payload = _load_json_payload(config["oauth_json"], config["oauth_file"])
            if not payload:
                raise RuntimeError("Invalid or unreadable Search Console OAuth payload.")
            credentials = OAuthCredentials.from_authorized_user_info(payload, scopes=[GSC_SCOPE])

        service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
        return service, {
            "configured": True,
            "available": True,
            "status": "ready",
            "site_url": config["site_url"],
            "auth_mode": config["auth_mode"],
            "source": config["source"],
            "detail": "",
        }
    except Exception as exc:
        return None, {
            "configured": True,
            "available": True,
            "status": "auth_error",
            "site_url": config["site_url"],
            "auth_mode": config["auth_mode"],
            "source": config["source"],
            "detail": str(exc),
        }


def _site_entry_matches_target(site_url: str, target_url: str) -> bool:
    candidate = _normalize_property_url(site_url)
    target = _normalize_property_url(target_url)
    if not candidate or not target:
        return False
    target_host = _target_host(target)
    if candidate.startswith("sc-domain:"):
        return _host_matches_domain(target_host, candidate.split(":", 1)[1])
    parsed_candidate = urlparse(candidate)
    parsed_target = urlparse(target)
    if parsed_candidate.netloc.lower() != parsed_target.netloc.lower():
        return False
    candidate_path = parsed_candidate.path or "/"
    target_path = parsed_target.path or "/"
    return target_path.startswith(candidate_path)


def _best_site_entry(site_entries: List[Dict[str, Any]], target_url: str, preferred_site_url: str) -> Optional[Dict[str, Any]]:
    preferred = _normalize_property_url(preferred_site_url)
    if preferred:
        exact = next((entry for entry in site_entries if _normalize_property_url(entry.get("siteUrl", "")) == preferred), None)
        if exact and _site_entry_matches_target(exact.get("siteUrl", ""), target_url):
            return exact
    for entry in site_entries:
        if _site_entry_matches_target(entry.get("siteUrl", ""), target_url):
            return entry
    return None


def get_signalatlas_provider_status(target_url: str = "", mode: str = "public") -> List[dict]:
    clean_mode = str(mode or "public").strip().lower() or "public"
    gsc = _gsc_provider_config()
    gsc_package = _google_client_package_state()
    target_matches = bool(target_url and gsc["site_url"] and _site_entry_matches_target(gsc["site_url"], target_url))
    gsc_status = "configured" if gsc["configured"] else "not_configured"
    if not gsc_package["available"]:
        gsc_status = "connector_missing" if gsc["configured"] else "not_configured"
    elif clean_mode == "verified_owner" and gsc["configured"] and target_url and not target_matches:
        gsc_status = "target_mismatch"

    return [
        {
            "id": "google_search_console",
            "name": "Google Search Console",
            "status": gsc_status,
            "configured": bool(gsc["configured"]),
            "available": True,
            "priority": 1,
            "owner_required": True,
            "source": gsc["source"],
            "auth_mode": gsc["auth_mode"],
            "site_url": gsc["site_url"],
            "target_match": target_matches,
            "package_available": bool(gsc_package["available"]),
            "package_reason": gsc_package["reason"],
            "detail": gsc_package["detail"] if not gsc_package["available"] else "",
        },
        {
            "id": "pagespeed_insights",
            "name": "PageSpeed Insights",
            "status": "configured" if bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("PAGESPEED_API_KEY")) else "scaffolded",
            "configured": bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("PAGESPEED_API_KEY")),
            "available": True,
            "priority": 2,
            "owner_required": False,
            "source": "env" if bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("PAGESPEED_API_KEY")) else "missing",
            "auth_mode": "api_key",
            "site_url": "",
            "target_match": False,
            "package_available": True,
            "package_reason": "",
            "detail": "",
        },
        {
            "id": "bing_webmaster",
            "name": "Bing Webmaster Tools",
            "status": "configured" if bool(os.environ.get("BING_WEBMASTER_API_KEY")) else "scaffolded",
            "configured": bool(os.environ.get("BING_WEBMASTER_API_KEY")),
            "available": True,
            "priority": 3,
            "owner_required": True,
            "source": "env" if bool(os.environ.get("BING_WEBMASTER_API_KEY")) else "missing",
            "auth_mode": "api_key",
            "site_url": "",
            "target_match": False,
            "package_available": True,
            "package_reason": "",
            "detail": "",
        },
        {
            "id": "indexnow",
            "name": "IndexNow",
            "status": "configured" if bool(os.environ.get("INDEXNOW_KEY")) else "scaffolded",
            "configured": bool(os.environ.get("INDEXNOW_KEY")),
            "available": True,
            "priority": 4,
            "owner_required": True,
            "source": "env" if bool(os.environ.get("INDEXNOW_KEY")) else "missing",
            "auth_mode": "key",
            "site_url": "",
            "target_match": False,
            "package_available": True,
            "package_reason": "",
            "detail": "",
        },
        {
            "id": "semrush",
            "name": "Semrush",
            "status": "configured" if bool(os.environ.get("SEMRUSH_API_KEY")) else "scaffolded",
            "configured": bool(os.environ.get("SEMRUSH_API_KEY")),
            "available": True,
            "priority": 5,
            "owner_required": False,
            "source": "env" if bool(os.environ.get("SEMRUSH_API_KEY")) else "missing",
            "auth_mode": "api_key",
            "site_url": "",
            "target_match": False,
            "package_available": True,
            "package_reason": "",
            "detail": "Optional future provider for keyword volume, difficulty, competitors, and external organic pages.",
        },
    ]


def build_owner_context(target_url: str, mode: str = "public") -> Dict[str, Any]:
    clean_mode = str(mode or "public").strip().lower() or "public"
    context: Dict[str, Any] = {
        "mode": clean_mode,
        "integrations": [],
    }
    if clean_mode != "verified_owner":
        return context

    service, status = _build_gsc_service()
    integration = {
        "id": "google_search_console",
        "configured": bool(status.get("configured")),
        "available": bool(status.get("available")),
        "status": status.get("status", "not_configured"),
        "confidence": "Unknown",
        "site_url": status.get("site_url", ""),
        "source": status.get("source", ""),
        "auth_mode": status.get("auth_mode", ""),
        "detail": status.get("detail", ""),
    }

    if service is None:
        context["integrations"].append(integration)
        return context

    try:
        sites_response = service.sites().list().execute()
        site_entries = list((sites_response or {}).get("siteEntry") or [])
        chosen = _best_site_entry(site_entries, target_url, integration["site_url"])
        if not chosen:
            integration.update({
                "status": "property_unverified",
                "confidence": "Unknown",
                "detail": "No verified Search Console property matched the requested target.",
                "verified_property_count": len(site_entries),
            })
            context["integrations"].append(integration)
            return context

        chosen_site_url = _normalize_property_url(chosen.get("siteUrl", ""))
        permission_level = str(chosen.get("permissionLevel") or "").strip()
        integration.update({
            "status": "confirmed",
            "confidence": "Confirmed",
            "site_url": chosen_site_url,
            "permission_level": permission_level,
            "detail": "Verified Search Console property access confirmed for this target.",
        })

        try:
            sitemaps_response = service.sitemaps().list(siteUrl=chosen_site_url).execute()
            sitemap_entries = list((sitemaps_response or {}).get("sitemap") or [])
        except Exception as exc:
            sitemap_entries = []
            integration["sitemaps_error"] = str(exc)

        integration["sitemaps"] = [
            {
                "path": str(item.get("path") or "").strip(),
                "type": str(item.get("type") or "").strip(),
                "last_submitted": str(item.get("lastSubmitted") or "").strip(),
                "is_pending": bool(item.get("isPending")),
                "warning_count": int(item.get("warnings") or 0),
                "submitted_count": int(item.get("contents", [{}])[0].get("submitted") or 0) if isinstance(item.get("contents"), list) and item.get("contents") else 0,
                "indexed_count": int(item.get("contents", [{}])[0].get("indexed") or 0) if isinstance(item.get("contents"), list) and item.get("contents") else 0,
            }
            for item in sitemap_entries[:24]
            if isinstance(item, dict)
        ]
    except Exception as exc:
        integration.update({
            "status": "error",
            "confidence": "Unknown",
            "detail": str(exc),
        })

    context["integrations"].append(integration)
    return context
