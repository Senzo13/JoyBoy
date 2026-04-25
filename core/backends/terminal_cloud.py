"""Cloud provider handling for JoyBoy terminal.

This module keeps provider retry, quota/auth classification, context sizing,
and circuit-breaker behavior out of the terminal orchestration loop. The
methods are implemented as a mixin so existing TerminalBrain callers keep the
same private helper API while the responsibilities are split cleanly.
"""

from __future__ import annotations

import re
import time
from email.utils import parsedate_to_datetime
from typing import Any, Optional


class TerminalCloudMixin:
    """Cloud-model sizing, retry, and circuit-breaker helpers."""

    def _default_cloud_context_size(self, model: str | None = None) -> int:
        model_id = str(model or "").strip().lower()
        if model_id in {"openai:gpt-5.5", "openai:gpt-5.4"}:
            return 1_000_000
        if model_id.startswith("openai:gpt-5"):
            return 400_000
        if model_id.startswith("gemini:"):
            return 1_000_000
        return self.DEFAULT_CLOUD_CONTEXT_SIZE

    def _normalize_context_size(self, context_size: int | str | None, cloud: bool = False, model: str | None = None) -> int:
        try:
            value = int(context_size or 4096)
        except Exception:
            value = 4096
        if cloud:
            value = max(value, self._default_cloud_context_size(model))
            return max(self.MIN_CONTEXT_SIZE, min(self.MAX_CLOUD_CONTEXT_SIZE, value))
        return max(self.MIN_CONTEXT_SIZE, min(self.MAX_LOCAL_CONTEXT_SIZE, value))

    def _turn_token_budget(self, context_size: int, autonomous: bool = False, cloud: bool = False) -> int:
        if cloud:
            if autonomous:
                # Autonomous turns should be deeper than normal turns, but
                # still checkpoint before a no-progress loop can spend a whole
                # large-context window on repeated reads/searches.
                return max(32000, min(90000, int(context_size * 0.45)))
            return max(26000, min(90000, int(context_size * 0.5)))
        if autonomous:
            return max(6500, min(self.MAX_LOCAL_CONTEXT_SIZE, int(context_size * 0.75)))
        if context_size <= 32768:
            return max(2500, min(self.max_non_autonomous_tokens, int(context_size * 0.9)))
        if context_size <= 65536:
            return 12000
        if context_size <= 131072:
            return 18000
        return 26000

    @staticmethod
    def _extract_cloud_error_status_code(exc: BaseException) -> Optional[int]:
        for attr in ("status_code", "status"):
            value = getattr(exc, attr, None)
            if isinstance(value, int):
                return value

        response = getattr(exc, "response", None)
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int):
            return response_status

        detail = str(exc or "")
        match = re.search(r"\b(?:api error|error)\s+(\d{3})\b", detail, re.IGNORECASE)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _extract_cloud_error_code(exc: BaseException) -> Optional[str]:
        for attr in ("code", "error_code"):
            value = getattr(exc, attr, None)
            if value not in (None, ""):
                return str(value)

        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                for key in ("code", "type"):
                    value = error.get(key)
                    if value not in (None, ""):
                        return str(value)
        return None

    @staticmethod
    def _extract_cloud_error_detail(exc: BaseException) -> str:
        detail = str(exc or "").strip()
        if detail:
            return detail
        message = getattr(exc, "message", None)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return exc.__class__.__name__

    @staticmethod
    def _extract_cloud_retry_after_ms(exc: BaseException) -> Optional[int]:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if not headers or not hasattr(headers, "get"):
            return None

        raw_value: Any = None
        header_name = ""
        for key in ("retry-after-ms", "Retry-After-Ms", "retry-after", "Retry-After"):
            value = headers.get(key)
            if value not in (None, ""):
                raw_value = value
                header_name = key
                break
        if raw_value in (None, ""):
            return None

        try:
            multiplier = 1 if "ms" in header_name.lower() else 1000
            return max(0, int(float(raw_value) * multiplier))
        except (TypeError, ValueError):
            try:
                target = parsedate_to_datetime(str(raw_value))
                delta = target.timestamp() - time.time()
                return max(0, int(delta * 1000))
            except (TypeError, ValueError, OverflowError):
                return None

    def _classify_cloud_model_error(self, exc: BaseException) -> tuple[bool, str]:
        detail = self._extract_cloud_error_detail(exc).lower()
        error_code = (self._extract_cloud_error_code(exc) or "").lower()
        status_code = self._extract_cloud_error_status_code(exc)

        quota_patterns = (
            "insufficient_quota", "quota", "billing", "credit", "payment",
            "余额不足", "超出限额", "额度不足", "欠费",
        )
        auth_patterns = (
            "authentication", "unauthorized", "invalid api key", "invalid_api_key",
            "permission", "forbidden", "access denied", "未授权", "无权",
        )
        busy_patterns = (
            "server busy", "temporarily unavailable", "try again later",
            "please retry", "please try again", "overloaded", "high demand",
            "rate limit", "service unavailable", "timeout", "timed out",
        )
        retriable_statuses = {408, 409, 425, 429, 500, 502, 503, 504}

        if any(pattern in detail or pattern in error_code for pattern in quota_patterns):
            return False, "quota"
        if any(pattern in detail or pattern in error_code for pattern in auth_patterns):
            return False, "auth"
        if status_code in retriable_statuses:
            return True, "busy" if status_code == 429 else "transient"
        if any(pattern in detail for pattern in busy_patterns):
            return True, "busy"
        return False, "generic"

    def _cloud_retry_delay_ms(self, attempt: int, exc: BaseException) -> int:
        retry_after_ms = self._extract_cloud_retry_after_ms(exc)
        if retry_after_ms is not None:
            return min(retry_after_ms, 60000)

        status_code = self._extract_cloud_error_status_code(exc)
        base_delay = 1500 if status_code in {429, 503} else 1000
        return min(base_delay * (2 ** max(0, attempt - 1)), 8000)

    @staticmethod
    def _cloud_retry_message(attempt: int, max_attempts: int, wait_ms: int, reason: str) -> str:
        seconds = max(1, round(wait_ms / 1000))
        if reason == "busy":
            reason_text = "provider busy or rate-limited"
        else:
            reason_text = "temporary provider failure"
        return f"Cloud model retry {attempt}/{max_attempts}: {reason_text}. Retrying in {seconds}s."

    def _cloud_error_user_message(self, exc: BaseException) -> str:
        detail = str(exc or "").strip()
        _, reason = self._classify_cloud_model_error(exc)
        if reason == "quota":
            return (
                "Le provider cloud a refusé la requête car le compte n'a plus de quota, "
                "de crédits API, ou de facturation active."
            )
        if reason == "auth":
            return (
                "Le provider cloud a refusé la requête car l'authentification ou l'accès "
                "est invalide. Vérifie la clé ou le mode d'accès."
            )
        if reason in {"busy", "transient"}:
            return (
                "Le provider cloud est temporairement indisponible après plusieurs tentatives. "
                "Réessaie dans un instant."
            )
        return detail or "Cloud model request failed."

    @staticmethod
    def _cloud_provider_key(model_name: str) -> str:
        provider, _, _rest = str(model_name or "").partition(":")
        return provider or "cloud"

    def _cloud_circuit_block_reason(self, model_name: str) -> Optional[str]:
        provider_key = self._cloud_provider_key(model_name)
        open_until = float(self._cloud_circuit_open_until.get(provider_key, 0.0) or 0.0)
        now = time.time()
        if open_until and now < open_until:
            self._cloud_circuit_state[provider_key] = "open"
            remaining = max(1, int(round(open_until - now)))
            return (
                f"Cloud circuit breaker active for {provider_key}. "
                f"Too many transient failures; retry in about {remaining}s."
            )
        if open_until and now >= open_until:
            self._cloud_circuit_state[provider_key] = "half_open"
            self._cloud_circuit_open_until[provider_key] = 0.0
            self._cloud_circuit_probe_in_flight[provider_key] = False

        if self._cloud_circuit_state.get(provider_key) == "half_open":
            if self._cloud_circuit_probe_in_flight.get(provider_key):
                return (
                    f"Cloud circuit breaker recovery probe already running for {provider_key}. "
                    "Wait for that request before retrying."
                )
            self._cloud_circuit_probe_in_flight[provider_key] = True
            return None
        return None

    def _record_cloud_circuit_success(self, model_name: str) -> None:
        provider_key = self._cloud_provider_key(model_name)
        self._cloud_circuit_failures[provider_key] = 0
        self._cloud_circuit_open_until[provider_key] = 0.0
        self._cloud_circuit_state[provider_key] = "closed"
        self._cloud_circuit_probe_in_flight[provider_key] = False

    def _record_cloud_circuit_failure(self, model_name: str) -> None:
        provider_key = self._cloud_provider_key(model_name)
        if self._cloud_circuit_state.get(provider_key) == "half_open":
            self._cloud_circuit_failures[provider_key] = self._cloud_circuit_threshold
            self._cloud_circuit_open_until[provider_key] = time.time() + self._cloud_circuit_timeout_seconds
            self._cloud_circuit_state[provider_key] = "open"
            self._cloud_circuit_probe_in_flight[provider_key] = False
            return

        failures = int(self._cloud_circuit_failures.get(provider_key, 0) or 0) + 1
        self._cloud_circuit_failures[provider_key] = failures
        if failures >= self._cloud_circuit_threshold:
            self._cloud_circuit_open_until[provider_key] = time.time() + self._cloud_circuit_timeout_seconds
            self._cloud_circuit_state[provider_key] = "open"
            self._cloud_circuit_probe_in_flight[provider_key] = False
