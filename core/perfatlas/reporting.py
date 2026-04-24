"""Structured reporting and export helpers for PerfAtlas."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _field_summary(field_data: List[Dict[str, Any]]) -> str:
    if not field_data:
        return "No public field data was confirmed in this pass."
    best = next((
        item for item in field_data
        if item.get("scope") == "url" and str(item.get("form_factor") or "").lower() == "all"
    ), None) or next((
        item for item in field_data
        if item.get("scope") == "origin" and str(item.get("form_factor") or "").lower() == "all"
    ), None) or field_data[0]
    parts = []
    if best.get("lcp_ms") is not None:
        parts.append(f"LCP p75 {round(best.get('lcp_ms'))} ms")
    if best.get("inp_ms") is not None:
        parts.append(f"INP p75 {round(best.get('inp_ms'))} ms")
    if best.get("cls") is not None:
        parts.append(f"CLS p75 {round(best.get('cls'), 3)}")
    form_factor = str(best.get("form_factor") or "all").upper()
    return f"Field source: {best.get('source')} ({best.get('scope')} / {form_factor}) — " + ", ".join(parts)


def _owner_summary(owner_context: Dict[str, Any]) -> str:
    integrations = [
        item for item in (owner_context.get("integrations") or [])
        if isinstance(item, dict)
    ]
    if not integrations:
        return "Owner context: no verified platform connector matched this audit."
    ready = [
        str(item.get("name") or item.get("id") or "").strip()
        for item in integrations
        if str(item.get("status") or "").strip().lower() in {"ready", "configured"}
    ]
    partial = [
        str(item.get("name") or item.get("id") or "").strip()
        for item in integrations
        if str(item.get("status") or "").strip().lower() == "partial"
    ]
    parts: List[str] = []
    if ready:
        parts.append("ready: " + ", ".join(ready))
    if partial:
        parts.append("partial: " + ", ".join(partial))
    return "Owner context: " + (", ".join(parts) if parts else "connectors are attached but not fully ready for this target.")


def _owner_context_lines(item: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    context = item.get("context") or {}
    simple_keys = (
        "project_id",
        "site_id",
        "zone_id",
        "name",
        "framework",
        "custom_domain",
        "production_branch",
        "build_command",
        "publish_dir",
        "published_deploy",
        "snippet_count",
        "snippet_head_count",
        "snippet_footer_count",
        "snippet_script_count",
    )
    for key in simple_keys:
        value = context.get(key)
        if value not in (None, "", [], {}):
            label = key.replace("_", " ")
            lines.append(f"  - {label.title()}: `{value}`")
    domains = context.get("domains") or []
    if domains:
        lines.append(f"  - Domains: `{', '.join(str(value) for value in domains[:6])}`")
    name_servers = context.get("name_servers") or []
    if name_servers:
        lines.append(f"  - Name servers: `{', '.join(str(value) for value in name_servers[:4])}`")
    platform_signals = context.get("platform_signals") or {}
    if platform_signals:
        signal_summary = ", ".join(
            f"{key}={value}"
            for key, value in platform_signals.items()
            if value not in (None, "", [], {})
        )
        if signal_summary:
            lines.append(f"  - Platform signals: `{signal_summary}`")
    snippet_titles = context.get("snippet_titles") or []
    if snippet_titles:
        lines.append(f"  - Snippet titles: `{', '.join(str(value) for value in snippet_titles[:6])}`")
    recent_deployments = context.get("recent_deployments") or []
    if recent_deployments:
        lines.append("  - Recent deployments:")
        for deploy in recent_deployments[:4]:
            if not isinstance(deploy, dict):
                continue
            state = deploy.get("state") or "unknown"
            target = deploy.get("target") or deploy.get("context") or "default"
            created = deploy.get("created_at") or deploy.get("published_at") or ""
            deploy_url = deploy.get("url") or deploy.get("deploy_url") or ""
            descriptor = " / ".join(part for part in [str(state), str(target), str(created)] if str(part).strip())
            if deploy_url:
                lines.append(f"    - `{deploy_url}` — {descriptor}")
            else:
                lines.append(f"    - {descriptor}")
    return lines


def build_executive_summary(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    snapshot = audit.get("snapshot") or {}
    runtime = snapshot.get("runtime") or {}
    field_data = snapshot.get("field_data") or []
    lab_runs = snapshot.get("lab_runs") or []
    top_findings = findings[:5]
    lines = [
        f"PerfAtlas audited {summary.get('target') or 'the requested site'} in {summary.get('mode', 'public')} mode.",
        f"Global performance score: {summary.get('global_score', 'n/a')}.",
        f"Detected platform: {summary.get('platform', 'Custom')}.",
        f"Sample coverage: {summary.get('pages_crawled', 0)} page(s) analyzed from {summary.get('pages_discovered', 0)} discovered URL(s), bounded by a page budget of {summary.get('page_budget', 0)}.",
        _field_summary(field_data),
        (
            f"Lab runtime: {runtime.get('runner', 'unavailable')} — {runtime.get('note', 'No additional runtime note.')}"
        ),
        _owner_summary(audit.get("owner_context") or {}),
    ]
    if lab_runs:
        representative = next((item for item in lab_runs if item.get("score") is not None), None)
        if representative:
            lines.append(
                f"Representative lab page: {representative.get('url')} — score {representative.get('score')}, "
                f"LCP {representative.get('largest_contentful_paint_ms') or 'n/a'} ms, "
                f"TBT {representative.get('total_blocking_time_ms') or 'n/a'} ms."
            )
    if summary.get("blocking_risk", {}).get("level") not in {"", "Low", None}:
        lines.append(
            f"Blocking risk: {summary.get('blocking_risk', {}).get('level')} — {summary.get('blocking_risk', {}).get('summary')}"
        )
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
    field_data = snapshot.get("field_data") or []
    lab_runs = snapshot.get("lab_runs") or []
    template_clusters = snapshot.get("template_clusters") or []
    asset_samples = snapshot.get("asset_samples") or []
    providers = snapshot.get("provider_statuses") or []
    owner_context = audit.get("owner_context") or {}

    lines = [
        "# PerfAtlas Audit",
        "",
        f"- Target: `{summary.get('target', '')}`",
        f"- Mode: `{summary.get('mode', 'public')}`",
        f"- Global score: `{summary.get('global_score', 'n/a')}`",
        f"- Platform: `{summary.get('platform', 'Custom')}`",
        f"- Pages sampled: `{summary.get('pages_crawled', 0)}`",
        f"- Page budget: `{summary.get('page_budget', 0)}`",
        f"- Lab pages analyzed: `{summary.get('lab_pages_analyzed', 0)}`",
        "",
        "## Executive Summary",
        "",
        build_executive_summary(audit),
        "",
        "## Provenance & Runtime",
        "",
        f"- Runtime runner: `{(snapshot.get('runtime') or {}).get('runner', 'unavailable')}`",
        f"- Runtime note: {(snapshot.get('runtime') or {}).get('note', '')}",
        "",
        "### Providers",
        "",
    ]
    if providers:
        for item in providers:
            lines.append(
                f"- **{item.get('name')}** — status `{item.get('status')}`, configured `{bool(item.get('configured'))}`"
            )
            if item.get("detail"):
                lines.append(f"  - Detail: {item.get('detail')}")
        lines.append("")
    else:
        lines.extend(["- No provider status was attached to this audit.", ""])

    lines.extend(["## Field Data", ""])
    if field_data:
        for item in field_data:
            lines.extend([
                f"### {item.get('scope').upper()}",
                "",
                f"- Source: `{item.get('source')}`",
                f"- Form factor: `{item.get('form_factor')}`",
                f"- LCP p75: `{item.get('lcp_ms')}`",
                f"- INP p75: `{item.get('inp_ms')}`",
                f"- CLS p75: `{item.get('cls')}`",
                f"- TTFB p75: `{item.get('ttfb_ms')}`",
                f"- Good LCP share: `{item.get('good_lcp_fraction')}`",
                f"- Good INP share: `{item.get('good_inp_fraction')}`",
                f"- Good CLS share: `{item.get('good_cls_fraction')}`",
                f"- Note: {item.get('note', '')}",
                "",
            ])
    else:
        lines.extend(["- No field dataset was confirmed in this pass.", ""])

    lines.extend(["## Lab Runs", ""])
    if lab_runs:
        for item in lab_runs:
            lines.extend([
                f"### {item.get('url')}",
                "",
                f"- Runner: `{item.get('runner')}`",
                f"- Strategy: `{item.get('strategy')}`",
                f"- Score: `{item.get('score', 'n/a')}`",
                f"- LCP: `{item.get('largest_contentful_paint_ms', 'n/a')}`",
                f"- TBT: `{item.get('total_blocking_time_ms', 'n/a')}`",
                f"- Request count: `{item.get('request_count', 'n/a')}`",
                f"- Total byte weight: `{item.get('total_byte_weight', 'n/a')}`",
                f"- Note: {item.get('note', '')}",
                "",
            ])
            if item.get("opportunities"):
                lines.append("#### Opportunities")
                lines.append("")
                for opp in item.get("opportunities")[:6]:
                    lines.append(f"- **{opp.get('title')}** — {opp.get('display_value') or opp.get('numeric_value')}")
                lines.append("")
    else:
        lines.extend(["- No lab run completed in this pass.", ""])

    lines.extend(["## Scores", ""])
    for score in scores:
        lines.append(
            f"- **{score.get('label')}** — {score.get('score')} / 100 (confidence: {score.get('confidence')}, coverage: {score.get('coverage')})"
        )
    lines.extend(["", "## Findings", ""])
    if findings:
        for item in findings:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- URL / scope: `{item.get('url') or item.get('scope')}`",
                f"- Category: `{item.get('category')}`",
                f"- Severity: `{item.get('severity')}`",
                f"- Confidence: `{item.get('confidence')}`",
                f"- Evidence mode: `{item.get('evidence_mode')}`",
                f"- Expected impact: `{item.get('expected_impact')}`",
                f"- Diagnostic: {item.get('diagnostic')}",
                f"- Probable cause: {item.get('probable_cause')}",
                f"- Recommended fix: {item.get('recommended_fix')}",
                f"- Acceptance criteria: {item.get('acceptance_criteria')}",
                "",
            ])
    else:
        lines.extend(["No major performance findings were detected in the sampled coverage.", ""])

    if asset_samples:
        lines.extend(["## Sampled Assets", ""])
        for asset in asset_samples[:10]:
            lines.append(
                f"- `{asset.get('url')}` — `{asset.get('kind')}` / cache `{asset.get('cache_control') or 'none'}` / encoding `{asset.get('content_encoding') or 'none'}`"
            )
        lines.append("")

    if template_clusters:
        lines.extend(["## Template Clusters", ""])
        for cluster in template_clusters[:8]:
            lines.append(
                f"- `{cluster.get('template')}` — {cluster.get('count')} page(s), avg TTFB `{cluster.get('avg_ttfb_ms')}` ms, avg HTML `{cluster.get('avg_html_kb')}` KB"
            )
        lines.append("")

    integrations = owner_context.get("integrations") or []
    if integrations:
        lines.extend(["## Owner Context", ""])
        for item in integrations:
            if not isinstance(item, dict):
                continue
            lines.append(f"- **{item.get('name') or item.get('id')}** — status `{item.get('status')}`")
            if item.get("detail"):
                lines.append(f"  - Detail: {item.get('detail')}")
            lines.extend(_owner_context_lines(item))
        lines.append("")

    interpretations = audit.get("interpretations") or []
    if interpretations:
        latest = interpretations[-1]
        lines.extend([
            "## AI Interpretation",
            "",
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
        "Use the following PerfAtlas audit as the deterministic source of truth. "
        "Do not invent field data, Lighthouse metrics, or owner-provider context. "
        "Produce the exact implementation plan and concrete fixes only.\n\n"
        f"{report}"
    )


def build_report_html(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    score_cards = "".join(
        f"<div class='score-card'><div class='label'>{score.get('label')}</div>"
        f"<div class='value'>{score.get('score')}</div>"
        f"<div class='meta'>{score.get('confidence')}</div></div>"
        for score in (audit.get("scores") or [])
    )
    finding_rows = "".join(
        "<tr>"
        f"<td>{item.get('title')}</td>"
        f"<td>{item.get('severity')}</td>"
        f"<td>{item.get('confidence')}</td>"
        f"<td>{item.get('url') or item.get('scope')}</td>"
        "</tr>"
        for item in (audit.get("findings") or [])
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>PerfAtlas Audit</title>
  <style>
    body {{ font-family: Inter, Arial, sans-serif; color: #101828; padding: 40px; }}
    h1 {{ margin-bottom: 4px; }}
    .muted {{ color: #667085; }}
    .scores {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 24px 0; }}
    .score-card {{ border: 1px solid #d0d5dd; border-radius: 14px; padding: 16px; }}
    .score-card .label {{ font-size: 12px; color: #475467; text-transform: uppercase; letter-spacing: 0.06em; }}
    .score-card .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .score-card .meta {{ font-size: 12px; color: #667085; margin-top: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #eaecf0; padding: 10px 8px; text-align: left; font-size: 13px; }}
    th {{ color: #475467; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>PerfAtlas Audit</h1>
  <div class="muted">{summary.get('target', '')}</div>
  <p>{build_executive_summary(audit)}</p>
  <div class="scores">{score_cards}</div>
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
