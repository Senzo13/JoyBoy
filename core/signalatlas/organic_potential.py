"""Google Search Console CSV analysis for SignalAtlas organic potential."""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from core.runtime.storage import utc_now_iso


GSC_ACCEPTED_KINDS = {
    "chart",
    "pages",
    "queries",
    "devices",
    "countries",
    "search_appearance",
    "filters",
}

GENERIC_HOST_TOKENS = {
    "www",
    "com",
    "net",
    "org",
    "fr",
    "io",
    "app",
    "dev",
    "co",
    "uk",
}


def _decode_csv_content(content: Any) -> str:
    if isinstance(content, bytes):
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower().lstrip("\ufeff"))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _lookup(row: Dict[str, Any], *candidates: str) -> str:
    keyed = {_header_key(key): value for key, value in row.items()}
    for candidate in candidates:
        key = _header_key(candidate)
        if key in keyed:
            return _clean_text(keyed.get(key))
    return ""


def _parse_int(value: Any) -> int:
    text = _clean_text(value)
    if not text:
        return 0
    text = text.replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", "")
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _parse_float(value: Any) -> Optional[float]:
    text = _clean_text(value)
    if not text:
        return None
    text = text.replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    text = text.replace("%", "").replace(",", ".")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_ctr(value: Any, clicks: int = 0, impressions: int = 0) -> float:
    text = _clean_text(value)
    parsed = _parse_float(text)
    if parsed is None:
        return round(clicks / impressions, 6) if impressions else 0.0
    if "%" in text or parsed > 1:
        parsed = parsed / 100.0
    return round(max(0.0, min(parsed, 1.0)), 6)


def _weighted_position(rows: Iterable[Dict[str, Any]]) -> Optional[float]:
    weighted = 0.0
    weight = 0
    for row in rows:
        position = row.get("position")
        impressions = int(row.get("impressions") or 0)
        if position is None or impressions <= 0:
            continue
        weighted += float(position) * impressions
        weight += impressions
    if not weight:
        return None
    return round(weighted / weight, 2)


def _expected_ctr(position: Optional[float]) -> float:
    if position is None:
        return 0.0
    if position <= 1:
        return 0.28
    if position <= 2:
        return 0.16
    if position <= 3:
        return 0.11
    if position <= 4:
        return 0.08
    if position <= 5:
        return 0.06
    if position <= 6:
        return 0.045
    if position <= 7:
        return 0.035
    if position <= 8:
        return 0.028
    if position <= 9:
        return 0.023
    if position <= 10:
        return 0.02
    if position <= 20:
        return 0.01
    if position <= 30:
        return 0.005
    return 0.0015


def _missed_clicks(clicks: int, impressions: int, position: Optional[float]) -> float:
    if impressions <= 0:
        return 0.0
    expected = impressions * _expected_ctr(position)
    return round(max(0.0, expected - clicks), 2)


def _opportunity_type(clicks: int, impressions: int, ctr: float, position: Optional[float]) -> str:
    expected = _expected_ctr(position)
    if impressions < 10:
        return "low_value"
    if clicks == 0 and impressions >= 20:
        if position is not None and position <= 12:
            return "ctr_gap"
        if position is not None and position <= 30:
            return "ranking_distance"
        return "content_gap"
    if position is not None and 4 <= position <= 12 and impressions >= 20:
        if expected and ctr < expected * 0.75:
            return "ctr_gap"
        return "quick_win"
    if position is not None and 12 < position <= 30 and impressions >= 20:
        return "ranking_distance"
    if position is not None and position > 30 and impressions >= 20:
        return "content_gap"
    if expected and ctr < expected * 0.55 and impressions >= 20:
        return "ctr_gap"
    return "low_value"


def _priority_score(
    *,
    impressions: int,
    clicks: int,
    position: Optional[float],
    missed_clicks: float,
    flags: Optional[List[str]] = None,
) -> float:
    if impressions <= 0:
        return 0.0
    impression_score = min(34.0, math.log10(impressions + 1) * 11.0)
    missed_score = min(34.0, math.sqrt(max(0.0, missed_clicks)) * 7.0)
    position_score = 0.0
    if position is not None:
        if 4 <= position <= 12:
            position_score = 22.0
        elif 12 < position <= 30:
            position_score = 16.0
        elif position <= 3:
            position_score = 10.0
        elif position > 30:
            position_score = 6.0
    click_bonus = 4.0 if clicks == 0 and impressions >= 20 else 0.0
    flag_bonus = min(8.0, len(flags or []) * 2.0)
    return round(min(100.0, impression_score + missed_score + position_score + click_bonus + flag_bonus), 1)


