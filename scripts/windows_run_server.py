"""Run JoyBoy's Flask server under a Windows kill-on-close process job."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.infra.windows_job import assign_process_to_job, close_job, create_kill_on_close_job


def _stop_process(process: subprocess.Popen[object], job: int | None) -> int:
    if process.poll() is not None:
        return int(process.returncode or 0)

    try:
        process.terminate()
        return int(process.wait(timeout=8) or 0)
    except Exception:
        # Closing the job is the reliable last resort for a venv python.exe
        # redirector plus its base-python child.
        if job:
            close_job(job)
            return 130
        try:
            process.kill()
        except Exception:
            pass
        return 130


def main() -> int:
    os.chdir(PROJECT_DIR)

    job: int | None = None
    if os.name == "nt":
        try:
            job = create_kill_on_close_job()
        except Exception as exc:
            print(f"[STARTUP] Windows process guard unavailable: {exc}")
            job = None

    process = subprocess.Popen(
        [sys.executable, "-u", str(PROJECT_DIR / "web" / "app.py")],
        cwd=str(PROJECT_DIR),
        env=os.environ.copy(),
    )

    assigned = False
    if job:
        assigned = assign_process_to_job(job, process)
        if not assigned:
            print("[STARTUP] Windows process guard could not attach; continuing without it.")

    try:
        return int(process.wait() or 0)
    except KeyboardInterrupt:
        return _stop_process(process, job if assigned else None)
    finally:
        if job:
            close_job(job)


if __name__ == "__main__":
    raise SystemExit(main())
