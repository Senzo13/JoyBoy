"""
ModelManager - Source unique de vérité pour tous les modèles.

Singleton thread-safe qui gère le cycle de vie de TOUS les modèles :
- Inpainting, Text2Img, Video, Outpaint (diffusers)
- ControlNet Depth (pour nudity, clothing, pose)
- IP-Adapter FaceID (pour préservation du visage)
- Upscale (Real-ESRGAN), Caption (Florence-2), ZoeDepth
- Segmentation (SegFormer, GroundingDINO)
- Ollama (chat, utility)

Principes :
1. Zéro chargement au démarrage
2. Load-on-demand uniquement
3. load_for_task() gère le smart unload par groupes VRAM (diffusion/video/chat)
4. cleanup() ne décharge que les utilitaires temporaires (Florence, segmentation)
5. unload_all() réservé aux actions explicites (hard reset, unload-all endpoint)
"""

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


class ModelManager:
    """Source unique de vérité pour tous les modèles."""

    _instance = None
    _lock = threading.Lock()

    # Pipelines diffusers
    _inpaint_pipe = None
    _video_pipe = None
    _video_pipe_native = False     # True si backend natif Wan (pas diffusers)
    _ltx_upsampler = None          # LTX spatial upscaler (multi-scale)
    _ltx_upsample_pipe = None      # LTXLatentUpsamplePipeline
    _outpaint_pipe = None

    # ControlNet + IP-Adapter
    _controlnet_model = None       # ControlNet Depth (active)
    _controlnet_depth = None       # ControlNet Depth (stored ref)
    _controlnet_openpose = None    # ControlNet OpenPose (stored ref)
    _active_controlnet_type = 'depth'  # 'depth' or 'openpose'
    _ip_adapter_loaded = False     # IP-Adapter FaceID chargé dans le pipe
    _ip_adapter_style_loaded = False  # IP-Adapter Style (CLIP) chargé dans le pipe
    _ip_adapter_dual_loaded = False   # Les 2 IP-Adapters chargés ensemble
    _depth_estimator = None        # Depth Anything V2 Small
    _depth_processor = None        # Image processor for depth estimator

    # Modèles utilitaires
    _upscale_model = None
    _caption_model = None
    _caption_processor = None
    _zoe_detector = None

    # Track quel modèle exact est chargé par type
    _current_inpaint_model = None
    _current_video_model = None

    # LoRA
    _loras_loaded = {}  # {"nsfw": True, "skin": True, ...}
    _lora_scales = {}   # {"nsfw": 0.0, "skin": 0.5, ...}
    _pending_custom_loras = {}  # {"name": scale} — chargés au prochain pipeline load
    _textual_inversions_loaded = set()

    # État
    _generating = False

    # Backend (diffusers ou gguf)
    _backend = "diffusers"  # "diffusers" ou "gguf"
    _gguf_quant = "Q6_K"    # Q8_0, Q6_K, Q5_K, Q4_K
    _gguf_pipe = None       # Pipeline GGUF actuel

    @classmethod
    def get(cls):
        """Retourne l'instance singleton."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _apply_imported_model_assets(self, model_name: str):
        """Load prompt assets attached to user-imported checkpoints.

        CivitAI pages often recommend textual inversions such as positive/negative
        embeddings. We keep them tied to the imported model instead of global
        state so switching checkpoints stays predictable.
        """
        if not model_name or self._inpaint_pipe is None:
            return
        try:
            from core.infra.model_imports import get_imported_model_runtime_config
            runtime = get_imported_model_runtime_config(model_name)
        except Exception:
            runtime = None
        if not runtime:
            return

        for resource in runtime.get("recommended_resources") or []:
            if str(resource.get("type", "")).lower() != "textualinversion":
                continue
            local_path = resource.get("local_path")
            token = (resource.get("token") or "").strip(" ,")
            if not local_path or not os.path.exists(local_path) or not token:
                continue
            key = f"{model_name}:{local_path}:{token}"
            if key in self._textual_inversions_loaded:
                continue
            try:
                self._inpaint_pipe.load_textual_inversion(local_path, token=token)
                self._textual_inversions_loaded.add(key)
                print(f"[MM] Textual inversion importée: {token}")
            except Exception as exc:
                print(f"[MM] Textual inversion ignorée ({token}): {exc}")

    # =========================================================
    # BACKEND MANAGEMENT
    # =========================================================

    def set_backend(self, backend: str, quant: str = None):
        """Change le backend (diffusers ou gguf)."""
        if backend not in ("diffusers", "gguf"):
            print(f"[MM] Backend inconnu: {backend}, fallback diffusers")
            backend = "diffusers"

        if backend != self._backend:
            print(f"[MM] Backend changé: {self._backend} → {backend}")
            # Décharger l'ancien pipeline si on change de backend
            # Sur high-end GPU (40GB+), on garde la vidéo pour itérer plus vite
            if self._inpaint_pipe is not None or self._gguf_pipe is not None:
                self._unload_diffusers(keep_video=IS_HIGH_END_GPU)
                self._unload_gguf()
            self._backend = backend

        if quant and quant in ("Q8_0", "Q6_K", "Q5_K", "Q4_K"):
            if quant != self._gguf_quant:
                print(f"[MM] GGUF quant changé: {self._gguf_quant} → {quant}")
                # Décharger le pipeline GGUF si on change de quant
                if self._gguf_pipe is not None:
                    self._unload_gguf()
                self._gguf_quant = quant

    def get_backend(self) -> tuple:
        """Retourne (backend, quant)."""
        return self._backend, self._gguf_quant

    def _unload_gguf(self):
        """Décharge le pipeline GGUF."""
        if self._gguf_pipe is not None:
            print("[MM] Unloading GGUF pipeline...")
            try:
                self._gguf_pipe.unload()
            except Exception:
                pass
            self._gguf_pipe = None
        # Aussi appeler la fonction du module gguf_backend
        try:
            from core.gguf_backend import unload_gguf
            unload_gguf()
        except Exception:
            pass

    # =========================================================
    # UNLOAD
    # =========================================================

    def unload_all(self):
        """Décharge TOUT. VRAM → 0, RAM → 0."""
        with self._lock:
            self._unload_diffusers()
            self._unload_gguf()
            self._unload_segmentation(force=True)  # Tout décharger y compris CPU légers
            self._unload_ollama()
            self._unload_utils()
            self._unload_mmaudio()
            self._clear_memory(aggressive=True)

    def unload_all_except_video(self):
        """Décharge tout SAUF le modèle vidéo (trop long à recharger)."""
        with self._lock:
            # Sauvegarder le pipeline vidéo
            video_pipe = self._video_pipe
            video_model = self._current_video_model
            self._video_pipe = None  # Empêcher _unload_diffusers de le supprimer
            self._unload_diffusers()
            self._unload_segmentation()
            self._unload_ollama()
            self._unload_utils()
            self._unload_mmaudio()
            # Restaurer le pipeline vidéo
            self._video_pipe = video_pipe
            self._current_video_model = video_model
            self._clear_memory(aggressive=False)
            if video_pipe is not None:
                print(f"[MM] Modèle vidéo conservé: {video_model}")

    def _unload_video(self):
        """Décharge le pipeline vidéo + tous ses composants associés."""
        if self._video_pipe is not None:
            print(f"[MM] Unloading video ({self._current_video_model})...")
            del self._video_pipe
            self._video_pipe = None
            self._current_video_model = None
        if hasattr(self, '_ltx_upsampler') and self._ltx_upsampler is not None:
            del self._ltx_upsampler
            self._ltx_upsampler = None
        if hasattr(self, '_ltx_upsample_pipe') and self._ltx_upsample_pipe is not None:
            del self._ltx_upsample_pipe
            self._ltx_upsample_pipe = None
        # Décharger les décodeurs rapides (TAEHV, Turbo-VAED)
        try:
            from core.taehv_decode import unload_taehv
            unload_taehv()
        except Exception:
            pass
        try:
            from core.turbo_vaed_decode import unload_turbo_vaed
            unload_turbo_vaed()
        except Exception:
            pass
        self._unload_mmaudio()

    def _unload_mmaudio(self):
        """Décharge MMAudio si chargé."""
        try:
            from core.processing import unload_mmaudio
            unload_mmaudio()
        except Exception:
            pass

    def _unload_diffusers(self, keep_video=False):
        """Décharge tous les pipelines diffusers.

        Args:
            keep_video: Si True, préserve le modèle vidéo (utile pour high-end GPU 40GB+)
        """
        if self._inpaint_pipe is not None:
            # Détacher IP-Adapter si chargé
            if self._ip_adapter_loaded or self._ip_adapter_style_loaded or self._ip_adapter_dual_loaded:
                try:
                    self._inpaint_pipe.unload_ip_adapter()
                except Exception:
                    pass
                self._ip_adapter_loaded = False
                self._ip_adapter_style_loaded = False
                self._ip_adapter_dual_loaded = False
            # Détacher LoRAs si chargés
            if self._loras_loaded:
                try:
                    self._inpaint_pipe.disable_lora()
                except Exception:
                    pass
                self._loras_loaded = {}
                self._lora_scales = {}
            print("[MM] Unloading inpaint...")
            del self._inpaint_pipe
            self._inpaint_pipe = None
            self._current_inpaint_model = None

        if self._controlnet_model is not None:
            print("[MM] Unloading ControlNet...")
            del self._controlnet_model
            self._controlnet_model = None
        if self._controlnet_depth is not None:
            del self._controlnet_depth
            self._controlnet_depth = None
        if self._controlnet_openpose is not None:
            del self._controlnet_openpose
            self._controlnet_openpose = None
        self._active_controlnet_type = 'depth'

        if self._depth_estimator is not None:
            print("[MM] Unloading Depth Anything V2...")
            del self._depth_estimator
            self._depth_estimator = None
        if self._depth_processor is not None:
            del self._depth_processor
            self._depth_processor = None

        if not keep_video:
            self._unload_video()

        if self._outpaint_pipe is not None:
            print("[MM] Unloading outpaint...")
            del self._outpaint_pipe
            self._outpaint_pipe = None

    def _unload_utils(self):
        """Décharge les modèles utilitaires (Upscale, DWPose).
        Note: Florence (~500MB) et Depth Anything V2 (~100MB) sont gardés en mémoire (utilisés souvent)."""
        if self._upscale_model is not None:
            print("[MM] Unloading upscale...")
            del self._upscale_model
            self._upscale_model = None

        # Florence et Depth Anything V2 sont gardés chargés (reload trop lent vs gain VRAM)

        if self._zoe_detector is not None:
            print("[MM] Unloading ZoeDepth...")
            del self._zoe_detector
            self._zoe_detector = None

        # DWPose (body estimation)
        try:
            from core.body_estimation import unload_dwpose
            unload_dwpose()
        except Exception:
            pass

    def _unload_segmentation(self, force=False):
        """Décharge les modèles de segmentation.
        force=False: garde les légers (SCHP, B2, B4) chargés (~230MB GPU).
        force=True: décharge tout (unload_all)."""
        try:
            from core.segmentation import unload_segmentation_models
            unload_segmentation_models(force=force)
        except Exception:
            pass

    def _unload_ollama(self):
        """Décharge tous les modèles Ollama."""
        try:
            from core.ollama_service import get_loaded_models, unload_model
            loaded = get_loaded_models()
            for model_name in loaded:
                try:
                    unload_model(model_name)
                except Exception:
                    pass
        except Exception:
            pass

    def _wait_ollama_unloaded(self, timeout=12.0):
        """Wait briefly until Ollama has actually released its loaded models.

        Ollama unload requests are asynchronous: the HTTP call can return while
        the model is still visible in ``/api/ps`` and still occupies VRAM. On
        8-10GB GPUs we must wait here before loading diffusion/video, otherwise
        SDXL or SVD can start with the chat model still resident and freeze at
        0% under critical VRAM pressure.
        """
        try:
            import time
            from core.ollama_service import get_loaded_models

            deadline = time.time() + float(timeout)
            last_loaded = []
            while time.time() < deadline:
                last_loaded = get_loaded_models()
                if not last_loaded:
                    return True
                time.sleep(0.35)
            if last_loaded:
                print(f"[MM] Ollama encore charge apres {timeout:.1f}s: {', '.join(last_loaded)}")
        except Exception as exc:
            print(f"[MM] Attente unload Ollama ignoree: {exc}")
        return False

    def _clear_memory(self, aggressive=False):
        """Nettoie la mémoire GPU et CPU."""
        gc.collect(0)
        gc.collect(1)
        gc.collect(2)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            if aggressive:
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.reset_accumulated_memory_stats()

        if aggressive:
            try:
                import sys
                if sys.platform == 'win32':
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    psapi = ctypes.windll.psapi
                    handle = kernel32.GetCurrentProcess()
                    kernel32.SetProcessWorkingSetSize(handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1))
                    try:
                        psapi.EmptyWorkingSet(handle)
                    except Exception:
                        pass

                    # Vider la standby list Windows (mémoire cache système)
                    try:
                        self._clear_windows_standby_list()
                    except Exception:
                        pass
            except Exception:
                pass

    def _clear_windows_standby_list(self):
        """Vide la standby list Windows (mémoire cache système). Requiert admin."""
        from utils.windows import clear_standby_list
        clear_standby_list()

    def _quantize_video_transformer(self, transformer, model_name, prefer_speed=None, vram_for_gpu_direct=None):
        """
        Quantifie un transformer vidéo.

        - INT8 = ~50% réduction VRAM, PLUS RAPIDE (support GPU natif)
        - INT4 = ~75% réduction VRAM, PLUS LENT (unpacking overhead) mais tient en faible VRAM

        prefer_speed=None: AUTO - INT4 si VRAM <= 10GB, INT8 sinon
        prefer_speed=True: Force INT8 (rapide)
        prefer_speed=False: Force INT4 (compact)

        vram_for_gpu_direct: Seuil VRAM pour GPU direct. Si VRAM < seuil + 1.5, offloading sera
                             utilisé et on SKIP la quantification (INT8 incompatible avec record_stream).

        Returns: (success: bool, quant_type: str or None)
        """
        # 16GB+ (nominalement 18-20GB) GPU: skip quantization, native bf16 is fast enough
        if VRAM_GB >= 16:
            print(f"[MM]   → Skip quantification {model_name}: {VRAM_GB:.0f}GB VRAM - native bf16")
            return False, None

        # CRITICAL: INT8/INT4 quanto est INCOMPATIBLE avec group offloading (record_stream crash)
        # Si on va utiliser l'offloading, ne pas quantifier du tout
        if vram_for_gpu_direct is not None and VRAM_GB < vram_for_gpu_direct + 1.5:
            print(f"[MM]   → Skip quantification {model_name}: offloading sera utilisé (VRAM {VRAM_GB:.1f}GB < {vram_for_gpu_direct + 1.5:.1f}GB)")
            return False, None

        # AUTO: choisir selon VRAM
        if prefer_speed is None:
            prefer_speed = VRAM_GB > 10  # INT4 pour <= 10GB, INT8 pour > 10GB
        try:
            from optimum.quanto import quantize, freeze, qint4, qint8
        except ImportError:
            print(f"[MM] Installation optimum-quanto...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
            from optimum.quanto import quantize, freeze, qint4, qint8

        # INT8 = plus rapide (support GPU natif), INT4 = plus compact mais plus lent
        # Voir: https://github.com/huggingface/optimum-quanto/issues/367
        if prefer_speed:
            quant_order = [("int8", qint8), ("int4", qint4)]
        else:
            quant_order = [("int4", qint4), ("int8", qint8)]

        ninja_installed = False
        for quant_type, quant_weight in quant_order:
            try:
                print(f"[MM]   → Quantification transformer {quant_type}...")
                quantize(transformer, weights=quant_weight)
                freeze(transformer)
                speed_note = " (rapide)" if quant_type == "int8" else " (compact)"
                print(f"[MM]   → Transformer {model_name} quantifié ({quant_type}){speed_note}")
                return True, quant_type
            except Exception as e:
                err_str = str(e).lower()
                if quant_type == "int4":
                    # INT4 peut échouer si ninja, DLL, ou compilateur C++ manquant
                    if "ninja" in err_str and not ninja_installed:
                        print(f"[MM]   → Installation de Ninja (build tool)...")
                        try:
                            subprocess.run([sys.executable, '-m', 'pip', 'install', 'ninja', '-q'], check=True)
                            ninja_installed = True
                            print(f"[MM]   → Ninja installé, nouvelle tentative INT4...")
                            try:
                                quantize(transformer, weights=quant_weight)
                                freeze(transformer)
                                print(f"[MM]   → Transformer {model_name} quantifié (int4)")
                                return True, "int4"
                            except Exception as e2:
                                print(f"[MM]   → INT4 échoué après Ninja ({e2})")
                        except Exception:
                            print(f"[MM]   → Échec installation Ninja")
                    elif "dll" in err_str or "quanto_cpp" in err_str:
                        print(f"[MM]   → INT4 indisponible (DLL quanto_cpp manquante)")
                    elif "cl" in err_str or "compiler" in err_str or "msvc" in err_str:
                        print(f"[MM]   → INT4 indisponible (compilateur C++ manquant)")
                    else:
                        print(f"[MM]   → INT4 échoué ({e})")
                else:
                    print(f"[MM]   → {quant_type} échoué: {e}")

        print(f"[MM]   → ⚠️ Quantification impossible, bf16 conservé")
        return False, None

    def _quantize_text_encoder(self, pipe, model_name):
        """
        Quantifie le text encoder (T5, CLIP, etc.) en INT8 pour économiser VRAM.
        T5-XXL: ~9.5GB → ~4.7GB
        """
        try:
            from optimum.quanto import quantize, freeze, qint8

            # Chercher le text encoder (différents attributs selon le pipeline)
            text_encoder = None
            encoder_name = "text_encoder"

            if hasattr(pipe, 'text_encoder') and pipe.text_encoder is not None:
                text_encoder = pipe.text_encoder
                encoder_name = "text_encoder"
            elif hasattr(pipe, 'text_encoder_1') and pipe.text_encoder_1 is not None:
                text_encoder = pipe.text_encoder_1
                encoder_name = "text_encoder_1"

            if text_encoder is None:
                return False

            print(f"[MM]   → Quantification {encoder_name} int8...")
            quantize(text_encoder, weights=qint8)
            freeze(text_encoder)
            print(f"[MM]   → {encoder_name} quantifié (int8) - {model_name}")

            # Certains pipelines ont un second text encoder
            if hasattr(pipe, 'text_encoder_2') and pipe.text_encoder_2 is not None:
                print(f"[MM]   → Quantification text_encoder_2 int8...")
                quantize(pipe.text_encoder_2, weights=qint8)
                freeze(pipe.text_encoder_2)
                print(f"[MM]   → text_encoder_2 quantifié (int8)")

            return True
        except Exception as e:
            print(f"[MM]   → Text encoder non quantifié: {e}")
            return False

    # =========================================================
    # LOAD FOR TASK
    # =========================================================

    def load_for_task(self, task_type, **kwargs):
        """
        Charge uniquement ce qui est nécessaire pour la tâche donnée.
        Unload intelligent : ne décharge que ce qui est en conflit VRAM.

        task_type: 'inpaint', 'text2img', 'video', 'chat', 'upscale', 'expand', 'edit',
                   'inpaint_controlnet', 'caption'
        kwargs: model_name, needs_controlnet, needs_ip_adapter, needs_ip_adapter_style,
                preserve_ollama
        """
        preserve_ollama = bool(kwargs.get("preserve_ollama", False))
        # Groupes VRAM: les tâches dans le même groupe peuvent coexister,
        # mais les groupes différents doivent être unload
        VRAM_GROUPS = {
            'diffusion': ['inpaint', 'text2img', 'inpaint_controlnet', 'edit', 'upscale', 'expand'],
            'video': ['video'],
            'chat': ['chat', 'caption'],  # Ollama = process séparé, pas de conflit VRAM
        }

        def _get_group(tt):
            for g, types in VRAM_GROUPS.items():
                if tt in types:
                    return g
            return None

        current_group = _get_group(task_type)

        # Unload uniquement les groupes en conflit (pas le même groupe)
        import concurrent.futures

        # Lancer le déchargement Ollama en PARALLÈLE quand c'est safe.
        # Sur <=10GB VRAM, on bloque avant diffusion/vidéo: garder un LLM
        # chargé pendant SDXL/SVD provoque des freezes et des 0% interminables.
        ollama_future = None
        low_vram = 0 < float(VRAM_GB or 0) <= 10
        ollama_unload_required = False
        ollama_unload_blocking = False
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        with self._lock:
            if current_group == 'video':
                # Vidéo a besoin de TOUTE la VRAM → unload tout SAUF vidéo elle-même
                video_pipe_backup = self._video_pipe
                video_model_backup = self._current_video_model
                self._video_pipe = None
                self._unload_diffusers()
                self._video_pipe = video_pipe_backup
                self._current_video_model = video_model_backup
                self._unload_segmentation()
                self._unload_utils()
                ollama_unload_required = True
                ollama_unload_blocking = low_vram
                self._clear_memory(aggressive=True)
            elif current_group == 'diffusion':
                # Diffusion → unload vidéo/Ollama sauf sur high-end GPU (40GB+)
                # Sur faible VRAM, ne jamais laisser Ollama cohabiter avec un job
                # diffusion. Même si le pipeline est déjà chaud, le run suivant a
                # besoin de marge pour ControlNet, segmentation, VAE et cache CUDA.
                _diffusion_already_loaded = self._inpaint_pipe is not None
                if not IS_HIGH_END_GPU:
                    self._unload_video()
                    self._clear_memory(aggressive=True)
                    if not preserve_ollama and (low_vram or not _diffusion_already_loaded):
                        ollama_unload_required = True
                        ollama_unload_blocking = low_vram
            # Chat → pas besoin d'unload diffusion

        model_name = kwargs.get('model_name')
        needs_controlnet = kwargs.get('needs_controlnet', False)
        needs_ip_adapter = kwargs.get('needs_ip_adapter', False)
        needs_ip_adapter_style = kwargs.get('needs_ip_adapter_style', False)

        if ollama_unload_required:
            if ollama_unload_blocking:
                print(f"[MM] Low VRAM ({VRAM_GB:.1f}GB): unload Ollama avant {current_group}...")
                self._unload_ollama()
                self._wait_ollama_unloaded(timeout=12.0)
                self._clear_memory(aggressive=True)
            else:
                ollama_future = executor.submit(self._unload_ollama)

        if task_type == 'inpaint':
            if needs_controlnet:
                self._load_inpaint_with_controlnet(model_name)
            else:
                self._load_inpaint(model_name)
            if needs_ip_adapter:
                self._load_ip_adapter_face()
            elif self._ip_adapter_loaded:
                self._unload_ip_adapter_safe()
        elif task_type == 'inpaint_controlnet':
            self._load_inpaint_with_controlnet(model_name)
            if needs_ip_adapter:
                self._load_ip_adapter_face()
            elif self._ip_adapter_loaded:
                self._unload_ip_adapter_safe()
        elif task_type == 'text2img':
            self._load_text2img(model_name)
            if needs_controlnet:
                if kwargs.get('use_depth_controlnet'):
                    self._load_controlnet_depth()
                else:
                    self._load_controlnet_openpose()
            if needs_ip_adapter and needs_ip_adapter_style:
                self._load_ip_adapter_dual()
            elif needs_ip_adapter:
                self._load_ip_adapter_face()
            elif needs_ip_adapter_style:
                self._load_ip_adapter_style()
            else:
                self._unload_ip_adapter_safe()
        elif task_type == 'video':
            self._load_video(model_name)
        elif task_type == 'chat':
            # Chat: juste unload diffusers, Ollama géré séparément
            pass
        elif task_type == 'upscale':
            self._load_upscale()
        elif task_type == 'expand':
            self._load_inpaint(model_name)
        elif task_type == 'edit':
            self._load_inpaint(model_name)
        elif task_type == 'caption':
            self._load_caption()

        # Attendre que Ollama finisse de se décharger (en background, non-bloquant pendant le load)
        if ollama_future is not None:
            try:
                ollama_future.result(timeout=1.0)  # Max 1s d'attente, sinon continue
            except Exception:
                pass  # Pas grave si timeout, Ollama continue en background
        executor.shutdown(wait=False)

    # =========================================================
    # PRIVATE LOADERS
    # =========================================================

    def _load_inpaint(self, model_name=None):
        """Charge le pipeline d'inpainting (SDXL, SD 1.5 ou Flux)."""
        # === GGUF BACKEND ===
        if self._backend == "gguf":
            self._load_inpaint_gguf(model_name)
            return

        # === DIFFUSERS BACKEND ===
        from core.models import (
            MODELS, SINGLE_FILE_MODELS, MODEL_QUANT, FLUX_MODELS, get_model_loading_kwargs,
            optimize_pipeline, IS_MAC, custom_cache, _refresh_imported_model_registries
        )
        _refresh_imported_model_registries()

        # Mapping text2img → inpaint + backward compat
        INPAINT_MAPPING = {
            "epiCRealism XL": "epiCRealism XL (Moyen)",
            "epiCRealism XL Inpaint": "epiCRealism XL (Moyen)",  # backward compat
            "Juggernaut XL v9": "Juggernaut XL (Moyen)",
            "Fluently XL v3": "Fluently XL v3 Inpaint",
            "SDXL Turbo": "epiCRealism XL (Moyen)",
            "CyberRealistic Pony": "CyberRealistic Pony (Moyen)",
        }

        if model_name and model_name in INPAINT_MAPPING:
            model_name = INPAINT_MAPPING[model_name]

        # Flux Fill — pipeline séparé
        if model_name and model_name in FLUX_MODELS:
            self._load_flux_fill(model_name)
            return

        # Flux Kontext — editing intelligent (Diffusers, pas GGUF)
        from core.models import FLUX_KONTEXT_MODELS
        if model_name and model_name in FLUX_KONTEXT_MODELS:
            self._load_flux_kontext(model_name)
            return

        if not model_name or model_name == "Automatique" or (model_name not in MODELS and model_name not in SINGLE_FILE_MODELS):
            model_name = "epiCRealism XL (Moyen)"

        if model_name in SINGLE_FILE_MODELS:
            model_id = model_name  # Nom complet (inclut variante Fast/Moyen/Normal)
        else:
            model_id = MODELS[model_name]

        # Si même modèle déjà chargé, réutiliser
        # Comparer model_name (inclut variante Fast/Moyen/Normal) et non model_id (repo, identique pour les 3)
        if self._inpaint_pipe is not None and self._current_inpaint_model == model_name:
            return

        print(f"[MM] Loading inpaint: {model_name}...")

        # Nettoyage caches legacy (anciens noms de clé, ancien modèle 9-ch, caches corrompus)
        try:
            from core.preload import QUANTIZED_CACHE_DIR
            _legacy_patterns = [
                "epicrealism_int*.pt",           # ancien format pré-refactoring
                "*inpainting*_int*.pt",          # anciens modèles 9-ch (tous remplacés par 4-ch)
                "epicrealism_xl_*_int*.pt",      # cache corrompu (nom de modèle comme clé)
                "txt2img_*_int*.pt",             # ancien repo text2img séparé
                "krnl_epicrealism*_int*.pt",     # ancien repo V8-KiSS (remplacé par CrystalClear)
            ]
            for pattern in _legacy_patterns:
                for legacy in QUANTIZED_CACHE_DIR.glob(pattern):
                    legacy.unlink()
                    print(f"[MM] Cache legacy supprimé: {legacy.name}")
        except Exception:
            pass

        # Reset SageAttention global si actif (évite freeze avec SDXL)
        try:
            from core.video_optimizations import reset_global_sageattention
            reset_global_sageattention()
        except Exception:
            pass

        from diffusers import StableDiffusionInpaintPipeline, StableDiffusionXLInpaintPipeline, DPMSolverMultistepScheduler

        sdxl_keywords = ["SDXL", "Fluently", "Juggernaut", "epiCRealism", "CyberRealistic", "Illustrious", "Pony"]
        model_quant = MODEL_QUANT.get(model_name, "int8")
        if model_name in SINGLE_FILE_MODELS or any(kw in model_name for kw in sdxl_keywords):
            if model_name in SINGLE_FILE_MODELS:
                from core.models.registry import resolve_single_file_model
                sfm = SINGLE_FILE_MODELS[model_name]
                model_quant = sfm[2] if len(sfm) > 2 else "int8"
                model_path = resolve_single_file_model(model_name)
                self._inpaint_pipe = StableDiffusionXLInpaintPipeline.from_single_file(
                    model_path, torch_dtype=TORCH_DTYPE,
                    low_cpu_memory_usage=False,
                )
            else:
                load_kwargs = get_model_loading_kwargs()
                try:
                    self._inpaint_pipe = StableDiffusionXLInpaintPipeline.from_pretrained(model_id, **load_kwargs)
                except (ValueError, OSError):
                    load_kwargs.pop("local_files_only", None)
                    load_kwargs.pop("variant", None)
                    print(f"[MM] Fallback: téléchargement {model_id} sans variant fp16...")
                    self._inpaint_pipe = StableDiffusionXLInpaintPipeline.from_pretrained(model_id, **load_kwargs)

            self._inpaint_pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                self._inpaint_pipe.scheduler.config,
                algorithm_type="dpmsolver++", solver_order=2,
                use_karras_sigmas=True, lower_order_final=True,
            )
            self._inpaint_pipe.enable_vae_slicing()
            self._inpaint_pipe.enable_vae_tiling()

            # FIX: Remplacer le VAE SDXL par la version fp16-fix
            # Poids VAE optimisés pour fp16 (moins de perte de précision au décodage)
            # Sur macOS/MPS, _place_sdxl_pipe force aussi le decode VAE en fp32.
            from diffusers import AutoencoderKL
            fixed_vae = AutoencoderKL.from_pretrained(
                "madebyollin/sdxl-vae-fp16-fix", torch_dtype=TORCH_DTYPE
            )
            self._inpaint_pipe.vae = fixed_vae
            self._inpaint_pipe.enable_vae_slicing()
            print(f"[MM] VAE remplacé par sdxl-vae-fp16-fix ({DTYPE_NAME})")
            self._apply_imported_model_assets(model_name)

            self._inpaint_pipe = optimize_pipeline(self._inpaint_pipe, f"inpaint ({model_name})")

            # Fooocus Inpaint Patch: apply weight deltas BEFORE quantization
            # Fixes VAE color shift (yellow skin) by training the UNet for inpainting
            fooocus_applied = False
            if self._inpaint_pipe.unet.config.in_channels == 4:
                try:
                    from core.generation.fooocus_patch import apply_fooocus_patch
                    fooocus_applied = apply_fooocus_patch(self._inpaint_pipe.unet, torch_dtype=TORCH_DTYPE)
                except Exception as e:
                    print(f"[MM] Fooocus patch skipped: {e}")

            # Quantification selon le profil GPU + variante du modèle
            from core.models.gpu_profile import should_quantize
            do_quant, quant_type = should_quantize('sdxl', model_quant)
            quantized_ok = False
            if do_quant and not IS_MAC:
                try:
                    from optimum.quanto import quantize, freeze, qint8, qint4
                except ImportError:
                    print(f"[MM] Installation optimum-quanto...")
                    import subprocess
                    subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                    from optimum.quanto import quantize, freeze, qint8, qint4

                # Essayer les quantifications dans l'ordre: int4 → int8 → FP16
                quant_attempts = ["int4", "int8"] if quant_type == "int4" else [quant_type]
                quantized_ok = False

                _base_cache_key = model_id.replace("/", "_").replace(" ", "_").lower()
                _cache_key = _base_cache_key + ("_fooocus" if fooocus_applied else "")

                # Fix meta tensors AVANT quantification
                _fix_meta_params(self._inpaint_pipe.unet, "unet (pre-quant)")
                _materialize_module(self._inpaint_pipe.unet, "unet")

                for quant_name in quant_attempts:
                    try:
                        from core.preload import get_quantized_cache_path
                        cache_path = get_quantized_cache_path(_cache_key, quant_name)
                        quant_weight = qint4 if quant_name == "int4" else qint8

                        _loaded_from_cache = False
                        if cache_path.exists():
                            try:
                                print(f"[MM] Chargement UNet {quant_name} depuis cache...")
                                _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                                self._inpaint_pipe.unet.load_state_dict(torch.load(cache_path, map_location="cpu", mmap=True), strict=False)
                                _safe_freeze(self._inpaint_pipe.unet)
                                print(f"[MM] UNet {quant_name} chargé depuis cache")
                                _loaded_from_cache = True
                            except Exception as cache_err:
                                print(f"[MM] Cache {quant_name} corrompu: {cache_err}")
                                print(f"[MM] Suppression cache + rechargement modèle...")
                                cache_path.unlink(missing_ok=True)
                                # Cache corrupt after quantize() modified modules → reload pipeline from scratch
                                self._inpaint_pipe = None
                                torch.cuda.empty_cache()
                                import gc; gc.collect()
                                self._inpaint_pipe = StableDiffusionXLPipeline.from_pretrained(
                                    model_id, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
                                )
                                _fix_meta_params(self._inpaint_pipe.unet, "unet (reload)")
                                if fooocus_applied:
                                    from core.generation.fooocus_patch import apply_fooocus_patch
                                    apply_fooocus_patch(self._inpaint_pipe.unet, torch_dtype=TORCH_DTYPE)

                        if not _loaded_from_cache:
                            # Quantifier à la volée et sauvegarder
                            print(f"[MM] Quantification UNet ({quant_name})...")
                            _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                            _safe_freeze(self._inpaint_pipe.unet)

                            try:
                                cache_path.parent.mkdir(parents=True, exist_ok=True)
                                torch.save(self._inpaint_pipe.unet.state_dict(), cache_path)
                                print(f"[MM] UNet {quant_name} sauvegardé dans cache")
                            except Exception as save_err:
                                print(f"[MM] Erreur sauvegarde cache: {save_err}")

                            print(f"[MM] UNet quantifié ({quant_name})")

                        quantized_ok = True
                        break

                    except Exception as e:
                        print(f"[MM] Quantification {quant_name} échouée: {e}")
                        if quant_name == "int4":
                            print(f"[MM] Fallback vers INT8...")
                        continue

                if not quantized_ok:
                    print(f"[MM] ⚠️  ATTENTION: Quantification impossible, FP16 = LENT!")

                # Re-register Fooocus hook (quanto replaces conv_in with QConv2d, losing the hook)
                if fooocus_applied:
                    from core.generation.fooocus_patch import reattach_fooocus_hook
                    reattach_fooocus_hook(self._inpaint_pipe.unet)

            _place_sdxl_pipe(self._inpaint_pipe, model_name, quantized=quantized_ok)

            # SageAttention pour le UNet SDXL (20-30% plus rapide)
            try:
                from core.video_optimizations import apply_sageattention_unet, is_sageattention_available, install_sageattention
                if is_sageattention_available() or install_sageattention():
                    apply_sageattention_unet(self._inpaint_pipe)
            except Exception as e:
                print(f"[MM] SageAttention non activé: {e}")
        else:
            self._inpaint_pipe = StableDiffusionInpaintPipeline.from_pretrained(
                model_id, torch_dtype=TORCH_DTYPE, safety_checker=None,
                requires_safety_checker=False, cache_dir=custom_cache,
            )
            self._inpaint_pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                self._inpaint_pipe.scheduler.config, algorithm_type="dpmsolver++", solver_order=2,
                use_karras_sigmas=True, lower_order_final=True,
            )
            self._inpaint_pipe.enable_vae_slicing()
            self._inpaint_pipe.enable_vae_tiling()
            self._inpaint_pipe = optimize_pipeline(self._inpaint_pipe, f"inpaint SD ({model_name})")
            _place_sdxl_pipe(self._inpaint_pipe, model_name)

            # SageAttention pour le UNet SD 1.5
            try:
                from core.video_optimizations import apply_sageattention_unet, is_sageattention_available, install_sageattention
                if is_sageattention_available() or install_sageattention():
                    apply_sageattention_unet(self._inpaint_pipe)
            except Exception as e:
                print(f"[MM] SageAttention non activé: {e}")

        self._current_inpaint_model = model_name
        self._loras_loaded = {}
        self._lora_scales = {}

        # LoRAs SDXL chargés à la demande (lazy) lors de la génération
        self._load_pending_custom_loras()

        print(f"[MM] Ready: {model_name}")

    def _load_text2img(self, model_name=None):
        """Charge un pipeline text2img SDXL SANS patch Fooocus (poids originaux).

        Le patch Fooocus modifie 960 poids du UNet pour l'inpainting → incompatible
        avec la génération text2img pure. On charge donc le modèle original avec
        StableDiffusionXLPipeline et un cache quantifié séparé (_txt2img suffix).
        """
        from core.models import (
            TEXT2IMG_MODELS, MODEL_QUANT, get_model_loading_kwargs,
            optimize_pipeline, IS_MAC, custom_cache, _refresh_imported_model_registries
        )
        _refresh_imported_model_registries()

        # Mapping inpaint model names → text2img equivalents
        _T2I_MAPPING = {
            "epiCRealism XL (Moyen)": "epiCRealism XL",
            "epiCRealism XL (Fast)": "epiCRealism XL",
            "epiCRealism XL (Normal)": "epiCRealism XL",
            "Juggernaut XL (Moyen)": "Juggernaut XL v9",
            "CyberRealistic Pony (Normal)": "CyberRealistic Pony (Moyen)",
        }
        if model_name and model_name in _T2I_MAPPING:
            model_name = _T2I_MAPPING[model_name]

        from core.models import SINGLE_FILE_MODELS
        if not model_name or model_name == "Automatique" or (model_name not in TEXT2IMG_MODELS and model_name not in SINGLE_FILE_MODELS):
            model_name = "epiCRealism XL"

        # Flux Dev → pipeline séparé
        if 'flux' in model_name.lower() and 'dev' in model_name.lower():
            self._load_flux_dev_text2img(model_name)
            return

        is_single_file = model_name in SINGLE_FILE_MODELS
        model_id = model_name if is_single_file else TEXT2IMG_MODELS[model_name]
        model_key = f"{model_name}_txt2img"

        # Si même modèle text2img déjà chargé, réutiliser
        if self._inpaint_pipe is not None and self._current_inpaint_model == model_key:
            _publish_runtime_progress(
                "load_text2img_model",
                100,
                100,
                f"Modèle Text2Img déjà chargé: {model_name}",
            )
            return

        print(f"[MM] Loading text2img: {model_name} (sans Fooocus patch)...")
        _publish_runtime_progress(
            "load_text2img_model",
            8,
            100,
            f"Chargement Text2Img: {model_name}...",
        )

        # Reset SageAttention global
        try:
            from core.video_optimizations import reset_global_sageattention
            reset_global_sageattention()
        except Exception:
            pass

        from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

        is_turbo = 'turbo' in model_name.lower()

        if is_single_file:
            from core.models.registry import resolve_single_file_model
            model_path = resolve_single_file_model(model_name)
            _publish_runtime_progress(
                "load_text2img_model",
                18,
                100,
                f"Lecture du checkpoint local: {model_name}...",
            )
            self._inpaint_pipe = StableDiffusionXLPipeline.from_single_file(
                model_path, torch_dtype=TORCH_DTYPE,
                low_cpu_memory_usage=False,
            )
        else:
            load_kwargs = get_model_loading_kwargs()
            try:
                _publish_runtime_progress(
                    "load_text2img_model",
                    18,
                    100,
                    f"Chargement depuis Hugging Face: {model_name}...",
                )
                self._inpaint_pipe = StableDiffusionXLPipeline.from_pretrained(model_id, **load_kwargs)
            except (ValueError, OSError):
                load_kwargs.pop("local_files_only", None)
                load_kwargs.pop("variant", None)
                print(f"[MM] Fallback: téléchargement {model_id} sans variant fp16...")
                _publish_runtime_progress(
                    "download_text2img_model",
                    20,
                    100,
                    f"Téléchargement modèle Text2Img: {model_name}...",
                )
                self._inpaint_pipe = StableDiffusionXLPipeline.from_pretrained(model_id, **load_kwargs)
        _publish_runtime_progress(
            "load_text2img_model",
            45,
            100,
            "Pipeline Text2Img chargé",
        )

        if not is_turbo:
            # Scheduler créé from scratch (PAS from_config) car le modèle vient avec
            # EDMDPMSolverMultistepScheduler dont le config EDM est incompatible.
            # DPMSolver++ = previews propres (x0 via convert_model_output) + meilleure qualité
            self._inpaint_pipe.scheduler = DPMSolverMultistepScheduler(
                beta_start=0.00085,
                beta_end=0.012,
                beta_schedule="scaled_linear",
                num_train_timesteps=1000,
                prediction_type="epsilon",
                algorithm_type="dpmsolver++",
                solver_order=2,
                use_karras_sigmas=True,
                lower_order_final=True,
            )

        self._inpaint_pipe.enable_vae_slicing()
        self._inpaint_pipe.enable_vae_tiling()

        # VAE fp16-fix (même que inpaint)
        from diffusers import AutoencoderKL
        _publish_runtime_progress(
            "download_vae",
            50,
            100,
            "Préparation VAE fp16-fix...",
        )
        fixed_vae = AutoencoderKL.from_pretrained(
            "madebyollin/sdxl-vae-fp16-fix", torch_dtype=TORCH_DTYPE
        )
        self._inpaint_pipe.vae = fixed_vae
        self._inpaint_pipe.enable_vae_slicing()
        print(f"[MM] VAE remplacé par sdxl-vae-fp16-fix ({DTYPE_NAME})")
        _publish_runtime_progress("download_vae", 100, 100, "VAE prêt")
        self._apply_imported_model_assets(model_name)

        self._inpaint_pipe = optimize_pipeline(self._inpaint_pipe, f"text2img ({model_name})")

        # Quantification (PAS de Fooocus patch → cache séparé avec _txt2img suffix)
        model_quant = MODEL_QUANT.get(model_name, "int8")
        if is_single_file:
            sfm = SINGLE_FILE_MODELS[model_name]
            model_quant = sfm[2] if len(sfm) > 2 else model_quant
        from core.models.gpu_profile import should_quantize
        do_quant, quant_type = should_quantize('sdxl', model_quant)
        quantized_ok = False

        if do_quant and not IS_MAC:
            _publish_runtime_progress(
                "quantize_model",
                68,
                100,
                "Préparation quantification Text2Img...",
            )
            try:
                from optimum.quanto import quantize, freeze, qint8, qint4
            except ImportError:
                import subprocess
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import quantize, freeze, qint8, qint4

            quant_attempts = ["int4", "int8"] if quant_type == "int4" else [quant_type]
            _cache_key = model_id.replace("/", "_").replace(" ", "_").lower() + "_txt2img"

            _fix_meta_params(self._inpaint_pipe.unet, "unet (pre-quant text2img)")

            for quant_name in quant_attempts:
                try:
                    from core.preload import get_quantized_cache_path
                    cache_path = get_quantized_cache_path(_cache_key, quant_name)
                    quant_weight = qint4 if quant_name == "int4" else qint8

                    _loaded_from_cache = False
                    if cache_path.exists():
                        try:
                            print(f"[MM] Chargement UNet text2img {quant_name} depuis cache...")
                            _publish_runtime_progress(
                                "quantize_model",
                                75,
                                100,
                                f"Chargement cache UNet Text2Img {quant_name}...",
                            )
                            _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                            self._inpaint_pipe.unet.load_state_dict(
                                torch.load(cache_path, map_location="cpu", mmap=True), strict=False
                            )
                            _safe_freeze(self._inpaint_pipe.unet)
                            print(f"[MM] UNet text2img {quant_name} chargé depuis cache")
                            _loaded_from_cache = True
                        except Exception as cache_err:
                            print(f"[MM] Cache text2img {quant_name} corrompu: {cache_err}")
                            cache_path.unlink(missing_ok=True)
                            self._inpaint_pipe = None
                            torch.cuda.empty_cache()
                            gc.collect()
                            self._inpaint_pipe = StableDiffusionXLPipeline.from_pretrained(
                                model_id, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
                            )
                            _fix_meta_params(self._inpaint_pipe.unet, "unet (reload text2img)")

                    if not _loaded_from_cache:
                        print(f"[MM] Quantification UNet text2img ({quant_name})...")
                        _publish_runtime_progress(
                            "quantize_model",
                            78,
                            100,
                            f"Quantification UNet Text2Img {quant_name}...",
                        )
                        _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                        _safe_freeze(self._inpaint_pipe.unet)
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            torch.save(self._inpaint_pipe.unet.state_dict(), cache_path)
                            print(f"[MM] UNet text2img {quant_name} sauvegardé dans cache")
                        except Exception as save_err:
                            print(f"[MM] Erreur sauvegarde cache text2img: {save_err}")

                    quantized_ok = True
                    break

                except Exception as e:
                    print(f"[MM] Quantification text2img {quant_name} échouée: {e}")
                    if quant_name == "int4":
                        print(f"[MM] Fallback vers INT8...")
                    continue

            if not quantized_ok:
                print(f"[MM] Text2img: quantification impossible, FP16")

        _place_sdxl_pipe(self._inpaint_pipe, model_name, quantized=quantized_ok)
        _publish_runtime_progress(
            "load_text2img_model",
            96,
            100,
            "Placement GPU/CPU prêt",
        )

        # SageAttention pour le UNet SDXL
        try:
            from core.video_optimizations import apply_sageattention_unet, is_sageattention_available, install_sageattention
            if is_sageattention_available() or install_sageattention():
                apply_sageattention_unet(self._inpaint_pipe)
        except Exception as e:
            print(f"[MM] SageAttention non activé: {e}")

        self._current_inpaint_model = model_key
        self._loras_loaded = {}
        self._lora_scales = {}
        self._load_pending_custom_loras()

        print(f"[MM] Ready: {model_name} text2img (sans Fooocus)")
        _publish_runtime_progress(
            "load_text2img_model",
            100,
            100,
            "Modèle Text2Img prêt",
        )

    def _load_flux_dev_text2img(self, model_name="Flux Dev INT4"):
        """Charge Flux.1 Dev 12B pour text2img (NF4, INT8, ou bf16)."""
        from core.models import TEXT2IMG_MODELS, FLUX_DEV_NF4_REPO, VRAM_GB, IS_HIGH_END_GPU

        model_id = TEXT2IMG_MODELS[model_name]
        is_int4 = "INT4" in model_name or "int4" in model_name.lower()
        is_int8 = "INT8" in model_name or "int8" in model_name.lower()

        if is_int8:
            _quant_tag = "int8"
        elif is_int4:
            _quant_tag = "int4"
        else:
            _quant_tag = "bf16"
        model_key = f"txt2img_flux_dev_{_quant_tag}"

        if self._inpaint_pipe is not None and self._current_inpaint_model == model_key:
            return

        from diffusers import FluxPipeline, FluxTransformer2DModel

        if is_int8:
            # === INT8 QUANTO ===
            # Pattern: charger pipeline complet bf16 → quantifier transformer in-place → cache
            # (charger transformer séparément puis from_pretrained corrompt le device context PyTorch)
            print(f"[MM] Loading Flux Dev 12B INT8 (text2img, quanto)...")

            print(f"[MM]   → Pipeline complet bf16 depuis {model_id}...")
            self._inpaint_pipe = FluxPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16,
            )

            try:
                from optimum.quanto import qint8
            except ImportError:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import qint8

            from core.preload import get_quantized_cache_path
            _cache_key = "flux_dev_transformer"
            cache_path = get_quantized_cache_path(_cache_key, "int8")

            if cache_path.exists():
                try:
                    print(f"[MM]   → Chargement transformer INT8 depuis cache...")
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    self._inpaint_pipe.transformer.load_state_dict(
                        torch.load(cache_path, map_location="cpu", mmap=True), strict=False
                    )
                    _safe_freeze(self._inpaint_pipe.transformer)
                    print(f"[MM]   → Transformer INT8 chargé depuis cache")
                except Exception as cache_err:
                    print(f"[MM]   → Cache INT8 corrompu: {cache_err}, re-quantification...")
                    cache_path.unlink(missing_ok=True)
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    _safe_freeze(self._inpaint_pipe.transformer)
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
            else:
                print(f"[MM]   → Quantification transformer INT8...")
                _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                _safe_freeze(self._inpaint_pipe.transformer)
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
                    print(f"[MM]   → Transformer INT8 sauvegardé dans cache")
                except Exception as save_err:
                    print(f"[MM]   → Erreur sauvegarde cache: {save_err}")

            _place_flux_int8_pipe(self._inpaint_pipe, "Flux Dev INT8 text2img")
            self._inpaint_pipe.enable_vae_slicing()
            mode = "INT8 quanto + CUDA direct"

        elif is_int4:
            from diffusers import BitsAndBytesConfig as DiffusersBnBConfig
            from transformers import BitsAndBytesConfig as TransformersBnBConfig
            _bnb_4bit = DiffusersBnBConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")
            _bnb_4bit_t5 = TransformersBnBConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")

            print(f"[MM] Loading Flux Dev 12B NF4 (text2img, pré-quantifié)...")

            print(f"[MM]   → Transformer NF4 depuis {FLUX_DEV_NF4_REPO}...")
            transformer = FluxTransformer2DModel.from_pretrained(
                FLUX_DEV_NF4_REPO,
                subfolder="transformer",
                torch_dtype=torch.bfloat16,
                quantization_config=_bnb_4bit,
            )

            _use_gpu_direct = VRAM_GB >= 18
            if _use_gpu_direct:
                try:
                    from transformers import T5EncoderModel
                    print(f"[MM]   → T5 encoder NF4 depuis {FLUX_DEV_NF4_REPO}...")
                    text_encoder_2 = T5EncoderModel.from_pretrained(
                        FLUX_DEV_NF4_REPO,
                        subfolder="text_encoder_2",
                        torch_dtype=torch.bfloat16,
                        quantization_config=_bnb_4bit_t5,
                        device_map="auto",
                    )

                    print(f"[MM]   → Assemblage pipeline...")
                    self._inpaint_pipe = FluxPipeline.from_pretrained(
                        model_id,
                        transformer=transformer,
                        text_encoder_2=text_encoder_2,
                        torch_dtype=torch.bfloat16,
                    )

                    for name in ['transformer', 'text_encoder', 'vae']:
                        comp = getattr(self._inpaint_pipe, name, None)
                        if comp is not None:
                            comp.to("cuda")
                    mode = "NF4 + GPU direct"
                except (ValueError, RuntimeError) as e:
                    print(f"[MM]   → T5 NF4 GPU direct échoué ({e}), fallback cpu_offload...")
                    _use_gpu_direct = False
                    try:
                        del text_encoder_2
                    except NameError:
                        pass
                    gc.collect()
                    torch.cuda.empty_cache()

            if not _use_gpu_direct:
                print(f"[MM]   → T5 bf16 + cpu_offload")
                self._inpaint_pipe = FluxPipeline.from_pretrained(
                    model_id,
                    transformer=transformer,
                    torch_dtype=torch.bfloat16,
                )
                self._inpaint_pipe.enable_model_cpu_offload()
                self._inpaint_pipe.enable_vae_slicing()
                mode = "NF4 + cpu_offload"

        elif IS_HIGH_END_GPU:
            print(f"[MM] Loading Flux Dev 12B (GPU direct, bf16)...")
            self._inpaint_pipe = FluxPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16,
            )
            self._inpaint_pipe.to("cuda")
            mode = "GPU direct"

        else:
            print(f"[MM] Loading Flux Dev 12B (cpu_offload, bf16)...")
            self._inpaint_pipe = FluxPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16,
            )
            self._inpaint_pipe.enable_model_cpu_offload()
            self._inpaint_pipe.enable_vae_slicing()
            mode = "cpu_offload"

        self._inpaint_pipe.enable_vae_slicing()
        self._current_inpaint_model = model_key
        self._loras_loaded = {}
        self._lora_scales = {}

        print(f"[MM] Ready: Flux Dev text2img (12B, {mode})")

    def _load_inpaint_gguf(self, model_name=None):
        """Charge le pipeline d'inpainting via GGUF (modèles quantizés)."""
        from core.gguf_backend import (
            is_gguf_available, ensure_gguf_backend, load_gguf_inpaint,
            load_gguf_edit, is_kontext_model, get_model_path, download_gguf_model
        )

        # Mapping nom diffusers → nom GGUF
        GGUF_MODEL_MAPPING = {
            "epiCRealism XL Inpaint": "epicrealismxl",
            "epiCRealism XL": "epicrealismxl",
            "Juggernaut XL (Moyen)": "juggernautxl",
            "Juggernaut XL v9": "juggernautxl",
            "Flux Kontext": "flux-kontext",
            "Flux.1 Fill Dev": "fluxfill",
            "Flux Fill": "fluxfill",
        }

        # Flux Kontext → editing intelligent (pas de masque)
        if model_name and "kontext" in model_name.lower():
            # Extraire la quantization du nom (ex: "Flux Kontext Q4" → "Q4_K")
            quant_from_name = self._gguf_quant  # défaut
            for q in ["Q8", "Q6", "Q4", "Q3", "Q2"]:
                if q in model_name.upper():
                    quant_map = {"Q8": "Q8_0", "Q6": "Q6_K", "Q4": "Q4_K", "Q3": "Q3_K", "Q2": "Q2_K"}
                    quant_from_name = quant_map.get(q, self._gguf_quant)
                    break
            print(f"[MM] Flux Kontext détecté → mode EDITING ({quant_from_name})")
            pipe = load_gguf_edit("flux-kontext", quant_from_name)
            if pipe:
                if self._inpaint_pipe is not None:
                    del self._inpaint_pipe
                    self._inpaint_pipe = None
                    self._clear_memory(aggressive=True)
                self._gguf_pipe = pipe
                self._current_inpaint_model = f"flux-kontext_{quant_from_name}"
                self._is_kontext_mode = True  # Flag pour bypass pipeline
                print(f"[MM] Ready: Flux Kontext ({quant_from_name}) - EDITING MODE")
                return
            else:
                print(f"[MM] ⚠️ Kontext non disponible, fallback Diffusers")
                self._backend = "diffusers"
                self._load_flux_fill("Flux.1 Fill Dev")
                return

        # Trouver le nom GGUF correspondant
        if not model_name or model_name == "Automatique":
            model_name = "epiCRealism XL (Moyen)"

        gguf_name = GGUF_MODEL_MAPPING.get(model_name)
        if not gguf_name:
            # Fallback: essayer de normaliser le nom
            normalized = model_name.lower().replace(" ", "").replace("-", "")
            for key, value in GGUF_MODEL_MAPPING.items():
                if normalized in key.lower().replace(" ", ""):
                    gguf_name = value
                    break

        if not gguf_name:
            print(f"[MM] ⚠️ GGUF: Modèle {model_name} non supporté, FALLBACK DIFFUSERS")
            self._backend = "diffusers"  # Fallback temporaire
            self._load_inpaint(model_name)
            return

        # Vérifier si déjà chargé
        model_key = f"{gguf_name}_{self._gguf_quant}"
        if self._gguf_pipe is not None and self._current_inpaint_model == model_key:
            print(f"[MM] GGUF: Réutilisation {gguf_name} ({self._gguf_quant})")
            return

        print(f"[MM] Loading GGUF: {gguf_name} ({self._gguf_quant})...")

        # Installer le backend si nécessaire
        if not ensure_gguf_backend():
            print("[MM] ⚠️ GGUF: Backend indisponible, FALLBACK DIFFUSERS")
            self._backend = "diffusers"
            self._load_inpaint(model_name)
            return

        # Charger le modèle GGUF (auto-download si pas présent)
        pipe = load_gguf_inpaint(gguf_name, self._gguf_quant)
        if pipe is None:
            print(f"[MM] ⚠️ GGUF: Modèle {gguf_name} non disponible (pas de version pré-convertie sur HF), FALLBACK DIFFUSERS")
            self._backend = "diffusers"
            self._load_inpaint(model_name)
            return

        # Décharger l'ancien pipeline diffusers si présent
        if self._inpaint_pipe is not None:
            print("[MM] Unloading diffusers pipeline (switching to GGUF)...")
            del self._inpaint_pipe
            self._inpaint_pipe = None
            self._clear_memory(aggressive=True)

        self._gguf_pipe = pipe
        self._current_inpaint_model = model_key
        self._loras_loaded = {}
        self._lora_scales = {}
        print(f"[MM] Ready: {gguf_name} ({self._gguf_quant}) via GGUF")

    def _load_flux_fill(self, model_name="Flux.1 Fill Dev"):
        """Charge Flux.1 Fill Dev 12B pour l'inpainting (NF4, INT8, ou bf16)."""
        from core.models import FLUX_MODELS

        model_id = FLUX_MODELS[model_name]
        is_int4 = "INT4" in model_name
        is_int8 = "INT8" in model_name

        # Model key unique par quantification
        if is_int8:
            model_key = f"{model_id}_int8"
        elif is_int4:
            model_key = f"{model_id}_int4"
        else:
            model_key = model_id

        # Si même modèle déjà chargé, réutiliser
        if self._inpaint_pipe is not None and self._current_inpaint_model == model_key:
            return

        from core.models import IS_HIGH_END_GPU
        from diffusers import FluxFillPipeline

        if is_int8:
            # === INT8 QUANTO ===
            # Pattern: charger pipeline complet bf16 → quantifier transformer in-place → cache
            print(f"[MM] Loading Flux Fill 12B INT8 (quanto)...")

            print(f"[MM]   → Pipeline complet bf16 depuis {model_id}...")
            self._inpaint_pipe = FluxFillPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16,
            )

            try:
                from optimum.quanto import qint8
            except ImportError:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import qint8

            from core.preload import get_quantized_cache_path
            _cache_key = "flux_fill_transformer"
            cache_path = get_quantized_cache_path(_cache_key, "int8")

            if cache_path.exists():
                try:
                    print(f"[MM]   → Chargement transformer INT8 depuis cache...")
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    self._inpaint_pipe.transformer.load_state_dict(
                        torch.load(cache_path, map_location="cpu", mmap=True), strict=False
                    )
                    _safe_freeze(self._inpaint_pipe.transformer)
                    print(f"[MM]   → Transformer INT8 chargé depuis cache")
                except Exception as cache_err:
                    print(f"[MM]   → Cache INT8 corrompu: {cache_err}, re-quantification...")
                    cache_path.unlink(missing_ok=True)
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    _safe_freeze(self._inpaint_pipe.transformer)
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
            else:
                print(f"[MM]   → Quantification transformer INT8...")
                _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                _safe_freeze(self._inpaint_pipe.transformer)
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
                    print(f"[MM]   → Transformer INT8 sauvegardé dans cache")
                except Exception as save_err:
                    print(f"[MM]   → Erreur sauvegarde cache: {save_err}")

            _place_flux_int8_pipe(self._inpaint_pipe, "Flux Fill INT8")
            self._inpaint_pipe.enable_vae_slicing()
            mode = "INT8 quanto + CUDA direct"

        elif is_int4:
            # === NF4 PRÉ-QUANTIFIÉ ===
            from core.models import FLUX_FILL_NF4_REPO, VRAM_GB
            from diffusers import FluxTransformer2DModel
            from diffusers import BitsAndBytesConfig as DiffusersBnBConfig
            from transformers import BitsAndBytesConfig as TransformersBnBConfig
            _bnb_4bit = DiffusersBnBConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")
            _bnb_4bit_t5 = TransformersBnBConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")

            print(f"[MM] Loading Flux Fill 12B NF4 (pré-quantifié)...")

            # Transformer NF4 — BnB quantization, supporte .to() et offload
            print(f"[MM]   → Transformer NF4 depuis {FLUX_FILL_NF4_REPO}...")
            transformer = FluxTransformer2DModel.from_pretrained(
                FLUX_FILL_NF4_REPO,
                subfolder="transformer",
                torch_dtype=torch.bfloat16,
                quantization_config=_bnb_4bit,
            )

            _use_gpu_direct = VRAM_GB >= 18
            if _use_gpu_direct:
                # >= 18GB : T5 NF4 (BnB) + transformer NF4 → GPU direct (~13GB total)
                # BnB ne supporte pas .to() → device_map="auto" place sur CUDA directement
                # WDDM peut rapporter 20GB sur un GPU 8GB (shared memory) → fallback si échec
                try:
                    from transformers import T5EncoderModel
                    print(f"[MM]   → T5 encoder NF4 depuis {FLUX_FILL_NF4_REPO}...")
                    text_encoder_2 = T5EncoderModel.from_pretrained(
                        FLUX_FILL_NF4_REPO,
                        subfolder="text_encoder_2",
                        torch_dtype=torch.bfloat16,
                        quantization_config=_bnb_4bit_t5,
                        device_map="auto",
                    )

                    print(f"[MM]   → Assemblage pipeline...")
                    self._inpaint_pipe = FluxFillPipeline.from_pretrained(
                        model_id,
                        transformer=transformer,
                        text_encoder_2=text_encoder_2,
                        torch_dtype=torch.bfloat16,
                    )

                    # GPU direct — pipe.to("cuda") crasherait sur T5 BnB
                    # Déplacer les composants non-BnB individuellement
                    for name in ['transformer', 'text_encoder', 'vae']:
                        comp = getattr(self._inpaint_pipe, name, None)
                        if comp is not None:
                            comp.to("cuda")
                    mode = "NF4 pré-quantifié + GPU direct"
                except (ValueError, RuntimeError) as e:
                    print(f"[MM]   → T5 NF4 GPU direct échoué ({e}), fallback cpu_offload...")
                    _use_gpu_direct = False
                    # Nettoyage avant fallback
                    try:
                        del text_encoder_2
                    except NameError:
                        pass
                    gc.collect()
                    torch.cuda.empty_cache()

            if not _use_gpu_direct:
                # < 18GB : T5 NF4 BnB = ~6GB, ne peut pas être offloadé (refuse .to())
                # → Utiliser T5 bf16 du repo original avec cpu_offload
                # Le transformer NF4 (~6.7GB diffusers quant) supporte l'offload
                print(f"[MM]   → T5 bf16 + cpu_offload (T5 NF4 BnB incompatible offload)")
                self._inpaint_pipe = FluxFillPipeline.from_pretrained(
                    model_id,
                    transformer=transformer,
                    torch_dtype=torch.bfloat16,
                )
                self._inpaint_pipe.enable_model_cpu_offload()
                self._inpaint_pipe.enable_vae_slicing()
                mode = "NF4 transformer + T5 bf16 cpu_offload"

        elif IS_HIGH_END_GPU:
            # === HIGH-END (38GB+) — GPU direct bf16 ===
            print(f"[MM] Loading Flux Fill 12B... (GPU direct, ~30GB download)")

            self._inpaint_pipe = FluxFillPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
            )
            self._inpaint_pipe.to("cuda")
            mode = "GPU direct"

        else:
            # === STANDARD (18-37GB) — cpu_offload bf16 ===
            print(f"[MM] Loading Flux Fill 12B... (cpu_offload, ~30GB download)")

            self._inpaint_pipe = FluxFillPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
            )
            self._inpaint_pipe.enable_model_cpu_offload()
            self._inpaint_pipe.enable_vae_slicing()
            mode = "cpu_offload"

        self._current_inpaint_model = model_key
        self._loras_loaded = {}
        self._lora_scales = {}

        # LoRAs Flux: chargement lazy via ensure_lora_loaded() pendant la génération
        # (économise ~700MB VRAM si l'user n'a pas activé les LoRAs)

        print(f"[MM] Ready: {model_name} (12B, {mode})")

    def _load_flux_kontext(self, model_name="Flux Kontext"):
        """Charge Flux Kontext 12B pour l'editing intelligent (sans masque)."""
        from core.models import FLUX_KONTEXT_MODELS, custom_cache, IS_HIGH_END_GPU, optimize_flux_pipeline
        from core.models._legacy import get_flux_kontext_uncensored_lora_spec

        model_id = FLUX_KONTEXT_MODELS.get(model_name, "black-forest-labs/FLUX.1-Kontext-dev")
        is_int8 = "INT8" in model_name or "int8" in model_name.lower()

        _model_key_suffix = "_int8" if is_int8 else ""
        # Si même modèle déjà chargé, réutiliser
        if self._inpaint_pipe is not None and self._current_inpaint_model == f"kontext_{model_id}{_model_key_suffix}":
            return

        # FluxKontextPipeline disponible dans diffusers récent
        try:
            from diffusers import FluxKontextPipeline
        except ImportError:
            print("[MM] FluxKontextPipeline non disponible, mise à jour diffusers...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', 'diffusers'], check=True)
            from diffusers import FluxKontextPipeline

        if is_int8:
            # === INT8 QUANTO ===
            # Pattern: charger pipeline complet bf16 → quantifier transformer in-place → cache
            print(f"[MM] Loading Flux Kontext 12B INT8 (quanto)...")

            print(f"[MM]   → Pipeline complet bf16 depuis {model_id}...")
            self._inpaint_pipe = FluxKontextPipeline.from_pretrained(
                model_id, torch_dtype=torch.bfloat16, cache_dir=custom_cache,
            )

            try:
                from optimum.quanto import qint8
            except ImportError:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import qint8

            from core.preload import get_quantized_cache_path
            _cache_key = "flux_kontext_transformer"
            cache_path = get_quantized_cache_path(_cache_key, "int8")

            if cache_path.exists():
                try:
                    print(f"[MM]   → Chargement transformer INT8 depuis cache...")
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    self._inpaint_pipe.transformer.load_state_dict(
                        torch.load(cache_path, map_location="cpu", mmap=True), strict=False
                    )
                    _safe_freeze(self._inpaint_pipe.transformer)
                    print(f"[MM]   → Transformer INT8 chargé depuis cache")
                except Exception as cache_err:
                    print(f"[MM]   → Cache INT8 corrompu: {cache_err}, re-quantification...")
                    cache_path.unlink(missing_ok=True)
                    _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                    _safe_freeze(self._inpaint_pipe.transformer)
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
            else:
                print(f"[MM]   → Quantification transformer INT8...")
                _safe_quantize(self._inpaint_pipe.transformer, weights=qint8)
                _safe_freeze(self._inpaint_pipe.transformer)
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    torch.save(self._inpaint_pipe.transformer.state_dict(), cache_path)
                    print(f"[MM]   → Transformer INT8 sauvegardé dans cache")
                except Exception as save_err:
                    print(f"[MM]   → Erreur sauvegarde cache: {save_err}")

            _place_flux_int8_pipe(self._inpaint_pipe, "Flux Kontext INT8")
            offload = "INT8 quanto + CUDA direct"
        else:
            # === BF16 (standard) ===
            print(f"[MM] Loading Flux Kontext 12B... (~24GB)")

            self._inpaint_pipe = FluxKontextPipeline.from_pretrained(
                model_id,
                torch_dtype=torch.bfloat16,
                cache_dir=custom_cache,
            )

            # Optimisations Flux (torch.compile sur transformer)
            self._inpaint_pipe = optimize_flux_pipeline(self._inpaint_pipe, "Flux Kontext")

            # High-end GPU (40GB+): GPU direct, sinon cpu_offload
            if IS_HIGH_END_GPU:
                self._inpaint_pipe.to("cuda")
                offload = "GPU direct"
                print(f"[OPT] GPU direct ({VRAM_GB:.0f}GB VRAM)")
            else:
                self._inpaint_pipe.enable_model_cpu_offload()
                offload = "cpu_offload"
                print(f"[OPT] model_cpu_offload ({VRAM_GB:.0f}GB VRAM)")

        # Charger le LoRA uncensored (INT8 = toujours uncensored, sinon selon le nom)
        is_uncensored = is_int8 or "uncensored" in model_name.lower()
        lora_loaded = False
        if is_uncensored:
            try:
                if not self._ensure_peft():
                    print("[MM] LoRA uncensored désactivé (peft non disponible)")
                else:
                    lora_repo_id, lora_filename = get_flux_kontext_uncensored_lora_spec()
                    if not lora_repo_id or not lora_filename:
                        print("[MM] LoRA uncensored: aucun pack local actif ne fournit cette ressource")
                    else:
                        print(f"[MM] Chargement LoRA Flux Kontext avancé depuis {lora_repo_id}...")
                        from huggingface_hub import hf_hub_download
                        lora_path = hf_hub_download(
                            repo_id=lora_repo_id,
                            filename=lora_filename
                        )
                        self._inpaint_pipe.load_lora_weights(
                            lora_path,
                            adapter_name="uncensored"
                        )
                        self._inpaint_pipe.set_adapters(["uncensored"], adapter_weights=[1.0])
                        print("[MM] LoRA uncensored activé (scale=1.0)")
                        lora_loaded = True
            except Exception as e:
                print(f"[MM] LoRA uncensored: échec ({e}) - Flux Kontext fonctionne sans LoRA")

        self._current_inpaint_model = f"kontext_{model_id}{_model_key_suffix}"
        self._is_kontext_mode = True  # Flag pour traitement spécial
        self._loras_loaded = {"uncensored": is_uncensored}
        self._lora_scales = {"uncensored": 1.0 if is_uncensored else 0.0}

        mode = "INT8 Uncensored" if is_int8 else ("Uncensored" if is_uncensored else "Standard")
        print(f"[MM] Ready: Flux Kontext {mode} (12B, {offload}) - EDITING MODE")

        # WARMUP: uniquement avec torch.compile (Linux) — pré-compile les graphes par taille
        from core.models import USE_TORCH_COMPILE, GPU_MODEL_CONFIG, GPU_TIER
        flux_config = GPU_MODEL_CONFIG.get("flux_kontext", {}).get(GPU_TIER, {})
        needs_warmup = flux_config.get("warmup", False) and USE_TORCH_COMPILE

        if needs_warmup and torch.cuda.is_available():
            try:
                from PIL import Image
                import numpy as np
                from core.models import WARMUP_SIZES
                print(f"[MM] Warmup CUDA Flux Kontext ({len(WARMUP_SIZES)} tailles, torch.compile actif)...")
                for h, w in WARMUP_SIZES:
                    dummy_img = Image.fromarray(np.zeros((h, w, 3), dtype=np.uint8))
                    with torch.no_grad():
                        _ = self._inpaint_pipe(
                            prompt="warmup",
                            image=dummy_img,
                            num_inference_steps=1,
                            guidance_scale=1.0,
                            output_type="latent",
                        )
                    print(f"[MM]   → {h}x{w} OK")
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                print("[MM] Warmup Flux terminé")
            except Exception as e:
                print(f"[MM] Warmup Flux skip: {e}")
        elif torch.cuda.is_available():
            print(f"[MM] Warmup Flux skip (pas de torch.compile)")

    # LoRA Flux registry: (civitai_version_id, filename, default_scale)
    FLUX_LORA_REGISTRY = {}

    # LoRA Flux HuggingFace: (repo_id, subfolder, weight_name, default_scale)
    FLUX_HF_LORA_REGISTRY = {
        "clothes_off": ("speedchemistry/lora", "Flux-Kontext", "clothes_remover_v0.safetensors", 0.0),
    }

    def _load_flux_loras(self):
        """Charge les LoRAs Flux."""
        if self._inpaint_pipe is None:
            return

        # Installer peft si nécessaire
        if not self._ensure_peft():
            print("[MM] LoRAs Flux désactivés (peft non disponible)")
            return

        # LoRAs depuis CivitAI
        for name, (version_id, filename, default_scale) in self.FLUX_LORA_REGISTRY.items():
            try:
                lora_path = self._download_civitai_lora(version_id, filename)
                print(f"[MM] Chargement LoRA Flux {name}...")
                self._inpaint_pipe.load_lora_weights(
                    lora_path,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA Flux {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA Flux {name}: échec ({e})")
                self._loras_loaded[name] = False

        # LoRAs depuis HuggingFace (clothes removal, etc.)
        for name, (repo_id, subfolder, weight_name, default_scale) in self.FLUX_HF_LORA_REGISTRY.items():
            try:
                print(f"[MM] Chargement LoRA Flux {name} (HuggingFace, 344MB)...")
                self._inpaint_pipe.load_lora_weights(
                    repo_id,
                    subfolder=subfolder,
                    weight_name=weight_name,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA Flux {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA Flux {name}: échec ({e})")
                self._loras_loaded[name] = False

        self._apply_lora_scales()

    def _download_civitai_lora(self, model_version_id, filename):
        """Télécharge un LoRA depuis CivitAI si pas déjà présent."""
        from pathlib import Path

        lora_dir = Path(__file__).parent.parent / "ext_weights" / "loras"
        lora_dir.mkdir(parents=True, exist_ok=True)
        lora_path = lora_dir / filename

        if lora_path.exists():
            print(f"[MM] LoRA déjà présent: {filename}")
            return str(lora_path)

        from config import CIVITAI_API_KEY
        api_key = CIVITAI_API_KEY
        url = f"https://civitai.com/api/download/models/{model_version_id}"
        if api_key:
            url += f"?token={api_key}"

        print(f"[MM] Téléchargement LoRA depuis CivitAI (version {model_version_id})...")
        import requests
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        with open(lora_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (50 * 1024 * 1024) < 8192:
                    pct = downloaded * 100 // total
                    print(f"[MM] LoRA download: {pct}%")

        size_mb = lora_path.stat().st_size / (1024 * 1024)
        print(f"[MM] LoRA téléchargé: {filename} ({size_mb:.0f}MB)")
        return str(lora_path)

    # LoRA registry: (civitai_version_id, filename, default_scale, trigger_word)
    # IMPORTANT: default_scale=0.0 pour TOUS les LoRAs — l'utilisateur doit les activer explicitement
    LORA_REGISTRY = {}

    _peft_checked = False
    _peft_available = False

    def _ensure_peft(self):
        """Vérifie que peft est disponible. Ne tente l'install qu'une seule fois."""
        if ModelManager._peft_checked:
            return ModelManager._peft_available
        ModelManager._peft_checked = True
        try:
            import peft
            ModelManager._peft_available = True
            return True
        except ImportError:
            print("[MM] peft manquant, tentative d'installation...")
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'peft'], check=True, capture_output=True)
                import peft
                print("[MM] peft installé avec succès")
                ModelManager._peft_available = True
                return True
            except Exception as e:
                print(f"[MM] peft indisponible: {e}")
                print("[MM] → pip install peft pour activer les LoRAs")
                ModelManager._peft_available = False
                return False

    def _load_all_loras(self):
        """Télécharge et charge tous les LoRAs du registry."""
        if self._inpaint_pipe is None:
            return

        # Installer peft si nécessaire
        if not self._ensure_peft():
            print("[MM] LoRAs désactivés (peft non disponible)")
            return

        for name, (version_id, filename, default_scale, trigger) in self.LORA_REGISTRY.items():
            try:
                lora_path = self._download_civitai_lora(version_id, filename)
                print(f"[MM] Chargement LoRA {name}...")
                self._inpaint_pipe.load_lora_weights(
                    lora_path,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA {name}: échec ({e})")
                self._loras_loaded[name] = False
                # Nettoyer l'adapter partiellement enregistré (évite "already in use")
                try:
                    self._inpaint_pipe.delete_adapters(name)
                except Exception:
                    pass

        # Appliquer les scales initiales
        self._apply_lora_scales()

    def _apply_lora_scales(self):
        """Applique les scales courantes de tous les LoRAs chargés (sans IP-Adapter)."""
        if self._inpaint_pipe is None:
            return
        active = [(n, s) for n, s in self._lora_scales.items() if self._loras_loaded.get(n)]
        if not active:
            return
        names, weights = zip(*active)
        try:
            self._inpaint_pipe.set_adapters(list(names), adapter_weights=list(weights))
            print(f"[MM] LoRA scales appliqués: {dict(zip(names, weights))}")
        except Exception as e:
            print(f"[MM] LoRA set_adapters error: {e}")

    def _apply_all_adapters(self):
        """Applique TOUS les adapters: LoRAs custom + built-in + IP-Adapter (faceid_0 etc.)."""
        if self._inpaint_pipe is None:
            return
        # Collecter les LoRAs actifs
        all_names = []
        all_weights = []
        for n, s in self._lora_scales.items():
            if self._loras_loaded.get(n):
                all_names.append(n)
                all_weights.append(s)
        # Ajouter les adapters IP-Adapter (faceid_0 etc.) s'ils existent
        try:
            target = getattr(self._inpaint_pipe, 'unet', None) or getattr(self._inpaint_pipe, 'transformer', None)
            if target is not None and hasattr(target, 'peft_config'):
                for adapter_name in target.peft_config:
                    if adapter_name not in all_names and adapter_name.startswith('faceid'):
                        all_names.append(adapter_name)
                        all_weights.append(1.0)  # IP-Adapter scale géré séparément
        except Exception:
            pass
        if not all_names:
            return
        try:
            self._inpaint_pipe.set_adapters(all_names, adapter_weights=all_weights)
            print(f"[MM] Adapters actifs: {dict(zip(all_names, all_weights))}")
        except Exception as e:
            print(f"[MM] set_adapters error: {e}")

    def _is_flux_pipeline(self):
        """Détecte si le pipeline actif est Flux (Fill ou Kontext)."""
        if self._inpaint_pipe is None:
            return False
        pipe_class = type(self._inpaint_pipe).__name__
        return 'Flux' in pipe_class

    def ensure_lora_loaded(self, name):
        """Charge un LoRA à la demande s'il n'est pas déjà chargé. Retourne True si chargé.
        Route automatiquement vers le bon registre (SDXL ou Flux) selon le pipeline actif."""
        if self._loras_loaded.get(name):
            return True
        if self._inpaint_pipe is None:
            return False
        if not self._ensure_peft():
            return False

        is_flux = self._is_flux_pipeline()

        if is_flux:
            # Mapping intentions SDXL → noms Flux (skin → clothes_off)
            flux_name = self._FLUX_LORA_NAME_MAP.get(name, name)
            if flux_name != name:
                # Vérifier si déjà chargé sous le nom Flux
                if self._loras_loaded.get(flux_name):
                    self._loras_loaded[name] = True
                    return True
                name = flux_name

            # Chercher dans FLUX_LORA_REGISTRY (CivitAI)
            if name in self.FLUX_LORA_REGISTRY:
                version_id, filename, default_scale = self.FLUX_LORA_REGISTRY[name]
                try:
                    lora_path = self._download_civitai_lora(version_id, filename)
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA Flux {name} (lazy)...")
                    self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA Flux {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA Flux {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False

            # Chercher dans FLUX_HF_LORA_REGISTRY (HuggingFace)
            if name in self.FLUX_HF_LORA_REGISTRY:
                repo_id, subfolder, weight_name, default_scale = self.FLUX_HF_LORA_REGISTRY[name]
                try:
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA Flux {name} (HuggingFace, lazy)...")
                    self._inpaint_pipe.load_lora_weights(
                        repo_id, subfolder=subfolder,
                        weight_name=weight_name, adapter_name=name
                    )
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA Flux {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA Flux {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False
        else:
            # Chercher dans LORA_REGISTRY (SDXL)
            if name in self.LORA_REGISTRY:
                version_id, filename, default_scale, trigger = self.LORA_REGISTRY[name]
                try:
                    lora_path = self._download_civitai_lora(version_id, filename)
                    # Nettoyer un adapter fantôme d'un chargement précédent échoué
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA {name} (lazy)...")
                    self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False

        # Fallback: chercher dans trained_loras/ (custom LoRAs)
        custom_path = self._find_custom_lora(name)
        if custom_path:
            return self._load_custom_lora(name, custom_path)

        return False

    def _find_custom_lora(self, name):
        """Cherche un LoRA custom dans trained_loras/."""
        from pathlib import Path
        lora_dir = Path(__file__).parent.parent.parent / "trained_loras"
        if not lora_dir.exists():
            return None
        # Chercher par nom exact ou avec .safetensors
        for ext in ['.safetensors', '.pt', '.bin']:
            path = lora_dir / f"{name}{ext}"
            if path.exists():
                return str(path)
        # Chercher par prefix (sans extension)
        for f in lora_dir.iterdir():
            if f.stem == name and f.suffix in {'.safetensors', '.pt', '.bin'}:
                return str(f)
        return None

    def _load_custom_lora(self, name, lora_path, scale=0.8):
        """Charge un LoRA custom depuis un fichier local.
        Compatible avec IP-Adapter (préserve les adapters existants comme faceid_0).
        """
        if self._inpaint_pipe is None:
            return False
        try:
            # Sauvegarder les adapters existants (IP-Adapter etc.) AVANT modification
            existing_adapters = []
            try:
                existing_adapters = list(self._inpaint_pipe.get_active_adapters())
            except Exception:
                pass

            # Supprimer l'ancien adapter si déjà chargé (ignore erreurs)
            try:
                self._inpaint_pipe.delete_adapters(name)
            except Exception:
                pass

            # Restaurer les adapters existants après suppression
            # (delete_adapters peut changer l'adapter actif)
            if existing_adapters:
                remaining = [a for a in existing_adapters if a != name]
                if remaining:
                    try:
                        self._inpaint_pipe.set_adapters(remaining)
                    except Exception:
                        pass

            print(f"[MM] Chargement LoRA custom '{name}' depuis {lora_path}...")
            self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
            self._loras_loaded[name] = True
            self._lora_scales[name] = scale

            # Activer TOUS les adapters (custom LoRAs + IP-Adapter)
            self._apply_all_adapters()

            # Diagnostic: vérifier que les couches LoRA sont bien injectées
            lora_layers = 0
            target = getattr(self._inpaint_pipe, 'unet', None) or getattr(self._inpaint_pipe, 'transformer', None)
            if target is not None:
                for _, module in target.named_modules():
                    if hasattr(module, 'lora_A') and name in getattr(module, 'lora_A', {}):
                        lora_layers += 1
            active = []
            try:
                active = list(self._inpaint_pipe.get_active_adapters())
            except Exception:
                pass
            print(f"[MM] LoRA custom '{name}' chargé (scale={scale}, {lora_layers} couches, adapters actifs: {active})")
            return True
        except Exception as e:
            print(f"[MM] LoRA custom '{name}': échec ({e})")
            import traceback
            traceback.print_exc()
            try:
                self._inpaint_pipe.delete_adapters(name)
            except Exception:
                pass
            self._loras_loaded[name] = False
            return False

    def list_custom_loras(self):
        """Liste les LoRAs custom disponibles dans trained_loras/."""
        from pathlib import Path
        lora_dir = Path(__file__).parent.parent.parent / "trained_loras"
        if not lora_dir.exists():
            return []
        loras = []
        for f in sorted(lora_dir.iterdir()):
            if f.suffix in {'.safetensors', '.pt', '.bin'}:
                is_loaded = self._loras_loaded.get(f.stem, False)
                is_pending = f.stem in self._pending_custom_loras
                loras.append({
                    "name": f.stem,
                    "filename": f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "loaded": is_loaded or is_pending,
                    "pending": is_pending and not is_loaded,
                    "scale": self._lora_scales.get(f.stem, self._pending_custom_loras.get(f.stem, 0.8)),
                })
        return loras

    def _load_pending_custom_loras(self):
        """Charge les custom LoRAs en attente après un chargement de pipeline."""
        if not self._pending_custom_loras or self._inpaint_pipe is None:
            return
        if not self._ensure_peft():
            return
        loaded = []
        for name, scale in list(self._pending_custom_loras.items()):
            custom_path = self._find_custom_lora(name)
            if custom_path:
                if self._load_custom_lora(name, custom_path, scale=scale):
                    loaded.append(name)
                    print(f"[MM] Custom LoRA '{name}' chargé (pending, scale={scale})")
        # Nettoyer les pending qui ont été chargés
        for name in loaded:
            del self._pending_custom_loras[name]

    # Mapping intentions frontend → noms LoRA Flux réels
    _FLUX_LORA_NAME_MAP = {"skin": "clothes_off"}

    def set_lora_scale(self, name, scale):
        """Ajuste le scale d'un LoRA spécifique."""
        # Résoudre le nom réel pour Flux (skin → clothes_off)
        if self._is_flux_pipeline():
            name = self._FLUX_LORA_NAME_MAP.get(name, name)
        if not self._loras_loaded.get(name) or self._inpaint_pipe is None:
            return
        self._lora_scales[name] = scale
        self._apply_lora_scales()

    def unload_lora(self, name):
        """Décharge complètement un LoRA du pipeline (libère la VRAM)."""
        if self._is_flux_pipeline():
            name = self._FLUX_LORA_NAME_MAP.get(name, name)
        if not self._loras_loaded.get(name) or self._inpaint_pipe is None:
            return
        try:
            self._inpaint_pipe.delete_adapters(name)
            print(f"[MM] LoRA {name} déchargé (VRAM libérée)")
        except Exception as e:
            print(f"[MM] LoRA {name} unload error: {e}")
        self._loras_loaded[name] = False
        self._lora_scales.pop(name, None)
        # Réappliquer les adapters restants
        self._apply_lora_scales()

    def prepare_prompt_with_lora_triggers(self, prompt: str) -> str:
        """Ajoute les trigger words des LoRAs actifs au prompt.

        Un LoRA est considéré actif si son scale > 0 et qu'il est chargé.
        Le trigger word est ajouté au début du prompt s'il n'est pas déjà présent.
        """
        if not prompt:
            return prompt

        triggers_to_add = []
        for name, (_, _, _, trigger) in self.LORA_REGISTRY.items():
            if trigger and self._loras_loaded.get(name) and self._lora_scales.get(name, 0) > 0:
                # Vérifier si le trigger n'est pas déjà dans le prompt
                if trigger.lower() not in prompt.lower():
                    triggers_to_add.append(trigger)
                    print(f"[MM] LoRA {name} trigger ajouté: {trigger[:40]}...")

        if triggers_to_add:
            return ", ".join(triggers_to_add) + ", " + prompt
        return prompt

    def _load_video(self, model_name=None):
        """Charge un modele video.

        Delegue le chargement aux fonctions specialisees dans core/video_loader.py.
        """
        from core.models import custom_cache

        if not model_name:
            model_name = "svd"

        framepack_aliases = {"framepack", "framepack-fast"}
        same_framepack_backend = (
            self._current_video_model in framepack_aliases
            and model_name in framepack_aliases
        )

        if self._video_pipe is not None and (self._current_video_model == model_name or same_framepack_backend):
            self._current_video_model = model_name
            return

        # Unload l'ancien modele video si on change de modele
        if self._video_pipe is not None and self._current_video_model != model_name:
            print(f"[MM] Changement video: {self._current_video_model} -> {model_name}")
            self._unload_video()
            self._clear_memory(aggressive=True)

        # TOUJOURS vider le cache CUDA avant de charger un nouveau modele video
        # Le cache peut accumuler 10GB+ apres des erreurs/generations precedentes
        if torch.cuda.is_available():
            cache_before = torch.cuda.memory_reserved() / 1024**3
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            gc.collect()
            cache_after = torch.cuda.memory_reserved() / 1024**3
            if cache_before - cache_after > 0.5:
                print(f"[MM] Cache CUDA libere: {cache_before:.1f}GB -> {cache_after:.1f}GB")

        print(f"[MM] Loading video: {model_name}...")

        # Reset native flag (sera mis a True si backend natif)
        self._video_pipe_native = False

        # Dispatch to per-model loader in video_loader.py
        from core import video_loader

        if model_name == "svd":
            result = video_loader.load_svd(custom_cache)
        elif model_name == "cogvideox":
            result = video_loader.load_cogvideox(custom_cache)
        elif model_name == "cogvideox-q4":
            result = video_loader.load_cogvideox_q4(custom_cache)
        elif model_name == "cogvideox-2b":
            result = video_loader.load_cogvideox_2b(custom_cache)
        elif model_name == "wan":
            result = video_loader.load_wan_21_14b(custom_cache)
        elif model_name == "wan22":
            result = video_loader.load_wan22_a14b(custom_cache)
        elif model_name == "hunyuan":
            result = video_loader.load_hunyuan(custom_cache)
        elif model_name in ("wan22-5b", "fastwan"):
            result = video_loader.load_wan22_5b(model_name, custom_cache)
        elif model_name == "wan22-t2v-14b":
            result = video_loader.load_wan22_t2v_14b(custom_cache)
        elif model_name == "ltx":
            result = video_loader.load_ltx(custom_cache)
        elif model_name in ("framepack", "framepack-fast"):
            result = video_loader.load_framepack(custom_cache)
        elif model_name == "ltx2":
            result = video_loader.load_ltx2(custom_cache)
        elif model_name == "ltx2_fp8":
            result = video_loader.load_ltx2_fp8(custom_cache)
        elif model_name in ("wan-native-5b", "wan-native-14b"):
            result = video_loader.load_wan_native(model_name, custom_cache)
        else:
            raise ValueError(f"Modele video inconnu: {model_name}")

        # Unpack result from loader
        self._video_pipe = result["pipe"]
        extras = result.get("extras", {})
        if extras.get("native"):
            self._video_pipe_native = True
        if "ltx_upsampler" in extras:
            self._ltx_upsampler = extras["ltx_upsampler"]
        if "ltx_upsample_pipe" in extras:
            self._ltx_upsample_pipe = extras["ltx_upsample_pipe"]

        self._current_video_model = model_name
        print(f"[MM] Ready: {model_name}")

    def _load_upscale(self):
        """Charge Real-ESRGAN."""
        if self._upscale_model is not None:
            return

        from utils.compat import _patch_torchvision_compatibility
        from core.models._legacy import _install_upscale_dependencies

        _patch_torchvision_compatibility()

        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except ImportError:
            _install_upscale_dependencies()
            _patch_torchvision_compatibility()
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
        self._upscale_model = RealESRGANer(
            scale=2,
            model_path='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth',
            model=model, tile=0, tile_pad=10, pre_pad=0, half=True, gpu_id=0,
        )
        print("[MM] Ready: Real-ESRGAN x2plus (no tiling)")

    def _load_caption(self):
        """Charge Florence-2 pour caption/description."""
        if self._caption_model is not None:
            return

        from core.florence import load_florence
        model, processor = load_florence()
        self._caption_model = model
        self._caption_processor = processor

    # =========================================================
    # CONTROLNET + IP-ADAPTER
    # =========================================================

    def _load_controlnet_depth(self):
        """Charge ControlNet Depth Small pour SDXL."""
        if self._controlnet_model is not None:
            return

        from diffusers import ControlNetModel
        from core.models import custom_cache, IS_MAC, VRAM_GB

        print("[MM] Loading ControlNet Depth Small...")
        _publish_runtime_progress(
            "download_controlnet",
            8,
            100,
            "Préparation ControlNet Depth...",
        )
        _cn_repo = "diffusers/controlnet-depth-sdxl-1.0-small"
        try:
            self._controlnet_model = ControlNetModel.from_pretrained(
                _cn_repo, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
                local_files_only=True,
            )
        except OSError:
            _publish_runtime_progress(
                "download_controlnet",
                10,
                100,
                "Téléchargement ControlNet Depth...",
            )
            self._controlnet_model = ControlNetModel.from_pretrained(
                _cn_repo, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
            )
        # Fix meta tensors: reload depuis safetensors si nécessaire
        _has_meta = any(p.is_meta for _, p in self._controlnet_model.named_parameters())
        if _has_meta:
            try:
                from safetensors.torch import load_file
                from huggingface_hub import try_to_load_from_cache
                _cn_file = try_to_load_from_cache(_cn_repo, "diffusion_pytorch_model.safetensors", cache_dir=custom_cache)
                if _cn_file and isinstance(_cn_file, str):
                    sd = load_file(_cn_file)
                    self._controlnet_model.load_state_dict(sd, strict=False, assign=True)
                    print(f"[MM] ControlNet: meta tensors fixés via reload safetensors")
                else:
                    _fix_meta_params(self._controlnet_model, "ControlNet Depth")
            except Exception as e:
                print(f"[MM] ControlNet reload failed: {e}")
                _fix_meta_params(self._controlnet_model, "ControlNet Depth")

        # Aggressive meta fix (parallel loading race condition)
        _materialize_module(self._controlnet_model, "ControlNet Depth")

        # Quantification int8 ControlNet selon profil GPU (~360MB → ~180MB)
        from core.models.gpu_profile import should_quantize as _sq_cn
        _do_quant_cn, _ = _sq_cn('sdxl', 'int8')
        quantized = False
        if _do_quant_cn and not IS_MAC:
            try:
                from optimum.quanto import quantize, freeze, qint8
            except ImportError:
                import subprocess, sys
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import quantize, freeze, qint8

            try:
                # Vérifier si le cache quantifié existe
                from core.preload import get_quantized_cache_path, is_quantized_cached
                cache_path = get_quantized_cache_path("controlnet_depth", "int8")

                if is_quantized_cached("controlnet_depth", "int8"):
                    print(f"[MM] Chargement ControlNet depuis cache (int8)...")
                    cached_state = torch.load(cache_path, map_location="cpu", weights_only=False)
                    _safe_quantize(self._controlnet_model, weights=qint8)
                    try:
                        _safe_freeze(self._controlnet_model)
                    except Exception:
                        pass  # Normal sur Windows sans compilateur C++
                    self._controlnet_model.load_state_dict(cached_state, strict=False)
                    print(f"[MM] ControlNet chargé depuis cache (int8)")
                else:
                    _safe_quantize(self._controlnet_model, weights=qint8)
                    _safe_freeze(self._controlnet_model)
                    torch.save(self._controlnet_model.state_dict(), cache_path)
                    print(f"[MM] ControlNet quantifié et mis en cache (int8)")
                quantized = True
            except Exception as e:
                print(f"[MM] Quantification ControlNet skip: {e}")

        # GPU direct — ControlNet tourne AVEC la diffusion mais ~180MB int8
        # Toujours en CUDA dès 6GB (sera bougé dans le pipeline de toute façon)
        q_str = " int8" if quantized else ""
        _target = "mps" if IS_MAC else ("cuda" if VRAM_GB >= 6 else None)
        if _target:
            try:
                self._controlnet_model.to(_target)
            except (NotImplementedError, RuntimeError):
                print(f"[MM] ControlNet: meta tensors persistent, to_empty fallback")
                sd = {k: v for k, v in self._controlnet_model.state_dict().items() if v.device.type != "meta"}
                self._controlnet_model.to_empty(device="cpu")
                self._controlnet_model.load_state_dict(sd, strict=False, assign=True)
                self._controlnet_model.to(_target)
        dev_str = _target.upper() if _target else "CPU"
        print(f"[MM] Ready: ControlNet Depth Small{q_str} ({dev_str})")
        _publish_runtime_progress(
            "download_controlnet",
            100,
            100,
            "ControlNet Depth prêt",
        )

        # Stocker la ref depth pour swap ultérieur
        self._controlnet_depth = self._controlnet_model
        self._active_controlnet_type = 'depth'

    def _load_controlnet_openpose(self):
        """Charge ControlNet OpenPose pour SDXL. Lazy load + INT8."""
        if self._controlnet_openpose is not None:
            return

        from diffusers import ControlNetModel
        from core.models import custom_cache, IS_MAC, VRAM_GB

        print("[MM] Loading ControlNet OpenPose SDXL...")
        _publish_runtime_progress(
            "load_openpose",
            8,
            100,
            "Préparation ControlNet OpenPose...",
        )
        _cn_repo = "thibaud/controlnet-openpose-sdxl-1.0"
        try:
            cn = ControlNetModel.from_pretrained(
                _cn_repo, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
                local_files_only=True,
            )
        except OSError:
            _publish_runtime_progress(
                "download_openpose",
                12,
                100,
                "Téléchargement ControlNet OpenPose (~5GB)...",
            )
            cn = ControlNetModel.from_pretrained(
                _cn_repo, torch_dtype=TORCH_DTYPE, cache_dir=custom_cache,
            )
        _publish_runtime_progress(
            "load_openpose",
            55,
            100,
            "ControlNet OpenPose chargé",
        )

        # INT8 quantification (same pattern as depth)
        from core.models.gpu_profile import should_quantize as _sq_cn
        _do_quant_cn, _ = _sq_cn('sdxl', 'int8')
        quantized = False
        if _do_quant_cn and not IS_MAC:
            try:
                from optimum.quanto import quantize, freeze, qint8
                from core.preload import get_quantized_cache_path, is_quantized_cached
                cache_path = get_quantized_cache_path("controlnet_openpose", "int8")

                if is_quantized_cached("controlnet_openpose", "int8"):
                    print(f"[MM] Chargement ControlNet OpenPose depuis cache (int8)...")
                    _publish_runtime_progress(
                        "quantize_openpose",
                        70,
                        100,
                        "Chargement cache OpenPose INT8...",
                    )
                    cached_state = torch.load(cache_path, map_location="cpu", weights_only=False)
                    _safe_quantize(cn, weights=qint8)
                    try:
                        _safe_freeze(cn)
                    except Exception:
                        pass
                    cn.load_state_dict(cached_state, strict=False)
                    print(f"[MM] ControlNet OpenPose chargé depuis cache (int8)")
                else:
                    print(f"[MM] Quantification ControlNet OpenPose INT8...")
                    _publish_runtime_progress(
                        "quantize_openpose",
                        72,
                        100,
                        "Quantification ControlNet OpenPose INT8...",
                    )
                    _safe_quantize(cn, weights=qint8)
                    _safe_freeze(cn)
                    torch.save(cn.state_dict(), cache_path)
                    print(f"[MM] ControlNet OpenPose quantifié et mis en cache (int8)")
                quantized = True
            except Exception as e:
                print(f"[MM] Quantification ControlNet OpenPose skip: {e}")

        q_str = " int8" if quantized else ""
        # Garder sur CPU — sera mis sur CUDA seulement lors du swap
        self._controlnet_openpose = cn
        print(f"[MM] Ready: ControlNet OpenPose SDXL{q_str} (CPU, prêt pour swap)")
        _publish_runtime_progress(
            "load_openpose",
            100,
            100,
            "ControlNet OpenPose prêt",
        )

    def swap_controlnet(self, cn_type='depth'):
        """Swap le ControlNet actif dans le pipeline (depth ↔ openpose).
        Déplace l'ancien sur CPU, le nouveau sur CUDA."""
        if cn_type == self._active_controlnet_type:
            return
        if self._inpaint_pipe is None:
            return

        from core.models import VRAM_GB, IS_MAC
        _device = "mps" if IS_MAC else ("cuda" if VRAM_GB >= 6 else "cpu")

        if cn_type == 'openpose':
            if self._controlnet_openpose is None:
                self._load_controlnet_openpose()
            # Depth → CPU, OpenPose → CUDA
            if self._controlnet_depth is not None:
                self._controlnet_depth.to("cpu")
            self._controlnet_openpose.to(_device)
            self._inpaint_pipe.controlnet = self._controlnet_openpose
            self._controlnet_model = self._controlnet_openpose
            self._active_controlnet_type = 'openpose'
            print(f"[MM] ControlNet swapped: depth → openpose ({_device})")
        else:
            if self._controlnet_depth is None:
                return
            # OpenPose → CPU, Depth → CUDA
            if self._controlnet_openpose is not None:
                self._controlnet_openpose.to("cpu")
            self._controlnet_depth.to(_device)
            self._inpaint_pipe.controlnet = self._controlnet_depth
            self._controlnet_model = self._controlnet_depth
            self._active_controlnet_type = 'depth'
            print(f"[MM] ControlNet swapped: openpose → depth ({_device})")
        torch.cuda.empty_cache()

    def _load_depth_estimator(self):
        """Charge Depth Anything V2 Small pour l'estimation de profondeur."""
        if self._depth_estimator is not None and self._depth_processor is not None:
            return
        if self._depth_estimator is not None or self._depth_processor is not None:
            # A previous parallel preload may have left a half-initialized state.
            self._depth_estimator = None
            self._depth_processor = None

        from transformers import AutoModelForDepthEstimation, AutoImageProcessor
        from core.models import custom_cache, IS_MAC, VRAM_GB

        print("[MM] Loading Depth Anything V2 Small...")
        _publish_runtime_progress(
            "download_depth",
            8,
            100,
            "Préparation Depth Anything...",
        )
        model_id = "depth-anything/Depth-Anything-V2-Small-hf"

        def _load_depth_from_hf(*, local_files_only=False):
            processor = AutoImageProcessor.from_pretrained(
                model_id,
                cache_dir=custom_cache,
                local_files_only=local_files_only,
            )
            estimator = AutoModelForDepthEstimation.from_pretrained(
                model_id,
                torch_dtype=torch.float32,
                cache_dir=custom_cache,
                low_cpu_mem_usage=False,
                local_files_only=local_files_only,
            )
            return processor, estimator

        try:
            self._depth_processor, self._depth_estimator = _load_depth_from_hf(local_files_only=True)
        except Exception as e:
            self._depth_processor = None
            self._depth_estimator = None
            print(f"[MM] Depth local cache unavailable/corrupt ({type(e).__name__}: {e})")
            _publish_runtime_progress(
                "download_depth",
                10,
                100,
                "Téléchargement Depth Anything...",
            )
            try:
                self._depth_processor, self._depth_estimator = _load_depth_from_hf(local_files_only=False)
            except Exception as download_error:
                self._depth_processor = None
                self._depth_estimator = None
                print(f"[MM] Depth estimator unavailable ({type(download_error).__name__}: {download_error})")
                _publish_runtime_progress(
                    "download_depth",
                    100,
                    100,
                    "Depth indisponible, fallback sans depth",
                )
                return

        self._depth_estimator.eval()

        # Fix meta tensors (parallel loading race with init_empty_weights)
        _fix_meta_params(self._depth_estimator, "Depth Estimator")
        _materialize_module(self._depth_estimator, "Depth Estimator")

        # GPU direct — ~100MB, tourne avant la diffusion → pas de conflit VRAM
        _target = "mps" if IS_MAC else ("cuda" if VRAM_GB >= 6 else None)
        if _target:
            try:
                self._depth_estimator.to(_target)
            except (NotImplementedError, RuntimeError, AssertionError) as e:
                print(f"[MM] Depth: GPU placement failed ({e}), trying CPU-safe fallback")
                try:
                    sd = {k: v for k, v in self._depth_estimator.state_dict().items() if v.device.type != "meta"}
                    self._depth_estimator.to_empty(device="cpu")
                    self._depth_estimator.load_state_dict(sd, strict=False, assign=True)
                    self._depth_estimator.to(_target)
                except Exception as fallback_error:
                    print(f"[MM] Depth: keeping estimator on CPU ({fallback_error})")
                    _target = None
        dev_str = _target.upper() if _target else "CPU"
        print(f"[MM] Ready: Depth Anything V2 Small (~100MB, {dev_str})")
        _publish_runtime_progress(
            "download_depth",
            100,
            100,
            "Depth Anything prêt",
        )

    @staticmethod
    def _pipeline_has_meta_tensors(pipe):
        """Vérifie si un pipeline a des meta tensors (= poids pas chargés)."""
        for comp_name in ('unet', 'text_encoder', 'text_encoder_2', 'vae'):
            comp = getattr(pipe, comp_name, None)
            if comp is not None:
                for _, p in comp.named_parameters():
                    if p.is_meta:
                        return True
        return False

    @staticmethod
    def _reload_meta_components(pipe, model_id, cache_dir=None):
        """Recharge les state dicts des composants avec meta tensors depuis safetensors.

        Utilise load_state_dict(assign=True) pour écraser les meta tensors
        avec les vrais poids du fichier safetensors. Retourne True si réussi.
        """
        try:
            from safetensors.torch import load_file
            from huggingface_hub import try_to_load_from_cache
        except ImportError:
            return False

        _comp_files = {
            'unet': 'unet/diffusion_pytorch_model.safetensors',
            'text_encoder': 'text_encoder/model.safetensors',
            'text_encoder_2': 'text_encoder_2/model.safetensors',
            'vae': 'vae/diffusion_pytorch_model.safetensors',
        }
        any_fixed = False
        for comp_name, filename in _comp_files.items():
            comp = getattr(pipe, comp_name, None)
            if comp is None:
                continue
            has_meta = any(p.is_meta for _, p in comp.named_parameters())
            if not has_meta:
                continue

            # Restore clean register_parameter first (may be patched from parallel loading)
            _restore_register_parameter()

            # Trouver le fichier dans le cache HF
            import os as _os
            cached = try_to_load_from_cache(model_id, filename, cache_dir=cache_dir)
            if cached is None or not isinstance(cached, str) or not _os.path.isfile(str(cached)):
                print(f"[MM] {comp_name}: safetensors pas en cache, skip reload")
                _fix_meta_params(comp, comp_name)
                any_fixed = True
                continue
            try:
                sd = load_file(cached)

                # Method 1: load_state_dict with assign=True
                comp.load_state_dict(sd, strict=False, assign=True)
                still_meta = any(p.is_meta for _, p in comp.named_parameters())
                if not still_meta:
                    print(f"[MM] {comp_name}: meta tensors fixés via reload safetensors")
                    any_fixed = True
                    continue

                # Method 2: to_empty + load_state_dict (copy_ mode)
                print(f"[MM] {comp_name}: assign=True insuffisant, to_empty + reload...")
                comp.to_empty(device="cpu")
                comp.load_state_dict(sd, strict=False)
                still_meta = any(p.is_meta for _, p in comp.named_parameters())
                if not still_meta:
                    print(f"[MM] {comp_name}: meta tensors fixés via to_empty + reload")
                    any_fixed = True
                    continue

                # Method 3: manual parameter assignment (handles tied/derived weights)
                print(f"[MM] {comp_name}: to_empty insuffisant, manual assignment...")
                for key, value in sd.items():
                    parts = key.split('.')
                    target = comp
                    try:
                        for part in parts[:-1]:
                            target = getattr(target, part)
                        param_name = parts[-1]
                        if param_name in target._parameters and target._parameters[param_name] is not None:
                            if target._parameters[param_name].is_meta:
                                target._parameters[param_name] = torch.nn.Parameter(
                                    value, requires_grad=target._parameters[param_name].requires_grad
                                )
                        elif param_name in target._buffers and target._buffers[param_name] is not None:
                            if target._buffers[param_name].is_meta:
                                target._buffers[param_name] = value
                    except (AttributeError, KeyError):
                        pass

                # Tie weights if available (CLIP has tied embeddings)
                if hasattr(comp, 'tie_weights'):
                    comp.tie_weights()

                # Zero-fill anything still meta (last resort)
                remaining = sum(1 for _, p in comp.named_parameters() if p.is_meta)
                if remaining > 0:
                    print(f"[MM] {comp_name}: {remaining} meta tensors restants, zero-fill")
                    _fix_meta_params(comp, comp_name)
                else:
                    print(f"[MM] {comp_name}: meta tensors fixés via manual assignment")
                any_fixed = True

            except Exception as e:
                print(f"[MM] {comp_name}: reload safetensors échoué: {e}")
                _fix_meta_params(comp, comp_name)
                any_fixed = True

        # Vérifier s'il reste des meta tensors
        still_meta = ModelManager._pipeline_has_meta_tensors(pipe)
        if still_meta:
            print(f"[MM] WARN: meta tensors persistent après reload")
            # Dernier recours: _fix_meta_params sur tout
            for comp_name in ('unet', 'text_encoder', 'text_encoder_2', 'vae'):
                comp = getattr(pipe, comp_name, None)
                if comp is not None:
                    _fix_meta_params(comp, comp_name)
            still_meta = ModelManager._pipeline_has_meta_tensors(pipe)

        return not still_meta

    def _try_load_pretrained_pipeline(self, pipeline_cls, model_id, load_kwargs, **extra_kwargs):
        """
        Charge un pipeline from_pretrained avec recovery automatique:
        1. local_files_only + variant=fp16
        2. local_files_only sans variant (si pas de fp16)
        3. avec réseau sans variant (si cache corrompu/manquant)
        4. clean cache corrompu + retry réseau (si fichiers incomplets)
        Vérifie après chaque étape que les poids sont bien chargés (pas de meta tensors).
        """
        from core.models._legacy import custom_cache
        import os

        # Étape 1: essai local + variant fp16
        try:
            pipe = pipeline_cls.from_pretrained(model_id, **load_kwargs, **extra_kwargs)
            if not self._pipeline_has_meta_tensors(pipe):
                return pipe
            print(f"[MM] Chargement local fp16 incomplet (meta tensors), retry...")
            del pipe
        except (OSError, ValueError, EnvironmentError):
            pass

        # Étape 2: sans variant (le repo n'a peut-être pas de fp16)
        load_kwargs.pop("variant", None)
        try:
            pipe = pipeline_cls.from_pretrained(model_id, **load_kwargs, **extra_kwargs)
            if not self._pipeline_has_meta_tensors(pipe):
                return pipe
            # Meta tensors détectés — tenter reload safetensors avec assign=True
            print(f"[MM] Meta tensors détectés, reload state dicts depuis safetensors...")
            if self._reload_meta_components(pipe, model_id, load_kwargs.get("cache_dir")):
                return pipe
            print(f"[MM] Reload échoué, retry réseau...")
            del pipe
        except (OSError, ValueError, EnvironmentError):
            pass

        # Étape 3: sans local_files_only (re-télécharger)
        load_kwargs.pop("local_files_only", None)
        print(f"[MM] Re-téléchargement ({model_id})...")
        try:
            pipe = pipeline_cls.from_pretrained(model_id, **load_kwargs, **extra_kwargs)
            if not self._pipeline_has_meta_tensors(pipe):
                return pipe
            if self._reload_meta_components(pipe, model_id, load_kwargs.get("cache_dir")):
                return pipe
            print(f"[MM] Toujours des meta tensors, nettoyage cache...")
            del pipe
        except (OSError, ValueError, EnvironmentError):
            pass

        # Étape 4: nettoyer le cache corrompu et retry
        print(f"[MM] Cache corrompu, suppression et re-téléchargement complet...")
        import pathlib, shutil
        cache_dir = custom_cache or os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
        cache_name = "models--" + model_id.replace("/", "--")
        cache_path = pathlib.Path(cache_dir) / cache_name
        if cache_path.exists():
            shutil.rmtree(cache_path, ignore_errors=True)
        pipe = pipeline_cls.from_pretrained(model_id, **load_kwargs, **extra_kwargs)
        if self._pipeline_has_meta_tensors(pipe):
            self._reload_meta_components(pipe, model_id, load_kwargs.get("cache_dir"))
        return pipe

    def _load_inpaint_with_controlnet(self, model_name=None):
        """Charge le pipeline inpaint + ControlNet combiné."""
        # GGUF ne supporte pas ControlNet → fallback Diffusers
        if self._backend == "gguf":
            print("[MM] ⚠️ GGUF ne supporte pas ControlNet, fallback Diffusers")
            # Switcher temporairement en diffusers pour cette génération
            self._backend = "diffusers"

        # Reset SageAttention global si actif (évite freeze avec SDXL)
        try:
            from core.video_optimizations import reset_global_sageattention
            reset_global_sageattention()
        except Exception:
            pass

        from core.models import (
            MODELS, SINGLE_FILE_MODELS, MODEL_QUANT, get_model_loading_kwargs,
            optimize_pipeline, custom_cache, _refresh_imported_model_registries
        )
        _refresh_imported_model_registries()
        from diffusers import StableDiffusionXLControlNetInpaintPipeline, DPMSolverMultistepScheduler

        # Charger le ControlNet Depth + estimateur EN PARALLÈLE
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._load_controlnet_depth),
                executor.submit(self._load_depth_estimator)
            ]
            concurrent.futures.wait(futures)

        # CRITICAL: restore clean register_parameter after parallel loading.
        # ThreadPoolExecutor + accelerate's init_empty_weights() causes a race
        # condition where the monkey-patch leaks permanently, creating meta
        # tensors in ALL subsequent model loads (pipeline, VAE, etc.)
        _restore_register_parameter()

        # Mapping text2img → inpaint + backward compat
        INPAINT_MAPPING = {
            "epiCRealism XL": "epiCRealism XL (Moyen)",
            "epiCRealism XL Inpaint": "epiCRealism XL (Moyen)",  # backward compat
            "Juggernaut XL v9": "Juggernaut XL (Moyen)",
            "SDXL Turbo": "epiCRealism XL (Moyen)",
            "CyberRealistic Pony": "CyberRealistic Pony (Moyen)",
        }

        if model_name and model_name in INPAINT_MAPPING:
            model_name = INPAINT_MAPPING[model_name]

        if not model_name or model_name == "Automatique" or (model_name not in MODELS and model_name not in SINGLE_FILE_MODELS):
            model_name = "epiCRealism XL (Moyen)"

        if model_name in SINGLE_FILE_MODELS:
            model_id = model_name  # Utiliser le nom complet (inclut variante Fast/Moyen/Normal)
        else:
            model_id = MODELS[model_name]

        # Si même modèle déjà chargé avec ControlNet, réutiliser
        # Comparer model_name (inclut variante Fast/Moyen/Normal) et non model_id (repo, identique pour les 3)
        has_controlnet_pipe = hasattr(self._inpaint_pipe, 'controlnet') and self._inpaint_pipe.controlnet is not None
        if self._inpaint_pipe is not None and self._current_inpaint_model == model_name and self._controlnet_model is not None and has_controlnet_pipe:
            print(f"[MM] Réutilisation: {model_name} + ControlNet Depth (déjà chargé)")
            return

        print(f"[MM] Loading inpaint+controlnet: {model_name}...")

        # Nettoyage caches legacy (anciens noms de clé, ancien modèle 9-ch, caches corrompus)
        try:
            from core.preload import QUANTIZED_CACHE_DIR
            _legacy_patterns = [
                "epicrealism_int*.pt",           # ancien format pré-refactoring
                "*inpainting*_int*.pt",          # anciens modèles 9-ch (tous remplacés par 4-ch)
                "epicrealism_xl_*_int*.pt",      # cache corrompu (nom de modèle comme clé)
                "txt2img_*_int*.pt",             # ancien repo text2img séparé
                "krnl_epicrealism*_int*.pt",     # ancien repo V8-KiSS (remplacé par CrystalClear)
            ]
            for pattern in _legacy_patterns:
                for legacy in QUANTIZED_CACHE_DIR.glob(pattern):
                    legacy.unlink()
                    print(f"[MM] Cache legacy supprimé: {legacy.name}")
        except Exception:
            pass

        import time as _t_load
        _t0_load = _t_load.time()
        load_kwargs = get_model_loading_kwargs()

        model_quant = MODEL_QUANT.get(model_name, "int8")
        if model_name in SINGLE_FILE_MODELS:
            from core.models.registry import resolve_single_file_model
            sfm = SINGLE_FILE_MODELS[model_name]
            model_quant = sfm[2] if len(sfm) > 2 else "int8"
            print(f"[MM] Resolving model file ({sfm[0]})...")
            _publish_runtime_progress(
                "load_image_model",
                18,
                100,
                f"Chargement {model_name}...",
            )
            model_path = resolve_single_file_model(model_name)
            print(f"[MM] Loading from_single_file... ({_t_load.time() - _t0_load:.1f}s)")
            self._inpaint_pipe = StableDiffusionXLControlNetInpaintPipeline.from_single_file(
                model_path,
                controlnet=self._controlnet_model,
                torch_dtype=TORCH_DTYPE,
                low_cpu_memory_usage=False,
            )
            print(f"[MM] Pipeline loaded ({_t_load.time() - _t0_load:.1f}s)")
        else:
            print(f"[MM] Loading from_pretrained ({model_id})...")
            _publish_runtime_progress(
                "load_image_model",
                18,
                100,
                f"Chargement {model_name or model_id}...",
            )
            self._inpaint_pipe = self._try_load_pretrained_pipeline(
                StableDiffusionXLControlNetInpaintPipeline,
                model_id, load_kwargs, controlnet=self._controlnet_model
            )
            print(f"[MM] Pipeline loaded ({_t_load.time() - _t0_load:.1f}s)")
        _publish_runtime_progress(
            "load_image_model",
            45,
            100,
            "Pipeline image chargé",
        )

        # Fix meta tensors laissés par from_single_file (low_cpu_mem_usage=True par défaut)
        for _comp_name in ('unet', 'text_encoder', 'text_encoder_2'):
            _comp = getattr(self._inpaint_pipe, _comp_name, None)
            if _comp is not None:
                _fix_meta_params(_comp, _comp_name)

        self._inpaint_pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            self._inpaint_pipe.scheduler.config,
            algorithm_type="dpmsolver++", solver_order=2,
            use_karras_sigmas=True, lower_order_final=True,
        )
        self._inpaint_pipe.enable_vae_slicing()

        # FIX: Remplacer le VAE SDXL par la version fp16-fix
        _restore_register_parameter()  # Ensure clean state for VAE loading
        print(f"[MM] Loading VAE fp16-fix...")
        _publish_runtime_progress(
            "download_vae",
            50,
            100,
            "Préparation VAE fp16-fix...",
        )
        from diffusers import AutoencoderKL
        try:
            fixed_vae = AutoencoderKL.from_pretrained(
                "madebyollin/sdxl-vae-fp16-fix", torch_dtype=TORCH_DTYPE,
                local_files_only=True,
            )
        except OSError:
            _publish_runtime_progress(
                "download_vae",
                55,
                100,
                "Téléchargement VAE fp16-fix...",
            )
            fixed_vae = AutoencoderKL.from_pretrained(
                "madebyollin/sdxl-vae-fp16-fix", torch_dtype=TORCH_DTYPE,
            )
        self._inpaint_pipe.vae = fixed_vae
        self._inpaint_pipe.enable_vae_slicing()
        print(f"[MM] VAE remplacé par sdxl-vae-fp16-fix ({DTYPE_NAME}) ({_t_load.time() - _t0_load:.1f}s)")
        _publish_runtime_progress(
            "download_vae",
            100,
            100,
            "VAE prêt",
        )
        self._apply_imported_model_assets(model_name)

        # Optimisations: xformers/SDPA, channels_last, torch.compile
        optimize_pipeline(self._inpaint_pipe, "SDXL ControlNet")

        # Fooocus Inpaint Patch: apply weight deltas BEFORE quantization
        # Fixes VAE color shift (yellow skin) by training the UNet for inpainting
        print(f"[MM] Applying Fooocus patch... ({_t_load.time() - _t0_load:.1f}s)")
        _publish_runtime_progress(
            "download_fooocus",
            60,
            100,
            "Préparation patch Fooocus...",
        )
        fooocus_applied = False
        if self._inpaint_pipe.unet.config.in_channels == 4:
            try:
                from core.generation.fooocus_patch import apply_fooocus_patch
                fooocus_applied = apply_fooocus_patch(self._inpaint_pipe.unet, torch_dtype=TORCH_DTYPE)
            except Exception as e:
                print(f"[MM] Fooocus patch skipped: {e}")

        # Placement GPU intelligent selon profil GPU
        from core.models import IS_MAC, VRAM_GB
        from core.models.gpu_profile import should_quantize as _sq

        print(f"[MM] Quantification + placement GPU... ({_t_load.time() - _t0_load:.1f}s)")
        _publish_runtime_progress(
            "quantize_model",
            70,
            100,
            "Quantification et placement GPU...",
        )
        do_quant, quant_type = _sq('sdxl', model_quant)
        quantized = False
        q_str = ""
        if do_quant and not IS_MAC:
            try:
                from optimum.quanto import quantize, freeze, qint8, qint4
            except ImportError:
                print(f"[MM] Installation optimum-quanto...")
                import subprocess
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'optimum-quanto>=0.2.0', '-q'], check=True)
                from optimum.quanto import quantize, freeze, qint8, qint4

            # Essayer les quantifications dans l'ordre: int4 → int8 → FP16
            quant_attempts = ["int4", "int8"] if quant_type == "int4" else [quant_type]

            # Cache key = nom du modèle normalisé (pas hardcodé "epicrealism")
            _base_cache_key = model_id.replace("/", "_").replace(" ", "_").lower()
            _cache_key = _base_cache_key + ("_fooocus" if fooocus_applied else "")

            # Fix meta tensors AVANT quantification (from_pretrained low_cpu_mem_usage=True en laisse)
            _fix_meta_params(self._inpaint_pipe.unet, "unet (pre-quant)")
            # Aggressive fallback: to_empty + reload if _fix_meta_params missed anything
            _materialize_module(self._inpaint_pipe.unet, "unet")

            for quant_name in quant_attempts:
                try:
                    from core.preload import get_quantized_cache_path, is_quantized_cached
                    cache_path = get_quantized_cache_path(_cache_key, quant_name)
                    quant_weight = qint4 if quant_name == "int4" else qint8

                    # Supprimer l'ancien cache (sans _fooocus) si le nouveau existe
                    if fooocus_applied:
                        old_cache = get_quantized_cache_path(_base_cache_key, quant_name)
                        if old_cache.exists():
                            old_cache.unlink()
                            print(f"[MM] Ancien cache supprimé: {old_cache.name}")

                    _loaded_from_cache = False
                    if is_quantized_cached(_cache_key, quant_name):
                        try:
                            print(f"[MM] Chargement UNet quantifié depuis cache ({quant_name})...")
                            cached_state = torch.load(cache_path, map_location="cpu", weights_only=False)
                            _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                            _safe_freeze(self._inpaint_pipe.unet)
                            self._inpaint_pipe.unet.load_state_dict(cached_state, strict=False)
                            print(f"[MM] UNet chargé depuis cache ({quant_name})")
                            _loaded_from_cache = True
                        except Exception as cache_err:
                            print(f"[MM] Cache {quant_name} corrompu: {cache_err}")
                            print(f"[MM] Suppression cache + rechargement modèle...")
                            cache_path.unlink(missing_ok=True)
                            # Reload pipeline from scratch (quantize() corrupted the modules)
                            self._inpaint_pipe = None
                            torch.cuda.empty_cache()
                            import gc; gc.collect()
                            from diffusers import StableDiffusionXLControlNetInpaintPipeline
                            self._inpaint_pipe = StableDiffusionXLControlNetInpaintPipeline.from_pretrained(
                                model_id, controlnet=self._controlnet_model,
                                torch_dtype=TORCH_DTYPE,
                            )
                            _fix_meta_params(self._inpaint_pipe.unet, "unet (reload)")
                            if fooocus_applied:
                                from core.generation.fooocus_patch import apply_fooocus_patch
                                apply_fooocus_patch(self._inpaint_pipe.unet, torch_dtype=TORCH_DTYPE)

                    if not _loaded_from_cache:
                        print(f"[MM] Quantification UNet ({quant_name})...")
                        _safe_quantize(self._inpaint_pipe.unet, weights=quant_weight)
                        _safe_freeze(self._inpaint_pipe.unet)
                        try:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            torch.save(self._inpaint_pipe.unet.state_dict(), cache_path)
                            print(f"[MM] UNet quantifié et mis en cache ({quant_name})")
                        except Exception as save_err:
                            print(f"[MM] Erreur sauvegarde cache: {save_err}")

                    quantized = True
                    q_str = f" + {quant_name}"
                    break

                except Exception as e:
                    print(f"[MM] Quantification {quant_name} échouée: {e}")
                    import traceback
                    traceback.print_exc()
                    if quant_name == "int4":
                        print(f"[MM] Fallback vers INT8...")
                    continue

            if not quantized:
                print(f"[MM] ⚠️  ATTENTION: Quantification impossible, FP16 = LENT!")

            # Re-register Fooocus hook (quanto replaces conv_in with QConv2d, losing the hook)
            if fooocus_applied:
                from core.generation.fooocus_patch import reattach_fooocus_hook
                reattach_fooocus_hook(self._inpaint_pipe.unet)

        # Placement selon le profil GPU (quantification, offload_strategy du JSON)
        _place_sdxl_pipe(self._inpaint_pipe, model_name, quantized=quantized, has_controlnet=True)

        self._current_inpaint_model = model_name
        self._loras_loaded = {}
        self._lora_scales = {}

        # Afficher VRAM utilisée
        if torch.cuda.is_available():
            vram_used = torch.cuda.memory_allocated() / 1024**3
            vram_reserved = torch.cuda.memory_reserved() / 1024**3
            print(f"[MM] VRAM: {vram_used:.1f}GB utilisée / {vram_reserved:.1f}GB réservée / {VRAM_GB:.0f}GB total")

        # WARMUP: Pré-compile les kernels CUDA avec torch.compile (Linux uniquement)
        # Sans warmup + torch.compile, le 1er step de chaque nouvelle taille prend 12-16 sec
        # Sans torch.compile (Windows), les kernels cuDNN sont déjà pré-compilés → warmup inutile
        from core.models import USE_TORCH_COMPILE, GPU_MODEL_CONFIG, GPU_TIER
        sdxl_config = GPU_MODEL_CONFIG.get("sdxl", {}).get(GPU_TIER, {})
        needs_warmup = sdxl_config.get("warmup", False) and USE_TORCH_COMPILE

        if needs_warmup and torch.cuda.is_available():
            try:
                from PIL import Image
                import numpy as np
                from core.models import WARMUP_SIZES
                print(f"[MM] Warmup CUDA ({len(WARMUP_SIZES)} tailles, torch.compile actif)...")
                for h, w in WARMUP_SIZES:
                    dummy_img = Image.fromarray(np.zeros((h, w, 3), dtype=np.uint8))
                    dummy_mask = Image.fromarray(np.ones((h, w), dtype=np.uint8) * 255)
                    dummy_depth = Image.fromarray(np.zeros((h, w, 3), dtype=np.uint8))
                    with torch.no_grad():
                        _ = self._inpaint_pipe(
                            prompt="warmup",
                            negative_prompt="",
                            image=dummy_img,
                            mask_image=dummy_mask,
                            control_image=dummy_depth,
                            num_inference_steps=2,
                            strength=1.0,
                            guidance_scale=1.0,
                            output_type="latent",
                        )
                    print(f"[MM]   → {w}x{h} OK")
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                print("[MM] Warmup terminé - kernels compilés")
            except Exception as e:
                print(f"[MM] Warmup skip: {e}")
        elif torch.cuda.is_available():
            print(f"[MM] Warmup skip (pas de torch.compile — kernels cuDNN pré-compilés)")

        # LoRAs chargés à la demande (lazy load) pour éviter perte de temps
        # self._load_all_loras()

    _face_analyzer = None  # InsightFace (singleton)
    _insightface_checked = False
    _insightface_available = False

    def _ensure_insightface(self):
        """Installe insightface si nécessaire, retourne True si disponible.
        Auto-fix: détecte les incompatibilités numpy binaires et reinstalle."""
        # Cache résultat — ne pas retenter chaque génération
        if ModelManager._insightface_checked:
            return ModelManager._insightface_available

        try:
            from insightface.app import FaceAnalysis
            ModelManager._insightface_checked = True
            ModelManager._insightface_available = True
            return True
        except ImportError:
            print("[MM] Installation de insightface...")
            return self._install_insightface()
        except Exception as e:
            err_msg = str(e)
            if 'dtype size changed' in err_msg or 'binary incompatibility' in err_msg:
                # numpy version mismatch → auto-fix par reinstallation
                print(f"[MM] insightface numpy incompatibility detected, auto-fixing...")
                return self._install_insightface(force=True)
            print(f"[MM] insightface indisponible: {e}")
            ModelManager._insightface_checked = True
            ModelManager._insightface_available = False
            return False

    def _install_insightface(self, force=False):
        """Installe ou reinstalle insightface. Retourne True si OK.
        Si numpy binary incompat → downgrade numpy <2.0 sur disque, skip cette session."""
        try:
            if not force:
                # Installation initiale (pas encore installé)
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', 'insightface', '--quiet'],
                    capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    wheel_url = "https://github.com/Gourieff/Assets/raw/main/Insightface/insightface-0.7.3-cp312-cp312-win_amd64.whl"
                    subprocess.run(
                        [sys.executable, '-m', 'pip', 'install', wheel_url, '--quiet'],
                        check=True, timeout=300)
                # Purger modules et re-importer
                for mod_name in list(sys.modules.keys()):
                    if 'insightface' in mod_name:
                        del sys.modules[mod_name]
                from insightface.app import FaceAnalysis
                print("[MM] insightface installé")
                ModelManager._insightface_checked = True
                ModelManager._insightface_available = True
                return True
            else:
                # numpy incompat → downgrade numpy sur disque SANS re-importer
                # (numpy 2.x déjà chargé en mémoire, ne pas toucher sys.modules)
                print("[MM] Downgrade numpy pour compatibilité insightface...")
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', 'numpy>=1.26,<2.0', '--quiet'],
                    capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    print("[MM] ✓ numpy downgraded sur disque → IP-Adapter FaceID actif au prochain démarrage")
                else:
                    print(f"[MM] numpy downgrade failed: {result.stderr[-300:]}")
                # Cette session: insightface indisponible (numpy 2.x en mémoire)
                ModelManager._insightface_checked = True
                ModelManager._insightface_available = False
                return False
        except Exception as e:
            print(f"[MM] insightface non disponible: {e}")
            ModelManager._insightface_checked = True
            ModelManager._insightface_available = False
            return False

    def _load_ip_adapter_face(self):
        """Charge IP-Adapter FaceID pour préserver le visage."""
        if self._ip_adapter_loaded:
            return

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter: pas de pipeline inpaint")
            return

        # Installer insightface si nécessaire
        if not self._ensure_insightface():
            return

        print("[MM] Loading IP-Adapter FaceID...")
        try:
            self._inpaint_pipe.load_ip_adapter(
                "h94/IP-Adapter-FaceID",
                subfolder=None,
                weight_name="ip-adapter-faceid_sdxl.bin",
                image_encoder_folder=None,
            )
            # Aligner dtype des poids FaceID avec le UNet (fp16 vs bf16)
            unet_dtype = self._inpaint_pipe.unet.dtype
            if hasattr(self._inpaint_pipe.unet, 'encoder_hid_proj'):
                self._inpaint_pipe.unet.encoder_hid_proj.to(dtype=unet_dtype)
            self._ip_adapter_loaded = True
            print(f"[MM] Ready: IP-Adapter FaceID (dtype={unet_dtype}, scale set dynamically)")
        except Exception as e:
            print(f"[MM] IP-Adapter FaceID error: {e}")
            self._ip_adapter_loaded = False

    def _load_ip_adapter_style(self):
        """Charge IP-Adapter Plus (CLIP) pour style reference."""
        if self._ip_adapter_style_loaded:
            return

        # Décharger tout IP-Adapter existant d'abord
        if self._ip_adapter_loaded or self._ip_adapter_dual_loaded:
            self._unload_ip_adapter_safe()

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter Style: pas de pipeline")
            return

        print("[MM] Loading IP-Adapter SDXL (CLIP ViT-H style)...")
        try:
            # Standard IP-Adapter (pas Plus) — projection simple, pas de Perceiver resampler
            # ViT-H encoder dans models/image_encoder (1280 dim)
            self._inpaint_pipe.load_ip_adapter(
                "h94/IP-Adapter",
                subfolder="sdxl_models",
                weight_name="ip-adapter_sdxl_vit-h.safetensors",
                image_encoder_folder="models/image_encoder",
            )
            self._ip_adapter_style_loaded = True
            print("[MM] Ready: IP-Adapter SDXL (CLIP ViT-H style)")
        except Exception as e:
            print(f"[MM] IP-Adapter Style error: {e}")
            self._ip_adapter_style_loaded = False

    def _load_ip_adapter_dual(self):
        """Charge les 2 IP-Adapters simultanément (FaceID + Style CLIP)."""
        if self._ip_adapter_dual_loaded:
            return

        # Décharger tout IP-Adapter existant d'abord
        if self._ip_adapter_loaded or self._ip_adapter_style_loaded:
            self._unload_ip_adapter_safe()

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter Dual: pas de pipeline")
            return

        # Installer insightface si nécessaire (pour FaceID)
        if not self._ensure_insightface():
            # Fallback: charger seulement le style
            print("[MM] insightface indisponible, fallback style seul")
            self._load_ip_adapter_style()
            return

        print("[MM] Loading IP-Adapter Dual (Style CLIP + FaceID)...")
        try:
            # FaceID repo n'a pas la structure standard → pré-charger comme dict
            # IMPORTANT: Style (repo) DOIT être en premier pour que diffusers charge
            # l'image_encoder depuis le repo (impossible depuis un dict)
            # Ordre: [0]=Style CLIP, [1]=FaceID → ip_adapter_image_embeds=[style, face]
            from huggingface_hub import hf_hub_download
            faceid_path = hf_hub_download(
                "h94/IP-Adapter-FaceID",
                filename="ip-adapter-faceid_sdxl.bin",
            )
            faceid_sd = torch.load(faceid_path, map_location="cpu", weights_only=False)

            self._inpaint_pipe.load_ip_adapter(
                ["h94/IP-Adapter", faceid_sd],
                subfolder=["sdxl_models", None],
                weight_name=["ip-adapter_sdxl_vit-h.safetensors", None],
                image_encoder_folder="models/image_encoder",
            )
            self._ip_adapter_dual_loaded = True
            print("[MM] Ready: IP-Adapter Dual (Style[0] + FaceID[1])")
        except Exception as e:
            print(f"[MM] IP-Adapter Dual error: {e}")
            import traceback
            traceback.print_exc()
            self._ip_adapter_dual_loaded = False

    def _unload_ip_adapter_safe(self):
        """Décharge IP-Adapter en préservant les hooks d'offload.

        unload_ip_adapter() casse les hooks model_cpu_offload/group_offload,
        ce qui laisse le UNet sur CPU → crash "HalfTensor vs cuda.HalfTensor".
        On re-enable l'offload après le unload pour restaurer les hooks.
        """
        if not (self._ip_adapter_loaded or self._ip_adapter_style_loaded or self._ip_adapter_dual_loaded):
            return
        if self._inpaint_pipe is None:
            return
        try:
            self._inpaint_pipe.unload_ip_adapter()
            print("[MM] IP-Adapter déchargé (pas nécessaire pour cette génération)")
            # Re-enable offload hooks (unload_ip_adapter les casse)
            from core.models.gpu_profile import get_offload_strategy
            if get_offload_strategy('sdxl') != "none":
                self._inpaint_pipe.enable_model_cpu_offload()
                print("[MM] Offload hooks ré-activés après déchargement IP-Adapter")
        except Exception as e:
            print(f"[MM] Erreur déchargement IP-Adapter: {e}")
        self._ip_adapter_loaded = False
        self._ip_adapter_style_loaded = False
        self._ip_adapter_dual_loaded = False

    def extract_face_embedding(self, image):
        """Extrait le face embedding via InsightFace pour IP-Adapter FaceID."""
        import numpy as np
        import cv2

        # Bail early si insightface déjà marqué indisponible
        if ModelManager._insightface_checked and not ModelManager._insightface_available:
            print("[MM] IP-Adapter: insightface indisponible (skip)")
            return None

        try:
            if self._face_analyzer is None:
                from insightface.app import FaceAnalysis
                self._face_analyzer = FaceAnalysis(
                    name="buffalo_l",
                    providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                )
                self._face_analyzer.prepare(ctx_id=0, det_size=(640, 640))

            # PIL → cv2 BGR
            if hasattr(image, 'mode'):
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                image_cv2 = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            else:
                image_cv2 = image

            faces = self._face_analyzer.get(image_cv2)
            if not faces:
                print("[MM] IP-Adapter: aucun visage détecté")
                return None

            def _face_rank(face):
                bbox = getattr(face, "bbox", None)
                if bbox is None:
                    area = 0.0
                else:
                    x1, y1, x2, y2 = bbox
                    area = max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))
                score = float(getattr(face, "det_score", 0.0) or 0.0)
                return area * max(score, 0.01)

            selected_face = max(faces, key=_face_rank)
            if len(faces) > 1:
                print(f"[MM] IP-Adapter: {len(faces)} visages détectés, meilleur visage utilisé")
            selected_score = float(getattr(selected_face, "det_score", 0.0) or 0.0)
            if selected_score < 0.45:
                print(f"[MM] IP-Adapter: visage trop incertain (score={selected_score:.2f}), ignoré")
                return None

            # Embedding normalisé [1, 1, 512]
            faceid_embed = torch.from_numpy(selected_face.normed_embedding).unsqueeze(0)
            ref_embeds = faceid_embed.unsqueeze(0)  # [1, 1, 512]
            neg_embeds = torch.zeros_like(ref_embeds)
            # Utiliser le dtype du pipeline (bf16 sur high-end, fp16 sinon)
            pipe_dtype = torch.float16
            if self._inpaint_pipe is not None and hasattr(self._inpaint_pipe, 'unet'):
                pipe_dtype = self._inpaint_pipe.unet.dtype
            id_embeds = torch.cat([neg_embeds, ref_embeds]).to(dtype=pipe_dtype, device="cuda")
            bbox = getattr(selected_face, "bbox", None)
            if bbox is not None:
                x1, y1, x2, y2 = bbox
                area_pct = (
                    max(0.0, float(x2 - x1))
                    * max(0.0, float(y2 - y1))
                    / max(1.0, float(image_cv2.shape[0] * image_cv2.shape[1]))
                )
                print(
                    f"[MM] IP-Adapter: face embedding extrait "
                    f"(score={selected_score:.2f}, face={area_pct:.1%})"
                )
            else:
                print(f"[MM] IP-Adapter: face embedding extrait (score={selected_score:.2f})")
            return id_embeds

        except Exception as e:
            print(f"[MM] IP-Adapter face embedding error: {e}")
            return None

    def extract_style_embedding(self, image):
        """Extrait le CLIP embedding pour IP-Adapter style (pose, corps, ambiance).

        Utilisé en mode dual (face+style) pour pré-calculer les embeddings style.
        En mode style seul, diffusers encode l'image PIL en interne via ip_adapter_image.
        """
        try:
            pipe = self._inpaint_pipe
            if pipe is None:
                print("[MM] IP-Adapter Style: pas de pipeline")
                return None

            # Le image_encoder et feature_extractor sont chargés par load_ip_adapter
            feature_extractor = pipe.feature_extractor
            image_encoder = pipe.image_encoder

            if feature_extractor is None or image_encoder is None:
                print("[MM] IP-Adapter Style: image_encoder ou feature_extractor manquant")
                return None

            if hasattr(image, 'mode') and image.mode != 'RGB':
                image = image.convert('RGB')

            clip_image = feature_extractor(images=image, return_tensors="pt").pixel_values
            clip_image = clip_image.to(device="cuda", dtype=torch.float16)

            # Déplacer l'encoder sur CUDA si nécessaire (model_cpu_offload le laisse sur CPU)
            encoder_device = next(image_encoder.parameters()).device
            if encoder_device.type == "cpu":
                image_encoder.to(device="cuda", dtype=torch.float16)

            with torch.no_grad():
                # Standard adapter (non-Plus) utilise le pooled output CLIP
                image_embeds = image_encoder(clip_image).image_embeds  # [1, 1280]

            # Remettre l'encoder sur CPU pour libérer la VRAM
            if encoder_device.type == "cpu":
                image_encoder.to("cpu")
                torch.cuda.empty_cache()

            neg_embeds = torch.zeros_like(image_embeds)
            result = torch.cat([neg_embeds, image_embeds])  # [2, 1280]
            print(f"[MM] IP-Adapter Style: CLIP embedding extrait (shape={list(result.shape)})")
            return result

        except Exception as e:
            print(f"[MM] IP-Adapter style embedding error: {e}")
            import traceback
            traceback.print_exc()
            return None

    _depth_cache_hash = None
    _depth_cache_result = None

    def extract_depth(self, image):
        """Extrait une depth map RGB d'une image via Depth Anything V2."""
        if self._depth_estimator is None or self._depth_processor is None:
            self._load_depth_estimator()

        if self._depth_estimator is None:
            print("[MM] Depth estimator unavailable")
            return None

        import numpy as np
        import hashlib
        from PIL import Image as PILImage

        try:
            # Depth Anything V2 attend du RGB, pas RGBA
            if hasattr(image, 'mode') and image.mode != 'RGB':
                image = image.convert('RGB')

            # Cache: même image → même depth map
            _thumb = image.copy()
            _thumb.thumbnail((16, 16), PILImage.BILINEAR)
            _hash = hashlib.md5(_thumb.tobytes()).hexdigest()
            if _hash == ModelManager._depth_cache_hash and ModelManager._depth_cache_result is not None:
                print(f"[MM] Depth cache hit → skip extraction")
                return ModelManager._depth_cache_result.copy()

            device = next(self._depth_estimator.parameters()).device
            inputs = self._depth_processor(images=image, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._depth_estimator(**inputs)
                depth = outputs.predicted_depth  # (1, H, W)

            # Interpoler à la taille originale
            depth = torch.nn.functional.interpolate(
                depth.unsqueeze(0),
                size=image.size[::-1],  # (H, W)
                mode="bicubic",
                align_corners=False,
            ).squeeze()

            # Normaliser en [0, 255] et convertir en RGB
            depth_np = depth.cpu().numpy()
            depth_np = (depth_np - depth_np.min()) / (depth_np.max() - depth_np.min() + 1e-8) * 255
            depth_rgb = np.stack([depth_np] * 3, axis=-1).astype(np.uint8)
            _result = PILImage.fromarray(depth_rgb)
            ModelManager._depth_cache_hash = _hash
            ModelManager._depth_cache_result = _result.copy()
            print(f"[MM] Depth map extracted ({image.size[0]}x{image.size[1]})")
            return _result

        except Exception as e:
            print(f"[MM] Depth extraction error: {e}")
            return None

    # =========================================================
    # GET PIPELINE
    # =========================================================

    def get_pipeline(self, task_type):
        """Retourne le pipeline chargé pour le type de tâche."""
        if task_type in ('inpaint', 'edit', 'expand', 'inpaint_controlnet', 'text2img'):
            # Si backend GGUF et pipeline GGUF chargé, retourner celui-ci
            if self._backend == "gguf" and self._gguf_pipe is not None:
                return self._gguf_pipe
            return self._inpaint_pipe
        elif task_type == 'video':
            return self._video_pipe
        elif task_type == 'video_upscale':
            return self._ltx_upsample_pipe
        elif task_type == 'upscale':
            return self._upscale_model
        return None

    def is_gguf_pipeline(self) -> bool:
        """Retourne True si le pipeline actuel est GGUF."""
        return self._backend == "gguf" and self._gguf_pipe is not None

    def get_caption_model(self):
        """Retourne le modèle de caption (charge si nécessaire)."""
        self._load_caption()
        return self._caption_model, self._caption_processor

    # =========================================================
    # CLEANUP
    # =========================================================

    def cleanup(self):
        """Appelé après génération. Décharge uniquement les utilitaires temporaires.
        Les pipelines principaux (inpaint, video) restent chargés
        pour être réutilisés sans re-téléchargement."""
        with self._lock:
            self._unload_utils()        # BLIP, ZoeDepth, upscale
            self._unload_segmentation() # SegFormer, GroundingDINO
            self._clear_memory(aggressive=False)

    # =========================================================
    # STATUS
    # =========================================================

    def get_status(self):
        """État VRAM pour le monitoring frontend."""
        total_gb = 0
        used_gb = 0
        free_gb = 0
        models_loaded = []
        cuda_details = {}

        # nvidia-smi pour la VRAM totale (inclut tout: CUDA, DirectX, autres apps)
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.total,memory.used,memory.free', '--format=csv,noheader,nounits'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(',')
                if len(parts) >= 3:
                    total_gb = float(parts[0].strip()) / 1024
                    used_gb = float(parts[1].strip()) / 1024
                    free_gb = float(parts[2].strip()) / 1024
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            if torch.cuda.is_available():
                total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
                used_gb = torch.cuda.memory_reserved() / 1024**3
                free_gb = total_gb - used_gb

        # Détails mémoire CUDA PyTorch
        if torch.cuda.is_available():
            cuda_details = {
                'reserved_gb': round(torch.cuda.memory_reserved() / 1024**3, 2),
                'allocated_gb': round(torch.cuda.memory_allocated() / 1024**3, 2),
                'cached_gb': round((torch.cuda.memory_reserved() - torch.cuda.memory_allocated()) / 1024**3, 2),
            }

        # Modèles diffusers
        if self._inpaint_pipe is not None:
            model_info = f"inpaint:{self._current_inpaint_model}"
            # Ajouter info quantification si applicable
            if hasattr(self._inpaint_pipe, 'unet') and hasattr(self._inpaint_pipe.unet, '_hf_hook'):
                model_info += " (offload)"
            models_loaded.append(model_info)

        if self._video_pipe is not None:
            from core.models import VIDEO_MODELS
            vid_name = VIDEO_MODELS.get(self._current_video_model, {}).get("name", self._current_video_model or "video")
            models_loaded.append(f"video:{vid_name}")
        if self._outpaint_pipe is not None:
            models_loaded.append("outpaint")
        if self._caption_model is not None:
            models_loaded.append("caption:Florence")
        if self._upscale_model is not None:
            models_loaded.append("upscale:RealESRGAN")

        # GGUF
        if self._gguf_pipe is not None:
            models_loaded.append(f"gguf:{self._current_inpaint_model}({self._gguf_quant})")

        # ControlNet et Depth
        if self._controlnet_model is not None:
            models_loaded.append("controlnet:Depth")
        if self._depth_estimator is not None:
            models_loaded.append("depth:DepthAnything")

        # IP-Adapter
        if self._ip_adapter_dual_loaded:
            models_loaded.append("ip-adapter:FaceID+Style")
        elif self._ip_adapter_loaded:
            models_loaded.append("ip-adapter:FaceID")
        elif self._ip_adapter_style_loaded:
            models_loaded.append("ip-adapter:Style")

        # LoRAs chargés
        if self._loras_loaded:
            for name, loaded in self._loras_loaded.items():
                if loaded:
                    scale = self._lora_scales.get(name, 0)
                    models_loaded.append(f"lora:{name}(scale={scale})")

        # Segmentation — seulement les modèles GPU (GroundingDINO, Sapiens)
        # SCHP, B2, B4 sont sur CPU/RAM → affichés dans le RAM status
        try:
            from core.segmentation import get_segmentation_status
            seg = get_segmentation_status()
            if seg.get('grounding_dino'):
                models_loaded.append('segmentation:GroundingDINO')
        except Exception:
            pass

        # DWPose (body estimation)
        try:
            from core.body_estimation import _dwpose_model
            if _dwpose_model is not None:
                models_loaded.append('pose:DWPose')
        except Exception:
            pass

        # Florence — CPU/RAM → affichée dans le RAM status, pas ici

        # Ollama
        try:
            from core.ollama_service import get_loaded_models
            for m in get_loaded_models():
                models_loaded.append(f"ollama:{m}")
        except Exception:
            pass

        return {
            'total_gb': round(total_gb, 2),
            'used_gb': round(used_gb, 2),
            'free_gb': round(free_gb, 2),
            'cuda_details': cuda_details,
            'models_loaded': models_loaded,
            'backend': self._backend,
            'gguf_quant': self._gguf_quant if self._backend == 'gguf' else None,
        }
