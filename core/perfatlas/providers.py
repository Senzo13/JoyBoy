"""Owner/public provider status and enrichment for PerfAtlas."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from core.infra.local_config import get_perfatlas_provider_settings
from core.signalatlas.providers import (
    build_owner_context as build_signalatlas_owner_context,
    get_signalatlas_provider_status,
)


REQUEST_TIMEOUT = 12


def _normalize_host(target_url: str) -> str:
    try:
        parsed = urlparse(target_url if "://" in target_url else f"https://{target_url}")
        return str(parsed.hostname or "").strip().lower()
    except Exception:
        return ""


def _host_matches(host: str, domain: str) -> bool:
    clean_host = str(host or "").lower().strip(".")
    clean_domain = str(domain or "").lower().strip(".")
    if not clean_host or not clean_domain:
        return False
    return clean_host == clean_domain or clean_host.endswith(f".{clean_domain}")


def _host_from_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        return str(parsed.hostname or "").strip().lower()
    except Exception:
        return ""


def _env_or_local(env_keys: List[str], provider_id: str, field: str = "") -> str:
    for key in env_keys:
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    settings = get_perfatlas_provider_settings(provider_id)
    if field:
        return str(settings.get(field) or "").strip()
    for value in settings.values():
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _config_source(env_keys: List[str], provider_id: str) -> str:
    if any(str(os.environ.get(key) or "").strip() for key in env_keys):
        return "env"
    if any(str(value or "").strip() for value in get_perfatlas_provider_settings(provider_id).values()):
        return "local"
    return "missing"


def get_pagespeed_api_key() -> str:
    return _env_or_local(["PAGESPEED_API_KEY", "GOOGLE_API_KEY"], "pagespeed_insights", "api_key")


def get_crux_api_key() -> str:
    return _env_or_local(["CRUX_API_KEY", "GOOGLE_API_KEY"], "crux_api", "api_key")


def get_webpagetest_api_key() -> str:
    return _env_or_local(["WEBPAGETEST_API_KEY", "WPT_API_KEY"], "webpagetest", "api_key")


def _vercel_config() -> Dict[str, str]:
    settings = get_perfatlas_provider_settings("vercel")
    return {
        "token": _env_or_local(["VERCEL_TOKEN"], "vercel", "token"),
        "team_id": str(os.environ.get("VERCEL_TEAM_ID") or settings.get("team_id") or "").strip(),
        "project_id": str(os.environ.get("PERFATLAS_VERCEL_PROJECT_ID") or settings.get("project_id") or "").strip(),
        "source": _config_source(["VERCEL_TOKEN", "VERCEL_TEAM_ID", "PERFATLAS_VERCEL_PROJECT_ID"], "vercel"),
    }


def _netlify_config() -> Dict[str, str]:
    settings = get_perfatlas_provider_settings("netlify")
    return {
        "token": _env_or_local(["NETLIFY_AUTH_TOKEN"], "netlify", "token"),
        "site_id": str(os.environ.get("PERFATLAS_NETLIFY_SITE_ID") or settings.get("site_id") or "").strip(),
        "source": _config_source(["NETLIFY_AUTH_TOKEN", "PERFATLAS_NETLIFY_SITE_ID"], "netlify"),
    }


def _cloudflare_config() -> Dict[str, str]:
    settings = get_perfatlas_provider_settings("cloudflare")
    return {
        "api_token": _env_or_local(["CLOUDFLARE_API_TOKEN"], "cloudflare", "api_token"),
        "zone_id": str(os.environ.get("PERFATLAS_CLOUDFLARE_ZONE_ID") or settings.get("zone_id") or "").strip(),
        "account_id": str(os.environ.get("CLOUDFLARE_ACCOUNT_ID") or settings.get("account_id") or "").strip(),
        "source": _config_source(["CLOUDFLARE_API_TOKEN", "PERFATLAS_CLOUDFLARE_ZONE_ID", "CLOUDFLARE_ACCOUNT_ID"], "cloudflare"),
    }


def _base_provider_entry(
    *,
    provider_id: str,
    name: str,
    configured: bool,
    source: str,
    priority: int,
    owner_required: bool,
    auth_mode: str,
    status: str,
    detail: str = "",
    target_match: bool = False,
    site_url: str = "",
) -> Dict[str, Any]:
    return {
        "id": provider_id,
        "name": name,
        "status": status,
        "configured": configured,
        "available": True,
        "priority": priority,
        "owner_required": owner_required,
        "source": source,
        "auth_mode": auth_mode,
        "site_url": site_url,
        "target_match": target_match,
        "package_available": True,
        "package_reason": "",
        "detail": detail,
    }


def _request_any(url: str, headers: Dict[str, str] | None = None, params: Dict[str, Any] | None = None) -> Any:
    response = requests.get(url, headers=headers or {}, params=params or {}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _request_json(url: str, headers: Dict[str, str] | None = None, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = _request_any(url, headers=headers, params=params)
    return payload if isinstance(payload, dict) else {}


def _request_list(
    url: str,
    *,
    headers: Dict[str, str] | None = None,
    params: Dict[str, Any] | None = None,
    list_key: str = "result",
) -> List[Dict[str, Any]]:
    payload = _request_any(url, headers=headers, params=params)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get(list_key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _iso_from_epoch_millis(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _vercel_params(config: Dict[str, str], **extra: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if config.get("team_id"):
        params["teamId"] = config["team_id"]
    params.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return params


def _candidate_zone_names(host: str) -> List[str]:
    parts = [part for part in str(host or "").split(".") if part]
    candidates: List[str] = []
    for index in range(len(parts) - 1):
        suffix = ".".join(parts[index:])
        if suffix.count(".") >= 1 and suffix not in candidates:
            candidates.append(suffix)
    return candidates


def _vercel_recent_deployments(headers: Dict[str, str], config: Dict[str, str], project_id: str) -> Dict[str, Any]:
    if not project_id:
        return {}
    try:
        payload = _request_json(
            "https://api.vercel.com/v6/deployments",
            headers=headers,
            params=_vercel_params(config, projectId=project_id, limit=4),
        )
        deployments = payload.get("deployments") or []
        recent: List[Dict[str, Any]] = []
        non_ready = 0
        for item in deployments[:4]:
            if not isinstance(item, dict):
                continue
            state = str(item.get("readyState") or item.get("state") or "").strip().upper()
            deployment_url = str(item.get("url") or "").strip()
            if deployment_url and not deployment_url.startswith("http"):
                deployment_url = f"https://{deployment_url}"
            summary = {
                "id": str(item.get("uid") or item.get("id") or "").strip(),
                "target": str(item.get("target") or "").strip(),
                "state": state,
                "url": deployment_url,
                "created_at": _iso_from_epoch_millis(item.get("createdAt")) or str(item.get("createdAt") or ""),
                "aliases": [str(alias or "").strip() for alias in (item.get("alias") or []) if str(alias or "").strip()][:4],
            }
            if summary["state"] not in {"READY", "CACHED"}:
                non_ready += 1
            recent.append(summary)
        return {
            "recent_deployments": recent,
            "latest_deployment": recent[0] if recent else {},
            "recent_non_ready_count": non_ready,
        }
    except Exception as exc:
        return {"deployments_error": str(exc)}


def _netlify_recent_deployments(headers: Dict[str, str], site_id: str) -> Dict[str, Any]:
    if not site_id:
        return {}
    try:
        payload = _request_list(
            f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
            headers=headers,
            params={"per_page": 4},
            list_key="deploys",
        )
        recent: List[Dict[str, Any]] = []
        non_ready = 0
        for item in payload[:4]:
            state = str(item.get("state") or "").strip().lower()
            summary = {
                "id": str(item.get("id") or "").strip(),
                "state": state,
                "context": str(item.get("context") or "").strip(),
                "branch": str(item.get("branch") or "").strip(),
                "created_at": str(item.get("created_at") or "").strip(),
                "published_at": str(item.get("published_at") or "").strip(),
                "deploy_url": str(item.get("deploy_url") or "").strip(),
            }
            if state not in {"current", "ready", "processed", "published", "old"}:
                non_ready += 1
            recent.append(summary)
        return {
            "recent_deployments": recent,
            "latest_deployment": recent[0] if recent else {},
            "recent_non_ready_count": non_ready,
        }
    except Exception as exc:
        return {"deployments_error": str(exc)}


def _netlify_snippets(headers: Dict[str, str], site_id: str) -> Dict[str, Any]:
    if not site_id:
        return {}
    try:
        payload = _request_any(
            f"https://api.netlify.com/api/v1/sites/{site_id}/snippets",
            headers=headers,
        )
        snippets = payload if isinstance(payload, list) else []
        titles: List[str] = []
        total = 0
        head_count = 0
        footer_count = 0
        script_count = 0
        for item in snippets[:20]:
            if not isinstance(item, dict):
                continue
            total += 1
            title = str(item.get("title") or "").strip()
            if title and title not in titles:
                titles.append(title)
            general_position = str(item.get("general_position") or "").strip().lower()
            goal_position = str(item.get("goal_position") or "").strip().lower()
            if general_position == "head":
                head_count += 1
            if general_position == "footer" or goal_position == "footer":
                footer_count += 1
            general = str(item.get("general") or "").lower()
            goal = str(item.get("goal") or "").lower()
            if "<script" in general or "<script" in goal:
                script_count += 1
        return {
            "snippet_count": total,
            "snippet_head_count": head_count,
            "snippet_footer_count": footer_count,
            "snippet_script_count": script_count,
            "snippet_titles": titles[:6],
        }
    except Exception as exc:
        return {"snippets_error": str(exc)}


def _cloudflare_setting_value(result: Dict[str, Any]) -> Any:
    if not isinstance(result, dict):
        return ""
    if "value" in result:
        return result.get("value")
    if "enabled" in result:
        return "on" if result.get("enabled") else "off"
    return ""


def _cloudflare_settings_summary(headers: Dict[str, str], zone_id: str) -> Dict[str, Any]:
    if not zone_id:
        return {}
    signal_ids = (
        "brotli",
        "http3",
        "early_hints",
        "cache_level",
        "browser_cache_ttl",
        "polish",
        "image_resizing",
    )
    signals: Dict[str, Any] = {}
    errors: List[str] = []
    for setting_id in signal_ids:
        try:
            payload = _request_json(
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/settings/{setting_id}",
                headers=headers,
            )
            result = payload.get("result") or {}
            value = _cloudflare_setting_value(result)
            if value not in ("", None, {}):
                signals[setting_id] = value
        except Exception as exc:
            errors.append(f"{setting_id}: {exc}")
    data: Dict[str, Any] = {}
    if signals:
        data["platform_signals"] = signals
    if errors:
        data["settings_error"] = "; ".join(errors[:3])
    return data


def _vercel_context(target_url: str) -> Dict[str, Any]:
    config = _vercel_config()
    if not config["token"]:
        return _base_provider_entry(
            provider_id="vercel",
            name="Vercel",
            configured=False,
            source=config["source"],
            priority=5,
            owner_required=True,
            auth_mode="token",
            status="scaffolded",
            detail="Missing Vercel token.",
        )
    host = _normalize_host(target_url)
    headers = {"Authorization": f"Bearer {config['token']}"}
    detail = ""
    target_match = False
    project_summary: Dict[str, Any] = {}
    status = "partial" if not config["project_id"] else "configured"
    try:
        if config["project_id"]:
            data = _request_json(
                f"https://api.vercel.com/v9/projects/{config['project_id']}",
                headers=headers,
                params=_vercel_params(config),
            )
            domains = [item.get("name", "") for item in data.get("domains", []) if isinstance(item, dict)]
            target_match = any(_host_matches(host, domain) for domain in domains if domain)
            status = "ready" if target_match else "target_mismatch"
            project_summary = {
                "project_id": data.get("id") or config["project_id"],
                "name": data.get("name") or "",
                "framework": data.get("framework") or "",
                "production_domain_count": len(domains),
                "domains": domains[:6],
            }
        else:
            data = _request_json(
                "https://api.vercel.com/v9/projects",
                headers=headers,
                params=_vercel_params(config, limit=20),
            )
            projects = data.get("projects") or []
            match = next((
                item for item in projects
                if any(
                    _host_matches(host, str(domain.get("name") or ""))
                    for domain in (item.get("domains") or [])
                    if isinstance(domain, dict)
                )
            ), None)
            if match:
                target_match = True
                status = "ready"
                project_summary = {
                    "project_id": match.get("id") or "",
                    "name": match.get("name") or "",
                    "framework": match.get("framework") or "",
                    "production_domain_count": len(match.get("domains") or []),
                    "domains": [item.get("name", "") for item in (match.get("domains") or []) if isinstance(item, dict)][:6],
                }
            else:
                detail = "Token configured, but no Vercel project could be matched to this host."
    except Exception as exc:
        detail = str(exc)
        status = "partial"

    if project_summary.get("project_id"):
        project_summary.update(_vercel_recent_deployments(headers, config, str(project_summary.get("project_id") or "")))
    if target_match and not detail:
        detail = "Matched a Vercel project to this host and collected deployment context."
    if project_summary.get("deployments_error"):
        detail = (detail + " " if detail else "") + "Recent deployment context could not be loaded completely."

    entry = _base_provider_entry(
        provider_id="vercel",
        name="Vercel",
        configured=True,
        source=config["source"],
        priority=5,
        owner_required=True,
        auth_mode="token",
        status=status,
        detail=detail.strip(),
        target_match=target_match,
    )
    if project_summary:
        entry["context"] = project_summary
    return entry


def _netlify_context(target_url: str) -> Dict[str, Any]:
    config = _netlify_config()
    if not config["token"]:
        return _base_provider_entry(
            provider_id="netlify",
            name="Netlify",
            configured=False,
            source=config["source"],
            priority=6,
            owner_required=True,
            auth_mode="token",
            status="scaffolded",
            detail="Missing Netlify token.",
        )
    host = _normalize_host(target_url)
    headers = {"Authorization": f"Bearer {config['token']}"}
    detail = ""
    target_match = False
    site_summary: Dict[str, Any] = {}
    status = "partial" if not config["site_id"] else "configured"
    try:
        if config["site_id"]:
            payload = _request_any(
                f"https://api.netlify.com/api/v1/sites/{config['site_id']}",
                headers=headers,
            )
            payload = payload if isinstance(payload, dict) else {}
            domains = [
                value
                for value in [payload.get("custom_domain"), payload.get("ssl_url"), payload.get("url")]
                if isinstance(value, str) and value
            ]
            target_match = any(_host_matches(host, _host_from_url(value)) for value in domains)
            status = "ready" if target_match else "target_mismatch"
            site_summary = {
                "site_id": payload.get("id") or config["site_id"],
                "name": payload.get("name") or "",
                "custom_domain": payload.get("custom_domain") or "",
                "published_deploy": (payload.get("published_deploy") or {}).get("id", ""),
                "production_branch": str(payload.get("published_branch") or (payload.get("repo") or {}).get("branch") or ""),
                "build_command": str((payload.get("build_settings") or {}).get("cmd") or ""),
                "publish_dir": str((payload.get("build_settings") or {}).get("publish") or ""),
            }
        else:
            payload = _request_any("https://api.netlify.com/api/v1/sites", headers=headers)
            sites = payload if isinstance(payload, list) else []
            match = next((
                item for item in sites
                if isinstance(item, dict)
                and any(
                    _host_matches(host, _host_from_url(value))
                    for value in [item.get("custom_domain"), item.get("ssl_url"), item.get("url")]
                    if isinstance(value, str) and value
                )
            ), None)
            if match:
                target_match = True
                status = "ready"
                site_summary = {
                    "site_id": match.get("id") or "",
                    "name": match.get("name") or "",
                    "custom_domain": match.get("custom_domain") or "",
                    "published_deploy": (match.get("published_deploy") or {}).get("id", ""),
                    "production_branch": str(match.get("published_branch") or (match.get("repo") or {}).get("branch") or ""),
                    "build_command": str((match.get("build_settings") or {}).get("cmd") or ""),
                    "publish_dir": str((match.get("build_settings") or {}).get("publish") or ""),
                }
            else:
                detail = "Token configured, but no Netlify site could be matched to this host."
    except Exception as exc:
        detail = str(exc)
        status = "partial"

    if site_summary.get("site_id"):
        site_summary.update(_netlify_recent_deployments(headers, str(site_summary.get("site_id") or "")))
        site_summary.update(_netlify_snippets(headers, str(site_summary.get("site_id") or "")))
    if target_match and not detail:
        detail = "Matched a Netlify site to this host and collected deploy plus snippet context."
    if site_summary.get("deployments_error"):
        detail = (detail + " " if detail else "") + "Recent deploy context could not be loaded completely."
    if site_summary.get("snippets_error"):
        detail = (detail + " " if detail else "") + "Snippet injection context could not be loaded completely."

    entry = _base_provider_entry(
        provider_id="netlify",
        name="Netlify",
        configured=True,
        source=config["source"],
        priority=6,
        owner_required=True,
        auth_mode="token",
        status=status,
        detail=detail.strip(),
        target_match=target_match,
    )
    if site_summary:
        entry["context"] = site_summary
    return entry


def _cloudflare_context(target_url: str) -> Dict[str, Any]:
    config = _cloudflare_config()
    if not config["api_token"]:
        return _base_provider_entry(
            provider_id="cloudflare",
            name="Cloudflare",
            configured=False,
            source=config["source"],
            priority=7,
            owner_required=True,
            auth_mode="token",
            status="scaffolded",
            detail="Missing Cloudflare API token.",
        )
    host = _normalize_host(target_url)
    headers = {"Authorization": f"Bearer {config['api_token']}"}
    detail = ""
    target_match = False
    zone_summary: Dict[str, Any] = {}
    status = "partial" if not config["zone_id"] else "configured"
    try:
        if config["zone_id"]:
            payload = _request_json(
                f"https://api.cloudflare.com/client/v4/zones/{config['zone_id']}",
                headers=headers,
            )
            result = payload.get("result") or {}
            zone_host = str(result.get("name") or "").strip().lower()
            target_match = _host_matches(host, zone_host)
            status = "ready" if target_match else "target_mismatch"
            zone_summary = {
                "zone_id": result.get("id") or config["zone_id"],
                "name": zone_host,
                "status": result.get("status") or "",
                "name_servers": result.get("name_servers") or [],
            }
        else:
            for zone_name in _candidate_zone_names(host):
                payload = _request_json(
                    "https://api.cloudflare.com/client/v4/zones",
                    headers=headers,
                    params={"name": zone_name, "per_page": 5},
                )
                result = payload.get("result") or []
                match = next((item for item in result if _host_matches(host, item.get("name", ""))), None)
                if match:
                    target_match = True
                    status = "ready"
                    zone_summary = {
                        "zone_id": match.get("id") or "",
                        "name": match.get("name") or "",
                        "status": match.get("status") or "",
                        "name_servers": match.get("name_servers") or [],
                    }
                    break
            if not zone_summary:
                detail = "Token configured, but no Cloudflare zone could be matched to this host."
    except Exception as exc:
        detail = str(exc)
        status = "partial"

    if zone_summary.get("zone_id"):
        zone_summary.update(_cloudflare_settings_summary(headers, str(zone_summary.get("zone_id") or "")))
    if target_match and not detail:
        detail = "Matched a Cloudflare zone to this host and collected edge delivery settings."
    if zone_summary.get("settings_error"):
        detail = (detail + " " if detail else "") + "Some edge settings could not be read with this token."

    entry = _base_provider_entry(
        provider_id="cloudflare",
        name="Cloudflare",
        configured=True,
        source=config["source"],
        priority=7,
        owner_required=True,
        auth_mode="token",
        status=status,
        detail=detail.strip(),
        target_match=target_match,
    )
    if zone_summary:
        entry["context"] = zone_summary
    return entry


def get_perfatlas_provider_status(target_url: str = "", mode: str = "public") -> List[dict]:
    clean_mode = str(mode or "public").strip().lower() or "public"
    google_entries = get_signalatlas_provider_status(target_url=target_url, mode=clean_mode)
    gsc_entry = next((item for item in google_entries if item.get("id") == "google_search_console"), None)
    pagespeed_key = get_pagespeed_api_key()
    crux_key = get_crux_api_key()
    webpagetest_key = get_webpagetest_api_key()
    vercel_config = _vercel_config()
    netlify_config = _netlify_config()
    cloudflare_config = _cloudflare_config()

    providers: List[dict] = []
    if gsc_entry:
        providers.append(dict(gsc_entry))
    providers.extend([
        _base_provider_entry(
            provider_id="crux_api",
            name="Chrome UX Report API",
            configured=bool(crux_key),
            source=_config_source(["CRUX_API_KEY", "GOOGLE_API_KEY"], "crux_api"),
            priority=1,
            owner_required=False,
            auth_mode="api_key",
            status="configured" if crux_key else "scaffolded",
            detail="" if crux_key else "Add CRUX_API_KEY or GOOGLE_API_KEY to unlock field metrics.",
        ),
        _base_provider_entry(
            provider_id="crux_history_api",
            name="Chrome UX Report History API",
            configured=bool(crux_key),
            source=_config_source(["CRUX_API_KEY", "GOOGLE_API_KEY"], "crux_api"),
            priority=2,
            owner_required=False,
            auth_mode="api_key",
            status="configured" if crux_key else "scaffolded",
            detail="" if crux_key else "Uses the same Google API key as CrUX.",
        ),
        _base_provider_entry(
            provider_id="pagespeed_insights",
            name="PageSpeed Insights",
            configured=bool(pagespeed_key),
            source=_config_source(["PAGESPEED_API_KEY", "GOOGLE_API_KEY"], "pagespeed_insights"),
            priority=3,
            owner_required=False,
            auth_mode="api_key",
            status="configured" if pagespeed_key else "scaffolded",
            detail="" if pagespeed_key else "A key is optional for light public use, but required for stable quota.",
        ),
        _base_provider_entry(
            provider_id="webpagetest",
            name="WebPageTest",
            configured=bool(webpagetest_key),
            source=_config_source(["WEBPAGETEST_API_KEY", "WPT_API_KEY"], "webpagetest"),
            priority=4,
            owner_required=False,
            auth_mode="api_key",
            status="configured" if webpagetest_key else "scaffolded",
            detail="" if webpagetest_key else "Optional deep-lab provider for future filmstrip, waterfall, and location-based runs.",
        ),
    ])
    if clean_mode == "verified_owner":
        providers.extend([
            _vercel_context(target_url),
            _netlify_context(target_url),
            _cloudflare_context(target_url),
        ])
    else:
        providers.extend([
            _base_provider_entry(
                provider_id="vercel",
                name="Vercel",
                configured=bool(vercel_config["token"]),
                source=vercel_config["source"],
                priority=5,
                owner_required=True,
                auth_mode="token",
                status="configured" if vercel_config["token"] else "scaffolded",
                detail="Owner connector enriches deployment context when verified-owner mode is used.",
            ),
            _base_provider_entry(
                provider_id="netlify",
                name="Netlify",
                configured=bool(netlify_config["token"]),
                source=netlify_config["source"],
                priority=6,
                owner_required=True,
                auth_mode="token",
                status="configured" if netlify_config["token"] else "scaffolded",
                detail="Owner connector enriches deploy context when verified-owner mode is used.",
            ),
            _base_provider_entry(
                provider_id="cloudflare",
                name="Cloudflare",
                configured=bool(cloudflare_config["api_token"]),
                source=cloudflare_config["source"],
                priority=7,
                owner_required=True,
                auth_mode="token",
                status="configured" if cloudflare_config["api_token"] else "scaffolded",
                detail="Owner connector enriches CDN and edge delivery context when verified-owner mode is used.",
            ),
        ])
    return providers


def build_owner_context(target_url: str, mode: str = "public") -> Dict[str, Any]:
    clean_mode = str(mode or "public").strip().lower() or "public"
    context = build_signalatlas_owner_context(target_url, mode=clean_mode)
    if clean_mode != "verified_owner":
        return context
    integrations = list(context.get("integrations") or [])
    integrations.extend([
        _vercel_context(target_url),
        _netlify_context(target_url),
        _cloudflare_context(target_url),
    ])
    context["integrations"] = integrations
    return context
