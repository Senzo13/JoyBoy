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

import os
import subprocess
import threading

import torch

from core.models import IS_HIGH_END_GPU, VRAM_GB
from core.models.manager_support import _restore_register_parameter
from core.models.manager_controlnet import ModelManagerControlNetMixin
from core.models.manager_flux_loaders import ModelManagerFluxLoaderMixin
from core.models.manager_ip_adapter import ModelManagerIPAdapterMixin
from core.models.manager_lora import ModelManagerLoraMixin
from core.models.manager_memory import ModelManagerMemoryMixin
from core.models.manager_sdxl_loaders import ModelManagerSDXLLoaderMixin
from core.models.manager_utility_loaders import ModelManagerUtilityLoaderMixin
from core.infra.gpu_processes import list_gpu_processes

class ModelManager(
    ModelManagerMemoryMixin,
    ModelManagerLoraMixin,
    ModelManagerUtilityLoaderMixin,
    ModelManagerControlNetMixin,
    ModelManagerIPAdapterMixin,
    ModelManagerSDXLLoaderMixin,
    ModelManagerFluxLoaderMixin,
):
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
        gpu_processes = []

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
                'device_count': torch.cuda.device_count(),
                'reserved_gb': round(torch.cuda.memory_reserved() / 1024**3, 2),
                'allocated_gb': round(torch.cuda.memory_allocated() / 1024**3, 2),
                'cached_gb': round((torch.cuda.memory_reserved() - torch.cuda.memory_allocated()) / 1024**3, 2),
            }

        gpu_processes = list_gpu_processes()

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
            'gpu_processes': gpu_processes,
            'models_loaded': models_loaded,
            'backend': self._backend,
            'gguf_quant': self._gguf_quant if self._backend == 'gguf' else None,
        }
