"""Shared model context for native audit modules."""

from __future__ import annotations

from typing import Any, Dict

from core.agent_runtime import get_llm_provider_catalog, get_terminal_model_profiles


def get_audit_model_context() -> Dict[str, Any]:
    return {
        "llm_providers": get_llm_provider_catalog(),
        "terminal_model_profiles": get_terminal_model_profiles(configured_only=False, discover_remote=False),
        "presets": [
            {
                "id": "fast",
                "label": "Fast",
                "summary": "Shortest turnaround, compact interpretation.",
                "time_profile": "fast",
                "privacy_profile": "depends_on_model",
            },
            {
                "id": "balanced",
                "label": "Balanced",
                "summary": "Default JoyBoy balance between speed and depth.",
                "time_profile": "balanced",
                "privacy_profile": "depends_on_model",
            },
            {
                "id": "expert",
                "label": "Expert",
                "summary": "Longer, deeper interpretation with stronger prioritization.",
                "time_profile": "slower",
                "privacy_profile": "depends_on_model",
            },
            {
                "id": "local_private",
                "label": "Local Private",
                "summary": "Prefer privacy-preserving local models with terse output.",
                "time_profile": "local",
                "privacy_profile": "local_first",
            },
        ],
        "levels": [
            {"id": "no_ai", "label": "No AI interpretation"},
            {"id": "basic_summary", "label": "Basic summary"},
            {"id": "full_expert_analysis", "label": "Full expert analysis"},
            {"id": "ai_remediation_pack", "label": "AI remediation pack"},
        ],
    }
