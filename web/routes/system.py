"""
Blueprint pour les routes systeme (VRAM/RAM monitoring, hard-reset, restart,
benchmark, hardware info, tunnel Cloudflare).
"""
from flask import Blueprint, request, jsonify, render_template_string, send_file
import os
import shutil
from pathlib import Path

system_bp = Blueprint('system', __name__)


def _existing_path_for_usage(path: Path) -> Path:
    """Return the nearest existing parent so disk_usage works for new caches."""
    current = path.expanduser()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _get_disk_status():
    """Return real disk usage for the storage volume used by model downloads."""
    try:
        from core.infra.paths import get_huggingface_cache_dir, get_models_dir

        target_path = get_huggingface_cache_dir()
        fallback_path = get_models_dir()
    except Exception:
        target_path = Path(os.getcwd())
        fallback_path = target_path

    usage_path = _existing_path_for_usage(target_path)
    if not usage_path.exists():
        usage_path = _existing_path_for_usage(fallback_path)

    usage = shutil.disk_usage(usage_path)
    total_gb = usage.total / (1024 ** 3)
    used_gb = usage.used / (1024 ** 3)
    free_gb = usage.free / (1024 ** 3)
    percent = round((used_gb / total_gb * 100) if total_gb > 0 else 0, 1)

    return {
        'path': str(target_path),
        'volume_path': str(usage_path),
        'total_gb': round(total_gb, 1),
        'used_gb': round(used_gb, 1),
        'free_gb': round(free_gb, 1),
        'percent': percent,
        'free_percent': round(100 - percent, 1),
    }


@system_bp.route('/docs/<path:doc_name>')
def serve_local_doc(doc_name):
    """Serve a small allowlist of local docs linked from the UI."""
    allowed_docs = {
        'THIRD_PARTY_PACKS.md',
        'GETTING_STARTED.md',
        'LOCAL_PACKS.md',
    }
    normalized = os.path.basename(os.path.normpath(doc_name or ''))
    if normalized not in allowed_docs:
        return jsonify({'error': 'Document non disponible'}), 404

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    doc_path = os.path.join(repo_root, 'docs', normalized)
    if not os.path.isfile(doc_path):
        return jsonify({'error': 'Document introuvable'}), 404
    return send_file(doc_path, mimetype='text/markdown; charset=utf-8')


# --- Helper: lazy imports from web.app to avoid circular imports ---

def _get_active_generations():
    from web.app import active_generations
    return active_generations

def _get_generations_lock():
    from web.app import generations_lock
    return generations_lock


# ========== GPU PROFILE ==========

@system_bp.route('/api/gpu-profile')
def get_gpu_profile():
    """Return the active GPU profile (based on detected VRAM)."""
    from core.models.gpu_profile import get_active_profile
    profile = get_active_profile()
    return jsonify(profile)


@system_bp.route('/api/version/status')
def get_version_status():
    """Return local version plus lightweight GitHub release/update signals."""
    from core.infra.versioning import get_app_version_status

    force_refresh = str(request.args.get('refresh', '')).lower() in {'1', 'true', 'yes'}
    return jsonify(get_app_version_status(force_refresh=force_refresh))


@system_bp.route('/api/version/update', methods=['POST'])
def update_version_from_git():
    """Pull the current git branch and restart JoyBoy when the pull succeeds."""
    from core.infra.app_control import pull_git_updates

    payload = request.get_json(silent=True) or {}
    restart = payload.get('restart', True) is not False
    result = pull_git_updates(restart=restart)
    if result.get('success'):
        return jsonify(result)

    status_code = 409 if result.get('code') == 'local_changes' else 400
    return jsonify(result), status_code


@system_bp.route('/api/runtime-console')
def get_runtime_console():
    """Return recent stdout/stderr lines captured from the running JoyBoy app."""
    from core.infra.runtime_console import get_runtime_console_entries

    return jsonify(get_runtime_console_entries(
        after=request.args.get('after', 0),
        limit=request.args.get('limit', 300),
    ))


# ========== VRAM / RAM MONITORING ==========

