"""Shared low-level helpers for ModelManager mixins."""

import gc
import sys
import os
import threading
import subprocess
import torch
import torch.nn as nn
from core.models import move_video_to_device, VRAM_GB, IS_HIGH_END_GPU, TORCH_DTYPE, DTYPE_NAME

# ── Save CLEAN register_parameter BEFORE accelerate/transformers monkey-patch it ──
# accelerate's init_empty_weights() patches nn.Module.register_parameter globally.
# With ThreadPoolExecutor, the patch leaks permanently (race condition on save/restore).
# This clean reference lets us restore it after parallel model loading.
_CLEAN_REGISTER_PARAMETER = nn.Module.register_parameter


def _restore_register_parameter():
    """Restore PyTorch's original register_parameter after parallel loading."""
    nn.Module.register_parameter = _CLEAN_REGISTER_PARAMETER


# ── Make init_empty_weights() THREAD-SAFE ──
# accelerate's init_empty_weights() saves/restores register_parameter in a
# context manager. With ThreadPoolExecutor, two threads can overlap:
#   Thread A: saves clean, patches to meta
#   Thread B: saves META (wrong!), patches to meta
#   Thread A: restores to clean (ok)
#   Thread B: restores to META (permanent leak!)
# Fix: wrap init_empty_weights in a threading lock so save/restore is atomic.
_init_weights_lock = threading.Lock()

def _patch_init_empty_weights():
    """Monkey-patch accelerate's init_empty_weights to be thread-safe."""
    try:
        import accelerate
        import accelerate.big_modeling
        from contextlib import contextmanager

        _original = accelerate.big_modeling.init_empty_weights

        @contextmanager
        def _safe_init_empty_weights(*args, **kwargs):
            with _init_weights_lock:
                with _original(*args, **kwargs):
                    yield

        # Patch accelerate
        accelerate.init_empty_weights = _safe_init_empty_weights
        accelerate.big_modeling.init_empty_weights = _safe_init_empty_weights

        # Patch diffusers' local reference (imported at module level)
        try:
            import diffusers.models.modeling_utils as _dmu
            if hasattr(_dmu, 'init_empty_weights'):
                _dmu.init_empty_weights = _safe_init_empty_weights
        except ImportError:
            pass

        # Patch transformers' local reference
        try:
            import transformers.modeling_utils as _tmu
            if hasattr(_tmu, 'init_empty_weights'):
                _tmu.init_empty_weights = _safe_init_empty_weights
        except ImportError:
            pass

        print("[MM] init_empty_weights patched (thread-safe)")
    except ImportError:
        pass

_patch_init_empty_weights()


def _publish_runtime_progress(phase: str, step: int = 0, total: int = 100, message: str = ""):
    """Best-effort progress visible from the generation card during model setup.

    First-run downloads often happen inside Hugging Face / Diffusers helpers. We
    cannot always get byte-level callbacks from those libraries, but publishing
    the current setup phase prevents the UI from looking frozen.
    """
    try:
        from core.generation.state import set_progress_phase

        set_progress_phase(phase, step=step, total=total, message=message)
    except Exception:
        pass


def _fix_meta_params(module, label=""):
    """Remplace les meta tensors (sans données) par des zéros sur CPU.

    from_single_file / from_pretrained avec low_cpu_mem_usage=True peut laisser
    des paramètres en meta device si certaines clés du checkpoint ne matchent pas.
    Ces meta tensors cassent LoRA loading, .to("cuda"), quanto freeze(), etc.
    """
    fixed = 0
    # Fix parameters — accès direct _parameters dict (plus fiable que setattr pour tied weights)
    for _, submod in module.named_modules():
        for pname, p in list(submod._parameters.items()):
            if p is not None and p.is_meta:
                submod._parameters[pname] = torch.nn.Parameter(
                    torch.zeros(p.shape, dtype=p.dtype, device="cpu"),
                    requires_grad=p.requires_grad
                )
                fixed += 1
        # Fix buffers
        for bname, b in list(submod._buffers.items()):
            if b is not None and b.is_meta:
                submod._buffers[bname] = torch.zeros(b.shape, dtype=b.dtype, device="cpu")
                fixed += 1
        # Fix direct tensor attributes (not registered as param/buffer)
        for attr_name in list(vars(submod).keys()):
            if attr_name.startswith('_'):
                continue
            val = getattr(submod, attr_name, None)
            if isinstance(val, torch.Tensor) and val.is_meta:
                setattr(submod, attr_name, torch.zeros(val.shape, dtype=val.dtype, device="cpu"))
                fixed += 1
    if fixed > 0:
        print(f"[MM] Fixed {fixed} meta tensors in {label or type(module).__name__}")
    return fixed


