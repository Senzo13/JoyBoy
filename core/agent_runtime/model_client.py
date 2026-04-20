"""LLM provider catalog and lightweight cloud chat client.

The runtime stays local-first: Ollama remains the default path. Cloud models are
opt-in by using a provider-prefixed model id such as `openai:gpt-5.4-mini` or
`openrouter:provider/model`.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from core.infra.local_config import (
    get_provider_auth_status,
    get_provider_secret,
    load_claude_code_oauth_credential,
    load_codex_cli_credential,
)

from .output import truncate_middle


class CloudModelError(RuntimeError):
    """Raised when a configured cloud model cannot be called safely."""


CODEX_CLI_BASE_URL = "https://chatgpt.com/backend-api/codex"
ANTHROPIC_OAUTH_BETAS = "oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14"
ANTHROPIC_OAUTH_BILLING_HEADER = (
    "x-anthropic-billing-header: cc_version=2.1.85.351; cc_entrypoint=cli; cch=6c6d5;"
)


@dataclass(frozen=True)
class LLMProviderDescriptor:
    id: str
    label: str
    env_key: str
    protocol: str
    base_url: str = ""
    requires_key: bool = True
    openai_compatible: bool = False
    terminal_runtime: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    supports_thinking: bool = False
    default_models: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def to_public_dict(self, configured: bool) -> dict[str, Any]:
        data = asdict(self)
        data["default_models"] = list(self.default_models)
        data["configured"] = bool(configured)
        return data


LLM_PROVIDER_CATALOG: tuple[LLMProviderDescriptor, ...] = (
    LLMProviderDescriptor(
        id="ollama",
        label="Ollama",
        env_key="",
        protocol="ollama",
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        requires_key=False,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("qwen3.5:2b", "qwen3.5:4b"),
        notes="Local default runtime.",
    ),
    LLMProviderDescriptor(
        id="openai",
        label="OpenAI",
        env_key="OPENAI_API_KEY",
        protocol="openai-compatible",
        base_url="https://api.openai.com/v1",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=(
            "gpt-5.4",
            "gpt-5.2-codex",
            "gpt-5.1-codex-max",
            "gpt-5.4-mini",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.2",
            "gpt-5.1-codex-mini",
            "gpt-5.4-nano",
        ),
    ),
    LLMProviderDescriptor(
        id="openrouter",
        label="OpenRouter",
        env_key="OPENROUTER_API_KEY",
        protocol="openai-compatible",
        base_url="https://openrouter.ai/api/v1",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=(
            "google/gemini-2.5-flash-preview",
            "anthropic/claude-sonnet-4",
            "moonshotai/kimi-k2",
            "openai/gpt-4o-mini",
        ),
    ),
    LLMProviderDescriptor(
        id="deepseek",
        label="DeepSeek",
        env_key="DEEPSEEK_API_KEY",
        protocol="openai-compatible",
        base_url="https://api.deepseek.com/v1",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_thinking=True,
        default_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    LLMProviderDescriptor(
        id="moonshot",
        label="Moonshot / Kimi",
        env_key="MOONSHOT_API_KEY",
        protocol="openai-compatible",
        base_url="https://api.moonshot.cn/v1",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("kimi-k2.5", "kimi-k2"),
    ),
    LLMProviderDescriptor(
        id="novita",
        label="Novita AI",
        env_key="NOVITA_API_KEY",
        protocol="openai-compatible",
        base_url="https://api.novita.ai/openai",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("deepseek/deepseek-v3.2",),
    ),
    LLMProviderDescriptor(
        id="minimax",
        label="MiniMax",
        env_key="MINIMAX_API_KEY",
        protocol="openai-compatible",
        base_url="https://api.minimax.io/v1",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("MiniMax-M2.5",),
    ),
    LLMProviderDescriptor(
        id="vllm",
        label="vLLM",
        env_key="VLLM_API_KEY",
        protocol="openai-compatible",
        base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_thinking=True,
        default_models=("Qwen/Qwen3-32B",),
        notes="Set VLLM_BASE_URL when your server is not on localhost:8000/v1.",
    ),
    LLMProviderDescriptor(
        id="anthropic",
        label="Anthropic",
        env_key="ANTHROPIC_API_KEY",
        protocol="anthropic",
        base_url="https://api.anthropic.com/v1",
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("claude-sonnet-4-5", "claude-opus-4-5", "claude-3-5-sonnet-20241022"),
        notes="Native Anthropic Messages API adapter.",
    ),
    LLMProviderDescriptor(
        id="gemini",
        label="Google Gemini",
        env_key="GEMINI_API_KEY",
        protocol="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("gemini-2.0-flash", "gemini-2.5-pro"),
        notes="Native Google Generative Language API adapter.",
    ),
    LLMProviderDescriptor(
        id="volcengine",
        label="Volcengine / Doubao",
        env_key="VOLCENGINE_API_KEY",
        protocol="openai-compatible",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("doubao-seed-1-8-251228", "doubao-seed-2.0-code"),
    ),
    LLMProviderDescriptor(
        id="glm",
        label="Zhipu / GLM",
        env_key="ZHIPU_API_KEY",
        protocol="openai-compatible",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        openai_compatible=True,
        terminal_runtime=True,
        supports_tools=True,
        supports_vision=True,
        supports_thinking=True,
        default_models=("glm-5.1", "glm-4.5", "glm-4-plus"),
        notes="Set GLM_BASE_URL for a custom Zhipu-compatible endpoint.",
    ),
)

_PROVIDERS_BY_ID = {provider.id: provider for provider in LLM_PROVIDER_CATALOG}
_DISCOVERY_TTL_SECONDS = 300
_MAX_DISCOVERED_MODELS = 80
_MAX_DISCOVERED_MODELS_PER_FAMILY = 5
_DISCOVERY_CACHE: dict[tuple[str, str, str], tuple[float, list[str]]] = {}
_MODEL_EXCLUDED_FRAGMENTS = (
    "audio",
    "dall-e",
    "embedding",
    "image",
    "moderation",
    "rerank",
    "realtime",
    "speech",
    "tts",
    "transcribe",
    "whisper",
)
_PROVIDER_MODEL_PREFERENCES: dict[str, tuple[str, ...]] = {
    "openai": (
        "gpt-5.4",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
        "gpt-5.1-codex-mini",
        "gpt-5.4-nano",
    ),
    "anthropic": ("claude-sonnet-4-5", "claude-opus-4-5", "claude-3-5-sonnet-20241022"),
    "gemini": ("gemini-2.5-pro", "gemini-2.0-flash"),
}


def get_llm_provider_descriptor(provider_id: str) -> LLMProviderDescriptor | None:
    return _PROVIDERS_BY_ID.get(str(provider_id or "").strip().lower())


def split_cloud_model_name(model_name: str) -> tuple[str | None, str]:
    raw = str(model_name or "").strip()
    if ":" not in raw:
        return None, raw
    provider_id, provider_model = raw.split(":", 1)
    provider_id = provider_id.strip().lower()
    if provider_id not in _PROVIDERS_BY_ID or provider_id == "ollama":
        return None, raw
    return provider_id, provider_model.strip()


def is_cloud_model_name(model_name: str) -> bool:
    provider_id, _ = split_cloud_model_name(model_name)
    return provider_id is not None


def _provider_is_configured(provider: LLMProviderDescriptor) -> bool:
    if provider.id == "ollama":
        return True
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if not auth_status["uses_api_key"]:
        return bool(auth_status["runtime_ready"])
    if provider.requires_key and provider.env_key:
        return bool(get_provider_secret(provider.env_key))
    return True


def _provider_auth_public(provider: LLMProviderDescriptor) -> dict[str, Any]:
    if provider.id == "ollama":
        return {
            "auth_mode": "local",
            "auth_kind": "local",
            "auth_label": "Local",
            "auth_status": "ready",
            "auth_uses_api_key": False,
            "auth_runtime_ready": True,
        }
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    return {
        "auth_mode": auth_status["mode"],
        "auth_kind": auth_status["kind"],
        "auth_label": auth_status["label"],
        "auth_status": auth_status["status"],
        "auth_uses_api_key": auth_status["uses_api_key"],
        "auth_runtime_ready": auth_status["runtime_ready"],
    }


def _ensure_direct_api_auth(provider: LLMProviderDescriptor) -> None:
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if auth_status["uses_api_key"]:
        return
    raise CloudModelError(
        f"{provider.label} is set to {auth_status['label']} access. "
        f"JoyBoy will not use {provider.env_key or 'an API key'} while that mode is selected. "
        "Switch this provider back to API key mode or enable a subscription CLI connector."
    )


def _provider_secret_fingerprint(provider: LLMProviderDescriptor) -> str:
    if not provider.env_key:
        return ""
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if not auth_status["uses_api_key"]:
        return auth_status["mode"]
    secret = get_provider_secret(provider.env_key) or ""
    return f"{len(secret)}:{hash(secret)}" if secret else ""


def _dedupe_model_ids(model_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for model_id in model_ids:
        value = str(model_id or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        clean.append(value)
    return clean


def _extract_model_id(model_payload: Any) -> str:
    if isinstance(model_payload, str):
        return model_payload.strip()
    if not isinstance(model_payload, dict):
        return ""
    raw = (
        model_payload.get("id")
        or model_payload.get("name")
        or model_payload.get("model")
        or ""
    )
    model_id = str(raw or "").strip()
    if model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1]
    return model_id


def _extract_model_created_at(model_payload: Any) -> int:
    if not isinstance(model_payload, dict):
        return 0
    raw = (
        model_payload.get("created")
        or model_payload.get("created_at")
        or model_payload.get("updated_at")
        or model_payload.get("modified_at")
        or 0
    )
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _model_family_id(provider: LLMProviderDescriptor, model_id: str) -> str:
    lower = str(model_id or "").lower().strip()
    if not lower:
        return "other"

    if provider.id == "openai":
        if "codex" in lower:
            return "codex"
        if lower.startswith("gpt-"):
            parts = lower.split("-")
            if len(parts) >= 2:
                major = parts[1].split(".", 1)[0]
                return f"gpt-{major}"
            return "gpt"
        if lower.startswith("o"):
            return lower.split("-", 1)[0]
        return "openai"

    if provider.id == "anthropic":
        if "opus" in lower:
            return "claude-opus"
        if "sonnet" in lower:
            return "claude-sonnet"
        if "haiku" in lower:
            return "claude-haiku"
        return "claude"

    if provider.id == "gemini":
        parts = lower.split("-")
        return "-".join(parts[:2]) if len(parts) >= 2 else "gemini"

    if "/" in lower:
        return lower.split("/", 1)[0]
    return lower.split("-", 1)[0].split(":", 1)[0]


def _is_text_generation_model(provider: LLMProviderDescriptor, model_payload: Any, model_id: str) -> bool:
    lower = model_id.lower()
    if not lower:
        return False
    if any(fragment in lower for fragment in _MODEL_EXCLUDED_FRAGMENTS):
        return False

    if provider.id == "openai":
        return lower.startswith(("gpt-", "o")) or "codex" in lower

    if provider.id == "anthropic":
        return lower.startswith("claude-")

    if provider.id == "gemini":
        if isinstance(model_payload, dict):
            methods = model_payload.get("supportedGenerationMethods") or model_payload.get("supported_generation_methods") or []
            if methods and "generateContent" not in methods:
                return False
        return lower.startswith("gemini-")

    if isinstance(model_payload, dict):
        architecture = model_payload.get("architecture") if isinstance(model_payload.get("architecture"), dict) else {}
        input_modalities = architecture.get("input_modalities") or architecture.get("inputModalities") or []
        output_modalities = architecture.get("output_modalities") or architecture.get("outputModalities") or []
        if input_modalities and "text" not in [str(value).lower() for value in input_modalities]:
            return False
        if output_modalities and "text" not in [str(value).lower() for value in output_modalities]:
            return False

    return True


def _rank_model_candidates(provider: LLMProviderDescriptor, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferences = _PROVIDER_MODEL_PREFERENCES.get(provider.id, provider.default_models)
    preference_index = {model: index for index, model in enumerate(preferences)}
    return sorted(
        candidates,
        key=lambda candidate: (
            0 if int(candidate.get("created") or 0) else 1,
            -int(candidate.get("created") or 0),
            preference_index.get(candidate["id"], 10_000),
            candidate.get("index", 10_000),
            candidate["id"],
        ),
    )


def _limit_model_candidates_by_family(
    provider: LLMProviderDescriptor,
    candidates: list[dict[str, Any]],
) -> list[str]:
    limited: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        family = _model_family_id(provider, candidate["id"])
        by_family.setdefault(family, []).append(candidate)

    for family_candidates in by_family.values():
        limited.extend(_rank_model_candidates(provider, family_candidates)[:_MAX_DISCOVERED_MODELS_PER_FAMILY])

    return [candidate["id"] for candidate in _rank_model_candidates(provider, limited)[:_MAX_DISCOVERED_MODELS]]


def _parse_model_list_payload(provider: LLMProviderDescriptor, payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raw_models = []
    elif isinstance(payload, list):
        raw_models = payload
    else:
        raw_models = []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_models):
        model_id = _extract_model_id(item)
        if model_id in seen or not _is_text_generation_model(provider, item, model_id):
            continue
        seen.add(model_id)
        candidates.append({
            "id": model_id,
            "created": _extract_model_created_at(item),
            "index": index,
        })
    return _limit_model_candidates_by_family(provider, candidates)


def _discover_models_url(provider: LLMProviderDescriptor) -> str:
    return f"{_provider_base_url(provider)}/models"


def discover_provider_model_ids(
    provider: LLMProviderDescriptor,
    timeout_seconds: int = 6,
    use_cache: bool = True,
) -> tuple[list[str], str]:
    """Return live provider models when the provider exposes a model-list endpoint."""
    if provider.id == "ollama":
        return list(provider.default_models), ""
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if not auth_status["uses_api_key"]:
        return [], f"{provider.label} model discovery needs API key mode"
    if provider.requires_key and provider.env_key and not get_provider_secret(provider.env_key):
        return [], "missing key"

    try:
        url = _discover_models_url(provider)
    except CloudModelError as exc:
        return [], str(exc)

    cache_key = (provider.id, url, _provider_secret_fingerprint(provider))
    now = time.monotonic()
    if use_cache:
        cached = _DISCOVERY_CACHE.get(cache_key)
        if cached and now - cached[0] < _DISCOVERY_TTL_SECONDS:
            return list(cached[1]), ""

    headers = {"Accept": "application/json"}
    api_key = get_provider_secret(provider.env_key) if provider.env_key else ""
    if api_key:
        if provider.id == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider.id == "gemini":
            headers["x-goog-api-key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
    except requests.RequestException as exc:
        return [], f"{provider.label} model discovery failed: {exc}"

    if response.status_code >= 400:
        detail = truncate_middle(response.text or response.reason or "", 500)
        return [], f"{provider.label} model discovery API error {response.status_code}: {detail}"

    try:
        payload = response.json()
    except ValueError as exc:
        return [], f"{provider.label} model discovery returned invalid JSON: {exc}"

    model_ids = _parse_model_list_payload(provider, payload)
    if model_ids:
        _DISCOVERY_CACHE[cache_key] = (now, list(model_ids))
    return model_ids, ""


def _profile_model_ids(
    provider: LLMProviderDescriptor,
    configured: bool,
    discover_remote: bool,
    discovery_timeout_seconds: int,
) -> tuple[list[str], str, str]:
    if provider.id == "ollama":
        return list(provider.default_models), "default", ""

    if discover_remote and configured:
        discovered, error = discover_provider_model_ids(
            provider,
            timeout_seconds=discovery_timeout_seconds,
        )
        if discovered:
            return discovered, "remote", ""
        if error:
            return list(provider.default_models), "default", truncate_middle(error, 220)

    return list(provider.default_models), "default", ""


def get_llm_provider_catalog(discover_remote: bool = False) -> list[dict[str, Any]]:
    catalog = []
    for provider in LLM_PROVIDER_CATALOG:
        configured = _provider_is_configured(provider)
        data = provider.to_public_dict(configured=configured)
        data.update(_provider_auth_public(provider))
        if discover_remote:
            model_ids, source, error = _profile_model_ids(
                provider,
                configured=configured,
                discover_remote=True,
                discovery_timeout_seconds=6,
            )
            data["available_models"] = model_ids
            data["model_source"] = source
            data["model_discovery_error"] = error
        catalog.append(data)
    return catalog


def get_terminal_model_profiles(
    configured_only: bool = False,
    discover_remote: bool = False,
    discovery_timeout_seconds: int = 6,
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for provider in LLM_PROVIDER_CATALOG:
        configured = _provider_is_configured(provider)
        if configured_only and not configured:
            continue
        auth_public = _provider_auth_public(provider)
        model_ids, source, discovery_error = _profile_model_ids(
            provider,
            configured=configured,
            discover_remote=discover_remote,
            discovery_timeout_seconds=discovery_timeout_seconds,
        )
        for model in model_ids:
            model_id = model if provider.id == "ollama" else f"{provider.id}:{model}"
            profiles.append({
                "id": model_id,
                "provider": provider.id,
                "provider_label": provider.label,
                "model": model,
                "configured": configured,
                "terminal_runtime": provider.terminal_runtime,
                "supports_tools": provider.supports_tools,
                "supports_vision": provider.supports_vision,
                "supports_thinking": provider.supports_thinking,
                "model_source": source,
                "discovered": source == "remote",
                "discovery_error": discovery_error,
                **auth_public,
            })
    return profiles


def _provider_base_url(provider: LLMProviderDescriptor) -> str:
    env_override = os.environ.get(f"{provider.id.upper()}_BASE_URL") or os.environ.get(f"{provider.env_key}_BASE_URL")
    base_url = (env_override or provider.base_url or "").rstrip("/")
    if not base_url:
        raise CloudModelError(f"Provider {provider.id} needs a base_url before terminal use")
    return base_url


def _normalise_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    clean_calls = []
    for index, call in enumerate(tool_calls or []):
        call_dict = dict(call) if isinstance(call, dict) else {}
        function = call_dict.get("function", {}) if isinstance(call_dict.get("function"), dict) else {}
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments, ensure_ascii=False)
        clean_calls.append({
            "id": call_dict.get("id") or f"call_{index}",
            "type": call_dict.get("type") or "function",
            "function": {
                "name": function.get("name", ""),
                "arguments": str(arguments or "{}"),
            },
        })
    return clean_calls


def _normalise_messages_for_chat_completions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user") or "user")
        content = message.get("content", "")
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id", "") or "").strip()
            tool_name = str(message.get("tool_name", message.get("name", "")) or "").strip()
            if not tool_call_id:
                normalised.append({
                    "role": "user",
                    "content": f"Tool result ({tool_name or 'tool'}):\n{content or ''}",
                })
                continue
            item = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": str(content or ""),
            }
            if tool_name:
                item["name"] = tool_name
            normalised.append(item)
            continue

        if role not in {"system", "user", "assistant"}:
            role = "user"
        item = {
            "role": role,
            "content": "" if content is None else str(content),
        }
        if role == "assistant" and message.get("tool_calls"):
            item["tool_calls"] = _normalise_tool_calls(message.get("tool_calls"))
        normalised.append(item)
    return normalised


def _tool_call_arguments_dict(tool_call: dict[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function", {}) if isinstance(tool_call.get("function"), dict) else {}
    raw_args = function.get("arguments", {})
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _normalise_openai_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function", {}) if isinstance(tool.get("function"), dict) else {}
    return {
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "parameters": function.get("parameters") or {"type": "object", "properties": {}},
    }


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted = []
    for tool in tools or []:
        schema = _normalise_openai_tool_schema(tool)
        if not schema["name"]:
            continue
        converted.append({
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema["parameters"],
        })
    return converted


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []

    for message in messages:
        role = str(message.get("role", "user") or "user")
        content = "" if message.get("content") is None else str(message.get("content"))
        if role == "system":
            if content:
                system_parts.append(content)
            continue

        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or "tool_result"),
                    "content": content,
                }],
            })
            continue

        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tool_call in _normalise_tool_calls(message.get("tool_calls")):
                function = tool_call.get("function", {})
                blocks.append({
                    "type": "tool_use",
                    "id": tool_call.get("id") or f"call_{len(blocks)}",
                    "name": function.get("name", ""),
                    "input": _tool_call_arguments_dict(tool_call),
                })
            converted.append({"role": "assistant", "content": blocks or content})
            continue

        converted.append({"role": "user", "content": content})

    return "\n\n".join(system_parts), converted


def _anthropic_request_payload(
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    system_prompt, anthropic_messages = _anthropic_messages(messages)
    payload: dict[str, Any] = {
        "model": provider_model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_prompt:
        payload["system"] = system_prompt
    converted_tools = _anthropic_tools(tools)
    if converted_tools:
        payload["tools"] = converted_tools
    return payload


def _parse_anthropic_response(provider: LLMProviderDescriptor, provider_model: str, data: dict[str, Any]) -> dict[str, Any]:
    content_blocks = data.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for index, block in enumerate(content_blocks):
        block_dict = dict(block) if isinstance(block, dict) else {}
        if block_dict.get("type") == "text":
            text_parts.append(str(block_dict.get("text") or ""))
        elif block_dict.get("type") == "tool_use":
            tool_calls.append({
                "id": block_dict.get("id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": block_dict.get("name") or "",
                    "arguments": json.dumps(block_dict.get("input") or {}, ensure_ascii=False),
                },
            })

    usage = data.get("usage") or {}
    message: dict[str, Any] = {"role": "assistant", "content": "\n".join(part for part in text_parts if part)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "message": message,
        "prompt_eval_count": int(usage.get("input_tokens") or 0),
        "eval_count": int(usage.get("output_tokens") or 0),
        "total_duration": 0,
        "provider": provider.id,
        "model": provider_model,
    }


def _post_anthropic_request(
    provider: LLMProviderDescriptor,
    provider_model: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    url = f"{_provider_base_url(provider)}/messages"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise CloudModelError(f"{provider.label} request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = truncate_middle(response.text or response.reason or "", 800)
        raise CloudModelError(f"{provider.label} API error {response.status_code}: {detail}")

    try:
        data = response.json()
    except ValueError as exc:
        raise CloudModelError(f"{provider.label} returned invalid JSON") from exc
    return _parse_anthropic_response(provider, provider_model, data)


def _apply_claude_oauth_billing(payload: dict[str, Any]) -> None:
    billing_block = {
        "type": "text",
        "text": os.environ.get("ANTHROPIC_BILLING_HEADER", ANTHROPIC_OAUTH_BILLING_HEADER),
    }
    system = payload.get("system")
    if isinstance(system, list):
        payload["system"] = [billing_block] + [
            block for block in system
            if not (isinstance(block, dict) and "x-anthropic-billing-header:" in str(block.get("text") or ""))
        ]
    elif isinstance(system, str) and system:
        payload["system"] = [billing_block, {"type": "text", "text": system}]
    else:
        payload["system"] = [billing_block]

    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict) and "user_id" not in metadata:
        device_id = hashlib.sha256(f"joyboy-{socket.gethostname()}".encode("utf-8")).hexdigest()
        metadata["user_id"] = json.dumps(
            {
                "device_id": device_id,
                "account_uuid": "joyboy",
                "session_id": str(uuid.uuid4()),
            },
            ensure_ascii=False,
        )


def _chat_with_claude_code_oauth(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    credential = load_claude_code_oauth_credential()
    access_token = str((credential or {}).get("access_token") or "").strip()
    if not access_token:
        raise CloudModelError(
            "Claude Code OAuth auth not found. Expected CLAUDE_CODE_OAUTH_TOKEN, "
            "ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_CREDENTIALS_PATH, or ~/.claude/.credentials.json."
        )

    payload = _anthropic_request_payload(provider_model, messages, tools, max_tokens, temperature)
    _apply_claude_oauth_billing(payload)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
        "anthropic-beta": os.environ.get("ANTHROPIC_OAUTH_BETAS", ANTHROPIC_OAUTH_BETAS),
    }
    return _post_anthropic_request(provider, provider_model, payload, headers, timeout_seconds)


def _chat_with_anthropic(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if auth_status["mode"] == "claude_cli":
        return _chat_with_claude_code_oauth(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)

    _ensure_direct_api_auth(provider)
    api_key = get_provider_secret(provider.env_key) if provider.env_key else ""
    if provider.requires_key and not api_key:
        raise CloudModelError(f"Missing {provider.env_key} for provider {provider.label}")

    payload = _anthropic_request_payload(provider_model, messages, tools, max_tokens, temperature)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
    }
    return _post_anthropic_request(provider, provider_model, payload, headers, timeout_seconds)


def _gemini_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    declarations = []
    for tool in tools or []:
        schema = _normalise_openai_tool_schema(tool)
        if not schema["name"]:
            continue
        declarations.append({
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
        })
    return [{"functionDeclarations": declarations}] if declarations else []


def _gemini_contents(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []

    for message in messages:
        role = str(message.get("role", "user") or "user")
        content = "" if message.get("content") is None else str(message.get("content"))
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role == "tool":
            tool_name = str(message.get("tool_name") or message.get("name") or "tool")
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": tool_name,
                        "response": {"content": content},
                    }
                }],
            })
            continue
        if role == "assistant":
            parts: list[dict[str, Any]] = []
            if content:
                parts.append({"text": content})
            for tool_call in _normalise_tool_calls(message.get("tool_calls")):
                function = tool_call.get("function", {})
                parts.append({
                    "functionCall": {
                        "name": function.get("name") or "",
                        "args": _tool_call_arguments_dict(tool_call),
                    }
                })
            contents.append({"role": "model", "parts": parts or [{"text": content}]})
            continue
        contents.append({"role": "user", "parts": [{"text": content}]})

    return "\n\n".join(system_parts), contents


def _chat_with_gemini(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    _ensure_direct_api_auth(provider)
    api_key = get_provider_secret(provider.env_key) if provider.env_key else ""
    if provider.requires_key and not api_key:
        raise CloudModelError(f"Missing {provider.env_key} for provider {provider.label}")

    system_prompt, contents = _gemini_contents(messages)
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    converted_tools = _gemini_tools(tools)
    if converted_tools:
        payload["tools"] = converted_tools
        payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    base_url = _provider_base_url(provider)
    url = f"{base_url}/models/{provider_model}:generateContent"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise CloudModelError(f"{provider.label} request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = truncate_middle(response.text or response.reason or "", 800)
        raise CloudModelError(f"{provider.label} API error {response.status_code}: {detail}")

    try:
        data = response.json()
    except ValueError as exc:
        raise CloudModelError(f"{provider.label} returned invalid JSON") from exc

    candidates = data.get("candidates") or []
    if not candidates:
        raise CloudModelError(f"{provider.label} returned no candidates")
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        part_dict = dict(part) if isinstance(part, dict) else {}
        if "text" in part_dict:
            text_parts.append(str(part_dict.get("text") or ""))
        if "functionCall" in part_dict:
            function_call = part_dict.get("functionCall") or {}
            name = function_call.get("name") or ""
            tool_calls.append({
                "id": f"gemini_call_{index}_{name or 'tool'}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(function_call.get("args") or {}, ensure_ascii=False),
                },
            })

    usage = data.get("usageMetadata") or {}
    message: dict[str, Any] = {"role": "assistant", "content": "\n".join(part for part in text_parts if part)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "message": message,
        "prompt_eval_count": int(usage.get("promptTokenCount") or 0),
        "eval_count": int(usage.get("candidatesTokenCount") or 0),
        "total_duration": 0,
        "provider": provider.id,
        "model": provider_model,
    }


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [_content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "output"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        nested = content.get("content")
        if nested is not None:
            return _content_to_text(nested)
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    return str(content)


def _codex_input_items(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions_parts: list[str] = []
    input_items: list[dict[str, Any]] = []

    for message in messages:
        role = str(message.get("role", "user") or "user")
        content = _content_to_text(message.get("content"))
        if role == "system":
            if content:
                instructions_parts.append(content)
            continue
        if role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": str(message.get("tool_call_id") or "tool_result"),
                "output": content,
            })
            continue
        if role == "assistant":
            if content:
                input_items.append({"role": "assistant", "content": content})
            for tool_call in _normalise_tool_calls(message.get("tool_calls")):
                function = tool_call.get("function", {})
                input_items.append({
                    "type": "function_call",
                    "name": function.get("name") or "",
                    "arguments": str(function.get("arguments") or "{}"),
                    "call_id": tool_call.get("id") or f"call_{len(input_items)}",
                })
            continue
        input_items.append({"role": "user", "content": content})

    instructions = "\n\n".join(instructions_parts) or "You are a helpful assistant."
    return instructions, input_items


def _codex_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools or []:
        schema = _normalise_openai_tool_schema(tool)
        if not schema["name"]:
            continue
        converted.append({
            "type": "function",
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
        })
    return converted


def _parse_codex_sse_data_line(line: Any) -> dict[str, Any] | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    line = str(line or "").strip()
    if not line.startswith("data:"):
        return None
    raw_data = line[5:].strip()
    if not raw_data or raw_data == "[DONE]":
        return None
    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _merge_codex_streamed_output(
    completed_response: dict[str, Any],
    streamed_output_items: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    if not streamed_output_items:
        return completed_response

    response_output = completed_response.get("output")
    merged_output = list(response_output) if isinstance(response_output, list) else []
    max_index = max(max(streamed_output_items), len(merged_output) - 1)
    if max_index >= 0 and len(merged_output) <= max_index:
        merged_output.extend([None] * (max_index + 1 - len(merged_output)))

    for output_index, output_item in streamed_output_items.items():
        existing_item = merged_output[output_index]
        if not isinstance(existing_item, dict):
            merged_output[output_index] = output_item

    merged_response = dict(completed_response)
    merged_response["output"] = [item for item in merged_output if isinstance(item, dict)]
    return merged_response


def _stream_codex_response(headers: dict[str, str], payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{CODEX_CLI_BASE_URL}/responses",
            headers=headers,
            json=payload,
            stream=True,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise CloudModelError(f"OpenAI Codex request failed: {exc}") from exc

    try:
        if response.status_code >= 400:
            detail = truncate_middle(response.text or response.reason or "", 800)
            raise CloudModelError(f"OpenAI Codex API error {response.status_code}: {detail}")

        completed_response: dict[str, Any] | None = None
        streamed_output_items: dict[int, dict[str, Any]] = {}
        try:
            line_iter = response.iter_lines(decode_unicode=True)
        except TypeError:
            line_iter = response.iter_lines()
        for line in line_iter:
            data = _parse_codex_sse_data_line(line)
            if not data:
                continue
            event_type = data.get("type")
            if event_type == "response.output_item.done":
                output_index = data.get("output_index")
                output_item = data.get("item")
                if isinstance(output_index, int) and isinstance(output_item, dict):
                    streamed_output_items[output_index] = output_item
            elif event_type == "response.completed":
                response_payload = data.get("response")
                if isinstance(response_payload, dict):
                    completed_response = response_payload

        if completed_response is None:
            raise CloudModelError("OpenAI Codex stream ended without response.completed")
        return _merge_codex_streamed_output(completed_response, streamed_output_items)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _parse_codex_response(provider_model: str, response: dict[str, Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for index, output_item in enumerate(response.get("output") or []):
        if not isinstance(output_item, dict):
            continue
        if output_item.get("type") == "message":
            for part in output_item.get("content") or []:
                part_dict = dict(part) if isinstance(part, dict) else {}
                if part_dict.get("type") in {"output_text", "text"}:
                    text_parts.append(str(part_dict.get("text") or ""))
        elif output_item.get("type") == "function_call":
            arguments = output_item.get("arguments") or "{}"
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            tool_calls.append({
                "id": output_item.get("call_id") or f"call_{index}",
                "type": "function",
                "function": {
                    "name": output_item.get("name") or "",
                    "arguments": str(arguments or "{}"),
                },
            })

    usage = response.get("usage") or {}
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "message": message,
        "prompt_eval_count": int(usage.get("input_tokens") or 0),
        "eval_count": int(usage.get("output_tokens") or 0),
        "total_duration": 0,
        "provider": "openai",
        "model": provider_model,
    }


def _chat_with_codex_cli(
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    credential = load_codex_cli_credential()
    access_token = str((credential or {}).get("access_token") or "").strip()
    if not access_token:
        raise CloudModelError("OpenAI Codex auth not found. Expected CODEX_AUTH_PATH, CODEX_HOME/auth.json, or ~/.codex/auth.json.")

    instructions, input_items = _codex_input_items(messages)
    payload: dict[str, Any] = {
        "model": provider_model,
        "instructions": instructions,
        "input": input_items,
        "store": False,
        "stream": True,
        "reasoning": {"effort": "medium", "summary": "detailed"},
    }
    converted_tools = _codex_tools(tools)
    if converted_tools:
        payload["tools"] = converted_tools

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "originator": "codex_cli_rs",
    }
    account_id = str((credential or {}).get("account_id") or "").strip()
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id

    response = _stream_codex_response(headers, payload, timeout_seconds)
    return _parse_codex_response(provider_model, response)


def _chat_with_openai_compatible(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    _ensure_direct_api_auth(provider)
    api_key = get_provider_secret(provider.env_key) if provider.env_key else ""
    if provider.requires_key and not api_key:
        raise CloudModelError(f"Missing {provider.env_key} for provider {provider.label}")

    payload: dict[str, Any] = {
        "model": provider_model,
        "messages": _normalise_messages_for_chat_completions(messages),
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider.id == "openrouter":
        headers["X-Title"] = "JoyBoy"

    url = f"{_provider_base_url(provider)}/chat/completions"
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except requests.RequestException as exc:
        raise CloudModelError(f"{provider.label} request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = truncate_middle(response.text or response.reason or "", 800)
        raise CloudModelError(f"{provider.label} API error {response.status_code}: {detail}")

    try:
        data = response.json()
    except ValueError as exc:
        raise CloudModelError(f"{provider.label} returned invalid JSON") from exc

    choices = data.get("choices") or []
    if not choices:
        raise CloudModelError(f"{provider.label} returned no choices")

    message = choices[0].get("message") or {}
    if message.get("content") is None:
        message["content"] = ""
    if message.get("tool_calls"):
        message["tool_calls"] = _normalise_tool_calls(message.get("tool_calls"))

    usage = data.get("usage") or {}
    return {
        "message": message,
        "prompt_eval_count": int(usage.get("prompt_tokens") or 0),
        "eval_count": int(usage.get("completion_tokens") or 0),
        "total_duration": 0,
        "provider": provider.id,
        "model": provider_model,
    }


def chat_with_cloud_model(
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    provider_id, provider_model = split_cloud_model_name(model_name)
    if not provider_id:
        raise CloudModelError(f"Cloud model id must use provider:model syntax, got: {model_name}")
    provider = get_llm_provider_descriptor(provider_id)
    if not provider or not provider.terminal_runtime:
        raise CloudModelError(f"Provider {provider_id} is not wired for terminal runtime yet")
    if not provider_model:
        raise CloudModelError(f"Missing model name after provider prefix: {model_name}")

    auth_status = get_provider_auth_status(provider.id, provider.env_key)
    if provider.id == "openai" and auth_status["mode"] == "codex_cli":
        return _chat_with_codex_cli(provider_model, messages, tools, timeout_seconds)
    if provider.protocol == "anthropic":
        return _chat_with_anthropic(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    if provider.protocol == "gemini":
        return _chat_with_gemini(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    if provider.openai_compatible:
        return _chat_with_openai_compatible(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    raise CloudModelError(f"Provider {provider_id} protocol is not supported for terminal runtime")
