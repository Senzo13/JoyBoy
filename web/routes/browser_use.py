"""Browser Use routes.

This is an optional local runtime.  The UI can install/use it on demand without
making browser automation part of the mandatory JoyBoy startup path.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request


browser_use_bp = Blueprint("browser_use", __name__)


@browser_use_bp.route("/api/browser-use/status", methods=["GET"])
def browser_use_status():
    from core.infra.browser_use_runtime import get_browser_use_status

    return jsonify(get_browser_use_status())


@browser_use_bp.route("/api/browser-use/install", methods=["POST"])
def browser_use_install():
    from core.infra.browser_use_runtime import install_browser_use_runtime

    data = request.get_json(silent=True) or {}
    include_agent = bool(data.get("include_agent") or data.get("includeAgent"))
    background = bool(data.get("background") or data.get("async_install") or data.get("async"))
    result = install_browser_use_runtime(include_agent=include_agent, background=background)
    return jsonify(result), (200 if result.get("success") else 500)


@browser_use_bp.route("/api/browser-use/action", methods=["POST"])
def browser_use_action():
    from core.infra.browser_use_runtime import run_browser_use_action

    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "screenshot").strip().lower()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    result = run_browser_use_action(action, payload)
    return jsonify(result), (200 if result.get("success") else 500)
