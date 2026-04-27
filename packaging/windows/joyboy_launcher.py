"""Desktop launcher for packaged JoyBoy builds.

The launcher is intentionally small: the packaged executable owns the desktop
icon and process UX, while the app code and Python runtime stay as regular
files beside it. That keeps heavyweight ML dependencies out of the launcher
itself and makes model/packs storage easy to reason about.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


APP_URL = os.environ.get("JOYBOY_URL", "http://127.0.0.1:7860")


def _app_root() -> Path:
    override = os.environ.get("JOYBOY_APP_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _configure_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("JOYBOY_DESKTOP", "1")
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    data_dir = root / "data"
    portable = env.get("JOYBOY_PORTABLE", "").strip().lower()
    if portable in {"1", "true", "yes"} or (portable not in {"0", "false", "no"} and data_dir.exists()):
        data_dir.mkdir(parents=True, exist_ok=True)
        for child in ("models", "packs", "cache", "output", "logs"):
            (data_dir / child).mkdir(parents=True, exist_ok=True)
        hf_cache = data_dir / "models" / "huggingface"
        hf_cache.mkdir(parents=True, exist_ok=True)
        env.setdefault("JOYBOY_HOME", str(data_dir))
        env.setdefault("JOYBOY_MODELS_DIR", str(data_dir / "models"))
        env.setdefault("JOYBOY_HF_CACHE_DIR", str(hf_cache))
        env.setdefault("JOYBOY_PACKS_DIR", str(data_dir / "packs"))
        env.setdefault("JOYBOY_OUTPUT_DIR", str(data_dir / "output"))
        env["HF_HOME"] = str(hf_cache)
        env["HF_HUB_CACHE"] = str(hf_cache)
        env.setdefault("HF_ASSETS_CACHE", str(hf_cache / "assets"))

    return env


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "venv" / "Scripts" / "python.exe"
    return root / "venv" / "bin" / "python"


def _system_python() -> Path | None:
    names = ("python.exe", "python") if os.name == "nt" else ("python3", "python")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _candidate_pythons(root: Path) -> list[Path]:
    candidates = [
        _venv_python(root),
        root / "runtime" / "python.exe",
        root / "runtime" / "bin" / "python",
        root / "python312" / "python.exe",
        root / "python312" / "bin" / "python",
    ]
    system_python = _system_python()
    if system_python:
        candidates.append(system_python)
    return candidates


def _bootstrap_venv_if_possible(root: Path, env: dict[str, str]) -> Path | None:
    venv_python = _venv_python(root)
    if venv_python.exists():
        return venv_python

    bootstrap = root / "scripts" / "bootstrap.py"
    if not bootstrap.exists():
        return None

    if os.name == "nt":
        base_python = root / "python312" / "python.exe"
        venv_helper = root / "scripts" / "windows_venv.py"
        if not base_python.exists() or not venv_helper.exists():
            return None

        print("[JOYBOY] Bundled venv missing; preparing it from bundled Python...")
        first = subprocess.run([str(base_python), str(venv_helper), "ensure"], cwd=str(root), env=env)
        if first.returncode != 0 or not venv_python.exists():
            return None
    else:
        base_python = _system_python()
        if not base_python:
            return None

        print("[JOYBOY] Bundled venv missing; preparing it from system Python...")
        first = subprocess.run([str(base_python), "-m", "venv", "venv"], cwd=str(root), env=env)
        if first.returncode != 0 or not venv_python.exists():
            return None

    second = subprocess.run([str(venv_python), str(bootstrap), "setup"], cwd=str(root), env=env)
    if second.returncode != 0:
        return None
    return venv_python


def _find_python(root: Path, env: dict[str, str]) -> Path | None:
    bootstrapped = _bootstrap_venv_if_possible(root, env)
    if bootstrapped:
        return bootstrapped
    for candidate in _candidate_pythons(root):
        if candidate.exists():
            return candidate
    return None


def _open_browser_when_ready() -> None:
    if os.environ.get("JOYBOY_OPEN_BROWSER", "1").strip().lower() in {"0", "false", "no"}:
        return

    def worker() -> None:
        for _ in range(90):
            try:
                with urllib.request.urlopen(APP_URL, timeout=1):
                    webbrowser.open(APP_URL)
                    return
            except Exception:
                time.sleep(1)
        webbrowser.open(APP_URL)

    threading.Thread(target=worker, daemon=True).start()


def _pause_on_error() -> None:
    if os.environ.get("JOYBOY_NO_PAUSE", "").strip():
        return
    try:
        input("\nPress Enter to close JoyBoy...")
    except EOFError:
        pass


def main() -> int:
    root = _app_root()
    app = root / "web" / "app.py"
    env = _configure_env(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    if not app.exists():
        print(f"[JOYBOY] web/app.py not found in packaged app root: {root}")
        _pause_on_error()
        return 1

    python = _find_python(root, env)
    if not python:
        print("[JOYBOY] No bundled Python runtime was found.")
        print("[JOYBOY] Expected a packaged venv/runtime, or a system python3 that can create one.")
        _pause_on_error()
        return 1

    os.chdir(root)
    print("[JOYBOY] Starting JoyBoy desktop launcher")
    print(f"[JOYBOY] App root: {root}")
    print(f"[JOYBOY] Python : {python}")
    print(f"[JOYBOY] URL    : {APP_URL}")
    _open_browser_when_ready()

    job = None
    assigned = False
    if os.name == "nt":
        try:
            from core.infra.windows_job import assign_process_to_job, close_job, create_kill_on_close_job

            job = create_kill_on_close_job()
        except Exception as exc:
            print(f"[JOYBOY] Windows process guard unavailable: {exc}")
            close_job = None  # type: ignore[assignment]
            assign_process_to_job = None  # type: ignore[assignment]

    process = subprocess.Popen([str(python), str(app)], cwd=str(root), env=env)
    if job and assign_process_to_job:
        assigned = bool(assign_process_to_job(job, process))
        if not assigned:
            print("[JOYBOY] Windows process guard could not attach; continuing without it.")

    try:
        return int(process.wait() or 0)
    finally:
        if job and close_job:
            close_job(job)


if __name__ == "__main__":
    raise SystemExit(main())
