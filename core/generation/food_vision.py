"""Optional food/drink vision analyzer.

The public core keeps Florence as the cheap generic captioner. This module adds
a specialized VLM that is loaded only when an image or user request is clearly
about food/drinks.
"""

from __future__ import annotations

import ast
import gc
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from typing import Any


DEFAULT_MODEL_ID = "CreatorJarvis/FoodExtract-Vision-SmolVLM2-500M-fine-tune"
MODEL_ENV = "JOYBOY_FOODEXTRACT_MODEL"
INT8_ENV = "JOYBOY_FOODEXTRACT_INT8"
KEEP_LOADED_ENV = "JOYBOY_FOODEXTRACT_KEEP_LOADED"

FOODEXTRACT_PROMPT = """Classify the input image as food or not. If edible food or drink items are visible, extract them to lists.

Return only valid JSON in this shape:
{
  "is_food": 0,
  "image_title": "",
  "food_items": [],
  "drink_items": [],
  "count": 0
}
"""

FOOD_VISUAL_WORDS = {
    "food", "drink", "drinks", "beverage", "beverages", "meal", "dish", "plate",
    "bowl", "cup", "glass", "mug", "breakfast", "lunch", "dinner", "dessert",
    "cake", "cookie", "cookies", "bread", "pizza", "pasta", "burger", "sandwich",
    "salad", "soup", "rice", "noodle", "noodles", "ramen", "steak", "sushi",
    "fruit", "fruits", "vegetable", "vegetables", "coffee", "tea", "juice",
    "wine", "beer", "cocktail", "smoothie", "milk",
}

FOOD_REQUEST_WORDS = FOOD_VISUAL_WORDS | {
    "bouffe", "nourriture", "aliment", "aliments", "manger", "mangeable",
    "repas", "plat", "plats", "assiette", "boisson", "boissons", "verre",
    "tasse", "cafe", "the", "jus", "vin", "biere", "cocktail",
    "comida", "bebida", "bebidas", "plato", "platos", "vaso", "taza",
    "cibo", "bevanda", "bevande", "piatto", "piatti", "bicchiere", "tazza",
}

IMAGE_ANALYSIS_WORDS = {
    "analyse", "analyser", "analyses", "analyze", "analysez", "analysee",
    "describe", "decris", "decrire", "decrivez", "detect", "detecte", "detecter",
    "recognize", "reconnaitre", "reconnais", "identify", "identifie", "identifier",
    "quoi", "cest", "contenu", "contains", "contain",
    "contient", "caption", "legende", "legender", "explica", "analiza",
    "descrivi", "analizza",
}

_pipe: Any | None = None
_pipe_quantized = False
_last_load_error = ""
_lock = threading.Lock()
_cache: dict[str, "FoodExtractResult"] = {}
_CACHE_MAX = 64


@dataclass(frozen=True)
class FoodExtractResult:
    success: bool
    is_food: bool = False
    image_title: str = ""
    food_items: tuple[str, ...] = ()
    drink_items: tuple[str, ...] = ()
    count: int = 0
    raw_text: str = ""
    error: str = ""
    model_id: str = DEFAULT_MODEL_ID
    quantized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "is_food": self.is_food,
            "image_title": self.image_title,
            "food_items": list(self.food_items),
            "drink_items": list(self.drink_items),
            "count": self.count,
            "raw_text": self.raw_text,
            "error": self.error,
            "model_id": self.model_id,
            "quantized": self.quantized,
        }


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_model_id() -> str:
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID


