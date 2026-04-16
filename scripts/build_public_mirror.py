"""
Build or preview a clean public mirror from the private JoyBoy workspace.

The goal is not to rewrite Git history here, but to make it easy to:
- preview which files belong in the future public repo
- copy a clean mirror to another directory
- keep sensitive/private assets explicitly excluded via public_mirror.exclude
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infra.public_mirror import (
    DEFAULT_PUBLIC_MIRROR_EXCLUDE_FILE,
    PROJECT_DIR,
    collect_public_mirror_files,
    is_text_mirror_file,
    load_public_mirror_patterns,
    transform_public_mirror_text,
)

DEFAULT_EXCLUDE_FILE = DEFAULT_PUBLIC_MIRROR_EXCLUDE_FILE


def _replace_target_dir(temp_dir: Path, target: Path) -> None:
    """Atomically replace target when possible, with a Windows-friendly fallback.

    Explorer or a previously launched preview can keep the target directory handle
    open even after every file inside it has been removed. In that case Windows
    refuses to delete the directory itself. Keeping the directory and replacing
    its contents avoids leaving duplicate mirror folders around.
    """
    if not target.exists():
        temp_dir.replace(target)
        return

    try:
        shutil.rmtree(target)
        temp_dir.replace(target)
        return
    except Exception:
        # Fallback: preserve the locked target directory, clear whatever remains,
        # then move the freshly built mirror contents into it.
        target.mkdir(parents=True, exist_ok=True)
        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in temp_dir.iterdir():
            shutil.move(str(child), str(target / child.name))
        shutil.rmtree(temp_dir, ignore_errors=True)


def build_public_mirror(
    target_dir: Path | str,
    source_dir: Path | None = None,
    exclude_file: Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict:
    root = Path(source_dir or PROJECT_DIR).resolve()
    target = Path(target_dir).expanduser().resolve()
    patterns = load_public_mirror_patterns(exclude_file)
    files = collect_public_mirror_files(root, patterns)

    result = {
        "source": str(root),
        "target": str(target),
        "exclude_file": str(Path(exclude_file or DEFAULT_EXCLUDE_FILE).resolve()),
        "exclude_patterns": patterns,
        "files": files,
        "file_count": len(files),
        "dry_run": bool(dry_run),
        "sanitized_files": [],
    }

    for rel_path in files:
        if not is_text_mirror_file(rel_path):
            continue
        source_path = root / rel_path
        content = source_path.read_text(encoding="utf-8", errors="ignore")
        transformed = transform_public_mirror_text(rel_path, content)
        if transformed != content:
            result["sanitized_files"].append(rel_path)

    if dry_run:
        return result

    if target.exists() and not overwrite:
        raise FileExistsError(f"Le dossier cible existe déjà: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{target.name}-build-", dir=str(target.parent))).resolve()

    try:
        for rel_path in files:
            source_path = root / rel_path
            target_path = temp_dir / rel_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if is_text_mirror_file(rel_path):
                content = source_path.read_text(encoding="utf-8", errors="ignore")
                transformed = transform_public_mirror_text(rel_path, content)
                target_path.write_text(transformed, encoding="utf-8")
            else:
                shutil.copy2(source_path, target_path)

        try:
            _replace_target_dir(temp_dir, target)
        except Exception as exc:
            raise RuntimeError(
                f"Impossible de remplacer le miroir existant ({target}). "
                "Ferme le preview public en cours puis relance la génération."
            ) from exc
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or build a clean JoyBoy public mirror.")
    parser.add_argument("--target", help="Target directory for the public mirror.")
    parser.add_argument("--exclude-file", default=str(DEFAULT_EXCLUDE_FILE), help="Path to the exclusion manifest.")
    parser.add_argument("--overwrite", action="store_true", help="Replace the target directory if it already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the files that would be copied.")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of plain text.")
    args = parser.parse_args()

    if not args.dry_run and not args.target:
        parser.error("--target is required unless --dry-run is used")

    result = build_public_mirror(
        target_dir=args.target or (PROJECT_DIR / "_public_mirror_preview"),
        exclude_file=Path(args.exclude_file),
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Source: {result['source']}")
        print(f"Exclude file: {result['exclude_file']}")
        print(f"Files selected: {result['file_count']}")
        if args.dry_run:
            for rel_path in result["files"]:
                print(rel_path)
        else:
            print(f"Mirror built at: {result['target']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
