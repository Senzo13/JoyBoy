"""Higher-level deterministic performance intelligence for PerfAtlas.

This module turns raw crawl, asset, lab, and field snapshots into an
implementation-oriented packet that can be rendered in the UI and exported for
AI handoff without inventing measurements.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


PERFORMANCE_BUDGETS: Dict[str, Dict[str, Any]] = {
    "page_weight": {"label": "Total page weight", "limit": 1_600_000, "unit": "bytes"},
    "requests": {"label": "Request count", "limit": 80, "unit": "count"},
    "javascript": {"label": "Sampled JavaScript", "limit": 420_000, "unit": "bytes"},
    "css": {"label": "Sampled CSS", "limit": 140_000, "unit": "bytes"},
    "images": {"label": "Sampled images", "limit": 900_000, "unit": "bytes"},
    "fonts": {"label": "Sampled fonts", "limit": 180_000, "unit": "bytes"},
    "third_party_hosts": {"label": "Third-party hosts", "limit": 5, "unit": "count"},
    "ttfb": {"label": "Document TTFB", "limit": 800, "unit": "ms"},
    "lcp": {"label": "Largest Contentful Paint", "limit": 2500, "unit": "ms"},
    "tbt": {"label": "Total Blocking Time", "limit": 200, "unit": "ms"},
    "cls": {"label": "Cumulative Layout Shift", "limit": 0.1, "unit": "score"},
}

KIND_NORMALIZATION = {
    "script": "javascript",
    "stylesheet": "css",
    "image": "images",
    "font": "fonts",
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[Any]) -> float:
    clean = [_num(value) for value in values if value not in (None, "")]
    return round(statistics.mean(clean), 1) if clean else 0.0


def _host(value: str) -> str:
    try:
        return str(urlparse(value).hostname or "").strip().lower()
    except Exception:
        return ""


def _path(value: str) -> str:
    try:
        return str(urlparse(value).path or "/").strip() or "/"
    except Exception:
        return "/"


def _asset_kind(asset: Dict[str, Any]) -> str:
    raw = str(asset.get("kind") or "asset").strip().lower()
    return KIND_NORMALIZATION.get(raw, raw or "asset")


def _asset_bytes(asset: Dict[str, Any]) -> int:
    return max(0, int(_num(asset.get("content_length"), 0)))


def _is_compressed(asset: Dict[str, Any]) -> bool:
    return str(asset.get("content_encoding") or "").strip().lower() in {"br", "gzip", "zstd"}


def _cache_control(asset: Dict[str, Any]) -> str:
    return str(asset.get("cache_control") or "").strip().lower()


def _cache_ttl(asset: Dict[str, Any]) -> int:
    cache = _cache_control(asset)
    for part in cache.split(","):
        key_value = part.strip().split("=", 1)
        if len(key_value) != 2:
            continue
        key, value = key_value
        if key.strip() not in {"max-age", "s-maxage"}:
            continue
        try:
            return int(value.strip().strip('"'))
        except ValueError:
            continue
    return 0


def _has_strong_cache(asset: Dict[str, Any]) -> bool:
    cache = _cache_control(asset)
    return "immutable" in cache or _cache_ttl(asset) >= 2_592_000


def _is_uncacheable(asset: Dict[str, Any]) -> bool:
    cache = _cache_control(asset)
    return any(token in cache for token in ("no-store", "no-cache", "private"))


def _status_from_ratio(ratio: float) -> str:
    if ratio <= 0:
        return "unknown"
    if ratio <= 1:
        return "ok"
    if ratio <= 1.35:
        return "warn"
    return "fail"


def _page_type(url: str) -> str:
    path = _path(url)
    segments = [segment for segment in path.split("/") if segment]
    lower = path.lower()
    if not segments:
        return "home"
    if any(part in lower for part in ("/blog/", "/news/", "/guides/", "/article/")):
        return "article"
    if any(part in lower for part in ("/product/", "/products/", "/shop/", "/pricing/")):
        return "commerce"
    if any(part in lower for part in ("/category/", "/tag/", "/collections/", "/services/")):
        return "listing"
    if any(part in lower for part in ("/app/", "/dashboard/", "/account/", "/login/")):
        return "app"
    if len(segments) >= 3:
        return "deep_content"
    return "landing"


def _representative_lab(lab_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return next((item for item in lab_runs if item.get("score") is not None), {}) or {}


def _asset_rollups(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_kind: Dict[str, Dict[str, Any]] = {}
    by_host: Dict[str, Dict[str, Any]] = {}
    for asset in assets:
        kind = _asset_kind(asset)
        host = str(asset.get("host") or _host(str(asset.get("url") or "")) or "unknown")
        same_host = bool(asset.get("same_host"))
        size = _asset_bytes(asset)
        kind_row = by_kind.setdefault(kind, {
            "kind": kind,
            "count": 0,
            "bytes": 0,
            "compressed_count": 0,
            "strong_cache_count": 0,
            "weak_cache_count": 0,
            "uncacheable_count": 0,
        })
        kind_row["count"] += 1
        kind_row["bytes"] += size
        kind_row["compressed_count"] += 1 if _is_compressed(asset) else 0
        kind_row["strong_cache_count"] += 1 if _has_strong_cache(asset) else 0
        kind_row["weak_cache_count"] += 0 if _has_strong_cache(asset) else 1
        kind_row["uncacheable_count"] += 1 if _is_uncacheable(asset) else 0

        host_row = by_host.setdefault(host, {
            "host": host,
            "count": 0,
            "bytes": 0,
            "same_host": same_host,
            "kinds": Counter(),
        })
        host_row["count"] += 1
        host_row["bytes"] += size
        host_row["same_host"] = bool(host_row["same_host"] and same_host)
        host_row["kinds"][kind] += 1

    host_rows = []
    for item in by_host.values():
        host_rows.append({
            "host": item["host"],
            "count": item["count"],
            "bytes": item["bytes"],
            "same_host": item["same_host"],
            "kinds": dict(item["kinds"]),
        })
    return {
        "by_kind": sorted(by_kind.values(), key=lambda item: item["bytes"], reverse=True),
        "by_host": sorted(host_rows, key=lambda item: item["bytes"], reverse=True),
    }


def _build_budgets(
    pages: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    lab_runs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    representative = _representative_lab(lab_runs)
    kind_bytes = defaultdict(int)
    for asset in assets:
        kind_bytes[_asset_kind(asset)] += _asset_bytes(asset)

    third_party_hosts = {
        str(host or "").strip().lower()
        for page in pages
        for host in (page.get("external_hosts") or [])
        if str(host or "").strip()
    }
    avg_ttfb = _mean(page.get("ttfb_ms") for page in pages)
    actuals = {
        "page_weight": representative.get("total_byte_weight") or sum(kind_bytes.values()),
        "requests": representative.get("request_count") or len(assets),
        "javascript": kind_bytes.get("javascript", 0),
        "css": kind_bytes.get("css", 0),
        "images": kind_bytes.get("images", 0),
        "fonts": kind_bytes.get("fonts", 0),
        "third_party_hosts": max(len(third_party_hosts), max((_num(page.get("third_party_host_count")) for page in pages), default=0)),
        "ttfb": representative.get("server_response_time_ms") or avg_ttfb,
        "lcp": representative.get("largest_contentful_paint_ms"),
        "tbt": representative.get("total_blocking_time_ms"),
        "cls": representative.get("cumulative_layout_shift"),
    }

    budgets: List[Dict[str, Any]] = []
    for budget_id, budget in PERFORMANCE_BUDGETS.items():
        actual = actuals.get(budget_id)
        if actual in (None, ""):
            status = "unknown"
            ratio = 0.0
        else:
            ratio = _num(actual) / max(_num(budget["limit"], 1), 0.0001)
            status = _status_from_ratio(ratio)
        budgets.append({
            "id": budget_id,
            "label": budget["label"],
            "actual": round(_num(actual), 3) if actual not in (None, "") else None,
            "limit": budget["limit"],
            "unit": budget["unit"],
            "ratio": round(ratio, 2),
            "status": status,
        })
    return budgets


def _build_lab_summary(lab_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [item for item in lab_runs if item.get("score") is not None]
    if not valid:
        return {
            "available": False,
            "runner": "unavailable",
            "summary": "No stable lab measurement was available.",
            "runs": len(lab_runs),
        }
    scores = [_num(item.get("score")) for item in valid]
    lcps = [_num(item.get("largest_contentful_paint_ms")) for item in valid if item.get("largest_contentful_paint_ms") is not None]
    tbts = [_num(item.get("total_blocking_time_ms")) for item in valid if item.get("total_blocking_time_ms") is not None]
    representative = valid[0]
    diagnostics = representative.get("diagnostics") or {}
    multi_run = diagnostics.get("multi_run_summary") or {}
    return {
        "available": True,
        "runner": representative.get("runner") or "lab",
        "strategy": representative.get("strategy") or "mobile",
        "pages": len(valid),
        "score_min": round(min(scores), 1),
        "score_median": round(statistics.median(scores), 1),
        "score_max": round(max(scores), 1),
        "lcp_median_ms": round(statistics.median(lcps), 1) if lcps else None,
        "tbt_median_ms": round(statistics.median(tbts), 1) if tbts else None,
        "repeatability": multi_run,
        "summary": f"{len(valid)} representative lab page(s) completed via {representative.get('runner')}.",
    }


def _build_field_summary(field_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    best = next((item for item in field_data if item.get("scope") == "url"), None) or (field_data[0] if field_data else {})
    if not best:
        return {
            "available": False,
            "summary": "No CrUX field data confirmed for this target.",
            "metrics": {},
            "trends": {},
        }
    metrics = {
        "lcp_ms": best.get("lcp_ms"),
        "inp_ms": best.get("inp_ms"),
        "cls": best.get("cls"),
        "fcp_ms": best.get("fcp_ms"),
        "ttfb_ms": best.get("ttfb_ms"),
    }
    return {
        "available": True,
        "source": best.get("source"),
        "scope": best.get("scope"),
        "form_factor": best.get("form_factor"),
        "metrics": metrics,
        "trends": best.get("history") or {},
        "summary": f"Field data confirmed from {best.get('source')} on {best.get('scope')} scope.",
    }


def _build_waterfall(
    pages: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    asset_rollups: Dict[str, Any],
) -> Dict[str, Any]:
    same_host_bytes = sum(_asset_bytes(asset) for asset in assets if asset.get("same_host"))
    third_party_bytes = sum(_asset_bytes(asset) for asset in assets if not asset.get("same_host"))
    blocking_pages = [
        page for page in pages
        if page.get("render_blocking_hints")
    ]
    return {
        "asset_count": len(assets),
        "first_party_bytes": same_host_bytes,
        "third_party_bytes": third_party_bytes,
        "third_party_byte_share": round(third_party_bytes / max(same_host_bytes + third_party_bytes, 1), 3),
        "redirected_pages": len([page for page in pages if page.get("redirect_count", 0)]),
        "blocking_markup_pages": len(blocking_pages),
        "max_stylesheets": max((int(_num(page.get("stylesheet_count"))) for page in pages), default=0),
        "max_sync_script_hints": len([page for page in pages if "blocking_scripts" in (page.get("render_blocking_hints") or [])]),
        "by_kind": asset_rollups.get("by_kind") or [],
        "top_hosts": (asset_rollups.get("by_host") or [])[:8],
    }


def _build_third_party_tax(pages: List[Dict[str, Any]], asset_rollups: Dict[str, Any]) -> Dict[str, Any]:
    host_counter: Counter[str] = Counter()
    for page in pages:
        host_counter.update(str(host or "").strip().lower() for host in (page.get("external_hosts") or []) if str(host or "").strip())
    asset_hosts = {
        item["host"]: item
        for item in asset_rollups.get("by_host") or []
        if not item.get("same_host")
    }
    rows: List[Dict[str, Any]] = []
    for host, mentions in host_counter.items():
        asset = asset_hosts.get(host, {})
        rows.append({
            "host": host,
            "page_mentions": mentions,
            "sampled_requests": int(asset.get("count") or 0),
            "sampled_bytes": int(asset.get("bytes") or 0),
            "kinds": asset.get("kinds") or {},
            "risk": "high" if mentions >= 3 or int(asset.get("bytes") or 0) >= 250_000 else "medium" if mentions >= 1 else "low",
        })
    for host, asset in asset_hosts.items():
        if host in host_counter:
            continue
        rows.append({
            "host": host,
            "page_mentions": 0,
            "sampled_requests": int(asset.get("count") or 0),
            "sampled_bytes": int(asset.get("bytes") or 0),
            "kinds": asset.get("kinds") or {},
            "risk": "medium" if int(asset.get("bytes") or 0) >= 250_000 else "low",
        })
    rows.sort(key=lambda item: (item["risk"] == "high", item["sampled_bytes"], item["page_mentions"]), reverse=True)
    high_risk = [item for item in rows if item["risk"] == "high"]
    return {
        "host_count": len(rows),
        "high_risk_count": len(high_risk),
        "top_hosts": rows[:10],
        "summary": "Third-party surface is heavy." if high_risk else "No dominant third-party hotspot was confirmed in the sample.",
    }


def _build_cache_simulation(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    reusable = [asset for asset in assets if _has_strong_cache(asset)]
    weak = [asset for asset in assets if not _has_strong_cache(asset)]
    uncacheable = [asset for asset in assets if _is_uncacheable(asset)]
    reusable_bytes = sum(_asset_bytes(asset) for asset in reusable)
    weak_bytes = sum(_asset_bytes(asset) for asset in weak)
    total_bytes = reusable_bytes + weak_bytes
    risk = "high" if weak_bytes >= 600_000 else "medium" if weak_bytes >= 180_000 else "low"
    return {
        "sampled_asset_bytes": total_bytes,
        "repeat_visit_reusable_bytes": reusable_bytes,
        "repeat_visit_risky_bytes": weak_bytes,
        "explicitly_uncacheable_bytes": sum(_asset_bytes(asset) for asset in uncacheable),
        "strong_cache_asset_count": len(reusable),
        "weak_cache_asset_count": len(weak),
        "uncacheable_asset_count": len(uncacheable),
        "repeat_visit_risk": risk,
        "summary": (
            "Repeat visits are likely wasting bytes because sampled assets lack durable cache policy."
            if risk in {"high", "medium"}
            else "Repeat-visit cache risk looks contained in the sampled assets."
        ),
    }


def _detector(id_: str, title: str, status: str, summary: str, evidence: List[str], priority: int) -> Dict[str, Any]:
    return {
        "id": id_,
        "title": title,
        "status": status,
        "summary": summary,
        "evidence": [item for item in evidence if item],
        "priority": priority,
    }


def _build_detectives(
    pages: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    lab_runs: List[Dict[str, Any]],
    field_data: List[Dict[str, Any]],
    waterfall: Dict[str, Any],
    cache: Dict[str, Any],
) -> List[Dict[str, Any]]:
    representative = _representative_lab(lab_runs)
    field = _build_field_summary(field_data)
    lcp = _num(representative.get("largest_contentful_paint_ms"), 0)
    tbt = _num(representative.get("total_blocking_time_ms"), 0)
    cls = representative.get("cumulative_layout_shift")
    avg_ttfb = _mean(page.get("ttfb_ms") for page in pages)
    image_count = sum(int(_num(page.get("image_count"))) for page in pages)
    lazy_count = sum(int(_num(page.get("lazy_image_count"))) for page in pages)
    missing_dims = sum(int(_num(page.get("image_missing_dimension_count"))) for page in pages)
    stylesheet_max = int(waterfall.get("max_stylesheets") or 0)
    blocking_pages = int(waterfall.get("blocking_markup_pages") or 0)
    font_hosts = max((int(_num(page.get("font_host_count"))) for page in pages), default=0)
    preconnects = max((int(_num(page.get("preconnect_count"))) for page in pages), default=0)
    js_bytes = sum(_asset_bytes(asset) for asset in assets if _asset_kind(asset) == "javascript")
    css_bytes = sum(_asset_bytes(asset) for asset in assets if _asset_kind(asset) == "css")
    image_bytes = sum(_asset_bytes(asset) for asset in assets if _asset_kind(asset) == "images")

    return [
        _detector(
            "lcp_path",
            "LCP path detective",
            "bad" if lcp > 4000 or (lcp == 0 and (avg_ttfb > 1200 or image_bytes > 900_000 or blocking_pages)) else "warn" if lcp > 2500 or avg_ttfb > 800 or image_bytes > 600_000 else "good",
            "Prioritize the hero/LCP path: document response, render blockers, hero media, then client work.",
            [
                f"Lab LCP: {round(lcp)} ms" if lcp else "",
                f"Average sampled TTFB: {avg_ttfb} ms" if avg_ttfb else "",
                f"Sampled image bytes: {round(image_bytes / 1024)} KB" if image_bytes else "",
                f"{blocking_pages} sampled page(s) expose render-blocking hints." if blocking_pages else "",
            ],
            1,
        ),
        _detector(
            "main_thread",
            "Main-thread and INP risk detective",
            "bad" if tbt > 600 else "warn" if tbt > 200 or js_bytes > 420_000 else "unknown" if not representative else "good",
            "Reduce shipped and executed JavaScript before chasing micro-optimizations.",
            [
                f"Lab TBT: {round(tbt)} ms" if tbt else "",
                f"Sampled JS bytes: {round(js_bytes / 1024)} KB" if js_bytes else "",
                f"Field INP: {field.get('metrics', {}).get('inp_ms')} ms" if field.get("metrics", {}).get("inp_ms") else "",
            ],
            2,
        ),
        _detector(
            "css_rendering",
            "CSS and render-blocking detective",
            "bad" if stylesheet_max >= 6 else "warn" if stylesheet_max >= 3 or css_bytes > 140_000 else "good",
            "Keep only first-screen CSS on the critical path and defer the rest.",
            [
                f"Max stylesheet count: {stylesheet_max}",
                f"Sampled CSS bytes: {round(css_bytes / 1024)} KB" if css_bytes else "",
            ],
            3,
        ),
        _detector(
            "image_delivery",
            "Image delivery detective",
            "bad" if image_bytes > 1_500_000 or (image_count and lazy_count == 0 and image_count >= 8) else "warn" if image_bytes > 900_000 or missing_dims else "good",
            "Tighten eager/lazy behavior, responsive variants, dimensions, and modern formats.",
            [
                f"Sampled image bytes: {round(image_bytes / 1024)} KB" if image_bytes else "",
                f"Images in sampled HTML: {image_count}",
                f"Lazy images: {lazy_count}",
                f"Images missing dimensions: {missing_dims}" if missing_dims else "",
            ],
            4,
        ),
        _detector(
            "font_loading",
            "Font loading detective",
            "warn" if font_hosts and preconnects == 0 else "good",
            "Remote fonts need explicit connection and display strategy to avoid startup surprises.",
            [
                f"Font hosts: {font_hosts}",
                f"Preconnect hints: {preconnects}",
            ],
            5,
        ),
        _detector(
            "layout_stability",
            "Layout stability detective",
            "bad" if cls is not None and _num(cls) > 0.25 else "warn" if (cls is not None and _num(cls) > 0.1) or missing_dims else "unknown" if cls is None else "good",
            "Reserve space for media, embeds, ads, and dynamic widgets before they load.",
            [
                f"Lab CLS: {cls}" if cls is not None else "",
                f"Images missing dimensions: {missing_dims}" if missing_dims else "",
            ],
            6,
        ),
        _detector(
            "cache_repeat",
            "Repeat-visit cache detective",
            "bad" if cache.get("repeat_visit_risk") == "high" else "warn" if cache.get("repeat_visit_risk") == "medium" else "good",
            "Separate mutable HTML from immutable versioned assets.",
            [
                f"Risky repeat-visit bytes: {round((cache.get('repeat_visit_risky_bytes') or 0) / 1024)} KB",
                f"Weak cache assets: {cache.get('weak_cache_asset_count')}",
            ],
            7,
        ),
    ]


def _build_page_type_clusters(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        url = str(page.get("final_url") or page.get("url") or "")
        type_id = _page_type(url)
        bucket = buckets.setdefault(type_id, {
            "type": type_id,
            "count": 0,
            "avg_ttfb_ms": 0.0,
            "avg_html_kb": 0.0,
            "sample_urls": [],
        })
        bucket["count"] += 1
        bucket["avg_ttfb_ms"] += _num(page.get("ttfb_ms"))
        bucket["avg_html_kb"] += _num(page.get("html_bytes")) / 1024
        if len(bucket["sample_urls"]) < 4:
            bucket["sample_urls"].append(url)
    rows: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        count = max(1, int(bucket["count"]))
        rows.append({
            "type": bucket["type"],
            "count": count,
            "avg_ttfb_ms": round(bucket["avg_ttfb_ms"] / count, 1),
            "avg_html_kb": round(bucket["avg_html_kb"] / count, 1),
            "sample_urls": bucket["sample_urls"],
        })
    return sorted(rows, key=lambda item: (-item["count"], item["type"]))


def _build_action_plan(
    budgets: List[Dict[str, Any]],
    detectives: List[Dict[str, Any]],
    third_party: Dict[str, Any],
    cache: Dict[str, Any],
) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    bad_budgets = [item for item in budgets if item.get("status") == "fail"]
    warn_budgets = [item for item in budgets if item.get("status") == "warn"]
    budget_names = ", ".join(item["label"] for item in (bad_budgets + warn_budgets)[:4])
    if budget_names:
        actions.append({
            "priority": 1,
            "title": "Bring the worst performance budgets back under control",
            "impact": "High",
            "effort": "Medium",
            "evidence": budget_names,
            "dev_prompt": "Start with the failed PerfAtlas budgets, reduce the largest transfer and execution costs, then rerun the audit.",
            "validation": "Failed budgets move to warn or ok in the next run.",
        })
    lcp = next((item for item in detectives if item["id"] == "lcp_path"), {})
    if lcp.get("status") in {"bad", "warn"}:
        actions.append({
            "priority": 2,
            "title": "Shorten the LCP critical path",
            "impact": "High",
            "effort": "Medium",
            "evidence": "; ".join(lcp.get("evidence") or []),
            "dev_prompt": "Trace the LCP path from HTML response to visible element and remove the slowest blocking resource first.",
            "validation": "Lab LCP drops below 2500 ms or the LCP detective moves to good.",
        })
    main_thread = next((item for item in detectives if item["id"] == "main_thread"), {})
    if main_thread.get("status") in {"bad", "warn"}:
        actions.append({
            "priority": 3,
            "title": "Reduce main-thread and hydration pressure",
            "impact": "High",
            "effort": "High",
            "evidence": "; ".join(main_thread.get("evidence") or []),
            "dev_prompt": "Cut unused JavaScript, defer non-critical code, and split expensive interactive islands away from first paint.",
            "validation": "TBT drops below 200 ms and JS budget improves.",
        })
    if third_party.get("high_risk_count"):
        actions.append({
            "priority": 4,
            "title": "Audit third-party cost like production code",
            "impact": "Medium",
            "effort": "Low",
            "evidence": f"{third_party.get('high_risk_count')} high-risk third-party host(s).",
            "dev_prompt": "Inventory third-party tags, remove low-value ones, and delay unavoidable vendors until after the critical path.",
            "validation": "Third-party host count and bytes shrink on the next audit.",
        })
    if cache.get("repeat_visit_risk") in {"high", "medium"}:
        actions.append({
            "priority": 5,
            "title": "Fix repeat-visit caching for versioned assets",
            "impact": "Medium",
            "effort": "Low",
            "evidence": f"{round((cache.get('repeat_visit_risky_bytes') or 0) / 1024)} KB of sampled assets remain risky for repeat visits.",
            "dev_prompt": "Apply immutable long-lived caching to versioned JS, CSS, fonts, and images while keeping HTML mutable.",
            "validation": "Repeat-visit risky bytes fall below 180 KB.",
        })
    return actions[:8]


def build_performance_intelligence(
    *,
    target_url: str,
    profile: Dict[str, Any],
    pages: List[Dict[str, Any]],
    assets: List[Dict[str, Any]],
    lab_runs: List[Dict[str, Any]],
    field_data: List[Dict[str, Any]],
    template_clusters: List[Dict[str, Any]],
    provider_statuses: List[Dict[str, Any]],
    owner_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Build an export-friendly performance intelligence packet."""
    asset_rollups = _asset_rollups(assets)
    budgets = _build_budgets(pages, assets, lab_runs)
    lab = _build_lab_summary(lab_runs)
    field = _build_field_summary(field_data)
    waterfall = _build_waterfall(pages, assets, asset_rollups)
    third_party = _build_third_party_tax(pages, asset_rollups)
    cache = _build_cache_simulation(assets)
    detectives = _build_detectives(pages, assets, lab_runs, field_data, waterfall, cache)
    page_types = _build_page_type_clusters(pages)
    action_plan = _build_action_plan(budgets, detectives, third_party, cache)
    failed_budgets = [item for item in budgets if item.get("status") == "fail"]
    warning_budgets = [item for item in budgets if item.get("status") == "warn"]
    bad_detectives = [item for item in detectives if item.get("status") == "bad"]
    configured_providers = [
        item.get("id") for item in provider_statuses
        if item.get("configured") or str(item.get("status") or "").lower() in {"ready", "configured"}
    ]
    return {
        "version": 1,
        "target": target_url,
        "profile": {
            "label": profile.get("label"),
            "sample_pages": profile.get("sample_pages"),
            "lab_pages": profile.get("lab_pages"),
            "lab_runs": profile.get("lab_runs"),
        },
        "coverage": {
            "sampled_pages": len(pages),
            "template_clusters": len(template_clusters),
            "page_types": len(page_types),
            "configured_providers": configured_providers,
        },
        "summary": {
            "failed_budget_count": len(failed_budgets),
            "warning_budget_count": len(warning_budgets),
            "bad_detector_count": len(bad_detectives),
            "top_action": action_plan[0]["title"] if action_plan else "No priority action generated.",
            "diagnostic_confidence": "high" if lab.get("available") and field.get("available") else "medium" if lab.get("available") or field.get("available") else "limited",
        },
        "budgets": budgets,
        "lab": lab,
        "field": field,
        "waterfall": waterfall,
        "third_party_tax": third_party,
        "cache_simulation": cache,
        "detectives": sorted(detectives, key=lambda item: item.get("priority", 99)),
        "page_types": page_types,
        "template_clusters": template_clusters[:10],
        "action_plan": action_plan,
        "owner_context_available": bool((owner_context or {}).get("integrations")),
        "export_notes": [
            "All PerfAtlas intelligence values are derived from the attached crawl, lab, field, provider, and asset snapshots.",
            "Unknown values mean the runtime did not have enough evidence; they should not be filled in by an AI.",
            "Use the action plan order before optimizing lower-impact opportunities.",
        ],
    }


