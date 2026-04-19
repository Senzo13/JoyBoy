"""Small backend-managed subagents for coding workflows."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .output import mask_workspace_paths, truncate_middle


IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",
    "out",
    "coverage",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".sh",
    ".ps1",
    ".bat",
    ".go",
    ".rs",
    ".java",
    ".cs",
    ".php",
    ".rb",
    ".sql",
}

IMPORTANT_ROOT_FILES = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "setup.py",
    "Cargo.toml",
    "go.mod",
    "AGENTS.md",
)

STOP_WORDS = {
    "avec",
    "dans",
    "pour",
    "quoi",
    "comment",
    "faire",
    "code",
    "fichier",
    "projet",
    "repo",
    "analyse",
    "explore",
    "implement",
    "fix",
    "the",
    "and",
    "that",
    "this",
    "from",
    "with",
    "what",
    "where",
    "how",
}


@dataclass
class SubagentResult:
    task_id: str
    agent_type: str
    status: str
    task: str
    summary: str = ""
    observations: List[str] = field(default_factory=list)
    files: List[Dict[str, Any]] = field(default_factory=list)
    commands: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = int((self.ended_at - self.started_at) * 1000)
        return data


def _workspace_root(workspace_path: str) -> Path | None:
    if not workspace_path:
        return None
    root = Path(workspace_path).expanduser().resolve()
    return root if root.exists() and root.is_dir() else None


def _is_text_file(path: Path) -> bool:
    if path.name in IMPORTANT_ROOT_FILES:
        return True
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    if not path.suffix:
        try:
            return path.stat().st_size < 100_000 and b"\0" not in path.read_bytes()[:2048]
        except OSError:
            return False
    return False


def _task_terms(task: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9_./-]{4,}", task or "")
    terms = []
    for term in raw_terms:
        clean = term.strip("./-_:").lower()
        if clean and clean not in STOP_WORDS and clean not in terms:
            terms.append(clean)
    return terms[:12]


def _iter_candidate_files(root: Path, max_files_seen: int = 2500):
    seen = 0
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORE_DIRS]
        for filename in files:
            if seen >= max_files_seen:
                return
            seen += 1
            path = Path(current_root) / filename
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                if resolved.stat().st_size > 1_000_000 or not _is_text_file(resolved):
                    continue
                yield resolved
            except OSError:
                continue


def _read_excerpt(path: Path, root: Path, max_chars: int = 2200) -> dict:
    rel_path = path.relative_to(root).as_posix()
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": rel_path, "error": str(exc)}
    lines = content.splitlines()
    return {
        "path": rel_path,
        "lines": len(lines),
        "excerpt": truncate_middle(content, max_chars),
    }


def run_code_explorer_subagent(workspace_path: str, task: str, max_files: int = 8) -> Dict[str, Any]:
    """Run a bounded read-only code explorer.

    This is intentionally deterministic for now: it gives local models a
    high-signal context bundle without letting them spin on `ls`/`glob`.
    """
    started_at = time.time()
    task_id = f"explorer-{uuid.uuid4().hex[:10]}"
    root = _workspace_root(workspace_path)
    if root is None:
        return SubagentResult(
            task_id=task_id,
            agent_type="code_explorer",
            status="error",
            task=task,
            summary="Invalid workspace",
            warnings=["workspace_path is missing or not a directory"],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()

    try:
        max_files = max(2, min(int(max_files or 8), 16))
    except Exception:
        max_files = 8

    terms = _task_terms(task)
    scored: list[tuple[int, Path, list[str]]] = []
    warnings: list[str] = []

    important_paths = [root / name for name in IMPORTANT_ROOT_FILES if (root / name).is_file()]
    for path in _iter_candidate_files(root):
        rel = path.relative_to(root).as_posix().lower()
        score = 0
        hits: list[str] = []
        if path in important_paths:
            score += 4
        for term in terms:
            if term in rel:
                score += 5
                hits.append(f"path:{term}")
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:60_000].lower()
        except OSError:
            continue
        for term in terms:
            count = sample.count(term)
            if count:
                score += min(count, 8)
                hits.append(f"text:{term}x{count}")
        if score > 0 or path in important_paths:
            scored.append((score, path, hits[:6]))

    scored.sort(key=lambda item: (-item[0], item[1].relative_to(root).as_posix()))
    selected: list[Path] = []
    for path in important_paths:
        if path not in selected:
            selected.append(path)
    for _, path, _ in scored:
        if path not in selected:
            selected.append(path)
        if len(selected) >= max_files:
            break

    files = [_read_excerpt(path, root) for path in selected[:max_files]]
    observations = []
    if terms:
        observations.append("Task terms: " + ", ".join(terms))
    observations.append(f"Selected {len(files)} file(s) from {root.name}")
    if scored:
        top = []
        for score, path, hits in scored[:6]:
            top.append(f"{path.relative_to(root).as_posix()} score={score}" + (f" hits={', '.join(hits)}" if hits else ""))
        observations.append("Top matches:\n" + "\n".join(f"- {item}" for item in top))
    else:
        warnings.append("No strong task-specific matches found; returned important root files when available.")

    result = SubagentResult(
        task_id=task_id,
        agent_type="code_explorer",
        status="completed",
        task=task,
        summary="Read-only code explorer completed.",
        observations=[mask_workspace_paths(item, str(root)) for item in observations],
        files=files,
        warnings=warnings,
        started_at=started_at,
        ended_at=time.time(),
    ).to_dict()
    return result


def _reject_shell_syntax(command: str) -> str | None:
    if not command or not command.strip():
        return "Command is required"
    if "\n" in command or "\r" in command:
        return "Multiline commands are not allowed"
    if re.search(r"(\&\&|\|\||[;&|<>`])", command):
        return "Shell chaining, pipes, redirects, and metacharacters are not allowed"
    return None


def _arg_escapes_workspace(token: str) -> bool:
    if token == "./...":
        return False
    value = token.replace("\\", "/")
    if value.startswith("../") or "/../" in value or value == "..":
        return True
    if re.match(r"^[a-zA-Z]:/", value) or value.startswith("/"):
        return True
    return False


def _command_name(token: str) -> str:
    name = Path(token).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _resolve_executable(executable: str) -> tuple[str | None, str | None]:
    resolved = shutil.which(executable)
    if resolved:
        return resolved, None
    return None, f"Executable not found on PATH: {executable}"


def _safe_verifier_command(command: str) -> tuple[list[str] | None, str | None]:
    reason = _reject_shell_syntax(command)
    if reason:
        return None, reason

    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return None, f"Invalid command: {exc}"

    if not tokens:
        return None, "Command is required"
    if any(_arg_escapes_workspace(token) for token in tokens[1:]):
        return None, "Command arguments must stay inside the workspace"

    executable = _command_name(tokens[0])
    if executable in {"python", "python3", "py"}:
        if len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] in {"unittest", "pytest"}:
            return [sys.executable, *tokens[1:]], None
        return None, "Only `python -m unittest ...` and `python -m pytest ...` are allowed"

    if executable == "pytest":
        return [sys.executable, "-m", "pytest", *tokens[1:]], None

    if executable in {"npm", "pnpm", "yarn"}:
        allowed = {
            (executable, "test"),
            (executable, "run", "test"),
            (executable, "run", "build"),
            (executable, "run", "lint"),
            (executable, "run", "typecheck"),
        }
        prefix = tuple(tokens[:3]) if len(tokens) >= 3 else tuple(tokens)
        short_prefix = tuple(tokens[:2])
        if prefix in allowed or short_prefix in allowed:
            resolved, error = _resolve_executable(tokens[0])
            if error:
                return None, error
            return [resolved, *tokens[1:]], None
        return None, f"Only safe {executable} test/build/lint/typecheck scripts are allowed"

    if executable == "go" and len(tokens) >= 2 and tokens[1] == "test":
        resolved, error = _resolve_executable(tokens[0])
        if error:
            return None, error
        return [resolved, *tokens[1:]], None

    if executable == "cargo" and len(tokens) >= 2 and tokens[1] in {"test", "check"}:
        resolved, error = _resolve_executable(tokens[0])
        if error:
            return None, error
        return [resolved, *tokens[1:]], None

    return None, f"Unsupported verifier command: {tokens[0]}"


def run_verifier_subagent(
    workspace_path: str,
    task: str,
    command: str,
    timeout_seconds: int = 90,
) -> Dict[str, Any]:
    """Run one bounded verification command without a shell."""
    started_at = time.time()
    task_id = f"verifier-{uuid.uuid4().hex[:10]}"
    root = _workspace_root(workspace_path)
    if root is None:
        return SubagentResult(
            task_id=task_id,
            agent_type="verifier",
            status="error",
            task=task,
            summary="Invalid workspace",
            warnings=["workspace_path is missing or not a directory"],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()

    argv, reason = _safe_verifier_command(command)
    if reason or argv is None:
        return SubagentResult(
            task_id=task_id,
            agent_type="verifier",
            status="error",
            task=task,
            summary=reason or "Command rejected",
            warnings=["Verifier subagent accepts only allowlisted test/build commands."],
            commands=[{"command": command, "allowed": False, "error": reason}],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()

    try:
        timeout_seconds = max(5, min(int(timeout_seconds or 90), 180))
    except Exception:
        timeout_seconds = 90

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("NO_COLOR", "1")

    try:
        completed = subprocess.run(
            argv,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        output = completed.stdout or ""
        if completed.stderr:
            output += ("\n[STDERR]\n" if output else "[STDERR]\n") + completed.stderr
        output = mask_workspace_paths(truncate_middle(output, 12000), str(root))
        status = "completed" if completed.returncode == 0 else "failed"
        summary = "Verification passed." if completed.returncode == 0 else f"Verification failed with exit code {completed.returncode}."
        command_result = {
            "command": command,
            "allowed": True,
            "return_code": completed.returncode,
            "output": output,
            "timeout_seconds": timeout_seconds,
        }
        return SubagentResult(
            task_id=task_id,
            agent_type="verifier",
            status=status,
            task=task,
            summary=summary,
            observations=[summary],
            commands=[command_result],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + ("\n[STDERR]\n" + exc.stderr if exc.stderr else "")
        output = mask_workspace_paths(truncate_middle(output, 6000), str(root))
        return SubagentResult(
            task_id=task_id,
            agent_type="verifier",
            status="failed",
            task=task,
            summary=f"Verification timed out after {timeout_seconds}s.",
            commands=[{"command": command, "allowed": True, "timeout": True, "output": output}],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()
    except OSError as exc:
        return SubagentResult(
            task_id=task_id,
            agent_type="verifier",
            status="error",
            task=task,
            summary=f"Verifier command could not start: {exc}",
            commands=[{"command": command, "allowed": True, "error": str(exc)}],
            started_at=started_at,
            ended_at=time.time(),
        ).to_dict()


def run_subagent(agent_type: str, workspace_path: str, task: str, **kwargs: Any) -> Dict[str, Any]:
    kind = str(agent_type or "code_explorer").strip().lower()
    if kind == "code_explorer":
        return run_code_explorer_subagent(workspace_path, task, max_files=kwargs.get("max_files", 8))
    if kind == "verifier":
        return run_verifier_subagent(
            workspace_path,
            task,
            command=str(kwargs.get("command", "") or ""),
            timeout_seconds=kwargs.get("timeout_seconds", 90),
        )
    if kind not in {"code_explorer", "verifier"}:
        return {
            "task_id": f"subagent-{uuid.uuid4().hex[:10]}",
            "agent_type": kind,
            "status": "error",
            "task": task,
            "summary": f"Unsupported subagent type: {kind}",
            "observations": [],
            "files": [],
            "commands": [],
            "warnings": ["Only code_explorer and verifier are available in this JoyBoy runtime slice."],
        }
