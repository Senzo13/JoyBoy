"""
Terminal tool registry and permissions.

This module is the stable contract between the terminal agent and the actual
tool implementations. Keep policy here instead of scattering safety checks in
the agent loop, routes, or frontend cards.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from core.agent_runtime.output import truncate_middle


class ToolRisk:
    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    SHELL = "shell"
    NETWORK = "network"
    REASONING = "reasoning"


DEFAULT_PERMISSION_MODE = "default"
FULL_ACCESS_PERMISSION_MODE = "full_access"
TERMINAL_PERMISSION_MODES = {DEFAULT_PERMISSION_MODE, FULL_ACCESS_PERMISSION_MODE}
ALLOWED_SHELL_COMMANDS = {
    "npm", "node", "npx", "yarn", "pnpm",
    "python", "python3", "pip", "pip3",
    "git", "gh",
    "ls", "pwd", "cat", "head", "tail", "wc",
    "grep", "find", "which", "echo", "date",
    "rg", "fd", "findstr", "where", "dir", "type",
    "get-childitem", "select-string", "get-content", "measure-object", "select-object", "where-object",
    "foreach-object", "sort-object", "format-table", "format-list", "out-string",
    "get-command", "resolve-path", "test-path",
    "gci", "gc", "sls", "select", "foreach", "sort", "measure",
    "mkdir", "touch", "cp", "mv", "rm", "rmdir", "rd",
    "cargo", "go", "make",
    "pytest", "jest", "vitest",
    "eslint", "prettier", "tsc",
}


def normalize_permission_mode(mode: str | None) -> str:
    normalized = str(mode or DEFAULT_PERMISSION_MODE).strip().lower().replace("-", "_")
    return normalized if normalized in TERMINAL_PERMISSION_MODES else DEFAULT_PERMISSION_MODE


def is_workspace_clear_shell_command(command: str | None) -> bool:
    """Return True for broad shell commands that mean "empty this workspace"."""
    lowered = " ".join(str(command or "").strip().lower().split())
    if not lowered:
        return False

    if (
        re.search(r"(?:^|\s)find\s+\.(?:\s|$)", lowered)
        and "-mindepth 1" in lowered
        and "-maxdepth 1" in lowered
        and re.search(r"(?:^|\s)-exec\s+rm\b", lowered)
        and re.search(r"\brm\s+-[a-z]*[rf][a-z]*[rf]?[a-z]*\b", lowered)
    ):
        return True

    if (
        "get-childitem" in lowered
        and "| remove-item" in lowered
        and "-recurse" in lowered
    ):
        return True

    return False


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    schema: Dict[str, Any]
    risk: str = ToolRisk.READ_ONLY
    concurrent_safe: bool = True
    enabled: bool = True
    tags: List[str] = field(default_factory=list)

    def to_ollama_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "concurrent_safe": self.concurrent_safe,
            "enabled": self.enabled,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str = ""
    risk: str = ToolRisk.READ_ONLY
    requires_confirmation: bool = False
    mode: str = DEFAULT_PERMISSION_MODE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
            "mode": self.mode,
        }


class ToolRegistry:
    """Registry for core tools, pack tools, and future plugin tools."""

    def __init__(self, tools: Optional[Iterable[ToolDefinition]] = None):
        self._tools: Dict[str, ToolDefinition] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if not tool.name:
            raise ValueError("Tool name is required")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list(self, enabled_only: bool = True) -> List[ToolDefinition]:
        tools = list(self._tools.values())
        if enabled_only:
            tools = [tool for tool in tools if tool.enabled]
        return tools

    def ollama_tools(self, names: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        if names is None:
            return [tool.to_ollama_tool() for tool in self.list(enabled_only=True)]

        selected: List[Dict[str, Any]] = []
        for name in names:
            tool = self.get(name)
            if tool and tool.enabled:
                selected.append(tool.to_ollama_tool())
        return selected

    def public_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_public_dict() for tool in self.list(enabled_only=False)]


_TOOL_RISKS = {
    "list_files": ToolRisk.READ_ONLY,
    "read_file": ToolRisk.READ_ONLY,
    "search": ToolRisk.READ_ONLY,
    "glob": ToolRisk.READ_ONLY,
    "ask_clarification": ToolRisk.READ_ONLY,
    "write_todos": ToolRisk.REASONING,
    "tool_search": ToolRisk.READ_ONLY,
    "write_file": ToolRisk.WRITE,
    "write_files": ToolRisk.WRITE,
    "edit_file": ToolRisk.WRITE,
    "clear_workspace": ToolRisk.DESTRUCTIVE,
    "delete_file": ToolRisk.DESTRUCTIVE,
    "bash": ToolRisk.SHELL,
    "web_search": ToolRisk.NETWORK,
    "web_fetch": ToolRisk.NETWORK,
    "delegate_subagent": ToolRisk.SHELL,
    "load_skill": ToolRisk.READ_ONLY,
    "remember_fact": ToolRisk.WRITE,
    "list_memory": ToolRisk.READ_ONLY,
    "think": ToolRisk.REASONING,
    "open_workspace": ToolRisk.READ_ONLY,
}

_TOOL_CONCURRENCY = {
    "write_file": False,
    "write_files": False,
    "edit_file": False,
    "delete_file": False,
    "bash": False,
}


def build_default_terminal_tool_registry(legacy_tools: Iterable[Dict[str, Any]]) -> ToolRegistry:
    """Convert the current Ollama-style tool list into the registry contract."""
    registry = ToolRegistry()
    for item in legacy_tools:
        fn = item.get("function", {})
        name = fn.get("name", "")
        if not name:
            continue
        registry.register(
            ToolDefinition(
                name=name,
                description=fn.get("description", ""),
                schema=fn.get("parameters", {"type": "object", "properties": {}}),
                risk=_TOOL_RISKS.get(name, ToolRisk.READ_ONLY),
                concurrent_safe=_TOOL_CONCURRENCY.get(name, True),
                tags=["core"],
            )
        )
    return registry


class PermissionEngine:
    """Policy gate for terminal tool calls.

    The terminal UI does not have a human approval loop yet, so commands that
    would normally require confirmation are denied with a clear reason. This is
    intentional: once approval cards exist, this class can return
    requires_confirmation=True without touching the agent loop again.
    """

    _DESTRUCTIVE_SHELL_PATTERNS = [
        re.compile(r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*|/[sq]\b)", re.I),
        re.compile(r"\bremove-item\b.*(?:^|\s)-recurse\b", re.I),
        re.compile(r"\bdel(?:ete)?\b.*\s/[sq]\b", re.I),
        re.compile(r"\brd\b.*\s/[sq]\b", re.I),
        re.compile(r"\brmdir\b.*\s/[sq]\b", re.I),
        re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
        re.compile(r"\bgit\s+clean\s+-[^\s]*[fd][^\s]*\b", re.I),
        re.compile(r"\bgit\s+checkout\s+--\s+", re.I),
    ]

    _CRITICAL_SHELL_PATTERNS = [
        re.compile(r"\bformat\b", re.I),
        re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b", re.I),
        re.compile(r"\bshutdown\b", re.I),
        re.compile(r"\bstop-computer\b|\brestart-computer\b", re.I),
        re.compile(r"\bset-executionpolicy\b", re.I),
        re.compile(r"\b(start-process)\b.*\b-verb\s+runas\b", re.I),
        re.compile(r"\b(iex|invoke-expression)\b", re.I),
        re.compile(r"\b(curl|wget|irm|iwr)\b.*\|\s*(bash|sh|pwsh|powershell)\b", re.I),
    ]

    _SHELL_DELETE_PATTERNS = [
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\b", re.I),
        re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\b", re.I),
        re.compile(r"\bfind\b.*\b-exec\b\s+rm\b.*-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\b", re.I),
        re.compile(r"\bremove-item\b.*(?:^|\s)-recurse\b", re.I),
        re.compile(r"\bdel(?:ete)?\b.*\s/[sq]\b", re.I),
        re.compile(r"\brd\b.*\s/[sq]\b", re.I),
        re.compile(r"\brmdir\b.*\s/[sq]\b", re.I),
    ]

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def check(
        self,
        tool_name: str,
        args: Dict[str, Any],
        workspace_path: str,
        permission_mode: str | None = None,
    ) -> PermissionDecision:
        mode = normalize_permission_mode(permission_mode)
        tool = self.registry.get(tool_name)
        if not tool:
            return PermissionDecision(False, f"Unknown tool: {tool_name}", risk="unknown", mode=mode)
        if not tool.enabled:
            return PermissionDecision(False, f"Tool disabled: {tool_name}", risk=tool.risk, mode=mode)

        if not self._valid_workspace(workspace_path):
            return PermissionDecision(False, "Invalid or inaccessible workspace", risk=tool.risk, mode=mode)

        if tool.risk == ToolRisk.DESTRUCTIVE and mode != FULL_ACCESS_PERMISSION_MODE:
            return PermissionDecision(
                False,
                "Destructive action blocked: switch terminal permissions to full access first.",
                risk=tool.risk,
                requires_confirmation=True,
                mode=mode,
            )

        if tool_name == "bash":
            command = str(args.get("command", ""))
            shell_decision = self._check_shell_command(command, permission_mode=mode)
            if not shell_decision.allowed:
                return shell_decision

        return PermissionDecision(True, risk=tool.risk, mode=mode)

    @staticmethod
    def _valid_workspace(workspace_path: str) -> bool:
        if not workspace_path:
            return False
        try:
            return os.path.isdir(os.path.abspath(workspace_path))
        except Exception:
            return False

    def _check_shell_command(self, command: str, permission_mode: str | None = None) -> PermissionDecision:
        mode = normalize_permission_mode(permission_mode)
        normalized = " ".join(command.strip().split())
        if not normalized:
            return PermissionDecision(False, "Empty command", risk=ToolRisk.SHELL, mode=mode)
        if len(command) > 10_000:
            return PermissionDecision(
                False,
                "Command blocked: command too long.",
                risk=ToolRisk.SHELL,
                requires_confirmation=True,
                mode=mode,
            )
        if "\x00" in command:
            return PermissionDecision(
                False,
                "Command blocked: null byte detected.",
                risk=ToolRisk.SHELL,
                requires_confirmation=True,
                mode=mode,
            )

        lowered = normalized.lower()
        for pattern in self._CRITICAL_SHELL_PATTERNS:
            if pattern.search(lowered):
                return PermissionDecision(
                    False,
                    "Command blocked: critical system or privilege action.",
                    risk=ToolRisk.SHELL,
                    requires_confirmation=True,
                    mode=mode,
                )

        if mode == FULL_ACCESS_PERMISSION_MODE and is_workspace_clear_shell_command(command):
            return PermissionDecision(True, risk=ToolRisk.SHELL, mode=mode)

        for pattern in self._SHELL_DELETE_PATTERNS:
            if pattern.search(lowered):
                return PermissionDecision(
                    False,
                    "Command blocked: recursive shell deletion is not allowed; use clear_workspace or delete_file instead.",
                    risk=ToolRisk.SHELL,
                    requires_confirmation=mode != FULL_ACCESS_PERMISSION_MODE,
                    mode=mode,
                )

        if mode != FULL_ACCESS_PERMISSION_MODE:
            for pattern in self._DESTRUCTIVE_SHELL_PATTERNS:
                if pattern.search(lowered):
                    return PermissionDecision(
                        False,
                        "Command blocked: switch terminal permissions to full access first.",
                        risk=ToolRisk.SHELL,
                        requires_confirmation=True,
                        mode=mode,
                    )

        sub_commands, split_error = self._split_compound_command(command)
        if split_error:
            return PermissionDecision(
                False,
                f"Command blocked: {split_error}.",
                risk=ToolRisk.SHELL,
                requires_confirmation=True,
                mode=mode,
            )

        for sub_command in sub_commands:
            main_cmd = self._shell_main_command(sub_command)
            if not main_cmd:
                return PermissionDecision(False, "Command blocked: empty sub-command.", risk=ToolRisk.SHELL, mode=mode)
            if main_cmd.lower() not in ALLOWED_SHELL_COMMANDS:
                return PermissionDecision(
                    False,
                    f"Command blocked: sub-command is not allowed: {main_cmd}",
                    risk=ToolRisk.SHELL,
                    requires_confirmation=True,
                    mode=mode,
                )

        return PermissionDecision(True, risk=ToolRisk.SHELL, mode=mode)

    @staticmethod
    def _shell_main_command(command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return ""
        return parts[0] if parts else ""

    @staticmethod
    def _split_compound_command(command: str) -> tuple[List[str], str | None]:
        parts: List[str] = []
        current: List[str] = []
        in_single_quote = False
        in_double_quote = False
        escaping = False
        index = 0

        while index < len(command):
            char = command[index]

            if escaping:
                current.append(char)
                escaping = False
                index += 1
                continue

            if char == "\\" and not in_single_quote:
                current.append(char)
                escaping = True
                index += 1
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
                index += 1
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
                index += 1
                continue

            if not in_single_quote and not in_double_quote:
                if command.startswith("&&", index) or command.startswith("||", index):
                    part = "".join(current).strip()
                    if part:
                        parts.append(part)
                    current = []
                    index += 2
                    continue
                if char in {";", "|"}:
                    part = "".join(current).strip()
                    if part:
                        parts.append(part)
                    current = []
                    index += 1
                    continue

            current.append(char)
            index += 1

        if in_single_quote or in_double_quote or escaping:
            return [command], "unclosed quote or dangling escape"

        part = "".join(current).strip()
        if part:
            parts.append(part)
        return (parts if parts else [command]), None
