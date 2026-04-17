"""
Blueprint pour les routes settings/config (config API, preload, segmentation,
backend GGUF, gallery, setup wizard, context, prompt helper, output serving).
"""
from flask import Blueprint, request, jsonify
import os
import threading

settings_bp = Blueprint('settings', __name__)


# --- Helper: lazy imports from web.app to avoid circular imports ---

def _get_ollama_service():
    from core import ollama_service
    return ollama_service


# ===== BACKEND GGUF =====

# État global du backend
_current_backend = 'diffusers'
_current_gguf_quant = 'Q6_K'


def get_active_backend():
    """Helper: retourne le backend actif (pour utilisation interne)"""
    return _current_backend, _current_gguf_quant


# Setup state for tracking installation progress
setup_progress = {
    'status': 'idle',  # idle, checking, downloading_text, downloading_image, complete, error
    'progress': 0,
    'message': '',
    'text_model': None,
    'error': None
}


# ========== CONFIG ==========

@settings_bp.route('/api/config')
def get_config():
    """Retourne la config pour le frontend"""
    from config import (AI_NAME, AI_DESCRIPTION, LOGO_PATH, MONOGRAM_PATH,
                        MESSAGES, PRIMARY_COLOR, DEFAULT_STEPS, DEFAULT_STRENGTH, DEFAULT_DILATION)
    return jsonify({
        'name': AI_NAME,
        'description': AI_DESCRIPTION,
        'logo': LOGO_PATH,
        'monogram': MONOGRAM_PATH,
        'messages': MESSAGES,
        'primaryColor': PRIMARY_COLOR,
        'defaults': {
            'steps': DEFAULT_STEPS,
            'strength': DEFAULT_STRENGTH,
            'dilation': DEFAULT_DILATION,
        }
    })


# ========== PROVIDERS / LOCAL CONFIG ==========

@settings_bp.route('/api/providers/status')
def providers_status():
    """Retourne l'état des providers et de la config locale."""
    from core.infra.local_config import (
        get_feature_flags,
        get_local_config_overview,
        get_onboarding_state,
        get_provider_status,
    )
    from core.infra.packs import get_feature_exposure_map, get_pack_index, get_pack_ui_overrides

    overview = get_local_config_overview()
    return jsonify({
        'success': True,
        'providers': get_provider_status(),
        'features': get_feature_flags(),
        'onboarding': get_onboarding_state(),
        'packs': get_pack_index()['packs'],
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
        'uses_legacy_path': overview['uses_legacy_path'],
        'precedence': 'process env > .env > local UI'
    })


@settings_bp.route('/api/providers/secret', methods=['POST'])
def providers_save_secret():
    """Sauvegarde une clé provider en local hors git."""
    from core.infra.local_config import (
        PROVIDER_META,
        get_local_config_overview,
        get_provider_status,
        set_provider_secret,
    )

    data = request.get_json(silent=True) or {}
    key = str(data.get('key', '')).strip()
    value = str(data.get('value', ''))

    if key not in PROVIDER_META:
        return jsonify({'success': False, 'error': f'Provider inconnu: {key}'}), 400

    set_provider_secret(key, value)
    overview = get_local_config_overview()
    return jsonify({
        'success': True,
        'providers': get_provider_status(),
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
    })


@settings_bp.route('/api/providers/secret/clear', methods=['POST'])
def providers_clear_secret():
    """Efface une clé provider locale."""
    from core.infra.local_config import (
        PROVIDER_META,
        clear_provider_secret,
        get_local_config_overview,
        get_provider_status,
    )

    data = request.get_json(silent=True) or {}
    key = str(data.get('key', '')).strip()

    if key not in PROVIDER_META:
        return jsonify({'success': False, 'error': f'Provider inconnu: {key}'}), 400

    clear_provider_secret(key)
    overview = get_local_config_overview()
    return jsonify({
        'success': True,
        'providers': get_provider_status(),
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
    })


# ========== FEATURE FLAGS ==========

@settings_bp.route('/api/features/status')
def feature_flags_status():
    """Retourne les feature flags locaux du harness."""
    from core.infra.local_config import get_feature_flags, get_local_config_overview, get_onboarding_state
    from core.infra.packs import get_feature_exposure_map, get_pack_index, get_pack_ui_overrides

    overview = get_local_config_overview()
    return jsonify({
        'success': True,
        'features': get_feature_flags(),
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
        'packs': get_pack_index()['packs'],
        'onboarding': get_onboarding_state(),
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
    })


