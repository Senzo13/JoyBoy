"""
Local model source resolver + background importer.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from html import unescape

import requests

from core.infra.local_config import LOCAL_DIR, get_provider_secret, load_local_config, save_local_config


MODEL_IMPORTS_DIR = LOCAL_DIR / "model_imports"
import_jobs: dict[str, dict] = {}
_CIVITAI_API_BASES = ("https://civitai.com", "https://civitai.red")
_PROJECT_DIR = Path(__file__).resolve().parents[2]
_GPU_PROFILES_DIR = _PROJECT_DIR / "gpu_profiles"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned[:120] or "model"


def _size_label(num_bytes: int | float | None) -> str:
    try:
        value = float(num_bytes or 0)
    except Exception:
        value = 0
    if value <= 0:
        return "~?"
    if value >= 1024 ** 3:
        return f"~{value / (1024 ** 3):.1f} GB"
    return f"~{value / (1024 ** 2):.0f} MB"


def _detect_import_vram_gb() -> float:
    """Best-effort VRAM read without making model-import tests require torch."""
    try:
        from core.models.registry import VRAM_GB  # Local import: registry pulls torch.
        return float(VRAM_GB or 0)
    except Exception:
        return 0.0


def _sdxl_quant_from_profile(vram_gb: float) -> str:
    try:
        for profile_path in sorted(_GPU_PROFILES_DIR.glob("*.json")):
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            vmin, vmax = profile.get("_vram_range", [0, 0])
            if float(vmin) <= float(vram_gb or 0) <= float(vmax):
                return str((profile.get("sdxl") or {}).get("quantization") or "").lower()
    except Exception:
        pass
    return ""


def get_import_quant_policy(target_family: str = "generic", vram_gb: float | None = None) -> dict:
    """Return the runtime quantization JoyBoy should use for imported checkpoints.

    CivitAI often only provides FP16 checkpoints. On low VRAM we still download the
    source checkpoint, then quantize/cache the UNet at load time through ModelManager.
    """
    family = str(target_family or "generic").lower()
    vram = _detect_import_vram_gb() if vram_gb is None else float(vram_gb or 0)
    image_like = family in {"generic", "image", "inpaint", "text2img"}
    profile_quant = _sdxl_quant_from_profile(vram) if image_like and vram > 0 else ""
    quantized_profile = profile_quant not in {"", "none", "native", "fp16", "bf16"}
    should_quantize = image_like and (vram <= 0 or quantized_profile or (vram <= 16 and not profile_quant))
    runtime_quant = "int8" if should_quantize else "none"
    return {
        "runtime_quant": runtime_quant,
        "source_preference": "low_vram" if should_quantize else "native",
        "vram_gb": round(vram, 1) if vram > 0 else 0,
        "profile_quant": profile_quant,
        "note": (
            "profile_runtime_quant"
            if should_quantize else "native_runtime"
        ),
    }


def _precision_probe_text(file_info: dict | None = None, file_name: str | None = None) -> str:
    info = file_info or {}
    metadata = info.get("metadata") or {}
    parts = [
        file_name or "",
        str(info.get("name") or ""),
        str(metadata.get("fp") or ""),
        str(metadata.get("precision") or ""),
        str(metadata.get("size") or ""),
        str(metadata.get("format") or ""),
    ]
    return " ".join(parts).lower()


def _detect_file_precision(file_info: dict | None = None, file_name: str | None = None) -> str:
    text = _precision_probe_text(file_info, file_name)
    if any(token in text for token in ("int8", "q8_0", "q8-", "q8.", "8bit", "8-bit")):
        return "int8"
    if any(token in text for token in ("fp8", "e4m3", "e5m2")):
        return "fp8"
    if any(token in text for token in ("int4", "q4_0", "q4-", "q4.", "nf4", "4bit", "4-bit")):
        return "int4"
    if any(token in text for token in ("bf16", "bfloat16")):
        return "bf16"
    if any(token in text for token in ("fp16", "float16", "16bit", "16-bit", "half")):
        return "fp16"
    if any(token in text for token in ("fp32", "float32", "32bit", "32-bit")):
        return "fp32"
    return ""


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _is_civitai_host(netloc: str) -> bool:
    host = str(netloc or "").lower()
    return "civitai.com" in host or "civitai.red" in host


def _preferred_civitai_base(source: str | None = None) -> str:
    parsed = urlparse(str(source or ""))
    host = parsed.netloc.lower()
    if "civitai.red" in host:
        return "https://civitai.red"
    return "https://civitai.com"


def _job_update(job_id: str, **updates) -> None:
    import_jobs.setdefault(job_id, {}).update(updates)


def _huggingface_token() -> str:
    return get_provider_secret("HF_TOKEN", "")


def _civitai_token() -> str:
    return get_provider_secret("CIVITAI_API_KEY", "")


def _civitai_headers() -> dict:
    headers = {"User-Agent": "JoyBoy/1.0"}
    token = _civitai_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _civitai_get_json(path: str, preferred_base: str | None = None, timeout: int = 45) -> tuple[dict, str]:
    bases = []
    if preferred_base:
        bases.append(preferred_base.rstrip("/"))
    bases.extend(base for base in _CIVITAI_API_BASES if base.rstrip("/") not in bases)

    last_error = None
    for base in bases:
        try:
            response = requests.get(f"{base}{path}", headers=_civitai_headers(), timeout=timeout)
            response.raise_for_status()
            return response.json(), base
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"CivitAI API indisponible: {last_error}")


def _pick_civitai_file(files: list[dict], quant_policy: dict | None = None) -> dict | None:
    if not files:
        return None

    low_vram = (quant_policy or {}).get("source_preference") == "low_vram"
    priorities = []
    for index, file_info in enumerate(files):
        name = str(file_info.get("name", "")).lower()
        metadata = file_info.get("metadata") or {}
        precision = _detect_file_precision(file_info)
        score = 0
        if file_info.get("primary"):
            score += 40
        if name.endswith(".safetensors"):
            score += 30
        if str(metadata.get("format", "")).lower() == "safeTensor".lower():
            score += 20
        if "pruned" in name:
            score += 5
        if re.search(r"\b(vae|embedding|textual[-_ ]?inversion|lora|locon)\b", name) and not file_info.get("primary"):
            score -= 100
        if low_vram:
            if precision == "int8":
                score += 90
            elif precision == "fp8":
                score += 65
            elif precision == "int4":
                score += 35
            elif precision == "fp16":
                score += 8
            elif precision == "fp32":
                score -= 25
        priorities.append((score, -index, file_info))

    priorities.sort(key=lambda item: item[0], reverse=True)
    return priorities[0][2]


def _extract_civitai_links(*html_chunks: str) -> list[dict]:
    seen = set()
    links = []
    for html in html_chunks:
        for match in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', str(html or ""), flags=re.I | re.S):
            url = unescape(match.group(1))
            label = _strip_html(match.group(2))
            parsed = urlparse(url)
            if not _is_civitai_host(parsed.netloc):
                continue
            model_match = re.search(r"/models/(\d+)", parsed.path)
            if not model_match:
                continue
            query = parse_qs(parsed.query or "")
            model_id = model_match.group(1)
            version_id = (query.get("modelVersionId") or [None])[0]
            key = (model_id, version_id, label)
            if key in seen:
                continue
            seen.add(key)
            links.append({
                "url": url,
                "label": label or f"civitai-{model_id}",
                "model_id": model_id,
                "version_id": version_id,
            })
    return links


def _resolve_civitai_version(model_id: str, version_id: str | None, preferred_base: str | None = None) -> tuple[dict, dict | None, str]:
    if version_id:
        version_payload, used_base = _civitai_get_json(f"/api/v1/model-versions/{version_id}", preferred_base)
        model_payload = None
        try:
            model_payload, _ = _civitai_get_json(f"/api/v1/models/{model_id}", used_base)
        except Exception:
            pass
        return version_payload, model_payload, used_base

    model_payload, used_base = _civitai_get_json(f"/api/v1/models/{model_id}", preferred_base)
    versions = model_payload.get("modelVersions") or []
    if not versions:
        raise RuntimeError("Aucune version CivitAI disponible")
    return versions[0], model_payload, used_base


def _resource_usage_from_context(label: str, resource_name: str, description: str) -> str | None:
    probe = f"{label} {resource_name}".lower()
    if "negative" in probe or "negatives" in probe:
        return "negative"
    if "positive" in probe or "positives" in probe:
        return "positive"

    text = _strip_html(description).lower()
    label_lower = label.lower()
    idx = text.find(label_lower) if label_lower else -1
    if idx >= 0:
        window = text[max(0, idx - 120):idx + 220]
        if "negative prompt" in window or "invite négative" in window:
            return "negative"
        if "prompt" in window or "invite" in window:
            return "positive"
    return None


def _resolve_recommended_civitai_resource(link: dict, description_context: str, preferred_base: str | None) -> dict | None:
    try:
        version, model_payload, used_base = _resolve_civitai_version(
            str(link.get("model_id")),
            str(link.get("version_id") or "") or None,
            preferred_base,
        )
    except Exception:
        return None

    model_info = version.get("model") or {}
    model_name = (model_payload or {}).get("name") or model_info.get("name") or link.get("label") or "CivitAI resource"
    model_type = (model_payload or {}).get("type") or model_info.get("type") or "Unknown"
    chosen_file = _pick_civitai_file(version.get("files") or [])
    usage = _resource_usage_from_context(str(link.get("label") or ""), str(model_name), description_context)
    token = str(link.get("label") or model_name or "").strip()
    return {
        "source": link.get("url"),
        "provider": "civitai",
        "model_id": str(link.get("model_id")),
        "version_id": str(version.get("id") or link.get("version_id") or ""),
        "name": model_name,
        "label": link.get("label") or model_name,
        "type": model_type,
        "base_model": version.get("baseModel"),
        "file_name": chosen_file.get("name") if chosen_file else "",
        "download_url": (chosen_file or {}).get("downloadUrl") or version.get("downloadUrl"),
        "size_bytes": int(float((chosen_file or {}).get("sizeKB") or 0) * 1024) if chosen_file else 0,
        "usage": usage,
        "token": token,
        "api_base": used_base,
    }


def _enrich_civitai_resolved(resolved: dict) -> dict:
    if resolved.get("provider") != "civitai" or resolved.get("source_type") == "direct_download":
        return resolved

    preferred_base = resolved.get("api_base") or _preferred_civitai_base(resolved.get("normalized_source"))
    version, model_payload, used_base = _resolve_civitai_version(
        str(resolved.get("model_id")),
        str(resolved.get("version_id") or "") or None,
        preferred_base,
    )
    model_info = version.get("model") or {}
    model_name = (model_payload or {}).get("name") or model_info.get("name") or resolved.get("display_name")
    model_type = (model_payload or {}).get("type") or model_info.get("type") or "Unknown"
    target_family = str(resolved.get("target_family") or "image")
    quant_policy = get_import_quant_policy(target_family)
    chosen_file = _pick_civitai_file(version.get("files") or [], quant_policy)
    file_name = chosen_file.get("name") if chosen_file else None
    size_bytes = int(float((chosen_file or {}).get("sizeKB") or 0) * 1024) if chosen_file else 0
    source_precision = _detect_file_precision(chosen_file, file_name)
    model_desc = (model_payload or {}).get("description") or ""
    version_desc = version.get("description") or ""

    recommended = []
    for link in _extract_civitai_links(model_desc, version_desc):
        if str(link.get("model_id")) == str(resolved.get("model_id")):
            continue
        item = _resolve_recommended_civitai_resource(link, f"{model_desc}\n{version_desc}", used_base)
        if item and item.get("download_url"):
            recommended.append(item)

    resolved.update({
        "display_name": f"{model_name} - {version.get('name')}" if version.get("name") else str(model_name),
        "model_name": model_name,
        "model_type": model_type,
        "version_name": version.get("name") or "",
        "version_id": str(version.get("id") or resolved.get("version_id") or ""),
        "base_model": version.get("baseModel"),
        "base_model_type": version.get("baseModelType"),
        "trained_words": version.get("trainedWords") or [],
        "file_name": file_name,
        "source_precision": source_precision,
        "download_url": (chosen_file or {}).get("downloadUrl") or version.get("downloadUrl"),
        "size_bytes": size_bytes,
        "size_label": _size_label(size_bytes),
        "quant_policy": {
            **quant_policy,
            "source_precision": source_precision,
        },
        "api_base": used_base,
        "recommended_resources": recommended[:10],
        "usage_tips": {
            "steps": "27+" if "27+" in _strip_html(version_desc) else "",
            "cfg": "5" if "CFG Scale: 5" in _strip_html(version_desc) else "",
            "clip_skip": "2" if "Clip Skip: 2" in _strip_html(version_desc) else "",
        },
    })
    return resolved


def resolve_model_source(source: str, target_family: str = "generic") -> dict:
    raw = str(source or "").strip()
    if not raw:
        raise ValueError("Source modèle vide")

    if re.match(r"^[\w.-]+/[\w.-]+$", raw):
        return {
            "provider": "huggingface",
            "source_type": "repo",
            "normalized_source": raw,
            "display_name": raw,
            "requires_auth": False,
        }

    parsed = urlparse(raw)
    netloc = parsed.netloc.lower()
    path = parsed.path.strip("/")
    query = parse_qs(parsed.query or "")

    if "huggingface.co" in netloc:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2:
            raise ValueError("URL Hugging Face invalide")
        repo_id = "/".join(parts[:2])
        return {
            "provider": "huggingface",
            "source_type": "repo",
            "normalized_source": repo_id,
            "display_name": repo_id,
            "requires_auth": False,
        }

    if raw.startswith("civitai:"):
        model_id = raw.split(":", 1)[1].strip()
        if not model_id:
            raise ValueError("Référence CivitAI invalide")
        quant_policy = get_import_quant_policy(target_family)
        return {
            "provider": "civitai",
            "source_type": "model_page",
            "normalized_source": f"https://civitai.com/models/{model_id}",
            "display_name": f"civitai-{model_id}",
            "model_id": model_id,
            "version_id": None,
            "target_family": target_family,
            "quant_policy": quant_policy,
            "requires_auth": bool(_civitai_token()),
        }

    if _is_civitai_host(netloc):
        if "/api/download/models/" in parsed.path:
            file_id = parsed.path.rstrip("/").split("/")[-1]
            return {
                "provider": "civitai",
                "source_type": "direct_download",
                "normalized_source": raw,
                "display_name": f"civitai-file-{file_id}",
                "file_id": file_id,
                "target_family": target_family,
                "source_precision": _detect_file_precision(file_name=raw),
                "quant_policy": get_import_quant_policy(target_family),
                "api_base": _preferred_civitai_base(raw),
                "requires_auth": bool(_civitai_token()),
            }

        model_match = re.search(r"/models/(\d+)", parsed.path)
        if model_match:
            resolved = {
                "provider": "civitai",
                "source_type": "model_page",
                "normalized_source": raw,
                "display_name": f"civitai-{model_match.group(1)}",
                "model_id": model_match.group(1),
                "version_id": (query.get("modelVersionId") or [None])[0],
                "target_family": target_family,
                "api_base": _preferred_civitai_base(raw),
                "requires_auth": bool(_civitai_token()),
            }
            try:
                return _enrich_civitai_resolved(resolved)
            except Exception as exc:
                resolved["warning"] = str(exc)
                return resolved

    raise ValueError("Source non reconnue. Colle un repo Hugging Face, un lien CivitAI ou une référence civitai:<id>.")


def _download_file(job_id: str, url: str, destination: Path, headers: dict | None = None) -> None:
    headers = headers or {}
    with requests.get(url, headers=headers, stream=True, timeout=120) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", "0") or 0)
        _job_update(job_id, total_bytes=total)
        downloaded = 0
        with destination.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                progress = int((downloaded / total) * 100) if total else 0
                _job_update(job_id, downloaded_bytes=downloaded, progress=min(progress, 99))


def _start_huggingface_import(job_id: str, resolved: dict, target_family: str) -> None:
    from huggingface_hub import snapshot_download

    repo_id = resolved["normalized_source"]
    destination = MODEL_IMPORTS_DIR / target_family / _slugify(repo_id.replace("/", "--"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = _huggingface_token() or None
    _job_update(job_id, status="running", message=f"Téléchargement Hugging Face: {repo_id}", target_path=str(destination))
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(destination),
        token=token,
        resume_download=True,
        local_dir_use_symlinks=False,
    )
    _job_update(job_id, status="completed", progress=100, message="Import Hugging Face terminé")


def _download_recommended_resource(job_id: str, resource: dict, destination_dir: Path) -> dict:
    file_name = resource.get("file_name") or f"civitai-{resource.get('version_id')}.safetensors"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / _slugify(file_name)
    if destination.exists() and destination.stat().st_size > 0:
        resource["local_path"] = str(destination)
        return resource
    _job_update(job_id, message=f"Ressource recommandée: {resource.get('name') or file_name}")
    _download_file(job_id, resource["download_url"], destination, headers=_civitai_headers())
    resource["local_path"] = str(destination)
    return resource


def _register_imported_image_model(entry: dict) -> dict:
    config = load_local_config()
    imported = config.setdefault("imported_models", {}).setdefault("image", [])
    existing_idx = None
    for idx, item in enumerate(imported):
        if item.get("id") == entry.get("id") or (
            item.get("provider") == entry.get("provider")
            and item.get("model_id") == entry.get("model_id")
            and item.get("version_id") == entry.get("version_id")
        ):
            existing_idx = idx
            break
    if existing_idx is None:
        imported.append(entry)
    else:
        imported[existing_idx] = {**imported[existing_idx], **entry}
    save_local_config(config)
    return entry


def get_imported_image_models() -> list[dict]:
    models = load_local_config().get("imported_models", {}).get("image", [])
    return [item for item in models if isinstance(item, dict)]


def get_imported_model_runtime_config(model_name: str) -> dict | None:
    for item in get_imported_image_models():
        if item.get("name") == model_name:
            return item
    return None


def get_imported_model_registry_entries() -> list[dict]:
    entries = []
    for item in get_imported_image_models():
        path = Path(str(item.get("file_path") or ""))
        if not path.exists():
            continue
        entries.append({
            "key": f"imported_{_slugify(item.get('id') or item.get('name')).lower()}",
            "name": item.get("name"),
            "repo": f"local-file:{path}",
            "single_file": (f"local-file:{path}", path.name, item.get("quant", "int8")),
            "size": item.get("size_label") or _size_label(path.stat().st_size),
            "category": "image",
            "desc": item.get("desc") or f"Import {item.get('provider', 'local')} · {item.get('base_model') or 'checkpoint'}",
            "quant": item.get("quant", "int8"),
            "capabilities": item.get("capabilities") or ["inpaint", "txt2img"],
            "imported": True,
        })
    return entries


def get_imported_model_ui_overrides() -> dict:
    overrides = {"image_models": {"inpaint": [], "text2img": []}}
    for item in get_imported_image_models():
        if not Path(str(item.get("file_path") or "")).exists():
            continue
        ui_entry = {
            "id": item.get("name"),
            "name": item.get("display_name") or item.get("name"),
            "desc": item.get("desc") or f"{item.get('base_model') or 'Checkpoint'} · import local",
            "badge": "powerful",
            "icon": "download",
            "backend": "diffusers",
            "imported": True,
        }
        for bucket in ("inpaint", "text2img"):
            overrides["image_models"][bucket].append(ui_entry)
    return overrides


def apply_imported_model_prompt_hooks(model_name: str, prompt: str, negative_prompt: str | None) -> tuple[str, str | None]:
    config = get_imported_model_runtime_config(model_name)
    if not config:
        return prompt, negative_prompt

    def _prepend_once(text: str | None, prefix: str | None) -> str | None:
        prefix = str(prefix or "").strip(" ,")
        if not prefix:
            return text
        base = str(text or "").strip()
        if prefix.lower() in base.lower():
            return base
        return f"{prefix}, {base}" if base else prefix

    prompt = _prepend_once(prompt, config.get("prompt_prefix")) or prompt
    negative_prompt = _prepend_once(negative_prompt, config.get("negative_prefix"))
    return prompt, negative_prompt


def _start_civitai_import(job_id: str, resolved: dict, target_family: str, include_recommended: bool = True) -> None:
    headers = _civitai_headers()
    source_type = resolved["source_type"]
    download_url = None
    file_name = None
    quant_policy = get_import_quant_policy(target_family)

    if source_type == "direct_download":
        download_url = resolved["normalized_source"]
        file_name = f"{resolved['display_name']}.safetensors"
        resolved["source_precision"] = _detect_file_precision(file_name=file_name)
        resolved["quant_policy"] = {
            **quant_policy,
            "source_precision": resolved.get("source_precision") or "",
        }
    else:
        resolved = dict(resolved)
        resolved["target_family"] = target_family
        resolved = _enrich_civitai_resolved(resolved)
        quant_policy = resolved.get("quant_policy") or quant_policy

        download_url = resolved.get("download_url")
        file_name = resolved.get("file_name") or f"civitai-{resolved['model_id']}.safetensors"
        if not download_url:
            raise RuntimeError("Aucun fichier exploitable trouvé sur CivitAI")
        resolved["display_name"] = file_name
        _job_update(job_id, resolved=resolved)

    destination_dir = MODEL_IMPORTS_DIR / target_family / "civitai"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / _slugify(file_name)
    _job_update(job_id, status="running", message=f"Téléchargement CivitAI: {resolved['display_name']}", target_path=str(destination))
    _download_file(job_id, download_url, destination, headers=headers)

    installed_recommended = []
    if include_recommended:
        dep_dir = destination_dir / "dependencies"
        for resource in resolved.get("recommended_resources") or []:
            if resource.get("download_url") and str(resource.get("type", "")).lower() in {"textualinversion", "lora", "locon"}:
                try:
                    installed_recommended.append(_download_recommended_resource(job_id, dict(resource), dep_dir))
                except Exception as exc:
                    failed = dict(resource)
                    failed["error"] = str(exc)
                    installed_recommended.append(failed)

    registered_model = None
    if target_family in {"image", "generic"} and str(file_name or "").lower().endswith((".safetensors", ".ckpt")):
        positive = next((res for res in installed_recommended if res.get("usage") == "positive" and res.get("local_path")), None)
        negative = next((res for res in installed_recommended if res.get("usage") == "negative" and res.get("local_path")), None)
        safe_name = resolved.get("model_name") or Path(file_name).stem
        version_name = str(resolved.get("version_name") or resolved.get("version_id") or "").strip()
        model_name = f"{safe_name} ({version_name or 'CivitAI'})"
        source_precision = resolved.get("source_precision") or _detect_file_precision(file_name=file_name) or Path(file_name).suffix.lstrip(".")
        runtime_quant = (quant_policy or {}).get("runtime_quant") or "int8"
        desc_bits = [
            resolved.get("base_model") or "Checkpoint",
            "CivitAI import",
            f"source {str(source_precision).upper()}",
        ]
        if runtime_quant and runtime_quant != "none":
            desc_bits.append(f"runtime {str(runtime_quant).upper()}")
        else:
            desc_bits.append("runtime natif")
        registered_model = _register_imported_image_model({
            "id": f"civitai-{resolved.get('model_id') or resolved.get('file_id')}-{resolved.get('version_id') or ''}".strip("-"),
            "provider": "civitai",
            "source": resolved.get("normalized_source"),
            "model_id": str(resolved.get("model_id") or ""),
            "version_id": str(resolved.get("version_id") or ""),
            "name": model_name,
            "display_name": model_name,
            "file_path": str(destination),
            "file_name": file_name,
            "model_type": resolved.get("model_type") or "Checkpoint",
            "base_model": resolved.get("base_model"),
            "base_model_type": resolved.get("base_model_type"),
            "trained_words": resolved.get("trained_words") or [],
            "size_label": resolved.get("size_label") or _size_label(destination.stat().st_size),
            "source_precision": source_precision,
            "runtime_quant": runtime_quant,
            "quant_policy": quant_policy,
            "desc": " · ".join(desc_bits),
            "quant": runtime_quant,
            "capabilities": ["inpaint", "txt2img"],
            "prompt_prefix": positive.get("token") if positive else "",
            "negative_prefix": negative.get("token") if negative else "",
            "recommended_resources": installed_recommended,
        })

    _job_update(
        job_id,
        status="completed",
        progress=100,
        message="Import CivitAI terminé",
        registered_model=registered_model,
        resolved=resolved,
    )


def start_model_import(source: str, target_family: str = "generic", include_recommended: bool = True) -> dict:
    resolved = resolve_model_source(source)
    job_id = uuid.uuid4().hex[:12]
    MODEL_IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    import_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "message": "Import en attente",
        "target_family": target_family,
        "resolved": resolved,
    }

    def _run():
        try:
            if resolved["provider"] == "huggingface":
                _start_huggingface_import(job_id, resolved, target_family)
            elif resolved["provider"] == "civitai":
                _start_civitai_import(job_id, resolved, target_family, include_recommended=include_recommended)
            else:
                raise RuntimeError(f"Provider non supporté: {resolved['provider']}")
        except Exception as exc:
            _job_update(job_id, status="error", error=str(exc), message=f"Échec import: {exc}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return import_jobs[job_id]


def get_model_import_status(job_id: str | None = None):
    if job_id:
        return import_jobs.get(job_id)
    return list(import_jobs.values())
