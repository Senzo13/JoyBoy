"""
Central Ollama text-model selection for JoyBoy utility calls.

This keeps router/utility/chat helpers from each inventing their own fallback
order. The preferred small model is installed on demand when Ollama is running,
then every caller reuses the same selection path.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests
from pydantic import BaseModel, ValidationError

from config import OLLAMA_BASE_URL, ROUTER_MODEL, ROUTER_MODEL_CANDIDATES, UTILITY_MODEL


_MODEL_CACHE_TTL = 20.0
_installed_cache: tuple[float, set[str]] | None = None
_pull_attempted: set[str] = set()


@dataclass(frozen=True)
class TextModelChoice:
    name: str
    source: str
    installed: bool = True


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _auto_pull_enabled() -> bool:
    return os.environ.get("JOYBOY_AUTO_PULL_TEXT_MODEL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def invalidate_text_model_cache() -> None:
    global _installed_cache
    _installed_cache = None


def list_installed_text_models(timeout: float = 3.0, refresh: bool = False) -> set[str]:
    """Return installed Ollama model names, cached briefly."""
    global _installed_cache

    now = time.time()
    if (
        not refresh
        and _installed_cache is not None
        and now - _installed_cache[0] <= _MODEL_CACHE_TTL
    ):
        return set(_installed_cache[1])

    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        if response.status_code != 200:
            return set()
        installed = {
            model.get("name", "")
            for model in response.json().get("models", [])
            if model.get("name")
        }
        _installed_cache = (now, installed)
        return set(installed)
    except Exception as exc:
        print(f"[TEXT_MODEL] Ollama discovery skipped: {exc}")
        return set()


def _candidates_for(purpose: str) -> list[str]:
    if purpose == "router":
        return _unique([ROUTER_MODEL, *ROUTER_MODEL_CANDIDATES, UTILITY_MODEL])
    return _unique([UTILITY_MODEL, ROUTER_MODEL, *ROUTER_MODEL_CANDIDATES])


def pull_text_model(model_name: str, timeout: int = 1800) -> bool:
    """Install an Ollama model once per process."""
    model_name = str(model_name or "").strip()
    if not model_name:
        return False
    if model_name in _pull_attempted:
        return model_name in list_installed_text_models(refresh=True)

    _pull_attempted.add(model_name)
    print(f"[TEXT_MODEL] Installation Ollama requise: {model_name}")
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model_name, "stream": False},
            timeout=timeout,
        )
        if response.status_code == 200:
            invalidate_text_model_cache()
            installed = model_name in list_installed_text_models(refresh=True)
            print(f"[TEXT_MODEL] {model_name} {'installé' if installed else 'non confirmé'}")
            return installed
        print(f"[TEXT_MODEL] Pull HTTP {response.status_code}: {response.text[:200]}")
    except requests.exceptions.Timeout:
        print(f"[TEXT_MODEL] Pull timeout pour {model_name}")
    except Exception as exc:
        print(f"[TEXT_MODEL] Pull impossible pour {model_name}: {exc}")
    return False


def select_text_model(purpose: str = "utility", auto_pull: bool = True) -> TextModelChoice | None:
    """Select the best installed text model, optionally installing the preferred one."""
    candidates = _candidates_for(purpose)
    installed = list_installed_text_models()

    for candidate in candidates:
        if candidate in installed:
            return TextModelChoice(candidate, source=f"{purpose}:installed")

    preferred = candidates[0] if candidates else UTILITY_MODEL
    if auto_pull and _auto_pull_enabled() and preferred:
        if pull_text_model(preferred):
            return TextModelChoice(preferred, source=f"{purpose}:auto-pulled")

    # Last resort: use any configured candidate. Ollama may still lazy-pull or
    # error clearly; callers should not silently rewrite this to qwen2.5.
    if preferred:
        return TextModelChoice(preferred, source=f"{purpose}:configured", installed=False)
    return None


def strip_thinking(content: str) -> str:
    """Normalize thinking-model output into plain content."""
    value = str(content or "").strip()
    if "</think>" in value:
        value = value.split("</think>")[-1].strip()
    return value


def _extract_json_object(content: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a model response."""
    text = strip_thinking(content)
    if not text:
        return None

    fenced_match = None
    if "```" in text:
        import re

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = [fenced_match.group(1) if fenced_match else "", text]

    decoder = json.JSONDecoder()
    for candidate in candidates:
        payload = str(candidate or "").strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        for index, char in enumerate(payload):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(payload[index:])
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _validate_structured_payload(
    payload: dict[str, Any] | None,
    schema_model: type[BaseModel] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if schema_model is None:
        return payload
    try:
        validated = schema_model.model_validate(payload)
        return validated.model_dump(mode="json", by_alias=False)
    except ValidationError as exc:
        print(f"[TEXT_MODEL] Structured validation failed: {exc}")
    except Exception as exc:
        print(f"[TEXT_MODEL] Structured validation error: {exc}")
    return None


def call_text_model_structured(
    messages: list[dict],
    *,
    schema_model: type[BaseModel],
    purpose: str = "utility",
    model: str | None = None,
    num_predict: int = 120,
    temperature: float = 0.1,
    timeout: int = 20,
) -> dict[str, Any] | None:
    """Shared structured text-model call using a JSON schema contract.

    Local Ollama models receive the actual JSON schema via ``format``.
    Cloud models fall back to an explicit JSON-only instruction plus validation.
    """
    choice = TextModelChoice(model, source="explicit") if model else select_text_model(purpose)
    if not choice or not choice.name:
        print("[TEXT_MODEL] Aucun modèle texte disponible pour la sortie structurée")
        return None

    schema = schema_model.model_json_schema()

    try:
        from core.agent_runtime import CloudModelError, chat_with_cloud_model, is_cloud_model_name
        use_cloud_model = is_cloud_model_name(choice.name)
    except Exception:
        CloudModelError = RuntimeError
        chat_with_cloud_model = None
        use_cloud_model = False

    if use_cloud_model and chat_with_cloud_model:
        try:
            cloud_messages = []
            for message in messages:
                cleaned = dict(message)
                cleaned.pop("images", None)
                cloud_messages.append(cleaned)
            cloud_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Return only one JSON object that matches this schema exactly. "
                        "Do not add prose, markdown fences, or extra keys.\n"
                        f"JSON schema:\n{json.dumps(schema, ensure_ascii=False)}"
                    ),
                }
            )
            response = chat_with_cloud_model(
                choice.name,
                messages=cloud_messages,
                tools=[],
                max_tokens=max(1, num_predict),
                temperature=temperature,
                timeout_seconds=max(timeout, 20),
            )
            content = (response.get("message") or {}).get("content", "")
            return _validate_structured_payload(_extract_json_object(content), schema_model=schema_model)
        except CloudModelError as exc:
            print(f"[TEXT_MODEL] Structured cloud error ({choice.name}): {exc}")
        except Exception as exc:
            print(f"[TEXT_MODEL] Structured cloud {type(exc).__name__} ({choice.name}): {exc}")
        return None

    payload = {
        "model": choice.name,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "format": schema,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }

    def _post_with_timeout(request_timeout: int):
        return requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=request_timeout,
        )

    try:
        response = _post_with_timeout(timeout)
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "")
            return _validate_structured_payload(_extract_json_object(content), schema_model=schema_model)
        print(f"[TEXT_MODEL] Structured HTTP {response.status_code} ({choice.name}): {response.text[:200]}")
    except requests.exceptions.Timeout:
        retry_timeout = min(max(timeout * 2, 30), 90)
        if retry_timeout > timeout:
            print(f"[TEXT_MODEL] Structured timeout après {timeout}s avec {choice.name}, retry {retry_timeout}s")
            try:
                response = _post_with_timeout(retry_timeout)
                if response.status_code == 200:
                    content = response.json().get("message", {}).get("content", "")
                    return _validate_structured_payload(_extract_json_object(content), schema_model=schema_model)
                print(f"[TEXT_MODEL] Structured HTTP {response.status_code} ({choice.name}): {response.text[:200]}")
            except requests.exceptions.Timeout:
                print(f"[TEXT_MODEL] Structured timeout après {retry_timeout}s avec {choice.name}")
            except requests.exceptions.ConnectionError:
                print(f"[TEXT_MODEL] Ollama indisponible ({OLLAMA_BASE_URL})")
            except Exception as exc:
                print(f"[TEXT_MODEL] Structured {type(exc).__name__}: {exc}")
        else:
            print(f"[TEXT_MODEL] Structured timeout après {timeout}s avec {choice.name}")
    except requests.exceptions.ConnectionError:
        print(f"[TEXT_MODEL] Ollama indisponible ({OLLAMA_BASE_URL})")
    except Exception as exc:
        print(f"[TEXT_MODEL] Structured {type(exc).__name__}: {exc}")
    return None


