"""Hugging Face cache helpers shared by preload and model loaders."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Iterable

from core.infra.paths import get_models_dir
from core.models.runtime_env import get_huggingface_hub_cache_dir, resolve_huggingface_cache_paths

SDXL_BASE_CONFIG_REPO = "stabilityai/stable-diffusion-xl-base-1.0"


def iter_hf_cache_dirs(cache_dir: str | Path | None = None) -> Iterable[Path]:
    """Yield known HF Hub cache directories, including JoyBoy's legacy layout."""
    candidates: list[Path] = []

    if cache_dir:
        hf_home, hf_hub_cache = resolve_huggingface_cache_paths(str(cache_dir))
        candidates.extend([Path(hf_hub_cache), Path(hf_home)])

    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw))

    hf_home_env = os.environ.get("HF_HOME")
    if hf_home_env:
        candidates.extend([Path(hf_home_env) / "hub", Path(hf_home_env)])

    joyboy_hf_home = get_models_dir() / "huggingface"
    candidates.extend([
        joyboy_hf_home / "hub",
        joyboy_hf_home,
        Path.home() / ".cache" / "huggingface" / "hub",
        Path.home() / ".cache" / "huggingface",
    ])

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.expanduser().resolve())
        except Exception:
            resolved = str(candidate.expanduser().absolute())
        key = resolved.lower() if os.name == "nt" else resolved
        if key in seen:
            continue
        seen.add(key)
        yield Path(resolved)


def preferred_hf_hub_cache_dir(cache_dir: str | Path | None = None) -> str:
    """Return the cache dir JoyBoy should use for new HF Hub downloads."""
    if cache_dir:
        return get_huggingface_hub_cache_dir(str(cache_dir))
    env_cache = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env_cache:
        return env_cache
    return get_huggingface_hub_cache_dir(str(get_models_dir() / "huggingface"))


def hf_repo_cache_folder(repo_id: str) -> str:
    """Return the on-disk folder name used by huggingface_hub for a repo id."""
    return f"models--{repo_id.replace('/', '--')}"


def find_hf_cache_dir_for_repo(repo_id: str, *, cache_dir: str | Path | None = None) -> str | None:
    """Return the cache root that already contains ``repo_id`` if present."""
    repo_folder = hf_repo_cache_folder(repo_id)
    for candidate in iter_hf_cache_dirs(cache_dir):
        if (candidate / repo_folder).exists():
            return str(candidate)
    return None


def find_hf_file_in_cache(
    repo_id: str,
    filename: str,
    *,
    cache_dir: str | Path | None = None,
) -> str | None:
    """Return a cached HF file path without touching the network."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        try_to_load_from_cache = None

    for candidate in iter_hf_cache_dirs(cache_dir):
        if try_to_load_from_cache is not None:
            try:
                cached = try_to_load_from_cache(repo_id, filename, cache_dir=str(candidate))
                if isinstance(cached, str) and Path(cached).exists():
                    return cached
            except Exception:
                pass

        repo_root = candidate / hf_repo_cache_folder(repo_id)
        snapshots = repo_root / "snapshots"
        if not snapshots.exists():
            continue
        try:
            for match in snapshots.glob(f"*/{filename}"):
                if match.exists():
                    return str(match)
        except Exception:
            continue

    return None


def is_hf_file_cached(repo_id: str, filename: str, *, cache_dir: str | Path | None = None) -> bool:
    """Return whether ``filename`` for ``repo_id`` is present in any local cache."""
    return find_hf_file_in_cache(repo_id, filename, cache_dir=cache_dir) is not None


def find_hf_snapshot_dir(
    repo_id: str,
    filename: str = "model_index.json",
    *,
    cache_dir: str | Path | None = None,
) -> str | None:
    """Return the snapshot directory containing ``filename`` for ``repo_id``."""
    cached_file = find_hf_file_in_cache(repo_id, filename, cache_dir=cache_dir)
    if not cached_file:
        return None

    path = Path(cached_file)
    parts = path.parts
    for index, part in enumerate(parts):
        if part == "snapshots" and index + 1 < len(parts):
            return str(Path(*parts[: index + 2]))
    return str(path.parent)


def single_file_sdxl_config_kwargs(cache_dir: str | Path | None = None) -> dict[str, str]:
    """Return kwargs that let Diffusers load SDXL single-file configs offline."""
    cache_root = find_hf_cache_dir_for_repo(SDXL_BASE_CONFIG_REPO, cache_dir=cache_dir)
    if cache_root is None:
        cache_root = preferred_hf_hub_cache_dir(cache_dir)

    kwargs = {"cache_dir": cache_root}
    snapshot_dir = find_hf_snapshot_dir(
        SDXL_BASE_CONFIG_REPO,
        "model_index.json",
        cache_dir=cache_dir,
    )
    if snapshot_dir:
        kwargs["config"] = snapshot_dir
    return kwargs


def is_huggingface_reachable(host: str = "huggingface.co") -> bool:
    """Fast DNS-level reachability check used to avoid HF retry spam offline."""
    offline_flags = (
        os.environ.get("HF_HUB_OFFLINE"),
        os.environ.get("TRANSFORMERS_OFFLINE"),
        os.environ.get("DIFFUSERS_OFFLINE"),
    )
    if any(str(flag).strip().lower() in {"1", "true", "yes", "on"} for flag in offline_flags if flag is not None):
        return False

    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False