def _detect_kind(filename: str, headers: List[str]) -> str:
    name = str(filename or "").strip().lower()
    header_keys = {_header_key(header) for header in headers}
    if "queries" in name or "query" in name or "topqueries" in header_keys:
        return "queries"
    if "pages" in name or "page" in name or "toppages" in header_keys:
        return "pages"
    if "device" in name or "device" in header_keys:
        return "devices"
    if "countr" in name or "country" in header_keys:
        return "countries"
    if "search appearance" in name or "searchappearance" in name or "searchappearance" in header_keys:
        return "search_appearance"
    if "filter" in name:
        return "filters"
    if "chart" in name or "date" in header_keys:
        return "chart"
    return "unknown"


def _read_csv(filename: str, content: Any) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    text = _decode_csv_content(content)
    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    headers = list(reader.fieldnames or [])
    kind = _detect_kind(filename, headers)
    rows: List[Dict[str, Any]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        clean_row = {str(key or "").strip().lstrip("\ufeff"): value for key, value in row.items()}
        if any(_clean_text(value) for value in clean_row.values()):
            rows.append(clean_row)
    return kind, rows, headers


def _metric_row(row: Dict[str, Any], dimension: str) -> Dict[str, Any]:
    clicks = _parse_int(_lookup(row, "Clicks"))
    impressions = _parse_int(_lookup(row, "Impressions"))
    ctr = _parse_ctr(_lookup(row, "CTR"), clicks, impressions)
    position = _parse_float(_lookup(row, "Position"))
    return {
        "dimension": dimension,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": round(position, 2) if position is not None else None,
    }


def _url_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    except Exception:
        return raw.lower().rstrip("/")
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, host, path or "/", "", "", ""))


def _path_signature(value: str) -> str:
    key = _url_key(value)
    try:
        parsed = urlparse(key)
    except Exception:
        return key
    parts = [part for part in (parsed.path or "/").split("/") if part]
    if parts and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0], flags=re.I):
        parts = parts[1:]
    if not parts:
        return "/"
    return "/".join(parts).lower()


def _audit_host(audit: Optional[Dict[str, Any]]) -> str:
    target = (audit or {}).get("target") or {}
    summary = (audit or {}).get("summary") or {}
    raw = target.get("normalized_url") or target.get("raw") or summary.get("target") or ""
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        return parsed.netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _brand_tokens(audit: Optional[Dict[str, Any]]) -> List[str]:
    host = _audit_host(audit)
    tokens = []
    if host:
        primary = host.split(".")[0]
        tokens.extend(re.split(r"[^a-z0-9]+", primary.lower()))
    metadata_terms = (((audit or {}).get("metadata") or {}).get("brand_terms") or [])
    if isinstance(metadata_terms, str):
        metadata_terms = [metadata_terms]
    tokens.extend(str(term or "").lower().strip() for term in metadata_terms)
    clean = []
    for token in tokens:
        if len(token) >= 3 and token not in GENERIC_HOST_TOKENS and token not in clean:
            clean.append(token)
    return clean


def _is_brand_query(query: str, tokens: List[str]) -> bool:
    clean = str(query or "").lower()
    return any(token and token in clean for token in tokens)


