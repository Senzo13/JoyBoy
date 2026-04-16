"""
Flask backend pour l'interface
"""
import os
import sys
import warnings
import logging

# Supprimer les warnings xformers/Triton si d'autres modules tentent de les importer
# (models.py désinstalle xformers au startup, mais certains imports peuvent logger)
warnings.filterwarnings("ignore", message=".*Triton.*")
warnings.filterwarnings("ignore", message=".*triton.*")
warnings.filterwarnings("ignore", message=".*xformers.*")
logging.getLogger("xformers").setLevel(logging.ERROR)

from flask import Flask, render_template
from PIL import Image
import base64
from io import BytesIO

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import AI_NAME, MESSAGES
from core.models import MODELS
from core import ollama_service
from core import tunnel_service
from core.model_manager import ModelManager
from contextlib import contextmanager
import threading

# Nettoyage dossiers pip corrompus (~ prefix = install interrompue)
try:
    import site as _site
    _sp_dirs = _site.getsitepackages() if hasattr(_site, 'getsitepackages') else []
    if not _sp_dirs:
        _sp_dirs = [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'venv', 'Lib', 'site-packages')]
    for _sp in _sp_dirs:
        if os.path.isdir(_sp):
            for _item in os.listdir(_sp):
                if _item.startswith('~'):
                    import shutil as _shutil
                    _corrupt = os.path.join(_sp, _item)
                    try:
                        _shutil.rmtree(_corrupt)
                        print(f"[SETUP] Nettoyé dossier corrompu: {_item}")
                    except Exception:
                        pass
except Exception:
    pass

# Auto-install dépendances manquantes au démarrage
# Vérifie les imports critiques — si un seul manque, pip install -r requirements.txt
_CRITICAL_IMPORTS = [
    'flask', 'PIL', 'numpy', 'diffusers', 'transformers', 'accelerate',
    'safetensors', 'einops', 'sentencepiece', 'peft', 'scipy', 'ftfy',
    'omegaconf',
]
_missing_pkgs = []
for _mod in _CRITICAL_IMPORTS:
    try:
        __import__(_mod)
    except (ImportError, OSError):
        _missing_pkgs.append(_mod)

if _missing_pkgs:
    import subprocess as _sp
    print(f"[SETUP] {len(_missing_pkgs)} package(s) manquant(s): {', '.join(_missing_pkgs)}")
    print("[SETUP] Installation automatique depuis requirements.txt...")
    _req_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'requirements.txt')
    if os.path.exists(_req_path):
        _sp.run([sys.executable, '-m', 'pip', 'install', '-r', _req_path, '--quiet'], check=False)
    else:
        print("[SETUP] requirements.txt introuvable, installation individuelle...")
        _PKG_MAP = {'PIL': 'Pillow', 'cv2': 'opencv-python-headless'}
        for _m in _missing_pkgs:
            _p = _PKG_MAP.get(_m, _m)
            _sp.run([sys.executable, '-m', 'pip', 'install', _p, '--quiet'], check=False)
    print("[SETUP] Installation terminée!")

app = Flask(__name__, static_folder='static', template_folder='templates')

# Register Blueprints
from web.routes.chat import chat_bp
app.register_blueprint(chat_bp)
from web.routes.generation import generation_bp
app.register_blueprint(generation_bp)
from web.routes.video import video_bp
app.register_blueprint(video_bp)
from web.routes.terminal import terminal_bp
app.register_blueprint(terminal_bp)
from web.routes.models import models_bp
app.register_blueprint(models_bp)
from web.routes.system import system_bp
app.register_blueprint(system_bp)
from web.routes.settings import settings_bp
app.register_blueprint(settings_bp)
from web.routes.training import training_bp
app.register_blueprint(training_bp)
from web.routes.runtime import runtime_bp
app.register_blueprint(runtime_bp)

