"""Shared local workspace scanning for code-oriented native modules."""

from __future__ import annotations

import ast
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".next",
    ".nuxt",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    "coverage",
    "models",
    "output",
    "outputs",
    "checkpoints",
}

TEXT_EXTENSIONS = {
    ".bat",
    ".css",
    ".env",
    ".go",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".php",
    ".ps1",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}

CODE_EXTENSIONS = {
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".ts",
    ".tsx",
    ".vue",
}

FRONTEND_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".vue", ".css", ".html"}
BACKEND_EXTENSIONS = {".py", ".go", ".rs", ".java", ".php", ".rb"}
AGENT_FILE_NAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules"}
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|private[_-]?key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{12,})"
)


def normalize_workspace_target(raw_path: str) -> Dict[str, Any]:
    raw = str(raw_path or "").strip().strip('"')
    if not raw:
        raise ValueError("Chemin projet requis.")
    path = Path(raw).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError("Le chemin projet doit pointer vers un dossier existant.")
    return {
        "raw": raw,
        "normalized_path": str(path),
        "host": path.name,
        "mode": "local_workspace",
    }


def _is_text_candidate(path: Path) -> bool:
    if path.name in AGENT_FILE_NAMES:
        return True
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    if not path.suffix:
        try:
            chunk = path.read_bytes()[:2048]
            return len(chunk) < 2048 or b"\0" not in chunk
        except OSError:
            return False
    return False


def _iter_workspace_files(root: Path, max_files_seen: int = 5000) -> Iterable[Path]:
    seen = 0
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORE_DIRS and not name.startswith(".git")]
        for filename in files:
            seen += 1
            if seen > max_files_seen:
                return
            path = Path(current_root) / filename
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    continue
                yield resolved
            except OSError:
                continue


