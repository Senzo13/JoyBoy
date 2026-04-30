"""Exports for CodeAtlas reports."""

from __future__ import annotations

import json
from typing import Any, Dict


def _markdown(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    scores = audit.get("scores") or []
    findings = audit.get("findings") or []
    remediation = audit.get("remediation_items") or []
    lines = [
        f"# CodeAtlas report: {audit.get('title') or audit.get('id')}",
        "",
        f"Global score: **{summary.get('global_score', '--')}/100**",
        f"Top risk: {summary.get('top_risk', 'n/a')}",
        "",
        "## Scores",
        "",
    ]
    for score in scores:
        lines.append(f"- {score.get('label')}: {score.get('score')}/100")
    lines.extend(["", "## Findings", ""])
    for finding in findings:
        lines.append(f"- **[{finding.get('severity')}] {finding.get('title')}**: {finding.get('detail')}")
    lines.extend(["", "## Remediation plan", ""])
    for item in remediation:
        lines.append(f"### {item.get('priority')} - {item.get('title')}")
        lines.append(item.get("why") or "")
        for action in item.get("actions") or []:
            lines.append(f"- {action}")
        if item.get("validation"):
            lines.append("Validation:")
            for command in item["validation"]:
                lines.append(f"- `{command}`")
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
