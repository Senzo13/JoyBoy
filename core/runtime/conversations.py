"""Durable local conversation storage for JoyBoy."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .storage import get_runtime_root, utc_now_iso


class ConversationStore:
    """Small JSON store for conversations and message metadata.

    Heavy artifacts stay in output/cache directories. Conversations store stable
    references: message text, attachments metadata, and job ids.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (get_runtime_root() / "conversations.json")
        self._lock = threading.RLock()
        self._conversations: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._conversations = {
                    str(conv_id): conv
                    for conv_id, conv in data.get("conversations", {}).items()
                    if isinstance(conv, dict)
                }
        except Exception as exc:
            print(f"[RUNTIME] Conversation store ignored ({exc})")
            self._conversations = {}

    def _save_locked(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "updated_at": utc_now_iso(),
            "conversations": self._conversations,
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def create(
        self,
        *,
        conversation_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        conversation_id = str(conversation_id or uuid.uuid4())
        title = title or "Nouvelle conversation"
        conv = {
            "id": conversation_id,
            "title": title,
            "summary": "",
            "metadata": metadata or {},
            "messages": [],
            "jobs": [],
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }
        with self._lock:
            self._conversations[conversation_id] = conv
            self._save_locked()
            return deepcopy(conv)

    def ensure(self, conversation_id: str | None, *, title: str | None = None) -> dict[str, Any]:
        conversation_id = str(conversation_id or "default")
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                return deepcopy(conv)
        return self.create(conversation_id=conversation_id, title=title)

    def append_message(
        self,
        conversation_id: str | None,
        role: str,
        content: str,
        *,
        message_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conv = self.ensure(conversation_id)
        message = {
            "id": message_id or str(uuid.uuid4()),
            "role": role,
            "content": content or "",
            "job_id": job_id,
            "metadata": metadata or {},
            "created_at": utc_now_iso(),
        }
        with self._lock:
            stored = self._conversations[conv["id"]]
            stored.setdefault("messages", []).append(message)
            stored["updated_at"] = message["created_at"]
            if role == "user" and content and stored.get("title") in {"Nouvelle conversation", "New conversation"}:
                stored["title"] = _title_from_message(content)
            self._save_locked()
            return deepcopy(message)

    def attach_job(self, conversation_id: str | None, job_id: str, *, kind: str = "", prompt: str = "") -> None:
        conv = self.ensure(conversation_id)
        ref = {
            "id": job_id,
            "kind": kind,
            "prompt": prompt or "",
            "created_at": utc_now_iso(),
        }
        with self._lock:
            stored = self._conversations[conv["id"]]
            jobs = stored.setdefault("jobs", [])
            if not any(item.get("id") == job_id for item in jobs):
                jobs.append(ref)
            stored["updated_at"] = ref["created_at"]
            self._save_locked()

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            conv = self._conversations.get(str(conversation_id))
            return deepcopy(conv) if conv else None

    def list(self, *, include_archived: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            conversations = list(self._conversations.values())
        if not include_archived:
            conversations = [conv for conv in conversations if not conv.get("archived")]
        conversations.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        # Keep list payload light; full messages are loaded only when opening.
        result = []
        for conv in conversations[: max(1, min(limit, 500))]:
            item = deepcopy(conv)
            item["message_count"] = len(item.get("messages", []))
            item["job_count"] = len(item.get("jobs", []))
            item.pop("messages", None)
            result.append(item)
        return result

    def archive(self, conversation_id: str, archived: bool = True) -> dict[str, Any] | None:
        with self._lock:
            conv = self._conversations.get(str(conversation_id))
            if not conv:
                return None
            conv["archived"] = archived
            conv["updated_at"] = utc_now_iso()
            self._save_locked()
            return deepcopy(conv)

    def clear(self) -> None:
        with self._lock:
            self._conversations = {}
            self._save_locked()


def _title_from_message(content: str) -> str:
    text = " ".join(str(content or "").split())
    if len(text) > 54:
        return text[:51].rstrip() + "..."
    return text or "Nouvelle conversation"


_CONVERSATION_STORE: ConversationStore | None = None
_STORE_LOCK = threading.Lock()


def get_conversation_store() -> ConversationStore:
    global _CONVERSATION_STORE
    with _STORE_LOCK:
        if _CONVERSATION_STORE is None:
            _CONVERSATION_STORE = ConversationStore()
        return _CONVERSATION_STORE
