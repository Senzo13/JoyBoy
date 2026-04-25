"""Guardrails, progress detection, and fallback answers for terminal agent."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from core.agent_runtime import tool_guard_reason, tool_signature
from core.backends.terminal_tool_schemas import WRITE_CORE_TOOL_NAMES


class TerminalGuardrailsMixin:
    """Loop/error guardrails and user-visible fallback messages."""

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
            start_line = data.get("start_line")
            end_line = data.get("end_line")
            range_text = f":{start_line}-{end_line}" if start_line and end_line else ""
            summary["summary"] = f"{data.get('path', args.get('path', ''))}{range_text} ({data.get('lines', 0)} lines)"
        elif tool_name == "glob":
            summary["summary"] = f"{len(data.get('files', []))} file(s)"
        elif tool_name == "search":
            summary["summary"] = f"{len(data.get('results', []))} result(s)"
        elif tool_name == "write_file":
            path = data.get("path", args.get("path", ""))
            state = "created" if data.get("created") else "updated"
            verified = ", verified" if data.get("verified") else ""
            summary["summary"] = f"{path} ({state}{verified})".strip()
        elif tool_name == "edit_file":
            path = data.get("path", args.get("path", ""))
            replacements = int(data.get("replacements", 0) or 0)
            verified = ", verified" if data.get("verified") else ""
            summary["summary"] = f"{path} ({replacements} replacement(s){verified})".strip()
        elif tool_name == "delete_file":
            path = data.get("path", args.get("path", ""))
            verified = ", verified" if data.get("verified") else ""
            summary["summary"] = f"{path} (deleted{verified})".strip()
        elif tool_name == "write_files":
            files = data.get("files", []) if isinstance(data, dict) else []
            paths = [str(item.get("path", "")).strip() for item in files[:4] if item.get("path")]
            suffix = f", +{len(files) - len(paths)} more" if len(files) > len(paths) else ""
            preview = ", ".join(paths)
            count = data.get("count", len(files))
            summary["summary"] = f"{count} file(s): {preview}{suffix}".strip(": ").strip()
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
        elif tool_name == "clear_workspace":
            kept = data.get("kept", []) if isinstance(data, dict) else []
            kept_text = f", kept {', '.join(kept)}" if kept else ""
            summary["summary"] = f"deleted {data.get('count', 0)} top-level item(s){kept_text}"
        elif tool_name == "remember_fact":
            fact = data.get("fact", {}) if isinstance(data, dict) else {}
            summary["summary"] = fact.get("id", "memory saved")
        elif tool_name == "list_memory":
            summary["summary"] = f"{data.get('count', 0)} fact(s)"
        elif tool_name == "bash":
            summary["summary"] = f"code {data.get('return_code', '?')}"
        elif tool_name == "open_workspace":
            summary["summary"] = data.get("path", "workspace opened")
        elif tool_name in self._mcp_tools_by_name:
            server_name = data.get("server_name", "")
            summary["summary"] = f"mcp tool via {server_name or 'external'}"
        else:
            summary["summary"] = "ok"
        return summary

    def _explicit_verify_requested(self, initial_message: str) -> bool:
        msg = self._intent_text(initial_message)
        explicit_verify_markers = (
            "test", "tests", "build", "lint", "verifie", "vérifie", "verify",
            "lance", "run ", "npm install", "pnpm install", "yarn install",
            "demarre", "démarre", "start",
        )
        return any(marker in msg for marker in explicit_verify_markers)

    def _successful_mutation_items(self, executed_tools: List[Dict]) -> List[Dict]:
        mutation_tools = {"write_file", "write_files", "edit_file", "clear_workspace", "delete_file"}
        return [
            item
            for item in executed_tools or []
            if item.get("success") and item.get("tool") in mutation_tools
        ]

    def _last_successful_mutation_index(self, executed_tools: List[Dict]) -> int:
        for index in range(len(executed_tools or []) - 1, -1, -1):
            item = (executed_tools or [])[index]
            if item.get("success") and item.get("tool") in {"write_file", "write_files", "edit_file", "clear_workspace", "delete_file"}:
                return index
        return -1

    def _should_surface_verified_write_progress(self, initial_message: str, executed_tools: List[Dict]) -> bool:
        if self.current_intent not in {"write", "execute"}:
            return False
        if not self._has_successful_mutation(executed_tools):
            return False
        if self.current_plan and self._has_incomplete_todos():
            return False
        if self._explicit_verify_requested(initial_message):
            return False

        last_mutation_index = self._last_successful_mutation_index(executed_tools)
        if last_mutation_index < 0:
            return False

        later_failures = [
            item
            for item in (executed_tools or [])[last_mutation_index + 1:]
            if not item.get("success", False)
        ]
        return not later_failures

    def _format_recent_tool_block(self, executed_tools: List[Dict], limit: int = 8) -> str:
        lines: List[str] = []
        for item in (executed_tools or [])[-limit:]:
            tool_name = str(item.get("tool") or item.get("name") or "tool").strip()
            summary = self._compact_summary_snippet(item.get("summary", ""), limit=180)
            if summary:
                line = f"[{'OK' if item.get('success', True) else 'FAIL'}] {tool_name}: {summary}"
            else:
                line = f"[{'OK' if item.get('success', True) else 'FAIL'}] {tool_name}"
            lines.append(line)
        if not lines:
            lines.append("[INFO] Aucun outil utile exécuté avant l'arrêt.")
        return "```text\n" + "\n".join(lines) + "\n```"

    def _verified_write_progress_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        relevant = self._successful_mutation_items(executed_tools)[-8:] or executed_tools[-8:]
        lead = (
            "J'ai déjà appliqué des changements vérifiés avant d'arrêter la boucle."
            if not self._is_scaffold_write_request(initial_message)
            else "C'est fait. Les changements demandés ont été appliqués et vérifiés avant que la boucle soit stoppée."
        )
        return (
            f"{lead}\n\n"
            "Changements réellement appliqués:\n"
            f"{self._format_recent_tool_block(relevant)}"
        )

    def _debug_content_preview(self, text: str, limit: int = 140) -> str:
        compact = self._compact_summary_snippet(text, limit=max(limit * 2, 220))
        if not compact:
            return "None"
        compact = re.sub(r"\bto=\w+\b[^`]*?(?=(?:\bto=\w+\b|$))", "[tool-trace-hidden] ", compact)
        compact = compact.replace("● List(.)", "[list-files-hidden]")
        compact = compact.replace("⎿ Subagent", "[subagent-hidden]")
        return self._compact_summary_snippet(compact, limit=limit) or "None"

    def _tool_call_debug_preview(self, tool_name: str, args: Dict[str, Any]) -> str:
        args = args or {}
        if tool_name in {"read_file", "write_file", "edit_file", "delete_file", "open_workspace"}:
            return str(args.get("path") or args.get("url") or "").strip()
        if tool_name == "write_files":
            files = args.get("files", []) if isinstance(args.get("files"), list) else []
            paths = [str(item.get("path", "")).strip() for item in files[:4] if isinstance(item, dict) and item.get("path")]
            suffix = f", +{len(files) - len(paths)} more" if len(files) > len(paths) else ""
            return f"{len(files)} file(s): {', '.join(paths)}{suffix}".strip()
        if tool_name == "bash":
            return self._compact_summary_snippet(str(args.get("command", "")), limit=140)
        if tool_name == "glob":
            return str(args.get("pattern", "")).strip()
        if tool_name == "search":
            pattern = self._compact_summary_snippet(str(args.get("pattern", "")), limit=80)
            base = str(args.get("path", ".")).strip()
            return f"{pattern} @ {base}".strip()
        if tool_name == "write_todos":
            todos = args.get("todos", []) if isinstance(args.get("todos"), list) else []
            return f"{len(todos)} todo(s)"
        if tool_name == "delegate_subagent":
            task = self._compact_summary_snippet(str(args.get("task", "")), limit=120)
            agent_type = str(args.get("agent_type", "subagent")).strip()
            return f"{agent_type}: {task}".strip(": ")
        return self._compact_summary_snippet(str(args), limit=140)

    def _has_successful_mutation(self, executed_tools: List[Dict]) -> bool:
        for item in executed_tools:
            if not item.get("success"):
                continue
            tool = item.get("tool")
            if tool in {"write_file", "write_files", "edit_file", "clear_workspace", "delete_file"}:
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

    def _should_finalize_after_scaffold_write(self, initial_message: str, executed_tools: List[Dict]) -> bool:
        """Stop after a verified scaffold batch instead of spending another LLM turn."""
        if not self._is_scaffold_write_request(initial_message):
            return False
        if self.current_plan and self._has_incomplete_todos():
            return False

        if self._explicit_verify_requested(initial_message):
            return False

        last_write_index = -1
        for index, item in enumerate(executed_tools or []):
            if item.get("tool") == "write_files" and item.get("success"):
                last_write_index = index
        if last_write_index < 0:
            return False

        later_failures = [
            item for item in (executed_tools or [])[last_write_index + 1:]
            if not item.get("success", False)
        ]
        return not later_failures

    def _post_write_finalize_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        """Compact deterministic final answer for scaffold turns."""
        mutation_items = self._successful_mutation_items(executed_tools)[-8:]
        details = self._format_recent_tool_block(mutation_items) if mutation_items else "```text\n[OK] Écritures appliquées et vérifiées.\n```"
        return (
            "C'est fait. J'ai appliqué la structure demandée et les écritures ont été vérifiées côté runtime.\n\n"
            "Changements appliqués:\n"
            f"{details}"
        )

    def _classify_tool_error(self, result: ToolResult) -> str:
        detail = str(result.error or "").lower()
        data_error = str((result.data or {}).get("error", "")).lower() if isinstance(result.data, dict) else ""
        combined = f"{detail}\n{data_error}"

        if any(marker in combined for marker in ("timeout", "temporarily unavailable", "please retry", "service unavailable")):
            return "transient"
        if any(marker in combined for marker in ("full access", "not allowed", "dangerous command blocked", "permission", "access denied")):
            return "permission"
        if any(marker in combined for marker in ("read first", "path escapes", "existing files blocked", "duplicate path", "file path is required", "content is required")):
            return "validation"
        if any(marker in combined for marker in ("analysis, not modification", "user asked for analysis")):
            return "intent"
        if any(marker in combined for marker in ("unknown tool", "no deferred tools matched")):
            return "missing"
        if any(marker in combined for marker in ("blocked", "verification failed", "still exists after deletion", "file not found after write")):
            return "blocked"
        return "generic"

    def _tool_error_followup_message(
        self,
        initial_message: str,
        tool_name: str,
        args: Dict[str, Any],
        result: ToolResult,
        failure_reason: str,
        repeated_failures: int,
    ) -> str:
        if repeated_failures >= 2:
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"The same {tool_name} call already failed {repeated_failures} times. "
                "Do not retry it unchanged. Either adjust the arguments, choose another tool, or explain the blocker clearly."
            )

        if failure_reason == "transient":
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"{tool_name} failed in a way that looks temporary. Retry at most once with adjusted arguments, "
                "or switch to another tool if the next step can continue without it."
            )
        if failure_reason == "permission":
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"{tool_name} is blocked by permissions or safety rules. Do not retry the same blocked call. "
                "Choose a safer tool path or explain what permission is missing."
            )
        if failure_reason == "validation":
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"{tool_name} failed because the request shape or file state is invalid. "
                "Read the target file, narrow the path, or fix the arguments before trying again."
            )
        if failure_reason == "intent":
            return (
                "[TOOL ERROR REMINDER]\n"
                "The current turn is read-only by intent. Stop trying to mutate files and either answer from context or wait for an explicit modification request."
            )
        if failure_reason == "missing":
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"{tool_name} is unavailable or did not match anything useful. "
                "Use one of the already available core tools, or choose a different deferred tool only if it is clearly needed."
            )
        if self.current_intent in {"write", "execute"}:
            return (
                f"[TOOL ERROR REMINDER]\n"
                f"{tool_name} failed. Stop repeating the same failing action. "
                "Move to the next concrete write step with edit_file/write_files/write_file/bash, or explain the blocker."
            )
        return (
            f"[TOOL ERROR REMINDER]\n"
            f"{tool_name} failed. Inspect the error once, adjust if needed, then continue from the available context instead of retrying blindly."
        )

    def _should_stop_after_tool_error(
        self,
        tool_name: str,
        result: ToolResult,
        failure_reason: str,
        repeated_failures: int,
        executed_tools: List[Dict],
    ) -> bool:
        if repeated_failures >= 3:
            return True
        if failure_reason in {"permission", "intent"} and repeated_failures >= 2:
            return True
        if failure_reason == "validation" and repeated_failures >= 2 and self.current_intent in {"write", "execute"}:
            return True

        consecutive_failures = 0
        for item in reversed(executed_tools or []):
            if item.get("success"):
                break
            consecutive_failures += 1
        if consecutive_failures >= 4 and not self._has_successful_mutation(executed_tools):
            return True
        return False

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

    def _should_continue_write_after_guard(self, tool_name: str, executed_tools: List[Dict]) -> bool:
        passive_guard_tools = {"list_files", "glob", "search", "tool_search", "write_todos", "bash"}
        return (
            self.current_intent in {"write", "execute"}
            and tool_name in passive_guard_tools
            and not self._has_attempted_mutation(executed_tools)
        )

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
        if self._should_surface_verified_write_progress(initial_message, executed_tools):
            return self._verified_write_progress_answer(initial_message, executed_tools)
        observed = executed_tools[-8:]
        if not observed:
            return (
                "J'ai stoppé le terminal avant qu'il parte en boucle. "
                "Aucun outil utile n'a encore produit de contexte; choisis un workspace puis demande "
                "par exemple: `analyse la structure`, `lis README.md`, ou `cherche les routes Flask`."
            )
        return (
            "J'ai stoppé la boucle d'outils avant de gaspiller plus de tokens.\n\n"
            "Dernières observations utiles:\n"
            + self._format_recent_tool_block(observed)
            + "\n\nDemande-moi une cible plus précise, ou relance `analyse mon repo` maintenant: "
            "JoyBoy utilisera le scan borné au lieu de refaire `ls/glob/pwd` en boucle."
        )

    def _tool_error_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        if self._should_surface_verified_write_progress(initial_message, executed_tools):
            return self._verified_write_progress_answer(initial_message, executed_tools)
        return (
            "J'ai stoppé la boucle après des erreurs outils répétées pour éviter de gaspiller plus de tours.\n\n"
            "Dernières actions observées:\n"
            + self._format_recent_tool_block(executed_tools[-8:])
            + "\n\nRelance avec une cible plus précise ou un autre angle d'action; JoyBoy gardera le contexte déjà collecté."
        )

    def _tool_batch_loop_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        if self._should_surface_verified_write_progress(initial_message, executed_tools):
            return self._verified_write_progress_answer(initial_message, executed_tools)
        details = self._format_recent_tool_block(executed_tools[-8:])
        return (
            "J'ai stoppé le terminal parce que le modèle répétait exactement le même lot d'outils.\n\n"
            "Contexte déjà collecté:\n"
            + details
            + "\n\nRelance avec une cible plus précise, ou demande-moi de continuer depuis un fichier/outil concret."
        )

    def _budget_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        if executed_tools:
            return (
                "J'ai coupé avant de relancer le modèle pour ne pas brûler plus de tokens.\n\n"
                "Dernières observations utiles:\n"
                + self._format_recent_tool_block(executed_tools[-6:], limit=6)
                + "\n\nRelance avec une cible plus précise ou demande un audit du workspace: "
                "JoyBoy utilisera un scan borné sans boucle d'exploration."
            )

        return (
            "J'ai coupé avant un nouvel appel modèle pour éviter une boucle coûteuse. "
            "Aucun outil n'avait encore produit de contexte utile; demande un audit du workspace "
            "ou cible un fichier précis."
        )

    def _iteration_limit_fallback_answer(self, initial_message: str, executed_tools: List[Dict]) -> str:
        if self._should_surface_verified_write_progress(initial_message, executed_tools):
            return self._verified_write_progress_answer(initial_message, executed_tools)
        if self.current_intent in {"write", "execute"} and not self._has_successful_mutation(executed_tools):
            return (
                "J'ai stoppé la boucle avant qu'elle continue à brûler des tokens sans appliquer de changement.\n\n"
                "Dernières actions observées:\n"
                + self._format_recent_tool_block(executed_tools[-8:])
                + "\n\nAucune écriture vérifiée n'a été faite. Relance la même demande: JoyBoy doit maintenant exposer "
                "`write_files`/`edit_file` directement et éviter `tool_search`/`write_todos` sur ce type de tâche."
            )
        return (
            "J'ai atteint la limite d'itérations, donc je rends l'état observé au lieu de repartir en boucle.\n\n"
            "Dernières actions observées:\n"
            + self._format_recent_tool_block(executed_tools[-8:])
        )

