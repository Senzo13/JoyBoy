from __future__ import annotations

"""
Terminal Brain - Cerveau central pour le mode terminal
Architecture Cursor/Claude Code avec Native Ollama Tool Calling

Fonctionnement:
1. User envoie un message
2. LLM répond avec des tool_calls structurés (pas du texte à parser)
3. On exécute les tools et on renvoie les résultats
4. Loop jusqu'à ce que le LLM réponde sans tool_call

"""

import os
import json
import queue
import re
import threading
import time
from collections import defaultdict
from html import unescape
from typing import Dict, List, Optional, Any, Generator
from config import TOOL_CAPABLE_MODELS, TOOL_EXCLUDED_MODELS
from core.agent_runtime import (
    CloudModelError,
    get_cached_mcp_tools,
    ToolLoopGuard,
    chat_with_cloud_model,
    is_cloud_model_name,
    runtime_event,
    tool_signature,
)
from core.backends.terminal_tools import (
    DEFAULT_PERMISSION_MODE,
    FULL_ACCESS_PERMISSION_MODE,
    PermissionEngine,
    build_default_terminal_tool_registry,
    is_workspace_clear_shell_command,
    normalize_permission_mode,
)
from core.backends.terminal_tool_schemas import (
    DEFERRED_TOOL_NAMES,
    TOOLS,
)
from core.backends.terminal_actions import TerminalActionsMixin
from core.backends.terminal_cloud import TerminalCloudMixin
from core.backends.terminal_commands import TerminalSlashCommandsMixin
from core.backends.terminal_context import (
    MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE,
    TerminalContextMixin,
)
from core.backends.terminal_deferred_tools import TerminalDeferredToolMixin
from core.backends.terminal_guardrails import TerminalGuardrailsMixin
from core.backends.terminal_intent import TerminalIntentMixin
from core.backends.terminal_plan import ExecutionPlan, PlanStatus, PlanTask, TerminalPlanMixin
from core.backends.terminal_prompting import TerminalPromptingMixin
from core.backends.terminal_read_guard import TerminalReadGuardMixin
from core.backends.terminal_types import FileSnapshot, ToolResult

# Ollama client - auto-install si manquant
try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    print("[BRAIN] Package ollama manquant, installation automatique...")
    import subprocess
    import sys
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "ollama", "-q"])
        import ollama
        HAS_OLLAMA = True
        print("[BRAIN] Package ollama installé avec succès!")
    except Exception as e:
        HAS_OLLAMA = False
        print(f"[BRAIN] Erreur installation ollama: {e}")


# ===== MODÈLES COMPATIBLES TOOL CALLING =====
# TOOL_CAPABLE_MODELS et TOOL_EXCLUDED_MODELS importés depuis config.py


def is_tool_capable(model_name: str) -> bool:
    """Vérifie si un modèle supporte le native tool calling"""
    model_lower = model_name.lower()
    if any(excl in model_lower for excl in TOOL_EXCLUDED_MODELS):
        return False
    return any(cap in model_lower for cap in TOOL_CAPABLE_MODELS)


# ===== TERMINAL BRAIN =====

