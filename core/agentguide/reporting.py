"""Exports for AgentGuide reports."""

from __future__ import annotations

import json
from typing import Any, Dict


def _markdown(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    generated = (audit.get("metadata") or {}).get("generated_files") or []
    lines = [
        f"# AgentGuide report: {audit.get('title') or audit.get('id')}",
        "",
        f"Global score: **{summary.get('global_score', '--')}/100**",
        f"Top risk: {summary.get('top_risk', 'n/a')}",
        "",
        "## Proposed files",
        "",
    ]
    for item in generated:
        lines.append(f"### {item.get('path')}")
        lines.append("")
        lines.append("```md")
        lines.append(str(item.get("content") or "").strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_export_payload(audit: Dict[str, Any], export_format: str) -> Dict[str, str]:
    clean = str(export_format or "").strip().lower()
    if clean == "json":
        return {
            "content": json.dumps(audit, ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
        }
    if clean in {"md", "markdown"}:
        return {
            "content": _markdown(audit),
            "mimetype": "text/markdown; charset=utf-8",
            "extension": "md",
        }
    raise ValueError("Format export non supporté.")
