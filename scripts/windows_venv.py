"""
Windows venv bootstrap for JoyBoy.

The batch launcher can download portable Python, but Python is much better at
creating/removing/verifying virtual environments and at reporting useful errors.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
PYTHON_EXE = PROJECT_DIR / "python312" / "python.exe"
VENV_DIR = PROJECT_DIR / "venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
LOG_DIR = PROJECT_DIR / ".joyboy" / "logs"
LOG_PATH = LOG_DIR / "windows_setup_last.log"


def _write_log(text: str, append: bool = True) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with LOG_PATH.open(mode, encoding="utf-8") as handle:
        handle.write(text)
        if text and not text.endswith("\n"):
            handle.write("\n")


def _run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    _write_log("> " + " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.stdout:
        _write_log(result.stdout)
    if result.stderr:
        _write_log(result.stderr)
    _write_log(f"[exit {result.returncode}]")
    return result


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def _make_writable(func, path, _exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    func(path)


def _remove_partial_venv() -> bool:
    if not VENV_DIR.exists():
        return True

    print("    Removing old incomplete/incompatible venv...")
    try:
        shutil.rmtree(VENV_DIR, onerror=_make_writable)
        return True
    except Exception as exc:
        _write_log(f"Failed to remove venv: {exc}")
        print("    [ERROR] Could not remove the old venv.")
        print("    Close any JoyBoy/Python terminals using it, then run setup again.")
        print(f"    Log: {LOG_PATH}")
        return False


def _python_version_ok(python_exe: Path) -> bool:
    if not python_exe.exists():
        return False
    result = _run(
        [
            str(python_exe),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        timeout=15,
    )
    return result.returncode == 0 and result.stdout.strip() == "3.12"


def _portable_python_ok() -> bool:
    if not PYTHON_EXE.exists():
        print(f"    [ERROR] Portable Python not found: {PYTHON_EXE}")
        return False
    if not _python_version_ok(PYTHON_EXE):
        print("    [ERROR] Invalid portable Python: expected version 3.12")
        print(f"    Log: {LOG_PATH}")
        return False
    result = _run([str(PYTHON_EXE), "-c", "import ensurepip; import venv"], timeout=15)
    if result.returncode != 0:
        print("    [ERROR] Portable Python is incomplete: ensurepip/venv unavailable")
        print(f"    Log: {LOG_PATH}")
        return False
    return True


def _venv_ok() -> bool:
    if not VENV_PYTHON.exists():
        return False
    if not _python_version_ok(VENV_PYTHON):
        return False
    result = _run([str(VENV_PYTHON), "-m", "pip", "--version"], timeout=20)
    return result.returncode == 0


def ensure_venv() -> int:
    _write_log("JoyBoy Windows setup log\n", append=False)

    if not _portable_python_ok():
        return 10

    if _venv_ok():
        print("    [OK] Python 3.12 venv is working")
        return 0

    if not _remove_partial_venv():
        return 20

    print("    Creating Python 3.12 venv...")
    result = _run([str(PYTHON_EXE), "-m", "venv", str(VENV_DIR)], timeout=180)
    if result.returncode != 0:
        print("    [ERROR] Could not create the Python 3.12 venv")
        if result.stderr:
            print("    Last error:")
            print(_tail(result.stderr))
        print(f"    Full log: {LOG_PATH}")
        return 30

    if not VENV_PYTHON.exists():
        print("    [ERROR] Venv was created, but python.exe was not found")
        print(f"    Expected path: {VENV_PYTHON}")
        print(f"    Full log: {LOG_PATH}")
        return 31

    result = _run([str(VENV_PYTHON), "-m", "ensurepip", "--upgrade"], timeout=180)
    if result.returncode != 0:
        print("    [ERROR] Pip is unavailable in the venv")
        if result.stderr:
            print(_tail(result.stderr))
        print(f"    Full log: {LOG_PATH}")
        return 32

    result = _run([str(VENV_PYTHON), "-m", "pip", "--version"], timeout=30)
    if result.returncode != 0:
        print("    [ERROR] Could not verify pip inside the venv")
        print(f"    Full log: {LOG_PATH}")
        return 33

    print("    [OK] Venv created and verified")
    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "ensure"
    if command != "ensure":
        print("Usage: windows_venv.py ensure")
        return 2
    return ensure_venv()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