def _norm(text: str | None) -> str:
    import unicodedata

    raw = unicodedata.normalize("NFKD", str(text or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return raw.lower()


def _words(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def is_image_analysis_request(message: str | None) -> bool:
    words = _words(message)
    if not words:
        return False
    if words & IMAGE_ANALYSIS_WORDS:
        return True
    text = _norm(message)
    return any(phrase in text for phrase in ("c est quoi", "c'est quoi", "what is this", "whats this"))


def should_run_foodextract(
    description: str | None = None,
    user_message: str | None = None,
    content_type: str | None = None,
) -> bool:
    if str(content_type or "").lower() == "food":
        return True

    desc_words = _words(description)
    if desc_words & FOOD_VISUAL_WORDS:
        return True

    user_words = _words(user_message)
    if user_words & FOOD_REQUEST_WORDS:
        return True

    return bool((user_words & IMAGE_ANALYSIS_WORDS) and (desc_words & FOOD_VISUAL_WORDS))


def _image_hash(image: Any) -> str:
    if image is None or not hasattr(image, "convert"):
        return ""
    sample = image.convert("RGB").resize((64, 64))
    payload = sample.tobytes() + f"{getattr(image, 'size', '')}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _preferred_dtype(device: str) -> Any | None:
    try:
        import torch

        if device == "cuda":
            if getattr(torch.cuda, "is_bf16_supported", lambda: False)():
                return torch.bfloat16
            return torch.float16
        return torch.float32
    except Exception:
        return None


def _build_pipeline(use_int8: bool) -> tuple[Any, bool]:
    from transformers import pipeline

    model_id = get_model_id()
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    device = "cpu"
    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        pass

    base_kwargs: dict[str, Any] = {
        "model": model_id,
        "device_map": "auto",
        "trust_remote_code": True,
    }
    if token:
        base_kwargs["token"] = token

    if use_int8 and device == "cuda":
        try:
            from transformers import BitsAndBytesConfig

            quantization_config = BitsAndBytesConfig(load_in_8bit=True)
            kwargs = dict(base_kwargs)
            kwargs["model_kwargs"] = {"quantization_config": quantization_config}
            return pipeline("image-text-to-text", **kwargs), True
        except Exception as exc:
            print(f"[FOODEXTRACT] INT8 unavailable, fallback precision: {exc}")

    dtype = _preferred_dtype(device)
    dtype_keys = ("dtype", "torch_dtype") if dtype is not None else (None,)
    last_error: Exception | None = None
    for dtype_key in dtype_keys:
        kwargs = dict(base_kwargs)
        if dtype_key:
            kwargs[dtype_key] = dtype
        try:
            return pipeline("image-text-to-text", **kwargs), False
        except TypeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("FoodExtract pipeline could not be created")


def load_foodextract() -> tuple[Any | None, bool]:
    global _pipe, _pipe_quantized, _last_load_error

    with _lock:
        if _pipe is not None:
            return _pipe, _pipe_quantized

        model_id = get_model_id()
        use_int8 = _env_flag(INT8_ENV, False)
        print(f"[FOODEXTRACT] Loading {model_id} ({'INT8 requested' if use_int8 else 'BF16/FP16'})...")
        try:
            _pipe, _pipe_quantized = _build_pipeline(use_int8)
            _last_load_error = ""
            print(f"[FOODEXTRACT] Ready ({'int8' if _pipe_quantized else 'native precision'})")
            return _pipe, _pipe_quantized
        except Exception as exc:
            _last_load_error = str(exc)
            print(f"[FOODEXTRACT] Load failed: {_last_load_error}")
            _pipe = None
            _pipe_quantized = False
            return None, False


def unload_foodextract() -> None:
    global _pipe, _pipe_quantized

    with _lock:
        if _pipe is None:
            return
        print("[FOODEXTRACT] Unloading...")
        del _pipe
        _pipe = None
        _pipe_quantized = False
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                chunks.append(str(item.get("text") or item.get("content") or ""))
            else:
                chunks.append(str(item))
        return "\n".join(chunk for chunk in chunks if chunk)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "")


def extract_generated_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        if not output:
            return ""
        if all(isinstance(item, str) for item in output):
            return "\n".join(output)
        # Chat-style generated_text often contains the full dialogue. Prefer the
        # last assistant message when available.
        for item in reversed(output):
            if isinstance(item, dict) and item.get("role") == "assistant":
                text = _extract_text_from_content(item.get("content"))
                if text:
                    return text
        for item in output:
            text = extract_generated_text(item)
            if text:
                return text
        return ""
    if isinstance(output, dict):
        for key in ("generated_text", "text", "content", "answer", "output"):
            if key in output:
                text = extract_generated_text(output[key])
                if text:
                    return text
    return str(output or "")


def _extract_json_object(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    quote = ""
    escape = False
    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            continue
        if ch in {"'", '"'}:
            in_string = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:idx + 1]
    return cleaned[start:]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "food"}


def _as_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r",|\n", value)]
        return tuple(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
        return tuple(items)
    text = str(value or "").strip()
    return (text,) if text else ()


def parse_foodextract_text(text: str, *, model_id: str | None = None, quantized: bool = False) -> FoodExtractResult:
    raw_text = str(text or "").strip()
    object_text = _extract_json_object(raw_text)
    if not object_text:
        return FoodExtractResult(
            success=False,
            raw_text=raw_text,
            error="No JSON object found",
            model_id=model_id or get_model_id(),
            quantized=quantized,
        )

    try:
        data = json.loads(object_text)
    except json.JSONDecodeError:
        try:
            data = ast.literal_eval(object_text)
        except Exception as exc:
            return FoodExtractResult(
                success=False,
                raw_text=raw_text,
                error=f"Invalid JSON: {exc}",
                model_id=model_id or get_model_id(),
                quantized=quantized,
            )

    if not isinstance(data, dict):
        return FoodExtractResult(
            success=False,
            raw_text=raw_text,
            error="JSON root is not an object",
            model_id=model_id or get_model_id(),
            quantized=quantized,
        )

    food_items = _as_items(data.get("food_items"))
    drink_items = _as_items(data.get("drink_items"))
    is_food = _as_bool(data.get("is_food")) or bool(food_items or drink_items)
    count_value = data.get("count")
    try:
        count = int(count_value)
    except (TypeError, ValueError):
        count = len(food_items) + len(drink_items)

    return FoodExtractResult(
        success=True,
        is_food=is_food,
        image_title=str(data.get("image_title") or "").strip(),
        food_items=food_items,
        drink_items=drink_items,
        count=count,
        raw_text=raw_text,
        model_id=model_id or get_model_id(),
        quantized=quantized,
    )


def _run_pipeline(pipe: Any, image: Any, *, max_new_tokens: int = 220) -> Any:
    message = [{
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": FOODEXTRACT_PROMPT},
        ],
    }]

    attempts = (
        lambda: pipe(message, max_new_tokens=max_new_tokens, do_sample=False),
        lambda: pipe(text=message, max_new_tokens=max_new_tokens, do_sample=False),
        lambda: pipe(images=image, text=FOODEXTRACT_PROMPT, max_new_tokens=max_new_tokens, do_sample=False),
    )
    last_error: Exception | None = None
    for call in attempts:
        try:
            return call()
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("FoodExtract pipeline call failed")


