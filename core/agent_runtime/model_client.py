"""LLM provider catalog and lightweight cloud chat client.

The runtime stays local-first: Ollama remains the default path. Cloud models are
opt-in by using a provider-prefixed model id such as `openai:gpt-5.4-mini` or
`openrouter:provider/model`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from core.infra.local_config import get_provider_secret

from .output import truncate_middle


class CloudModelError(RuntimeError):
    """Raised when a configured cloud model cannot be called safely."""


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
        default_models=("gpt-5.4-mini", "gpt-5.4", "gpt-5.4-nano"),
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


def get_llm_provider_catalog() -> list[dict[str, Any]]:
    catalog = []
    for provider in LLM_PROVIDER_CATALOG:
        configured = True
        if provider.requires_key and provider.env_key:
            configured = bool(get_provider_secret(provider.env_key))
        catalog.append(provider.to_public_dict(configured=configured))
    return catalog


def get_terminal_model_profiles(configured_only: bool = False) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for provider in LLM_PROVIDER_CATALOG:
        configured = True
        if provider.requires_key and provider.env_key:
            configured = bool(get_provider_secret(provider.env_key))
        if configured_only and not configured:
            continue
        for model in provider.default_models:
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


def _chat_with_anthropic(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    api_key = get_provider_secret(provider.env_key) if provider.env_key else ""
    if provider.requires_key and not api_key:
        raise CloudModelError(f"Missing {provider.env_key} for provider {provider.label}")

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

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": os.environ.get("ANTHROPIC_VERSION", "2023-06-01"),
    }
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


def _chat_with_openai_compatible(
    provider: LLMProviderDescriptor,
    provider_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> dict[str, Any]:
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

    if provider.protocol == "anthropic":
        return _chat_with_anthropic(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    if provider.protocol == "gemini":
        return _chat_with_gemini(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    if provider.openai_compatible:
        return _chat_with_openai_compatible(provider, provider_model, messages, tools, max_tokens, temperature, timeout_seconds)
    raise CloudModelError(f"Provider {provider_id} protocol is not supported for terminal runtime")