def _unpatch_register_parameter():
    """Context manager: restore original nn.Module.register_parameter.

    accelerate and transformers permanently monkey-patch register_parameter
    to intercept parameter creation (for meta tensors, device placement, etc).
    This breaks quanto's freeze() because WeightQBytesTensor doesn't support
    the kwargs that the monkey-patches pass to param_cls().

    Uses _CLEAN_REGISTER_PARAMETER saved at module load (before any patching).
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        _saved = nn.Module.register_parameter
        nn.Module.register_parameter = _CLEAN_REGISTER_PARAMETER
        try:
            yield
        finally:
            nn.Module.register_parameter = _saved

    return _ctx()


def _safe_quantize(model, weights):
    """Wrapper around quanto quantize() that handles meta tensors AND monkey-patched register_parameter.

    Two issues fixed:
    1. quanto's from_module() creates QModules on meta device — some PyTorch versions
       fail to materialize them properly.
    2. accelerate/transformers permanently monkey-patch nn.Module.register_parameter
       which breaks quanto's freeze() (WeightQBytesTensor incompatible with meta recreation).

    This wrapper temporarily restores clean register_parameter during quantize().
    """
    from optimum.quanto import quantize

    # Un-patch register_parameter to prevent accelerate/transformers interference
    with _unpatch_register_parameter():
        try:
            # First try: set default device to CPU and quantize normally
            try:
                torch.set_default_device("cpu")
            except (AttributeError, RuntimeError):
                pass

            try:
                quantize(model, weights=weights)
                return
            except NotImplementedError:
                pass  # Meta tensor error — fall through to patched approach
            finally:
                try:
                    torch.set_default_device(None)
                except (AttributeError, RuntimeError):
                    pass

            # Second try: monkey-patch from_module to fix meta tensors
            print("[MM] Quantification standard échouée (meta tensors), retry avec patch...")
            from optimum.quanto.nn.qmodule import QModuleMixin
            _original_from_module = QModuleMixin.from_module

            @classmethod
            def _patched_from_module(cls, module, weights=None, activations=None, optimizer=None):
                """from_module with meta tensor recovery."""
                qmodule = cls.qcreate(module, weights, activations, optimizer)
                if qmodule is None:
                    try:
                        qmodule = cls.qcreate(module, weights, activations, optimizer, device="meta")
                    except TypeError:
                        return None
                if qmodule is None:
                    return None

                # Force all meta tensors to CPU via to_empty
                try:
                    qmodule = qmodule.to_empty(device="cpu")
                except Exception:
                    pass

                # Fix any remaining meta params/buffers
                for _, submod in qmodule.named_modules():
                    for pname, p in list(submod._parameters.items()):
                        if p is not None and p.is_meta:
                            submod._parameters[pname] = torch.nn.Parameter(
                                torch.zeros(p.shape, dtype=p.dtype, device="cpu"),
                                requires_grad=p.requires_grad
                            )
                    for bname, b in list(submod._buffers.items()):
                        if b is not None and b.is_meta:
                            submod._buffers[bname] = torch.zeros(b.shape, dtype=b.dtype, device="cpu")

                # Copy real weights from original module
                with torch.no_grad():
                    if hasattr(module, 'weight') and module.weight is not None:
                        qmodule.weight = module.weight
                    if hasattr(module, 'bias') and module.bias is not None:
                        qmodule.bias = module.bias

                # Reinitialize scale buffers
                if hasattr(qmodule, 'input_scale') and qmodule.input_scale is not None:
                    qmodule.input_scale = torch.ones_like(qmodule.input_scale)
                if hasattr(qmodule, 'output_scale') and qmodule.output_scale is not None:
                    qmodule.output_scale = torch.ones_like(qmodule.output_scale)

                return qmodule

            QModuleMixin.from_module = _patched_from_module
            try:
                quantize(model, weights=weights)
                print("[MM] Quantification réussie avec patch meta tensor")
            finally:
                QModuleMixin.from_module = _original_from_module
        except Exception:
            raise


def _safe_freeze(model):
    """Wrapper around quanto freeze() with clean register_parameter."""
    from optimum.quanto import freeze
    with _unpatch_register_parameter():
        freeze(model)


def _materialize_module(module, label=""):
    """Force-materialize ALL tensors in a module from meta to CPU.

    Uses to_empty() + reload state dict — more aggressive than _fix_meta_params.
    Preserves real weights, replaces meta tensors with zeros.
    """
    has_meta = any(p.is_meta for _, p in module.named_parameters())
    has_meta = has_meta or any(b.is_meta for _, b in module.named_buffers())
    if not has_meta:
        return False

    print(f"[MM] Materializing {label}: to_empty + reload state dict...")
    try:
        # Save real (non-meta) tensors
        real_sd = {}
        for k, v in module.state_dict().items():
            if v.device.type != "meta":
                real_sd[k] = v

        # to_empty creates uninitialized tensors on CPU for ALL params
        module.to_empty(device="cpu")

        # Reload real weights (meta keys stay as uninitialized zeros)
        if real_sd:
            module.load_state_dict(real_sd, strict=False, assign=True)

        # Zero out any remaining uninitialized params
        _fix_meta_params(module, f"{label} (post-materialize)")
        print(f"[MM] {label}: materialized ({len(real_sd)} real weights preserved)")
        return True
    except Exception as e:
        print(f"[MM] {label}: materialize failed: {e}")
        _fix_meta_params(module, label)
        return False


_PIPE_COMPONENTS = ('unet', 'controlnet', 'vae', 'text_encoder', 'text_encoder_2', 'image_encoder')
CUDA_MOVE_ERRORS = (NotImplementedError, RuntimeError, AssertionError)


def _cuda_unavailable_message():
    return (
        "PyTorch est installé sans CUDA alors qu'une génération image demande le GPU. "
        "Lance `start_windows.bat` puis choisis Setup complet pour réinstaller PyTorch CUDA "
        "dans le venv JoyBoy."
    )


def _move_pipe_to_cuda(pipe, label=""):
    """Déplace tous les composants du pipeline vers CUDA, avec fix meta tensors."""
    if not torch.cuda.is_available():
        raise RuntimeError(_cuda_unavailable_message())

    for comp_name in _PIPE_COMPONENTS:
        comp = getattr(pipe, comp_name, None)
        if comp is not None:
            _fix_meta_params(comp, f"{comp_name} (pre-cuda)")
            try:
                comp.to("cuda")
            except CUDA_MOVE_ERRORS:
                # Meta tensors persistants — forcer via to_empty + reload state
                print(f"[MM] {comp_name}: meta tensors persistants, to_empty fallback")
                sd = {k: v for k, v in comp.state_dict().items() if not v.is_meta}
                comp.to_empty(device="cpu")
                comp.load_state_dict(sd, strict=False)
                comp.to("cuda")
    if label:
        print(f"[MM] {label}: GPU direct")


def _place_sdxl_pipe(pipe, model_name, quantized=False, has_controlnet=False):
    """Place le pipeline SDXL sur le device selon le profil GPU.

    Lit offload_strategy du profil JSON au lieu de hardcoder les seuils VRAM.
    Gère le cas spécial quanto INT8 (incompatible avec model_cpu_offload).
    """
    from core.models import IS_MAC, VRAM_GB
    from core.models.gpu_profile import get_offload_strategy

    q_str = " + quantized" if quantized else ""
    cn_str = " + ControlNet" if has_controlnet else ""
    label = f"{model_name}{cn_str}"

    if IS_MAC:
        from core.models.runtime_env import apply_mps_pipeline_optimizations

        pipe.to("mps")
        apply_mps_pipeline_optimizations(pipe, label)
        print(f"[MM] Ready: {label} (MPS)")
        return

    if not torch.cuda.is_available():
        message = _cuda_unavailable_message()
        print(f"[MM] CUDA indisponible: {message}")
        _publish_runtime_progress("runtime_error", 100, 100, message)
        raise RuntimeError(message)

    offload = get_offload_strategy('sdxl')

    if offload == "none":
        # GPU direct — tout en VRAM
        _move_pipe_to_cuda(pipe)
        print(f"[MM] Ready: {label} (GPU direct{q_str}, {VRAM_GB:.0f}GB)")

    elif offload == "model_cpu_offload":
        if quantized:
            # quanto INT8/INT4 incompatible avec model_cpu_offload (QBytesTensor ignore .to() hooks)
            # → UNet + ControlNet + VAE en CUDA direct, encoders en group offload
            try:
                from diffusers.hooks import apply_group_offloading
                onload = torch.device("cuda")
                offload_dev = torch.device("cpu")

                for comp_name in ('unet', 'controlnet', 'vae'):
                    comp = getattr(pipe, comp_name, None)
                    if comp is not None:
                        _fix_meta_params(comp, comp_name)
                        comp.to("cuda")
                for enc_name in ('text_encoder', 'text_encoder_2'):
                    enc = getattr(pipe, enc_name, None)
                    if enc is not None:
                        _fix_meta_params(enc, enc_name)
                        enc.to(dtype=TORCH_DTYPE)
                        apply_group_offloading(
                            enc, onload_device=onload,
                            offload_type="block_level", num_blocks_per_group=2
                        )
                print(f"[MM] Ready: {label} (CUDA{q_str}, enc group offload, {VRAM_GB:.0f}GB)")
            except Exception as e:
                print(f"[MM] Group offload failed: {e}, fallback CPU offload")
                _move_pipe_to_cuda(pipe)
                print(f"[MM] Ready: {label} (GPU direct fallback{q_str}, {VRAM_GB:.0f}GB)")
        else:
            # FP16/BF16 non-quantifié → model_cpu_offload classique
            # Fix meta tensors sur TOUS les composants avant .to("cpu") interne
            for _cname in ('unet', 'controlnet', 'vae', 'text_encoder', 'text_encoder_2'):
                _c = getattr(pipe, _cname, None)
                if _c is not None:
                    _fix_meta_params(_c, _cname)
            try:
                pipe.enable_model_cpu_offload()
                print(f"[MM] Ready: {label} (CPU offload, {VRAM_GB:.0f}GB)")
            except CUDA_MOVE_ERRORS as e:
                print(f"[MM] CPU offload failed ({e}), fallback GPU direct")
                _move_pipe_to_cuda(pipe)
                print(f"[MM] Ready: {label} (GPU direct fallback, {VRAM_GB:.0f}GB)")
    else:
        # Fallback sécuritaire
        for _cname in ('unet', 'controlnet', 'vae', 'text_encoder', 'text_encoder_2'):
            _c = getattr(pipe, _cname, None)
            if _c is not None:
                _fix_meta_params(_c, _cname)
        try:
            pipe.enable_model_cpu_offload()
            print(f"[MM] Ready: {label} (CPU offload fallback, {VRAM_GB:.0f}GB)")
        except CUDA_MOVE_ERRORS as e:
            print(f"[MM] CPU offload failed ({e}), fallback GPU direct")
            _move_pipe_to_cuda(pipe)
            print(f"[MM] Ready: {label} (GPU direct fallback, {VRAM_GB:.0f}GB)")


# _load_no_mmap, _patch_ftfy_encoding -> moved to core/video_loader.py


def _place_flux_int8_pipe(pipe, label="Flux INT8"):
    """Place un pipeline Flux quantifié INT8 sur les devices.

    quanto INT8 QBytesTensors ignorent les hooks .to() via accelerate,
    mais .to("cuda") direct fonctionne. Stratégie :
    1) model_cpu_offload pour tout (VAE, CLIP, T5 = on-demand CUDA↔CPU)
    2) force transformer sur CUDA (quanto ignore les hooks, il y reste)
    Résultat : ~12-13GB VRAM permanent (transformer), le reste swap auto.
    """
    import gc

    # model_cpu_offload : hooks .to("cuda") avant forward, .to("cpu") après
    # → fonctionne pour VAE/encoders (tensors normaux), no-op pour quanto
    pipe.enable_model_cpu_offload()

    # Force transformer sur CUDA — .to() direct fonctionne avec quanto
    # Les hooks post-forward feront .to("cpu") mais quanto les ignore → reste sur CUDA
    if pipe.transformer is not None:
        pipe.transformer.to("cuda")

    gc.collect()
    torch.cuda.empty_cache()
    vram_used = torch.cuda.memory_allocated() / 1024**3
    print(f"[MM] {label}: transformer CUDA direct + model_cpu_offload "
          f"({vram_used:.1f}/{VRAM_GB:.0f}GB VRAM)")


def _check_cpp_compiler():
    """Vérifie si le compilateur C++ (cl.exe) est disponible."""
    try:
        result = subprocess.run(['where', 'cl'], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False


def _install_vs_build_tools():
    """
    Installe Visual Studio Build Tools automatiquement via winget.
    Nécessaire pour la quantification INT4 optimisée.
    """
    print("\n" + "="*60)
    print("  INSTALLATION VISUAL STUDIO BUILD TOOLS")
    print("  (Nécessaire pour INT4 optimisé)")
    print("="*60)

    # Vérifier si winget est disponible
    try:
        result = subprocess.run(['winget', '--version'], capture_output=True, text=True)
        has_winget = result.returncode == 0
    except Exception:
        has_winget = False

    if has_winget:
        print("\n[INSTALL] Installation via winget (peut prendre 5-10 min)...")
        print("[INSTALL] Téléchargement de Visual Studio Build Tools 2022...")

        try:
            # Installation silencieuse avec workload C++
            cmd = [
                'winget', 'install',
                'Microsoft.VisualStudio.2022.BuildTools',
                '--silent',
                '--accept-package-agreements',
                '--accept-source-agreements',
                '--override', '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
            ]

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            for line in process.stdout:
                line = line.strip()
                if line:
                    print(f"[INSTALL] {line}")

            process.wait()

            if process.returncode == 0:
                print("\n" + "="*60)
                print("  ✓ INSTALLATION RÉUSSIE!")
                print("  ")
                print("  ⚠️  REDÉMARRAGE NÉCESSAIRE pour activer le compilateur C++")
                print("  Après redémarrage, INT4 sera 3x plus rapide!")
                print("="*60 + "\n")
                return True
            else:
                print(f"[INSTALL] Erreur installation (code {process.returncode})")
                return False

        except Exception as e:
            print(f"[INSTALL] Erreur: {e}")
            return False
    else:
        # Fallback: télécharger l'installeur manuellement
        print("\n[INSTALL] winget non disponible, téléchargement manuel...")

        import urllib.request

        installer_url = "https://aka.ms/vs/17/release/vs_BuildTools.exe"
        installer_path = os.path.join(os.environ.get('TEMP', '.'), 'vs_BuildTools.exe')

        try:
            print(f"[INSTALL] Téléchargement depuis {installer_url}...")
            urllib.request.urlretrieve(installer_url, installer_path)

            print(f"[INSTALL] Lancement de l'installeur...")
            # Lancer l'installeur avec le workload C++
            cmd = [
                installer_path,
                '--passive', '--wait',
                '--add', 'Microsoft.VisualStudio.Workload.VCTools',
                '--includeRecommended'
            ]

            subprocess.run(cmd, check=False)

            print("\n" + "="*60)
            print("  ✓ INSTALLATION LANCÉE!")
            print("  ")
            print("  ⚠️  REDÉMARREZ après l'installation pour activer C++")
            print("="*60 + "\n")
            return True

        except Exception as e:
            print(f"[INSTALL] Erreur téléchargement: {e}")
            return False


# Flag global pour éviter de proposer l'installation plusieurs fois
_vs_install_proposed = False


