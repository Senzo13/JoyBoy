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
import platform
import re
import unicodedata
from collections import defaultdict
from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from config import TOOL_CAPABLE_MODELS, TOOL_EXCLUDED_MODELS
from core.agent_runtime import (
    CloudModelError,
    ToolLoopGuard,
    chat_with_cloud_model,
    is_cloud_model_name,
    mask_workspace_paths,
    runtime_event,
    tool_guard_reason,
    tool_signature,
    truncate_middle,
)
from core.backends.terminal_tools import (
    DEFAULT_PERMISSION_MODE,
    PermissionEngine,
    build_default_terminal_tool_registry,
    normalize_permission_mode,
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
            "name": "write_files",
            "description": "Create or fully replace multiple files in one backend-verified batch. Prefer this for scaffolds, templates, and multi-file creation instead of one write_file call per file. Existing files are blocked unless overwrite_existing is true and each file was read first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "description": "Files to write. Keep batches focused, usually 2-12 files.",
                        "items": {
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
                    },
                    "overwrite_existing": {
                        "type": "boolean",
                        "description": "Allow replacing existing files only after read_file has been called for each one. Default: false."
                    }
                },
                "required": ["files"]
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
            "name": "write_todos",
            "description": "Create or update the active task list for complex, multi-step work. Keep it short and update statuses as work progresses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "Ordered task list. Use 2 to 6 items.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Stable short id such as '1' or 'audit-runtime'."
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Concrete task description."
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed", "blocked"],
                                    "description": "Current task status."
                                },
                                "note": {
                                    "type": "string",
                                    "description": "Optional short result or blocker note."
                                }
                            },
                            "required": ["content", "status"]
                        }
                    }
                },
                "required": ["todos"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": "Fetch full schema definitions for deferred terminal tools. Use this only when a hidden tool is needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Tool name or keywords. Supports select:name1,name2 for exact tool names."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web or internet through the configured local search provider.",
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
            "name": "web_fetch",
            "description": "Fetch readable text from an exact public URL returned by web_search or provided by the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Exact http(s) URL to fetch."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_subagent",
            "description": "Run a backend-managed subagent for code exploration or controlled verification. Use code_explorer for broad analysis and verifier for tests/build checks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Concrete exploration task for the subagent."
                    },
                    "agent_type": {
                        "type": "string",
                        "enum": ["code_explorer", "verifier"],
                        "description": "Subagent type. code_explorer is read-only; verifier runs one allowlisted test/build command."
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum relevant files to return. Default: 8, max: 16."
                    },
                    "command": {
                        "type": "string",
                        "description": "Verifier command, for example 'python -m unittest discover -s tests' or 'npm test'. Required for verifier."
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Verifier timeout in seconds. Default: 90, max: 180."
                    }
                },
                "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "Load an active local pack SKILL.md workflow by skill_id when it is relevant to the user's task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "Skill id from the local pack skills list, for example 'my-pack:code-review'."
                    }
                },
                "required": ["skill_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Persist a stable local memory fact outside git. Use only when the user explicitly asks to remember something or when a durable project preference is clearly useful.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact to remember. Do not store secrets or one-off transient details."
                    },
                    "category": {
                        "type": "string",
                        "description": "Short category such as preference, project, workflow, or context."
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence from 0 to 1. Default 0.6."
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_memory",
            "description": "Retrieve relevant local memory facts for the terminal agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional keywords to search in memory."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum facts to return, default 8."
                    }
                },
                "required": []
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


