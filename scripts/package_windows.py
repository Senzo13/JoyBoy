"""Build a Windows desktop distribution for JoyBoy.

The output is a folder-based package:

    dist/JoyBoy-win-x64/
        JoyBoy.exe
        web/
        core/
        scripts/
        venv/              optional, copied when --include-runtime is used
        python312/         optional, copied when present
        data/              portable user data root

Model weights, generated output, local config, and local pack sources are not
copied from the repository. Users install or import them from the app.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build" / "windows"
PACKAGE_DIR = DIST_DIR / "JoyBoy-win-x64"
ICON_PATH = PROJECT_DIR / "packaging" / "assets" / "joyboy.ico"
LAUNCHER_PATH = PROJECT_DIR / "packaging" / "windows" / "joyboy_launcher.py"

PUBLIC_FILES = (
    ".env.example",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "VERSION",
    "config.py",
    "start_windows.bat",
)

PUBLIC_DIRS = (
    "core",
    "docs",
    "gpu_profiles",
    "packaging",
    "prompts",
    "scripts",
    "utils",
    "web",
)

EXCLUDED_DIR_NAMES = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    ".joyboy",
    "__pycache__",
    "build",
    "checkpoints",
    "dist",
    "ext_weights",
    "Fooocus",
    "local_pack_sources",
    "models",
    "output",
    "tmpntigp4w4",
    "trained_loras",
    "training_data",
}

EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    "release_plan.json",
    "tunnel_config.json",
}

EXCLUDED_SUFFIXES = {
    ".ckpt",
    ".egg-info",
    ".log",
    ".pt",
    ".pt2",
    ".pth",
    ".pyc",
    ".pyo",
    ".safetensors",
}


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _remove_package_dir() -> None:
    if PACKAGE_DIR.exists():
        if not _is_inside(PACKAGE_DIR, DIST_DIR):
            raise RuntimeError(f"Refusing to remove unexpected path: {PACKAGE_DIR}")
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)


def _ignore_names(_src: str, names: Iterable[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(name)
        suffixes = "".join(path.suffixes)
        if name in EXCLUDED_DIR_NAMES or name in EXCLUDED_FILE_NAMES:
            ignored.add(name)
        elif path.suffix in EXCLUDED_SUFFIXES or suffixes in EXCLUDED_SUFFIXES:
            ignored.add(name)
        elif name.startswith("public_live_"):
            ignored.add(name)
    return ignored


def _copy_path(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, ignore=_ignore_names)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_public_core() -> None:
    for name in PUBLIC_FILES:
        source = PROJECT_DIR / name
        if source.exists():
            _copy_path(source, PACKAGE_DIR / name)
    for name in PUBLIC_DIRS:
        source = PROJECT_DIR / name
        if source.exists():
            _copy_path(source, PACKAGE_DIR / name)


def _copy_runtime(include_runtime: bool) -> None:
    if not include_runtime:
        return

    runtime_dirs = ("python312", "venv")
    copied = []
    for name in runtime_dirs:
        source = PROJECT_DIR / name
        if source.exists():
            print(f"[PACKAGE] Copying {name} runtime. This can take a while...")
            _copy_path(source, PACKAGE_DIR / name)
            copied.append(name)

    if "venv" not in copied:
        print("[PACKAGE] WARNING: venv was not copied. JoyBoy.exe may need first-run setup.")
    if "python312" not in copied:
        print("[PACKAGE] WARNING: python312 was not copied. Bundled setup fallback will be unavailable.")


def _ensure_icon() -> None:
    if ICON_PATH.exists():
        return
    print("[PACKAGE] Windows icon missing; generating it from the JoyBoy monogram...")
    from scripts.generate_app_icons import generate_windows_icon

    generate_windows_icon()


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


def _build_launcher(install_build_deps: bool) -> Path:
    _ensure_icon()
    _ensure_pyinstaller(install_build_deps)
    launcher_dist = BUILD_DIR / "launcher-dist"
    launcher_work = BUILD_DIR / "pyinstaller-work"
    launcher_spec = BUILD_DIR / "pyinstaller-spec"
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
        "--icon",
        str(ICON_PATH),
        "--distpath",
        str(launcher_dist),
        "--workpath",
        str(launcher_work),
        "--specpath",
        str(launcher_spec),
        str(LAUNCHER_PATH),
    ]
    print("[PACKAGE] Building JoyBoy.exe launcher...")
    subprocess.run(command, cwd=str(PROJECT_DIR), check=True)
    exe = launcher_dist / "JoyBoy.exe"
    if not exe.exists():
        raise RuntimeError(f"PyInstaller did not create {exe}")
    return exe


def _write_portable_data_dirs() -> None:
    data = PACKAGE_DIR / "data"
    for child in ("models", "packs", "cache", "output", "logs"):
        (data / child).mkdir(parents=True, exist_ok=True)


def _write_readme(include_runtime: bool) -> None:
    runtime_note = "included" if include_runtime else "not included"
    readme = f"""JoyBoy Windows Package

Run JoyBoy.exe to start the app.

Runtime: {runtime_note}
User data: data/
URL: http://127.0.0.1:7860

This package intentionally does not include model weights, generated outputs,
local secrets, or private local pack sources. Install models and packs from
inside JoyBoy after launch.

Set JOYBOY_PORTABLE=0 before launching if an installer should use the normal
user data location instead of this package's data/ folder.
"""
    (PACKAGE_DIR / "README_FIRST.txt").write_text(readme, encoding="utf-8")


def _write_manifest(include_runtime: bool) -> None:
    version_path = PROJECT_DIR / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else "unknown"
    manifest = {
        "name": "JoyBoy",
        "version": version,
        "platform": "windows-x64",
        "launcher": "JoyBoy.exe",
        "icon": "packaging/assets/joyboy.ico",
        "runtime_included": include_runtime,
        "portable_data_dir": "data",
    }
    (PACKAGE_DIR / "joyboy-package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def build_package(include_runtime: bool, install_build_deps: bool, skip_launcher: bool) -> Path:
    _remove_package_dir()
    _copy_public_core()
    _copy_runtime(include_runtime)
    _write_portable_data_dirs()

    if not skip_launcher:
        exe = _build_launcher(install_build_deps)
        shutil.copy2(exe, PACKAGE_DIR / "JoyBoy.exe")
    else:
        print("[PACKAGE] Skipped launcher build; JoyBoy.exe was not created.")

    _write_readme(include_runtime)
    _write_manifest(include_runtime)
    return PACKAGE_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a JoyBoy Windows package.")
    parser.add_argument("--include-runtime", dest="include_runtime", action="store_true", default=True)
    parser.add_argument("--no-runtime", dest="include_runtime", action="store_false")
    parser.add_argument("--install-build-deps", action="store_true", help="Install PyInstaller if missing")
    parser.add_argument("--skip-launcher", action="store_true", help="Copy files without building JoyBoy.exe")
    args = parser.parse_args()

    package = build_package(
        include_runtime=bool(args.include_runtime),
        install_build_deps=bool(args.install_build_deps),
        skip_launcher=bool(args.skip_launcher),
    )
    print(f"[PACKAGE] Windows package ready: {package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
