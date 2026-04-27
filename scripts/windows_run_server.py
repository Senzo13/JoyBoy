"""Run JoyBoy's Flask server under a Windows kill-on-close process job."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TextIO


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from core.infra.windows_job import assign_process_to_job, close_job, create_kill_on_close_job


LOG_DIR = PROJECT_DIR / ".joyboy" / "logs"
SERVER_LOG = LOG_DIR / "windows_server_last.log"


def _write_header(log: TextIO) -> None:
    log.write(f"JoyBoy Windows server log - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"Python: {sys.executable}\n")
    log.write(f"Project: {PROJECT_DIR}\n")
    log.flush()


def _tee_output(stream: object, log: TextIO) -> None:
    try:
        for line in stream:  # type: ignore[union-attr]
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
    except Exception as exc:
        print(f"[STARTUP] Log capture stopped: {exc}")


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
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    job: int | None = None
    if os.name == "nt":
        try:
            job = create_kill_on_close_job()
        except Exception as exc:
            print(f"[STARTUP] Windows process guard unavailable: {exc}")
            job = None

    with SERVER_LOG.open("w", encoding="utf-8", errors="replace") as log:
        _write_header(log)
        process = subprocess.Popen(
            [sys.executable, "-u", str(PROJECT_DIR / "web" / "app.py")],
            cwd=str(PROJECT_DIR),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        output_thread = threading.Thread(target=_tee_output, args=(process.stdout, log), daemon=True)
        output_thread.start()

        assigned = False
        if job:
            assigned = assign_process_to_job(job, process)
            if not assigned:
                print("[STARTUP] Windows process guard could not attach; continuing without it.")

        try:
            exit_code = int(process.wait() or 0)
            output_thread.join(timeout=2)
            log.write(f"\n[exit {exit_code}]\n")
            return exit_code
        except KeyboardInterrupt:
            exit_code = _stop_process(process, job if assigned else None)
            log.write(f"\n[interrupted exit {exit_code}]\n")
            return exit_code
        finally:
            if job:
                close_job(job)


if __name__ == "__main__":
    raise SystemExit(main())
