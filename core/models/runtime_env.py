"""Runtime environment policy for model loading and placement.

Keep platform-specific Hugging Face and Diffusers switches in one place so
registry/model loaders do not grow scattered OS conditionals.
"""
from __future__ import annotations

import os
import platform
import types
from typing import MutableMapping


def resolve_huggingface_cache_paths(cache_dir: str) -> tuple[str, str]:
    """Return ``(HF_HOME, HF_HUB_CACHE)`` for JoyBoy's model cache root.

    ``HF_HOME`` is Hugging Face's root directory. The Hub cache that contains
    ``models--...`` folders normally lives one level below it in ``hub``.
    Some legacy JoyBoy calls still pass an explicit ``cache_dir`` themselves,
    but loaders that rely on environment defaults need the real hub path.
    """
    cache_root = os.path.abspath(os.path.expanduser(str(cache_dir)))
    if os.path.basename(cache_root).lower() == "hub":
        return os.path.dirname(cache_root), cache_root
    return cache_root, os.path.join(cache_root, "hub")


def get_huggingface_hub_cache_dir(cache_dir: str) -> str:
    """Return the concrete Hugging Face Hub cache path for ``cache_dir``."""
    return resolve_huggingface_cache_paths(cache_dir)[1]


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
    hf_home, hf_hub_cache = resolve_huggingface_cache_paths(cache_dir)
    os.makedirs(hf_home, exist_ok=True)
    os.makedirs(hf_hub_cache, exist_ok=True)
    env["HF_HOME"] = hf_home
    env["HF_HUB_CACHE"] = hf_hub_cache
    env["HUGGINGFACE_HUB_CACHE"] = hf_hub_cache
    env.setdefault("HF_ASSETS_CACHE", os.path.join(hf_home, "assets"))
    env["HF_HUB_DOWNLOAD_TIMEOUT"] = "600"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS"] = "1"
    env.setdefault("HF_TOKEN", hf_token or "")
    env["HF_ENABLE_PARALLEL_LOADING"] = (
        "YES" if should_enable_hf_parallel_loading(system_name) else "NO"
    )