def _read_text(path: Path, max_bytes: int = 600_000) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return path.read_text(encoding="utf-8", errors="replace")[:max_bytes]
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _parse_package_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _detect_commands(root: Path) -> List[Dict[str, str]]:
    commands: List[Dict[str, str]] = []
    package_json = root / "package.json"
    if package_json.exists():
        data = _parse_package_json(package_json)
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        for name in ("lint", "test", "build", "typecheck", "check"):
            if scripts.get(name):
                commands.append({"kind": name, "command": f"npm run {name}", "source": "package.json"})
    if (root / "pytest.ini").exists() or (root / "tests").exists():
        commands.append({"kind": "test", "command": "pytest", "source": "pytest/tests"})
    if (root / "pyproject.toml").exists():
        commands.append({"kind": "python", "command": "python -m pytest", "source": "pyproject.toml"})
    if list(root.glob("*.py")) or (root / "core").exists():
        commands.append({"kind": "compile", "command": "python -m py_compile <changed .py files>", "source": "python"})
    commands.append({"kind": "diff", "command": "git diff --check", "source": "git"})
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in commands:
        key = item["command"]
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def _detect_stack(root: Path, ext_counts: Counter, text_by_path: Dict[str, str]) -> Dict[str, Any]:
    package = _parse_package_json(root / "package.json") if (root / "package.json").exists() else {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(package.get(key), dict):
            deps.update(package[key])
    frameworks = []
    if "next" in deps or (root / "next.config.js").exists() or (root / "next.config.mjs").exists():
        frameworks.append("Next.js")
    if "react" in deps:
        frameworks.append("React")
    if "vue" in deps:
        frameworks.append("Vue")
    if "vite" in deps or (root / "vite.config.js").exists() or (root / "vite.config.ts").exists():
        frameworks.append("Vite")
    if any("from flask" in text or "import flask" in text for text in text_by_path.values()):
        frameworks.append("Flask")
    if any("FastAPI" in text or "fastapi" in text for text in text_by_path.values()):
        frameworks.append("FastAPI")
    if (root / "pyproject.toml").exists():
        frameworks.append("Python package")
    languages = []
    if ext_counts[".py"]:
        languages.append("Python")
    if ext_counts[".ts"] or ext_counts[".tsx"]:
        languages.append("TypeScript")
    if ext_counts[".js"] or ext_counts[".jsx"]:
        languages.append("JavaScript")
    if ext_counts[".css"]:
        languages.append("CSS")
    return {
        "languages": languages,
        "frameworks": sorted(set(frameworks)),
        "package_manager": "npm" if package else "",
    }


def _syntax_findings(root: Path, text_files: Dict[str, str]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for rel, text in text_files.items():
        if not rel.endswith(".py"):
            continue
        try:
            ast.parse(text, filename=rel)
        except SyntaxError as exc:
            findings.append({
                "id": f"syntax:{rel}:{exc.lineno}",
                "category": "backend",
                "severity": "critical",
                "title": "Erreur de syntaxe Python",
                "detail": f"{rel}:{exc.lineno} {exc.msg}",
                "file": rel,
            })
    return findings


def _secret_findings(text_files: Dict[str, str]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for rel, text in text_files.items():
        if rel.startswith(".git/"):
            continue
        for match in SECRET_RE.finditer(text):
            findings.append({
                "id": f"secret:{rel}:{match.start()}",
                "category": "security",
                "severity": "high",
                "title": "Secret potentiel dans le projet",
                "detail": f"Mot-clé sensible détecté: {match.group(1)}",
                "file": rel,
            })
            break
    return findings[:20]


def _duplication_findings(text_files: Dict[str, str]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    fingerprints: Dict[str, List[str]] = defaultdict(list)
    for rel, text in text_files.items():
        if Path(rel).suffix.lower() not in CODE_EXTENSIONS:
            continue
        normalized = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith(("#", "//", "/*", "*"))
        ]
        for index in range(0, max(0, len(normalized) - 7), 4):
            block = "\n".join(normalized[index:index + 8])
            if len(block) < 160:
                continue
            fingerprints[block].append(rel)
    repeated = [
        {"files": sorted(set(paths)), "occurrences": len(paths)}
        for paths in fingerprints.values()
        if len(set(paths)) > 1
    ]
    repeated.sort(key=lambda item: (item["occurrences"], len(item["files"])), reverse=True)
    findings = []
    for item in repeated[:10]:
        findings.append({
            "id": "duplication:" + "|".join(item["files"][:3]),
            "category": "maintainability",
            "severity": "medium",
            "title": "Bloc de code probablement dupliqué",
            "detail": "Même bloc logique détecté dans plusieurs fichiers. Extraire un helper/composant partagé.",
            "files": item["files"][:6],
        })
    return findings, {"repeated_blocks": len(repeated), "examples": repeated[:8]}


def scan_workspace(raw_path: str, *, max_files: int = 5000) -> Dict[str, Any]:
    target = normalize_workspace_target(raw_path)
    root = Path(target["normalized_path"])
    files = list(_iter_workspace_files(root, max_files_seen=max_files))
    ext_counts: Counter = Counter(path.suffix.lower() for path in files)
    text_by_path: Dict[str, str] = {}
    file_records: List[Dict[str, Any]] = []
    large_files: List[Dict[str, Any]] = []
    agent_files: Dict[str, Dict[str, Any]] = {}

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        suffix = path.suffix.lower()
        record = {"path": rel, "size": size, "ext": suffix}
        file_records.append(record)
        if size > 250_000 and suffix in CODE_EXTENSIONS:
            large_files.append(record)
        if path.name in AGENT_FILE_NAMES:
            text = _read_text(path, max_bytes=120_000)
            agent_files[path.name] = {"path": rel, "size": size, "text": text}
        if size <= 800_000 and _is_text_candidate(path):
            text_by_path[rel] = _read_text(path)

    tests = [
        record["path"]
        for record in file_records
        if record["path"].startswith("tests/") or "/test_" in record["path"] or record["path"].endswith(".test.ts") or record["path"].endswith(".test.js")
    ]
    generated_present = [
        name for name in ("models", "output", "outputs", "dist", "build", "node_modules", "venv", ".venv")
        if (root / name).exists()
    ]
    syntax = _syntax_findings(root, text_by_path)
    secret = _secret_findings(text_by_path)
    duplication, duplication_meta = _duplication_findings(text_by_path)
    stack = _detect_stack(root, ext_counts, text_by_path)

    return {
        "target": target,
        "root": str(root),
        "files": file_records[:300],
        "metrics": {
            "total_files": len(files),
            "text_files": len(text_by_path),
            "code_files": sum(ext_counts[ext] for ext in CODE_EXTENSIONS),
            "backend_files": sum(ext_counts[ext] for ext in BACKEND_EXTENSIONS),
            "frontend_files": sum(ext_counts[ext] for ext in FRONTEND_EXTENSIONS),
            "test_files": len(tests),
            "large_code_files": len(large_files),
            "agent_files": len(agent_files),
            "generated_dirs_present": generated_present,
            "extensions": dict(ext_counts.most_common(20)),
        },
        "stack": stack,
        "commands": _detect_commands(root),
        "agent_files": agent_files,
        "tests": tests[:120],
        "large_files": large_files[:40],
        "findings": syntax + secret + duplication,
        "duplication": duplication_meta,
        "text_excerpt": {
            rel: text[:3000]
            for rel, text in list(text_by_path.items())[:80]
        },
    }
