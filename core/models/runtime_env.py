"""Runtime environment policy for model loading.

Keep platform-specific Hugging Face switches in one place so registry/model
loaders do not grow scattered OS conditionals.
"""
from __future__ import annotations

import os
import platform
from typing import MutableMapping


def should_enable_hf_parallel_loading(system_name: str | None = None) -> bool:
    """Return whether Hugging Face/Diffusers parallel loading is safe.

    Diffusers rejects parallel loading when components are loaded with
    low_cpu_mem_usage=False. JoyBoy deliberately uses low_cpu_mem_usage=False
    on macOS/MPS to avoid meta-tensor issues, so parallel loading must be off
    there while remaining enabled on Windows/Linux.
    """
    current_system = system_name or platform.system()
    return current_system != "Darwin"


def configure_huggingface_env(
    cache_dir: str,
    hf_token: str | None = None,
    *,
    system_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Configure Hugging Face runtime env vars for the current platform."""
    env = environ if environ is not None else os.environ
    env["HF_HOME"] = cache_dir
    env["HF_HUB_DOWNLOAD_TIMEOUT"] = "600"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS"] = "1"
    env.setdefault("HF_TOKEN", hf_token or "")
    env["HF_ENABLE_PARALLEL_LOADING"] = (
        "YES" if should_enable_hf_parallel_loading(system_name) else "NO"
    )


def apply_mps_pipeline_optimizations(
    pipe: object,
    label: str = "pipeline",
    *,
    log_skip: bool = True,
) -> bool:
    """Apply conservative Diffusers pipeline tweaks for macOS/MPS.

    Apple Silicon generation is often limited by unified-memory pressure. The
    Diffusers MPS guide recommends attention slicing for machines with less
    than 64GB RAM or larger-than-512px generations, which matches JoyBoy's SDXL
    text2img and inpaint use cases.
    """
    enable_attention_slicing = getattr(pipe, "enable_attention_slicing", None)
    if not callable(enable_attention_slicing):
        if log_skip:
            print(f"[MM] {label}: attention slicing unavailable (MPS)")
        return False

    try:
        enable_attention_slicing()
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: attention slicing skip ({exc})")
        return False

    print(f"[MM] {label}: attention slicing active (MPS)")
    return True
