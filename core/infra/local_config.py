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
import shutil
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
    "provider_auth_modes": {},
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

PROVIDER_ID_BY_KEY = {
    "OPENAI_API_KEY": "openai",
    "OPENROUTER_API_KEY": "openrouter",
    "ANTHROPIC_API_KEY": "anthropic",
    "GEMINI_API_KEY": "gemini",
    "DEEPSEEK_API_KEY": "deepseek",
    "MOONSHOT_API_KEY": "moonshot",
    "NOVITA_API_KEY": "novita",
    "MINIMAX_API_KEY": "minimax",
    "VOLCENGINE_API_KEY": "volcengine",
    "ZHIPU_API_KEY": "glm",
    "VLLM_API_KEY": "vllm",
}

DEFAULT_PROVIDER_AUTH_MODE = "api_key"

PROVIDER_AUTH_OPTIONS = {
    "openai": [
        {
            "id": "api_key",
            "kind": "api_key",
            "label": "API key",
            "implemented": True,
        },
        {
            "id": "codex_cli",
            "kind": "subscription_cli",
            "label": "Codex CLI",
            "command": "codex",
            "implemented": False,
            "docs_url": "https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan/",
        },
    ],
    "anthropic": [
        {
            "id": "api_key",
            "kind": "api_key",
            "label": "API key",
            "implemented": True,
        },
        {
            "id": "claude_cli",
            "kind": "subscription_cli",
            "label": "Claude Code",
            "command": "claude",
            "implemented": False,
            "docs_url": "https://docs.anthropic.com/en/docs/claude-code/costs",
        },
    ],
    "gemini": [
        {
            "id": "api_key",
            "kind": "api_key",
            "label": "API key",
            "implemented": True,
        },
        {
            "id": "gemini_cli",
            "kind": "subscription_cli",
            "label": "Gemini CLI",
            "command": "gemini",
            "implemented": False,
            "docs_url": "https://codelabs.developers.google.com/gemini-cli-deep-dive",
        },
    ],
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


def _provider_auth_options_for(provider_id: str) -> list[dict]:
    provider_id = str(provider_id or "").strip().lower()
    options = PROVIDER_AUTH_OPTIONS.get(provider_id)
    if options:
        return deepcopy(options)
    return [{
        "id": DEFAULT_PROVIDER_AUTH_MODE,
        "kind": "api_key",
        "label": "API key",
        "implemented": True,
    }]


def _command_path(command: str) -> str:
    if not command:
        return ""
    return shutil.which(command) or ""


def _normalise_provider_auth_mode(provider_id: str, auth_mode: str | None) -> str:
    requested = str(auth_mode or "").strip().lower()
    valid_modes = {option["id"] for option in _provider_auth_options_for(provider_id)}
    if requested in valid_modes:
        return requested
    return DEFAULT_PROVIDER_AUTH_MODE


def get_provider_auth_mode(provider_id: str) -> str:
    provider_id = str(provider_id or "").strip().lower()
    config = load_local_config()
    stored = config.get("provider_auth_modes", {}).get(provider_id, DEFAULT_PROVIDER_AUTH_MODE)
    return _normalise_provider_auth_mode(provider_id, stored)


def set_provider_auth_mode(provider_id: str, auth_mode: str) -> dict:
    provider_id = str(provider_id or "").strip().lower()
    normalised = _normalise_provider_auth_mode(provider_id, auth_mode)
    if normalised != str(auth_mode or "").strip().lower():
        valid = ", ".join(option["id"] for option in _provider_auth_options_for(provider_id))
        raise ValueError(f"Mode d'accès inconnu pour {provider_id}: {auth_mode}. Modes valides: {valid}")

    config = load_local_config()
    config.setdefault("provider_auth_modes", {})[provider_id] = normalised
    return save_local_config(config)


def provider_auth_mode_uses_api_key(provider_id: str, auth_mode: str | None = None) -> bool:
    mode = _normalise_provider_auth_mode(provider_id, auth_mode or get_provider_auth_mode(provider_id))
    option = next((item for item in _provider_auth_options_for(provider_id) if item["id"] == mode), None)
    return (option or {}).get("kind") == "api_key"


def get_provider_auth_status(provider_id: str, env_key: str = "") -> dict:
    provider_id = str(provider_id or "").strip().lower()
    selected_mode = get_provider_auth_mode(provider_id)
    options = []
    selected_option = None
    key_configured = bool(get_provider_secret(env_key)) if env_key else False

    for raw_option in _provider_auth_options_for(provider_id):
        option = deepcopy(raw_option)
        command = str(option.get("command", "") or "")
        command_path = _command_path(command)
        kind = option.get("kind", "api_key")
        implemented = bool(option.get("implemented", False))

        if kind == "api_key":
            status = "configured" if key_configured else "missing_key"
            selectable = True
            runtime_ready = key_configured
        else:
            if not command_path:
                status = "connector_missing"
            elif implemented:
                status = "ready"
            else:
                status = "connector_pending"
            selectable = bool(command_path)
            runtime_ready = bool(command_path and implemented)

        option.update({
            "command_path": command_path,
            "selectable": selectable,
            "runtime_ready": runtime_ready,
            "status": status,
            "selected": option["id"] == selected_mode,
            "uses_api_key": kind == "api_key",
        })
        if option["selected"]:
            selected_option = option
        options.append(option)

    selected_option = selected_option or options[0]
    configured = bool(selected_option.get("runtime_ready"))
    if selected_option.get("uses_api_key"):
        configured = key_configured

    return {
        "provider_id": provider_id,
        "mode": selected_option["id"],
        "kind": selected_option.get("kind", "api_key"),
        "label": selected_option.get("label", selected_option["id"]),
        "uses_api_key": bool(selected_option.get("uses_api_key")),
        "configured": configured,
        "runtime_ready": bool(selected_option.get("runtime_ready")),
        "status": selected_option.get("status", "missing_key"),
        "options": options,
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
        provider_id = PROVIDER_ID_BY_KEY.get(key, "")
        auth_status = get_provider_auth_status(provider_id, key) if provider_id else {
            "provider_id": "",
            "mode": DEFAULT_PROVIDER_AUTH_MODE,
            "kind": "api_key",
            "label": "API key",
            "uses_api_key": True,
            "configured": bool(effective),
            "runtime_ready": bool(effective),
            "status": "configured" if effective else "missing_key",
            "options": _provider_auth_options_for(""),
        }
        status.append({
            "key": key,
            "provider_id": provider_id,
            "label": meta["label"],
            "description": meta["description"],
            "placeholder": meta["placeholder"],
            "scope": meta.get("scope", "assets"),
            "key_url": meta.get("key_url", ""),
            "models_url": meta.get("models_url", ""),
            "configured": bool(auth_status["configured"]),
            "source": "env" if env_value else ("local" if value else "missing"),
            "masked": mask_secret(effective),
            "local_only": bool(value) and not env_value,
            "auth_mode": auth_status["mode"],
            "auth_kind": auth_status["kind"],
            "auth_label": auth_status["label"],
            "auth_status": auth_status["status"],
            "auth_uses_api_key": auth_status["uses_api_key"],
            "auth_runtime_ready": auth_status["runtime_ready"],
            "auth_modes": auth_status["options"],
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
