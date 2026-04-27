"""Optional local Browser Use runtime.

The public core keeps browser control optional and dependency-light.  When
Playwright is installed locally, JoyBoy can drive a headless Chromium session
and stream screenshots into the UI panel.  Heavier autonomous agents can still
be layered later through a local pack without coupling the core to them.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


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


def normalize_direct_browser_url(raw: str | None) -> str:
    """Normalize explicit URLs only.

    Natural-language Browser Use tasks are interpreted by the model-driven
    agent path. This helper intentionally avoids turning arbitrary text into a
    Google query, which made generic browser commands behave like search terms.
    """
    value = str(raw or "").strip()
    if not value:
        return "about:blank"
    if _URL_RE.match(value):
        return value
    if value.startswith("localhost") or value.startswith("127.") or value.startswith("[::1]"):
        return f"http://{value}"
    if "." in value and " " not in value:
        return f"https://{value}"
    return value


class BrowserAgentDecision(BaseModel):
    action: str = Field(
        default="finish",
        description=(
            "One of open_url, click_target, click_text, type_text, press_key, "
            "scroll, wait, finish."
        ),
    )
    url: str | None = None
    target: int | None = None
    text: str | None = None
    key: str | None = None
    scroll_y: int | None = None
    answer: str | None = None
    reason: str | None = None


def get_browser_use_status() -> dict[str, Any]:
    worker_status = _WORKER.status()
    return {
        "success": True,
        "playwright_installed": _module_available("playwright"),
        "browser_use_installed": _module_available("browser_use"),
        "usable": _module_available("playwright"),
        "running": _WORKER.is_running(),
        "url": worker_status.get("url") or _WORKER.current_url,
        "title": worker_status.get("title") or _WORKER.current_title,
        **worker_status,
        "install": _INSTALLER.status(),
    }


def install_browser_use_runtime(include_agent: bool = False, background: bool = False) -> dict[str, Any]:
    """Install the optional runtime on demand.

    This deliberately does not run during JoyBoy setup/start.  Browser control
    stays an opt-in extension so it cannot surprise users with a Chromium
    download or dependency churn.
    """

    if background:
        return _INSTALLER.start(include_agent=include_agent)

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


class BrowserUseInstaller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = self._idle_state()

    def _idle_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "complete": False,
            "success": False,
            "progress": 0,
            "step": "",
            "detail": "",
            "error": "",
            "started_at": 0,
            "finished_at": 0,
            "logs": [],
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["logs"] = list(self._state.get("logs") or [])[-40:]
            return state

    def start(self, include_agent: bool = False) -> dict[str, Any]:
        should_start = False
        with self._lock:
            if self._thread and self._thread.is_alive():
                pass
            elif _module_available("playwright"):
                self._state = {
                    **self._idle_state(),
                    "complete": True,
                    "success": True,
                    "progress": 100,
                    "step": "Runtime déjà installé",
                    "detail": "Playwright est disponible.",
                    "finished_at": time.time(),
                }
            else:
                self._state = {
                    **self._idle_state(),
                    "active": True,
                    "progress": 2,
                    "step": "Préparation du runtime navigateur",
                    "detail": "JoyBoy prépare Playwright et Chromium.",
                    "started_at": time.time(),
                }
                self._thread = threading.Thread(
                    target=self._run,
                    args=(include_agent,),
                    name="joyboy-browser-use-install",
                    daemon=True,
                )
                should_start = True
        if should_start and self._thread:
            self._thread.start()
        return get_browser_use_status()

    def _set(self, **updates: Any) -> None:
        with self._lock:
            self._state.update(updates)

    def _append_log(self, line: str) -> None:
        clean = line.rstrip()
        if not clean:
            return
        with self._lock:
            logs = list(self._state.get("logs") or [])
            logs.append(clean[-600:])
            self._state["logs"] = logs[-80:]

    def _run(self, include_agent: bool) -> None:
        try:
            packages = ["playwright>=1.48,<2"]
            if include_agent:
                packages.append("browser-use")

            commands: list[tuple[list[str], str, int, int]] = [
                ([sys.executable, "-m", "pip", "install", *packages], "Installation de Playwright", 5, 46),
                ([sys.executable, "-m", "playwright", "install", "chromium"], "Téléchargement de Chromium", 46, 96),
            ]

            for command, step, start, end in commands:
                self._set(step=step, detail=" ".join(command), progress=start)
                proc = subprocess.Popen(
                    command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._append_log(line)
                    lower = line.lower()
                    if "downloading" in lower or "download" in lower:
                        detail = "Téléchargement des fichiers navigateur..."
                    elif "installing" in lower or "collecting" in lower:
                        detail = "Installation des dépendances locales..."
                    elif "already" in lower or "requirement already satisfied" in lower:
                        detail = "Dépendances déjà présentes, vérification..."
                    else:
                        detail = line.strip()[:140] or step
                    current = int(self.status().get("progress") or start)
                    self._set(detail=detail, progress=min(end - 1, max(start, current + 1)))
                return_code = proc.wait()
                if return_code != 0:
                    raise RuntimeError(f"Commande échouée ({return_code}): {' '.join(command)}")
                self._set(progress=end, detail=f"{step} terminé.")

            self._set(
                active=False,
                complete=True,
                success=True,
                progress=100,
                step="Runtime Browser Use prêt",
                detail="Playwright et Chromium sont installés.",
                error="",
                finished_at=time.time(),
            )
        except Exception as exc:  # pragma: no cover - depends on local package installer
            self._append_log(str(exc))
            self._set(
                active=False,
                complete=True,
                success=False,
                error=str(exc),
                detail=str(exc),
                finished_at=time.time(),
            )


@dataclass
class _BrowserCommand:
    action: str
    payload: dict[str, Any]
    result_queue: "queue.Queue[dict[str, Any]]"


class BrowserUseWorker:
    def __init__(self) -> None:
        self._commands: "queue.Queue[_BrowserCommand | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._live_state: dict[str, Any] = self._empty_live_state()
        self._started_at = 0.0
        self.current_url = ""
        self.current_title = ""

    def _empty_live_state(self) -> dict[str, Any]:
        return {
            "action_active": False,
            "action": "",
            "task": "",
            "status": "",
            "detail": "",
            "progress": 0,
            "url": "",
            "title": "",
            "screenshot": "",
            "cursor": None,
            "agent_steps": [],
            "updated_at": 0,
        }

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = dict(self._live_state)
            state["agent_steps"] = list(self._live_state.get("agent_steps") or [])
            state["cursor"] = dict(self._live_state["cursor"]) if isinstance(self._live_state.get("cursor"), dict) else None
            return state

    def _set_live(self, **updates: Any) -> None:
        with self._state_lock:
            self._live_state.update(updates)
            self._live_state["updated_at"] = time.time()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def cancel_current_action(self) -> dict[str, Any]:
        self._cancel_event.set()
        self._set_live(
            status="Interruption demandée",
            detail="La navigation automatique va rendre la main...",
            action_active=True,
        )
        return {
            "success": True,
            "cancelled": True,
            "url": self.current_url,
            "title": self.current_title,
        }

    def call(self, action: str, payload: dict[str, Any] | None = None, timeout: float = 75.0) -> dict[str, Any]:
        action = str(action or "screenshot").strip().lower()
        if action in {"cancel", "interrupt", "stop"}:
            return self.cancel_current_action()

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

        def snapshot(active_page, **extra: Any) -> dict[str, Any]:
            png = active_page.screenshot(full_page=False, type="png")
            data = {
                "success": True,
                "url": active_page.url,
                "title": active_page.title(),
                "screenshot": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            }
            data.update(extra)
            self.current_url = str(data.get("url") or "")
            self.current_title = str(data.get("title") or "")
            self._set_live(**data)
            return data

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
            self._set_live(**self._empty_live_state())
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
                if action == "task":
                    self._cancel_event.clear()
                self._set_live(
                    action_active=action != "close",
                    action=action,
                    task=str(payload.get("task") or payload.get("url") or ""),
                    status="Navigation en cours...",
                    detail=str(payload.get("task") or payload.get("url") or ""),
                    progress=8,
                    cursor=None,
                    agent_steps=[],
                )

                if action == "close":
                    result = close_runtime()
                else:
                    active_page = ensure_page(width, height)
                    try:
                        snapshot(active_page, progress=12, status="Navigateur prêt")
                    except Exception:
                        pass
                    if action in {"open", "navigate"}:
                        active_page.goto(
                            normalize_browser_url(payload.get("url") or payload.get("task")),
                            wait_until="domcontentloaded",
                            timeout=35000,
                        )
                        result = snapshot(active_page, progress=100, status="Page ouverte")
                    elif action == "task":
                        task = str(payload.get("task") or "").strip()
                        result = _run_browser_agent_task(active_page, task, payload, snapshot, self._cancel_event)
                        self._set_live(
                            action_active=False,
                            progress=100,
                            status=result.get("answer") or result.get("error") or "Action terminée",
                        )
                        command.result_queue.put(result)
                        continue
                    elif action == "click":
                        x = float(payload.get("x") or 0)
                        y = float(payload.get("y") or 0)
                        active_page.mouse.move(x, y, steps=12)
                        active_page.mouse.click(x, y)
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
                    if action != "open" and action != "navigate":
                        result = snapshot(active_page, progress=100, status="Action terminée")
                        if action == "click":
                            result["cursor"] = {"x": x, "y": y}
                            self._set_live(cursor=result["cursor"])
                self._set_live(action_active=False, progress=100)
                command.result_queue.put(result)
            except Exception as exc:  # pragma: no cover - depends on local browser runtime
                self._set_live(action_active=False, status="Browser Use bloqué", detail=str(exc), progress=100)
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


def _truncate_browser_text(value: Any, limit: int = 6000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _describe_browser_decision(decision: BrowserAgentDecision) -> str:
    parts: list[str] = []
    if decision.url:
        parts.append(f"url={_truncate_browser_text(decision.url, 140)}")
    if decision.target is not None:
        parts.append(f"target={decision.target}")
    if decision.text:
        parts.append(f"text={_truncate_browser_text(decision.text, 140)}")
    if decision.key:
        parts.append(f"key={_truncate_browser_text(decision.key, 40)}")
    if decision.scroll_y:
        parts.append(f"scroll_y={decision.scroll_y}")
    if decision.reason:
        parts.append(f"reason={_truncate_browser_text(decision.reason, 180)}")
    return " ".join(parts)


def _read_browser_page_text(page: Any) -> str:
    try:
        return _truncate_browser_text(page.locator("body").inner_text(timeout=2500), 6500)
    except Exception:
        return ""


def _extract_browser_targets(page: Any) -> list[dict[str, Any]]:
    script = r"""