@system_bp.route('/api/vram/status')
def get_vram_status():
    """Retourne l'état VRAM en temps réel pour le monitoring"""
    from config import UTILITY_MODEL
    from core.model_manager import ModelManager
    from core import ollama_service

    mgr = ModelManager.get()
    _status = mgr.get_status()
    resources = {}
    try:
        from core.runtime import get_resource_scheduler

        resources = get_resource_scheduler().state(_status)
    except Exception as exc:
        resources = {"error": str(exc)}

    try:
        resources['disk'] = _get_disk_status()
    except Exception as exc:
        resources['disk_error'] = str(exc)

    # Create a simple namespace for compatibility
    class _S:
        total_gb = _status['total_gb']
        used_gb = _status['used_gb']
        free_gb = _status['free_gb']
        models_loaded = _status['models_loaded']
        cuda_details = _status.get('cuda_details', {})
    status = _S()
    percent = round((status.used_gb / status.total_gb * 100) if status.total_gb > 0 else 0, 1)

    # Récupérer les infos détaillées des modèles Ollama
    ollama_detailed = ollama_service.get_loaded_models_detailed()

    # Générer des conseils d'optimisation
    tips = []
    warnings = []

    # Liste des modèles avec infos détaillées
    models_detailed = []

    # Ajouter les modèles Ollama avec leurs détails
    for m in ollama_detailed:
        model_name = m['name']
        # Catégoriser
        if UTILITY_MODEL and model_name == UTILITY_MODEL:
            cat = 'utility'
            icon = 'zap'  # Lucide icon
        else:
            cat = 'chat'
            icon = 'message-square'  # Lucide icon

        # Format: "qwen2.5:7b" → "qwen2.5 7b", "model:latest" → "model"
        parts = model_name.split(':')
        tag = parts[1] if len(parts) > 1 else 'latest'
        display_name = f"{parts[0]} {tag}" if tag != 'latest' else parts[0]

        models_detailed.append({
            'name': display_name,
            'full_name': model_name,
            'category': cat,
            'icon': icon,
            'vram_gb': m['vram_gb'],
            'size_gb': m['size_gb'],
            'params': m.get('parameter_size', ''),
            'quant': m.get('quantization', '')
        })

    # Ajouter les modèles image depuis status.models_loaded
    for model in status.models_loaded:
        if model.startswith('inpaint:'):
            name = model.replace('inpaint:', '')
            # Détecter si offload
            has_offload = '(offload)' in name
            name = name.replace(' (offload)', '')
            models_detailed.append({
                'name': name[:20] + ('...' if len(name) > 20 else ''),
                'full_name': name,
                'category': 'inpaint' + (' (CPU)' if has_offload else ''),
                'icon': 'brush',
                'vram_gb': 2.5 if has_offload else 6.5,  # Estimation
            })
        elif model.startswith('txt2img:'):
            models_detailed.append({
                'name': model.replace('txt2img:', '')[:20],
                'full_name': model.replace('txt2img:', ''),
                'category': 'text2img',
                'icon': 'image',
                'vram_gb': None,
            })
        elif model.startswith('video:'):
            models_detailed.append({
                'name': model.replace('video:', ''),
                'full_name': model.replace('video:', ''),
                'category': 'video',
                'icon': 'film',
                'vram_gb': None,
            })
        elif model.startswith('caption:'):
            models_detailed.append({
                'name': model.replace('caption:', ''),
                'full_name': model.replace('caption:', ''),
                'category': 'caption',
                'icon': 'type',
                'vram_gb': None,
            })
        elif model.startswith('gguf:'):
            name = model.replace('gguf:', '')
            models_detailed.append({
                'name': name[:20],
                'full_name': name,
                'category': 'gguf',
                'icon': 'package',
                'vram_gb': 2.0,  # GGUF est compact
            })
        elif model.startswith('controlnet:'):
            models_detailed.append({
                'name': model.replace('controlnet:', ''),
                'full_name': model.replace('controlnet:', ''),
                'category': 'controlnet',
                'icon': 'sliders',
                'vram_gb': 0.4,
            })
        elif model.startswith('depth:'):
            models_detailed.append({
                'name': model.replace('depth:', ''),
                'full_name': model.replace('depth:', ''),
                'category': 'depth',
                'icon': 'layers',
                'vram_gb': 0.3,
            })
        elif model.startswith('ip-adapter:'):
            models_detailed.append({
                'name': model.replace('ip-adapter:', ''),
                'full_name': model.replace('ip-adapter:', ''),
                'category': 'ip-adapter',
                'icon': 'user',
                'vram_gb': 0.5,
            })
        elif model.startswith('lora:'):
            # Format: lora:name(scale=X)
            lora_info = model.replace('lora:', '')
            models_detailed.append({
                'name': lora_info,
                'full_name': lora_info,
                'category': 'lora',
                'icon': 'sparkles',
                'vram_gb': 0.1,  # LoRAs sont petits
            })
        elif model.startswith('pose:'):
            models_detailed.append({
                'name': model.replace('pose:', ''),
                'full_name': model.replace('pose:', ''),
                'category': 'pose',
                'icon': 'person-standing',
                'vram_gb': 0.3,
            })
        elif model.startswith('vision:'):
            # Format: vision:Florence(cpu) ou vision:Florence(cuda)
            vision_info = model.replace('vision:', '')
            device = 'cpu' if 'cpu' in vision_info.lower() else 'gpu'
            models_detailed.append({
                'name': vision_info,
                'full_name': vision_info,
                'category': f'vision ({device})',
                'icon': 'eye',
                'vram_gb': 0.5 if device == 'gpu' else 0,
            })
        elif model.startswith('upscale:'):
            models_detailed.append({
                'name': model.replace('upscale:', ''),
                'full_name': model.replace('upscale:', ''),
                'category': 'upscale',
                'icon': 'maximize-2',
                'vram_gb': 0.5,
            })
        elif model.startswith('segmentation:'):
            seg_name = model.replace('segmentation:', '')
            vram_estimates = {'SAM': 0.4, 'GroundingDINO': 0.7, 'SegFormer-FASHN': 0.2, 'SCHP': 0.3, 'rembg': 0.3}
            models_detailed.append({
                'name': seg_name,
                'full_name': seg_name,
                'category': 'segmentation',
                'icon': 'scan' if seg_name == 'SAM' else ('target' if 'DINO' in seg_name else 'scissors'),
                'vram_gb': vram_estimates.get(seg_name, 0.3),
            })

    # Compter
    ollama_count = len(ollama_detailed)
    image_count = len([m for m in models_detailed if m['category'] in ('inpaint', 'text2img', 'video')])

    # Warning si VRAM critique
    if percent > 90:
        warnings.append("VRAM critique !")
    elif percent > 75:
        warnings.append("VRAM élevée")

    # Conseil si plusieurs modèles
    if ollama_count > 2:
        tips.append(f"{ollama_count} modèles Ollama")
    if image_count > 0 and ollama_count > 0:
        tips.append("Image + Chat chargés")
    if not models_detailed:
        tips.append("VRAM libre")

    # Ajouter CUDA context comme modèle si de la VRAM est utilisée mais pas trackée
    tracked_vram = sum(m.get('vram_gb', 0) or 0 for m in models_detailed)
    cuda_details = status.cuda_details
    if cuda_details:
        # VRAM allouée par PyTorch mais pas trackée par nos modèles
        pytorch_allocated = cuda_details.get('allocated_gb', 0)
        untracked = max(0, pytorch_allocated - tracked_vram)
        if untracked > 0.1:  # Si plus de 100MB non tracké
            models_detailed.append({
                'name': f'PyTorch cache',
                'full_name': f'Mémoire CUDA non trackée ({untracked:.1f}GB)',
                'category': 'cache',
                'icon': 'database',
                'vram_gb': round(untracked, 1),
            })

        # Mémoire réservée mais pas allouée (cache CUDA)
        cuda_cache = cuda_details.get('cached_gb', 0)
        if cuda_cache > 0.1:
            models_detailed.append({
                'name': f'CUDA cache',
                'full_name': f'Cache CUDA réservé ({cuda_cache:.1f}GB) - libérable',
                'category': 'cache',
                'icon': 'hard-drive',
                'vram_gb': round(cuda_cache, 1),
            })

    return jsonify({
        'vram': {
            'total': status.total_gb,
            'used': status.used_gb,
            'free': status.free_gb,
            'percent': percent,
            'cuda_allocated': cuda_details.get('allocated_gb', 0) if cuda_details else 0,
            'cuda_reserved': cuda_details.get('reserved_gb', 0) if cuda_details else 0,
        },
        'models': models_detailed,
        'warnings': warnings,
        'tips': tips,
        'resources': resources,
    })


