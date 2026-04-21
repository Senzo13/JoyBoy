"""Shared data types for terminal agent modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class FileSnapshot:
    path: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ToolResult:
    success: bool
    tool_name: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
