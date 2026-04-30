"""Video and lightweight utility loaders for ModelManager."""

import gc

import torch


class ModelManagerUtilityLoaderMixin:
    def _video_oom_fallback_env(self, model_name):
        env = {
            "JOYBOY_VIDEO_FORCE_CPU_OFFLOAD": "1",
            "JOYBOY_FASTWAN_FORCE_OFFLOAD": "1",
        }
        if model_name in {"framepack", "framepack-fast"}:
            env["JOYBOY_FRAMEPACK_FORCE_MODEL_CPU_OFFLOAD"] = "1"
            env["JOYBOY_FRAMEPACK_GPU_DIRECT"] = "0"
        if str(model_name or "").startswith("wan-native-"):
            env["JOYBOY_WAN_NATIVE_FORCE_OFFLOAD"] = "1"
        if str(model_name or "").startswith("lightx2v-"):
            env["JOYBOY_LIGHTX2V_FORCE_OFFLOAD"] = "1"
        return env

    def _load_video_once(self, model_name, custom_cache):
        from core import video_loader

        if model_name == "svd":
            return video_loader.load_svd(custom_cache)
        if model_name == "cogvideox":
            return video_loader.load_cogvideox(custom_cache)
        if model_name == "cogvideox-q4":
            return video_loader.load_cogvideox_q4(custom_cache)
        if model_name == "cogvideox-2b":
            return video_loader.load_cogvideox_2b(custom_cache)
        if model_name == "wan":
            return video_loader.load_wan_21_14b(custom_cache)
        if model_name == "wan22":
            return video_loader.load_wan22_a14b(custom_cache)
        if model_name == "hunyuan":
            return video_loader.load_hunyuan(custom_cache)
        if model_name in ("wan22-5b", "fastwan"):
            return video_loader.load_wan22_5b(model_name, custom_cache)
        if model_name == "wan22-t2v-14b":
            return video_loader.load_wan22_t2v_14b(custom_cache)
        if model_name == "ltx":
            return video_loader.load_ltx(custom_cache)
        if model_name in ("framepack", "framepack-fast"):
            return video_loader.load_framepack(custom_cache)
        if model_name == "ltx2":
            return video_loader.load_ltx2(custom_cache)
        if model_name == "ltx2_fp8":
            return video_loader.load_ltx2_fp8(custom_cache)
        if model_name == "ltx23_fp8":
            return video_loader.load_ltx2_fp8(custom_cache, model_name)
        if model_name in ("wan-native-5b", "wan-native-14b"):
            return video_loader.load_wan_native(model_name, custom_cache)
        if str(model_name or "").startswith("lightx2v-"):
            return video_loader.load_lightx2v(model_name, custom_cache)
        raise ValueError(f"Modele video inconnu: {model_name}")

    def _load_video(self, model_name=None):
        """Charge un modele video.

        Delegue le chargement aux fonctions specialisees dans core/video_loader.py.
        """
        from core.models import custom_cache
        from core.generation.video_optimizations import is_cuda_oom_error, temporary_env

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

        try:
            result = self._load_video_once(model_name, custom_cache)
        except RuntimeError as exc:
            if not is_cuda_oom_error(exc):
                raise
            print(f"[MM] CUDA OOM pendant le chargement video ({model_name}); retry en offload...")
            self._unload_video()
            self._clear_memory(aggressive=True)
            with temporary_env(self._video_oom_fallback_env(model_name)):
                result = self._load_video_once(model_name, custom_cache)

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