class TerminalBrain(
    TerminalActionsMixin,
    TerminalCloudMixin,
    TerminalContextMixin,
    TerminalIntentMixin,
    TerminalSlashCommandsMixin,
    TerminalDeferredToolMixin,
    TerminalGuardrailsMixin,
    TerminalPromptingMixin,
    TerminalReadGuardMixin,
    TerminalPlanMixin,
):
    """
    Cerveau du mode terminal avec Native Tool Calling.

    Comme Cursor/Claude Code:
    1. User message → LLM
    2. LLM répond avec tool_calls[] (structuré, pas du texte)
    3. Execute tools → feed results back
    4. Repeat jusqu'à réponse finale sans tools
    """

    MIN_CONTEXT_SIZE = 2048
    MAX_LOCAL_CONTEXT_SIZE = 262144
    DEFAULT_CLOUD_CONTEXT_SIZE = 262144
    MAX_CLOUD_CONTEXT_SIZE = 1_000_000
    _TEXT_TOOL_TAG_ALIASES = {
        "ask_clarification": "ask_clarification",
        "askclarification": "ask_clarification",
        "bash": "bash",
        "clear_workspace": "clear_workspace",
        "clearworkspace": "clear_workspace",
        "delegate_subagent": "delegate_subagent",
        "delegatesubagent": "delegate_subagent",
        "delete_file": "delete_file",
        "deletefile": "delete_file",
        "edit_file": "edit_file",
        "editfile": "edit_file",
        "glob": "glob",
        "list_files": "list_files",
        "listfiles": "list_files",
        "list_memory": "list_memory",
        "listmemory": "list_memory",
        "load_skill": "load_skill",
        "loadskill": "load_skill",
        "open_workspace": "open_workspace",
        "openworkspace": "open_workspace",
        "read_file": "read_file",
        "readfile": "read_file",
        "remember_fact": "remember_fact",
        "rememberfact": "remember_fact",
        "search": "search",
        "think": "think",
        "tool_search": "tool_search",
        "toolsearch": "tool_search",
        "web_fetch": "web_fetch",
        "webfetch": "web_fetch",
        "web_search": "web_search",
        "websearch": "web_search",
        "write_file": "write_file",
        "writefile": "write_file",
        "write_files": "write_files",
        "writefiles": "write_files",
        "write_todos": "write_todos",
        "writetodos": "write_todos",
    }
    _TEXT_TOOL_SCALAR_ARGS = {
        "ask_clarification": "question",
        "bash": "command",
        "delete_file": "path",
        "glob": "pattern",
        "list_files": "path",
        "list_memory": "query",
        "load_skill": "skill_id",
        "read_file": "path",
        "remember_fact": "content",
        "search": "pattern",
        "think": "thought",
        "tool_search": "query",
        "web_fetch": "url",
        "web_search": "query",
    }

    def __init__(self):
        self.snapshots: Dict[str, FileSnapshot] = {}
        self.action_history: List[Dict] = []
        # Keep the agent useful without letting a small local model spin forever.
        # `/auto` can still raise the budget for longer coding tasks.
        self.max_iterations = 8
        self.max_non_autonomous_tokens = 6500
        self._active_context_size = 4096
        self._active_workspace_path = ""
        self._active_deferred_tool_names = set()
        self._active_promoted_tool_names = set()
        self._ordered_deferred_tool_names = list(DEFERRED_TOOL_NAMES)
        self._mcp_tools_by_name: Dict[str, Any] = {}
        self.current_plan: Optional[ExecutionPlan] = None
        self._read_files_by_workspace = defaultdict(dict)
        self._active_read_result_signatures: set[str] = set()
        self._active_execution_journal: List[Dict[str, Any]] = []

        # Protection écriture
        self.current_intent: str = 'question'
        self.write_blocked: bool = False
        self.permission_mode: str = DEFAULT_PERMISSION_MODE
        self._cloud_circuit_failures = defaultdict(int)
        self._cloud_circuit_open_until = defaultdict(float)
        self._cloud_circuit_state = defaultdict(lambda: "closed")
        self._cloud_circuit_probe_in_flight = defaultdict(bool)
        self._cloud_circuit_threshold = 3
        self._cloud_circuit_timeout_seconds = 60
        self._progress_reporting_tools = {"bash", "web_search", "web_fetch", "delegate_subagent"}
        self._tool_progress_threshold_seconds = 2.0
        self._tool_progress_poll_seconds = 0.5

        # Modèle par défaut
        self.default_model = "qwen3.5:2b"

        # ToolRegistry is the new stable contract. The legacy dispatcher below
        # still runs the actual tools, but every call now goes through this
        # policy layer first so future packs/plugins do not bypass safety.
        self.tool_registry = build_default_terminal_tool_registry(TOOLS)
        self.permission_engine = PermissionEngine(self.tool_registry)
        self._refresh_dynamic_tool_registry()

    # ===== TEXT TOOL-CALL RECOVERY =====

    def _recover_text_tool_calls(self, content: str | None) -> tuple[List[Dict[str, Any]], str]:
        """Recover provider-emitted pseudo-XML tool calls.

        Some providers occasionally return literal tags such as
        ``<write_todos>...</write_todos>`` instead of structured ``tool_calls``.
        We only recover calls for tools known by the registry; normal execution
        still passes through PermissionEngine before doing anything.
        """
        source = str(content or "")
        if "<" not in source or ">" not in source:
            return [], source

        calls: List[Dict[str, Any]] = []
        spans: List[tuple[int, int]] = []

        wrapper_pattern = re.compile(r"<tool_call\b[^>]*>(?P<body>[\s\S]*?)</tool_call>", re.I)
        for match in wrapper_pattern.finditer(source):
            recovered = self._recover_text_tool_calls_from_block(match.group("body"), len(calls))
            if recovered:
                calls.extend(recovered)
                spans.append(match.span())

        direct_pattern = self._text_tool_tag_pattern()
        for match in direct_pattern.finditer(source):
            if any(start <= match.start() and match.end() <= end for start, end in spans):
                continue
            call = self._text_tool_call_from_match(match, len(calls))
            if call:
                calls.append(call)
                spans.append(match.span())

        if not calls:
            return [], source

        cleaned = self._remove_text_spans(source, spans)
        return self._normalise_tool_calls_for_history(calls, prefix="text_call"), cleaned

    @classmethod
    def _text_tool_tag_pattern(cls) -> re.Pattern:
        names = sorted(cls._TEXT_TOOL_TAG_ALIASES.keys(), key=len, reverse=True)
        escaped = "|".join(re.escape(name) for name in names)
        return re.compile(
            rf"<(?P<tag>{escaped})\b(?P<attrs>[^>]*)>(?P<body>[\s\S]*?)</(?P=tag)>",
            re.I,
        )

    def _recover_text_tool_calls_from_block(self, body: str, start_index: int = 0) -> List[Dict[str, Any]]:
        source = str(body or "").strip()
        if not source:
            return []

        json_payload = self._first_json_payload(source)
        call = self._text_tool_call_from_payload(json_payload, start_index) if isinstance(json_payload, dict) else None
        if call:
            return [call]

        calls: List[Dict[str, Any]] = []
        for match in self._text_tool_tag_pattern().finditer(source):
            call = self._text_tool_call_from_match(match, start_index + len(calls))
            if call:
                calls.append(call)
        return calls

    def _text_tool_call_from_payload(self, payload: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        raw_name = payload.get("name") or payload.get("tool") or payload.get("tool_name")
        tool_name = self._normalise_text_tool_name(raw_name)
        if not self._can_recover_text_tool(tool_name):
            return None

        args = payload.get("arguments", payload.get("args", payload.get("input", {})))
        if isinstance(args, str):
            args = self._first_json_payload(args) or {self._TEXT_TOOL_SCALAR_ARGS.get(tool_name, "input"): args}
        if not isinstance(args, dict):
            args = {}
        return self._build_recovered_tool_call(tool_name, self._normalise_recovered_tool_args(tool_name, args), index)

    def _text_tool_call_from_match(self, match: re.Match, index: int) -> Optional[Dict[str, Any]]:
        tool_name = self._normalise_text_tool_name(match.group("tag"))
        if not self._can_recover_text_tool(tool_name):
            return None

        attrs = self._parse_xmlish_attrs(match.group("attrs") or "")
        args = self._text_tool_args_from_body(tool_name, match.group("body") or "", attrs)
        if args is None:
            return None
        return self._build_recovered_tool_call(tool_name, args, index)

    def _can_recover_text_tool(self, tool_name: str) -> bool:
        return bool(tool_name and self.tool_registry.get(tool_name))

    @classmethod
    def _normalise_text_tool_name(cls, raw_name: Any) -> str:
        name = str(raw_name or "").strip()
        if not name:
            return ""
        compact = re.sub(r"[^a-zA-Z0-9_:-]+", "", name).replace("-", "_").lower()
        return cls._TEXT_TOOL_TAG_ALIASES.get(compact, compact)

    def _text_tool_args_from_body(
        self,
        tool_name: str,
        body: str,
        attrs: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        source = unescape(str(body or "").strip())
        payload = self._first_json_payload(source)
        if isinstance(payload, dict):
            return self._normalise_recovered_tool_args(tool_name, payload)
        if isinstance(payload, list) and tool_name == "write_todos":
            return {"todos": payload}

        if tool_name == "write_todos":
            todos = self._parse_text_todos(source)
            if todos:
                return {"todos": todos}
            lines = [line.strip("-* \t") for line in source.splitlines() if line.strip()]
            if lines:
                return {"todos": [{"content": line, "status": "pending"} for line in lines[:6]]}
            return None

        arg_key = self._TEXT_TOOL_SCALAR_ARGS.get(tool_name)
        if arg_key and source:
            return self._normalise_recovered_tool_args(tool_name, {arg_key: source})
        if attrs:
            return self._normalise_recovered_tool_args(tool_name, attrs)
        if tool_name == "open_workspace":
            return {}
        return None

    def _normalise_recovered_tool_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(args or {})
        if tool_name == "tool_search" and not payload.get("query"):
            query = payload.get("name") or payload.get("tool") or payload.get("tool_name")
            if query:
                payload["query"] = str(query)
        if tool_name == "write_todos":
            todos = payload.get("todos")
            if isinstance(todos, dict):
                payload["todos"] = [todos]
            elif isinstance(todos, str):
                payload["todos"] = self._parse_text_todos(todos) or [
                    {"content": todos.strip(), "status": "pending"}
                ]
        return payload

    def _parse_text_todos(self, source: str) -> List[Dict[str, Any]]:
        todos: List[Dict[str, Any]] = []
        todo_pattern = re.compile(r"<todo\b(?P<attrs>[^>]*)>(?P<body>[\s\S]*?)</todo>|<todo\b(?P<self_attrs>[^>]*)/?>", re.I)
        for index, match in enumerate(todo_pattern.finditer(str(source or "")), start=1):
            attrs = self._parse_xmlish_attrs(match.group("attrs") or match.group("self_attrs") or "")
            body = unescape(str(match.group("body") or "")).strip()
            content = str(attrs.get("content") or body or "").strip()
            if not content:
                continue
            status = str(attrs.get("status") or attrs.get("state") or "pending").strip().lower()
            if status not in {"pending", "in_progress", "completed", "blocked"}:
                status = "pending"
            todo: Dict[str, Any] = {
                "id": str(attrs.get("id") or index),
                "content": content,
                "status": status,
            }
            active_form = attrs.get("activeForm") or attrs.get("active_form") or attrs.get("activeform")
            if active_form:
                todo["activeForm"] = str(active_form)
            note = attrs.get("note")
            if note:
                todo["note"] = str(note)
            todos.append(todo)
        return todos

    @staticmethod
    def _parse_xmlish_attrs(source: str) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        attr_pattern = re.compile(r"([a-zA-Z_:][\w:.-]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>/]+))")
        for key, double, single, bare in attr_pattern.findall(str(source or "")):
            attrs[key] = unescape(double or single or bare or "")
        return attrs

    @staticmethod
    def _first_json_payload(source: Any) -> Any:
        text = str(source or "").strip()
        if not text:
            return None
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
                return payload
            except Exception:
                continue
        return None

    @staticmethod
    def _remove_text_spans(source: str, spans: List[tuple[int, int]]) -> str:
        if not spans:
            return source
        cleaned: List[str] = []
        cursor = 0
        for start, end in sorted(spans):
            if start < cursor:
                continue
            cleaned.append(source[cursor:start])
            cleaned.append("\n")
            cursor = end
        cleaned.append(source[cursor:])
        return re.sub(r"\n{3,}", "\n\n", "".join(cleaned)).strip()

    @staticmethod
    def _build_recovered_tool_call(tool_name: str, args: Dict[str, Any], index: int) -> Dict[str, Any]:
        return {
            "id": f"text_call_{index}_{tool_name}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(args or {}, ensure_ascii=False),
            },
        }

    # ===== TOOL EXECUTION =====

    def execute_tool(self, tool_name: str, args: Dict, workspace_path: str) -> ToolResult:
        """
        Exécute un tool et retourne le résultat.
        Crée des snapshots avant les modifications.
        """
        from core.workspace_tools import (
            list_files, read_file, search_files, glob_files,
            write_file, edit_file, delete_file
        )

        permission = self.permission_engine.check(
            tool_name,
            args or {},
            workspace_path,
            permission_mode=self.permission_mode,
        )
        if not permission.allowed:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                data={"permission": permission.to_dict()},
                error=permission.reason,
            )

        # Protection écriture si intent = lecture seule
        write_tools = ['write_file', 'write_files', 'edit_file', 'clear_workspace', 'delete_file']
        if tool_name in write_tools and self.is_read_only_intent(self.current_intent):
            self.write_blocked = True
            return ToolResult(
                success=False,
                tool_name=tool_name,
                error=f"BLOCKED: the user asked for analysis, not modification. "
                      f"Intent: '{self.current_intent}'"
            )

        try:
            # === LIST FILES ===
            if tool_name == "list_files":
                path = args.get('path', '.')
                result = list_files(workspace_path, path)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === READ FILE ===
            elif tool_name == "read_file":
                path = args.get('path', '')
                max_lines = args.get('max_lines', 220)
                start_line = args.get('start_line', 1)
                result = read_file(workspace_path, path, max_lines=max_lines, start_line=start_line)
                if result.get('success'):
                    state = result.get("read_state") if isinstance(result, dict) else {}
                    normalised_read_path = str(path or "").replace("\\", "/").lower()
                    read_signature = (
                        f"{self._workspace_key(workspace_path)}:"
                        f"{normalised_read_path}:"
                        f"{state.get('start_line')}:{state.get('end_line')}:{state.get('sha256')}"
                    )
                    if read_signature in self._active_read_result_signatures:
                        result["already_read"] = True
                        result["content"] = (
                            f"(unchanged; {result.get('path', path)} lines "
                            f"{result.get('start_line', '')}-{result.get('end_line', '')} "
                            "were already read earlier in this run)"
                        )
                    else:
                        self._active_read_result_signatures.add(read_signature)
                    self._track_read_file(workspace_path, path, result)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === WRITE FILE ===
            elif tool_name == "write_file":
                path = args.get('path', '')
                content = args.get('content', '')
                full_path = self._resolve_for_snapshot(workspace_path, path)
                if not full_path:
                    return ToolResult(success=False, tool_name=tool_name, error="Path escapes the workspace")

                # Snapshot si existe
                if os.path.exists(full_path):
                    blocked = self._require_read_before_existing_write(workspace_path, path, full_path, tool_name)
                    if blocked:
                        return blocked
                    self._create_snapshot(full_path, path)
                    # Validation anti-écrasement
                    is_valid, error = self._validate_write(full_path, content)
                    if not is_valid:
                        return ToolResult(success=False, tool_name=tool_name, error=error)

                result = write_file(workspace_path, path, content)
                if result.get('success'):
                    verified = self._verify_file_write(workspace_path, path)
                    result.update(verified)
                    if not verified.get('verified'):
                        return ToolResult(success=False, tool_name=tool_name, data=result, error=verified.get('error', 'Verification failed'))
                self._log_action('write_file', path, result.get('success', False))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === WRITE FILES ===
            elif tool_name == "write_files":
                result = self._execute_write_files_batch(
                    args.get('files', []),
                    workspace_path,
                    overwrite_existing=bool(args.get('overwrite_existing', False)),
                )
                return ToolResult(
                    success=result.get('success', False),
                    tool_name=tool_name,
                    data=result,
                    error=result.get('error'),
                )

            # === EDIT FILE ===
            elif tool_name == "edit_file":
                path = args.get('path', '')
                old_text = args.get('old_text', '')
                new_text = args.get('new_text', '')
                full_path = self._resolve_for_snapshot(workspace_path, path)
                if not full_path:
                    return ToolResult(success=False, tool_name=tool_name, error="Path escapes the workspace")

                if os.path.exists(full_path):
                    blocked = self._require_read_before_existing_write(
                        workspace_path,
                        path,
                        full_path,
                        tool_name,
                        old_text=old_text,
                    )
                    if blocked:
                        return blocked
                    self._create_snapshot(full_path, path)

                result = edit_file(
                    workspace_path,
                    path,
                    old_text,
                    new_text,
                    replace_all=bool(args.get('replace_all', False)),
                )
                if result.get('success'):
                    verified = self._verify_file_write(workspace_path, path)
                    result.update(verified)
                    if not verified.get('verified'):
                        return ToolResult(success=False, tool_name=tool_name, data=result, error=verified.get('error', 'Verification failed'))
                self._log_action('edit_file', path, result.get('success', False))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === DELETE FILE ===
            elif tool_name == "delete_file":
                path = args.get('path', '')
                full_path = self._resolve_for_snapshot(workspace_path, path)
                if not full_path:
                    return ToolResult(success=False, tool_name=tool_name, error="Path escapes the workspace")

                if os.path.exists(full_path):
                    self._create_snapshot(full_path, path)

                result = delete_file(workspace_path, path)
                if result.get('success'):
                    verified = self._verify_file_deleted(workspace_path, path)
                    result.update(verified)
                    if not verified.get('verified'):
                        return ToolResult(success=False, tool_name=tool_name, data=result, error=verified.get('error', 'Verification failed'))
                self._log_action('delete_file', path, result.get('success', False))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === CLEAR WORKSPACE ===
            elif tool_name == "clear_workspace":
                result = self._clear_workspace(workspace_path, keep=args.get('keep') or [])
                return ToolResult(
                    success=result.get('success', False),
                    tool_name=tool_name,
                    data=result,
                    error=result.get('error'),
                )

            # === SEARCH ===
            elif tool_name == "search":
                pattern = args.get('pattern', '')
                result = search_files(
                    workspace_path,
                    pattern,
                    file_pattern=args.get('file_pattern') or args.get('glob') or "*",
                    max_results=args.get('max_results', 50),
                    path=args.get('path', ''),
                    literal=bool(args.get('literal', False)),
                    case_sensitive=bool(args.get('case_sensitive', False)),
                )
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === GLOB ===
            elif tool_name == "glob":
                pattern = args.get('pattern', '')
                result = glob_files(
                    workspace_path,
                    pattern,
                    max_results=args.get('max_results', 100),
                    path=args.get('path', ''),
                    include_dirs=bool(args.get('include_dirs', False)),
                )
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === BASH ===
            elif tool_name == "bash":
                command = args.get('command', '')
                if (
                    self.permission_mode == FULL_ACCESS_PERMISSION_MODE
                    and is_workspace_clear_shell_command(command)
                ):
                    result = self._clear_workspace(workspace_path, keep=[".git"])
                    result["converted_action"] = "clear_workspace"
                    result["original_command"] = command
                    result["output"] = (
                        f"Converted broad shell deletion to internal clear_workspace. "
                        f"Deleted {result.get('count', 0)} top-level item(s)."
                    )
                    result["return_code"] = 0 if result.get("success") else 1
                    self._log_action('clear_workspace', "workspace", result.get('success', False))
                    return ToolResult(
                        success=result.get('success', False),
                        tool_name=tool_name,
                        data=result,
                        error=result.get('error'),
                    )
                result = self._execute_bash(command, workspace_path)
                self._log_action('bash', command, result.get('success', False))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === ASK CLARIFICATION ===
            elif tool_name == "ask_clarification":
                payload = self._build_clarification_payload(args)
                return ToolResult(success=True, tool_name=tool_name, data=payload)

            # === WRITE TODOS ===
            elif tool_name == "write_todos":
                result = self._write_todos(args.get('todos', []))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            # === TOOL SEARCH ===
            elif tool_name == "tool_search":
                query = args.get('query', '')
                result = self._execute_tool_search(query)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === WEB SEARCH ===
            elif tool_name == "web_search":
                query = args.get('query', '')
                result = self._execute_web_search(query)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === WEB FETCH ===
            elif tool_name == "web_fetch":
                url = args.get('url', '')
                result = self._execute_web_fetch(url)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            # === DELEGATE SUBAGENT ===
            elif tool_name == "delegate_subagent":
                agent_type = args.get('agent_type', 'code_explorer')
                result = self._delegate_subagent(
                    agent_type,
                    args.get('task', ''),
                    workspace_path,
                    max_files=args.get('max_files', 8),
                    command=args.get('command', ''),
                    timeout_seconds=args.get('timeout_seconds', 90),
                )
                status = str(result.get('status') or '').lower()
                verifier_completed_with_failure = agent_type == 'verifier' and status == 'failed'
                success = status == 'completed' or verifier_completed_with_failure
                error = result.get('error') or (None if success else result.get('summary'))
                return ToolResult(success=success, tool_name=tool_name, data=result, error=error)

            # === LOAD SKILL ===
            elif tool_name == "load_skill":
                skill_id = args.get('skill_id', '')
                result = self._load_pack_skill(skill_id)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            # === MEMORY ===
            elif tool_name == "remember_fact":
                result = self._remember_fact(args)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            elif tool_name == "list_memory":
                result = self._list_memory(args)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            # === OPEN WORKSPACE ===
            elif tool_name == "open_workspace":
                result = self._open_workspace_folder(workspace_path)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result, error=result.get('error'))

            # === THINK ===
            elif tool_name == "think":
                thought = args.get('thought', '')
                return ToolResult(
                    success=True,
                    tool_name=tool_name,
                    data={"thought": thought, "message": "Reasoning noted. Continue with a concrete tool call or final answer."}
                )

            # === MCP / EXTERNAL TOOLS ===
            elif tool_name in self._mcp_tools_by_name:
                tool = self._mcp_tools_by_name.get(tool_name)
                payload = tool.invoke(args or {})
                return ToolResult(
                    success=True,
                    tool_name=tool_name,
                    data={
                        "result": payload,
                        "server_name": getattr(tool, "server_name", ""),
                        "source": "mcp",
                    },
                )

            else:
                return ToolResult(success=False, tool_name=tool_name, error=f"Unknown tool: {tool_name}")

        except Exception as e:
            return ToolResult(success=False, tool_name=tool_name, error=str(e))

    # ===== AGENTIC LOOP =====

    def run_agentic_loop(
        self,
        initial_message: str,
        workspace_path: str,
        model: str = None,
        system_prompt: str = None,
        history: List[Dict] = None,
        autonomous: bool = False,  # Mode autonome: autorise les tâches longues, sans changer les permissions destructrices
        context_size: int = 4096,  # Taille du contexte (défaut: 4096)
        reasoning_effort: str | None = None,
        permission_mode: str | None = None,
        job_id: str = None,
        locale: str | None = None,
    ) -> Generator[Dict, None, None]:
        """
        Boucle agentique avec Native Tool Calling.

        Yields:
        - {'type': 'thinking'} - LLM réfléchit
        - {'type': 'content', 'text': '...'} - Réponse texte
        - {'type': 'tool_call', 'name': '...', 'args': {...}} - Tool appelé
        - {'type': 'tool_result', 'result': ToolResult} - Résultat
        - {'type': 'done', 'full_response': '...'} - Terminé
        - {'type': 'error', 'message': '...'} - Erreur
        """
        model = model or self.default_model
        use_cloud_model = is_cloud_model_name(model)
        self.permission_mode = normalize_permission_mode(permission_mode)
        self._active_context_size = self._normalize_context_size(context_size, cloud=use_cloud_model, model=model)
        self._active_workspace_path = workspace_path

        slash_command, slash_args = self._parse_terminal_slash_command(initial_message)
        if slash_command in self.TERMINAL_SLASH_COMMANDS:
            yield from self._run_terminal_slash_command(
                slash_command,
                slash_args,
                workspace_path,
                model=model,
                reasoning_effort=reasoning_effort,
                locale=locale,
            )
            return

        if self._is_casual_greeting_request(initial_message):
            self.current_intent = "question"
            self.write_blocked = False
            text = self._casual_greeting_answer(initial_message)
            yield runtime_event(
                'intent',
                intent=self.current_intent,
                read_only=True,
                autonomous=False,
                permission_mode=self.permission_mode,
            )
            yield runtime_event('content', text=text, token_stats={})
            yield runtime_event('done', full_response=text, token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0})
            return

        if not use_cloud_model and not HAS_OLLAMA:
            yield runtime_event('error', message='Package ollama non installé. pip install ollama')
            return

        resource_scheduler = None
        resource_lease_id = None

        def _end_resource_lease():
            nonlocal resource_lease_id
            if resource_scheduler and resource_lease_id:
                resource_scheduler.end_task(resource_lease_id)
                resource_lease_id = None

        try:
            from core.runtime import get_resource_scheduler

            if job_id:
                resource_scheduler = get_resource_scheduler()
                lease = resource_scheduler.begin_task(
                    "terminal",
                    job_id=job_id,
                    model_name=model,
                    requested_kwargs={
                        "context_size": self._active_context_size,
                        "autonomous": autonomous,
                        "reasoning_effort": reasoning_effort or "",
                        "permission_mode": self.permission_mode,
                    },
                )
                resource_lease_id = lease.get("id")
        except Exception as exc:
            print(f"[BRAIN] Resource scheduler skipped: {exc}")

        # Vérifier si le modèle supporte les tools
        if not use_cloud_model and not is_tool_capable(model):
            yield runtime_event('warning', message=f"Le modèle {model} ne supporte peut-être pas bien les tools. Recommandé: qwen3.5, qwen3, llama3.1")

        # Détecter le mode autonome via mot-clé
        if '/auto' in initial_message.lower() or '!auto' in initial_message.lower() or autonomous:
            autonomous = True
            initial_message = initial_message.replace('/auto', '').replace('!auto', '').replace('/AUTO', '').replace('!AUTO', '').strip()

        # Détecter l'intention (ou forcer write si mode autonome)
        if autonomous:
            self.current_intent = 'write'
            print(f"[BRAIN] 🤖 MODE AUTONOME ACTIVÉ")
        else:
            self.current_intent = self.detect_intent(initial_message)
        self.write_blocked = False
        self._active_read_result_signatures = set()
        self._active_execution_journal = []
        self._reset_deferred_tools(initial_message)
        self._active_promoted_tool_names.update(self._auto_promoted_deferred_tools(initial_message, []))
        if use_cloud_model:
            response_token_limit = 8192 if autonomous else (2048 if self.is_read_only_intent(self.current_intent) else 4096)
        else:
            response_token_limit = 4096 if autonomous else (1024 if self.is_read_only_intent(self.current_intent) else 2048)

        yield runtime_event(
            'intent',
            intent=self.current_intent,
            read_only=self.is_read_only_intent(self.current_intent),
            autonomous=autonomous,
            permission_mode=self.permission_mode,
        )

        if (
            self._is_clear_workspace_request(initial_message)
            and not self._is_scaffold_write_request(initial_message)
        ):
            args = {"keep": []}
            yield runtime_event('tool_call', name='clear_workspace', args=args)
            result = self.execute_tool('clear_workspace', args, workspace_path)
            yield runtime_event('tool_result', result={
                'success': result.success,
                'tool_name': result.tool_name,
                'data': result.data,
                'error': result.error,
                'write_blocked': False,
            })

            permission = result.data.get("permission") if isinstance(result.data, dict) else None
            if (
                not result.success
                and permission
                and permission.get("requires_confirmation")
                and permission.get("mode") == DEFAULT_PERMISSION_MODE
            ):
                yield runtime_event(
                    "approval_required",
                    tool_name="clear_workspace",
                    args=args,
                    permission=permission,
                    reason=result.error or permission.get("reason", ""),
                )
                _end_resource_lease()
                yield runtime_event(
                    "done",
                    full_response="",
                    token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0},
                    approval_required=True,
                )
                return

            if result.success:
                data = result.data if isinstance(result.data, dict) else {}
                count = data.get("count", 0)
                kept = data.get("kept", [])
                kept_text = f" Conservé : {', '.join(kept)}." if kept else ""
                text = f"C'est fait, j'ai vidé le dossier. {count} élément(s) supprimé(s).{kept_text}"
                yield runtime_event('content', text=text, token_stats={})
                _end_resource_lease()
                yield runtime_event(
                    'done',
                    full_response=text,
                    token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0},
                )
                return

            text = f"Je n'ai pas réussi à vider le dossier: {result.error or 'erreur inconnue'}"
            yield runtime_event('content', text=text, token_stats={})
            _end_resource_lease()
            yield runtime_event(
                'done',
                full_response=text,
                token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0},
            )
            return

        if self._is_open_workspace_request(initial_message):
            args = {}
            yield runtime_event('tool_call', name='open_workspace', args=args)
            result = self.execute_tool('open_workspace', args, workspace_path)
            yield runtime_event('tool_result', result={
                'success': result.success,
                'tool_name': result.tool_name,
                'data': result.data,
                'error': result.error,
                'write_blocked': False
            })
            text = (
                f"Dossier ouvert: {result.data.get('path', workspace_path)}"
                if result.success
                else f"Je n'ai pas réussi à ouvrir le dossier: {result.error or 'erreur inconnue'}"
            )
            yield runtime_event('content', text=text, token_stats={})
            _end_resource_lease()
            yield runtime_event('done', full_response=text, token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0})
            return

        if self._should_clarify_request(initial_message, history=history):
            text = self._clarification_answer(initial_message)
            yield runtime_event('content', text=text, token_stats={})
            _end_resource_lease()
            yield runtime_event('done', full_response=text, token_stats={'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0})
            return

        # System prompt par défaut
        if not system_prompt:
            system_prompt = self._get_default_system_prompt(workspace_path)

        repo_brief = None
        repo_brief_events = []
        if self._is_repo_overview_request(initial_message):
            repo_brief, repo_brief_events = self._build_repo_brief(workspace_path)
            if use_cloud_model:
                response_token_limit = min(response_token_limit, 1100)
            else:
                response_token_limit = min(response_token_limit, 800)
            for event in repo_brief_events:
                yield event

        # Construire les messages
        messages = [{"role": "system", "content": system_prompt}]

        if history:
            messages.extend(self._compact_history(history, context_size=self._active_context_size))

        memory_context = self._build_memory_context_prompt(initial_message)
        if memory_context:
            messages.append({"role": "user", "content": memory_context})

        if repo_brief:
            messages.append({
                "role": "user",
                "content": (
                    f"{initial_message}\n\n"
                    "REPO CONTEXT ALREADY EXPLORED BY JOYBOY:\n"
                    f"{repo_brief}\n\n"
                    "Answer now in the user's language with a concrete synthesis that feels useful, not tiny. "
                    "Target 10 to 16 short lines total, no code blocks, no JSON/templates, no long boilerplate. "
                    "Use up to four compact sections: verdict, what is solid, concrete issues from observed files, next step. "
                    "Mention 3 to 5 grounded points when the explored files support them. "
                    "Do not start with meta narration such as 'je vais', 'je n’ai pas besoin', or 'I will'. "
                    "Do not call list_files/glob/ls/pwd again: the useful context is already available."
                )
            })
        else:
            messages.append({"role": "user", "content": initial_message})

        full_response = ""
        iteration = 0
        iteration_budget = 20 if autonomous else (3 if repo_brief else self.max_iterations)
        turn_token_budget = self._turn_token_budget(
            self._active_context_size,
            autonomous=autonomous,
            cloud=use_cloud_model,
        )
        total_token_stats = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total': 0,
            'context_size': self._active_context_size,
        }
        loop_guard = ToolLoopGuard()
        guard_hits = 0
        force_final = bool(repo_brief)
        executed_tools = []
        continuation_nudges = 0
        todo_completion_reminders = 0
        write_progress_nudges = 0
        tool_error_followups = 0
        failed_tool_signatures: Dict[str, int] = defaultdict(int)
        tool_batch_signatures: Dict[str, int] = defaultdict(int)

        while iteration < iteration_budget:
            iteration += 1
            streamed_content_for_call = ""
            yield runtime_event('thinking', iteration=iteration, max_iterations=iteration_budget)

            try:
                messages, tools_for_model, prompt_estimate, tool_schema_stats = self._prepare_model_call(
                    messages=messages,
                    initial_message=initial_message,
                    executed_tools=executed_tools,
                    force_final=force_final,
                    autonomous=autonomous,
                )
                provider_messages = self._format_messages_for_provider(
                    messages,
                    "cloud" if use_cloud_model else "ollama",
                )

                if not autonomous and not force_final and iteration > 1:
                    remaining_budget = turn_token_budget - total_token_stats['total']
                    if remaining_budget <= 0 or prompt_estimate >= max(900, remaining_budget):
                        yield runtime_event(
                            'loop_warning',
                            action='token_budget',
                            reason='Stopping before another model call because the next prompt would exceed the turn budget.',
                        )
                        final_text = self._budget_fallback_answer(initial_message, executed_tools)
                        full_response += final_text
                        yield runtime_event('content', text=final_text, token_stats={})
                        _end_resource_lease()
                        yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                        return

                if use_cloud_model:
                    circuit_block = self._cloud_circuit_block_reason(model)
                    if circuit_block:
                        raise CloudModelError(circuit_block)
                    stream_cloud_content = not bool(repo_brief)
                    yield runtime_event(
                        'model_call',
                        model=model,
                        provider='cloud',
                        iteration=iteration,
                        tools_count=len(tools_for_model),
                        estimated_prompt_tokens=prompt_estimate,
                    )
                    cloud_attempt = 1
                    cloud_max_attempts = 3
                    while True:
                        try:
                            print(f"[BRAIN] Calling cloud model={model}, tools={len(tools_for_model)} tools")
                            stream_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
                            result_holder: Dict[str, Any] = {}

                            def _on_cloud_delta(chunk: str) -> None:
                                if chunk:
                                    stream_queue.put(("content", chunk))

                            def _call_cloud_model() -> None:
                                try:
                                    result_holder["response"] = chat_with_cloud_model(
                                        model,
                                        messages=provider_messages,
                                        tools=tools_for_model,
                                        max_tokens=response_token_limit,
                                        temperature=0.2,
                                        reasoning_effort=reasoning_effort,
                                        stream_callback=_on_cloud_delta if stream_cloud_content else None,
                                    )
                                except BaseException as exc:
                                    result_holder["error"] = exc
                                finally:
                                    stream_queue.put(("done", None))

                            worker = threading.Thread(target=_call_cloud_model, daemon=True)
                            worker.start()
                            model_call_started_at = time.monotonic()
                            last_progress_emit_at = model_call_started_at
                            while True:
                                try:
                                    stream_kind, stream_payload = stream_queue.get(timeout=0.25)
                                except queue.Empty:
                                    now = time.monotonic()
                                    elapsed = int(now - model_call_started_at)
                                    if elapsed >= 4 and now - last_progress_emit_at >= 6:
                                        last_progress_emit_at = now
                                        yield runtime_event(
                                            "model_progress",
                                            model=model,
                                            provider="cloud",
                                            iteration=iteration,
                                            elapsed_seconds=elapsed,
                                            stage=self._model_progress_stage(elapsed),
                                            context_kind="repo_overview" if repo_brief else "agent_turn",
                                            streamed=stream_cloud_content,
                                        )
                                    continue
                                if stream_kind == "content":
                                    chunk = str(stream_payload or "")
                                    if chunk:
                                        streamed_content_for_call += chunk
                                        full_response += chunk
                                        yield runtime_event('content', text=chunk, token_stats={})
                                elif stream_kind == "done":
                                    break
                            worker.join(timeout=0)
                            if result_holder.get("error"):
                                raise result_holder["error"]
                            response = result_holder.get("response") or {}
                            self._record_cloud_circuit_success(model)
                            break
                        except CloudModelError as exc:
                            retriable, reason = self._classify_cloud_model_error(exc)
                            if retriable and cloud_attempt < cloud_max_attempts:
                                wait_ms = self._cloud_retry_delay_ms(cloud_attempt, exc)
                                retry_message = self._cloud_retry_message(
                                    cloud_attempt,
                                    cloud_max_attempts,
                                    wait_ms,
                                    reason,
                                )
                                print(f"[BRAIN] {retry_message} ({exc})")
                                yield runtime_event('warning', message=retry_message)
                                time.sleep(wait_ms / 1000)
                                cloud_attempt += 1
                                continue
                            if retriable:
                                self._record_cloud_circuit_failure(model)
                            raise
                else:
                    print(f"[BRAIN] Calling ollama.chat with model={model}, tools={len(tools_for_model)} tools")
                    chat_kwargs = {
                        "model": model,
                        "messages": provider_messages,
                        "stream": False,
                        # Qwen reasoning models can spend the whole budget in hidden
                        # thinking and return message.content=None. Terminal mode
                        # needs visible answers first; tools already provide traces.
                        "think": False,
                        "keep_alive": "10m",
                        "options": {
                            'num_ctx': self._active_context_size,  # Utiliser la config utilisateur
                            'num_predict': response_token_limit,
                            'temperature': 0.2,
                        },
                    }
                    if tools_for_model:
                        chat_kwargs["tools"] = tools_for_model
                    try:
                        response = ollama.chat(**chat_kwargs)
                    except TypeError as exc:
                        if "keep_alive" not in str(exc):
                            raise
                        chat_kwargs.pop("keep_alive", None)
                        response = ollama.chat(**chat_kwargs)
                print(f"[BRAIN] Response type: {type(response)}")

                # Gérer réponse objet ou dict
                if hasattr(response, 'message'):
                    # Objet ChatResponse
                    msg = response.message
                    content = msg.content if hasattr(msg, 'content') else ''
                    content = content or ''
                    tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') and msg.tool_calls else []
                    # Convertir en dict pour l'historique
                    message_dict = {'role': 'assistant', 'content': content}
                    if tool_calls:
                        tool_calls = self._normalise_tool_calls_for_history(tool_calls)
                        message_dict['tool_calls'] = tool_calls
                else:
                    # Dict response
                    msg = response.get('message', {}) if isinstance(response, dict) else {}
                    msg = msg if isinstance(msg, dict) else {}
                    content = msg.get('content', '') or ''
                    tool_calls = self._normalise_tool_calls_for_history(msg.get('tool_calls', []))
                    message_dict = {'role': 'assistant', 'content': content}
                    if tool_calls:
                        message_dict['tool_calls'] = tool_calls

                if not tool_calls and content:
                    recovered_tool_calls, recovered_content = self._recover_text_tool_calls(content)
                    if recovered_tool_calls:
                        tool_calls = recovered_tool_calls
                        content = recovered_content
                        message_dict['content'] = content
                        message_dict['tool_calls'] = tool_calls
                        print(f"[BRAIN] Recovered text tool calls: {len(tool_calls)}")

                if repo_brief and content:
                    content = self._compact_repo_overview_response(content)
                    message_dict['content'] = content

                # Extraire les stats de tokens
                token_stats = {}
                if hasattr(response, 'prompt_eval_count'):
                    token_stats['prompt_tokens'] = response.prompt_eval_count or 0
                if hasattr(response, 'eval_count'):
                    token_stats['completion_tokens'] = response.eval_count or 0
                if isinstance(response, dict):
                    token_stats['prompt_tokens'] = int(response.get('prompt_eval_count') or 0)
                    token_stats['completion_tokens'] = int(response.get('eval_count') or 0)
                token_stats['total'] = token_stats.get('prompt_tokens', 0) + token_stats.get('completion_tokens', 0)
                token_stats['context_size'] = self._active_context_size
                token_stats['estimated_prompt_tokens'] = prompt_estimate
                token_stats.update(tool_schema_stats)

                # Accumuler les stats de tokens
                total_token_stats['prompt_tokens'] += token_stats.get('prompt_tokens', 0)
                total_token_stats['completion_tokens'] += token_stats.get('completion_tokens', 0)
                total_token_stats['total'] += token_stats.get('total', 0)
                total_token_stats['context_size'] = self._active_context_size
                total_token_stats['tool_count'] = token_stats.get('tool_count', 0)
                total_token_stats['tool_schema_tokens'] = token_stats.get('tool_schema_tokens', 0)
                total_token_stats['estimated_prompt_tokens'] = token_stats.get('estimated_prompt_tokens', 0)

                print(f"[BRAIN] Content: {self._debug_content_preview(content)}...")
                print(f"[BRAIN] Tool calls: {len(tool_calls) if tool_calls else 0}")
                print(f"[BRAIN] Tokens this call: {token_stats.get('total', 0)} | Total session: {total_token_stats['total']}")

                if tool_calls and not autonomous:
                    tool_calls, dropped_subagents = self._limit_delegate_subagent_calls(tool_calls)
                    if dropped_subagents:
                        if isinstance(message_dict, dict) and message_dict.get('tool_calls'):
                            message_dict['tool_calls'], _ = self._limit_delegate_subagent_calls(message_dict.get('tool_calls', []))
                        yield runtime_event(
                            'loop_warning',
                            action='delegate_subagent',
                            reason=(
                                f"Dropped {dropped_subagents} excess delegate_subagent call(s); "
                                f"limit is {MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE} per model response."
                            ),
                        )

                    tool_calls, dropped_by_type = self._limit_tool_calls_by_type(tool_calls)
                    if dropped_by_type:
                        if isinstance(message_dict, dict) and message_dict.get('tool_calls'):
                            message_dict['tool_calls'], _ = self._limit_tool_calls_by_type(message_dict.get('tool_calls', []))
                        summary = ", ".join(f"{name}={count}" for name, count in sorted(dropped_by_type.items()))
                        yield runtime_event(
                            'loop_warning',
                            action='tool_batch_frequency',
                            reason=(
                                f"Dropped excess tool calls in one model response: {summary}. "
                                "Batch frequency limits protect the turn from no-progress loops."
                            ),
                        )

                over_budget = (
                    not autonomous
                    and total_token_stats['total'] >= turn_token_budget
                    and not force_final
                )

                # Si du texte n'a pas déjà été envoyé par le stream cloud, l'envoyer maintenant.
                content_to_emit = content
                if streamed_content_for_call and content:
                    if content.startswith(streamed_content_for_call):
                        content_to_emit = content[len(streamed_content_for_call):]
                    elif content in streamed_content_for_call or streamed_content_for_call in content:
                        content_to_emit = ""
                if content_to_emit:
                    full_response += content_to_emit
                    yield runtime_event('content', text=content_to_emit, token_stats=token_stats)

                if over_budget:
                    yield runtime_event(
                        'loop_warning',
                        action='token_budget',
                        reason='Turn token budget reached; stopping before another model call.',
                    )
                    if not full_response.strip():
                        final_text = self._budget_fallback_answer(initial_message, executed_tools)
                        full_response += final_text
                        yield runtime_event('content', text=final_text, token_stats={})
                    _end_resource_lease()
                    yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                    return

                # Si pas de tool calls, vérifier si le modèle voulait continuer
                if not tool_calls:
                    if not content.strip() and not full_response.strip():
                        final_text = self._empty_model_fallback_answer(
                            initial_message=initial_message,
                            repo_brief=repo_brief,
                            executed_tools=executed_tools,
                        )
                        full_response += final_text
                        yield runtime_event('content', text=final_text, token_stats=token_stats)

                    # Détecter si le contenu suggère une continuation
                    continuation_keywords = [
                        'maintenant', 'ensuite', 'allons', 'je vais', 'nous allons',
                        'installons', 'créons', 'ajoutons', 'configurons', 'modifions',
                        'now let', "let's", 'next', 'then we', 'i will', "we'll",
                        'install', 'create', 'add', 'configure', 'modify', 'set up',
                        '...'  # Texte tronqué = probablement pas fini
                    ]
                    content_lower = (content or '').lower()
                    wants_to_continue = any(kw in content_lower for kw in continuation_keywords)

                    if self._looks_like_unverified_write_claim(content, executed_tools) and iteration < iteration_budget - 1:
                        print("[BRAIN] Réponse finale non vérifiée - relance avec exigence de preuve")
                        messages.append({
                            'role': 'assistant',
                            'content': content
                        })
                        messages.append({
                            'role': 'user',
                            'content': (
                                "You just claimed a creation or modification, but no write_file, edit_file, "
                                "or verified shell mutation succeeded in this session. Use write_file, "
                                "edit_file, or bash now, then verify with list_files/read_file or command "
                                "output. Otherwise clearly say that nothing was created."
                            )
                        })
                        continue

                    if self._has_incomplete_todos() and not force_final and iteration < iteration_budget - 1 and todo_completion_reminders < 2:
                        todo_completion_reminders += 1
                        messages.append({
                            'role': 'assistant',
                            'content': content
                        })
                        messages.append({
                            'role': 'user',
                            'content': (
                                "You still have incomplete active todos:\n"
                                f"{self._format_active_todos()}\n\n"
                                "Continue working on them. Call write_todos to update statuses before the final answer."
                            )
                        })
                        continue

                    if wants_to_continue and not force_final and iteration < iteration_budget - 1 and continuation_nudges < 1:
                        # Le modèle voulait continuer mais n'a pas fait de tool call
                        # Relancer avec un message de nudge
                        print(f"[BRAIN] Modèle veut continuer mais pas de tool call - relance")
                        continuation_nudges += 1
                        messages.append({
                            'role': 'assistant',
                            'content': content
                        })
                        messages.append({
                            'role': 'user',
                            'content': 'Continue by using the available tools for the next concrete step.'
                        })
                        continue  # Relancer la boucle

                    _end_resource_lease()
                    yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                    return

                batch_signature = self._tool_call_batch_signature(tool_calls) if len(tool_calls or []) > 1 else ""
                if batch_signature:
                    tool_batch_signatures[batch_signature] += 1
                    batch_seen = tool_batch_signatures[batch_signature]
                    if not autonomous and batch_seen >= 3:
                        yield runtime_event(
                            'loop_warning',
                            action='tool_batch_loop',
                            reason='Repeated identical tool-call batch reached the hard limit; stopping before executing it again.',
                        )
                        final_text = self._tool_batch_loop_fallback_answer(initial_message, executed_tools)
                        full_response += final_text
                        yield runtime_event('content', text=final_text, token_stats={})
                        _end_resource_lease()
                        yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                        return
                    if not autonomous and batch_seen >= 2:
                        yield runtime_event(
                            'loop_warning',
                            action='tool_batch_loop',
                            reason='Repeated identical tool-call batch detected; asking the model to choose a different next step.',
                        )
                        if content.strip():
                            messages.append({'role': 'assistant', 'content': content})
                        messages.append({
                            'role': 'user',
                            'content': (
                                "[LOOP DETECTED]\n"
                                "You repeated the same batch of tool calls. Do not execute that exact batch again. "
                                "Use the collected results, choose one different targeted tool call, or answer with the blocker."
                            ),
                        })
                        continue

                # Ajouter la réponse du LLM aux messages
                messages.append(message_dict)

                # Exécuter chaque tool call
                for tc in tool_calls:
                    # Gérer objet ou dict
                    if hasattr(tc, 'function'):
                        # Objet ToolCall
                        tool_name = tc.function.name
                        args_raw = tc.function.arguments
                        tool_call_id = getattr(tc, "id", "")
                    else:
                        # Dict
                        func = tc.get('function', {})
                        tool_name = func.get('name', '')
                        args_raw = func.get('arguments', {})
                        tool_call_id = tc.get('id', '')

                    # Parse les arguments
                    if isinstance(args_raw, str):
                        try:
                            args = json.loads(args_raw)
                        except Exception:
                            args = {}
                    else:
                        args = args_raw if args_raw else {}

                    print(f"[BRAIN] Executing tool: {tool_name}({self._tool_call_debug_preview(tool_name, args)})")

                    guard_reason = loop_guard.check(tool_name, args, executed_tools)
                    if guard_reason and not autonomous:
                        guard_hits += 1
                        yield runtime_event('loop_warning', action=tool_name, reason=guard_reason)
                        guard_text = (
                            f"[TERMINAL GUARDRAIL] {guard_reason}. "
                            "Stop repetitive tools and continue from the available context."
                        )
                        guard_message = {"role": "tool", "tool_name": tool_name, "content": guard_text}
                        if tool_call_id:
                            guard_message["tool_call_id"] = tool_call_id
                        messages.append(guard_message)
                        if self._should_continue_write_after_guard(tool_name, executed_tools) and guard_hits < 3:
                            messages.append({
                                'role': 'user',
                                'content': self._write_progress_nudge(initial_message),
                            })
                            continue

                        force_final = True
                        if guard_hits >= 2:
                            final_text = self._guardrail_fallback_answer(initial_message, executed_tools)
                            full_response += final_text
                            yield runtime_event('content', text=final_text, token_stats={})
                            _end_resource_lease()
                            yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                            return
                        messages.append({
                            'role': 'user',
                            'content': 'Answer now without tools. Summarize what is known and suggest the next useful file to read.'
                        })
                        continue

                    yield runtime_event('tool_call', name=tool_name, args=args)

                    # Exécuter le tool
                    result = None
                    if tool_name in self._progress_reporting_tools:
                        result_holder: Dict[str, Any] = {}

                        def _run_tool_with_progress() -> None:
                            try:
                                result_holder["result"] = self.execute_tool(tool_name, args, workspace_path)
                            except BaseException as exc:
                                result_holder["error"] = exc

                        started_at = time.time()
                        progress_thread = threading.Thread(target=_run_tool_with_progress, daemon=True)
                        progress_thread.start()
                        progress_tick = -1
                        while progress_thread.is_alive():
                            progress_thread.join(timeout=self._tool_progress_poll_seconds)
                            if not progress_thread.is_alive():
                                break
                            elapsed_seconds = int(time.time() - started_at)
                            if (
                                elapsed_seconds >= self._tool_progress_threshold_seconds
                                and elapsed_seconds > progress_tick
                            ):
                                progress_tick = elapsed_seconds
                                yield runtime_event(
                                    'tool_progress',
                                    name=tool_name,
                                    args=args,
                                    elapsed_seconds=elapsed_seconds,
                                )
                        if result_holder.get("error"):
                            raise result_holder["error"]
                        result = result_holder.get("result")
                    else:
                        result = self.execute_tool(tool_name, args, workspace_path)
                    if result is None:
                        result = ToolResult(success=False, tool_name=tool_name, error="Tool finished without a result")
                    executed_summary = self._summarize_executed_tool(tool_name, args, result)
                    executed_tools.append(executed_summary)
                    self._record_execution_journal(tool_name, args, result, executed_summary)
                    failure_signature = tool_signature(tool_name, args) if not result.success else ""
                    repeated_tool_failures = 0
                    if failure_signature:
                        failed_tool_signatures[failure_signature] += 1
                        repeated_tool_failures = failed_tool_signatures[failure_signature]

                    yield runtime_event('tool_result', result={
                        'success': result.success,
                        'tool_name': result.tool_name,
                        'data': result.data,
                        'error': result.error,
                        'write_blocked': self.write_blocked
                    })

                    if tool_name == "ask_clarification" and result.success:
                        final_text = self._format_clarification_payload_for_user(result.data)
                        full_response += final_text
                        yield runtime_event('content', text=final_text, token_stats={})
                        _end_resource_lease()
                        yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                        return

                    # Reset flag
                    if self.write_blocked:
                        self.write_blocked = False

                    # Ajouter le résultat aux messages pour le LLM
                    result_text = self._format_result_for_llm(result)
                    tool_message = {
                        "role": "tool",
                        "tool_name": result.tool_name,
                        "content": result_text
                    }
                    if tool_call_id:
                        tool_message["tool_call_id"] = tool_call_id
                    messages.append(tool_message)

                    permission = result.data.get("permission") if isinstance(result.data, dict) else None
                    if (
                        not result.success
                        and permission
                        and permission.get("requires_confirmation")
                        and permission.get("mode") == DEFAULT_PERMISSION_MODE
                    ):
                        yield runtime_event(
                            "approval_required",
                            tool_name=tool_name,
                            args=args,
                            permission=permission,
                            reason=result.error or permission.get("reason", ""),
                        )
                        _end_resource_lease()
                        yield runtime_event(
                            "done",
                            full_response=full_response,
                            token_stats=total_token_stats,
                            approval_required=True,
                        )
                        return

                    if not result.success and not autonomous:
                        failure_reason = self._classify_tool_error(result)
                        followup = self._tool_error_followup_message(
                            initial_message,
                            tool_name,
                            args,
                            result,
                            failure_reason,
                            repeated_tool_failures,
                        )
                        if followup and tool_error_followups < 3:
                            tool_error_followups += 1
                            messages.append({"role": "user", "content": followup})

                        if repeated_tool_failures >= 2:
                            yield runtime_event(
                                'loop_warning',
                                action='tool_error',
                                reason=(
                                    f"{tool_name} failed {repeated_tool_failures} times with the same arguments; "
                                    "stop retrying the same broken call."
                                ),
                            )

                        if self._should_stop_after_tool_error(
                            tool_name,
                            result,
                            failure_reason,
                            repeated_tool_failures,
                            executed_tools,
                        ):
                            force_final = True
                            final_text = self._tool_error_fallback_answer(initial_message, executed_tools)
                            full_response += final_text
                            yield runtime_event('content', text=final_text, token_stats={})
                            _end_resource_lease()
                            yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                            return

                if (
                    not autonomous
                    and not force_final
                    and self._should_finalize_after_scaffold_write(initial_message, executed_tools)
                ):
                    final_text = self._post_write_finalize_answer(initial_message, executed_tools)
                    full_response += final_text
                    yield runtime_event('content', text=final_text, token_stats={})
                    _end_resource_lease()
                    yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
                    return

                if (
                    not force_final
                    and write_progress_nudges < 2
                    and iteration < iteration_budget
                    and self._should_nudge_write_progress(initial_message, executed_tools)
                ):
                    write_progress_nudges += 1
                    messages.append({
                        'role': 'user',
                        'content': self._write_progress_nudge(initial_message),
                    })

            except CloudModelError as e:
                _end_resource_lease()
                print(f"[BRAIN] Cloud model failure: {e}")
                yield runtime_event('error', message=self._cloud_error_user_message(e))
                return
            except Exception as e:
                _end_resource_lease()
                yield runtime_event('error', message=str(e))
                return

        _end_resource_lease()
        if executed_tools:
            yield runtime_event(
                'loop_warning',
                action='iteration_limit',
                reason=f'Iteration limit reached ({iteration_budget}); returning collected context instead of another tool loop.',
            )
            final_text = self._iteration_limit_fallback_answer(initial_message, executed_tools)
            full_response += final_text
            yield runtime_event('content', text=final_text, token_stats={})
            yield runtime_event('done', full_response=full_response, token_stats=total_token_stats)
            return
        yield runtime_event('error', message=f'Iteration limit reached ({iteration_budget})')

    # ===== HELPERS =====

    def _model_progress_stage(self, elapsed_seconds: int) -> str:
        """Return a coarse UI stage while a model call is still pending."""
        elapsed = max(0, int(elapsed_seconds or 0))
        if elapsed < 10:
            return "drafting"
        if elapsed < 22:
            return "grounding"
        if elapsed < 40:
            return "formatting"
        return "finalizing"

    def get_snapshot(self, path: str) -> Optional[FileSnapshot]:
        return self.snapshots.get(path)

    def _compact_repo_overview_response(self, text: str, max_lines: int = 16, max_chars: int = 2200) -> str:
        """Keep quick repository audits closer to Codex-style summaries."""
        raw = str(text or "").strip()
        if not raw:
            return raw

        without_code = re.sub(r"```[\s\S]*?```", "", raw)
        visible_lines = [line for line in raw.splitlines() if line.strip()]
        lines: List[str] = []
        skip_prefixes = (
            "je vais",
            "je n'ai pas besoin",
            "je n’ai pas besoin",
            "i will",
            "i don't need",
            "voici une analyse détaillée",
            "voici l'analyse détaillée",
        )
        low_signal_prefixes = (
            "structure connue",
            "fichiers applicatifs principaux",
            "minimum recommandé",
            "exemple",
            "priorité ",
            "priorite ",
        )

        has_noisy_shape = (
            "```" in raw
            or any(
                line.strip().lower().lstrip("#-*0123456789. ").startswith(low_signal_prefixes)
                for line in raw.splitlines()
                if line.strip()
            )
            or any(
                line.strip().lower().startswith(skip_prefixes)
                for line in raw.splitlines()
                if line.strip()
            )
        )
        if not has_noisy_shape and len(raw) <= max_chars and len(visible_lines) <= max_lines:
            return raw

        for line in without_code.replace("\r\n", "\n").splitlines():
            item = line.strip()
            if not item:
                continue
            if item.startswith("```"):
                continue
            normalized = item.lower().lstrip("#-*0123456789. ")
            if any(normalized.startswith(prefix) for prefix in skip_prefixes):
                continue
            if any(normalized.startswith(prefix) for prefix in low_signal_prefixes):
                continue
            if len(item) > 190:
                item = item[:187].rstrip() + "..."
            lines.append(item)
            if len(lines) >= max_lines:
                break

        compact = "\n".join(lines).strip()
        if not compact:
            compact = re.sub(r"```[a-zA-Z0-9_+-]*\s*|\s*```", "", raw).strip()[:max_chars].strip()
        if len(compact) > max_chars:
            compact = compact[:max_chars].rstrip()
            if "\n" in compact:
                compact = compact.rsplit("\n", 1)[0].rstrip()
            compact += "\n..."
        return compact

    def rollback(self, path: str, workspace_path: str) -> bool:
        """Restaure un fichier depuis son snapshot"""
        snapshot = self.snapshots.get(path)
        if not snapshot:
            return False
        try:
            full_path = os.path.join(workspace_path, path)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(snapshot.content)
            print(f"[BRAIN] Rollback: {path}")
            return True
        except Exception:
            return False


# ===== INSTANCE GLOBALE =====

_brain_instance = None

def get_brain() -> TerminalBrain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = TerminalBrain()
    return _brain_instance
