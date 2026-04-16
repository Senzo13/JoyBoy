"""
Blueprint pour les routes video (generate-video, video-progress, video-models, reset-video, etc.).
"""
from flask import Blueprint, request, jsonify
import uuid

video_bp = Blueprint('video', __name__)


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
        continue_from_last = data.get('continue', False)
        add_audio = data.get('add_audio', False) is True
        face_restore = data.get('face_restore', 'off')  # 'off', 'gfpgan', 'codeformer'
        # Migration: ancien booleen -> string
        if face_restore is True:
            face_restore = 'codeformer'
        elif face_restore is False:
            face_restore = 'off'
        chat_model = data.get('chat_model', 'qwen3.5:2b')
        chat_id = data.get('chatId')
        quality = data.get('quality', '720p')
        refine_passes = int(data.get('refine_passes', 0))
        allow_experimental_video = bool(data.get('allow_experimental_video', False))

        # Politique runtime: evite les backends connus comme instables en low VRAM.
        from core.models import VIDEO_MODELS as _VM, VRAM_GB
        from core.models.video_policy import get_runtime_video_defaults, is_low_vram, resolve_video_model_for_runtime

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

        # T2V mode: allow no image for models that support it
        t2v_models = ("wan22-5b", "fastwan", "wan-native-5b", "wan22-t2v-14b")
        if not image_b64 and not continue_from_last:
            if video_model not in t2v_models:
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
        print(f"  Audio:    {add_audio}")
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
                "requested_model": model_policy.requested_model,
                "effective_model": video_model,
                "quality": quality,
                "target_frames": target_frames,
                "steps": num_steps,
                "fps": fps,
                "add_audio": add_audio,
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

        with generation_pipeline('video', generation_id, model_name=video_model) as mgr:
            if is_cancelled():
                job_manager.cancel(generation_id)
                return cancelled_response()

            img = base64_to_pil(image_b64) if image_b64 else None
            pipe = mgr.get_pipeline('video')
            upscale_pipe = mgr.get_pipeline('video_upscale')
            job_manager.update(generation_id, phase="generating", progress=12, message="Génération vidéo en cours")
            video_base64, last_frame, video_format = generate_video(
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
                release_pipe_before_export=mgr._unload_video if video_model in ("framepack", "framepack-fast") else None,
            )

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
                    requestedModel=model_policy.requested_model,
                    effectiveModel=video_model,
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

    # Chercher le fichier video (avec ou sans timestamp dans le nom)
    for ext in ['mp4', 'webm', 'gif']:
        # D'abord: format avec timestamp (video_{timestamp}_{chat_id}.ext)
        pattern = os.path.join(videos_dir, f"video_*_{chat_id}.{ext}")
        matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if matches:
            response = make_response(send_from_directory(videos_dir, os.path.basename(matches[0])))
            # Anti-cache headers
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        # Fallback: ancien format sans timestamp (video_{chat_id}.ext)
        filename = f"video_{chat_id}.{ext}"
        filepath = os.path.join(videos_dir, filename)
        if os.path.exists(filepath):
            response = make_response(send_from_directory(videos_dir, filename))
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response

    # Fallback: derniere video generee (pour T2V sans chat_id)
    all_videos = []
    for ext in ['mp4', 'webm', 'gif']:
        all_videos.extend(glob.glob(os.path.join(videos_dir, f"*.{ext}")))
    if all_videos:
        latest = max(all_videos, key=os.path.getmtime)
        response = make_response(send_from_directory(videos_dir, os.path.basename(latest)))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    return jsonify({'error': 'Video not found'}), 404