# Désactiver les logs de requêtes HTTP (werkzeug)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# State
class AppState:
    original_image = None
    modified_image = None
    current_prompt = ""
    chat_history = []  # Historique de conversation
    last_user_image = None  # Dernière image envoyée par l'utilisateur
    last_original_image = None  # Dernière image originale
    last_modified_image = None  # Dernière image modifiée
    last_mask = None  # Dernier masque utilisé (pour refine)
    brush_masks = {}  # Masques dessinés à la main par image (pour X-Ray Ghost)
    last_prompt = ""  # Dernier prompt utilisé (pour refine)
    last_model = ""  # Dernier modèle utilisé (pour refine)

state = AppState()

# Active generations tracking (for cancellation)
active_generations = {}  # {generation_id: {"cancelled": bool, "chat_id": str}}
generations_lock = threading.Lock()

# Universal cancellation flags
chat_stream_cancelled = False
generation_cancelled = False  # For image/video — checked by is_cancelled()


@contextmanager
def generation_pipeline(task_type, generation_id, preload_future=None, **load_kwargs):
    """
    Context manager pour toute génération.
    unload_all → load_for_task → yield → cleanup

    Si preload_future est fourni, attend que le preload (lancé en background) se termine
    au lieu de refaire load_for_task.
    Timeout 120s + fallback sur load_for_task direct si le preload échoue.
    Si le preload est stale (retourné sans charger, car une nouvelle gen l'a remplacé),
    on fait un load_for_task direct.
    """
    import concurrent.futures
    mgr = ModelManager.get()
    active_generations[generation_id] = {"cancelled": False}
    resource_scheduler = None
    resource_lease_id = None
    try:
        try:
            from core.runtime import get_job_manager, get_resource_scheduler

            resource_scheduler = get_resource_scheduler()
            status_snapshot = mgr.get_status()
            lease = resource_scheduler.begin_task(
                task_type,
                job_id=generation_id,
                model_name=str(load_kwargs.get("model_name", "")),
                requested_kwargs=load_kwargs,
                status_snapshot=status_snapshot,
            )
            resource_lease_id = lease.get("id")
            get_job_manager().update(
                generation_id,
                metadata={"resource_plan": lease.get("plan", {})},
            )
        except Exception as exc:
            print(f"[RUNTIME] Resource scheduler skipped: {exc}")

        if preload_future is not None:
            try:
                preload_future.result(timeout=120)
            except concurrent.futures.TimeoutError:
                print("[PIPELINE] Preload timeout (120s), fallback direct load")
                mgr.load_for_task(task_type, **load_kwargs)
            except Exception as e:
                print(f"[PIPELINE] Preload error: {e}, fallback direct load")
                mgr.load_for_task(task_type, **load_kwargs)
            else:
                # Preload returned OK — but check if it actually loaded the model.
                # A stale preload (superseded by newer gen) returns early without loading.
                if mgr._inpaint_pipe is None and task_type in ('inpaint', 'inpaint_controlnet'):
                    print("[PIPELINE] Preload was stale (no pipe loaded), fallback direct load")
                    mgr.load_for_task(task_type, **load_kwargs)
                else:
                    # Preload succeeded — handle IP-Adapter (not included in preload)
                    needs_ip_adapter = load_kwargs.get('needs_ip_adapter', False)
                    if needs_ip_adapter:
                        mgr._load_ip_adapter_face()
                    elif mgr._ip_adapter_loaded:
                        mgr._unload_ip_adapter_safe()
        else:
            mgr.load_for_task(task_type, **load_kwargs)
        yield mgr
    finally:
        mgr.cleanup()
        if resource_scheduler and resource_lease_id:
            resource_scheduler.end_task(resource_lease_id)
        active_generations.pop(generation_id, None)


def pil_to_base64(img):
    if img is None:
        return None
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def base64_to_pil(b64_string):
    if not b64_string:
        return None
    # Remove data URL prefix if present
    if ',' in b64_string:
        b64_string = b64_string.split(',')[1]
    img_data = base64.b64decode(b64_string)
    return Image.open(BytesIO(img_data))


