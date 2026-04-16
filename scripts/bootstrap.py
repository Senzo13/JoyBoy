"""
Cross-platform bootstrap helpers for JoyBoy.

This keeps the platform launchers thin and gives contributors one Python
entrypoint for setup and doctor checks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
INSTALL_DEPS = PROJECT_DIR / "scripts" / "install_deps.py"
CHECK_DEPS = PROJECT_DIR / "scripts" / "check_deps.py"
PUBLIC_MIRROR_BUILDER = PROJECT_DIR / "scripts" / "build_public_mirror.py"
DEFAULT_LOCAL_ADULT_PACK_SOURCE = PROJECT_DIR / "local_pack_sources" / "local-advanced-runtime"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))


def _run(command: list[str], title: str) -> int:
    print(f"\n[BOOTSTRAP] {title}")
    print(f"[BOOTSTRAP] > {' '.join(command)}")
    completed = subprocess.run(command, cwd=str(PROJECT_DIR))
    return int(completed.returncode or 0)


def run_setup() -> int:
    exit_code = _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], "Upgrade pip")
    if exit_code != 0:
        return exit_code

    exit_code = _run([sys.executable, str(INSTALL_DEPS)], "Install base dependencies")
    if exit_code != 0:
        return exit_code

    return _run([sys.executable, str(CHECK_DEPS)], "Verify optimized dependencies")


def run_doctor(json_mode: bool = False) -> int:
    from core.infra.doctor import run_doctor

    report = run_doctor()
    if json_mode:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("\nJoyBoy Doctor")
    print("=" * 40)
    print(f"Status : {report['status'].upper()}")
    print(f"Résumé : {report['summary']}")
    print("")
    for check in report.get("checks", []):
        print(f"- [{check['status'].upper()}] {check['label']}: {check['detail']}")
        if check.get("action"):
            print(f"  Action: {check['action']}")
    return 0 if report.get("status") != "error" else 1


def run_mirror(target: str | None = None, dry_run: bool = False, json_mode: bool = False, overwrite: bool = False) -> int:
    command = [sys.executable, str(PUBLIC_MIRROR_BUILDER)]
    if target:
        command.extend(["--target", target])
    if dry_run:
        command.append("--dry-run")
    if json_mode:
        command.append("--json")
    if overwrite:
        command.append("--overwrite")
    return _run(command, "Build public mirror")


def run_pack_install(source: str | None = None, kind: str = "adult", activate: bool = True, replace: bool = True) -> int:
    from core.infra.packs import import_pack_from_directory, set_pack_active

    source_path = Path(source).expanduser() if source else DEFAULT_LOCAL_ADULT_PACK_SOURCE
    if not source_path.exists():
        print(f"[PACK] Source introuvable: {source_path}")
        return 1

    print(f"[PACK] Import depuis {source_path}")
    pack = import_pack_from_directory(str(source_path), replace=replace)
    print(f"[PACK] Installé: {pack['name']} ({pack['id']})")

    if activate:
        set_pack_active(pack["id"], enabled=True)
        print(f"[PACK] Activé localement pour kind={kind}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="JoyBoy bootstrap helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Install/update Python dependencies and run dependency checks")
    doctor_parser = subparsers.add_parser("doctor", help="Run JoyBoy doctor checks")
    doctor_parser.add_argument("--json", action="store_true", help="Print doctor report as JSON")
    mirror_parser = subparsers.add_parser("mirror", help="Preview or build a clean public mirror")
    mirror_parser.add_argument("--target", help="Target directory for the public mirror")
    mirror_parser.add_argument("--dry-run", action="store_true", help="Preview files without copying")
    mirror_parser.add_argument("--json", action="store_true", help="Print mirror result as JSON")
    mirror_parser.add_argument("--overwrite", action="store_true", help="Overwrite target directory if it exists")
    pack_parser = subparsers.add_parser("pack-install", help="Install a local pack source into ~/.joyboy/packs")
    pack_parser.add_argument("--source", help="Local pack source directory")
    pack_parser.add_argument("--kind", default="adult", help="Pack kind to activate after import")
    pack_parser.add_argument("--no-activate", action="store_true", help="Import without activating the pack")
    pack_parser.add_argument("--no-replace", action="store_true", help="Do not overwrite an existing pack with the same id")

    args = parser.parse_args()

    if args.command == "setup":
        return run_setup()
    if args.command == "doctor":
        return run_doctor(json_mode=bool(args.json))
    if args.command == "mirror":
        return run_mirror(
            target=args.target,
            dry_run=bool(args.dry_run),
            json_mode=bool(args.json),
            overwrite=bool(args.overwrite),
        )
    if args.command == "pack-install":
        return run_pack_install(
            source=args.source,
            kind=args.kind,
            activate=not bool(args.no_activate),
            replace=not bool(args.no_replace),
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
