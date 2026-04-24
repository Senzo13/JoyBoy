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
from .providers import build_owner_context, get_signalatlas_provider_status
from .scoring import score_findings


USER_AGENT = "JoyBoy-SignalAtlas/1.0 (+https://joyboy.local)"
DEFAULT_TIMEOUT = (5, 15)
MAX_LINK_SAMPLES = 48
MAX_RENDER_PROBES = 3
CJK_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")
LOCALE_ROOT_RE = re.compile(r"^/[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?$", re.I)
SYSTEM_PATH_PREFIXES = ("/cdn-cgi/",)
CC_TLD_LANGUAGE_MAP = {
    "fr": "fr",
    "de": "de",
    "it": "it",
    "es": "es",
    "pt": "pt",
    "nl": "nl",
    "pl": "pl",
    "tr": "tr",
    "jp": "ja",
    "kr": "ko",
    "cn": "zh",
    "tw": "zh",
    "ru": "ru",
}
GEO_STRUCTURED_TYPES = {
    "organization",
    "website",
    "article",
    "newsarticle",
    "blogposting",
    "faqpage",
    "howto",
    "breadcrumblist",
    "product",
    "service",
    "localbusiness",
    "person",
}


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


def _comparison_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunparse((parsed.scheme or "https", parsed.netloc.lower(), path, "", "", ""))


def _normalized_path(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return path


def _same_normalized_url(left: str, right: str) -> bool:
    return _comparison_url(left) == _comparison_url(right)


def _is_system_url(url: str) -> bool:
    path = _normalized_path(url).lower()
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in SYSTEM_PATH_PREFIXES)


def _host_tld(host: str) -> str:
    parts = [part.strip().lower() for part in str(host or "").split(".") if part.strip()]
    if not parts:
        return ""
    return parts[-1]


def _normalize_lang_tag(value: str) -> str:
    clean = str(value or "").strip().lower().replace("_", "-")
    if not clean:
        return ""
    return clean


def _lang_root(value: str) -> str:
    clean = _normalize_lang_tag(value)
    return clean.split("-", 1)[0] if clean else ""


def _path_locale_hint(url: str) -> str:
    parts = [part for part in _normalized_path(url).split("/") if part]
    if not parts:
        return ""
    first = str(parts[0] or "").strip().lower()
    if re.fullmatch(r"[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?", first):
        return _normalize_lang_tag(first)
    return ""


def _page_language_hint(page: Dict[str, Any]) -> str:
    return _normalize_lang_tag(page.get("html_lang") or _path_locale_hint(page.get("final_url") or page.get("url") or ""))


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


def _text_metrics(text: str) -> Dict[str, Any]:
    compact = " ".join(str(text or "").split())
    if not compact:
        return {
            "word_count": 0,
            "cjk_char_count": 0,
            "content_units": 0,
            "cjk_adjusted": False,
        }
    word_count = len(compact.split())
    cjk_char_count = len(CJK_CHAR_RE.findall(compact))
    # CJK copy carries more meaning per visible character than whitespace-tokenized word counts suggest.
    content_units = max(word_count, round(cjk_char_count * 0.75))
    return {
        "word_count": word_count,
        "cjk_char_count": cjk_char_count,
        "content_units": content_units,
        "cjk_adjusted": content_units > word_count and cjk_char_count >= 80,
    }


