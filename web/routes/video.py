"""
Blueprint pour les routes video (generate-video, video-progress, video-models, reset-video, etc.).
"""
from flask import Blueprint, request, jsonify
import base64
import fnmatch
import os
import shutil
import threading
import tempfile
import uuid

video_bp = Blueprint('video', __name__)
video_download_status = {}

_LIGHTWEIGHT_REWRITE_MODELS = {
    "qwen3.5:2b",
    "qwen3.5:0.8b",
    "qwen3:0.6b",
    "qwen3:1.7b",
}


def _as_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _video_prompt_rewrite_model(chat_model=None, *, vram_gb=0):
    """Pick the text model used to rewrite prompts before a heavy video run."""
    configured = os.environ.get("JOYBOY_VIDEO_PROMPT_REWRITE_MODEL", "").strip()
    if configured:
        return configured

    requested = str(chat_model or "").strip()
    current_vram = _as_float(vram_gb)
    try:
        min_vram = float(os.environ.get("JOYBOY_VIDEO_PROMPT_REWRITE_HEAVY_MIN_VRAM_GB", "24"))
    except ValueError:
        min_vram = 24.0

    if current_vram >= min_vram and (not requested or requested in _LIGHTWEIGHT_REWRITE_MODELS):
        try:
            from config import AUTO_HIGH_END_CHAT_MODEL
            return AUTO_HIGH_END_CHAT_MODEL or requested or None
        except Exception:
            return requested or None
    return requested or None


def _prefer_lightx2v_high_end_model(video_model, *, video_models, cache_dir, vram_gb=0):
    """Prefer downloaded LightX2V over the native Wan 14B path on high-end GPUs."""
    requested = str(video_model or "").strip()
    try:
        from core.models.video_policy import normalize_video_model_id
        requested = normalize_video_model_id(requested)
    except Exception:
        pass
    if requested != "wan-native-14b":
        return requested
    if os.environ.get("JOYBOY_PREFER_LIGHTX2V_ON_HIGH_END", "1").strip().lower() in {"0", "false", "no", "off"}:
        return requested
    if _as_float(vram_gb) < 48.0:
        return requested

    target = os.environ.get("JOYBOY_HIGH_END_I2V_MODEL", "lightx2v-wan22-i2v-4step").strip()
    if not target or target == requested or target not in video_models:
        return requested

    meta = video_models.get(target, {})
    if meta.get("backend") != "lightx2v":
        return requested
    try:
        if not _video_model_downloaded(meta, cache_dir):
            return requested
    except Exception:
        return requested

    print(f"[VIDEO_POLICY] {requested} remplacé par {target} (LightX2V déjà téléchargé sur grosse VRAM)")
    return target


def _rewrite_video_prompt_for_high_vram(prompt, *, chat_model=None, vram_gb=0):
    """Rewrite/translate video prompts with the selected chat model on high-VRAM machines only."""
    clean = str(prompt or "").strip()
    if not clean:
        return clean

    mode = os.environ.get("JOYBOY_VIDEO_PROMPT_REWRITE", "auto").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return clean

    try:
        min_vram = float(os.environ.get("JOYBOY_VIDEO_PROMPT_REWRITE_MIN_VRAM_GB", "24"))
    except ValueError:
        min_vram = 24.0
    current_vram = _as_float(vram_gb)
    if mode not in {"1", "true", "yes", "on", "force"} and current_vram < min_vram:
        return clean

    try:
        from core.utility_ai import _call_utility

        messages = [
            {
                "role": "system",
                "content": (
                    "Translate or rewrite the user's request into a concise English prompt for an image-to-video model. "
                    "Preserve the user's intent. Focus on visible motion and temporal action. "
                    "Do not add unrelated details. Reply with only the final prompt."
                ),
            },
            {"role": "user", "content": clean},
        ]
        rewritten = _call_utility(
            messages,
            num_predict=140,
            temperature=0.1,
            timeout=20,
            model=_video_prompt_rewrite_model(chat_model, vram_gb=current_vram),
        )
    except Exception as exc:
        print(f"[VIDEO] Prompt rewrite LLM ignoré ({exc})")
        return clean

    rewritten = " ".join(str(rewritten or "").split()).strip(" \"'")
    if not rewritten:
        return clean
    if rewritten.lower().startswith("prompt:"):
        rewritten = rewritten.split(":", 1)[1].strip()
    return rewritten or clean


# --- Helper: lazy imports from web.app to avoid circular imports ---

def _get_state():
    from web.app import state
    return state

def _get_active_generations():
    from web.app import active_generations
    return active_generations

def _get_generations_lock():
    from web.app import generations_lock
    return generations_lock

def _get_generation_pipeline():
    from web.app import generation_pipeline
    return generation_pipeline

def _is_generation_cancelled():
    from web.app import generation_cancelled
    return generation_cancelled

def _set_generation_cancelled(value):
    import web.app as app_module
    app_module.generation_cancelled = value

def _base64_to_pil(b64_string):
    from web.app import base64_to_pil
    return base64_to_pil(b64_string)

def _pil_to_base64(img):
    from web.app import pil_to_base64
    return pil_to_base64(img)


# --- Routes ---

