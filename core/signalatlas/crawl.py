"""Smart crawl frontier helpers for SignalAtlas."""

from __future__ import annotations

import re
from collections import deque
from typing import Callable, Deque, Iterable, List, Set, Tuple
from urllib.parse import urlparse


BLOG_PATH_RE = re.compile(r"/(?:blog|news|articles|guides|learn|resources)(?:/|$)", re.I)
COMMERCIAL_PATH_RE = re.compile(r"/(?:pricing|services|products|solutions|features|use-cases|case-studies)(?:/|$)", re.I)
LOCALE_PATH_RE = re.compile(r"^/[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?(?:/|$)", re.I)


def crawl_priority(url: str) -> Tuple[int, int, str]:
    """Rank URLs so a bounded sample covers important templates early."""

    parsed = urlparse(str(url or ""))
    path = parsed.path or "/"
    depth = len([part for part in path.split("/") if part])
    if path in {"", "/"}:
        return (0, depth, path)
    if LOCALE_PATH_RE.search(path) and depth <= 2:
        return (1, depth, path)
    if COMMERCIAL_PATH_RE.search(path):
        return (2, depth, path)
    if BLOG_PATH_RE.search(path):
        return (3, depth, path)
    if depth <= 2:
        return (4, depth, path)
    return (5, depth, path)


def seed_frontier(
    entry_url: str,
    sitemap_urls: Iterable[str],
    *,
    max_pages: int,
    clean_url: Callable[[str], str],
    same_host: Callable[[str], bool],
    is_system_url: Callable[[str], bool],
) -> Tuple[Deque[Tuple[str, int]], Set[str], Set[str]]:
    """Build the initial crawl queue from homepage + prioritized sitemap URLs."""

    seen: Set[str] = set()
    discovered: Set[str] = set()
    candidates: List[str] = [entry_url]
    candidates.extend(list(sitemap_urls or []))
    unique: List[str] = []
    for candidate in candidates:
        clean = clean_url(candidate)
        if not clean or clean in seen or not same_host(clean) or is_system_url(clean):
            continue
        seen.add(clean)
        discovered.add(clean)
        unique.append(clean)

    homepage = unique[:1]
    rest = sorted(unique[1:], key=crawl_priority)
    selected = homepage + rest[: max(0, int(max_pages or 1) * 2)]
    return deque((url, 0) for url in selected), set(selected), discovered


def should_enqueue_link(
    url: str,
    *,
    depth: int,
    max_depth: int,
    seen: Set[str],
    max_seen: int,
    same_host: Callable[[str], bool],
    is_system_url: Callable[[str], bool],
) -> bool:
    if depth >= max_depth:
        return False
    if len(seen) >= max_seen:
        return False
    if url in seen:
        return False
    if not same_host(url) or is_system_url(url):
        return False
    return True