def intelligence_finding_specs(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return deterministic finding specs derived from the intelligence packet."""
    specs: List[Dict[str, Any]] = []
    summary = intelligence.get("summary") or {}
    budgets = intelligence.get("budgets") or []
    failed = [item for item in budgets if item.get("status") == "fail"]
    if len(failed) >= 2:
        labels = ", ".join(str(item.get("label") or item.get("id")) for item in failed[:5])
        specs.append({
            "finding_id": "performance-budget-breached",
            "title": "Performance budgets are breached across key startup signals",
            "scope": "performance_budget",
            "category": "budget",
            "bucket": "lab_startup",
            "severity": "high" if len(failed) >= 4 else "medium",
            "confidence": "Strong signal",
            "expected_impact": "High",
            "evidence": [f"Failed budgets: {labels}."],
            "diagnostic": "PerfAtlas found multiple budget breaches that should be treated as release-quality constraints, not isolated warnings.",
            "probable_cause": "The page is exceeding one or more transfer, request, rendering, or interaction limits at the same time.",
            "recommended_fix": "Fix the failed budgets in priority order, starting with the signals that affect LCP and main-thread work.",
            "acceptance_criteria": "The next audit moves failed budgets to warning or passing state.",
            "dev_prompt": "Use PerfAtlas budgets as hard constraints: reduce the worst failing budget first, rerun, then continue down the list.",
            "validation_state": "confirmed",
            "evidence_mode": "derived",
            "relationship_summary": "Budget breaches connect isolated symptoms into a release-ready performance contract.",
        })
    cache = intelligence.get("cache_simulation") or {}
    if cache.get("repeat_visit_risk") in {"high", "medium"}:
        specs.append({
            "finding_id": "repeat-visit-cache-waste",
            "title": "Repeat visits still waste cacheable asset bytes",
            "scope": "cache_simulation",
            "category": "caching",
            "bucket": "cache_transport",
            "severity": "medium",
            "confidence": "Strong signal",
            "expected_impact": "Medium",
            "evidence": [f"{round((cache.get('repeat_visit_risky_bytes') or 0) / 1024)} KB of sampled asset bytes are risky for repeat visits."],
            "diagnostic": "The cache simulation suggests returning visitors may still re-download assets that should be reusable.",
            "probable_cause": "Versioned static assets may be missing immutable long-lived caching on the final production path.",
            "recommended_fix": "Apply strong cache headers to versioned static assets and keep mutable HTML on a shorter policy.",
            "acceptance_criteria": "Repeat-visit risky bytes fall below the PerfAtlas threshold on the next audit.",
            "dev_prompt": "Separate immutable asset caching from document caching and verify the public headers, not only framework config.",
            "validation_state": "confirmed",
            "evidence_mode": "derived",
            "relationship_summary": "Repeat-visit waste hurts perceived speed after the first page load and makes navigations feel heavier.",
        })
    lab = intelligence.get("lab") or {}
    repeatability = lab.get("repeatability") or {}
    if _num(repeatability.get("score_range"), 0) >= 15 or _num(repeatability.get("lcp_range_ms"), 0) >= 800:
        specs.append({
            "finding_id": "lab-results-unstable",
            "title": "Lab results are noisy enough to require multi-run validation",
            "scope": "lab_repeatability",
            "category": "lab_runtime",
            "bucket": "ux_resilience",
            "severity": "low",
            "confidence": "Confirmed",
            "expected_impact": "Low",
            "evidence": [
                f"Score range: {repeatability.get('score_range')}.",
                f"LCP range: {repeatability.get('lcp_range_ms')} ms.",
            ],
            "diagnostic": "Repeated lab runs varied enough that a single measurement should not drive product decisions.",
            "probable_cause": "Network, CPU, third-party, cache, or server variance may be affecting lab stability.",
            "recommended_fix": "Use median multi-run values and investigate the most variable metric before claiming a regression or improvement.",
            "acceptance_criteria": "Follow-up lab runs show a narrower score and LCP range.",
            "dev_prompt": "Do not chase a single Lighthouse number; validate fixes against median and worst-case lab behavior.",
            "validation_state": "confirmed",
            "evidence_mode": "lab",
            "relationship_summary": "Stable measurement is a prerequisite for trustworthy optimization work.",
        })
    if summary.get("bad_detector_count", 0) >= 3:
        bad_titles = ", ".join(item.get("title", "") for item in (intelligence.get("detectives") or []) if item.get("status") == "bad")
        specs.append({
            "finding_id": "multiple-performance-detectives-red",
            "title": "Multiple performance detectives point to structural startup debt",
            "scope": "performance_intelligence",
            "category": "diagnostics",
            "bucket": "lab_startup",
            "severity": "high",
            "confidence": "Strong signal",
            "expected_impact": "High",
            "evidence": [bad_titles],
            "diagnostic": "Several independent diagnostic lenses agree that the problem is structural rather than a single small tweak.",
            "probable_cause": "The page likely combines delivery, asset, rendering, and client-execution pressure.",
            "recommended_fix": "Follow the PerfAtlas action plan order instead of applying isolated micro-fixes.",
            "acceptance_criteria": "The next audit reduces red detectives and improves the global score without regressing field or lab signals.",
            "dev_prompt": "Treat this as a coordinated performance pass: critical path, JS execution, images, cache, and third parties must be handled together.",
            "validation_state": "confirmed",
            "evidence_mode": "derived",
            "relationship_summary": "When multiple detectives are red, isolated fixes rarely move the needle enough.",
        })
    return specs


def _metric_delta(current: Any, previous: Any) -> Dict[str, Any]:
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "direction": "unknown"}
    current_value = _num(current)
    previous_value = _num(previous)
    delta = round(current_value - previous_value, 3)
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "current": current,
        "previous": previous,
        "delta": delta,
        "direction": direction,
    }


def _budget_status_counts(intelligence: Dict[str, Any]) -> Dict[str, int]:
    counts = Counter(str(item.get("status") or "unknown").lower() for item in intelligence.get("budgets") or [])
    return {
        "fail": int(counts.get("fail", 0)),
        "warn": int(counts.get("warn", 0)),
        "ok": int(counts.get("ok", 0)),
        "unknown": int(counts.get("unknown", 0)),
    }


def _finding_severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(str(item.get("severity") or "info").lower() for item in findings)
    return {
        "critical": int(counts.get("critical", 0)),
        "high": int(counts.get("high", 0)),
        "medium": int(counts.get("medium", 0)),
        "low": int(counts.get("low", 0)),
        "info": int(counts.get("info", 0)),
    }


def build_regression_summary(current_audit: Dict[str, Any], previous_audit: Dict[str, Any] | None) -> Dict[str, Any]:
    if not previous_audit:
        return {
            "available": False,
            "summary": "No previous completed PerfAtlas audit was available for this host.",
            "previous_audit_id": "",
            "risk": "unknown",
        }
    current_summary = current_audit.get("summary") or {}
    previous_summary = previous_audit.get("summary") or {}
    current_snapshot = current_audit.get("snapshot") or {}
    previous_snapshot = previous_audit.get("snapshot") or {}
    current_intel = current_snapshot.get("performance_intelligence") or {}
    previous_intel = previous_snapshot.get("performance_intelligence") or {}
    current_lab = current_intel.get("lab") or {}
    previous_lab = previous_intel.get("lab") or {}
    current_cache = current_intel.get("cache_simulation") or {}
    previous_cache = previous_intel.get("cache_simulation") or {}
    current_budget_counts = _budget_status_counts(current_intel)
    previous_budget_counts = _budget_status_counts(previous_intel)
    current_severities = _finding_severity_counts(current_audit.get("findings") or [])
    previous_severities = _finding_severity_counts(previous_audit.get("findings") or [])

    deltas = {
        "global_score": _metric_delta(current_summary.get("global_score"), previous_summary.get("global_score")),
        "lab_score_median": _metric_delta(current_lab.get("score_median"), previous_lab.get("score_median")),
        "lab_lcp_median_ms": _metric_delta(current_lab.get("lcp_median_ms"), previous_lab.get("lcp_median_ms")),
        "lab_tbt_median_ms": _metric_delta(current_lab.get("tbt_median_ms"), previous_lab.get("tbt_median_ms")),
        "failed_budget_count": _metric_delta(current_budget_counts.get("fail"), previous_budget_counts.get("fail")),
        "high_finding_count": _metric_delta(current_severities.get("high"), previous_severities.get("high")),
        "repeat_visit_risky_bytes": _metric_delta(current_cache.get("repeat_visit_risky_bytes"), previous_cache.get("repeat_visit_risky_bytes")),
    }

    regressions: List[str] = []
    improvements: List[str] = []
    score_delta = _num(deltas["global_score"].get("delta"), 0)
    lcp_delta = _num(deltas["lab_lcp_median_ms"].get("delta"), 0)
    tbt_delta = _num(deltas["lab_tbt_median_ms"].get("delta"), 0)
    failed_budget_delta = _num(deltas["failed_budget_count"].get("delta"), 0)
    high_finding_delta = _num(deltas["high_finding_count"].get("delta"), 0)
    cache_delta = _num(deltas["repeat_visit_risky_bytes"].get("delta"), 0)

    if score_delta <= -5:
        regressions.append(f"Global score dropped by {abs(score_delta)} point(s).")
    elif score_delta >= 5:
        improvements.append(f"Global score improved by {score_delta} point(s).")
    if lcp_delta >= 300:
        regressions.append(f"Lab LCP median worsened by {round(lcp_delta)} ms.")
    elif lcp_delta <= -300:
        improvements.append(f"Lab LCP median improved by {round(abs(lcp_delta))} ms.")
    if tbt_delta >= 100:
        regressions.append(f"Lab TBT median worsened by {round(tbt_delta)} ms.")
    elif tbt_delta <= -100:
        improvements.append(f"Lab TBT median improved by {round(abs(tbt_delta))} ms.")
    if failed_budget_delta > 0:
        regressions.append(f"{round(failed_budget_delta)} additional budget(s) failed.")
    elif failed_budget_delta < 0:
        improvements.append(f"{round(abs(failed_budget_delta))} failed budget(s) recovered.")
    if high_finding_delta > 0:
        regressions.append(f"{round(high_finding_delta)} additional high-severity finding(s).")
    if cache_delta >= 180_000:
        regressions.append(f"Repeat-visit risky bytes increased by {round(cache_delta / 1024)} KB.")

    if regressions:
        risk = "regressed"
        summary = "Regression risk detected versus the previous completed audit."
    elif improvements:
        risk = "improved"
        summary = "Performance improved versus the previous completed audit."
    else:
        risk = "stable"
        summary = "Performance is broadly stable versus the previous completed audit."

    return {
        "available": True,
        "previous_audit_id": previous_audit.get("id") or "",
        "previous_created_at": previous_audit.get("created_at") or "",
        "previous_updated_at": previous_audit.get("updated_at") or "",
        "risk": risk,
        "summary": summary,
        "deltas": deltas,
        "current_budget_status_counts": current_budget_counts,
        "previous_budget_status_counts": previous_budget_counts,
        "current_severity_counts": current_severities,
        "previous_severity_counts": previous_severities,
        "regressions": regressions,
        "improvements": improvements,
    }
