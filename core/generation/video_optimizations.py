"""
Video Generation Optimizations
- SageAttention: 2-5x faster than FlashAttention
- TorchAO FP8: Compatible with group offload (unlike quanto)
- Group offload + CUDA streams: 46% faster
"""

import torch
import subprocess
import sys
from functools import lru_cache

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform == 'linux'
IS_MAC = sys.platform == 'darwin'


# ============================================================================
# SAGE ATTENTION
# ============================================================================

@lru_cache(maxsize=1)
def is_sageattention_available():
    """Check if SageAttention is installed."""
    try:
        import sageattention
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def can_triton_compile():
    """Test if Triton can compile kernels (requires Python.h on Windows)."""
    try:
        import triton
        import triton.language as tl
        import torch

        # Définir un kernel triton minimal pour tester la compilation
        @triton.jit
        def _test_kernel(x_ptr, n_elements, BLOCK_SIZE: tl.constexpr):
            pid = tl.program_id(0)
            offsets = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
            mask = offsets < n_elements
            x = tl.load(x_ptr + offsets, mask=mask)
            tl.store(x_ptr + offsets, x, mask=mask)

        # Essayer de lancer le kernel (va compiler)
        x = torch.zeros(128, device='cuda')
        _test_kernel[(1,)](x, 128, BLOCK_SIZE=128)
        print("[OPT] Triton compilation OK")
        return True
    except Exception as e:
        error_str = str(e).lower()
        if "python.h" in error_str or "tcc.exe" in error_str or "compile" in error_str or "failed" in error_str:
            print(f"[OPT] Triton ne peut pas compiler: {e}")
            return False
        print(f"[OPT] Triton test error: {e}")
        return False


def install_sageattention():
    """
    Install SageAttention.
    - Windows: uses pre-built wheels + triton-windows
    - Linux: pip install sageattention (builds from source) + triton
    Returns True if successful.
    """
    if is_sageattention_available():
        print("[OPT] SageAttention déjà installé")
        return True

    print("[OPT] Installation de SageAttention...")

    try:
        # 1. Install triton (platform-specific)
        if IS_WINDOWS:
            print("[OPT]   → Installation triton-windows...")
            subprocess.run([sys.executable, '-m', 'pip', 'uninstall', 'triton', '-y'],
                          capture_output=True)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'triton-windows<3.7', '-q'],
                          check=True)
        elif IS_LINUX:
            print("[OPT]   → Installation triton...")
            subprocess.run([sys.executable, '-m', 'pip', 'uninstall', 'triton-windows', '-y'],
                          capture_output=True)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'triton', '-q'],
                          check=True)
        else:
            # Mac - triton not supported
            print("[OPT]   → Triton non supporté sur Mac, skip SageAttention")
            return False

        # 2. Detect PyTorch and CUDA version
        torch_version = torch.__version__.split('+')[0]  # e.g., "2.6.0"
        major_minor = '.'.join(torch_version.split('.')[:2])  # e.g., "2.6"

        # Get CUDA version
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda  # e.g., "12.6"
            cuda_major_minor = cuda_version.replace('.', '')[:3]  # e.g., "126"
        else:
            print("[OPT]   → CUDA non disponible, skip SageAttention")
            return False

        # Get Python version
        py_version = f"cp{sys.version_info.major}{sys.version_info.minor}"  # e.g., "cp312"

        # 3. Platform-specific installation
        if IS_WINDOWS:
            # Try to install from pre-built wheels (Windows only)
            # Wheel URL pattern: sageattention-{version}+cu{cuda}torch{torch}-{pyver}-{pyver}-win_amd64.whl
            wheel_urls = [
                # SageAttention 2.1.1 for various PyTorch versions
                f"https://github.com/woct0rdho/SageAttention/releases/download/v2.1.1-windows/sageattention-2.1.1+cu{cuda_major_minor}torch{major_minor}.0-{py_version}-{py_version}-win_amd64.whl",
                # Fallback: try without patch version
                f"https://github.com/woct0rdho/SageAttention/releases/download/v2.1.1-windows/sageattention-2.1.1+cu126torch2.6.0-{py_version}-{py_version}-win_amd64.whl",
            ]

            for url in wheel_urls:
                try:
                    print(f"[OPT]   → Tentative: {url.split('/')[-1]}")
                    result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'install', url, '-q'],
                        capture_output=True, text=True, timeout=120
                    )
                    if result.returncode == 0:
                        # Clear cache and verify
                        is_sageattention_available.cache_clear()
                        if is_sageattention_available():
                            print("[OPT]   → SageAttention installé avec succès!")
                            return True
                except Exception as e:
                    continue

        # 4. Fallback (or Linux primary): try pip install (builds from source on Linux)
        print("[OPT]   → Tentative pip install standard...")
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', 'sageattention', '--no-build-isolation', '-q'],
            capture_output=True, text=True, timeout=300
        )

        is_sageattention_available.cache_clear()
        if is_sageattention_available():
            print("[OPT]   → SageAttention installé avec succès!")
            return True

        if IS_WINDOWS:
            print("[OPT]   → Échec installation SageAttention (Visual Studio Build Tools peut être requis)")
        else:
            print("[OPT]   → Échec installation SageAttention (build from source failed)")
        return False

    except Exception as e:
        print(f"[OPT]   → Erreur installation SageAttention: {e}")
        return False