@video_bp.route('/video-source', methods=['POST'])
def register_video_source():
    """Register an uploaded/pasted video as a continuation source session."""
    from core.api_helpers import validation_error

    try:
        data = request.json or {}
        video_data = str(data.get('video') or '').strip()
        if not video_data:
            return validation_error('Video requise')

        header = ''
        payload = video_data
        if ',' in video_data and video_data.startswith('data:'):
            header, payload = video_data.split(',', 1)
        mime = 'video/mp4'
        if header:
            mime = header.split(';', 1)[0].replace('data:', '') or mime
        if not mime.startswith('video/'):
            return validation_error('Le fichier colle doit etre une video')

        ext_map = {
            'video/mp4': '.mp4',
            'video/webm': '.webm',
            'video/quicktime': '.mov',
            'video/x-matroska': '.mkv',
        }
        suffix = ext_map.get(mime, '.mp4')
        try:
            raw = base64.b64decode(payload, validate=True)
        except Exception:
            return validation_error('Video base64 invalide')

        max_bytes = int(os.environ.get('JOYBOY_VIDEO_UPLOAD_MAX_MB', '512')) * 1024 * 1024
        if len(raw) > max_bytes:
            return validation_error('Video trop lourde pour cet upload local')

        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(tmp_path, 'wb') as handle:
                handle.write(raw)

            from core.generation.video_sessions import create_video_source_session, public_video_session

            fps = int(data.get('fps') or 24)
            session = create_video_source_session(
                video_path=tmp_path,
                prompt=str(data.get('prompt') or '').strip(),
                model_id=str(data.get('video_model') or 'external-video'),
                model_name='Video importee',
                fps=fps,
                chat_id=data.get('chatId'),
                video_format=suffix.lstrip('.'),
            )
            public = public_video_session(session)
            return jsonify({
                'success': True,
                **public,
                'durationSec': session.get('duration_sec'),
                'frames': session.get('frames'),
                'fps': session.get('fps'),
                'fileName': data.get('fileName') or 'video',
            })
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(exc)}), 500

