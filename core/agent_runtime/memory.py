"""Local file-backed memory for the JoyBoy agent runtime.

This is intentionally small and public-core friendly. DeerFlow keeps memory in
runtime state and storage providers; JoyBoy starts with a local JSON store under
``JOYBOY_HOME`` so terminal agents can persist useful facts without touching the
repository or leaking secrets into git.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MEMORY_SCHEMA_VERSION = "1.0"
DEFAULT_MEMORY_FILENAME = "agent_memory.json"
MAX_MEMORY_FACTS = 200
SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|hf|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:sk-ant|sk-or)(?:-[A-Za-z0-9_-]+){1,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
SECRET_WORD_PATTERN = re.compile(r"\b(api[_-]?key|secret|token|password|passwd|bearer)\b", re.I)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def joyboy_home() -> Path:
    return Path(os.environ.get("JOYBOY_HOME", "~/.joyboy")).expanduser()


def default_memory_path() -> Path:
    return joyboy_home() / DEFAULT_MEMORY_FILENAME


def create_empty_memory() -> dict[str, Any]:
    return {
        "version": MEMORY_SCHEMA_VERSION,
        "lastUpdated": utc_now_iso(),
        "facts": [],
    }


def normalize_search_text(value: Any) -> str:
    text = str(value or "").lower()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def looks_like_secret(value: str) -> bool:
    text = str(value or "")
    if any(pattern.search(text) for pattern in SECRET_VALUE_PATTERNS):
        return True
    return bool(SECRET_WORD_PATTERN.search(text) and re.search(r"[:=]\s*\S{8,}", text))


@dataclass(frozen=True)
class MemoryFact:
    id: str
    content: str
    category: str
    confidence: float
    source: str
    createdAt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "createdAt": self.createdAt,
        }


class FileMemoryStore:
    """Atomic JSON memory storage with lightweight keyword retrieval."""

    def __init__(self, path: str | Path | None = None, max_facts: int = MAX_MEMORY_FACTS):
        self.path = Path(path).expanduser() if path else default_memory_path()
        self.max_facts = max(10, int(max_facts or MAX_MEMORY_FACTS))

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return create_empty_memory()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return create_empty_memory()
        if not isinstance(data, dict):
            return create_empty_memory()
        facts = data.get("facts", [])
        if not isinstance(facts, list):
            facts = []
        return {
            "version": str(data.get("version") or MEMORY_SCHEMA_VERSION),
            "lastUpdated": str(data.get("lastUpdated") or ""),
            "facts": [fact for fact in facts if isinstance(fact, dict)],
        }

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "version": MEMORY_SCHEMA_VERSION,
            "lastUpdated": utc_now_iso(),
            "facts": list(data.get("facts", []))[-self.max_facts :],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.path)
        return normalized

    def add_fact(
        self,
        content: str,
        category: str = "context",
        confidence: float = 0.6,
        source: str = "terminal",
    ) -> dict[str, Any]:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            raise ValueError("content is required")
        if looks_like_secret(normalized_content):
            raise ValueError("memory facts must not contain secrets, tokens, or API keys")
        normalized_category = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(category or "context").strip()).strip("-").lower()
        normalized_category = normalized_category or "context"
        normalized_source = str(source or "terminal").strip()[:80] or "terminal"
        confidence_value = float(confidence)
        if not math.isfinite(confidence_value):
            raise ValueError("confidence must be finite")
        confidence_value = max(0.0, min(1.0, confidence_value))

        fact = MemoryFact(
            id=f"fact_{uuid.uuid4().hex[:10]}",
            content=normalized_content[:1200],
            category=normalized_category[:64],
            confidence=round(confidence_value, 3),
            source=normalized_source,
            createdAt=utc_now_iso(),
        )

        data = self.load()
        facts = list(data.get("facts", []))
        facts.append(fact.to_dict())
        data["facts"] = facts[-self.max_facts :]
        saved = self.save(data)
        return {"memory": saved, "fact": fact.to_dict()}

    def search(self, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        data = self.load()
        facts = list(data.get("facts", []))
        try:
            limit = max(1, min(int(limit or 8), 20))
        except Exception:
            limit = 8
        normalized_query = normalize_search_text(query)
        tokens = [token for token in re.split(r"\W+", normalized_query) if len(token) >= 3]
        if not tokens:
            return list(reversed(facts))[:limit]

        scored: list[tuple[int, str, dict[str, Any]]] = []
        for fact in facts:
            searchable = normalize_search_text(" ".join(
                str(fact.get(key, ""))
                for key in ("content", "category", "source")
            ))
            score = sum(searchable.count(token) for token in tokens)
            if score:
                scored.append((score, str(fact.get("createdAt", "")), fact))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [fact for _, _, fact in scored[:limit]]


def remember_terminal_fact(
    content: str,
    category: str = "context",
    confidence: float = 0.6,
    source: str = "terminal",
) -> dict[str, Any]:
    return FileMemoryStore().add_fact(content, category=category, confidence=confidence, source=source)


def search_terminal_memory(query: str = "", limit: int = 8) -> list[dict[str, Any]]:
    return FileMemoryStore().search(query=query, limit=limit)