def apply_sageattention(pipe, model_type="auto"):
    """
    Apply SageAttention to a diffusers pipeline.

    Args:
        pipe: Diffusers pipeline with a transformer
        model_type: "wan", "ltx", "hunyuan", "cogvideo", or "auto"

    Returns:
        True if successfully applied
    """
    if not is_sageattention_available():
        print("[OPT] SageAttention non disponible")
        return False

    # SageAttention nécessite Triton qui doit pouvoir compiler
    if not can_triton_compile():
        print("[OPT] SageAttention désactivé: Triton ne peut pas compiler (Python.h manquant)")
        return False

    transformer = getattr(pipe, 'transformer', None)
    if transformer is None:
        print("[OPT] Pas de transformer trouvé dans le pipeline")
        return False

    # Determine best backend based on model and GPU
    if model_type == "auto":
        model_type = _detect_model_type(pipe)

    # Method 1: Try diffusers native backend (0.32+)
    if hasattr(transformer, 'set_attention_backend'):
        # Try CUDA kernel first (no Triton compilation needed on Windows)
        # "sage" peut utiliser Triton en arrière-plan ce qui nécessite Python.h
        backends_to_try = ["_sage_qk_int8_pv_fp16_cuda", "sage", "_sage_qk_int8_pv_fp16_triton"]
        for backend in backends_to_try:
            try:
                transformer.set_attention_backend(backend)
                print(f"[OPT] SageAttention activé: {backend}")
                return True
            except Exception as e:
                continue

    # Method 2: Global monkey-patch (fallback)
    print("[OPT] Fallback: monkey-patch global SageAttention...")
    try:
        import torch.nn.functional as F
        from sageattention import sageattn

        # Store original for potential reset
        if not hasattr(F, '_original_sdpa'):
            F._original_sdpa = F.scaled_dot_product_attention

        # Wrapper to handle incompatible arguments
        def sage_sdpa_wrapper(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None, **kwargs):
            # SageAttention doesn't support attn_mask, dropout, or extra kwargs (enable_gqa, etc.)
            if attn_mask is not None or dropout_p > 0 or kwargs:
                return F._original_sdpa(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal, scale=scale, **kwargs)
            try:
                # SageAttention requires headdim in [64, 96, 128]
                headdim = query.shape[-1]
                if headdim not in [64, 96, 128]:
                    return F._original_sdpa(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal, scale=scale, **kwargs)
                return sageattn(query, key, value, is_causal=is_causal, tensor_layout="HND")
            except Exception:
                # Fallback if sageattn fails
                return F._original_sdpa(query, key, value, attn_mask=attn_mask, dropout_p=dropout_p, is_causal=is_causal, scale=scale, **kwargs)

        F.scaled_dot_product_attention = sage_sdpa_wrapper
        print("[OPT] SageAttention activé (monkey-patch global)")
        return True
    except Exception as e:
        print(f"[OPT] Erreur activation SageAttention: {e}")
        return False


def reset_sageattention(pipe):
    """Reset attention backend to default."""
    transformer = getattr(pipe, 'transformer', None)
    if transformer and hasattr(transformer, 'reset_attention_backend'):
        transformer.reset_attention_backend()
        print("[OPT] Attention backend réinitialisé")


