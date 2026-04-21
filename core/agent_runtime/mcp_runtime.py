"""DeerFlow-style MCP runtime for JoyBoy terminal tools.

This module keeps MCP support local-first and optional:
- configuration lives in JoyBoy's local config outside git
- MCP packages are imported lazily
- tools are cached by config signature
- terminal can expose MCP tools through deferred `tool_search`
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import hashlib
import importlib.util
import inspect
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import requests

from core.infra.local_config import get_mcp_servers

logger = logging.getLogger(__name__)

_SYNC_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="joyboy-mcp")
atexit.register(lambda: _SYNC_TOOL_EXECUTOR.shutdown(wait=False))

_MCP_TOOLS_CACHE: list["McpToolAdapter"] = []
_MCP_CACHE_SIGNATURE = ""
_MCP_LAST_ERROR = ""
_MCP_LOCK = threading.Lock()


@dataclass(frozen=True)
class McpToolAdapter:
    name: str
    description: str
    schema: dict[str, Any]
    invoke: Callable[[dict[str, Any]], Any]
    server_name: str = ""
    source: str = "mcp"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "server_name": self.server_name,
            "source": self.source,
            "tags": list(self.tags),
        }


@dataclass
class _OAuthToken:
    access_token: str
    token_type: str
    expires_at: datetime


class _OAuthTokenManager:
    def __init__(self, oauth_by_server: dict[str, dict[str, Any]]):
        self._oauth_by_server = oauth_by_server
        self._tokens: dict[str, _OAuthToken] = {}
        self._locks: dict[str, asyncio.Lock] = {name: asyncio.Lock() for name in oauth_by_server}

    def has_oauth_servers(self) -> bool:
        return bool(self._oauth_by_server)

    def oauth_server_names(self) -> list[str]:
        return list(self._oauth_by_server.keys())

    async def get_authorization_header(self, server_name: str) -> str | None:
        oauth = self._oauth_by_server.get(server_name)
        if not oauth:
            return None

        token = self._tokens.get(server_name)
        if token and not self._is_expiring(token, oauth):
            return f"{token.token_type} {token.access_token}"

        async with self._locks[server_name]:
            token = self._tokens.get(server_name)
            if token and not self._is_expiring(token, oauth):
                return f"{token.token_type} {token.access_token}"

            fresh = await self._fetch_token(oauth)
            self._tokens[server_name] = fresh
            return f"{fresh.token_type} {fresh.access_token}"

    @staticmethod
    def _is_expiring(token: _OAuthToken, oauth: dict[str, Any]) -> bool:
        try:
            skew = int(oauth.get("refresh_skew_seconds") or 60)
        except (TypeError, ValueError):
            skew = 60
        return token.expires_at <= datetime.now(UTC) + timedelta(seconds=max(skew, 0))

    async def _fetch_token(self, oauth: dict[str, Any]) -> _OAuthToken:
        token_url = str(oauth.get("token_url") or "").strip()
        if not token_url:
            raise ValueError("OAuth token_url is required")

        grant_type = str(oauth.get("grant_type") or "client_credentials").strip() or "client_credentials"
        data: dict[str, str] = {
            "grant_type": grant_type,
            **{str(k): str(v) for k, v in dict(oauth.get("extra_token_params") or {}).items()},
        }

        scope = str(oauth.get("scope") or "").strip()
        audience = str(oauth.get("audience") or "").strip()
        if scope:
            data["scope"] = scope
        if audience:
            data["audience"] = audience

        if grant_type == "client_credentials":
            client_id = str(oauth.get("client_id") or "").strip()
            client_secret = str(oauth.get("client_secret") or "").strip()
            if not client_id or not client_secret:
                raise ValueError("OAuth client_credentials requires client_id and client_secret")
            data["client_id"] = client_id
            data["client_secret"] = client_secret
        elif grant_type == "refresh_token":
            refresh_token = str(oauth.get("refresh_token") or "").strip()
            if not refresh_token:
                raise ValueError("OAuth refresh_token grant requires refresh_token")
            data["refresh_token"] = refresh_token
            client_id = str(oauth.get("client_id") or "").strip()
            client_secret = str(oauth.get("client_secret") or "").strip()
            if client_id:
                data["client_id"] = client_id
            if client_secret:
                data["client_secret"] = client_secret
        else:
            raise ValueError(f"Unsupported OAuth grant type: {grant_type}")

        def _post() -> dict[str, Any]:
            response = requests.post(token_url, data=data, timeout=15)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}

        payload = await asyncio.to_thread(_post)
        token_field = str(oauth.get("token_field") or "access_token").strip() or "access_token"
        token_type_field = str(oauth.get("token_type_field") or "token_type").strip() or "token_type"
        expires_in_field = str(oauth.get("expires_in_field") or "expires_in").strip() or "expires_in"
        default_token_type = str(oauth.get("default_token_type") or "Bearer").strip() or "Bearer"

        access_token = str(payload.get(token_field) or "").strip()
        if not access_token:
            raise ValueError(f"OAuth token response missing '{token_field}'")

        token_type = str(payload.get(token_type_field) or default_token_type).strip() or default_token_type
        try:
            expires_in = int(payload.get(expires_in_field) or 3600)
        except (TypeError, ValueError):
            expires_in = 3600

        return _OAuthToken(
            access_token=access_token,
            token_type=token_type,
            expires_at=datetime.now(UTC) + timedelta(seconds=max(expires_in, 1)),
        )


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("$"):
            return os.getenv(value[1:], "")
        return value
    if isinstance(value, dict):
        return {str(key): _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    return value


def _package_state() -> dict[str, bool]:
    return {
        "langchain_core": bool(importlib.util.find_spec("langchain_core")),
        "langchain_mcp_adapters": bool(importlib.util.find_spec("langchain_mcp_adapters")),
        "mcp": bool(importlib.util.find_spec("mcp")),
    }


def _config_signature(raw_servers: dict[str, Any]) -> str:
    state = {
        "packages": _package_state(),
        "servers": raw_servers,
    }
    blob = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _enabled_mcp_servers(resolve_env: bool = False) -> dict[str, dict[str, Any]]:
    raw = get_mcp_servers()
    enabled = {
        name: config
        for name, config in raw.items()
        if isinstance(config, dict) and bool(config.get("enabled", True))
    }
    if resolve_env:
        return {name: _resolve_env_placeholders(config) for name, config in enabled.items()}
    return enabled


def _build_server_params(server_name: str, config: dict[str, Any]) -> dict[str, Any]:
    transport = str(config.get("type") or "stdio").strip().lower() or "stdio"
    params: dict[str, Any] = {"transport": transport}

    if transport == "stdio":
        command = str(config.get("command") or "").strip()
        if not command:
            raise ValueError(f"MCP server '{server_name}' with stdio transport requires 'command'")
        params["command"] = command
        params["args"] = list(config.get("args") or [])
        env = dict(config.get("env") or {})
        if env:
            params["env"] = env
    elif transport in {"sse", "http"}:
        url = str(config.get("url") or "").strip()
        if not url:
            raise ValueError(f"MCP server '{server_name}' with {transport} transport requires 'url'")
        params["url"] = url
        headers = dict(config.get("headers") or {})
        if headers:
            params["headers"] = headers
    else:
        raise ValueError(f"Unsupported MCP transport for '{server_name}': {transport}")

    return params


def _build_servers_config(enabled_servers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    servers_config: dict[str, dict[str, Any]] = {}
    for server_name, config in enabled_servers.items():
        try:
            servers_config[server_name] = _build_server_params(server_name, config)
        except Exception as exc:
            logger.warning("Skipping MCP server %s: %s", server_name, exc)
    return servers_config


def _oauth_manager(enabled_servers: dict[str, dict[str, Any]]) -> _OAuthTokenManager | None:
    oauth_by_server: dict[str, dict[str, Any]] = {}
    for server_name, config in enabled_servers.items():
        oauth = config.get("oauth")
        if isinstance(oauth, dict) and bool(oauth.get("enabled", True)):
            oauth_by_server[server_name] = oauth
    if not oauth_by_server:
        return None
    return _OAuthTokenManager(oauth_by_server)


async def _get_initial_oauth_headers(enabled_servers: dict[str, dict[str, Any]]) -> dict[str, str]:
    manager = _oauth_manager(enabled_servers)
    if manager is None:
        return {}

    headers: dict[str, str] = {}
    for server_name in manager.oauth_server_names():
        header = await manager.get_authorization_header(server_name)
        if header:
            headers[server_name] = header
    return headers


def _build_oauth_tool_interceptor(enabled_servers: dict[str, dict[str, Any]]) -> Any | None:
    manager = _oauth_manager(enabled_servers)
    if manager is None:
        return None

    async def oauth_interceptor(request: Any, handler: Any) -> Any:
        header = await manager.get_authorization_header(request.server_name)
        if not header:
            return await handler(request)

        updated_headers = dict(getattr(request, "headers", {}) or {})
        updated_headers["Authorization"] = header
        if hasattr(request, "override"):
            return await handler(request.override(headers=updated_headers))
        request.headers = updated_headers
        return await handler(request)

    return oauth_interceptor


def _run_awaitable(awaitable: Any) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        future = _SYNC_TOOL_EXECUTOR.submit(asyncio.run, awaitable)
        return future.result()
    return asyncio.run(awaitable)


def _make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return _run_awaitable(coro(*args, **kwargs))
        except Exception as exc:
            logger.error("Error invoking MCP tool '%s': %s", tool_name, exc, exc_info=True)
            raise

    return sync_wrapper


def _fallback_schema(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None:
        for method_name in ("model_json_schema", "schema"):
            method = getattr(args_schema, method_name, None)
            if callable(method):
                try:
                    schema = method()
                    if isinstance(schema, dict):
                        return schema
                except Exception:
                    pass
    return {"type": "object", "properties": {}}


def _server_name_from_tool_name(name: str) -> str:
    if "__" in name:
        return name.split("__", 1)[0]
    if ":" in name:
        return name.split(":", 1)[0]
    return ""


def _build_tool_invoker(tool: Any) -> Callable[[dict[str, Any]], Any]:
    sync_coro = None
    if callable(getattr(tool, "coroutine", None)):
        sync_coro = _make_sync_tool_wrapper(tool.coroutine, getattr(tool, "name", "mcp_tool"))

    def invoke(arguments: dict[str, Any]) -> Any:
        args = dict(arguments or {})

        if callable(getattr(tool, "invoke", None)):
            response = tool.invoke(args)
            if inspect.isawaitable(response):
                return _run_awaitable(response)
            return response

        if callable(getattr(tool, "func", None)):
            return tool.func(**args) if args else tool.func()

        if sync_coro is not None:
            return sync_coro(**args) if args else sync_coro()

        raise RuntimeError(f"MCP tool '{getattr(tool, 'name', 'unknown')}' is not invokable")

    return invoke


def _tool_to_adapter(tool: Any) -> McpToolAdapter:
    description = str(getattr(tool, "description", "") or "")
    schema = _fallback_schema(tool)

    try:
        from langchain_core.utils.function_calling import convert_to_openai_function

        fn = convert_to_openai_function(tool)
        description = str(fn.get("description") or description)
        schema = fn.get("parameters") or schema
    except Exception:
        pass

    name = str(getattr(tool, "name", "") or "").strip()
    server_name = _server_name_from_tool_name(name)
    tags = tuple(part for part in ("mcp", server_name) if part)
    return McpToolAdapter(
        name=name,
        description=description,
        schema=schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
        invoke=_build_tool_invoker(tool),
        server_name=server_name,
        tags=tags,
    )


async def _load_mcp_tools_async() -> list[McpToolAdapter]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    enabled_servers = _enabled_mcp_servers(resolve_env=True)
    servers_config = _build_servers_config(enabled_servers)
    if not servers_config:
        return []

    initial_oauth_headers = await _get_initial_oauth_headers(enabled_servers)
    for server_name, auth_header in initial_oauth_headers.items():
        if server_name not in servers_config:
            continue
        if servers_config[server_name].get("transport") in {"sse", "http"}:
            headers = dict(servers_config[server_name].get("headers", {}) or {})
            headers["Authorization"] = auth_header
            servers_config[server_name]["headers"] = headers

    interceptors = []
    oauth_interceptor = _build_oauth_tool_interceptor(enabled_servers)
    if oauth_interceptor is not None:
        interceptors.append(oauth_interceptor)

    client = MultiServerMCPClient(servers_config, tool_interceptors=interceptors, tool_name_prefix=True)
    tools = await client.get_tools()
    return [_tool_to_adapter(tool) for tool in tools if getattr(tool, "name", None)]


def reset_mcp_tool_cache() -> None:
    global _MCP_TOOLS_CACHE, _MCP_CACHE_SIGNATURE, _MCP_LAST_ERROR
    with _MCP_LOCK:
        _MCP_TOOLS_CACHE = []
        _MCP_CACHE_SIGNATURE = ""
        _MCP_LAST_ERROR = ""


def get_cached_mcp_tools(force_refresh: bool = False) -> list[McpToolAdapter]:
    global _MCP_TOOLS_CACHE, _MCP_CACHE_SIGNATURE, _MCP_LAST_ERROR

    raw_servers = get_mcp_servers()
    signature = _config_signature(raw_servers)

    with _MCP_LOCK:
        if not force_refresh and signature == _MCP_CACHE_SIGNATURE:
            return list(_MCP_TOOLS_CACHE)

    enabled_count = sum(1 for config in raw_servers.values() if isinstance(config, dict) and bool(config.get("enabled", True)))
    packages = _package_state()
    if enabled_count == 0:
        with _MCP_LOCK:
            _MCP_TOOLS_CACHE = []
            _MCP_CACHE_SIGNATURE = signature
            _MCP_LAST_ERROR = ""
        return []

    if not all(packages.values()):
        missing = [name for name, available in packages.items() if not available]
        error = "Missing MCP runtime packages: " + ", ".join(missing)
        with _MCP_LOCK:
            _MCP_TOOLS_CACHE = []
            _MCP_CACHE_SIGNATURE = signature
            _MCP_LAST_ERROR = error
        logger.warning(error)
        return []

    try:
        adapters = _run_awaitable(_load_mcp_tools_async())
        error = ""
    except Exception as exc:
        adapters = []
        error = str(exc)
        logger.error("Failed to load MCP tools: %s", exc, exc_info=True)

    with _MCP_LOCK:
        _MCP_TOOLS_CACHE = list(adapters)
        _MCP_CACHE_SIGNATURE = signature
        _MCP_LAST_ERROR = error

    return list(adapters)


def get_mcp_runtime_status(load_tools: bool = False) -> dict[str, Any]:
    raw_servers = get_mcp_servers()
    enabled_servers = [name for name, config in raw_servers.items() if isinstance(config, dict) and bool(config.get("enabled", True))]
    packages = _package_state()
    tools: list[McpToolAdapter] = []
    if load_tools and enabled_servers and all(packages.values()):
        tools = get_cached_mcp_tools()

    with _MCP_LOCK:
        last_error = _MCP_LAST_ERROR
        cached_count = len(_MCP_TOOLS_CACHE)

    return {
        "configured_count": len(raw_servers),
        "enabled_count": len(enabled_servers),
        "enabled_servers": enabled_servers,
        "package_state": packages,
        "package_available": all(packages.values()),
        "cached_tool_count": cached_count,
        "loaded_tool_count": len(tools),
        "loaded_tools": [tool.to_public_dict() for tool in tools],
        "last_error": last_error,
    }

