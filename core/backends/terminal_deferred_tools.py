"""Deferred tool registry and MCP-backed tool search for terminal agent."""

from __future__ import annotations

import re
import sys
from typing import Dict, List

from core.agent_runtime import get_cached_mcp_tools
from core.backends.terminal_tool_schemas import (
    CORE_TOOL_NAMES,
    DEFERRED_TOOL_MAX_RESULTS,
    DEFERRED_TOOL_NAMES,
    TOOLS,
    WRITE_CORE_TOOL_NAMES,
)
from core.backends.terminal_tools import (
    PermissionEngine,
    ToolDefinition,
    ToolRisk,
    build_default_terminal_tool_registry,
)


class TerminalDeferredToolMixin:
    """DeerFlow-style deferred tools and compact tool discovery."""

    def _load_cached_mcp_tools(self):
        owner_module = sys.modules.get(self.__class__.__module__)
        loader = getattr(owner_module, "get_cached_mcp_tools", get_cached_mcp_tools)
        return loader()

    def _refresh_dynamic_tool_registry(self) -> None:
        """Reload optional MCP tools into the terminal registry."""
        registry = build_default_terminal_tool_registry(TOOLS)
        self._mcp_tools_by_name = {}

        deferred_order = list(DEFERRED_TOOL_NAMES)
        deferred_seen = set(deferred_order)
        try:
            mcp_tools = self._load_cached_mcp_tools()
        except Exception:
            mcp_tools = []

        for tool in mcp_tools:
            name = str(getattr(tool, "name", "") or "").strip()
            if not name or registry.get(name):
                continue
            description = str(getattr(tool, "description", "") or "MCP tool")
            schema = getattr(tool, "schema", None) or {"type": "object", "properties": {}}
            server_name = str(getattr(tool, "server_name", "") or "").strip()
            tags = ["mcp"]
            if server_name:
                tags.append(server_name)
            registry.register(
                ToolDefinition(
                    name=name,
                    description=description,
                    schema=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
                    risk=ToolRisk.NETWORK,
                    concurrent_safe=False,
                    tags=tags,
                )
            )
            self._mcp_tools_by_name[name] = tool
            if name not in deferred_seen:
                deferred_seen.add(name)
                deferred_order.append(name)

        self._ordered_deferred_tool_names = deferred_order
        self.tool_registry = registry
        self.permission_engine = PermissionEngine(self.tool_registry)

    def _reset_deferred_tools(self) -> None:
        """Prepare a DeerFlow-style deferred tool registry for this terminal run."""
        self._refresh_dynamic_tool_registry()
        self._active_deferred_tool_names = {
            name
            for name in self._ordered_deferred_tool_names
            if self.tool_registry.get(name)
        }
        self._active_promoted_tool_names = set()

    def _auto_promoted_deferred_tools(
        self,
        initial_message: str,
        executed_tools: List[Dict],
    ) -> List[str]:
        """Promote rare tools when the user's wording clearly asks for them."""
        msg = self._intent_text(initial_message)
        names: List[str] = []

        if any(word in msg for word in ("web", "internet", "url", "http", "site", "cherche sur le web", "search online")):
            names.extend(["web_search", "web_fetch"])

        if any(word in msg for word in ("skill", "pack", "workflow")):
            names.append("load_skill")

        if any(word in msg for word in ("memory", "memoire", "mémoire", "remember", "souviens", "souvenir", "retiens", "retenir")):
            names.extend(["list_memory", "remember_fact"])

        explicit_subagent_request = any(word in msg for word in (
            "subagent", "sub-agent", "delegate", "delegue", "délègue",
            "agent parallele", "agent parallèle", "parallel agent",
            "deerflow", "deer flow",
        ))
        if explicit_subagent_request:
            names.append("delegate_subagent")

        if self._is_clear_workspace_request(initial_message):
            names.append("clear_workspace")
        elif any(word in msg for word in ("delete", "supprime", "remove", "efface")):
            names.append("delete_file")

        if (
            explicit_subagent_request
            and self.current_plan
            and self._active_step_mode(initial_message) in {"verify", "analyze"}
        ):
            names.append("delegate_subagent")

        if self._should_use_todos_for_request(initial_message) and not self.current_plan:
            names.append("write_todos")

        seen = set()
        ordered: List[str] = []
        for name in names:
            if name in self._active_deferred_tool_names and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _should_offer_tool_search(self, message: str, executed_tools: List[Dict]) -> bool:
        """Expose tool_search only when a deferred tool is plausibly needed."""
        if not (self._active_deferred_tool_names - self._active_promoted_tool_names):
            return False

        msg = self._intent_text(message)
        deferred_markers = (
            "web", "internet", "url", "http", "site", "search online",
            "cherche sur le web", "skill", "pack", "workflow", "memory",
            "memoire", "mémoire", "remember", "souviens", "retiens",
            "delete", "supprime", "remove", "efface", "agent", "subagent",
            "delegate", "mcp", "outil", "tool",
        )
        explicit_deferred_request = any(marker in msg for marker in deferred_markers)
        if self._should_force_step_focus(message, executed_tools) and not explicit_deferred_request:
            return False
        if explicit_deferred_request:
            delete_request = any(marker in msg for marker in ("delete", "supprime", "remove", "efface"))
            if delete_request and {"clear_workspace", "delete_file"} & set(self._active_promoted_tool_names):
                return False
            return True
        if self._should_use_todos_for_request(message):
            return True
        if any(item.get("tool") == "tool_search" for item in executed_tools):
            return True
        return False

    def _search_deferred_tool_names(self, query: str) -> List[str]:
        """Search deferred tools by name/description without loading all schemas."""
        query = str(query or "").strip()
        candidates = [
            name
            for name in self._ordered_deferred_tool_names
            if name in self._active_deferred_tool_names
            and name not in self._active_promoted_tool_names
            and self.tool_registry.get(name)
        ]
        if not candidates:
            return []

        if query.startswith("select:"):
            requested = {item.strip() for item in query[7:].split(",") if item.strip()}
            return [name for name in candidates if name in requested][:DEFERRED_TOOL_MAX_RESULTS]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            required = parts[0].lower() if parts else ""
            narrowed = [name for name in candidates if required and required in self._deferred_tool_searchable_text(name).lower()]
            if len(parts) > 1:
                pattern = parts[1]
                narrowed.sort(
                    key=lambda name: self._deferred_tool_regex_score(pattern, name),
                    reverse=True,
                )
            return narrowed[:DEFERRED_TOOL_MAX_RESULTS]

        if not query:
            return candidates[:DEFERRED_TOOL_MAX_RESULTS]

        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)

        scored = []
        for name in candidates:
            searchable = self._deferred_tool_searchable_text(name)
            if regex.search(searchable):
                score = 2 if regex.search(name) else 1
                scored.append((score, name))

        if not scored:
            tokens = [token for token in re.split(r"\W+", query.lower()) if len(token) > 2]
            for name in candidates:
                searchable = self._deferred_tool_searchable_text(name).lower()
                score = sum(1 for token in tokens if token in searchable)
                if score:
                    scored.append((score, name))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [name for _, name in scored[:DEFERRED_TOOL_MAX_RESULTS]]

    def _deferred_tool_searchable_text(self, name: str) -> str:
        tool = self.tool_registry.get(name)
        if not tool:
            return name
        tags = " ".join(str(tag) for tag in (tool.tags or []))
        return f"{name} {tool.description or ''} {tags}"

    @staticmethod
    def _tool_search_requested_names(query: str) -> List[str]:
        query = str(query or "").strip()
        if not query.startswith("select:"):
            return []
        seen: set[str] = set()
        ordered: List[str] = []
        for item in query[7:].split(","):
            name = item.strip()
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _deferred_tool_regex_score(self, pattern: str, name: str) -> int:
        searchable = self._deferred_tool_searchable_text(name)
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        return len(regex.findall(searchable))

    def _execute_tool_search(self, query: str) -> Dict:
        requested = self._tool_search_requested_names(query)
        requested_core = [
            name
            for name in requested
            if name in CORE_TOOL_NAMES and self.tool_registry.get(name)
        ]
        blocked_core = [
            name
            for name in requested_core
            if name in WRITE_CORE_TOOL_NAMES and self.is_read_only_intent(self.current_intent)
        ]
        already_available = [name for name in requested_core if name not in blocked_core]
        matched_names = self._search_deferred_tool_names(query)
        self._active_promoted_tool_names.update(matched_names)
        tools = [
            self.tool_registry.get(name).to_ollama_tool()
            for name in matched_names
            if self.tool_registry.get(name)
        ]
        return {
            "success": True,
            "query": query,
            "promoted": matched_names,
            "already_available": already_available,
            "blocked_by_intent": blocked_core,
            "tools": tools,
            "remaining_deferred": [
                name
                for name in self._ordered_deferred_tool_names
                if name in self._active_deferred_tool_names
                and name not in self._active_promoted_tool_names
            ],
        }
