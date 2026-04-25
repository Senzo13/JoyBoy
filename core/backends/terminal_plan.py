"""Planning and short-term execution state for the terminal agent."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


EXECUTION_JOURNAL_HEADER = "[EXECUTION JOURNAL]"


class PlanStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class PlanTask:
    id: str
    title: str
    description: str = ""
    status: PlanStatus = PlanStatus.PENDING
    result: Optional[str] = None


@dataclass
class ExecutionPlan:
    title: str
    goal: str
    tasks: List[PlanTask] = field(default_factory=list)
    current_task_index: int = 0

    def get_current_task(self) -> Optional[PlanTask]:
        if 0 <= self.current_task_index < len(self.tasks):
            return self.tasks[self.current_task_index]
        return None

    def mark_current_done(self, result: str = "") -> bool:
        task = self.get_current_task()
        if task:
            task.status = PlanStatus.COMPLETED
            task.result = result
            self.current_task_index += 1
            return True
        return False

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"**Objectif:** {self.goal}", ""]
        for i, task in enumerate(self.tasks):
            icon = "✅" if task.status == PlanStatus.COMPLETED else "⏳" if task.status == PlanStatus.IN_PROGRESS else "⬜"
            current = " 👈" if i == self.current_task_index else ""
            lines.append(f"{icon} {task.id}. {task.title}{current}")
        return "\n".join(lines)


class TerminalPlanMixin:
    """Todo planning, progress reminders, and short-lived execution journal."""

    def _should_use_todos_for_request(self, message: str) -> bool:
        """Keep TodoMiddleware-style planning for real multi-step work only."""
        if self._is_scaffold_write_request(message):
            return False
        return self._is_complex_task_request(message)

    def _write_todos(self, todos: Any) -> Dict:
        if not isinstance(todos, list):
            return {"success": False, "error": "todos must be a list"}
        if not todos:
            self.current_plan = None
            return {"success": True, "todos": [], "summary": "Todo list cleared"}

        normalized, error = self._normalize_todos_payload(todos)
        if error:
            return {"success": False, "error": error}

        if self.current_plan and self._plan_signature(normalized) == self._plan_signature(self.current_plan.tasks):
            return {
                "success": False,
                "error": (
                    "todo list unchanged. Continue the active step and call write_todos again "
                    "only when statuses or notes actually change."
                ),
                "todos": [self._task_to_dict(task) for task in self.current_plan.tasks],
                "incomplete": self._has_incomplete_todos(),
            }

        current_index = 0
        for index, task in enumerate(normalized):
            if task.status in {PlanStatus.PENDING, PlanStatus.IN_PROGRESS, PlanStatus.BLOCKED}:
                current_index = index
                break
        else:
            current_index = len(normalized)

        self.current_plan = ExecutionPlan(
            title="Terminal task list",
            goal="Complete the user's request",
            tasks=normalized,
            current_task_index=current_index,
        )
        counts = {status.value: 0 for status in PlanStatus}
        for task in normalized:
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return {
            "success": True,
            "todos": [self._task_to_dict(task) for task in normalized],
            "counts": counts,
            "incomplete": self._has_incomplete_todos(),
        }

    def _normalize_todos_payload(self, todos: Any) -> tuple[List[PlanTask], Optional[str]]:
        if not isinstance(todos, list):
            return [], "todos must be a list"

        normalized: List[PlanTask] = []
        valid_statuses = {item.value for item in PlanStatus}
        for index, item in enumerate(todos[:8], start=1):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or item.get("title") or "").strip()
            if not content:
                continue
            raw_status = str(item.get("status") or "pending").strip().lower()
            if raw_status not in valid_statuses:
                raw_status = "pending"
            task_id = str(item.get("id") or index).strip() or str(index)
            note = str(item.get("note") or item.get("result") or "").strip()
            normalized.append(
                PlanTask(
                    id=task_id[:48],
                    title=content[:240],
                    status=PlanStatus(raw_status),
                    result=note[:280] if note else None,
                )
            )

        if not normalized:
            return [], "todos must include at least one item with content"
        return normalized, None

    @staticmethod
    def _plan_signature(tasks: List[PlanTask]) -> List[tuple[str, str, str, str]]:
        return [
            (
                str(task.id or ""),
                str(task.title or ""),
                str(task.status.value if isinstance(task.status, PlanStatus) else task.status or ""),
                str(task.result or ""),
            )
            for task in tasks or []
        ]

    @staticmethod
    def _task_to_dict(task: PlanTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "content": task.title,
            "status": task.status.value,
            "note": task.result or "",
        }

    def _has_incomplete_todos(self) -> bool:
        if not self.current_plan or not self.current_plan.tasks:
            return False
        return any(task.status != PlanStatus.COMPLETED for task in self.current_plan.tasks)

    def _format_active_todos(self) -> str:
        if not self.current_plan or not self.current_plan.tasks:
            return ""
        lines = []
        for task in self.current_plan.tasks:
            suffix = f" - {task.result}" if task.result else ""
            lines.append(f"- [{task.status.value}] {task.title}{suffix}")
        return "\n".join(lines)

    def _format_current_task_focus(self) -> str:
        if not self.current_plan:
            return ""
        task = self.current_plan.get_current_task()
        if not task:
            return ""
        suffix = f" - {task.result}" if task.result else ""
        return f"- [{task.status.value}] {task.title}{suffix}"

    def _format_recent_execution_progress(self, executed_tools: Optional[List[Dict[str, Any]]], limit: int = 4) -> str:
        if not executed_tools:
            return ""

        ignored = {"write_todos", "think", "tool_search"}
        lines: List[str] = []
        seen: set[str] = set()
        for item in reversed(executed_tools):
            tool_name = str(item.get("tool") or "").strip()
            if not tool_name or tool_name in ignored:
                continue
            summary = self._compact_summary_snippet(item.get("summary", ""), limit=140)
            if not summary:
                continue
            success = item.get("success", True)
            line = f"- {tool_name}: {summary}" if success else f"- {tool_name} failed: {summary}"
            normalized = unicodedata.normalize("NFKD", line).encode("ascii", "ignore").decode("ascii").lower()
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(line)
            if len(lines) >= limit:
                break
        return "\n".join(lines)

    def _record_execution_journal(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        executed_summary: Dict[str, Any],
    ) -> None:
        ignored = {"write_todos", "think", "tool_search", "remember_fact", "list_memory"}
        if tool_name in ignored:
            return

        line = self._execution_journal_line(tool_name, args or {}, result, executed_summary or {})
        if not line:
            return

        entry = {
            "tool": tool_name,
            "success": bool(result.success),
            "line": line,
            "signature": self._execution_journal_signature(tool_name, args or {}, line),
        }

        self._active_execution_journal = [
            item
            for item in self._active_execution_journal
            if item.get("signature") != entry["signature"]
        ]
        self._active_execution_journal.append(entry)
        self._active_execution_journal = self._active_execution_journal[-8:]

    def _execution_journal_line(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        executed_summary: Dict[str, Any],
    ) -> str:
        data = result.data or {}
        if result.error:
            detail = self._compact_summary_snippet(result.error, limit=180)
            return f"{tool_name} failed: {detail}" if detail else ""

        if tool_name == "list_files":
            path = str(args.get("path") or ".")
            return f"listed {path}: {len(data.get('items', []))} item(s)"
        if tool_name == "read_file":
            path = data.get("path") or args.get("path") or ""
            start_line = data.get("start_line")
            end_line = data.get("end_line")
            total_lines = data.get("lines", 0)
            if start_line and end_line and not (int(start_line) == 1 and int(end_line) == int(total_lines or 0)):
                return f"read {path}: lines {start_line}-{end_line} of {total_lines} line(s)"
            return f"read {path}: {total_lines} line(s)"
        if tool_name == "glob":
            return f"glob {args.get('pattern', '')}: {len(data.get('files', []))} file(s)"
        if tool_name == "search":
            location = args.get("path") or "."
            pattern = self._compact_summary_snippet(str(args.get("pattern", "")), limit=80)
            return f"searched {location} for {pattern}: {len(data.get('results', []))} result(s)"
        if tool_name in {"write_file", "edit_file", "delete_file"}:
            path = data.get("path") or args.get("path") or ""
            action = "wrote" if tool_name == "write_file" else "edited" if tool_name == "edit_file" else "deleted"
            return f"{action} {path}".strip()
        if tool_name == "write_files":
            files = data.get("files", []) if isinstance(data, dict) else []
            paths = [item.get("path", "") for item in files[:5] if item.get("path")]
            suffix = ", ".join(paths)
            if len(files) > len(paths):
                suffix += f", +{len(files) - len(paths)} more"
            return f"wrote batch: {suffix}" if suffix else "wrote batch"
        if tool_name == "clear_workspace":
            kept = data.get("kept", []) if isinstance(data, dict) else []
            kept_suffix = f" (kept {', '.join(kept)})" if kept else ""
            return f"cleared workspace: {data.get('count', 0)} top-level item(s) deleted{kept_suffix}"
        if tool_name == "bash":
            command = self._compact_summary_snippet(str(args.get("command", "")), limit=120)
            line = f"bash `{command}` -> code {data.get('return_code', '?')}"
            verification = data.get("verification") if isinstance(data, dict) else None
            if isinstance(verification, dict) and verification.get("path"):
                status = "verified" if verification.get("verified") else "unverified"
                line += f" ({status}: {verification.get('path')})"
            return line
        if tool_name == "delegate_subagent":
            agent_type = data.get("agent_type", "subagent") if isinstance(data, dict) else "subagent"
            status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
            summary = self._compact_summary_snippet(str(data.get("summary", "")) if isinstance(data, dict) else "", limit=140)
            return f"{agent_type} {status}: {summary}".rstrip(": ")
        if tool_name == "web_fetch":
            title = self._compact_summary_snippet(str(data.get("title", "page")), limit=140)
            return f"fetched web page: {title}"
        if tool_name == "load_skill":
            skill = data.get("skill", {}) if isinstance(data, dict) else {}
            return f"loaded skill: {skill.get('id', 'skill')}"
        if tool_name == "open_workspace":
            return f"opened workspace: {data.get('path', '')}"
        if tool_name in self._mcp_tools_by_name:
            return f"ran MCP tool {tool_name} via {data.get('server_name', 'external')}"

        summary = self._compact_summary_snippet(str(executed_summary.get("summary", "")), limit=180)
        return f"{tool_name}: {summary}" if summary else ""

    def _execution_journal_signature(self, tool_name: str, args: Dict[str, Any], line: str) -> str:
        target = (
            args.get("path")
            or args.get("pattern")
            or args.get("command")
            or args.get("query")
            or line
        )
        raw = f"{tool_name}:{target}"
        folded = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"\s+", " ", folded).strip()[:240]

    def _format_execution_journal(self, limit: int = 6) -> str:
        if not self._active_execution_journal:
            return ""

        lines = [
            EXECUTION_JOURNAL_HEADER,
            "Short-lived state from this terminal run. Use it to avoid repeating tools after context compaction.",
        ]
        for item in self._active_execution_journal[-limit:]:
            prefix = "OK" if item.get("success") else "FAIL"
            line = self._compact_summary_snippet(str(item.get("line", "")), limit=220)
            if line:
                lines.append(f"- [{prefix}] {line}")
        if len(lines) <= 2:
            return ""
        return "\n".join(lines)

    def _inject_execution_journal(self, messages: List[Dict]) -> List[Dict]:
        if not messages or not self._active_execution_journal:
            return messages
        if self.current_intent not in {"write", "execute"} and not self.current_plan:
            return messages

        journal = self._format_execution_journal()
        if not journal:
            return messages

        cleaned = [
            msg for msg in messages
            if not str(msg.get("content", "") or "").startswith(EXECUTION_JOURNAL_HEADER)
        ]
        if not cleaned:
            return messages
        reminder = {"role": "user", "content": journal}
        return [cleaned[0], reminder] + cleaned[1:]

    def _message_has_visible_todos(self, messages: List[Dict]) -> bool:
        for msg in messages:
            if msg.get("tool_name") == "write_todos":
                return True
            content = str(msg.get("content", "") or "")
            if "[ACTIVE TODO LIST]" in content:
                return True
            for call in msg.get("tool_calls", []) or []:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                if function.get("name") == "write_todos":
                    return True
        return False

    def _message_has_step_focus(self, messages: List[Dict]) -> bool:
        for msg in messages:
            content = str(msg.get("content", "") or "")
            if "[ACTIVE EXECUTION STEP]" in content:
                return True
        return False

    def _step_focus_tool_hint(self, initial_message: str) -> str:
        mode = self._active_step_mode(initial_message)
        if mode == "verify":
            return "Use bash or delegate_subagent(verifier) for the next concrete verification step, then update files only if the check fails."
        if mode == "analyze":
            return "Use one focused read/search/delegate_subagent step, then move to the concrete change instead of broad repo exploration."
        if mode == "scaffold":
            return "Use write_files or write_file now for the scaffold itself, then verify with read_file/list_files."
        return "Use edit_file, write_files, write_file, or bash now for the concrete change, then verify the result."

    def _inject_todo_reminder(self, messages: List[Dict], executed_tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict]:
        if not self._has_incomplete_todos() or self._message_has_visible_todos(messages):
            return messages
        if not messages:
            return messages
        current_focus = self._format_current_task_focus()
        recent_progress = self._format_recent_execution_progress(executed_tools)
        focus_block = (
            f"\nCurrent execution step:\n{current_focus}\n"
            if current_focus
            else ""
        )
        progress_block = (
            f"\nRecent observed progress:\n{recent_progress}\n"
            if recent_progress
            else ""
        )
        reminder = {
            "role": "user",
            "content": (
                "[ACTIVE TODO LIST]\n"
                "Your earlier write_todos call is no longer visible after context compaction, "
                "but the task list is still active:\n"
                f"{self._format_active_todos()}\n\n"
                f"{focus_block}"
                f"{progress_block}"
                "Continue from this list and call write_todos when statuses change."
            ),
        }
        return [messages[0], reminder] + messages[1:]

    def _inject_step_focus_reminder(
        self,
        messages: List[Dict],
        initial_message: str,
        executed_tools: List[Dict[str, Any]],
    ) -> List[Dict]:
        if not self._should_force_step_focus(initial_message, executed_tools):
            return messages
        if not messages or self._message_has_step_focus(messages):
            return messages

        current_focus = self._format_current_task_focus()
        recent_progress = self._format_recent_execution_progress(executed_tools)
        reminder_lines = [
            "[ACTIVE EXECUTION STEP]",
            "You are in a write task with an active plan, but the recent turns stayed passive.",
        ]
        if current_focus:
            reminder_lines.extend(["Current step:", current_focus])
        if recent_progress:
            reminder_lines.extend(["Recent passive/progress context:", recent_progress])
        reminder_lines.extend([
            "",
            self._step_focus_tool_hint(initial_message),
            "Do not restart broad exploration unless one specific missing file blocks the next action.",
        ])
        reminder = {
            "role": "user",
            "content": "\n".join(reminder_lines),
        }
        return [messages[0], reminder] + messages[1:]
