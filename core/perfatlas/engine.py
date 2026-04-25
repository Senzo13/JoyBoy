"""Deterministic performance auditing for PerfAtlas."""

from __future__ import annotations

import json
import math
import os
import shutil
import statistics
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.audit_modules.targets import normalize_public_target

from .intelligence import build_performance_intelligence, intelligence_finding_specs
from .providers import build_owner_context, get_crux_api_key, get_pagespeed_api_key, get_perfatlas_provider_status, get_webpagetest_api_key
from .scoring import score_findings


ProgressCallback = Optional[Callable[[str, float, str], None]]
CancelCheck = Optional[Callable[[], bool]]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JoyBoy PerfAtlas/1.0; +https://joyboy.local)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SYSTEM_PATH_PREFIXES = (
    "/cdn-cgi/",
    "/wp-admin/",
    "/wp-json/",
    "/api/",
)

LCP_GOOD = 2500
LCP_POOR = 4000
INP_GOOD = 200
INP_POOR = 500
CLS_GOOD = 0.1
CLS_POOR = 0.25
TTFB_GOOD = 800
TTFB_POOR = 1800
TBT_GOOD = 200
TBT_POOR = 600


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


def _is_system_url(url: str) -> bool:
    try:
        path = urlparse(url).path or "/"
    except Exception:
        return False
    return any(path.startswith(prefix) for prefix in SYSTEM_PATH_PREFIXES)


def _normalize_url(url: str, base_url: str) -> str:
    resolved = urljoin(base_url, url or "")
    parsed = urlparse(resolved)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return ""
    clean = parsed._replace(
        fragment="",
        params="",
        path=parsed.path or "/",
    )
    return clean.geturl()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _content_length(response: requests.Response) -> int:
    header = _safe_int(response.headers.get("Content-Length"), 0)
    return header or len(response.content or b"")


def _header_map(response: requests.Response) -> Dict[str, str]:
    keep = (
        "Cache-Control",
        "Content-Encoding",
        "Content-Length",
        "Content-Type",
        "Server",
        "Age",
        "ETag",
        "Last-Modified",
        "Vary",
        "CF-Cache-Status",
        "Alt-Svc",
    )
    return {key: str(response.headers.get(key) or "") for key in keep if response.headers.get(key) is not None}


def _template_signature(url: str) -> str:
    try:
        path = urlparse(url).path or "/"
    except Exception:
        path = "/"
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    normalized: List[str] = []
    for part in parts[:4]:
        if any(ch.isdigit() for ch in part) or len(part) > 48:
            normalized.append("{dynamic}")
        else:
            normalized.append(part.lower())
    return "/" + "/".join(normalized)


def _detect_platform(html: str, headers: Dict[str, str]) -> str:
    lower = html.lower()
    server = str(headers.get("Server") or "").lower()
    if "__next_data__" in lower or "_next/static" in lower:
        return "Next.js"
    if "vite" in lower or "/assets/index-" in lower:
        return "Vite"
    if "astro-island" in lower or "astro/" in lower:
        return "Astro"
    if "x-powered-by" in lower or "express" in server:
        return "Node/Express"
    if "cf-cache-status" in {key.lower() for key in headers.keys()}:
        return "Cloudflare fronted"
    return "Custom"


def _extract_links(base_url: str, soup: BeautifulSoup, host: str) -> Tuple[List[str], List[str]]:
    internal: List[str] = []
    external_hosts: List[str] = []
    seen_internal = set()
    seen_external = set()
    for anchor in soup.select("a[href]"):
        href = _normalize_url(anchor.get("href") or "", base_url)
        if not href:
            continue
        parsed = urlparse(href)
        if _same_host(parsed.hostname or "", host):
            if href not in seen_internal and not _is_system_url(href):
                seen_internal.add(href)
                internal.append(href)
        else:
            external_host = str(parsed.hostname or "").strip().lower()
            if external_host and external_host not in seen_external:
                seen_external.add(external_host)
                external_hosts.append(external_host)
    return internal, external_hosts


def _collect_assets(base_url: str, soup: BeautifulSoup) -> List[Dict[str, str]]:
    assets: List[Dict[str, str]] = []
    seen = set()

    def add(url: str, kind: str) -> None:
        href = _normalize_url(url, base_url)
        if not href or href in seen:
            return
        seen.add(href)
        assets.append({"url": href, "kind": kind})

    for tag in soup.select("script[src]"):
        add(tag.get("src") or "", "script")
    for tag in soup.select("link[rel]"):
        rel = " ".join(tag.get("rel") or []).lower()
        href = tag.get("href") or ""
        if not href:
            continue
        if "stylesheet" in rel:
            add(href, "stylesheet")
        elif "preload" in rel and str(tag.get("as") or "").lower() == "font":
            add(href, "font")
    for tag in soup.select("img[src]"):
        add(tag.get("src") or "", "image")
    return assets


def _collect_page_snapshot(
    session: requests.Session,
    url: str,
    depth: int,
    *,
    timeout: int = 15,
) -> Tuple[Dict[str, Any], List[Dict[str, str]], str]:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    body = response.text if "text" in (response.headers.get("Content-Type") or "") or "html" in (response.headers.get("Content-Type") or "") else response.text
    soup = BeautifulSoup(body or "", "html.parser")
    final_url = response.url or url
    parsed_final = urlparse(final_url)
    host = str(parsed_final.hostname or "").strip().lower()
    internal_links, external_hosts = _extract_links(final_url, soup, host)
    assets = _collect_assets(final_url, soup)
    scripts = soup.select("script[src]")
    stylesheets = [tag for tag in soup.select("link[rel]") if "stylesheet" in " ".join(tag.get("rel") or []).lower()]
    images = soup.select("img")
    lazy_images = [
        tag for tag in images
        if str(tag.get("loading") or "").strip().lower() == "lazy"
    ]
    image_missing_dimensions = [
        tag for tag in images
        if not str(tag.get("width") or "").strip() or not str(tag.get("height") or "").strip()
    ]
    preloads = [tag for tag in soup.select("link[rel]") if "preload" in " ".join(tag.get("rel") or []).lower()]
    preconnects = [tag for tag in soup.select("link[rel]") if "preconnect" in " ".join(tag.get("rel") or []).lower()]
    third_party_hosts = {
        urlparse(item["url"]).hostname.lower()
        for item in assets
        if urlparse(item["url"]).hostname and not _same_host(urlparse(item["url"]).hostname or "", host)
    }
    font_hosts = {
        urlparse(item["url"]).hostname.lower()
        for item in assets
        if item["kind"] == "font" and urlparse(item["url"]).hostname
    }
    render_blocking_hints: List[str] = []
    if len(stylesheets) >= 3:
        render_blocking_hints.append("multiple_stylesheets")
    blocking_scripts = [
        tag for tag in scripts
        if not tag.has_attr("defer") and not tag.has_attr("async")
    ]
    if blocking_scripts:
        render_blocking_hints.append("blocking_scripts")

    snapshot = {
        "url": url,
        "final_url": final_url,
        "status_code": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type") or ""),
        "title": str(soup.title.string or "").strip() if soup.title and soup.title.string else "",
        "html_lang": str((soup.html or {}).get("lang") or "").strip(),
        "template_signature": _template_signature(final_url),
        "content_length": _content_length(response),
        "transfer_size_bytes": _content_length(response),
        "html_bytes": len((body or "").encode("utf-8")),
        "ttfb_ms": round(float(response.elapsed.total_seconds()) * 1000, 1),
        "request_duration_ms": round(float(response.elapsed.total_seconds()) * 1000, 1),
        "script_count": len(scripts),
        "stylesheet_count": len(stylesheets),
        "image_count": len(images),
        "lazy_image_count": len(lazy_images),
        "image_missing_dimension_count": len(image_missing_dimensions),
        "preload_count": len(preloads),
        "preconnect_count": len(preconnects),
        "font_host_count": len(font_hosts),
        "third_party_host_count": len(third_party_hosts),
        "render_blocking_hints": render_blocking_hints,
        "resource_hints": {
            "preload": len(preloads),
            "preconnect": len(preconnects),
        },
        "redirected": bool(response.history),
        "redirect_count": len(response.history or []),
        "headers": _header_map(response),
        "internal_links": internal_links,
        "external_hosts": external_hosts[:12],
        "notes": [],
        "system_url": _is_system_url(final_url),
        "crawl_depth": depth,
    }
    if not lazy_images and len(images) >= 4:
        snapshot["notes"].append("many_images_without_lazy_loading")
    if not preconnects and any("fonts.gstatic.com" in item["url"] for item in assets):
        snapshot["notes"].append("font_preconnect_missing")
    if response.headers.get("Content-Encoding", "").lower() not in {"br", "gzip"} and len(body or "") > 20000:
        snapshot["notes"].append("document_not_compressed")
    return snapshot, assets, body or ""


