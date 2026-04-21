"""Reusable agent runtime primitives for JoyBoy.

This package is the public-core boundary for terminal/coding agent behavior.
Routes and UI adapters can depend on it, but it must stay independent from
Flask and other app-layer modules.
"""

from .events import TERMINAL_EVENT_TYPES, TERMINAL_EVENT_VERSION, runtime_event
from .guardrails import ToolLoopGuard, tool_guard_reason, tool_signature
from .model_client import (
    CloudModelError,
    chat_with_cloud_model,
    get_llm_provider_catalog,
    get_terminal_model_profiles,
    is_cloud_model_name,
)
from .memory import FileMemoryStore, remember_terminal_fact, search_terminal_memory
from .mcp_runtime import McpToolAdapter, get_cached_mcp_tools, get_deerflow_extensions_config, get_mcp_runtime_status, get_mcp_server_templates, reset_mcp_tool_cache
from .output import mask_workspace_paths, truncate_middle
from .subagents import run_code_explorer_subagent, run_subagent, run_verifier_subagent

__all__ = [
    "FileMemoryStore",
    "TERMINAL_EVENT_TYPES",
    "TERMINAL_EVENT_VERSION",
    "ToolLoopGuard",
    "CloudModelError",
    "chat_with_cloud_model",
    "get_llm_provider_catalog",
    "get_terminal_model_profiles",
    "is_cloud_model_name",
    "mask_workspace_paths",
    "McpToolAdapter",
    "get_cached_mcp_tools",
    "get_deerflow_extensions_config",
    "get_mcp_runtime_status",
    "get_mcp_server_templates",
    "remember_terminal_fact",
    "reset_mcp_tool_cache",
    "runtime_event",
    "run_code_explorer_subagent",
    "run_subagent",
    "run_verifier_subagent",
    "search_terminal_memory",
    "tool_guard_reason",
    "tool_signature",
    "truncate_middle",
]
