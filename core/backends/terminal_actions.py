"""Concrete terminal tool actions for memory, repo scans, shell, web, and subagents."""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

from core.agent_runtime import mask_workspace_paths, runtime_event, truncate_middle
from core.backends.terminal_tools import ALLOWED_SHELL_COMMANDS
from core.backends.terminal_types import FileSnapshot


class TerminalActionsMixin:
    """Concrete implementations behind terminal tools."""

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

    def _clear_workspace(self, workspace_path: str, keep: Optional[List[str]] = None) -> Dict[str, Any]:
        """Remove top-level workspace contents while preserving repository metadata."""
        root = os.path.realpath(os.path.abspath(workspace_path or ""))
        if not root or not os.path.isdir(root):
            return {"success": False, "error": "Invalid workspace"}

        protected = {".git", ".hg", ".svn"}
        keep_names = set(protected)
        for item in keep or []:
            name = str(item or "").strip().replace("\\", "/").strip("/")
            if name and "/" not in name and name not in {".", ".."}:
                keep_names.add(name)

        deleted: list[str] = []
        kept: list[str] = []
        errors: list[str] = []

        try:
            entries = list(os.scandir(root))
        except OSError as exc:
            return {"success": False, "error": str(exc)}

        for entry in entries:
            name = entry.name
            if name in keep_names:
                kept.append(name)
                continue

            full_path = os.path.realpath(entry.path)
            if full_path == root or not full_path.startswith(root + os.sep):
                errors.append(f"{name}: path escapes workspace")
                continue

            try:
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
                deleted.append(name)
                self._log_action("clear_workspace", name, True)
            except OSError as exc:
                errors.append(f"{name}: {exc}")
                self._log_action("clear_workspace", name, False)

        if errors:
            return {
                "success": False,
                "error": "; ".join(errors[:5]),
                "deleted": deleted,
                "kept": sorted(kept),
                "count": len(deleted),
            }

        return {
            "success": True,
            "deleted": deleted,
            "kept": sorted(kept),
            "count": len(deleted),
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

        try:
            parts = shlex.split(command)
            main_cmd = parts[0] if parts else ""
        except Exception:
            main_cmd = command.split()[0] if command.split() else ""

        if main_cmd.lower() not in ALLOWED_SHELL_COMMANDS:
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

    # ===== SNAPSHOT & ROLLBACK =====

