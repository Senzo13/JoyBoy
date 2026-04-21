"""Static terminal tool schemas and toolset groups."""

from __future__ import annotations

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
DEFERRED_PROMPT_MAX_MCP_NAMES = 40
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
