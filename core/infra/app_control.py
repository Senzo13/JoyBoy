"""Application update and restart helpers.

Keep process control in one place so UI routes can trigger the same restart
path on Windows, Linux, and macOS.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List


PROJECT_DIR = Path(__file__).resolve().parents[2]


def _run_git(args: List[str], timeout: float = 60.0) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": "git is not installed or not available in PATH",
        }
    except Exception as exc:
        return {"ok": False, "returncode": 1, "stdout": "", "stderr": str(exc)}

    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
    }


def _trim_output(value: str, limit: int = 4000) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[-limit:]


def _popen_detached(command: List[str], *, shell: bool = False) -> None:
    kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_DIR),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        "shell": shell,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command if not shell else " ".join(command), **kwargs)


def launch_new_instance() -> None:
    """Start JoyBoy again using the platform launcher when available."""
    system = platform.system()

    if system == "Windows":
        script = PROJECT_DIR / "start_windows.bat"
        if script.exists():
            # "start" is a cmd builtin, so shell=True is intentional here.
            subprocess.Popen(
                f'start "JoyBoy" cmd /c "{script}" --restart',
                cwd=str(PROJECT_DIR),
                shell=True,
            )
            return

    if system == "Darwin":
        script = PROJECT_DIR / "start_mac.command"
        if script.exists():
            _popen_detached(["/bin/bash", str(script), "--restart"])
            return

    script = PROJECT_DIR / "start_linux.sh"
    if script.exists():
        _popen_detached(["/bin/bash", str(script), "--restart"])
        return

    _popen_detached([sys.executable, str(PROJECT_DIR / "web" / "app.py")])


def schedule_restart(delay_seconds: float = 0.8) -> None:
    """Launch a new JoyBoy instance and terminate the current backend shortly after."""

    def _restart() -> None:
        time.sleep(max(0.1, delay_seconds))
        launch_new_instance()
        time.sleep(0.3)
        os._exit(42)

    threading.Thread(target=_restart, daemon=True).start()


def pull_git_updates(*, restart: bool = True) -> Dict[str, Any]:
    """Run a safe git pull for the active JoyBoy checkout.

    The pull is fast-forward only and refuses to continue when local files are
    modified, which keeps the public core from silently overwriting local work.
    """
    if not (PROJECT_DIR / ".git").exists():
        return {
            "success": False,
            "code": "not_git_checkout",
            "error": "JoyBoy is not running from a git checkout.",
        }

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=5.0)
    if not branch["ok"] or not branch["stdout"]:
        return {
            "success": False,
            "code": "git_branch_failed",
            "error": branch["stderr"] or "Could not read the current git branch.",
        }
    current_branch = branch["stdout"]
    if current_branch == "HEAD":
        return {
            "success": False,
            "code": "detached_head",
            "error": "JoyBoy is on a detached git commit. Checkout a branch before updating.",
        }

    status = _run_git(["status", "--porcelain"], timeout=5.0)
    if not status["ok"]:
        return {
            "success": False,
            "code": "git_status_failed",
            "error": status["stderr"] or "Could not read git status.",
        }
    dirty_files = [line[3:] for line in status["stdout"].splitlines() if len(line) >= 4]
    if dirty_files:
        return {
            "success": False,
            "code": "local_changes",
            "error": "Local changes would be overwritten by git pull.",
            "dirty_files": dirty_files[:50],
        }

    before = _run_git(["rev-parse", "HEAD"], timeout=5.0)
    before_commit = before["stdout"] if before["ok"] else ""

    fetch = _run_git(["fetch", "origin", current_branch], timeout=90.0)
    if not fetch["ok"]:
        return {
            "success": False,
            "code": "git_fetch_failed",
            "error": fetch["stderr"] or fetch["stdout"] or "git fetch failed.",
            "output": _trim_output(fetch["stdout"] + "\n" + fetch["stderr"]),
        }

    pull = _run_git(["pull", "--ff-only", "origin", current_branch], timeout=180.0)
    if not pull["ok"]:
        return {
            "success": False,
            "code": "git_pull_failed",
            "error": pull["stderr"] or pull["stdout"] or "git pull failed.",
            "output": _trim_output(pull["stdout"] + "\n" + pull["stderr"]),
        }

    after = _run_git(["rev-parse", "HEAD"], timeout=5.0)
    after_commit = after["stdout"] if after["ok"] else ""
    updated = bool(before_commit and after_commit and before_commit != after_commit)

    if restart:
        schedule_restart()

    return {
        "success": True,
        "code": "updated" if updated else "already_current",
        "branch": current_branch,
        "before": before_commit,
        "after": after_commit,
        "updated": updated,
        "restart_scheduled": bool(restart),
        "output": _trim_output(pull["stdout"] + "\n" + pull["stderr"]),
    }

