"""Backend, unload, memory, and quantization helpers for ModelManager."""

import gc
import subprocess
import sys

import torch

from core.models import IS_HIGH_END_GPU, VRAM_GB


class ModelManagerMemoryMixin:
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