@system_bp.route('/api/disk/status')
def get_disk_status():
    """Retourne l'espace disque réel du volume utilisé par les modèles."""
    return jsonify({'disk': _get_disk_status()})


@system_bp.route('/api/ram/status')
def get_ram_status():
    """Retourne l'état RAM en temps réel"""
    import psutil
    import os

    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    used_gb = mem.used / (1024 ** 3)
    free_gb = mem.available / (1024 ** 3)
    percent = mem.percent

    # RAM utilisée par le process Python
    process = psutil.Process(os.getpid())
    python_gb = process.memory_info().rss / (1024 ** 3)

    # Modèles chargés en RAM (CPU)
    models = []
    try:
        from core.segmentation import get_segmentation_status
        seg = get_segmentation_status()
        if seg.get('schp'):
            models.append({'name': 'SCHP', 'size_mb': 80, 'icon': 'scan', 'category': 'segmentation'})
        if seg.get('fusion_b2'):
            models.append({'name': 'SegFormer B2', 'size_mb': 90, 'icon': 'scan', 'category': 'segmentation'})
        if seg.get('fusion_b4'):
            models.append({'name': 'SegFormer B4', 'size_mb': 60, 'icon': 'scan', 'category': 'segmentation'})
        if seg.get('segformer_single'):
            models.append({'name': f'SegFormer ({seg["segformer_variant"]})', 'size_mb': 90, 'icon': 'scan', 'category': 'segmentation'})
        if seg.get('grounding_dino'):
            models.append({'name': 'GroundingDINO', 'size_mb': 170, 'icon': 'search', 'category': 'segmentation'})
    except Exception:
        pass

    try:
        from core.florence import is_loaded as florence_loaded
        if florence_loaded():
            models.append({'name': 'Florence-2', 'size_mb': 500, 'icon': 'eye', 'category': 'vision'})
    except Exception:
        pass

    models_ram_mb = sum(m['size_mb'] for m in models)

    return jsonify({
        'ram': {
            'total': round(total_gb, 1),
            'used': round(used_gb, 1),
            'free': round(free_gb, 1),
            'percent': round(percent, 1),
            'python_gb': round(python_gb, 1)
        },
        'models': models,
        'models_ram_mb': models_ram_mb
    })


