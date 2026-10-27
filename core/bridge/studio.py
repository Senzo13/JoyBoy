"""Shared operations for the local UI and MCP. Immutable files live outside git."""
from __future__ import annotations

import json
from io import BytesIO
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from core.bridge.codex import CodexClient
from core.bridge.images import DEFAULT_IMAGE_MODEL, request_image
from core.generation.compositing import composite_with_original
from core.infra.local_config import get_provider_secret
from core.infra.paths import get_joyboy_home
from core.infra.packs import get_studio_feature_exposure_map

MAX_PIXELS = 16_000_000
MAX_FILE_BYTES = 40 * 1024 * 1024


def read_image(data):
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Image exceeds 40 MiB")
    with Image.open(BytesIO(data)) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError("Image exceeds 16 megapixels")
        return ImageOps.exif_transpose(source).convert("RGBA")


class Studio:
    def __init__(self, root=None, allowed_roots=(), codex_factory=CodexClient):
        self.root = Path(root or os.environ.get("JOYBOY_STUDIO_DIR") or
                         get_joyboy_home() / "studio").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allowed_roots = [self.root, *(Path(p).expanduser().resolve() for p in allowed_roots)]
        self.codex_factory = codex_factory
        self.lock = threading.RLock()

    def allowed_file(self, path):
        resolved = Path(path).expanduser().resolve()
        if not any(resolved.is_relative_to(p) for p in self.allowed_roots):
            raise ValueError("File is outside allowed roots; start MCP with --allow-root <folder>")
        if not resolved.is_file() or resolved.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("File missing or exceeds 40 MiB")
        return resolved

    def file(self, asset_id, suffix="png"):
        if not re.fullmatch(r"[a-f0-9]{32}", asset_id or ""):
            raise ValueError("Invalid asset ID")
        path = self.root / f"{asset_id}.{suffix}"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unknown asset")
        return path

    def inspect(self, asset_id):
        return json.loads(self.file(asset_id, "json").read_text(encoding="utf-8"))

    def image(self, asset_id, kind="image"):
        if self.inspect(asset_id)["kind"] != kind:
            raise ValueError(f"Expected {kind}")
        with Image.open(self.file(asset_id)) as image:
            return image.copy()

    def save(self, image, kind="image", **metadata):
        asset_id = uuid4().hex
        image_path = self.root / f"{asset_id}.png"
        image.save(image_path, format="PNG")
        record = {**metadata, "id": asset_id, "kind": kind, "width": image.width,
                  "height": image.height, "path": str(image_path)}
        temp = self.root / f"{asset_id}.json.tmp"
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.root / f"{asset_id}.json")
        return record

    def import_bytes(self, data, name="Image"):
        return self.save(read_image(data), name=Path(name).name)

    def import_image(self, path):
        source = self.allowed_file(path)
        return self.import_bytes(source.read_bytes(), source.name)

    def list_images(self):
        records = []
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if re.fullmatch(r"[a-f0-9]{32}", path.stem):
                record = self.inspect(path.stem)
                if record.get("kind") == "image":
                    records.append(record)
        return records[:100]

    def set_mask(self, asset_id, rectangles=None, mask_data=None):
        original = self.image(asset_id)
        if mask_data is not None:
            # Grayscale white=edit. Alpha is deliberately not inferred.
            mask = read_image(mask_data).convert("L")
            if mask.size != original.size:
                raise ValueError("Mask must match the original canvas exactly")
        else:
            mask = Image.new("L", original.size, 0)
            draw = ImageDraw.Draw(mask)
            for rect in rectangles or []:
                if len(rect) != 4 or any(type(v) is not int for v in rect):
                    raise ValueError("Rectangles are integer [x, y, width, height]")
                x, y, width, height = rect
                if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > original.width or y + height > original.height:
                    raise ValueError("Rectangle must fit inside the canvas")
                draw.rectangle((x, y, x + width - 1, y + height - 1), fill=255)
        if mask.getbbox() is None:
            raise ValueError("Select a nonempty edit region first")
        return self.save(mask, kind="mask", source_id=asset_id,
                         bounds=list(mask.getbbox()), convention="white=edit, black=protect")

    def selection(self, asset_id, mask_id):
        if self.inspect(mask_id).get("source_id") != asset_id:
            raise ValueError("Mask belongs to a different image revision")
        return self.image(mask_id, "mask")

    def apply_candidate(self, asset_id, mask_id, candidate_id, feather=0, **metadata):
        original = self.image(asset_id)
        candidate = self.image(candidate_id)
        mask = self.selection(asset_id, mask_id)
        if not 0 <= feather <= 64:
            raise ValueError("Feather must be between 0 and 64 pixels")
        result = composite_with_original(original, candidate, mask,
                                         feather_pixels=feather, color_match=False, strict=True)
        before, after = np.array(original), np.array(result)
        protected = np.array(mask) == 0
        changed = np.any(before != after, axis=-1)
        report = {"dimensions_preserved": result.size == original.size,
                  "protected_pixels": int(protected.sum()),
                  "protected_pixels_changed": int((changed & protected).sum()),
                  "selected_pixels_changed": int((changed & ~protected).sum())}
        if report["protected_pixels_changed"]:
            raise RuntimeError("Protected pixel verification failed")
        return self.save(result, name="Masked edit", parent_id=asset_id,
                         candidate_id=candidate_id, mask_id=mask_id,
                         feather=feather, verification=report, **metadata)

    def edit(self, asset_id, mask_id, prompt, feather=0):
        self.validate_prompt(prompt)
        original = self.image(asset_id)
        mask = self.selection(asset_id, mask_id)
        candidate, metadata = request_image(prompt, original, mask)
        # Only the generated layer may be resized. The source/mask never are.
        metadata["candidate_resized"] = candidate.size != original.size
        if metadata["candidate_resized"]:
            candidate = candidate.resize(original.size, Image.Resampling.LANCZOS)
        saved = self.save(candidate, name="OpenAI candidate", **metadata)
        return self.apply_candidate(asset_id, mask_id, saved["id"], feather,
                                    prompt=prompt, **metadata)

    def generate(self, prompt):
        self.validate_prompt(prompt)
        image, metadata = request_image(prompt)
        return self.save(image, name="OpenAI generation", prompt=prompt, **metadata)

    @staticmethod
    def validate_prompt(prompt):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32000:
            raise ValueError("Prompt must contain 1–32000 characters")

    def codex_call(self, callback):
        # A fresh process lets Codex manage its own auth/config lifecycle.
        client = self.codex_factory(self.root)
        try:
            return callback(client)
        finally:
            client.close()

    def status(self):
        try:
            codex = self.codex_call(lambda client: client.status())
        except (RuntimeError, OSError, TimeoutError):
            codex = {"available": False, "authenticated": False, "models": [],
                     "reason": "Codex unavailable; install CLI or set JOYBOY_CODEX_BIN"}
        image_ready = bool(get_provider_secret("OPENAI_API_KEY"))
        return {"codex": codex, "image_api": {"configured": image_ready,
                "model": os.environ.get("JOYBOY_OPENAI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
                "billing": "Separate OpenAI API billing"},
                "feature_exposure": get_studio_feature_exposure_map(
                    codex_authenticated=bool(codex.get("authenticated")),
                    image_api_configured=image_ready), "storage": str(self.root)}

    def chat(self, text, model=None, thread_id=None, image_ids=()):
        self.validate_prompt(text)
        paths = [self.file(image_id) for image_id in image_ids]
        # Resume only threads previously created through this workspace.
        if thread_id and (not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", thread_id) or
                          not (self.root / f"thread-{thread_id}").is_file()):
            raise ValueError("Unknown JoyBoy chat")
        result = self.codex_call(lambda client: client.chat(text, model, thread_id, paths))
        marker = self.root / f"thread-{result['thread_id']}"
        marker.touch()
        return result
