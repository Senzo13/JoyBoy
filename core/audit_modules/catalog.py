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
    ]
    return [module.to_dict() for module in modules]