def reset_global_sageattention():
    """Reset global SDPA monkey-patch to original PyTorch implementation."""
    import torch.nn.functional as F
    if hasattr(F, '_original_sdpa'):
        F.scaled_dot_product_attention = F._original_sdpa
        print("[OPT] SageAttention global désactivé → SDPA original restauré")
        return True
    return False


def _detect_model_type(pipe):
    """Detect model type from pipeline class name."""
    class_name = pipe.__class__.__name__.lower()
    if 'wan' in class_name:
        return 'wan'
    elif 'ltx' in class_name:
        return 'ltx'
    elif 'hunyuan' in class_name:
        return 'hunyuan'
    elif 'cogvideo' in class_name:
        return 'cogvideo'
    return 'auto'


def apply_sageattention_unet(pipe):
    """
    Apply SageAttention to a UNet-based pipeline (SDXL, SD 1.5).

    For image models, we use the global monkey-patch method since UNet
    doesn't have set_attention_backend like transformers.

    Returns True if successful.
    """
    if not is_sageattention_available():
        print("[OPT] SageAttention non disponible pour UNet")
        return False

    unet = getattr(pipe, 'unet', None)
    if unet is None:
        print("[OPT] Pas de UNet trouvé dans le pipeline")
        return False

    try:
        # Method 1: Try set_attention_backend if available (newer diffusers)
        if hasattr(unet, 'set_attention_backend'):
            unet.set_attention_backend("_sage_qk_int8_pv_fp16_cuda")
            print("[OPT] SageAttention UNet activé (backend)")
            return True

        # Method 2: Global monkey-patch for older diffusers
        import torch.nn.functional as F
        from sageattention import sageattn

        # Store original for potential reset
        if not hasattr(F, '_original_sdpa'):
            F._original_sdpa = F.scaled_dot_product_attention

        # Wrapper to handle incompatible arguments
        def sage_sdpa_wrapper(query, key, value, attn_mask=None, dropout_p=0.0, is_causal=False, scale=None):
            # SageAttention doesn't support attn_mask or dropout
            if attn_mask is not None or dropout_p > 0:
                return F._original_sdpa(query, key, value, attn_mask, dropout_p, is_causal, scale)
            return sageattn(query, key, value, is_causal=is_causal, tensor_layout="HND")

        F.scaled_dot_product_attention = sage_sdpa_wrapper
        print("[OPT] SageAttention UNet activé (monkey-patch)")
        return True

    except Exception as e:
        print(f"[OPT] Erreur activation SageAttention UNet: {e}")
        return False


def reset_sageattention_unet():
    """Reset UNet attention to default."""
    import torch.nn.functional as F
    if hasattr(F, '_original_sdpa'):
        F.scaled_dot_product_attention = F._original_sdpa
        print("[OPT] SageAttention UNet réinitialisé")


# ============================================================================
# TORCHAO FP8 QUANTIZATION
# ============================================================================

@lru_cache(maxsize=1)
def is_torchao_available():
    """Check if TorchAO is installed."""
    try:
        import torchao
        return True
    except ImportError:
        return False


def install_torchao():
    """Install TorchAO."""
    if is_torchao_available():
        print("[OPT] TorchAO déjà installé")
        return True

    print("[OPT] Installation de TorchAO...")
    try:
        # Get CUDA version for correct wheel
        if torch.cuda.is_available():
            cuda_version = torch.version.cuda
            cuda_major = cuda_version.split('.')[0]
            if int(cuda_major) >= 12:
                index_url = "https://download.pytorch.org/whl/cu126"
            else:
                index_url = "https://download.pytorch.org/whl/cu118"
        else:
            index_url = None

        cmd = [sys.executable, '-m', 'pip', 'install', 'torchao', '-q']
        if index_url:
            cmd.extend(['--index-url', index_url])

        subprocess.run(cmd, check=True)
        is_torchao_available.cache_clear()

        if is_torchao_available():
            print("[OPT] TorchAO installé avec succès!")
            return True

    except Exception as e:
        print(f"[OPT] Erreur installation TorchAO: {e}")

    return False


