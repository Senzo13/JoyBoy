"""Agent runtime guardrails that are independent from Flask/UI code."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional


TOOL_FREQUENCY_LIMITS = {
    "list_files": 4,
    "glob": 4,
    "search": 6,
    "bash": 5,
    "read_file": 10,
}
DEFAULT_TOOL_FREQUENCY_LIMIT = 12


def _normalized_tool_args(raw_args: Any) -> tuple[Dict[str, Any], str | None]:
    if isinstance(raw_args, dict):
        return dict(raw_args), None
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, raw_args.strip()
        if isinstance(parsed, dict):
            return dict(parsed), None
        return {}, json.dumps(parsed, sort_keys=True, ensure_ascii=False, default=str)
    if raw_args is None:
        return {}, None
    return {}, json.dumps(raw_args, sort_keys=True, ensure_ascii=False, default=str)


def _clean_path(value: Any, default: str = "") -> str:
    path = str(value if value not in (None, "") else default).strip().replace("\\", "/")
    path = re.sub(r"/+", "/", path)
    if path.startswith("./"):
        path = path[2:]
    return path or default


def _clean_command(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _canonical_tool_args(tool_name: str, args: Dict[str, Any], fallback_key: str | None) -> Any:
    if tool_name == "read_file":
        path = _clean_path(args.get("path"))
        if not path:
            return fallback_key or {}
        return {"path": path}

    if tool_name == "list_files":
        return {"path": _clean_path(args.get("path"), ".") or "."}

    if tool_name == "glob":
        return {
            "path": _clean_path(args.get("path"), ".") or ".",
            "pattern": str(args.get("pattern") or args.get("glob") or "").strip(),
        }

    if tool_name == "search":
        return {
            "path": _clean_path(args.get("path"), ".") or ".",
            "pattern": str(args.get("pattern") or args.get("query") or "").strip(),
        }

    if tool_name == "bash":
        return {"command": _clean_command(args.get("command") or args.get("cmd"))}

    if tool_name in {"write_file", "write_files", "edit_file", "delete_file", "str_replace"}:
        return fallback_key if fallback_key is not None else args

    salient_fields = (
        "path", "url", "query", "command", "pattern", "glob", "cmd",
        "skill_id", "agent_type", "task", "name",
    )
    stable_args = {
        field: (_clean_command(args[field]) if field in {"command", "cmd"} else args[field])
        for field in salient_fields
        if args.get(field) not in (None, "")
    }
    if stable_args:
        return stable_args
    return fallback_key if fallback_key is not None else args


def tool_signature(tool_name: str, args: Dict[str, Any]) -> str:
    """Return a stable signature for repeated tool-call detection.

    The signature intentionally ignores noisy defaults for read/exploration
    tools while keeping write/edit payloads content-sensitive.
    """
    normalized_args, fallback_key = _normalized_tool_args(args)
    canonical_args = _canonical_tool_args(tool_name, normalized_args, fallback_key)
    try:
        clean_args = json.dumps(canonical_args or {}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        clean_args = str(canonical_args)
    return f"{tool_name}:{clean_args}"


def tool_guard_reason(
    tool_name: str,
    args: Dict[str, Any],
    seen_count: int,
    executed_tools: List[Dict[str, Any]],
    tool_frequency: int | None = None,
) -> Optional[str]:
    """Return a reason when a tool call is likely to waste turns.

    This mirrors the DeerFlow-style loop guard idea but keeps JoyBoy's current
    tool vocabulary and local-first constraints.
    """
    if seen_count >= 3:
        return f"repeated call {seen_count} times: {tool_name}({args})"

    path = str((args or {}).get("path", "")).strip()
    pattern = str((args or {}).get("pattern", "")).strip()
    command = str((args or {}).get("command", "")).strip().lower()

    if tool_name == "read_file" and path in {"", ".", "./"}:
        return "read_file must target a file, not the workspace root"

    if tool_name == "list_files" and path in {"", ".", "./"} and seen_count >= 2:
        return "root listing already ran; read specific files or conclude"

    noisy_roots = {"**/*", "*", ".", "./"}
    if tool_name == "glob" and pattern in noisy_roots and len(executed_tools) >= 2:
        return "broad glob already gave enough context; read specific files or conclude"

    if tool_name == "search" and pattern in {"", ".", ".*"}:
        return "search pattern is too broad to produce useful signal"

    repeated_shell = {"ls", "ls -la", "dir", "pwd", "find . -type f"}
    if tool_name == "bash" and command in repeated_shell and len(executed_tools) >= 2:
        return f"exploratory shell command already used: {command}"

    recent_names = [item.get("tool") for item in executed_tools[-4:]]
    if len(recent_names) == 4 and len(set(recent_names)) <= 2 and tool_name in {"list_files", "glob", "bash"}:
        return "repeated exploration without reading useful files"

    if tool_frequency is not None:
        frequency_limit = TOOL_FREQUENCY_LIMITS.get(tool_name, DEFAULT_TOOL_FREQUENCY_LIMIT)
        if tool_frequency >= frequency_limit:
            return (
                f"{tool_name} called {tool_frequency} times this turn; "
                "stop looping and use the collected context"
            )

    return None


class ToolLoopGuard:
    """Stateful repeated-tool guard for one agent turn."""

    def __init__(self) -> None:
        self._seen = defaultdict(int)
        self._tool_frequency = defaultdict(int)

    def check(self, tool_name: str, args: Dict[str, Any], executed_tools: List[Dict[str, Any]]) -> Optional[str]:
        signature = tool_signature(tool_name, args)
        self._seen[signature] += 1
        self._tool_frequency[tool_name] += 1
        return tool_guard_reason(
            tool_name,
            args,
            self._seen[signature],
            executed_tools,
            tool_frequency=self._tool_frequency[tool_name],
        )

    def seen_count(self, tool_name: str, args: Dict[str, Any]) -> int:
        return self._seen.get(tool_signature(tool_name, args), 0)

    def tool_frequency(self, tool_name: str) -> int:
        return self._tool_frequency.get(tool_name, 0)
