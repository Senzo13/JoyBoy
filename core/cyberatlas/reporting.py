"""Structured reporting and export helpers for CyberAtlas."""

from __future__ import annotations

import json
from html import escape as html_escape
from typing import Any, Dict, List


def _fmt(value: Any, fallback: str = "n/a") -> str:
    if value in (None, "", [], {}):
        return fallback
    return str(value)


def _severity_counts(audit: Dict[str, Any]) -> Dict[str, int]:
    summary = audit.get("summary") or {}
    return {
        "critical": int(summary.get("critical_count") or 0),
        "high": int(summary.get("high_count") or 0),
        "medium": int(summary.get("medium_count") or 0),
        "low": int(summary.get("low_count") or 0),
    }


def build_executive_summary(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    snapshot = audit.get("snapshot") or {}
    tls = snapshot.get("tls") or {}
    openapi = snapshot.get("openapi") or {}
    recon = snapshot.get("recon_summary") or {}
    protections = snapshot.get("protections") or {}
    counts = _severity_counts(audit)
    lines = [
        f"CyberAtlas audited {summary.get('target') or 'the requested target'} in {summary.get('mode', 'public')} mode.",
        f"Defensive security score: {summary.get('global_score', 'n/a')} / 100.",
        f"Risk level: {summary.get('risk_level', 'Unknown')}.",
        (
            f"Coverage: {summary.get('pages_crawled', 0)} page(s), "
            f"{summary.get('exposure_count', 0)} reachable exposure probe(s), "
            f"{summary.get('endpoint_count', 0)} endpoint signal(s)."
        ),
        (
            f"Severity mix: {counts['critical']} critical, {counts['high']} high, "
            f"{counts['medium']} medium, {counts['low']} low."
        ),
    ]
    if tls.get("available"):
        lines.append(
            f"TLS: {tls.get('protocol') or 'unknown protocol'}, certificate days remaining: {tls.get('days_remaining', 'n/a')}."
        )
    elif tls.get("error"):
        lines.append(f"TLS probe note: {tls.get('error')}.")
    if openapi.get("available"):
        lines.append(
            f"OpenAPI: {openapi.get('endpoint_count', 0)} endpoint(s) parsed from {openapi.get('source_url') or 'public spec'}, "
            f"{openapi.get('unauthenticated_count', 0)} without declared security."
        )
    if recon:
        lines.append(
            "Recon: "
            f"framework={recon.get('framework') or 'unknown'}, "
            f"database_hint={recon.get('database_type') or 'Unknown'}, "
            f"auth_surface={recon.get('auth_surface_count', 0)}, "
            f"source_maps={recon.get('source_map_count', 0)}."
        )
    if protections:
        cdn = ", ".join(protections.get("cdn") or []) or "none observed"
        lines.append(
            f"Edge protection signals: CDN={cdn}, WAF={bool(protections.get('waf_detected'))}, "
            f"rate-limit={bool(protections.get('rate_limit_detected'))}."
        )
    blocking = summary.get("blocking_risk") or {}
    if blocking.get("level") not in {"", "Low", None}:
        lines.append(f"Blocking risk: {blocking.get('level')} - {blocking.get('summary')}")
    top = (audit.get("findings") or [])[:5]
    if top:
        lines.append("Priority security findings:")
        for item in top:
            lines.append(f"- {item.get('title')} [{item.get('severity')} / {item.get('confidence')}]")
    return "\n".join(lines)


def build_markdown_report(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    snapshot = audit.get("snapshot") or {}
    tls = snapshot.get("tls") or {}
    headers = snapshot.get("security_headers") or {}
    probes = snapshot.get("exposure_probes") or []
    openapi = snapshot.get("openapi") or {}
    api_inventory = snapshot.get("api_inventory") or {}
    frontend_hints = snapshot.get("frontend_hints") or {}
    protections = snapshot.get("protections") or {}
    recon = snapshot.get("recon_summary") or {}
    pages = snapshot.get("pages") or []
    scores = audit.get("scores") or []
    findings = audit.get("findings") or []
    remediation = audit.get("remediation_items") or []
    lines = [
        "# CyberAtlas Audit",
        "",
        f"- Target: `{summary.get('target', '')}`",
        f"- Mode: `{summary.get('mode', 'public')}`",
        f"- Profile: `{summary.get('profile', 'elevated')}`",
        f"- Defensive score: `{summary.get('global_score', 'n/a')}`",
        f"- Risk level: `{summary.get('risk_level', 'Unknown')}`",
        f"- Safe mode: `{bool(summary.get('safe_mode', True))}`",
        f"- Discovered endpoint signals: `{summary.get('discovered_endpoint_count', 0)}`",
        f"- Frontend API references: `{summary.get('frontend_api_reference_count', 0)}`",
        f"- Source maps: `{summary.get('source_map_count', 0)}`",
        "",
        "## Executive Summary",
        "",
        build_executive_summary(audit),
        "",
        "## Scope & Safety",
        "",
        "- CyberAtlas v1 performs defensive HTTP evidence collection, header review, TLS inspection, OpenAPI parsing, and safe public exposure probes.",
        "- It does not exploit targets, brute-force logins, attempt stealth, or send injection payloads.",
        "- Treat every result as a prioritized remediation signal; confirm high-risk changes in a controlled environment.",
        "",
        "## TLS",
        "",
        f"- Available: `{bool(tls.get('available'))}`",
        f"- Protocol: `{_fmt(tls.get('protocol'))}`",
        f"- Issuer: `{_fmt(tls.get('issuer'))}`",
        f"- Certificate expiry: `{_fmt(tls.get('not_after'))}`",
        f"- Days remaining: `{_fmt(tls.get('days_remaining'))}`",
        f"- Probe error: `{_fmt(tls.get('error'), '')}`",
        "",
        "## Recon & Edge Protection",
        "",
        f"- Framework hint: `{_fmt(recon.get('framework'))}`",
        f"- Database hint: `{_fmt(recon.get('database_type'))}`",
        f"- CDN signals: `{', '.join(protections.get('cdn') or []) or 'none observed'}`",
        f"- WAF signal: `{bool(protections.get('waf_detected'))}`",
        f"- Rate-limit signal: `{bool(protections.get('rate_limit_detected'))}`",
        f"- Auth surface signals: `{recon.get('auth_surface_count', 0)}`",
        f"- Public sensitive endpoint signals: `{recon.get('sensitive_public_endpoint_count', 0)}`",
        "",
        "## Security Headers",
        "",
    ]
    if headers:
        for key, value in headers.items():
            lines.append(f"- `{key}`: `{str(value)[:240]}`")
    else:
        lines.append("- No response headers captured.")
    lines.extend(["", "## Exposure Probes", ""])
    for probe in probes:
        status = probe.get("status_code")
        exists = "reachable" if probe.get("exists") else "not reachable"
        lines.append(
            f"- `{probe.get('path')}` - {exists}, HTTP `{status if status is not None else 'n/a'}`, "
            f"type `{probe.get('content_type') or 'unknown'}`"
        )
    lines.extend(["", "## OpenAPI / API Surface", ""])
    if openapi.get("available"):
        lines.extend([
            f"- Source: `{openapi.get('source_url')}`",
            f"- Title: `{openapi.get('title') or 'n/a'}`",
            f"- Version: `{openapi.get('version') or 'n/a'}`",
            f"- Endpoints parsed: `{openapi.get('endpoint_count', 0)}`",
            f"- Operations without declared security: `{openapi.get('unauthenticated_count', 0)}`",
            "",
        ])
        for endpoint in (openapi.get("endpoints") or [])[:30]:
            security = "auth declared" if endpoint.get("security_declared") else "no auth declaration"
            lines.append(f"- `{endpoint.get('method')} {endpoint.get('path')}` - {security}")
    else:
        lines.append("- No public OpenAPI document was parsed in this audit.")
    inventory_endpoints = api_inventory.get("endpoints") or []
    lines.extend(["", "## Discovered API Inventory", ""])
    if inventory_endpoints:
        lines.extend([
            f"- Endpoint signals: `{api_inventory.get('endpoint_count', len(inventory_endpoints))}`",
            f"- Auth-protected signals: `{api_inventory.get('auth_protected_count', 0)}`",
            f"- Sensitive-looking public signals: `{api_inventory.get('public_sensitive_count', 0)}`",
            "",
        ])
        for endpoint in inventory_endpoints[:40]:
            auth = "auth required" if endpoint.get("requires_auth") else "public/unknown auth"
            methods = ", ".join(endpoint.get("allowed_methods") or []) or "not declared"
            lines.append(
                f"- `{endpoint.get('path')}` - HTTP `{endpoint.get('status_code')}`, {auth}, "
                f"type `{endpoint.get('response_type')}`, methods `{methods}`"
            )
    else:
        lines.append("- No additional endpoint inventory signals were found.")
    lines.extend(["", "## Frontend Code Hints", ""])
    if frontend_hints:
        backend_hosts = ", ".join(frontend_hints.get("backend_hosts") or []) or "none"
        lines.extend([
            f"- API references: `{frontend_hints.get('api_reference_count', 0)}`",
            f"- Backend hosts referenced: `{backend_hosts}`",
            f"- Private backend hosts: `{', '.join(frontend_hints.get('private_backend_hosts') or []) or 'none'}`",
            f"- Source maps: `{frontend_hints.get('source_map_count', 0)}`",
            f"- Secret-like identifier names: `{', '.join(frontend_hints.get('secret_name_hints') or []) or 'none'}`",
            "",
        ])
        for ref in (frontend_hints.get("api_references") or [])[:30]:
            lines.append(f"- `{ref.get('kind')}` `{ref.get('url')}` from `{ref.get('source')}`")
    else:
        lines.append("- No frontend code hints were collected.")
    lines.extend(["", "## Sampled Pages & Forms", ""])
    for page in pages[:8]:
        lines.extend([
            f"### {page.get('final_url') or page.get('url')}",
            "",
            f"- HTTP status: `{page.get('status_code')}`",
            f"- Title: `{page.get('title') or ''}`",
            f"- Forms: `{page.get('form_count', 0)}`",
            f"- Password forms: `{page.get('password_form_count', 0)}`",
            f"- Mixed content references: `{page.get('mixed_content_count', 0)}`",
            f"- Error indicators: `{', '.join(page.get('body_error_indicators') or []) or 'none'}`",
            "",
        ])
    lines.extend(["## Scores", ""])
    for score in scores:
        lines.append(
            f"- **{score.get('label')}** - {score.get('score')} / 100 "
            f"(confidence: {score.get('confidence')}, coverage: {score.get('coverage')})"
        )
    lines.extend(["", "## Findings", ""])
    if findings:
        for item in findings:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- Scope: `{item.get('scope')}`",
                f"- Category: `{item.get('category')}`",
                f"- Severity: `{item.get('severity')}`",
                f"- Confidence: `{item.get('confidence')}`",
                f"- Evidence mode: `{item.get('evidence_mode')}`",
                f"- Diagnostic: {item.get('diagnostic')}",
                f"- Probable cause: {item.get('probable_cause')}",
                f"- Recommended fix: {item.get('recommended_fix')}",
                f"- Acceptance criteria: {item.get('acceptance_criteria')}",
                "",
            ])
            evidence = item.get("evidence") or []
            if evidence:
                lines.append("Evidence:")
                for evidence_item in evidence[:6]:
                    lines.append(f"- {evidence_item}")
                lines.append("")
    else:
        lines.extend(["No blocking cyber findings were detected in the sampled evidence.", ""])
    if remediation:
        lines.extend(["## Remediation Pack", ""])
        for item in remediation[:20]:
            lines.extend([
                f"### {item.get('finding_id')}",
                "",
                f"- Severity: `{item.get('severity')}`",
                f"- Fix: {item.get('recommended_fix')}",
                f"- Validation: {item.get('acceptance_criteria')}",
                f"- Implementation prompt: {item.get('dev_prompt')}",
                "",
            ])
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
        "Use the following CyberAtlas audit as the deterministic source of truth. "
        "This is defensive remediation work. Do not invent vulnerabilities, do not add exploit steps, "
        "and do not request secrets. Produce concrete secure-code/configuration fixes, rollout order, "
        "and validation steps only.\n\n"
        f"{report}"
    )