def _fetch_asset_sample(session: requests.Session, asset: Dict[str, str], host: str) -> Optional[Dict[str, Any]]:
    url = str(asset.get("url") or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    try:
        response = session.head(url, timeout=10, allow_redirects=True)
        if response.status_code >= 400 or not response.headers:
            response = session.get(url, timeout=10, allow_redirects=True, stream=True)
    except Exception:
        try:
            response = session.get(url, timeout=10, allow_redirects=True, stream=True)
        except Exception:
            return None
    return {
        "url": response.url or url,
        "kind": asset.get("kind") or "asset",
        "host": str(urlparse(response.url or url).hostname or "").lower(),
        "same_host": _same_host(urlparse(response.url or url).hostname or "", host),
        "status_code": int(response.status_code),
        "content_length": _safe_int(response.headers.get("Content-Length"), 0),
        "content_type": str(response.headers.get("Content-Type") or ""),
        "cache_control": str(response.headers.get("Cache-Control") or ""),
        "content_encoding": str(response.headers.get("Content-Encoding") or ""),
        "cf_cache_status": str(response.headers.get("CF-Cache-Status") or ""),
        "age": str(response.headers.get("Age") or ""),
        "etag": str(response.headers.get("ETag") or ""),
        "vary": str(response.headers.get("Vary") or ""),
    }


def _parse_cache_control(value: str) -> Dict[str, Any]:
    directives: Dict[str, Any] = {}
    for raw_part in str(value or "").split(","):
        part = raw_part.strip().lower()
        if not part:
            continue
        if "=" in part:
            key, raw_value = part.split("=", 1)
            clean_key = key.strip()
            clean_value = raw_value.strip().strip('"')
            directives[clean_key] = clean_value
        else:
            directives[part] = True
    return directives


def _cache_ttl_seconds(asset: Dict[str, Any]) -> int:
    directives = _parse_cache_control(str(asset.get("cache_control") or ""))
    for key in ("s-maxage", "max-age"):
        value = directives.get(key)
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except Exception:
            continue
    return 0


def _is_strong_asset_cache(asset: Dict[str, Any]) -> bool:
    directives = _parse_cache_control(str(asset.get("cache_control") or ""))
    ttl = _cache_ttl_seconds(asset)
    if directives.get("immutable"):
        return True
    return ttl >= 2_592_000


def _is_explicitly_uncacheable(asset: Dict[str, Any]) -> bool:
    directives = _parse_cache_control(str(asset.get("cache_control") or ""))
    return any(key in directives for key in ("no-store", "private", "no-cache"))


def _aggregate_template_clusters(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        signature = str(page.get("template_signature") or "/")
        bucket = buckets.setdefault(signature, {"template": signature, "count": 0, "avg_ttfb_ms": 0.0, "avg_html_kb": 0.0, "sample_urls": []})
        bucket["count"] += 1
        bucket["avg_ttfb_ms"] += _safe_float(page.get("ttfb_ms"), 0.0)
        bucket["avg_html_kb"] += round(_safe_float(page.get("html_bytes"), 0.0) / 1024, 1)
        if len(bucket["sample_urls"]) < 5:
            bucket["sample_urls"].append(page.get("final_url") or page.get("url") or "")
    clusters: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        count = max(1, int(bucket["count"]))
        clusters.append({
            "template": bucket["template"],
            "count": count,
            "avg_ttfb_ms": round(bucket["avg_ttfb_ms"] / count, 1),
            "avg_html_kb": round(bucket["avg_html_kb"] / count, 1),
            "sample_urls": bucket["sample_urls"],
        })
    clusters.sort(key=lambda item: (-item["count"], item["template"]))
    return clusters


def _detect_chrome_path() -> str:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("msedge"),
        shutil.which("msedge.exe"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if shutil.which(candidate) or (isinstance(candidate, str) and os.path.exists(candidate)):
            return candidate
    return ""


def _run_subprocess(command: List[str], timeout: int = 120) -> Tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return completed.returncode, completed.stdout or "", completed.stderr or ""
    except Exception as exc:
        return 1, "", str(exc)


def _lighthouse_runtime_status() -> Dict[str, Any]:
    node_path = shutil.which("node")
    npx_path = shutil.which("npx") or shutil.which("npx.cmd")
    chrome_path = _detect_chrome_path()
    if not node_path or not npx_path:
        return {
            "available": False,
            "runner": "unavailable",
            "note": "Node or npx is unavailable in this runtime.",
            "chrome_path": chrome_path,
        }
    if not chrome_path:
        return {
            "available": False,
            "runner": "unavailable",
            "note": "No Chrome/Chromium runtime was detected for local Lighthouse.",
            "chrome_path": "",
        }
    code, stdout, stderr = _run_subprocess([npx_path, "--no-install", "lighthouse", "--version"], timeout=20)
    if code != 0:
        return {
            "available": False,
            "runner": "unavailable",
            "note": (stderr or stdout or "Lighthouse is not installed for npx --no-install.").strip(),
            "chrome_path": chrome_path,
        }
    return {
        "available": True,
        "runner": "lighthouse_local",
        "note": (stdout or "Local Lighthouse runtime ready.").strip(),
        "chrome_path": chrome_path,
    }


def _parse_lighthouse_result(
    url: str,
    runner: str,
    strategy: str,
    data: Dict[str, Any],
    *,
    runs_attempted: int,
    runs_completed: int,
    note: str = "",
) -> Dict[str, Any]:
    lhr = data.get("lhr") if isinstance(data.get("lhr"), dict) else data.get("lighthouseResult") or data
    categories = lhr.get("categories") or {}
    audits = lhr.get("audits") or {}
    raw_performance_score = (categories.get("performance") or {}).get("score")
    performance_score = _safe_float(raw_performance_score, 0.0)
    score = round(performance_score * 100, 1) if raw_performance_score is not None else None

    def audit_numeric(audit_id: str) -> Optional[float]:
        value = (audits.get(audit_id) or {}).get("numericValue")
        return None if value is None else round(_safe_float(value), 1)

    opportunity_ids = (
        "render-blocking-resources",
        "unused-javascript",
        "unused-css-rules",
        "modern-image-formats",
        "offscreen-images",
        "uses-long-cache-ttl",
        "uses-text-compression",
        "third-party-summary",
        "server-response-time",
    )
    opportunities: List[Dict[str, Any]] = []
    for audit_id in opportunity_ids:
        audit = audits.get(audit_id) or {}
        numeric = audit.get("numericValue")
        display = str(audit.get("displayValue") or "").strip()
        if numeric in (None, 0) and not display:
            continue
        opportunities.append({
            "id": audit_id,
            "title": audit.get("title") or audit_id.replace("-", " ").title(),
            "display_value": display,
            "numeric_value": _safe_float(numeric, 0.0),
            "description": audit.get("description") or "",
        })
    diagnostics = {}
    for audit_id in ("largest-contentful-paint-element", "network-requests", "resource-summary"):
        audit = audits.get(audit_id) or {}
        if audit:
            diagnostics[audit_id] = {
                "title": audit.get("title") or audit_id,
                "display_value": audit.get("displayValue") or "",
                "details": audit.get("details") or {},
            }
    return {
        "url": url,
        "runner": runner,
        "strategy": strategy,
        "runs_attempted": runs_attempted,
        "runs_completed": runs_completed,
        "score": score,
        "first_contentful_paint_ms": audit_numeric("first-contentful-paint"),
        "largest_contentful_paint_ms": audit_numeric("largest-contentful-paint"),
        "cumulative_layout_shift": audit_numeric("cumulative-layout-shift"),
        "total_blocking_time_ms": audit_numeric("total-blocking-time"),
        "speed_index_ms": audit_numeric("speed-index"),
        "interactive_ms": audit_numeric("interactive"),
        "server_response_time_ms": audit_numeric("server-response-time"),
        "total_byte_weight": _safe_int(audit_numeric("total-byte-weight"), 0) or None,
        "request_count": _safe_int(audit_numeric("network-requests"), 0) or None,
        "diagnostics": diagnostics,
        "opportunities": opportunities[:8],
        "note": note,
    }


def _median_run(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [item for item in runs if item.get("score") is not None]
    if not valid:
        return runs[0] if runs else {}
    ordered = sorted(valid, key=lambda item: item.get("score") or 0)
    return ordered[len(ordered) // 2]


def _run_local_lighthouse(url: str, strategy: str, runs: int, runtime_status: Dict[str, Any]) -> Dict[str, Any]:
    chrome_path = runtime_status.get("chrome_path") or ""
    npx_path = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx_path or not chrome_path:
        return {}
    collected: List[Dict[str, Any]] = []
    for _ in range(max(1, runs)):
        command = [
            npx_path,
            "--no-install",
            "lighthouse",
            url,
            "--only-categories=performance",
            "--quiet",
            "--output=json",
            "--output-path=stdout",
            f"--chrome-path={chrome_path}",
            "--chrome-flags=--headless=new --no-sandbox",
            "--emulated-form-factor=" + ("mobile" if strategy == "mobile" else "desktop"),
        ]
        code, stdout, stderr = _run_subprocess(command, timeout=180)
        if code != 0 or not stdout.strip():
            note = (stderr or stdout or "Lighthouse run failed.").strip()
            return {
                "url": url,
                "runner": "lighthouse_local",
                "strategy": strategy,
                "runs_attempted": runs,
                "runs_completed": len(collected),
                "note": note,
                "opportunities": [],
                "diagnostics": {},
            }
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "url": url,
                "runner": "lighthouse_local",
                "strategy": strategy,
                "runs_attempted": runs,
                "runs_completed": len(collected),
                "note": "Local Lighthouse returned invalid JSON.",
                "opportunities": [],
                "diagnostics": {},
            }
        collected.append(_parse_lighthouse_result(url, "lighthouse_local", strategy, payload, runs_attempted=runs, runs_completed=len(collected) + 1))
    chosen = _median_run(collected)
    chosen["runs_attempted"] = runs
    chosen["runs_completed"] = len(collected)
    scores = [_safe_float(item.get("score"), math.nan) for item in collected if item.get("score") is not None]
    lcps = [_safe_float(item.get("largest_contentful_paint_ms"), math.nan) for item in collected if item.get("largest_contentful_paint_ms") is not None]
    tbts = [_safe_float(item.get("total_blocking_time_ms"), math.nan) for item in collected if item.get("total_blocking_time_ms") is not None]
    multi_run_summary = {
        "policy": "median_score_run",
        "runs_completed": len(collected),
        "score_min": round(min(scores), 1) if scores else None,
        "score_max": round(max(scores), 1) if scores else None,
        "score_range": round(max(scores) - min(scores), 1) if len(scores) >= 2 else 0,
        "lcp_min_ms": round(min(lcps), 1) if lcps else None,
        "lcp_max_ms": round(max(lcps), 1) if lcps else None,
        "lcp_range_ms": round(max(lcps) - min(lcps), 1) if len(lcps) >= 2 else 0,
        "tbt_min_ms": round(min(tbts), 1) if tbts else None,
        "tbt_max_ms": round(max(tbts), 1) if tbts else None,
        "tbt_range_ms": round(max(tbts) - min(tbts), 1) if len(tbts) >= 2 else 0,
    }
    chosen.setdefault("diagnostics", {})
    chosen["diagnostics"]["multi_run_summary"] = multi_run_summary
    chosen["diagnostics"]["raw_run_summaries"] = [
        {
            "score": item.get("score"),
            "lcp_ms": item.get("largest_contentful_paint_ms"),
            "tbt_ms": item.get("total_blocking_time_ms"),
            "cls": item.get("cumulative_layout_shift"),
            "total_byte_weight": item.get("total_byte_weight"),
            "request_count": item.get("request_count"),
        }
        for item in collected[:10]
    ]
    return chosen


def _run_pagespeed_insights(url: str, strategy: str) -> Dict[str, Any]:
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
    }
    key = get_pagespeed_api_key()
    if key:
        params["key"] = key
    try:
        response = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
        return _parse_lighthouse_result(url, "pagespeed_insights", strategy, payload, runs_attempted=1, runs_completed=1, note="Remote lab data via PageSpeed Insights.")
    except Exception as exc:
        return {
            "url": url,
            "runner": "pagespeed_insights",
            "strategy": strategy,
            "runs_attempted": 1,
            "runs_completed": 0,
            "note": str(exc),
            "opportunities": [],
            "diagnostics": {},
        }


def _webpagetest_metric(data: Dict[str, Any], *names: str) -> Optional[float]:
    for name in names:
        value: Any = data
        for part in str(name).split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value is None:
            continue
        numeric = _safe_float(value, math.nan)
        if not math.isnan(numeric):
            return round(numeric, 1)
    return None


def _score_webpagetest_result(first_view: Dict[str, Any]) -> Optional[float]:
    lcp = _webpagetest_metric(first_view, "LargestContentfulPaint", "largestContentfulPaint", "chromeUserTiming.LargestContentfulPaint")
    tbt = _webpagetest_metric(first_view, "TotalBlockingTime", "totalBlockingTime")
    ttfb = _webpagetest_metric(first_view, "TTFB", "ttfb")
    speed_index = _webpagetest_metric(first_view, "SpeedIndex", "speedIndex")
    if not any(value is not None for value in (lcp, tbt, ttfb, speed_index)):
        return None
    score = 100.0
    if lcp:
        score -= max(0.0, min(35.0, (lcp - LCP_GOOD) / 90.0))
    if tbt:
        score -= max(0.0, min(25.0, (tbt - TBT_GOOD) / 32.0))
    if ttfb:
        score -= max(0.0, min(18.0, (ttfb - TTFB_GOOD) / 70.0))
    if speed_index:
        score -= max(0.0, min(22.0, (speed_index - 3400.0) / 170.0))
    return round(max(0.0, min(100.0, score)), 1)


def _parse_webpagetest_result(url: str, strategy: str, payload: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    median = data.get("median") or {}
    first_view = (median.get("firstView") or {})
    if not first_view:
        runs = data.get("runs") or {}
        first_run = next((item for item in runs.values() if isinstance(item, dict)), {})
        first_view = first_run.get("firstView") or {}
    if not first_view:
        return {
            "url": url,
            "runner": "webpagetest",
            "strategy": strategy,
            "runs_attempted": 1,
            "runs_completed": 0,
            "note": note or "WebPageTest result did not include a first-view payload.",
            "opportunities": [],
            "diagnostics": {},
        }
    total_bytes = _safe_int(first_view.get("bytesIn") or first_view.get("bytesInDoc"), 0) or None
    request_count = _safe_int(first_view.get("requestsFull") or first_view.get("requests"), 0) or None
    lcp = _webpagetest_metric(first_view, "LargestContentfulPaint", "largestContentfulPaint", "chromeUserTiming.LargestContentfulPaint")
    tbt = _webpagetest_metric(first_view, "TotalBlockingTime", "totalBlockingTime")
    ttfb = _webpagetest_metric(first_view, "TTFB", "ttfb")
    opportunities: List[Dict[str, Any]] = []
    if ttfb and ttfb > TTFB_GOOD:
        opportunities.append({
            "id": "server-response-time",
            "title": "Reduce initial server response time",
            "display_value": f"{round(ttfb)} ms",
            "numeric_value": ttfb,
            "description": "WebPageTest measured a slow time to first byte.",
        })
    if total_bytes and total_bytes > 1_600_000:
        opportunities.append({
            "id": "total-byte-weight",
            "title": "Reduce total page weight",
            "display_value": f"{round(total_bytes / 1024)} KiB",
            "numeric_value": total_bytes,
            "description": "WebPageTest measured a heavy first-view payload.",
        })
    return {
        "url": url,
        "runner": "webpagetest",
        "strategy": strategy,
        "runs_attempted": 1,
        "runs_completed": 1,
        "score": _score_webpagetest_result(first_view),
        "first_contentful_paint_ms": _webpagetest_metric(first_view, "firstContentfulPaint", "chromeUserTiming.firstContentfulPaint"),
        "largest_contentful_paint_ms": lcp,
        "cumulative_layout_shift": _webpagetest_metric(first_view, "CumulativeLayoutShift", "cumulativeLayoutShift"),
        "total_blocking_time_ms": tbt,
        "speed_index_ms": _webpagetest_metric(first_view, "SpeedIndex", "speedIndex"),
        "interactive_ms": _webpagetest_metric(first_view, "domInteractive"),
        "server_response_time_ms": ttfb,
        "total_byte_weight": total_bytes,
        "request_count": request_count,
        "diagnostics": {
            "webpagetest": {
                "test_id": data.get("id") or data.get("testId") or "",
                "summary": data.get("summary") or "",
                "test_url": data.get("userUrl") or url,
            }
        },
        "opportunities": opportunities,
        "note": note or "Remote lab data via WebPageTest.",
    }


def _run_webpagetest(url: str, strategy: str) -> Dict[str, Any]:
    api_key = get_webpagetest_api_key()
    if not api_key:
        return {
            "url": url,
            "runner": "webpagetest",
            "strategy": strategy,
            "runs_attempted": 1,
            "runs_completed": 0,
            "note": "WEBPAGETEST_API_KEY is not configured.",
            "opportunities": [],
            "diagnostics": {},
        }
    headers = {"X-WPT-API-KEY": api_key}
    params = {
        "url": url,
        "f": "json",
        "runs": 1,
        "video": 1,
        "mobile": 1 if strategy == "mobile" else 0,
    }
    try:
        response = requests.get("https://www.webpagetest.org/runtest.php", params=params, headers=headers, timeout=30)
        response.raise_for_status()
        submitted_payload = response.json()
        submitted = submitted_payload if isinstance(submitted_payload, dict) else {}
        data = submitted.get("data") or {}
        json_url = str(data.get("jsonUrl") or "").strip()
        test_id = str(data.get("testId") or data.get("id") or "").strip()
        if not json_url and test_id:
            json_url = f"https://www.webpagetest.org/jsonResult.php?test={test_id}"
        if not json_url:
            return {
                "url": url,
                "runner": "webpagetest",
                "strategy": strategy,
                "runs_attempted": 1,
                "runs_completed": 0,
                "note": str(submitted.get("statusText") or "WebPageTest did not return a result URL."),
                "opportunities": [],
                "diagnostics": {},
            }
        for attempt in range(8):
            poll = requests.get(json_url, headers=headers, timeout=30)
            poll.raise_for_status()
            poll_payload = poll.json()
            payload = poll_payload if isinstance(poll_payload, dict) else {}
            status_code = _safe_int(payload.get("statusCode"), 0)
            if status_code == 200 or (payload.get("data") or {}).get("median"):
                return _parse_webpagetest_result(url, strategy, payload, note="Remote lab data via WebPageTest.")
            if status_code >= 400:
                break
            time.sleep(5 + attempt)
        return {
            "url": url,
            "runner": "webpagetest",
            "strategy": strategy,
            "runs_attempted": 1,
            "runs_completed": 0,
            "note": "WebPageTest did not finish before the PerfAtlas polling window closed.",
            "opportunities": [],
            "diagnostics": {},
        }
    except Exception as exc:
        return {
            "url": url,
            "runner": "webpagetest",
            "strategy": strategy,
            "runs_attempted": 1,
            "runs_completed": 0,
            "note": str(exc),
            "opportunities": [],
            "diagnostics": {},
        }


def _extract_history_series(metric: Dict[str, Any]) -> List[float]:
    percentiles = metric.get("percentilesTimeseries") or {}
    values = percentiles.get("p75s") or []
    series = [_safe_float(value, math.nan) for value in values if value is not None]
    return [value for value in series if not math.isnan(value)]


def _query_crux(
    scope_value: str,
    scope: str,
    *,
    form_factor: str | None = None,
    history: bool = False,
) -> Dict[str, Any]:
    api_key = get_crux_api_key()
    if not api_key or not scope_value:
        return {}
    endpoint = "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord" if history else "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
    payload: Dict[str, Any] = {}
    if form_factor:
        payload["formFactor"] = form_factor
    payload["origin" if scope == "origin" else "url"] = scope_value
    try:
        response = requests.post(f"{endpoint}?key={api_key}", json=payload, timeout=30)
        response.raise_for_status()
        return response.json() if isinstance(response.json(), dict) else {}
    except Exception:
        return {}


def _metric_good_fraction(metric: Dict[str, Any]) -> Optional[float]:
    histogram = metric.get("histogram") or []
    if not isinstance(histogram, list):
        return None
    for bucket in histogram:
        if not isinstance(bucket, dict):
            continue
        start = bucket.get("start")
        end = bucket.get("end")
        if start == 0 and end in (2500, 0.1, 200):
            try:
                return round(float(bucket.get("density") or 0.0), 3)
            except Exception:
                return None
    return None


def _parse_crux_snapshot(
    scope_value: str,
    scope: str,
    payload: Dict[str, Any],
    *,
    form_factor: str | None = None,
) -> Dict[str, Any]:
    record = payload.get("record") or {}
    metrics = record.get("metrics") or {}
    collection_period = record.get("collectionPeriod") or {}
    lcp = ((metrics.get("largest_contentful_paint") or {}).get("percentiles") or {}).get("p75")
    inp = ((metrics.get("interaction_to_next_paint") or {}).get("percentiles") or {}).get("p75")
    cls = ((metrics.get("cumulative_layout_shift") or {}).get("percentiles") or {}).get("p75")
    fcp = ((metrics.get("first_contentful_paint") or {}).get("percentiles") or {}).get("p75")
    ttfb = ((metrics.get("experimental_time_to_first_byte") or {}).get("percentiles") or {}).get("p75")
    history_payload = _query_crux(scope_value, scope, form_factor=form_factor, history=True)
    history_record = (history_payload.get("record") or {}).get("metrics") or {}
    history: Dict[str, Any] = {}
    for metric_id in ("largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift"):
        series = _extract_history_series(history_record.get(metric_id) or {})
        if len(series) >= 2:
            history[metric_id] = {
                "latest": series[-1],
                "earliest": series[0],
                "direction": "improving" if series[-1] < series[0] else "regressing" if series[-1] > series[0] else "steady",
            }
    return {
        "scope": scope,
        "source": "crux_api",
        "form_factor": str(form_factor or "all").lower(),
        "lcp_ms": _safe_float(lcp, 0.0) or None,
        "inp_ms": _safe_float(inp, 0.0) or None,
        "cls": round(_safe_float(cls, 0.0), 3) if cls is not None else None,
        "fcp_ms": _safe_float(fcp, 0.0) or None,
        "ttfb_ms": _safe_float(ttfb, 0.0) or None,
        "good_lcp_fraction": _metric_good_fraction(metrics.get("largest_contentful_paint") or {}),
        "good_inp_fraction": _metric_good_fraction(metrics.get("interaction_to_next_paint") or {}),
        "good_cls_fraction": _metric_good_fraction(metrics.get("cumulative_layout_shift") or {}),
        "collection_period": collection_period,
        "note": f"Chrome UX Report field data for {scope}" + (f" ({form_factor.lower()})" if form_factor else " (all form factors)") + ".",
        "history": history,
    }


def _build_field_snapshots(entry_url: str) -> List[Dict[str, Any]]:
    snapshots: List[Dict[str, Any]] = []
    parsed = urlparse(entry_url)
    origin = parsed._replace(path="", params="", query="", fragment="").geturl().rstrip("/")
    combinations = (
        ("url", entry_url, None),
        ("origin", origin, None),
        ("url", entry_url, "PHONE"),
        ("origin", origin, "PHONE"),
    )
    for scope, value, form_factor in combinations:
        payload = _query_crux(value, scope, form_factor=form_factor, history=False)
        if payload:
            snapshots.append(_parse_crux_snapshot(value, scope, payload, form_factor=form_factor))
    return snapshots


def _make_finding(
    *,
    finding_id: str,
    title: str,
    url: str,
    scope: str,
    category: str,
    bucket: str,
    severity: str,
    confidence: str,
    expected_impact: str,
    evidence: Iterable[str],
    diagnostic: str,
    probable_cause: str,
    recommended_fix: str,
    acceptance_criteria: str,
    dev_prompt: str,
    validation_state: str = "confirmed",
    evidence_mode: str = "measured",
    relationship_summary: str = "",
) -> Dict[str, Any]:
    return {
        "id": finding_id,
        "title": title,
        "url": url,
        "scope": scope,
        "category": category,
        "bucket": bucket,
        "severity": severity,
        "confidence": confidence,
        "expected_impact": expected_impact,
        "evidence": [str(item) for item in evidence if str(item).strip()],
        "diagnostic": diagnostic,
        "probable_cause": probable_cause,
        "recommended_fix": recommended_fix,
        "acceptance_criteria": acceptance_criteria,
        "dev_prompt": dev_prompt,
        "validation_state": validation_state,
        "evidence_mode": evidence_mode,
        "relationship_summary": relationship_summary,
    }


def _select_primary_field_snapshot(field_data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    preferences = (
        ("url", "all"),
        ("origin", "all"),
        ("url", "phone"),
        ("origin", "phone"),
    )
    for scope, form_factor in preferences:
        match = next((
            item for item in field_data
            if str(item.get("scope") or "") == scope
            and str(item.get("form_factor") or "").lower() == form_factor
        ), None)
        if match:
            return match
    return field_data[0] if field_data else None


def _field_trend_findings(best: Dict[str, Any], target_url: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    history = best.get("history") or {}
    lcp_history = history.get("largest_contentful_paint") or {}
    if lcp_history.get("direction") == "regressing" and (_safe_float(lcp_history.get("latest"), 0.0) - _safe_float(lcp_history.get("earliest"), 0.0)) >= 150:
        findings.append(_make_finding(
            finding_id="field-lcp-regressing",
            title="Largest Contentful Paint trend is regressing in field history",
            url=target_url,
            scope=best.get("scope") or "field",
            category="core_web_vitals",
            bucket="field_readiness",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                f"CrUX history for {best.get('scope')} {best.get('form_factor')} shows LCP worsening from {round(_safe_float(lcp_history.get('earliest'), 0.0))} ms to {round(_safe_float(lcp_history.get('latest'), 0.0))} ms."
            ],
            diagnostic="Historical CrUX data suggests the real-user LCP trend is getting worse rather than stabilizing.",
            probable_cause="Recent template, infrastructure, or asset changes may have increased the startup path cost over time.",
            recommended_fix="Compare recent shipping changes against the LCP path and verify that any optimization work actually improves the next CrUX collection window.",
            acceptance_criteria="The next CrUX history windows stop regressing and the LCP trend stabilizes or improves.",
            dev_prompt="Treat this as a regression investigation, not just a static optimization ticket: identify what changed in the LCP path recently.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="A regressing field trend means performance is actively getting worse for real users, not merely staying below target.",
        ))
    inp_history = history.get("interaction_to_next_paint") or {}
    if inp_history.get("direction") == "regressing" and (_safe_float(inp_history.get("latest"), 0.0) - _safe_float(inp_history.get("earliest"), 0.0)) >= 20:
        findings.append(_make_finding(
            finding_id="field-inp-regressing",
            title="Interaction responsiveness is regressing in field history",
            url=target_url,
            scope=best.get("scope") or "field",
            category="core_web_vitals",
            bucket="interactivity",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                f"CrUX history for {best.get('scope')} {best.get('form_factor')} shows INP worsening from {round(_safe_float(inp_history.get('earliest'), 0.0))} ms to {round(_safe_float(inp_history.get('latest'), 0.0))} ms."
            ],
            diagnostic="Historical CrUX data suggests the interaction path is trending in the wrong direction.",
            probable_cause="JavaScript growth, heavier hydration, or growing third-party work may be increasing real-user interaction delays.",
            recommended_fix="Review recent JS and interactivity changes, then confirm that the next release materially reduces long tasks on the critical interaction path.",
            acceptance_criteria="CrUX history stops regressing for INP and begins to stabilize or improve.",
            dev_prompt="Investigate what recently made the interaction path heavier, especially around hydration, event handlers, and third-party tags.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="A worsening INP trend often signals accumulating main-thread debt release after release.",
        ))
    return findings


def _field_findings(field_data: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    best = _select_primary_field_snapshot(field_data)
    if not best:
        findings.append(_make_finding(
            finding_id="field-data-unavailable",
            title="No field data confirmed for this target yet",
            url=target_url,
            scope=target_url,
            category="field_data",
            bucket="field_readiness",
            severity="low",
            confidence="Estimated",
            expected_impact="Low",
            evidence=["Chrome UX Report returned no usable record for the sampled URL or origin."],
            diagnostic="No CrUX field record was available for this target in the current pass.",
            probable_cause="Traffic volume may be too low, the URL is too new, or the target is not yet represented in public field datasets.",
            recommended_fix="Treat lab findings as the immediate action surface, then re-run once the target has enough real-user traffic.",
            acceptance_criteria="CrUX returns at least an origin-level record for the target.",
            dev_prompt="When no CrUX record exists, prioritize deterministic lab and delivery fixes first, then recheck field data later.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="Without field data, PerfAtlas cannot confirm whether lab regressions are already visible to real users.",
        ))
        return findings

    lcp = best.get("lcp_ms")
    inp = best.get("inp_ms")
    cls = best.get("cls")
    if lcp and lcp > LCP_GOOD:
        findings.append(_make_finding(
            finding_id="field-lcp-poor",
            title="Largest Contentful Paint is slow in field data",
            url=target_url,
            scope=best.get("scope") or "field",
            category="core_web_vitals",
            bucket="field_readiness",
            severity="high" if lcp >= LCP_POOR else "medium",
            confidence="Confirmed",
            expected_impact="High",
            evidence=[f"CrUX {best.get('scope')} LCP p75: {round(lcp)} ms"],
            diagnostic="Real-user LCP is above the good threshold.",
            probable_cause="Render-blocking resources, large hero media, slow server response, or late client rendering delay the largest contentful paint.",
            recommended_fix="Reduce LCP candidate size, cut render-blocking work, improve server delivery, and prioritize critical above-the-fold resources.",
            acceptance_criteria="CrUX LCP p75 moves below 2500 ms on the monitored scope.",
            dev_prompt="Prioritize the LCP element path end-to-end: server response, critical CSS, hero media size, font blocking, and client-side hydration delay.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="This is a real-user performance regression already visible in Chrome field data.",
        ))
    if inp and inp > INP_GOOD:
        findings.append(_make_finding(
            finding_id="field-inp-poor",
            title="Interaction to Next Paint is slow in field data",
            url=target_url,
            scope=best.get("scope") or "field",
            category="core_web_vitals",
            bucket="interactivity",
            severity="high" if inp >= INP_POOR else "medium",
            confidence="Confirmed",
            expected_impact="High",
            evidence=[f"CrUX {best.get('scope')} INP p75: {round(inp)} ms"],
            diagnostic="Real-user interactivity is slower than the good Core Web Vitals threshold.",
            probable_cause="Long main-thread tasks, heavy JavaScript, expensive event handlers, or slow third-party work may block interactions.",
            recommended_fix="Reduce long tasks, delay non-critical JavaScript, split hydration, and optimize expensive input handlers.",
            acceptance_criteria="CrUX INP p75 moves below 200 ms on the monitored scope.",
            dev_prompt="Treat INP as a main-thread budgeting problem: reduce long tasks, third-party work, and interaction handler cost.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="This confirms real users feel interaction delay, not just a lab-only bottleneck.",
        ))
    if cls is not None and cls > CLS_GOOD:
        findings.append(_make_finding(
            finding_id="field-cls-poor",
            title="Layout shifts are too high in field data",
            url=target_url,
            scope=best.get("scope") or "field",
            category="core_web_vitals",
            bucket="ux_resilience",
            severity="high" if cls >= CLS_POOR else "medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[f"CrUX {best.get('scope')} CLS p75: {round(cls, 3)}"],
            diagnostic="Real-user layout stability falls outside the good threshold.",
            probable_cause="Late-loading images, embeds, ads, fonts, or dynamic UI insertions shift the viewport during use.",
            recommended_fix="Reserve dimensions, stabilize late components, and prevent unbounded content injection above visible content.",
            acceptance_criteria="CrUX CLS p75 moves below 0.1 on the monitored scope.",
            dev_prompt="Stabilize layout by reserving space for media, embeds, ads, dynamic widgets, and font swaps.",
            validation_state="confirmed",
            evidence_mode="public_api",
            relationship_summary="This is a user-visible stability issue already confirmed in field data.",
        ))
    findings.extend(_field_trend_findings(best, target_url))
    return findings


def _lab_findings(lab_runs: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    representative = next((item for item in lab_runs if item.get("score") is not None), None)
    if not representative:
        findings.append(_make_finding(
            finding_id="lab-runtime-unavailable",
            title="No stable lab runtime was available for this pass",
            url=target_url,
            scope=target_url,
            category="lab_runtime",
            bucket="ux_resilience",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[str(item.get("note") or "") for item in lab_runs if item.get("note")][:3] or ["Local Lighthouse and PSI were unavailable or incomplete."],
            diagnostic="PerfAtlas could not secure a reliable lab execution path for this pass.",
            probable_cause="No browser runtime or Lighthouse executable was available, and remote PSI could not provide a usable result.",
            recommended_fix="Enable either a local Lighthouse runtime or a Google PSI/CrUX key path, then rerun the audit.",
            acceptance_criteria="At least one representative lab run completes with usable metrics.",
            dev_prompt="Restore a stable lab runtime for PerfAtlas so that startup and interactivity opportunities can be measured, not guessed.",
            validation_state="confirmed",
            evidence_mode="runtime",
            relationship_summary="Without lab data, startup and interactivity prioritization remains incomplete.",
        ))
        return findings

    lcp = representative.get("largest_contentful_paint_ms")
    tbt = representative.get("total_blocking_time_ms")
    total_bytes = representative.get("total_byte_weight")
    request_count = representative.get("request_count")
    server_response = representative.get("server_response_time_ms")
    opportunities = {item.get("id"): item for item in representative.get("opportunities") or [] if item.get("id")}

    if lcp and lcp > LCP_GOOD:
        findings.append(_make_finding(
            finding_id="lab-lcp-slow",
            title="Largest Contentful Paint is slow in lab runs",
            url=representative.get("url") or target_url,
            scope="lab",
            category="lab_performance",
            bucket="lab_startup",
            severity="high" if lcp >= LCP_POOR else "medium",
            confidence="Confirmed",
            expected_impact="High",
            evidence=[f"Representative lab LCP: {round(lcp)} ms", f"Runner: {representative.get('runner')}"],
            diagnostic="The representative lab run shows a slow largest contentful paint.",
            probable_cause="Critical path resources, slow server response, heavy hero media, or blocking client work delay first meaningful rendering.",
            recommended_fix="Optimize the LCP element path, reduce blocking CSS/JS, compress hero media, and shorten server response time.",
            acceptance_criteria="Representative lab LCP drops below 2500 ms.",
            dev_prompt="Use the lab diagnostics to trace the LCP element and remove blocking work before it can render.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="This explains poor startup and often correlates with field LCP regressions when traffic is sufficient.",
        ))
    if tbt and tbt > TBT_GOOD:
        findings.append(_make_finding(
            finding_id="lab-main-thread-heavy",
            title="Main-thread blocking is too high in lab runs",
            url=representative.get("url") or target_url,
            scope="lab",
            category="interactivity",
            bucket="interactivity",
            severity="high" if tbt >= TBT_POOR else "medium",
            confidence="Confirmed",
            expected_impact="High",
            evidence=[f"Representative lab TBT: {round(tbt)} ms"],
            diagnostic="The lab run shows too much main-thread blocking work.",
            probable_cause="Hydration, large script execution, third-party tags, or expensive synchronous work delay input responsiveness.",
            recommended_fix="Defer non-critical scripts, reduce hydration scope, split long tasks, and move expensive work off the critical path.",
            acceptance_criteria="Representative lab TBT drops below 200 ms.",
            dev_prompt="Treat TBT as the lab proxy for INP risk: reduce long tasks and interactive JS overhead.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Heavy main-thread work is a strong precursor of poor interaction quality.",
        ))
    if total_bytes and total_bytes > 1_600_000 or request_count and request_count > 120:
        findings.append(_make_finding(
            finding_id="lab-payload-bloat",
            title="Total payload and request pressure are high",
            url=representative.get("url") or target_url,
            scope="lab",
            category="payload",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                f"Total byte weight: {round((total_bytes or 0) / 1024)} KB",
                f"Request count: {request_count or 0}",
            ],
            diagnostic="The representative lab run loads a heavy payload and/or too many requests.",
            probable_cause="Over-shipped JavaScript, oversized media, too many third-party resources, or fragmented asset delivery can inflate the critical path.",
            recommended_fix="Reduce JS and media weight, consolidate assets, and remove low-value third-party or duplicate requests.",
            acceptance_criteria="Representative lab payload is materially reduced and request count drops to a sane level for the page type.",
            dev_prompt="Audit the network waterfall for oversized bundles, images, fonts, and low-value third-party requests.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Large payloads slow both startup and interactivity, especially on mobile connections.",
        ))
    if server_response and server_response > TTFB_GOOD:
        findings.append(_make_finding(
            finding_id="lab-server-response-slow",
            title="Server response time is slowing the critical path",
            url=representative.get("url") or target_url,
            scope="lab",
            category="delivery",
            bucket="network_delivery",
            severity="high" if server_response >= TTFB_POOR else "medium",
            confidence="Confirmed",
            expected_impact="High",
            evidence=[f"Representative lab server response time: {round(server_response)} ms"],
            diagnostic="The backend or edge response time materially delays rendering.",
            probable_cause="Slow origin work, cache misses, edge misconfiguration, or heavyweight server rendering may be delaying response start.",
            recommended_fix="Reduce origin latency, improve caching, and optimize server-side work on the critical route.",
            acceptance_criteria="Representative lab server response time drops below 800 ms.",
            dev_prompt="Trace origin versus edge response time and move cacheable work out of the request path.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Slow response start drags down both LCP and perceived snappiness.",
        ))
    if "render-blocking-resources" in opportunities:
        findings.append(_make_finding(
            finding_id="render-blocking-resources",
            title="Render-blocking resources still delay startup",
            url=representative.get("url") or target_url,
            scope="lab",
            category="startup",
            bucket="lab_startup",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                opportunities["render-blocking-resources"].get("display_value") or "Lighthouse flagged render-blocking resources."
            ],
            diagnostic="Critical rendering is delayed by blocking stylesheets or scripts.",
            probable_cause="CSS or sync scripts are still placed on the critical path before visible content can paint.",
            recommended_fix="Inline or split critical CSS, defer non-essential scripts, and preload only the resources that unlock first paint.",
            acceptance_criteria="Render-blocking opportunity no longer appears in the representative lab result.",
            dev_prompt="Reduce blocking CSS/JS on the first screen and prove the improvement with a new lab run.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Render-blocking work directly slows startup and often worsens LCP.",
        ))
    if "unused-javascript" in opportunities:
        findings.append(_make_finding(
            finding_id="unused-javascript-lab",
            title="Unused JavaScript still bloats the representative route",
            url=representative.get("url") or target_url,
            scope="lab",
            category="javascript",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[opportunities["unused-javascript"].get("display_value") or "Lighthouse flagged unused JavaScript."],
            diagnostic="The representative lab run still shows a meaningful amount of shipped JavaScript that is not needed for the current route.",
            probable_cause="Large shared bundles, over-hydration, route-agnostic imports, or third-party scripts may be shipping code that the page does not use immediately.",
            recommended_fix="Split bundles more aggressively, defer non-critical route code, and remove low-value third-party JavaScript from critical pages.",
            acceptance_criteria="The unused JavaScript opportunity materially shrinks or disappears on the representative route.",
            dev_prompt="Audit shipped JavaScript on the critical route and stop sending code that the initial experience does not need.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Unused JavaScript hurts both startup and interactivity because it still needs to be downloaded, parsed, and often executed.",
        ))
    if "unused-css-rules" in opportunities:
        findings.append(_make_finding(
            finding_id="unused-css-lab",
            title="Unused CSS still inflates the critical rendering path",
            url=representative.get("url") or target_url,
            scope="lab",
            category="css",
            bucket="lab_startup",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[opportunities["unused-css-rules"].get("display_value") or "Lighthouse flagged unused CSS."],
            diagnostic="The representative run still ships CSS that is not needed for the current route.",
            probable_cause="Global styles, dead design system branches, or route-agnostic CSS bundles may be inflating the first render path.",
            recommended_fix="Trim unused CSS, split route-level styling where practical, and keep only first-screen CSS on the startup path.",
            acceptance_criteria="The unused CSS opportunity is materially reduced on the representative route.",
            dev_prompt="Reduce CSS that the browser must download and evaluate before it can render the representative page cleanly.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Unused CSS is usually a secondary issue, but it still adds parse and transfer cost to the first render.",
        ))
    if "offscreen-images" in opportunities:
        findings.append(_make_finding(
            finding_id="offscreen-images-lab",
            title="Offscreen images still compete with critical rendering work",
            url=representative.get("url") or target_url,
            scope="lab",
            category="images",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[opportunities["offscreen-images"].get("display_value") or "Lighthouse flagged offscreen images."],
            diagnostic="The representative route still spends meaningful bandwidth on images that are not needed for the first screen.",
            probable_cause="Below-the-fold media may still load too early or be delivered in oversized variants.",
            recommended_fix="Lazy-load offscreen images, serve tighter responsive variants, and reserve eager loading only for media that matters to the first viewport.",
            acceptance_criteria="The offscreen images opportunity materially shrinks on the representative route.",
            dev_prompt="Keep the first-screen image path fast by moving non-critical media out of the startup waterfall.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Offscreen image pressure often wastes both bytes and decode time before the first useful view stabilizes.",
        ))
    if "third-party-summary" in opportunities:
        findings.append(_make_finding(
            finding_id="third-party-lab-summary",
            title="Third-party code still costs too much on the representative route",
            url=representative.get("url") or target_url,
            scope="lab",
            category="third_party",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[opportunities["third-party-summary"].get("display_value") or "Lighthouse flagged third-party pressure."],
            diagnostic="The representative lab run attributes a meaningful share of work or bytes to third-party resources.",
            probable_cause="Tags, embeds, analytics, remote fonts, or external widgets may be crowding the route’s startup and interaction budget.",
            recommended_fix="Delay or remove low-value third parties, and move the unavoidable ones off the critical path whenever possible.",
            acceptance_criteria="Third-party pressure on the representative route is materially reduced in follow-up lab runs.",
            dev_prompt="Treat each third-party dependency as a performance budget decision and prove that it earns its place on the page.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="Lab-level third-party pressure often shows up as both slower startup and heavier main-thread work.",
        ))
    if "uses-long-cache-ttl" in opportunities:
        findings.append(_make_finding(
            finding_id="lab-cache-ttl-opportunity",
            title="Representative route still exposes a cache TTL opportunity",
            url=representative.get("url") or target_url,
            scope="lab",
            category="caching",
            bucket="cache_transport",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[opportunities["uses-long-cache-ttl"].get("display_value") or "Lighthouse flagged cache TTL."],
            diagnostic="The lab run still sees assets that could advertise a stronger cache lifetime.",
            probable_cause="Versioned assets may not be receiving durable cache headers through the final serving path.",
            recommended_fix="Tighten cache policy for versioned assets and verify the final public response headers after deploy.",
            acceptance_criteria="The cache TTL opportunity disappears or materially shrinks for the representative route.",
            dev_prompt="Reconcile build output versioning with the real CDN and origin cache policy seen by browsers.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="This mostly affects repeat visits and re-renders after navigation, but it is still worth fixing on mature sites.",
        ))
    if "uses-text-compression" in opportunities:
        findings.append(_make_finding(
            finding_id="lab-text-compression-opportunity",
            title="Representative route still exposes a text-compression opportunity",
            url=representative.get("url") or target_url,
            scope="lab",
            category="compression",
            bucket="cache_transport",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[opportunities["uses-text-compression"].get("display_value") or "Lighthouse flagged text compression."],
            diagnostic="The representative lab run still sees compressible text assets that are too expensive on the wire.",
            probable_cause="Compression may be disabled, bypassed, or inconsistent between origin, proxy, and edge delivery.",
            recommended_fix="Enable consistent text compression on the final public delivery path and verify the real production headers after deploy.",
            acceptance_criteria="The text-compression opportunity disappears for the representative route.",
            dev_prompt="Fix compression on the actual production path, not just in the app server or local proxy layer.",
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary="This validates compression debt from the browser’s perspective rather than only from header sampling.",
        ))
    derived_opportunity_specs = (
        {
            "id": "uses-responsive-images",
            "finding_id": "responsive-images-lab",
            "title": "Responsive image sizing still leaves avoidable bytes on the wire",
            "category": "images",
            "bucket": "asset_efficiency",
            "severity": "low",
            "expected_impact": "Medium",
            "diagnostic": "The representative route still ships image candidates that are larger than necessary for the rendered viewport.",
            "probable_cause": "Responsive image markup, srcset coverage, or image transformation rules may not line up with the real client breakpoints.",
            "recommended_fix": "Tighten responsive image markup and transformation rules so first-screen and below-the-fold images ship variants closer to the real rendered size.",
            "acceptance_criteria": "The responsive images opportunity materially shrinks or disappears on the representative route.",
            "dev_prompt": "Audit how the route chooses image candidates and stop overserving image bytes to common viewport classes.",
            "relationship_summary": "Responsive image mismatches quietly waste transfer budget even when the image format itself is modern.",
        },
        {
            "id": "modern-image-formats",
            "finding_id": "modern-image-formats-lab",
            "title": "Modern image formats are still underused on the representative route",
            "category": "images",
            "bucket": "asset_efficiency",
            "severity": "low",
            "expected_impact": "Medium",
            "diagnostic": "The representative route still serves image formats that leave easy transfer savings on the table.",
            "probable_cause": "The media pipeline may still default to legacy formats or skip route-aware transcoding for important assets.",
            "recommended_fix": "Move eligible images toward modern formats where they preserve quality acceptably and verify the production pipeline serves them consistently.",
            "acceptance_criteria": "The modern image formats opportunity materially shrinks on the representative route.",
            "dev_prompt": "Review the image pipeline for format negotiation and stop serving heavier legacy encodings where a modern format is safe.",
            "relationship_summary": "Format efficiency is often a fast win on image-heavy pages once sizing and loading strategy are under control.",
        },
        {
            "id": "legacy-javascript",
            "finding_id": "legacy-javascript-lab",
            "title": "Legacy JavaScript is still shipped to modern browsers",
            "category": "javascript",
            "bucket": "asset_efficiency",
            "severity": "low",
            "expected_impact": "Low",
            "diagnostic": "The representative route still ships compatibility-heavy JavaScript that modern browsers do not need.",
            "probable_cause": "Bundler targets, polyfill defaults, or broad transpilation settings may be producing heavier modern-browser bundles than necessary.",
            "recommended_fix": "Tighten browser targets, remove unnecessary polyfills, and ship the lightest modern bundle the production support matrix allows.",
            "acceptance_criteria": "The legacy JavaScript opportunity materially shrinks or disappears in follow-up lab runs.",
            "dev_prompt": "Audit transpilation and polyfill policy so modern browsers stop paying for compatibility they do not need.",
            "relationship_summary": "Legacy JavaScript adds byte weight and parse cost without helping the majority of modern clients.",
        },
        {
            "id": "font-display",
            "finding_id": "font-display-lab",
            "title": "Font-display strategy still risks invisible text during startup",
            "category": "fonts",
            "bucket": "lab_startup",
            "severity": "low",
            "expected_impact": "Low",
            "diagnostic": "The representative route still exposes a font-loading pattern that can delay visible text.",
            "probable_cause": "Critical fonts may still rely on default loading behavior instead of an explicit display strategy aligned to the first screen.",
            "recommended_fix": "Set an intentional font-display strategy for critical fonts and verify it improves first-screen text visibility without introducing unacceptable layout shift.",
            "acceptance_criteria": "The font-display opportunity disappears or materially shrinks on representative lab runs.",
            "dev_prompt": "Treat font loading as part of the first-screen content strategy and avoid invisible text on critical views.",
            "relationship_summary": "Font-display fixes are usually incremental, but they help stabilize visible startup behavior.",
        },
    )
    for spec in derived_opportunity_specs:
        opportunity = opportunities.get(spec["id"])
        if not opportunity:
            continue
        findings.append(_make_finding(
            finding_id=spec["finding_id"],
            title=spec["title"],
            url=representative.get("url") or target_url,
            scope="lab",
            category=spec["category"],
            bucket=spec["bucket"],
            severity=spec["severity"],
            confidence="Confirmed",
            expected_impact=spec["expected_impact"],
            evidence=[opportunity.get("display_value") or f"Lighthouse flagged {spec['id']} on the representative route."],
            diagnostic=spec["diagnostic"],
            probable_cause=spec["probable_cause"],
            recommended_fix=spec["recommended_fix"],
            acceptance_criteria=spec["acceptance_criteria"],
            dev_prompt=spec["dev_prompt"],
            validation_state="confirmed",
            evidence_mode="lab",
            relationship_summary=spec["relationship_summary"],
        ))
    return findings


def _delivery_findings(pages: List[Dict[str, Any]], assets: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not pages:
        return findings
    doc_ttfbs = [page.get("ttfb_ms") for page in pages if page.get("ttfb_ms")]
    avg_ttfb = round(statistics.mean(doc_ttfbs), 1) if doc_ttfbs else 0.0
    redirected_pages = [
        page for page in pages
        if page.get("redirect_count", 0) or str(page.get("url") or "").rstrip("/") != str(page.get("final_url") or "").rstrip("/")
    ]
    heavy_html_pages = [page for page in pages if _safe_float(page.get("html_bytes"), 0.0) >= 120_000]
    uncompressed_documents = [page for page in pages if "document_not_compressed" in (page.get("notes") or [])]

    if redirected_pages:
        entry_redirected = any(
            str(page.get("url") or "").rstrip("/") == str(target_url or "").rstrip("/")
            and (page.get("redirect_count", 0) or str(page.get("final_url") or "").rstrip("/") != str(page.get("url") or "").rstrip("/"))
            for page in redirected_pages
        )
        findings.append(_make_finding(
            finding_id="document-redirect-hops",
            title="Redirect hops still delay the final HTML response",
            url=target_url,
            scope="delivery",
            category="redirects",
            bucket="network_delivery",
            severity="medium" if entry_redirected else "low",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                f"{len(redirected_pages)} sampled page(s) redirected before the final HTML response."
            ],
            diagnostic="At least one sampled document requires an extra hop before the browser can start parsing the final HTML.",
            probable_cause="Protocol, host, locale-root, or legacy path redirects may still sit in front of the canonical HTML response.",
            recommended_fix="Point internal links, canonicals, and marketing URLs directly to the final public URL whenever possible, and keep unavoidable redirects to a single hop.",
            acceptance_criteria="Critical entry routes resolve to the final HTML response without unnecessary redirects.",
            dev_prompt="Reduce redirect hops on important landing routes so the browser starts downloading the final HTML immediately.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Each redirect adds avoidable latency before rendering and can materially slow startup on mobile networks.",
        ))

    if avg_ttfb > TTFB_GOOD:
        findings.append(_make_finding(
            finding_id="document-ttfb-slow",
            title="Document response time is slow across sampled pages",
            url=target_url,
            scope="sample",
            category="delivery",
            bucket="network_delivery",
            severity="high" if avg_ttfb >= TTFB_POOR else "medium",
            confidence="Strong signal",
            expected_impact="High",
            evidence=[f"Average sampled document TTFB: {avg_ttfb} ms"],
            diagnostic="Multiple sampled pages show slow response start before rendering can begin.",
            probable_cause="Origin latency, uncached server rendering, edge misses, or heavy middleware may be slowing the first byte.",
            recommended_fix="Profile origin latency, cache hot paths, and ensure the critical landing routes are edge-friendly when possible.",
            acceptance_criteria="Average sampled document TTFB drops below 800 ms.",
            dev_prompt="Investigate why the HTML document itself starts slowly and fix the highest-latency part of the request path.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="This is a structural delivery issue that drags down every later rendering step.",
        ))
    if heavy_html_pages:
        avg_html_kb = round(
            statistics.mean((_safe_float(page.get("html_bytes"), 0.0) / 1024.0) for page in heavy_html_pages),
            1,
        )
        findings.append(_make_finding(
            finding_id="html-document-heavy",
            title="HTML document payload is heavy on sampled pages",
            url=target_url,
            scope="delivery",
            category="html_payload",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Strong signal",
            expected_impact="Medium",
            evidence=[
                f"{len(heavy_html_pages)} sampled page(s) exceeded roughly 120 KB of HTML.",
                f"Average heavy HTML size: {avg_html_kb} KB.",
            ],
            diagnostic="The initial HTML response is carrying a large amount of markup and inline payload before subresources even start.",
            probable_cause="Large SSR output, repeated inline data, oversized inlined scripts/styles, or excessive template payload can inflate the document.",
            recommended_fix="Trim server-rendered markup, move bulky inline data out of HTML when safe, and keep only critical inline resources in the document shell.",
            acceptance_criteria="Important templates keep HTML payload lean enough that the document itself is no longer a major transfer cost.",
            dev_prompt="Audit the raw HTML response for heavy inline state, duplicated markup, and oversized in-document CSS or script payloads.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Heavy HTML slows first-byte-to-first-paint progress even before the rest of the asset graph loads.",
        ))
    if uncompressed_documents:
        findings.append(_make_finding(
            finding_id="document-compression-missing",
            title="HTML documents are not consistently compressed on sampled pages",
            url=target_url,
            scope="delivery",
            category="compression",
            bucket="cache_transport",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                f"{len(uncompressed_documents)} sampled HTML response(s) larger than 20 KB were served without a br/gzip signal."
            ],
            diagnostic="Some sampled HTML documents are still being transferred without an obvious text compression signal.",
            probable_cause="Compression may be disabled or bypassed at the origin, proxy, or edge for HTML documents.",
            recommended_fix="Enable compression consistently for production HTML responses and verify the final public path rather than only the app server.",
            acceptance_criteria="Sampled HTML documents return Brotli or gzip when expected on production.",
            dev_prompt="Verify compression on the real public HTML responses and fix the serving layer where document compression is being lost.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Uncompressed HTML wastes bandwidth on the very first response the browser needs before it can render anything useful.",
        ))
    same_host_assets = [item for item in assets if item.get("same_host")]
    if same_host_assets:
        uncompressed = [
            item for item in same_host_assets
            if item.get("status_code", 0) < 400
            and item.get("content_length", 0) > 12000
            and str(item.get("content_encoding") or "").lower() not in {"br", "gzip"}
        ]
        if uncompressed:
            findings.append(_make_finding(
                finding_id="compression-missing",
                title="Compression is missing on sampled first-party assets",
                url=target_url,
                scope="delivery",
                category="compression",
                bucket="cache_transport",
                severity="medium",
                confidence="Confirmed",
                expected_impact="Medium",
                evidence=[f"{len(uncompressed)} sampled asset(s) larger than 12 KB were served without br/gzip."],
                diagnostic="Sampled first-party assets are still being served without a text compression signal.",
                probable_cause="Compression may be disabled at the edge, proxy, or origin for some asset types.",
                recommended_fix="Enable Brotli or gzip consistently for HTML, CSS, JS, and other text assets on the production path.",
                acceptance_criteria="Sampled first-party text assets return a compression signal where expected.",
                dev_prompt="Fix compression at the actual serving layer, not just in local dev, then verify on production responses.",
                validation_state="confirmed",
                evidence_mode="measured",
                relationship_summary="Missing compression inflates transfer size and slows startup, especially on slower networks.",
            ))
        weak_cache = [
            item for item in same_host_assets
            if item.get("status_code", 0) < 400
            and item.get("kind") in {"script", "stylesheet", "font", "image"}
            and not _is_strong_asset_cache(item)
        ]
        if weak_cache:
            findings.append(_make_finding(
                finding_id="cache-policy-weak",
                title="Long-lived caching is weak on sampled first-party assets",
                url=target_url,
                scope="delivery",
                category="caching",
                bucket="cache_transport",
                severity="medium",
                confidence="Confirmed",
                expected_impact="Medium",
                evidence=[f"{len(weak_cache)} sampled asset(s) lacked a strong cache policy signal."],
                diagnostic="Several sampled first-party assets are not advertising a durable cache policy.",
                probable_cause="Build outputs, CDN defaults, or proxy rules may not be setting long-lived immutable caching on versioned assets.",
                recommended_fix="Apply strong cache headers on versioned static assets and keep shorter policies only where the payload is intentionally mutable.",
                acceptance_criteria="Versioned first-party static assets advertise strong cache headers in production.",
                dev_prompt="Differentiate mutable HTML from versioned static assets and give the latter long-lived immutable cache headers.",
                validation_state="confirmed",
                evidence_mode="measured",
                relationship_summary="Weak caching forces unnecessary repeat transfers and slows return visits.",
            ))
        explicitly_uncacheable = [
            item for item in same_host_assets
            if item.get("status_code", 0) < 400
            and item.get("kind") in {"script", "stylesheet", "font", "image"}
            and _is_explicitly_uncacheable(item)
        ]
        if explicitly_uncacheable:
            findings.append(_make_finding(
                finding_id="static-assets-uncacheable",
                title="Some sampled static assets are explicitly marked uncacheable",
                url=target_url,
                scope="delivery",
                category="caching",
                bucket="cache_transport",
                severity="medium",
                confidence="Confirmed",
                expected_impact="Medium",
                evidence=[f"{len(explicitly_uncacheable)} sampled static asset(s) returned no-store, private, or no-cache directives."],
                diagnostic="At least some first-party static assets are being served with cache directives that prevent efficient reuse.",
                probable_cause="A generic CDN or origin cache rule may be treating static assets like mutable HTML responses.",
                recommended_fix="Separate HTML and versioned static asset policies so immutable assets are cacheable while documents remain intentionally fresh.",
                acceptance_criteria="Versioned static assets stop returning explicitly uncacheable directives on production.",
                dev_prompt="Audit the final caching layer for static assets and stop inheriting document-style cache policies on JS, CSS, fonts, and images.",
                validation_state="confirmed",
                evidence_mode="measured",
                relationship_summary="Explicitly uncacheable static assets force avoidable re-downloads even when the files are versioned and safe to reuse.",
            ))
    return findings


def _resource_findings(pages: List[Dict[str, Any]], target_url: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not pages:
        return findings
    blocking_markup = [
        page for page in pages
        if "multiple_stylesheets" in (page.get("render_blocking_hints") or [])
        or "blocking_scripts" in (page.get("render_blocking_hints") or [])
    ]
    if len(blocking_markup) >= max(1, math.ceil(len(pages) * 0.5)):
        findings.append(_make_finding(
            finding_id="blocking-markup-structure",
            title="Synchronous scripts and stylesheet fan-out still pressure startup",
            url=target_url,
            scope="sample",
            category="critical_path",
            bucket="lab_startup",
            severity="medium",
            confidence="Strong signal",
            expected_impact="Medium",
            evidence=[
                f"{len(blocking_markup)} sampled page(s) exposed blocking script or multi-stylesheet hints in the initial HTML."
            ],
            diagnostic="The raw HTML structure still suggests avoidable startup pressure before any deeper lab tooling runs.",
            probable_cause="Multiple blocking stylesheets, synchronous scripts, or a crowded head section may be extending the critical rendering path.",
            recommended_fix="Reduce head fan-out, defer non-critical scripts, and keep only the CSS required for the first screen on the startup path.",
            acceptance_criteria="Critical templates stop exposing obvious blocking script and stylesheet fan-out in the initial HTML shell.",
            dev_prompt="Treat the initial HTML head as a strict budget and remove anything that does not directly unlock first-screen rendering.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Even before lab runs, the document structure suggests avoidable startup work on the critical path.",
        ))
    high_third_party = [page for page in pages if page.get("third_party_host_count", 0) >= 6]
    if high_third_party:
        findings.append(_make_finding(
            finding_id="third-party-pressure",
            title="Third-party pressure is high on sampled pages",
            url=target_url,
            scope="sample",
            category="third_party",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Strong signal",
            expected_impact="Medium",
            evidence=[f"{len(high_third_party)} sampled page(s) referenced six or more third-party hosts."],
            diagnostic="The site depends on a large external surface for scripts, embeds, fonts, or trackers.",
            probable_cause="Marketing, analytics, widgets, or remote asset dependencies may be crowding the critical path.",
            recommended_fix="Reduce low-value third parties, delay non-critical embeds, and audit each external dependency for measurable value.",
            acceptance_criteria="Critical pages materially reduce third-party hosts and requests.",
            dev_prompt="Audit every third-party dependency on the critical route and keep only the ones with clear business value.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Third-party pressure increases startup cost, main-thread work, and operational fragility.",
        ))
    image_heavy = [page for page in pages if page.get("image_count", 0) >= 6 and page.get("lazy_image_count", 0) < max(1, math.floor(page.get("image_count", 0) * 0.5))]
    if image_heavy:
        findings.append(_make_finding(
            finding_id="image-loading-inefficient",
            title="Image loading strategy looks inefficient on sampled pages",
            url=target_url,
            scope="sample",
            category="images",
            bucket="asset_efficiency",
            severity="medium",
            confidence="Strong signal",
            expected_impact="Medium",
            evidence=[f"{len(image_heavy)} sampled page(s) load many images with limited lazy-loading signals."],
            diagnostic="Pages with a meaningful image surface do not consistently signal deferred loading for below-the-fold content.",
            probable_cause="Non-critical images may still load eagerly or be delivered without responsive/lazy-loading hints.",
            recommended_fix="Lazy-load non-critical images, serve responsive sizes, and prioritize only the images needed for the first screen.",
            acceptance_criteria="Critical pages lazy-load below-the-fold images and avoid overserving image bytes.",
            dev_prompt="Differentiate the LCP image from the rest, and make the non-critical image pipeline cheaper and lazier.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Inefficient image loading inflates both payload and rendering work.",
        ))
    hints_missing = [page for page in pages if "font_preconnect_missing" in (page.get("notes") or [])]
    if hints_missing:
        findings.append(_make_finding(
            finding_id="font-resource-hints-missing",
            title="Font resource hints look incomplete on sampled pages",
            url=target_url,
            scope="sample",
            category="resource_hints",
            bucket="lab_startup",
            severity="low",
            confidence="Estimated",
            expected_impact="Low",
            evidence=[f"{len(hints_missing)} sampled page(s) reference remote fonts without a preconnect hint."],
            diagnostic="Remote font loading appears to miss at least one obvious connection hint.",
            probable_cause="Font loading may rely on defaults rather than an explicitly optimized critical path.",
            recommended_fix="Add only the resource hints that clearly improve the first screen, especially for critical remote font origins.",
            acceptance_criteria="Critical font origins expose only the hints that improve startup without hint spam.",
            dev_prompt="Use resource hints sparingly and only where they shorten the first-screen critical path.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="Hints alone will not fix a slow page, but missing critical ones can leave easy wins on the table.",
        ))
    cross_origin_hint_gap = [
        page for page in pages
        if page.get("third_party_host_count", 0) >= 4 and _safe_int(page.get("preconnect_count"), 0) <= 0
    ]
    if cross_origin_hint_gap:
        findings.append(_make_finding(
            finding_id="cross-origin-hints-thin",
            title="Cross-origin connection hints look thin on third-party-heavy pages",
            url=target_url,
            scope="sample",
            category="resource_hints",
            bucket="lab_startup",
            severity="low",
            confidence="Strong signal",
            expected_impact="Low",
            evidence=[f"{len(cross_origin_hint_gap)} sampled page(s) referenced several third-party hosts without any preconnect hints."],
            diagnostic="Pages that depend on multiple third-party origins do not appear to advertise even a minimal connection warm-up strategy.",
            probable_cause="Remote fonts, analytics, embeds, or tag-manager dependencies may have accumulated without a first-screen connection-hint review.",
            recommended_fix="Add only the preconnect hints that clearly shorten the startup path for unavoidable third-party origins, and avoid spraying hints everywhere.",
            acceptance_criteria="Critical templates warm only the few cross-origin connections that materially matter to first-screen startup.",
            dev_prompt="Treat connection hints as part of the critical path budget: add only the high-value cross-origin preconnects that measurably help startup.",
            validation_state="confirmed",
            evidence_mode="measured",
            relationship_summary="When third-party origins are unavoidable, a thin hint strategy can leave easy startup latency on the table.",
        ))
    return findings


def _owner_context_findings(
    owner_context: Dict[str, Any],
    pages: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    target_url: str,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    integrations = [
        item for item in (owner_context.get("integrations") or [])
        if isinstance(item, dict)
    ]
    startup_pressure = any(
        "multiple_stylesheets" in (page.get("render_blocking_hints") or [])
        or "blocking_scripts" in (page.get("render_blocking_hints") or [])
        for page in pages
    )
    third_party_pressure = any(page.get("third_party_host_count", 0) >= 6 for page in pages)
    image_pressure = any(
        page.get("image_count", 0) >= 6
        and page.get("lazy_image_count", 0) < max(1, math.floor(page.get("image_count", 0) * 0.5))
        for page in pages
    )
    for owner_id, owner_name in (("vercel", "Vercel"), ("netlify", "Netlify")):
        connector = next((item for item in integrations if item.get("id") == owner_id), None)
        if not connector or str(connector.get("status") or "").lower() not in {"ready", "configured"}:
            continue
        context = connector.get("context") or {}
        latest_deployment = context.get("latest_deployment") or {}
        recent_non_ready = _safe_int(context.get("recent_non_ready_count"), 0)
        latest_state = str(latest_deployment.get("state") or "").strip().lower()
        latest_target = str(latest_deployment.get("target") or latest_deployment.get("context") or "").strip().lower()
        if recent_non_ready >= 2 or (latest_state and latest_state not in {"ready", "cached", "current", "old", "processed", "published"} and latest_target in {"production", "prod"}):
            findings.append(_make_finding(
                finding_id=f"{owner_id}-deploy-health-noisy",
                title=f"{owner_name} deployment health looks noisy for this target",
                url=target_url,
                scope="owner_context",
                category="owner_delivery",
                bucket="ux_resilience",
                severity="medium",
                confidence="Confirmed",
                expected_impact="Medium",
                evidence=[
                    f"{owner_name} owner context reported {recent_non_ready} recent non-ready deployment(s)."
                ],
                diagnostic="Recent owner-side deployment history suggests release health may be unstable for the matched target.",
                probable_cause="Recent failed, errored, or cancelled deployments may be slowing rollout, rollback, or fix velocity for performance work.",
                recommended_fix="Stabilize the production deploy path first so performance fixes can ship, validate, and stick without rollout noise.",
                acceptance_criteria="Recent deployment history no longer shows a noisy pattern of non-ready releases for the matched production target.",
                dev_prompt="Treat unstable deploy health as a delivery risk multiplier: clean up the release path before relying on frequent perf iterations.",
                validation_state="confirmed",
                evidence_mode="owner_context",
                relationship_summary="Performance programs slow down when the deployment path itself is unstable or difficult to trust.",
            ))
        if owner_id == "netlify":
            snippet_count = _safe_int(context.get("snippet_count"), 0)
            snippet_script_count = _safe_int(context.get("snippet_script_count"), 0)
            snippet_head_count = _safe_int(context.get("snippet_head_count"), 0)
            if snippet_count and (third_party_pressure or startup_pressure):
                evidence = [f"Netlify owner context reports {snippet_count} site snippet(s), including {snippet_script_count} script-bearing snippet(s)."]
                if snippet_head_count:
                    evidence.append(f"{snippet_head_count} snippet(s) inject into the document head.")
                if third_party_pressure:
                    evidence.append("Sampled pages also reference a heavy third-party host surface.")
                if startup_pressure:
                    evidence.append("Sampled pages still expose blocking startup hints in the initial HTML.")
                findings.append(_make_finding(
                    finding_id="netlify-snippet-pressure",
                    title="Netlify snippet injection may be contributing to third-party pressure",
                    url=target_url,
                    scope="owner_context",
                    category="owner_delivery",
                    bucket="asset_efficiency",
                    severity="medium" if snippet_script_count or snippet_head_count else "low",
                    confidence="Confirmed",
                    expected_impact="Medium" if third_party_pressure else "Low",
                    evidence=evidence,
                    diagnostic="Owner-side snippet injection is active on the matched Netlify site while the sampled pages already show signs of third-party or startup pressure.",
                    probable_cause="Analytics, marketing, or verification tags may have been added through Netlify snippets instead of the app bundle, making them easier to miss during code review and performance budgeting.",
                    recommended_fix="Audit each injected Netlify snippet, remove low-value ones, and move unavoidable tags off the critical path whenever possible.",
                    acceptance_criteria="Netlify snippets are reduced to the truly necessary set and no longer add avoidable startup or third-party pressure.",
                    dev_prompt="Treat Netlify snippets as first-class production code: inventory them, justify them, and keep head injection extremely strict on critical pages.",
                    validation_state="confirmed",
                    evidence_mode="owner_context",
                    relationship_summary="Owner-side snippet injection can quietly grow the third-party surface even when application code looks clean.",
                ))
    cloudflare = next((item for item in integrations if item.get("id") == "cloudflare"), None)
    if not cloudflare or str(cloudflare.get("status") or "").lower() not in {"ready", "configured"}:
        return findings

    context = cloudflare.get("context") or {}
    platform_signals = context.get("platform_signals") or {}
    brotli_value = str(platform_signals.get("brotli") or "").strip().lower()
    http3_value = str(platform_signals.get("http3") or "").strip().lower()
    early_hints_value = str(platform_signals.get("early_hints") or "").strip().lower()
    polish_value = str(platform_signals.get("polish") or "").strip().lower()
    image_resizing_value = str(platform_signals.get("image_resizing") or "").strip().lower()
    compression_pressure = any("document_not_compressed" in (page.get("notes") or []) for page in pages) or any(
        item.get("same_host")
        and item.get("status_code", 0) < 400
        and item.get("content_length", 0) > 12000
        and str(item.get("content_encoding") or "").lower() not in {"br", "gzip"}
        for item in assets
    )
    if brotli_value == "off" and compression_pressure:
        findings.append(_make_finding(
            finding_id="cloudflare-brotli-disabled",
            title="Cloudflare edge Brotli is disabled for this zone",
            url=target_url,
            scope="owner_context",
            category="owner_delivery",
            bucket="cache_transport",
            severity="medium",
            confidence="Confirmed",
            expected_impact="Medium",
            evidence=[
                "Cloudflare owner context reports the Brotli zone setting as off.",
                "Measured responses in this audit also showed missing compression on sampled HTML or first-party assets.",
            ],
            diagnostic="The Cloudflare zone itself is not advertising Brotli, which makes the measured compression gap actionable at the edge configuration layer.",
            probable_cause="Edge compression may be disabled or overridden in the current Cloudflare zone configuration.",
            recommended_fix="Enable Brotli at the Cloudflare edge and verify the final production responses still return compressed HTML, CSS, and JavaScript.",
            acceptance_criteria="Cloudflare reports Brotli on for the matched zone and sampled production responses return compression where expected.",
            dev_prompt="Fix the compression gap where it actually lives: verify the Cloudflare zone setting and then confirm the public responses are compressed end to end.",
            validation_state="confirmed",
            evidence_mode="owner_context",
            relationship_summary="This converts a generic compression issue into a specific owner-side platform action.",
        ))
    if http3_value == "off":
        findings.append(_make_finding(
            finding_id="cloudflare-http3-disabled",
            title="Cloudflare HTTP/3 is disabled for this zone",
            url=target_url,
            scope="owner_context",
            category="owner_delivery",
            bucket="network_delivery",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[
                "Cloudflare owner context reports the HTTP/3 zone setting as off."
            ],
            diagnostic="The matched Cloudflare zone is not currently offering HTTP/3 at the edge.",
            probable_cause="The zone transport setting may not have been enabled after onboarding or was turned off intentionally.",
            recommended_fix="Review whether HTTP/3 should be enabled for the production zone and validate the impact on real traffic after rollout.",
            acceptance_criteria="If compatible with the site’s transport policy, the zone exposes HTTP/3 on production.",
            dev_prompt="Treat HTTP/3 as a measured transport opportunity: enable it only after verifying the zone and SSL prerequisites are already in place.",
            validation_state="confirmed",
            evidence_mode="owner_context",
            relationship_summary="This is an owner-side transport opportunity that can improve connection setup without changing application code.",
        ))
    if early_hints_value == "off" and startup_pressure:
        findings.append(_make_finding(
            finding_id="cloudflare-early-hints-disabled",
            title="Cloudflare Early Hints is disabled while startup pressure remains high",
            url=target_url,
            scope="owner_context",
            category="owner_delivery",
            bucket="lab_startup",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[
                "Cloudflare owner context reports Early Hints as off.",
                "Sampled pages still expose blocking startup hints in the initial HTML.",
            ],
            diagnostic="The matched Cloudflare zone is not currently using an owner-side startup optimization that may help deliver critical Link hints sooner.",
            probable_cause="The zone setting may simply not have been enabled or evaluated yet for the production target.",
            recommended_fix="Review whether Early Hints is appropriate for the production zone, then validate the startup path after enabling it.",
            acceptance_criteria="If suitable for the stack, Early Hints is enabled and revalidated against the startup path.",
            dev_prompt="Treat Early Hints as a secondary edge optimization only after the first-screen resource graph is already intentional and clean.",
            validation_state="confirmed",
            evidence_mode="owner_context",
            relationship_summary="This is not a substitute for fixing the critical path, but it can amplify good preload discipline at the edge.",
        ))
    if polish_value == "off" and image_pressure:
        findings.append(_make_finding(
            finding_id="cloudflare-polish-disabled",
            title="Cloudflare Polish is disabled while image-heavy pages remain expensive",
            url=target_url,
            scope="owner_context",
            category="owner_delivery",
            bucket="asset_efficiency",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[
                "Cloudflare owner context reports Polish as off.",
                "Sampled pages still expose a large image surface with limited lazy-loading signals.",
            ],
            diagnostic="The matched Cloudflare zone is not using an owner-side image optimization setting while sampled pages still suggest image pressure.",
            probable_cause="Image optimization may be handled elsewhere, or the Cloudflare image stack may simply not have been enabled for this zone.",
            recommended_fix="Review whether Cloudflare Polish is appropriate for the production zone, then validate image quality and payload impact after enabling it.",
            acceptance_criteria="If it fits the image pipeline, the zone enables Polish and follow-up measurements confirm leaner image delivery without regressions.",
            dev_prompt="Treat owner-side image optimization as an amplifier, not a substitute: first fix oversized image behavior, then decide whether the edge should optimize the remainder.",
            validation_state="confirmed",
            evidence_mode="owner_context",
            relationship_summary="This is a concrete owner-side lever for image-heavy sites, but it only helps when the image pipeline is already intentional.",
        ))
    if image_resizing_value == "off" and image_pressure:
        findings.append(_make_finding(
            finding_id="cloudflare-image-resizing-disabled",
            title="Cloudflare image resizing is disabled while image-heavy pages remain expensive",
            url=target_url,
            scope="owner_context",
            category="owner_delivery",
            bucket="asset_efficiency",
            severity="low",
            confidence="Confirmed",
            expected_impact="Low",
            evidence=[
                "Cloudflare owner context reports image resizing as off.",
                "Sampled pages still expose an image-heavy first-load surface.",
            ],
            diagnostic="The matched Cloudflare zone is not currently using an owner-side image transformation path while the sampled pages still carry meaningful image pressure.",
            probable_cause="Responsive image handling may rely entirely on the application layer, or Cloudflare image resizing may not have been evaluated for this zone.",
            recommended_fix="Review whether Cloudflare image resizing belongs in the production image pipeline and validate the resulting responsive delivery strategy end to end.",
            acceptance_criteria="If adopted, image resizing is enabled intentionally and the production markup plus edge pipeline deliver tighter variants to real clients.",
            dev_prompt="Only enable owner-side image resizing if it fits the real media pipeline and can be validated against the responsive markup strategy already in use.",
            validation_state="confirmed",
            evidence_mode="owner_context",
            relationship_summary="This is an owner-side image delivery opportunity, not a replacement for fixing oversized or eagerly loaded media in the app.",
        ))
    return findings


def _build_remediation_items(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "finding_id": item.get("id"),
            "url": item.get("url"),
            "category": item.get("category"),
            "severity": item.get("severity"),
            "confidence": item.get("confidence"),
            "expected_impact": item.get("expected_impact"),
            "diagnostic": item.get("diagnostic"),
            "probable_cause": item.get("probable_cause"),
            "recommended_fix": item.get("recommended_fix"),
            "acceptance_criteria": item.get("acceptance_criteria"),
            "dev_prompt": item.get("dev_prompt"),
        }
        for item in findings
    ]


def _profile_settings(max_pages: int) -> Dict[str, Any]:
    if max_pages <= 3:
        return {"label": "basic", "sample_pages": 3, "lab_pages": 1, "lab_runs": 1}
    if max_pages <= 8:
        return {"label": "elevated", "sample_pages": min(max_pages, 8), "lab_pages": 3, "lab_runs": 3}
    return {"label": "ultra", "sample_pages": min(max_pages, 20), "lab_pages": 5, "lab_runs": 5}


def _lab_probe_plan(pages: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not pages:
        return []
    label = str(profile.get("label") or "basic")
    page_count = len(pages)
    if label == "ultra":
        max_pages = 2 if page_count <= 8 else min(5, int(profile.get("lab_pages") or 5))
        primary_runs = 2 if page_count <= 8 else 3
    elif label == "elevated":
        max_pages = 2
        primary_runs = 2
    else:
        max_pages = 1
        primary_runs = 1

    selected: List[Dict[str, Any]] = []
    seen_templates = set()
    for page in pages:
        url = page.get("final_url") or page.get("url")
        if not url:
            continue
        template = str(page.get("template_signature") or url)
        if template in seen_templates and len(selected) >= 1:
            continue
        seen_templates.add(template)
        selected.append({"url": url, "runs": primary_runs if not selected else 1})
        if len(selected) >= max_pages:
            break

    if not selected:
        url = pages[0].get("final_url") or pages[0].get("url")
        if url:
            selected.append({"url": url, "runs": primary_runs})
    return selected


def run_site_audit(
    target_url: str,
    *,
    mode: str = "public",
    max_pages: int = 8,
    progress_callback: ProgressCallback = None,
    cancel_check: CancelCheck = None,
) -> Dict[str, Any]:
    normalized = normalize_public_target(target_url, mode)
    entry_url = normalized["normalized_url"]
    started_at = _utc_now()
    profile = _profile_settings(max_pages)
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    provider_statuses = get_perfatlas_provider_status(entry_url, mode=mode)
    runtime_status = _lighthouse_runtime_status()

    _emit(progress_callback, "crawl", 8, "Preparing performance target")
    queue: List[Tuple[str, int]] = [(entry_url, 0)]
    visited: set[str] = set()
    discovered: List[str] = []
    pages: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    page_html: Dict[str, str] = {}
    host = normalized["host"].split(":")[0]

    while queue and len(pages) < profile["sample_pages"]:
        if _cancelled(cancel_check):
            break
        current_url, depth = queue.pop(0)
        if current_url in visited or _is_system_url(current_url):
            continue
        visited.add(current_url)
        discovered.append(current_url)
        try:
            _emit(progress_callback, "crawl", 12 + (len(pages) * 18 / max(1, profile["sample_pages"])), f"Crawling {current_url}")
            snapshot, page_assets, html = _collect_page_snapshot(session, current_url, depth)
            if "html" not in str(snapshot.get("content_type") or "").lower():
                continue
            pages.append(snapshot)
            page_html[snapshot["final_url"]] = html
            assets.extend(page_assets[:18])
            next_depth = depth + 1
            if next_depth <= 2:
                for link in snapshot.get("internal_links") or []:
                    if link not in visited and len(queue) < profile["sample_pages"] * 6:
                        queue.append((link, next_depth))
        except Exception:
            continue

    if not pages:
        raise RuntimeError("PerfAtlas could not fetch a usable HTML page from the target.")

    _emit(progress_callback, "extract", 38, "Collecting delivery and resource signals")
    asset_samples: List[Dict[str, Any]] = []
    seen_assets = set()
    for asset in assets:
        asset_url = str(asset.get("url") or "").strip()
        if not asset_url or asset_url in seen_assets or len(asset_samples) >= 12:
            continue
        seen_assets.add(asset_url)
        sample = _fetch_asset_sample(session, asset, host)
        if sample:
            asset_samples.append(sample)

    _emit(progress_callback, "field", 52, "Collecting field performance signals")
    field_data = _build_field_snapshots(entry_url)

    _emit(progress_callback, "lab", 66, "Running lab performance probes")
    lab_plan = _lab_probe_plan(pages, profile)
    lab_runs: List[Dict[str, Any]] = []
    for item in lab_plan:
        if _cancelled(cancel_check):
            break
        url = str(item.get("url") or "")
        runs = max(1, int(item.get("runs") or 1))
        if runtime_status.get("available"):
            lab_runs.append(_run_local_lighthouse(url, "mobile", runs, runtime_status))
        else:
            remote_lab = _run_pagespeed_insights(url, "mobile")
            if remote_lab.get("score") is None and get_webpagetest_api_key():
                remote_lab = _run_webpagetest(url, "mobile")
            lab_runs.append(remote_lab)

    _emit(progress_callback, "owner", 78, "Collecting owner context")
    owner_context = build_owner_context(entry_url, mode=mode)
    template_clusters = _aggregate_template_clusters(pages)
    intelligence = build_performance_intelligence(
        target_url=entry_url,
        profile=profile,
        pages=pages,
        assets=asset_samples,
        lab_runs=lab_runs,
        field_data=field_data,
        template_clusters=template_clusters,
        provider_statuses=provider_statuses,
        owner_context=owner_context,
    )

    _emit(progress_callback, "score", 88, "Scoring performance findings")
    findings: List[Dict[str, Any]] = []
    findings.extend(_field_findings(field_data, entry_url))
    findings.extend(_lab_findings(lab_runs, entry_url))
    findings.extend(_delivery_findings(pages, asset_samples, entry_url))
    findings.extend(_resource_findings(pages, entry_url))
    findings.extend(_owner_context_findings(owner_context, pages, asset_samples, entry_url))
    for spec in intelligence_finding_specs(intelligence):
        findings.append(_make_finding(url=entry_url, **spec))
    findings.sort(key=lambda item: ({"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(str(item.get("severity")).lower(), 0)), reverse=True)
    lab_ready = any(item.get("score") is not None for item in lab_runs)
    field_ready = bool(field_data)
    representative_lab = next((item for item in lab_runs if item.get("score") is not None), {})
    scores = score_findings(
        findings,
        pages_analyzed=len(pages),
        page_budget=profile["sample_pages"],
        lab_score=representative_lab.get("score"),
        lab_available=lab_ready,
        field_available=field_ready,
    )
    remediation_items = _build_remediation_items(findings)
    platform = _detect_platform(page_html.get(pages[0].get("final_url") or "", ""), pages[0].get("headers") or {})

    blocking_risk = scores.get("blocking_risk") or {}
    summary = {
        "target": entry_url,
        "mode": mode,
        "platform": platform,
        "rendering": "hybrid",
        "global_score": scores.get("global_score"),
        "pages_crawled": len(pages),
        "pages_discovered": len(set(discovered)),
        "page_budget": profile["sample_pages"],
        "lab_pages_analyzed": len(lab_runs),
        "runtime_runner": runtime_status.get("runner") or "unavailable",
        "runtime_note": runtime_status.get("note") or "",
        "lab_probe_plan": lab_plan,
        "field_data_available": field_ready,
        "lab_data_available": lab_ready,
        "top_risk": findings[0]["title"] if findings else "",
        "blocking_risk": blocking_risk,
        "score_guardrails": scores.get("guardrails") or [],
        "owner_integrations_count": len(owner_context.get("integrations") or []),
        "performance_budget": intelligence.get("summary") or {},
        "top_performance_action": (intelligence.get("summary") or {}).get("top_action") or "",
        "diagnostic_confidence": (intelligence.get("summary") or {}).get("diagnostic_confidence") or "limited",
    }
    snapshot = {
        "started_at": started_at,
        "finished_at": _utc_now(),
        "entry_url": entry_url,
        "pages": pages,
        "discovered_urls": sorted(set(discovered)),
        "field_data": field_data,
        "lab_runs": lab_runs,
        "asset_samples": asset_samples,
        "template_clusters": template_clusters,
        "performance_intelligence": intelligence,
        "provider_statuses": provider_statuses,
        "runtime": runtime_status,
        "lab_probe_plan": lab_plan,
    }
    return {
        "summary": summary,
        "snapshot": snapshot,
        "findings": findings,
        "scores": scores["categories"],
        "remediation_items": remediation_items,
        "owner_context": owner_context,
    }