@video_bp.route('/generate-video', methods=['POST'])
def generate_video_endpoint():
    """Genere une video avec le modele selectionne (SVD, CogVideoX, etc.)"""
    _set_generation_cancelled(False)  # Reset au debut de chaque generation video
    import time
    generation_id = None

    active_generations = _get_active_generations()
    generation_pipeline = _get_generation_pipeline()
    base64_to_pil = _base64_to_pil

    from core.api_helpers import cancelled_response, error_response, validation_error, video_response

    try:
        data = request.json
        image_b64 = data.get('image')
        prompt = data.get('prompt', '')
        video_model = data.get('video_model', 'svd')
        requested_video_model = video_model
        continue_from_last = data.get('continue', False)
        add_audio = data.get('add_audio', False) is True
        face_restore = data.get('face_restore', 'off')  # 'off', 'gfpgan', 'codeformer'
        # Migration: ancien booleen -> string
        if face_restore is True:
            face_restore = 'codeformer'
        elif face_restore is False:
            face_restore = 'off'
        chat_model = str(data.get('chat_model') or '').strip()
        chat_id = data.get('chatId')
        quality = data.get('quality', '720p')
        refine_passes = int(data.get('refine_passes', 0))
        allow_experimental_video = bool(data.get('allow_experimental_video', False))
        source_video_session_id = (
            data.get('source_video_session_id')
            or data.get('videoSessionId')
            or data.get('video_session_id')
        )
        try:
            anchor_frame_index = int(data.get('anchor_frame_index')) if data.get('anchor_frame_index') is not None else None
        except (TypeError, ValueError):
            anchor_frame_index = None
        continuation_prompt = str(data.get('continuation_prompt') or '').strip()
        analyze_video = data.get('analyze_video', True) is not False
        video_analysis_model = str(data.get('video_analysis_model') or '').strip() or None
        audio_engine = str(data.get('audio_engine') or ('mmaudio' if add_audio else 'auto')).strip() or 'auto'
        audio_prompt = str(data.get('audio_prompt') or '').strip()

        # Politique runtime: evite les backends connus comme instables en low VRAM.
        from core.models import VIDEO_MODELS as _VM, VRAM_GB, custom_cache
        from core.models.video_policy import (
            get_runtime_video_defaults,
            is_low_vram,
            model_supports_continuation,
            model_supports_text_to_video,
            resolve_video_model_for_runtime,
        )
        from core.generation.video_sessions import (
            analyze_video_session,
            build_continuation_prompt,
            find_latest_video_session,
            get_anchor_image,
            load_video_session,
        )

        video_model = _prefer_lightx2v_high_end_model(
            video_model,
            video_models=_VM,
            cache_dir=custom_cache,
            vram_gb=VRAM_GB,
        )

        model_policy = resolve_video_model_for_runtime(
            video_model,
            vram_gb=VRAM_GB,
            allow_experimental=allow_experimental_video,
        )
        video_policy_warning = model_policy.warning
        if model_policy.changed:
            print(f"[VIDEO_POLICY] {video_policy_warning}")
            video_model = model_policy.model

        # Params selon le modele (defaults intelligents)
        _model_defaults = _VM.get(video_model, {})
        runtime_defaults = get_runtime_video_defaults(video_model, _model_defaults, vram_gb=VRAM_GB)
        default_frames = runtime_defaults['default_frames']
        default_steps = runtime_defaults['default_steps']
        default_fps = runtime_defaults['default_fps']

        if model_policy.changed or (is_low_vram(VRAM_GB) and video_model == 'svd'):
            # The frontend may have sent parameters for the blocked model. When
            # we reroute, use the effective model defaults to avoid odd durations.
            # On <=10GB, also ignore stale localStorage sliders for SVD; otherwise
            # old 24fps/120-frame settings make the "safe" path heavy again.
            target_frames = default_frames
            num_steps = default_steps
            fps = default_fps
        else:
            target_frames = data.get('target_frames', default_frames)
            num_steps = data.get('num_steps', default_steps)
            fps = data.get('fps', default_fps)

        source_video_session = None
        continuation_context = {}
        analysis_summary = {}
        if continue_from_last:
            if source_video_session_id:
                source_video_session = load_video_session(source_video_session_id)
            elif chat_id:
                source_video_session = find_latest_video_session(chat_id)

            if source_video_session:
                if not model_supports_continuation(_model_defaults):
                    return validation_error('Ce modele video ne supporte pas la continuation depuis une video source')
                anchor_image = get_anchor_image(source_video_session, anchor_frame_index)
                if anchor_image is None:
                    return validation_error('Impossible de charger la frame d ancrage de cette video')
                user_continuation = continuation_prompt or prompt
                if analyze_video:
                    analysis_summary = analyze_video_session(
                        source_video_session,
                        user_prompt=user_continuation,
                        model=video_analysis_model,
                    )
                prompt = build_continuation_prompt(
                    source_video_session.get('final_prompt') or source_video_session.get('prompt') or '',
                    user_continuation,
                    analysis_summary,
                )
                if not audio_prompt:
                    audio_prompt = (
                        analysis_summary.get('audio_prompt')
                        or user_continuation
                        or source_video_session.get('final_prompt')
                        or source_video_session.get('prompt')
                        or ''
                    )
                image_b64 = None
                continuation_context = {
                    "source_session_id": source_video_session.get("id"),
                    "source_video_path": source_video_session.get("video_path"),
                    "source_frames": source_video_session.get("frames") or 0,
                    "source_width": source_video_session.get("width"),
                    "source_height": source_video_session.get("height"),
                    "source_keyframes": source_video_session.get("keyframes") or [],
                    "anchor_frame_index": anchor_frame_index,
                    "continuation_prompt": user_continuation,
                    "analysis_summary": analysis_summary,
                    "anchor_image": anchor_image,
                }
            elif continuation_prompt and not prompt:
                prompt = continuation_prompt

        rewrite_model = _video_prompt_rewrite_model(chat_model, vram_gb=VRAM_GB)
        rewritten_prompt = _rewrite_video_prompt_for_high_vram(
            prompt,
            chat_model=rewrite_model,
            vram_gb=VRAM_GB,
        )
        if rewritten_prompt != prompt:
            print(f"[VIDEO] Prompt réécrit par LLM ({rewrite_model or 'auto'}): {rewritten_prompt}")
            prompt = rewritten_prompt

        # T2V mode: allow no image for models that support it
        if not image_b64 and not continue_from_last:
            if not model_supports_text_to_video(_model_defaults):
                return validation_error('Image requise (ce modele ne supporte pas T2V)')
            else:
                print(f"  [T2V MODE] Generation sans image avec {video_model}")

        # ===== LOG =====
        from core.models import VIDEO_MODELS
        model_info = VIDEO_MODELS.get(video_model, VIDEO_MODELS["svd"])
        duration_sec = target_frames / fps if fps > 0 else 0

        print(f"\n{'='*60}")
        print(f"  VIDEO REQUEST | {model_info['name']} | {duration_sec:.1f}s ({target_frames} frames)")
        print(f"{'='*60}")
        print(f"  Model:    {video_model}")
        print(f"  Quality:  {quality}")
        print(f"  Steps:    {num_steps} | FPS: {fps}")
        print(f"  Continue: {continue_from_last}")
        print(f"  SourceID: {source_video_session.get('id') if source_video_session else '-'}")
        print(f"  Audio:    {add_audio}")
        print(f"  AudioEng: {audio_engine}")
        print(f"  FaceRest: {face_restore}")
        print(f"  Refine:   {refine_passes} passes")
        print(f"  Image:    {'OUI (' + str(len(image_b64) // 1024) + 'KB)' if image_b64 else 'NON (T2V mode)'}")
        if prompt:
            print(f"  Prompt:   {prompt[:80]}")
        else:
            print(f"  Prompt:   (aucun -- prompt par defaut)")
        print(f"  ChatID:   {chat_id}")
        print(f"{'='*60}")

        generation_id = str(uuid.uuid4())
        active_generations[generation_id] = {"cancelled": False, "chat_id": chat_id}
        start_time = time.time()

        from core.runtime import get_job_manager, get_conversation_store
        job_manager = get_job_manager()
        conversation_store = get_conversation_store()
        job_manager.create(
            "video",
            job_id=generation_id,
            conversation_id=chat_id,
            prompt=prompt,
            model=video_model,
            metadata={
                "requested_model": requested_video_model,
                "effective_model": video_model,
                "quality": quality,
                "target_frames": target_frames,
                "steps": num_steps,
                "fps": fps,
                "add_audio": add_audio,
                "audio_engine": audio_engine,
                "source_video_session_id": source_video_session.get("id") if source_video_session else None,
                "face_restore": face_restore,
            },
        )
        if chat_id:
            conversation_store.ensure(chat_id, title="Video generation")
            conversation_store.attach_job(chat_id, generation_id, kind="video", prompt=prompt)
        job_manager.update(generation_id, status="running", phase="loading", progress=3, message="Chargement du modèle vidéo")

        def is_cancelled():
            if job_manager.is_cancel_requested(generation_id):
                return True
            if _is_generation_cancelled():
                return True
            gen = active_generations.get(generation_id)
            if gen:
                return gen.get("cancelled", False)
            return False

        from core.processing import generate_video, GenerationCancelledException
        from core.generation.video_optimizations import is_cuda_oom_error, temporary_env

        with generation_pipeline('video', generation_id, model_name=video_model) as mgr:
            if is_cancelled():
                job_manager.cancel(generation_id)
                return cancelled_response()

            def run_video_generation():
                img = continuation_context.get("anchor_image") or (base64_to_pil(image_b64) if image_b64 else None)
                pipe = mgr.get_pipeline('video')
                upscale_pipe = mgr.get_pipeline('video_upscale')
                try:
                    from core.infra.model_imports import apply_active_video_loras

                    loaded_video_loras = apply_active_video_loras(pipe, video_model)
                    if loaded_video_loras:
                        print("[VIDEO-LORA] Actifs: " + ", ".join(
                            str(item.get("display_name") or item.get("name") or item.get("id"))
                            for item in loaded_video_loras
                        ))
                except Exception as exc:
                    print(f"[VIDEO-LORA] Application ignorée: {exc}")
                return generate_video(
                    img,
                    prompt=prompt,
                    target_frames=target_frames,
                    num_steps=num_steps,
                    fps=fps,
                    video_model=video_model,
                    continue_from_last=continue_from_last,
                    unload_after=False,  # generation_pipeline handles cleanup
                    chat_id=chat_id,
                    pipe=pipe,
                    upscale_pipe=upscale_pipe,
                    cancel_check=is_cancelled,
                    add_audio=add_audio,
                    quality=quality,
                    face_restore=face_restore,
                    refine_passes=refine_passes,
                    continuation_context=continuation_context,
                    audio_engine=audio_engine,
                    audio_prompt=audio_prompt,
                    release_pipe_before_export=mgr._unload_video if video_model in ("framepack", "framepack-fast") else None,
                )

            job_manager.update(generation_id, phase="generating", progress=12, message="Génération vidéo en cours")
            try:
                video_base64, last_frame, video_format = run_video_generation()
            except RuntimeError as exc:
                if not is_cuda_oom_error(exc):
                    raise
                print(f"[VIDEO] CUDA OOM pendant génération ({video_model}); unload + retry en offload...")
                job_manager.update(
                    generation_id,
                    phase="loading",
                    progress=8,
                    message="VRAM saturée, retry en offload",
                )
                mgr._unload_video()
                mgr._clear_memory(aggressive=True)
                with temporary_env(mgr._video_oom_fallback_env(video_model)):
                    mgr._load_video(video_model)
                    video_base64, last_frame, video_format = run_video_generation()

            generation_time = time.time() - start_time

            if video_base64:
                from core.processing import get_video_info
                video_info = get_video_info()

                total_duration = video_info['duration_sec']
                total_frames = video_info['total_frames']
                print(f"[VIDEO] Termine en {generation_time:.1f}s | {total_frames} frames | ~{total_duration:.1f}s de video")
                print(f"{'='*50}\n")

                job_manager.complete(
                    generation_id,
                    message="Vidéo terminée",
                    artifact={
                        "type": "video",
                        "format": video_format,
                        "total_frames": total_frames,
                        "duration": total_duration,
                        "generation_time": generation_time,
                        "chat_id": chat_id,
                    },
                )
                return video_response(
                    video_base64,
                    video_format,
                    generation_time=generation_time,
                    total_frames=total_frames,
                    total_duration=total_duration,
                    can_continue=video_info['can_continue'],
                    warning=video_policy_warning,
                    requestedModel=requested_video_model,
                    effectiveModel=video_model,
                    videoSessionId=video_info.get('video_session_id'),
                    sourceVideoSessionId=video_info.get('source_video_session_id'),
                    continuationAnchors=video_info.get('continuation_anchors') or [],
                    analysisSummary=video_info.get('analysis_summary') or analysis_summary,
                    audioEngine=audio_engine,
                )
            else:
                print(f"[VIDEO] Erreur: {video_format}")
                job_manager.fail(generation_id, video_format)
                return error_response(video_format)

    except GenerationCancelledException:
        print(f"\n[VIDEO] Annule par l'utilisateur")
        from core.processing import clear_video_progress
        clear_video_progress()
        if generation_id:
            try:
                from core.runtime import get_job_manager
                get_job_manager().cancel(generation_id)
            except Exception:
                pass
        return cancelled_response()

    except Exception as e:
        print(f"[VIDEO] ERREUR: {e}")
        import traceback
        traceback.print_exc()
        from core.processing import clear_video_progress
        clear_video_progress()
        if generation_id:
            try:
                from core.runtime import get_job_manager
                get_job_manager().fail(generation_id, str(e))
            except Exception:
                pass
        return error_response(str(e))


