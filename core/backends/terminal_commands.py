"""Native slash commands for JoyBoy Terminal."""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from core.agent_runtime import chat_with_cloud_model, is_cloud_model_name, runtime_event
from core.agent_runtime.output import mask_workspace_paths, truncate_middle


SUPPORTED_COMMAND_LOCALES = {"fr", "en", "es", "it"}


def _normalise_command_locale(locale: str | None) -> str:
    value = str(locale or "fr").strip().lower().replace("_", "-")
    if not value:
        return "fr"
    prefix = value.split("-", 1)[0]
    return prefix if prefix in SUPPORTED_COMMAND_LOCALES else "fr"


COMMAND_TEXT = {
    "fr": {
        "help_title": "Commandes JoyBoy Terminal",
        "help_intro": "Tape une commande slash dans un projet dev pour lancer un workflow précis.",
        "command_scope": "Terminal",
        "active": "Capacités actives",
        "mcp_none": "Aucun outil MCP actif pour l'instant.",
        "mcp_title": "Outils MCP",
        "tools_title": "Outils JoyBoy Terminal",
        "skills_title": "Skills locaux",
        "status_title": "Statut du workspace",
        "diff_title": "Diff du workspace",
        "skills_none": "Aucun skill de pack local actif.",
        "no_git": "Aucun repo Git détecté dans ce workspace.",
        "no_changes": "Aucun changement détecté.",
        "branch": "Branche",
        "latest_commit": "Dernier commit",
        "changes": "Changements",
        "compared_to": "Comparé à",
        "working_tree": "Working tree",
        "browser_note": "Contrôle navigateur/ordinateur : Playwright existe dans SignalAtlas/PerfAtlas, mais il n'est pas encore exposé comme outil terminal général.",
        "cap_workspace": "Workspace: lecture, recherche, édition vérifiée, shell sécurisé.",
        "cap_web_active": "Web: web_search + web_fetch.",
        "cap_web_missing": "Web: non configuré.",
        "cap_mcp": "MCP: {count} outil(s) disponible(s).",
        "cap_skills": "Skills locaux: {count}.",
        "ultra_fallback": "Relance avec un modèle cloud pour l'arbitrage LLM complet; voici la synthèse locale des passes réalisées.",
        "verify_skipped": "Aucune commande standard de test/lint/build détectée.",
        "no_high_confidence": "Aucun bug haute confiance n'a été confirmé par les passes locales.",
        "final_blocker": "La synthèse modèle a échoué; je te rends les éléments vérifiés.",
        "commands": [
            ("/help", "Affiche les commandes et les capacités disponibles."),
            ("/status", "Affiche l'état Git, la branche, le dernier commit et les changements."),
            ("/diff", "Résume les fichiers modifiés et le diff de la branche courante."),
            ("/ultrareview [focus]", "Revue profonde multi-angle du repo ou de la branche courante."),
            ("/mcp", "Liste les outils MCP connectés et ceux découverts par les packs."),
            ("/tools", "Affiche les outils terminal actifs, y compris web_search/web_fetch."),
            ("/skills", "Liste les skills locaux importés via les packs JoyBoy."),
            ("/auto <demande>", "Autorise une tâche longue multi-étapes avec plan de travail."),
        ],
    },
    "en": {
        "help_title": "JoyBoy Terminal Commands",
        "help_intro": "Type a slash command inside a dev project to launch a precise workflow.",
        "command_scope": "Terminal",
        "active": "Active capabilities",
        "mcp_none": "No active MCP tools yet.",
        "mcp_title": "MCP Tools",
        "tools_title": "JoyBoy Terminal Tools",
        "skills_title": "Local Skills",
        "status_title": "Workspace Status",
        "diff_title": "Workspace Diff",
        "skills_none": "No active local pack skill.",
        "no_git": "No Git repository detected in this workspace.",
        "no_changes": "No changes detected.",
        "branch": "Branch",
        "latest_commit": "Latest commit",
        "changes": "Changes",
        "compared_to": "Compared to",
        "working_tree": "Working tree",
        "browser_note": "Browser/computer control: Playwright exists in SignalAtlas/PerfAtlas, but it is not exposed yet as a general terminal tool.",
        "cap_workspace": "Workspace: reading, search, verified edits, safe shell.",
        "cap_web_active": "Web: web_search + web_fetch.",
        "cap_web_missing": "Web: not configured.",
        "cap_mcp": "MCP: {count} available tool(s).",
        "cap_skills": "Local skills: {count}.",
        "ultra_fallback": "Run again with a cloud model for the full LLM arbitration; here is the local synthesis of completed passes.",
        "verify_skipped": "No standard test/lint/build command detected.",
        "no_high_confidence": "No high-confidence bug was confirmed by the local passes.",
        "final_blocker": "The model synthesis failed; here are the verified review materials.",
        "commands": [
            ("/help", "Show available commands and capabilities."),
            ("/status", "Show Git state, branch, latest commit, and changes."),
            ("/diff", "Summarize changed files and the current branch diff."),
            ("/ultrareview [focus]", "Run a deep multi-angle review of the repo or current branch."),
            ("/mcp", "List connected MCP tools and pack-discovered tools."),
            ("/tools", "Show active terminal tools, including web_search/web_fetch."),
            ("/skills", "List local skills imported through JoyBoy packs."),
            ("/auto <request>", "Allow a long multi-step task with a visible work plan."),
        ],
    },
    "es": {
        "help_title": "Comandos de JoyBoy Terminal",
        "help_intro": "Escribe un comando slash dentro de un proyecto dev para lanzar un workflow preciso.",
        "command_scope": "Terminal",
        "active": "Capacidades activas",
        "mcp_none": "No hay herramientas MCP activas por ahora.",
        "mcp_title": "Herramientas MCP",
        "tools_title": "Herramientas de JoyBoy Terminal",
        "skills_title": "Skills locales",
        "status_title": "Estado del workspace",
        "diff_title": "Diff del workspace",
        "skills_none": "No hay skills de packs locales activos.",
        "no_git": "No se detectó ningún repositorio Git en este workspace.",
        "no_changes": "No se detectaron cambios.",
        "branch": "Rama",
        "latest_commit": "Último commit",
        "changes": "Cambios",
        "compared_to": "Comparado con",
        "working_tree": "Working tree",
        "browser_note": "Control de navegador/ordenador: Playwright existe en SignalAtlas/PerfAtlas, pero aún no está expuesto como herramienta terminal general.",
        "cap_workspace": "Workspace: lectura, búsqueda, ediciones verificadas, shell seguro.",
        "cap_web_active": "Web: web_search + web_fetch.",
        "cap_web_missing": "Web: no configurado.",
        "cap_mcp": "MCP: {count} herramienta(s) disponible(s).",
        "cap_skills": "Skills locales: {count}.",
        "ultra_fallback": "Reintenta con un modelo cloud para el arbitraje LLM completo; aquí va la síntesis local de las pasadas realizadas.",
        "verify_skipped": "No se detectó ningún comando estándar de test/lint/build.",
        "no_high_confidence": "Las pasadas locales no confirmaron ningún bug de alta confianza.",
        "final_blocker": "La síntesis del modelo falló; devuelvo los elementos verificados.",
        "commands": [
            ("/help", "Muestra los comandos y capacidades disponibles."),
            ("/status", "Muestra estado Git, rama, último commit y cambios."),
            ("/diff", "Resume archivos modificados y diff de la rama actual."),
            ("/ultrareview [focus]", "Ejecuta una revisión profunda multiángulo del repo o rama actual."),
            ("/mcp", "Lista herramientas MCP conectadas y descubiertas por packs."),
            ("/tools", "Muestra herramientas terminal activas, incluido web_search/web_fetch."),
            ("/skills", "Lista skills locales importadas vía packs JoyBoy."),
            ("/auto <solicitud>", "Permite una tarea larga multietapa con plan visible."),
        ],
    },
    "it": {
        "help_title": "Comandi JoyBoy Terminal",
        "help_intro": "Digita un comando slash in un progetto dev per avviare un workflow preciso.",
        "command_scope": "Terminal",
        "active": "Capacità attive",
        "mcp_none": "Nessuno strumento MCP attivo per ora.",
        "mcp_title": "Strumenti MCP",
        "tools_title": "Strumenti JoyBoy Terminal",
        "skills_title": "Skill locali",
        "status_title": "Stato workspace",
        "diff_title": "Diff workspace",
        "skills_none": "Nessuna skill di pack locale attiva.",
        "no_git": "Nessun repository Git rilevato in questo workspace.",
        "no_changes": "Nessuna modifica rilevata.",
        "branch": "Branch",
        "latest_commit": "Ultimo commit",
        "changes": "Modifiche",
        "compared_to": "Confrontato con",
        "working_tree": "Working tree",
        "browser_note": "Controllo browser/computer: Playwright esiste in SignalAtlas/PerfAtlas, ma non è ancora esposto come strumento terminale generale.",
        "cap_workspace": "Workspace: lettura, ricerca, modifiche verificate, shell sicura.",
        "cap_web_active": "Web: web_search + web_fetch.",
        "cap_web_missing": "Web: non configurato.",
        "cap_mcp": "MCP: {count} strumento/i disponibile/i.",
        "cap_skills": "Skill locali: {count}.",
        "ultra_fallback": "Rilancia con un modello cloud per l'arbitraggio LLM completo; ecco la sintesi locale dei passaggi eseguiti.",
        "verify_skipped": "Nessun comando standard di test/lint/build rilevato.",
        "no_high_confidence": "Nessun bug ad alta confidenza è stato confermato dai passaggi locali.",
        "final_blocker": "La sintesi del modello è fallita; restituisco gli elementi verificati.",
        "commands": [
            ("/help", "Mostra comandi e capacità disponibili."),
            ("/status", "Mostra stato Git, branch, ultimo commit e modifiche."),
            ("/diff", "Riassume file modificati e diff del branch corrente."),
            ("/ultrareview [focus]", "Esegue una revisione profonda multi-angolo del repo o ramo corrente."),
            ("/mcp", "Elenca strumenti MCP connessi e scoperti dai pack."),
            ("/tools", "Mostra gli strumenti terminal attivi, incluso web_search/web_fetch."),
            ("/skills", "Elenca skill locali importate tramite pack JoyBoy."),
            ("/auto <richiesta>", "Consente un'attività lunga multi-step con piano visibile."),
        ],
    },
}


