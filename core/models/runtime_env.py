"""Runtime environment policy for model loading and placement.

Keep platform-specific Hugging Face and Diffusers switches in one place so
registry/model loaders do not grow scattered OS conditionals.
"""
from __future__ import annotations

import os
import platform
import types
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

    Apple Silicon generation is often limited by unified-memory pressure and
    SDXL VAE fp16 decode can emit NaN/inf pixels on MPS. Keep denoising fast in
    fp16, but ask Diffusers to upcast the VAE for final decode and enable
    attention slicing for JoyBoy's SDXL text2img/inpaint sizes.
    """
    enabled_any = _enable_mps_vae_force_upcast(pipe, label, log_skip=log_skip)
    enabled_any = _enable_mps_full_vae_fp32_decode(pipe, label, log_skip=log_skip) or enabled_any
    enabled_any = _enable_mps_postprocess_nan_guard(pipe, label, log_skip=log_skip) or enabled_any

    enable_attention_slicing = getattr(pipe, "enable_attention_slicing", None)
    if not callable(enable_attention_slicing):
        if log_skip:
            print(f"[MM] {label}: attention slicing unavailable (MPS)")
        return enabled_any

    try:
        enable_attention_slicing()
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: attention slicing skip ({exc})")
        return enabled_any

    print(f"[MM] {label}: attention slicing active (MPS)")
    return True


def _enable_mps_vae_force_upcast(
    pipe: object,
    label: str,
    *,
    log_skip: bool = True,
) -> bool:
    """Ask SDXL pipelines to decode the VAE in fp32 on MPS.

    Keeping the denoiser in fp16 is fast enough on Apple Silicon, but fp16 VAE
    decode can produce NaN/inf pixels on MPS. Diffusers' SDXL pipelines honor
    ``vae.config.force_upcast`` by temporarily upcasting the VAE for decode.
    """
    vae = getattr(pipe, "vae", None)
    if vae is None:
        return False

    config = getattr(vae, "config", None)
    if getattr(config, "force_upcast", False) is True:
        _log_once(pipe, "_joyboy_mps_force_upcast_logged", f"[MM] {label}: VAE force_upcast active (MPS)")
        return True

    try:
        register_to_config = getattr(vae, "register_to_config", None)
        if callable(register_to_config):
            register_to_config(force_upcast=True)
        elif config is not None:
            setattr(config, "force_upcast", True)
        else:
            if log_skip:
                print(f"[MM] {label}: VAE force_upcast unavailable (MPS)")
            return False
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: VAE force_upcast skip ({exc})")
        return False

    print(f"[MM] {label}: VAE force_upcast active (MPS)")
    return True


def _enable_mps_full_vae_fp32_decode(
    pipe: object,
    label: str,
    *,
    log_skip: bool = True,
) -> bool:
    """Patch Diffusers' SDXL VAE upcast to keep the whole VAE in fp32 on MPS.

    Diffusers' default ``upcast_vae`` may move attention-adjacent VAE modules
    back to fp16 when Torch 2 attention processors are available. That saves
    memory, but on Apple MPS those fp16 decode blocks can still emit NaN/inf
    pixels at final image postprocess. JoyBoy's Mac policy favors a slower but
    stable final decode.
    """
    vae = getattr(pipe, "vae", None)
    upcast_vae = getattr(pipe, "upcast_vae", None)
    if vae is None or not callable(upcast_vae):
        return False

    if getattr(pipe, "_joyboy_mps_full_vae_fp32_decode", False):
        _log_once(
            pipe,
            "_joyboy_mps_full_vae_fp32_decode_logged",
            f"[MM] {label}: full VAE fp32 decode active (MPS)",
        )
        return True

    try:
        import torch

        def _joyboy_full_upcast_vae(self) -> None:
            self.vae.to(dtype=torch.float32)

        pipe.upcast_vae = types.MethodType(_joyboy_full_upcast_vae, pipe)
        setattr(pipe, "_joyboy_mps_full_vae_fp32_decode", True)
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: full VAE fp32 decode skip ({exc})")
        return False

    print(f"[MM] {label}: full VAE fp32 decode active (MPS)")
    return True


def _enable_mps_postprocess_nan_guard(
    pipe: object,
    label: str,
    *,
    log_skip: bool = True,
) -> bool:
    """Clamp non-finite decoded pixels before Diffusers converts to uint8."""
    image_processor = getattr(pipe, "image_processor", None)
    postprocess = getattr(image_processor, "postprocess", None)
    if image_processor is None or not callable(postprocess):
        return False

    if getattr(image_processor, "_joyboy_mps_nan_guard", False):
        _log_once(
            image_processor,
            "_joyboy_mps_nan_guard_logged",
            f"[MM] {label}: decoded image NaN guard active (MPS)",
        )
        return True

    try:
        import torch

        original_postprocess = postprocess

        def _joyboy_guarded_postprocess(self, image, *args, **kwargs):
            try:
                if torch.is_tensor(image) and not bool(torch.isfinite(image).all().item()):
                    _log_once(
                        self,
                        "_joyboy_mps_nan_guard_triggered",
                        f"[MM] {label}: sanitized non-finite decoded pixels (MPS)",
                    )
                    image = torch.nan_to_num(image, nan=0.0, posinf=1.0, neginf=-1.0)
            except Exception:
                pass
            return original_postprocess(image, *args, **kwargs)

        image_processor.postprocess = types.MethodType(_joyboy_guarded_postprocess, image_processor)
        setattr(image_processor, "_joyboy_mps_nan_guard", True)
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: decoded image NaN guard skip ({exc})")
        return False

    print(f"[MM] {label}: decoded image NaN guard active (MPS)")
    return True


def _log_once(target: object, flag_name: str, message: str) -> None:
    if getattr(target, flag_name, False):
        return
    print(message)
    try:
        setattr(target, flag_name, True)
    except Exception:
        pass