def _free_windows_memory():
    """Libère la RAM système — délègue à utils.windows."""
    from utils.windows import free_windows_memory
    return free_windows_memory()


@system_bp.route('/api/ram/free', methods=['POST'])
def free_ram():
    """Libère la RAM comme Wise Memory Optimizer / Mem Reduct.
    Séquence: gc Python → CUDA cache → empty ALL working sets → flush file cache →
    flush modified pages → purge standby → combine pages."""
    import psutil
    import gc

    # Mesurer avant
    mem_before = psutil.virtual_memory()
    used_before = mem_before.used
    print(f"[RAM] === Libération mémoire (avant: {used_before / (1024**3):.1f}GB utilisé) ===")

    # 1. Garbage collect Python
    gc.collect()

    # 2. Vider le cache CUDA
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("[RAM] CUDA cache vidé")
    except ImportError:
        pass

    # 3. Séquence complète Windows (comme Wise Memory Optimizer)
    win_results = {}
    import sys
    if sys.platform == 'win32':
        win_results = _free_windows_memory()

    # 4. Re-run gc (rattrape les objets libérés par le trim)
    gc.collect()

    # Mesurer après
    mem_after = psutil.virtual_memory()
    used_after = mem_after.used
    freed_mb = max(0, (used_before - used_after)) / (1024 ** 2)

    print(f"[RAM] === Terminé: {freed_mb:.0f} MB libérés ({used_before / (1024**3):.1f}GB → {used_after / (1024**3):.1f}GB) ===")

    return jsonify({
        'success': True,
        'freed_mb': round(freed_mb),
        'steps': win_results.get('steps', {}),
        'privileges': win_results.get('privileges', {}),
        'pages_combined': win_results.get('pages_combined', 0),
        'ram': {
            'total': round(mem_after.total / (1024 ** 3), 1),
            'used': round(mem_after.used / (1024 ** 3), 1),
            'free': round(mem_after.available / (1024 ** 3), 1),
            'percent': round(mem_after.percent, 1)
        }
    })


# ========== SYSTEM CONTROL ==========

