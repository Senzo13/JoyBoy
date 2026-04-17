"""
Terminal Brain - Cerveau central pour le mode terminal
Architecture Cursor/Claude Code avec Native Ollama Tool Calling

Fonctionnement:
1. User envoie un message
2. LLM répond avec des tool_calls structurés (pas du texte à parser)
3. On exécute les tools et on renvoie les résultats
4. Loop jusqu'à ce que le LLM réponde sans tool_call

Sources:
- https://github.com/ollama/ollama/blob/main/docs/api.md#chat-request-with-tools
- https://ollama.com/blog/tool-support
"""

import os
import json
from collections import defaultdict
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from config import TOOL_CAPABLE_MODELS, TOOL_EXCLUDED_MODELS
from core.backends.terminal_tools import (
    PermissionEngine,
    build_default_terminal_tool_registry,
)

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


# ===== DÉFINITION DES TOOLS =====
# Format Ollama/OpenAI compatible

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the workspace. Default: '.'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file. Always read an existing file before editing or replacing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace."
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum lines to read. Default: 220. Prefer small chunks to preserve context."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or fully replace a file. If the file already exists, read_file must be called first or the tool fails.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace."
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact text slice in an existing file. Fails unless read_file was called first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace."
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text to replace. It must be unique in the file."
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text."
                    }
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file. This is blocked until the UI supports explicit confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to delete."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for a regex pattern in workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for."
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in. Default: the whole workspace."
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional file filter, for example '*.py' or '*.js'."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by glob pattern, for example '**/*.py'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, for example '**/*.py' or 'src/**/*.js'."
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run an allowed shell command inside the workspace. Prefer tools for file edits; use shell for tests, builds, installs, scaffolds, and git status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web through the configured local search provider.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": "Think briefly before acting. Useful for planning complex tasks, but do not loop on it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {
                        "type": "string",
                        "description": "Short reasoning note about the next action."
                    }
                },
                "required": ["thought"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_workspace",
            "description": "Open the workspace root folder in the local file explorer.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


# ===== TYPES =====

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


@dataclass
class FileSnapshot:
    path: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ToolResult:
    success: bool
    tool_name: str
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ===== TERMINAL BRAIN =====

class TerminalBrain:
    """
    Cerveau du mode terminal avec Native Tool Calling.

    Comme Cursor/Claude Code:
    1. User message → LLM
    2. LLM répond avec tool_calls[] (structuré, pas du texte)
    3. Execute tools → feed results back
    4. Repeat jusqu'à réponse finale sans tools
    """

    def __init__(self):
        self.snapshots: Dict[str, FileSnapshot] = {}
        self.action_history: List[Dict] = []
        # Keep the agent useful without letting a small local model spin forever.
        # `/auto` can still raise the budget for longer coding tasks.
        self.max_iterations = 8
        self.max_non_autonomous_tokens = 12000
        self._active_context_size = 4096
        self.current_plan: Optional[ExecutionPlan] = None
        self._read_files_by_workspace = defaultdict(dict)

        # Protection écriture
        self.current_intent: str = 'question'
        self.write_blocked: bool = False

        # Modèle par défaut
        self.default_model = "qwen3.5:2b"

        # ToolRegistry is the new stable contract. The legacy dispatcher below
        # still runs the actual tools, but every call now goes through this
        # policy layer first so future packs/plugins do not bypass safety.
        self.tool_registry = build_default_terminal_tool_registry(TOOLS)
        self.permission_engine = PermissionEngine(self.tool_registry)

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

        permission = self.permission_engine.check(tool_name, args or {}, workspace_path)
        if not permission.allowed:
            return ToolResult(
                success=False,
                tool_name=tool_name,
                data={"permission": permission.to_dict()},
                error=permission.reason,
            )

        # Protection écriture si intent = lecture seule
        write_tools = ['write_file', 'edit_file', 'delete_file']
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
                result = read_file(workspace_path, path, max_lines=max_lines)
                if result.get('success'):
                    self._track_read_file(workspace_path, path)
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

            # === EDIT FILE ===
            elif tool_name == "edit_file":
                path = args.get('path', '')
                old_text = args.get('old_text', '')
                new_text = args.get('new_text', '')
                full_path = self._resolve_for_snapshot(workspace_path, path)
                if not full_path:
                    return ToolResult(success=False, tool_name=tool_name, error="Path escapes the workspace")

                if os.path.exists(full_path):
                    blocked = self._require_read_before_existing_write(workspace_path, path, full_path, tool_name)
                    if blocked:
                        return blocked
                    self._create_snapshot(full_path, path)

                result = edit_file(workspace_path, path, old_text, new_text)
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

            # === SEARCH ===
            elif tool_name == "search":
                pattern = args.get('pattern', '')
                result = search_files(workspace_path, pattern)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === GLOB ===
            elif tool_name == "glob":
                pattern = args.get('pattern', '')
                result = glob_files(workspace_path, pattern)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === BASH ===
            elif tool_name == "bash":
                command = args.get('command', '')
                result = self._execute_bash(command, workspace_path)
                self._log_action('bash', command, result.get('success', False))
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

            # === WEB SEARCH ===
            elif tool_name == "web_search":
                query = args.get('query', '')
                result = self._execute_web_search(query)
                return ToolResult(success=result.get('success', False), tool_name=tool_name, data=result)

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
        autonomous: bool = False,  # Mode autonome - bypass les protections
        context_size: int = 4096,  # Taille du contexte (défaut: 4096)
        job_id: str = None,
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
        if not HAS_OLLAMA:
            yield {'type': 'error', 'message': 'Package ollama non installé. pip install ollama'}
            return

        model = model or self.default_model
        self._active_context_size = max(2048, int(context_size or 4096))
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
                    requested_kwargs={"context_size": context_size, "autonomous": autonomous},
                )
                resource_lease_id = lease.get("id")
        except Exception as exc:
            print(f"[BRAIN] Resource scheduler skipped: {exc}")

        # Vérifier si le modèle supporte les tools
        if not is_tool_capable(model):
            yield {'type': 'warning', 'message': f"Le modèle {model} ne supporte peut-être pas bien les tools. Recommandé: qwen3.5, qwen3, llama3.1"}

        # Détecter le mode autonome via mot-clé
        if '/auto' in initial_message.lower() or '!auto' in initial_message.lower() or autonomous:
            autonomous = True
            initial_message = initial_message.replace('/auto', '').replace('!auto', '').replace('/AUTO', '').replace('!AUTO', '').strip()

        # Détecter l'intention (ou forcer write si mode autonome)
        if autonomous:
            self.current_intent = 'write'  # Mode autonome = tout est permis
            print(f"[BRAIN] 🤖 MODE AUTONOME ACTIVÉ - Aucune restriction")
        else:
            self.current_intent = self.detect_intent(initial_message)
        self.write_blocked = False

        yield {'type': 'intent', 'intent': self.current_intent, 'read_only': self.is_read_only_intent(self.current_intent), 'autonomous': autonomous}

        if self._is_open_workspace_request(initial_message):
            args = {}
            yield {'type': 'tool_call', 'name': 'open_workspace', 'args': args}
            result = self.execute_tool('open_workspace', args, workspace_path)
            yield {'type': 'tool_result', 'result': {
                'success': result.success,
                'tool_name': result.tool_name,
                'data': result.data,
                'error': result.error,
                'write_blocked': False
            }}
            text = (
                f"Dossier ouvert: {result.data.get('path', workspace_path)}"
                if result.success
                else f"Je n'ai pas réussi à ouvrir le dossier: {result.error or 'erreur inconnue'}"
            )
            yield {'type': 'content', 'text': text, 'token_stats': {}}
            _end_resource_lease()
            yield {'type': 'done', 'full_response': text, 'token_stats': {'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0}}
            return

        # System prompt par défaut
        if not system_prompt:
            system_prompt = self._get_default_system_prompt(workspace_path)

        repo_brief = None
        repo_brief_events = []
        if self._is_repo_overview_request(initial_message):
            repo_brief, repo_brief_events = self._build_repo_brief(workspace_path)
            for event in repo_brief_events:
                yield event

        # Construire les messages
        messages = [{"role": "system", "content": system_prompt}]

        if history:
            messages.extend(self._compact_history(history, context_size=context_size))

        if repo_brief:
            messages.append({
                "role": "user",
                "content": (
                    f"{initial_message}\n\n"
                    "REPO CONTEXT ALREADY EXPLORED BY JOYBOY:\n"
                    f"{repo_brief}\n\n"
                    "Answer now in the user's language with a concrete synthesis. "
                    "Do not call list_files/glob/ls/pwd again: the useful context is already available."
                )
            })
        else:
            messages.append({"role": "user", "content": initial_message})

        full_response = ""
        iteration = 0
        iteration_budget = 20 if autonomous else (3 if repo_brief else self.max_iterations)
        turn_token_budget = max(3500, min(self.max_non_autonomous_tokens, int(self._active_context_size * 1.35)))
        total_token_stats = {'prompt_tokens': 0, 'completion_tokens': 0, 'total': 0}
        tool_seen = defaultdict(int)
        guard_hits = 0
        force_final = bool(repo_brief)
        executed_tools = []

        while iteration < iteration_budget:
            iteration += 1
            yield {'type': 'thinking', 'iteration': iteration, 'max_iterations': iteration_budget}

            try:
                # Appel Ollama avec tools
                tools_for_model = [] if force_final else self.tool_registry.ollama_tools()
                messages = self._compact_loop_messages(messages, context_size=self._active_context_size)
                print(f"[BRAIN] Calling ollama.chat with model={model}, tools={len(tools_for_model)} tools")
                chat_kwargs = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    # Qwen reasoning models can spend the whole budget in hidden
                    # thinking and return message.content=None. Terminal mode
                    # needs visible answers first; tools already provide traces.
                    "think": False,
                    "keep_alive": "10m",
                    "options": {
                        'num_ctx': self._active_context_size,  # Utiliser la config utilisateur
                        'num_predict': 4096 if autonomous else 2048,
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
                        message_dict['tool_calls'] = [
                            {'type': 'function', 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}}
                            for tc in tool_calls
                        ]
                else:
                    # Dict response
                    msg = response.get('message', {})
                    content = msg.get('content', '') or ''
                    tool_calls = msg.get('tool_calls', [])
                    message_dict = msg

                # Extraire les stats de tokens
                token_stats = {}
                if hasattr(response, 'prompt_eval_count'):
                    token_stats['prompt_tokens'] = response.prompt_eval_count or 0
                if hasattr(response, 'eval_count'):
                    token_stats['completion_tokens'] = response.eval_count or 0
                token_stats['total'] = token_stats.get('prompt_tokens', 0) + token_stats.get('completion_tokens', 0)

                # Accumuler les stats de tokens
                total_token_stats['prompt_tokens'] += token_stats.get('prompt_tokens', 0)
                total_token_stats['completion_tokens'] += token_stats.get('completion_tokens', 0)
                total_token_stats['total'] += token_stats.get('total', 0)

                print(f"[BRAIN] Content: {content[:100] if content else 'None'}...")
                print(f"[BRAIN] Tool calls: {len(tool_calls) if tool_calls else 0}")
                print(f"[BRAIN] Tokens this call: {token_stats.get('total', 0)} | Total session: {total_token_stats['total']}")

                if not autonomous and total_token_stats['total'] >= turn_token_budget and not force_final:
                    force_final = True
                    yield {
                        'type': 'loop_warning',
                        'action': 'token_budget',
                        'reason': 'Turn token budget reached; switching to a final synthesis.'
                    }
                    messages.append({
                        'role': 'user',
                        'content': (
                            "Stop using tools: the turn budget is reached. Produce a concrete final answer "
                            "from the observed evidence. If context is insufficient, name the exact files "
                            "that should be read next."
                        )
                    })
                    continue

                # Si du texte, l'envoyer avec les stats
                if content:
                    full_response += content
                    yield {'type': 'content', 'text': content, 'token_stats': token_stats}

                # Si pas de tool calls, vérifier si le modèle voulait continuer
                if not tool_calls:
                    if not content.strip() and not full_response.strip():
                        final_text = self._empty_model_fallback_answer(
                            initial_message=initial_message,
                            repo_brief=repo_brief,
                            executed_tools=executed_tools,
                        )
                        full_response += final_text
                        yield {'type': 'content', 'text': final_text, 'token_stats': token_stats}

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

                    if wants_to_continue and iteration < iteration_budget - 1:
                        # Le modèle voulait continuer mais n'a pas fait de tool call
                        # Relancer avec un message de nudge
                        print(f"[BRAIN] Modèle veut continuer mais pas de tool call - relance")
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
                    yield {'type': 'done', 'full_response': full_response, 'token_stats': total_token_stats}
                    return

                # Ajouter la réponse du LLM aux messages
                messages.append(message_dict)

                # Exécuter chaque tool call
                for tc in tool_calls:
                    # Gérer objet ou dict
                    if hasattr(tc, 'function'):
                        # Objet ToolCall
                        tool_name = tc.function.name
                        args_raw = tc.function.arguments
                    else:
                        # Dict
                        func = tc.get('function', {})
                        tool_name = func.get('name', '')
                        args_raw = func.get('arguments', {})

                    # Parse les arguments
                    if isinstance(args_raw, str):
                        try:
                            args = json.loads(args_raw)
                        except Exception:
                            args = {}
                    else:
                        args = args_raw if args_raw else {}

                    print(f"[BRAIN] Executing tool: {tool_name}({args})")

                    signature = self._tool_signature(tool_name, args)
                    tool_seen[signature] += 1
                    guard_reason = self._tool_guard_reason(tool_name, args, tool_seen[signature], executed_tools)
                    if guard_reason and not autonomous:
                        guard_hits += 1
                        force_final = True
                        yield {
                            'type': 'loop_warning',
                            'action': tool_name,
                            'reason': guard_reason,
                        }
                        guard_text = (
                            f"[TERMINAL GUARDRAIL] {guard_reason}. "
                            "Stop repetitive tools and produce the final synthesis now."
                        )
                        messages.append({"role": "tool", "tool_name": tool_name, "content": guard_text})
                        if guard_hits >= 2:
                            final_text = self._guardrail_fallback_answer(initial_message, executed_tools)
                            full_response += final_text
                            yield {'type': 'content', 'text': final_text, 'token_stats': {}}
                            _end_resource_lease()
                            yield {'type': 'done', 'full_response': full_response, 'token_stats': total_token_stats}
                            return
                        messages.append({
                            'role': 'user',
                            'content': 'Answer now without tools. Summarize what is known and suggest the next useful file to read.'
                        })
                        continue

                    yield {'type': 'tool_call', 'name': tool_name, 'args': args}

                    # Exécuter le tool
                    result = self.execute_tool(tool_name, args, workspace_path)
                    executed_tools.append(self._summarize_executed_tool(tool_name, args, result))

                    yield {'type': 'tool_result', 'result': {
                        'success': result.success,
                        'tool_name': result.tool_name,
                        'data': result.data,
                        'error': result.error,
                        'write_blocked': self.write_blocked
                    }}

                    # Reset flag
                    if self.write_blocked:
                        self.write_blocked = False

                    # Ajouter le résultat aux messages pour le LLM
                    result_text = self._format_result_for_llm(result)
                    messages.append({
                        "role": "tool",
                        "tool_name": result.tool_name,
                        "content": result_text
                    })

            except Exception as e:
                _end_resource_lease()
                yield {'type': 'error', 'message': str(e)}
                return

        _end_resource_lease()
        yield {'type': 'error', 'message': f'Iteration limit reached ({iteration_budget})'}

    # ===== HELPERS =====

    def _compact_history(self, history: List[Dict], context_size: int = 4096) -> List[Dict]:
        """Keep recent terminal context inside a rough character budget.

        Local 2B/4B models slow down sharply when we dump huge histories into
        every tool call. This mirrors Codex-style session compaction: preserve
        the latest turns, skip empty messages, and let files be re-read by tools
        instead of pasting the whole world back into the prompt.
        """
        max_chars = max(3000, min(12000, int(context_size) * 1))
        compact: List[Dict] = []
        total = 0
        for msg in reversed(history[-12:]):
            content = str(msg.get("content", "")).strip()
            role = msg.get("role", "user")
            if not content:
                continue
            if len(content) > 1200:
                content = content[:1200] + "\n... (conversation tronquee)"
            if total + len(content) > max_chars and compact:
                break
            compact.append({"role": role, "content": content})
            total += len(content)
        compact.reverse()
        return compact

    def _compact_loop_messages(self, messages: List[Dict], context_size: int = 4096) -> List[Dict]:
        """Bound the live agent loop context before each Ollama call.

        Tool loops repeat the entire prompt every iteration. Without a hard
        projection step, one read_file result can make the next turn eat the
        user's whole context slider. Keep the system prompt and newest evidence,
        but trim old assistant/tool chatter aggressively.
        """
        if not messages:
            return messages

        max_chars = max(6000, min(22000, int(context_size) * 3))
        system = messages[0]
        tail = messages[1:]
        kept: List[Dict] = []
        total = len(str(system.get("content", "")))

        for msg in reversed(tail):
            compact_msg = dict(msg)
            role = compact_msg.get("role", "user")
            content = str(compact_msg.get("content", "") or "")

            if role == "tool" and len(content) > 3500:
                content = content[:3500] + "\n... (tool result truncated for context)"
            elif role == "assistant" and len(content) > 1600:
                content = content[:1600] + "\n... (assistant text truncated for context)"
            elif role == "user" and len(content) > 3500:
                suffix = "older user text truncated for context" if kept else "user text truncated for context"
                content = content[:3500] + f"\n... ({suffix})"

            compact_msg["content"] = content
            msg_len = len(content)
            if kept and total + msg_len > max_chars:
                break
            kept.append(compact_msg)
            total += msg_len

        kept.reverse()
        return [system] + kept

    def _is_repo_overview_request(self, message: str) -> bool:
        """Detect broad repo audits that should not rely on free-form tool loops.

        Small local models often get stuck repeating ``ls``/``glob`` on vague
        requests such as "analyse mon repo". For those cases JoyBoy does a
        deterministic, bounded preflight scan, then asks the model to summarize
        without tools. Precise requests still use the normal agentic loop.
        """
        msg = (message or "").lower()
        overview_words = ("analyse", "audit", "regarde", "explore", "inspecte", "comprendre")
        repo_words = ("repo", "projet", "codebase", "workspace", "dossier")
        write_words = ("corrige", "fix", "modifie", "ajoute", "supprime", "implémente", "implemente")
        return (
            any(word in msg for word in overview_words)
            and any(word in msg for word in repo_words)
            and not any(word in msg for word in write_words)
        )

    def _is_open_workspace_request(self, message: str) -> bool:
        msg = (message or "").lower()
        open_words = ("ouvre", "ouvrir", "open", "affiche", "montre")
        folder_words = ("dossier", "folder", "workspace", "projet", "répertoire", "repertoire")
        return any(word in msg for word in open_words) and any(word in msg for word in folder_words)

    def _build_repo_brief(self, workspace_path: str) -> tuple[str, List[Dict]]:
        """Build a bounded repo brief and emit normal tool events for the UI."""
        from core.workspace_tools import get_workspace_summary, list_files, read_file

        events: List[Dict] = []
        lines: List[str] = []

        events.append({'type': 'tool_call', 'name': 'list_files', 'args': {'path': '.'}})
        root_listing = list_files(workspace_path, '.', max_files=80)
        events.append({'type': 'tool_result', 'result': {
            'success': root_listing.get('success', False),
            'tool_name': 'list_files',
            'data': root_listing,
            'error': root_listing.get('error'),
            'write_blocked': False,
        }})

        summary = get_workspace_summary(workspace_path)
        if summary.get("success"):
            lines.append(f"Project: {summary.get('name')} ({summary.get('total_files', 0)} files)")
            root_dirs = ", ".join(summary.get("root_dirs", [])[:12]) or "none"
            root_files = ", ".join(summary.get("root_files", [])[:12]) or "none"
            top_ext = ", ".join(f"{ext}:{count}" for ext, count in summary.get("top_extensions", [])[:8])
            lines.append(f"Root directories: {root_dirs}")
            lines.append(f"Important root files: {root_files}")
            lines.append(f"Main extensions: {top_ext or 'unknown'}")

        if root_listing.get("success"):
            items = root_listing.get("items", [])
            readable_root_files = [
                item.get("name")
                for item in items
                if item.get("type") == "file" and item.get("readable")
            ]
            root_dirs = [item.get("name") for item in items if item.get("type") == "dir"]
            if readable_root_files:
                lines.append("Readable root files: " + ", ".join(readable_root_files[:18]))
            if root_dirs:
                lines.append("Visible root directories: " + ", ".join(root_dirs[:18]))

        preferred = [
            "README.md", "readme.md", "pyproject.toml", "package.json",
            "requirements.txt", "web/app.py", "app.py", "core/__init__.py",
            "core/models/manager.py", "core/backends/terminal_brain.py",
        ]
        read_count = 0
        for path in preferred:
            if read_count >= 5:
                break
            result = read_file(workspace_path, path, max_lines=120)
            if not result.get("success"):
                continue
            read_count += 1
            events.append({'type': 'tool_call', 'name': 'read_file', 'args': {'path': path, 'max_lines': 120}})
            events.append({'type': 'tool_result', 'result': {
                'success': True,
                'tool_name': 'read_file',
                'data': result,
                'error': None,
                'write_blocked': False,
            }})
            content = result.get("content", "")
            excerpt = content[:1800]
            if len(content) > len(excerpt):
                excerpt += "\n... (excerpt truncated)"
            lines.append(f"\n--- {path} ({result.get('lines', 0)} lines) ---\n{excerpt}")

        if not lines:
            lines.append("Could not build repository context: workspace is empty or unreadable.")

        return "\n".join(lines), events

    def _empty_model_fallback_answer(
        self,
        initial_message: str,
        repo_brief: Optional[str],
        executed_tools: List[Dict],
    ) -> str:
        """Visible fallback when a local model returns no assistant content.

        This happens especially with small reasoning models when ``think`` is
        ignored or when the model burns the budget without emitting final text.
        The UI should never be left with only ``List(.)`` and no answer.
        """
        if repo_brief:
            useful_lines = [
                line.strip()
                for line in repo_brief.splitlines()
                if line.strip() and not line.startswith("---")
            ][:18]
            summary = "\n".join(f"- {line}" for line in useful_lines[:10])
            next_files = [
                line.replace("---", "").strip()
                for line in repo_brief.splitlines()
                if line.startswith("---")
            ][:5]
            next_text = "\n".join(f"- {path}" for path in next_files) if next_files else "- README / fichiers de config"
            return (
                "J'ai bien lancé l'analyse du workspace, mais le modèle local n'a pas renvoyé "
                "de texte exploitable à la fin. Je te laisse quand même le résumé déterministe "
                "de ce que JoyBoy a déjà scanné:\n\n"
                f"{summary or '- Workspace lisible, mais résumé vide.'}\n\n"
                "Prochaine étape utile:\n"
                f"{next_text}\n\n"
                "Si tu me redemandes une analyse ciblée, je partirai directement de ces fichiers "
                "au lieu de boucler sur la racine."
            )

        if executed_tools:
            tool_lines = []
            for tool in executed_tools[-6:]:
                name = tool.get("tool", tool.get("name", "outil"))
                target = tool.get("target") or tool.get("path") or tool.get("command") or ""
                ok = "OK" if tool.get("success", False) else "erreur"
                tool_lines.append(f"- {name} {target} ({ok})".strip())
            return (
                "Le modèle local n'a pas produit de réponse finale, mais voici les actions déjà faites:\n\n"
                + "\n".join(tool_lines)
                + "\n\nJe peux continuer avec une demande plus précise ou relancer une synthèse."
            )

        return (
            "Le modèle local n'a pas renvoyé de réponse exploitable. "
            "Je n'ai donc rien à afficher de fiable pour cette demande. "
            "Relance avec une demande plus ciblée ou choisis un modèle terminal plus costaud."
        )

    def _tool_signature(self, tool_name: str, args: Dict) -> str:
        try:
            clean_args = json.dumps(args or {}, sort_keys=True, ensure_ascii=False)
        except TypeError:
            clean_args = str(args)
        return f"{tool_name}:{clean_args}"

    def _tool_guard_reason(
        self,
        tool_name: str,
        args: Dict,
        seen_count: int,
        executed_tools: List[Dict],
    ) -> Optional[str]:
        """Return a reason when a tool call is clearly no-progress noise."""
        if seen_count >= 3:
            return f"repeated call {seen_count} times: {tool_name}({args})"

        path = str((args or {}).get("path", "")).strip()
        pattern = str((args or {}).get("pattern", "")).strip()
        command = str((args or {}).get("command", "")).strip().lower()

        if tool_name == "read_file" and path in {"", ".", "./"}:
            return "read_file must target a file, not the workspace root"

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

        return None

    def _summarize_executed_tool(self, tool_name: str, args: Dict, result: ToolResult) -> Dict:
        summary = {"tool": tool_name, "args": args or {}, "success": result.success}
        if result.error:
            summary["summary"] = result.error[:220]
            return summary

        data = result.data or {}
        if tool_name == "list_files":
            summary["summary"] = f"{len(data.get('items', []))} item(s)"
        elif tool_name == "read_file":
            summary["summary"] = f"{data.get('path', args.get('path', ''))} ({data.get('lines', 0)} lines)"
        elif tool_name == "glob":
            summary["summary"] = f"{len(data.get('files', []))} file(s)"
        elif tool_name == "search":
            summary["summary"] = f"{len(data.get('results', []))} result(s)"
        elif tool_name == "bash":
            summary["summary"] = f"code {data.get('return_code', '?')}"
        elif tool_name == "open_workspace":
            summary["summary"] = data.get("path", "workspace opened")
        else:
            summary["summary"] = "ok"
        return summary

    def _has_successful_mutation(self, executed_tools: List[Dict]) -> bool:
        for item in executed_tools:
            if not item.get("success"):
                continue
            tool = item.get("tool")
            if tool in {"write_file", "edit_file", "delete_file"}:
                return True
            if tool == "bash":
                command = str((item.get("args") or {}).get("command", "")).lower()
                mutation_markers = (
                    "npm create", "npx create", "create-vite", "mkdir", "touch",
                    "copy ", "cp ", "move ", "mv ", "git init", "pnpm create",
                    "yarn create", "npm install", "pnpm install", "yarn install",
                )
                if any(marker in command for marker in mutation_markers):
                    return True
        return False

    def _looks_like_unverified_write_claim(self, content: str, executed_tools: List[Dict]) -> bool:
        if self.is_read_only_intent(self.current_intent) or self._has_successful_mutation(executed_tools):
            return False

        text = (content or "").lower()
        if not text:
            return False

        claim_markers = (
            "j'ai créé", "j ai créé", "j'ai cree", "j ai cree", "j'ai ajouté",
            "j ai ajoute", "j'ai modifié", "j ai modifie", "j'ai corrigé",
            "j ai corrige", "c'est fait", "terminé", "j'ai mis en place",
            "i created", "i've created", "i have created", "i added",
            "i updated", "i modified", "i implemented", "i fixed",
            "created the", "added the", "updated the", "implemented the",
            "the file has been", "template has been", "project has been created",
        )
        return any(marker in text for marker in claim_markers)

    def _verify_file_write(self, workspace_path: str, relative_path: str) -> Dict:
        try:
            from core.workspace_tools import _resolve_workspace_path

            full_path = _resolve_workspace_path(workspace_path, relative_path)
            if not full_path or not os.path.isfile(full_path):
                return {"verified": False, "error": f"File not found after write: {relative_path}"}
            size = os.path.getsize(full_path)
            return {"verified": True, "path": relative_path, "size": size}
        except Exception as exc:
            return {"verified": False, "error": str(exc)}

    def _verify_file_deleted(self, workspace_path: str, relative_path: str) -> Dict:
        try:
            from core.workspace_tools import _resolve_workspace_path

            full_path = _resolve_workspace_path(workspace_path, relative_path)
            if full_path and os.path.exists(full_path):
                return {"verified": False, "error": f"File still exists after deletion: {relative_path}"}
            return {"verified": True, "path": relative_path}
        except Exception as exc:
            return {"verified": False, "error": str(exc)}

    def _resolve_for_snapshot(self, workspace_path: str, relative_path: str) -> Optional[str]:
        try:
            from core.workspace_tools import _resolve_workspace_path

            return _resolve_workspace_path(workspace_path, relative_path)
        except Exception:
            return None

    def _guardrail_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        observed = executed_tools[-8:]
        if not observed:
            return (
                "J'ai stoppé le terminal avant qu'il parte en boucle. "
                "Aucun outil utile n'a encore produit de contexte; choisis un workspace puis demande "
                "par exemple: `analyse la structure`, `lis README.md`, ou `cherche les routes Flask`."
            )
        bullet_lines = [
            f"- {item.get('tool')} {item.get('args', {})}: {item.get('summary', '')}"
            for item in observed
        ]
        return (
            "J'ai stoppé la boucle d'outils avant de gaspiller plus de tokens.\n\n"
            "Dernières observations utiles:\n"
            + "\n".join(bullet_lines)
            + "\n\nDemande-moi une cible plus précise, ou relance `analyse mon repo` maintenant: "
            "JoyBoy utilisera le scan borné au lieu de refaire `ls/glob/pwd` en boucle."
        )

    def build_system_prompt(
        self,
        workspace_path: str,
        workspace_name: Optional[str] = None,
        force_response_language: Optional[str] = None,
    ) -> str:
        """Build the terminal agent prompt in English.

        Local coding models are usually more reliable when the operational
        contract is written in English, even when the final answer is in the
        user's language. Keep UI translations elsewhere; this prompt is for the
        tool-using model.
        """
        project_name = workspace_name or os.path.basename(os.path.abspath(workspace_path or "")) or "workspace"
        language_rule = (
            f"Final answer language: {force_response_language}.\n"
            if force_response_language
            else "Final answer language: match the user's language.\n"
        )
        return f"""You are JoyBoy Terminal, an expert coding agent working inside a local project folder.

Workspace name: {project_name}
Workspace path: {workspace_path}
{language_rule}
Core contract:
1. Use tools for real work. Do not pretend that files were created, edited, installed, or tested.
2. Always call read_file before editing or replacing an existing file.
3. Prefer edit_file for targeted changes. Use write_file only for new files or intentional full rewrites.
4. Never call read_file on "." or on a directory. read_file is only for specific files.
5. Do one meaningful step at a time, then verify the result before claiming success.
6. Do not loop on list_files, glob, ls, dir, or pwd. One root exploration is enough; then read specific files.
7. If a shell scaffold command succeeds, verify the expected folder and package.json before saying it exists.
8. If a command or edit fails, inspect the error, adjust once or twice, then explain the blocker.
9. Keep context lean: read focused file chunks, summarize large outputs, and avoid dumping entire files.
10. For final code snippets, use fenced Markdown blocks with a language tag.

Safe workflow for analysis:
1. list_files once if needed.
2. read 2 to 5 relevant files.
3. answer with concrete findings from observed files.

Safe workflow for modifications:
1. read_file the target file.
2. edit_file or write_file.
3. verify with read_file, list_files, or command output.
4. only then summarize what changed.

Safe workflow for project scaffolding:
1. run the scaffold command inside the workspace.
2. verify the generated folder and package.json.
3. read the key generated files before describing them.

You have access to filesystem, search, shell, and workspace tools. Use them to complete the user's task."""

    def _get_default_system_prompt(self, workspace_path: str) -> str:
        """Default Claude-Code-style terminal system prompt."""
        return self.build_system_prompt(workspace_path)

    def _format_result_for_llm(self, result: ToolResult) -> str:
        """Formate le résultat d'un tool pour le LLM"""
        if not result.success:
            if result.tool_name == 'bash' and result.data:
                data = result.data
                output = data.get('output', '')
                verification = data.get('verification')
                if verification:
                    output += (
                        f"\n[VERIFICATION]\n"
                        f"{verification.get('kind', 'artifact')}: FAILED - "
                        f"{verification.get('path', '')}"
                    )
                    if verification.get('package_json') is not None:
                        output += f" (package.json: {'yes' if verification.get('package_json') else 'no'})"
                return f"[ERROR bash] {result.error or 'Command failed'}\n```\n{output}\n```"
            return f"[ERROR {result.tool_name}] {result.error}"

        data = result.data

        if result.tool_name == 'list_files':
            items = data.get('items', [])
            listing = '\n'.join([
                f"{'[DIR]' if i.get('type') == 'dir' else '[FILE]'} {i.get('name')}"
                for i in items[:50]
            ])
            return f"[RESULT list_files]\n{listing}"

        elif result.tool_name == 'read_file':
            content = data.get('content', '')
            lines = data.get('lines', 0)
            # Tronquer si trop long
            max_chars = max(2500, min(6500, int(self._active_context_size * 1.2)))
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated to preserve context)"
            return f"[RESULT read_file] ({lines} lines)\n```\n{content}\n```"

        elif result.tool_name == 'write_file':
            verified = " verified" if data.get('verified') else ""
            size = f", {data.get('size')} bytes" if data.get('size') is not None else ""
            return f"[RESULT write_file] OK{verified} - File {'created' if data.get('created') else 'modified'}: {data.get('path', '')}{size}"

        elif result.tool_name == 'edit_file':
            verified = " verified" if data.get('verified') else ""
            size = f", {data.get('size')} bytes" if data.get('size') is not None else ""
            return f"[RESULT edit_file] OK{verified} - {data.get('replacements', 0)} replacement(s): {data.get('path', '')}{size}"

        elif result.tool_name == 'delete_file':
            verified = " verified" if data.get('verified') else ""
            return f"[RESULT delete_file] OK{verified} - Deleted: {data.get('path', '')}"

        elif result.tool_name == 'search':
            results = data.get('results', [])
            matches = '\n'.join([
                f"{r.get('file')}:{r.get('line')}: {r.get('content', '')[:80]}"
                for r in results[:20]
            ])
            return f"[RESULT search]\n{matches or 'No results'}"

        elif result.tool_name == 'glob':
            files = data.get('files', [])
            return f"[RESULT glob]\n" + '\n'.join(files[:30])

        elif result.tool_name == 'bash':
            output = data.get('output', '')
            code = data.get('return_code', -1)
            status = 'OK' if code == 0 else 'ERROR'
            verification = data.get('verification')
            if verification:
                verified_label = "OK" if verification.get('verified') else "FAILED"
                output += (
                    f"\n[VERIFICATION]\n"
                    f"{verification.get('kind', 'artifact')}: {verified_label} - "
                    f"{verification.get('path', '')}"
                )
                if verification.get('package_json') is not None:
                    output += f" (package.json: {'yes' if verification.get('package_json') else 'no'})"
            return f"[RESULT bash] {status} (code: {code})\n```\n{output}\n```"

        elif result.tool_name == 'web_search':
            items = data.get('results', [])
            if not items:
                return "[RESULT web_search] No results"
            results_text = '\n'.join([
                f"{i+1}. {item.get('title', 'Untitled')}\n   {item.get('url', '')}\n   {item.get('snippet', '')[:150]}"
                for i, item in enumerate(items[:5])
            ])
            return f"[RESULT web_search]\n{results_text}"

        elif result.tool_name == 'think':
            return f"[THOUGHT] {data.get('thought', '')} - Continue with the appropriate concrete action."

        elif result.tool_name == 'open_workspace':
            return f"[RESULT open_workspace] Folder opened: {data.get('path', '')}"

        return f"[RESULT {result.tool_name}] OK"

    def _open_workspace_folder(self, workspace_path: str) -> Dict:
        """Open the current workspace in the OS file explorer."""
        import platform
        import subprocess

        path = os.path.abspath(workspace_path or "")
        if not os.path.isdir(path):
            return {"success": False, "error": "Invalid or missing workspace", "path": path}

        try:
            system = platform.system().lower()
            if system == "windows":
                os.startfile(path)  # type: ignore[attr-defined]
            elif system == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return {"success": True, "path": path}
        except Exception as exc:
            return {"success": False, "error": str(exc), "path": path}

    def _create_snapshot(self, full_path: str, relative_path: str):
        """Crée un snapshot pour rollback"""
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.snapshots[relative_path] = FileSnapshot(path=relative_path, content=content)
            print(f"[BRAIN] Snapshot: {relative_path}")
        except Exception as e:
            print(f"[BRAIN] Erreur snapshot: {e}")

    def _validate_write(self, full_path: str, new_content: str) -> tuple:
        """Valide une écriture pour éviter les écrasements"""
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                original = f.read()

            if len(original) > 100 and len(new_content) < 10:
                return False, "BLOCKED: near-empty replacement content. Use edit_file for targeted edits."

            if len(original) > 500:
                ratio = len(new_content) / len(original)
                if ratio < 0.1:
                    return False, f"BLOCKED: this would drop {int((1-ratio)*100)}% of the file content. Read the file first and use edit_file."
        except Exception:
            pass

        return True, None

    def _log_action(self, action: str, path: str, success: bool):
        """Log une action"""
        self.action_history.append({
            'action': action,
            'path': path,
            'success': success,
            'timestamp': datetime.now().isoformat()
        })

    def _verify_bash_side_effects(self, command: str, workspace_path: str, parts: Optional[List[str]] = None) -> Optional[Dict]:
        """Verify common filesystem side effects so the agent cannot claim fake scaffolds."""
        import shlex

        try:
            tokens = parts or shlex.split(command)
        except Exception:
            tokens = command.split()

        if not tokens:
            return None

        main_cmd = tokens[0].lower()
        operators = {'&&', '||', ';', '|'}

        def clean_targets(raw_tokens: List[str]) -> List[str]:
            targets = []
            skip_next = False
            for token in raw_tokens:
                if skip_next:
                    skip_next = False
                    continue
                if token in operators:
                    break
                if token in {'--template', '-t', '--variant'}:
                    skip_next = True
                    continue
                if token == '--' or token.startswith('-'):
                    continue
                targets.append(token)
            return targets

        def artifact_status(kind: str, rel_path: str, require_package_json: bool = False) -> Dict:
            display_path = rel_path or '.'
            full_path = os.path.abspath(workspace_path) if display_path == '.' else self._resolve_for_snapshot(workspace_path, display_path)
            exists = bool(full_path and os.path.exists(full_path))
            package_json = bool(full_path and os.path.isfile(os.path.join(full_path, 'package.json')))
            verified = exists and (package_json if require_package_json else True)
            result = {
                'kind': kind,
                'path': display_path.replace('\\', '/'),
                'exists': exists,
                'verified': verified,
            }
            if require_package_json:
                result['package_json'] = package_json
            return result

        if main_cmd == 'mkdir':
            targets = clean_targets(tokens[1:])
            if targets:
                checks = [artifact_status('mkdir', target) for target in targets]
                return {
                    'kind': 'mkdir',
                    'path': ', '.join(check['path'] for check in checks),
                    'verified': all(check['verified'] for check in checks),
                    'items': checks,
                }

        if main_cmd == 'touch':
            targets = clean_targets(tokens[1:])
            if targets:
                checks = [artifact_status('touch', target) for target in targets]
                return {
                    'kind': 'touch',
                    'path': ', '.join(check['path'] for check in checks),
                    'verified': all(check['verified'] for check in checks),
                    'items': checks,
                }

        scaffold = self._detect_scaffold_target(tokens)
        if scaffold is not None:
            kind, target = scaffold
            return artifact_status(kind, target, require_package_json=True)

        return None

    def _detect_vite_target(self, tokens: List[str]) -> Optional[str]:
        scaffold = self._detect_scaffold_target(tokens)
        if not scaffold or scaffold[0] != 'vite_scaffold':
            return None
        return scaffold[1]

    def _detect_scaffold_target(self, tokens: List[str]) -> Optional[tuple[str, str]]:
        if not tokens:
            return None

        lowered = [token.lower() for token in tokens]
        start = None
        kind = None
        if len(tokens) >= 3 and lowered[0] == 'npm' and lowered[1] in {'create', 'init'} and 'vite' in lowered[2]:
            start = 3
            kind = 'vite_scaffold'
        elif len(tokens) >= 2 and lowered[0] == 'npx' and 'create-vite' in lowered[1]:
            start = 2
            kind = 'vite_scaffold'
        elif len(tokens) >= 3 and lowered[0] in {'pnpm', 'yarn'} and lowered[1] == 'create' and 'vite' in lowered[2]:
            start = 3
            kind = 'vite_scaffold'
        elif len(tokens) >= 2 and lowered[0] == 'npx' and lowered[1].startswith('create-react-app'):
            start = 2
            kind = 'react_app_scaffold'
        elif len(tokens) >= 3 and lowered[0] == 'npm' and lowered[1] in {'create', 'init'} and lowered[2].startswith('react-app'):
            start = 3
            kind = 'react_app_scaffold'
        elif len(tokens) >= 2 and lowered[0] == 'npx' and lowered[1].startswith('create-next-app'):
            start = 2
            kind = 'next_app_scaffold'
        elif len(tokens) >= 3 and lowered[0] in {'npm', 'pnpm', 'yarn'} and lowered[1] in {'create', 'init'} and lowered[2].startswith('next-app'):
            start = 3
            kind = 'next_app_scaffold'

        if start is None:
            return None

        skip_next = False
        for token in tokens[start:]:
            lower = token.lower()
            if skip_next:
                skip_next = False
                continue
            if token in {'&&', '||', ';', '|'}:
                break
            if lower in {'--template', '-t', '--variant'}:
                skip_next = True
                continue
            if token == '--' or token.startswith('-'):
                continue
            return (kind or 'scaffold', token)

        return (kind or 'scaffold', '.')

    def _execute_bash(self, command: str, workspace_path: str) -> Dict:
        """Exécute une commande bash de manière sécurisée"""
        import subprocess
        import shlex

        # Commandes dangereuses
        DANGEROUS = ['rm -rf /', 'rm -rf ~', 'sudo ', 'format ', 'mkfs', ':(){:|:&};:']
        for pattern in DANGEROUS:
            if pattern in command.lower():
                return {"success": False, "error": f"Dangerous command blocked: {pattern}"}

        # Whitelist
        ALLOWED = [
            'npm', 'node', 'npx', 'yarn', 'pnpm',
            'python', 'python3', 'pip', 'pip3',
            'git', 'gh',
            'ls', 'pwd', 'cat', 'head', 'tail', 'wc',
            'grep', 'find', 'which', 'echo', 'date',
            'mkdir', 'touch', 'cp', 'mv', 'rm', 'rmdir', 'rd',
            'cargo', 'go', 'make',
            'pytest', 'jest', 'vitest',
            'eslint', 'prettier', 'tsc',
        ]

        try:
            parts = shlex.split(command)
            main_cmd = parts[0] if parts else ""
        except Exception:
            main_cmd = command.split()[0] if command.split() else ""

        if not any(main_cmd.startswith(cmd) or main_cmd == cmd for cmd in ALLOWED):
            return {"success": False, "error": f"Command is not allowed: {main_cmd}"}

        try:
            result = subprocess.run(
                command, shell=True, cwd=workspace_path,
                capture_output=True, text=True, timeout=60
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[STDERR]\n{result.stderr}"

            if len(output) > 8000:
                output = output[:8000] + "\n... (tronqué)"

            response = {
                "success": result.returncode == 0,
                "output": output,
                "return_code": result.returncode,
                "error": result.stderr if result.returncode != 0 else None
            }
            verification = self._verify_bash_side_effects(command, workspace_path, parts)
            if verification:
                response["verification"] = verification
                if result.returncode == 0 and not verification.get("verified"):
                    response["success"] = False
                    response["error"] = (
                        f"Command completed but the expected artifact was not found: "
                        f"{verification.get('path', '')}"
                    )
            return response

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout (60s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_web_search(self, query: str) -> Dict:
        """Recherche web"""
        try:
            from core.web_search import web_search
            return web_search(query, num_results=8)
        except ImportError:
            return {"success": False, "error": "web_search module is unavailable"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ===== INTENT DETECTION =====

    @staticmethod
    def detect_intent(message: str) -> str:
        """Détecte l'intention: 'read', 'write', 'execute', 'question'"""
        msg = message.lower()

        # WRITE
        write_kw = ['modifie', 'modifier', 'change', 'ajoute', 'supprime', 'crée', 'créer',
                    'écris', 'fix', 'corrige', 'refactor', 'implémente', 'update']
        if any(kw in msg for kw in write_kw):
            return 'write'

        # EXECUTE
        exec_kw = ['lance', 'run', 'execute', 'npm ', 'python ', 'pip ', 'test', 'build', 'git ']
        if any(kw in msg for kw in exec_kw):
            return 'execute'

        # READ
        read_kw = ['analyse', 'explique', 'montre', 'lis', 'regarde', 'c\'est quoi', 'comprendre']
        if any(kw in msg for kw in read_kw):
            return 'read'

        return 'question'

    @staticmethod
    def is_read_only_intent(intent: str) -> bool:
        return intent in ['read', 'question']

    # ===== SNAPSHOT & ROLLBACK =====

    def get_snapshot(self, path: str) -> Optional[FileSnapshot]:
        return self.snapshots.get(path)

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
