"""Module catalog for native JoyBoy workspaces."""

from __future__ import annotations

from typing import List

from .schemas import ModuleDescriptor


def get_module_catalog() -> List[dict]:
    modules = [
        ModuleDescriptor(
            id="signalatlas",
            name="SignalAtlas",
            tagline="Deterministic SEO and web visibility intelligence",
            description=(
                "Technical crawl, indexability checks, architecture analysis, "
                "AI interpretation, and export-ready remediation packs."
            ),
            icon="radar",
            status="active",
            entry_view="signalatlas-view",
            capabilities=[
                "technical_audit",
                "crawlability",
                "indexability",
                "visibility",
                "ai_remediation",
                "exports",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="signalatlas",
            category="audit",
        ),
        ModuleDescriptor(
            id="perfatlas",
            name="PerfAtlas",
            tagline="Performance intelligence and remediation for production websites",
            description=(
                "Field data, lab probes, delivery diagnostics, owner-aware connectors, "
                "AI remediation packs, and export-ready performance reports."
            ),
            icon="zap",
            status="active",
            entry_view="perfatlas-view",
            capabilities=[
                "core_web_vitals",
                "lab_performance",
                "delivery_diagnostics",
                "owner_context",
                "ai_remediation",
                "exports",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="perfatlas",
            category="audit",
        ),
        ModuleDescriptor(
            id="cyberatlas",
            name="CyberAtlas",
            tagline="Defensive web and API security posture intelligence",
            description=(
                "TLS, security headers, exposure probes, OpenAPI surface mapping, "
                "session hygiene, evidence packs, and AI remediation reports."
            ),
            icon="shield-check",
            status="active",
            entry_view="cyberatlas-view",
            capabilities=[
                "tls_security",
                "security_headers",
                "exposure_mapping",
                "api_surface",
                "ai_remediation",
                "exports",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="cyberatlas",
            category="audit",
        ),
        ModuleDescriptor(
            id="deployatlas",
            name="DeployAtlas",
            tagline="AI-assisted VPS deployment with SSH, HTTPS and rollback",
            description=(
                "Project analysis, saved server profiles, SSH evidence, guided remote "
                "deployment plans, live terminal progress, HTTPS runbooks, and rollback snapshots."
            ),
            icon="server-cog",
            status="active",
            entry_view="deployatlas-view",
            capabilities=[
                "vps_inventory",
                "ssh_fingerprint",
                "project_analysis",
                "deployment_plan",
                "https_ssl",
                "rollback",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="deployatlas",
            category="deployment",
        ),
        ModuleDescriptor(
            id="codeatlas",
            name="CodeAtlas",
            tagline="Local code quality, architecture and regression audits",
            description=(
                "Backend/frontend scoring, duplicate-code detection, validation commands, "
                "and before/after remediation plans for local projects."
            ),
            icon="scan-search",
            status="active",
            entry_view="codeatlas-view",
            capabilities=[
                "code_audit",
                "backend_score",
                "frontend_score",
                "architecture",
                "regression_risk",
                "remediation_plan",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="codeatlas",
            category="developer",
        ),
        ModuleDescriptor(
            id="agentguide",
            name="AgentGuide",
            tagline="Generate AGENTS.md and CLAUDE.md for better AI coding",
            description=(
                "Scans a project, scores agent readiness, and proposes concise, "
                "repo-specific AGENTS.md and CLAUDE.md files with anti-regression rules."
            ),
            icon="bot",
            status="active",
            entry_view="agentguide-view",
            capabilities=[
                "agents_md",
                "claude_md",
                "multi_agent_rules",
                "regression_safety",
                "diff_preview",
            ],
            premium=True,
            available=True,
            featured=True,
            theme="agentguide",
            category="developer",
        ),
    ]
    return [module.to_dict() for module in modules]
