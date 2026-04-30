"""Storage for AgentGuide audits and generated files."""

from __future__ import annotations

from functools import lru_cache

from core.audit_modules.storage import AuditModuleStorage


class AgentGuideStorage(AuditModuleStorage):
    def __init__(self) -> None:
        super().__init__("agentguide")


@lru_cache(maxsize=1)
def get_agentguide_storage() -> AgentGuideStorage:
    return AgentGuideStorage()
