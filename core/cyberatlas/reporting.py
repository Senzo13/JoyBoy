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
        f"Defensive security score: {summary.get('global_score', 'n/a')} / 100, grade {summary.get('security_grade') or 'n/a'}.",
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
    if int(summary.get("standard_attention_count") or 0) or int(summary.get("security_ticket_count") or 0):
        lines.append(
            f"Standards and execution: {summary.get('standard_attention_count', 0)} control area(s) need attention, "
            f"{summary.get('security_ticket_count', 0)} security ticket(s) generated."
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
    action_plan = audit.get("action_plan") or []
    owner_plan = audit.get("owner_verification_plan") or snapshot.get("owner_verification_plan") or []
    attack_paths = audit.get("attack_paths") or snapshot.get("attack_paths") or []
    coverage = audit.get("coverage") or snapshot.get("coverage") or {}
    standard_map = audit.get("standard_map") or snapshot.get("standard_map") or []
    security_tickets = audit.get("security_tickets") or snapshot.get("security_tickets") or []
    evidence_graph = audit.get("evidence_graph") or snapshot.get("evidence_graph") or {}
    recommendations = audit.get("recommendations") or []
    comparison = audit.get("comparison") or {}
    surface_matrix = snapshot.get("surface_matrix") or []
    lines = [
        "# CyberAtlas Audit",
        "",
        f"- Target: `{summary.get('target', '')}`",
        f"- Mode: `{summary.get('mode', 'public')}`",
        f"- Profile: `{summary.get('profile', 'elevated')}`",
        f"- Defensive score: `{summary.get('global_score', 'n/a')}`",
        f"- Security grade: `{summary.get('security_grade', 'n/a')}`",
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
        "## Action Plan",
        "",
    ]
    if action_plan:
        for item in action_plan:
            lines.extend([
                f"### {item.get('order')}. {item.get('title')}",
                "",
                f"- Priority: `{item.get('priority')}`",
                f"- Triggered: `{bool(item.get('triggered'))}`",
                f"- Why: {item.get('description')}",
                f"- Action: {item.get('action')}",
                f"- Validation: {item.get('validation')}",
                "",
            ])
            evidence = item.get("evidence") or []
            if evidence:
                lines.append("Evidence:")
                for evidence_item in evidence[:5]:
                    lines.append(f"- {evidence_item}")
                lines.append("")
    else:
        lines.extend(["- No action plan was generated.", ""])
    lines.extend([
        "## Standards Map",
        "",
        "- Mapping is deterministic and defensive. It helps prioritize remediation against common OWASP/ASVS/CWE families; it is not a certification claim.",
        "",
    ])
    if standard_map:
        for item in standard_map:
            if item.get("status") == "clear":
                continue
            lines.extend([
                f"### {item.get('framework')} {item.get('id')} - {item.get('label')}",
                "",
                f"- Status: `{item.get('status')}`",
                f"- Severity: `{item.get('severity')}`",
                f"- Finding count: `{item.get('finding_count', 0)}`",
                f"- Finding IDs: `{', '.join(item.get('finding_ids') or []) or 'none'}`",
                f"- Next action: {item.get('action')}",
                "",
            ])
    else:
        lines.extend(["- No standard mapping was generated.", ""])
    lines.extend([
        "## Security Tickets",
        "",
        "- These tickets are safe remediation or owner-verification tasks designed to be handed to a developer or another AI.",
        "",
    ])
    if security_tickets:
        for item in security_tickets:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- Ticket ID: `{item.get('id')}`",
                f"- Type: `{item.get('type')}`",
                f"- Priority: `{item.get('priority')}`",
                f"- Effort: `{item.get('effort')}`",
                f"- Owner mode required: `{bool(item.get('owner_mode_required'))}`",
                f"- Summary: {item.get('summary')}",
                f"- Implementation prompt: {item.get('implementation_prompt') or item.get('implementation')}",
                f"- Acceptance criteria: {item.get('acceptance_criteria')}",
                f"- Related findings: `{', '.join(item.get('related_finding_ids') or []) or 'none'}`",
                f"- Standards: `{', '.join(item.get('standards') or []) or 'none'}`",
                "",
            ])
            steps = item.get("validation_steps") or []
            if steps:
                lines.append("Validation steps:")
                for step in steps[:6]:
                    lines.append(f"- {step}")
                lines.append("")
    else:
        lines.extend(["- No security ticket was generated.", ""])
    lines.extend([
        "## Attack Surface Matrix",
        "",
    ])
    if surface_matrix:
        for item in surface_matrix:
            lines.extend([
                f"### {item.get('label') or item.get('id')}",
                "",
                f"- Status: `{item.get('status')}`",
                f"- Next action: {item.get('next_action')}",
            ])
            for signal in item.get("signals") or []:
                lines.append(f"- {signal}")
            lines.append("")
    else:
        lines.extend(["- No surface matrix was generated.", ""])
    lines.extend([
        "## Owner Verification Plan",
        "",
        "- These are controlled follow-up checks for the site owner. They are not exploit payloads and should run only with authorization.",
        "",
    ])
    if owner_plan:
        for item in owner_plan:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- Priority: `{item.get('priority')}`",
                f"- Category: `{item.get('category')}`",
                f"- Owner mode required: `{bool(item.get('owner_mode_required'))}`",
                f"- Why: {item.get('why')}",
                f"- Validation: {item.get('validation')}",
                "",
                "Safe steps:",
            ])
            for step in item.get("safe_steps") or []:
                lines.append(f"- {step}")
            lines.append("")
    else:
        lines.extend(["- No owner verification plan was generated.", ""])
    lines.extend(["## Likely Risk Paths", ""])
    if attack_paths:
        for item in attack_paths:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- Severity: `{item.get('severity')}`",
                "- Chain:",
            ])
            for link in item.get("chain") or []:
                lines.append(f"- {link}")
            lines.append("- Breakpoints:")
            for breakpoint in item.get("breakpoints") or []:
                lines.append(f"- {breakpoint}")
            lines.append("")
    else:
        lines.extend(["- No chained risk path was generated from the sampled evidence.", ""])
    lines.extend(["## Evidence Graph", ""])
    graph_nodes = evidence_graph.get("nodes") or []
    graph_edges = evidence_graph.get("edges") or []
    if graph_nodes or graph_edges:
        if evidence_graph.get("note"):
            lines.extend([f"- Note: {evidence_graph.get('note')}", ""])
        lines.append("Nodes:")
        for node in graph_nodes[:24]:
            lines.append(
                f"- `{node.get('id')}` - {node.get('label')} ({node.get('kind') or 'node'}, weight `{node.get('weight', 0)}`)"
            )
        lines.append("")
        lines.append("Edges:")
        for edge in graph_edges[:32]:
            lines.append(f"- `{edge.get('from')}` -> `{edge.get('to')}`: {edge.get('label')}")
        lines.append("")
    else:
        lines.extend(["- No evidence graph was generated.", ""])
    lines.extend([
        "## Audit Coverage",
        "",
        f"- Coverage confidence: `{coverage.get('confidence_score', 'n/a')}`",
        f"- Confirmed findings: `{coverage.get('confirmed_findings', 0)}`",
        f"- Strong-signal findings: `{coverage.get('strong_signal_findings', 0)}`",
        f"- Estimated findings: `{coverage.get('estimated_findings', 0)}`",
        f"- Public-mode limit: {coverage.get('public_mode_limit') or 'n/a'}",
        "",
    ])
    for item in coverage.get("checks") or []:
        lines.extend([
            f"### {item.get('label') or item.get('id')}",
            "",
            f"- Status: `{item.get('status')}`",
            f"- Evidence count: `{item.get('evidence_count')}`",
            f"- Limit: {item.get('limit')}",
            "",
        ])
    lines.extend([
        "## Previous Audit Comparison",
        "",
        f"- Status: `{comparison.get('status') or 'baseline'}`",
        f"- Previous audit: `{comparison.get('previous_audit_id') or 'none'}`",
        f"- Score delta: `{comparison.get('score_delta', 0)}`",
        f"- Critical delta: `{comparison.get('critical_delta', 0)}`",
        f"- High delta: `{comparison.get('high_delta', 0)}`",
        f"- Public sensitive endpoint delta: `{comparison.get('public_sensitive_delta', 0)}`",
        f"- Source map delta: `{comparison.get('source_map_delta', 0)}`",
        "",
    ])
    if comparison.get("new_finding_ids") or comparison.get("fixed_finding_ids"):
        lines.extend([
            f"- New finding IDs: `{', '.join(comparison.get('new_finding_ids') or []) or 'none'}`",
            f"- Fixed finding IDs: `{', '.join(comparison.get('fixed_finding_ids') or []) or 'none'}`",
            "",
        ])
    lines.extend([
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
    ])
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
            reasons = ", ".join(endpoint.get("risk_reasons") or []) or "none"
            lines.append(
                f"- `{endpoint.get('path')}` - HTTP `{endpoint.get('status_code')}`, {auth}, "
                f"type `{endpoint.get('response_type')}`, category `{endpoint.get('category') or 'unknown'}`, methods `{methods}`, risk hints `{reasons}`"
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
    if recommendations:
        lines.extend(["## Recommendation Backlog", ""])
        for item in recommendations:
            lines.extend([
                f"### {item.get('title')}",
                "",
                f"- Priority: `{item.get('priority')}`",
                f"- Triggered: `{bool(item.get('triggered'))}`",
                f"- Action: {item.get('action')}",
                f"- Validation: {item.get('validation')}",
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
    snapshot = audit.get("snapshot") or {}
    findings = audit.get("findings") or []
    standard_map = audit.get("standard_map") or snapshot.get("standard_map") or []
    security_tickets = audit.get("security_tickets") or snapshot.get("security_tickets") or []
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
    if int(summary.get("dangerous_method_count") or 0) > 0:
        warnings.append(f"{summary.get('dangerous_method_count')} public endpoint(s) advertise write-capable HTTP methods.")
    attention_standards = [item for item in standard_map if item.get("status") == "attention"]
    if len(attention_standards) >= 4:
        warnings.append(f"{len(attention_standards)} OWASP/ASVS control area(s) need remediation attention.")
    return {
        "schema": "joyboy.cyberatlas.security_gate.v1",
        "audit_id": audit.get("id") or "",
        "target": summary.get("target") or (audit.get("target") or {}).get("normalized_url") or "",
        "status": "failed" if failures else "passed",
        "passed": not failures,
        "score": summary.get("global_score"),
        "security_grade": summary.get("security_grade"),
        "risk_level": summary.get("risk_level"),
        "critical_count": summary.get("critical_count", 0),
        "high_count": summary.get("high_count", 0),
        "public_sensitive_endpoint_count": summary.get("public_sensitive_endpoint_count", 0),
        "source_map_count": summary.get("source_map_count", 0),
        "coverage_confidence": summary.get("coverage_confidence", 0),
        "owner_verification_count": summary.get("owner_verification_count", 0),
        "attack_path_count": summary.get("attack_path_count", 0),
        "standard_attention_count": summary.get("standard_attention_count", len(attention_standards)),
        "security_ticket_count": summary.get("security_ticket_count", len(security_tickets)),
        "dangerous_method_count": summary.get("dangerous_method_count", 0),
        "failures": failures,
        "warnings": warnings,
        "action_plan": audit.get("action_plan") or [],
        "owner_verification_plan": audit.get("owner_verification_plan") or (audit.get("snapshot") or {}).get("owner_verification_plan") or [],
        "standard_map": standard_map,
        "security_tickets": security_tickets,
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
        "surface_matrix": snapshot.get("surface_matrix") or [],
        "coverage": audit.get("coverage") or snapshot.get("coverage") or {},
        "owner_verification_plan": audit.get("owner_verification_plan") or snapshot.get("owner_verification_plan") or [],
        "attack_paths": audit.get("attack_paths") or snapshot.get("attack_paths") or [],
        "standard_map": audit.get("standard_map") or snapshot.get("standard_map") or [],
        "security_tickets": audit.get("security_tickets") or snapshot.get("security_tickets") or [],
        "evidence_graph": audit.get("evidence_graph") or snapshot.get("evidence_graph") or {},
        "comparison": audit.get("comparison") or {},
        "findings": audit.get("findings") or [],
        "remediation_items": audit.get("remediation_items") or [],
        "recommendations": audit.get("recommendations") or [],
        "action_plan": audit.get("action_plan") or [],
    }


def build_report_html(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    snapshot = audit.get("snapshot") or {}
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
    plan_rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('order') or ''))}</td>"
        f"<td>{html_escape(str(item.get('priority') or ''))}</td>"
        f"<td>{html_escape(str(item.get('title') or ''))}</td>"
        f"<td>{html_escape(str(item.get('action') or ''))}</td>"
        "</tr>"
        for item in (audit.get("action_plan") or [])
    )
    owner_rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('priority') or ''))}</td>"
        f"<td>{html_escape(str(item.get('category') or ''))}</td>"
        f"<td>{html_escape(str(item.get('title') or ''))}</td>"
        f"<td>{html_escape(str(item.get('validation') or ''))}</td>"
        "</tr>"
        for item in (audit.get("owner_verification_plan") or (audit.get("snapshot") or {}).get("owner_verification_plan") or [])
    )
    standard_rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('framework') or ''))} {html_escape(str(item.get('id') or ''))}</td>"
        f"<td>{html_escape(str(item.get('label') or ''))}</td>"
        f"<td>{html_escape(str(item.get('status') or ''))}</td>"
        f"<td>{html_escape(str(item.get('severity') or ''))}</td>"
        f"<td>{html_escape(str(item.get('action') or ''))}</td>"
        "</tr>"
        for item in (audit.get("standard_map") or snapshot.get("standard_map") or [])
        if item.get("status") != "clear"
    )
    ticket_rows = "".join(
        "<tr>"
        f"<td>{html_escape(str(item.get('priority') or ''))}</td>"
        f"<td>{html_escape(str(item.get('type') or ''))}</td>"
        f"<td>{html_escape(str(item.get('title') or ''))}</td>"
        f"<td>{html_escape(str(item.get('implementation_prompt') or item.get('implementation') or ''))}</td>"
        f"<td>{html_escape(str(item.get('acceptance_criteria') or ''))}</td>"
        "</tr>"
        for item in (audit.get("security_tickets") or snapshot.get("security_tickets") or [])
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
  <p><strong>Grade:</strong> {html_escape(str(summary.get('security_grade') or 'n/a'))}</p>
  <p><strong>Coverage confidence:</strong> {html_escape(str(summary.get('coverage_confidence') or 'n/a'))}</p>
  <p><strong>Severity mix:</strong> {counts['critical']} critical · {counts['high']} high · {counts['medium']} medium · {counts['low']} low</p>
  <div class="scores">{score_cards}</div>
  <h2>Action plan</h2>
  <table>
    <thead><tr><th>#</th><th>Priority</th><th>Action</th><th>Fix</th></tr></thead>
    <tbody>{plan_rows}</tbody>
  </table>
  <h2>Owner verification plan</h2>
  <table>
    <thead><tr><th>Priority</th><th>Category</th><th>Check</th><th>Validation</th></tr></thead>
    <tbody>{owner_rows}</tbody>
  </table>
  <h2>Standards map</h2>
  <table>
    <thead><tr><th>Control</th><th>Label</th><th>Status</th><th>Severity</th><th>Next action</th></tr></thead>
    <tbody>{standard_rows}</tbody>
  </table>
  <h2>Security tickets</h2>
  <table>
    <thead><tr><th>Priority</th><th>Type</th><th>Ticket</th><th>Implementation</th><th>Acceptance</th></tr></thead>
    <tbody>{ticket_rows}</tbody>
  </table>
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
    if fmt in {"tickets", "security-tickets"}:
        snapshot = audit.get("snapshot") or {}
        return {
            "content": json.dumps(audit.get("security_tickets") or snapshot.get("security_tickets") or [], ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "Security tickets",
        }
    if fmt in {"standards", "standard-map"}:
        snapshot = audit.get("snapshot") or {}
        return {
            "content": json.dumps(audit.get("standard_map") or snapshot.get("standard_map") or [], ensure_ascii=False, indent=2),
            "mimetype": "application/json",
            "extension": "json",
            "label": "Standards map",
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