@system_bp.route('/system/hard-reset', methods=['POST'])
def hard_reset():
    """HARD RESET - Arrête TOUT et libère toute la VRAM via ModelManager."""
    from core.model_manager import ModelManager

    print("\n" + "="*60)
    print("[HARD RESET] ====== ARRÊT COMPLET DU SYSTÈME ======")
    print("="*60)

    results = {
        'generations_cancelled': 0,
        'vram_cleared': False
    }

    try:
        # 1. Annuler TOUTES les générations en cours
        active_generations = _get_active_generations()
        generations_lock = _get_generations_lock()
        with generations_lock:
            for gen_id, gen_info in active_generations.items():
                if not gen_info.get('cancelled'):
                    gen_info['cancelled'] = True
                    results['generations_cancelled'] += 1
                    print(f"[HARD RESET] Génération {gen_id} annulée")
        print(f"[HARD RESET] {results['generations_cancelled']} génération(s) annulée(s)")

        # 2. Décharger TOUT via ModelManager (image + Ollama + segmentation + gc)
        print("[HARD RESET] Déchargement de tous les modèles...")
        ModelManager.get().unload_all()
        results['vram_cleared'] = True

        print("="*60)
        print("[HARD RESET] ====== SYSTÈME RÉINITIALISÉ ======")
        print("="*60 + "\n")

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        print(f"[HARD RESET] Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@system_bp.route('/system/restart', methods=['POST'])
def restart_server():
    """
    Redémarre le serveur Flask avec le launcher adapté à l'OS.
    """
    from core.infra.app_control import schedule_restart

    print("\n" + "="*60)
    print("[RESTART] ====== REDÉMARRAGE DU SERVEUR ======")
    print("="*60)

    schedule_restart()

    return jsonify({'success': True, 'message': 'Server restarting...'})


# ========== HARDWARE BENCHMARK ==========

@system_bp.route('/api/benchmark', methods=['GET'])
def benchmark_hardware():
    """Analyse le hardware et recommande les modèles adaptés"""
    import platform
    import torch
    import psutil

    result = {
        'os': platform.system(),
        'arch': platform.machine(),
        'gpu': None,
        'vram_gb': 0,
        'ram_gb': round(psutil.virtual_memory().total / (1024**3), 1),
        'recommended_text_model': None,
        'recommended_text_model_size': None,
        'image_config': 'cpu_offload',
        'performance_tier': 'low'
    }

    # Détection GPU
    if torch.cuda.is_available():
        result['gpu'] = torch.cuda.get_device_name(0)
        result['vram_gb'] = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)

        # Config basée sur VRAM
        if result['vram_gb'] >= 16:
            result['recommended_text_model'] = 'qwen3.5:4b'
            result['recommended_text_model_size'] = '3.4GB'
            result['image_config'] = 'cuda_full'
            result['performance_tier'] = 'high'
        elif result['vram_gb'] >= 10:
            result['recommended_text_model'] = 'qwen3.5:2b'
            result['recommended_text_model_size'] = '2.7GB'
            result['image_config'] = 'cuda_direct'
            result['performance_tier'] = 'high'
        elif result['vram_gb'] >= 6:
            result['recommended_text_model'] = 'qwen3.5:2b'
            result['recommended_text_model_size'] = '2.7GB'
            result['image_config'] = 'cpu_offload'
            result['performance_tier'] = 'medium'
        else:
            result['recommended_text_model'] = 'qwen3.5:0.8b'
            result['recommended_text_model_size'] = '1GB'
            result['image_config'] = 'cpu_offload'
            result['performance_tier'] = 'low'

    elif platform.system() == 'Darwin':
        # Apple Silicon
        result['gpu'] = 'Apple Silicon'
        # Unified memory = RAM
        if result['ram_gb'] >= 32:
            result['recommended_text_model'] = 'qwen3.5:4b'
            result['recommended_text_model_size'] = '3.4GB'
            result['image_config'] = 'mps_optimized'
            result['performance_tier'] = 'high'
        elif result['ram_gb'] >= 16:
            result['recommended_text_model'] = 'qwen3.5:2b'
            result['recommended_text_model_size'] = '2.7GB'
            result['image_config'] = 'mps'
            result['performance_tier'] = 'medium'
        else:
            result['recommended_text_model'] = 'qwen3.5:0.8b'
            result['recommended_text_model_size'] = '1GB'
            result['image_config'] = 'mps'
            result['performance_tier'] = 'low'
    else:
        # CPU only
        result['gpu'] = 'CPU'
        result['recommended_text_model'] = 'qwen3.5:0.8b'
        result['recommended_text_model_size'] = '1GB'
        result['image_config'] = 'cpu'
        result['performance_tier'] = 'low'

    return jsonify(result)


