"""OpenAI Images API adapter. No subscription token is read or forwarded."""
from __future__ import annotations

import base64
from io import BytesIO
import os

from PIL import Image, ImageChops
import requests

from core.infra.local_config import get_provider_secret

DEFAULT_IMAGE_MODEL = "gpt-image-2.5-sunburst"


def png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def openai_mask(selection):
    """JoyBoy white=edit becomes OpenAI transparent=edit (explicit inversion)."""
    result = Image.new("RGBA", selection.size, "white")
    result.putalpha(ImageChops.invert(selection.convert("L")))
    return result


def request_image(prompt, original=None, selection=None):
    key = get_provider_secret("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY locally. Images API billing is separate from ChatGPT/Codex.")
    model = os.environ.get("JOYBOY_OPENAI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    params = {"model": model, "prompt": prompt, "n": 1,
              "quality": "low", "size": "auto", "output_format": "png"}
    headers = {"Authorization": f"Bearer {key}"}
    if original is not None:
        mask = png_bytes(openai_mask(selection))
        if len(mask) >= 4 * 1024 * 1024:
            raise ValueError("API mask must be smaller than 4 MiB")
        response = requests.post("https://api.openai.com/v1/images/edits", headers=headers,
            data=params, files={"image": ("source.png", png_bytes(original), "image/png"),
                               "mask": ("mask.png", mask, "image/png")}, timeout=(15, 240))
    else:
        response = requests.post("https://api.openai.com/v1/images/generations", headers=headers,
                                 json=params, timeout=(15, 240))
    if not response.ok:
        raise RuntimeError(f"OpenAI Images HTTP {response.status_code}; check API billing/model access")
    encoded = response.json().get("data", [{}])[0].get("b64_json")
    if not encoded:
        raise RuntimeError("OpenAI returned no base64 image")
    image = Image.open(BytesIO(base64.b64decode(encoded, validate=True))).convert("RGBA")
    return image, {"provider": "openai_api", "model": model,
                   "provider_size": list(image.size)}
