"""Build macOS/Linux desktop distributions for JoyBoy.

The package contains a small executable launcher plus the public JoyBoy core.
It intentionally excludes model weights, generated files, secrets, and private
local pack sources. Users install models and packs from inside JoyBoy.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR_FOR_IMPORT = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR_FOR_IMPORT))

from scripts.package_windows import (
    PROJECT_DIR,
    DIST_DIR,
    BUILD_DIR,
    PUBLIC_DIRS,
    PUBLIC_FILES,
    _copy_path,
    _is_inside,
)


LAUNCHER_PATH = PROJECT_DIR / "packaging" / "windows" / "joyboy_launcher.py"


def _default_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _package_dir(package_name: str) -> Path:
    return DIST_DIR / package_name


def _reset_package_dir(package_dir: Path) -> None:
    if package_dir.exists():
        if not _is_inside(package_dir, DIST_DIR):
            raise RuntimeError(f"Refusing to remove unexpected path: {package_dir}")
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)


def _copy_public_core(package_dir: Path, platform_name: str) -> None:
    base_files = tuple(name for name in PUBLIC_FILES if name != "start_windows.bat")
    extra_files = {
        "macos": ("start_mac.command",),
        "linux": ("start_linux.sh",),
    }.get(platform_name, ())
    for name in (*base_files, *extra_files):
        source = PROJECT_DIR / name
        if source.exists():
            _copy_path(source, package_dir / name)
    for name in PUBLIC_DIRS:
        source = PROJECT_DIR / name
        if source.exists():
            _copy_path(source, package_dir / name)


def _ensure_pyinstaller(install_build_deps: bool) -> None:
    try:
        import PyInstaller  # noqa: F401
        return
    except ImportError:
        if not install_build_deps:
            raise SystemExit(
                "PyInstaller is required. Re-run with --install-build-deps "
                "or install it with: python -m pip install pyinstaller"
            )
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)


def _build_launcher(platform_name: str, install_build_deps: bool) -> Path:
    _ensure_pyinstaller(install_build_deps)
    launcher_dist = BUILD_DIR / platform_name / "launcher-dist"
    launcher_work = BUILD_DIR / platform_name / "pyinstaller-work"
    launcher_spec = BUILD_DIR / platform_name / "pyinstaller-spec"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        "JoyBoy",
        "--distpath",
        str(launcher_dist),
        "--workpath",
        str(launcher_work),
        "--specpath",
        str(launcher_spec),
        str(LAUNCHER_PATH),
    ]
    print(f"[PACKAGE] Building JoyBoy launcher for {platform_name}...")
    subprocess.run(command, cwd=str(PROJECT_DIR), check=True)
    executable = launcher_dist / "JoyBoy"
    if not executable.exists():
        raise RuntimeError(f"PyInstaller did not create {executable}")
    return executable


def _write_portable_data_dirs(package_dir: Path) -> None:
    data = package_dir / "data"
    for child in ("models", "packs", "cache", "output", "logs"):
        (data / child).mkdir(parents=True, exist_ok=True)


def _write_readme(package_dir: Path, platform_name: str, launcher: str, runtime_included: bool) -> None:
    runtime_note = "included" if runtime_included else "not included"
    readme = f"""JoyBoy {platform_name} Package

Run ./{launcher} to start the app.

Runtime: {runtime_note}
User data: data/
URL: http://127.0.0.1:7860

This package intentionally does not include model weights, generated outputs,
local secrets, or private local pack sources. Install models and packs from
inside JoyBoy after launch.

The launcher pins Hugging Face downloads to:

  data/models/huggingface

Set JOYBOY_PORTABLE=0 before launching if an installer should use the normal
user data location instead of this package's data/ folder.
"""
    (package_dir / "README_FIRST.txt").write_text(readme, encoding="utf-8")


def _write_shell_launcher(package_dir: Path, platform_name: str, launcher: str) -> None:
    start_script = "start_mac.command" if platform_name == "macos" else "start_linux.sh"
    content = f"""#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec ./{start_script} "$@"
"""
    (package_dir / launcher).write_text(content, encoding="utf-8", newline="\n")


def _write_manifest(package_dir: Path, platform_name: str, launcher: str, runtime_included: bool) -> None:
    version_path = PROJECT_DIR / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
    manifest = {
        "name": "JoyBoy",
        "version": version,
        "platform": platform_name,
        "launcher": launcher,
        "runtime_included": runtime_included,
        "portable_data_dir": "data",
    }
    (package_dir / "joyboy-package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _chmod_launchers(package_dir: Path, launcher: str) -> None:
    for path in [package_dir / launcher, package_dir / "start_linux.sh", package_dir / "start_mac.command"]:
        if path.exists():
            current = path.stat().st_mode
            path.chmod(current | 0o755)


def build_package(
    platform_name: str,
    package_name: str,
    *,
    install_build_deps: bool,
    skip_launcher: bool,
) -> Path:
    package_dir = _package_dir(package_name)
    _reset_package_dir(package_dir)
    _copy_public_core(package_dir, platform_name)
    _write_portable_data_dirs(package_dir)

    launcher = "JoyBoy"
    if not skip_launcher:
        executable = _build_launcher(platform_name, install_build_deps)
        shutil.copy2(executable, package_dir / launcher)
    else:
        print("[PACKAGE] Skipped native launcher build; writing shell launcher.")
        _write_shell_launcher(package_dir, platform_name, launcher)

    _chmod_launchers(package_dir, launcher)
    _write_readme(package_dir, platform_name, launcher, runtime_included=False)
    _write_manifest(package_dir, platform_name, launcher, runtime_included=False)
    return package_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a JoyBoy macOS/Linux package.")
    parser.add_argument("--platform", default=_default_platform(), choices=("macos", "linux"))
    parser.add_argument("--package-name", help="Output folder name under dist/")
    parser.add_argument("--install-build-deps", action="store_true", help="Install PyInstaller if missing")
    parser.add_argument("--skip-launcher", action="store_true", help="Copy files without building JoyBoy")
    args = parser.parse_args()

    platform_name = str(args.platform)
    package_name = args.package_name or f"JoyBoy-{platform_name}"
    package = build_package(
        platform_name,
        package_name,
        install_build_deps=bool(args.install_build_deps),
        skip_launcher=bool(args.skip_launcher),
    )
    print(f"[PACKAGE] {platform_name} package ready: {package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
