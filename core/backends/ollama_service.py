"""
Service Ollama pour le chat local et le routing léger.
"""
import requests
import subprocess
import sys
import os
import time
import json

# Import config
try:
    from config import (
        EXTREME_CHAT_MODEL,
        EXTREME_CHAT_MODEL_INT8,
        HIGH_END_CHAT_MODEL,
        UTILITY_MODEL,
        VIDEO_ANALYSIS_MODEL,
        VIDEO_ANALYSIS_MODEL_EXTREME,
        OLLAMA_MAX_VRAM_GB,
        OLLAMA_BASE_URL,
    )
except ImportError:
    UTILITY_MODEL = "qwen3.5:2b"
    HIGH_END_CHAT_MODEL = "llama3.3:70b-instruct-q8_0"
    EXTREME_CHAT_MODEL = "qwen3:235b-a22b-instruct-2507-q4_K_M"
    EXTREME_CHAT_MODEL_INT8 = "qwen3:235b-a22b-instruct-2507-q8_0"
    VIDEO_ANALYSIS_MODEL = "qwen3-vl:32b-instruct-q8_0"
    VIDEO_ANALYSIS_MODEL_EXTREME = "qwen3-vl:235b-a22b-instruct-q4_K_M"
    OLLAMA_MAX_VRAM_GB = None
    OLLAMA_BASE_URL = "http://127.0.0.1:11434"

def get_effective_ollama_max_vram_gb():
    """Return the configured Ollama VRAM cap, preferring the active GPU profile."""
    if os.environ.get("JOYBOY_OLLAMA_MAX_VRAM_GB", "").strip():
        return OLLAMA_MAX_VRAM_GB
    try:
        from core.models.gpu_profile import get_config
        value = get_config("ollama").get("max_vram_gb")
        if value is not None:
            return float(value)
    except Exception:
        pass
    return OLLAMA_MAX_VRAM_GB


def _apply_ollama_vram_env(env=None):
    target = env if env is not None else os.environ
    limit_gb = get_effective_ollama_max_vram_gb()
    if limit_gb is not None and float(limit_gb) > 0:
        max_vram_bytes = int(float(limit_gb) * 1024 * 1024 * 1024)
        target["OLLAMA_MAX_VRAM"] = str(max_vram_bytes)
    return limit_gb


# Configurer la limite VRAM globalement (pour tous les sous-processus)
_apply_ollama_vram_env()

# Cache pour savoir si le utility model est installé
_utility_model_available = None
_utility_model_warmed = False


def _select_utility_model(auto_pull=False):
    try:
        from core.ai.text_model_router import select_text_model
        return select_text_model("utility", auto_pull=auto_pull)
    except Exception as exc:
        print(f"[OLLAMA] Sélection modèle texte indisponible: {exc}")
        return None


def is_ollama_installed():
    """Vérifie si Ollama est installé"""
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def restart_ollama_with_vram_limit():
    """
    Redémarre Ollama avec la limite VRAM configurée.
    Nécessaire si Ollama était déjà en cours d'exécution.
    """
    print("[OLLAMA] Redémarrage avec limite VRAM...")

    # Arrêter Ollama (platform-specific)
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                          capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                          capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
    else:
        # Linux/Mac
        try:
            subprocess.run(["pkill", "-f", "ollama"], capture_output=True)
        except Exception:
            pass

    time.sleep(1)

    # Redémarrer avec les nouvelles settings
    return start_ollama()


def is_ollama_running():
    """Vérifie si le serveur Ollama tourne"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def start_ollama():
    """Démarre le serveur Ollama en arrière-plan avec limite VRAM"""
    if is_ollama_running():
        return True

    try:
        # Configurer la limite VRAM (offload vers RAM au-delà)
        env = os.environ.copy()
        limit_gb = _apply_ollama_vram_env(env)
        if limit_gb:
            print(f"[OLLAMA] Limite VRAM: {limit_gb}GB (offload RAM au-delà)")

        # Windows
        if sys.platform == "win32":
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )

        # Attendre que le serveur démarre
        for _ in range(10):
            time.sleep(0.5)
            if is_ollama_running():
                print("[OLLAMA] Serveur démarré")
                return True

        return False
    except Exception as e:
        print(f"[OLLAMA] Erreur démarrage: {e}")
        return False


def get_installed_models(quiet=False):
    """Retourne la liste des modèles installés avec détails (params, quant, famille)"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = []
            for model in data.get("models", []):
                name = model.get("name", "")
                size = model.get("size", 0)
                size_gb = round(size / (1024**3), 1) if size else 0
                details = model.get("details", {})
                families = details.get("families", [])
                models.append({
                    "name": name,
                    "size": f"{size_gb}GB",
                    "modified": model.get("modified_at", ""),
                    "params": details.get("parameter_size", ""),
                    "quant": details.get("quantization_level", ""),
                    "family": details.get("family", ""),
                    "vision": "clip" in families,
                })
            return models
    except Exception as e:
        if not quiet:
            print(f"[OLLAMA] Erreur liste modèles: {e}")
    return []


