"""
Shared helpers for preparing a clean JoyBoy public mirror.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PUBLIC_MIRROR_EXCLUDE_FILE = PROJECT_DIR / "public_mirror.exclude"
ALWAYS_EXCLUDED = {".git", ".git/"}
TEXT_FILE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".html",
    ".css", ".yml", ".yaml", ".bat", ".sh", ".command",
}


def normalize_rel_path(path: Path | str) -> str:
    rel_path = str(path).replace("\\", "/").strip()
    if rel_path.startswith("./"):
        rel_path = rel_path[2:]
    return rel_path


def load_public_mirror_patterns(exclude_file: Path | None = None) -> list[str]:
    path = Path(exclude_file or DEFAULT_PUBLIC_MIRROR_EXCLUDE_FILE)
    if not path.exists():
        return []

    patterns: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(normalize_rel_path(line))
    return patterns


def is_public_mirror_excluded(rel_path: str, patterns: list[str] | None = None) -> bool:
    normalized = normalize_rel_path(rel_path)
    all_patterns = list(ALWAYS_EXCLUDED) + list(patterns or [])

    segments = [segment for segment in normalized.split("/") if segment]
    if ".git" in segments or "__pycache__" in segments:
        return True

    for pattern in all_patterns:
        candidate = normalize_rel_path(pattern)
        if not candidate:
            continue

        if candidate.endswith("/"):
            prefix = candidate.rstrip("/")
            if normalized == prefix or normalized.startswith(prefix + "/"):
                return True

        if fnmatch.fnmatch(normalized, candidate):
            return True

    return False


def collect_public_mirror_files(source_dir: Path | None = None, patterns: list[str] | None = None) -> list[str]:
    root = Path(source_dir or PROJECT_DIR).resolve()
    files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = normalize_rel_path(path.relative_to(root))
        if is_public_mirror_excluded(rel_path, patterns or []):
            continue
        files.append(rel_path)
    return sorted(files)


def is_text_mirror_file(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in TEXT_FILE_SUFFIXES


def _remove_ui_pack_entries(content: str) -> str:
    content = re.sub(r"(?m)^// === .*advanced-pack.*$\n?", "", content)
    content = re.sub(r"(?m)^.*adult:\s*true\s*\},?\s*$\n?", "", content)
    return content


def _remove_registry_adult_blocks(content: str) -> str:
    block_patterns = [
        r'\n\s*"inpaint_lustify": \{\n(?:\s+.*\n)+?\s+\},',
        r'\n\s*"inpaint_lustify_hq": \{\n(?:\s+.*\n)+?\s+\},',
    ]
    for pattern in block_patterns:
        content = re.sub(pattern, "\n", content)

    line_patterns = [
        r'(?m)^\s*"LUSTIFY \(Normal\)": "none",\s*$\n?',
        r'(?m)^\s*"LUSTIFY \(Moyen\)": \("civitai:2155386", "lustifySDXLNSFW_ggwpV7\.safetensors"\),\s*$\n?',
        r'(?m)^\s*"LUSTIFY \(Normal\)": \("civitai:2155386", "lustifySDXLNSFW_ggwpV7\.safetensors", "none"\),\s*$\n?',
        r'(?m)^\s*"Flux Kontext Uncensored": "black-forest-labs/FLUX\.1-Kontext-dev",\s*$\n?',
        r'(?m)^FLUX_KONTEXT_UNCENSORED_LORA = "enhanceaiteam/Flux-Uncensored-V2"\s*$\n?',
        r'(?m)^FLUX_KONTEXT_UNCENSORED_LORA_FILE = "lora\.safetensors"\s*$\n?',
    ]
    for pattern in line_patterns:
        content = re.sub(pattern, "", content)

    return content


def _sanitize_manager_private_runtime(content: str) -> str:
    block_replacements = [
        (
            r'(?ms)^    FLUX_LORA_REGISTRY = \{\n.*?^    \}\n',
            '    FLUX_LORA_REGISTRY = {}\n',
        ),
        (
            r'(?ms)^    LORA_REGISTRY = \{\n.*?^    \}\n',
            '    LORA_REGISTRY = {}\n',
        ),
    ]
    for pattern, replacement in block_replacements:
        content = re.sub(pattern, replacement, content)

    line_patterns = [
        r'(?m)^\s*"LUSTIFY": "LUSTIFY \(Moyen\)",\s*$\n?',
        r'(?m)^\s*"LUSTIFY \(Normal\)": "LUSTIFY \(Moyen\)",\s*$\n?',
        r'(?m)^(\s*def _load_flux_kontext\(self, model_name=)"Flux Kontext Uncensored"(\):)\s*$',
    ]
    content = re.sub(line_patterns[0], "", content)
    content = re.sub(line_patterns[1], "", content)
    content = re.sub(line_patterns[2], r'\1"Flux Kontext"\2', content)
    content = content.replace('"LUSTIFY", ', "")
    content = content.replace(', "LUSTIFY"', "")
    return content


def _sanitize_router_methods_json(content: str) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return content

    methods = data.get("methods", [])
    if isinstance(methods, list):
        data["methods"] = [
            method for method in methods
            if not (isinstance(method, dict) and method.get("nsfw"))
        ]

    prompt_constants = data.get("prompt_constants", {})
    if isinstance(prompt_constants, dict):
        prompt_constants.pop("nudity_negative", None)
        prompt_constants.pop("nudity_realism_suffix", None)

    controlnet_intents = data.get("controlnet_intents", [])
    if isinstance(controlnet_intents, list):
        data["controlnet_intents"] = [intent for intent in controlnet_intents if intent != "nudity"]

    controlnet_scales = data.get("controlnet_scales", {})
    if isinstance(controlnet_scales, dict):
        controlnet_scales.pop("nudity", None)

    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def transform_public_mirror_text(rel_path: str, content: str) -> str:
    normalized = normalize_rel_path(rel_path)

    if normalized == "web/static/js/ui.js":
        content = _remove_ui_pack_entries(content)

    if normalized == "core/models/registry.py":
        content = _remove_registry_adult_blocks(content)

    if normalized == "core/models/manager.py":
        content = _sanitize_manager_private_runtime(content)

    if normalized == "prompts/router_methods.json":
        content = _sanitize_router_methods_json(content)

    generic_replacements = (
        ("Mode local avancé", "Mode local avancé"),
        ("surface locale avancée", "surface locale avancée"),
        ("surfaces locales avancées", "surfaces locales avancées"),
        ("routes spécialisées", "routes spécialisées"),
        ("LOCAL+", "LOCAL+"),
        ("LoRA Local", "LoRA Local"),
        ("pack local ready", "pack local ready"),
        ("local pack specialist", "local pack specialist"),
    )
    for old, new in generic_replacements:
        content = content.replace(old, new)

    return content