def get_image_hash(img):
    """Calcule un hash simple d'une image pour l'identifier."""
    import hashlib
    # Resize petit pour hash rapide, convertir en bytes
    thumb = img.copy()
    thumb.thumbnail((64, 64))
    return hashlib.md5(thumb.tobytes()).hexdigest()[:16]


@app.route('/')
def index():
    return render_template('index.html',
        models=list(MODELS.keys()),
        ai_name=AI_NAME,
        messages=MESSAGES
    )


if __name__ == '__main__':
    # ASCII Art Banner
    print("\n")
    print("       ██╗ ██████╗ ██╗   ██╗██████╗  ██████╗ ██╗   ██╗")
    print("       ██║██╔═══██╗╚██╗ ██╔╝██╔══██╗██╔═══██╗╚██╗ ██╔╝")
    print("       ██║██║   ██║ ╚████╔╝ ██████╔╝██║   ██║ ╚████╔╝ ")
    print("  ██   ██║██║   ██║  ╚██╔╝  ██╔══██╗██║   ██║  ╚██╔╝  ")
    print("  ╚█████╔╝╚██████╔╝   ██║   ██████╔╝╚██████╔╝   ██║   ")
    print("   ╚════╝  ╚═════╝    ╚═╝   ╚═════╝  ╚═════╝    ╚═╝   ")
    print("")
    print("        Dream. Create. Be Free.")
    print("        100% local · Zero cloud · No limits")
    print("")
    print(f"        {AI_NAME} is running at: http://127.0.0.1:7860")
    print("\n")

    # Vérifier Ollama
    if ollama_service.is_ollama_installed():
        print("[STARTUP] Ollama détecté")
        if not ollama_service.is_ollama_running():
            print("[STARTUP] Démarrage d'Ollama...")
            ollama_service.start_ollama()

        models = ollama_service.get_installed_models()
        model_names = [m['name'] for m in models]

        if models:
            print(f"[STARTUP] {len(models)} modèle(s) Ollama disponible(s)")
            for m in models[:3]:
                print(f"  - {m['name']} ({m['size']})")

        # Vérifier le utility model sans bloquer le démarrage.
        # Le téléchargement est géré par l'onboarding/doctor ou par le premier
        # appel texte utile. Le faire ici rendait le boot imprévisible sur les
        # petites configs et les connexions lentes.
        from config import UTILITY_MODEL
        if UTILITY_MODEL not in model_names:
            print(f"[STARTUP] Utility model manquant: {UTILITY_MODEL} (installation différée)")
            print(f"  -> Doctor/onboarding ou premier appel pourra lancer: ollama pull {UTILITY_MODEL}")

        if not models:
            print("[STARTUP] Aucun modèle de chat installé")
            print("  -> ollama pull qwen2.5vl:3b")
    else:
        print("[STARTUP] Ollama non installé")
        print("  -> https://ollama.ai/download")

    # Vérifications en background (ne bloque pas le démarrage)
    def background_checks():
        # Web Search dependencies
        try:
            from core.web_search import check_and_install_dependencies, is_searxng_available

            deps_ok = check_and_install_dependencies(silent=True)
            if deps_ok:
                if is_searxng_available():
                    print("[STARTUP] ✓ SearXNG disponible")
        except Exception:
            pass

        # Auto-start tunnel Cloudflare si activé
        tunnel_cfg = tunnel_service.load_tunnel_config()
        if tunnel_cfg.get("enabled"):
            print("[STARTUP] Tunnel Cloudflare démarrage...")
            result = tunnel_service.start_tunnel(port=7860)
            if result.get("success"):
                url = result['url']
                import time, sys
                time.sleep(1)
                sys.stdout.write(f"\n\n{'='*60}\n   TUNNEL CLOUDFLARE ACTIF\n   {url}\n{'='*60}\n\n")
                sys.stdout.flush()

    import threading
    threading.Thread(target=background_checks, daemon=True).start()

    print("\n[STARTUP] Prêt! (Modèles image chargés à la demande)\n")

    app.run(host='127.0.0.1', port=7860, debug=False)
