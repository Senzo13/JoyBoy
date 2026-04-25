"""Project ingestion and deterministic stack analysis for DeployAtlas."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

from core.runtime.storage import utc_now_iso

from .storage import _slug


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".cache",
    ".next",
    "dist",
    "build",
    "coverage",
}

SECRET_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "key.pem",
}

MAX_ANALYZED_FILES = 1200
MAX_FILE_BYTES = 12 * 1024 * 1024


def _safe_relative_path(value: str) -> Path:
    raw = str(value or "").replace("\\", "/").strip().lstrip("/")
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise ValueError("Nom de fichier invalide.")
    clean = Path(*parts)
    if clean.is_absolute() or ".." in clean.parts:
        raise ValueError("Chemin dangereux refusé dans l’archive.")
    return clean


def _should_skip(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & {item.lower() for item in EXCLUDED_DIRS})


def _is_secret_file(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_FILENAMES or name.startswith(".env.")


def extract_archive(archive_path: Path, destination: Path) -> dict[str, Any]:
    suffix = "".join(archive_path.suffixes[-2:]).lower()
    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target = _safe_relative_path(member.filename)
                if _should_skip(target) or _is_secret_file(target):
                    continue
                output = destination / target
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source:
                    output.write_bytes(source.read(MAX_FILE_BYTES + 1)[:MAX_FILE_BYTES])
        return {"format": "zip", "rar_supported": False}
    if suffix in {".tar.gz", ".tgz"} or archive_path.suffix.lower() == ".tar":
        mode = "r:gz" if suffix in {".tar.gz", ".tgz"} else "r"
        with tarfile.open(archive_path, mode) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                target = _safe_relative_path(member.name)
                if _should_skip(target) or _is_secret_file(target):
                    continue
                output = destination / target
                output.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source:
                    output.write_bytes(source.read(MAX_FILE_BYTES + 1)[:MAX_FILE_BYTES])
        return {"format": "tar", "rar_supported": False}
    if archive_path.suffix.lower() == ".rar":
        seven_zip = shutil.which("7z") or shutil.which("7za")
        if seven_zip:
            return {
                "format": "rar",
                "rar_supported": True,
                "warning": "RAR détecté, mais l’extraction automatique reste désactivée côté serveur pour éviter les chemins dangereux.",
            }
        raise ValueError("Archive RAR détectée: installe 7z/7za ou envoie un ZIP/TAR.GZ.")
    raise ValueError("Format d’archive non supporté. Utilise .zip, .tar, .tar.gz, .tgz ou .rar avec 7z.")


def copy_uploaded_files(files: Iterable[Any], destination: Path) -> list[str]:
    written: list[str] = []
    for uploaded in files:
        filename = getattr(uploaded, "filename", "") or ""
        rel = _safe_relative_path(filename)
        if _should_skip(rel) or _is_secret_file(rel):
            continue
        output = destination / rel
        output.parent.mkdir(parents=True, exist_ok=True)
        content = uploaded.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"Fichier trop volumineux: {rel.as_posix()}")
        output.write_bytes(content)
        written.append(rel.as_posix())
    return written


def _read_text(path: Path, max_bytes: int = 100_000) -> str:
    try:
        return path.read_bytes()[:max_bytes].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(_read_text(path))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= MAX_ANALYZED_FILES:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _should_skip(rel) or _is_secret_file(rel):
            continue
        files.append(path)
    return files


def analyze_project(root: Path, *, name: str = "", source_type: str = "upload", ingest_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root)
    files = _collect_files(root)
    rel_names = [path.relative_to(root).as_posix() for path in files]
    lower_names = {name.lower() for name in rel_names}
    root_names = {Path(name).name.lower() for name in rel_names}
    package_json = _load_json(root / "package.json") if "package.json" in root_names else {}
    pyproject = _read_text(root / "pyproject.toml") if "pyproject.toml" in root_names else ""

    frameworks: list[str] = []
    stack = "static"
    package_manager = ""
    strategy = "static"
    entrypoints: list[str] = []

    deps = {}
    deps.update(package_json.get("dependencies") or {})
    deps.update(package_json.get("devDependencies") or {})
    if package_json:
        stack = "node"
        strategy = "systemd-node"
        if "next" in deps:
            frameworks.append("Next.js")
        if "vite" in deps or "vite.config.js" in root_names or "vite.config.ts" in root_names:
            frameworks.append("Vite")
        if "react" in deps:
            frameworks.append("React")
        if "pnpm-lock.yaml" in root_names:
            package_manager = "pnpm"
        elif "yarn.lock" in root_names:
            package_manager = "yarn"
        else:
            package_manager = "npm"
        scripts = package_json.get("scripts") or {}
        if "start" in scripts:
            entrypoints.append(f"{package_manager} run start")
        if "build" in scripts:
            entrypoints.append(f"{package_manager} run build")

    if "docker-compose.yml" in root_names or "compose.yml" in root_names or "dockerfile" in root_names:
        strategy = "docker-compose" if "docker-compose.yml" in root_names or "compose.yml" in root_names else "docker"
        frameworks.append("Docker")

    if {"requirements.txt", "pyproject.toml", "setup.py"} & root_names:
        if stack == "static":
            stack = "python"
            strategy = "systemd-python"
        if "fastapi" in pyproject.lower() or any("fastapi" in _read_text(path).lower() for path in files[:80]):
            frameworks.append("FastAPI")
        if "flask" in pyproject.lower() or any("flask" in _read_text(path).lower() for path in files[:80]):
            frameworks.append("Flask")

    if {"composer.json"} & root_names:
        stack = "php" if stack == "static" else stack
        strategy = "php-fpm"
        frameworks.append("PHP")

    if "index.html" in root_names and stack == "static":
        entrypoints.append("file_server")

    env_keys: set[str] = set()
    for env_file in ("env.example", ".env.example", "sample.env"):
        if env_file in lower_names:
            text = _read_text(root / env_file)
            for line in text.splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    env_keys.add(line.split("=", 1)[0].strip())

    warnings: list[str] = []
    if len(files) >= MAX_ANALYZED_FILES:
        warnings.append("Analyse tronquée: trop de fichiers, les dossiers lourds sont exclus.")
    if not entrypoints and strategy not in {"docker", "docker-compose"}:
        warnings.append("Aucun script de démarrage évident détecté; DeployAtlas demandera validation avant exécution réelle.")

    display_name = name or root.name
    return {
        "id": _slug(f"{display_name}-{utc_now_iso()}", "project"),
        "name": display_name,
        "source_type": source_type,
        "root_name": root.name,
        "stack": stack,
        "frameworks": sorted(set(frameworks)),
        "package_manager": package_manager,
        "strategy": strategy,
        "entrypoints": entrypoints,
        "env_keys": sorted(env_keys),
        "file_count": len(files),
        "sample_files": rel_names[:80],
        "warnings": warnings,
        "ingest": ingest_meta or {},
        "created_at": utc_now_iso(),
    }


def suggested_app_slug(analysis: dict[str, Any]) -> str:
    return _slug(analysis.get("name") or analysis.get("root_name") or "app", "app")