def is_utility_model_available():
    """Vérifie si le utility model (pour checks rapides) est installé"""
    global _utility_model_available

    if _utility_model_available is not None:
        return _utility_model_available

    choice = _select_utility_model(auto_pull=False)
    _utility_model_available = bool(choice and choice.installed)

    if _utility_model_available:
        print(f"[UTILITY] {choice.name} disponible pour les checks rapides")
    else:
        print(f"[UTILITY] {UTILITY_MODEL} non installé - checks désactivés ou via chat model")

    return _utility_model_available


def get_check_model(fallback_model=None):
    """Retourne le modèle à utiliser pour les checks (image, memory)"""
    choice = _select_utility_model(auto_pull=True)
    if choice:
        return choice.name
    return fallback_model or get_default_model()


def reset_utility_model_cache():
    """Reset le cache pour re-vérifier si le utility model est dispo"""
    global _utility_model_available
    _utility_model_available = None



def search_models(query="", filter_type=None):
    """Recherche des modèles disponibles (liste statique des populaires)"""
    # Modèles avec tags: open, fast (<=3b), powerful (>=13b), vision (comprend les images)
    popular_models = [
        # === MODÈLES VISION (comprennent les images) ===
        {"name": "qwen2.5vl:3b", "desc": "Qwen 2.5 VL - Vision léger et performant (recommandé)", "size": "2.1GB", "uncensored": False, "fast": True, "powerful": False, "vision": True},
        {"name": "moondream:1.8b", "desc": "Moondream - Vision ultra-léger (filtrage plus strict)", "size": "1.7GB", "uncensored": False, "fast": True, "powerful": False, "vision": True},
        {"name": VIDEO_ANALYSIS_MODEL, "desc": "Qwen3-VL 32B INT8 - analyse locale de keyframes vidéo", "size": "~35GB", "uncensored": False, "fast": False, "powerful": True, "vision": True, "high_end": True, "auto_pull": False},
        {"name": VIDEO_ANALYSIS_MODEL_EXTREME, "desc": "Qwen3-VL 235B MoE Q4 - vision très lourde pour cloud local", "size": "~140GB", "uncensored": False, "fast": False, "powerful": True, "vision": True, "high_end": True, "auto_pull": False},

        # === MODÈLES QWEN RÉCENTS POUR ROUTING/CHAT LÉGER ===
        {"name": "qwen3.5:0.8b", "desc": "Qwen 3.5 0.8B - Ultra léger pour routing et réponses rapides", "size": "1GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},
        {"name": "qwen3.5:2b", "desc": "Qwen 3.5 2B - Recommandé pour JoyBoy: meilleur que 2.5 sans exploser la VRAM", "size": "2.7GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},
        {"name": "qwen3.5:4b", "desc": "Qwen 3.5 4B - Plus robuste, encore raisonnable", "size": "3.4GB", "uncensored": False, "fast": False, "powerful": False, "vision": False},
        {"name": "qwen3:30b-a3b-instruct-2507-q4_K_M", "desc": "Qwen3 30B-A3B Q4 - très récent, rapide sur A100 40GB, excellent généraliste", "size": "~19GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "qwen3:32b-q4_K_M", "desc": "Qwen3 32B Q4 - dense, raisonnement solide, bon choix 40GB", "size": "~20GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "qwen3-coder:30b-a3b-q4_K_M", "desc": "Qwen3 Coder 30B-A3B Q4 - code/agent, long contexte, recommandé dev", "size": "~19GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},

        # === MODÈLES OPEN ULTRA-LÉGERS (pour petites configs) ===
        {"name": "tinydolphin:1.1b", "desc": "TinyDolphin - Ultra léger, réponse directe", "size": "637MB", "uncensored": True, "fast": True, "powerful": False, "vision": False},
        {"name": "dolphin-phi:2.7b", "desc": "Dolphin Phi - Léger et flexible", "size": "1.6GB", "uncensored": True, "fast": True, "powerful": False, "vision": False},

        # === MODÈLES OPEN (recommandés) ===
        {"name": "dolphin-mistral:7b", "desc": "Dolphin Mistral - Rapide et ouvert", "size": "4.1GB", "uncensored": True, "fast": False, "powerful": False, "vision": False},
        {"name": "dolphin-llama3:8b", "desc": "Dolphin Llama3 - Intelligent et ouvert", "size": "4.7GB", "uncensored": True, "fast": False, "powerful": False, "vision": False},
        {"name": "nous-hermes2:10.7b", "desc": "Nous Hermes 2 - Très intelligent, créatif", "size": "6.1GB", "uncensored": True, "fast": False, "powerful": True, "vision": False},
        {"name": "openhermes:7b", "desc": "OpenHermes - Polyvalent et permissif", "size": "4.1GB", "uncensored": True, "fast": False, "powerful": False, "vision": False},
        {"name": "wizard-vicuna-uncensored:13b", "desc": "Wizard Vicuna - Puissant, style ouvert", "size": "7.4GB", "uncensored": True, "fast": False, "powerful": True, "vision": False},
        {"name": "dolphin-mixtral:8x7b", "desc": "Dolphin Mixtral - Le plus capable", "size": "26GB", "uncensored": True, "fast": False, "powerful": True, "vision": False},
        {"name": "llama2-uncensored:7b", "desc": "Llama 2 - Variante ouverte", "size": "3.8GB", "uncensored": True, "fast": False, "powerful": False, "vision": False},

        # === MODÈLES RAPIDES (<=3B) ===
        {"name": "qwen2.5:3b", "desc": "Qwen 2.5 3B - Très rapide, léger", "size": "2GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},
        {"name": "llama3.2:3b", "desc": "Llama 3.2 - Meta, rapide", "size": "2GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},
        {"name": "phi3:mini", "desc": "Phi-3 Mini - Microsoft, très rapide", "size": "2.3GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},
        {"name": "gemma2:2b", "desc": "Gemma 2 2B - Google, léger", "size": "1.6GB", "uncensored": False, "fast": True, "powerful": False, "vision": False},

        # === MODÈLES STANDARDS ===
        {"name": "qwen3.5:9b", "desc": "Qwen 3.5 9B - Plus capable, à réserver aux configs confortables", "size": "6.6GB", "uncensored": False, "fast": False, "powerful": True, "vision": False},
        {"name": "llama3.3:70b-instruct-q4_K_M", "desc": "Llama 3.3 70B Q4 - gros chat local réaliste pour 40GB VRAM", "size": "~43GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": HIGH_END_CHAT_MODEL, "desc": "Llama 3.3 70B INT8 - chat local haute VRAM", "size": "~70GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": EXTREME_CHAT_MODEL, "desc": "Qwen3 235B-A22B MoE Q4 - très puissant, RAM système élevée", "size": "~140GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": EXTREME_CHAT_MODEL_INT8, "desc": "Qwen3 235B-A22B MoE INT8 - qualité max, téléchargement massif", "size": "~250GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "deepseek-r1:7b", "desc": "DeepSeek R1 - Bon raisonnement", "size": "4.7GB", "uncensored": False, "fast": False, "powerful": False, "vision": False},
        {"name": "deepseek-r1:14b", "desc": "DeepSeek R1 14B - Plus puissant", "size": "9GB", "uncensored": False, "fast": False, "powerful": True, "vision": False},
        {"name": "deepseek-r1:32b", "desc": "DeepSeek R1 32B - raisonnement costaud, bon fit A100 40GB", "size": "~20GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "openthinker:32b-q4_K_M", "desc": "OpenThinker 32B Q4 - raisonnement/math/code open, format 40GB-friendly", "size": "~20GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "nemotron:70b-instruct-q4_K_M", "desc": "Nemotron 70B Q4 - NVIDIA, très bon assistant local haute VRAM", "size": "~43GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "tulu3:70b-q4_K_M", "desc": "Tulu 3 70B Q4 - instruct open, alternative solide à Llama", "size": "~43GB", "uncensored": False, "fast": False, "powerful": True, "vision": False, "high_end": True, "auto_pull": False},
        {"name": "qwen2.5:7b", "desc": "Qwen 2.5 - Rapide et polyvalent", "size": "4.7GB", "uncensored": False, "fast": False, "powerful": False, "vision": False},
        {"name": "mistral:7b", "desc": "Mistral - Français, performant", "size": "4.1GB", "uncensored": False, "fast": False, "powerful": False, "vision": False},
        {"name": "codellama:7b", "desc": "Code Llama - Spécialisé code", "size": "3.8GB", "uncensored": False, "fast": False, "powerful": False, "vision": False},
        {"name": "llama3.1:70b", "desc": "Llama 3.1 70B - Très puissant", "size": "40GB", "uncensored": False, "fast": False, "powerful": True, "vision": False},
    ]

    results = popular_models

    # Apply text search
    if query:
        query = query.lower()
        results = [m for m in results if query in m["name"].lower() or query in m["desc"].lower()]

    return results


def pull_model(model_name, progress_callback=None):
    """Télécharge un modèle Ollama"""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
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

                if progress_callback and total > 0:
                    progress = int((completed / total) * 100)
                    progress_callback(status, progress)
                elif progress_callback:
                    progress_callback(status, -1)

                if data.get("error"):
                    return False, data["error"]

        return True, "OK"
    except Exception as e:
        return False, str(e)


def delete_model(model_name):
    """Supprime un modèle Ollama"""
    try:
        response = requests.delete(
            f"{OLLAMA_BASE_URL}/api/delete",
            json={"name": model_name},
            timeout=30
        )
        return response.status_code == 200
    except Exception:
        return False


def get_loaded_models():
    """Retourne la liste des modèles actuellement chargés en VRAM"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            return [m.get("name", "unknown") for m in models]
    except Exception:
        pass
    return []


def get_loaded_models_detailed():
    """
    Retourne les infos détaillées des modèles chargés en VRAM.
    Inclut: nom, taille, VRAM utilisée, contexte, etc.
    """
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            result = []
            for m in models:
                model_info = {
                    'name': m.get('name', 'unknown'),
                    'size_gb': round(m.get('size', 0) / 1024**3, 2),
                    'vram_gb': round(m.get('size_vram', 0) / 1024**3, 2),
                    'digest': m.get('digest', '')[:12],  # Short hash
                }
                # Extraire les details si disponibles
                details = m.get('details', {})
                if details:
                    model_info['family'] = details.get('family', '')
                    model_info['parameter_size'] = details.get('parameter_size', '')
                    model_info['quantization'] = details.get('quantization_level', '')
                result.append(model_info)
            return result
    except Exception as e:
        print(f"[OLLAMA] Erreur get_loaded_models_detailed: {e}")
    return []


def log_loaded_models(context: str = ""):
    """Log les modèles actuellement chargés en VRAM"""
    models = get_loaded_models()
    if models:
        print(f"[VRAM] {context} Modèles chargés: {', '.join(models)}")
    else:
        print(f"[VRAM] {context} Aucun modèle chargé")
    return models


def unload_model(model_name):
    """Décharge un modèle de la RAM Ollama (keep_alive: 0). Non-bloquant."""
    try:
        before = get_loaded_models()
        if model_name not in str(before):
            return True

        print(f"   ├─ Déchargement {model_name}...")

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model_name,
                "prompt": "",
                "keep_alive": "0s",
                "stream": False
            },
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        return False


def preload_model(model_name):
    """Précharge un modèle dans la VRAM"""
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model_name,
                "prompt": "hello",
                "keep_alive": "5m",
                "think": False,
                "options": {"num_predict": 1}
            },
            timeout=60
        )
        if response.status_code == 200:
            return True
        return False
    except Exception as e:
        return False


def chat(messages, model="qwen3.5:2b", max_tokens=2000):
    """
    Envoie un message au modèle Ollama (non-streaming, pour compatibilité)
    messages: liste de {"role": "user"|"assistant"|"system", "content": str}
    Retourne: (response_text, success)
    """
    if not is_ollama_running():
        if not start_ollama():
            return "Erreur: Ollama n'est pas démarré", False

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.5,
                }
            },
            timeout=120
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("message", {}).get("content", ""), True
        else:
            return f"Erreur Ollama: {response.status_code}", False

    except requests.exceptions.Timeout:
        return "Timeout - le modèle met trop de temps", False
    except Exception as e:
        return f"Erreur: {str(e)}", False


def chat_stream(messages, model="qwen3.5:2b", max_tokens=2000):
    """
    Envoie un message au modèle Ollama avec streaming
    Yields: chunks de texte au fur et à mesure
    """
    # Déléguer à la version avec contexte
    for chunk in chat_stream_with_context(messages, model, max_tokens, context_size=4096):
        yield chunk


def chat_stream_with_context(messages, model="qwen3.5:2b", max_tokens=2000, context_size=4096):
    """
    Envoie un message au modèle Ollama avec streaming et taille de contexte configurable
    Yields: chunks de texte au fur et à mesure
    """
    if not is_ollama_running():
        if not start_ollama():
            yield {"error": "Ollama n'est pas démarré"}
            return

    try:
        options = {
            "temperature": 0.5,
            "num_ctx": context_size,  # Taille du contexte configurable
        }

        # num_predict: -1 = illimité, 0 = défaut Ollama, >0 = limite
        if max_tokens == -1:
            options["num_predict"] = -1  # Illimité pour le mode terminal
        elif max_tokens > 0:
            options["num_predict"] = max_tokens

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "think": False,
                "options": options
            },
            stream=True,
            timeout=300  # 5 min pour les gros contextes
        )

        if response.status_code != 200:
            yield {"error": f"Erreur Ollama: {response.status_code}"}
            return

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    if data.get("done"):
                        # Récupérer les stats de tokens depuis la réponse Ollama
                        token_stats = {
                            "prompt_tokens": data.get("prompt_eval_count", 0),
                            "completion_tokens": data.get("eval_count", 0),
                            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                            "context_size": context_size
                        }
                        yield {"done": True, "token_stats": token_stats}
                    else:
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield {"content": content}
                except json.JSONDecodeError:
                    continue

    except requests.exceptions.Timeout:
        yield {"error": "Timeout"}
    except Exception as e:
        yield {"error": str(e)}


def get_default_model():
    """Retourne le modèle par défaut (préfère les petits modèles ≤3B)"""
    models = get_installed_models()
    if models:
        # Préférer Qwen 3.5 léger si installé.
        for m in models:
            if "qwen3.5:2b" in m["name"].lower():
                return m["name"]
        for m in models:
            if "qwen3.5:0.8b" in m["name"].lower():
                return m["name"]
        for m in models:
            if "qwen3:1.7b" in m["name"].lower():
                return m["name"]
        # Sinon un modèle 3B quelconque
        for m in models:
            if "3b" in m["name"].lower():
                return m["name"]
        # Sinon le premier installé
        return models[0]["name"]
    return "qwen3.5:2b"


# ========== SYSTÈME DE DÉTECTION RAPIDE ==========
# Délégation vers core/utility_ai.py pour centraliser les appels au utility model

from core.utility_ai import (
    check_image_request as _check_image_request,
    check_needs_memory as _check_needs_memory
)


def check_image_request(user_message, model=None):
    """
    Check si l'utilisateur demande de GÉNÉRER/CRÉER une image visuelle.
    Utilise le modèle chat si disponible pour éviter de charger un 2e modèle.
    """
    return _check_image_request(user_message, model=model)


def check_needs_memory(user_message, model=None):
    """
    Check si le message nécessite des infos de la mémoire.
    Utilise le modèle chat si disponible pour éviter de charger un 2e modèle.
    """
    return _check_needs_memory(user_message, model=model)


def generate_image_prompt(user_message, model=None):
    """
    Génère un prompt d'image en anglais à partir de la demande utilisateur.
    Utilise le modèle chat si disponible pour éviter de charger un 2e modèle.
    """
    from core.utility_ai import extract_image_prompt
    return extract_image_prompt(user_message, model=model)


def get_enhanced_system_prompt(base_system_prompt):
    """
    Retourne le system prompt tel quel.
    L'IA de chat ne doit PAS savoir qu'elle peut générer des images.
    La détection d'image se fait séparément.
    """
    return base_system_prompt


# ========== AI-BASED MEMORY EXTRACTION ==========

def extract_memories_ai(messages, existing_memories=None, all_conversations_summary=None, model=None):
    """
    Utilise l'IA pour extraire les informations importantes.
    - messages: historique du chat actuel
    - existing_memories: mémoires déjà connues
    - all_conversations_summary: résumé de toutes les conversations
    """
    if not model:
        model = get_default_model()

    if not is_ollama_running():
        return []

    existing = existing_memories or []

    # Dernier message user
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            last_user_msg = msg.get('content', '')
            break

    if not last_user_msg or len(last_user_msg) < 5:
        return []

    try:
        # Construire le contexte
        context = ""
        if all_conversations_summary:
            context = f"Previous conversations summary: {all_conversations_summary}\n\n"
        if existing:
            context += f"Already known facts: {', '.join(existing[:10])}\n\n"

        extraction_prompt = f"""{context}Message: "{last_user_msg}"

Extrais UNIQUEMENT des faits personnels clairs et explicites:
- Prénom (ex: "Je m'appelle Pierre" -> Name: Pierre)
- Âge (ex: "J'ai 25 ans" -> Age: 25)
- Métier (ex: "Je suis dev" -> Job: Developer)
- Ville (ex: "J'habite Paris" -> Location: Paris)

RÈGLES STRICTES:
- Si le message est une salutation (salut, bonjour, hey) -> NONE
- Si le message est une question -> NONE
- Si aucun fait personnel clair -> NONE
- Jamais extraire le contenu du message lui-même

Réponds NONE ou un seul fait sur une ligne avec "- "

Réponse:"""

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": extraction_prompt,
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": 100,
                    "temperature": 0.2,
                }
            },
            timeout=15
        )

        new_memories = []

        if response.status_code == 200:
            data = response.json()
            result = data.get("response", "").strip()

            if "NONE" in result.upper() and len(result) < 20:
                return []

            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    fact = line[2:].strip()
                    # Vérifications de qualité strictes
                    if not fact or len(fact) < 3 or len(fact) > 50:
                        continue
                    # Doit commencer par un type connu
                    valid_prefixes = ['name:', 'age:', 'job:', 'location:', 'prénom:', 'âge:', 'métier:', 'ville:']
                    is_valid = any(fact.lower().startswith(p) for p in valid_prefixes)
                    if not is_valid:
                        continue
                    # Pas de doublons
                    if fact in existing or fact in new_memories:
                        continue
                    # Pas de garbage
                    garbage_words = ['salut', 'bonjour', 'hey', 'mdr', 'lol', 'wtf', 'bro']
                    if any(g in fact.lower() for g in garbage_words):
                        continue
                    new_memories.append(fact)

            if new_memories:
                print(f"[MEMORY-AI] Extracted: {new_memories}")

        return new_memories[:1]  # Maximum 1 mémoire à la fois

    except Exception as e:
        print(f"[MEMORY-AI] Error: {e}")
        return []


def summarize_conversations(conversations, model=None):
    """
    Crée un résumé de toutes les conversations pour le contexte global.
    conversations: liste de {"title": str, "messages": [...]}
    """
    if not model:
        model = get_default_model()

    if not conversations or not is_ollama_running():
        return ""

    try:
        # Construire un aperçu des conversations
        conv_texts = []
        for conv in conversations[-10:]:  # Max 10 dernières
            title = conv.get("title", "")
            msgs = conv.get("messages", [])[-3:]  # 3 derniers messages
            text = f"Topic: {title}"
            for msg in msgs:
                role = msg.get("role", "")
                content = msg.get("content", "")[:100]  # Tronquer
                if content:
                    text += f"\n  {role}: {content}"
            conv_texts.append(text)

        all_convs = "\n\n".join(conv_texts)

        summary_prompt = f"""Summarize these conversations in 2-3 sentences.
Focus on: user's interests, projects, preferences, recurring topics.

Conversations:
{all_convs}

Summary:"""

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": summary_prompt,
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": 150,
                    "temperature": 0.3,
                }
            },
            timeout=20
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("response", "").strip()

        return ""

    except Exception as e:
        print(f"[SUMMARY] Error: {e}")
        return ""
