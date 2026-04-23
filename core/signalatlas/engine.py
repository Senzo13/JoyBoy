"""Deterministic public audit engine for SignalAtlas."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, deque
from html import unescape
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - best effort fallback
    BeautifulSoup = None

from core.runtime.storage import utc_now_iso
from .providers import build_owner_context
from .scoring import score_findings


USER_AGENT = "JoyBoy-SignalAtlas/1.0 (+https://joyboy.local)"
DEFAULT_TIMEOUT = (5, 15)
MAX_LINK_SAMPLES = 48
MAX_RENDER_PROBES = 3


def _normalize_target(raw_target: str) -> Tuple[str, str]:
    value = str(raw_target or "").strip()
    if not value:
        raise ValueError("Target URL required")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", value):
        value = f"https://{value}"
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))
    return normalized, host


def _clean_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path or "/"
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), path, "", "", ""))


def _same_host(url: str, host: str) -> bool:
    try:
        return urlparse(url).netloc.lower() == host.lower()
    except Exception:
        return False


def _is_http_html(response: requests.Response) -> bool:
    content_type = str(response.headers.get("content-type", "")).lower()
    return "text/html" in content_type or "application/xhtml+xml" in content_type


def _text_content(html: str) -> str:
    if not html:
        return ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for node in soup(["script", "style", "noscript", "template"]):
            node.decompose()
        return " ".join(soup.get_text(" ").split())
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()


def _meta_content(soup: Any, *names: str) -> str:
    lowered = {name.lower() for name in names}
    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").strip().lower()
        if name in lowered:
            return str(meta.get("content") or "").strip()
    return ""


def _all_meta_contents(soup: Any, *names: str) -> Dict[str, str]:
    lowered = {name.lower() for name in names}
    values: Dict[str, str] = {}
    for meta in soup.find_all("meta"):
        name = str(meta.get("name") or meta.get("property") or "").strip().lower()
        if name in lowered:
            values[name] = str(meta.get("content") or "").strip()
    return values


def _extract_internal_links(soup: Any, page_url: str, host: str) -> Tuple[List[str], int]:
    internal: List[str] = []
    external = 0
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = _clean_url(urljoin(page_url, href))
        if not absolute.startswith("http"):
            continue
        if _same_host(absolute, host):
            if absolute not in seen:
                internal.append(absolute)
                seen.add(absolute)
        else:
            external += 1
    return internal[:MAX_LINK_SAMPLES], external


def _template_signature(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    normalized: List[str] = []
    for part in parts[:6]:
        if re.fullmatch(r"\d+", part):
            normalized.append("{num}")
        elif len(part) > 20 and re.search(r"[a-z]", part, re.I):
            normalized.append("{slug}")
        elif re.fullmatch(r"[0-9a-fA-F-]{8,}", part):
            normalized.append("{id}")
        else:
            normalized.append(part.lower())
    return "/" + "/".join(normalized or [""])


def _framework_signatures(html: str, headers: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    text = html or ""
    header_blob = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    signatures: List[str] = []
    reasons: List[str] = []

    checks = [
        ("nextjs", [("__NEXT_DATA__", "Found __NEXT_DATA__ payload"), ("/_next/", "Found /_next/ assets")]),
        ("nuxt", [("_nuxt/", "Found _nuxt assets"), ("__NUXT__", "Found __NUXT__ payload")]),
        ("astro", [("astro-island", "Found astro-island component"), ("/_astro/", "Found Astro assets")]),
        ("wordpress", [("wp-content/", "Found wp-content assets"), ('name="generator" content="WordPress', "WordPress generator meta")]),
        ("shopify", [("cdn.shopify.com", "Found Shopify CDN assets"), ("Shopify.theme", "Found Shopify theme object")]),
        ("webflow", [("data-wf-page", "Found Webflow page marker"), ("webflow.js", "Found Webflow runtime")]),
        ("react_spa", [('id="root"', "Found root app container"), ('id="app"', "Found app container")]),
        ("vite", [("/@vite/client", "Found Vite client"), ('type="module"', "Found ES module entrypoints")]),
    ]
    for name, probes in checks:
        matched = False
        for probe, reason in probes:
            if probe in text or probe.lower() in header_blob:
                matched = True
                reasons.append(reason)
        if matched:
            signatures.append(name)

    return signatures, reasons


def _render_signals(html: str, text_content: str) -> Tuple[List[str], bool, List[str]]:
    raw = html or ""
    plain_text = text_content or ""
    script_count = raw.count("<script")
    word_count = len(plain_text.split())
    reasons: List[str] = []
    signals: List[str] = []
    shell_like = False

    if script_count >= 8:
        signals.append("script_heavy")
        reasons.append("High script density compared to visible content.")
    if word_count <= 120:
        signals.append("thin_initial_html")
        reasons.append("Very little visible text in the initial HTML response.")
    if re.search(r'<div[^>]+id="(?:root|app|__next)"[^>]*>\s*</div>', raw, re.I | re.S):
        signals.append("app_shell")
        reasons.append("Primary app container is close to empty in raw HTML.")
    if "hydrate" in raw.lower():
        signals.append("hydration_signals")
        reasons.append("Hydration-related markers found in the HTML payload.")
    if ("app_shell" in signals and "thin_initial_html" in signals) or (script_count >= 12 and word_count <= 80):
        shell_like = True
        reasons.append("Initial response looks like a JS shell rather than a fully rendered document.")
    return signals, shell_like, reasons


def _playwright_runtime_status() -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        return {
            "available": False,
            "reason": "playwright_not_installed",
            "detail": str(exc),
        }
    return {
        "available": True,
        "reason": "",
        "detail": "",
    }


def _render_page_with_playwright(url: str) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - guarded by _playwright_runtime_status
        return {
            "url": url,
            "executed": False,
            "reason": "playwright_not_installed",
            "detail": str(exc),
        }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900})
                page.goto(url, wait_until="networkidle", timeout=15000)
                html = page.content() or ""
                title = page.title() or ""
            finally:
                browser.close()

        plain_text = _text_content(html)
        render_signals, shell_like, reasons = _render_signals(html, plain_text)
        return {
            "url": url,
            "executed": True,
            "html": html,
            "title": title[:240],
            "word_count": len(plain_text.split()),
            "text_hash": _hash_text(plain_text),
            "shell_like": shell_like,
            "render_signals": render_signals,
            "classification_reasons": reasons,
        }
    except Exception as exc:
        return {
            "url": url,
            "executed": False,
            "reason": "playwright_error",
            "detail": str(exc),
        }


def _apply_render_probe(
    pages: List[Dict[str, Any]],
    entry_url: str,
    *,
    render_js: bool,
    progress_callback: Optional[Callable[[str, float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    if not render_js:
        return {
            "render_js_requested": False,
            "render_js_available": False,
            "render_js_executed": False,
            "candidate_count": 0,
            "executed_page_count": 0,
            "changed_page_count": 0,
            "reason": "not_requested",
            "note": "JS rendering was not requested for this audit.",
            "rendered_pages": [],
        }

    runtime = _playwright_runtime_status()
    if not runtime["available"]:
        return {
            "render_js_requested": True,
            "render_js_available": False,
            "render_js_executed": False,
            "candidate_count": 0,
            "executed_page_count": 0,
            "changed_page_count": 0,
            "reason": runtime["reason"],
            "note": "Playwright is unavailable, so SignalAtlas kept the raw-HTML audit baseline only.",
            "detail": runtime["detail"],
            "rendered_pages": [],
        }

    page_by_url = {page.get("final_url") or page.get("url"): page for page in pages}
    candidates: List[str] = []
    for candidate in [entry_url] + [
        page.get("final_url") or page.get("url")
        for page in pages
        if page.get("shell_like")
    ]:
        clean = str(candidate or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
        if len(candidates) >= MAX_RENDER_PROBES:
            break

    rendered_pages: List[Dict[str, Any]] = []
    changed_count = 0

    for index, candidate in enumerate(candidates, start=1):
        if cancel_check and cancel_check():
            raise RuntimeError("SignalAtlas audit cancelled")
        if progress_callback:
            progress_callback(
                "render",
                min(75, 65 + (index * 4)),
                f"Rendering JS for {candidate}",
            )
        rendered = _render_page_with_playwright(candidate)
        raw_page = page_by_url.get(candidate)
        if rendered.get("executed") and raw_page is not None:
            raw_words = int(raw_page.get("word_count") or 0)
            rendered_words = int(rendered.get("word_count") or 0)
            word_delta = rendered_words - raw_words
            changed = (
                (raw_page.get("shell_like") and rendered_words >= max(150, raw_words + 80))
                or word_delta >= 120
                or bool(rendered.get("title") and not raw_page.get("title"))
            )
            raw_page["render_js_executed"] = True
            raw_page["rendered_word_count"] = rendered_words
            raw_page["rendered_shell_like"] = bool(rendered.get("shell_like"))
            raw_page["render_word_delta"] = word_delta
            raw_page["render_changed_content"] = changed
            if changed:
                changed_count += 1
                raw_page.setdefault("classification_reasons", []).append(
                    f"Rendered probe exposed richer HTML content ({rendered_words} words vs {raw_words} raw)."
                )
            elif rendered.get("executed"):
                raw_page.setdefault("classification_reasons", []).append(
                    "Rendered probe did not materially change the visible content sample."
                )
        rendered_pages.append({
            "url": candidate,
            "executed": bool(rendered.get("executed")),
            "reason": rendered.get("reason", ""),
            "detail": rendered.get("detail", ""),
            "word_count": int(rendered.get("word_count") or 0),
            "shell_like": bool(rendered.get("shell_like")),
            "title": rendered.get("title", ""),
        })

    executed_count = sum(1 for item in rendered_pages if item.get("executed"))
    if executed_count:
        note = (
            "Playwright rendered a bounded sample of pages to compare raw HTML against post-JS content."
        )
        reason = "executed"
    else:
        note = "Playwright was available but could not complete a render probe on the selected pages."
        reason = "execution_failed"

    return {
        "render_js_requested": True,
        "render_js_available": True,
        "render_js_executed": executed_count > 0,
        "candidate_count": len(candidates),
        "executed_page_count": executed_count,
        "changed_page_count": changed_count,
        "reason": reason,
        "note": note,
        "rendered_pages": rendered_pages,
    }


def _classify_site(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    signatures = Counter()
    render_signals = Counter()
    shell_pages = 0
    reasons: List[str] = []
    for page in pages:
        signatures.update(page.get("framework_signatures") or [])
        render_signals.update(page.get("render_signals") or [])
        if page.get("shell_like"):
            shell_pages += 1
        reasons.extend(page.get("classification_reasons") or [])

    top_signature = signatures.most_common(1)[0][0] if signatures else "custom"
    shell_ratio = float(shell_pages) / float(len(pages) or 1)

    platform = "Custom"
    rendering = "hybrid"
    seo_risk = "moderate"
    if top_signature == "wordpress":
        platform = "WordPress"
        rendering = "server_rendered"
        seo_risk = "low"
    elif top_signature == "shopify":
        platform = "Shopify"
        rendering = "hybrid"
        seo_risk = "moderate"
    elif top_signature == "webflow":
        platform = "Webflow"
        rendering = "server_rendered"
        seo_risk = "low"
    elif top_signature == "astro":
        platform = "Astro"
        rendering = "ssg"
        seo_risk = "low"
    elif top_signature == "nextjs":
        platform = "Next.js"
        rendering = "hybrid" if shell_ratio > 0.34 else "server_rendered"
        seo_risk = "high" if shell_ratio > 0.5 else "moderate"
    elif top_signature == "nuxt":
        platform = "Nuxt"
        rendering = "hybrid" if shell_ratio > 0.34 else "server_rendered"
        seo_risk = "high" if shell_ratio > 0.5 else "moderate"
    elif top_signature in {"react_spa", "vite"}:
        platform = "Custom React/Vite"
        rendering = "spa"
        seo_risk = "high"

    if shell_ratio >= 0.6:
        rendering = "spa"
        seo_risk = "high"
        reasons.append("A majority of sampled pages look like JS shells.")

    if top_signature == "nextjs" and any("__NEXT_DATA__" in " ".join(page.get("classification_reasons") or []) for page in pages):
        reasons.append("Next.js signals were confirmed by framework markers in the sampled HTML.")

    return {
        "platform": platform,
        "rendering": rendering,
        "seo_risk": seo_risk,
        "top_signature": top_signature,
        "signature_counts": dict(signatures),
        "render_signal_counts": dict(render_signals),
        "reasons": reasons[:18],
    }


def _is_blog_like(url: str, title: str) -> bool:
    text = f"{url} {title}".lower()
    return any(marker in text for marker in ("/blog", "/news", "/articles", "/guides", "/posts"))


def _parse_robots(session: requests.Session, entry_url: str) -> Dict[str, Any]:
    parsed = urlparse(entry_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    result = {
        "url": robots_url,
        "found": False,
        "status_code": 0,
        "allowed": True,
        "sitemaps": [],
        "rules_sample": [],
    }
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = session.get(robots_url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        result["status_code"] = response.status_code
        if response.ok:
            result["found"] = True
            content = response.text or ""
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            result["rules_sample"] = lines[:24]
            result["sitemaps"] = [line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:")]
            parser.parse(lines)
            result["allowed"] = parser.can_fetch(USER_AGENT, entry_url)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _parse_sitemap_xml(content: str) -> Tuple[List[str], List[str]]:
    urls: List[str] = []
    indexes: List[str] = []
    if not content:
        return urls, indexes
    locs = re.findall(r"<loc>(.*?)</loc>", content, flags=re.I | re.S)
    if "<sitemapindex" in content.lower():
        indexes = [unescape(item.strip()) for item in locs]
    else:
        urls = [unescape(item.strip()) for item in locs]
    return urls, indexes


def _discover_sitemaps(session: requests.Session, entry_url: str, robots: Dict[str, Any]) -> Dict[str, Any]:
    parsed = urlparse(entry_url)
    candidates = list(robots.get("sitemaps") or [])
    default = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    if default not in candidates:
        candidates.append(default)

    seen = set()
    sitemap_urls: List[str] = []
    sitemap_indexes: List[str] = []
    fetched: List[Dict[str, Any]] = []

    while candidates and len(fetched) < 8:
        url = _clean_url(candidates.pop(0))
        if url in seen:
            continue
        seen.add(url)
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
            item = {"url": url, "status_code": response.status_code, "found": bool(response.ok)}
            if response.ok:
                urls, indexes = _parse_sitemap_xml(response.text or "")
                item["url_count"] = len(urls)
                item["index_count"] = len(indexes)
                sitemap_urls.extend(urls)
                sitemap_indexes.extend(indexes)
                for nested in indexes:
                    if nested not in seen:
                        candidates.append(nested)
            fetched.append(item)
        except Exception as exc:
            fetched.append({"url": url, "found": False, "error": str(exc)})

    unique_urls = []
    url_seen = set()
    for url in sitemap_urls:
        clean = _clean_url(url)
        if clean not in url_seen:
            unique_urls.append(clean)
            url_seen.add(clean)

    return {
        "found": any(item.get("found") for item in fetched),
        "files": fetched,
        "urls": unique_urls,
        "indexes": sitemap_indexes,
    }


def _extract_page_snapshot(
    session: requests.Session,
    url: str,
    host: str,
    depth: int,
) -> Dict[str, Any]:
    response = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    final_url = _clean_url(response.url)
    content_type = str(response.headers.get("content-type", ""))
    page: Dict[str, Any] = {
        "url": url,
        "final_url": final_url,
        "status_code": response.status_code,
        "content_type": content_type,
        "crawl_depth": depth,
        "framework_signatures": [],
        "render_signals": [],
        "classification_reasons": [],
        "internal_links": [],
        "external_link_count": 0,
        "heading_counts": {},
        "hreflang": [],
        "structured_data_types": [],
        "open_graph": {},
        "twitter_cards": {},
        "word_count": 0,
        "image_total": 0,
        "image_missing_alt": 0,
        "shell_like": False,
        "template_signature": _template_signature(final_url),
        "has_blog_signals": False,
    }
    if not _is_http_html(response):
        page["classification_reasons"].append("Non-HTML response; metadata extraction skipped.")
        return page

    html = response.text or ""
    plain_text = _text_content(html)
    page["word_count"] = len(plain_text.split())
    page["text_hash"] = _hash_text(plain_text)
    page["content_hash"] = _hash_text(re.sub(r"\s+", " ", html))

    if BeautifulSoup is None:
        page["classification_reasons"].append("BeautifulSoup unavailable; using reduced extraction.")
        page["render_signals"], page["shell_like"], extra_reasons = _render_signals(html, plain_text)
        page["classification_reasons"].extend(extra_reasons)
        return page

    soup = BeautifulSoup(html, "html.parser")
    page["title"] = (soup.title.get_text(" ", strip=True) if soup.title else "")[:240]
    page["meta_description"] = _meta_content(soup, "description")
    page["canonical"] = str((soup.find("link", rel=lambda rel: rel and "canonical" in str(rel).lower()) or {}).get("href") or "").strip()

    heading_counts = {}
    for level in ("h1", "h2", "h3", "h4"):
        heading_counts[level] = len(soup.find_all(level))
    page["heading_counts"] = heading_counts
    first_h1 = soup.find("h1")
    page["h1"] = first_h1.get_text(" ", strip=True)[:240] if first_h1 else ""

    robots_meta = _meta_content(soup, "robots")
    x_robots = str(response.headers.get("x-robots-tag", "")).strip()
    robots_blob = f"{robots_meta},{x_robots}".lower()
    page["noindex"] = "noindex" in robots_blob
    page["nofollow"] = "nofollow" in robots_blob
    page["x_robots_tag"] = x_robots

    hreflang = []
    for tag in soup.find_all("link", rel=lambda rel: rel and "alternate" in str(rel).lower(), hreflang=True):
        hreflang.append({
            "lang": str(tag.get("hreflang") or "").strip(),
            "href": str(tag.get("href") or "").strip(),
        })
    page["hreflang"] = hreflang[:24]

    structured_types = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        structured_types.append("ld+json")
        content = script.string or script.get_text(" ", strip=True)
        if not content:
            continue
        try:
            parsed_json = json.loads(content)
            nodes = parsed_json if isinstance(parsed_json, list) else [parsed_json]
            for node in nodes:
                if isinstance(node, dict):
                    node_type = node.get("@type")
                    if isinstance(node_type, list):
                        structured_types.extend(str(item) for item in node_type[:6])
                    elif node_type:
                        structured_types.append(str(node_type))
        except Exception:
            continue
    dedup_types = []
    type_seen = set()
    for item in structured_types:
        if item not in type_seen:
            dedup_types.append(item)
            type_seen.add(item)
    page["structured_data_count"] = len(dedup_types)
    page["structured_data_types"] = dedup_types[:12]

    page["open_graph"] = _all_meta_contents(soup, "og:title", "og:description", "og:type", "og:image")
    page["twitter_cards"] = _all_meta_contents(soup, "twitter:card", "twitter:title", "twitter:description", "twitter:image")

    internal_links, external_links = _extract_internal_links(soup, final_url, host)
    page["internal_links"] = internal_links
    page["external_link_count"] = external_links

    images = soup.find_all("img")
    page["image_total"] = len(images)
    page["image_missing_alt"] = sum(1 for image in images if not str(image.get("alt") or "").strip())

    signatures, reasons = _framework_signatures(html, dict(response.headers))
    render_signals, shell_like, render_reasons = _render_signals(html, plain_text)
    page["framework_signatures"] = signatures
    page["render_signals"] = render_signals
    page["shell_like"] = shell_like
    page["classification_reasons"] = reasons + render_reasons
    page["has_blog_signals"] = _is_blog_like(final_url, page["title"])
    return page


def _build_template_clusters(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clusters: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        key = page.get("template_signature") or "/"
        cluster = clusters.setdefault(
            key,
            {
                "signature": key,
                "count": 0,
                "sample_urls": [],
                "avg_word_count": 0.0,
                "shell_like_count": 0,
                "blog_like_count": 0,
            },
        )
        cluster["count"] += 1
        cluster["avg_word_count"] += float(page.get("word_count") or 0)
        cluster["shell_like_count"] += 1 if page.get("shell_like") else 0
        cluster["blog_like_count"] += 1 if page.get("has_blog_signals") else 0
        if len(cluster["sample_urls"]) < 4:
            cluster["sample_urls"].append(page.get("final_url") or page.get("url"))
    rows = []
    for cluster in clusters.values():
        count = max(1, int(cluster["count"]))
        cluster["avg_word_count"] = round(float(cluster["avg_word_count"]) / count, 1)
        rows.append(cluster)
    rows.sort(key=lambda item: item["count"], reverse=True)
    return rows


def _finding(
    identifier: str,
    *,
    title: str,
    url: str,
    scope: str,
    category: str,
    bucket: str,
    severity: str,
    confidence: str,
    impact: str,
    evidence: Iterable[str],
    diagnostic: str,
    probable_cause: str,
    recommended_fix: str,
    acceptance: str,
) -> Dict[str, Any]:
    dev_prompt = (
        "You are fixing a JoyBoy SignalAtlas audit issue.\n"
        f"Category: {category}\n"
        f"URL or scope: {url or scope}\n"
        f"Diagnosis: {diagnostic}\n"
        f"Recommended fix: {recommended_fix}\n"
        f"Acceptance criteria: {acceptance}\n"
        "Return a concise implementation plan and the exact code or configuration change needed."
    )
    content_prompt = (
        "You are helping remediate an SEO content issue.\n"
        f"URL or scope: {url or scope}\n"
        f"Diagnosis: {diagnostic}\n"
        f"Recommended fix: {recommended_fix}\n"
        f"Acceptance criteria: {acceptance}\n"
        "Return replacement copy or editorial changes only."
    )
    seo_prompt = (
        "You are reviewing a structured SEO audit issue.\n"
        f"Category: {category}\n"
        f"URL or scope: {url or scope}\n"
        f"Evidence: {' | '.join(str(item) for item in evidence)}\n"
        f"Diagnosis: {diagnostic}\n"
        f"Recommended fix: {recommended_fix}\n"
        "Return the prioritized remediation steps, expected impact, and the validation checklist."
    )
    return {
        "id": identifier,
        "title": title,
        "url": url,
        "scope": scope,
        "category": category,
        "bucket": bucket,
        "severity": severity,
        "confidence": confidence,
        "expected_impact": impact,
        "evidence": list(evidence),
        "diagnostic": diagnostic,
        "probable_cause": probable_cause,
        "recommended_fix": recommended_fix,
        "acceptance_criteria": acceptance,
        "dev_prompt": dev_prompt,
        "content_prompt": content_prompt,
        "seo_prompt": seo_prompt,
    }


def _build_findings(
    pages: List[Dict[str, Any]],
    *,
    target_url: str,
    robots: Dict[str, Any],
    sitemaps: Dict[str, Any],
    site_classification: Dict[str, Any],
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    page_by_url = {page.get("final_url") or page.get("url"): page for page in pages}
    homepage = page_by_url.get(target_url) or (pages[0] if pages else {})

    if not robots.get("found"):
        findings.append(_finding(
            "robots-missing",
            title="robots.txt missing",
            url=robots.get("url", ""),
            scope="site",
            category="robots",
            bucket="crawl_discovery",
            severity="medium",
            confidence="Confirmed",
            impact="Medium",
            evidence=[robots.get("url", "")],
            diagnostic="No robots.txt file was returned on the sampled host.",
            probable_cause="The site does not expose crawler directives at the expected path.",
            recommended_fix="Publish a minimal robots.txt file and declare sitemap locations explicitly.",
            acceptance="robots.txt returns HTTP 200 and contains clear crawler rules plus sitemap directives.",
        ))

    if not sitemaps.get("found"):
        findings.append(_finding(
            "sitemap-missing",
            title="Sitemap not discovered",
            url=urlparse(target_url)._replace(path="/sitemap.xml").geturl(),
            scope="site",
            category="sitemap",
            bucket="crawl_discovery",
            severity="medium",
            confidence="Strong signal",
            impact="High",
            evidence=[robots.get("url", ""), "sitemap.xml lookup"],
            diagnostic="SignalAtlas could not discover a sitemap index or sitemap.xml during the public crawl.",
            probable_cause="The sitemap is missing, blocked, or published at a non-standard location without robots.txt hints.",
            recommended_fix="Expose a sitemap.xml or sitemap index and reference it from robots.txt.",
            acceptance="At least one sitemap file is reachable and references canonical crawlable URLs.",
        ))

    if homepage.get("status_code", 0) >= 500:
        findings.append(_finding(
            "homepage-5xx",
            title="Homepage returns a server error",
            url=homepage.get("final_url") or homepage.get("url") or target_url,
            scope="site",
            category="http_status",
            bucket="indexability",
            severity="critical",
            confidence="Confirmed",
            impact="Critical",
            evidence=[f"HTTP {homepage.get('status_code')}"],
            diagnostic="The entry page returned a 5XX response during the crawl.",
            probable_cause="The origin or application failed before returning a valid HTML document.",
            recommended_fix="Restore a stable 200 response for the homepage before deeper SEO work.",
            acceptance="The homepage returns HTTP 200 consistently with valid HTML.",
        ))

    if homepage.get("noindex"):
        findings.append(_finding(
            "homepage-noindex",
            title="Homepage is marked noindex",
            url=homepage.get("final_url") or target_url,
            scope="page",
            category="indexability",
            bucket="indexability",
            severity="critical",
            confidence="Confirmed",
            impact="Critical",
            evidence=[homepage.get("x_robots_tag", ""), "meta robots noindex"],
            diagnostic="The homepage exposes noindex directives.",
            probable_cause="A staging directive or broad robots policy leaked into production.",
            recommended_fix="Remove the noindex directive from the homepage and revalidate deployment defaults.",
            acceptance="Homepage HTML and headers no longer contain noindex and the page remains crawlable.",
        ))

    shell_like_pages = [page for page in pages if page.get("shell_like")]
    if shell_like_pages:
        sample = shell_like_pages[0]
        findings.append(_finding(
            "js-shell-risk",
            title="Initial HTML looks JS-heavy",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="rendering",
            bucket="rendering_delivery",
            severity="high" if site_classification.get("seo_risk") == "high" else "medium",
            confidence="Strong signal",
            impact="High",
            evidence=sample.get("classification_reasons") or ["Thin initial HTML", "App shell markers"],
            diagnostic="Several sampled pages expose very little meaningful HTML before client-side hydration.",
            probable_cause="The site relies heavily on client-side rendering or an app shell with delayed content injection.",
            recommended_fix="Ensure critical content, metadata, canonicals, and links are present in the initial HTML response.",
            acceptance="Sampled pages return crawlable HTML with meaningful body copy and metadata before JS execution.",
        ))

    pages_without_title = [page for page in pages if not page.get("title")]
    if pages_without_title:
        sample = pages_without_title[0]
        findings.append(_finding(
            "missing-title",
            title="Pages missing meta title",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="metadata",
            bucket="metadata_semantics",
            severity="high",
            confidence="Confirmed",
            impact="High",
            evidence=[f"{len(pages_without_title)} sampled page(s) without a title tag"],
            diagnostic="At least one sampled page is missing a title element.",
            probable_cause="The template does not set a document title for every route.",
            recommended_fix="Add unique server-side titles to every indexable template.",
            acceptance="All sampled HTML documents contain a non-empty, route-specific title tag.",
        ))

    pages_without_description = [page for page in pages if not page.get("meta_description")]
    if pages_without_description:
        sample = pages_without_description[0]
        findings.append(_finding(
            "missing-description",
            title="Pages missing meta description",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="metadata",
            bucket="metadata_semantics",
            severity="medium",
            confidence="Confirmed",
            impact="Medium",
            evidence=[f"{len(pages_without_description)} sampled page(s) without a meta description"],
            diagnostic="The sampled templates do not always publish a meta description.",
            probable_cause="Description fields are not generated or omitted on secondary pages.",
            recommended_fix="Add concise, route-specific descriptions to each indexable page type.",
            acceptance="All key templates return a non-empty meta description aligned with the page intent.",
        ))

    missing_h1 = [page for page in pages if not page.get("h1")]
    if missing_h1:
        sample = missing_h1[0]
        findings.append(_finding(
            "missing-h1",
            title="Pages missing H1 heading",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="headings",
            bucket="metadata_semantics",
            severity="medium",
            confidence="Confirmed",
            impact="Medium",
            evidence=[f"{len(missing_h1)} sampled page(s) without an H1"],
            diagnostic="One or more sampled templates have no primary H1 heading.",
            probable_cause="Content hierarchy is not enforced consistently across templates.",
            recommended_fix="Ensure each indexable page exposes exactly one descriptive H1 in the main content.",
            acceptance="Sampled pages contain a visible, route-relevant H1 in the body.",
        ))

    alt_missing = [page for page in pages if page.get("image_missing_alt", 0) > 0]
    if alt_missing:
        sample = alt_missing[0]
        findings.append(_finding(
            "images-missing-alt",
            title="Images missing alt text",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="images",
            bucket="metadata_semantics",
            severity="low",
            confidence="Confirmed",
            impact="Low",
            evidence=[f"{sample.get('image_missing_alt', 0)} image(s) missing alt on {sample.get('final_url')}"],
            diagnostic="Some sampled images are missing descriptive alt attributes.",
            probable_cause="Image components or CMS entries do not enforce alt text.",
            recommended_fix="Populate meaningful alt text on informative images and leave decorative images empty intentionally.",
            acceptance="Informative sampled images expose alt text; decorative images are explicitly empty-alt.",
        ))

    thin_pages = [page for page in pages if int(page.get("word_count") or 0) < 180 and page.get("status_code", 0) < 400]
    if len(thin_pages) >= max(2, len(pages) // 3):
        sample = thin_pages[0]
        findings.append(_finding(
            "thin-content",
            title="Large share of sampled pages are thin",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="content",
            bucket="content_depth_blog",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(thin_pages)} of {len(pages)} sampled pages have under 180 visible words"],
            diagnostic="A meaningful portion of the crawl exposes very short visible content.",
            probable_cause="Template placeholders, sparse landing pages, or overly shallow article bodies.",
            recommended_fix="Expand key pages with genuinely useful copy, internal anchors, and supporting context.",
            acceptance="Core templates exceed minimal content depth and expose substantial visible text in HTML.",
        ))

    duplicates = Counter(page.get("text_hash") for page in pages if page.get("text_hash"))
    duplicate_hashes = {hash_value for hash_value, count in duplicates.items() if count > 1}
    if duplicate_hashes:
        dup_pages = [page for page in pages if page.get("text_hash") in duplicate_hashes]
        sample = dup_pages[0]
        findings.append(_finding(
            "duplicate-content",
            title="Quasi-duplicate content detected",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="content",
            bucket="content_depth_blog",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(dup_pages)} sampled pages share near-identical extracted text"],
            diagnostic="The sampled crawl surfaced repeated or near-repeated content bodies.",
            probable_cause="Duplicated templates, paginated clones, parameter variants, or copied boilerplate pages.",
            recommended_fix="Consolidate duplicates with canonicals, redirects, or differentiated content.",
            acceptance="Duplicate templates are consolidated and canonical targets are consistent.",
        ))

    orphan_like = []
    internal_linked = {link for page in pages for link in page.get("internal_links") or []}
    for url in sitemaps.get("urls") or []:
        if url not in internal_linked and url not in {page.get("final_url") for page in pages}:
            orphan_like.append(url)
    if orphan_like:
        findings.append(_finding(
            "orphan-like-pages",
            title="Sitemap URLs look weakly linked",
            url=orphan_like[0],
            scope="site",
            category="internal_linking",
            bucket="architecture_linking",
            severity="medium",
            confidence="Estimated",
            impact="Medium",
            evidence=[f"{len(orphan_like)} sitemap URL(s) were not seen in the sampled internal link graph"],
            diagnostic="Some URLs referenced by the sitemap were not discovered through internal links during the bounded crawl.",
            probable_cause="Weak navigation, deep architecture, or sitemap entries that are isolated from the main site graph.",
            recommended_fix="Surface important sitemap URLs from relevant navigation, hubs, or contextual links.",
            acceptance="Important sitemap URLs are reachable through internal links within a reasonable click depth.",
        ))

    blog_pages = [page for page in pages if page.get("has_blog_signals")]
    if not blog_pages:
        findings.append(_finding(
            "blog-surface-absent",
            title="No blog/editorial surface detected",
            url=target_url,
            scope="site",
            category="content_strategy",
            bucket="content_depth_blog",
            severity="low",
            confidence="Estimated",
            impact="Medium",
            evidence=["No sampled URLs matched common editorial patterns such as /blog, /guides, or /news"],
            diagnostic="The sampled crawl did not expose a clear editorial surface or knowledge hub.",
            probable_cause="The site may rely entirely on commercial pages or the editorial surface is deeply buried.",
            recommended_fix="If content-led acquisition matters for the niche, create an editorial architecture tied to core topics.",
            acceptance="The site exposes a crawlable editorial hub with clear topic clusters or deliberately documents why one is unnecessary.",
        ))

    if not homepage.get("structured_data_count"):
        findings.append(_finding(
            "structured-data-missing",
            title="Structured data absent on homepage sample",
            url=homepage.get("final_url") or target_url,
            scope="page",
            category="structured_data",
            bucket="visibility_readiness",
            severity="low",
            confidence="Confirmed",
            impact="Low",
            evidence=[homepage.get("final_url") or target_url],
            diagnostic="No structured data types were detected on the sampled homepage.",
            probable_cause="Schema markup is not implemented or injected client-side only.",
            recommended_fix="Add stable JSON-LD for the relevant entity types directly in the initial HTML.",
            acceptance="Homepage HTML includes valid JSON-LD that matches the page intent.",
        ))

    if not homepage.get("open_graph"):
        findings.append(_finding(
            "open-graph-missing",
            title="Open Graph metadata missing on homepage sample",
            url=homepage.get("final_url") or target_url,
            scope="page",
            category="social_meta",
            bucket="visibility_readiness",
            severity="low",
            confidence="Confirmed",
            impact="Low",
            evidence=[homepage.get("final_url") or target_url],
            diagnostic="No Open Graph metadata was detected on the sampled homepage.",
            probable_cause="Social sharing metadata is not set by the main layout.",
            recommended_fix="Add core Open Graph and Twitter metadata to the main templates.",
            acceptance="Homepage and key templates expose OG title, description, and image metadata in HTML.",
        ))

    if homepage.get("canonical") and _clean_url(urljoin(homepage.get("final_url") or target_url, homepage["canonical"])) != _clean_url(homepage.get("final_url") or target_url):
        findings.append(_finding(
            "homepage-canonical-mismatch",
            title="Homepage canonical points elsewhere",
            url=homepage.get("final_url") or target_url,
            scope="page",
            category="canonical",
            bucket="indexability",
            severity="high",
            confidence="Confirmed",
            impact="High",
            evidence=[homepage.get("canonical", "")],
            diagnostic="The homepage canonical does not self-reference the sampled final URL.",
            probable_cause="Canonical logic is using a stale host, wrong locale root, or staging domain.",
            recommended_fix="Point the homepage canonical to the preferred public homepage URL.",
            acceptance="Homepage canonical matches the intended live homepage without cross-domain drift.",
        ))

    return findings


def _build_visibility_signals(
    robots: Dict[str, Any],
    sitemaps: Dict[str, Any],
    classification: Dict[str, Any],
    pages: List[Dict[str, Any]],
    owner_context: Optional[Dict[str, Any]] = None,
    render_detection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    owner_context = owner_context or {}
    render_detection = render_detection or {}
    owner_integrations = {
        item.get("id"): item
        for item in (owner_context.get("integrations") or [])
        if isinstance(item, dict)
    }
    gsc = owner_integrations.get("google_search_console") or {}
    google_status = "Unknown"
    google_confidence = "Unknown"
    google_note = "Public audit mode cannot confirm exact Google indexing without an official source such as Search Console."
    if gsc.get("status") == "confirmed":
        google_status = "Confirmed"
        google_confidence = "Confirmed"
        google_note = (
            "Verified Search Console property access confirmed this site ownership context. "
            "SignalAtlas still does not infer exact index counts without explicit official metrics."
        )
    elif owner_context.get("mode") == "verified_owner":
        google_note = gsc.get("detail") or "Verified owner mode was requested, but no confirmed Search Console property was available for this target."

    sitemap_status = "Strong signal" if sitemaps.get("found") else "Estimated"
    sitemap_confidence = "Strong signal" if sitemaps.get("found") else "Estimated"
    if gsc.get("status") == "confirmed" and gsc.get("sitemaps"):
        sitemap_status = "Confirmed"
        sitemap_confidence = "Confirmed"

    js_confidence = "Strong signal"
    js_note = "Based on sampled initial HTML, app-shell markers, and framework signatures."
    if render_detection.get("render_js_executed"):
        js_confidence = "Confirmed"
        if int(render_detection.get("changed_page_count") or 0) > 0:
            js_note = "Confirmed by a bounded Playwright render probe comparing raw HTML with post-JS content."
        else:
            js_note = "Playwright render probes were executed and did not materially change the sampled content."
    elif render_detection.get("render_js_requested") and not render_detection.get("render_js_executed"):
        js_note = render_detection.get("note") or js_note

    return {
        "google": {
            "status": google_status,
            "confidence": google_confidence,
            "note": google_note,
        },
        "bing": {
            "status": "Estimated",
            "confidence": "Estimated",
            "note": "Bing ecosystem visibility is inferred from crawlability, metadata, and sitemap coherence only.",
        },
        "indexnow": {
            "status": "Unknown",
            "confidence": "Unknown",
            "note": "IndexNow support cannot be confirmed in public mode without owner-side validation.",
        },
        "crawlability": {
            "status": "Confirmed" if robots.get("allowed", True) else "Blocked",
            "confidence": "Confirmed",
            "note": "Derived from robots.txt presence, crawl access, and sampled internal linking.",
        },
        "sitemap_coherence": {
            "status": sitemap_status,
            "confidence": sitemap_confidence,
            "note": "Based on sitemap discovery and the sampled crawl graph.",
        },
        "js_render_risk": {
            "status": classification.get("seo_risk", "moderate"),
            "confidence": js_confidence,
            "note": js_note,
        },
    }


def run_site_audit(
    target: str,
    *,
    mode: str = "public",
    max_pages: int = 12,
    render_js: bool = False,
    progress_callback: Optional[Callable[[str, float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    start = time.time()
    started_at = utc_now_iso()
    entry_url, host = _normalize_target(target)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    def emit(phase: str, progress: float, message: str) -> None:
        if progress_callback:
            progress_callback(phase, progress, message)

    def ensure_not_cancelled() -> None:
        if cancel_check and cancel_check():
            raise RuntimeError("SignalAtlas audit cancelled")

    emit("crawl", 6, "Preparing crawl target")
    ensure_not_cancelled()
    robots = _parse_robots(session, entry_url)

    emit("crawl", 12, "Discovering sitemap signals")
    ensure_not_cancelled()
    sitemaps = _discover_sitemaps(session, entry_url, robots)

    queue: Deque[Tuple[str, int]] = deque()
    seen = set()
    for candidate in [entry_url] + list(sitemaps.get("urls") or [])[: max_pages]:
        clean = _clean_url(candidate)
        if _same_host(clean, host) and clean not in seen:
            queue.append((clean, 0))
            seen.add(clean)

    pages: List[Dict[str, Any]] = []
    discovered_urls = set(seen)
    broken_urls = set()

    while queue and len(pages) < max_pages:
        ensure_not_cancelled()
        current, depth = queue.popleft()
        emit("crawl", 12 + ((len(pages) / float(max_pages or 1)) * 46), f"Crawling {current}")
        try:
            page = _extract_page_snapshot(session, current, host, depth)
            pages.append(page)
            if page.get("status_code", 0) >= 400:
                broken_urls.add(page.get("final_url") or current)
                continue
            for link in page.get("internal_links") or []:
                clean = _clean_url(link)
                if clean in seen or not _same_host(clean, host):
                    continue
                seen.add(clean)
                discovered_urls.add(clean)
                if len(seen) <= max_pages * 3:
                    queue.append((clean, depth + 1))
        except Exception as exc:
            broken_urls.add(current)
            pages.append({
                "url": current,
                "final_url": current,
                "status_code": 0,
                "content_type": "",
                "crawl_depth": depth,
                "framework_signatures": [],
                "render_signals": [],
                "classification_reasons": [str(exc)],
                "internal_links": [],
                "external_link_count": 0,
                "heading_counts": {},
                "hreflang": [],
                "structured_data_types": [],
                "open_graph": {},
                "twitter_cards": {},
                "word_count": 0,
                "image_total": 0,
                "image_missing_alt": 0,
                "shell_like": False,
                "template_signature": _template_signature(current),
                "has_blog_signals": _is_blog_like(current, ""),
            })

    emit("extract", 65, "Extracting technical signals")
    ensure_not_cancelled()
    classification = _classify_site(pages)
    render_detection = _apply_render_probe(
        pages,
        entry_url,
        render_js=render_js,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    owner_context = build_owner_context(entry_url, mode=mode)
    visibility = _build_visibility_signals(
        robots,
        sitemaps,
        classification,
        pages,
        owner_context=owner_context,
        render_detection=render_detection,
    )
    template_clusters = _build_template_clusters(pages)

    findings = _build_findings(
        pages,
        target_url=entry_url,
        robots=robots,
        sitemaps=sitemaps,
        site_classification=classification,
    )

    emit("score", 76, "Scoring technical findings")
    score_payload = score_findings(findings, pages_analyzed=len(pages), page_budget=max_pages)

    emit("report", 88, "Building audit report")
    summary = {
        "target": entry_url,
        "host": host,
        "mode": mode,
        "pages_crawled": len(pages),
        "pages_sampled": len(pages),
        "global_score": score_payload["global_score"],
        "coverage": score_payload["coverage"],
        "top_risk": classification.get("seo_risk", "moderate"),
        "platform": classification.get("platform", "Custom"),
        "rendering": classification.get("rendering", "hybrid"),
        "blog_detected": any(page.get("has_blog_signals") for page in pages),
        "owner_confirmed": any(
            item.get("status") == "confirmed"
            for item in (owner_context.get("integrations") or [])
            if isinstance(item, dict)
        ),
        "render_js_requested": bool(render_detection.get("render_js_requested")),
        "render_js_executed": bool(render_detection.get("render_js_executed")),
        "signals": {
            "robots": "Confirmed" if robots.get("found") else "Unknown",
            "sitemap": visibility.get("sitemap_coherence", {}).get("confidence", "Estimated"),
            "rendering": visibility.get("js_render_risk", {}).get("confidence", "Strong signal"),
        },
        "notes": [
            "Technical findings come from a deterministic crawl and extraction layer.",
            (
                "Owner-mode enrichment was confirmed through Search Console."
                if any(item.get("status") == "confirmed" for item in (owner_context.get("integrations") or []))
                else "Index coverage cannot be confirmed without an official owner integration."
            ),
            (
                "Bounded Playwright render probes were executed for JS-heavy pages."
                if render_detection.get("render_js_executed")
                else render_detection.get("note") or "Raw HTML remained the source of truth for rendering analysis."
            ),
            "LLM interpretation can be rerun later without repeating the crawl.",
        ],
    }

    finished_at = utc_now_iso()
    crawl_snapshot = {
        "started_at": started_at,
        "finished_at": finished_at,
        "entry_url": entry_url,
        "pages": pages,
        "crawled_urls": [page.get("final_url") or page.get("url") for page in pages],
        "discovered_urls": sorted(discovered_urls),
        "broken_urls": sorted(broken_urls),
        "robots": robots,
        "sitemaps": sitemaps,
        "framework_detection": classification,
        "render_detection": render_detection,
        "visibility_signals": visibility,
        "template_clusters": template_clusters,
        "page_count": len(pages),
        "duration_seconds": round(time.time() - start, 2),
    }

    remediation_items = [
        {
            "finding_id": item["id"],
            "url": item.get("url", ""),
            "category": item.get("category", ""),
            "severity": item.get("severity", ""),
            "confidence": item.get("confidence", ""),
            "expected_impact": item.get("expected_impact", ""),
            "diagnostic": item.get("diagnostic", ""),
            "probable_cause": item.get("probable_cause", ""),
            "recommended_fix": item.get("recommended_fix", ""),
            "acceptance_criteria": item.get("acceptance_criteria", ""),
            "dev_prompt": item.get("dev_prompt", ""),
            "content_prompt": item.get("content_prompt", ""),
            "seo_prompt": item.get("seo_prompt", ""),
        }
        for item in findings
    ]

    emit("report", 100, "SignalAtlas audit ready")
    return {
        "summary": summary,
        "snapshot": crawl_snapshot,
        "findings": findings,
        "scores": score_payload["categories"],
        "remediation_items": remediation_items,
        "owner_context": owner_context,
    }


def run_public_audit(
    target: str,
    *,
    max_pages: int = 12,
    render_js: bool = False,
    progress_callback: Optional[Callable[[str, float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    return run_site_audit(
        target,
        mode="public",
        max_pages=max_pages,
        render_js=render_js,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