class TerminalSlashCommandsMixin:
    """Handle built-in terminal slash commands without spending a model turn."""

    TERMINAL_SLASH_COMMANDS = {"help", "status", "diff", "mcp", "tools", "skills", "ultrareview"}

    def _parse_terminal_slash_command(self, message: str) -> Tuple[str, str]:
        text = str(message or "").strip()
        if not text.startswith("/"):
            return "", ""
        head, _, tail = text.partition(" ")
        command = head.lstrip("/").strip().lower()
        return command, tail.strip()

    def _is_terminal_slash_command(self, message: str) -> bool:
        command, _ = self._parse_terminal_slash_command(message)
        return command in self.TERMINAL_SLASH_COMMANDS

    def _terminal_command_texts(self, locale: str | None) -> Dict[str, Any]:
        return COMMAND_TEXT[_normalise_command_locale(locale)]

    def _run_terminal_slash_command(
        self,
        command: str,
        args: str,
        workspace_path: str,
        model: str,
        reasoning_effort: str | None = None,
        locale: str | None = None,
    ) -> Generator[Dict[str, Any], None, None]:
        if command == "help":
            yield from self._run_terminal_help_command(workspace_path, locale)
            return
        if command == "status":
            yield from self._run_terminal_status_command(workspace_path, locale)
            return
        if command == "diff":
            yield from self._run_terminal_diff_command(workspace_path, locale)
            return
        if command == "mcp":
            yield from self._run_terminal_mcp_command(locale)
            return
        if command == "tools":
            yield from self._run_terminal_tools_command(locale)
            return
        if command == "skills":
            yield from self._run_terminal_skills_command(locale)
            return
        if command == "ultrareview":
            yield from self._run_ultrareview_command(
                focus=args,
                workspace_path=workspace_path,
                model=model,
                reasoning_effort=reasoning_effort,
                locale=locale,
            )

    def _finish_static_command(self, text: str) -> Generator[Dict[str, Any], None, None]:
        yield runtime_event(
            "intent",
            intent="review",
            read_only=True,
            autonomous=False,
            permission_mode=self.permission_mode,
        )
        yield runtime_event("content", text=text, token_stats={})
        yield runtime_event("done", full_response=text, token_stats={"prompt_tokens": 0, "completion_tokens": 0, "total": 0})

    def _run_terminal_help_command(self, workspace_path: str, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        catalog = self._build_terminal_help_catalog(workspace_path, locale)
        yield runtime_event(
            "intent",
            intent="question",
            read_only=True,
            autonomous=False,
            permission_mode=self.permission_mode,
        )
        yield runtime_event("command_catalog", catalog=catalog)
        yield runtime_event("done", full_response="", token_stats={"prompt_tokens": 0, "completion_tokens": 0, "total": 0})

    def _run_terminal_mcp_command(self, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        text = self._build_terminal_mcp_text(locale)
        yield from self._finish_static_command(text)

    def _run_terminal_tools_command(self, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        text = self._build_terminal_tools_text(locale)
        yield from self._finish_static_command(text)

    def _run_terminal_skills_command(self, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        text = self._build_terminal_skills_text(locale)
        yield from self._finish_static_command(text)

    def _run_terminal_status_command(self, workspace_path: str, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        texts = self._terminal_command_texts(locale)
        if not (Path(workspace_path or "") / ".git").exists():
            text = f"## {texts['status_title']}\n\n{texts['no_git']}"
            yield from self._finish_static_command(text)
            return

        yield runtime_event(
            "intent",
            intent="review",
            read_only=True,
            autonomous=False,
            permission_mode=self.permission_mode,
        )
        status = yield from self._execute_and_emit_tool("bash", {"command": "git status --short --branch"}, workspace_path)
        latest = yield from self._execute_and_emit_tool("bash", {"command": "git log -1 --oneline --decorate"}, workspace_path)
        stat = yield from self._execute_and_emit_tool("bash", {"command": "git diff --stat HEAD"}, workspace_path)

        text = self._build_terminal_status_text(
            status.data if status else {},
            latest.data if latest else {},
            stat.data if stat else {},
            locale,
        )
        yield runtime_event("content", text=text, token_stats={})
        yield runtime_event("done", full_response=text, token_stats={"prompt_tokens": 0, "completion_tokens": 0, "total": 0})

    def _run_terminal_diff_command(self, workspace_path: str, locale: str | None) -> Generator[Dict[str, Any], None, None]:
        texts = self._terminal_command_texts(locale)
        if not (Path(workspace_path or "") / ".git").exists():
            text = f"## {texts['diff_title']}\n\n{texts['no_git']}"
            yield from self._finish_static_command(text)
            return

        yield runtime_event(
            "intent",
            intent="review",
            read_only=True,
            autonomous=False,
            permission_mode=self.permission_mode,
        )
        default_ref = self._detect_git_default_ref(workspace_path)
        name_status = yield from self._execute_and_emit_tool("bash", {"command": "git diff --name-status HEAD"}, workspace_path)
        stat = yield from self._execute_and_emit_tool("bash", {"command": "git diff --stat HEAD"}, workspace_path)
        branch_name_status = None
        branch_stat = None
        if default_ref:
            branch_name_status = yield from self._execute_and_emit_tool("bash", {"command": f"git diff --name-status {default_ref}...HEAD"}, workspace_path)
            branch_stat = yield from self._execute_and_emit_tool("bash", {"command": f"git diff --stat {default_ref}...HEAD"}, workspace_path)

        text = self._build_terminal_diff_text(
            name_status.data if name_status else {},
            stat.data if stat else {},
            branch_name_status.data if branch_name_status else {},
            branch_stat.data if branch_stat else {},
            default_ref,
            locale,
        )
        yield runtime_event("content", text=text, token_stats={})
        yield runtime_event("done", full_response=text, token_stats={"prompt_tokens": 0, "completion_tokens": 0, "total": 0})

    def _build_terminal_help_text(self, workspace_path: str, locale: str | None) -> str:
        catalog = self._build_terminal_help_catalog(workspace_path, locale)
        commands = "\n".join(f"- `{item['name']}` - {item['description']}" for item in catalog["commands"])
        active = [f"- {item}" for item in catalog["capabilities"]]
        return (
            f"## {catalog['title']}\n\n"
            f"{catalog['intro']}\n\n"
            f"{commands}\n\n"
            f"### {self._terminal_command_texts(locale)['active']}\n"
            + "\n".join(active)
        )

    def _build_terminal_help_catalog(self, workspace_path: str, locale: str | None) -> Dict[str, Any]:
        texts = self._terminal_command_texts(locale)
        self._refresh_dynamic_tool_registry()
        tools = self.tool_registry.public_tools()
        mcp_tools = [tool for tool in tools if "mcp" in (tool.get("tags") or [])]
        web_active = any(tool.get("name") in {"web_search", "web_fetch"} for tool in tools)
        skill_count = self._pack_skill_count()
        capabilities = [
            texts["cap_workspace"],
            texts["cap_web_active"] if web_active else texts["cap_web_missing"],
            texts["cap_mcp"].format(count=len(mcp_tools)),
            texts["cap_skills"].format(count=skill_count),
            texts["browser_note"],
        ]
        return {
            "title": texts["help_title"],
            "intro": texts["help_intro"],
            "scope": texts["command_scope"],
            "commands": [
                {"name": name, "description": desc, "scope": texts["command_scope"]}
                for name, desc in texts["commands"]
            ],
            "capabilities_title": texts["active"],
            "capabilities": capabilities,
        }

    def _build_terminal_mcp_text(self, locale: str | None) -> str:
        texts = self._terminal_command_texts(locale)
        self._refresh_dynamic_tool_registry()
        tools = [
            tool
            for tool in self.tool_registry.public_tools()
            if "mcp" in (tool.get("tags") or [])
        ]
        if not tools:
            return f"## {texts['mcp_title']}\n\n{texts['mcp_none']}"
        lines = [f"## {texts['mcp_title']}", ""]
        for tool in tools[:40]:
            tags = [tag for tag in tool.get("tags", []) if tag != "mcp"]
            server = tags[0] if tags else "external"
            description = truncate_middle(str(tool.get("description", "")), 140)
            lines.append(f"- `{tool.get('name')}` ({server}) - {description}")
        if len(tools) > 40:
            lines.append(f"- ... +{len(tools) - 40}")
        return "\n".join(lines)

    def _build_terminal_tools_text(self, locale: str | None) -> str:
        texts = self._terminal_command_texts(locale)
        tools = self.tool_registry.public_tools()
        grouped: Dict[str, List[str]] = {}
        for tool in tools:
            risk = str(tool.get("risk") or "other")
            grouped.setdefault(risk, []).append(str(tool.get("name") or ""))
        lines = [f"## {texts['tools_title']}", ""]
        for risk in sorted(grouped):
            names = ", ".join(f"`{name}`" for name in sorted(grouped[risk]) if name)
            lines.append(f"- {risk}: {names}")
        return "\n".join(lines)

    def _build_terminal_skills_text(self, locale: str | None) -> str:
        texts = self._terminal_command_texts(locale)
        skills = self._pack_skills()
        if not skills:
            return f"## {texts['skills_title']}\n\n{texts['skills_none']}"
        lines = [f"## {texts['skills_title']}", ""]
        for skill in skills[:40]:
            summary = truncate_middle(str(skill.get("summary", "")), 140)
            suffix = f" - {summary}" if summary else ""
            lines.append(f"- `{skill.get('id')}` - {skill.get('name', 'Skill')}{suffix}")
        if len(skills) > 40:
            lines.append(f"- ... +{len(skills) - 40}")
        return "\n".join(lines)

    def _build_terminal_status_text(self, status: Dict[str, Any], latest: Dict[str, Any], stat: Dict[str, Any], locale: str | None) -> str:
        texts = self._terminal_command_texts(locale)
        status_output = str(status.get("output") or "").strip()
        latest_output = str(latest.get("output") or "").strip()
        stat_output = str(stat.get("output") or "").strip()
        branch = ""
        changes: List[str] = []
        for line in status_output.splitlines():
            clean = line.strip()
            if clean.startswith("##"):
                branch = clean.lstrip("# ").strip()
            elif clean:
                changes.append(clean)
        lines = [f"## {texts['status_title']}", ""]
        if branch:
            lines.append(f"- {texts['branch']}: `{truncate_middle(branch, 120)}`")
        if latest_output:
            lines.append(f"- {texts['latest_commit']}: `{truncate_middle(latest_output.splitlines()[0], 160)}`")
        lines.append(f"- {texts['changes']}: {len(changes) if changes else texts['no_changes']}")
        if changes:
            lines.append("")
            lines.append(f"### {texts['working_tree']}")
            lines.extend(f"- `{truncate_middle(item, 180)}`" for item in changes[:20])
            if len(changes) > 20:
                lines.append(f"- ... +{len(changes) - 20}")
        if stat_output:
            lines.append("")
            lines.append("```text")
            lines.append(truncate_middle(stat_output, 1200))
            lines.append("```")
        return "\n".join(lines).strip()

    def _build_terminal_diff_text(
        self,
        name_status: Dict[str, Any],
        stat: Dict[str, Any],
        branch_name_status: Dict[str, Any],
        branch_stat: Dict[str, Any],
        default_ref: str,
        locale: str | None,
    ) -> str:
        texts = self._terminal_command_texts(locale)
        working_files = self._git_changed_file_lines(name_status)
        branch_files = self._git_changed_file_lines(branch_name_status)
        stat_output = str(stat.get("output") or "").strip()
        branch_stat_output = str(branch_stat.get("output") or "").strip()
        lines = [f"## {texts['diff_title']}", ""]
        lines.append(f"- {texts['working_tree']}: {len(working_files) if working_files else texts['no_changes']}")
        if default_ref:
            lines.append(f"- {texts['compared_to']} `{default_ref}`: {len(branch_files) if branch_files else texts['no_changes']}")
        if working_files:
            lines.append("")
            lines.append(f"### {texts['working_tree']}")
            lines.extend(f"- `{truncate_middle(item, 180)}`" for item in working_files[:25])
            if len(working_files) > 25:
                lines.append(f"- ... +{len(working_files) - 25}")
        if stat_output:
            lines.append("")
            lines.append("```text")
            lines.append(truncate_middle(stat_output, 1600))
            lines.append("```")
        if default_ref and branch_files:
            lines.append("")
            lines.append(f"### {texts['compared_to']} `{default_ref}`")
            lines.extend(f"- `{truncate_middle(item, 180)}`" for item in branch_files[:25])
            if len(branch_files) > 25:
                lines.append(f"- ... +{len(branch_files) - 25}")
        if branch_stat_output:
            lines.append("")
            lines.append("```text")
            lines.append(truncate_middle(branch_stat_output, 1600))
            lines.append("```")
        return "\n".join(lines).strip()

    def _git_changed_file_lines(self, result: Dict[str, Any] | None) -> List[str]:
        output = str((result or {}).get("output") or "").strip()
        lines: List[str] = []
        for line in output.splitlines():
            clean = line.strip()
            if clean and not clean.startswith("[STDERR]"):
                lines.append(clean)
        return lines

    def _pack_skills(self) -> List[Dict[str, Any]]:
        try:
            from core.infra.packs import get_pack_skills

            return list(get_pack_skills() or [])
        except Exception:
            return []

    def _pack_skill_count(self) -> int:
        return len(self._pack_skills())

    def _run_ultrareview_command(
        self,
        focus: str,
        workspace_path: str,
        model: str,
        reasoning_effort: str | None = None,
        locale: str | None = None,
    ) -> Generator[Dict[str, Any], None, None]:
        texts = self._terminal_command_texts(locale)
        self.current_intent = "read"
        self.write_blocked = False
        self._active_read_result_signatures = set()
        self._active_execution_journal = []
        self._reset_deferred_tools()
        self._active_promoted_tool_names.update({"delegate_subagent", "web_search", "web_fetch"})
        review_reasoning_effort = self._ultrareview_reasoning_effort(reasoning_effort)

        yield runtime_event(
            "intent",
            intent="read",
            read_only=True,
            autonomous=False,
            permission_mode=self.permission_mode,
        )

        todo_args = {
            "todos": [
                {"id": "scope", "content": "Déterminer le périmètre git", "activeForm": "Détermination du périmètre git", "status": "in_progress"},
                {"id": "reviewers", "content": "Lancer les reviewers spécialisés", "activeForm": "Lancement des reviewers spécialisés", "status": "pending"},
                {"id": "verify", "content": "Exécuter une vérification standard", "activeForm": "Vérification standard", "status": "pending"},
                {"id": "synthesis", "content": "Croiser et vérifier les findings", "activeForm": "Croisement des findings", "status": "pending"},
            ]
        }
        yield from self._execute_and_emit_tool("write_todos", todo_args, workspace_path)

        review_materials: List[Dict[str, Any]] = []
        git_commands = []
        if (Path(workspace_path or "") / ".git").exists():
            default_ref = self._detect_git_default_ref(workspace_path)
            git_commands = [
                "git status --short",
                "git log --oneline --decorate -5",
            ]
            if default_ref:
                git_commands.insert(1, f"git diff --name-only {default_ref}...HEAD")
                git_commands.insert(2, f"git diff --stat {default_ref}...HEAD")
            git_commands.insert(-1, "git diff --name-only HEAD")
            git_commands.insert(-1, "git diff --stat HEAD")
        for command in git_commands:
            result = yield from self._execute_and_emit_tool("bash", {"command": command}, workspace_path)
            review_materials.append({"kind": "git", "command": command, "result": result.data if result else {}})
        if not git_commands:
            review_materials.append({"kind": "git", "summary": "No .git directory detected; reviewing the workspace files directly."})

        changed_paths = self._extract_changed_paths(review_materials)
        todo_args["todos"][0]["status"] = "completed"
        todo_args["todos"][1]["status"] = "in_progress"
        yield from self._execute_and_emit_tool("write_todos", todo_args, workspace_path)

        path_hint = ", ".join(changed_paths[:18]) if changed_paths else "important entrypoints, configs, tests, routes, UI surfaces"
        focus_hint = focus.strip() or "current branch, staged changes, and working tree"
        git_review_materials = [item for item in review_materials if item.get("kind") == "git"]
        reviewer_labels = self._ultrareview_progress_labels(locale)
        reviewer_tasks = [
            (
                reviewer_labels["correctness"],
                "Find runtime bugs, broken contracts, logic regressions, missing edge cases, and unsafe assumptions. "
                f"Focus: {focus_hint}. Changed/likely files: {path_hint}. Return evidence and exact paths.",
            ),
            (
                reviewer_labels["security"],
                "Find security, secrets, auth, injection, dependency, permission, and unsafe shell/process risks. "
                f"Focus: {focus_hint}. Changed/likely files: {path_hint}. Return only actionable evidence.",
            ),
            (
                reviewer_labels["quality"],
                "Find test/build gaps, API/UI mismatches, dead code, config mistakes, i18n misses, and maintainability risks. "
                f"Focus: {focus_hint}. Changed/likely files: {path_hint}. Return concrete file-backed observations.",
            ),
        ]
        for index, (label, task) in enumerate(reviewer_tasks, start=1):
            result = yield from self._execute_and_emit_tool(
                "delegate_subagent",
                {"agent_type": "code_explorer", "task": f"{label}: {task}", "max_files": 16},
                workspace_path,
            )
            explorer_material = {"kind": "reviewer", "label": label, "result": result.data if result else {}}
            review_materials.append(explorer_material)
            if is_cloud_model_name(model):
                reviewer_text = yield from self._run_ultrareview_llm_reviewer(
                    label=label,
                    task=task,
                    review_materials=[*git_review_materials, explorer_material],
                    workspace_path=workspace_path,
                    model=model,
                    reasoning_effort=review_reasoning_effort,
                    locale=locale,
                    iteration=index,
                )
                review_materials.append({
                    "kind": "llm_reviewer",
                    "label": label,
                    "summary": reviewer_text,
                })

        todo_args["todos"][1]["status"] = "completed"
        todo_args["todos"][2]["status"] = "in_progress"
        yield from self._execute_and_emit_tool("write_todos", todo_args, workspace_path)

        verifier_command = self._pick_ultrareview_verifier_command(workspace_path)
        if verifier_command:
            result = yield from self._execute_and_emit_tool(
                "delegate_subagent",
                {
                    "agent_type": "verifier",
                    "task": "Run one standard repository verification for ultrareview.",
                    "command": verifier_command,
                    "timeout_seconds": 180,
                },
                workspace_path,
            )
            review_materials.append({"kind": "verifier", "command": verifier_command, "result": result.data if result else {}})
        else:
            review_materials.append({"kind": "verifier", "summary": texts["verify_skipped"]})

        todo_args["todos"][2]["status"] = "completed"
        todo_args["todos"][3]["status"] = "in_progress"
        yield from self._execute_and_emit_tool("write_todos", todo_args, workspace_path)

        final_text = ""
        if is_cloud_model_name(model):
            final_text = yield from self._run_ultrareview_model_synthesis(
                review_materials=review_materials,
                workspace_path=workspace_path,
                model=model,
                reasoning_effort=review_reasoning_effort,
                locale=locale,
            )

        if not final_text.strip():
            final_text = self._build_ultrareview_fallback_report(review_materials, workspace_path, locale)
            yield runtime_event("content", text=final_text, token_stats={})

        yield runtime_event(
            "done",
            full_response=final_text,
            token_stats={"prompt_tokens": 0, "completion_tokens": 0, "total": 0},
        )

    def _ultrareview_progress_labels(self, locale: str | None) -> Dict[str, str]:
        labels = {
            "fr": {
                "correctness": "Reviewer correction",
                "security": "Reviewer sécurité",
                "quality": "Reviewer qualité",
                "final": "Synthèse finale Ultrareview",
                "suffix": "revue LLM",
            },
            "en": {
                "correctness": "Correctness reviewer",
                "security": "Security reviewer",
                "quality": "Quality reviewer",
                "final": "Final Ultrareview synthesis",
                "suffix": "LLM review",
            },
            "es": {
                "correctness": "Revisor de corrección",
                "security": "Revisor de seguridad",
                "quality": "Revisor de calidad",
                "final": "Síntesis final Ultrareview",
                "suffix": "revisión LLM",
            },
            "it": {
                "correctness": "Revisore correttezza",
                "security": "Revisore sicurezza",
                "quality": "Revisore qualità",
                "final": "Sintesi finale Ultrareview",
                "suffix": "revisione LLM",
            },
        }
        return labels[_normalise_command_locale(locale)]

    def _ultrareview_reasoning_effort(self, reasoning_effort: str | None) -> str:
        value = str(reasoning_effort or "").strip().lower().replace("-", "").replace("_", "")
        if value in {"xhigh", "extra", "extrahigh", "veryhigh", "tresapprofondi", "tresprofond"}:
            return "xhigh"
        if value in {"high", "eleve", "elevé"}:
            return "high"
        if value in {"medium", "moyen"}:
            return "high"
        if value in {"low", "bas"}:
            return "medium"
        return "high"

    def _run_ultrareview_llm_reviewer(
        self,
        label: str,
        task: str,
        review_materials: List[Dict[str, Any]],
        workspace_path: str,
        model: str,
        reasoning_effort: str,
        locale: str | None,
        iteration: int,
    ) -> Generator[Dict[str, Any], None, str]:
        language = {
            "fr": "French",
            "en": "English",
            "es": "Spanish",
            "it": "Italian",
        }[_normalise_command_locale(locale)]
        context = self._format_ultrareview_materials(review_materials, workspace_path)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an independent JoyBoy Ultrareview subagent. "
                    "You are read-only and must not suggest broad rewrites. "
                    "Find concrete bugs, broken contracts, security risks, missing verification, or user-visible regressions. "
                    "Use exact file/path evidence from the provided materials. "
                    "If evidence is insufficient, label it as a residual risk. "
                    f"Write concise notes in {language}."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Reviewer role: {label}\n"
                    f"Mission: {task}\n\n"
                    "Materials:\n"
                    f"{context}\n\n"
                    "Return only this reviewer's useful output:\n"
                    "- Confirmed findings, if any, with severity and evidence.\n"
                    "- Residual risks / checks, only if useful.\n"
                    "If no confirmed finding exists, say that explicitly in one sentence."
                ),
            },
        ]
        progress_suffix = self._ultrareview_progress_labels(locale)["suffix"]
        progress_label = f"{label} · {progress_suffix}"
        yield runtime_event(
            "model_call",
            model=model,
            provider="cloud",
            iteration=iteration,
            tools_count=0,
            estimated_prompt_tokens=max(1, len(context) // 4),
            context_kind="ultrareview_reviewer",
            label=progress_label,
        )

        holder: Dict[str, Any] = {}

        def _call_model() -> None:
            try:
                holder["response"] = chat_with_cloud_model(
                    model,
                    messages=messages,
                    tools=[],
                    max_tokens=1400,
                    temperature=0.1,
                    reasoning_effort=reasoning_effort,
                )
            except BaseException as exc:
                holder["error"] = exc

        worker = threading.Thread(target=_call_model, daemon=True)
        worker.start()
        started_at = time.monotonic()
        last_progress = started_at
        while worker.is_alive():
            worker.join(timeout=0.25)
            if not worker.is_alive():
                break
            now = time.monotonic()
            elapsed = int(now - started_at)
            if elapsed >= 4 and now - last_progress >= 6:
                last_progress = now
                yield runtime_event(
                    "model_progress",
                    model=model,
                    provider="cloud",
                    iteration=iteration,
                    elapsed_seconds=elapsed,
                    stage=self._model_progress_stage(elapsed),
                    context_kind="ultrareview_reviewer",
                    label=progress_label,
                )
        worker.join(timeout=0)
        if holder.get("error"):
            return f"{label}: reviewer failed ({holder['error']})."
        response = holder.get("response") or {}
        message = response.get("message", {}) if isinstance(response, dict) else {}
        text = str(message.get("content") or "").strip()
        return text or f"{label}: no reviewer output."

    def _execute_and_emit_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        workspace_path: str,
    ) -> Generator[Dict[str, Any], None, Optional[Any]]:
        yield runtime_event("tool_call", name=tool_name, args=args)
        started_at = time.time()
        holder: Dict[str, Any] = {}

        def _run_tool() -> None:
            try:
                holder["result"] = self.execute_tool(tool_name, args, workspace_path)
            except BaseException as exc:
                holder["error"] = exc

        thread = threading.Thread(target=_run_tool, daemon=True)
        thread.start()
        last_progress = -1
        while thread.is_alive():
            thread.join(timeout=0.5)
            if not thread.is_alive():
                break
            elapsed = int(time.time() - started_at)
            if elapsed >= 2 and elapsed > last_progress:
                last_progress = elapsed
                yield runtime_event("tool_progress", name=tool_name, args=args, elapsed_seconds=elapsed)
        if holder.get("error"):
            raise holder["error"]
        result = holder.get("result")
        if result is None:
            return None
        executed_summary = self._summarize_executed_tool(tool_name, args, result)
        self._record_execution_journal(tool_name, args, result, executed_summary)
        yield runtime_event("tool_result", result={
            "success": result.success,
            "tool_name": result.tool_name,
            "data": result.data,
            "error": result.error,
            "write_blocked": self.write_blocked,
        })
        return result

    def _extract_changed_paths(self, review_materials: List[Dict[str, Any]]) -> List[str]:
        paths: List[str] = []
        for item in review_materials:
            result = item.get("result") if isinstance(item, dict) else {}
            output = str((result or {}).get("output") or "")
            for line in output.splitlines():
                clean = line.strip()
                if not clean:
                    continue
                if re.match(r"^[ MADRCU?!]{1,2}\s+", clean):
                    clean = clean[2:].strip()
                if re.search(r"\.(py|js|jsx|ts|tsx|css|html|json|md|yml|yaml|toml|go|rs|java|cs|php|rb|sql)$", clean, re.I):
                    clean = clean.strip('"')
                    if clean not in paths:
                        paths.append(clean)
        return paths[:30]

    def _detect_git_default_ref(self, workspace_path: str) -> str:
        root = Path(workspace_path or "")
        if not root.exists():
            return ""
        checks = [
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
            ["git", "rev-parse", "--verify", "origin/main"],
            ["git", "rev-parse", "--verify", "origin/master"],
            ["git", "rev-parse", "--verify", "main"],
            ["git", "rev-parse", "--verify", "master"],
        ]
        for argv in checks:
            try:
                completed = subprocess.run(
                    argv,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    shell=False,
                )
            except Exception:
                continue
            if completed.returncode != 0:
                continue
            output = (completed.stdout or "").strip().splitlines()[0:1]
            if argv[1] == "symbolic-ref" and output:
                return output[0]
            if len(argv) >= 4:
                return argv[-1]
        return ""

    def _pick_ultrareview_verifier_command(self, workspace_path: str) -> str:
        root = Path(workspace_path or "")
        package_json = root / "package.json"
        if package_json.is_file():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
                scripts = package.get("scripts") if isinstance(package, dict) else {}
                if isinstance(scripts, dict):
                    for name, command in (
                        ("test", "npm test"),
                        ("lint", "npm run lint"),
                        ("typecheck", "npm run typecheck"),
                        ("build", "npm run build"),
                    ):
                        if name in scripts:
                            return command
            except Exception:
                return ""
        if (root / "tests").is_dir():
            return "python -m unittest discover -s tests"
        if (root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file():
            return "python -m unittest discover -s tests"
        return ""

    def _run_ultrareview_model_synthesis(
        self,
        review_materials: List[Dict[str, Any]],
        workspace_path: str,
        model: str,
        reasoning_effort: str | None,
        locale: str | None,
    ) -> Generator[Dict[str, Any], None, str]:
        language = {
            "fr": "French",
            "en": "English",
            "es": "Spanish",
            "it": "Italian",
        }[_normalise_command_locale(locale)]
        context = self._format_ultrareview_materials(review_materials, workspace_path)
        progress_label = self._ultrareview_progress_labels(locale)["final"]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are JoyBoy Ultrareview, a strict code-review coordinator. "
                    "You aggregate independent reviewer passes and verifier output. "
                    "Report findings first, ordered by severity. Only include actionable bugs or risks grounded in evidence. "
                    "Avoid style-only advice. If evidence is weak, say it is a residual risk instead of a confirmed bug. "
                    "Do not mention hidden absolute host paths. "
                    f"Answer in {language}."
                ),
            },
            {
                "role": "user",
                "content": (
                    "ULTRAREVIEW MATERIALS:\n"
                    f"{context}\n\n"
                    "Write a compact but useful review:\n"
                    "1. Confirmed findings with severity, file/path evidence, and why it matters.\n"
                    "2. Verification result.\n"
                    "3. Residual risks / next checks.\n"
                    "If no confirmed bug exists, say that clearly and keep the answer short."
                ),
            },
        ]
        yield runtime_event(
            "model_call",
            model=model,
            provider="cloud",
            iteration=1,
            tools_count=0,
            estimated_prompt_tokens=max(1, len(context) // 4),
            context_kind="ultrareview_synthesis",
            label=progress_label,
        )

        stream_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        holder: Dict[str, Any] = {}

        def _on_delta(chunk: str) -> None:
            if chunk:
                stream_queue.put(("content", chunk))

        def _call_model() -> None:
            try:
                holder["response"] = chat_with_cloud_model(
                    model,
                    messages=messages,
                    tools=[],
                    max_tokens=2200,
                    temperature=0.1,
                    reasoning_effort=reasoning_effort,
                    stream_callback=_on_delta,
                )
            except BaseException as exc:
                holder["error"] = exc
            finally:
                stream_queue.put(("done", None))

        worker = threading.Thread(target=_call_model, daemon=True)
        worker.start()
        started_at = time.monotonic()
        last_progress = started_at
        full_response = ""
        while True:
            try:
                kind, payload = stream_queue.get(timeout=0.25)
            except queue.Empty:
                now = time.monotonic()
                elapsed = int(now - started_at)
                if elapsed >= 4 and now - last_progress >= 6:
                    last_progress = now
                    yield runtime_event(
                        "model_progress",
                        model=model,
                        provider="cloud",
                        iteration=1,
                        elapsed_seconds=elapsed,
                        stage=self._model_progress_stage(elapsed),
                        context_kind="ultrareview",
                        streamed=True,
                        label=progress_label,
                    )
                continue
            if kind == "content":
                chunk = str(payload or "")
                full_response += chunk
                yield runtime_event("content", text=chunk, token_stats={})
            elif kind == "done":
                break
        worker.join(timeout=0)
        if holder.get("error"):
            texts = self._terminal_command_texts(locale)
            fallback = f"{texts['final_blocker']}\n\n{self._build_ultrareview_fallback_report(review_materials, workspace_path, locale)}"
            yield runtime_event("content", text=fallback, token_stats={})
            return fallback
        if not full_response.strip():
            response = holder.get("response") or {}
            message = response.get("message", {}) if isinstance(response, dict) else {}
            full_response = str(message.get("content") or "")
            if full_response:
                yield runtime_event("content", text=full_response, token_stats={})
        return full_response

    def _format_ultrareview_materials(self, review_materials: List[Dict[str, Any]], workspace_path: str) -> str:
        lines: List[str] = []
        for item in review_materials:
            kind = item.get("kind", "material")
            lines.append(f"\n## {kind}")
            if item.get("label"):
                lines.append(f"Label: {item.get('label')}")
            if item.get("command"):
                lines.append(f"Command: {item.get('command')}")
            if item.get("summary"):
                lines.append(str(item.get("summary")))
            result = item.get("result")
            if isinstance(result, dict):
                if kind == "reviewer":
                    lines.append(self._format_delegate_subagent_for_llm(result))
                elif kind == "verifier":
                    lines.append(self._format_delegate_subagent_for_llm(result))
                else:
                    output = str(result.get("output") or result.get("summary") or result)
                    lines.append(truncate_middle(mask_workspace_paths(output, workspace_path), 3000))
        return truncate_middle("\n".join(lines), 28000)

    def _build_ultrareview_fallback_report(
        self,
        review_materials: List[Dict[str, Any]],
        workspace_path: str,
        locale: str | None,
    ) -> str:
        texts = self._terminal_command_texts(locale)
        lines = ["## Ultrareview", "", texts["ultra_fallback"], ""]
        verifier = next((item for item in review_materials if item.get("kind") == "verifier"), None)
        if verifier:
            result = verifier.get("result") or {}
            summary = verifier.get("summary") or result.get("summary") or texts["verify_skipped"]
            lines.append(f"- Verification: {summary}")
        reviewer_count = len([item for item in review_materials if item.get("kind") == "reviewer"])
        lines.append(f"- Reviewer passes: {reviewer_count}")
        changed = self._extract_changed_paths(review_materials)
        if changed:
            lines.append("- Scope: " + ", ".join(changed[:10]))
        lines.append(f"- Verdict: {texts['no_high_confidence']}")
        return mask_workspace_paths("\n".join(lines), workspace_path)