def analyze_food_image(image: Any, *, max_new_tokens: int = 220) -> FoodExtractResult:
    key = _image_hash(image)
    if key and key in _cache:
        print("[FOODEXTRACT] Cache hit")
        return _cache[key]

    pipe, quantized = load_foodextract()
    model_id = get_model_id()
    if pipe is None:
        return FoodExtractResult(
            success=False,
            error=_last_load_error or "FoodExtract model unavailable",
            model_id=model_id,
            quantized=quantized,
        )

    try:
        output = _run_pipeline(pipe, image, max_new_tokens=max_new_tokens)
        raw_text = extract_generated_text(output)
        result = parse_foodextract_text(raw_text, model_id=model_id, quantized=quantized)
    except Exception as exc:
        result = FoodExtractResult(
            success=False,
            error=str(exc),
            model_id=model_id,
            quantized=quantized,
        )
    finally:
        if not _env_flag(KEEP_LOADED_ENV, False):
            unload_foodextract()

    if key:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result


def enrich_food_description(description: str | None, result: FoodExtractResult | None) -> str:
    base = str(description or "").strip()
    if not result or not result.success or not result.is_food:
        return base

    details = []
    if result.image_title:
        details.append(f"food image title: {result.image_title}")
    if result.food_items:
        details.append("food items: " + ", ".join(result.food_items))
    if result.drink_items:
        details.append("drink items: " + ", ".join(result.drink_items))
    if not details:
        details.append("food or drink visible")

    suffix = "Food/drink analysis: " + "; ".join(details)
    return f"{base}. {suffix}" if base else suffix


def format_food_context(description: str | None, result: FoodExtractResult | None = None) -> str:
    lines = ["=== IMAGE CONTEXT ==="]
    if description:
        lines.append(f"Florence caption: {description}")

    if result and result.success:
        lines.append("Specialized food/drink analysis:")
        lines.append(f"- Food or drink detected: {'yes' if result.is_food else 'no'}")
        if result.image_title:
            lines.append(f"- Image title: {result.image_title}")
        if result.food_items:
            lines.append(f"- Food items: {', '.join(result.food_items)}")
        if result.drink_items:
            lines.append(f"- Drink items: {', '.join(result.drink_items)}")
        if result.count:
            lines.append(f"- Visible item count: {result.count}")
    elif result and result.error:
        lines.append(f"Specialized food/drink analysis unavailable: {result.error}")

    lines.append("Use this image context to answer the user. Do not claim certainty beyond what is visible.")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_MODEL_ID",
    "FoodExtractResult",
    "analyze_food_image",
    "enrich_food_description",
    "extract_generated_text",
    "format_food_context",
    "get_model_id",
    "is_image_analysis_request",
    "load_foodextract",
    "parse_foodextract_text",
    "should_run_foodextract",
    "unload_foodextract",
]
