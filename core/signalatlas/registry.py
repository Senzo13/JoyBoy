"""Module registry for native JoyBoy workspaces."""

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
        ),
    ]
    return [module.to_dict() for module in modules]
