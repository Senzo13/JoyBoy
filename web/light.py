"""Minimal JoyBoy UI entrypoint: Flask + PIL + Codex, without GPU bootstrapping."""
from __future__ import annotations

import argparse
import base64
import secrets
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from core.bridge.studio import Studio, MAX_FILE_BYTES
from core.infra.paths import PROJECT_DIR


def create_app(studio=None):
    load_dotenv(PROJECT_DIR / ".env", override=False)
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(MAX_CONTENT_LENGTH=MAX_FILE_BYTES, STUDIO_TOKEN=secrets.token_urlsafe(32))
    studio = studio or Studio()

    @app.before_request
    def local_only():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
            abort(403)
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403)
        if request.path.startswith("/api/") and not secrets.compare_digest(
                request.headers.get("X-JoyBoy-Token", ""), app.config["STUDIO_TOKEN"]):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, ValueError):
            return jsonify(error=str(exc)), 400
        if isinstance(exc, (RuntimeError, TimeoutError)):
            return jsonify(error=str(exc)), 502
        app.logger.error("Studio operation failed: %s", type(exc).__name__)
        return jsonify(error="Operation failed; check the local server"), 500

    @app.get("/")
    def index():
        return render_template("light.html", token=app.config["STUDIO_TOKEN"])

    @app.get("/api/status")
    def status():
        return jsonify(studio.status())

    @app.get("/api/images")
    def images():
        return jsonify(studio.list_images())

    @app.get("/assets/<asset_id>.png")
    def image(asset_id):
        return send_file(studio.file(asset_id), mimetype="image/png")

    @app.post("/api/import")
    def upload():
        file = request.files["image"]
        return jsonify(studio.import_bytes(file.read(), file.filename))

    @app.post("/api/mask")
    def mask():
        body = request.get_json()
        data = body.get("mask")
        decoded = base64.b64decode(data.split(",", 1)[-1], validate=True) if data else None
        return jsonify(studio.set_mask(body["asset_id"], body.get("rectangles"), decoded))

    @app.post("/api/apply")
    def apply():
        return jsonify(studio.apply_candidate(**request.get_json()))

    @app.post("/api/edit")
    def edit():
        return jsonify(studio.edit(**request.get_json()))

    @app.post("/api/generate")
    def generate():
        return jsonify(studio.generate(**request.get_json()))

    @app.post("/api/chat")
    def chat():
        with studio.lock:
            return jsonify(studio.chat(**request.get_json()))

    return app


def main():
    parser = argparse.ArgumentParser(description="JoyBoy Light — local Codex/image studio")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env", override=False)
    create_app(Studio(args.data_dir)).run(host="127.0.0.1", port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