@video_bp.route('/video-progress', methods=['GET'])
def video_progress_endpoint():
    """Retourne la progression globale de la generation video.

    The frontend intentionally attaches this single global state to the newest
    active video skeleton in the chat. If this ever becomes per-generation, also
    pass a stable generation id to the UI to avoid updating old messages.
    """
    try:
        from core.processing import get_video_progress
        progress = get_video_progress()
        return jsonify(progress)
    except Exception as e:
        return jsonify({'error': str(e), 'active': False})


@video_bp.route('/api/video-models', methods=['GET'])
def get_video_models():
    """Retourne le catalogue video filtre pour la machine courante."""
    from core.models import VIDEO_MODELS, VRAM_GB
    from core.models.video_policy import build_video_model_catalog

    include_advanced = str(request.args.get("advanced", "")).lower() in {"1", "true", "yes", "on"}
    allow_experimental = str(request.args.get("allow_experimental", "")).lower() in {"1", "true", "yes", "on"}
    return jsonify(build_video_model_catalog(
        VIDEO_MODELS,
        vram_gb=VRAM_GB,
        include_advanced=include_advanced,
        allow_experimental=allow_experimental,
    ))


def _video_repo_downloaded(repo_id, cache_dir):
    """Return whether a Hugging Face video repo is already cached locally."""
    local_dir = os.path.join(cache_dir, str(repo_id).replace("/", "--"))
    if os.path.exists(local_dir):
        try:
            with os.scandir(local_dir) as entries:
                if any(entries):
                    return True
        except OSError:
            pass

    try:
        from huggingface_hub import scan_cache_dir
        cache_dirs = [
            cache_dir,
            os.path.expanduser("~/.cache/huggingface"),
            os.path.join(os.environ.get("USERPROFILE", ""), ".cache", "huggingface"),
        ]
        for candidate in cache_dirs:
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                cache_info = scan_cache_dir(candidate)
                if any(repo.repo_id == repo_id for repo in cache_info.repos):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _normalize_hf_patterns(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(pattern).strip() for pattern in value if str(pattern).strip()]
    return []


