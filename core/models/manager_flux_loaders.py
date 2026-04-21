"""Flux and GGUF image loaders for ModelManager."""

import gc
import subprocess
import sys

import torch

from core.models import IS_MAC, TORCH_DTYPE, VRAM_GB
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


class ModelManagerFluxLoaderMixin:
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


