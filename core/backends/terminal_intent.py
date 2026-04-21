"""Intent detection and per-turn tool selection for terminal agent."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

from core.backends.terminal_tool_schemas import READ_CORE_TOOL_ORDER, SCAFFOLD_CORE_TOOL_ORDER


class TerminalIntentMixin:
    """Classify user intent and choose the focused tool surface for a turn."""

    def _select_tool_names_for_turn(
        self,
        initial_message: str,
        executed_tools: List[Dict],
        autonomous: bool = False,
    ) -> List[str]:
        if self.current_intent in {"write", "execute"}:
            if self.current_plan and self._has_incomplete_todos():
                names = self._focused_tool_order_for_active_step(initial_message, executed_tools)
            elif self._is_scaffold_write_request(initial_message):
                names = list(SCAFFOLD_CORE_TOOL_ORDER)
            else:
                names = ["list_files", "read_file", "write_file", "write_files", "edit_file", "bash", "search", "glob"]
        else:
            names = list(READ_CORE_TOOL_ORDER)

        self._active_promoted_tool_names.update(self._auto_promoted_deferred_tools(initial_message, executed_tools))

        priority_promoted: List[str] = []
        active_step_mode = self._active_step_mode(initial_message) if self.current_plan else ""
        if "clear_workspace" in self._active_promoted_tool_names:
            priority_promoted.append("clear_workspace")
        if active_step_mode in {"verify", "analyze"} and "delegate_subagent" in self._active_promoted_tool_names:
            priority_promoted.append("delegate_subagent")

        for name in priority_promoted:
            if name == "clear_workspace" and "write_files" in names:
                names.insert(names.index("write_files"), name)
                continue
            insert_after = "bash" if active_step_mode == "verify" else "search"
            if insert_after in names:
                names.insert(names.index(insert_after) + 1, name)
            else:
                names.append(name)

        for name in self._ordered_deferred_tool_names:
            if name in self._active_promoted_tool_names and name not in priority_promoted:
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

    def _current_task_text(self) -> str:
        if not self.current_plan:
            return ""
        task = self.current_plan.get_current_task()
        if not task:
            return ""
        return " ".join(part for part in (task.title, task.description, task.result or "") if part).strip()

    def _active_step_mode(self, initial_message: str) -> str:
        msg = self._intent_text(initial_message)
        task_text = self._intent_text(self._current_task_text())
        combined = f"{msg} {task_text}".strip()

        scaffold_markers = (
            "template", "scaffold", "starter", "bootstrap", "next js", "nextjs",
            "react", "component", "page", "route", "layout", "setup", "init",
        )
        verify_markers = (
            "verify", "verifie", "vérifie", "test", "tests", "build", "lint",
            "check", "smoke", "validate", "validation",
        )
        analyze_markers = (
            "analyse", "audit", "inspect", "explore", "review", "compare", "cherche",
            "research", "look into",
        )

        if self._is_scaffold_write_request(initial_message) or any(marker in combined for marker in scaffold_markers):
            return "scaffold"
        if any(marker in combined for marker in verify_markers):
            return "verify"
        if any(marker in combined for marker in analyze_markers):
            return "analyze"
        return "write" if self.current_intent in {"write", "execute"} else "read"

    def _focused_tool_order_for_active_step(
        self,
        initial_message: str,
        executed_tools: List[Dict],
    ) -> List[str]:
        mode = self._active_step_mode(initial_message)
        force_focus = self._should_force_step_focus(initial_message, executed_tools)

        if mode == "verify":
            names = ["read_file", "bash", "edit_file", "write_files", "write_file", "search", "list_files"]
        elif mode == "analyze":
            names = ["read_file", "search", "glob", "list_files", "edit_file", "write_files", "write_file", "bash"]
        elif mode == "scaffold":
            names = ["read_file", "write_files", "write_file", "edit_file", "bash", "search", "list_files", "glob"]
        else:
            names = ["read_file", "edit_file", "write_files", "write_file", "bash", "search", "list_files", "glob"]

        if force_focus:
            names = [name for name in names if name not in {"glob", "tool_search"}]
        return names

    def _consecutive_passive_tools(self, executed_tools: List[Dict]) -> int:
        passive_tools = {"list_files", "read_file", "glob", "search", "tool_search", "write_todos", "think"}
        count = 0
        for item in reversed(executed_tools or []):
            tool = str(item.get("tool") or "").strip()
            if not tool:
                continue
            if tool not in passive_tools:
                break
            count += 1
        return count

    def _should_force_step_focus(self, initial_message: str, executed_tools: List[Dict]) -> bool:
        return (
            self.current_intent in {"write", "execute"}
            and self.current_plan is not None
            and self._has_incomplete_todos()
            and not self._has_successful_mutation(executed_tools)
            and self._consecutive_passive_tools(executed_tools) >= 3
        )

    def _is_repo_overview_request(self, message: str) -> bool:
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

    def _should_clarify_request(self, message: str, history: Optional[List[Dict]] = None) -> bool:
        if self._is_repo_overview_request(message) or self._is_open_workspace_request(message):
            return False
        if self._is_casual_greeting_request(message):
            return False
        if self.current_plan and self._has_incomplete_todos():
            return False
        if self._has_actionable_history(history):
            return False

        text = self._folded_single_line(message)
        if not text or len(text) > 120:
            return False

        exact_followups = {
            "continue",
            "continue stp",
            "continue encore",
            "vas y",
            "go",
            "ok",
            "ok vas y",
            "ok go",
            "fais le",
            "fait le",
            "fais ca",
            "fait ca",
            "fais ça",
            "fait ça",
            "ok fais le",
            "ok fait le",
            "fais le stp",
            "fait le stp",
        }
        if text in exact_followups:
            return True

        tokens = text.split()
        destructive_verbs = {"supprime", "delete", "remove", "efface"}
        global_targets = {"tout", "tous", "toute", "toutes", "all", "everything"}
        if any(token in destructive_verbs for token in tokens) and any(token in global_targets for token in tokens):
            return False

        if len(tokens) > 7:
            return False

        action_verbs = {
            "continue", "corrige", "fix", "debug", "ameliore", "améliore", "modifie",
            "supprime", "delete", "remove", "cree", "crée", "creer", "créer",
            "ajoute", "fait", "fais", "code", "regle", "règle", "refactor",
            "execute", "lance", "run",
        }
        if not any(token in action_verbs for token in tokens):
            return False
        if self._has_specific_request_target(message):
            return False

        filler_tokens = {
            "le", "la", "les", "ca", "ça", "ce", "cet", "cette", "ceci", "cela",
            "stp", "please", "moi", "un", "une", "du", "de", "des", "tout",
            "y", "vas", "ok", "go",
        }
        meaningful_tokens = [
            token for token in tokens
            if token not in action_verbs and token not in filler_tokens
        ]
        return len(meaningful_tokens) <= 1

    def _has_actionable_history(self, history: Optional[List[Dict]]) -> bool:
        if not history:
            return False

        for msg in reversed(history[-8:]):
            content = str(msg.get("content", "") or "").strip()
            if not content:
                continue
            if self._is_compaction_summary_message(msg):
                return True

            role = str(msg.get("role", ""))
            folded = self._folded_single_line(content)
            if role == "user" and (
                self._has_specific_request_target(content)
                or len(folded) >= 24
            ):
                return True
            if role == "assistant" and len(folded) >= 40:
                return True
        return False

    def _has_specific_request_target(self, message: str) -> bool:
        raw = str(message or "")
        text = self._folded_single_line(raw)
        if not text:
            return False

        if re.search(r"[\w./\\-]+\.(py|js|jsx|ts|tsx|css|html|md|json|yaml|yml|toml|txt|go|rs|java|cs|php|rb)\b", raw, re.IGNORECASE):
            return True

        target_terms = (
            "fichier", "file", "ligne", "page", "component", "composant", "scroll",
            "input", "button", "bouton", "modal", "picker", "readme", "mcp",
            "provider", "settings", "chat", "terminal", "api", "route", "css",
            "javascript", "typescript", "react", "next", "vite", "python", "test",
            "doctor", "image", "video", "prompt", "ui", "ux", "seo", "bug", "erreur",
            "feature", "fonction", "projet", "repo", "workspace", "dossier", "template",
            "joyboy", "deerflow", "deer flow", "permission", "permissions", "auth",
        )
        if any(term in text for term in target_terms):
            return True

        stop_tokens = {
            "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
            "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou",
            "a", "au", "aux", "en", "sur", "pour", "avec", "sans", "ca", "ça",
            "ce", "cet", "cette", "tout", "tous", "toute", "toutes", "stp",
            "please", "fais", "fait", "continue", "corrige", "modifie", "ameliore",
            "améliore", "supprime", "cree", "crée", "creer", "créer", "ajoute",
            "code", "fix", "debug", "go", "ok",
        }
        meaningful = [token for token in text.split() if len(token) >= 4 and token not in stop_tokens]
        return len(meaningful) >= 3

    def _clarification_answer(self, message: str) -> str:
        text = self._folded_single_line(message)
        if text in {"continue", "continue stp", "continue encore", "vas y", "go", "ok vas y", "ok go"}:
            intro = "Je peux continuer, mais j’ai besoin de savoir quoi reprendre exactement."
        elif self.current_intent in {"write", "execute"}:
            intro = "Je peux le faire, mais ta demande est encore trop vague pour que j’agisse proprement."
        else:
            intro = "J’ai besoin d’un peu plus de contexte pour te répondre utilement."

        if self.current_intent in {"write", "execute"}:
            prompts = [
                "le fichier, l’écran ou la feature à toucher",
                "le résultat attendu au final",
                "si tu veux que je continue la tâche précédente ou repartir d’un point précis",
            ]
            examples = [
                "corrige le scroll du modal projet",
                "continue sur le MCP settings",
                "crée un template React dans le dossier caca",
            ]
        else:
            prompts = [
                "le fichier, dossier ou écran que tu veux que j’analyse",
                "ce que tu veux comprendre ou vérifier",
                "si tu veux un audit global ou un point précis",
            ]
            examples = [
                "analyse tout le repo",
                "regarde core/backends/terminal_brain.py",
                "explique le picker cloud/local",
            ]

        lines = [intro, "", "Dis-moi juste l’un de ces formats :"]
        for index, prompt in enumerate(prompts, start=1):
            lines.append(f"{index}. {prompt}")
        lines.append("")
        lines.append("Exemples : " + " | ".join(f'"{item}"' for item in examples))
        return "\n".join(lines)

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

    @staticmethod
    def _intent_text(message: str) -> str:
        raw = str(message or "").lower()
        folded = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        return f"{raw}\n{folded}"

    @staticmethod
    def _is_clear_workspace_request(message: str) -> bool:
        msg = TerminalIntentMixin._intent_text(message)
        clear_markers = (
            "supprime tout", "efface tout", "delete all", "delete tout",
            "remove all", "clear workspace", "vide le dossier", "vide tout",
            "repart de zero", "repart de zéro", "from scratch", "remplace tout",
            "remplacer tout", "supprime le projet", "reset le projet",
        )
        return any(marker in msg for marker in clear_markers)

    @staticmethod
    def _is_scaffold_write_request(message: str) -> bool:
        """Detect project/template creation requests that are write actions."""
        msg = TerminalIntentMixin._intent_text(message)
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
            "projet de base", "page complete", "page complète", "architecture",
            "squelette", "structure", "starter project",
        )
        framework_terms = (
            "react", "next js", "next.js", "nextjs", "vite", "app router",
            "tailwind", "vue", "svelte", "express", "node", "backend",
            "api", "serveur", "server",
        )

        has_scaffold_term = any(term in msg for term in scaffold_terms)
        has_framework_term = any(term in msg for term in framework_terms)
        has_creation = any(marker in msg for marker in creation_markers)
        has_read = any(marker in msg for marker in read_markers)

        if has_read and not has_creation:
            return False
        if TerminalIntentMixin._is_clear_workspace_request(message) and has_creation:
            return True
        if has_scaffold_term and (has_creation or not has_read):
            return True
        if has_framework_term and has_creation:
            return True
        return False

    @staticmethod
    def detect_intent(message: str) -> str:
        """Détecte l'intention: 'read', 'write', 'execute', 'question'"""
        msg = TerminalIntentMixin._intent_text(message)

        if TerminalIntentMixin._is_scaffold_write_request(message):
            return 'write'

        write_kw = ['modifie', 'modifier', 'change', 'ajoute', 'supprime', 'crée', 'créer',
                    'cree', 'creer', 'cr?er', 'écris', 'ecris', 'fix', 'corrige',
                    'refactor', 'implémente', 'implemente', 'update', 'create', 'make',
                    'code', 'coder', 'fais', 'fait', 'delete', 'remove', 'efface',
                    'remplace', 'replace', 'convert', 'convertis']
        if any(kw in msg for kw in write_kw):
            return 'write'

        exec_kw = ['lance', 'run', 'execute', 'npm ', 'python ', 'pip ', 'test', 'build', 'git ']
        if any(kw in msg for kw in exec_kw):
            return 'execute'

        read_kw = ['analyse', 'explique', 'montre', 'lis', 'regarde', 'c\'est quoi', 'comprendre']
        if any(kw in msg for kw in read_kw):
            return 'read'

        return 'question'

    @staticmethod
    def is_read_only_intent(intent: str) -> bool:
        return intent in ['read', 'question']