def _video_repo_allow_patterns(meta, repo_id):
    allow = (meta or {}).get("hf_allow_patterns")
    if not isinstance(allow, dict):
        return []
    patterns = allow.get(repo_id) or allow.get(str(repo_id).replace("/", "--"))
    return _normalize_hf_patterns(patterns)


def _video_repo_required_files(meta, repo_id):
    required = (meta or {}).get("hf_required_files")
    if not isinstance(required, dict):
        return []
    patterns = required.get(repo_id) or required.get(str(repo_id).replace("/", "--"))
    return _normalize_hf_patterns(patterns)


def _matches_hf_patterns(path, patterns):
    if not patterns:
        return True
    normalized = str(path).replace("\\", "/")
    basename = os.path.basename(normalized)
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern)
        for pattern in patterns
    )


def _video_repo_size(repo_id, allow_patterns=None):
    try:
        from huggingface_hub import HfApi
        repo_info = HfApi().repo_info(repo_id=repo_id, repo_type="model", files_metadata=True)
        total = 0
        for sibling in repo_info.siblings:
            name = getattr(sibling, "rfilename", "") or getattr(sibling, "path", "") or ""
            if allow_patterns and not _matches_hf_patterns(name, allow_patterns):
                continue
            size = getattr(sibling, "size", None)
            if size:
                total += int(size)
        return total
    except Exception:
        return 0


def _video_model_repos(meta):
    repos = (meta or {}).get("hf_repos")
    if isinstance(repos, (list, tuple)):
        return [str(repo).strip() for repo in repos if str(repo).strip()]
    repo_id = str((meta or {}).get("id") or "").strip()
    return [repo_id] if repo_id else []


def _folder_size(path, allow_patterns=None):
    total = 0
    if not path or not os.path.exists(path):
        return 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, path).replace(os.sep, "/")
                if allow_patterns and not _matches_hf_patterns(rel_path, allow_patterns):
                    continue
                total += os.path.getsize(file_path)
            except OSError:
                pass
    return total


def _video_model_downloaded(meta, cache_dir):
    if (meta or {}).get("backend") == "lightx2v":
        try:
            from core.models.lightx2v_backend import is_lightx2v_model_downloaded
            return is_lightx2v_model_downloaded(meta, cache_dir)
        except Exception:
            return False
    repos = _video_model_repos(meta)
    required_any = any(_video_repo_required_files(meta, repo_id) for repo_id in repos)
    if required_any:
        try:
            from huggingface_hub import try_to_load_from_cache
        except Exception:
            try_to_load_from_cache = None
        for repo_id in repos:
            local_dir = os.path.join(cache_dir, repo_id.replace("/", "--"))
            for required_file in _video_repo_required_files(meta, repo_id):
                local_path = os.path.join(local_dir, required_file)
                if os.path.exists(local_path):
                    continue
                cached = try_to_load_from_cache(repo_id, required_file, cache_dir=cache_dir) if try_to_load_from_cache else None
                if isinstance(cached, str) and os.path.exists(cached):
                    continue
                return False
        return True
    return bool(repos) and all(_video_repo_downloaded(repo_id, cache_dir) for repo_id in repos)


