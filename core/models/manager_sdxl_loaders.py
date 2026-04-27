"""SDXL inpaint and text-to-image loaders for ModelManager."""

import gc
import subprocess
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
    _move_pipe_to_cuda,
    _place_flux_int8_pipe,
    _place_sdxl_pipe,
    _publish_runtime_progress,
    _safe_freeze,
    _safe_quantize,
)


class ModelManagerSDXLLoaderMixin:
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

        register_sdnq_for_diffusers()
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
                    **single_file_sdxl_config_kwargs(custom_cache),
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
            sdnq_quantized = is_sdnq_quantized_model(self._inpaint_pipe.unet)
            quantized_ok = sdnq_quantized
            if sdnq_quantized:
                print("[MM] SDNQ pré-quantifié détecté sur le UNet SDXL")
            elif do_quant and not IS_MAC:
                self._inpaint_pipe.unet, quantized_ok, _sdnq_mode = apply_sdnq_post_load_quant(
                    self._inpaint_pipe.unet,
                    quant_type=quant_type,
                    label=f"SDXL UNet ({model_name})",
                    quant_conv=fooocus_applied,
                    torch_dtype=TORCH_DTYPE,
                )
                if quantized_ok:
                    sdnq_quantized = True
                    print(f"[MM] {_sdnq_mode}")
            if do_quant and not IS_MAC and not quantized_ok:
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

            _place_sdxl_pipe(self._inpaint_pipe, model_name, quantized=quantized_ok and not sdnq_quantized)

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

        register_sdnq_for_diffusers()
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
                **single_file_sdxl_config_kwargs(custom_cache),
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
        sdnq_quantized = is_sdnq_quantized_model(self._inpaint_pipe.unet)
        quantized_ok = sdnq_quantized
        if sdnq_quantized:
            print("[MM] SDNQ pré-quantifié détecté sur le UNet Text2Img")

        if do_quant and not IS_MAC and not quantized_ok:
            self._inpaint_pipe.unet, quantized_ok, _sdnq_mode = apply_sdnq_post_load_quant(
                self._inpaint_pipe.unet,
                quant_type=quant_type,
                label=f"SDXL Text2Img UNet ({model_name})",
                quant_conv=False,
                torch_dtype=TORCH_DTYPE,
            )
            if quantized_ok:
                sdnq_quantized = True
                print(f"[MM] {_sdnq_mode}")

        if do_quant and not IS_MAC and not quantized_ok:
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

        _place_sdxl_pipe(self._inpaint_pipe, model_name, quantized=quantized_ok and not sdnq_quantized)
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