def call_text_model(
    messages: list[dict],
    purpose: str = "utility",
    model: str | None = None,
    num_predict: int = 80,
    temperature: float = 0.1,
    timeout: int = 20,
) -> str | None:
    """Shared non-streaming Ollama chat call."""
    choice = TextModelChoice(model, source="explicit") if model else select_text_model(purpose)
    if not choice or not choice.name:
        print("[TEXT_MODEL] Aucun modèle texte disponible")
        return None

    try:
        from core.agent_runtime import CloudModelError, chat_with_cloud_model, is_cloud_model_name
        use_cloud_model = is_cloud_model_name(choice.name)
    except Exception:
        CloudModelError = RuntimeError
        chat_with_cloud_model = None
        use_cloud_model = False

    if use_cloud_model and chat_with_cloud_model:
        cloud_messages = []
        for message in messages:
            cleaned = dict(message)
            # Utility calls are text-only today. Avoid sending Ollama-specific
            # image payloads to API runtimes that do not accept them.
            cleaned.pop("images", None)
            cloud_messages.append(cleaned)

        try:
            response = chat_with_cloud_model(
                choice.name,
                messages=cloud_messages,
                tools=[],
                max_tokens=max(1, num_predict),
                temperature=temperature,
                timeout_seconds=max(timeout, 20),
            )
            content = (response.get("message") or {}).get("content", "")
            return strip_thinking(content) or None
        except CloudModelError as exc:
            print(f"[TEXT_MODEL] Cloud error ({choice.name}): {exc}")
        except Exception as exc:
            print(f"[TEXT_MODEL] Cloud {type(exc).__name__} ({choice.name}): {exc}")
        return None

    payload = {
        "model": choice.name,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }

    def _post_with_timeout(request_timeout: int):
        return requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=request_timeout,
        )

    try:
        response = _post_with_timeout(timeout)
        if response.status_code == 200:
            content = response.json().get("message", {}).get("content", "")
            return strip_thinking(content) or None
        print(f"[TEXT_MODEL] HTTP {response.status_code} ({choice.name}): {response.text[:200]}")
    except requests.exceptions.Timeout:
        retry_timeout = min(max(timeout * 2, 30), 90)
        if retry_timeout > timeout:
            print(f"[TEXT_MODEL] Timeout après {timeout}s avec {choice.name}, retry {retry_timeout}s")
            try:
                response = _post_with_timeout(retry_timeout)
                if response.status_code == 200:
                    content = response.json().get("message", {}).get("content", "")
                    return strip_thinking(content) or None
                print(f"[TEXT_MODEL] HTTP {response.status_code} ({choice.name}): {response.text[:200]}")
            except requests.exceptions.Timeout:
                print(f"[TEXT_MODEL] Timeout après {retry_timeout}s avec {choice.name}")
            except requests.exceptions.ConnectionError:
                print(f"[TEXT_MODEL] Ollama indisponible ({OLLAMA_BASE_URL})")
            except Exception as exc:
                print(f"[TEXT_MODEL] {type(exc).__name__}: {exc}")
        else:
            print(f"[TEXT_MODEL] Timeout après {timeout}s avec {choice.name}")
    except requests.exceptions.ConnectionError:
        print(f"[TEXT_MODEL] Ollama indisponible ({OLLAMA_BASE_URL})")
    except Exception as exc:
        print(f"[TEXT_MODEL] {type(exc).__name__}: {exc}")
    return None
