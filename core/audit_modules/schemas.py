"""Shared schemas for native audit modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


def _clean_mapping(values: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        cleaned[key] = value
    return cleaned


@dataclass
class ModuleDescriptor:
    id: str
    name: str
    tagline: str
    description: str
    icon: str
    status: str
    entry_view: str
    capabilities: List[str] = field(default_factory=list)
    premium: bool = False
    available: bool = True
    locked_reason: str = ""
    featured: bool = False
    theme: str = "default"
    category: str = "audit"

    def to_dict(self) -> Dict[str, Any]:
        return _clean_mapping(asdict(self))
