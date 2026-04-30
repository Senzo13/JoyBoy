"""Storage for CodeAtlas audits."""

from __future__ import annotations

from functools import lru_cache

from core.audit_modules.storage import AuditModuleStorage


class CodeAtlasStorage(AuditModuleStorage):
    def __init__(self) -> None:
        super().__init__("codeatlas")


@lru_cache(maxsize=1)
def get_codeatlas_storage() -> CodeAtlasStorage:
    return CodeAtlasStorage()