def _crawl_pages(audit: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    pages = (((audit or {}).get("snapshot") or {}).get("pages") or [])
    mapping: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        for candidate in (page.get("final_url"), page.get("url")):
            key = _url_key(candidate or "")
            if key:
                mapping[key] = page
    return mapping


def _crawl_match(page_url: str, crawl_map: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
    key = _url_key(page_url)
    page = crawl_map.get(key)
    if not page:
        return {"matched": False, "url": ""}, ["not_sampled_in_crawl"]

    title = _clean_text(page.get("title"))
    meta = _clean_text(page.get("meta_description"))
    h1 = _clean_text(page.get("h1"))
    content_units = int(page.get("content_units") or page.get("word_count") or 0)
    crawl_depth = int(page.get("crawl_depth") or 0)
    internal_links = page.get("internal_links") or []
    indexable = bool(page.get("indexable_candidate"))
    flags: List[str] = []
    if not title or len(title) < 30:
        flags.append("weak_title")
    if not meta or len(meta) < 70:
        flags.append("weak_meta")
    if not h1 or len(h1) < 12:
        flags.append("weak_h1")
    if content_units and content_units < 350:
        flags.append("thin_content")
    if crawl_depth >= 3 or len(internal_links) <= 1:
        flags.append("weak_depth_or_internal_linking")
    if not indexable:
        flags.append("not_indexable_candidate")

    return {
        "matched": True,
        "url": page.get("final_url") or page.get("url") or page_url,
        "title": title,
        "meta_description": meta,
        "h1": h1,
        "content_units": content_units,
        "crawl_depth": crawl_depth,
        "internal_link_count": len(internal_links),
        "indexable_candidate": indexable,
    }, flags


def _page_action(opportunity_type: str, flags: List[str]) -> str:
    if "not_sampled_in_crawl" in flags:
        return "Crawl this URL in a broader pass, then validate title, content depth, canonicals, and internal links before changing copy."
    if "not_indexable_candidate" in flags:
        return "Resolve indexability first, then rerun GSC import to avoid optimizing demand that Google cannot reliably surface."
    if opportunity_type == "ctr_gap":
        return "Rewrite title/meta around the real search intent, preserve relevance, and test a clearer click promise."
    if opportunity_type == "quick_win":
        return "Strengthen the page answer, H1/title alignment, and internal links because it is already close to page-one visibility."
    if opportunity_type == "ranking_distance":
        return "Expand the content cluster, add supporting sections, and link from stronger pages to push positions 13-30 upward."
    if opportunity_type == "content_gap":
        return "Create or rebuild content that directly satisfies the query family before expecting meaningful clicks."
    return "Keep monitoring; this row is currently lower priority than stronger impression or position gaps."


def _query_intent(query: str) -> str:
    clean = f" {str(query or '').lower()} "
    if re.search(r"\b(prix|tarif|cost|price|acheter|buy|download|télécharger|telecharger|avis|review)\b", clean):
        return "commercial"
    if re.search(r"\b(comment|how|why|pourquoi|guide|tutorial|best|meilleur|comparatif|gratuit|free)\b", clean):
        return "informational"
    if re.search(r"\b(login|connexion|near me|adresse|contact|site officiel)\b", clean):
        return "navigational"
    if len(clean.split()) <= 2:
        return "mixed_short_tail"
    return "informational"


def _parse_pages(rows: List[Dict[str, Any]], crawl_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        url = _lookup(row, "Top pages", "Page", "Pages")
        if not url:
            continue
        metric = _metric_row(row, url)
        missed = _missed_clicks(metric["clicks"], metric["impressions"], metric["position"])
        opportunity = _opportunity_type(metric["clicks"], metric["impressions"], metric["ctr"], metric["position"])
        crawl_match, flags = _crawl_match(url, crawl_map)
        if metric["clicks"] == 0 and metric["impressions"] >= 20 and crawl_match.get("indexable_candidate", True):
            flags.append("indexable_no_clicks")
        if metric["impressions"] < 10:
            flags.append("low_gsc_sample")
        parsed.append({
            "url": url,
            "normalized_url": _url_key(url),
            "clicks": metric["clicks"],
            "impressions": metric["impressions"],
            "ctr": metric["ctr"],
            "position": metric["position"],
            "expected_ctr": round(_expected_ctr(metric["position"]), 4),
            "missed_clicks": missed,
            "priority_score": _priority_score(
                impressions=metric["impressions"],
                clicks=metric["clicks"],
                position=metric["position"],
                missed_clicks=missed,
                flags=flags,
            ),
            "opportunity_type": opportunity,
            "opportunity_types": [opportunity],
            "crawl_match": crawl_match,
            "content_flags": sorted(set(flags)),
            "mapping_confidence": "page_only",
            "recommended_action": _page_action(opportunity, flags),
        })
    parsed.sort(key=lambda item: (item["priority_score"], item["missed_clicks"], item["impressions"]), reverse=True)
    return parsed


def _parse_queries(rows: List[Dict[str, Any]], audit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tokens = _brand_tokens(audit)
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        query = _lookup(row, "Top queries", "Query", "Queries")
        if not query:
            continue
        metric = _metric_row(row, query)
        missed = _missed_clicks(metric["clicks"], metric["impressions"], metric["position"])
        opportunity = _opportunity_type(metric["clicks"], metric["impressions"], metric["ctr"], metric["position"])
        family = "brand_query" if _is_brand_query(query, tokens) else "non_brand_query"
        if metric["clicks"] == 0 and metric["impressions"] >= 10:
            zero_click = True
        else:
            zero_click = False
        parsed.append({
            "query": query,
            "clicks": metric["clicks"],
            "impressions": metric["impressions"],
            "ctr": metric["ctr"],
            "position": metric["position"],
            "expected_ctr": round(_expected_ctr(metric["position"]), 4),
            "missed_clicks": missed,
            "priority_score": _priority_score(
                impressions=metric["impressions"],
                clicks=metric["clicks"],
                position=metric["position"],
                missed_clicks=missed,
                flags=["zero_click"] if zero_click else [],
            ),
            "opportunity_type": opportunity,
            "opportunity_types": [opportunity, family],
            "query_family": family,
            "intent": _query_intent(query),
            "zero_click": zero_click,
            "mapping_confidence": "query_only",
            "recommended_action": _query_action(opportunity, family, zero_click),
        })
    parsed.sort(key=lambda item: (item["priority_score"], item["missed_clicks"], item["impressions"]), reverse=True)
    return parsed


def _query_action(opportunity_type: str, family: str, zero_click: bool) -> str:
    if family == "brand_query":
        return "Protect branded demand with exact-match titles, sitelinks-friendly navigation, and a clean official landing path."
    if zero_click:
        return "Create a sharper answer for this exact query family and make the page title promise obvious enough to earn the first click."
    if opportunity_type == "quick_win":
        return "Push this query with focused copy, supporting FAQ blocks, and internal anchors from relevant pages."
    if opportunity_type == "ranking_distance":
        return "Build topical depth and internal links before expecting CTR work to move the needle."
    if opportunity_type == "ctr_gap":
        return "Test a stronger SERP title/meta angle because impressions already exist but clicks lag expected CTR."
    return "Cluster this query with related terms and monitor whether impressions keep growing."


def _parse_chart(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        date = _lookup(row, "Date")
        if not date:
            continue
        metric = _metric_row(row, date)
        parsed.append({
            "date": date,
            "clicks": metric["clicks"],
            "impressions": metric["impressions"],
            "ctr": metric["ctr"],
            "position": metric["position"],
        })
    return parsed


def _parse_segment(rows: List[Dict[str, Any]], dimension_headers: Tuple[str, ...]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        dimension = _lookup(row, *dimension_headers)
        if not dimension:
            continue
        metric = _metric_row(row, dimension)
        parsed.append({
            "name": dimension,
            "clicks": metric["clicks"],
            "impressions": metric["impressions"],
            "ctr": metric["ctr"],
            "position": metric["position"],
        })
    parsed.sort(key=lambda item: (item["clicks"], item["impressions"]), reverse=True)
    return parsed


def _summary_from_rows(pages: List[Dict[str, Any]], queries: List[Dict[str, Any]], chart: List[Dict[str, Any]]) -> Dict[str, Any]:
    primary = pages or queries or chart
    clicks = sum(int(item.get("clicks") or 0) for item in primary)
    impressions = sum(int(item.get("impressions") or 0) for item in primary)
    ctr = round(clicks / impressions, 6) if impressions else 0.0
    avg_position = _weighted_position(primary)
    missed = round(sum(float(item.get("missed_clicks") or 0) for item in (pages or queries)), 2)
    opportunity_types = Counter(
        item.get("opportunity_type")
        for item in [*pages, *queries]
        if item.get("opportunity_type")
        and item.get("opportunity_type") != "low_value"
        and float(item.get("priority_score") or 0) >= 25
    )
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "average_position": avg_position,
        "missed_clicks": missed,
        "page_count": len(pages),
        "query_count": len(queries),
        "opportunity_count": sum(1 for item in [*pages, *queries] if float(item.get("priority_score") or 0) >= 30),
        "top_opportunity_type": opportunity_types.most_common(1)[0][0] if opportunity_types else "",
        "chart_start_date": chart[0]["date"] if chart else "",
        "chart_end_date": chart[-1]["date"] if chart else "",
    }


def _build_opportunities(pages: List[Dict[str, Any]], queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    combined: List[Dict[str, Any]] = []
    for page in pages:
        if page.get("opportunity_type") == "low_value" and float(page.get("priority_score") or 0) < 25:
            continue
        combined.append({
            "kind": "page",
            "label": page.get("url"),
            "opportunity_type": page.get("opportunity_type"),
            "opportunity_types": page.get("opportunity_types") or [],
            "priority_score": page.get("priority_score"),
            "clicks": page.get("clicks"),
            "impressions": page.get("impressions"),
            "ctr": page.get("ctr"),
            "position": page.get("position"),
            "missed_clicks": page.get("missed_clicks"),
            "evidence": page.get("content_flags") or [],
            "recommended_action": page.get("recommended_action"),
            "mapping_confidence": page.get("mapping_confidence"),
        })
    for query in queries:
        if query.get("opportunity_type") == "low_value" and float(query.get("priority_score") or 0) < 25:
            continue
        combined.append({
            "kind": "query",
            "label": query.get("query"),
            "opportunity_type": query.get("opportunity_type"),
            "opportunity_types": query.get("opportunity_types") or [],
            "priority_score": query.get("priority_score"),
            "clicks": query.get("clicks"),
            "impressions": query.get("impressions"),
            "ctr": query.get("ctr"),
            "position": query.get("position"),
            "missed_clicks": query.get("missed_clicks"),
            "evidence": [query.get("intent"), query.get("query_family")],
            "recommended_action": query.get("recommended_action"),
            "mapping_confidence": query.get("mapping_confidence"),
        })
    combined.sort(key=lambda item: (float(item.get("priority_score") or 0), float(item.get("missed_clicks") or 0), int(item.get("impressions") or 0)), reverse=True)
    return combined[:80]


def _cannibalization_candidates(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for page in pages:
        signature = _path_signature(page.get("url") or "")
        if signature:
            grouped[signature].append(page)

    candidates = []
    for signature, items in grouped.items():
        if len(items) < 2:
            continue
        total_impressions = sum(int(item.get("impressions") or 0) for item in items)
        if total_impressions < 20:
            continue
        candidates.append({
            "signature": signature,
            "url_count": len(items),
            "impressions": total_impressions,
            "clicks": sum(int(item.get("clicks") or 0) for item in items),
            "urls": [item.get("url") for item in items[:8]],
            "reason": "Multiple URL variants share a close path signature in GSC page exports; query mapping is inferred because GSC CSV exports are separate.",
            "mapping_confidence": "inferred",
        })
    candidates.sort(key=lambda item: item["impressions"], reverse=True)
    return candidates[:20]


def analyze_gsc_csv_exports(
    files: Iterable[Dict[str, Any]],
    *,
    audit: Optional[Dict[str, Any]] = None,
    semrush_configured: bool = False,
) -> Dict[str, Any]:
    """Parse standard GSC CSV exports and return a storage-safe analysis payload."""

    parsed_files: Dict[str, List[Dict[str, Any]]] = {kind: [] for kind in GSC_ACCEPTED_KINDS}
    source_files: List[Dict[str, Any]] = []
    for file_item in files:
        filename = str(file_item.get("filename") or "").strip() if isinstance(file_item, dict) else ""
        content = file_item.get("content") if isinstance(file_item, dict) else ""
        kind, rows, headers = _read_csv(filename, content)
        accepted = kind in GSC_ACCEPTED_KINDS
        source_files.append({
            "filename": filename,
            "kind": kind,
            "rows": len(rows),
            "accepted": accepted,
            "headers": headers[:12],
        })
        if accepted:
            parsed_files[kind].extend(rows)

    crawl_map = _crawl_pages(audit)
    pages = _parse_pages(parsed_files["pages"], crawl_map)
    queries = _parse_queries(parsed_files["queries"], audit)
    chart = _parse_chart(parsed_files["chart"])
    segments = {
        "devices": _parse_segment(parsed_files["devices"], ("Device",)),
        "countries": _parse_segment(parsed_files["countries"], ("Country", "Countries")),
        "search_appearance": _parse_segment(parsed_files["search_appearance"], ("Search appearance", "Search Appearance")),
        "trend": chart,
        "filters": [
            {str(key or "").strip(): _clean_text(value) for key, value in row.items() if _clean_text(value)}
            for row in parsed_files["filters"][:20]
        ],
    }
    summary = _summary_from_rows(pages, queries, chart)
    summary["semrush_status"] = "configured" if semrush_configured else "not_configured"

    return {
        "generated_at": utc_now_iso(),
        "source": "google_search_console_csv",
        "mapping_mode": "separate_gsc_exports",
        "query_page_mapping": "inferred_only_without_page_query_export",
        "source_files": source_files,
        "summary": summary,
        "pages": pages[:300],
        "queries": queries[:500],
        "opportunities": _build_opportunities(pages, queries),
        "segments": segments,
        "cannibalization_candidates": _cannibalization_candidates(pages),
        "providers": {
            "google_search_console_csv": {
                "status": "imported" if any(item["accepted"] for item in source_files) else "empty",
                "confidence": "confirmed_metrics",
            },
            "semrush": {
                "status": "configured" if semrush_configured else "locked",
                "configured": bool(semrush_configured),
                "detail": "SEMRUSH_API_KEY can enrich future runs with volume, keyword difficulty, competitors, and external organic pages.",
            },
        },
    }
