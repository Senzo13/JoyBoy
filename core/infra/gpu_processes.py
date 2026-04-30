"""GPU process inspection helpers.

These helpers intentionally stay generic: they do not assume a specific cloud
provider and only kill processes that can be tied back to the current JoyBoy
checkout or its local LightX2V worker.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_proc_text(pid: int, name: str) -> str:
    try:
        raw = Path(f"/proc/{pid}/{name}").read_bytes()
    except Exception:
        return ""
    if name == "cmdline":
        return raw.replace(b"\0", b" ").decode("utf-8", errors="ignore").strip()
    return raw.decode("utf-8", errors="ignore").strip()


def _read_proc_cwd(pid: int) -> str:
    try:
        return str(Path(f"/proc/{pid}/cwd").resolve())
    except Exception:
        return ""


def _is_under(path: str, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def build_gpu_process_record(
    *,
    pid: int,
    process_name: str,
    used_memory_mb: float,
    cmdline: str = "",
    cwd: str = "",
    current_pid: int | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict:
    """Build a frontend-safe process record from nvidia-smi fields."""
    current_pid = os.getpid() if current_pid is None else current_pid
    cmd = (cmdline or "").strip()
    proc = (process_name or "").strip()
    root = project_root.resolve()
    root_s = str(root)
    web_app = str(root / "web" / "app.py")

    is_current = int(pid) == int(current_pid)
    is_lightx2v = "lightx2v" in cmd.lower() or "lightx2v" in proc.lower()
    is_repo_process = (
        web_app in cmd
        or (("web/app.py" in cmd or "web\\app.py" in cmd) and _is_under(cwd, root))
        or root_s in cmd
        or _is_under(cwd, root)
    )
    is_joyboy = is_current or is_repo_process or is_lightx2v

    if is_current:
        kind = "current"
        label = "JoyBoy serveur actuel"
    elif is_repo_process:
        kind = "joyboy"
        label = "Ancien JoyBoy"
    elif is_lightx2v:
        kind = "joyboy-worker"
        label = "Worker LightX2V"
    else:
        kind = "external"
        label = "Process externe"

    display_cmd = cmd or proc
    if len(display_cmd) > 160:
        display_cmd = display_cmd[:157] + "..."

    return {
        "pid": int(pid),
        "process_name": proc,
        "cmd": display_cmd,
        "cwd": cwd,
        "used_mb": round(float(used_memory_mb), 1),
        "used_gb": round(float(used_memory_mb) / 1024, 2),
        "kind": kind,
        "label": label,
        "is_current": is_current,
        "is_joyboy": is_joyboy,
        "killable": bool(is_joyboy and not is_current),
    }


def list_gpu_processes(project_root: Path = PROJECT_ROOT) -> list[dict]:
    """Return CUDA processes reported by nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    processes: list[dict] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.upper() == "N/A":
            continue
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            used_mb = float(parts[2])
        except ValueError:
            continue
        processes.append(
            build_gpu_process_record(
                pid=pid,
                process_name=parts[1],
                used_memory_mb=used_mb,
                cmdline=_read_proc_text(pid, "cmdline"),
                cwd=_read_proc_cwd(pid),
                project_root=project_root,
            )
        )
    return processes


def kill_stale_joyboy_gpu_processes(project_root: Path = PROJECT_ROOT, timeout: float = 1.0) -> list[dict]:
    """Terminate stale JoyBoy GPU processes, never the current server."""
    targets = [proc for proc in list_gpu_processes(project_root) if proc.get("killable")]
    killed: list[dict] = []
    for proc in targets:
        try:
            os.kill(int(proc["pid"]), signal.SIGTERM)
            killed.append({**proc, "signal": "TERM"})
        except ProcessLookupError:
            continue
        except PermissionError:
            killed.append({**proc, "signal": "DENIED"})

    if targets and timeout > 0:
        time.sleep(timeout)

    for proc in targets:
        pid = int(proc["pid"])
        if not Path(f"/proc/{pid}").exists():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append({**proc, "signal": "KILL"})
        except (ProcessLookupError, PermissionError):
            pass
    return killed
