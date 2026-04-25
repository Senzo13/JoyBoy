"""Shared data types for terminal agent modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class FileSnapshot:
    path: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FileReadRange:
    start_line: int
    end_line: int
    full_read: bool = False

    def covers(self, start_line: int, end_line: int) -> bool:
        return self.start_line <= start_line and self.end_line >= end_line


@dataclass
class FileReadState:
    mtime_ns: int
    size: int
    sha256: str
    total_lines: int
    ranges: List[FileReadRange] = field(default_factory=list)

    @property
    def has_full_read(self) -> bool:
        return any(item.full_read for item in self.ranges)

    def covers(self, start_line: int, end_line: int) -> bool:
        if self.has_full_read:
            return True
        return any(item.covers(start_line, end_line) for item in self.ranges)

    def add_range(self, read_range: FileReadRange) -> None:
        self.ranges.append(read_range)


@dataclass
class ToolResult:
    success: bool
    tool_name: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
