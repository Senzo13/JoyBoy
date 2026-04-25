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


def _format_perf_value(value: Any, unit: str) -> str:
    if value is None:
        return "n/a"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if unit == "bytes":
        if numeric >= 1024 * 1024:
            return f"{round(numeric / 1024 / 1024, 2)} MB"
        return f"{round(numeric / 1024)} KB"
    if unit == "ms":
        return f"{round(numeric)} ms"
    if unit == "score":
        return str(round(numeric, 3))
    return str(round(numeric, 1) if numeric % 1 else int(numeric))


def _performance_intelligence(audit: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = audit.get("snapshot") or {}
    intelligence = snapshot.get("performance_intelligence") or {}
    return intelligence if isinstance(intelligence, dict) else {}


def _performance_regression(audit: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = audit.get("snapshot") or {}
    regression = snapshot.get("regression") or {}
    return regression if isinstance(regression, dict) else {}


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
    intelligence = _performance_intelligence(audit)
    intelligence_summary = intelligence.get("summary") or {}
    regression = _performance_regression(audit)
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
    if intelligence:
        lines.append(
            "Performance intelligence: "
            f"{intelligence_summary.get('failed_budget_count', 0)} failed budget(s), "
            f"{intelligence_summary.get('bad_detector_count', 0)} red detective(s), "
            f"confidence {intelligence_summary.get('diagnostic_confidence', 'limited')}."
        )
        if intelligence_summary.get("top_action"):
            lines.append(f"Top action: {intelligence_summary.get('top_action')}")
    if regression and regression.get("available"):
        lines.append(f"Regression: {regression.get('risk')} — {regression.get('summary')}")
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
    intelligence = _performance_intelligence(audit)
    regression = _performance_regression(audit)

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

    if intelligence:
        intel_summary = intelligence.get("summary") or {}
        lines.extend([
            "## Performance Intelligence",
            "",
            f"- Diagnostic confidence: `{intel_summary.get('diagnostic_confidence', 'limited')}`",
            f"- Failed budgets: `{intel_summary.get('failed_budget_count', 0)}`",
            f"- Warning budgets: `{intel_summary.get('warning_budget_count', 0)}`",
            f"- Red detectives: `{intel_summary.get('bad_detector_count', 0)}`",
            f"- Top action: {intel_summary.get('top_action') or 'No priority action generated.'}",
            "",
            "### Performance Budgets",
            "",
        ])
        for budget in (intelligence.get("budgets") or []):
            lines.append(
                f"- **{budget.get('label')}** — `{budget.get('status')}` "
                f"({_format_perf_value(budget.get('actual'), budget.get('unit', ''))} / "
                f"{_format_perf_value(budget.get('limit'), budget.get('unit', ''))})"
            )
        lines.extend(["", "### Detectives", ""])
        for detective in (intelligence.get("detectives") or []):
            lines.append(f"- **{detective.get('title')}** — `{detective.get('status')}`: {detective.get('summary')}")
            evidence = detective.get("evidence") or []
            if evidence:
                lines.append(f"  - Evidence: {'; '.join(str(item) for item in evidence[:4])}")
        waterfall = intelligence.get("waterfall") or {}
        lines.extend([
            "",
            "### Waterfall & Third-Party Tax",
            "",
            f"- Sampled assets: `{waterfall.get('asset_count', 0)}`",
            f"- First-party bytes: `{_format_perf_value(waterfall.get('first_party_bytes'), 'bytes')}`",
            f"- Third-party bytes: `{_format_perf_value(waterfall.get('third_party_bytes'), 'bytes')}`",
            f"- Blocking markup pages: `{waterfall.get('blocking_markup_pages', 0)}`",
            "",
        ])
        third_party = intelligence.get("third_party_tax") or {}
        for host in (third_party.get("top_hosts") or [])[:6]:
            lines.append(
                f"- `{host.get('host')}` — risk `{host.get('risk')}`, "
                f"mentions `{host.get('page_mentions')}`, sampled bytes `{_format_perf_value(host.get('sampled_bytes'), 'bytes')}`"
            )
        cache = intelligence.get("cache_simulation") or {}
        lines.extend([
            "",
            "### Cache Simulation",
            "",
            f"- Repeat-visit risk: `{cache.get('repeat_visit_risk', 'unknown')}`",
            f"- Reusable bytes: `{_format_perf_value(cache.get('repeat_visit_reusable_bytes'), 'bytes')}`",
            f"- Risky repeat-visit bytes: `{_format_perf_value(cache.get('repeat_visit_risky_bytes'), 'bytes')}`",
            f"- Summary: {cache.get('summary', '')}",
            "",
            "### Action Plan",
            "",
        ])
        for action in (intelligence.get("action_plan") or []):
            lines.extend([
                f"#### P{action.get('priority')} — {action.get('title')}",
                "",
                f"- Impact: `{action.get('impact')}`",
                f"- Effort: `{action.get('effort')}`",
                f"- Evidence: {action.get('evidence')}",
                f"- Dev prompt: {action.get('dev_prompt')}",
                f"- Validation: {action.get('validation')}",
                "",
            ])
    if regression:
        lines.extend(["## Regression Compare", ""])
        if regression.get("available"):
            lines.extend([
                f"- Previous audit: `{regression.get('previous_audit_id')}`",
                f"- Risk: `{regression.get('risk')}`",
                f"- Summary: {regression.get('summary')}",
                "",
            ])
            for label, values in (regression.get("deltas") or {}).items():
                lines.append(
                    f"- **{label.replace('_', ' ').title()}**: `{values.get('previous')}` → `{values.get('current')}` "
                    f"(delta `{values.get('delta')}`)"
                )
            if regression.get("regressions"):
                lines.extend(["", "### Regressions", ""])
                for item in regression.get("regressions") or []:
                    lines.append(f"- {item}")
            if regression.get("improvements"):
                lines.extend(["", "### Improvements", ""])
                for item in regression.get("improvements") or []:
                    lines.append(f"- {item}")
        else:
            lines.append(f"- {regression.get('summary') or 'No previous audit available.'}")
        lines.append("")

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
        "Respect the Performance Intelligence action-plan order, budgets, detectives, "
        "cache simulation, third-party tax, and lab/field confidence. "
        "Produce the exact implementation plan and concrete fixes only.\n\n"
        f"{report}"
    )


def build_ci_gate_payload(audit: Dict[str, Any]) -> Dict[str, Any]:
    summary = audit.get("summary") or {}
    intelligence = _performance_intelligence(audit)
    regression = _performance_regression(audit)
    findings = audit.get("findings") or []
    score = summary.get("global_score")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = 0.0
    intel_summary = intelligence.get("summary") or {}
    failed_budgets = [
        item for item in (intelligence.get("budgets") or [])
        if str(item.get("status") or "").lower() == "fail"
    ]
    high_findings = [
        item for item in findings
        if str(item.get("severity") or "").lower() in {"critical", "high"}
    ]
    failures: List[str] = []
    warnings: List[str] = []
    if str(audit.get("status") or "").lower() != "done":
        failures.append("Audit is not complete.")
    if numeric_score < 70:
        failures.append(f"Global score is below release gate: {numeric_score}.")
    elif numeric_score < 80:
        warnings.append(f"Global score is below ideal target: {numeric_score}.")
    if failed_budgets:
        failures.append(f"{len(failed_budgets)} performance budget(s) failed.")
    if len(high_findings) >= 3:
        failures.append(f"{len(high_findings)} high/critical finding(s) remain.")
    elif high_findings:
        warnings.append(f"{len(high_findings)} high/critical finding(s) remain.")
    if regression.get("risk") == "regressed":
        failures.append("Regression risk detected versus the previous completed audit.")
    if not summary.get("lab_data_available"):
        warnings.append("No reliable lab data was available.")
    if not summary.get("field_data_available"):
        warnings.append("No public field data was available.")
    return {
        "schema": "joyboy.perfatlas.ci_gate.v1",
        "audit_id": audit.get("id") or "",
        "target": summary.get("target") or (audit.get("target") or {}).get("normalized_url") or "",
        "status": "failed" if failures else "passed",
        "passed": not failures,
        "score": numeric_score,
        "minimum_score": 70,
        "ideal_score": 80,
        "diagnostic_confidence": intel_summary.get("diagnostic_confidence") or summary.get("diagnostic_confidence") or "limited",
        "failed_budget_count": len(failed_budgets),
        "high_or_critical_finding_count": len(high_findings),
        "regression_risk": regression.get("risk") or "unknown",
        "failures": failures,
        "warnings": warnings,
        "top_action": intel_summary.get("top_action") or summary.get("top_performance_action") or "",
        "budgets": intelligence.get("budgets") or [],
    }


def build_evidence_pack(audit: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = audit.get("snapshot") or {}
    return {
        "schema": "joyboy.perfatlas.evidence_pack.v1",
        "audit_id": audit.get("id") or "",
        "target": audit.get("target") or {},
        "summary": audit.get("summary") or {},
        "runtime": snapshot.get("runtime") or {},
        "field_data": snapshot.get("field_data") or [],
        "lab_runs": snapshot.get("lab_runs") or [],
        "pages": snapshot.get("pages") or [],
        "asset_samples": snapshot.get("asset_samples") or [],
        "template_clusters": snapshot.get("template_clusters") or [],
        "performance_intelligence": _performance_intelligence(audit),
        "regression": _performance_regression(audit),
        "provider_statuses": snapshot.get("provider_statuses") or [],
        "findings": audit.get("findings") or [],
        "remediation_items": audit.get("remediation_items") or [],
    }


def build_report_html(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    intelligence = _performance_intelligence(audit)
    intelligence_summary = intelligence.get("summary") or {}
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
    action_rows = "".join(
        "<tr>"
        f"<td>P{item.get('priority')}</td>"
        f"<td>{item.get('title')}</td>"
        f"<td>{item.get('impact')}</td>"
        f"<td>{item.get('effort')}</td>"
        "</tr>"
        for item in (intelligence.get("action_plan") or [])
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
  <h2>Performance Intelligence</h2>
  <p class="muted">Failed budgets: {intelligence_summary.get('failed_budget_count', 0)} · Red detectives: {intelligence_summary.get('bad_detector_count', 0)} · Confidence: {intelligence_summary.get('diagnostic_confidence', 'limited')}</p>
  <table>
    <thead><tr><th>Priority</th><th>Action</th><th>Impact</th><th>Effort</th></tr></thead>
    <tbody>{action_rows}</tbody>
  </table>
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
    if fmt in {"ci", "ci-gate", "budget-gate"}:
        return {
            "content": json.dumps(build_ci_gate_payload(audit), ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "CI performance gate",
        }
    if fmt in {"evidence", "evidence-pack"}:
        return {
            "content": json.dumps(build_evidence_pack(audit), ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "Evidence pack",
        }
    raise ValueError(f"Unsupported export format: {export_format}")


def render_pdf_bytes(audit: Dict[str, Any]) -> bytes:
    html = build_report_html(audit)
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("WeasyPrint is not available for PDF exports.") from exc
    return HTML(string=html).write_pdf()
