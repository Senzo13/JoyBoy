"""ControlNet, depth, and ControlNet inpaint loaders for ModelManager."""

import sys

import torch

from core.backends.sdnq_backend import (
    apply_sdnq_post_load_quant,
    is_sdnq_quantized_model,
    register_sdnq_for_diffusers,
)
from core.models import IS_MAC, TORCH_DTYPE, VRAM_GB
from core.models.hf_cache import single_file_sdxl_config_kwargs
from core.models.manager_support import (
    DTYPE_NAME,
    _fix_meta_params,
    _materialize_module,
    _place_sdxl_pipe,
    _publish_runtime_progress,
    _restore_register_parameter,
    _safe_freeze,
    _safe_quantize,
)


class ModelManagerControlNetMixin:
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
        still_meta = ModelManagerControlNetMixin._pipeline_has_meta_tensors(pipe)
        if still_meta:
            print(f"[MM] WARN: meta tensors persistent après reload")
            # Dernier recours: _fix_meta_params sur tout
            for comp_name in ('unet', 'text_encoder', 'text_encoder_2', 'vae'):
                comp = getattr(pipe, comp_name, None)
                if comp is not None:
                    _fix_meta_params(comp, comp_name)
            still_meta = ModelManagerControlNetMixin._pipeline_has_meta_tensors(pipe)

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
        register_sdnq_for_diffusers()
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
                **single_file_sdxl_config_kwargs(custom_cache),
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
        sdnq_quantized = is_sdnq_quantized_model(self._inpaint_pipe.unet)
        quantized = sdnq_quantized
        q_str = ""
        if sdnq_quantized:
            q_str = " + sdnq"
            print("[MM] SDNQ pré-quantifié détecté sur le UNet ControlNet")
        elif do_quant and not IS_MAC:
            self._inpaint_pipe.unet, quantized, _sdnq_mode = apply_sdnq_post_load_quant(
                self._inpaint_pipe.unet,
                quant_type=quant_type,
                label=f"SDXL ControlNet UNet ({model_name})",
                quant_conv=fooocus_applied,
                torch_dtype=TORCH_DTYPE,
            )
            if quantized:
                sdnq_quantized = True
                q_str = " + sdnq"
                print(f"[MM] {_sdnq_mode}")

        if do_quant and not IS_MAC and not quantized:
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
        _place_sdxl_pipe(
            self._inpaint_pipe,
            model_name,
            quantized=quantized and not sdnq_quantized,
            has_controlnet=True,
        )

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