def apply_fp8_quantization(model, method="layerwise"):
    """
    Apply FP8 quantization to a model.

    Args:
        model: PyTorch model (transformer, unet, etc.)
        method: "layerwise" (native diffusers) or "torchao"

    Returns:
        True if successful
    """
    if method == "layerwise":
        # Native diffusers method - no extra dependencies
        if hasattr(model, 'enable_layerwise_casting'):
            try:
                model.enable_layerwise_casting(
                    storage_dtype=torch.float8_e4m3fn,
                    compute_dtype=torch.bfloat16
                )
                print("[OPT] FP8 layerwise casting activé")
                return True
            except Exception as e:
                print(f"[OPT] Erreur FP8 layerwise: {e}")
                return False
        else:
            print("[OPT] enable_layerwise_casting non supporté")
            return False

    elif method == "torchao":
        if not is_torchao_available():
            if not install_torchao():
                return False

        try:
            from torchao.quantization import quantize_, float8_weight_only
            quantize_(model, float8_weight_only())
            print("[OPT] TorchAO FP8 weight-only quantization activé")
            return True
        except Exception as e:
            print(f"[OPT] Erreur TorchAO FP8: {e}")
            return False

    return False


# ============================================================================
# GROUP OFFLOAD + CUDA STREAMS
# ============================================================================

def apply_optimized_offload(pipe, vram_gb, model_type="auto"):
    """
    Apply optimized offloading strategy based on VRAM.

    Strategy:
    - 24GB+: GPU direct (no offload)
    - 12-24GB: Group offload with CUDA streams (fastest offload)
    - 8-12GB: Group offload with low_cpu_mem_usage
    - <8GB: model_cpu_offload fallback

    EXCEPTION: Pipelines with text encoders (Wan, LTX) use model_cpu_offload
    because group offload doesn't handle text_encoder embeddings (CPU/CUDA mismatch).

    Args:
        pipe: Diffusers pipeline
        vram_gb: Available VRAM in GB
        model_type: For model-specific optimizations
    """
    # Detect pipelines with text encoders incompatible with group offload
    pipe_class = type(pipe).__name__
    has_text_encoder_issue = any(x in pipe_class for x in [
        "Wan", "LTX", "Hunyuan", "CogVideo"  # All have T5/UMT5 text encoders
    ])

    # Detect MoE models (2 transformers) - need cpu_offload even on high-end GPUs
    is_moe = hasattr(pipe, 'transformer_2')

    # Detect large dense models (14B+) - also need cpu_offload on 40GB
    # Wan 2.1 14B: transformer ~28GB + text_encoder ~9GB = ~37GB (doesn't fit in 40GB with intermediates)
    is_large_dense = False
    param_count = 0
    transformer = getattr(pipe, 'transformer', None)
    if transformer and not is_moe:
        try:
            param_count = sum(p.numel() for p in transformer.parameters()) / 1e9
            is_large_dense = param_count > 10  # 10B+ = large model
        except Exception:
            pass

    if is_moe or is_large_dense:
        # MoE (14B×2 = 28GB+) or large dense (14B = 28GB) too big even for 40GB
        reason = "MoE 28GB+" if is_moe else f"dense {param_count:.0f}B"
        try:
            pipe.enable_model_cpu_offload()
            print(f"[OPT] model_cpu_offload ({reason} too big for GPU direct) ({vram_gb:.1f}GB VRAM)")
            return "model_cpu_offload"
        except Exception:
            pipe.enable_sequential_cpu_offload()
            print(f"[OPT] sequential_cpu_offload fallback ({vram_gb:.1f}GB VRAM)")
            return "sequential_cpu_offload"

    if has_text_encoder_issue and vram_gb < 24:
        # Force model_cpu_offload for text encoder pipelines
        # Group offload doesn't move text_encoder → CPU/CUDA mismatch on embeddings
        try:
            pipe.enable_model_cpu_offload()
            print(f"[OPT] model_cpu_offload (text_encoder fix) ({vram_gb:.1f}GB VRAM)")
            return "model_cpu_offload"
        except Exception:
            pipe.enable_sequential_cpu_offload()
            print(f"[OPT] sequential_cpu_offload fallback ({vram_gb:.1f}GB VRAM)")
            return "sequential_cpu_offload"

    if vram_gb >= 24:
        # GPU direct - no offload needed
        pipe.to("cuda")
        print(f"[OPT] GPU direct ({vram_gb:.1f}GB VRAM)")
        return "gpu_direct"

    transformer = getattr(pipe, 'transformer', None)
    vae = getattr(pipe, 'vae', None)

    if vram_gb >= 12:
        # Group offload with streams - best balance
        try:
            if transformer:
                transformer.enable_group_offload(
                    onload_device=torch.device("cuda"),
                    offload_device=torch.device("cpu"),
                    offload_type="leaf_level",
                    use_stream=True,
                    record_stream=True,
                    low_cpu_mem_usage=False  # Pre-pin for speed
                )
            if vae:
                vae.enable_group_offload(
                    onload_device=torch.device("cuda"),
                    offload_device=torch.device("cpu"),
                    offload_type="leaf_level",
                    use_stream=True
                )
            print(f"[OPT] Group offload + CUDA streams ({vram_gb:.1f}GB VRAM)")
            return "group_offload_streams"
        except Exception as e:
            print(f"[OPT] Group offload failed: {e}, fallback model_cpu_offload")

    elif vram_gb >= 8:
        # Group offload with low CPU mem - for RAM-constrained systems
        try:
            if transformer:
                transformer.enable_group_offload(
                    onload_device=torch.device("cuda"),
                    offload_device=torch.device("cpu"),
                    offload_type="leaf_level",
                    use_stream=True,
                    record_stream=True,
                    low_cpu_mem_usage=True  # Save CPU RAM
                )
            if vae:
                vae.enable_group_offload(
                    onload_device=torch.device("cuda"),
                    offload_device=torch.device("cpu"),
                    offload_type="leaf_level",
                    use_stream=True
                )
            print(f"[OPT] Group offload + low_cpu_mem ({vram_gb:.1f}GB VRAM)")
            return "group_offload_lowmem"
        except Exception as e:
            print(f"[OPT] Group offload failed: {e}, fallback model_cpu_offload")

    # Fallback: model_cpu_offload
    try:
        pipe.enable_model_cpu_offload()
        print(f"[OPT] model_cpu_offload fallback ({vram_gb:.1f}GB VRAM)")
        return "model_cpu_offload"
    except Exception:
        pipe.enable_sequential_cpu_offload()
        print(f"[OPT] sequential_cpu_offload fallback ({vram_gb:.1f}GB VRAM)")
        return "sequential_cpu_offload"


