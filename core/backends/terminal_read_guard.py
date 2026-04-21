"""Read-before-write guard for terminal workspace edits."""

from __future__ import annotations

import os
from typing import Optional

from core.backends.terminal_types import ToolResult


class TerminalReadGuardMixin:
    """Track file reads so existing files are not overwritten blindly."""

    def _workspace_key(self, workspace_path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(workspace_path or "")))

    def _canonical_file_key(self, full_path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(full_path)))

    def _track_read_file(self, workspace_path: str, relative_path: str):
        full_path = self._resolve_for_snapshot(workspace_path, relative_path)
        if full_path and os.path.isfile(full_path):
            stat = os.stat(full_path)
            self._read_files_by_workspace[self._workspace_key(workspace_path)][
                self._canonical_file_key(full_path)
            ] = (stat.st_mtime_ns, stat.st_size)

    def _has_read_file(self, workspace_path: str, relative_path: str) -> bool:
        full_path = self._resolve_for_snapshot(workspace_path, relative_path)
        if not full_path:
            return False
        return self._canonical_file_key(full_path) in self._read_files_by_workspace.get(self._workspace_key(workspace_path), {})

    def _read_guard_error(self, workspace_path: str, relative_path: str, full_path: str) -> Optional[str]:
        workspace_reads = self._read_files_by_workspace.get(self._workspace_key(workspace_path), {})
        file_key = self._canonical_file_key(full_path)
        read_marker = workspace_reads.get(file_key)
        if not read_marker:
            return (
                "BLOCKED: existing file was not read first. Call read_file on this file "
                "before editing or replacing it, then retry the edit."
            )

        try:
            stat = os.stat(full_path)
        except OSError as exc:
            return f"BLOCKED: cannot verify the file state before writing: {exc}"

        current_marker = (stat.st_mtime_ns, stat.st_size)
        if current_marker != read_marker:
            return (
                "BLOCKED: the file changed since the last read_file call. Read it again "
                "with read_file before editing or replacing it."
            )
        return None

    def _require_read_before_existing_write(self, workspace_path: str, relative_path: str, full_path: str, tool_name: str) -> Optional[ToolResult]:
        if os.path.exists(full_path):
            error = self._read_guard_error(workspace_path, relative_path, full_path)
            if not error:
                return None
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=error,
            )
        return None
