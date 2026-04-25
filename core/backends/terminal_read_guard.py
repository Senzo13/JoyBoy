"""Read-before-write guard for terminal workspace edits."""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from core.backends.terminal_types import FileReadRange, FileReadState, ToolResult


class TerminalReadGuardMixin:
    """Track file reads so existing files are not overwritten blindly."""

    def _workspace_key(self, workspace_path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(workspace_path or "")))

    def _canonical_file_key(self, full_path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(full_path)))

    def _file_sha256(self, full_path: str) -> str:
        hasher = hashlib.sha256()
        with open(full_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _track_read_file(self, workspace_path: str, relative_path: str, read_result: Optional[dict] = None):
        full_path = self._resolve_for_snapshot(workspace_path, relative_path)
        if full_path and os.path.isfile(full_path):
            stat = os.stat(full_path)
            state = (read_result or {}).get("read_state") or {}
            sha256 = str(state.get("sha256") or self._file_sha256(full_path))
            total_lines = int(state.get("total_lines") or (read_result or {}).get("lines") or 0)
            start_line = int(state.get("start_line") or (read_result or {}).get("start_line") or 1)
            end_line = int(state.get("end_line") or (read_result or {}).get("end_line") or start_line)
            full_read = bool(state.get("full_read") or (read_result or {}).get("full_read"))

            workspace_reads = self._read_files_by_workspace[self._workspace_key(workspace_path)]
            file_key = self._canonical_file_key(full_path)
            existing = workspace_reads.get(file_key)
            read_range = FileReadRange(start_line=start_line, end_line=end_line, full_read=full_read)

            if (
                isinstance(existing, FileReadState)
                and existing.mtime_ns == stat.st_mtime_ns
                and existing.size == stat.st_size
                and existing.sha256 == sha256
            ):
                existing.add_range(read_range)
                return

            workspace_reads[file_key] = FileReadState(
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
                sha256=sha256,
                total_lines=total_lines,
                ranges=[read_range],
            )

    def _has_read_file(self, workspace_path: str, relative_path: str) -> bool:
        full_path = self._resolve_for_snapshot(workspace_path, relative_path)
        if not full_path:
            return False
        return self._canonical_file_key(full_path) in self._read_files_by_workspace.get(self._workspace_key(workspace_path), {})

    def _text_line_span(self, full_path: str, old_text: str) -> Optional[tuple[int, int]]:
        if not old_text:
            return None
        try:
            from core.workspace_tools import _read_text_with_metadata

            content, _ = _read_text_with_metadata(full_path)
        except OSError:
            return None
        except Exception:
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read()
            except OSError:
                return None
        needle = str(old_text).replace("\r\n", "\n").replace("\r", "\n")
        normalised = content.replace("\r\n", "\n").replace("\r", "\n")
        index = normalised.find(needle)
        if index < 0:
            return None
        start_line = normalised.count("\n", 0, index) + 1
        newline_count = needle.count("\n")
        end_line = start_line + newline_count
        if needle.endswith("\n") and newline_count:
            end_line -= 1
        return start_line, max(start_line, end_line)

    def _read_guard_error(
        self,
        workspace_path: str,
        relative_path: str,
        full_path: str,
        tool_name: str,
        old_text: str = "",
    ) -> Optional[str]:
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

        if not isinstance(read_marker, FileReadState):
            previous_marker = read_marker
            current_marker = (stat.st_mtime_ns, stat.st_size)
            if current_marker != previous_marker:
                return (
                    "BLOCKED: the file changed since the last read_file call. Read it again "
                    "with read_file before editing or replacing it."
                )
            return None

        try:
            current_sha256 = self._file_sha256(full_path)
        except OSError as exc:
            return f"BLOCKED: cannot verify the file content before writing: {exc}"

        if (
            stat.st_mtime_ns != read_marker.mtime_ns
            or stat.st_size != read_marker.size
            or current_sha256 != read_marker.sha256
        ):
            return (
                "BLOCKED: the file changed since the last read_file call. Read it again "
                "with read_file before editing or replacing it."
            )

        if tool_name in {"write_file", "write_files"} and not read_marker.has_full_read:
            return (
                "BLOCKED: only part of the existing file was read. Read the full file before "
                "replacing it, or use edit_file for a targeted change inside the lines already read."
            )

        if tool_name == "edit_file" and not read_marker.has_full_read:
            span = self._text_line_span(full_path, old_text)
            if not span:
                return (
                    "BLOCKED: cannot prove the requested edit is inside the lines already read. "
                    "Read the target range again before editing."
                )
            if not read_marker.covers(span[0], span[1]):
                return (
                    f"BLOCKED: edit targets lines {span[0]}-{span[1]}, but those lines were not read. "
                    "Read that range with read_file before editing."
                )
        return None

    def _require_read_before_existing_write(
        self,
        workspace_path: str,
        relative_path: str,
        full_path: str,
        tool_name: str,
        old_text: str = "",
    ) -> Optional[ToolResult]:
        if os.path.exists(full_path):
            error = self._read_guard_error(workspace_path, relative_path, full_path, tool_name, old_text=old_text)
            if not error:
                return None
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=error,
            )
        return None