@settings_bp.route('/api/features/set', methods=['POST'])
def feature_flags_set():
    """Met à jour un feature flag local hors git."""
    from core.infra.local_config import (
        DEFAULT_LOCAL_CONFIG,
        get_feature_flags,
        get_local_config_overview,
        set_feature_flag,
    )
    from core.infra.packs import (
        get_feature_exposure_map,
        get_pack_index,
        get_pack_ui_overrides,
        invalidate_runtime_pack_caches,
    )

    data = request.get_json(silent=True) or {}
    key = str(data.get('key', '')).strip()
    value = bool(data.get('value'))
    valid_flags = set(DEFAULT_LOCAL_CONFIG.get('features', {}).keys())

    if key not in valid_flags:
        return jsonify({'success': False, 'error': f'Feature inconnue: {key}'}), 400

    set_feature_flag(key, value)
    invalidate_runtime_pack_caches()
    overview = get_local_config_overview()
    return jsonify({
        'success': True,
        'features': get_feature_flags(),
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
        'packs': get_pack_index()['packs'],
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
    })


# ========== LOCAL PACKS ==========

@settings_bp.route('/api/packs/status')
def packs_status():
    """Retourne les packs locaux installés et la carte d'exposition des features."""
    from core.infra.local_config import get_local_config_overview
    from core.infra.packs import get_feature_exposure_map, get_pack_index, get_pack_ui_overrides, get_packs_dir

    overview = get_local_config_overview()
    index = get_pack_index()
    return jsonify({
        'success': True,
        'packs': index['packs'],
        'active': {kind: pack['id'] for kind, pack in index['active'].items()},
        'packs_dir': str(get_packs_dir()),
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
        'config_path': overview['config_path'],
        'active_source': overview['active_source'],
    })


@settings_bp.route('/api/packs/editor-prompts')
def packs_editor_prompts():
    """Expose only pack prompt snippets that the browser editor is allowed to use."""
    from core.infra.packs import (
        get_feature_exposure_map,
        get_pack_editor_prompt_assets,
        is_adult_runtime_available,
    )

    adult_runtime_available = is_adult_runtime_available()
    editor_prompts = get_pack_editor_prompt_assets("adult") if adult_runtime_available else {}

    return jsonify({
        'success': True,
        'adult_runtime_available': adult_runtime_available,
        'feature_exposure': get_feature_exposure_map(),
        'editor_prompts': editor_prompts,
    })


@settings_bp.route('/api/packs/activate', methods=['POST'])
def packs_activate():
    """Active ou désactive un pack local."""
    from core.infra.packs import get_feature_exposure_map, get_pack_index, get_pack_ui_overrides, set_pack_active

    data = request.get_json(silent=True) or {}
    pack_id = str(data.get('pack_id', '')).strip()
    enabled = bool(data.get('enabled', True))

    if not pack_id:
        return jsonify({'success': False, 'error': 'pack_id requis'}), 400

    try:
        set_pack_active(pack_id, enabled=enabled)
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    index = get_pack_index()
    return jsonify({
        'success': True,
        'packs': index['packs'],
        'active': {kind: pack['id'] for kind, pack in index['active'].items()},
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
    })


@settings_bp.route('/api/packs/import', methods=['POST'])
def packs_import():
    """Importe un pack local depuis une archive zip ou un dossier local."""
    from core.infra.packs import (
        get_feature_exposure_map,
        get_pack_index,
        get_pack_ui_overrides,
        import_pack_from_directory,
        import_pack_from_zip,
    )

    replace = str(request.form.get('replace', 'false')).lower() in {'1', 'true', 'yes', 'on'}

    try:
        if 'archive' in request.files and request.files['archive'].filename:
            pack = import_pack_from_zip(request.files['archive'], replace=replace)
        else:
            data = request.get_json(silent=True) or {}
            source_path = str(data.get('source_path', '')).strip()
            if not source_path:
                return jsonify({'success': False, 'error': 'Archive zip ou source_path requis'}), 400
            pack = import_pack_from_directory(source_path, replace=replace)
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    index = get_pack_index()
    return jsonify({
        'success': True,
        'pack': pack,
        'packs': index['packs'],
        'active': {kind: active_pack['id'] for kind, active_pack in index['active'].items()},
        'pack_ui_overrides': get_pack_ui_overrides(),
        'feature_exposure': get_feature_exposure_map(),
    })


# ========== DOCTOR ==========

@settings_bp.route('/api/doctor/report')
def doctor_report():
    """Rapport doctor pour onboarding et setup public-ready."""
    from core.infra.doctor import run_doctor
    return jsonify(run_doctor())


# ========== ONBOARDING ==========

