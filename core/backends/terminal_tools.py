"""
Terminal tool registry and permissions.

This module is the stable contract between the terminal agent and the actual
tool implementations. Keep policy here instead of scattering safety checks in
the agent loop, routes, or frontend cards.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


class ToolRisk:
    READ_ONLY = "read_only"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    SHELL = "shell"
    NETWORK = "network"
    REASONING = "reasoning"


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
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

    def ollama_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_ollama_tool() for tool in self.list(enabled_only=True)]

    def public_tools(self) -> List[Dict[str, Any]]:
        return [tool.to_public_dict() for tool in self.list(enabled_only=False)]


_TOOL_RISKS = {
    "list_files": ToolRisk.READ_ONLY,
    "read_file": ToolRisk.READ_ONLY,
    "search": ToolRisk.READ_ONLY,
    "glob": ToolRisk.READ_ONLY,
    "write_file": ToolRisk.WRITE,
    "edit_file": ToolRisk.WRITE,
    "delete_file": ToolRisk.DESTRUCTIVE,
    "bash": ToolRisk.SHELL,
    "web_search": ToolRisk.NETWORK,
    "think": ToolRisk.REASONING,
    "open_workspace": ToolRisk.READ_ONLY,
}

_TOOL_CONCURRENCY = {
    "write_file": False,
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
        re.compile(r"\bformat\b", re.I),
        re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b", re.I),
        re.compile(r"\bshutdown\b", re.I),
        re.compile(r"\bstop-computer\b|\brestart-computer\b", re.I),
        re.compile(r"\bset-executionpolicy\b", re.I),
        re.compile(r"\b(start-process)\b.*\b-verb\s+runas\b", re.I),
        re.compile(r"\b(iex|invoke-expression)\b", re.I),
        re.compile(r"\b(curl|wget|irm|iwr)\b.*\|\s*(bash|sh|pwsh|powershell)\b", re.I),
    ]

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def check(self, tool_name: str, args: Dict[str, Any], workspace_path: str) -> PermissionDecision:
        tool = self.registry.get(tool_name)
        if not tool:
            return PermissionDecision(False, f"Tool inconnu: {tool_name}", risk="unknown")
        if not tool.enabled:
            return PermissionDecision(False, f"Tool desactive: {tool_name}", risk=tool.risk)

        if not self._valid_workspace(workspace_path):
            return PermissionDecision(False, "Workspace invalide ou inaccessible", risk=tool.risk)

        if tool.risk == ToolRisk.DESTRUCTIVE:
            return PermissionDecision(
                False,
                "Action destructive bloquee: confirmation UI non disponible.",
                risk=tool.risk,
                requires_confirmation=True,
            )

        if tool_name == "bash":
            command = str(args.get("command", ""))
            shell_decision = self._check_shell_command(command)
            if not shell_decision.allowed:
                return shell_decision

        return PermissionDecision(True, risk=tool.risk)

    @staticmethod
    def _valid_workspace(workspace_path: str) -> bool:
        if not workspace_path:
            return False
        try:
            return os.path.isdir(os.path.abspath(workspace_path))
        except Exception:
            return False

    def _check_shell_command(self, command: str) -> PermissionDecision:
        normalized = " ".join(command.strip().split())
        if not normalized:
            return PermissionDecision(False, "Commande vide", risk=ToolRisk.SHELL)

        lowered = normalized.lower()
        for pattern in self._DESTRUCTIVE_SHELL_PATTERNS:
            if pattern.search(lowered):
                return PermissionDecision(
                    False,
                    "Commande bloquee: action destructive ou elevation non confirmee.",
                    risk=ToolRisk.SHELL,
                    requires_confirmation=True,
                )

        return PermissionDecision(True, risk=ToolRisk.SHELL)