# ============================================================================
# COMBINED OPTIMIZATION
# ============================================================================

def optimize_video_pipeline(pipe, vram_gb, enable_sageattention=True, enable_fp8=True):
    """
    Apply all optimizations to a video pipeline.

    Args:
        pipe: Diffusers video pipeline
        vram_gb: Available VRAM
        enable_sageattention: Try to install/enable SageAttention
        enable_fp8: Apply FP8 quantization

    Returns:
        dict with optimization status
    """
    result = {
        "fp8": False,
        "sageattention": False,
        "offload_strategy": None,
        "high_end_mode": False
    }

    # High-end GPU mode (36GB+ réel, nominalement 40GB+): skip FP8, use native bf16
    # Note: A100 40GB reports ~39.4GB, A6000 48GB reports ~47GB
    is_high_end = vram_gb >= 36
    if is_high_end:
        print(f"[OPT] High-end GPU detected ({vram_gb:.0f}GB) - native bf16 mode")
        result["high_end_mode"] = True
        enable_fp8 = False  # Skip FP8, bf16 is fast enough on A100/H100

    # 1. FP8 quantization (before offload setup) - only for mid-range GPUs
    if enable_fp8 and not is_high_end:
        transformer = getattr(pipe, 'transformer', None)
        if transformer:
            result["fp8"] = apply_fp8_quantization(transformer, method="layerwise")

    # 2. Offload strategy
    result["offload_strategy"] = apply_optimized_offload(pipe, vram_gb)

    # 3. SageAttention (after model is on device) - always good, even on high-end
    if enable_sageattention:
        if is_sageattention_available() or install_sageattention():
            result["sageattention"] = apply_sageattention(pipe)

    # 4. High-end: ensure VAE is float32 for max quality (we have the VRAM)
    if is_high_end:
        try:
            vae = getattr(pipe, 'vae', None)
            if vae is not None:
                vae.to(dtype=torch.float32)
                print("[OPT] VAE float32 (high-end quality mode)")
        except Exception:
            pass  # Not critical, ignore

    return result