def _video_model_downloaded_size(meta, cache_dir):
    total = 0
    for repo_id in _video_model_repos(meta):
        total += _folder_size(
            os.path.join(cache_dir, repo_id.replace("/", "--")),
            _video_repo_allow_patterns(meta, repo_id),
        )
    return total


def _safe_rmtree_under(path, parent):
    if not path or not parent:
        return False
    target = os.path.abspath(path)
    root = os.path.abspath(parent)
    try:
        if os.path.commonpath([target, root]) != root:
            print(f"[VIDEO_MODELS] Refus suppression hors cache: {target}")
            return False
    except ValueError:
        return False
    if not os.path.exists(target):
        return False
    shutil.rmtree(target)
    return True


def _delete_video_repo_artifacts(repo_id, cache_dir):
    deleted = False
    local_dir = os.path.join(cache_dir, str(repo_id).replace("/", "--"))
    if _safe_rmtree_under(local_dir, cache_dir):
        print(f"[VIDEO_MODELS] Cache local supprimé: {local_dir}")
        deleted = True

    try:
        from core.models import delete_model_from_cache
        deleted = bool(delete_model_from_cache(repo_id)) or deleted
    except Exception as exc:
        print(f"[VIDEO_MODELS] Suppression cache HF ignorée pour {repo_id}: {exc}")

    return deleted


def _video_model_total_size(meta):
    return sum(_video_repo_size(repo_id, _video_repo_allow_patterns(meta, repo_id)) for repo_id in _video_model_repos(meta))


def _format_gb(size_bytes):
    return f"{size_bytes / (1024 ** 3):.1f} GB"


def _download_space_error(repo_id, cache_dir, total_size, allow_patterns=None):
    """Return a user-facing error when a video download cannot fit on disk."""
    if not total_size:
        return None
    local_dir = os.path.join(cache_dir, repo_id.replace("/", "--"))
    parent = os.path.dirname(local_dir) or cache_dir
    os.makedirs(parent, exist_ok=True)
    downloaded = _folder_size(local_dir, allow_patterns)
    remaining = max(total_size - downloaded, 0)
    # HF may keep temporary blobs while reconstructing files; keep a small buffer.
    required = int(remaining + min(max(total_size * 0.10, 2 * 1024 ** 3), 20 * 1024 ** 3))
    free = shutil.disk_usage(parent).free
    if free >= required:
        return None
    return (
        "Espace disque insuffisant pour télécharger ce modèle vidéo. "
        f"Libre: {_format_gb(free)} · requis environ: {_format_gb(required)} · "
        f"modèle: {_format_gb(total_size)}. Libère de l'espace ou définis JOYBOY_MODELS_DIR "
        "vers un volume plus grand."
    )


def _download_model_space_error(meta, cache_dir, total_size):
    repos = _video_model_repos(meta)
    if len(repos) <= 1:
        return _download_space_error(
            repos[0],
            cache_dir,
            total_size,
            _video_repo_allow_patterns(meta, repos[0]),
        ) if repos else None
    if not total_size:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    downloaded = _video_model_downloaded_size(meta, cache_dir)
    remaining = max(total_size - downloaded, 0)
    required = int(remaining + min(max(total_size * 0.10, 2 * 1024 ** 3), 20 * 1024 ** 3))
    free = shutil.disk_usage(cache_dir).free
    if free >= required:
        return None
    return (
        "Espace disque insuffisant pour télécharger ce pack vidéo. "
        f"Libre: {_format_gb(free)} · requis environ: {_format_gb(required)} · "
        f"pack: {_format_gb(total_size)}. Définis JOYBOY_MODELS_DIR vers un volume plus grand."
    )


def _video_model_status_payload(include_advanced=False, allow_experimental=False):
    from core.models import VIDEO_MODELS, VRAM_GB, custom_cache
    from core.models.video_policy import build_video_model_catalog

    catalog = build_video_model_catalog(
        VIDEO_MODELS,
        vram_gb=VRAM_GB,
        include_advanced=include_advanced,
        allow_experimental=allow_experimental,
    )
    models = []
    for model in catalog.get("models", []):
        model_id = model.get("id")
        meta = VIDEO_MODELS.get(model_id, {})
        repo_id = model.get("repo_id") or model.get("hf_repo") or meta.get("id")
        status = video_download_status.get(model_id, {})
        downloading = bool(status.get("downloading"))
        downloaded = _video_model_downloaded(meta, custom_cache) if repo_id and not downloading else False
        backend_ready = True
        backend_status = meta.get("backend_status", "ready")
        launch_status = model.get("launch_status", "ready")
        if meta.get("backend") == "lightx2v":
            try:
                from core.models.lightx2v_backend import get_lightx2v_backend_status
                lightx2v_status = get_lightx2v_backend_status()
                backend_ready = bool(lightx2v_status.get("ready"))
                if not backend_ready:
                    backend_status = "adapter_required"
                    launch_status = "missing_backend"
            except Exception:
                backend_ready = False
                backend_status = "adapter_required"
                launch_status = "missing_backend"
        item = {
            **model,
            "key": model_id,
            "repo": repo_id,
            "repos": _video_model_repos(meta),
            "native_backend": bool(meta.get("native_backend")),
            "external_backend": meta.get("backend") or "",
            "backend_ready": backend_ready,
            "backend_status": backend_status,
            "launch_status": launch_status,
            "downloaded": downloaded,
            "downloading": downloading,
            "progress": status.get("progress", 0),
            "downloaded_bytes": status.get("downloaded_size", 0),
            "total_bytes": status.get("total_size", 0),
            "stage": status.get("stage"),
            "download_repo": status.get("repo"),
            "download_message": status.get("message"),
            "error": status.get("error"),
        }
        models.append(item)
    return {**catalog, "success": True, "models": models}


