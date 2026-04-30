"""Generate project-specific AGENTS.md and CLAUDE.md guidance."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List

from core.audit_modules.workspace_scan import scan_workspace


def _score_from_penalties(base: int, penalties: List[int]) -> int:
    return max(0, min(100, base - sum(penalties)))


def _agent_file_penalties(scan: Dict[str, Any]) -> Dict[str, List[int]]:
    penalties = {"readiness": [], "context": [], "regression": []}
    agent_files = scan.get("agent_files") or {}
    commands = scan.get("commands") or []
    if not agent_files.get("AGENTS.md"):
        penalties["readiness"].append(20)
        penalties["context"].append(12)
    if not agent_files.get("CLAUDE.md"):
        penalties["readiness"].append(14)
        penalties["context"].append(10)
    combined = "\n".join(str(item.get("text") or "") for item in agent_files.values())
    if combined and len(combined) > 20_000:
        penalties["context"].append(12)
    if combined and "duplicate" not in combined.lower() and "duplication" not in combined.lower():
        penalties["readiness"].append(10)
    if combined and not any(command["command"] in combined for command in commands):
        penalties["regression"].append(12)
    if not commands:
        penalties["regression"].append(18)
    if not scan.get("tests"):
        penalties["regression"].append(18)
    return penalties


def _repo_map(scan: Dict[str, Any]) -> List[str]:
    metrics = scan.get("metrics") or {}
    stack = scan.get("stack") or {}
    lines = [
        f"Workspace: `{scan['target']['normalized_path']}`",
        f"Languages: {', '.join(stack.get('languages') or ['unknown'])}",
        f"Frameworks: {', '.join(stack.get('frameworks') or ['none detected'])}",
        f"Files scanned: {metrics.get('total_files', 0)}",
        f"Code files: {metrics.get('code_files', 0)}",
    ]
    if metrics.get("generated_dirs_present"):
        lines.append("Generated/local dirs present: " + ", ".join(metrics["generated_dirs_present"]))
    return lines


def _validation_commands(scan: Dict[str, Any]) -> List[str]:
    commands = [item["command"] for item in scan.get("commands", [])]
    return commands or ["git diff --check"]


def _render_agents_md(scan: Dict[str, Any]) -> str:
    commands = _validation_commands(scan)
    repo_map = "\n".join(f"- {line}" for line in _repo_map(scan))
    command_lines = "\n".join(f"- `{command}`" for command in commands)
    return f"""# Agent Instructions

This repository is a local software project. Work with the existing architecture first; do not invent parallel systems.

## Project Map

{repo_map}

## Core Rules

- Inspect existing modules, routes, components, helpers, and tests before editing.
- Do not duplicate code. If behavior already exists, reuse it or extract a shared helper/component/service.
- Keep changes scoped to the user request and avoid unrelated refactors.
- Keep secrets, model weights, generated output, caches, and local machine data out of git.
- Prefer deterministic code paths and explicit errors over hidden fallback behavior.
- Update documentation and examples when public behavior changes.

## Multi-Agent Workflow

- Explorer: read the relevant code and summarize ownership boundaries before edits.
- Planner: split work by file/module ownership and define validation commands.
- Worker: edit only the assigned scope and list changed files.
- Reviewer: check bugs, regressions, imports, missing tests, and duplication before final handoff.
- Parallel agents must not edit the same file unless the coordinator explicitly merges the scopes.

## Validation

Run the smallest useful validation after each change:

{command_lines}

Always include `git diff --check` before commit. For Python changes, compile changed files. For frontend changes, run syntax/build checks when available.
"""


def _render_claude_md(scan: Dict[str, Any]) -> str:
    commands = _validation_commands(scan)
    stack = scan.get("stack") or {}
    command_lines = "\n".join(f"- {command}" for command in commands)
    frameworks = ", ".join(stack.get("frameworks") or ["none detected"])
    languages = ", ".join(stack.get("languages") or ["unknown"])
    return f"""# Claude Project Memory

Use this file as concise project guidance. Prefer reading the code over guessing.

## Stack

- Languages: {languages}
- Frameworks: {frameworks}

## How To Work

1. Identify the existing owner module for the requested behavior.
2. Reuse current helpers/components/services before creating new ones.
3. Keep routing and prompt decisions centralized.
4. Add tests proportional to risk.
5. Verify imports and syntax before claiming the task is done.

## Anti-Regression Checklist

{command_lines}

Also check:

