"""
Video generation pipeline: MMAudio, generate_video (all models).
Depends on: state.py
"""
from PIL import Image
import numpy as np
import gc
import os
import re
import torch
import time
from pathlib import Path

from core.generation.state import (
    _state, GenerationCancelledException,
    update_video_progress, clear_video_progress,
)
from core.generation.video_prompts import (
    DEFAULT_SCENE_VIDEO_PROMPT,
    DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT,
    _build_ltx2_motion_prompt,
    _build_ltx2_negative_prompt,
    _build_framepack_prompt,
    _build_video_negative_prompt,
    _build_video_prompt,
)
from core.infra.gallery_metadata import save_gallery_metadata
from core.generation.video_sessions import (
    concat_video_segments,
    create_video_session,
    extract_video_frames,
)


# ========== MMAUDIO — Ajout de son aux vidéos ==========

_mmaudio_loaded = False
_mmaudio_net = None
_mmaudio_feature_utils = None
_mmaudio_config = None

def add_audio_to_video(video_path: str, prompt: str = "") -> str:
    """
    Ajoute du son à une vidéo muette avec MMAudio.
    Retourne le chemin de la vidéo avec son, ou None si MMAudio pas dispo.
    """
    global _mmaudio_loaded, _mmaudio_net, _mmaudio_feature_utils, _mmaudio_config

    native_audio_muxed = False
    try:
        from mmaudio.eval_utils import (ModelConfig, all_model_cfg, generate as mmaudio_generate,
                                         load_video, make_video, setup_eval_logging)
        from mmaudio.model.flow_matching import FlowMatching
        from mmaudio.model.networks import MMAudio as MMAudioNet, get_my_mmaudio
        from mmaudio.model.utils.features_utils import FeaturesUtils
    except ImportError:
        print("[AUDIO] Installation de MMAudio...")
        try:
            import subprocess, sys
            # hatchling requis comme build backend pour MMAudio
            subprocess.check_call([sys.executable, "-m", "pip", "install", "hatchling", "-q"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "git+https://github.com/hkchengrex/MMAudio.git", "-q"])
            from mmaudio.eval_utils import (ModelConfig, all_model_cfg, generate as mmaudio_generate,
                                             load_video, make_video, setup_eval_logging)
            from mmaudio.model.flow_matching import FlowMatching
            from mmaudio.model.networks import MMAudio as MMAudioNet, get_my_mmaudio
            from mmaudio.model.utils.features_utils import FeaturesUtils
        except Exception as e:
            print(f"[AUDIO] Impossible d'installer MMAudio: {e}")
            return None

    update_video_progress(phase='audio', message='Ajout du son (MMAudio)...')
    print("[AUDIO] Génération du son avec MMAudio...")

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    dtype = torch.bfloat16

    # Charger le modèle si pas déjà fait
    if not _mmaudio_loaded:
        variant = "large_44k_v2"
        _mmaudio_config = all_model_cfg[variant]

        # Retry download si connexion coupe (fréquent sur gros fichiers)
        for attempt in range(3):
            try:
                _mmaudio_config.download_if_needed()
                break
            except Exception as e:
                if attempt < 2:
                    print(f"[AUDIO] Téléchargement échoué (tentative {attempt+1}/3): {e}")
                    print("[AUDIO] Retry dans 5s...")
                    import time as _t; _t.sleep(5)
                else:
                    print(f"[AUDIO] Téléchargement échoué après 3 tentatives: {e}")
                    return None

        _mmaudio_net = get_my_mmaudio(_mmaudio_config.model_name).to(device, dtype).eval()
        _mmaudio_net.load_weights(torch.load(_mmaudio_config.model_path, map_location=device, weights_only=True))

        _mmaudio_feature_utils = FeaturesUtils(
            tod_vae_ckpt=_mmaudio_config.vae_path,
            synchformer_ckpt=_mmaudio_config.synchformer_ckpt,
            enable_conditions=True,
            mode=_mmaudio_config.mode,
            bigvgan_vocoder_ckpt=_mmaudio_config.bigvgan_16k_path,
            need_vae_encoder=False
        ).to(device, dtype).eval()

        _mmaudio_loaded = True
        print("[AUDIO] MMAudio large_44k_v2 chargé")

    # Charger la vidéo
    video_info = load_video(Path(video_path), duration_sec=8.0)
    clip_frames = video_info.clip_frames.unsqueeze(0)
    sync_frames = video_info.sync_frames.unsqueeze(0)
    duration = video_info.duration_sec

    seq_cfg = _mmaudio_config.seq_cfg
    seq_cfg.duration = duration
    _mmaudio_net.update_seq_lengths(seq_cfg.latent_seq_len, seq_cfg.clip_seq_len, seq_cfg.sync_seq_len)

    rng = torch.Generator(device=device)
    rng.manual_seed(42)
    fm = FlowMatching(min_sigma=0, inference_mode='euler', num_steps=25)

    # Générer l'audio (torch.no_grad pour éviter "Inference tensors cannot be saved for backward")
    audio_prompt = prompt if prompt else ""
    with torch.no_grad():
        audios = mmaudio_generate(
            clip_frames, sync_frames,
            [audio_prompt],
            negative_text=["silence, noise, static"],
            feature_utils=_mmaudio_feature_utils,
            net=_mmaudio_net,
            fm=fm,
            rng=rng,
            cfg_strength=4.5,
        )
    audio = audios.float().cpu()[0]

    # Sauvegarder la vidéo avec son
    output_path = Path(video_path).with_suffix('.audio.mp4')
    make_video(video_info, output_path, audio, sampling_rate=seq_cfg.sampling_rate)

    print(f"[AUDIO] Son ajouté → {output_path}")
    return str(output_path)


def unload_mmaudio():
    """Décharge MMAudio de la VRAM"""
    global _mmaudio_loaded, _mmaudio_net, _mmaudio_feature_utils, _mmaudio_config
    if _mmaudio_loaded:
        del _mmaudio_net
        del _mmaudio_feature_utils
        _mmaudio_net = None
        _mmaudio_feature_utils = None
        _mmaudio_loaded = False
        torch.cuda.empty_cache()
        print("[AUDIO] MMAudio déchargé")