@video_bp.route('/api/video-models/status', methods=['GET'])
def get_video_models_status():
    include_advanced = str(request.args.get("advanced", "1")).lower() in {"1", "true", "yes", "on"}
    allow_experimental = str(request.args.get("allow_experimental", "1")).lower() in {"1", "true", "yes", "on"}
    return jsonify(_video_model_status_payload(include_advanced=include_advanced, allow_experimental=allow_experimental))


@video_bp.route('/api/video-models/download', methods=['POST'])
def download_video_model():
    data = request.json or {}
    model_id = str(data.get("model_id") or data.get("model") or "").strip()
    if not model_id:
        return jsonify({"success": False, "error": "model_id requis"}), 400

    from core.models import VIDEO_MODELS, custom_cache

    if model_id not in VIDEO_MODELS:
        return jsonify({"success": False, "error": "Modèle vidéo inconnu"}), 400

    meta = VIDEO_MODELS[model_id]
    repos = _video_model_repos(meta)
    repo_id = repos[0] if repos else ""
    if not repos:
        return jsonify({"success": False, "error": "Repo Hugging Face manquant"}), 400

    if _video_model_downloaded(meta, custom_cache):
        return jsonify({"success": True, "message": "already_cached"})
    if video_download_status.get(model_id, {}).get("downloading"):
        return jsonify({"success": True, "message": "downloading"})

    total_size = _video_model_total_size(meta)
    space_error = _download_model_space_error(meta, custom_cache, total_size)
    if space_error:
        video_download_status[model_id] = {
            "downloading": False,
            "progress": 0,
            "downloaded_size": _video_model_downloaded_size(meta, custom_cache),
            "total_size": total_size,
            "error": space_error,
            "stage": "error",
            "message": "Espace disque insuffisant",
        }
        return jsonify({"success": False, "error": space_error}), 400

    def download_thread():
        import time
        from huggingface_hub import snapshot_download

        video_download_status[model_id] = {
            "downloading": True,
            "progress": 0,
            "downloaded_size": 0,
            "total_size": total_size,
            "stage": "backend" if meta.get("backend") == "lightx2v" else "models",
            "message": "Installation du backend LightX2V" if meta.get("backend") == "lightx2v" else "Préparation du téléchargement",
            "started_at": time.time(),
        }
        stop_monitoring = threading.Event()

        def monitor():
            while not stop_monitoring.is_set():
                current = video_download_status.get(model_id, {})
                stage = current.get("stage")
                elapsed = max(0, time.time() - float(current.get("started_at") or time.time()))
                downloaded = _video_model_downloaded_size(meta, custom_cache)
                progress = min(99, int(downloaded * 100 / total_size)) if total_size else 0
                if stage == "backend":
                    progress = max(int(current.get("progress") or 0), min(12, 1 + int(elapsed // 3)))
                elif stage == "models" and meta.get("backend") == "lightx2v":
                    progress = max(12, progress)
                video_download_status[model_id].update({
                    "progress": progress,
                    "downloaded_size": downloaded,
                })
                time.sleep(2)

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            if meta.get("backend") == "lightx2v":
                video_download_status[model_id].update({
                    "stage": "backend",
                    "progress": 1,
                    "message": "Installation du backend LightX2V",
                })
                from core.models.lightx2v_backend import install_lightx2v_backend
                install_lightx2v_backend()

            for current_repo in repos:
                local_dir = os.path.join(custom_cache, current_repo.replace("/", "--"))
                allow_patterns = _video_repo_allow_patterns(meta, current_repo)
                video_download_status[model_id].update({
                    "stage": "models",
                    "repo": current_repo,
                    "message": f"Téléchargement {current_repo}",
                })
                kwargs = {
                    "repo_id": current_repo,
                    "cache_dir": custom_cache,
                    "local_dir": local_dir,
                }
                if allow_patterns:
                    kwargs["allow_patterns"] = allow_patterns
                snapshot_download(**kwargs)
            stop_monitoring.set()
            video_download_status[model_id] = {
                "downloading": False,
                "progress": 100,
                "downloaded_size": _video_model_downloaded_size(meta, custom_cache),
                "total_size": total_size,
                "stage": "complete",
                "message": "Modèle prêt",
            }
        except Exception as exc:
            stop_monitoring.set()
            video_download_status[model_id] = {
                "downloading": False,
                "progress": 0,
                "downloaded_size": _video_model_downloaded_size(meta, custom_cache),
                "total_size": total_size,
                "error": str(exc),
                "stage": "error",
                "message": "Téléchargement interrompu",
            }
            print(f"[VIDEO_MODELS] Download failed for {model_id}: {exc}")

    threading.Thread(target=download_thread, daemon=True).start()
    return jsonify({"success": True, "message": "downloading"})


@video_bp.route('/api/video-models/delete', methods=['POST'])
def delete_video_model():
    data = request.json or {}
    model_id = str(data.get("model_id") or data.get("model") or "").strip()
    if not model_id:
        return jsonify({"success": False, "error": "model_id requis"}), 400

    from core.models import VIDEO_MODELS, custom_cache

    if model_id not in VIDEO_MODELS:
        return jsonify({"success": False, "error": "Modèle vidéo inconnu"}), 400

    if video_download_status.get(model_id, {}).get("downloading"):
        return jsonify({"success": False, "error": "Téléchargement en cours, impossible de supprimer maintenant"}), 409

    meta = VIDEO_MODELS[model_id]
    repos = _video_model_repos(meta)
    if not repos:
        return jsonify({"success": False, "error": "Repo Hugging Face manquant"}), 400

    try:
        from core.model_manager import ModelManager
        mgr = ModelManager.get()
        if getattr(mgr, "_current_video_model", None) == model_id:
            mgr._unload_video()
            mgr._clear_memory(aggressive=True)
    except Exception as exc:
        print(f"[VIDEO_MODELS] Unload avant suppression ignoré: {exc}")

    deleted_repos = []
    for repo_id in repos:
        if _delete_video_repo_artifacts(repo_id, custom_cache):
            deleted_repos.append(repo_id)

    video_download_status.pop(model_id, None)

    if deleted_repos:
        return jsonify({
            "success": True,
            "message": "Modèle vidéo supprimé",
            "deleted_repos": deleted_repos,
        })
    return jsonify({"success": False, "error": "Modèle non trouvé dans le cache"})


@video_bp.route('/reset-video', methods=['POST'])
def reset_video_endpoint():
    """Reset la video en cours pour recommencer une nouvelle"""
    try:
        from core.processing import reset_video
        reset_video()
        return jsonify({'success': True, 'message': 'Video reset - pret pour nouvelle video'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@video_bp.route('/delete-chat-files', methods=['POST'])
def delete_chat_files():
    """Supprime les fichiers associes a une conversation (videos, etc.)"""
    try:
        data = request.json
        chat_id = data.get('chatId')

        if not chat_id:
            return jsonify({'error': 'chatId requis'}), 400

        from core.processing import delete_video_for_chat
        deleted = delete_video_for_chat(chat_id)

        return jsonify({
            'success': True,
            'deleted': deleted,
            'message': f'Fichiers supprimes pour chat {chat_id}' if deleted else 'Aucun fichier a supprimer'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@video_bp.route('/video-info', methods=['GET'])
def video_info_endpoint():
    """Retourne les infos sur la video en cours"""
    try:
        from core.processing import get_video_info
        info = get_video_info()
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@video_bp.route('/videos/<chat_id>')
def serve_video(chat_id):
    """Sert une video sauvegardee pour un chat"""
    import os
    import glob
    from flask import send_from_directory, make_response

    videos_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'output', 'videos')

    def _serve_video_file(filename):
        response = make_response(send_from_directory(videos_dir, filename, conditional=True))
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Chercher le fichier video (avec ou sans timestamp dans le nom)
    for ext in ['mp4', 'webm', 'gif']:
        # D'abord: format avec timestamp (video_{timestamp}_{chat_id}.ext)
        pattern = os.path.join(videos_dir, f"video_*_{chat_id}.{ext}")
        matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if matches:
            return _serve_video_file(os.path.basename(matches[0]))
        # Fallback: ancien format sans timestamp (video_{chat_id}.ext)
        filename = f"video_{chat_id}.{ext}"
        filepath = os.path.join(videos_dir, filename)
        if os.path.exists(filepath):
            return _serve_video_file(filename)

    # Fallback: derniere video generee (pour T2V sans chat_id)
    all_videos = []
    for ext in ['mp4', 'webm', 'gif']:
        all_videos.extend(glob.glob(os.path.join(videos_dir, f"*.{ext}")))
    if all_videos:
        latest = max(all_videos, key=os.path.getmtime)
        return _serve_video_file(os.path.basename(latest))

    return jsonify({'error': 'Video not found'}), 404


@video_bp.route('/videos/session/<session_id>')
def serve_video_session(session_id):
    """Sert une video exacte depuis une session de continuation."""
    from flask import send_file, make_response
    from pathlib import Path
    from core.generation.video_sessions import load_video_session

    session = load_video_session(session_id)
    if not session:
        return jsonify({'error': 'Video session not found'}), 404

    video_path = Path(session.get('video_path') or '')
    if not video_path.exists() or video_path.suffix.lower() not in {'.mp4', '.webm', '.gif'}:
        return jsonify({'error': 'Video file not found'}), 404

    mimetype = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.gif': 'image/gif',
    }.get(video_path.suffix.lower(), 'application/octet-stream')
    try:
        response = make_response(send_file(video_path, mimetype=mimetype, conditional=True))
    except FileNotFoundError:
        return jsonify({'error': 'Video file not found'}), 404
    response.headers['Accept-Ranges'] = 'bytes'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