def _probe_llms_txt(session: requests.Session, entry_url: str) -> Dict[str, Any]:
    parsed = urlparse(entry_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in ("/llms.txt", "/llms-full.txt"):
        url = f"{base}{path}"
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
        except Exception as exc:
            return {
                "found": False,
                "confidence": "Unknown",
                "status": "unknown",
                "note": str(exc),
                "url": url,
            }
        content_type = str(response.headers.get("content-type", "")).lower()
        body = str(response.text or "").strip()
        if response.ok and body and ("text/plain" in content_type or "text/markdown" in content_type or not content_type):
            return {
                "found": True,
                "confidence": "Confirmed",
                "status": "detected",
                "note": f"Detected {path} on the public host.",
                "url": url,
            }
    return {
        "found": False,
        "confidence": "Estimated",
        "status": "not_detected",
        "note": "No public llms.txt file was detected on the sampled host.",
        "url": f"{base}/llms.txt",
    }


def _excerpt(value: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    return compact[:limit]


def _normalized_text_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


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


def _parse_link_header_hreflang(header_value: str) -> List[Dict[str, str]]:
    raw = str(header_value or "").strip()
    if not raw:
        return []
    try:
        parsed_links = requests.utils.parse_header_links(raw.rstrip(">").replace(">,<", ">, <"))
    except Exception:
        return []
    entries: List[Dict[str, str]] = []
    for item in parsed_links:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("rel") or "").strip().lower()
        hreflang = str(item.get("hreflang") or "").strip()
        href = str(item.get("url") or "").strip()
        if "alternate" not in rel or not hreflang or not href:
            continue
        entries.append({"lang": hreflang, "href": href})
    return entries


def _merge_hreflang_entries(*groups: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for group in groups:
        for item in group or []:
            lang = str((item or {}).get("lang") or "").strip()
            href = str((item or {}).get("href") or "").strip()
            if not lang or not href:
                continue
            key = (_normalize_lang_tag(lang), href)
            if key in seen:
                continue
            seen.add(key)
            merged.append({"lang": lang, "href": href})
    return merged


def _is_absolute_http_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_robots_directives(robots_meta: str, x_robots: str) -> Dict[str, Any]:
    robots_blob = f"{robots_meta},{x_robots}".lower()
    max_snippet = None
    snippet_match = re.search(r"max-snippet\s*:\s*(-?\d+)", robots_blob)
    if snippet_match:
        try:
            max_snippet = int(snippet_match.group(1))
        except ValueError:
            max_snippet = None
    return {
        "robots_blob": robots_blob,
        "noindex": "noindex" in robots_blob,
        "nofollow": "nofollow" in robots_blob,
        "nosnippet": "nosnippet" in robots_blob,
        "max_snippet": max_snippet,
    }


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
            if _is_system_url(absolute):
                continue
            key = _comparison_url(absolute)
            if key not in seen:
                internal.append(absolute)
                seen.add(key)
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
    metrics = _text_metrics(plain_text)
    content_units = int(metrics["content_units"] or 0)
    reasons: List[str] = []
    signals: List[str] = []
    shell_like = False

    if script_count >= 8:
        signals.append("script_heavy")
        reasons.append("High script density compared to visible content.")
    if content_units <= 120:
        signals.append("thin_initial_html")
        reasons.append("Very little visible text in the initial HTML response.")
    if re.search(r'<div[^>]+id="(?:root|app|__next)"[^>]*>\s*</div>', raw, re.I | re.S):
        signals.append("app_shell")
        reasons.append("Primary app container is close to empty in raw HTML.")
    if "hydrate" in raw.lower():
        signals.append("hydration_signals")
        reasons.append("Hydration-related markers found in the HTML payload.")
    if ("app_shell" in signals and "thin_initial_html" in signals) or (script_count >= 12 and content_units <= 80):
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
        metrics = _text_metrics(plain_text)
        render_signals, shell_like, reasons = _render_signals(html, plain_text)
        return {
            "url": url,
            "executed": True,
            "html": html,
            "title": title[:240],
            "word_count": int(metrics["word_count"] or 0),
            "content_units": int(metrics["content_units"] or 0),
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
            raw_units = int(raw_page.get("content_units") or raw_page.get("word_count") or 0)
            rendered_units = int(rendered.get("content_units") or rendered.get("word_count") or 0)
            word_delta = rendered_units - raw_units
            changed = (
                (raw_page.get("shell_like") and rendered_units >= max(150, raw_units + 80))
                or word_delta >= 120
                or bool(rendered.get("title") and not raw_page.get("title"))
            )
            raw_page["render_js_executed"] = True
            raw_page["rendered_word_count"] = int(rendered.get("word_count") or 0)
            raw_page["rendered_content_units"] = rendered_units
            raw_page["rendered_shell_like"] = bool(rendered.get("shell_like"))
            raw_page["render_word_delta"] = word_delta
            raw_page["render_changed_content"] = changed
            if changed:
                changed_count += 1
                raw_page.setdefault("classification_reasons", []).append(
                    f"Rendered probe exposed richer HTML content ({rendered_units} content units vs {raw_units} raw)."
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
    rich_initial_html_pages = 0
    sparse_initial_html_pages = 0
    reasons: List[str] = []
    for page in pages:
        signatures.update(page.get("framework_signatures") or [])
        render_signals.update(page.get("render_signals") or [])
        if page.get("shell_like"):
            shell_pages += 1
        if (page.get("content_units") or page.get("word_count") or 0) >= 180 and page.get("h1") and not page.get("shell_like"):
            rich_initial_html_pages += 1
        if (page.get("content_units") or page.get("word_count") or 0) < 180 and (page.get("status_code") or 0) < 400:
            sparse_initial_html_pages += 1
        reasons.extend(page.get("classification_reasons") or [])

    total_pages = float(len(pages) or 1)
    top_signature = signatures.most_common(1)[0][0] if signatures else "custom"
    shell_ratio = float(shell_pages) / total_pages
    rich_ratio = float(rich_initial_html_pages) / total_pages
    sparse_ratio = float(sparse_initial_html_pages) / total_pages

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
        if shell_ratio >= 0.5:
            rendering = "spa"
            seo_risk = "high"
            reasons.append("React/Vite markers were found and a majority of sampled pages still look like JS shells.")
        elif rich_ratio >= 0.65 and shell_ratio <= 0.1:
            rendering = "ssg"
            seo_risk = "low"
            reasons.append(
                "React/Vite markers were found, but most sampled pages already deliver substantial HTML before JS."
            )
        else:
            rendering = "hybrid"
            seo_risk = "moderate"
            reasons.append(
                "React/Vite markers were found, but the sampled HTML mixes rich prerendered routes with thinner pages."
            )

    if shell_ratio >= 0.6:
        rendering = "spa"
        seo_risk = "high"
        reasons.append("A majority of sampled pages look like JS shells.")

    if top_signature == "nextjs" and any("__NEXT_DATA__" in " ".join(page.get("classification_reasons") or []) for page in pages):
        reasons.append("Next.js signals were confirmed by framework markers in the sampled HTML.")

    deduped_reasons: List[str] = []
    seen_reasons = set()
    for reason in reasons:
        label = str(reason or "").strip()
        if not label or label in seen_reasons:
            continue
        deduped_reasons.append(label)
        seen_reasons.add(label)

    return {
        "platform": platform,
        "rendering": rendering,
        "seo_risk": seo_risk,
        "top_signature": top_signature,
        "signature_counts": dict(signatures),
        "render_signal_counts": dict(render_signals),
        "shell_pages": shell_pages,
        "shell_ratio": round(shell_ratio, 3),
        "rich_initial_html_pages": rich_initial_html_pages,
        "rich_initial_html_ratio": round(rich_ratio, 3),
        "sparse_initial_html_pages": sparse_initial_html_pages,
        "sparse_initial_html_ratio": round(sparse_ratio, 3),
        "reasons": deduped_reasons[:18],
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


def _parse_sitemap_xml(content: str) -> Tuple[List[str], List[str], int]:
    urls: List[str] = []
    indexes: List[str] = []
    if not content:
        return urls, indexes, 0
    locs = re.findall(r"<loc>(.*?)</loc>", content, flags=re.I | re.S)
    alternate_count = len(re.findall(r"hreflang\s*=", content, flags=re.I))
    if "<sitemapindex" in content.lower():
        indexes = [unescape(item.strip()) for item in locs]
    else:
        urls = [unescape(item.strip()) for item in locs]
    return urls, indexes, alternate_count


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
    alternate_count = 0

    while candidates and len(fetched) < 8:
        url = _clean_url(candidates.pop(0))
        if url in seen:
            continue
        seen.add(url)
        try:
            response = session.get(url, timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT})
            item = {"url": url, "status_code": response.status_code, "found": bool(response.ok)}
            if response.ok:
                urls, indexes, alternates = _parse_sitemap_xml(response.text or "")
                item["url_count"] = len(urls)
                item["index_count"] = len(indexes)
                item["alternate_count"] = alternates
                sitemap_urls.extend(urls)
                sitemap_indexes.extend(indexes)
                alternate_count += alternates
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
        key = _comparison_url(clean)
        if key not in url_seen:
            unique_urls.append(clean)
            url_seen.add(key)

    return {
        "found": any(item.get("found") for item in fetched),
        "files": fetched,
        "urls": unique_urls,
        "indexes": sitemap_indexes,
        "alternate_count": alternate_count,
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
        "html_lang": "",
        "canonical_in_head": False,
        "canonical_relative": False,
        "structured_data_types": [],
        "open_graph": {},
        "twitter_cards": {},
        "word_count": 0,
        "content_units": 0,
        "cjk_char_count": 0,
        "visible_text_length": 0,
        "visible_text_excerpt": "",
        "body_text_excerpt": "",
        "body_html_excerpt": "",
        "robots_meta": "",
        "noindex": False,
        "nofollow": False,
        "nosnippet": False,
        "max_snippet": None,
        "x_robots_tag": "",
        "image_total": 0,
        "image_missing_alt": 0,
        "image_empty_alt": 0,
        "shell_like": False,
        "system_url": _is_system_url(final_url),
        "indexable_candidate": False,
        "template_signature": _template_signature(final_url),
        "has_blog_signals": False,
    }
    if not _is_http_html(response):
        page["classification_reasons"].append("Non-HTML response; metadata extraction skipped.")
        return page

    html = response.text or ""
    plain_text = _text_content(html)
    text_metrics = _text_metrics(plain_text)
    page["word_count"] = int(text_metrics["word_count"] or 0)
    page["content_units"] = int(text_metrics["content_units"] or 0)
    page["cjk_char_count"] = int(text_metrics["cjk_char_count"] or 0)
    page["visible_text_length"] = len(plain_text)
    page["visible_text_excerpt"] = _excerpt(plain_text)
    page["text_hash"] = _hash_text(plain_text)
    page["content_hash"] = _hash_text(re.sub(r"\s+", " ", html))

    if BeautifulSoup is None:
        page["classification_reasons"].append("BeautifulSoup unavailable; using reduced extraction.")
        page["render_signals"], page["shell_like"], extra_reasons = _render_signals(html, plain_text)
        page["classification_reasons"].extend(extra_reasons)
        return page

    soup = BeautifulSoup(html, "html.parser")
    html_tag = soup.find("html")
    page["html_lang"] = _normalize_lang_tag(
        str((html_tag or {}).get("lang") or (html_tag or {}).get("xml:lang") or "").strip()
    )
    head = soup.find("head")
    page["title"] = (soup.title.get_text(" ", strip=True) if soup.title else "")[:240]
    page["meta_description"] = _meta_content(soup, "description")
    canonical_in_head = head.find("link", rel=lambda rel: rel and "canonical" in str(rel).lower()) if head else None
    canonical_tag = canonical_in_head or soup.find("link", rel=lambda rel: rel and "canonical" in str(rel).lower())
    page["canonical"] = str((canonical_tag or {}).get("href") or "").strip()
    page["canonical_in_head"] = bool(canonical_in_head and page["canonical"])
    page["canonical_relative"] = bool(page["canonical"] and not _is_absolute_http_url(page["canonical"]))

    heading_counts = {}
    for level in ("h1", "h2", "h3", "h4"):
        heading_counts[level] = len(soup.find_all(level))
    page["heading_counts"] = heading_counts
    page["h1_count"] = heading_counts.get("h1", 0)
    first_h1 = soup.find("h1")
    page["h1"] = first_h1.get_text(" ", strip=True)[:240] if first_h1 else ""
    body_text = soup.body.get_text(" ", strip=True) if soup.body else plain_text
    page["body_text_excerpt"] = _excerpt(body_text)
    body_html = soup.body.decode_contents() if soup.body else html
    page["body_html_excerpt"] = _excerpt(body_html)

    robots_meta = _meta_content(soup, "robots")
    x_robots = str(response.headers.get("x-robots-tag", "")).strip()
    robots_directives = _extract_robots_directives(robots_meta, x_robots)
    page["robots_meta"] = robots_meta
    page["noindex"] = bool(robots_directives["noindex"])
    page["nofollow"] = bool(robots_directives["nofollow"])
    page["nosnippet"] = bool(robots_directives["nosnippet"])
    page["max_snippet"] = robots_directives["max_snippet"]
    page["x_robots_tag"] = x_robots

    html_hreflang = []
    for tag in soup.find_all("link", rel=lambda rel: rel and "alternate" in str(rel).lower(), hreflang=True):
        html_hreflang.append({
            "lang": str(tag.get("hreflang") or "").strip(),
            "href": str(tag.get("href") or "").strip(),
        })
    header_hreflang = _parse_link_header_hreflang(response.headers.get("link", ""))
    page["hreflang"] = _merge_hreflang_entries(html_hreflang, header_hreflang)[:24]

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
    page["image_missing_alt"] = sum(1 for image in images if not image.has_attr("alt"))
    page["image_empty_alt"] = sum(
        1 for image in images if image.has_attr("alt") and not str(image.get("alt") or "").strip()
    )

    signatures, reasons = _framework_signatures(html, dict(response.headers))
    render_signals, shell_like, render_reasons = _render_signals(html, plain_text)
    page["framework_signatures"] = signatures
    page["render_signals"] = render_signals
    page["shell_like"] = shell_like
    page["classification_reasons"] = reasons + render_reasons
    page["has_blog_signals"] = _is_blog_like(final_url, page["title"])
    page["indexable_candidate"] = _is_indexable_page(page)
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
                "avg_content_units": 0.0,
                "shell_like_count": 0,
                "blog_like_count": 0,
            },
        )
        cluster["count"] += 1
        cluster["avg_word_count"] += float(page.get("word_count") or 0)
        cluster["avg_content_units"] += float(page.get("content_units") or page.get("word_count") or 0)
        cluster["shell_like_count"] += 1 if page.get("shell_like") else 0
        cluster["blog_like_count"] += 1 if page.get("has_blog_signals") else 0
        if len(cluster["sample_urls"]) < 4:
            cluster["sample_urls"].append(page.get("final_url") or page.get("url"))
    rows = []
    for cluster in clusters.values():
        count = max(1, int(cluster["count"]))
        cluster["avg_word_count"] = round(float(cluster["avg_word_count"]) / count, 1)
        cluster["avg_content_units"] = round(float(cluster["avg_content_units"]) / count, 1)
        rows.append(cluster)
    rows.sort(key=lambda item: item["count"], reverse=True)
    return rows


def _render_baseline_only(render_detection: Optional[Dict[str, Any]]) -> bool:
    payload = render_detection or {}
    return bool(payload.get("render_js_requested")) and not bool(payload.get("render_js_executed"))


def _render_root_relationship(render_detection: Optional[Dict[str, Any]]) -> str:
    if _render_baseline_only(render_detection):
        return (
            "Treat this as the primary issue first. In this audit, some heading, content-depth, "
            "duplicate-like, and internal-linking findings may be downstream symptoms of the initial HTML baseline."
        )
    return (
        "Treat this as the primary issue first. Rendering delivery should be resolved before interpreting downstream "
        "content or linking symptoms."
    )


def _is_indexable_page(page: Dict[str, Any]) -> bool:
    status_code = int(page.get("status_code") or 0)
    if status_code <= 0 or status_code >= 400:
        return False
    if page.get("noindex"):
        return False
    if _is_system_url(page.get("final_url") or page.get("url") or ""):
        return False
    content_type = str(page.get("content_type") or "").lower()
    if content_type and "html" not in content_type and "xhtml" not in content_type:
        return False
    return True


def _is_self_canonical_page(page: Dict[str, Any]) -> bool:
    final_url = page.get("final_url") or page.get("url") or ""
    canonical = str(page.get("canonical") or "").strip()
    if not final_url or not canonical:
        return True
    canonical_url = _clean_url(urljoin(final_url, canonical))
    return _same_normalized_url(canonical_url, final_url)


def _homepage_canonical_allowed_alias(
    homepage: Dict[str, Any],
    target_url: str,
    sitemaps: Dict[str, Any],
) -> bool:
    final_url = homepage.get("final_url") or homepage.get("url") or target_url
    canonical = str(homepage.get("canonical") or "").strip()
    if not canonical:
        return False
    canonical_url = _clean_url(urljoin(final_url, canonical))
    if _same_normalized_url(canonical_url, final_url):
        return True
    if _normalized_path(final_url) != "/":
        return False
    if not _same_host(canonical_url, urlparse(final_url).netloc):
        return False
    canonical_path = _normalized_path(canonical_url)
    if not LOCALE_ROOT_RE.fullmatch(canonical_path):
        return False
    sitemap_keys = {_comparison_url(url) for url in sitemaps.get("urls") or []}
    return _comparison_url(final_url) not in sitemap_keys and _comparison_url(canonical_url) in sitemap_keys


def _multilingual_roots(indexable_pages: List[Dict[str, Any]], sitemap_urls: List[str]) -> List[str]:
    roots = {
        _lang_root(_page_language_hint(page))
        for page in indexable_pages
        if _page_language_hint(page)
    }
    roots.update(
        _lang_root(_path_locale_hint(url))
        for url in sitemap_urls
        if _path_locale_hint(url)
    )
    return sorted(root for root in roots if root)


def _geo_signal_snapshot(
    pages: List[Dict[str, Any]],
    llms_signal: Dict[str, Any],
) -> Dict[str, Any]:
    indexable_pages = [page for page in pages if _is_indexable_page(page)]
    schema_pages = 0
    faq_pages = 0
    article_pages = 0
    for page in indexable_pages:
        schema_types = {str(item or "").strip().lower() for item in page.get("structured_data_types") or []}
        if schema_types & GEO_STRUCTURED_TYPES:
            schema_pages += 1
        if "faqpage" in schema_types:
            faq_pages += 1
        if {"article", "newsarticle", "blogposting"} & schema_types:
            article_pages += 1

    if llms_signal.get("found"):
        return {
            "status": "Strong signal",
            "confidence": llms_signal.get("confidence", "Confirmed"),
            "note": (
                f"Detected public llms.txt support and {schema_pages} sampled page(s) with AI-friendly structured data."
                if schema_pages
                else llms_signal.get("note", "Detected public llms.txt support.")
            ),
            "llms_txt": llms_signal,
            "schema_pages": schema_pages,
            "faq_pages": faq_pages,
            "article_pages": article_pages,
        }

    if indexable_pages and schema_pages >= max(2, len(indexable_pages) // 2):
        return {
            "status": "Strong signal",
            "confidence": "Strong signal",
            "note": (
                f"{schema_pages} of {len(indexable_pages)} sampled indexable page(s) expose AI-friendly structured data "
                f"(FAQ/article/organization-style signals)."
            ),
            "llms_txt": llms_signal,
            "schema_pages": schema_pages,
            "faq_pages": faq_pages,
            "article_pages": article_pages,
        }

    if schema_pages:
        return {
            "status": "Partial signal",
            "confidence": "Estimated",
            "note": (
                f"Some sampled pages expose AI-friendly structured data ({schema_pages}/{len(indexable_pages)}), "
                "but SignalAtlas did not detect a stronger public GEO surface such as llms.txt."
            ),
            "llms_txt": llms_signal,
            "schema_pages": schema_pages,
            "faq_pages": faq_pages,
            "article_pages": article_pages,
        }

    return {
        "status": "Unknown",
        "confidence": llms_signal.get("confidence", "Estimated"),
        "note": (
            llms_signal.get("note")
            or "No strong public GEO signal was detected in the sampled HTML."
        ),
        "llms_txt": llms_signal,
        "schema_pages": schema_pages,
        "faq_pages": faq_pages,
        "article_pages": article_pages,
    }


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
    root_cause: bool = False,
    derived_from: Optional[Iterable[str]] = None,
    validation_state: str = "confirmed",
    evidence_mode: str = "public_crawl",
    relationship_summary: str = "",
) -> Dict[str, Any]:
    relation_text = relationship_summary or ""
    derived_ids = [str(item).strip() for item in (derived_from or []) if str(item).strip()]
    context_tail = []
    if root_cause:
        context_tail.append("Classification: root cause")
    elif derived_ids:
        context_tail.append(f"Likely downstream symptom of: {', '.join(derived_ids)}")
    if validation_state:
        context_tail.append(f"Validation state: {validation_state}")
    if evidence_mode:
        context_tail.append(f"Evidence mode: {evidence_mode}")
    if relation_text:
        context_tail.append(f"Relationship: {relation_text}")
    context_block = "\n".join(context_tail)
    context_suffix = f"\n{context_block}\n" if context_block else "\n"
    dev_prompt = (
        "You are fixing a JoyBoy SignalAtlas audit issue.\n"
        f"Category: {category}\n"
        f"URL or scope: {url or scope}\n"
        f"{context_suffix}"
        f"Diagnosis: {diagnostic}\n"
        f"Recommended fix: {recommended_fix}\n"
        f"Acceptance criteria: {acceptance}\n"
        "Return a concise implementation plan and the exact code or configuration change needed."
    )
    content_prompt = (
        "You are helping remediate an SEO content issue.\n"
        f"URL or scope: {url or scope}\n"
        f"{context_suffix}"
        f"Diagnosis: {diagnostic}\n"
        f"Recommended fix: {recommended_fix}\n"
        f"Acceptance criteria: {acceptance}\n"
        "Return replacement copy or editorial changes only."
    )
    seo_prompt = (
        "You are reviewing a structured SEO audit issue.\n"
        f"Category: {category}\n"
        f"URL or scope: {url or scope}\n"
        f"{context_suffix}"
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
        "root_cause": root_cause,
        "derived_from": derived_ids,
        "validation_state": validation_state,
        "evidence_mode": evidence_mode,
        "relationship_summary": relationship_summary,
    }


def _build_findings(
    pages: List[Dict[str, Any]],
    *,
    target_url: str,
    discovered_url_count: int,
    robots: Dict[str, Any],
    sitemaps: Dict[str, Any],
    site_classification: Dict[str, Any],
    render_detection: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    homepage = next(
        (
            page
            for page in pages
            if _same_normalized_url(page.get("final_url") or page.get("url") or "", target_url)
        ),
        pages[0] if pages else {},
    )
    baseline_only = _render_baseline_only(render_detection)
    indexable_pages = [page for page in pages if _is_indexable_page(page)]
    target_host = urlparse(target_url).netloc.lower()
    target_tld = _host_tld(target_host)
    sitemap_urls = [url for url in sitemaps.get("urls") or [] if not _is_system_url(url)]
    multilingual_roots = _multilingual_roots(indexable_pages, sitemap_urls)

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

    if discovered_url_count <= 8 or len(indexable_pages) <= 5:
        findings.append(_finding(
            "organic-surface-too-small",
            title="Very small crawlable surface limits organic visibility",
            url=target_url,
            scope="site",
            category="content_strategy",
            bucket="content_depth_blog",
            severity="high" if discovered_url_count <= 4 or len(indexable_pages) <= 3 else "medium",
            confidence="Confirmed",
            impact="High",
            evidence=[
                f"{discovered_url_count} URL(s) discovered in the crawl graph",
                f"{len(indexable_pages)} indexable sampled page(s)",
            ],
            diagnostic=(
                "SignalAtlas discovered a very small indexable surface. With so few crawlable pages, organic visibility usually stays limited to brand or exact-match queries."
            ),
            probable_cause=(
                "The site has very few published pages, or too much content is hidden behind weak navigation, JavaScript, or non-indexable routes."
            ),
            recommended_fix=(
                "Publish more indexable pages mapped to real search intents: core services, use cases, FAQs, comparisons, help content, and an editorial/blog surface if acquisition matters."
            ),
            acceptance=(
                "The site exposes a materially larger set of crawlable indexable pages covering core commercial and informational intents."
            ),
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

    snippet_restricted_pages = [
        page
        for page in indexable_pages
        if page.get("nosnippet") or (
            page.get("max_snippet") is not None and int(page.get("max_snippet") or 0) <= 0
        )
    ]
    if snippet_restricted_pages:
        sample = next(
            (
                page
                for page in snippet_restricted_pages
                if _same_normalized_url(page.get("final_url") or page.get("url") or "", target_url)
            ),
            snippet_restricted_pages[0],
        )
        evidence = [f"{len(snippet_restricted_pages)} sampled indexable page(s) emit nosnippet or max-snippet:0"]
        if sample.get("robots_meta"):
            evidence.append(f"meta robots: {sample.get('robots_meta')}")
        if sample.get("x_robots_tag"):
            evidence.append(f"X-Robots-Tag: {sample.get('x_robots_tag')}")
        findings.append(_finding(
            "snippet-controls-restrict-visibility",
            title="Snippet controls restrict Search and AI visibility",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site" if len(snippet_restricted_pages) > 1 else "page",
            category="search_appearance",
            bucket="visibility_readiness",
            severity="high" if _same_normalized_url(sample.get("final_url") or sample.get("url") or "", target_url) else "medium",
            confidence="Confirmed",
            impact="High",
            evidence=evidence,
            diagnostic=(
                "Some sampled pages use page-level snippet restrictions. These directives can suppress normal search snippets and, in Google, also limit or prevent direct reuse in AI Overviews and AI Mode."
            ),
            probable_cause=(
                "A conservative robots policy, legal default, or template-level SEO setting is applying nosnippet or max-snippet:0 to discovery pages."
            ),
            recommended_fix=(
                "Remove nosnippet or max-snippet:0 from pages meant to earn search snippets or AI citations, and keep these directives only where suppression is intentional."
            ),
            acceptance=(
                "Indexable pages intended for discovery no longer emit nosnippet or max-snippet:0 in meta robots or X-Robots-Tag."
            ),
        ))

    shell_like_pages = [page for page in pages if page.get("shell_like")]
    js_shell_root_active = bool(shell_like_pages)
    if shell_like_pages:
        sample = shell_like_pages[0]
        findings.append(_finding(
            "js-shell-risk",
            title="Initial HTML behaves like a JS app shell" if baseline_only else "Initial HTML looks JS-heavy",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="rendering",
            bucket="rendering_delivery",
            severity="high" if site_classification.get("seo_risk") == "high" else "medium",
            confidence="Strong signal",
            impact="High",
            evidence=sample.get("classification_reasons") or ["Thin initial HTML", "App shell markers"],
            diagnostic=(
                "Several sampled pages expose very little meaningful HTML before client-side hydration."
                if baseline_only
                else "Several sampled pages expose very little meaningful HTML before client-side hydration."
            ),
            probable_cause=(
                "The site likely relies on client-side rendering or prerenders metadata without delivering meaningful body content in the initial HTML response."
                if baseline_only
                else "The site relies heavily on client-side rendering or an app shell with delayed content injection."
            ),
            recommended_fix="Ensure critical content, metadata, canonicals, and links are present in the initial HTML response.",
            acceptance="Sampled pages return crawlable HTML with meaningful body copy and metadata before JS execution.",
            root_cause=True,
            validation_state="confirmed",
            evidence_mode="raw_html" if baseline_only else "raw_html_vs_rendered",
            relationship_summary=_render_root_relationship(render_detection),
        ))

    pages_without_title = [page for page in indexable_pages if not page.get("title")]
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

    self_canonical_pages = [page for page in indexable_pages if _is_self_canonical_page(page)]
    duplicate_titles = Counter(
        _normalized_text_key(page.get("title"))
        for page in self_canonical_pages
        if _normalized_text_key(page.get("title"))
    )
    duplicate_title_values = {value for value, count in duplicate_titles.items() if count >= 2}
    duplicate_title_pages = [
        page for page in self_canonical_pages if _normalized_text_key(page.get("title")) in duplicate_title_values
    ]
    if len(duplicate_title_pages) >= 2:
        sample = duplicate_title_pages[0]
        findings.append(_finding(
            "duplicate-title-text",
            title="Repeated title text weakens result differentiation",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="metadata",
            bucket="metadata_semantics",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(duplicate_title_pages)} sampled self-canonical page(s) share the same title text"],
            diagnostic="Multiple sampled pages reuse the same or near-identical title text.",
            probable_cause="Template defaults or CMS fallbacks are producing boilerplate titles instead of route-specific titles.",
            recommended_fix="Generate concise, distinct title text for each indexable template or URL cluster.",
            acceptance="Important sampled pages expose distinct titles that reflect their actual page content.",
        ))

    pages_without_description = [page for page in indexable_pages if not page.get("meta_description")]
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

    duplicate_descriptions = Counter(
        _normalized_text_key(page.get("meta_description"))
        for page in self_canonical_pages
        if _normalized_text_key(page.get("meta_description"))
    )
    duplicate_description_values = {value for value, count in duplicate_descriptions.items() if count >= 2}
    duplicate_description_pages = [
        page
        for page in self_canonical_pages
        if _normalized_text_key(page.get("meta_description")) in duplicate_description_values
    ]
    if len(duplicate_description_pages) >= 2:
        sample = duplicate_description_pages[0]
        findings.append(_finding(
            "duplicate-meta-description",
            title="Repeated meta descriptions weaken snippet quality",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="metadata",
            bucket="metadata_semantics",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(duplicate_description_pages)} sampled self-canonical page(s) share the same meta description"],
            diagnostic="Multiple sampled pages reuse the same or very similar meta description text.",
            probable_cause="A site-wide fallback description or boilerplate metadata is overriding page-level summaries.",
            recommended_fix="Generate unique meta descriptions for important pages, especially key landing pages, articles, and product/service URLs.",
            acceptance="Important sampled pages expose distinct meta descriptions that summarize the specific page intent.",
        ))

    missing_h1 = [page for page in indexable_pages if not page.get("h1")]
    if missing_h1:
        sample = missing_h1[0]
        findings.append(_finding(
            "missing-h1",
            title="H1 missing from the initial HTML baseline" if baseline_only and js_shell_root_active else "Pages missing H1 heading",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="headings",
            bucket="metadata_semantics",
            severity="medium",
            confidence="Confirmed",
            impact="Medium",
            evidence=[f"{len(missing_h1)} sampled page(s) without an H1"],
            diagnostic=(
                "Sampled pages do not expose an H1 in the initial HTML response."
                if baseline_only and js_shell_root_active
                else "One or more sampled templates have no primary H1 heading."
            ),
            probable_cause=(
                "The site may inject the main heading after hydration, or the initial HTML baseline may stop at an app shell."
                if baseline_only and js_shell_root_active
                else "Content hierarchy is not enforced consistently across templates."
            ),
            recommended_fix=(
                "Fix initial HTML delivery first, then ensure each indexable page still exposes exactly one descriptive H1 in the server-delivered HTML."
                if baseline_only and js_shell_root_active
                else "Ensure each indexable page exposes exactly one descriptive H1 in the main content."
            ),
            acceptance=(
                "Sampled pages expose a visible, route-relevant H1 in the initial HTML response, and rendered validation confirms the same heading survives hydration."
                if baseline_only and js_shell_root_active
                else "Sampled pages contain a visible, route-relevant H1 in the body."
            ),
            derived_from=["js-shell-risk"] if baseline_only and js_shell_root_active else [],
            validation_state="needs_render_validation" if baseline_only and js_shell_root_active else "confirmed",
            evidence_mode="raw_html",
            relationship_summary=(
                "Likely downstream symptom of the JS-heavy initial HTML baseline. Revalidate after fixing server-delivered HTML."
                if baseline_only and js_shell_root_active
                else ""
            ),
        ))

    alt_missing = [page for page in indexable_pages if page.get("image_missing_alt", 0) > 0]
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

    thin_pages = [
        page
        for page in indexable_pages
        if int(page.get("content_units") or page.get("word_count") or 0) < 180
    ]
    if len(thin_pages) >= max(2, len(indexable_pages) // 3):
        sample = thin_pages[0]
        findings.append(_finding(
            "thin-content",
            title="Initial HTML baseline looks very thin" if baseline_only and js_shell_root_active else "Large share of sampled pages are thin",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="content",
            bucket="content_depth_blog",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(thin_pages)} of {len(indexable_pages)} indexable sampled page(s) have under 180 content units"],
            diagnostic=(
                "A meaningful portion of the crawl exposes very short visible content in the initial HTML response."
                if baseline_only and js_shell_root_active
                else "A meaningful portion of the crawl exposes very short visible content."
            ),
            probable_cause=(
                "Critical page copy may be injected after hydration, or the templates may genuinely be too shallow."
                if baseline_only and js_shell_root_active
                else "Template placeholders, sparse landing pages, or overly shallow article bodies."
            ),
            recommended_fix=(
                "Fix initial HTML delivery first, then expand key pages that remain shallow even in server-delivered HTML."
                if baseline_only and js_shell_root_active
                else "Expand key pages with genuinely useful copy, internal anchors, and supporting context."
            ),
            acceptance=(
                "Core templates expose substantial visible text in the initial HTML baseline, and rendered comparison no longer shows major copy gaps."
                if baseline_only and js_shell_root_active
                else "Core templates exceed minimal content depth and expose substantial visible text in HTML."
            ),
            derived_from=["js-shell-risk"] if baseline_only and js_shell_root_active else [],
            validation_state="needs_render_validation" if baseline_only and js_shell_root_active else "confirmed",
            evidence_mode="raw_html",
            relationship_summary=(
                "Likely downstream symptom of the JS-heavy initial HTML baseline. Revalidate after fixing server-delivered HTML."
                if baseline_only and js_shell_root_active
                else ""
            ),
        ))

    duplicates = Counter(page.get("text_hash") for page in indexable_pages if page.get("text_hash"))
    duplicate_hashes = {hash_value for hash_value, count in duplicates.items() if count > 1}
    if duplicate_hashes:
        dup_pages = [page for page in indexable_pages if page.get("text_hash") in duplicate_hashes]
        sample = dup_pages[0]
        findings.append(_finding(
            "duplicate-content",
            title="Raw HTML baseline looks quasi-duplicate" if baseline_only and js_shell_root_active else "Quasi-duplicate content detected",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="content",
            bucket="content_depth_blog",
            severity="medium",
            confidence="Strong signal",
            impact="Medium",
            evidence=[f"{len(dup_pages)} sampled pages share near-identical extracted text"],
            diagnostic=(
                "The sampled crawl surfaced repeated or near-repeated content in the initial HTML baseline."
                if baseline_only and js_shell_root_active
                else "The sampled crawl surfaced repeated or near-repeated content bodies."
            ),
            probable_cause=(
                "Repeated app-shell HTML or shared boilerplate may be masking true page uniqueness before hydration."
                if baseline_only and js_shell_root_active
                else "Duplicated templates, paginated clones, parameter variants, or copied boilerplate pages."
            ),
            recommended_fix=(
                "Fix initial HTML delivery first, then re-evaluate duplicate clusters that remain similar after rendered validation."
                if baseline_only and js_shell_root_active
                else "Consolidate duplicates with canonicals, redirects, or differentiated content."
            ),
            acceptance=(
                "Important templates remain materially distinct in initial HTML or are consolidated with canonicals or redirects."
                if baseline_only and js_shell_root_active
                else "Duplicate templates are consolidated and canonical targets are consistent."
            ),
            derived_from=["js-shell-risk"] if baseline_only and js_shell_root_active else [],
            validation_state="needs_render_validation" if baseline_only and js_shell_root_active else "confirmed",
            evidence_mode="raw_html",
            relationship_summary=(
                "May partly reflect repeated app-shell HTML rather than true rendered duplication. Revalidate after fixing initial HTML delivery."
                if baseline_only and js_shell_root_active
                else ""
            ),
        ))

    crawled_keys = {_comparison_url(page.get("final_url") or page.get("url") or "") for page in pages}
    internal_linked_keys = {
        _comparison_url(link)
        for page in indexable_pages
        for link in (page.get("internal_links") or [])
        if link and not _is_system_url(link)
    }
    sitemap_only_urls: List[str] = []
    sampled_but_unlinked_urls: List[str] = []
    for url in sitemap_urls:
        key = _comparison_url(url)
        if key not in crawled_keys and key not in internal_linked_keys:
            sitemap_only_urls.append(url)
        elif key in crawled_keys and key not in internal_linked_keys:
            sampled_but_unlinked_urls.append(url)
    if sitemap_only_urls or sampled_but_unlinked_urls:
        sample = (sampled_but_unlinked_urls or sitemap_only_urls)[0]
        evidence = []
        if sitemap_only_urls:
            evidence.append(f"{len(sitemap_only_urls)} sitemap URL(s) were only seen in sitemap discovery")
        if sampled_but_unlinked_urls:
            evidence.append(f"{len(sampled_but_unlinked_urls)} sampled sitemap URL(s) were not corroborated by HTML internal links")
        findings.append(_finding(
            "orphan-like-pages",
            title=(
                "Sitemap URLs were not corroborated by the bounded HTML crawl graph"
                if baseline_only and js_shell_root_active
                else "Sitemap URLs were not corroborated by the bounded HTML crawl graph"
            ),
            url=sample,
            scope="site",
            category="internal_linking",
            bucket="architecture_linking",
            severity="medium",
            confidence="Estimated",
            impact="Medium",
            evidence=evidence,
            diagnostic=(
                "Some sitemap URLs were not corroborated by crawlable HTML links during the bounded crawl. This is a discovery-gap signal, not proof that the URLs are truly orphaned."
                if baseline_only and js_shell_root_active
                else "Some sitemap URLs were not corroborated by crawlable HTML links during the bounded crawl. This is a discovery-gap signal, not proof that the URLs are truly orphaned."
            ),
            probable_cause=(
                "Bounded crawl depth, locale partitioning, rendered navigation, or genuinely weak internal linking can all produce this pattern."
                if baseline_only and js_shell_root_active
                else "Bounded crawl depth, locale partitioning, rendered navigation, or genuinely weak internal linking can all produce this pattern."
            ),
            recommended_fix=(
                "Separate sitemap-only URLs from priority pages that should be linked from crawlable navigation, hubs, or contextual modules, then revalidate with rendered crawling if needed."
                if baseline_only and js_shell_root_active
                else "Separate sitemap-only URLs from priority pages that should be linked from crawlable navigation, hubs, or contextual modules."
            ),
            acceptance=(
                "Priority sitemap URLs are reachable through crawlable links within a reasonable click depth, and any sitemap-only URLs are intentionally isolated or removed from sitemap strategy."
                if baseline_only and js_shell_root_active
                else "Priority sitemap URLs are reachable through crawlable links within a reasonable click depth, and any sitemap-only URLs are intentionally isolated or removed from sitemap strategy."
            ),
            derived_from=["js-shell-risk"] if baseline_only and js_shell_root_active else [],
            validation_state="needs_render_validation" if baseline_only and js_shell_root_active else "confirmed",
            evidence_mode="raw_html",
            relationship_summary=(
                "May partly reflect links that only appear after client-side rendering. Revalidate after fixing initial HTML delivery."
                if baseline_only and js_shell_root_active
                else ""
            ),
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
            validation_state="needs_render_validation" if baseline_only and js_shell_root_active else "confirmed",
            evidence_mode="raw_html",
            derived_from=["js-shell-risk"] if baseline_only and js_shell_root_active else [],
            relationship_summary=(
                "This may partly reflect a raw-HTML baseline that hides editorial links until hydration."
                if baseline_only and js_shell_root_active
                else ""
            ),
        ))

    expected_lang = CC_TLD_LANGUAGE_MAP.get(target_tld)
    if expected_lang:
        mismatched_pages = [
            page
            for page in indexable_pages
            if _page_language_hint(page)
            and _lang_root(_page_language_hint(page)) != _lang_root(expected_lang)
        ]
        english_pages = [
            page for page in mismatched_pages if _lang_root(_page_language_hint(page)) == "en"
        ]
        if english_pages:
            sample = english_pages[0]
            findings.append(_finding(
                "cc-tld-language-mismatch",
                title=f"Country-code domain `.{target_tld}` carries English content",
                url=sample.get("final_url") or sample.get("url") or target_url,
                scope="site",
                category="internationalization",
                bucket="indexability",
                severity="high" if target_tld == "fr" else "medium",
                confidence="Strong signal",
                impact="High",
                evidence=[
                    f"{len(english_pages)} sampled page(s) expose English language signals on a .{target_tld} domain",
                    f"Sample page language hint: {_page_language_hint(sample) or 'en'}",
                ],
                diagnostic=(
                    f"The site uses a country-code domain `.{target_tld}` while publishing English sections. "
                    "A ccTLD sends a strong country-targeting signal, which can dilute international discoverability for those English pages."
                ),
                probable_cause=(
                    "The international strategy is mixing country-targeted hosting with a broader English content footprint."
                ),
                recommended_fix=(
                    "Keep the ccTLD primarily aligned with its target market language, or move international/English sections to a neutral domain, dedicated subdomain, or a deliberately managed hreflang structure."
                ),
                acceptance=(
                    "The domain strategy, language targeting, and hreflang signals are aligned so English pages are hosted on an intentional international surface rather than an ambiguous ccTLD setup."
                ),
            ))

    hreflang_pages = [page for page in indexable_pages if page.get("hreflang")]
    sitemap_alternates = int(sitemaps.get("alternate_count") or 0)
    relative_hreflang_pages = [
        page
        for page in hreflang_pages
        if any(not _is_absolute_http_url(item.get("href") or "") for item in (page.get("hreflang") or []))
    ]
    missing_self_hreflang_pages = [
        page
        for page in hreflang_pages
        if not any(
            _same_normalized_url(
                urljoin(page.get("final_url") or page.get("url") or "", item.get("href") or ""),
                page.get("final_url") or page.get("url") or "",
            )
            for item in (page.get("hreflang") or [])
            if item.get("href")
        )
    ]
    missing_all_alternates = len(multilingual_roots) >= 2 and not hreflang_pages and sitemap_alternates == 0
    if missing_all_alternates or relative_hreflang_pages or missing_self_hreflang_pages:
        sample = (
            relative_hreflang_pages
            or missing_self_hreflang_pages
            or indexable_pages
            or pages
            or [{"final_url": target_url}]
        )[0]
        evidence = [f"Detected multilingual roots: {', '.join(multilingual_roots) or 'none'}"]
        if missing_all_alternates:
            evidence.append("No hreflang annotations were detected in sampled HTML/HTTP responses or sitemap files.")
        if relative_hreflang_pages:
            evidence.append(f"{len(relative_hreflang_pages)} sampled page(s) use non-absolute hreflang URLs")
        if missing_self_hreflang_pages:
            evidence.append(f"{len(missing_self_hreflang_pages)} sampled page(s) omit a self-referencing alternate")
        if sitemap_alternates:
            evidence.append(f"{sitemap_alternates} sitemap alternate annotation(s) were discovered")
        findings.append(_finding(
            "hreflang-implementation-gaps",
            title="Localized alternate signals are missing or inconsistent",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="site",
            category="internationalization",
            bucket="indexability",
            severity="high" if missing_all_alternates and len(multilingual_roots) >= 3 else "medium",
            confidence="Strong signal" if missing_all_alternates else "Confirmed",
            impact="High",
            evidence=evidence,
            diagnostic=(
                "The site exposes multiple language variants, but the alternate-language implementation is missing or inconsistent in the sampled evidence."
            ),
            probable_cause=(
                "Localized pages were published without a maintained hreflang cluster, or the chosen implementation is incomplete on some templates."
            ),
            recommended_fix=(
                "Implement one maintained alternate-language method across localized pages (HTML link tags, HTTP Link headers, or sitemap alternates), and ensure each locale lists itself plus the other variants with fully-qualified URLs."
            ),
            acceptance=(
                "Localized versions expose a consistent alternate-language cluster across the chosen method, with self-references and fully-qualified locale URLs."
            ),
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

    relative_canonical_pages = [page for page in indexable_pages if page.get("canonical_relative")]
    if relative_canonical_pages:
        sample = relative_canonical_pages[0]
        findings.append(_finding(
            "relative-canonical-url",
            title="Canonical URLs use relative paths",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="canonical",
            bucket="indexability",
            severity="low",
            confidence="Confirmed",
            impact="Low",
            evidence=[f"{len(relative_canonical_pages)} sampled page(s) emit a relative canonical", sample.get("canonical", "")],
            diagnostic="Some sampled canonical annotations use relative paths instead of fully-qualified URLs.",
            probable_cause="The canonical helper is outputting path-only values from the router or template layer.",
            recommended_fix="Emit absolute canonical URLs in HTML and HTTP headers to avoid environment or host ambiguity.",
            acceptance="Sampled canonical annotations use fully-qualified public URLs.",
        ))

    canonical_outside_head_pages = [
        page for page in indexable_pages if page.get("canonical") and not page.get("canonical_in_head")
    ]
    if canonical_outside_head_pages:
        sample = canonical_outside_head_pages[0]
        findings.append(_finding(
            "canonical-outside-head",
            title="Canonical annotation is not anchored in the HTML head",
            url=sample.get("final_url") or sample.get("url") or target_url,
            scope="template",
            category="canonical",
            bucket="indexability",
            severity="medium",
            confidence="Confirmed",
            impact="Medium",
            evidence=[f"{len(canonical_outside_head_pages)} sampled page(s) expose canonical outside <head>"],
            diagnostic="A sampled canonical link was not found in the HTML head, where Google expects it.",
            probable_cause="The canonical element is being injected in the body, fragment, or an invalid document structure.",
            recommended_fix="Render the rel=canonical link inside a valid head section, or use a canonical HTTP Link header where appropriate.",
            acceptance="Sampled pages place canonical annotations in a valid HTML head or canonical HTTP header.",
        ))

    if homepage.get("canonical") and not _homepage_canonical_allowed_alias(homepage, target_url, sitemaps):
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
            diagnostic="The homepage canonical does not self-reference the sampled final URL and does not match a recognized locale-root alias pattern.",
            probable_cause="Canonical logic is using a stale host, wrong locale root, or staging domain.",
            recommended_fix="Point the homepage canonical to the preferred public homepage URL, or keep the locale-root alias strategy explicit and consistent with the sitemap.",
            acceptance="Homepage canonical matches the intended live homepage or a deliberate locale-root alias without cross-domain drift.",
        ))

    return findings


def _build_visibility_signals(
    robots: Dict[str, Any],
    sitemaps: Dict[str, Any],
    classification: Dict[str, Any],
    pages: List[Dict[str, Any]],
    owner_context: Optional[Dict[str, Any]] = None,
    provider_statuses: Optional[List[Dict[str, Any]]] = None,
    render_detection: Optional[Dict[str, Any]] = None,
    llms_signal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    owner_context = owner_context or {}
    provider_statuses = provider_statuses or []
    render_detection = render_detection or {}
    llms_signal = llms_signal or {}
    owner_integrations = {
        item.get("id"): item
        for item in (owner_context.get("integrations") or [])
        if isinstance(item, dict)
    }
    provider_by_id = {
        item.get("id"): item
        for item in provider_statuses
        if isinstance(item, dict)
    }
    gsc = owner_integrations.get("google_search_console") or {}
    bing_provider = provider_by_id.get("bing_webmaster") or {}
    indexnow_provider = provider_by_id.get("indexnow") or {}
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

    indexnow_public_hint = any(
        "indexnow" in str(line or "").lower()
        for line in (robots.get("rules_sample") or [])
    ) or any(
        "indexnow" in (
            f"{page.get('body_html_excerpt', '')} {page.get('visible_text_excerpt', '')}".lower()
        )
        for page in pages[:6]
    )

    owner_mode = owner_context.get("mode") == "verified_owner"

    if owner_mode and indexnow_provider.get("configured"):
        indexnow_status = "Strong signal"
        indexnow_confidence = "Confirmed"
        indexnow_note = (
            "Owner-side IndexNow key is configured in JoyBoy for this target workspace. "
            "This improves freshness signaling, but does not guarantee crawling or indexing."
        )
    elif indexnow_public_hint:
        indexnow_status = "Strong signal"
        indexnow_confidence = "Estimated"
        indexnow_note = (
            "SignalAtlas found public IndexNow hints in the sampled host output. "
            "IndexNow can speed discovery, but it does not guarantee crawling or indexing."
        )
    else:
        indexnow_status = "Unknown"
        indexnow_confidence = "Unknown"
        indexnow_note = "IndexNow support could not be confirmed from the public crawl."

    if owner_mode and bing_provider.get("configured"):
        bing_status = "Strong signal"
        bing_confidence = "Confirmed"
        bing_note = "Bing Webmaster connectivity is configured in JoyBoy for this target workspace."
    else:
        bing_status = "Estimated"
        bing_confidence = "Estimated"
        bing_note = "Bing ecosystem visibility is inferred from crawlability, metadata, and sitemap coherence only."

    geo_signal = _geo_signal_snapshot(pages, llms_signal)

    return {
        "google": {
            "status": google_status,
            "confidence": google_confidence,
            "note": google_note,
        },
        "bing": {
            "status": bing_status,
            "confidence": bing_confidence,
            "note": bing_note,
        },
        "indexnow": {
            "status": indexnow_status,
            "confidence": indexnow_confidence,
            "note": indexnow_note,
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
        "geo": geo_signal,
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
    llms_signal = _probe_llms_txt(session, entry_url)

    queue: Deque[Tuple[str, int]] = deque()
    seen = set()
    for candidate in [entry_url] + list(sitemaps.get("urls") or [])[: max_pages]:
        clean = _clean_url(candidate)
        if _same_host(clean, host) and clean not in seen and not _is_system_url(clean):
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
                if clean in seen or not _same_host(clean, host) or _is_system_url(clean):
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
                "html_lang": "",
                "structured_data_types": [],
                "open_graph": {},
                "twitter_cards": {},
                "word_count": 0,
                "content_units": 0,
                "cjk_char_count": 0,
                "visible_text_length": 0,
                "visible_text_excerpt": "",
                "body_text_excerpt": "",
                "body_html_excerpt": "",
                "image_total": 0,
                "image_missing_alt": 0,
                "image_empty_alt": 0,
                "shell_like": False,
                "system_url": _is_system_url(current),
                "indexable_candidate": False,
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
    provider_statuses = get_signalatlas_provider_status(entry_url, mode=mode)
    visibility = _build_visibility_signals(
        robots,
        sitemaps,
        classification,
        pages,
        owner_context=owner_context,
        provider_statuses=provider_statuses,
        render_detection=render_detection,
        llms_signal=llms_signal,
    )
    template_clusters = _build_template_clusters(pages)

    findings = _build_findings(
        pages,
        target_url=entry_url,
        discovered_url_count=len(discovered_urls),
        robots=robots,
        sitemaps=sitemaps,
        site_classification=classification,
        render_detection=render_detection,
    )

    emit("score", 76, "Scoring technical findings")
    score_payload = score_findings(findings, pages_analyzed=len(pages), page_budget=max_pages)
    root_causes = [item for item in findings if item.get("root_cause")]
    derived_symptoms = [item for item in findings if item.get("derived_from")]
    primary_root_cause = root_causes[0] if root_causes else None
    baseline_only = _render_baseline_only(render_detection)

    emit("report", 88, "Building audit report")
    summary = {
        "target": entry_url,
        "host": host,
        "mode": mode,
        "pages_crawled": len(pages),
        "pages_sampled": len(pages),
        "page_budget": max_pages,
        "pages_discovered": len(discovered_urls),
        "sitemap_url_count": len(sitemaps.get("urls") or []),
        "sitemap_index_count": len(sitemaps.get("indexes") or []),
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
        "baseline_only": baseline_only,
        "render_js_requested": bool(render_detection.get("render_js_requested")),
        "render_js_executed": bool(render_detection.get("render_js_executed")),
        "primary_root_cause_id": primary_root_cause.get("id", "") if primary_root_cause else "",
        "primary_root_cause_title": primary_root_cause.get("title", "") if primary_root_cause else "",
        "root_cause_count": len(root_causes),
        "derived_symptom_count": len(derived_symptoms),
        "needs_render_validation_count": sum(
            1 for item in findings if item.get("validation_state") == "needs_render_validation"
        ),
        "blocking_risk": score_payload.get("blocking_risk") or {},
        "signals": {
            "robots": "Confirmed" if robots.get("found") else "Unknown",
            "sitemap": visibility.get("sitemap_coherence", {}).get("confidence", "Estimated"),
            "rendering": visibility.get("js_render_risk", {}).get("confidence", "Strong signal"),
            "indexnow": visibility.get("indexnow", {}).get("confidence", "Unknown"),
            "geo": visibility.get("geo", {}).get("confidence", "Unknown"),
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
            (
                "Several symptoms are marked as baseline-only and should be revalidated after rendered-browser probing."
                if baseline_only and derived_symptoms
                else "No derived baseline-only symptom cluster was detected in this sampled pass."
            ),
            visibility.get("indexnow", {}).get("note", ""),
            visibility.get("geo", {}).get("note", ""),
            "LLM interpretation can be rerun later without repeating the crawl.",
        ],
        "root_causes": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "severity": item.get("severity"),
                "confidence": item.get("confidence"),
            }
            for item in root_causes
        ],
    }
    summary["notes"] = [note for note in summary.get("notes", []) if str(note or "").strip()]

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
        "llms_signal": llms_signal,
        "framework_detection": classification,
        "render_detection": render_detection,
        "visibility_signals": visibility,
        "provider_statuses": provider_statuses,
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