@settings_bp.route('/api/onboarding/status')
def onboarding_status():
    """Retourne l'état d'onboarding backend.

    The first UI paint asks for this endpoint before showing the setup modal.
    Keep it light by default; the heavier Doctor report is opt-in so the modal
    appears immediately on first launch instead of waiting on machine checks.
    """
    from core.infra.local_config import get_onboarding_state

    payload = {
        'success': True,
        'onboarding': get_onboarding_state(),
    }
    if str(request.args.get('doctor', '')).lower() in {'1', 'true', 'yes', 'on'}:
        from core.infra.doctor import run_doctor
        payload['doctor'] = run_doctor()
    return jsonify(payload)


@settings_bp.route('/api/onboarding/complete', methods=['POST'])
def onboarding_complete():
    """Marque l'onboarding comme terminé et enregistre le profil local."""
    from datetime import datetime
    from core.infra.local_config import get_onboarding_state, update_onboarding_state

    data = request.get_json(silent=True) or {}
    updates = {
        'completed': bool(data.get('completed', True)),
        'locale': str(data.get('locale', get_onboarding_state().get('locale', 'fr')) or 'fr').strip() or 'fr',
        'profile_type': str(data.get('profile_type', get_onboarding_state().get('profile_type', 'casual')) or 'casual').strip() or 'casual',
        'profile_name': str(data.get('profile_name', get_onboarding_state().get('profile_name', '')) or '').strip(),
        'last_completed_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
    }
    state = update_onboarding_state(**updates)
    return jsonify({'success': True, 'onboarding': state})


@settings_bp.route('/api/onboarding/reset', methods=['POST'])
def onboarding_reset():
    """Réinitialise l'onboarding backend."""
    from core.infra.local_config import reset_onboarding_state
    return jsonify({'success': True, 'onboarding': reset_onboarding_state()})


@settings_bp.route('/api/onboarding/locale', methods=['POST'])
def onboarding_locale():
    """Met à jour la langue locale d'interface sans finaliser l'onboarding."""
    from core.infra.local_config import get_onboarding_state, update_onboarding_state

    data = request.get_json(silent=True) or {}
    locale = str(data.get('locale', get_onboarding_state().get('locale', 'fr')) or 'fr').strip() or 'fr'
    state = update_onboarding_state(locale=locale)
    return jsonify({'success': True, 'onboarding': state})


# ========== MODEL SOURCE IMPORT ==========

@settings_bp.route('/api/models/import/resolve', methods=['POST'])
def resolve_model_source_route():
    """Résout une source modèle Hugging Face / CivitAI en entrée stable."""
    from core.infra.model_imports import resolve_model_source

    data = request.get_json(silent=True) or {}
    source = str(data.get('source', '')).strip()
    target_family = str(data.get('target_family', 'generic')).strip() or 'generic'
    if not source:
        return jsonify({'success': False, 'error': 'Source requise'}), 400

    try:
        resolved = resolve_model_source(source, target_family=target_family)
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    return jsonify({'success': True, 'resolved': resolved})


@settings_bp.route('/api/models/import/start', methods=['POST'])
def start_model_source_import():
    """Démarre un import provider local depuis une source Hugging Face / CivitAI."""
    from core.infra.model_imports import start_model_import

    data = request.get_json(silent=True) or {}
    source = str(data.get('source', '')).strip()
    target_family = str(data.get('target_family', 'generic')).strip() or 'generic'
    include_recommended = bool(data.get('include_recommended', True))
    if not source:
        return jsonify({'success': False, 'error': 'Source requise'}), 400

    try:
        job = start_model_import(source, target_family=target_family, include_recommended=include_recommended)
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    return jsonify({'success': True, 'job': job})


@settings_bp.route('/api/models/import/status')
def model_source_import_status():
    """Retourne l'état des imports modèles démarrés depuis l'UI."""
    from core.infra.model_imports import get_model_import_status

    job_id = request.args.get('job_id')
    return jsonify({
        'success': True,
        'job': get_model_import_status(job_id) if job_id else None,
        'jobs': [] if job_id else get_model_import_status(None),
    })


# ========== HARNESS AUDIT ==========

@settings_bp.route('/api/harness/audit')
def harness_audit():
    """Audit déterministe du harness JoyBoy."""
    from core.infra.harness_audit import run_harness_audit

    return jsonify({
        'success': True,
        **run_harness_audit(),
    })


# ========== PROMPT HELPER ==========