def build_security_gate_payload(audit: Dict[str, Any]) -> Dict[str, Any]:
    summary = audit.get("summary") or {}
    findings = audit.get("findings") or []
    failures: List[str] = []
    warnings: List[str] = []
    if str(audit.get("status") or "").lower() != "done":
        failures.append("Audit is not complete.")
    if int(summary.get("critical_count") or 0) > 0:
        failures.append(f"{summary.get('critical_count')} critical security finding(s) remain.")
    if int(summary.get("high_count") or 0) >= 2:
        failures.append(f"{summary.get('high_count')} high security finding(s) remain.")
    elif int(summary.get("high_count") or 0) == 1:
        warnings.append("1 high security finding remains.")
    if float(summary.get("global_score") or 0) < 70:
        failures.append(f"Security score below gate: {summary.get('global_score')}.")
    if not summary.get("safe_mode"):
        warnings.append("Audit used expanded safe probes; confirm scan authorization.")
    if int(summary.get("public_sensitive_endpoint_count") or 0) > 0:
        warnings.append(f"{summary.get('public_sensitive_endpoint_count')} sensitive-looking public endpoint signal(s) need review.")
    if int(summary.get("source_map_count") or 0) > 0:
        warnings.append(f"{summary.get('source_map_count')} public source map signal(s) were detected.")
    return {
        "schema": "joyboy.cyberatlas.security_gate.v1",
        "audit_id": audit.get("id") or "",
        "target": summary.get("target") or (audit.get("target") or {}).get("normalized_url") or "",
        "status": "failed" if failures else "passed",
        "passed": not failures,
        "score": summary.get("global_score"),
        "risk_level": summary.get("risk_level"),
        "critical_count": summary.get("critical_count", 0),
        "high_count": summary.get("high_count", 0),
        "public_sensitive_endpoint_count": summary.get("public_sensitive_endpoint_count", 0),
        "source_map_count": summary.get("source_map_count", 0),
        "failures": failures,
        "warnings": warnings,
        "top_findings": findings[:8],
    }