# ========== HARDWARE INFO ==========

@system_bp.route('/api/hardware/info')
def hardware_info():
    """Retourne les infos hardware et les modèles recommandés par profil"""
    import torch
    import psutil

    # Importer les configs
    try:
        from config import UTILITY_MODEL, MODEL_RECOMMENDATIONS, VRAM_THRESHOLDS, GENERATION_SETTINGS, IMAGE_MODEL_RECOMMENDATIONS
    except ImportError:
        UTILITY_MODEL = "qwen3.5:2b"
        MODEL_RECOMMENDATIONS = {
            "casual": {"low": "qwen3.5:0.8b", "medium": "qwen3.5:2b", "high": "qwen3.5:4b"}
        }
        VRAM_THRESHOLDS = {"extreme": 24, "ultra": 16, "very_high": 12, "high": 8, "medium": 4, "low": 0}
        GENERATION_SETTINGS = {
            "low": {"steps": 25, "text2imgSteps": 25, "strength": 0.70},
            "medium": {"steps": 35, "text2imgSteps": 30, "strength": 0.75},
            "high": {"steps": 35, "text2imgSteps": 35, "strength": 0.75},
        }
        IMAGE_MODEL_RECOMMENDATIONS = {
            "low": {"inpainting": "Fluently XL v3 Inpaint", "generation": "SDXL Turbo"},
            "medium": {"inpainting": "epiCRealism XL (Moyen)", "generation": "epiCRealism XL"},
            "high": {"inpainting": "epiCRealism XL (Moyen)", "generation": "epiCRealism XL"},
        }

    # Détecter VRAM
    vram_gb = 0
    vram_level = "low"
    gpu_name = None
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)

    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1)

        # Déterminer le niveau VRAM (du plus haut au plus bas)
        for level in ["high_end", "extreme", "ultra", "very_high", "high", "medium", "low"]:
            if level in VRAM_THRESHOLDS and vram_gb >= VRAM_THRESHOLDS[level]:
                vram_level = level
                break

    # Construire les recommandations par profil
    recommendations = {}
    for profile, models in MODEL_RECOMMENDATIONS.items():
        recommendations[profile] = models.get(vram_level, models.get("medium", "qwen3.5:2b"))

    # Paramètres de génération recommandés
    gen_settings = GENERATION_SETTINGS.get(vram_level, GENERATION_SETTINGS.get("medium", {}))

    # Modèles image recommandés
    image_models = IMAGE_MODEL_RECOMMENDATIONS.get(vram_level, IMAGE_MODEL_RECOMMENDATIONS.get("medium", {}))

    # Generation time estimates and GPU config
    from core.models import get_generation_time_estimates, DTYPE_NAME, USE_QUANTIZATION
    time_estimates = get_generation_time_estimates()

    return jsonify({
        'gpu': gpu_name,
        'vram_gb': vram_gb,
        'vram_level': vram_level,
        'ram_gb': ram_gb,
        'dtype': DTYPE_NAME,
        'quantization': 'int8' if USE_QUANTIZATION else 'none',
        'time_estimates': time_estimates,
        'utility_model': UTILITY_MODEL,
        'recommendations': recommendations,
        'generation_settings': gen_settings,
        'image_models': image_models
    })


# ========== TUNNEL CLOUDFLARE ==========

@system_bp.route('/api/tunnel/status')
def tunnel_status():
    """Retourne l'état du tunnel Cloudflare"""
    from core import tunnel_service
    status = tunnel_service.get_tunnel_status()
    return jsonify(status)


@system_bp.route('/api/tunnel/start', methods=['POST'])
def tunnel_start():
    """Télécharge cloudflared si nécessaire et démarre le tunnel"""
    from core import tunnel_service
    result = tunnel_service.start_tunnel(port=7860)
    if result.get("success"):
        tunnel_service.save_tunnel_config(True)
    return jsonify(result)


@system_bp.route('/api/tunnel/stop', methods=['POST'])
def tunnel_stop():
    """Arrête le tunnel Cloudflare"""
    from core import tunnel_service
    result = tunnel_service.stop_tunnel()
    tunnel_service.save_tunnel_config(False)
    return jsonify(result)