@settings_bp.route('/api/prompt-helper/generate', methods=['POST'])
def generate_prompt_helper():
    """Génère une reformulation orientée plateforme pour assister la création de prompt."""
    from core.api_helpers import error_response
    data = request.get_json()
    user_request = data.get('request', '').strip()
    platform = data.get('platform', 'grok')
    media_type = data.get('media_type', 'image')
    model = data.get('model', None)

    if not user_request:
        return error_response("Décris ce que tu veux générer")

    from core.utility_ai import generate_prompt_lab_prompt
    result = generate_prompt_lab_prompt(user_request, platform, media_type, model=model)

    if result.get("error"):
        return error_response(result["error"])
    return jsonify({"success": True, **result})


# ========== PRELOAD ==========

@settings_bp.route('/api/preload/status')
def get_preload_status():
    """Retourne le status du préchargement."""
    from core.preload import get_status
    return jsonify(get_status())


@settings_bp.route('/api/preload/stream')
def preload_stream():
    """SSE endpoint pour le préchargement avec updates temps réel."""
    from flask import Response, stream_with_context
    from core.preload import preload_all
    import json

    def generate():
        for status in preload_all():
            data = json.dumps(status)
            yield f"data: {data}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@settings_bp.route('/api/preload/check')
def check_preload_needed():
    """Vérifie si le préchargement est nécessaire (cache manquant)."""
    from core.preload import get_preload_cache_report

    report = get_preload_cache_report()
    counts = report["counts"]

    return jsonify({
        'needs_preload': not report['ready'],
        'ready': report['ready'],
        'skipped': report.get('skipped', False),
        'skip_reason': report.get('skip_reason'),
        'required': report['required'],
        'optional': report['optional'],
        'cached': {
            item['id']: item['cached']
            for item in report['required']
        },
        'summary': {
            'required_total': counts['required_total'],
            'required_cached': counts['required_cached'],
            'required_missing': counts['required_missing'],
            'optional_total': counts['optional_total'],
            'optional_cached': counts['optional_cached'],
        },
    })


# ========== CONTEXT ==========

@settings_bp.route('/context')
def get_context():
    from core.processing import get_context_summary
    return jsonify({'context': get_context_summary()})


@settings_bp.route('/clear-context', methods=['POST'])
def clear_ctx():
    from core.processing import clear_context
    clear_context()
    return jsonify({'success': True})


# ========== SEGMENTATION ==========

@settings_bp.route('/segmentation/methods')
def segmentation_methods():
    """Liste les stratégies de masque disponibles (Smart Router)"""
    from core.segmentation import SEGFORMER_VARIANT_CLASSES, get_segformer_variant
    variant = get_segformer_variant()
    vinfo = SEGFORMER_VARIANT_CLASSES.get(variant, SEGFORMER_VARIANT_CLASSES['b4'])
    strategies = list(vinfo['strategies'].keys()) + ['target:X', 'full', 'brush_only']
    return jsonify({'success': True, 'methods': strategies})


@settings_bp.route('/segmentation/preload-sam', methods=['POST'])
def preload_sam():
    """Précharge SAM - no-op dans la nouvelle architecture (load-on-demand)"""
    return jsonify({'success': True, 'skipped': True, 'reason': 'load_on_demand'})


# ========== SEGFORMER ==========

@settings_bp.route('/api/segformer/variant')
def segformer_variant_get():
    """Retourne le variant SegFormer actif"""
    from core.segmentation import get_segformer_variant, SEGFORMER_VARIANT_CLASSES
    variant = get_segformer_variant()
    vinfo = SEGFORMER_VARIANT_CLASSES.get(variant, SEGFORMER_VARIANT_CLASSES['b4'])
    return jsonify({
        'variant': variant,
        'label': vinfo['label'],
        'available': list(SEGFORMER_VARIANT_CLASSES.keys())
    })


@settings_bp.route('/api/segformer/variant', methods=['POST'])
def segformer_variant_set():
    """Change le variant SegFormer (fusion, schp, b4, b2, sapiens_1b)"""
    from core.segmentation import set_segformer_variant, get_segformer_variant, SEGFORMER_VARIANT_CLASSES
    data = request.json or {}
    variant = data.get('variant', 'fusion')
    if variant not in SEGFORMER_VARIANT_CLASSES:
        return jsonify({'success': False, 'error': f'Variant inconnu: {variant}'}), 400
    set_segformer_variant(variant)
    vinfo = SEGFORMER_VARIANT_CLASSES[variant]
    print(f"[SETTINGS] SegFormer variant -> {vinfo['label']}")
    return jsonify({'success': True, 'variant': variant, 'label': vinfo['label']})