def build_evidence_pack(audit: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = audit.get("snapshot") or {}
    return {
        "schema": "joyboy.cyberatlas.evidence_pack.v1",
        "audit_id": audit.get("id") or "",
        "target": audit.get("target") or {},
        "summary": audit.get("summary") or {},
        "tls": snapshot.get("tls") or {},
        "security_headers": snapshot.get("security_headers") or {},
        "pages": snapshot.get("pages") or [],
        "forms": snapshot.get("forms") or [],
        "exposure_probes": snapshot.get("exposure_probes") or [],
        "openapi": snapshot.get("openapi") or {},
        "api_inventory": snapshot.get("api_inventory") or {},
        "frontend_hints": snapshot.get("frontend_hints") or {},
        "protections": snapshot.get("protections") or {},
        "recon_summary": snapshot.get("recon_summary") or {},
        "findings": audit.get("findings") or [],
        "remediation_items": audit.get("remediation_items") or [],
    }


def build_report_html(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    counts = _severity_counts(audit)
    score_cards = "".join(
        f"<div class='score-card'><div class='label'>{html_escape(str(score.get('label')))}</div>"
        f"<div class='value'>{html_escape(str(score.get('score')))}</div>"
        f"<div class='meta'>{html_escape(str(score.get('confidence')))}</div></div>"
        for score in (audit.get("scores") or [])
    )
    rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('title') or ''))}</td>"
        f"<td>{html_escape(str(item.get('severity') or ''))}</td>"
        f"<td>{html_escape(str(item.get('confidence') or ''))}</td>"
        f"<td>{html_escape(str(item.get('scope') or ''))}</td>"
        "</tr>"
        for item in (audit.get("findings") or [])
    )
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CyberAtlas Audit</title>
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
  <h1>CyberAtlas Audit</h1>
  <div class="muted">{html_escape(str(summary.get('target', '')))}</div>
  <p>{html_escape(build_executive_summary(audit)).replace(chr(10), '<br>')}</p>
  <p><strong>Severity mix:</strong> {counts['critical']} critical · {counts['high']} high · {counts['medium']} medium · {counts['low']} low</p>
  <div class="scores">{score_cards}</div>
  <h2>Findings</h2>
  <table>
    <thead><tr><th>Issue</th><th>Severity</th><th>Confidence</th><th>Scope</th></tr></thead>
    <tbody>{rows}</tbody>
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
    if fmt in {"gate", "security-gate", "ci"}:
        return {
            "content": json.dumps(build_security_gate_payload(audit), ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "Security gate",
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
