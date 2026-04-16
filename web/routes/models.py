"""
Blueprint pour les routes de gestion des modeles (models/*, check-models, ollama/*).
"""
import re
from flask import Blueprint, request, jsonify

models_bp = Blueprint('models', __name__)


# --- Helper: lazy imports from web.app to avoid circular imports ---

def _get_active_generations():
    from web.app import active_generations
    return active_generations

def _get_generations_lock():
    from web.app import generations_lock
    return generations_lock


# ========== MODELS API ==========

@models_bp.route('/models')
def get_models():
    from core.models import MODELS
    return jsonify(list(MODELS.keys()))


@models_bp.route('/models/status')
def models_status():
    """Retourne le statut de tous les modeles (telecharges ou non)"""
    try:
        from core.models import get_all_models_status
        status = get_all_models_status()
        return jsonify({'success': True, 'models': status})
    except Exception as e:
        print(f"Error checking models: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/models/download', methods=['POST'])
def download_model():
    """Lance le telechargement d'un modele en background"""
    try:
        from core.models import download_model_background
        data = request.json
        model_key = data.get('model_key')

        if not model_key:
            return jsonify({'error': 'model_key requis'}), 400

        success, message = download_model_background(model_key)

        return jsonify({
            'success': success,
            'message': message
        })
    except Exception as e:
        print(f"Error downloading model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/models/delete', methods=['POST'])
def delete_hf_model():
    """Supprime un modele HuggingFace du cache"""
    try:
        from core.models import ALL_MODELS, delete_model_from_cache
        data = request.json
        model_key = data.get('model_key')

        if not model_key:
            return jsonify({'error': 'model_key requis'}), 400

        if model_key not in ALL_MODELS:
            return jsonify({'error': 'Modèle inconnu'}), 400

        repo_id = ALL_MODELS[model_key]['repo']
        success = delete_model_from_cache(repo_id)

        if success:
            return jsonify({'success': True, 'message': 'Modèle supprimé'})
        else:
            return jsonify({'success': False, 'error': 'Modèle non trouvé dans le cache'})

    except Exception as e:
        print(f"Error deleting model: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@models_bp.route('/models/preload-image', methods=['POST'])
def preload_image_model():
    """No-op dans la nouvelle architecture. Les modeles sont charges a la demande."""
    return jsonify({'success': True, 'skipped': True, 'reason': 'load_on_demand'})


@models_bp.route('/models/preload-sam', methods=['POST'])
def preload_sam_model():
    """No-op dans la nouvelle architecture. SAM est charge a la demande."""
    return jsonify({'success': True, 'skipped': True, 'reason': 'load_on_demand'})


@models_bp.route('/models/unload-image', methods=['POST'])
def unload_image_model():
    """Decharge tous les modeles image via ModelManager"""
    try:
        from core.model_manager import ModelManager
        mgr = ModelManager.get()
        mgr._unload_diffusers()
        print("[UNLOAD] Modèles image déchargés")
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error unloading image model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/models/unload-lora', methods=['POST'])
def unload_lora_model():
    """Décharge un LoRA spécifique du pipeline actif"""
    try:
        from core.model_manager import ModelManager
        lora_name = request.json.get('name', '') if request.is_json else ''
        if not lora_name:
            return jsonify({'error': 'name requis'}), 400
        # Strip scale info: "nsfw(scale=0.3)" → "nsfw"
        lora_name = re.sub(r'\(.*\)$', '', lora_name).strip()
        mgr = ModelManager.get()
        mgr.unload_lora(lora_name)
        print(f"[UNLOAD] LoRA {lora_name} déchargé")
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error unloading LoRA: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/models/unload-all', methods=['POST'])
def unload_all_models():
    """Decharge les modeles via ModelManager. keep_video=true pour garder le modele video."""
    keep_video = request.json.get('keep_video', False) if request.is_json else False
    print(f"\n[UNLOAD-ALL] ====== Déchargement de sécurité {'(keep video)' if keep_video else ''} ======")

    try:
        from core.model_manager import ModelManager
        # Cancel ALL active generations first (so they stop at next step)
        active_generations = _get_active_generations()
        generations_lock = _get_generations_lock()
        cancelled = 0
        with generations_lock:
            for gen_id, gen_info in active_generations.items():
                if not gen_info.get('cancelled'):
                    gen_info['cancelled'] = True
                    cancelled += 1
        if cancelled:
            print(f"[UNLOAD-ALL] {cancelled} génération(s) annulée(s)")

        mgr = ModelManager.get()
        if keep_video:
            mgr.unload_all_except_video()
        else:
            mgr.unload_all()
        print("[UNLOAD-ALL] ====== Tous les modèles déchargés ======\n")
        return jsonify({'success': True})

    except Exception as e:
        print(f"[UNLOAD-ALL] Erreur: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/check-models')
def check_models():
    """Verifie le statut des modeles d'image (HuggingFace)"""
    try:
        from core.models import get_all_models_status
        models_status = get_all_models_status()
        # Convertir le dict en array pour le frontend
        models_array = []
        for key, model in models_status.items():
            model['key'] = key
            models_array.append(model)
        return jsonify({
            'success': True,
            'models': models_array
        })
    except Exception as e:
        print(f"Error checking models: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== OLLAMA API ==========

@models_bp.route('/ollama/status')
def ollama_status():
    """Verifie le statut d'Ollama"""
    from core import ollama_service
    return jsonify({
        'installed': ollama_service.is_ollama_installed(),
        'running': ollama_service.is_ollama_running()
    })


@models_bp.route('/ollama/start', methods=['POST'])
def ollama_start():
    """Demarre le serveur Ollama"""
    from core import ollama_service
    success = ollama_service.start_ollama()
    return jsonify({'success': success})


@models_bp.route('/ollama/models')
def ollama_models():
    """Liste les modeles Ollama installes"""
    from core import ollama_service
    models = ollama_service.get_installed_models()
    return jsonify({'models': models})


@models_bp.route('/ollama/unload', methods=['POST'])
def ollama_unload():
    """Decharge un modele Ollama de la VRAM"""
    try:
        from core import ollama_service
        data = request.json
        model_name = data.get('model')

        if not model_name:
            return jsonify({'error': 'model requis'}), 400

        success = ollama_service.unload_model(model_name)
        return jsonify({'success': success})
    except Exception as e:
        print(f"Error unloading model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/ollama/preload', methods=['POST'])
def ollama_preload():
    """Precharge un modele Ollama dans la VRAM"""
    try:
        from core.model_manager import ModelManager
        from core import ollama_service
        # Skip si une generation image est en cours
        mgr = ModelManager.get()
        if mgr._generating:
            print("[PRELOAD] Ollama ignoré - génération en cours")
            return jsonify({'success': True, 'skipped': True, 'reason': 'generation_active'})

        data = request.json
        model_name = data.get('model')

        if not model_name:
            return jsonify({'error': 'model requis'}), 400

        success = ollama_service.preload_model(model_name)
        return jsonify({'success': success})
    except Exception as e:
        print(f"Error preloading model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/ollama/search')
def ollama_search():
    """Recherche des modeles disponibles"""
    from core import ollama_service
    query = request.args.get('q', '')
    models = ollama_service.search_models(query)
    return jsonify({'models': models})


@models_bp.route('/ollama/pull', methods=['POST'])
def ollama_pull():
    """Telecharge un modele Ollama"""
    try:
        from core import ollama_service
        data = request.json
        model_name = data.get('model')

        if not model_name:
            return jsonify({'error': 'model requis'}), 400

        print(f"[OLLAMA] Pulling model: {model_name}")
        success, message = ollama_service.pull_model(model_name)

        return jsonify({
            'success': success,
            'message': message
        })
    except Exception as e:
        print(f"Error pulling model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/ollama/delete', methods=['POST'])
def ollama_delete():
    """Supprime un modele Ollama"""
    try:
        from core import ollama_service
        data = request.json
        model_name = data.get('model')

        if not model_name:
            return jsonify({'error': 'model requis'}), 400

        success = ollama_service.delete_model(model_name)
        return jsonify({'success': success})
    except Exception as e:
        print(f"Error deleting model: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/ollama/pull-stream', methods=['POST'])
def ollama_pull_stream():
    """Telecharge un modele Ollama avec streaming de la progression"""
    from flask import Response, stream_with_context
    import json

    data = request.json
    model_name = data.get('model')

    if not model_name:
        return jsonify({'error': 'model requis'}), 400

    def generate():
        try:
            import requests
            response = requests.post(
                "http://127.0.0.1:11434/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=None
            )

            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)

                    progress = 0
                    if total > 0:
                        progress = int((completed / total) * 100)

                    yield f"data: {json.dumps({'status': status, 'progress': progress, 'completed': completed, 'total': total})}\n\n"

                    if data.get("error"):
                        yield f"data: {json.dumps({'error': data['error']})}\n\n"
                        return

            yield f"data: {json.dumps({'done': True, 'progress': 100})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@models_bp.route('/ollama/warmup', methods=['POST'])
def ollama_warmup():
    """Precharge un modele Ollama en memoire pour des reponses plus rapides"""
    try:
        from core.model_manager import ModelManager
        from core import ollama_service
        data = request.json
        model_name = data.get('model')

        if not model_name:
            return jsonify({'success': False, 'error': 'model requis'})

        # Ne pas warmup pendant une generation d'image
        mgr = ModelManager.get()
        if mgr._generating:
            print(f"[WARMUP] Skip {model_name} - génération en cours")
            return jsonify({'success': True, 'skipped': True, 'reason': 'generation_active'})

        # Verifier si Ollama tourne
        if not ollama_service.is_ollama_running():
            ollama_service.start_ollama()

        # Verifier si le modele existe
        models = ollama_service.get_installed_models()
        model_exists = any(m['name'] == model_name or m['name'].startswith(model_name.split(':')[0]) for m in models)

        if not model_exists:
            return jsonify({'success': False, 'error': f'Modèle {model_name} non installé'})

        print(f"[WARMUP] Préchauffage de {model_name}...")
        success = ollama_service.preload_model(model_name)

        if success:
            print(f"[WARMUP] {model_name} prêt!")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Échec du warmup'})

    except Exception as e:
        print(f"[WARMUP] Erreur: {e}")
        return jsonify({'success': False, 'error': str(e)})