DEFERRED_TOOL_NAMES = (
    "write_todos",
    "web_search",
    "web_fetch",
    "delegate_subagent",
    "load_skill",
    "remember_fact",
    "list_memory",
    "delete_file",
    "open_workspace",
    "think",
)
DEFERRED_TOOL_MAX_RESULTS = 5
MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE = 3
CORE_TOOL_NAMES = tuple(
    item.get("function", {}).get("name", "")
    for item in TOOLS
    if item.get("function", {}).get("name", "")
    and item.get("function", {}).get("name", "") not in DEFERRED_TOOL_NAMES
    and item.get("function", {}).get("name", "") != "tool_search"
)
WRITE_CORE_TOOL_NAMES = ("write_files", "write_file", "edit_file", "delete_file", "bash")
SCAFFOLD_CORE_TOOL_ORDER = (
    "list_files",
    "read_file",
    "write_files",
    "write_file",
    "edit_file",
    "bash",
    "search",
    "glob",
)
READ_CORE_TOOL_ORDER = ("list_files", "read_file", "search", "glob")


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

    MIN_CONTEXT_SIZE = 2048
    MAX_LOCAL_CONTEXT_SIZE = 262144
    DEFAULT_CLOUD_CONTEXT_SIZE = 262144
    MAX_CLOUD_CONTEXT_SIZE = 1_000_000

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
        self.current_plan: Optional[ExecutionPlan] = None
        self._read_files_by_workspace = defaultdict(dict)

        # Protection écriture
        self.current_intent: str = 'question'
        self.write_blocked: bool = False
        self.permission_mode: str = DEFAULT_PERMISSION_MODE

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
        write_tools = ['write_file', 'write_files', 'edit_file', 'delete_file']
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
                result = self._delegate_subagent(
                    args.get('agent_type', 'code_explorer'),
                    args.get('task', ''),
                    workspace_path,
                    max_files=args.get('max_files', 8),
                    command=args.get('command', ''),
                    timeout_seconds=args.get('timeout_seconds', 90),
                )
                return ToolResult(success=result.get('status') == 'completed', tool_name=tool_name, data=result, error=result.get('error'))

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

        self._active_context_size = self._normalize_context_size(context_size, cloud=use_cloud_model, model=model)
        self._active_workspace_path = workspace_path
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
        self._reset_deferred_tools()
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
                    "Answer now in the user's language with a concrete synthesis. "
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

        while iteration < iteration_budget:
            iteration += 1
            yield runtime_event('thinking', iteration=iteration, max_iterations=iteration_budget)

            try:
                # Appel Ollama avec tools
                tool_names_for_turn = self._select_tool_names_for_turn(
                    initial_message,
                    executed_tools=executed_tools,
                    autonomous=autonomous,
                )
                tools_for_model = [] if force_final else self.tool_registry.ollama_tools(tool_names_for_turn)
                messages = self._compact_loop_messages(messages, context_size=self._active_context_size)
                messages = self._inject_todo_reminder(messages)
                messages = self._patch_dangling_tool_messages(messages)

                if not autonomous and not force_final and iteration > 1:
                    estimated_prompt_tokens = self._estimate_prompt_tokens(messages, tools_for_model)
                    remaining_budget = turn_token_budget - total_token_stats['total']
                    if remaining_budget <= 0 or estimated_prompt_tokens >= max(900, remaining_budget):
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
                    print(f"[BRAIN] Calling cloud model={model}, tools={len(tools_for_model)} tools")
                    response = chat_with_cloud_model(
                        model,
                        messages=messages,
                        tools=tools_for_model,
                        max_tokens=response_token_limit,
                        temperature=0.2,
                        reasoning_effort=reasoning_effort,
                    )
                else:
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
                        normalised_tool_calls = []
                        for index, tc in enumerate(tool_calls):
                            call = {
                                'type': 'function',
                                'function': {'name': tc.function.name, 'arguments': tc.function.arguments},
                            }
                            tool_call_id = getattr(tc, "id", None)
                            if tool_call_id:
                                call['id'] = tool_call_id
                            elif use_cloud_model:
                                call['id'] = f"call_{index}"
                            normalised_tool_calls.append(call)
                        message_dict['tool_calls'] = normalised_tool_calls
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
                if isinstance(response, dict):
                    token_stats['prompt_tokens'] = int(response.get('prompt_eval_count') or 0)
                    token_stats['completion_tokens'] = int(response.get('eval_count') or 0)
                token_stats['total'] = token_stats.get('prompt_tokens', 0) + token_stats.get('completion_tokens', 0)
                token_stats['context_size'] = self._active_context_size

                # Accumuler les stats de tokens
                total_token_stats['prompt_tokens'] += token_stats.get('prompt_tokens', 0)
                total_token_stats['completion_tokens'] += token_stats.get('completion_tokens', 0)
                total_token_stats['total'] += token_stats.get('total', 0)
                total_token_stats['context_size'] = self._active_context_size

                print(f"[BRAIN] Content: {content[:100] if content else 'None'}...")
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

                over_budget = (
                    not autonomous
                    and total_token_stats['total'] >= turn_token_budget
                    and not force_final
                )

                # Si du texte, l'envoyer avec les stats
                if content:
                    full_response += content
                    yield runtime_event('content', text=content, token_stats=token_stats)

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

                    print(f"[BRAIN] Executing tool: {tool_name}({args})")

                    guard_reason = loop_guard.check(tool_name, args, executed_tools)
                    if guard_reason and not autonomous:
                        guard_hits += 1
                        force_final = True
                        yield runtime_event('loop_warning', action=tool_name, reason=guard_reason)
                        guard_text = (
                            f"[TERMINAL GUARDRAIL] {guard_reason}. "
                            "Stop repetitive tools and produce the final synthesis now."
                        )
                        guard_message = {"role": "tool", "tool_name": tool_name, "content": guard_text}
                        if tool_call_id:
                            guard_message["tool_call_id"] = tool_call_id
                        messages.append(guard_message)
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
                    result = self.execute_tool(tool_name, args, workspace_path)
                    executed_tools.append(self._summarize_executed_tool(tool_name, args, result))

                    yield runtime_event('tool_result', result={
                        'success': result.success,
                        'tool_name': result.tool_name,
                        'data': result.data,
                        'error': result.error,
                        'write_blocked': self.write_blocked
                    })

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
                yield runtime_event('error', message=str(e))
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

    def _default_cloud_context_size(self, model: str | None = None) -> int:
        model_id = str(model or "").strip().lower()
        if model_id == "openai:gpt-5.4":
            return 1_000_000
        if model_id.startswith("openai:gpt-5"):
            return 400_000
        if model_id.startswith("gemini:"):
            return 1_000_000
        return self.DEFAULT_CLOUD_CONTEXT_SIZE

    def _normalize_context_size(self, context_size: int | str | None, cloud: bool = False, model: str | None = None) -> int:
        try:
            value = int(context_size or 4096)
        except Exception:
            value = 4096
        if cloud:
            value = max(value, self._default_cloud_context_size(model))
            return max(self.MIN_CONTEXT_SIZE, min(self.MAX_CLOUD_CONTEXT_SIZE, value))
        return max(self.MIN_CONTEXT_SIZE, min(self.MAX_LOCAL_CONTEXT_SIZE, value))

    def _turn_token_budget(self, context_size: int, autonomous: bool = False, cloud: bool = False) -> int:
        if cloud:
            if autonomous:
                return max(32000, min(180000, int(context_size * 0.75)))
            return max(26000, min(90000, int(context_size * 0.5)))
        if autonomous:
            return max(6500, min(self.MAX_LOCAL_CONTEXT_SIZE, int(context_size * 0.75)))
        if context_size <= 32768:
            return max(2500, min(self.max_non_autonomous_tokens, int(context_size * 0.9)))
        if context_size <= 65536:
            return 12000
        if context_size <= 131072:
            return 18000
        return 26000

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
        omitted = max(0, len([msg for msg in history if str(msg.get("content", "")).strip()]) - len(compact))
        if omitted:
            compact.insert(0, {
                "role": "user",
                "content": (
                    f"Earlier conversation compacted: {omitted} message(s) omitted. "
                    "Use the current workspace files and recent messages as source of truth."
                ),
            })
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
            if role == "assistant" and compact_msg.get("tool_calls"):
                compact_msg["tool_calls"] = self._compact_assistant_tool_calls(compact_msg.get("tool_calls"))

            if role == "tool" and len(content) > 3500:
                content = content[:3500] + "\n... (tool result truncated for context)"
            elif role == "assistant" and len(content) > 1600:
                content = content[:1600] + "\n... (assistant text truncated for context)"
            elif role == "user" and len(content) > 3500:
                suffix = "older user text truncated for context" if kept else "user text truncated for context"
                content = content[:3500] + f"\n... ({suffix})"

            compact_msg["content"] = content
            tool_call_len = len(json.dumps(compact_msg.get("tool_calls", []), ensure_ascii=False)) if compact_msg.get("tool_calls") else 0
            msg_len = len(content) + tool_call_len
            if kept and total + msg_len > max_chars:
                break
            kept.append(compact_msg)
            total += msg_len

        kept.reverse()
        omitted = max(0, len(tail) - len(kept))
        if omitted:
            summary = {
                "role": "user",
                "content": (
                    f"Earlier terminal loop compacted: {omitted} message(s) omitted. "
                    "Do not repeat old broad exploration; rely on preserved tool results or read specific files again."
                ),
            }
            return [system, summary] + kept
        return [system] + kept

    def _compact_assistant_tool_calls(self, tool_calls: Any) -> List[Dict]:
        compact_calls: List[Dict] = []
        for call in tool_calls or []:
            call_dict = dict(call) if isinstance(call, dict) else {}
            function = dict(call_dict.get("function", {})) if isinstance(call_dict.get("function"), dict) else {}
            name = str(function.get("name") or call_dict.get("name") or "")
            raw_args = function.get("arguments", {})
            args = self._parse_tool_arguments(raw_args)

            if args:
                for key in ("content", "new_text", "old_text"):
                    value = args.get(key)
                    if isinstance(value, str) and len(value) > 260:
                        args[key] = f"<omitted {len(value)} chars from terminal history after {name}>"

                for key, value in list(args.items()):
                    if isinstance(value, str) and len(value) > 1200:
                        args[key] = truncate_middle(value, 1200)

                if isinstance(raw_args, dict):
                    function["arguments"] = args
                else:
                    function["arguments"] = json.dumps(args, ensure_ascii=False)

            call_dict["function"] = function
            compact_calls.append(call_dict)
        return compact_calls

    def _patch_dangling_tool_messages(self, messages: List[Dict]) -> List[Dict]:
        """Insert synthetic tool outputs for assistant tool calls missing results.

        Cloud providers reject histories where an assistant function_call has no
        matching function_call_output/tool message. DeerFlow solves this with a
        dangling-tool middleware; JoyBoy keeps the same invariant in its simple
        dict-based loop.
        """
        if not messages:
            return messages

        if not any(isinstance(message, dict) and message.get("role") == "assistant" and message.get("tool_calls") for message in messages):
            return messages

        patched: List[Dict] = []
        patched_ids = set()
        patch_count = 0
        for index, message in enumerate(messages):
            patched.append(message)
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            following_tool_ids = set()
            for later in messages[index + 1:]:
                if not isinstance(later, dict):
                    continue
                later_role = later.get("role")
                if later_role == "tool" and later.get("tool_call_id"):
                    following_tool_ids.add(str(later.get("tool_call_id") or ""))
                    continue
                if later_role in {"assistant", "user", "system"}:
                    break
            for call in message.get("tool_calls") or []:
                call_id = self._tool_call_id(call)
                if not call_id or call_id in following_tool_ids or call_id in patched_ids:
                    continue
                tool_name = self._tool_call_name(call) or "tool"
                patched.append({
                    "role": "tool",
                    "tool_name": tool_name,
                    "tool_call_id": call_id,
                    "content": (
                        "[TERMINAL GUARDRAIL] Tool call did not return an output "
                        "before the next model call. Treat it as failed and continue "
                        "from the available context."
                    ),
                })
                patched_ids.add(call_id)
                patch_count += 1

        if patch_count:
            print(f"[BRAIN] Patched {patch_count} dangling tool call output(s)")
        return patched

    def _limit_delegate_subagent_calls(self, tool_calls: Any) -> tuple[List[Any], int]:
        kept: List[Any] = []
        delegate_count = 0
        dropped = 0
        for call in tool_calls or []:
            name = self._tool_call_name(call)
            if name == "delegate_subagent":
                delegate_count += 1
                if delegate_count > MAX_DELEGATE_SUBAGENT_CALLS_PER_RESPONSE:
                    dropped += 1
                    continue
            kept.append(call)
        return kept, dropped

    @staticmethod
    def _tool_call_name(call: Any) -> str:
        if hasattr(call, "function") and hasattr(call.function, "name"):
            return str(call.function.name or "")
        if isinstance(call, dict):
            function = call.get("function", {})
            if isinstance(function, dict):
                return str(function.get("name") or "")
            return str(call.get("name") or "")
        return ""

    @staticmethod
    def _tool_call_id(call: Any) -> str:
        if hasattr(call, "id"):
            return str(getattr(call, "id", "") or "")
        if isinstance(call, dict):
            return str(call.get("id") or "")
        return ""

    @staticmethod
    def _parse_tool_arguments(raw_args: Any) -> Dict:
        if isinstance(raw_args, dict):
            return dict(raw_args)
        if isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _estimate_prompt_tokens(self, messages: List[Dict], tools: List[Dict]) -> int:
        """Rough local estimate used only to avoid one more doomed call."""
        try:
            char_count = len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools or [], ensure_ascii=False))
        except Exception:
            char_count = sum(len(str(msg.get("content", ""))) for msg in messages) + len(str(tools or []))
        return max(1, int(char_count / 4))

    def _reset_deferred_tools(self) -> None:
        """Prepare a DeerFlow-style deferred tool registry for this terminal run."""
        self._active_deferred_tool_names = {
            name
            for name in DEFERRED_TOOL_NAMES
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

        if any(word in msg for word in ("analyse", "audit", "explore", "inspecte", "test", "build", "verify", "vérifie", "verifie")):
            names.append("delegate_subagent")

        if any(word in msg for word in ("delete", "supprime", "remove", "efface")):
            names.append("delete_file")

        if executed_tools and any(item.get("tool") == "bash" for item in executed_tools):
            names.append("delegate_subagent")

        if self._should_use_todos_for_request(initial_message):
            names.append("write_todos")

        seen = set()
        ordered: List[str] = []
        for name in names:
            if name in self._active_deferred_tool_names and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _should_use_todos_for_request(self, message: str) -> bool:
        """Keep TodoMiddleware-style planning for real multi-step work only.

        DeerFlow's todo tool is deliberately not used for simple tasks. JoyBoy
        follows the same rule so a scaffold request does not burn a full turn on
        bookkeeping before touching files.
        """
        if self._is_scaffold_write_request(message):
            return False
        return self._is_complex_task_request(message)

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
        if any(marker in msg for marker in deferred_markers):
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
            for name in DEFERRED_TOOL_NAMES
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
            narrowed = [name for name in candidates if required and required in name.lower()]
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
            tool = self.tool_registry.get(name)
            searchable = f"{name} {tool.description if tool else ''}"
            if regex.search(searchable):
                score = 2 if regex.search(name) else 1
                scored.append((score, name))

        if not scored:
            tokens = [token for token in re.split(r"\W+", query.lower()) if len(token) > 2]
            for name in candidates:
                tool = self.tool_registry.get(name)
                searchable = f"{name} {tool.description if tool else ''}".lower()
                score = sum(1 for token in tokens if token in searchable)
                if score:
                    scored.append((score, name))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [name for _, name in scored[:DEFERRED_TOOL_MAX_RESULTS]]

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
        tool = self.tool_registry.get(name)
        searchable = f"{name} {tool.description if tool else ''}"
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
                for name in DEFERRED_TOOL_NAMES
                if name in self._active_deferred_tool_names
                and name not in self._active_promoted_tool_names
            ],
        }

    def _write_todos(self, todos: Any) -> Dict:
        if not isinstance(todos, list):
            return {"success": False, "error": "todos must be a list"}
        if not todos:
            self.current_plan = None
            return {"success": True, "todos": [], "summary": "Todo list cleared"}

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
            return {"success": False, "error": "todos must include at least one item with content"}

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

    def _inject_todo_reminder(self, messages: List[Dict]) -> List[Dict]:
        if not self._has_incomplete_todos() or self._message_has_visible_todos(messages):
            return messages
        if not messages:
            return messages
        reminder = {
            "role": "user",
            "content": (
                "[ACTIVE TODO LIST]\n"
                "Your earlier write_todos call is no longer visible after context compaction, "
                "but the task list is still active:\n"
                f"{self._format_active_todos()}\n\n"
                "Continue from this list and call write_todos when statuses change."
            ),
        }
        return [messages[0], reminder] + messages[1:]

    def _remember_fact(self, args: Dict[str, Any]) -> Dict:
        try:
            from core.agent_runtime import remember_terminal_fact

            saved = remember_terminal_fact(
                content=str(args.get("content", "") or ""),
                category=str(args.get("category", "context") or "context"),
                confidence=float(args.get("confidence", 0.6) or 0.6),
                source="terminal",
            )
            return {"success": True, **saved}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _list_memory(self, args: Dict[str, Any]) -> Dict:
        try:
            from core.agent_runtime import search_terminal_memory

            facts = search_terminal_memory(
                query=str(args.get("query", "") or ""),
                limit=int(args.get("limit", 8) or 8),
            )
            return {"success": True, "facts": facts, "count": len(facts)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _execute_write_files_batch(
        self,
        files: Any,
        workspace_path: str,
        overwrite_existing: bool = False,
    ) -> Dict[str, Any]:
        """Write several files with one backend verification pass.

        Repeated backend work stays out of the LLM loop: the model requests a
        whole scaffold once, then JoyBoy validates, writes, and verifies locally.
        """
        from core.workspace_tools import write_file

        if not isinstance(files, list) or not files:
            return {"success": False, "error": "files must be a non-empty array"}
        if len(files) > 40:
            return {"success": False, "error": "Too many files in one batch (max 40)"}

        prepared: list[tuple[str, str, str, bool]] = []
        seen: set[str] = set()
        conflicts: list[str] = []

        for item in files:
            if not isinstance(item, dict):
                return {"success": False, "error": "Each file entry must be an object"}
            path = str(item.get("path", "") or "").strip().replace("\\", "/")
            content = item.get("content")
            if not path:
                return {"success": False, "error": "File path is required"}
            if content is None:
                return {"success": False, "error": f"Content is required for {path}"}
            content = str(content)

            full_path = self._resolve_for_snapshot(workspace_path, path)
            if not full_path:
                return {"success": False, "error": f"Path escapes the workspace: {path}"}

            key = self._canonical_file_key(full_path)
            if key in seen:
                return {"success": False, "error": f"Duplicate path in batch: {path}"}
            seen.add(key)

            exists = os.path.exists(full_path)
            if exists and not overwrite_existing:
                conflicts.append(path)
                continue

            if exists:
                blocked = self._require_read_before_existing_write(workspace_path, path, full_path, "write_files")
                if blocked:
                    return {"success": False, "error": f"{path}: {blocked.error}"}
                is_valid, error = self._validate_write(full_path, content)
                if not is_valid:
                    return {"success": False, "error": f"{path}: {error}"}

            prepared.append((path, full_path, content, exists))

        if conflicts:
            return {
                "success": False,
                "error": "Existing files blocked. Read and overwrite explicitly, or remove them from the batch.",
                "conflicts": conflicts,
            }

        written: list[dict[str, Any]] = []
        for path, full_path, content, existed in prepared:
            if existed:
                self._create_snapshot(full_path, path)

            result = write_file(workspace_path, path, content)
            if not result.get("success"):
                return {
                    "success": False,
                    "error": result.get("error") or f"Failed to write {path}",
                    "files": written,
                }

            verified = self._verify_file_write(workspace_path, path)
            if not verified.get("verified"):
                return {
                    "success": False,
                    "error": verified.get("error", f"Verification failed for {path}"),
                    "files": written,
                }

            action = "updated" if existed else "created"
            self._log_action("write_files", path, True)
            written.append({
                "path": path,
                "action": action,
                "bytes": len(content.encode("utf-8", errors="replace")),
            })

        return {
            "success": True,
            "count": len(written),
            "files": written,
            "created": [item["path"] for item in written if item["action"] == "created"],
            "updated": [item["path"] for item in written if item["action"] == "updated"],
        }

    def _build_memory_context_prompt(self, initial_message: str, limit: int = 4) -> str:
        try:
            from core.agent_runtime import search_terminal_memory

            facts = search_terminal_memory(query=initial_message, limit=limit)
        except Exception:
            return ""

        if not facts:
            return ""

        lines = [
            "LOCAL MEMORY CONTEXT (read-only):",
            "Use these facts only if directly relevant to the user's request. Ignore irrelevant facts.",
        ]
        for fact in facts[:limit]:
            content = truncate_middle(str(fact.get("content", "")), 300)
            if not content:
                continue
            category = str(fact.get("category", "context") or "context")
            confidence = fact.get("confidence", "?")
            lines.append(f"- [{category}, confidence={confidence}] {content}")
        if len(lines) <= 2:
            return ""
        return "\n".join(lines)

    def _select_tool_names_for_turn(
        self,
        initial_message: str,
        executed_tools: List[Dict],
        autonomous: bool = False,
    ) -> Optional[List[str]]:
        if autonomous:
            return None

        if self.current_intent in {"write", "execute"}:
            if self._is_scaffold_write_request(initial_message):
                names = list(SCAFFOLD_CORE_TOOL_ORDER)
            else:
                names = ["list_files", "read_file", "write_file", "write_files", "edit_file", "bash", "search", "glob"]
        else:
            names = list(READ_CORE_TOOL_ORDER)

        self._active_promoted_tool_names.update(self._auto_promoted_deferred_tools(initial_message, executed_tools))

        for name in DEFERRED_TOOL_NAMES:
            if name in self._active_promoted_tool_names:
                names.append(name)

        if self._should_offer_tool_search(initial_message, executed_tools):
            names.append("tool_search")

        seen = set()
        ordered: List[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _is_repo_overview_request(self, message: str) -> bool:
        """Detect broad repo audits that should not rely on free-form tool loops.

        Small local models often get stuck repeating ``ls``/``glob`` on vague
        requests such as "analyse mon repo". For those cases JoyBoy does a
        deterministic, bounded preflight scan, then asks the model to summarize
        without tools. Precise requests still use the normal agentic loop.
        """
        msg = self._intent_text(message)
        overview_words = ("analyse", "audit", "regarde", "explore", "inspecte", "comprendre")
        repo_words = ("repo", "projet", "codebase", "workspace", "dossier")
        write_words = ("corrige", "fix", "modifie", "ajoute", "supprime", "implémente", "implemente")
        if any(word in msg for word in write_words):
            return False
        if not any(word in msg for word in overview_words):
            return False
        if re.search(r"[\w./\\-]+\.(py|js|jsx|ts|tsx|css|html|md|json|yaml|yml|toml|txt|go|rs|java|cs|php|rb)\b", msg):
            return False
        if any(word in msg for word in repo_words):
            return True

        vague_targets = (
            "analyse", "analyse le", "analyse la", "analyse les", "analyse ça",
            "analyse ca", "analyse ceci", "analyse ici", "regarde ça",
            "regarde ca", "regarde le", "explore le", "inspecte le",
        )
        raw = str(message or "").lower()
        folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        compact_candidates = {
            re.sub(r"\s+", " ", raw).strip(" .!?;:"),
            re.sub(r"\s+", " ", folded).strip(" .!?;:"),
        }
        return any(compact in vague_targets or len(compact.split()) <= 3 for compact in compact_candidates if compact)

    def _is_open_workspace_request(self, message: str) -> bool:
        msg = self._intent_text(message)
        open_words = ("ouvre", "ouvrir", "open", "affiche", "montre")
        folder_words = ("dossier", "folder", "workspace", "projet", "répertoire", "repertoire")
        return any(word in msg for word in open_words) and any(word in msg for word in folder_words)

    def _is_casual_greeting_request(self, message: str) -> bool:
        text = self._folded_single_line(message)
        if not text or len(text) > 90:
            return False

        action_words = (
            "analyse", "audit", "regarde", "inspecte", "explore", "cherche",
            "cree", "creer", "create", "make", "ajoute", "modifie", "corrige",
            "fix", "debug", "test", "installe", "install", "commit", "push",
            "fichier", "file", "repo", "projet", "workspace", "dossier",
            "terminal", "commande", "erreur", "error", "log",
        )
        if any(word in text for word in action_words):
            return False

        words = text.split()
        if len(words) > 7:
            return False

        greeting_words = (
            "yo", "yoo", "salut", "slt", "coucou", "hey", "hello", "hi",
            "bonjour", "bonsoir", "wesh", "bjr",
        )
        if words and words[0] in greeting_words:
            return True

        return any(phrase in text for phrase in ("ca va", "ça va", "t es la", "tu es la", "t'es la"))

    @staticmethod
    def _folded_single_line(message: str) -> str:
        raw = str(message or "").lower()
        folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        folded = re.sub(r"[^a-z0-9' ]+", " ", folded)
        return re.sub(r"\s+", " ", folded).strip()

    def _casual_greeting_answer(self, message: str) -> str:
        text = self._folded_single_line(message)
        words = set(text.split())
        if words & {"hello", "hey", "hi"} and not words & {"mec", "frero", "salut", "bonjour", "wesh"}:
            return "Hey, I'm here. Tell me what you want to do."
        if "j ai dis" in text or "j'ai dis" in text:
            return "Je suis là, je t'écoute. Le terminal repart en mode conversation propre."
        return "Je suis là, mec. Dis-moi ce que tu veux faire."

    def _is_complex_task_request(self, message: str) -> bool:
        msg = self._intent_text(message)
        complex_markers = (
            "analyse et", "corrige", "regle", "ameliore", "améliore", "implemente",
            "implémente", "refactor", "audit", "compare", "deerflow", "commit",
            "push", "termine", "terminé", "continue", "tout le projet", "long",
            "plusieurs", "multi", "tests", "verifie", "vérifie",
        )
        if any(marker in msg for marker in complex_markers):
            return True
        return len([part for part in re.split(r"\s+", msg) if part]) >= 18

    def _build_repo_brief(self, workspace_path: str) -> tuple[str, List[Dict]]:
        """Build a bounded repo brief and emit normal tool events for the UI."""
        from core.workspace_tools import get_workspace_summary, list_files, read_file
        from core.agent_runtime import run_subagent

        events: List[Dict] = []
        lines: List[str] = []

        events.append(runtime_event('tool_call', name='list_files', args={'path': '.'}))
        root_listing = list_files(workspace_path, '.', max_files=80)
        events.append(runtime_event('tool_result', result={
            'success': root_listing.get('success', False),
            'tool_name': 'list_files',
            'data': root_listing,
            'error': root_listing.get('error'),
            'write_blocked': False,
        }))

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

        explorer_args = {
            "agent_type": "code_explorer",
            "task": "Build a concise repository overview. Prefer README and configuration files, then likely app entrypoints.",
            "max_files": 8,
        }
        events.append(runtime_event('tool_call', name='delegate_subagent', args=explorer_args))
        explorer = run_subagent(
            "code_explorer",
            workspace_path,
            explorer_args["task"],
            max_files=explorer_args["max_files"],
        )
        events.append(runtime_event('tool_result', result={
            'success': explorer.get('status') == 'completed',
            'tool_name': 'delegate_subagent',
            'data': explorer,
            'error': explorer.get('error'),
            'write_blocked': False,
        }))
        if explorer.get("status") == "completed":
            observations = explorer.get("observations", [])
            if observations:
                lines.append("Explorer observations: " + " | ".join(str(item) for item in observations[:3]))
            for item in explorer.get("files", [])[:6]:
                path = item.get("path", "")
                excerpt = item.get("excerpt", "")
                if not path or not excerpt:
                    continue
                lines.append(
                    f"\n--- {path} ({item.get('lines', 0)} lines, explorer) ---\n"
                    f"{truncate_middle(excerpt, 1400)}"
                )

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
            events.append(runtime_event('tool_call', name='read_file', args={'path': path, 'max_lines': 120}))
            events.append(runtime_event('tool_result', result={
                'success': True,
                'tool_name': 'read_file',
                'data': result,
                'error': None,
                'write_blocked': False,
            }))
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
        return tool_signature(tool_name, args)

    def _tool_guard_reason(
        self,
        tool_name: str,
        args: Dict,
        seen_count: int,
        executed_tools: List[Dict],
    ) -> Optional[str]:
        """Return a reason when a tool call is clearly no-progress noise."""
        return tool_guard_reason(tool_name, args, seen_count, executed_tools)

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
        elif tool_name == "write_todos":
            counts = data.get("counts", {}) if isinstance(data, dict) else {}
            summary["summary"] = ", ".join(f"{key}={value}" for key, value in counts.items() if value) or "todo list updated"
        elif tool_name == "tool_search":
            summary["summary"] = f"{len(data.get('promoted', []))} tool(s) promoted"
        elif tool_name == "web_fetch":
            summary["summary"] = f"{data.get('title', 'page')} ({data.get('length', 0)} chars)"
        elif tool_name == "delegate_subagent":
            summary["summary"] = f"{data.get('agent_type', 'subagent')} {data.get('status', 'unknown')}"
        elif tool_name == "load_skill":
            skill = data.get("skill", {}) if isinstance(data, dict) else {}
            summary["summary"] = skill.get("id", "skill loaded")
        elif tool_name == "remember_fact":
            fact = data.get("fact", {}) if isinstance(data, dict) else {}
            summary["summary"] = fact.get("id", "memory saved")
        elif tool_name == "list_memory":
            summary["summary"] = f"{data.get('count', 0)} fact(s)"
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
            if tool in {"write_file", "write_files", "edit_file", "delete_file"}:
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

    def _has_attempted_mutation(self, executed_tools: List[Dict]) -> bool:
        return any((item.get("tool") in WRITE_CORE_TOOL_NAMES) for item in executed_tools)

    def _should_nudge_write_progress(self, initial_message: str, executed_tools: List[Dict]) -> bool:
        if self.current_intent not in {"write", "execute"}:
            return False
        if self._has_successful_mutation(executed_tools) or self._has_attempted_mutation(executed_tools):
            return False
        if len(executed_tools) < 3:
            return False
        recent = [item.get("tool") for item in executed_tools[-4:]]
        passive_tools = {"list_files", "read_file", "glob", "search", "tool_search", "write_todos", "think"}
        return all(tool in passive_tools for tool in recent)

    def _write_progress_nudge(self, initial_message: str) -> str:
        if self._is_scaffold_write_request(initial_message):
            return (
                "[WRITE TASK REMINDER]\n"
                "The user asked for a project/template scaffold. Stop planning or searching for write tools. "
                "Use write_files in the next response for the actual files, or edit_file/write_file if replacing an existing file. "
                "Then verify with list_files or read_file."
            )
        return (
            "[WRITE TASK REMINDER]\n"
            "The user asked for a modification. Stop passive exploration unless one specific file is still required. "
            "Use edit_file, write_file, write_files, or bash now, then verify the result."
        )

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

    def _budget_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        if executed_tools:
            bullet_lines = [
                f"- {item.get('tool')} {item.get('args', {})}: {item.get('summary', '')}"
                for item in executed_tools[-6:]
            ]
            return (
                "J'ai coupé avant de relancer le modèle pour ne pas brûler plus de tokens.\n\n"
                "Dernières observations utiles:\n"
                + "\n".join(bullet_lines)
                + "\n\nRelance avec une cible plus précise, ou demande `analyse le projet`: "
                "JoyBoy utilisera le scan borné sans boucle d'exploration."
            )

        return (
            "J'ai coupé avant un nouvel appel modèle pour éviter une boucle coûteuse. "
            "Aucun outil n'avait encore produit de contexte utile; demande `analyse le projet` "
            "ou cible un fichier précis."
        )

    def _iteration_limit_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        bullet_lines = [
            f"- {item.get('tool')} {item.get('args', {})}: {item.get('summary', '')}"
            for item in executed_tools[-8:]
        ]
        if self.current_intent in {"write", "execute"} and not self._has_successful_mutation(executed_tools):
            return (
                "J'ai stoppé la boucle avant qu'elle continue à brûler des tokens sans appliquer de changement.\n\n"
                "Dernières actions observées:\n"
                + "\n".join(bullet_lines)
                + "\n\nAucune écriture vérifiée n'a été faite. Relance la même demande: JoyBoy doit maintenant exposer "
                "`write_files`/`edit_file` directement et éviter `tool_search`/`write_todos` sur ce type de tâche."
            )
        return (
            "J'ai atteint la limite d'itérations, donc je rends l'état observé au lieu de repartir en boucle.\n\n"
            "Dernières actions observées:\n"
            + "\n".join(bullet_lines)
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
        skill_index = self._build_skill_index_prompt()
        deferred_tools = self._build_deferred_tools_prompt()
        host_os = platform.system() or os.name
        return f"""You are JoyBoy Terminal, an expert coding agent working inside a local project folder.

Workspace name: {project_name}
Workspace path visible to you: /workspace
Host workspace path: hidden by JoyBoy runtime; do not mention local absolute paths unless the user asks.
Host OS: {host_os}. The bash tool runs through the host default shell in the workspace; on Windows, use PowerShell/cmd-compatible commands unless a POSIX tool is confirmed available.
{language_rule}
Core contract:
1. Use tools for real work. Do not pretend that files were created, edited, installed, or tested.
2. Always call read_file before editing or replacing an existing file.
3. Prefer edit_file for targeted changes. Use write_files for scaffolds or multi-file creation. Use write_file only for a single new file or intentional full rewrite.
4. Never call read_file on "." or on a directory. read_file is only for specific files.
5. Do one meaningful step at a time, then verify the result before claiming success.
6. Do not loop on list_files, glob, ls, dir, or pwd. One root exploration is enough; then read specific files.
7. If a shell scaffold command succeeds, verify the expected folder and package.json before saying it exists.
8. If a command or edit fails, inspect the error, adjust once or twice, then explain the blocker.
9. Keep context lean: read focused file chunks, summarize large outputs, and avoid dumping entire files.
10. For final code snippets, use fenced Markdown blocks with a language tag.
11. For broad codebase tasks, prefer delegate_subagent(code_explorer) over repeated list_files/glob/search loops.
12. For web research, use web_search first, then web_fetch exact public URLs returned by search or provided by the user.
13. After modifications, prefer delegate_subagent(verifier) with one allowlisted test/build command instead of free-form shell retries.
14. Some rare tools are deferred to save tokens. If a needed deferred tool is listed by name only, call tool_search once to fetch its schema, then call that tool. Do not use tool_search for core tools like write_files, write_file, edit_file, read_file, list_files, bash, search, or glob.
15. For complex multi-step tasks, call write_todos early with 2-6 concrete items, keep exactly one item in_progress, and update it as you work. Do not use write_todos for simple scaffolds or small direct edits.
16. Use remember_fact only for explicit durable user/project preferences. Never store secrets, API keys, tokens, private URLs, or one-off transient details.
17. Use list_memory when the user asks about remembered context or when memory is clearly relevant.

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
1. Prefer write_files for small templates and starter projects so the whole scaffold is one tool step.
2. Use a scaffold command only when the user asks for a framework generator or the project is too large for a small batch.
3. Verify the generated files or package.json before describing them.
{skill_index}
{deferred_tools}

You have access to filesystem, search, shell, and workspace tools. Use them to complete the user's task."""

    def _get_default_system_prompt(self, workspace_path: str) -> str:
        """Default Claude-Code-style terminal system prompt."""
        return self.build_system_prompt(workspace_path)

    def _build_skill_index_prompt(self) -> str:
        try:
            from core.infra.packs import get_pack_skills

            skills = get_pack_skills()
        except Exception:
            skills = []

        if not skills:
            return ""

        lines = [
            "",
            "Local pack skills:",
            "- Use load_skill only when a listed skill clearly matches the task.",
            "- Do not load every skill preemptively; keep context lean.",
        ]
        for skill in skills[:20]:
            summary = f" - {skill.get('summary', '')}" if skill.get("summary") else ""
            lines.append(f"- {skill.get('id')}: {skill.get('name', 'Skill')}{summary}")
        if len(skills) > 20:
            lines.append(f"- ... {len(skills) - 20} more skill(s) hidden from the base prompt.")
        return "\n".join(lines)

    def _build_deferred_tools_prompt(self) -> str:
        remaining = [
            name
            for name in DEFERRED_TOOL_NAMES
            if name in self._active_deferred_tool_names
            and name not in self._active_promoted_tool_names
            and self.tool_registry.get(name)
        ]
        if not remaining:
            return ""

        lines = [
            "",
            "Available deferred tools:",
            "- Their full schemas are hidden from the base prompt to reduce token use.",
            "- Call tool_search with select:<tool_name> or keywords only when one is actually needed.",
            "- Core file tools are already active when the task needs them; never fetch write_files/write_file/edit_file/bash through tool_search.",
        ]
        for name in remaining:
            tool = self.tool_registry.get(name)
            lines.append(f"- {name}: {tool.description if tool else ''}")
        return "\n".join(lines)

    def _format_result_for_llm(self, result: ToolResult) -> str:
        """Formate le résultat d'un tool pour le LLM"""
        if not result.success:
            if result.tool_name == 'delegate_subagent' and result.data:
                return self._format_delegate_subagent_for_llm(result.data)
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
                output = truncate_middle(output, max(3000, min(8000, int(self._active_context_size * 1.35))))
                output = mask_workspace_paths(output, self._active_workspace_path)
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
            output = truncate_middle(output, max(3000, min(8000, int(self._active_context_size * 1.35))))
            output = mask_workspace_paths(output, self._active_workspace_path)
            return f"[RESULT bash] {status} (code: {code})\n```\n{output}\n```"

        elif result.tool_name == 'write_todos':
            todos = data.get("todos", []) if isinstance(data, dict) else []
            if not todos:
                return "[RESULT write_todos] Todo list cleared"
            lines = [
                f"- [{item.get('status', 'pending')}] {item.get('content', '')}"
                + (f" - {item.get('note')}" if item.get("note") else "")
                for item in todos
            ]
            return "[RESULT write_todos]\n" + "\n".join(lines)

        elif result.tool_name == 'write_files':
            files = data.get("files", []) if isinstance(data, dict) else []
            if not files:
                conflicts = data.get("conflicts", []) if isinstance(data, dict) else []
                if conflicts:
                    return "[RESULT write_files] Existing files blocked:\n" + "\n".join(f"- {path}" for path in conflicts)
                return f"[RESULT write_files] {'OK' if result.success else 'failed'}"
            lines = [
                f"- {item.get('action', 'written')}: {item.get('path', '')} ({item.get('bytes', 0)} bytes)"
                for item in files
            ]
            return "[RESULT write_files]\n" + "\n".join(lines)

        elif result.tool_name == 'tool_search':
            promoted = data.get("promoted", []) if isinstance(data, dict) else []
            already_available = data.get("already_available", []) if isinstance(data, dict) else []
            blocked_by_intent = data.get("blocked_by_intent", []) if isinstance(data, dict) else []
            tools = data.get("tools", []) if isinstance(data, dict) else []
            if not promoted and not already_available and not blocked_by_intent:
                return f"[RESULT tool_search] No deferred tools matched: {data.get('query', '') if isinstance(data, dict) else ''}"
            lines: List[str] = []
            if promoted:
                schemas = json.dumps(tools, ensure_ascii=False, indent=2)
                lines.append(f"Promoted deferred tools: {', '.join(promoted)}")
                lines.append("These tool schemas are now available for the next call:")
                lines.append(f"```json\n{schemas}\n```")
            if already_available:
                lines.append(
                    "Core tools already available in this turn; call them directly, do not fetch them through tool_search: "
                    + ", ".join(already_available)
                )
            if blocked_by_intent:
                lines.append(
                    "Core write tools were requested but this turn is read-only. The user must ask for a modification before using: "
                    + ", ".join(blocked_by_intent)
                )
            return "[RESULT tool_search]\n" + "\n".join(lines)

        elif result.tool_name == 'web_search':
            items = data.get('results', [])
            if not items:
                return "[RESULT web_search] No results"
            results_text = '\n'.join([
                f"{i+1}. {item.get('title', 'Untitled')}\n   {item.get('url', '')}\n   {item.get('snippet', '')[:150]}"
                for i, item in enumerate(items[:5])
            ])
            return f"[RESULT web_search]\n{results_text}"

        elif result.tool_name == 'web_fetch':
            title = data.get("title", "Untitled")
            url = data.get("url", "")
            content = truncate_middle(data.get("content", ""), max(3000, min(9000, int(self._active_context_size * 1.5))))
            return f"[RESULT web_fetch] {title}\nURL: {url}\n````markdown\n{content}\n````"

        elif result.tool_name == 'delegate_subagent':
            return self._format_delegate_subagent_for_llm(data)

        elif result.tool_name == 'load_skill':
            skill = data.get("skill", {}) if isinstance(data, dict) else {}
            content = data.get("content", "") if isinstance(data, dict) else ""
            content = truncate_middle(content, max(3500, min(9000, int(self._active_context_size * 1.5))))
            suffix = "\n... (skill truncated)" if data.get("truncated") else ""
            return f"[RESULT load_skill] {skill.get('id', '')} - {skill.get('name', 'Skill')}\n````markdown\n{content}{suffix}\n````"

        elif result.tool_name == 'remember_fact':
            fact = data.get("fact", {}) if isinstance(data, dict) else {}
            return (
                "[RESULT remember_fact] Saved local memory fact "
                f"{fact.get('id', '')}: {fact.get('content', '')}"
            )

        elif result.tool_name == 'list_memory':
            facts = data.get("facts", []) if isinstance(data, dict) else []
            if not facts:
                return "[RESULT list_memory] No local memory facts matched"
            lines = [
                f"- {fact.get('id', '')} [{fact.get('category', 'context')}, confidence={fact.get('confidence', '?')}]: {fact.get('content', '')}"
                for fact in facts[:10]
            ]
            return "[RESULT list_memory]\n" + "\n".join(lines)

        elif result.tool_name == 'think':
            return f"[THOUGHT] {data.get('thought', '')} - Continue with the appropriate concrete action."

        elif result.tool_name == 'open_workspace':
            return f"[RESULT open_workspace] Folder opened: {data.get('path', '')}"

        return f"[RESULT {result.tool_name}] OK"

    def _format_delegate_subagent_for_llm(self, data: Dict) -> str:
        observations = data.get("observations", []) if isinstance(data, dict) else []
        files = data.get("files", []) if isinstance(data, dict) else []
        commands = data.get("commands", []) if isinstance(data, dict) else []
        warnings = data.get("warnings", []) if isinstance(data, dict) else []
        lines = [
            f"[RESULT delegate_subagent] {data.get('agent_type', 'subagent')} {data.get('status', '')}",
            f"Task id: {data.get('task_id', '')}",
            f"Summary: {data.get('summary', '')}",
        ]
        if observations:
            lines.append("Observations:")
            lines.extend(f"- {item}" for item in observations[:8])
        if commands:
            lines.append("Commands:")
            for item in commands[:4]:
                lines.append(f"- {item.get('command', '')} (code: {item.get('return_code', 'n/a')})")
                output = item.get("output", "")
                if output:
                    lines.append("```")
                    lines.append(truncate_middle(output, 5000))
                    lines.append("```")
                if item.get("error"):
                    lines.append(f"  error: {item.get('error')}")
        if warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in warnings[:5])
        if files:
            lines.append("Relevant files:")
            for item in files[:8]:
                excerpt = item.get("excerpt", "")
                if excerpt:
                    excerpt = truncate_middle(excerpt, 1800)
                    lines.append(f"\n--- {item.get('path', '')} ({item.get('lines', '?')} lines) ---\n{excerpt}")
                else:
                    lines.append(f"- {item.get('path', '')}: {item.get('error', 'unreadable')}")
        return "\n".join(lines)

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

            output = truncate_middle(mask_workspace_paths(output, workspace_path), 8000)

            response = {
                "success": result.returncode == 0,
                "output": output,
                "return_code": result.returncode,
                "error": mask_workspace_paths(result.stderr, workspace_path) if result.returncode != 0 else None
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

    def _execute_web_fetch(self, url: str) -> Dict:
        """Fetch a readable public web page."""
        url = str(url or "").strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            return {"success": False, "error": "URL must start with http:// or https://"}
        try:
            from core.web_search import fetch_page_content

            return fetch_page_content(url)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _load_pack_skill(self, skill_id: str) -> Dict:
        try:
            from core.infra.packs import load_pack_skill

            return load_pack_skill(skill_id)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delegate_subagent(self, agent_type: str, task: str, workspace_path: str, **kwargs) -> Dict:
        try:
            from core.agent_runtime import run_subagent

            return run_subagent(agent_type, workspace_path, task, **kwargs)
        except Exception as e:
            return {
                "status": "error",
                "agent_type": agent_type or "code_explorer",
                "task": task,
                "error": str(e),
                "summary": "Subagent failed.",
            }

    # ===== INTENT DETECTION =====

    @staticmethod
    def _intent_text(message: str) -> str:
        raw = str(message or "").lower()
        folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        return f"{raw}\n{folded}"

    @staticmethod
    def _is_scaffold_write_request(message: str) -> bool:
        """Detect project/template creation requests that are write actions."""
        msg = TerminalBrain._intent_text(message)
        read_markers = (
            "analyse", "explique", "montre", "lis ", "regarde",
            "c'est quoi", "comprendre", "audit",
        )
        creation_markers = (
            "je veux", "veux", "besoin", "donne", "prepare", "prépare",
            "fais", "fait", "cree", "crée", "creer", "créer", "create",
            "make", "build", "code", "coder", "mets", "met", "ajoute",
            "setup", "set up",
        )
        scaffold_terms = (
            "template", "starter", "scaffold", "boilerplate", "app de base",
            "projet de base", "page complete", "page complète",
        )
        framework_terms = (
            "react", "next js", "next.js", "nextjs", "vite", "app router",
            "tailwind", "vue", "svelte",
        )

        has_scaffold_term = any(term in msg for term in scaffold_terms)
        has_framework_term = any(term in msg for term in framework_terms)
        has_creation = any(marker in msg for marker in creation_markers)
        has_read = any(marker in msg for marker in read_markers)

        if has_read and not has_creation:
            return False
        if has_scaffold_term and (has_creation or not has_read):
            return True
        if has_framework_term and has_creation:
            return True
        return False

    @staticmethod
    def detect_intent(message: str) -> str:
        """Détecte l'intention: 'read', 'write', 'execute', 'question'"""
        msg = TerminalBrain._intent_text(message)

        if TerminalBrain._is_scaffold_write_request(message):
            return 'write'

        # WRITE
        write_kw = ['modifie', 'modifier', 'change', 'ajoute', 'supprime', 'crée', 'créer',
                    'cree', 'creer', 'cr?er', 'écris', 'ecris', 'fix', 'corrige',
                    'refactor', 'implémente', 'implemente', 'update', 'create', 'make',
                    'code', 'coder', 'fais', 'fait', 'delete', 'remove', 'efface',
                    'remplace', 'replace', 'convert', 'convertis']
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