def generate_video(image: Image.Image, prompt: str = "", target_frames: int = 49, num_steps: int = 50, fps: int = 8, video_model: str = "svd", continue_from_last: bool = False, unload_after: bool = True, chat_id: str = None, pipe=None, upscale_pipe=None, cancel_check=None, add_audio: bool = False, quality: str = "720p", face_restore: str = "off", refine_passes: int = 0, release_pipe_before_export=None, continuation_context: dict | None = None, audio_engine: str = "auto", audio_prompt: str = ""):
    """
    Génère une vidéo avec le modèle sélectionné (SVD, CogVideoX, Wan2.1, etc.)

    Args:
        image: Image source (sera animée)
        prompt: Prompt texte pour le mouvement
        target_frames: Nombre de frames
        num_steps: Steps d'inférence
        fps: FPS de sortie
        video_model: "svd", "cogvideox", "cogvideox-2b", "wan", "wan22-5b", "fastwan"
        continue_from_last: Si True, utilise la dernière frame
        unload_after: Si True, décharge le modèle après
        cancel_check: Callable qui retourne True si annulé
        release_pipe_before_export: Callable optionnel pour libérer un backend très lourd
            avant l'encodage MP4. Utile pour FramePack/Hunyuan qui garde beaucoup
            de poids en RAM via CPU offload.
        quality: "720p" ou "480p" (pour Wan 2.2 5B / FastWan)

    Retourne: (video_base64, last_frame, format)
    """
    import torch

    continuation_context = continuation_context or {}
    source_video_path = continuation_context.get("source_video_path")
    persisted_continuation = bool(continuation_context.get("source_session_id"))
    source_frame_count = int(continuation_context.get("source_frames") or 0)
    source_width = int(continuation_context.get("source_width") or 0)
    source_height = int(continuation_context.get("source_height") or 0)

    # Si on continue depuis une session persistée, la route fournit l'image
    # d'ancrage et JoyBoy exporte un segment delta avant de le raccorder.
    if persisted_continuation:
        if image is None:
            return None, None, "Pas de frame d'ancrage pour continuer cette vidéo"
        _state.all_video_frames = []
        print(f"[VIDEO] Continuation persistée depuis session {continuation_context.get('source_session_id')}")
    elif continue_from_last:
        if _state.last_video_frame is not None:
            image = _state.last_video_frame
            # Réutiliser le prompt de la vidéo précédente si pas de nouveau prompt
            if not prompt and _state.last_video_prompt:
                prompt = _state.last_video_prompt
                print(f"[VIDEO] Continuation avec prompt précédent: {prompt}")
            print(f"[VIDEO] Continuation depuis la dernière frame (total: {len(_state.all_video_frames)} frames)")
        else:
            return None, None, "Pas de frame précédente pour continuer"
    else:
        # Nouvelle vidéo = reset des frames accumulées
        _state.all_video_frames = []
        print("[VIDEO] Nouvelle vidéo (reset frames)")

    # Sauvegarder le prompt pour continuation future
    if prompt:
        _state.last_video_prompt = prompt
    _state.last_video_fps = int(fps or 16)

    from core.models import VIDEO_MODELS
    model_capabilities = VIDEO_MODELS.get(video_model, {})

    # Déterminer le mode: T2V (sans image) ou I2V (avec image)
    is_t2v_mode = False

    if image is None:
        # Vérifier si le modèle supporte T2V
        if bool(model_capabilities.get("supports_t2v", False)):
            # T2V mode: PAS de fallback, on génère sans image
            is_t2v_mode = True
            print(f"[VIDEO] Mode T2V (text-to-video) — génération depuis le texte uniquement")
        else:
            # Modèle I2V only: essayer le fallback sur current_image
            image = _state.current_image
            if image is not None:
                print(f"[VIDEO] ⚠️ Pas d'image reçue, utilisation de current_image (fallback)")
            else:
                return None, None, "Pas d'image (ce modèle ne supporte pas T2V)"

    if image is not None:
        # S'assurer que c'est une PIL Image (peut être un tensor après continuation)
        if not isinstance(image, Image.Image):
            try:
                if hasattr(image, 'cpu'):  # Tensor PyTorch
                    image = image.cpu().numpy()
                if isinstance(image, np.ndarray):
                    if image.max() <= 1.0:
                        image = (image * 255).astype(np.uint8)
                    image = Image.fromarray(image)
                print(f"[VIDEO] Image convertie en PIL: {image.size[0]}x{image.size[1]}")
            except Exception as e:
                print(f"[VIDEO] ⚠️ Impossible de convertir l'image: {e}")
                return None, None, f"Image invalide: {e}"
        print(f"[VIDEO] Image reçue: {image.size[0]}x{image.size[1]} mode={image.mode}")

    has_visual_source = image is not None and not is_t2v_mode
    normalized_audio_engine = str(audio_engine or "auto").strip().lower()
    ltx_native_audio_engine_selected = normalized_audio_engine in {"native", "ltx2", "ltx-2", "ltx"}
    ltx_native_audio_requested = ltx_native_audio_engine_selected or (bool(add_audio) and normalized_audio_engine == "auto")
    _state.ltx2_audio = None

    def _source_fidelity_prompt(default_prompt: str) -> str:
        return _build_video_prompt(prompt, default_prompt, has_visual_source=has_visual_source)

    def _source_fidelity_negative(negative_prompt: str = "") -> str:
        return _build_video_negative_prompt(
            negative_prompt,
            has_visual_source=has_visual_source,
            user_prompt=prompt,
        )

    def _store_ltx_native_audio(audio_data, pipe_obj=None, *, label: str = "LTX-2") -> None:
        """Keep LTX native audio only when the user asked for audio."""
        _state.ltx2_audio = None
        if audio_data is None:
            return
        if not ltx_native_audio_requested:
            print(f"[VIDEO] Audio {label} généré mais ignoré (Audio désactivé)")
            return
        _state.ltx2_audio = audio_data
        try:
            _state.ltx2_audio_sr = pipe_obj.vocoder.config.output_sampling_rate
        except Exception:
            _state.ltx2_audio_sr = 24000
        print(f"[VIDEO] Audio {label} capturé (sample rate: {_state.ltx2_audio_sr})")

    # ========== INITIALISER PROGRESSION ==========
    update_video_progress(active=True, step=0, total_steps=0, pass_num=0, total_passes=1, phase='loading', message='Préparation VRAM...')

    # Le pipe est injecté par l'appelant (ModelManager via generation_pipeline)
    from core.models import VRAM_GB
    from core.generation.video_optimizations import configure_video_torch_runtime
    configure_video_torch_runtime()
    if pipe is None:
        raise ValueError("pipe must be provided (injected by ModelManager)")

    model_info = VIDEO_MODELS.get(video_model, VIDEO_MODELS["svd"])
    update_video_progress(phase='loading', message=f"{model_info['name']} prêt")
    print(f"[VIDEO] Modèle {model_info['name']} prêt")

    # === RÉSOLUTION selon le modèle ===
    # En mode T2V, utiliser une résolution par défaut (paysage 720p ou 480p)
    if is_t2v_mode:
        # Pas d'image = résolution par défaut paysage
        if quality == "480p":
            w, h = 832, 480
        else:
            w, h = 1280, 704
        print(f"[VIDEO] T2V résolution par défaut: {w}x{h} ({quality})")
    else:
        w, h = image.size
    is_cogvideo = video_model.startswith("cogvideo")
    is_wan = video_model in ("wan", "wan22")
    is_wan22 = video_model == "wan22"
    is_wan5b = video_model in ("wan22-5b", "fastwan", "wan22-t2v-14b")
    is_wan_t2v_14b = video_model == "wan22-t2v-14b"  # T2V only, already WanPipeline
    is_hunyuan = video_model == "hunyuan"
    is_framepack = video_model in ("framepack", "framepack-fast")
    is_framepack_fast = video_model == "framepack-fast"
    is_ltx = video_model == "ltx"
    is_ltx2 = video_model == "ltx2"
    is_ltx23_fp8 = video_model == "ltx23_fp8"
    is_ltx2_fp8 = video_model in ("ltx2_fp8", "ltx23_fp8")
    is_native_wan = video_model.startswith("wan-native-")  # Backend natif Wan
    is_lightx2v = video_model.startswith("lightx2v-")
    low_vram_framepack = is_framepack and 0 < float(VRAM_GB or 0) <= 10
    low_vram_ltx = is_ltx and 0 < float(VRAM_GB or 0) <= 10
    low_vram_svd = (
        not any((is_cogvideo, is_wan, is_wan22, is_wan5b, is_hunyuan, is_framepack, is_ltx, is_ltx2, is_ltx2_fp8, is_native_wan, is_lightx2v))
        and 0 < float(VRAM_GB or 0) <= 10
    )

    def _aspect_locked_size(
        base_w: int,
        base_h: int,
        *,
        max_area: int,
        mod_value: int = 16,
        min_side: int = 256,
        min_area: int | None = None,
    ):
        """Keep source format while snapping to model-friendly multiples.

        If the source is usable, keep its pixel area. If it is tiny, upscale to
        the requested model quality while preserving the exact aspect ratio.
        If it is too large, downscale to the model cap.
        """
        base_w = max(1, int(base_w or w or 1))
        base_h = max(1, int(base_h or h or 1))
        base_area = base_w * base_h
        floor_area = min_area or min(max_area, 480 * 832)
        target_area = max_area if base_area < floor_area else min(base_area, max_area)
        aspect_ratio = base_h / base_w
        target_h_local = round(np.sqrt(target_area * aspect_ratio)) // mod_value * mod_value
        target_w_local = round(np.sqrt(target_area / aspect_ratio)) // mod_value * mod_value
        target_w_local = max(min_side, target_w_local)
        target_h_local = max(min_side, target_h_local)
        return int(target_w_local), int(target_h_local)

    def _source_aspect_size(*, quality_value: str = "720p", max_480: int = 480 * 832, max_720: int = 704 * 1280, mod_value: int = 16):
        base_w = source_width or w
        base_h = source_height or h
        max_area = max_480 if quality_value == "480p" else max_720
        return _aspect_locked_size(base_w, base_h, max_area=max_area, mod_value=mod_value)

    if is_lightx2v:
        target_w, target_h = _source_aspect_size(quality_value=quality, mod_value=16)
        print(f"[VIDEO] LightX2V ratio source ({quality}): {target_w}x{target_h}")
    elif is_native_wan:
        # Backend NATIF Wan — résolutions fixes comme Wan 2.2 5B
        is_portrait = h > w
        if video_model == "wan-native-14b":
            # 14B I2V: 480p uniquement (stride 8)
            target_w, target_h = _source_aspect_size(quality_value="480p", mod_value=16)
            print(f"[VIDEO] Wan 2.2 14B (natif) en 480p ratio source: {target_w}x{target_h}")
        else:
            # 5B TI2V: 720p / 480p (stride 16)
            target_w, target_h = _source_aspect_size(quality_value=quality, mod_value=16)
            print(f"[VIDEO] Wan 2.2 5B (natif) en {quality} ratio source: {target_w}x{target_h}")
    elif is_wan5b:
        # Wan 2.2 TI2V 5B / FastWan / T2V-14B: RÉSOLUTIONS FIXES uniquement
        # T2V-14B: 480p only
        # 5B: 720p ou 480p selon quality
        is_portrait = h > w if not is_t2v_mode else False  # T2V mode: paysage par défaut
        if is_wan_t2v_14b:
            # T2V-14B: 480p uniquement
            target_w, target_h = (480, 832) if is_portrait else (832, 480)
            print(f"[VIDEO] Wan 2.2 T2V-14B en 480p ({'portrait' if is_portrait else 'paysage'})")
        elif quality == "480p":
            target_w, target_h = _source_aspect_size(quality_value="480p", mod_value=16)
            print(f"[VIDEO] Wan 2.2 5B en 480p ratio source: {target_w}x{target_h}")
        else:
            target_w, target_h = _source_aspect_size(quality_value="720p", mod_value=16)
            print(f"[VIDEO] Wan 2.2 5B en 720p ratio source: {target_w}x{target_h}")
    elif is_wan:
        # Wan 2.1/2.2 14B: RÉSOLUTIONS FIXES (modèles 480P/720P séparés)
        # 480p: 832x480 (paysage) ou 480x832 (portrait)
        target_w, target_h = _source_aspect_size(quality_value="480p", mod_value=16)
        print(f"[VIDEO] Wan 14B en 480p ratio source: {target_w}x{target_h}")
    elif is_hunyuan:
        # HunyuanVideo 1.5: 480p, résolution doit être multiple de 16
        target_w, target_h = _source_aspect_size(quality_value="480p", mod_value=16)
        print(f"[VIDEO] HunyuanVideo 1.5 en 480p ratio source: {target_w}x{target_h}")
    elif is_framepack:
        # FramePack F1 is Hunyuan-based. Keep <=10GB runs compact because the
        # model is large and relies on CPU/group offload.
        max_area = (288 * 384) if is_framepack_fast else ((320 * 448) if low_vram_framepack else (480 * 832))
        target_w, target_h = _aspect_locked_size(source_width or w, source_height or h, max_area=max_area, mod_value=16)
        low_vram_label = " low-VRAM" if low_vram_framepack else ""
        fast_label = " rapide" if is_framepack_fast else ""
        print(f"[VIDEO] FramePack{fast_label}{low_vram_label}: résolution ratio source {target_w}x{target_h}")
    elif is_ltx2_fp8:
        # LTX-2 19B FP8 (ltx_pipelines): two-stage pipeline, multiples de 64
        target_w, target_h = _aspect_locked_size(source_width or w, source_height or h, max_area=512 * 768, mod_value=64)
        ltx2_label = "LTX-2.3 FP8" if is_ltx23_fp8 else "LTX-2 FP8"
        print(f"[VIDEO] {ltx2_label} ratio source: {target_w}x{target_h}")
    elif is_ltx2:
        # LTX-2 19B (diffusers): 512p, dimensions multiples de 32
        target_w, target_h = _aspect_locked_size(source_width or w, source_height or h, max_area=512 * 768, mod_value=32)
        print(f"[VIDEO] LTX-2 ratio source: {target_w}x{target_h}")
    elif is_ltx:
        # LTX-Video 2B: dimensions multiples de 32.
        # Sur 8GB, le backend Diffusers de JoyBoy reste expérimental: on force
        # une zone plus petite que le profil Q8 public pour éviter les stalls.
        max_area = (352 * 512) if low_vram_ltx else (480 * 704)
        if low_vram_ltx:
            print("[VIDEO] LTX low-VRAM forcé: résolution conservative, single-pass")
        target_w, target_h = _aspect_locked_size(source_width or w, source_height or h, max_area=max_area, mod_value=32)
        print(f"[VIDEO] LTX-Video ratio source: {target_w}x{target_h}")
    elif is_cogvideo:
        # CogVideoX-5B: résolution fixe 720x480 (w x h) uniquement
        target_w = 720
        target_h = 480
    else:
        # SVD: compact GPU-direct mode on <=10GB. CPU offload fits, but it can
        # take tens of seconds per denoise step on consumer GPUs.
        fast_svd_8gb = os.environ.get("JOYBOY_SVD_FAST_8GB", "").strip().lower() in {"1", "true", "yes", "on"}
        MAX_SIZE = (448 if fast_svd_8gb else 512) if low_vram_svd else 576
        MIN_SIZE = 256
        if low_vram_svd:
            mode_label = "turbo" if fast_svd_8gb else "équilibrée"
            print(f"[VIDEO] SVD low-VRAM: résolution {mode_label} GPU direct")
        target_w, target_h = _aspect_locked_size(
            source_width or w,
            source_height or h,
            max_area=MAX_SIZE * MAX_SIZE,
            mod_value=64,
            min_side=MIN_SIZE,
            min_area=MIN_SIZE * MIN_SIZE,
        )
        print(f"[VIDEO] SVD ratio source: {target_w}x{target_h}")

    # En mode T2V, pas d'image à resizer
    if is_t2v_mode:
        image_resized = None
        print(f"[VIDEO] Mode T2V: résolution {target_w}x{target_h}")
    else:
        image_resized = image.resize((target_w, target_h), Image.LANCZOS)
        if image_resized.mode != "RGB":
            image_resized = image_resized.convert("RGB")
        print(f"[VIDEO] Image préparée: {target_w}x{target_h}")

    print("[VIDEO] Étape 3: Génération vidéo...")

    import time
    start_time = time.time()

    # Callback pour progression (frontend + backend logs)
    def video_step_callback(pipe_obj, step, timestep, callback_kwargs):
        # Vérifier annulation
        if cancel_check and cancel_check():
            print(f"\n[VIDEO] Annulé à step {step+1}/{num_steps}")
            raise GenerationCancelledException("Video generation cancelled")

        s = step + 1
        update_video_progress(step=s, message=f'Step {s}/{num_steps}')
        # Barre de progression ASCII dans les logs
        pct = s / num_steps
        bar_len = 30
        filled = int(bar_len * pct)
        bar = '█' * filled + '░' * (bar_len - filled)
        elapsed = time.time() - start_time
        eta = (elapsed / s) * (num_steps - s) if s > 0 else 0
        print(f"\r   [{bar}] {pct*100:5.1f}% | Step {s}/{num_steps} | {elapsed:.0f}s elapsed | ETA {eta:.0f}s", end='', flush=True)
        if s == num_steps:
            print()  # Newline at end
        return callback_kwargs

    def _release_framepack_generation_weights(pipe_obj):
        """Keep only the VAE/video processor so low-VRAM FramePack can decode safely."""
        if pipe_obj is None:
            return
        try:
            pipe_obj.maybe_free_model_hooks()
        except Exception:
            pass

        released = []
        for attr in (
            "transformer",
            "text_encoder",
            "text_encoder_2",
            "image_encoder",
            "feature_extractor",
            "tokenizer",
            "tokenizer_2",
        ):
            if hasattr(pipe_obj, attr) and getattr(pipe_obj, attr, None) is not None:
                try:
                    setattr(pipe_obj, attr, None)
                    released.append(attr)
                except Exception:
                    pass

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass
        if released:
            print(f"[VIDEO] FramePack low-VRAM: composants libérés avant décodage ({', '.join(released)})")

    def _decode_framepack_latents(pipe_obj, latent_sections, max_frames=None, latent_window_size=9):
        """Decode FramePack latents after heavy generation modules have been released."""
        if not latent_sections:
            return []

        _release_framepack_generation_weights(pipe_obj)
        total_sections = len(latent_sections)
        update_video_progress(
            phase='decoding',
            step=0,
            total_steps=total_sections,
            message=f'Décodage vidéo 0/{total_sections}...'
        )
        print("[VIDEO] FramePack low-VRAM: décodage VAE après libération du modèle")

        vae = pipe_obj.vae
        vae_dtype = getattr(vae, "dtype", torch.float16)
        try:
            vae_device = next(vae.parameters()).device
        except StopIteration:
            vae_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        history_video = None
        overlapped_frames = (latent_window_size - 1) * pipe_obj.vae_scale_factor_temporal + 1
        section_latent_frames = latent_window_size * 2
        with torch.inference_mode():
            for section_index in range(total_sections):
                index = section_index + 1
                section_latents = latent_sections[section_index]
                if cancel_check and cancel_check():
                    raise GenerationCancelledException("Video generation cancelled")
                print(f"[VIDEO] FramePack decode section {index}/{len(latent_sections)}")
                update_video_progress(
                    phase='decoding',
                    step=index,
                    total_steps=total_sections,
                    message=f'Décodage vidéo {index}/{total_sections}...'
                )

                # Diffusers returns cumulative latent history for output_type="latent".
                # Section 1 is the full initial history; following sections must decode
                # only the newest tail, otherwise the exported video repeats earlier motion.
                if history_video is None:
                    section_to_decode = section_latents
                else:
                    section_to_decode = section_latents[:, :, -section_latent_frames:]

                current_latents = section_to_decode.to(device=vae_device, dtype=vae_dtype) / vae.config.scaling_factor
                current_video = vae.decode(current_latents, return_dict=False)[0]

                if history_video is None:
                    history_video = current_video
                else:
                    history_video = pipe_obj._soft_append(history_video, current_video, overlapped_frames)

                latent_sections[section_index] = None
                del section_latents, section_to_decode, current_latents, current_video
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        generated_count = history_video.size(2)
        generated_count = (
            generated_count - 1
        ) // pipe_obj.vae_scale_factor_temporal * pipe_obj.vae_scale_factor_temporal + 1
        history_video = history_video[:, :, :generated_count]
        frame_batches = pipe_obj.video_processor.postprocess_video(history_video, output_type="pil")
        del history_video
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        frames = frame_batches[0] if frame_batches else []
        if max_frames and len(frames) > max_frames:
            print(f"[VIDEO] FramePack trim: {len(frames)} -> {max_frames} frames")
            frames = frames[:max_frames]
        return frames

    # Override steps pour les modèles à params fixes (avant progress bar)
    # Modèles configurables (respectent le slider): wan22-5b, svd
    # Modèles fixes (hardcodé): fastwan, wan22, cogvideo, ltx, hunyuan
    if is_lightx2v:
        num_steps = max(1, min(8, int(num_steps or model_info.get("default_steps") or 4)))
    elif is_native_wan:
        # Backend natif: 50 pour 5B, 40 pour 14B (configs officielles)
        num_steps = 40 if video_model == "wan-native-14b" else 50
    elif is_wan5b and video_model == "fastwan":
        num_steps = 3  # FastWan DMD: profil officiel 3 steps
    elif is_wan5b:
        # Wan 2.2 5B: configurable (slider, default 30, clamp 20-50)
        num_steps = max(20, min(50, num_steps))
    elif is_wan22:
        num_steps = 40
    elif is_cogvideo:
        num_steps = 50
    elif is_ltx2:
        num_steps = 40  # LTX-2 I2V recommended motion profile
    elif is_ltx2_fp8:
        num_steps = 8 if is_ltx23_fp8 else 40
    elif is_ltx:
        # Détecter si pipeline distillé ou base
        try:
            from diffusers import LTXConditionPipeline
            _ltx_distilled = isinstance(pipe, LTXConditionPipeline)
        except ImportError:
            _ltx_distilled = False
        num_steps = 8 if (low_vram_ltx and _ltx_distilled) else (30 if _ltx_distilled else 50)
    elif is_hunyuan:
        num_steps = 12
    elif is_framepack:
        num_steps = max(12, min(30, num_steps))

    update_video_progress(phase='generating', total_steps=num_steps, total_passes=1, pass_num=1, message='Génération...')

    # === GÉNÉRATION SELON LE MODÈLE ===
    if is_lightx2v:
        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT if has_visual_source else DEFAULT_SCENE_VIDEO_PROMPT)
        negative_prompt = _source_fidelity_negative(
            "overexposed, oversaturated, hyper contrast, beautified, relit, cinematic color grade, "
            "identity drift, face drift, body shape drift, distorted anatomy, bad hands, low quality"
        )
        print(f"[VIDEO] Prompt LightX2V: {video_prompt}")

        lightx2v_frames = target_frames
        if (lightx2v_frames - 1) % 4 != 0:
            lightx2v_frames = ((lightx2v_frames - 1) // 4) * 4 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {lightx2v_frames} (formule 4k+1)")
        fps = int(model_info.get("default_fps") or fps or 16)

        def _lightx2v_progress(step, total, message):
            if cancel_check and cancel_check():
                raise GenerationCancelledException("Video generation cancelled")
            if step is not None:
                update_video_progress(step=int(step), total_steps=int(total or num_steps), message=message)
                pct = max(0.0, min(1.0, int(step) / max(1, int(total or num_steps))))
                bar_len = 30
                filled = int(bar_len * pct)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f"\r   [{bar}] {pct*100:5.1f}% | {message}", end='', flush=True)
                if int(step) >= int(total or num_steps):
                    print()
            else:
                update_video_progress(message=message)

        result = pipe.generate(
            image=image_resized,
            prompt=video_prompt,
            negative_prompt=negative_prompt,
            width=target_w,
            height=target_h,
            frames=lightx2v_frames,
            steps=num_steps,
            fps=fps,
            quality=quality,
            cancel_check=cancel_check,
            progress_callback=_lightx2v_progress,
        )
        preencoded_video_path = Path(result.video_path)
        generated_frames = extract_video_frames(preencoded_video_path)
        if not generated_frames:
            raise RuntimeError(f"LightX2V a produit un MP4 illisible: {preencoded_video_path}")

    elif is_native_wan:
        # Backend NATIF Wan — code officiel sans diffusers
        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT)
        negative_prompt = _source_fidelity_negative("")  # Backend natif gère différemment
        print(f"[VIDEO] (Natif) Prompt: {video_prompt}")

        # Params selon modèle
        if video_model == "wan-native-14b":
            guidance = 3.5
            shift = 5.0
            fps = 24
        else:
            guidance = 5.0
            shift = 5.0 if quality != "480p" else 3.0
            fps = 24

        # Frames: formule 4n+1
        wan_frames = target_frames
        if (wan_frames - 1) % 4 != 0:
            wan_frames = ((wan_frames - 1) // 4) * 4 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {wan_frames} (formule 4n+1)")

        # max_area pour calcul latent (720p = 1280*704 = 901120, 480p = 832*480 = 399360)
        max_area = target_w * target_h

        native_gpu_direct = (
            video_model == "wan-native-5b"
            and float(VRAM_GB or 0) >= 36
            and os.environ.get("JOYBOY_WAN_NATIVE_FORCE_OFFLOAD", "").strip().lower() not in {"1", "true", "yes", "on"}
        )
        native_offload = not native_gpu_direct
        offload_label = "gpu_direct" if native_gpu_direct else "offload"
        print(f"[VIDEO] Mode: {video_model} (natif) — guidance={guidance}, steps={num_steps}, shift={shift}, {offload_label}")

        # Génération via API native
        # Le pipe est un WanI2V (pas un DiffusionPipeline)
        def _run_native_wan(offload_model: bool):
            with torch.inference_mode():
                return pipe.generate(
                    input_prompt=video_prompt,
                    img=image_resized,
                    max_area=max_area,
                    frame_num=wan_frames,
                    shift=shift,
                    sample_solver='unipc',
                    sampling_steps=num_steps,
                    guide_scale=guidance,
                    n_prompt=negative_prompt,
                    seed=42,
                    offload_model=offload_model,
                )

        try:
            video_tensor = _run_native_wan(native_offload)
        except RuntimeError as exc:
            is_oom = "out of memory" in str(exc).lower() or "cuda oom" in str(exc).lower()
            if not native_offload and is_oom:
                print("[VIDEO] Wan natif GPU direct OOM, retry avec offload CPU")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                video_tensor = _run_native_wan(True)
            else:
                raise
        # video_tensor: (C, N, H, W) float, range [0, 1]
        # Convertir en liste de PIL Images
        import torch
        video_tensor = video_tensor.cpu()
        # Clamp et convertir
        video_tensor = torch.clamp(video_tensor, 0, 1)
        # (C, N, H, W) → (N, H, W, C)
        video_np = video_tensor.permute(1, 2, 3, 0).numpy()
        video_np = (video_np * 255).astype('uint8')
        generated_frames = [Image.fromarray(frame) for frame in video_np]

    elif is_wan5b:
        # Wan 2.2 TI2V 5B / FastWan 2.2 5B — I2V avec qualité variable
        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT)
        negative_prompt = _source_fidelity_negative(
            "Bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, images, "
            "static, overall gray, worst quality, low quality, JPEG compression residue, ugly, incomplete, "
            "extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, "
            "fused fingers, still picture, messy background, three legs, many people in the background, walking backwards, "
            "distorted face, asymmetric eyes, strange mouth, frame-by-frame facial drift, bad anatomy"
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch

        # flow_shift selon résolution: 5.0 pour 720p, 3.0 pour 480p
        flow_shift = 3.0 if quality == "480p" else 5.0
        from diffusers.schedulers import UniPCMultistepScheduler
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config,
            flow_shift=flow_shift
        )

        gen = torch.Generator(device="cpu").manual_seed(42)
        fps = 24  # Wan 2.2 5B natif 24fps

        # Frames: formule 4k+1
        wan_frames = target_frames
        if (wan_frames - 1) % 4 != 0:
            wan_frames = ((wan_frames - 1) // 4) * 4 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {wan_frames} (formule 4k+1)")

        WAN5B_GUIDANCE = 1.0 if video_model == "fastwan" else 5.0
        if is_wan_t2v_14b:
            model_label = "Wan 2.2 T2V-14B MoE"
        elif video_model == "fastwan":
            model_label = "FastWan 2.2 5B"
        else:
            model_label = "Wan 2.2 TI2V 5B"
        mode_str = "T2V" if is_t2v_mode else "I2V"
        print(f"[VIDEO] Mode: {model_label} ({quality}, {mode_str}) — guidance={WAN5B_GUIDANCE}, steps={num_steps}, flow_shift={flow_shift}")

        import torch
        import inspect

        def _apply_fastwan_dmd_timesteps(pipeline_obj, kwargs):
            if video_model != "fastwan":
                return kwargs
            try:
                signature = inspect.signature(pipeline_obj.__call__)
                if "timesteps" in signature.parameters:
                    kwargs["timesteps"] = [1000, 757, 522]
                    kwargs["num_inference_steps"] = 3
                    print("[VIDEO] FastWan DMD timesteps officiels: 1000,757,522")
            except Exception:
                pass
            return kwargs

        wan5b_cpu_retry_done = False

        def _run_wan5b_pipeline(pipeline_obj, call_kwargs):
            nonlocal wan5b_cpu_retry_done
            try:
                with torch.inference_mode():
                    return pipeline_obj(**call_kwargs)
            except RuntimeError as exc:
                is_oom = "out of memory" in str(exc).lower() or "cuda oom" in str(exc).lower()
                force_offload = os.environ.get("JOYBOY_VIDEO_DISABLE_OOM_RETRY", "").strip().lower() in {"1", "true", "yes", "on"}
                if not is_oom or wan5b_cpu_retry_done or force_offload:
                    raise

                enable_offload = getattr(pipeline_obj, "enable_model_cpu_offload", None)
                if not callable(enable_offload):
                    raise

                wan5b_cpu_retry_done = True
                print("[VIDEO] Wan/FastWan GPU direct OOM, retry avec model_cpu_offload")
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                enable_offload()
                with torch.inference_mode():
                    return pipeline_obj(**call_kwargs)

        # Génération directe avec VAE slicing (activé au chargement du modèle)
        # Le slicing décode frame par frame, évitant l'OOM sans decode manuel
        if is_wan_t2v_14b:
            # T2V-14B: déjà chargé comme WanPipeline (T2V only)
            # Appel direct sans conversion
            call_kwargs = _apply_fastwan_dmd_timesteps(pipe, {
                "prompt": video_prompt,
                "negative_prompt": negative_prompt,
                "height": target_h,
                "width": target_w,
                "num_frames": wan_frames,
                "num_inference_steps": num_steps,
                "guidance_scale": WAN5B_GUIDANCE,
                "generator": gen,
                "callback_on_step_end": video_step_callback,
            })
            video_output = _run_wan5b_pipeline(pipe, call_kwargs)
        elif is_t2v_mode:
            # T2V avec modèle I2V: besoin de WanPipeline (pas WanImageToVideoPipeline)
            # Créer dynamiquement à partir des composants existants
            from diffusers import WanPipeline
            t2v_pipe = WanPipeline(
                transformer=pipe.transformer,
                vae=pipe.vae,
                text_encoder=pipe.text_encoder,
                tokenizer=pipe.tokenizer,
                scheduler=pipe.scheduler,
            )
            # Copier les optimisations du pipe original
            t2v_pipe.vae.enable_slicing()
            # FIX CRITIQUE: Forcer VAE float32 (sinon bruit/flou)
            t2v_pipe.vae.to(dtype=torch.float32)
            print(f"[VIDEO] T2V VAE forcé float32 (fix qualité)")

            call_kwargs = _apply_fastwan_dmd_timesteps(t2v_pipe, {
                "prompt": video_prompt,
                "negative_prompt": negative_prompt,
                "height": target_h,
                "width": target_w,
                "num_frames": wan_frames,
                "num_inference_steps": num_steps,
                "guidance_scale": WAN5B_GUIDANCE,
                "generator": gen,
                "callback_on_step_end": video_step_callback,
            })
            video_output = _run_wan5b_pipeline(t2v_pipe, call_kwargs)
            # Libérer le pipe T2V temporaire
            del t2v_pipe
        else:
            # I2V: avec image
            call_kwargs = _apply_fastwan_dmd_timesteps(pipe, {
                "image": image_resized,
                "prompt": video_prompt,
                "negative_prompt": negative_prompt,
                "height": target_h,
                "width": target_w,
                "num_frames": wan_frames,
                "num_inference_steps": num_steps,
                "guidance_scale": WAN5B_GUIDANCE,
                "generator": gen,
                "callback_on_step_end": video_step_callback,
            })
            video_output = _run_wan5b_pipeline(pipe, call_kwargs)
        generated_frames = video_output.frames[0]  # Liste de PIL Images

    elif is_wan:
        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT)
        negative_prompt = _source_fidelity_negative(
            "Bright tones, overexposed, static, blurred details, subtitles, style, works, paintings, images, "
            "static, overall gray, worst quality, low quality, JPEG compression residue, ugly, incomplete, "
            "extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, misshapen limbs, "
            "fused fingers, still picture, messy background, three legs, many people in the background, walking backwards, "
            "distorted face, asymmetric eyes, strange mouth, frame-by-frame facial drift, bad anatomy"
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch
        gen = torch.Generator(device="cpu").manual_seed(42)

        # Wan frames: formule 4k+1 (ex: 81, 61, 41)
        wan_frames = target_frames
        if (wan_frames - 1) % 4 != 0:
            wan_frames = ((wan_frames - 1) // 4) * 4 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {wan_frames} (formule 4k+1)")

        if is_wan22:
            # Wan 2.2 MoE — params optimaux pour mouvement
            WAN22_GUIDANCE = 5.0   # Monté de 3.5 pour plus de mouvement
            WAN22_STEPS = 40       # Officiel Wan 2.2
            num_steps = WAN22_STEPS
            fps = 16
            print(f"[VIDEO] Mode: Wan 2.2 MoE A14B — guidance={WAN22_GUIDANCE}, steps={WAN22_STEPS}")

            # Génération directe avec VAE slicing
            with torch.inference_mode():
                video_frames = pipe(
                    image=image_resized,
                    prompt=video_prompt,
                    negative_prompt=negative_prompt,
                    height=target_h,
                    width=target_w,
                    num_frames=wan_frames,
                    num_inference_steps=WAN22_STEPS,
                    guidance_scale=WAN22_GUIDANCE,
                    generator=gen,
                    callback_on_step_end=video_step_callback,
                ).frames[0]
            generated_frames = list(video_frames)
        else:
            # Wan 2.1 I2V 14B
            print(f"[VIDEO] Mode: Wan 2.1 I2V 14B (480P) — guidance=5.0, steps={num_steps}")

            # Génération directe avec VAE slicing
            with torch.inference_mode():
                video_frames = pipe(
                    image=image_resized,
                    prompt=video_prompt,
                    negative_prompt=negative_prompt,
                    height=target_h,
                    width=target_w,
                    num_frames=wan_frames,
                    num_inference_steps=num_steps,
                    guidance_scale=5.0,
                    generator=gen,
                    callback_on_step_end=video_step_callback,
                ).frames[0]
            generated_frames = list(video_frames)

    elif is_hunyuan:
        # HunyuanVideo 1.5 I2V (step-distilled) — suit exactement la doc officielle
        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT)
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch
        gen = torch.Generator(device="cuda:0").manual_seed(42)

        num_steps = 12  # Step-distilled: fixé à 12
        print(f"[VIDEO] Mode: HunyuanVideo 1.5 I2V (480P) — steps={num_steps}, frames={target_frames}")

        try:
            with torch.inference_mode():
                video_frames = pipe(
                    prompt=video_prompt,
                    image=image_resized,
                    generator=gen,
                    num_frames=target_frames,
                    num_inference_steps=num_steps,
                    callback_on_step_end=video_step_callback,
                ).frames[0]
        except TypeError:
            # Fallback sans callback
            print("[VIDEO] Fallback: génération sans progress bar")
            with torch.inference_mode():
                video_frames = pipe(
                    prompt=video_prompt,
                    image=image_resized,
                    generator=gen,
                    num_frames=target_frames,
                    num_inference_steps=num_steps,
                ).frames[0]

        generated_frames = list(video_frames)

    elif is_framepack:
        # FramePack F1 I2V via official Diffusers HunyuanVideoFramepackPipeline.
        # F1 must use vanilla sampling according to the model docs.
        video_prompt, was_trimmed = _build_framepack_prompt(prompt, fast=is_framepack_fast, has_visual_source=has_visual_source)
        if was_trimmed:
            print("[VIDEO] FramePack prompt raccourci pour rester sous la limite CLIP")
        negative_prompt = (
            "low quality, blurry, distorted, deformed, bad anatomy, bad hands, "
            "flicker, jitter, warped face, duplicate subject, artifacts, still frame, paused frame"
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch
        gen = torch.Generator(device="cpu").manual_seed(42)
        fps = 12 if is_framepack_fast else 18

        framepack_frames = int(target_frames or 33)
        if is_framepack_fast:
            requested_frames = framepack_frames
            requested_steps = num_steps
            framepack_frames = 60
            num_steps = 7
            if requested_frames != framepack_frames or requested_steps != num_steps:
                print(
                    f"[VIDEO] FramePack fast preset: "
                    f"{requested_frames}/{requested_steps} -> {framepack_frames}/{num_steps}"
                )
        elif low_vram_framepack:
            requested_frames = framepack_frames
            requested_steps = num_steps
            if framepack_frames < 120:
                framepack_frames = 90
                num_steps = 9
            else:
                framepack_frames = 180
                num_steps = 9
            if requested_frames != framepack_frames or requested_steps != num_steps:
                print(
                    f"[VIDEO] FramePack low-VRAM preset: "
                    f"{requested_frames}/{requested_steps} -> {framepack_frames}/{num_steps}"
                )
        if framepack_frames < 17:
            framepack_frames = 17
        if not low_vram_framepack and framepack_frames % 2 == 0:
            framepack_frames += 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {framepack_frames} (impair)")

        framepack_guidance = 5.4 if low_vram_framepack else 7.2
        print(f"[VIDEO] Mode: FramePack F1 I2V — vanilla, guidance={framepack_guidance}, steps={num_steps}")

        framepack_output_type = "latent" if low_vram_framepack else "pil"
        try:
            with torch.inference_mode():
                framepack_result = pipe(
                    image=image_resized,
                    prompt=video_prompt,
                    negative_prompt=negative_prompt,
                    height=target_h,
                    width=target_w,
                    num_frames=framepack_frames,
                    num_inference_steps=num_steps,
                    guidance_scale=framepack_guidance,
                    generator=gen,
                    sampling_type="vanilla",
                    output_type=framepack_output_type,
                    callback_on_step_end=video_step_callback,
                ).frames
        except TypeError:
            print("[VIDEO] FramePack fallback: génération sans callback")
            with torch.inference_mode():
                framepack_result = pipe(
                    image=image_resized,
                    prompt=video_prompt,
                    negative_prompt=negative_prompt,
                    height=target_h,
                    width=target_w,
                    num_frames=framepack_frames,
                    num_inference_steps=num_steps,
                    guidance_scale=framepack_guidance,
                    generator=gen,
                    sampling_type="vanilla",
                    output_type=framepack_output_type,
                ).frames

        if low_vram_framepack:
            video_frames = _decode_framepack_latents(pipe, framepack_result, max_frames=framepack_frames)
        else:
            video_frames = framepack_result[0]

        generated_frames = list(video_frames)

    elif is_ltx2:
        # === LTX-2 19B (full I2V profile, motion-first) ===
        video_prompt = _build_ltx2_motion_prompt(prompt, has_visual_source=has_visual_source)
        negative_prompt = _build_ltx2_negative_prompt(
            "shaky, glitchy, low quality, worst quality, deformed, distorted, "
            "disfigured, motion smear, motion artifacts, fused fingers, "
            "bad anatomy, weird hand, ugly, transition",
            has_visual_source=has_visual_source,
            user_prompt=prompt,
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch
        gen = torch.Generator(device="cpu").manual_seed(42)
        fps = 24

        # Frames: formule (N*8)+1 pour LTX-2
        ltx2_frames = target_frames
        if (ltx2_frames - 1) % 8 != 0:
            ltx2_frames = ((ltx2_frames - 1) // 8) * 8 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {ltx2_frames} (formule 8k+1)")

        print(f"[VIDEO] Mode: LTX-2 19B I2V — {num_steps} steps, CFG 4.0, {target_w}x{target_h}")

        # Construire les kwargs de génération
        gen_kwargs = dict(
            prompt=video_prompt,
            negative_prompt=negative_prompt,
            height=target_h,
            width=target_w,
            num_frames=ltx2_frames,
            frame_rate=float(fps),
            num_inference_steps=num_steps,
            sigmas=None,
            guidance_scale=4.0,
            generator=gen,
            callback_on_step_end=video_step_callback,
            output_type="pil",
            return_dict=False,
        )
        # I2V si image fournie
        if image_resized is not None:
            gen_kwargs["image"] = image_resized
            import inspect
            try:
                call_params = inspect.signature(pipe.__call__).parameters
                ltx_motion_kwargs = {
                    "noise_scale": 0.0,
                    "decode_timestep": 0.05,
                    "decode_noise_scale": 0.025,
                }
                active_motion_kwargs = {}
                for key, value in ltx_motion_kwargs.items():
                    if key in call_params:
                        gen_kwargs[key] = value
                        active_motion_kwargs[key] = value
                if active_motion_kwargs:
                    print(
                        "[VIDEO] LTX-2 I2V motion conditioning actif "
                        f"({', '.join(f'{key}={value}' for key, value in active_motion_kwargs.items())})"
                    )
            except Exception:
                pass

        # output_type="np" pour pouvoir encoder audio+video ensemble
        gen_kwargs["output_type"] = "np"
        with torch.inference_mode():
            result = pipe(**gen_kwargs)

        # LTX2Pipeline retourne (video, audio) en tuple
        if isinstance(result, tuple) and len(result) >= 2:
            video_np = result[0]  # shape: [batch, frames, H, W, C] ou [frames, H, W, C]
            audio_data = result[1]  # tensor audio
        else:
            video_np = result[0] if isinstance(result, tuple) else result
            audio_data = None

        # Convertir numpy frames en PIL
        frames_array = video_np[0] if video_np.ndim == 5 else video_np
        generated_frames = []
        for f in frames_array:
            if f.max() <= 1.0:
                f = (f * 255).clip(0, 255).astype(np.uint8)
            generated_frames.append(Image.fromarray(f))

        # Stocker l'audio LTX-2 pour le muxage ffmpeg seulement si demandé.
        _store_ltx_native_audio(audio_data, pipe, label="LTX-2")

    elif is_ltx2_fp8:
        # === LTX-2 / LTX-2.3 FP8 (ltx_pipelines natif) ===
        video_prompt = _build_ltx2_motion_prompt(prompt, has_visual_source=has_visual_source)
        print(f"[VIDEO] Prompt: {video_prompt}")

        fps = 24

        # Frames: formule (N*8)+1 pour LTX-2
        ltx2_frames = target_frames
        if (ltx2_frames - 1) % 8 != 0:
            ltx2_frames = ((ltx2_frames - 1) // 8) * 8 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {ltx2_frames} (formule 8k+1)")

        fp8_label = "LTX-2.3 22B FP8 distillé" if is_ltx23_fp8 else "LTX-2 19B FP8"
        print(f"[VIDEO] Mode: {fp8_label} (ltx_pipelines) — {target_w}x{target_h}, {ltx2_frames} frames")

        # Préparer l'image I2V (ltx_pipelines veut un chemin fichier, pas PIL)
        import tempfile
        try:
            from ltx_pipelines.utils.args import ImageConditioningInput
        except Exception:
            ImageConditioningInput = None

        images_arg = []
        _tmp_img_path = None
        if image_resized is not None:
            _tmp_fd, _tmp_img_path = tempfile.mkstemp(suffix='.png')
            os.close(_tmp_fd)
            image_resized.save(_tmp_img_path)
            if ImageConditioningInput is not None:
                images_arg = [ImageConditioningInput(path=_tmp_img_path, frame_idx=0, strength=1.0)]
            else:
                images_arg = [(_tmp_img_path, 0, 1.0, 33)]  # legacy tuple fallback
            print(f"[VIDEO] I2V: image sauvée → {_tmp_img_path}")

        # Génération via DistilledPipeline natif
        # API: prompt, seed, height, width, num_frames, frame_rate, images
        # Retourne: (Iterator[Tensor], Tensor) — video frames iterator + audio
        with torch.inference_mode():
            result = pipe(
                prompt=video_prompt,
                seed=42,
                height=target_h,
                width=target_w,
                num_frames=ltx2_frames,
                frame_rate=float(fps),
                images=images_arg,
            )

        # Output: (video_frames_iterator, audio_tensor)
        if isinstance(result, tuple) and len(result) >= 2:
            video_data = result[0]
            audio_data = result[1]
        else:
            video_data = result
            audio_data = None

        # video_data peut être un Iterator[Tensor] ou un Tensor direct
        # Collecter toutes les frames
        import torch
        if hasattr(video_data, '__iter__') and not isinstance(video_data, torch.Tensor):
            # Iterator de tensors — collecter
            video_chunks = list(video_data)
            if len(video_chunks) > 0:
                video_tensor = torch.cat(video_chunks, dim=0) if video_chunks[0].dim() >= 3 else video_chunks[-1]
            else:
                video_tensor = torch.zeros(1)
        else:
            video_tensor = video_data

        # Convertir tensor en PIL frames
        if hasattr(video_tensor, 'cpu'):
            video_np = video_tensor.cpu().numpy()
        else:
            video_np = np.array(video_tensor)

        # Shape: [frames, H, W, C] ou [batch, frames, H, W, C]
        if video_np.ndim == 5:
            video_np = video_np[0]

        generated_frames = []
        for f in video_np:
            if f.dtype in (np.float32, np.float64) and f.max() <= 1.0:
                f = (f * 255).clip(0, 255).astype(np.uint8)
            generated_frames.append(Image.fromarray(f.astype(np.uint8)))

        # Cleanup temp image
        if _tmp_img_path:
            try:
                os.unlink(_tmp_img_path)
            except Exception:
                pass

        # Stocker l'audio LTX natif pour le muxage ffmpeg seulement si demandé.
        _store_ltx_native_audio(audio_data, label=fp8_label)

    elif is_ltx:
        video_prompt = _source_fidelity_prompt(DEFAULT_SCENE_VIDEO_PROMPT)
        negative_prompt = (
            "worst quality, inconsistent motion, blurry, jittery, distorted, "
            "distorted face, deformed face, disfigured, asymmetric eyes, strange mouth, "
            "deformed facial features, asymmetrical face, frame-by-frame facial drift, "
            "bad anatomy, extra limbs, missing limbs, malformed hands, extra fingers"
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        import torch
        gen = torch.Generator(device="cpu").manual_seed(42)
        if low_vram_ltx:
            requested_frames = target_frames
            target_frames = min(int(target_frames or 41), 41)
            fps = 8
            if requested_frames != target_frames:
                print(f"[VIDEO] LTX low-VRAM: frames cap {requested_frames} -> {target_frames}")
        else:
            fps = 24  # LTX natif 24fps

        # Frames: formule (N*8)+1 pour LTX
        ltx_frames = target_frames
        if (ltx_frames - 1) % 8 != 0:
            ltx_frames = ((ltx_frames - 1) // 8) * 8 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {ltx_frames} (formule 8k+1)")

        # Détecter quel pipeline est chargé
        try:
            from diffusers import LTXConditionPipeline
            _is_distilled = isinstance(pipe, LTXConditionPipeline)
        except ImportError:
            _is_distilled = False

        # Turbo-VAED pour décodage rapide (2.9x plus rapide, 97% qualité)
        # TEMPORAIREMENT DÉSACTIVÉ pour debug - utiliser VAE standard
        _use_turbo_vaed = False
        _turbo_skip_denorm = False
        print(f"[VIDEO] Turbo-VAED DÉSACTIVÉ (debug) - utilisation VAE standard")

        if _is_distilled:
            # LTX-Video 2B Distillé 0.9.8 — LTXConditionPipeline
            from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
            from diffusers.utils import export_to_video as _ltx_export, load_video as _ltx_load

            # Convertir l'image en condition vidéo (compression vidéo requise)
            _tmp_path = _ltx_export([image_resized], fps=1)
            video_cond = _ltx_load(_tmp_path)
            condition = LTXVideoCondition(video=video_cond, frame_index=0)

            # Timesteps officiels (config ltxv-2b-0.9.8-distilled.yaml)
            PASS1_TIMESTEPS = [1000, 993, 987, 981, 975, 909, 725, 0.03]
            PASS2_TIMESTEPS = [1000, 909, 725, 421, 0]

            # Toutes les branches produisent ltx_latents, decode à la fin
            ltx_latents = None
            decode_h, decode_w = target_h, target_w

            if upscale_pipe is not None and not low_vram_ltx:
                # === MULTI-SCALE (doc officielle) ===
                # Pass 1: générer à 2/3 résolution → latents
                downscale = 2 / 3
                ds_h = int(target_h * downscale)
                ds_w = int(target_w * downscale)
                # Arrondir aux multiples du VAE spatial compression
                vae_ratio = pipe.vae_spatial_compression_ratio
                ds_h = ds_h - (ds_h % vae_ratio)
                ds_w = ds_w - (ds_w % vae_ratio)

                print(f"[VIDEO] Mode: LTX-Video 2B distillé multi-scale")
                print(f"[VIDEO]   Pass 1: {ds_w}x{ds_h} → {len(PASS1_TIMESTEPS)} steps")

                with torch.inference_mode():
                    latents = pipe(
                        conditions=[condition],
                        prompt=video_prompt,
                        negative_prompt=negative_prompt,
                        height=ds_h,
                        width=ds_w,
                        num_frames=ltx_frames,
                        timesteps=PASS1_TIMESTEPS,
                        guidance_scale=1.0,
                        guidance_rescale=0.7,
                        decode_timestep=0.05,
                        decode_noise_scale=0.025,
                        image_cond_noise_scale=0.0,
                        generator=gen,
                        callback_on_step_end=video_step_callback,
                        output_type="latent",
                    ).frames

                # Upscale latents (2x spatial)
                print(f"[VIDEO]   Upscale latents ({ds_w}x{ds_h} → {ds_w*2}x{ds_h*2})")
                with torch.inference_mode():
                    upscaled_latents = upscale_pipe(
                        latents=latents,
                        adain_factor=1.0,
                        tone_map_compression_ratio=0.6,
                        output_type="latent",
                    ).frames

                # Pass 2: raffiner à pleine résolution → latents
                up_h, up_w = ds_h * 2, ds_w * 2
                decode_h, decode_w = up_h, up_w
                print(f"[VIDEO]   Pass 2: {up_w}x{up_h} → {len(PASS2_TIMESTEPS)} steps (raffinement)")

                with torch.inference_mode():
                    ltx_latents = pipe(
                        conditions=[condition],
                        prompt=video_prompt,
                        negative_prompt=negative_prompt,
                        height=up_h,
                        width=up_w,
                        num_frames=ltx_frames,
                        denoise_strength=0.999,
                        timesteps=PASS2_TIMESTEPS,
                        latents=upscaled_latents,
                        guidance_scale=1.0,
                        guidance_rescale=0.7,
                        decode_timestep=0.05,
                        decode_noise_scale=0.025,
                        image_cond_noise_scale=0.0,
                        generator=gen,
                        callback_on_step_end=video_step_callback,
                        output_type="latent",
                    ).frames

            else:
                # === SINGLE-PASS (fallback sans upscaler) ===
                print(f"[VIDEO] Mode: LTX-Video 2B distillé single-pass — {len(PASS1_TIMESTEPS)} steps")

                with torch.inference_mode():
                    ltx_latents = pipe(
                        conditions=[condition],
                        prompt=video_prompt,
                        negative_prompt=negative_prompt,
                        height=target_h,
                        width=target_w,
                        num_frames=ltx_frames,
                        timesteps=PASS1_TIMESTEPS,
                        guidance_scale=1.0,
                        guidance_rescale=0.7,
                        decode_timestep=0.05,
                        decode_noise_scale=0.025,
                        image_cond_noise_scale=0.0,
                        generator=gen,
                        callback_on_step_end=video_step_callback,
                        output_type="latent",
                    ).frames

            # === PASSES DE RAFFINEMENT (optionnel) ===
            if refine_passes > 0 and ltx_latents is not None:
                REFINE_TIMESTEPS = [1000, 909, 725, 421, 0]
                for rp in range(refine_passes):
                    strength = max(0.05, 0.15 - rp * 0.02)  # 0.15, 0.13, 0.11, 0.09, 0.07
                    print(f"[VIDEO]   Refine pass {rp+1}/{refine_passes} (denoise_strength={strength})")
                    with torch.inference_mode():
                        ltx_latents = pipe(
                            conditions=[condition],
                            prompt=video_prompt,
                            negative_prompt=negative_prompt,
                            height=decode_h,
                            width=decode_w,
                            num_frames=ltx_frames,
                            denoise_strength=strength,
                            timesteps=REFINE_TIMESTEPS,
                            latents=ltx_latents,
                            guidance_scale=1.0,
                            guidance_rescale=0.7,
                            decode_timestep=0.05,
                            decode_noise_scale=0.025,
                            image_cond_noise_scale=0.0,
                            generator=gen,
                            callback_on_step_end=video_step_callback,
                            output_type="latent",
                        ).frames

            # === DECODE FINAL ===
            # Le VAE LTX nécessite temb (timestep embedding) qu'on n'a pas lors du décodage manuel.
            # Solution: refaire un pass avec output_type="pil" pour que le pipeline décode lui-même.
            print(f"[VIDEO]   Décodage VAE (via pipeline)...")
            with torch.inference_mode():
                video_frames = pipe(
                    conditions=[condition],
                    prompt=video_prompt,
                    negative_prompt=negative_prompt,
                    height=decode_h,
                    width=decode_w,
                    num_frames=ltx_frames,
                    latents=ltx_latents,
                    denoise_strength=0.0,  # Pas de débruitage, juste décoder
                    guidance_scale=1.0,
                    decode_timestep=0.05,
                    decode_noise_scale=0.025,
                    generator=gen,
                    output_type="pil",
                ).frames[0]

            # Resize final à la résolution cible si différent (multi-scale)
            if decode_h != target_h or decode_w != target_w:
                video_frames = [frame.resize((target_w, target_h)) for frame in video_frames]
        else:
            # LTX-Video 2B Base — LTXImageToVideoPipeline, 50 steps, guidance=3.0
            LTX_GUIDANCE = 3.0
            print(f"[VIDEO] Mode: LTX-Video 2B base — guidance={LTX_GUIDANCE}, steps={num_steps}")

            if _use_turbo_vaed:
                with torch.inference_mode():
                    result_base = pipe(
                        image=image_resized,
                        prompt=video_prompt,
                        negative_prompt=negative_prompt,
                        height=target_h,
                        width=target_w,
                        num_frames=ltx_frames,
                        num_inference_steps=num_steps,
                        guidance_scale=LTX_GUIDANCE,
                        generator=gen,
                        decode_timestep=0.03,
                        decode_noise_scale=0.025,
                        callback_on_step_end=video_step_callback,
                        output_type="latent",
                    )
                latents_base = result_base.frames
                video_frames = turbo_vaed_decode_ltx(latents_base, pipe.vae, skip_denorm=_turbo_skip_denorm)
            else:
                with torch.inference_mode():
                    video_frames = pipe(
                        image=image_resized,
                        prompt=video_prompt,
                        negative_prompt=negative_prompt,
                        height=target_h,
                        width=target_w,
                        num_frames=ltx_frames,
                        num_inference_steps=num_steps,
                        guidance_scale=LTX_GUIDANCE,
                        generator=gen,
                        decode_timestep=0.03,
                        decode_noise_scale=0.025,
                        callback_on_step_end=video_step_callback,
                    ).frames[0]

        generated_frames = list(video_frames)

    elif is_cogvideo:
        # CogVideoX - params fixes (entraîné pour ces valeurs, pas configurable)
        COG_STEPS = 50  # Optimal qualité (entraîné à 50)
        COG_GUIDANCE = 6  # Recommandé officiel
        COG_FPS = 8  # Natif du modèle

        video_prompt = _source_fidelity_prompt(DEFAULT_VISUAL_SOURCE_VIDEO_PROMPT)
        negative_prompt_cog = (
            "Distorted, discontinuous, Ugly, blurry, low resolution, motionless, static, "
            "disfigured, disconnected limbs, Ugly faces, incomplete arms, "
            "inconsistent motion, blurry motion, worse quality, degenerate outputs, "
            "distorted face, deformed face, asymmetric eyes, strange mouth, "
            "frame-by-frame facial drift, bad anatomy, extra fingers, malformed hands"
        )
        print(f"[VIDEO] Prompt: {video_prompt}")

        # Override les settings user — CogVideoX a ses propres params optimaux
        num_steps = COG_STEPS
        fps = COG_FPS

        import torch
        gen = torch.Generator(device="cpu").manual_seed(42)

        supports_image = model_info.get('supports_image', True)

        # CogVideoX frames: formule 8k+1 (ex: 49, 41, 33)
        cog_frames = target_frames
        if (cog_frames - 1) % 8 != 0:
            cog_frames = ((cog_frames - 1) // 8) * 8 + 1
            print(f"[VIDEO] Frames ajusté: {target_frames} → {cog_frames} (formule 8k+1)")

        if supports_image:
            # CogVideoX-5B I2V — dynamic_cfg désactivé (bug diffusers #9641)
            print(f"[VIDEO] Mode: Image-to-Video (I2V) — guidance={COG_GUIDANCE}, steps={COG_STEPS}")
            with torch.inference_mode():
                video_frames = pipe(
                    prompt=video_prompt,
                    negative_prompt=negative_prompt_cog,
                    image=image_resized,
                    num_videos_per_prompt=1,
                    num_inference_steps=COG_STEPS,
                    num_frames=cog_frames,
                    height=target_h,
                    width=target_w,
                    guidance_scale=COG_GUIDANCE,
                    generator=gen,
                    callback_on_step_end=video_step_callback,
                ).frames[0]
        else:
            print(f"[VIDEO] Mode: Text-to-Video (T2V) — guidance={COG_GUIDANCE}, steps={COG_STEPS}")
            with torch.inference_mode():
                video_frames = pipe(
                    prompt=video_prompt,
                    negative_prompt=negative_prompt_cog,
                    num_videos_per_prompt=1,
                    num_inference_steps=COG_STEPS,
                    num_frames=cog_frames,
                    height=target_h,
                    width=target_w,
                    guidance_scale=COG_GUIDANCE,
                    generator=gen,
                    callback_on_step_end=video_step_callback,
                ).frames[0]

        generated_frames = list(video_frames)

    else:
        # SVD - multi-pass pour vidéos longues
        MAX_FRAMES_PER_PASS = 25
        num_passes = (target_frames + MAX_FRAMES_PER_PASS - 1) // MAX_FRAMES_PER_PASS
        update_video_progress(total_passes=num_passes)

        current_frame = image_resized
        generated_frames = []

        for pass_num in range(num_passes):
            frames_this_pass = min(MAX_FRAMES_PER_PASS, target_frames - len(generated_frames))
            print(f"[VIDEO] Passe {pass_num + 1}/{num_passes}: {frames_this_pass} frames...")
            update_video_progress(pass_num=pass_num + 1, message=f'Passe {pass_num + 1}/{num_passes}...')

            # SVD 1.1 was finetuned with fixed 6 FPS conditioning and motion
            # bucket 127. Keep export FPS separate from this micro-conditioning.
            svd_conditioning_fps = 6
            svd_decode_chunk_size = 1 if (low_vram_svd and fast_svd_8gb) else 2

            with torch.inference_mode():
                frames = pipe(
                    current_frame,
                    decode_chunk_size=svd_decode_chunk_size,
                    num_frames=frames_this_pass,
                    motion_bucket_id=127,
                    noise_aug_strength=0.02,
                    fps=svd_conditioning_fps,
                    num_inference_steps=num_steps,
                    height=target_h,
                    width=target_w,
                    callback_on_step_end=video_step_callback,
                ).frames[0]

            if pass_num > 0 and len(generated_frames) > 0:
                generated_frames.extend(frames[1:])
            else:
                generated_frames.extend(frames)

            current_frame = frames[-1]
            if len(generated_frames) >= target_frames:
                break

    gen_time = time.time() - start_time
    print(f"[VIDEO] ⏱️ Génération: {gen_time:.1f}s ({len(generated_frames)} frames)")

    # Sauvegarder la dernière frame pour continuation future (toujours PIL Image)
    if len(generated_frames) > 0:
        last_frame = generated_frames[-1]
        # S'assurer que c'est une PIL Image
        if not isinstance(last_frame, Image.Image):
            try:
                if hasattr(last_frame, 'cpu'):
                    last_frame = last_frame.cpu().numpy()
                if isinstance(last_frame, np.ndarray):
                    if last_frame.max() <= 1.0:
                        last_frame = (last_frame * 255).astype(np.uint8)
                    last_frame = Image.fromarray(last_frame)
            except Exception as e:
                print(f"[VIDEO] ⚠️ Impossible de convertir last_frame: {e}")
                last_frame = None
        _state.last_video_frame = last_frame
    else:
        _state.last_video_frame = None

    # Accumuler les frames. For persisted continuations we export only the new
    # segment, trimming the first generated frame to avoid duplicating the
    # selected anchor when the source MP4 is concatenated back in.
    if persisted_continuation:
        if len(generated_frames) > 1:
            _state.all_video_frames = list(generated_frames[1:])
        else:
            _state.all_video_frames = list(generated_frames)
    elif continue_from_last and len(_state.all_video_frames) > 0:
        _state.all_video_frames.extend(generated_frames[1:])
    else:
        _state.all_video_frames.extend(generated_frames)

    print(f"[VIDEO] Total frames accumulées: {len(_state.all_video_frames)}")

    if is_framepack and release_pipe_before_export:
        print("[VIDEO] FramePack: libération du modèle avant export MP4 (évite saturation RAM)")
        heavy_pipe = pipe
        pipe = None
        upscale_pipe = None
        try:
            release_pipe_before_export()
        except Exception as exc:
            print(f"[VIDEO] FramePack: libération modèle ignorée ({exc})")
        finally:
            del heavy_pipe
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ========== ÉTAPE 4b: RESTAURATION FACIALE ==========
    # face_restore: 'off', 'gfpgan', 'codeformer' (ou True/False pour rétro-compat)
    fr_method = face_restore
    if fr_method is True:
        fr_method = 'codeformer'
    elif fr_method is False or fr_method == 'off':
        fr_method = None

    if fr_method:
        try:
            from core.face_restore import restore_faces_in_frames
            print(f"[VIDEO] Étape 4b: Restauration faciale ({fr_method.upper()})...")
            update_video_progress(phase='face_restore', message=f'Restauration {fr_method.upper()}...')
            _state.all_video_frames = restore_faces_in_frames(
                _state.all_video_frames, method=fr_method, fidelity_weight=0.5
            )
        except Exception as e:
            print(f"[VIDEO] Restauration faciale ignorée ({e})")
    else:
        print("[VIDEO] Étape 4b: Restauration faciale DÉSACTIVÉE (settings)")

    # ========== ÉTAPE 5: EXPORT MP4 (VIDÉO COMPLÈTE) ==========
    # Streaming direct: chaque frame est convertie et envoyée à ffmpeg immédiatement
    # → PAS de copie numpy intermédiaire → économise la RAM du tableau frames_np
    print("[VIDEO] Étape 5: Export vidéo MP4 (streaming)...")
    update_video_progress(phase='encoding', step=0, total_steps=1, message='Export MP4...')
    output_dir = Path("output") / "videos"
    output_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_filename = f"video_{timestamp}_{chat_id}.mp4" if chat_id else f"video_{timestamp}.mp4"
    mp4_path = output_dir / video_filename

    def _frame_to_rgb_bytes(frame):
        """Convertit une frame (PIL/numpy/tensor) en bytes RGB24 uint8."""
        if isinstance(frame, Image.Image):
            return np.array(frame.convert('RGB')).tobytes()
        elif isinstance(frame, np.ndarray):
            if frame.dtype != np.uint8:
                frame = (frame * 255).clip(0, 255).astype(np.uint8)
            return frame[:, :, :3].tobytes()
        elif hasattr(frame, 'cpu'):  # torch tensor
            f = frame.cpu().numpy()
            if f.max() <= 1.0:
                f = (f * 255).clip(0, 255).astype(np.uint8)
            if f.ndim == 3 and f.shape[0] in (3, 4):  # CHW → HWC
                f = np.transpose(f, (1, 2, 0))
            return f[:, :, :3].tobytes()
        else:
            return np.array(frame).tobytes()

    # Obtenir les dimensions depuis la première frame (sans copier tout)
    first = _state.all_video_frames[0]
    if isinstance(first, Image.Image):
        w_out, h_out = first.size
    elif isinstance(first, np.ndarray):
        h_out, w_out = first.shape[:2]
    elif hasattr(first, 'shape'):  # torch tensor
        if first.ndim == 3 and first.shape[0] in (3, 4):
            h_out, w_out = first.shape[1], first.shape[2]
        else:
            h_out, w_out = first.shape[:2]
    else:
        arr = np.array(first)
        h_out, w_out = arr.shape[:2]

    preencoded_path = locals().get("preencoded_video_path")
    use_preencoded_mp4 = bool(preencoded_path and not persisted_continuation and not continue_from_last and not fr_method)
    native_audio_muxed = False

    try:
        if use_preencoded_mp4:
            video_path = Path(preencoded_path)
            video_format = "mp4"
            update_video_progress(phase='encoding', step=1, total_steps=1, message='MP4 LightX2V prêt')
            print(f"[VIDEO] Export MP4 ignoré: LightX2V a déjà écrit {video_path}")
            if not video_path.exists() or video_path.stat().st_size <= 0:
                raise RuntimeError(f"MP4 LightX2V invalide: {video_path}")
        else:
            try:
                import imageio_ffmpeg
            except ImportError:
                print("[VIDEO] Installation imageio-ffmpeg...")
                import subprocess
                import sys
                subprocess.check_call([sys.executable, "-m", "pip", "install", "imageio-ffmpeg", "-q"])
                import imageio_ffmpeg

            import subprocess

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

            cmd = [
                ffmpeg_path, '-y',
                '-f', 'rawvideo', '-vcodec', 'rawvideo',
                '-s', f'{w_out}x{h_out}',
                '-pix_fmt', 'rgb24',
                '-r', str(fps),
                '-i', '-',
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p',
                '-crf', '23',
                '-vf', 'scale=in_range=pc:out_range=tv',
                '-color_range', 'tv',
                '-colorspace', 'bt709',
                '-color_trc', 'bt709',
                '-color_primaries', 'bt709',
                str(mp4_path),
            ]

            import threading
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

            # Thread pour drainer stderr en parallèle (évite deadlock si ffmpeg écrit >64KB)
            stderr_chunks = []
            def _drain_stderr():
                for line in process.stderr:
                    stderr_chunks.append(line)
            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            total_enc = len(_state.all_video_frames)
            update_video_progress(
                phase='encoding',
                step=0,
                total_steps=total_enc,
                message=f'Export MP4 0/{total_enc}...'
            )
            for fi, frame in enumerate(_state.all_video_frames):
                process.stdin.write(_frame_to_rgb_bytes(frame))
                pct = (fi + 1) / total_enc
                update_video_progress(
                    phase='encoding',
                    step=fi + 1,
                    total_steps=total_enc,
                    message=f'Export MP4 {fi + 1}/{total_enc}...'
                )
                bar_len = 30
                filled = int(bar_len * pct)
                bar = '█' * filled + '░' * (bar_len - filled)
                print(f"\r   [{bar}] {pct*100:5.1f}% | Frame {fi+1}/{total_enc}", end='', flush=True)
            print()

            process.stdin.close()
            stderr_thread.join(timeout=30)
            process.wait()
            if process.returncode != 0:
                stderr_output = b''.join(stderr_chunks).decode(errors='replace')
                raise RuntimeError(f"ffmpeg error: {stderr_output[-500:]}")

            video_path = mp4_path
            video_format = "mp4"
            print(f"[VIDEO] Export MP4 réussi (streaming direct, bt709 standard range)")

        # Muxer l'audio LTX-2 si disponible. For persisted continuations,
        # audio is generated after the final concatenated clip so the sound bed
        # matches the whole video instead of only the new segment.
        ltx2_audio = getattr(_state, 'ltx2_audio', None)
        if ltx2_audio is not None and ltx_native_audio_requested and not persisted_continuation:
            try:
                import torch as _t
                import tempfile, wave
                if "ffmpeg_path" not in locals():
                    import imageio_ffmpeg
                    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
                audio_sr = getattr(_state, 'ltx2_audio_sr', 24000)
                # audio_data: tensor [batch, samples] ou [samples]
                audio_tensor = ltx2_audio[0] if ltx2_audio.dim() >= 2 else ltx2_audio
                audio_np = audio_tensor.float().cpu().numpy()
                # Normaliser en int16
                audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

                # Écrire WAV temporaire
                wav_tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                with wave.open(wav_tmp.name, 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(audio_sr)
                    wf.writeframes(audio_int16.tobytes())

                # Muxer video + audio
                muxed_path = str(mp4_path).replace('.mp4', '_av.mp4')
                mux_cmd = [
                    ffmpeg_path, '-y',
                    '-i', str(mp4_path),
                    '-i', wav_tmp.name,
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                    '-shortest',
                    muxed_path,
                ]
                mux_proc = subprocess.run(mux_cmd, capture_output=True, timeout=60)
                if mux_proc.returncode == 0:
                    os.replace(muxed_path, str(mp4_path))
                    native_audio_muxed = True
                    print(f"[VIDEO] Audio LTX-2 muxé dans le MP4 (sr={audio_sr})")
                else:
                    print(f"[VIDEO] Muxage audio échoué: {mux_proc.stderr[-200:]}")

                os.unlink(wav_tmp.name)
                _state.ltx2_audio = None
            except Exception as e:
                print(f"[VIDEO] Erreur muxage audio LTX-2: {e}")
        elif ltx2_audio is not None and persisted_continuation:
            _state.ltx2_audio = None
            print("[VIDEO] Audio LTX-2 segment ignoré: audio final géré après continuation")
        elif ltx2_audio is not None:
            _state.ltx2_audio = None
            print("[VIDEO] Audio LTX-2 ignoré: audio natif non demandé")
    except Exception as e:
        print(f"[VIDEO] MP4 échoué: {e}, fallback GIF...")
        from diffusers.utils import export_to_gif
        gif_filename = f"video_{chat_id}.gif" if chat_id else "video.gif"
        gif_path = output_dir / gif_filename
        export_to_gif(_state.all_video_frames, str(gif_path))
        video_path = gif_path
        video_format = "gif"

    continuation_merged = False
    if persisted_continuation and source_video_path and video_format == "mp4":
        merged_path = concat_video_segments(source_video_path, video_path, fps=fps)
        if merged_path:
            video_path = merged_path
            continuation_merged = True
            print(f"[VIDEO] Continuation raccordée au clip source: {video_path}")
        else:
            print("[VIDEO] Raccord continuation ignoré: segment généré conservé seul")

    # ========== ÉTAPE 6: MMAUDIO - Ajout du son ==========
    # MMAudio is a large extra model. On 8-10GB cards it competes with video
    # generation/cache and can saturate VRAM for a non-essential post-process.
    allow_low_vram_mmaudio = os.environ.get("JOYBOY_ALLOW_MMAUDIO_LOW_VRAM", "").strip().lower() in {"1", "true", "yes", "on"}
    run_mmaudio = (
        add_audio
        and video_format == "mp4"
        and normalized_audio_engine != "native"
        and not (native_audio_muxed and normalized_audio_engine == "auto")
    )
    mmaudio_low_vram_blocked = run_mmaudio and 0 < float(VRAM_GB or 0) <= 10 and not allow_low_vram_mmaudio
    if mmaudio_low_vram_blocked:
        print(
            f"[VIDEO] MMAudio ignoré: {VRAM_GB:.1f}GB VRAM détectés. "
            "Audio auto trop lourd sur petite VRAM "
            "(override: JOYBOY_ALLOW_MMAUDIO_LOW_VRAM=1)."
        )
        unload_mmaudio()
    elif run_mmaudio:
        try:
            audio_path = add_audio_to_video(
                str(video_path),
                audio_prompt or prompt or _state.last_video_prompt,
            )
            if audio_path:
                video_path = Path(audio_path)
                print(f"[VIDEO] Son ajouté avec MMAudio")
        except Exception as e:
            print(f"[VIDEO] MMAudio ignoré: {e}")

    effective_video_prompt = locals().get("video_prompt") or prompt or "Image-to-video motion"
    segment_frames = len(_state.all_video_frames)
    include_source_frames = persisted_continuation and continuation_merged
    inherited_keyframes = (continuation_context.get("source_keyframes") or []) if include_source_frames else []
    total_frames_for_asset = source_frame_count + segment_frames if include_source_frames else segment_frames
    total_duration_for_asset = round(total_frames_for_asset / fps, 3) if fps else None
    session = create_video_session(
        video_path=video_path,
        frames=_state.all_video_frames,
        prompt=prompt or effective_video_prompt,
        final_prompt=effective_video_prompt,
        model_id=video_model,
        model_name=model_info.get("name", video_model),
        fps=fps,
        chat_id=chat_id,
        video_format=video_format,
        width=locals().get("w_out"),
        height=locals().get("h_out"),
        source_session_id=continuation_context.get("source_session_id"),
        anchor_frame_index=continuation_context.get("anchor_frame_index"),
        analysis_summary=continuation_context.get("analysis_summary") or {},
        continuation_prompt=continuation_context.get("continuation_prompt") or "",
        audio_engine=audio_engine or "auto",
        audio_prompt=audio_prompt or "",
        inherited_keyframes=inherited_keyframes,
        frame_index_offset=source_frame_count if include_source_frames else 0,
    )
    _state.last_video_session = session
    _state.last_video_total_frames = total_frames_for_asset
    _state.last_video_duration_sec = total_duration_for_asset or 0

    save_gallery_metadata(
        video_path,
        schema=2,
        asset_type="video",
        source="video",
        model=model_info.get("name", video_model),
        model_id=video_model,
        prompt=prompt or effective_video_prompt,
        final_prompt=effective_video_prompt,
        video_session_id=session.get("id"),
        source_video_session_id=session.get("source_session_id"),
        continuation_prompt=session.get("continuation_prompt"),
        analysis_summary=session.get("analysis_summary"),
        audio_engine=session.get("audio_engine"),
        audio_prompt=session.get("audio_prompt"),
        steps=num_steps,
        fps=fps,
        frames=total_frames_for_asset,
        duration_sec=total_duration_for_asset,
        width=w_out,
        height=h_out,
    )

    # Convertir en base64 pour le web
    import base64
    with open(video_path, "rb") as f:
        video_base64 = base64.b64encode(f.read()).decode('utf-8')

    total_duration = total_duration_for_asset or 0
    print(f"[VIDEO] ✅ Terminé! {total_frames_for_asset} frames (~{total_duration:.1f}s de vidéo)")

    # Nettoyer la progression (le cleanup VRAM est fait par generation_pipeline)
    clear_video_progress()

    return video_base64, _state.last_video_frame, video_format