def _env_flag(
    name: str,
    default: bool = False,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    env = environ if environ is not None else os.environ
    raw = env.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(
    name: str,
    default: float,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> float:
    env = environ if environ is not None else os.environ
    try:
        return float(env.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def get_segmentation_fusion_timeout_seconds(
    *,
    environ: MutableMapping[str, str] | None = None,
) -> float:
    """Maximum wait for B2/B4/SCHP fusion before using partial results."""
    timeout = _env_float(
        "JOYBOY_SEGMENTATION_FUSION_TIMEOUT",
        180.0,
        environ=environ,
    )
    return max(30.0, timeout)


def should_run_segmentation_on_cuda(
    vram_gb: float,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    """Return whether small segmentation models should use CUDA.

    On 8-10GB cards, running segmentation on CUDA while SDXL/ControlNet is being
    prepared can stall the whole request. CPU segmentation is slower, but it
    keeps low-VRAM installs moving predictably.
    """
    if vram_gb <= 0:
        return False
    if _env_flag("JOYBOY_SEGMENTATION_FORCE_CPU", False, environ=environ):
        return False
    if _env_flag("JOYBOY_SEGMENTATION_CUDA_LOW_VRAM", False, environ=environ):
        return True

    min_vram = _env_float(
        "JOYBOY_SEGMENTATION_CUDA_MIN_VRAM_GB",
        10.0,
        environ=environ,
    )
    return float(vram_gb) > min_vram


def get_parallel_image_preload_skip_reason(
    vram_gb: float,
    *,
    system_name: str | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> str | None:
    """Explain why image preload should not run beside routing/segmentation."""
    env = environ if environ is not None else os.environ
    if _env_flag("JOYBOY_DISABLE_PARALLEL_IMAGE_PRELOAD", False, environ=env):
        return "disabled by JOYBOY_DISABLE_PARALLEL_IMAGE_PRELOAD"

    current_system = system_name or platform.system()
    if current_system == "Darwin" and not _env_flag(
        "JOYBOY_ALLOW_PARALLEL_IMAGE_PRELOAD_MPS",
        False,
        environ=env,
    ):
        return "macOS/MPS uses shared memory"

    if float(vram_gb or 0) <= 0:
        return "no CUDA VRAM detected"

    if _env_flag("JOYBOY_ALLOW_PARALLEL_IMAGE_PRELOAD_LOW_VRAM", False, environ=env):
        return None

    threshold = _env_float(
        "JOYBOY_PARALLEL_IMAGE_PRELOAD_MIN_VRAM_GB",
        10.0,
        environ=env,
    )
    if 0 < float(vram_gb or 0) <= threshold:
        return f"low VRAM ({float(vram_gb):.1f}GB <= {threshold:.1f}GB)"

    return None


def get_image_preload_wait_timeout_seconds(
    *,
    environ: MutableMapping[str, str] | None = None,
) -> float:
    """Maximum wait for a background image preload before surfacing an error."""
    timeout = _env_float(
        "JOYBOY_IMAGE_PRELOAD_WAIT_TIMEOUT",
        120.0,
        environ=environ,
    )
    return max(30.0, timeout)


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
    enabled_any = _enable_mps_contiguous_vae_modules(pipe, label, log_skip=log_skip) or enabled_any
    enabled_any = _enable_mps_postprocess_nan_guard(pipe, label, log_skip=log_skip) or enabled_any
    enabled_any = _enable_mps_attention_upcast(pipe, label, log_skip=log_skip) or enabled_any

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
            target_device = _infer_mps_execution_device(self)
            kwargs = {"dtype": torch.float32}
            if target_device is not None:
                kwargs["device"] = target_device
            try:
                self.vae.to(**kwargs)
            except TypeError:
                if target_device is not None:
                    self.vae.to(target_device)
                self.vae.to(dtype=torch.float32)

        pipe.upcast_vae = types.MethodType(_joyboy_full_upcast_vae, pipe)
        setattr(pipe, "_joyboy_mps_full_vae_fp32_decode", True)
    except Exception as exc:
        if log_skip:
            print(f"[MM] {label}: full VAE fp32 decode skip ({exc})")
        return False

    print(f"[MM] {label}: full VAE fp32 decode active (MPS)")
    return True


def _enable_mps_contiguous_vae_modules(
    pipe: object,
    label: str,
    *,
    log_skip: bool = True,
) -> bool:
    """Make VAE tiled encode/decode inputs contiguous on MPS.

    Diffusers' VAE tiling slices tensors into views. On Apple MPS, conv2d can
    fail on those non-contiguous tile views with a stride/view RuntimeError.
    Keeping the module patch local avoids disabling VAE tiling globally.
    """
    vae = getattr(pipe, "vae", None)
    if vae is None:
        return False

    enabled = False
    for module_name in ("encoder", "decoder"):
        module = getattr(vae, module_name, None)
        if _patch_mps_contiguous_forward(module, label, f"VAE {module_name}"):
            enabled = True

    if not enabled and log_skip:
        print(f"[MM] {label}: VAE contiguous tile guard unavailable (MPS)")

    return enabled


def _patch_mps_contiguous_forward(module: object, label: str, module_label: str) -> bool:
    forward = getattr(module, "forward", None)
    if module is None or not callable(forward):
        return False

    if getattr(module, "_joyboy_mps_contiguous_forward", False):
        _log_once(
            module,
            "_joyboy_mps_contiguous_forward_logged",
            f"[MM] {label}: {module_label} contiguous tile guard active (MPS)",
        )
        return True

    try:
        import torch

        original_forward = forward

        def _joyboy_contiguous_forward(self, sample, *args, **kwargs):
            try:
                if torch.is_tensor(sample) and not sample.is_contiguous():
                    sample = sample.contiguous()
            except Exception:
                pass
            return original_forward(sample, *args, **kwargs)

        module.forward = types.MethodType(_joyboy_contiguous_forward, module)
        setattr(module, "_joyboy_mps_contiguous_forward", True)
    except Exception as exc:
        print(f"[MM] {label}: {module_label} contiguous tile guard skip ({exc})")
        return False

    print(f"[MM] {label}: {module_label} contiguous tile guard active (MPS)")
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


def _enable_mps_attention_upcast(
    pipe: object,
    label: str,
    *,
    log_skip: bool = True,
) -> bool:
    """Run SDXL attention score/softmax math in fp32 on MPS.

    The UNet can still denoise in fp16, but fp16 attention on Apple MPS can
    occasionally create non-finite latents. Diffusers attention modules expose
    the same stability switch used by SDXL UIs as "upcast cross attention".
    """
    changed = 0
    seen_any = False

    for component_name in ("unet", "controlnet"):
        component = getattr(pipe, component_name, None)
        if component is None:
            continue
        if getattr(component, "_joyboy_mps_attention_upcast", False):
            _log_once(
                component,
                "_joyboy_mps_attention_upcast_logged",
                f"[MM] {label}: attention upcast active (MPS)",
            )
            seen_any = True
            continue
        modules = getattr(component, "modules", None)
        if not callable(modules):
            continue
        component_changed = 0
        for module in modules():
            module_touched = False
            if hasattr(module, "upcast_attention"):
                seen_any = True
                if getattr(module, "upcast_attention", None) is not True:
                    setattr(module, "upcast_attention", True)
                    module_touched = True
            if hasattr(module, "upcast_softmax"):
                seen_any = True
                if getattr(module, "upcast_softmax", None) is not True:
                    setattr(module, "upcast_softmax", True)
                    module_touched = True
            if module_touched:
                component_changed += 1
        if component_changed:
            setattr(component, "_joyboy_mps_attention_upcast", True)
            changed += component_changed

    if changed:
        print(f"[MM] {label}: attention upcast active (MPS, {changed} modules)")
        return True

    if seen_any:
        return True

    if log_skip:
        print(f"[MM] {label}: attention upcast unavailable (MPS)")
    return False


def ensure_mps_sdxl_vae_ready_for_call(pipe: object, label: str = "pipeline") -> bool:
    """Keep SDXL VAE encode/decode on MPS fp32 before a Diffusers call.

    JoyBoy calls SDXL pipelines with ``output_type="latent"`` on macOS and
    decodes afterwards to avoid gray/NaN images. Inpaint pipelines still use the
    VAE inside ``prepare_latents`` to encode the source image. If a previous
    fallback left the VAE on CPU, Diffusers feeds it an MPS tensor and PyTorch
    raises "Input type (MPSFloatType) and weight type (torch.FloatTensor)".
    """
    import torch

    vae = getattr(pipe, "vae", None)
    if vae is None:
        return False

    target_device = _infer_mps_execution_device(pipe)
    if target_device is None:
        return False

    current_device = _module_device(vae)
    current_dtype = getattr(vae, "dtype", None)
    if (
        getattr(current_device, "type", None) == "mps"
        and current_dtype is torch.float32
    ):
        return False

    try:
        try:
            vae.to(device=target_device, dtype=torch.float32)
        except TypeError:
            vae.to(target_device)
            vae.to(dtype=torch.float32)
    except Exception as exc:
        print(f"[MM] {label}: VAE MPS fp32 align skip ({exc})")
        return False

    _log_once(vae, "_joyboy_mps_vae_call_align_logged", f"[MM] {label}: VAE aligned to MPS fp32 for inpaint encode")
    return True


def decode_sdxl_latents_with_mps_fallback(
    pipe: object,
    latents: object,
    label: str = "pipeline",
    *,
    output_type: str = "pil",
) -> object:
    """Decode SDXL latents in fp32 and fall back to CPU if MPS emits NaNs.

    This is intentionally used after calling Diffusers with ``output_type="latent"``.
    The previous postprocess NaN guard prevents crashes but cannot recover an
    image when the whole decoded tensor is NaN (it becomes a flat gray image).
    Decoding from verified finite latents lets JoyBoy retry just the fragile VAE
    step on CPU instead of rerunning the full diffusion process.
    """
    import torch

    if not torch.is_tensor(latents):
        return latents

    if not _tensor_is_finite(latents):
        raise RuntimeError(f"{label}: MPS diffusion produced non-finite latents")

    vae = getattr(pipe, "vae", None)
    image_processor = getattr(pipe, "image_processor", None)
    postprocess = getattr(image_processor, "postprocess", None)
    if vae is None or not callable(postprocess):
        raise RuntimeError(f"{label}: cannot decode SDXL latents without VAE image processor")

    original_dtype = getattr(vae, "dtype", None)
    original_device = _module_device(vae)
    decode_latents = _scale_sdxl_latents_for_vae(pipe, latents.detach().to(dtype=torch.float32))

    try:
        image = _decode_vae_on_device(vae, decode_latents, original_device)
        if not _tensor_is_finite(image):
            print(f"[MM] {label}: MPS VAE decode non-finite, retrying on CPU fp32")
            image = _decode_vae_on_device(vae, decode_latents, torch.device("cpu"))
            if not _tensor_is_finite(image):
                raise RuntimeError(f"{label}: CPU VAE decode also produced non-finite pixels")

        processed = image_processor.postprocess(image, output_type=output_type)
        if isinstance(processed, (list, tuple)):
            return processed[0]
        return processed
    finally:
        _restore_module_device_dtype(vae, original_device, original_dtype)


def _scale_sdxl_latents_for_vae(pipe: object, latents):
    import torch

    vae = getattr(pipe, "vae", None)
    config = getattr(vae, "config", None)
    scaling_factor = float(getattr(config, "scaling_factor", 1.0) or 1.0)
    has_latents_mean = hasattr(config, "latents_mean") and config.latents_mean is not None
    has_latents_std = hasattr(config, "latents_std") and config.latents_std is not None

    if has_latents_mean and has_latents_std:
        latents_mean = torch.tensor(config.latents_mean).view(1, 4, 1, 1).to(latents.device, latents.dtype)
        latents_std = torch.tensor(config.latents_std).view(1, 4, 1, 1).to(latents.device, latents.dtype)
        return latents * latents_std / scaling_factor + latents_mean

    return latents / scaling_factor


def _decode_vae_on_device(vae: object, latents, device):
    import torch

    target_device = device or latents.device
    with torch.no_grad():
        try:
            vae.to(device=target_device, dtype=torch.float32)
        except TypeError:
            vae.to(target_device)
            vae.to(dtype=torch.float32)
        return vae.decode(latents.to(device=target_device, dtype=torch.float32), return_dict=False)[0]


def _tensor_is_finite(value: object) -> bool:
    import torch

    try:
        return bool(torch.is_tensor(value) and torch.isfinite(value).all().item())
    except Exception:
        return False


def _module_device(module: object):
    try:
        first_param = next(module.parameters())
        return first_param.device
    except Exception:
        return None


def _infer_mps_execution_device(pipe: object):
    import torch

    for attr in ("_execution_device", "device"):
        device = getattr(pipe, attr, None)
        if getattr(device, "type", None) == "mps":
            return device
        if isinstance(device, str) and device == "mps":
            return torch.device("mps")

    for component_name in ("unet", "controlnet", "transformer", "text_encoder", "text_encoder_2"):
        component = getattr(pipe, component_name, None)
        device = _module_device(component) if component is not None else None
        if getattr(device, "type", None) == "mps":
            return device

    return None


def _restore_module_device_dtype(module: object, device, dtype) -> None:
    kwargs = {}
    if device is not None:
        kwargs["device"] = device
    if dtype is not None:
        kwargs["dtype"] = dtype
    if not kwargs:
        return
    try:
        module.to(**kwargs)
    except Exception:
        pass


def _log_once(target: object, flag_name: str, message: str) -> None:
    if getattr(target, flag_name, False):
        return
    print(message)
    try:
        setattr(target, flag_name, True)
    except Exception:
        pass
