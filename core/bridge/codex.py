"""Official Codex app-server JSONL client; credentials remain managed by Codex."""
from __future__ import annotations

import json
from collections import deque
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


def find_codex() -> str:
    candidates = [os.environ.get("JOYBOY_CODEX_BIN"), shutil.which("codex")]
    if os.name != "nt":
        candidates.extend([
            "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ])
    for candidate in dict.fromkeys(filter(None, candidates)):
        try:
            check = subprocess.run([candidate, "--version"], capture_output=True, timeout=8)
            if check.returncode == 0:
                return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("Codex CLI unavailable. Install Codex or set JOYBOY_CODEX_BIN.")


class CodexClient:
    """One synchronous JSONL client with a background stdout reader."""

    def __init__(self, cwd: Path, executable: str | None = None):
        self.cwd = str(cwd)
        child_env = dict(os.environ)
        # An Images API key must not silently change Codex's managed sign-in.
        child_env.pop("OPENAI_API_KEY", None)
        self.process = subprocess.Popen(
            [executable or find_codex(), "app-server", "--listen", "stdio://"], cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, env=child_env,
        )
        self.messages = queue.Queue()
        self.deferred = deque()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request("initialize", {"clientInfo": {
                "name": "joyboy_light", "title": "JoyBoy Light", "version": "0.1.0",
            }, "capabilities": {}})
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.messages.put(None)

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def receive(self, deadline, include_deferred=True):
        if time.monotonic() >= deadline:
            raise TimeoutError("Codex response timed out")
        if include_deferred and self.deferred:
            return self.deferred.popleft()
        try:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError("Codex response timed out") from None
        if message is None:
            raise RuntimeError("Codex app-server stopped")
        if "method" in message and "id" in message:
            # This prototype has no approval UI. Never silently approve actions.
            self.send({"id": message["id"], "error": {
                "code": -32601, "message": "JoyBoy Light cannot approve this request",
            }})
        return message

    def request(self, method, params, timeout=30):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline, include_deferred=False)
            if method == "turn/start" and "method" in message and "id" not in message:
                self.deferred.append(message)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    # Raw provider errors can contain paths or credentials.
                    raise RuntimeError(f"Codex rejected {method} ({message['error'].get('code')})")
                return message["result"]

    def status(self):
        result = self.request("account/read", {"refreshToken": False})
        account = result.get("account") or {}
        models, cursor = [], None
        while True:
            page = self.request("model/list", {"limit": 100, "cursor": cursor})
            models.extend({k: m.get(k) for k in (
                "id", "model", "displayName", "isDefault", "inputModalities",
            )} for m in page.get("data", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return {"available": True, "authenticated": bool(account),
                "auth_type": account.get("type"), "plan": account.get("planType"),
                "models": models}

    def chat(self, text, model=None, thread_id=None, image_paths=(), timeout=180):
        params = {"cwd": self.cwd, "approvalPolicy": "never", "sandbox": "read-only"}
        config = self.request("config/read", {"includeLayers": False}).get("config", {})
        # Empty TOML tables merge with inherited tables rather than clearing them.
        # Disable each configured integration in this thread's nested overrides.
        params["config"] = {
            "mcp_servers": {name: {"enabled": False} for name in config.get("mcp_servers", {})},
            "plugins": {name: {"enabled": False} for name in config.get("plugins", {})},
            "features": {"apps": False},
            "apps": {"_default": {"enabled": False}},
        }
        if model:
            params["model"] = model
        if thread_id:
            params.update(threadId=thread_id, excludeTurns=True)
            thread = self.request("thread/resume", params)["thread"]
        else:
            thread = self.request("thread/start", params)["thread"]
        cursor = None
        while True:
            tools = self.request("mcpServerStatus/list", {"threadId": thread["id"],
                "limit": 100, "cursor": cursor, "detail": "toolsAndAuthOnly"})
            if any(server.get("tools") for server in tools.get("data", [])):
                raise RuntimeError("Inherited MCP tools remain active; this prototype cannot safely handle their approvals")
            cursor = tools.get("nextCursor")
            if not cursor:
                break
        inputs = [{"type": "text", "text": text}]
        inputs.extend({"type": "localImage", "path": str(p)} for p in image_paths)
        started = self.request("turn/start", {"threadId": thread["id"], "input": inputs,
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False}})
        turn_id = started["turn"]["id"]
        deadline = time.monotonic() + timeout
        parts, completed = [], {}
        try:
            while True:
                event = self.receive(deadline)
                payload = event.get("params", {})
                if payload.get("threadId") != thread["id"]:
                    continue
                if event.get("method") == "item/agentMessage/delta" and payload.get("turnId") == turn_id:
                    parts.append(payload.get("delta", ""))
                if event.get("method") == "item/completed" and payload.get("turnId") == turn_id:
                    item = payload.get("item", {})
                    if item.get("type") == "agentMessage":
                        completed[item["id"]] = item.get("text", "")
                if event.get("method") == "turn/completed" and payload.get("turn", {}).get("id") == turn_id:
                    status = payload["turn"].get("status")
                    if status != "completed":
                        raise RuntimeError(f"Codex turn {status}; no successful answer")
                    return {"thread_id": thread["id"], "turn_id": turn_id,
                            "text": "\n\n".join(completed.values()) or "".join(parts),
                            "status": status}
        except TimeoutError:
            self.send({"id": self.next_id + 1, "method": "turn/interrupt",
                       "params": {"threadId": thread["id"], "turnId": turn_id}})
            raise

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()
