"""
Optional SDNQ backend for Diffusers-native image quantization.

This module keeps SDNQ support centralized so JoyBoy can:
- auto-register pre-quantized SDNQ Diffusers checkpoints when the package exists
- optionally prefer SDNQ post-load quantization over Quanto on supported loaders
- expose one place for feature detection, env parsing, and status reporting
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import threading
from typing import Any

import torch


_IMPORT_LOCK = threading.Lock()
_SDNQ_MODULE = None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_text(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_sdnq_enabled() -> bool:
    return _env_flag("JOYBOY_SDNQ_ENABLE", True)


def is_sdnq_postload_enabled() -> bool:
    return _env_flag("JOYBOY_SDNQ_POSTLOAD", True)


def is_sdnq_auto_install_enabled() -> bool:
    return _env_flag("JOYBOY_SDNQ_AUTO_INSTALL", False)


def is_sdnq_available() -> bool:
    return importlib.util.find_spec("sdnq") is not None


def ensure_sdnq_runtime(auto_install: bool | None = None) -> bool:
    """Ensure the optional SDNQ package is importable.

    Installation is opt-in because JoyBoy should stay predictable on first run.
    """
    if not is_sdnq_enabled():
        return False

    if is_sdnq_available():
        return True

    if auto_install is None:
        auto_install = is_sdnq_auto_install_enabled()
    if not auto_install:
        return False

    try:
        print("[SDNQ] Installation de sdnq...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "sdnq", "-q"],
            check=True,
        )
    except Exception as exc:
        print(f"[SDNQ] Installation impossible: {exc}")
        return False

    return is_sdnq_available()


def register_sdnq_for_diffusers(auto_install: bool | None = None) -> bool:
    """Import SDNQ once so Diffusers/Transformers can discover its quantizer."""
    global _SDNQ_MODULE

    if not is_sdnq_enabled():
        return False
    if _SDNQ_MODULE is not None:
        return True

    with _IMPORT_LOCK:
        if _SDNQ_MODULE is not None:
            return True
        if not ensure_sdnq_runtime(auto_install=auto_install):
            return False
        try:
            _SDNQ_MODULE = importlib.import_module("sdnq")
            getattr(_SDNQ_MODULE, "SDNQConfig", None)
            print("[SDNQ] Runtime enregistré pour Diffusers")
            return True
        except Exception as exc:
            print(f"[SDNQ] Import impossible: {exc}")
            _SDNQ_MODULE = None
            return False


def _resolve_weights_dtype(quant_type: str) -> str:
    override = _env_text("JOYBOY_SDNQ_WEIGHTS_DTYPE", "")
    if override:
        return override
    return "uint4" if str(quant_type or "").strip().lower() == "int4" else "int8"


def _resolve_use_svd(weights_dtype: str) -> bool:
    raw = _env_text("JOYBOY_SDNQ_USE_SVD", "auto").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return weights_dtype in {"int4", "uint4", "int3", "uint3", "int2", "uint2"}


def _resolve_use_quantized_matmul() -> bool:
    raw = _env_text("JOYBOY_SDNQ_USE_QUANTIZED_MATMUL", "auto").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    try:
        from sdnq.common import use_torch_compile

        return bool(use_torch_compile)
    except Exception:
        return False


def _resolve_use_quantized_matmul_conv(default: bool) -> bool:
    raw = _env_text("JOYBOY_SDNQ_USE_QUANTIZED_MATMUL_CONV", "auto").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def get_sdnq_postload_options(
    quant_type: str,
    *,
    quant_conv: bool = False,
    torch_dtype: torch.dtype | None = None,
) -> dict[str, Any]:
    """Return normalized SDNQ kwargs for post-load quantization."""
    weights_dtype = _resolve_weights_dtype(quant_type)
    use_quantized_matmul = _resolve_use_quantized_matmul()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return {
        "weights_dtype": weights_dtype,
        "torch_dtype": torch_dtype or (torch.bfloat16 if torch.cuda.is_available() else torch.float32),
        "group_size": _env_int("JOYBOY_SDNQ_GROUP_SIZE", 0),
        "svd_rank": _env_int("JOYBOY_SDNQ_SVD_RANK", 32),
        "svd_steps": _env_int("JOYBOY_SDNQ_SVD_STEPS", 8),
        "use_svd": _resolve_use_svd(weights_dtype),
        "quant_conv": bool(quant_conv or _env_flag("JOYBOY_SDNQ_QUANT_CONV", False)),
        "use_quantized_matmul": use_quantized_matmul,
        "use_quantized_matmul_conv": _resolve_use_quantized_matmul_conv(
            bool((quant_conv or _env_flag("JOYBOY_SDNQ_QUANT_CONV", False)) and use_quantized_matmul)
        ),
        "dequantize_fp32": _env_flag("JOYBOY_SDNQ_DEQUANTIZE_FP32", True),
        "quantization_device": device,
        "return_device": device,
    }


def _normalize_quant_method(value: object) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate or "").strip().lower()


def _extract_quantization_config(model: object) -> object:
    if model is None:
        return None
    direct = getattr(model, "quantization_config", None)
    if direct is not None:
        return direct
    config = getattr(model, "config", None)
    if config is None:
        return None
    nested = getattr(config, "quantization_config", None)
    if nested is not None:
        return nested
    if isinstance(config, dict):
        return config.get("quantization_config")
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter("quantization_config")
        except Exception:
            return None
    return None


def is_sdnq_quantized_model(model: object) -> bool:
    """Best-effort detection for pre-quantized SDNQ modules loaded by Diffusers."""
    if model is None:
        return False

    if _normalize_quant_method(getattr(model, "quantization_method", None)) == "sdnq":
        return True

    quant_config = _extract_quantization_config(model)
    if quant_config is None:
        return False

    if _normalize_quant_method(getattr(quant_config, "quant_method", None)) == "sdnq":
        return True
    if _normalize_quant_method(getattr(quant_config, "quantization_method", None)) == "sdnq":
        return True
    if isinstance(quant_config, dict):
        if _normalize_quant_method(quant_config.get("quant_method")) == "sdnq":
            return True
        if _normalize_quant_method(quant_config.get("quantization_method")) == "sdnq":
            return True
    return False


def apply_sdnq_post_load_quant(
    model: Any,
    *,
    quant_type: str,
    label: str,
    quant_conv: bool = False,
    torch_dtype: torch.dtype | None = None,
    auto_install: bool | None = None,
) -> tuple[Any, bool, str]:
    """Quantize a loaded Diffusers module with SDNQ when available."""
    if model is None:
        return model, False, "model-missing"
    if is_sdnq_quantized_model(model):
        return model, True, f"{label}: SDNQ pre-quantized"
    if not is_sdnq_enabled() or not is_sdnq_postload_enabled():
        return model, False, "sdnq-disabled"
    if not register_sdnq_for_diffusers(auto_install=auto_install):
        return model, False, "sdnq-unavailable"

    try:
        from sdnq import sdnq_post_load_quant
    except Exception as exc:
        print(f"[SDNQ] sdnq_post_load_quant indisponible: {exc}")
        return model, False, "sdnq-import-error"

    options = get_sdnq_postload_options(
        quant_type,
        quant_conv=quant_conv,
        torch_dtype=torch_dtype,
    )
    try:
        quantized_model = sdnq_post_load_quant(model, **options)
        descriptor = f"{options['weights_dtype']}{'+svd' if options['use_svd'] else ''}"
        print(f"[SDNQ] {label}: quantifié via SDNQ ({descriptor})")
        return quantized_model or model, True, f"{label}: SDNQ {descriptor}"
    except Exception as exc:
        print(f"[SDNQ] {label}: échec quantification SDNQ: {exc}")
        return model, False, "sdnq-postload-failed"


def get_sdnq_status() -> dict[str, Any]:
    weights_dtype = _resolve_weights_dtype("int4")
    return {
        "enabled": is_sdnq_enabled(),
        "postload_enabled": is_sdnq_postload_enabled(),
        "auto_install": is_sdnq_auto_install_enabled(),
        "available": is_sdnq_available(),
        "registered": _SDNQ_MODULE is not None,
        "weights_dtype_default_int4": weights_dtype,
        "use_svd_default_int4": _resolve_use_svd(weights_dtype),
        "supports_prequantized_diffusers": True,
        "install_hint": "pip install sdnq",
    }
