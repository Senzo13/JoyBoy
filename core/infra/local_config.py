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
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


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
    "mcp_servers": {},
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
    "signalatlas": {
        "providers": {
            "google_search_console": {
                "site_url": "",
                "service_account_json": "",
                "service_account_file": "",
                "oauth_json": "",
                "oauth_file": "",
            },
        },
    },
    "perfatlas": {
        "providers": {
            "google_search_console": {
                "site_url": "",
                "service_account_json": "",
                "service_account_file": "",
                "oauth_json": "",
                "oauth_file": "",
            },
            "pagespeed_insights": {
                "api_key": "",
            },
            "crux_api": {
                "api_key": "",
            },
            "vercel": {
                "token": "",
                "team_id": "",
                "project_id": "",
            },
            "netlify": {
                "token": "",
                "site_id": "",
            },
            "cloudflare": {
                "api_token": "",
                "zone_id": "",
                "account_id": "",
            },
        },
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
            "kind": "subscription_auth",
            "label": "Codex CLI",
            "detector": "codex_cli",
            "implemented": True,
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
            "kind": "subscription_auth",
            "label": "Claude Code",
            "detector": "claude_code_oauth",
            "command": "claude",
            "implemented": True,
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


def _home_dir() -> Path:
    home = os.environ.get("HOME")
    if home:
        return Path(home).expanduser()
    return Path.home()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.is_dir():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    clean: list[Path] = []
    for path in paths:
        resolved = str(path.expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        clean.append(path.expanduser())
    return clean


def _codex_cli_auth_paths() -> list[Path]:
    paths: list[Path] = []
    auth_path = os.environ.get("CODEX_AUTH_PATH")
    if auth_path:
        paths.append(Path(auth_path).expanduser())
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        paths.append(Path(codex_home).expanduser() / "auth.json")
    paths.append(_home_dir() / ".codex" / "auth.json")
    return _dedupe_paths(paths)


def load_codex_cli_credential() -> dict[str, str] | None:
    """Load Codex CLI auth without exposing it through public status payloads."""
    for auth_path in _codex_cli_auth_paths():
        data = _read_json_object(auth_path)
        if data is None:
            continue
        tokens = data.get("tokens", {})
        if not isinstance(tokens, dict):
            tokens = {}
        access_token = str(data.get("access_token") or data.get("token") or tokens.get("access_token") or "").strip()
        if not access_token:
            continue
        return {
            "access_token": access_token,
            "account_id": str(data.get("account_id") or tokens.get("account_id") or "").strip(),
            "source": str(auth_path),
        }
    return None


def _read_secret_from_fd(env_var: str) -> str:
    fd_value = os.environ.get(env_var, "").strip()
    if not fd_value:
        return ""
    try:
        fd = int(fd_value)
    except ValueError:
        return ""
    try:
        return os.read(fd, 1024 * 1024).decode("utf-8").strip()
    except OSError:
        return ""


def _claude_code_credential_paths() -> list[Path]:
    paths: list[Path] = []
    credentials_path = os.environ.get("CLAUDE_CODE_CREDENTIALS_PATH")
    if credentials_path:
        paths.append(Path(credentials_path).expanduser())
    paths.append(_home_dir() / ".claude" / ".credentials.json")
    return _dedupe_paths(paths)


def _extract_claude_code_credential(data: dict[str, Any], source: str) -> dict[str, Any] | None:
    oauth = data.get("claudeAiOauth", {})
    if not isinstance(oauth, dict):
        return None
    access_token = str(oauth.get("accessToken") or "").strip()
    if not access_token:
        return None
    expires_at = oauth.get("expiresAt") or 0
    try:
        expires_at_ms = int(float(expires_at))
    except (TypeError, ValueError):
        expires_at_ms = 0
    if expires_at_ms and time.time() * 1000 > expires_at_ms - 60_000:
        return None
    return {
        "access_token": access_token,
        "refresh_token": str(oauth.get("refreshToken") or "").strip(),
        "expires_at": expires_at_ms,
        "source": source,
    }


def _claude_code_file_status() -> str:
    found_file = False
    found_expired = False
    for credentials_path in _claude_code_credential_paths():
        data = _read_json_object(credentials_path)
        if data is None:
            continue
        found_file = True
        oauth = data.get("claudeAiOauth", {})
        if not isinstance(oauth, dict) or not str(oauth.get("accessToken") or "").strip():
            continue
        expires_at = oauth.get("expiresAt") or 0
        try:
            expires_at_ms = int(float(expires_at))
        except (TypeError, ValueError):
            expires_at_ms = 0
        if expires_at_ms and time.time() * 1000 > expires_at_ms - 60_000:
            found_expired = True

    if found_expired:
        return "auth_expired"
    if found_file:
        return "auth_invalid"
    return "auth_missing"


def load_claude_code_oauth_credential(consume_fd: bool = True) -> dict[str, Any] | None:
    direct_token = (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if direct_token:
        return {"access_token": direct_token, "source": "env"}

    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"):
        if not consume_fd:
            return {"access_token": "", "source": "fd"}
        fd_token = _read_secret_from_fd("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR")
        if fd_token:
            return {"access_token": fd_token, "source": "fd"}

    for credentials_path in _claude_code_credential_paths():
        data = _read_json_object(credentials_path)
        if data is None:
            continue
        credential = _extract_claude_code_credential(data, str(credentials_path))
        if credential:
            return credential
    return None


def _subscription_auth_detection(option: dict) -> dict[str, Any]:
    detector = str(option.get("detector", "") or "")

    if detector == "codex_cli":
        credential = load_codex_cli_credential()
        if credential:
            return {"detected": True, "status": "ready", "source": credential.get("source", "")}
        if any(path.exists() for path in _codex_cli_auth_paths()):
            return {"detected": False, "status": "auth_invalid", "source": ""}
        return {"detected": False, "status": "auth_missing", "source": ""}

    if detector == "claude_code_oauth":
        credential = load_claude_code_oauth_credential(consume_fd=False)
        if credential:
            return {"detected": True, "status": "ready", "source": credential.get("source", "")}
        return {"detected": False, "status": _claude_code_file_status(), "source": ""}

    return {"detected": False, "status": "auth_missing", "source": ""}


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
        auth_source = ""
        auth_detected = False

        if kind == "api_key":
            status = "configured" if key_configured else "missing_key"
            selectable = True
            runtime_ready = key_configured
        elif kind == "subscription_auth":
            auth_detection = _subscription_auth_detection(option)
            auth_source = str(auth_detection.get("source", "") or "")
            auth_detected = bool(auth_detection.get("detected"))
            if not auth_detected:
                status = str(auth_detection.get("status") or "auth_missing")
                runtime_ready = False
            elif implemented:
                status = "ready"
                runtime_ready = True
            else:
                status = "connector_pending"
                runtime_ready = False
            selectable = True
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
            "auth_detected": auth_detected,
            "auth_source": auth_source,
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


def _normalise_mcp_servers(servers: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(servers, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in servers.items():
        name = str(raw_name or "").strip()
        if not name or not isinstance(raw_config, dict):
            continue

        config = deepcopy(raw_config)
        config["enabled"] = bool(config.get("enabled", True))
        config["type"] = str(config.get("type") or "stdio").strip().lower() or "stdio"
        config["command"] = str(config.get("command") or "").strip() or None
        config["url"] = str(config.get("url") or "").strip() or None
        config["description"] = str(config.get("description") or "").strip()
        config["args"] = [str(item) for item in list(config.get("args") or [])]
        config["env"] = {
            str(key): str(value)
            for key, value in dict(config.get("env") or {}).items()
            if str(key).strip()
        }
        config["headers"] = {
            str(key): str(value)
            for key, value in dict(config.get("headers") or {}).items()
            if str(key).strip()
        }

        oauth = config.get("oauth")
        if isinstance(oauth, dict):
            oauth_copy = deepcopy(oauth)
            oauth_copy["enabled"] = bool(oauth_copy.get("enabled", True))
            oauth_copy["grant_type"] = str(oauth_copy.get("grant_type") or "client_credentials").strip() or "client_credentials"
            oauth_copy["token_url"] = str(oauth_copy.get("token_url") or "").strip()
            oauth_copy["token_field"] = str(oauth_copy.get("token_field") or "access_token").strip() or "access_token"
            oauth_copy["token_type_field"] = str(oauth_copy.get("token_type_field") or "token_type").strip() or "token_type"
            oauth_copy["expires_in_field"] = str(oauth_copy.get("expires_in_field") or "expires_in").strip() or "expires_in"
            oauth_copy["default_token_type"] = str(oauth_copy.get("default_token_type") or "Bearer").strip() or "Bearer"
            try:
                oauth_copy["refresh_skew_seconds"] = int(oauth_copy.get("refresh_skew_seconds") or 60)
            except (TypeError, ValueError):
                oauth_copy["refresh_skew_seconds"] = 60
            oauth_copy["extra_token_params"] = {
                str(key): str(value)
                for key, value in dict(oauth_copy.get("extra_token_params") or {}).items()
                if str(key).strip()
            }
            config["oauth"] = oauth_copy
        else:
            config["oauth"] = None

        normalized[name] = config

    return normalized


def load_local_config() -> dict:
    source_path = get_local_config_source_path()
    if not source_path.exists():
        return deepcopy(DEFAULT_LOCAL_CONFIG)

    try:
        raw_text = source_path.read_text(encoding="utf-8")
        if not raw_text.strip():
            return deepcopy(DEFAULT_LOCAL_CONFIG)
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"[LOCAL_CONFIG] Config JSON invalide ignorée {source_path}: {exc}")
        return deepcopy(DEFAULT_LOCAL_CONFIG)
    except OSError as exc:
        print(f"[LOCAL_CONFIG] Erreur lecture {source_path}: {exc}")
        return deepcopy(DEFAULT_LOCAL_CONFIG)

    merged = _deep_merge(DEFAULT_LOCAL_CONFIG, raw if isinstance(raw, dict) else {})
    deerflow_servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not merged.get("mcp_servers") and isinstance(deerflow_servers, dict):
        merged["mcp_servers"] = _normalise_mcp_servers(deerflow_servers)
    else:
        merged["mcp_servers"] = _normalise_mcp_servers(merged.get("mcp_servers", {}))
    return merged


def save_local_config(data: dict) -> dict:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    normalized = _deep_merge(DEFAULT_LOCAL_CONFIG, data if isinstance(data, dict) else {})
    normalized["mcp_servers"] = _normalise_mcp_servers(normalized.get("mcp_servers", {}))
    normalized.pop("mcpServers", None)
    with LOCAL_CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
    return normalized


def get_mcp_servers() -> dict[str, dict[str, Any]]:
    config = load_local_config()
    return deepcopy(_normalise_mcp_servers(config.get("mcp_servers", {})))


def set_mcp_servers(servers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    config = load_local_config()
    config["mcp_servers"] = _normalise_mcp_servers(servers)
    saved = save_local_config(config)
    return deepcopy(saved.get("mcp_servers", {}))


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


def get_signalatlas_settings() -> dict:
    return deepcopy(load_local_config().get("signalatlas", {}))


def _get_module_settings(module_key: str) -> dict:
    return deepcopy(load_local_config().get(str(module_key or "").strip(), {}))


def _get_module_provider_settings(module_key: str, provider_id: str) -> dict:
    settings = _get_module_settings(module_key)
    providers = settings.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    return deepcopy(providers.get(str(provider_id or "").strip(), {}))


def _set_module_provider_settings(module_key: str, provider_id: str, values: dict[str, Any]) -> dict:
    config = load_local_config()
    module_bucket = config.setdefault(str(module_key or "").strip(), {})
    providers = module_bucket.setdefault("providers", {})
    provider_key = str(provider_id or "").strip()
    if not provider_key:
        raise ValueError(f"{module_key} provider id required")
    current = providers.get(provider_key, {})
    if not isinstance(current, dict):
        current = {}
    clean_values = {
        str(key): str(value or "").strip()
        for key, value in dict(values or {}).items()
        if str(key).strip()
    }
    providers[provider_key] = {**current, **clean_values}
    saved = save_local_config(config)
    return deepcopy(saved.get(str(module_key or "").strip(), {}).get("providers", {}).get(provider_key, {}))


def get_signalatlas_provider_settings(provider_id: str) -> dict:
    return _get_module_provider_settings("signalatlas", provider_id)


def set_signalatlas_provider_settings(provider_id: str, values: dict[str, Any]) -> dict:
    return _set_module_provider_settings("signalatlas", provider_id, values)


def get_perfatlas_settings() -> dict:
    return _get_module_settings("perfatlas")


def get_perfatlas_provider_settings(provider_id: str) -> dict:
    return _get_module_provider_settings("perfatlas", provider_id)


def set_perfatlas_provider_settings(provider_id: str, values: dict[str, Any]) -> dict:
    return _set_module_provider_settings("perfatlas", provider_id, values)


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
