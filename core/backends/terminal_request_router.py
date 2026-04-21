"""Small deterministic router for terminal requests.

The agent loop still lets the model choose tools for normal work. This module
only catches high-confidence structural intents that are safer as harness
decisions than as free-form shell commands.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Sequence


@dataclass(frozen=True)
class TerminalRequestRoute:
    action: str = "unknown"
    target: str = "unknown"
    scope: str = "unknown"
    confidence: float = 0.0
    reason: str = ""

    @property
    def is_clear_workspace(self) -> bool:
        return self.action == "clear" and self.target == "workspace" and self.confidence >= 0.75


_ACTION_STEMS = (
    "clear",
    "clean",
    "delete",
    "effac",
    "erase",
    "nettoy",
    "remove",
    "remov",
    "remplac",
    "repart",
    "reset",
    "supprim",
    "vid",
    "wipe",
)

_BROAD_SCOPE_TOKENS = {
    "all",
    "complete",
    "complet",
    "completa",
    "completo",
    "contenido",
    "contenu",
    "content",
    "contents",
    "dedans",
    "dentro",
    "entier",
    "entire",
    "everything",
    "inside",
    "toda",
    "todo",
    "todos",
    "tout",
    "toute",
    "toutes",
    "tutti",
    "tutto",
    "zero",
}

_DEICTIC_CONTENT_TOKENS = {
    "ca",
    "ce",
    "cela",
    "inside",
    "it",
    "stuff",
    "that",
    "this",
    "what",
}

_WORKSPACE_TARGET_TOKENS = {
    "carpeta",
    "directory",
    "dossier",
    "folder",
    "projet",
    "project",
    "racine",
    "repo",
    "repository",
    "repertoire",
    "root",
    "workspace",
}

_FILE_TARGET_TOKENS = {
    "archivo",
    "file",
    "fichier",
    "fichiers",
    "folder",
}

_STOPWORDS = {
    "a",
    "and",
    "ce",
    "dans",
    "de",
    "del",
    "des",
    "di",
    "du",
    "el",
    "en",
    "et",
    "il",
    "in",
    "la",
    "le",
    "les",
    "lo",
    "of",
    "qu",
    "que",
    "qui",
    "the",
    "un",
    "una",
    "une",
    "y",
}

_CLAUSE_BOUNDARY_TOKENS = {
    "and",
    "ensuite",
    "et",
    "next",
    "puis",
    "then",
}

_FILE_NAME_RE = re.compile(r"^\.?[a-z0-9_-]+(?:\.[a-z0-9_-]+)+$")


def _fold(text: str) -> str:
    lowered = str(text or "").lower()
    return unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")


def _tokens(message: str) -> list[str]:
    folded = _fold(message)
    return re.findall(r"[a-z0-9_.\\/-]+", folded)


def _has_stem(tokens: Sequence[str], stems: Sequence[str]) -> bool:
    return any(any(token.startswith(stem) for stem in stems) for token in tokens)


def _has_path_like_target(tokens: Sequence[str]) -> bool:
    for token in tokens:
        if "/" in token or "\\" in token:
            return True
        if _FILE_NAME_RE.match(token):
            return True
    return False


def _has_named_target(tokens: Sequence[str]) -> bool:
    """Return True when the user points at a specific file/folder name.

    Broad workspace clears should say "all", "contents", "workspace", etc. A
    concrete leftover token after removing structural words is treated as a
    named target and must stay in the normal tool path.
    """
    if _has_path_like_target(tokens):
        return True

    structural = (
        set(_ACTION_STEMS)
        | _BROAD_SCOPE_TOKENS
        | _DEICTIC_CONTENT_TOKENS
        | _WORKSPACE_TARGET_TOKENS
        | _STOPWORDS
        | {"dans", "inside", "into", "sur", "from", "to"}
    )
    for token in tokens:
        if any(token.startswith(stem) for stem in _ACTION_STEMS):
            continue
        if token in structural:
            continue
        if len(token) <= 2:
            continue
        return True
    return False


def _first_destructive_clause(tokens: Sequence[str]) -> list[str]:
    """Keep the destructive clause separate from follow-up build instructions."""
    action_index = -1
    for index, token in enumerate(tokens):
        if token in {"rm", "del"} or any(token.startswith(stem) for stem in _ACTION_STEMS):
            action_index = index
            break
    if action_index < 0:
        return list(tokens)

    clause = list(tokens[action_index:])
    for index, token in enumerate(clause[1:], start=1):
        if token in _CLAUSE_BOUNDARY_TOKENS:
            return clause[:index]
    return clause


def classify_terminal_request(message: str) -> TerminalRequestRoute:
    tokens = _tokens(message)
    if not tokens:
        return TerminalRequestRoute(reason="empty")

    has_clear_action = _has_stem(tokens, _ACTION_STEMS) or {"rm", "del"} & set(tokens)
    if not has_clear_action:
        return TerminalRequestRoute(reason="no-clear-action")

    destructive_tokens = _first_destructive_clause(tokens)
    destructive_token_set = set(destructive_tokens)

    has_broad_scope = bool(destructive_token_set & _BROAD_SCOPE_TOKENS)
    has_deictic_content = bool(destructive_token_set & _DEICTIC_CONTENT_TOKENS)
    has_workspace_target = bool(destructive_token_set & _WORKSPACE_TARGET_TOKENS)
    has_file_target = bool((destructive_token_set & _FILE_TARGET_TOKENS) - {"folder"})
    has_named_target = _has_named_target(destructive_tokens)

    if has_file_target or has_named_target:
        return TerminalRequestRoute(
            action="delete",
            target="named_target",
            scope="specific",
            confidence=0.65,
            reason="specific-target",
        )

    if has_workspace_target and (has_broad_scope or has_deictic_content):
        return TerminalRequestRoute(
            action="clear",
            target="workspace",
            scope="contents",
            confidence=0.94,
            reason="workspace-target-with-broad-scope",
        )

    if has_broad_scope and not has_named_target:
        return TerminalRequestRoute(
            action="clear",
            target="workspace",
            scope="contents",
            confidence=0.86,
            reason="broad-clear-without-named-target",
        )

    if has_workspace_target and not has_named_target:
        return TerminalRequestRoute(
            action="clear",
            target="workspace",
            scope="contents",
            confidence=0.78,
            reason="workspace-clear-without-named-target",
        )

    return TerminalRequestRoute(
        action="delete",
        target="unknown",
        scope="unknown",
        confidence=0.3,
        reason="ambiguous-destructive-request",
    )


def should_clear_workspace(message: str) -> bool:
    return classify_terminal_request(message).is_clear_workspace
