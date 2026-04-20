"""
Config locale non suivie par Git pour JoyBoy.

Objectifs:
- stocker des secrets/providers sans passer par .env
- préparer des feature flags locaux sans casser le comportement actuel
- permettre une synchro runtime simple vers os.environ
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
LEGACY_LOCAL_DIR = PROJECT_DIR / ".joyboy"
LEGACY_LOCAL_CONFIG_PATH = LEGACY_LOCAL_DIR / "config.json"
LOCAL_DIR = Path(os.environ.get("JOYBOY_HOME", "~/.joyboy")).expanduser()
LOCAL_CONFIG_PATH = LOCAL_DIR / "config.json"

DEFAULT_LOCAL_CONFIG = {
    "providers": {
        "HF_TOKEN": "",
        "CIVITAI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "GEMINI_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "MOONSHOT_API_KEY": "",
        "NOVITA_API_KEY": "",
        "MINIMAX_API_KEY": "",
        "VOLCENGINE_API_KEY": "",
        "ZHIPU_API_KEY": "",
        "VLLM_API_KEY": "",
    },
    "features": {
        "adult_features_enabled": True,
        "public_repo_mode": False,
    },
    "packs": {
        "active": {
            "adult": None,
            "creative": None,
            "experimental": None,
        },
    },
    "imported_models": {
        "image": [],
    },
    "onboarding": {
        "completed": False,
        "locale": "fr",
        "profile_type": "casual",
        "profile_name": "",
        "last_completed_at": "",
    },
}

PROVIDER_META = {
    "HF_TOKEN": {
        "label": "HuggingFace",
        "description": "Pour les modèles privés ou gated et de meilleurs téléchargements HF",
        "placeholder": "hf_xxx",
        "scope": "assets",
        "secret": True,
    },
    "CIVITAI_API_KEY": {
        "label": "CivitAI",
        "description": "Pour les téléchargements CivitAI et les ressources qui demandent un compte",
        "placeholder": "xxxxxxxx",
        "scope": "assets",
        "secret": True,
    },
    "OPENAI_API_KEY": {
        "label": "OpenAI",
        "description": "Pour utiliser des LLM cloud compatibles tools dans le chat/terminal",
        "placeholder": "sk-...",
        "scope": "llm",
        "secret": True,
        "key_url": "https://platform.openai.com/api-keys",
        "models_url": "https://developers.openai.com/api/docs/models",
    },
    "OPENROUTER_API_KEY": {
        "label": "OpenRouter",
        "description": "Pour router JoyBoy vers plusieurs modèles cloud via une API OpenAI-compatible",
        "placeholder": "sk-or-...",
        "scope": "llm",
        "secret": True,
    },
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic",
        "description": "Pour préparer les modèles Claude cloud dans le harnais LLM",
        "placeholder": "sk-ant-...",
        "scope": "llm",
        "secret": True,
    },
    "GEMINI_API_KEY": {
        "label": "Google Gemini",
        "description": "Pour préparer les modèles Gemini cloud dans le harnais LLM",
        "placeholder": "AIza...",
        "scope": "llm",
        "secret": True,
    },
    "DEEPSEEK_API_KEY": {
        "label": "DeepSeek",
        "description": "Pour utiliser DeepSeek via son API OpenAI-compatible",
        "placeholder": "sk-...",
        "scope": "llm",
        "secret": True,
    },
    "MOONSHOT_API_KEY": {
        "label": "Moonshot / Kimi",
        "description": "Pour utiliser Kimi/Moonshot via API OpenAI-compatible",
        "placeholder": "sk-...",
        "scope": "llm",
        "secret": True,
    },
    "NOVITA_API_KEY": {
        "label": "Novita AI",
        "description": "Pour utiliser des modèles cloud Novita via API OpenAI-compatible",
        "placeholder": "sk-...",
        "scope": "llm",
        "secret": True,
    },
    "MINIMAX_API_KEY": {
        "label": "MiniMax",
        "description": "Pour utiliser les modèles MiniMax via API OpenAI-compatible",
        "placeholder": "sk-...",
        "scope": "llm",
        "secret": True,
    },
    "VOLCENGINE_API_KEY": {
        "label": "Volcengine / Doubao",
        "description": "Pour préparer les modèles Doubao/Volcengine dans le harnais LLM",
        "placeholder": "xxxxxxxx",
        "scope": "llm",
        "secret": True,
    },
    "ZHIPU_API_KEY": {
        "label": "Zhipu / GLM",
        "description": "Pour utiliser GLM via l'API OpenAI-compatible de Zhipu",
        "placeholder": "xxxxxxxx",
        "scope": "llm",
        "secret": True,
    },
    "VLLM_API_KEY": {
        "label": "vLLM",
        "description": "Pour parler à un serveur vLLM local ou distant exposant une API OpenAI-compatible",
        "placeholder": "token ou placeholder",
        "scope": "llm",
        "secret": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_local_config_source_path() -> Path:
    if LOCAL_CONFIG_PATH.exists():
        return LOCAL_CONFIG_PATH
    if LEGACY_LOCAL_CONFIG_PATH.exists():
        return LEGACY_LOCAL_CONFIG_PATH
    return LOCAL_CONFIG_PATH


def get_local_config_overview() -> dict:
    source_path = get_local_config_source_path()
    return {
        "config_path": str(LOCAL_CONFIG_PATH),
        "active_source": str(source_path),
        "uses_legacy_path": source_path == LEGACY_LOCAL_CONFIG_PATH,
    }


def load_local_config() -> dict:
    source_path = get_local_config_source_path()
    if not source_path.exists():
        return deepcopy(DEFAULT_LOCAL_CONFIG)

    try:
        with source_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:
        print(f"[LOCAL_CONFIG] Erreur lecture {source_path}: {exc}")
        return deepcopy(DEFAULT_LOCAL_CONFIG)

    return _deep_merge(DEFAULT_LOCAL_CONFIG, raw if isinstance(raw, dict) else {})


def save_local_config(data: dict) -> dict:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    normalized = _deep_merge(DEFAULT_LOCAL_CONFIG, data if isinstance(data, dict) else {})
    with LOCAL_CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
    return normalized


def get_provider_secret(name: str, default: str = "") -> str:
    env_value = os.environ.get(name)
    if env_value:
        return env_value

    config = load_local_config()
    return str(config.get("providers", {}).get(name, default) or default)


def set_provider_secret(name: str, value: str) -> dict:
    config = load_local_config()
    config.setdefault("providers", {})[name] = (value or "").strip()
    saved = save_local_config(config)
    sync_runtime_provider_env()
    return saved


def clear_provider_secret(name: str) -> dict:
    config = load_local_config()
    config.setdefault("providers", {})[name] = ""
    saved = save_local_config(config)
    sync_runtime_provider_env()
    return saved


def get_feature_flags() -> dict:
    return load_local_config().get("features", {}).copy()


def is_feature_enabled(name: str, default: bool = False) -> bool:
    flags = get_feature_flags()
    if name not in flags:
        return bool(default)
    return bool(flags.get(name))


def set_feature_flag(name: str, value: bool) -> dict:
    config = load_local_config()
    config.setdefault("features", {})[name] = bool(value)
    return save_local_config(config)


def get_pack_preferences() -> dict:
    return deepcopy(load_local_config().get("packs", {}))


def set_active_pack(kind: str, pack_id: str | None) -> dict:
    config = load_local_config()
    active = config.setdefault("packs", {}).setdefault("active", {})
    active[str(kind)] = pack_id or None
    return save_local_config(config)


def clear_active_pack(kind: str) -> dict:
    return set_active_pack(kind, None)


def get_onboarding_state() -> dict:
    return deepcopy(load_local_config().get("onboarding", {}))


def update_onboarding_state(**updates) -> dict:
    config = load_local_config()
    onboarding = config.setdefault("onboarding", {})
    for key, value in updates.items():
        onboarding[key] = value
    saved = save_local_config(config)
    return deepcopy(saved.get("onboarding", {}))


def reset_onboarding_state() -> dict:
    config = load_local_config()
    config["onboarding"] = deepcopy(DEFAULT_LOCAL_CONFIG["onboarding"])
    saved = save_local_config(config)
    return deepcopy(saved.get("onboarding", {}))


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "…" + value[-2:]
    return value[:4] + "…" + value[-4:]


def get_provider_status() -> list[dict]:
    config = load_local_config()
    providers = config.get("providers", {})
    status = []
    for key, meta in PROVIDER_META.items():
        value = str(providers.get(key, "") or "")
        env_value = os.environ.get(key, "")
        effective = env_value or value
        status.append({
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "placeholder": meta["placeholder"],
            "scope": meta.get("scope", "assets"),
            "key_url": meta.get("key_url", ""),
            "models_url": meta.get("models_url", ""),
            "configured": bool(effective),
            "source": "env" if env_value else ("local" if value else "missing"),
            "masked": mask_secret(effective),
            "local_only": bool(value) and not env_value,
        })
    return status


def get_provider_for_repo(repo_id: str) -> str:
    if str(repo_id or "").startswith("local-file:"):
        return "local"
    return "civitai" if str(repo_id or "").startswith("civitai:") else "huggingface"


def is_provider_configured_for_repo(repo_id: str) -> bool:
    provider = get_provider_for_repo(repo_id)
    if provider == "local":
        return True
    if provider == "civitai":
        return bool(get_provider_secret("CIVITAI_API_KEY"))
    return bool(get_provider_secret("HF_TOKEN"))


def sync_runtime_provider_env() -> None:
    """
    Synchronise la config locale vers os.environ et le module config si déjà importé.

    Ne remplace pas une valeur d'environnement existante si elle est non vide.
    """
    config = load_local_config()
    providers = config.get("providers", {})

    for key in PROVIDER_META:
        local_value = str(providers.get(key, "") or "")
        marker = f"JOYBOY_LOCAL_{key}"
        current_env = os.environ.get(key, "")
        if local_value:
            if not current_env or os.environ.get(marker) == "1":
                os.environ[key] = local_value
                os.environ[marker] = "1"
        elif os.environ.get(marker) == "1":
            os.environ.pop(key, None)
            os.environ.pop(marker, None)

    config_module = sys.modules.get("config")
    if config_module is not None:
        for key in PROVIDER_META:
            if hasattr(config_module, key):
                setattr(config_module, key, get_provider_secret(key, ""))