def _delete_seg_model_from_cache(vinfo):
    """Helper: supprime un modèle de segmentation du cache HuggingFace"""
    repo_id = vinfo['model']
    label = vinfo['label']
    if vinfo.get('engine') == 'sapiens':
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        deleted = False
        for repo in cache_info.repos:
            if repo.repo_id == repo_id:
                for revision in repo.revisions:
                    strategy = cache_info.delete_revisions(revision.commit_hash)
                    strategy.execute()
                    deleted = True
        if deleted:
            print(f"[DELETE] {label} supprimé du cache")
        return deleted
    else:
        from core.models import delete_model_from_cache
        return delete_model_from_cache(repo_id)


@settings_bp.route('/api/segformer/delete', methods=['POST'])
def segformer_delete():
    """Supprime le modèle de segmentation actif du cache"""
    from core.segmentation import (get_segformer_variant, SEGFORMER_VARIANT_CLASSES,
                                    unload_segmentation_models)
    variant = get_segformer_variant()
    vinfo = SEGFORMER_VARIANT_CLASSES[variant]
    label = vinfo['label']

    unload_segmentation_models(force=True)  # Delete = tout décharger

    try:
        success = _delete_seg_model_from_cache(vinfo)
        if success:
            return jsonify({'success': True, 'message': f'{label} supprimé'})
        return jsonify({'success': False, 'error': 'Non trouvé dans le cache'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/segformer/reinstall', methods=['POST'])
def segformer_reinstall():
    """Supprime puis retélécharge le modèle de segmentation actif"""
    from core.segmentation import (get_segformer_variant, SEGFORMER_VARIANT_CLASSES,
                                    unload_segmentation_models, load_clothes_segmenter,
                                    load_sapiens_segmenter)
    variant = get_segformer_variant()
    vinfo = SEGFORMER_VARIANT_CLASSES[variant]
    label = vinfo['label']

    # 1. Décharger + supprimer
    unload_segmentation_models(force=True)  # Reinstall = tout décharger
    try:
        _delete_seg_model_from_cache(vinfo)
    except Exception as e:
        print(f"[REINSTALL] Erreur suppression (continue quand même): {e}")

    # 2. Retélécharger
    try:
        if vinfo.get('engine') == 'sapiens':
            load_sapiens_segmenter()
        else:
            load_clothes_segmenter(variant)
        return jsonify({'success': True, 'message': f'{label} réinstallé'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@settings_bp.route('/api/segformer/verify', methods=['POST'])
def segformer_verify():
    """Vérifie l'intégrité du modèle de segmentation actif (sans décharger les modèles chargés)"""
    from core.segmentation import get_segformer_variant, SEGFORMER_VARIANT_CLASSES

    variant = get_segformer_variant()
    vinfo = SEGFORMER_VARIANT_CLASSES[variant]
    repo_id = vinfo['model']
    label = vinfo['label']
    issues = []

    # 1. Vérifier que les fichiers existent dans le cache
    try:
        from huggingface_hub import scan_cache_dir
        cache_info = scan_cache_dir()
        found = False
        repo_size = 0
        for repo in cache_info.repos:
            if repo.repo_id == repo_id:
                found = True
                repo_size = repo.size_on_disk
                break
        if not found:
            issues.append("Modèle non trouvé dans le cache HuggingFace")
        elif repo_size < 1_000_000:  # < 1MB = probablement corrompu
            issues.append(f"Fichiers trop petits ({repo_size} bytes) - probablement corrompu")
    except Exception as e:
        issues.append(f"Erreur scan cache: {e}")

    # 2. Tenter de charger le modèle sur CPU (sans toucher aux modèles déjà en VRAM)
    if not issues:
        try:
            import torch
            if vinfo.get('engine') == 'sapiens':
                from huggingface_hub import hf_hub_download
                model_path = hf_hub_download(repo_id=repo_id, filename=vinfo['model_file'])
                model = torch.jit.load(model_path, map_location='cpu')
                del model
            else:
                from transformers import SegformerImageProcessor, AutoModelForSemanticSegmentation
                processor = SegformerImageProcessor.from_pretrained(repo_id)
                model = AutoModelForSemanticSegmentation.from_pretrained(
                    repo_id, device_map=None, low_cpu_mem_usage=False
                )
                del processor, model

            import gc
            gc.collect()
        except Exception as e:
            issues.append(f"Erreur chargement: {e}")

    if issues:
        return jsonify({
            'success': True,
            'healthy': False,
            'label': label,
            'issues': issues,
            'recommendation': 'Utilisez "Réinstaller" pour corriger'
        })

    return jsonify({
        'success': True,
        'healthy': True,
        'label': label,
        'message': f'{label} OK - aucun problème détecté'
    })


# ========== BACKEND ==========

@settings_bp.route('/api/backend/gguf/status')
def gguf_status():
    """Retourne le statut du backend GGUF"""
    try:
        from core.gguf_backend import get_gguf_status
        return jsonify(get_gguf_status())
    except ImportError:
        return jsonify({
            'available': False,
            'error': 'Module gguf_backend non trouvé'
        })


@settings_bp.route('/api/backend/set', methods=['POST'])
def set_backend():
    """Change le backend actif (diffusers ou gguf)"""
    global _current_backend, _current_gguf_quant
    from core.model_manager import ModelManager
    data = request.json or {}
    backend = data.get('backend', 'diffusers')
    quant = data.get('quant', _current_gguf_quant)

    if backend not in ['diffusers', 'gguf']:
        return jsonify({'success': False, 'error': f'Backend inconnu: {backend}'}), 400

    _current_backend = backend
    if quant:
        _current_gguf_quant = quant

    # Propager le changement au ModelManager
    mgr = ModelManager.get()
    mgr.set_backend(backend, quant)

    print(f"[SETTINGS] Backend -> {backend}" + (f" ({quant})" if backend == 'gguf' else ""))
    return jsonify({
        'success': True,
        'backend': backend,
        'quant': _current_gguf_quant
    })


@settings_bp.route('/api/backend/get')
def get_backend():
    """Retourne le backend actif"""
    return jsonify({
        'backend': _current_backend,
        'quant': _current_gguf_quant
    })


@settings_bp.route('/api/backend/gguf/convert', methods=['POST'])
def gguf_convert():
    """Convertit un modèle safetensors en GGUF"""
    try:
        from core.gguf_backend import convert_to_gguf, list_convertible_models
        from pathlib import Path

        data = request.json or {}
        source_path = data.get('source_path')
        output_name = data.get('output_name')
        quant = data.get('quant', 'Q6_K')

        if not source_path or not output_name:
            return jsonify({'success': False, 'error': 'source_path et output_name requis'}), 400

        result = convert_to_gguf(
            Path(source_path),
            output_name,
            quant=quant,
        )

        if result:
            return jsonify({
                'success': True,
                'output_path': str(result),
                'quant': quant,
            })
        else:
            return jsonify({'success': False, 'error': 'Échec de la conversion'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/backend/gguf/convertible')
def gguf_convertible():
    """Liste les modèles convertibles en GGUF"""
    try:
        from core.gguf_backend import get_conversion_status
        return jsonify(get_conversion_status())
    except ImportError:
        return jsonify({'convertible_models': [], 'error': 'Module non disponible'})


# ========== LOG ==========

@settings_bp.route('/api/log/model-change', methods=['POST'])
def log_model_change():
    """Log le changement de modèle dans le picker. Pas de preload - load-on-demand."""
    try:
        data = request.json
        new_model = data.get('model', '?')
        model_type = data.get('type', '?')

        icon = "🖼️" if model_type == 'image' else "💬"
        print(f"\n[MODEL-CHANGE] {icon} {model_type.upper()}: {new_model}")

        # Pas de preload. Le modèle sera chargé quand une génération sera demandée.
        return jsonify({'success': True})
    except Exception as e:
        print(f"[MODEL-CHANGE] Erreur: {e}")
        return jsonify({'success': False})


# ========== GALLERY / STORAGE ==========

@settings_bp.route('/api/gallery/list')
def gallery_list():
    """Liste tous les fichiers générés (images et vidéos)"""
    import os
    import glob
    from datetime import datetime
    from core.infra.gallery_metadata import load_gallery_metadata

    def build_gallery_item(filepath, item_type, source, public_path):
        stat = os.stat(filepath)
        meta = load_gallery_metadata(filepath)
        return {
            'type': item_type,
            'source': meta.get('source') or source,
            'name': os.path.basename(filepath),
            'path': public_path,
            'size': stat.st_size,
            'size_mb': round(stat.st_size / (1024 * 1024), 2),
            'created': stat.st_mtime,
            'created_str': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            'model': meta.get('model') or meta.get('model_id') or '',
            'model_id': meta.get('model_id') or '',
            'prompt': meta.get('prompt') or '',
            'final_prompt': meta.get('final_prompt') or '',
            'negative_prompt': meta.get('negative_prompt') or '',
            'metadata': meta,
        }

    # __file__ = web/routes/settings.py → dirname twice = web/ → one more = project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    output_dir = os.path.join(project_root, 'output')
    videos_dir = os.path.join(output_dir, 'videos')

    files = []

    # Vidéos
    if os.path.exists(videos_dir):
        for ext in ['mp4', 'webm', 'gif']:
            for filepath in glob.glob(os.path.join(videos_dir, f'*.{ext}')):
                name = os.path.basename(filepath)
                files.append(build_gallery_item(
                    filepath,
                    'video',
                    'video',
                    f'/output/videos/{name}',
                ))

    # Images dans output/images/
    images_dir = os.path.join(output_dir, 'images')
    if os.path.exists(images_dir):
        for ext in ['png', 'jpg', 'jpeg', 'webp']:
            for filepath in glob.glob(os.path.join(images_dir, f'*.{ext}')):
                name = os.path.basename(filepath)
                # Source: txt2img_ = imagine, kontext_/image_ = modifiée
                if name.startswith('txt2img_'):
                    source = 'imagine'
                else:
                    source = 'modified'
                files.append(build_gallery_item(
                    filepath,
                    'image',
                    source,
                    f'/output/images/{name}',
                ))

    # Trier par date (plus récent en premier)
    files.sort(key=lambda x: x['created'], reverse=True)

    # Stats
    total_size = sum(f['size'] for f in files)
    video_count = len([f for f in files if f['type'] == 'video'])
    image_count = len([f for f in files if f['type'] == 'image'])

    return jsonify({
        'files': files,
        'stats': {
            'total': len(files),
            'videos': video_count,
            'images': image_count,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        }
    })


@settings_bp.route('/api/gallery/delete', methods=['POST'])
def gallery_delete():
    """Supprime un fichier de la galerie"""
    import os

    data = request.json or {}
    filepath = data.get('path', '')

    # Sécurité: vérifier que le chemin est dans output/
    if not filepath.startswith('/output/'):
        return jsonify({'success': False, 'error': 'Chemin invalide'}), 400

    # Construire le chemin réel
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    real_path = os.path.join(project_root, filepath.lstrip('/'))
    real_path = os.path.normpath(real_path)

    # Vérifier que le fichier existe et est dans output
    if not os.path.exists(real_path):
        return jsonify({'success': False, 'error': 'Fichier non trouvé'}), 404

    if 'output' not in real_path:
        return jsonify({'success': False, 'error': 'Chemin invalide'}), 400

    try:
        os.remove(real_path)
        sidecar_path = os.path.splitext(real_path)[0] + '.json'
        if os.path.exists(sidecar_path):
            os.remove(sidecar_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== OUTPUT FILE SERVING ==========

@settings_bp.route('/output/<path:filename>')
def serve_output_file(filename):
    """Sert un fichier depuis le dossier output"""
    import os
    from flask import send_from_directory

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    output_dir = os.path.join(project_root, 'output')
    return send_from_directory(output_dir, filename)


@settings_bp.route('/output/videos/<path:filename>')
def serve_output_video(filename):
    """Sert une vidéo depuis le dossier output/videos"""
    import os
    from flask import send_from_directory

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    videos_dir = os.path.join(project_root, 'output', 'videos')
    return send_from_directory(videos_dir, filename)


# ========== SETUP WIZARD ==========

@settings_bp.route('/api/setup/start', methods=['POST'])
def start_setup():
    """Démarre l'installation des modèles recommandés"""
    global setup_progress

    data = request.json or {}
    text_model = data.get('text_model')

    if not text_model:
        return jsonify({'success': False, 'error': 'Modèle texte requis'})

    # Reset progress
    setup_progress = {
        'status': 'downloading_text',
        'progress': 0,
        'message': f'Téléchargement de {text_model}...',
        'text_model': text_model,
        'error': None
    }

    # Start download in background
    def download_text_model():
        global setup_progress
        try:
            ollama_service = _get_ollama_service()
            # S'assurer qu'Ollama tourne
            if not ollama_service.is_ollama_running():
                setup_progress['message'] = 'Démarrage Ollama...'
                ollama_service.start_ollama()

            # Télécharger le modèle texte
            def progress_callback(status, progress):
                global setup_progress
                if progress >= 0:
                    setup_progress['progress'] = progress
                setup_progress['message'] = f'{text_model}: {status}'

            success, error = ollama_service.pull_model(text_model, progress_callback)

            if success:
                setup_progress['status'] = 'complete'
                setup_progress['progress'] = 100
                setup_progress['message'] = 'Installation terminée!'
            else:
                setup_progress['status'] = 'error'
                setup_progress['error'] = error
                setup_progress['message'] = f'Erreur: {error}'

        except Exception as e:
            setup_progress['status'] = 'error'
            setup_progress['error'] = str(e)
            setup_progress['message'] = f'Erreur: {e}'

    thread = threading.Thread(target=download_text_model)
    thread.daemon = True
    thread.start()

    return jsonify({'success': True})


@settings_bp.route('/api/setup/progress', methods=['GET'])
def get_setup_progress():
    """Retourne la progression de l'installation"""
    return jsonify(setup_progress)


@settings_bp.route('/api/setup/skip', methods=['POST'])
def skip_setup():
    """Skip l'installation auto - l'utilisateur installera manuellement"""
    global setup_progress
    setup_progress = {
        'status': 'idle',
        'progress': 0,
        'message': '',
        'text_model': None,
        'error': None
    }
    return jsonify({'success': True})


@settings_bp.route('/api/setup/profile', methods=['POST'])
def setup_profile_models():
    """Télécharge les modèles pour un profil donné"""
    global setup_progress

    data = request.json or {}
    profile = data.get('profile', 'casual')

    # Importer les configs
    try:
        from config import UTILITY_MODEL, MODEL_RECOMMENDATIONS, VRAM_THRESHOLDS
    except ImportError:
        UTILITY_MODEL = "qwen3.5:2b"
        MODEL_RECOMMENDATIONS = {
            "casual": {"low": "qwen3.5:0.8b", "medium": "qwen3.5:2b", "high": "qwen3.5:4b"}
        }
        VRAM_THRESHOLDS = {"low": 4, "medium": 8, "high": 999}

    # Déterminer le niveau VRAM
    import torch
    vram_level = "low"
    if torch.cuda.is_available():
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if vram_gb >= VRAM_THRESHOLDS["medium"]:
            vram_level = "high"
        elif vram_gb >= VRAM_THRESHOLDS["low"]:
            vram_level = "medium"

    # Obtenir le modèle recommandé pour ce profil
    if profile in MODEL_RECOMMENDATIONS:
        chat_model = MODEL_RECOMMENDATIONS[profile].get(vram_level, MODEL_RECOMMENDATIONS["casual"]["medium"])
    else:
        chat_model = MODEL_RECOMMENDATIONS["casual"].get(vram_level, "qwen3.5:2b")

    # Reset progress
    setup_progress = {
        'status': 'downloading_utility',
        'progress': 0,
        'message': f'Téléchargement de {UTILITY_MODEL}...',
        'text_model': chat_model,
        'utility_model': UTILITY_MODEL,
        'profile': profile,
        'error': None
    }

    def download_models():
        global setup_progress
        try:
            ollama_service = _get_ollama_service()
            # S'assurer qu'Ollama tourne
            if not ollama_service.is_ollama_running():
                setup_progress['message'] = 'Démarrage Ollama...'
                ollama_service.start_ollama()

            # 1. Télécharger le utility model d'abord
            setup_progress['status'] = 'downloading_utility'
            setup_progress['message'] = f'Téléchargement {UTILITY_MODEL} (utility)...'

            def progress_utility(status, progress):
                global setup_progress
                if progress >= 0:
                    # 0-40% pour utility model
                    setup_progress['progress'] = int(progress * 0.4)
                setup_progress['message'] = f'{UTILITY_MODEL}: {status}'

            success, error = ollama_service.pull_model(UTILITY_MODEL, progress_utility)
            if not success:
                setup_progress['status'] = 'error'
                setup_progress['error'] = f"Erreur utility model: {error}"
                return

            # 2. Télécharger le chat model
            setup_progress['status'] = 'downloading_chat'
            setup_progress['message'] = f'Téléchargement {chat_model} (chat)...'

            def progress_chat(status, progress):
                global setup_progress
                if progress >= 0:
                    # 40-100% pour chat model
                    setup_progress['progress'] = 40 + int(progress * 0.6)
                setup_progress['message'] = f'{chat_model}: {status}'

            success, error = ollama_service.pull_model(chat_model, progress_chat)
            if not success:
                setup_progress['status'] = 'error'
                setup_progress['error'] = f"Erreur chat model: {error}"
                return

            # Terminé!
            setup_progress['status'] = 'complete'
            setup_progress['progress'] = 100
            setup_progress['message'] = 'Installation terminée!'

        except Exception as e:
            setup_progress['status'] = 'error'
            setup_progress['error'] = str(e)
            setup_progress['message'] = f'Erreur: {e}'

    thread = threading.Thread(target=download_models)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'utility_model': UTILITY_MODEL,
        'chat_model': chat_model,
        'profile': profile,
        'vram_level': vram_level
    })
