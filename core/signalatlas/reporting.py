"""Structured reporting and export helpers for SignalAtlas."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def build_executive_summary(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    owner_context = audit.get("owner_context") or {}
    render_detection = (audit.get("snapshot") or {}).get("render_detection") or {}
    top_findings = findings[:5]
    lines = [
        f"SignalAtlas audited {summary.get('target') or 'the requested site'} in {summary.get('mode', 'public')} mode.",
        f"Global readiness score: {summary.get('global_score', 'n/a')}.",
        f"Detected platform: {summary.get('platform', 'Custom')} with {summary.get('rendering', 'hybrid')} rendering.",
        f"Sample coverage: {summary.get('pages_crawled', 0)} page(s).",
    ]
    if any(item.get("status") == "confirmed" for item in (owner_context.get("integrations") or []) if isinstance(item, dict)):
        lines.append("Owner-mode enrichment: confirmed via an official Search Console property.")
    elif summary.get("mode") == "verified_owner":
        lines.append("Owner-mode enrichment was requested, but no official property confirmation was available for this target.")
    if render_detection.get("render_js_requested"):
        if render_detection.get("render_js_executed"):
            lines.append(
                f"JS render probes executed on {render_detection.get('executed_page_count', 0)} page(s), "
                f"with material content changes on {render_detection.get('changed_page_count', 0)} page(s)."
            )
        else:
            lines.append(f"JS render probes were requested but not executed: {render_detection.get('note', 'unavailable')}")
    if top_findings:
        lines.append("Priority issues:")
        for item in top_findings:
            lines.append(f"- {item.get('title')} [{item.get('severity')}]")
    return "\n".join(lines)


def build_markdown_report(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    scores = audit.get("scores") or []
    findings = audit.get("findings") or []
    snapshot = audit.get("snapshot") or {}
    owner_context = audit.get("owner_context") or {}
    render_detection = snapshot.get("render_detection") or {}
    lines = [
        "# SignalAtlas Audit",
        "",
        f"- Target: `{summary.get('target', '')}`",
        f"- Mode: `{summary.get('mode', 'public')}`",
        f"- Global score: `{summary.get('global_score', 'n/a')}`",
        f"- Platform: `{summary.get('platform', 'Custom')}`",
        f"- Rendering: `{summary.get('rendering', 'hybrid')}`",
        f"- Pages sampled: `{summary.get('pages_crawled', 0)}`",
        "",
        "## Executive Summary",
        "",
        build_executive_summary(audit),
        "",
        "## Provenance & Confidence",
        "",
    ]

    owner_integrations = owner_context.get("integrations") or []
    if owner_integrations:
        lines.append("### Owner integrations")
        lines.append("")
        for item in owner_integrations:
            lines.append(
                f"- **{item.get('id')}** — status `{item.get('status')}`, confidence `{item.get('confidence', 'Unknown')}`"
            )
            if item.get("site_url"):
                lines.append(f"  - Property: `{item.get('site_url')}`")
            if item.get("detail"):
                lines.append(f"  - Detail: {item.get('detail')}")
        lines.append("")
    else:
        lines.extend([
            "### Owner integrations",
            "",
            "- No owner-only integration data was attached to this audit.",
            "",
        ])

    lines.extend([
        "### JS rendering",
        "",
        f"- Render JS requested: `{bool(render_detection.get('render_js_requested'))}`",
        f"- Render JS executed: `{bool(render_detection.get('render_js_executed'))}`",
        f"- Detail: {render_detection.get('note', 'Raw HTML baseline only.')}",
        "",
        "## Scores",
        "",
    ])
    for score in scores:
        lines.append(
            f"- **{score.get('label')}** — {score.get('score')} / 100 "
            f"(confidence: {score.get('confidence')}, coverage: {score.get('coverage')})"
        )
    lines.extend(["", "## Findings", ""])
    if findings:
        for item in findings:
            lines.extend(
                [
                    f"### {item.get('title')}",
                    "",
                    f"- URL / scope: `{item.get('url') or item.get('scope')}`",
                    f"- Category: `{item.get('category')}`",
                    f"- Severity: `{item.get('severity')}`",
                    f"- Confidence: `{item.get('confidence')}`",
                    f"- Expected impact: `{item.get('expected_impact')}`",
                    f"- Diagnostic: {item.get('diagnostic')}",
                    f"- Probable cause: {item.get('probable_cause')}",
                    f"- Recommended fix: {item.get('recommended_fix')}",
                    f"- Acceptance criteria: {item.get('acceptance_criteria')}",
                    "",
                ]
            )
    else:
        lines.extend(["No critical findings were detected in the sampled coverage.", ""])

    template_clusters = snapshot.get("template_clusters") or []
    if template_clusters:
        lines.extend(["## Template Clusters", ""])
        for cluster in template_clusters[:8]:
            lines.append(
                f"- `{cluster.get('signature')}` — {cluster.get('count')} page(s), "
                f"avg words `{cluster.get('avg_word_count')}`"
            )
        lines.append("")

    interpretations = audit.get("interpretations") or []
    if interpretations:
        lines.extend(["## AI Interpretation", ""])
        latest = interpretations[-1]
        lines.extend([
            f"- Model: `{latest.get('model')}`",
            f"- Level: `{latest.get('level')}`",
            "",
            latest.get("content", ""),
            "",
        ])

    return "\n".join(lines).strip() + "\n"


def build_ai_fix_prompt(audit: Dict[str, Any]) -> str:
    report = build_markdown_report(audit)
    return (
        "Use the following SignalAtlas audit as the deterministic source of truth. "
        "Do not invent crawl data. Produce the exact implementation plan and concrete fixes only.\n\n"
        f"{report}"
    )


def build_report_html(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    owner_context = audit.get("owner_context") or {}
    render_detection = (audit.get("snapshot") or {}).get("render_detection") or {}
    score_cards = "".join(
        f"<div class='score-card'><div class='label'>{score.get('label')}</div>"
        f"<div class='value'>{score.get('score')}</div>"
        f"<div class='meta'>{score.get('confidence')}</div></div>"
        for score in (audit.get("scores") or [])
    )
    owner_cards = "".join(
        f"<div class='owner-card'><div class='label'>{item.get('id')}</div>"
        f"<div class='value'>{item.get('status')}</div>"
        f"<div class='meta'>{item.get('detail') or item.get('site_url') or ''}</div></div>"
        for item in (owner_context.get("integrations") or [])
        if isinstance(item, dict)
    )
    finding_rows = "".join(
        "<tr>"
        f"<td>{item.get('title')}</td>"
        f"<td>{item.get('severity')}</td>"
        f"<td>{item.get('confidence')}</td>"
        f"<td>{item.get('url') or item.get('scope')}</td>"
        "</tr>"
        for item in findings
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SignalAtlas Audit</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; color: #101828; padding: 40px; }}
    h1 {{ margin-bottom: 4px; }}
    .muted {{ color: #667085; }}
    .scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0; }}
    .score-card {{ border: 1px solid #d0d5dd; border-radius: 14px; padding: 16px; }}
    .score-card .label {{ font-size: 12px; color: #475467; text-transform: uppercase; letter-spacing: 0.06em; }}
    .score-card .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .score-card .meta {{ font-size: 12px; color: #667085; margin-top: 6px; }}
    .owner-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 24px 0; }}
    .owner-card {{ border: 1px solid #d0d5dd; border-radius: 14px; padding: 16px; }}
    .owner-card .label {{ font-size: 12px; color: #475467; text-transform: uppercase; letter-spacing: 0.06em; }}
    .owner-card .value {{ font-size: 18px; font-weight: 700; margin-top: 8px; }}
    .owner-card .meta {{ font-size: 12px; color: #667085; margin-top: 6px; line-height: 1.5; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #eaecf0; padding: 10px 8px; text-align: left; font-size: 13px; }}
    th {{ color: #475467; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>SignalAtlas Audit</h1>
  <div class="muted">{summary.get('target', '')}</div>
  <p>{build_executive_summary(audit)}</p>
  <div class="scores">{score_cards}</div>
  <h2>Provenance & Confidence</h2>
  <div class="owner-grid">
    {owner_cards or "<div class='owner-card'><div class='label'>owner mode</div><div class='value'>none</div><div class='meta'>No owner-only integration data was attached to this audit.</div></div>"}
    <div class="owner-card">
      <div class="label">js rendering</div>
      <div class="value">{'executed' if render_detection.get('render_js_executed') else 'raw baseline'}</div>
      <div class="meta">{render_detection.get('note', 'Raw HTML baseline only.')}</div>
    </div>
  </div>
  <h2>Findings</h2>
  <table>
    <thead><tr><th>Issue</th><th>Severity</th><th>Confidence</th><th>Scope</th></tr></thead>
    <tbody>{finding_rows}</tbody>
  </table>
</body>
</html>
""".strip()


def build_export_payload(audit: Dict[str, Any], export_format: str) -> Dict[str, Any]:
    fmt = str(export_format or "").strip().lower()
    if fmt == "json":
        return {
            "content": json.dumps(audit, ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "JSON",
        }
    if fmt in {"md", "markdown"}:
        return {
            "content": build_markdown_report(audit),
            "mimetype": "text/markdown; charset=utf-8",
            "extension": "md",
            "label": "Markdown",
        }
    if fmt == "prompt":
        return {
            "content": build_ai_fix_prompt(audit),
            "mimetype": "text/plain; charset=utf-8",
            "extension": "txt",
            "label": "Prompt for AI fix",
        }
    if fmt == "remediation":
        return {
            "content": json.dumps(audit.get("remediation_items") or [], ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "AI remediation pack",
        }
    raise ValueError(f"Unsupported export format: {export_format}")


def render_pdf_bytes(audit: Dict[str, Any]) -> bytes:
    html = build_report_html(audit)
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("WeasyPrint is not available for PDF exports.") from exc
    return HTML(string=html).write_pdf()
