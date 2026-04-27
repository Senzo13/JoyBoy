"""Optional local Computer Use runtime.

This module keeps desktop control in the public core without requiring a
private pack.  It only activates on demand and uses local Python packages for
screen capture plus mouse/keyboard control.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Any


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _empty_install_state() -> dict[str, Any]:
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


_INSTALL_LOCK = threading.Lock()
_INSTALL_THREAD: threading.Thread | None = None
_INSTALL_STATE: dict[str, Any] = _empty_install_state()


def _status_without_install() -> dict[str, Any]:
    capture_ready = _module_available("PIL") or _module_available("mss")
    control_ready = _module_available("pyautogui")
    return {
        "success": True,
        "pyautogui_installed": control_ready,
        "pillow_installed": _module_available("PIL"),
        "mss_installed": _module_available("mss"),
        "usable": capture_ready and control_ready,
        "running": False,
        "url": "computer://desktop",
        "title": "Computer Use",
    }


def get_computer_use_status() -> dict[str, Any]:
    with _INSTALL_LOCK:
        install = dict(_INSTALL_STATE)
        install["logs"] = list(_INSTALL_STATE.get("logs") or [])[-40:]
    return {
        **_status_without_install(),
        "install": install,
    }


def _set_install(**updates: Any) -> None:
    with _INSTALL_LOCK:
        _INSTALL_STATE.update(updates)


def _append_install_log(line: str) -> None:
    clean = line.rstrip()
    if not clean:
        return
    with _INSTALL_LOCK:
        logs = list(_INSTALL_STATE.get("logs") or [])
        logs.append(clean[-600:])
        _INSTALL_STATE["logs"] = logs[-80:]


def _install_runtime_thread() -> None:
    try:
        commands: list[tuple[list[str], str, int, int]] = [
            ([sys.executable, "-m", "pip", "install", "pyautogui>=0.9.54", "pillow>=10", "mss>=9", "pyperclip>=1.8.2"], "Installation du runtime desktop", 5, 100),
        ]
        for command, step, start, end in commands:
            _set_install(step=step, detail=" ".join(command), progress=start)
            proc = subprocess.Popen(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                _append_install_log(line)
                lower = line.lower()
                if "collecting" in lower or "installing" in lower:
                    detail = "Installation des dépendances locales..."
                elif "requirement already satisfied" in lower:
                    detail = "Dépendances déjà présentes, vérification..."
                else:
                    detail = line.strip()[:140] or step
                current = int(get_computer_use_status().get("install", {}).get("progress") or start)
                _set_install(detail=detail, progress=min(end - 1, max(start, current + 2)))
            return_code = proc.wait()
            if return_code != 0:
                raise RuntimeError(f"Commande échouée ({return_code}): {' '.join(command)}")

        _set_install(
            active=False,
            complete=True,
            success=True,
            progress=100,
            step="Runtime Computer Use prêt",
            detail="Capture écran, souris et clavier sont disponibles.",
            error="",
            finished_at=time.time(),
        )
    except Exception as exc:  # pragma: no cover - depends on local package installer
        _append_install_log(str(exc))
        _set_install(
            active=False,
            complete=True,
            success=False,
            error=str(exc),
            detail=str(exc),
            finished_at=time.time(),
        )


def install_computer_use_runtime(background: bool = False) -> dict[str, Any]:
    global _INSTALL_THREAD
    if not background:
        packages = ["pyautogui>=0.9.54", "pillow>=10", "mss>=9", "pyperclip>=1.8.2"]
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", *packages],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if proc.returncode != 0:
            return {
                **get_computer_use_status(),
                "success": False,
                "error": "Commande échouée: pip install pyautogui pillow mss",
                "logs": proc.stdout[-8000:] if proc.stdout else "",
            }
        return get_computer_use_status()

    should_start = False
    with _INSTALL_LOCK:
        if _INSTALL_THREAD and _INSTALL_THREAD.is_alive():
            pass
        elif _status_without_install()["usable"]:
            _INSTALL_STATE.update({
                **_empty_install_state(),
                "complete": True,
                "success": True,
                "progress": 100,
                "step": "Runtime déjà installé",
                "detail": "Computer Use est disponible.",
                "finished_at": time.time(),
            })
        else:
            _INSTALL_STATE.update({
                **_empty_install_state(),
                "active": True,
                "progress": 2,
                "step": "Préparation du runtime desktop",
                "detail": "JoyBoy prépare capture écran, souris et clavier.",
                "started_at": time.time(),
            })
            _INSTALL_THREAD = threading.Thread(target=_install_runtime_thread, name="joyboy-computer-use-install", daemon=True)
            should_start = True
    if should_start and _INSTALL_THREAD:
        _INSTALL_THREAD.start()
    return get_computer_use_status()


def _require_pyautogui():
    try:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.04
        return pyautogui
    except Exception as exc:
        raise RuntimeError("Computer Use demande pyautogui. Installe le runtime depuis Extensions.") from exc


def _capture_screen() -> tuple[str, int, int]:
    try:
        from PIL import ImageGrab  # type: ignore

        image = ImageGrab.grab(all_screens=True)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"), int(image.width), int(image.height)
    except Exception:
        try:
            import mss  # type: ignore
            import mss.tools  # type: ignore

            with mss.mss() as screen:
                monitor = screen.monitors[0]
                shot = screen.grab(monitor)
                png = mss.tools.to_png(shot.rgb, shot.size)
                return "data:image/png;base64," + base64.b64encode(png).decode("ascii"), int(shot.width), int(shot.height)
        except Exception as exc:
            raise RuntimeError("Impossible de capturer l'écran local. Installe Pillow ou mss.") from exc


def _snapshot(status: str = "Computer Use prêt", detail: str = "", progress: int = 100) -> dict[str, Any]:
    screenshot, width, height = _capture_screen()
    cursor = None
    if _module_available("pyautogui"):
        try:
            pyautogui = _require_pyautogui()
            pos = pyautogui.position()
            cursor = {"x": int(pos.x), "y": int(pos.y)}
        except Exception:
            cursor = None
    return {
        "success": True,
        "url": "computer://desktop",
        "title": "Computer Use",
        "status": status,
        "detail": detail,
        "progress": progress,
        "screenshot": screenshot,
        "screenshot_width": width,
        "screenshot_height": height,
        "cursor": cursor,
        "agent_steps": [text for text in [status, detail] if text],
    }


def _error_response(message: str, status: str = "Computer Use indisponible") -> dict[str, Any]:
    return {
        **get_computer_use_status(),
        "success": False,
        "status": status,
        "detail": message,
        "error": message,
        "url": "computer://desktop",
        "title": "Computer Use",
        "agent_steps": [status, message],
    }


def _type_text(pyautogui: Any, text: str) -> None:
    if not text:
        return
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(text, interval=0.01)


def _extract_search_query(task: str) -> str:
    clean = re.sub(r"\s+", " ", task).strip()
    patterns = [
        r"(?:cherche|recherche|search|find)\s+(?:sur\s+)?(?:youtube|yt)\s+(.*)$",
        r"(?:sur\s+)?(?:youtube|yt)\s+(?:cherche|recherche|search|find)\s+(.*)$",
        r"(?:cherche|recherche|search|find)\s+(.*?)(?:\s+sur\s+(?:youtube|yt))?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" .,:;")
            query = re.sub(r"^(?:une?|des?|la|le|les)\s+", "", query, flags=re.IGNORECASE)
            if query:
                return query
    return clean


def _open_desktop_target_from_task(task: str) -> dict[str, Any] | None:
    lower = task.lower()
    wants_open = any(word in lower for word in ("ouvre", "ouvrir", "open", "lance", "launch", "go to", "va sur"))
    wants_browser = any(word in lower for word in ("navigateur", "browser", "chrome", "edge", "firefox"))
    wants_youtube = "youtube" in lower or re.search(r"\byt\b", lower) is not None
    wants_search = any(word in lower for word in ("cherche", "recherche", "search", "find"))
    if not (wants_open or wants_browser or wants_youtube):
        return None

    if wants_youtube:
        query = _extract_search_query(task) if wants_search else ""
        url = "https://www.youtube.com/"
        if query and query.lower() not in {"youtube", "yt"}:
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
        webbrowser.open(url, new=2, autoraise=True)
        time.sleep(0.8)
        return _snapshot("Navigateur système ouvert", f"YouTube: {query or 'accueil'}", 100)

    webbrowser.open("about:blank", new=2, autoraise=True)
    time.sleep(0.8)
    return _snapshot("Navigateur système ouvert", "Fenêtre navigateur demandée via Computer Use.", 100)


def run_computer_use_action(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        action_key = str(action or "screenshot").strip().lower()
        data = payload or {}

        if action_key in {"screenshot", "capture", "open", "reload", "back", "forward", "cancel"}:
            if not _status_without_install()["usable"]:
                return _error_response("Computer Use demande le runtime local pyautogui + Pillow/mss.")
            if action_key == "open":
                url = str(data.get("url") or "").strip()
                if url and not url.startswith("computer://"):
                    webbrowser.open(url, new=2, autoraise=True)
                    time.sleep(0.8)
                    return _snapshot("Navigateur système ouvert", url, 100)
            return _snapshot("Capture écran", "Aperçu desktop mis à jour.", 100)

        if not _status_without_install()["usable"]:
            return _error_response("Computer Use demande le runtime local pyautogui + Pillow/mss.")

        pyautogui = _require_pyautogui()

        if action_key == "click":
            x = int(float(data.get("x", 0)))
            y = int(float(data.get("y", 0)))
            button = str(data.get("button") or "left").lower()
            pyautogui.click(x=x, y=y, button=button)
            return _snapshot("Clic envoyé", f"{button} click à {x},{y}", 100)

        if action_key == "move":
            x = int(float(data.get("x", 0)))
            y = int(float(data.get("y", 0)))
            pyautogui.moveTo(x, y, duration=0.12)
            return _snapshot("Souris déplacée", f"Position {x},{y}", 100)

        if action_key == "scroll":
            delta = int(float(data.get("deltaY", data.get("amount", 0)) or 0))
            pyautogui.scroll(-max(-10, min(10, int(delta / 100) or (1 if delta < 0 else -1))))
            return _snapshot("Scroll envoyé", f"Delta {delta}", 100)

        if action_key == "type":
            text = str(data.get("text") or data.get("task") or "")
            _type_text(pyautogui, text)
            return _snapshot("Texte saisi", text[:120], 100)

        if action_key == "press":
            key = str(data.get("key") or "").strip()
            if key:
                pyautogui.press(key)
            return _snapshot("Touche envoyée", key, 100)

        if action_key == "task":
            task = str(data.get("task") or "").strip()
            lower = task.lower()
            opened = _open_desktop_target_from_task(task)
            if opened:
                return opened
            if lower.startswith(("type ", "write ", "tape ", "écris ", "ecris ")):
                text = task.split(" ", 1)[1].strip()
                if text:
                    _type_text(pyautogui, text)
                    return _snapshot("Texte saisi", text[:120], 100)
            if lower.startswith(("press ", "appuie ", "key ")):
                key = task.split(" ", 1)[1].strip().lower()
                if key:
                    aliases = {"entrée": "enter", "entree": "enter", "retour": "enter", "espace": "space", "suppr": "delete"}
                    pyautogui.press(aliases.get(key, key))
                    return _snapshot("Touche envoyée", aliases.get(key, key), 100)
            return _snapshot(
                "Computer Use manuel",
                task or "Clique dans la capture, utilise la molette, ou tape une commande simple.",
                100,
            )

        return _error_response(f"Action Computer Use inconnue: {action_key}", "Action inconnue")
    except Exception as exc:
        return _error_response(str(exc))
