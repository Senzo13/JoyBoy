"""Optional local Browser Use runtime.

The public core keeps browser control optional and dependency-light.  When
Playwright is installed locally, JoyBoy can drive a headless Chromium session
and stream screenshots into the UI panel.  Heavier autonomous agents can still
be layered later through a local pack without coupling the core to them.
"""

from __future__ import annotations

import base64
import importlib.util
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any


_URL_RE = re.compile(r"^(?:https?://|file://|about:)", re.IGNORECASE)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def normalize_browser_url(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return "about:blank"
    if _URL_RE.match(value):
        return value
    if value.startswith("localhost") or value.startswith("127.") or value.startswith("[::1]"):
        return f"http://{value}"
    if "." in value and " " not in value:
        return f"https://{value}"
    return f"https://www.google.com/search?q={value.replace(' ', '+')}"


def get_browser_use_status() -> dict[str, Any]:
    return {
        "success": True,
        "playwright_installed": _module_available("playwright"),
        "browser_use_installed": _module_available("browser_use"),
        "usable": _module_available("playwright"),
        "running": _WORKER.is_running(),
        "url": _WORKER.current_url,
        "title": _WORKER.current_title,
    }


def install_browser_use_runtime(include_agent: bool = False) -> dict[str, Any]:
    """Install the optional runtime on demand.

    This deliberately does not run during JoyBoy setup/start.  Browser control
    stays an opt-in extension so it cannot surprise users with a Chromium
    download or dependency churn.
    """

    packages = ["playwright>=1.48,<2"]
    if include_agent:
        packages.append("browser-use")

    commands: list[list[str]] = [
        [sys.executable, "-m", "pip", "install", *packages],
        [sys.executable, "-m", "playwright", "install", "chromium"],
    ]
    logs: list[str] = []
    for command in commands:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        logs.append(proc.stdout[-4000:] if proc.stdout else "")
        if proc.returncode != 0:
            return {
                **get_browser_use_status(),
                "success": False,
                "error": f"Commande échouée: {' '.join(command)}",
                "return_code": proc.returncode,
                "logs": "\n".join(logs)[-8000:],
            }

    return {
        **get_browser_use_status(),
        "success": True,
        "logs": "\n".join(logs)[-8000:],
    }


@dataclass
class _BrowserCommand:
    action: str
    payload: dict[str, Any]
    result_queue: "queue.Queue[dict[str, Any]]"


class BrowserUseWorker:
    def __init__(self) -> None:
        self._commands: "queue.Queue[_BrowserCommand | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0
        self.current_url = ""
        self.current_title = ""

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def call(self, action: str, payload: dict[str, Any] | None = None, timeout: float = 75.0) -> dict[str, Any]:
        if not _module_available("playwright"):
            return {
                **get_browser_use_status(),
                "success": False,
                "code": "runtime_missing",
                "error": "Browser Use demande Playwright. Installe l’extension depuis le hub Extensions.",
            }
        self._ensure_thread()
        result_queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=1)
        self._commands.put(_BrowserCommand(action=action, payload=payload or {}, result_queue=result_queue))
        try:
            result = result_queue.get(timeout=timeout)
        except queue.Empty:
            return {"success": False, "error": "Browser Use ne répond pas encore. Réessaie dans quelques secondes."}
        if result.get("url") is not None:
            self.current_url = str(result.get("url") or "")
        if result.get("title") is not None:
            self.current_title = str(result.get("title") or "")
        return result

    def _ensure_thread(self) -> None:
        if self.is_running():
            return
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="joyboy-browser-use", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        playwright = None
        browser = None
        context = None
        page = None

        def ensure_page(width: int = 1280, height: int = 820):
            nonlocal playwright, browser, context, page
            if playwright is None:
                from playwright.sync_api import sync_playwright

                playwright = sync_playwright().start()
            if browser is None:
                browser = playwright.chromium.launch(headless=True)
            if context is None:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    ignore_https_errors=True,
                )
            if page is None:
                page = context.new_page()
            else:
                page.set_viewport_size({"width": width, "height": height})
            return page

        def snapshot(active_page) -> dict[str, Any]:
            png = active_page.screenshot(full_page=False, type="png")
            return {
                "success": True,
                "url": active_page.url,
                "title": active_page.title(),
                "screenshot": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            }

        def close_runtime() -> dict[str, Any]:
            nonlocal playwright, browser, context, page
            try:
                if context is not None:
                    context.close()
            finally:
                context = None
                page = None
            try:
                if browser is not None:
                    browser.close()
            finally:
                browser = None
            try:
                if playwright is not None:
                    playwright.stop()
            finally:
                playwright = None
            return {"success": True, "url": "", "title": "", "closed": True}

        while True:
            command = self._commands.get()
            if command is None:
                close_runtime()
                return
            try:
                payload = command.payload or {}
                width = max(480, min(int(payload.get("width") or 1280), 2400))
                height = max(320, min(int(payload.get("height") or 820), 1800))
                action = str(command.action or "screenshot").strip().lower()

                if action == "close":
                    result = close_runtime()
                else:
                    active_page = ensure_page(width, height)
                    if action in {"open", "navigate"}:
                        active_page.goto(
                            normalize_browser_url(payload.get("url") or payload.get("task")),
                            wait_until="domcontentloaded",
                            timeout=35000,
                        )
                    elif action == "task":
                        task = str(payload.get("task") or "").strip()
                        active_page.goto(normalize_browser_url(_extract_url_or_query(task)), wait_until="domcontentloaded", timeout=35000)
                    elif action == "click":
                        active_page.mouse.click(float(payload.get("x") or 0), float(payload.get("y") or 0))
                        _try_load_wait(active_page, 5000)
                    elif action == "type":
                        text = str(payload.get("text") or "")
                        if text:
                            active_page.keyboard.type(text, delay=8)
                    elif action == "press":
                        active_page.keyboard.press(str(payload.get("key") or "Enter"))
                        _try_load_wait(active_page, 5000)
                    elif action == "scroll":
                        active_page.mouse.wheel(float(payload.get("deltaX") or 0), float(payload.get("deltaY") or 420))
                    elif action == "back":
                        active_page.go_back(wait_until="domcontentloaded", timeout=12000)
                    elif action == "forward":
                        active_page.go_forward(wait_until="domcontentloaded", timeout=12000)
                    elif action == "reload":
                        active_page.reload(wait_until="domcontentloaded", timeout=20000)
                    result = snapshot(active_page)
                command.result_queue.put(result)
            except Exception as exc:  # pragma: no cover - depends on local browser runtime
                command.result_queue.put({
                    "success": False,
                    "error": str(exc),
                    "url": self.current_url,
                    "title": self.current_title,
                })


def _try_load_wait(page: Any, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass


def _extract_url_or_query(task: str) -> str:
    match = re.search(r"(https?://[^\s]+|localhost:\d+[^\s]*|127\.\d+\.\d+\.\d+:\d+[^\s]*)", task, re.IGNORECASE)
    if match:
        return match.group(1)
    return task or "about:blank"


_WORKER = BrowserUseWorker()


def run_browser_use_action(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return _WORKER.call(action, payload or {})
