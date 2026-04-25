"""Local incremental cache for SignalAtlas page snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.runtime.storage import get_runtime_root


DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60


def _cache_key(url: str) -> str:
    return hashlib.sha1(str(url or "").encode("utf-8", errors="ignore")).hexdigest()


class SignalAtlasPageCache:
    """Small filesystem cache stored under the local JoyBoy runtime directory."""

    def __init__(self, root: Optional[Path] = None, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self.root = Path(root or (get_runtime_root() / "signalatlas" / "cache" / "pages"))
        self.ttl_seconds = max(0, int(ttl_seconds or 0))
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        return self.root / f"{_cache_key(url)}.json"

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        if self.ttl_seconds <= 0:
            return None
        path = self._path(url)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        cached_at = float(payload.get("cached_at") or 0)
        if cached_at <= 0 or (time.time() - cached_at) > self.ttl_seconds:
            return None
        page = payload.get("page")
        if not isinstance(page, dict):
            return None
        page = dict(page)
        page["cache_status"] = "hit"
        return page

    def set(self, url: str, page: Dict[str, Any]) -> None:
        if self.ttl_seconds <= 0 or not isinstance(page, dict):
            return
        if int(page.get("status_code") or 0) <= 0:
            return
        payload = {
            "cached_at": time.time(),
            "url": url,
            "final_url": page.get("final_url") or page.get("url") or url,
            "status_code": page.get("status_code", 0),
            "content_hash": page.get("content_hash", ""),
            "text_hash": page.get("text_hash", ""),
            "page": dict(page, cache_status="stored"),
        }
        path = self._path(url)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