() => {
  const quoteAttr = value => String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const visible = el => {
    if (!el || el.nodeType !== 1) return false;
    try {
      if (typeof el.checkVisibility === 'function' && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
        return false;
      }
    } catch (_) {}
    const rect = el.getBoundingClientRect();
    if (rect.width <= 1 || rect.height <= 1) return false;
    if (rect.bottom < 0 || rect.right < 0 || rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
    let node = el;
    while (node && node.nodeType === 1) {
      const style = window.getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity || 1) <= 0.01) return false;
      node = node.parentElement;
    }
    const style = window.getComputedStyle(el);
    if (style.pointerEvents === 'none') return false;
    const cx = Math.max(0, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
    const cy = Math.max(0, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));
    const top = document.elementFromPoint(cx, cy);
    return !top || top === el || el.contains(top) || top.contains(el);
  };
  const selectorFor = el => {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) return `#${CSS.escape(el.id)}`;
    const testId = el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-cy');
    if (testId) return `[data-testid="${quoteAttr(testId)}"], [data-test="${quoteAttr(testId)}"], [data-cy="${quoteAttr(testId)}"]`;
    const aria = el.getAttribute('aria-label');
    if (aria) return `[aria-label="${quoteAttr(aria)}"]`;
    const name = el.getAttribute('name');
    if (name) return `${el.tagName.toLowerCase()}[name="${quoteAttr(name)}"]`;
    const path = [];
    let node = el;
    while (node && node.nodeType === 1 && node.tagName.toLowerCase() !== 'html' && path.length < 6) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(child => child.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      path.unshift(part);
      node = parent;
    }
    return path.join(' > ');
  };
  document.querySelectorAll('[data-joyboy-browser-target]').forEach(el => el.removeAttribute('data-joyboy-browser-target'));
  const nodes = Array.from(document.querySelectorAll('a, button, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"]'));
  const visibleNodes = nodes
    .filter(visible)
    .slice(0, 90);
  visibleNodes.forEach((el, index) => el.setAttribute('data-joyboy-browser-target', String(index)));
  return visibleNodes.map((el, index) => {
      const rect = el.getBoundingClientRect();
      return {
        index,
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        text: String(el.innerText || el.textContent || el.value || '').trim().slice(0, 160),
        aria: String(el.getAttribute('aria-label') || '').trim().slice(0, 120),
        placeholder: String(el.getAttribute('placeholder') || '').trim().slice(0, 120),
        href: String(el.href || '').trim().slice(0, 240),
        selector: `[data-joyboy-browser-target="${index}"]`,
        fallback_selector: selectorFor(el),
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
    });
}
"""
    try:
        targets = page.evaluate(script)
    except Exception:
        return []
    if not isinstance(targets, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in targets:
        if isinstance(item, dict):
            cleaned.append(item)
    return cleaned


def _browser_agent_decision(
    *,
    task: str,
    model: str | None,
    step: int,
    page: Any,
    page_text: str,
    targets: list[dict[str, Any]],
    suggested_url: str,
    previous_steps: list[str],
) -> BrowserAgentDecision | None:
    try:
        from core.ai.text_model_router import call_text_model_structured
    except Exception as exc:
        print(f"[BROWSER_USE] Agent model unavailable: {exc}")
        return None

    compact_targets = [
        {
            "index": target.get("index"),
            "tag": target.get("tag"),
            "role": target.get("role"),
            "text": target.get("text"),
            "aria": target.get("aria"),
            "placeholder": target.get("placeholder"),
            "href": target.get("href"),
        }
        for target in targets[:60]
    ]
    system_prompt = (
        "You are JoyBoy Browser Use, a local browser-control agent. "
        "Understand the user's natural-language browser request and choose the next browser action. "
        "Do not blindly turn the full user request into a web search. "
        "If the user names a website or app, infer the normal destination yourself and open it. "
        "If the page has a relevant search/address/input field, use the visible target indexes. "
        "Prefer direct navigation, clicks, typing, scrolling, and finishing with a short status. "
        "Avoid unsafe actions, payments, logins, account changes, or entering secrets. "
        "Return only one JSON object matching the schema."
    )
    user_prompt = {
        "task": task,
        "step": step,
        "current_url": getattr(page, "url", ""),
        "current_title": page.title() if hasattr(page, "title") else "",
        "suggested_start_url_from_ui": suggested_url,
        "previous_steps": previous_steps[-8:],
        "visible_targets": compact_targets,
        "page_text": page_text,
        "allowed_actions": {
            "open_url": {"url": "explicit URL inferred by the model, not a search query"},
            "click_target": {"target": "visible_targets index"},
            "click_text": {"text": "visible text to click when no target index is suitable"},
            "type_text": {"target": "optional visible_targets index", "text": "text to type or fill"},
            "press_key": {"key": "Enter, Escape, Tab, etc."},
            "scroll": {"scroll_y": "positive or negative pixels"},
            "wait": {},
            "finish": {"answer": "short user-facing status"},
        },
    }
    decision = call_text_model_structured(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
        schema_model=BrowserAgentDecision,
        purpose="browser",
        model=model or None,
        num_predict=260,
        temperature=0.05,
        timeout=45,
    )
    if not decision:
        return None
    try:
        return BrowserAgentDecision.model_validate(decision)
    except Exception:
        return None


def _target_by_index(targets: list[dict[str, Any]], index: Any) -> dict[str, Any] | None:
    try:
        wanted = int(index)
    except Exception:
        return None
    for target in targets:
        try:
            if int(target.get("index")) == wanted:
                return target
        except Exception:
            continue
    return None


def _click_browser_target(page: Any, target: dict[str, Any]) -> dict[str, float] | None:
    selector = str(target.get("selector") or "").strip()
    if selector:
        cursor = _click_browser_locator(page, page.locator(selector).first, target)
        if cursor:
            return cursor
    text = str(target.get("text") or target.get("aria") or target.get("placeholder") or "").strip()
    if text:
        cursor = _click_browser_locator(page, page.get_by_text(text, exact=False).first, target)
        if cursor:
            return cursor
    x = float(target.get("x") or 0) + float(target.get("width") or 0) / 2
    y = float(target.get("y") or 0) + float(target.get("height") or 0) / 2
    page.mouse.move(x, y, steps=12)
    page.mouse.click(x, y)
    return {"x": x, "y": y}


def _click_browser_locator(page: Any, locator: Any, target: dict[str, Any] | None = None) -> dict[str, float] | None:
    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except Exception:
        pass

    try:
        if locator.is_visible(timeout=1200):
            box = locator.bounding_box(timeout=2500)
            if box:
                x = float(box["x"]) + float(box["width"]) / 2
                y = float(box["y"]) + float(box["height"]) / 2
                page.mouse.move(x, y, steps=14)
                page.mouse.click(x, y)
                return {"x": x, "y": y}
    except Exception:
        pass

    try:
        locator.click(timeout=2500)
        if target:
            return {
                "x": float(target.get("x") or 0) + float(target.get("width") or 0) / 2,
                "y": float(target.get("y") or 0) + float(target.get("height") or 0) / 2,
            }
        return None
    except Exception:
        pass

    if target:
        x = float(target.get("x") or 0) + float(target.get("width") or 0) / 2
        y = float(target.get("y") or 0) + float(target.get("height") or 0) / 2
        try:
            page.mouse.move(x, y, steps=14)
            page.mouse.click(x, y)
            return {"x": x, "y": y}
        except Exception:
            pass

    try:
        locator.evaluate("(el) => el.click()", timeout=2000)
        return None
    except Exception:
        return None


def _find_visible_text_target(targets: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    needle = str(text or "").strip().lower()
    if not needle:
        return None
    for target in targets:
        haystack = " ".join(
            str(target.get(key) or "")
            for key in ("text", "aria", "placeholder", "href")
        ).lower()
        if needle in haystack or haystack in needle:
            return target
    return None


def _execute_browser_agent_decision(
    page: Any,
    decision: BrowserAgentDecision,
    targets: list[dict[str, Any]],
) -> tuple[str, dict[str, float] | None]:
    action = str(decision.action or "").strip().lower().replace("-", "_")
    if action in {"open", "navigate", "go_to", "goto"}:
        action = "open_url"
    elif action in {"click", "tap"}:
        action = "click_target" if decision.target is not None else "click_text"
    elif action in {"type", "fill", "input"}:
        action = "type_text"
    elif action in {"press", "key"}:
        action = "press_key"

    if action == "open_url":
        url = normalize_direct_browser_url(decision.url)
        if not url or url == "about:blank" or (" " in url and "." not in url):
            raise RuntimeError("Le modèle navigateur n'a pas fourni d'URL explicite.")
        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        return f"open_url {url}", None

    if action == "click_target":
        target = _target_by_index(targets, decision.target)
        if not target:
            raise RuntimeError(f"Cible navigateur introuvable: {decision.target}")
        cursor = _click_browser_target(page, target)
        _try_load_wait(page, 4500)
        return f"click_target {decision.target}", cursor

    if action == "click_text":
        text = str(decision.text or "").strip()
        if not text:
            raise RuntimeError("Le modèle navigateur n'a pas fourni de texte à cliquer.")
        target = _find_visible_text_target(targets, text)
        if target:
            cursor = _click_browser_target(page, target)
        else:
            cursor = _click_browser_locator(page, page.get_by_text(text, exact=False).first)
        _try_load_wait(page, 4500)
        return f"click_text {text[:60]}", cursor

    if action == "type_text":
        text = str(decision.text or "")
        if not text:
            raise RuntimeError("Le modèle navigateur n'a pas fourni de texte à saisir.")
        target = _target_by_index(targets, decision.target)
        if target:
            selector = str(target.get("selector") or "").strip()
            if selector:
                locator = page.locator(selector).first
                try:
                    locator.fill(text, timeout=4500)
                except Exception:
                    locator.click(timeout=4500)
                    page.keyboard.type(text, delay=4)
            else:
                _click_browser_target(page, target)
                page.keyboard.type(text, delay=4)
        else:
            page.keyboard.type(text, delay=4)
        return f"type_text {text[:60]}", None

    if action == "press_key":
        key = str(decision.key or "Enter").strip() or "Enter"
        page.keyboard.press(key)
        _try_load_wait(page, 5000)
        return f"press_key {key}", None

    if action == "scroll":
        page.mouse.wheel(0, float(decision.scroll_y or 700))
        return f"scroll {decision.scroll_y or 700}", None

    if action == "wait":
        page.wait_for_timeout(700)
        return "wait", None

    if action == "finish":
        return "finish", None

    raise RuntimeError(f"Action navigateur inconnue: {decision.action}")


def _run_browser_agent_task(
    page: Any,
    task: str,
    payload: dict[str, Any],
    snapshot_fn: Any,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if not task:
        return snapshot_fn(page)

    model = str(payload.get("model") or payload.get("chat_model") or "").strip() or None
    suggested_url = str(payload.get("url") or "").strip()
    raw_max_steps = payload.get("max_steps")
    try:
        max_steps_value = int(raw_max_steps) if raw_max_steps not in (None, "", False) else 0
    except Exception:
        max_steps_value = 0
    max_steps = max(1, min(max_steps_value, 200)) if max_steps_value > 0 else None
    try:
        timeout_seconds = float(payload.get("timeout_seconds") or os.environ.get("JOYBOY_BROWSER_USE_TIMEOUT_SECONDS", "21600"))
    except Exception:
        timeout_seconds = 21600.0
    timeout_seconds = max(60.0, min(timeout_seconds, 21600.0))
    started_at = time.time()
    previous_steps: list[str] = []
    last_cursor: dict[str, float] | None = None

    step = 1
    while max_steps is None or step <= max_steps:
        if cancel_event and cancel_event.is_set():
            result = snapshot_fn(page, status="Navigation interrompue", progress=100, cursor=last_cursor)
            result.update({
                "answer": "Navigation interrompue, tu peux reprendre la main.",
                "cancelled": True,
                "agent_steps": previous_steps,
                "agent_model": model,
                "cursor": last_cursor,
            })
            return result

        if time.time() - started_at > timeout_seconds:
            result = snapshot_fn(page, status="Navigation mise en pause", progress=100, cursor=last_cursor)
            result.update({
                "answer": "J'ai mis la navigation en pause après un long run. Relance la demande pour continuer depuis cette page.",
                "paused_by_watchdog": True,
                "agent_steps": previous_steps,
                "agent_model": model,
                "cursor": last_cursor,
            })
            return result

        progress = min(92, 12 + int((step - 1) * (78 / max_steps))) if max_steps else min(92, 12 + step * 3)
        status_label = f"Analyse étape {step}/{max_steps}" if max_steps else f"Analyse étape {step}"
        try:
            snapshot_fn(
                page,
                progress=progress,
                status=status_label,
                detail="Lecture de la page et choix de la prochaine action...",
                agent_steps=previous_steps,
                cursor=last_cursor,
            )
        except Exception:
            pass
        targets = _extract_browser_targets(page)
        page_text = _read_browser_page_text(page)
        decision = _browser_agent_decision(
            task=task,
            model=model,
            step=step,
            page=page,
            page_text=page_text,
            targets=targets,
            suggested_url=suggested_url,
            previous_steps=previous_steps,
        )
        if decision is None:
            result = snapshot_fn(page)
            result.update({
                "success": False,
                "error": (
                    "Browser Use n'a pas réussi à obtenir une action claire du modèle. "
                    "Réessaie avec un modèle chat plus fiable ou une demande un peu plus précise."
                ),
                "agent_steps": previous_steps,
            })
            return result

        action = str(decision.action or "").strip().lower().replace("-", "_")
        print(
            f"[BROWSER_USE] Step {step}: action={action or 'unknown'} {_describe_browser_decision(decision)}",
            flush=True,
        )
        if cancel_event and cancel_event.is_set():
            result = snapshot_fn(page, status="Navigation interrompue", progress=100, cursor=last_cursor)
            result.update({
                "answer": "Navigation interrompue, tu peux reprendre la main.",
                "cancelled": True,
                "agent_steps": previous_steps,
                "agent_model": model,
                "cursor": last_cursor,
            })
            return result

        if action == "finish":
            print(
                f"[BROWSER_USE] Step {step}: finish {_truncate_browser_text(decision.answer or '', 220)}",
                flush=True,
            )
            result = snapshot_fn(page)
            result.update({
                "answer": decision.answer or "Action terminée.",
                "agent_steps": previous_steps,
                "agent_model": model,
                "cursor": last_cursor,
            })
            return result

        try:
            step_text, cursor = _execute_browser_agent_decision(page, decision, targets)
            previous_steps.append(step_text)
            print(f"[BROWSER_USE] Step {step}: done {step_text}", flush=True)
            if cursor:
                last_cursor = cursor
            try:
                snapshot_fn(
                    page,
                    progress=min(96, progress + (int(70 / max_steps) if max_steps else 3)),
                    status=step_text,
                    detail=step_text,
                    agent_steps=previous_steps,
                    cursor=last_cursor,
                )
            except Exception:
                pass
        except Exception as exc:
            print(f"[BROWSER_USE] Step {step}: error {exc}", flush=True)
            result = snapshot_fn(page)
            result.update({
                "success": False,
                "error": f"Browser Use bloqué: {exc}",
                "agent_steps": previous_steps,
                "agent_model": model,
                "cursor": last_cursor,
            })
            return result

        try:
            page.wait_for_timeout(120)
        except Exception:
            pass
        step += 1

    result = snapshot_fn(page)
    result.update({
        "answer": "J'ai avancé dans la navigation, mais la tâche demande encore une action.",
        "agent_steps": previous_steps,
        "agent_model": model,
        "cursor": last_cursor,
    })
    return result


_WORKER = BrowserUseWorker()
_INSTALLER = BrowserUseInstaller()


def run_browser_use_action(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    action_key = str(action or "").strip().lower()
    data = payload or {}
    if action_key == "task":
        try:
            timeout_seconds = float(data.get("timeout_seconds") or os.environ.get("JOYBOY_BROWSER_USE_TIMEOUT_SECONDS", "21600"))
        except Exception:
            timeout_seconds = 21600.0
        timeout = max(600.0, min(timeout_seconds + 60.0, 21660.0))
    else:
        timeout = 75.0
    return _WORKER.call(action, data, timeout=timeout)
