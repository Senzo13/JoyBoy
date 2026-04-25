"""Structured reporting and export helpers for SignalAtlas."""

from __future__ import annotations

import json
from html import escape as html_escape
from typing import Any, Dict, List


def _validation_state_label(value: str) -> str:
    labels = {
        "confirmed": "Confirmed",
        "needs_render_validation": "Needs render validation",
    }
    return labels.get(str(value or "").strip().lower(), "Confirmed")


def _evidence_mode_label(value: str) -> str:
    labels = {
        "raw_html": "Raw HTML baseline",
        "raw_html_vs_rendered": "Raw HTML + rendered comparison",
        "owner_confirmed": "Owner confirmed",
        "public_crawl": "Public crawl",
    }
    return labels.get(str(value or "").strip().lower(), "Public crawl")


def _group_findings(findings: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "root_causes": [item for item in findings if item.get("root_cause")],
        "derived": [item for item in findings if item.get("derived_from")],
        "other": [item for item in findings if not item.get("root_cause") and not item.get("derived_from")],
    }


def _signal_label(value: str) -> str:
    labels = {
        "google": "Google",
        "bing": "Bing",
        "indexnow": "IndexNow",
        "crawlability": "Crawlability",
        "sitemap_coherence": "Sitemap coherence",
        "js_render_risk": "JS rendering",
        "geo": "GEO / AI visibility",
    }
    return labels.get(str(value or "").strip(), str(value or "").replace("_", " ").title())


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(round(float(value or 0))):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_float(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_percent(value: Any) -> str:
    try:
        return f"{float(value or 0) * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def _organic_type_label(value: str) -> str:
    labels = {
        "quick_win": "Quick win",
        "ctr_gap": "CTR gap",
        "ranking_distance": "Ranking distance",
        "content_gap": "Content gap",
        "low_value": "Low value",
        "brand_query": "Brand query",
        "non_brand_query": "Non-brand query",
    }
    return labels.get(str(value or "").strip().lower(), str(value or "").replace("_", " ").title())


def _organic_potential_markdown(audit: Dict[str, Any]) -> List[str]:
    organic = audit.get("organic_potential") or {}
    if not organic:
        return [
            "## Organic Potential",
            "",
            "- No Google Search Console CSV import is attached to this audit yet.",
            "",
        ]

    summary = organic.get("summary") or {}
    lines = [
        "## Organic Potential",
        "",
        "- Source: `Google Search Console CSV`",
        f"- Mapping mode: `{organic.get('mapping_mode', 'separate_gsc_exports')}`",
        f"- Clicks: `{_fmt_int(summary.get('clicks'))}`",
        f"- Impressions: `{_fmt_int(summary.get('impressions'))}`",
        f"- CTR: `{_fmt_percent(summary.get('ctr'))}`",
        f"- Average position: `{_fmt_float(summary.get('average_position'), 2)}`",
        f"- Estimated missed clicks: `{_fmt_float(summary.get('missed_clicks'), 1)}`",
        f"- Pages analyzed: `{_fmt_int(summary.get('page_count'))}`",
        f"- Queries analyzed: `{_fmt_int(summary.get('query_count'))}`",
        "",
        "SignalAtlas treats GSC clicks, impressions, CTR, and positions as confirmed demand data. "
        "Page/query joins are marked as inferred when the imported CSV files are separate GSC exports.",
        "",
    ]

    opportunities = organic.get("opportunities") or []
    if opportunities:
        lines.extend(["### Highest-priority opportunities", ""])
        for item in opportunities[:10]:
            lines.append(
                f"- **{item.get('kind')}** `{item.get('label')}` — "
                f"{_organic_type_label(item.get('opportunity_type'))}, "
                f"priority `{_fmt_float(item.get('priority_score'), 1)}`, "
                f"missed clicks `{_fmt_float(item.get('missed_clicks'), 1)}`. "
                f"{item.get('recommended_action') or ''}"
            )
        lines.append("")

    pages = organic.get("pages") or []
    if pages:
        lines.extend(["### Top page opportunities", ""])
        for page in pages[:8]:
            flags = ", ".join(page.get("content_flags") or []) or "none"
            lines.append(
                f"- `{page.get('url')}` — impressions `{_fmt_int(page.get('impressions'))}`, "
                f"clicks `{_fmt_int(page.get('clicks'))}`, CTR `{_fmt_percent(page.get('ctr'))}`, "
                f"position `{_fmt_float(page.get('position'), 2)}`, flags `{flags}`."
            )
        lines.append("")

    queries = organic.get("queries") or []
    if queries:
        lines.extend(["### Top query opportunities", ""])
        for query in queries[:12]:
            types = ", ".join(_organic_type_label(item) for item in (query.get("opportunity_types") or []))
            lines.append(
                f"- `{query.get('query')}` — {types}; impressions `{_fmt_int(query.get('impressions'))}`, "
                f"clicks `{_fmt_int(query.get('clicks'))}`, position `{_fmt_float(query.get('position'), 2)}`."
            )
        lines.append("")

    cannibalization = organic.get("cannibalization_candidates") or []
    if cannibalization:
        lines.extend(["### Probable cannibalization / URL variants", ""])
        for item in cannibalization[:6]:
            lines.append(
                f"- `{item.get('signature')}` — {item.get('url_count')} URL(s), "
                f"`{_fmt_int(item.get('impressions'))}` impressions, confidence `{item.get('mapping_confidence')}`."
            )
        lines.append("")

    return lines


def _organic_potential_html(audit: Dict[str, Any]) -> str:
    organic = audit.get("organic_potential") or {}
    if not organic:
        return (
            "<h2>Organic Potential</h2>"
            "<p class='muted'>No Google Search Console CSV import is attached to this audit yet.</p>"
        )

    summary = organic.get("summary") or {}
    cards = [
        ("Clicks", _fmt_int(summary.get("clicks")), "Confirmed GSC clicks"),
        ("Impressions", _fmt_int(summary.get("impressions")), "Confirmed GSC impressions"),
        ("CTR", _fmt_percent(summary.get("ctr")), "Clicks divided by impressions"),
        ("Average position", _fmt_float(summary.get("average_position"), 2), "Weighted by impressions"),
        ("Missed clicks", _fmt_float(summary.get("missed_clicks"), 1), "Estimated from position-based CTR"),
        ("Opportunities", _fmt_int(summary.get("opportunity_count")), "Rows above priority threshold"),
    ]
    card_html = "".join(
        "<div class='score-card'>"
        f"<div class='label'>{html_escape(label)}</div>"
        f"<div class='value'>{html_escape(value)}</div>"
        f"<div class='meta'>{html_escape(meta)}</div>"
        "</div>"
        for label, value, meta in cards
    )
    rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('kind') or ''))}</td>"
        f"<td>{html_escape(str(item.get('label') or ''))}</td>"
        f"<td>{html_escape(_organic_type_label(item.get('opportunity_type')))}</td>"
        f"<td>{html_escape(_fmt_float(item.get('priority_score'), 1))}</td>"
        f"<td>{html_escape(_fmt_int(item.get('impressions')))}</td>"
        f"<td>{html_escape(_fmt_float(item.get('missed_clicks'), 1))}</td>"
        "</tr>"
        for item in (organic.get("opportunities") or [])[:12]
    )
    return (
        "<h2>Organic Potential</h2>"
        "<p class='muted'>Confirmed Google Search Console CSV metrics, with page/query joins marked inferred when exports are separate.</p>"
        f"<div class='scores'>{card_html}</div>"
        "<table>"
        "<thead><tr><th>Kind</th><th>Page / query</th><th>Type</th><th>Priority</th><th>Impressions</th><th>Missed clicks</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def build_executive_summary(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    owner_context = audit.get("owner_context") or {}
    render_detection = (audit.get("snapshot") or {}).get("render_detection") or {}
    visibility_signals = (audit.get("snapshot") or {}).get("visibility_signals") or {}
    organic_summary = (audit.get("organic_potential") or {}).get("summary") or {}
    grouped = _group_findings(findings)
    primary_root = grouped["root_causes"][0] if grouped["root_causes"] else {}
    top_findings = findings[:5]
    lines = [
        f"SignalAtlas audited {summary.get('target') or 'the requested site'} in {summary.get('mode', 'public')} mode.",
        f"Global readiness score: {summary.get('global_score', 'n/a')}.",
        f"Detected platform: {summary.get('platform', 'Custom')} with {summary.get('rendering', 'hybrid')} rendering.",
        (
            f"Sample coverage: {summary.get('pages_crawled', 0)} page(s) analyzed "
            f"from {summary.get('pages_discovered', summary.get('pages_crawled', 0))} discovered URL(s), "
            f"bounded by a page budget of {summary.get('page_budget', summary.get('pages_crawled', 0))}."
        ),
    ]
    if summary.get("sitemap_url_count"):
        lines.append(
            f"Sitemap discovery found {summary.get('sitemap_url_count')} URL(s) across {summary.get('sitemap_index_count', 0)} nested sitemap index file(s)."
        )
    if primary_root:
        lines.append(
            f"Primary root cause: {primary_root.get('title')} "
            f"({primary_root.get('severity')}, {_validation_state_label(primary_root.get('validation_state'))})."
        )
    if summary.get("blocking_risk", {}).get("level") not in {"", "Low", None}:
        lines.append(
            f"Blocking risk: {summary.get('blocking_risk', {}).get('level')} — "
            f"{summary.get('blocking_risk', {}).get('summary')}"
        )
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
    if visibility_signals.get("indexnow", {}).get("status") in {"Strong signal", "Confirmed"}:
        lines.append(f"IndexNow: {visibility_signals.get('indexnow', {}).get('note')}")
    if visibility_signals.get("geo", {}).get("status") in {"Strong signal", "Confirmed"}:
        lines.append(f"GEO / AI visibility: {visibility_signals.get('geo', {}).get('note')}")
    if organic_summary:
        lines.append(
            "Organic potential from GSC CSV: "
            f"{_fmt_int(organic_summary.get('clicks'))} click(s), "
            f"{_fmt_int(organic_summary.get('impressions'))} impression(s), "
            f"CTR {_fmt_percent(organic_summary.get('ctr'))}, "
            f"estimated missed clicks {_fmt_float(organic_summary.get('missed_clicks'), 1)}."
        )
    if grouped["derived"] and summary.get("baseline_only"):
        lines.append(
            f"{len(grouped['derived'])} downstream symptom(s) are currently treated as raw-HTML baseline signals and should be revalidated after rendered-browser probing."
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
    owner_context = audit.get("owner_context") or {}
    render_detection = snapshot.get("render_detection") or {}
    visibility_signals = snapshot.get("visibility_signals") or {}
    lines = [
        "# SignalAtlas Audit",
        "",
        f"- Target: `{summary.get('target', '')}`",
        f"- Mode: `{summary.get('mode', 'public')}`",
        f"- Global score: `{summary.get('global_score', 'n/a')}`",
        f"- Platform: `{summary.get('platform', 'Custom')}`",
        f"- Rendering: `{summary.get('rendering', 'hybrid')}`",
        f"- Pages sampled: `{summary.get('pages_crawled', 0)}`",
        f"- Page budget: `{summary.get('page_budget', summary.get('pages_crawled', 0))}`",
        f"- URLs discovered in crawl graph: `{summary.get('pages_discovered', summary.get('pages_crawled', 0))}`",
        f"- Sitemap URLs discovered: `{summary.get('sitemap_url_count', 0)}`",
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
        "### Search & AI visibility signals",
        "",
    ])
    if visibility_signals:
        for key, payload in visibility_signals.items():
            if not isinstance(payload, dict):
                continue
            lines.append(
                f"- **{_signal_label(key)}** — status `{payload.get('status', 'Unknown')}`, confidence `{payload.get('confidence', 'Unknown')}`"
            )
            if payload.get("note"):
                lines.append(f"  - Detail: {payload.get('note')}")
        lines.append("")
    else:
        lines.extend([
            "- No visibility signals were attached to this audit.",
            "",
        ])

    lines.extend(_organic_potential_markdown(audit))

    lines.extend([
        "## Root Cause Snapshot",
        "",
    ])

    blocking_risk = summary.get("blocking_risk") or {}
    if blocking_risk:
        lines.extend([
            f"- Blocking risk: `{blocking_risk.get('level', 'Low')}`",
            f"- Summary: {blocking_risk.get('summary', 'No blocking root cause was detected in the sampled baseline.')}",
            "",
        ])

    grouped = _group_findings(findings)
    if grouped["root_causes"]:
        lines.append("### Root causes")
        lines.append("")
        for item in grouped["root_causes"]:
            lines.extend(
                [
                    f"- **{item.get('title')}** — {_validation_state_label(item.get('validation_state'))}, {_evidence_mode_label(item.get('evidence_mode'))}",
                    f"  - Diagnostic: {item.get('diagnostic')}",
                ]
            )
            if item.get("relationship_summary"):
                lines.append(f"  - Why it matters: {item.get('relationship_summary')}")
        lines.append("")

    if grouped["derived"]:
        lines.append("### Derived symptoms to revalidate")
        lines.append("")
        for item in grouped["derived"]:
            lines.extend(
                [
                    f"- **{item.get('title')}** — {_validation_state_label(item.get('validation_state'))}, {_evidence_mode_label(item.get('evidence_mode'))}",
                    f"  - Linked root cause(s): {', '.join(item.get('derived_from') or [])}",
                ]
            )
            if item.get("relationship_summary"):
                lines.append(f"  - Why it is derived: {item.get('relationship_summary')}")
        lines.append("")

    lines.extend([
        "## Sampling & Extraction Evidence",
        "",
        "- The crawl is intentionally bounded by the configured page budget.",
        "- `Sitemap URLs discovered` reflects URLs declared in sitemap files.",
        "- `Pages sampled` reflects the subset actually fetched and analyzed in this run.",
        "",
    ])
    evidence_pages = (snapshot.get("pages") or [])[:8]
    if evidence_pages:
        for page in evidence_pages:
            page_lines = [
                f"### {page.get('final_url') or page.get('url')}",
                "",
                f"- Final URL: `{page.get('final_url') or page.get('url')}`",
                f"- HTTP status: `{page.get('status_code', 0)}`",
                f"- Title: `{page.get('title', '')}`",
                f"- Canonical: `{page.get('canonical', '')}`",
                (
                    f"- HTML lang: `{page.get('html_lang', '') or 'unknown'}`"
                    f"; hreflang entries: `{len(page.get('hreflang') or [])}`"
                ),
                f"- H1 count: `{page.get('h1_count', (page.get('heading_counts') or {}).get('h1', 0))}`",
                (
                    f"- Visible text length: `{page.get('visible_text_length', 0)}` characters / "
                    f"`{page.get('word_count', 0)}` raw words / `{page.get('content_units', page.get('word_count', 0))}` content units"
                    f"{' (CJK-adjusted)' if page.get('cjk_adjusted') else ''}"
                ),
                (
                    f"- Missing image alt count: `{page.get('image_missing_alt', 0)}` of `{page.get('image_total', 0)}` image(s)"
                    f"; decorative empty-alt count: `{page.get('image_empty_alt', 0)}`"
                    f"{' (valid for decorative images)' if page.get('image_empty_alt', 0) else ''}"
                ),
                f"- Cleaned body excerpt: {page.get('body_text_excerpt') or page.get('visible_text_excerpt') or '(empty)' }",
                "",
            ]
            if page.get("nosnippet") or page.get("max_snippet") is not None:
                page_lines.insert(
                    7,
                    f"- Snippet directives: `nosnippet={bool(page.get('nosnippet'))}` / "
                    f"`max-snippet={page.get('max_snippet') if page.get('max_snippet') is not None else 'default'}`",
                )
            lines.extend(page_lines)
    else:
        lines.extend([
            "- No page-level evidence snapshot was attached to this audit.",
            "",
        ])

    lines.extend([
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
                    f"- Validation state: `{_validation_state_label(item.get('validation_state'))}`",
                    f"- Evidence mode: `{_evidence_mode_label(item.get('evidence_mode'))}`",
                    f"- Expected impact: `{item.get('expected_impact')}`",
                    f"- Diagnostic: {item.get('diagnostic')}",
                    f"- Probable cause: {item.get('probable_cause')}",
                    (
                        f"- Relationship: {item.get('relationship_summary')}"
                        if item.get("relationship_summary")
                        else ""
                    ),
                    (
                        f"- Derived from: `{', '.join(item.get('derived_from') or [])}`"
                        if item.get("derived_from")
                        else ""
                    ),
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
                f"avg content units `{cluster.get('avg_content_units', cluster.get('avg_word_count'))}`"
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
    visibility_signals = (audit.get("snapshot") or {}).get("visibility_signals") or {}
    blocking_risk = summary.get("blocking_risk") or {}
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
    visibility_cards = "".join(
        f"<div class='owner-card'><div class='label'>{_signal_label(key)}</div>"
        f"<div class='value'>{payload.get('status', 'Unknown')}</div>"
        f"<div class='meta'>{payload.get('note', '')}</div></div>"
        for key, payload in visibility_signals.items()
        if isinstance(payload, dict)
    )
    organic_section = _organic_potential_html(audit)
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
  <p><strong>Blocking risk:</strong> {blocking_risk.get('level', 'Low')} — {blocking_risk.get('summary', 'No blocking root cause was detected in the sampled baseline.')}</p>
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
  <h2>Search & AI Visibility Signals</h2>
  <div class="owner-grid">
    {visibility_cards or "<div class='owner-card'><div class='label'>signals</div><div class='value'>none</div><div class='meta'>No visibility signals were attached to this audit.</div></div>"}
  </div>
  {organic_section}
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
