"""
Local feature pack registry for JoyBoy.

Public core behavior:
- the app can discover optional local packs from ~/.joyboy/packs
- packs can expose extra routing assets, prompts, model sources, and UI overrides
- advanced local surfaces can stay visible while remaining locked until a valid local pack is installed

Private/dev behavior:
- when public_repo_mode is disabled, the legacy built-in local advanced runtime remains available
  as a compatibility bridge so current private usage is not broken.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from copy import deepcopy
import importlib
from pathlib import Path
import sys

from core.infra.local_config import (
    PROJECT_DIR,
    clear_active_pack,
    get_feature_flags,
    get_pack_preferences,
    set_active_pack,
)
from core.infra.paths import get_packs_dir as resolve_packs_dir


PACKS_DIR = resolve_packs_dir()
PACK_MANIFEST_NAME = "pack.json"
SUPPORTED_PACK_KINDS = {"adult", "creative", "experimental"}
LOCAL_PACK_SOURCES_DIR = PROJECT_DIR / "local_pack_sources"
LEGACY_BRIDGE_PACKS = {
    "adult": LOCAL_PACK_SOURCES_DIR / "local-advanced-runtime",
}
REQUIRED_MANIFEST_KEYS = {
    "id",
    "name",
    "version",
    "kind",
    "capabilities",
    "router_rules_path",
    "prompt_assets_path",
    "model_sources_path",
    "ui_overrides_path",
    "feature_flags_required",
}


def get_packs_dir() -> Path:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    return PACKS_DIR


def _safe_pack_id(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"-", "_"})
    return cleaned[:64]


def _path_is_inside(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _normalize_optional_relpath(root: Path, raw_value) -> tuple[str, str | None]:
    if not raw_value:
        return "", None

    rel_value = str(raw_value).replace("\\", "/").strip()
    while rel_value.startswith("./"):
        rel_value = rel_value[2:]
    target = (root / rel_value).resolve()
    if not _path_is_inside(root, target):
        return rel_value, "Chemin pack invalide (sort du dossier du pack)"
    if not target.exists():
        return rel_value, f"Ressource introuvable: {rel_value}"
    return rel_value, None


def validate_pack_manifest(manifest: dict, pack_root: Path) -> dict:
    errors = []
    data = deepcopy(manifest or {})

    missing = sorted(REQUIRED_MANIFEST_KEYS - set(data.keys()))
    if missing:
        errors.append(f"Champs manquants: {', '.join(missing)}")

    pack_id = _safe_pack_id(data.get("id", ""))
    if not pack_id:
        errors.append("Identifiant de pack invalide")

    kind = str(data.get("kind", "")).strip().lower()
    if kind not in SUPPORTED_PACK_KINDS:
        errors.append(f"Type de pack non supporté: {kind or 'vide'}")

    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(isinstance(item, str) and item.strip() for item in capabilities):
        errors.append("capabilities doit être une liste de chaînes")
        capabilities = []

    feature_flags_required = data.get("feature_flags_required", [])
    if not isinstance(feature_flags_required, list):
        errors.append("feature_flags_required doit être une liste")
        feature_flags_required = []

    normalized_paths = {}
    for key in ("router_rules_path", "prompt_assets_path", "model_sources_path", "ui_overrides_path"):
        rel_value, path_error = _normalize_optional_relpath(pack_root, data.get(key, ""))
        normalized_paths[key] = rel_value
        if path_error:
            errors.append(path_error)

    skills_path, skills_error = _normalize_optional_relpath(pack_root, data.get("skills_path", ""))
    normalized_paths["skills_path"] = skills_path
    if skills_error:
        errors.append(skills_error)

    return {
        "valid": not errors,
        "errors": errors,
        "pack": {
            "id": pack_id,
            "name": str(data.get("name", pack_id or "Unnamed pack")).strip() or pack_id,
            "version": str(data.get("version", "0.0.0")).strip() or "0.0.0",
            "kind": kind,
            "description": str(data.get("description", "") or "").strip(),
            "capabilities": [item.strip() for item in capabilities if isinstance(item, str) and item.strip()],
            "feature_flags_required": [str(item).strip() for item in feature_flags_required if str(item).strip()],
            **normalized_paths,
        },
    }


def _load_manifest(pack_dir: Path) -> dict:
    manifest_path = pack_dir / PACK_MANIFEST_NAME
    if not manifest_path.exists():
        return {
            "valid": False,
            "errors": [f"Manifest manquant: {PACK_MANIFEST_NAME}"],
            "pack": {
                "id": pack_dir.name,
                "name": pack_dir.name,
                "version": "0.0.0",
                "kind": "",
                "description": "",
                "capabilities": [],
                "feature_flags_required": [],
                "router_rules_path": "",
                "prompt_assets_path": "",
                "model_sources_path": "",
                "ui_overrides_path": "",
                "skills_path": "",
            },
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "valid": False,
            "errors": [f"Manifest illisible: {exc}"],
            "pack": {
                "id": pack_dir.name,
                "name": pack_dir.name,
                "version": "0.0.0",
                "kind": "",
                "description": "",
                "capabilities": [],
                "feature_flags_required": [],
                "router_rules_path": "",
                "prompt_assets_path": "",
                "model_sources_path": "",
                "ui_overrides_path": "",
                "skills_path": "",
            },
        }

    result = validate_pack_manifest(manifest, pack_dir.resolve())
    result["pack"]["path"] = str(pack_dir.resolve())
    result["pack"]["manifest_path"] = str(manifest_path.resolve())
    return result


def _load_manifest_from_any_path(pack_dir: Path) -> dict:
    return _load_manifest(pack_dir.resolve())


def list_local_packs() -> list[dict]:
    prefs = get_pack_preferences()
    active_map = prefs.get("active", {}) if isinstance(prefs, dict) else {}
    packs = []

    for pack_dir in sorted(get_packs_dir().iterdir(), key=lambda item: item.name.lower()):
        if not pack_dir.is_dir():
            continue
        result = _load_manifest(pack_dir)
        pack = result["pack"]
        pack["valid"] = bool(result["valid"])
        pack["errors"] = result["errors"]
        pack["active"] = pack["valid"] and active_map.get(pack.get("kind")) == pack.get("id")
        packs.append(pack)

    return packs


def get_pack_index() -> dict:
    packs = list_local_packs()
    active = {}
    by_kind = {}
    for pack in packs:
        by_kind.setdefault(pack["kind"], []).append(pack)
        if pack.get("active"):
            active[pack["kind"]] = pack
    return {
        "packs": packs,
        "by_kind": by_kind,
        "active": active,
    }


def get_active_pack(kind: str) -> dict | None:
    return get_pack_index()["active"].get(kind)


def get_bridge_pack(kind: str) -> dict | None:
    source_dir = LEGACY_BRIDGE_PACKS.get(str(kind))
    if not source_dir or not source_dir.exists() or not source_dir.is_dir():
        return None

    result = _load_manifest_from_any_path(source_dir)
    pack = result["pack"]
    pack["valid"] = bool(result["valid"])
    pack["errors"] = result["errors"]
    pack["active"] = False
    pack["bridge"] = True
    return pack


def get_effective_pack(kind: str) -> dict | None:
    flags = get_feature_flags()
    if str(kind) == "adult" and not bool(flags.get("adult_features_enabled", True)):
        return None

    active_pack = get_active_pack(kind)
    if active_pack and active_pack.get("valid"):
        return active_pack

    # If the user installed a pack for this kind but did not activate it, the
    # explicit local preference is "locked". Do not silently fall back to the
    # private bridge, otherwise the UI can say "inactive" while runtime rules
    # still load from the local source pack.
    if has_valid_pack(kind):
        return None

    if str(kind) == "adult" and not bool(flags.get("public_repo_mode", False)):
        bridge_pack = get_bridge_pack("adult")
        if bridge_pack and bridge_pack.get("valid"):
            return bridge_pack

    return None


def _load_pack_json_asset(pack: dict | None, rel_path_key: str) -> dict:
    if not pack or not pack.get("valid"):
        return {}

    rel_path = str(pack.get(rel_path_key, "") or "").strip()
    base_path = str(pack.get("path", "") or "").strip()
    if not rel_path or not base_path:
        return {}

    asset_path = (Path(base_path) / rel_path).resolve()
    root = Path(base_path).resolve()
    if not _path_is_inside(root, asset_path) or not asset_path.exists() or not asset_path.is_file():
        return {}

    try:
        data = json.loads(asset_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _load_effective_pack_json_asset(kind: str, rel_path_key: str) -> dict:
    return _load_pack_json_asset(get_effective_pack(kind), rel_path_key)


def get_pack_router_rules(kind: str = "adult") -> dict:
    return _load_effective_pack_json_asset(kind, "router_rules_path")


def get_pack_prompt_assets(kind: str = "adult") -> dict:
    return _load_effective_pack_json_asset(kind, "prompt_assets_path")


def get_pack_editor_prompt_assets(kind: str = "adult") -> dict:
    """Return only prompt assets that are safe for the browser editor to consume.

    Full prompt assets can contain system prompts and private routing hints. The
    UI only needs a tiny contract here, so keep the exposed shape deliberately
    small and let packs override editor behavior without hardcoding it in JS.
    """
    prompt_assets = get_pack_prompt_assets(kind)
    if not isinstance(prompt_assets, dict):
        return {}

    editor_assets = prompt_assets.get("editor", {})
    if not isinstance(editor_assets, dict):
        editor_assets = {}

    candidates = (
        ("editor.auto_fill_prompt", editor_assets.get("auto_fill_prompt")),
        ("editor_auto_fill_prompt", prompt_assets.get("editor_auto_fill_prompt")),
        ("adult_auto_fill_prompt", prompt_assets.get("adult_auto_fill_prompt")),
        ("auto_fill_prompt", prompt_assets.get("auto_fill_prompt")),
        ("generative_fill_prompt", prompt_assets.get("generative_fill_prompt")),
    )

    for source_key, raw_prompt in candidates:
        prompt = str(raw_prompt or "").strip()
        if prompt:
            return {
                "auto_fill_prompt": prompt,
                "source_key": source_key,
            }

    return {}


def get_pack_model_sources(kind: str = "adult") -> dict:
    return _load_effective_pack_json_asset(kind, "model_sources_path")


def _skill_summary(content: str) -> tuple[str, str]:
    title = ""
    summary_lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            if summary_lines:
                break
            continue
        if line.startswith("#") and not title:
            title = line.lstrip("#").strip()
            continue
        if line.startswith("#"):
            if summary_lines:
                break
            continue
        summary_lines.append(line)
        if len(" ".join(summary_lines)) >= 260:
            break
    summary = " ".join(summary_lines).strip()
    return title, summary[:320]


def _discover_pack_skills(pack: dict | None, include_private: bool = False) -> list[dict]:
    if not pack or not pack.get("valid"):
        return []

    rel_path = str(pack.get("skills_path", "") or "").strip()
    base_path = str(pack.get("path", "") or "").strip()
    if not rel_path or not base_path:
        return []

    root = Path(base_path).resolve()
    skills_root = (root / rel_path).resolve()
    if not _path_is_inside(root, skills_root) or not skills_root.exists() or not skills_root.is_dir():
        return []

    skills = []
    for skill_file in sorted(skills_root.rglob("SKILL.md"), key=lambda item: str(item).lower()):
        try:
            if not _path_is_inside(skills_root, skill_file):
                continue
            rel_file = skill_file.relative_to(root).as_posix()
            rel_dir = skill_file.parent.relative_to(skills_root).as_posix()
            slug_source = rel_dir if rel_dir != "." else skill_file.parent.name
            skill_slug = _safe_pack_id(slug_source.replace("/", "-")) or _safe_pack_id(skill_file.parent.name)
            if not skill_slug:
                continue
            excerpt = skill_file.read_text(encoding="utf-8", errors="replace")[:4000]
            title, summary = _skill_summary(excerpt)
            item = {
                "id": f"{pack['id']}:{skill_slug}",
                "pack_id": pack["id"],
                "pack_name": pack.get("name", pack["id"]),
                "kind": pack.get("kind", ""),
                "name": title or skill_slug.replace("-", " ").title(),
                "summary": summary,
                "path": rel_file,
            }
            if include_private:
                item["_content_path"] = str(skill_file.resolve())
            skills.append(item)
        except Exception:
            continue
    return skills


def get_pack_skills(kind: str | None = None) -> list[dict]:
    """Return metadata for active local pack skills without loading full text."""
    packs = []
    if kind:
        pack = get_effective_pack(kind)
        if pack and pack.get("valid"):
            packs.append(pack)
    else:
        for pack_kind in SUPPORTED_PACK_KINDS:
            pack = get_effective_pack(pack_kind)
            if pack and pack.get("valid"):
                packs.append(pack)

    skills = []
    for pack in packs:
        skills.extend(_discover_pack_skills(pack, include_private=False))
    return skills


def load_pack_skill(skill_id: str, kind: str | None = None) -> dict:
    """Load one active local pack skill by id.

    The full SKILL.md stays outside the base prompt; terminal agents call this
    only when the skill is relevant to the task.
    """
    requested = str(skill_id or "").strip()
    if not requested:
        return {"success": False, "error": "skill_id requis"}

    packs = []
    if kind:
        pack = get_effective_pack(kind)
        if pack and pack.get("valid"):
            packs.append(pack)
    else:
        for pack_kind in SUPPORTED_PACK_KINDS:
            pack = get_effective_pack(pack_kind)
            if pack and pack.get("valid"):
                packs.append(pack)

    for pack in packs:
        for skill in _discover_pack_skills(pack, include_private=True):
            if skill.get("id") != requested:
                continue
            content_path = Path(str(skill.get("_content_path", "")))
            try:
                content = content_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return {"success": False, "error": f"Skill illisible: {exc}"}
            clean_skill = {key: value for key, value in skill.items() if not key.startswith("_")}
            return {
                "success": True,
                "skill": clean_skill,
                "content": content[:20000],
                "truncated": len(content) > 20000,
            }

    return {"success": False, "error": f"Skill introuvable ou pack inactif: {requested}"}


def invalidate_runtime_pack_caches() -> None:
    module_names = (
        "core.ai.router_rules",
        "core.ai.smart_router",
        "core.ai.suggestions",
        "core.ai.utility_ai",
    )
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is not None:
            importlib.reload(module)


def get_pack_ui_overrides() -> dict:
    """Merge UI overrides exposed by active local packs."""
    merged = {
        "image_models": {
            "inpaint": [],
            "text2img": [],
        },
        "labels": {},
        "filters": {},
    }

    effective_packs = []
    for kind in SUPPORTED_PACK_KINDS:
        pack = get_effective_pack(kind)
        if pack and pack.get("valid"):
            effective_packs.append(pack)

    for pack in effective_packs:
        overrides = _load_pack_json_asset(pack, "ui_overrides_path")
        image_models = overrides.get("image_models", {}) if isinstance(overrides.get("image_models"), dict) else {}
        for bucket in ("inpaint", "text2img"):
            entries = image_models.get(bucket, [])
            if isinstance(entries, list):
                merged["image_models"][bucket].extend(
                    entry for entry in entries if isinstance(entry, dict) and entry.get("id")
                )

        for key in ("labels", "filters"):
            values = overrides.get(key, {})
            if isinstance(values, dict):
                merged[key].update(values)

    try:
        from core.infra.model_imports import get_imported_model_ui_overrides
        imported_overrides = get_imported_model_ui_overrides()
        imported_image_models = imported_overrides.get("image_models", {})
        for bucket in ("inpaint", "text2img"):
            entries = imported_image_models.get(bucket, [])
            if isinstance(entries, list):
                merged["image_models"][bucket].extend(
                    entry for entry in entries if isinstance(entry, dict) and entry.get("id")
                )
    except Exception:
        pass

    return merged


def has_valid_pack(kind: str) -> bool:
    return any(pack.get("valid") for pack in get_pack_index()["by_kind"].get(kind, []))


def is_adult_runtime_available() -> bool:
    flags = get_feature_flags()
    if not bool(flags.get("adult_features_enabled", True)):
        return False

    active_adult_pack = get_effective_pack("adult")
    if active_adult_pack and active_adult_pack.get("valid"):
        return True

    return False


def get_feature_exposure_map() -> dict:
    flags = get_feature_flags()
    public_repo_mode = bool(flags.get("public_repo_mode", False))
    adult_feature_flag = bool(flags.get("adult_features_enabled", True))
    adult_pack_installed = has_valid_pack("adult")
    active_adult_pack = get_effective_pack("adult")
    adult_runtime = is_adult_runtime_available()

    is_bridge_pack = bool(active_adult_pack and active_adult_pack.get("bridge"))

    if not adult_feature_flag:
        adult_reason = "Le mode local avancé est désactivé dans les paramètres."
    elif is_bridge_pack and adult_runtime:
        adult_reason = "Le bridge privé local reste disponible tant que le mode public n'est pas activé."
    elif active_adult_pack and adult_runtime:
        adult_reason = f'Pack local avancé actif: {active_adult_pack["name"]}'
    elif public_repo_mode and not adult_pack_installed:
        adult_reason = "Importe un pack local avancé pour déverrouiller ces outils sur cette machine."
    elif public_repo_mode and adult_pack_installed:
        adult_reason = "Un pack local avancé est installé. Active-le pour déverrouiller ces outils."
    else:
        adult_reason = "Le bridge privé local reste disponible tant que le mode public n'est pas activé."

    return {
        "adult": {
            "visible": True,
            "locked": not adult_runtime,
            "runtime_available": adult_runtime,
            "feature_enabled": adult_feature_flag,
            "public_repo_mode": public_repo_mode,
            "pack_installed": adult_pack_installed,
            "active_pack_id": active_adult_pack["id"] if active_adult_pack and not is_bridge_pack else None,
            "reason": adult_reason,
        }
    }


def set_pack_active(pack_id: str, enabled: bool = True) -> dict:
    target = None
    for pack in list_local_packs():
        if pack.get("id") == pack_id:
            target = pack
            break

    if not target:
        raise ValueError(f"Pack inconnu: {pack_id}")
    if not target.get("valid"):
        raise ValueError("Impossible d'activer un pack invalide")

    if enabled:
        set_active_pack(target["kind"], target["id"])
    else:
        clear_active_pack(target["kind"])

    invalidate_runtime_pack_caches()
    return target


def _copy_pack_tree(source_dir: Path, replace: bool = False) -> dict:
    manifest_result = _load_manifest(source_dir)
    if not manifest_result["valid"]:
        raise ValueError("; ".join(manifest_result["errors"]))

    pack = manifest_result["pack"]
    target_dir = get_packs_dir() / pack["id"]

    if target_dir.exists():
        if not replace:
            raise FileExistsError(f"Le pack {pack['id']} est déjà installé")
        shutil.rmtree(target_dir)

    shutil.copytree(source_dir, target_dir)
    return _load_manifest(target_dir)["pack"]


def import_pack_from_directory(source_path: str, replace: bool = False) -> dict:
    source_dir = Path(str(source_path or "")).expanduser()
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Dossier pack introuvable: {source_path}")
    imported = _copy_pack_tree(source_dir.resolve(), replace=replace)
    invalidate_runtime_pack_caches()
    return imported


def import_pack_from_zip(file_storage, replace: bool = False) -> dict:
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise ValueError("Archive de pack manquante")

    temp_root = Path(tempfile.mkdtemp(prefix="joyboy-pack-"))
    archive_path = temp_root / "pack.zip"
    file_storage.save(str(archive_path))

    extract_dir = temp_root / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                rel_path = Path(info.filename)
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    raise ValueError("Archive invalide: chemin non sûr")
                archive.extract(info, path=extract_dir)

        manifest_candidates = list(extract_dir.rglob(PACK_MANIFEST_NAME))
        if not manifest_candidates:
            raise ValueError(f"Aucun {PACK_MANIFEST_NAME} trouvé dans l'archive")

        pack_root = manifest_candidates[0].parent
        imported = _copy_pack_tree(pack_root, replace=replace)
        invalidate_runtime_pack_caches()
        return imported
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
