"""Shared non-git storage for native audit modules."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.runtime.storage import get_runtime_root, utc_now_iso


def _slug_from_value(value: str) -> str:
    clean = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    clean = clean.strip("-")
    return clean or "audit"


class AuditModuleStorage:
    def __init__(self, module_id: str, root: Optional[Path] = None) -> None:
        self.module_id = str(module_id or "").strip().lower() or "audit"
        self.root = Path(root or (get_runtime_root() / self.module_id))
        self.audits_dir = self.root / "audits"
        self.exports_dir = self.root / "exports"
        self.index_path = self.root / "index.json"
        self._lock = threading.RLock()
        self.audits_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def _build_index_record(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        target = audit.get("target") or {}
        summary = audit.get("summary") or {}
        return {
            "id": str(audit.get("id") or "").strip(),
            "title": audit.get("title") or str(audit.get("id") or "").strip(),
            "status": audit.get("status") or "unknown",
            "created_at": audit.get("created_at"),
            "updated_at": audit.get("updated_at"),
            "target_url": target.get("normalized_url") or target.get("raw") or "",
            "host": target.get("host") or "",
            "mode": target.get("mode") or "public",
            "pages_crawled": summary.get("pages_crawled", 0),
            "top_risk": summary.get("top_risk", ""),
            "global_score": summary.get("global_score"),
            "has_ai": bool(audit.get("interpretations")),
        }

    def _load_index_locked(self) -> Dict[str, Any]:
        if not self.index_path.exists():
            return {"version": 1, "module_id": self.module_id, "audits": {}}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("audits"), dict):
                data.setdefault("module_id", self.module_id)
                return data
        except Exception as exc:
            print(f"[{self.module_id.upper()}] Audit index ignored ({exc})")
        return {"version": 1, "module_id": self.module_id, "audits": {}}

    def _save_index_locked(self, data: Dict[str, Any]) -> None:
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def _audit_path(self, audit_id: str) -> Path:
        return self.audits_dir / f"{audit_id}.json"

    def list_audits(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._lock:
            index = self._load_index_locked()
            items = list(index.get("audits", {}).values())
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items[: max(1, min(limit, 200))]

    def get_audit(self, audit_id: str) -> Optional[Dict[str, Any]]:
        path = self._audit_path(str(audit_id or "").strip())
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[{self.module_id.upper()}] Audit read failed for {audit_id}: {exc}")
            return None

    def create_audit_stub(
        self,
        *,
        target: Dict[str, Any],
        title: str,
        options: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        audit_id = str(uuid.uuid4())
        now = utc_now_iso()
        audit = {
            "id": audit_id,
            "target": target,
            "title": title,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "options": options or {},
            "summary": {},
            "snapshot": {},
            "findings": [],
            "scores": [],
            "interpretations": [],
            "remediation_items": [],
            "exports": [],
            "owner_context": {},
            "metadata": metadata or {},
        }
        self.save_audit(audit)
        return audit

    def save_audit(self, audit: Dict[str, Any]) -> Dict[str, Any]:
        audit = dict(audit or {})
        audit_id = str(audit.get("id", "")).strip()
        if not audit_id:
            raise ValueError("audit id required")

        audit["updated_at"] = audit.get("updated_at") or utc_now_iso()
        path = self._audit_path(audit_id)
        with self._lock:
            path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            index = self._load_index_locked()
            index.setdefault("audits", {})[audit_id] = self._build_index_record(audit)
            self._save_index_locked(index)
        return audit

    def update_audit(self, audit_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            audit = self.get_audit(audit_id)
            if not audit:
                return None
            audit.update(updates)
            audit["updated_at"] = utc_now_iso()
            return self.save_audit(audit)

    def append_interpretation(self, audit_id: str, interpretation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        audit = self.get_audit(audit_id)
        if not audit:
            return None
        items = list(audit.get("interpretations") or [])
        items.append(interpretation)
        audit["interpretations"] = items
        audit["updated_at"] = utc_now_iso()
        return self.save_audit(audit)

    def append_export(self, audit_id: str, export_artifact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        audit = self.get_audit(audit_id)
        if not audit:
            return None
        items = list(audit.get("exports") or [])
        items.append(export_artifact)
        audit["exports"] = items
        audit["updated_at"] = utc_now_iso()
        return self.save_audit(audit)

    def get_export_path(self, audit_id: str, format_name: str) -> Path:
        audit_folder = self.exports_dir / str(audit_id)
        audit_folder.mkdir(parents=True, exist_ok=True)
        return audit_folder / f"{_slug_from_value(format_name)}"

    def delete_audit(self, audit_id: str) -> bool:
        clean_audit_id = str(audit_id or "").strip()
        if not clean_audit_id:
            return False
        audit_path = self._audit_path(clean_audit_id)
        export_folder = self.exports_dir / clean_audit_id
        with self._lock:
            index = self._load_index_locked()
            audits = index.setdefault("audits", {})
            existed = clean_audit_id in audits or audit_path.exists() or export_folder.exists()
            audits.pop(clean_audit_id, None)
            self._save_index_locked(index)
            if audit_path.exists():
                audit_path.unlink()
            if export_folder.exists():
                shutil.rmtree(export_folder, ignore_errors=True)
        return existed