- no secrets or local paths committed
- no generated files, models, caches, or outputs committed
- no duplicate implementations of the same routing/prompt/UI behavior
- no UI text without i18n when the app already uses translations

## Agent Coordination

- Use read-only exploration before implementation.
- Assign workers disjoint write scopes.
- Let reviewers focus on bugs, regressions, missing tests, and API/UI contract breaks.
- If a change touches shared infrastructure, broaden tests before finalizing.
"""


def _diff_for_file(path: str, existing: str, proposed: str) -> str:
    return "\n".join(difflib.unified_diff(
        existing.splitlines(),
        proposed.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))


def _quality_findings(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    agent_files = scan.get("agent_files") or {}
    if "AGENTS.md" not in agent_files:
        findings.append({"severity": "high", "title": "AGENTS.md manquant", "detail": "Les agents génériques n'ont pas de guide projet."})
    if "CLAUDE.md" not in agent_files:
        findings.append({"severity": "medium", "title": "CLAUDE.md manquant", "detail": "Claude Code n'a pas de mémoire projet dédiée."})
    for name, payload in agent_files.items():
        text = str(payload.get("text") or "")
        if len(text) > 20_000:
            findings.append({"severity": "medium", "title": f"{name} trop long", "detail": "Un guide trop long consomme le contexte et devient moins actionnable."})
        if "test" not in text.lower():
            findings.append({"severity": "medium", "title": f"{name} sans stratégie de tests", "detail": "Ajouter les commandes réelles de validation réduit les régressions."})
        if "duplicate" not in text.lower() and "duplication" not in text.lower():
            findings.append({"severity": "medium", "title": f"{name} sans règle anti-duplication", "detail": "Forcer la réutilisation des helpers/composants existants."})
    return findings


def generate_agentguide(project_path: str) -> Dict[str, Any]:
    scan = scan_workspace(project_path)
    penalties = _agent_file_penalties(scan)
    scores = [
        {"id": "agent_readiness", "label": "Agent readiness", "score": _score_from_penalties(92, penalties["readiness"]), "max": 100},
        {"id": "regression_safety", "label": "Regression safety", "score": _score_from_penalties(90, penalties["regression"]), "max": 100},
        {"id": "context_quality", "label": "Context quality", "score": _score_from_penalties(92, penalties["context"]), "max": 100},
    ]
    proposed_agents = _render_agents_md(scan)
    proposed_claude = _render_claude_md(scan)
    existing_agents = str((scan.get("agent_files") or {}).get("AGENTS.md", {}).get("text") or "")
    existing_claude = str((scan.get("agent_files") or {}).get("CLAUDE.md", {}).get("text") or "")
    generated_files = [
        {
            "path": "AGENTS.md",
            "content": proposed_agents,
            "exists": bool(existing_agents),
            "diff": _diff_for_file("AGENTS.md", existing_agents, proposed_agents),
        },
        {
            "path": "CLAUDE.md",
            "content": proposed_claude,
            "exists": bool(existing_claude),
            "diff": _diff_for_file("CLAUDE.md", existing_claude, proposed_claude),
        },
    ]
    global_score = round(sum(item["score"] for item in scores) / len(scores))
    findings = _quality_findings(scan)
    return {
        "target": scan["target"],
        "summary": {
            "global_score": global_score,
            "agent_readiness": scores[0]["score"],
            "regression_safety": scores[1]["score"],
            "context_quality": scores[2]["score"],
            "top_risk": findings[0]["title"] if findings else "Guides agents prêts",
            "files_scanned": scan.get("metrics", {}).get("total_files", 0),
            "stack": scan.get("stack", {}),
        },
        "snapshot": {
            "metrics": scan.get("metrics", {}),
            "commands": scan.get("commands", []),
            "agent_files": {name: {"path": data.get("path"), "size": data.get("size")} for name, data in (scan.get("agent_files") or {}).items()},
        },
        "findings": findings,
        "scores": scores,
        "remediation_items": [
            {
                "id": "agent-files",
                "priority": "P1" if findings else "P3",
                "title": "Installer ou mettre à jour les guides agents",
                "why": "Des instructions projet courtes, spécifiques et vérifiables améliorent les agents de code.",
                "actions": ["Prévisualiser les diffs", "Appliquer seulement après validation", "Relancer AgentGuide après changements majeurs"],
                "validation": _validation_commands(scan),
            }
        ],
        "generated_files": generated_files,
    }
