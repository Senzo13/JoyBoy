"""
Utility AI - Centralise tous les appels au petit modèle utilitaire.

Ce module gère:
- Image check: Détecter si l'utilisateur demande une image
- Memory check: Détecter si le message a besoin de la mémoire
- Prompt enhancement: Améliorer les prompts pour la génération d'image
"""

from __future__ import annotations  # Python 3.9 compatibility for type hints

import requests
import threading
from config import UTILITY_MODEL, OLLAMA_BASE_URL
from core.ai.text_model_router import call_text_model, select_text_model
from core.infra.packs import get_pack_prompt_assets

# Cache pour le warmup
_utility_model_warmed = False

# Cache pour les enhance prompts (chargés depuis les packs locaux actifs)
_enhance_prompts_cache = None

def _load_enhance_prompt(mode: str) -> str:
    """Charge le system prompt enhance depuis les assets de pack actifs."""
    global _enhance_prompts_cache
    if _enhance_prompts_cache is None:
        _enhance_prompts_cache = get_pack_prompt_assets().get('enhance_system_prompt', {})
    return _enhance_prompts_cache.get(mode, "Translate to English for Stable Diffusion. RESPOND WITH:\nSTYLE: realistic\nPROMPT: [english prompt]")

# Verrou pour éviter les race conditions (déchargement pendant utilisation)
_utility_lock = threading.Lock()
_utility_in_use = False


def is_ollama_running():
    """Vérifie si Ollama est en cours d'exécution"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def is_utility_model_available():
    """Vérifie si le utility model est installé"""
    return select_text_model("utility", auto_pull=False) is not None


def warmup():
    """Préchauffe le utility model au démarrage"""
    global _utility_model_warmed

    if _utility_model_warmed:
        return True

    choice = select_text_model("utility", auto_pull=True)
    if not choice:
        print(f"[UTILITY] {UTILITY_MODEL} non installé")
        return False

    try:
        print(f"[UTILITY] Préchauffage de {choice.name}...")

        response = call_text_model(
            [{"role": "user", "content": "test"}],
            purpose="utility",
            model=choice.name,
            num_predict=1,
            temperature=0.0,
            timeout=60,
        )

        if response is not None:
            _utility_model_warmed = True
            print(f"[UTILITY] {choice.name} prêt (keep_alive: -1)")
            return True

    except Exception as e:
        print(f"[UTILITY] Erreur warmup: {e}")

    return False


def _call_utility(messages: list, num_predict: int = 50, temperature: float = 0.1, timeout: int = 10, model: str = None) -> str | None:
    """
    Appel générique au utility model avec verrou pour éviter les race conditions.

    Args:
        model: Modèle à utiliser (si None, utilise UTILITY_MODEL par défaut)

    Returns:
        La réponse du modèle ou None en cas d'erreur
    """
    global _utility_in_use

    choice = None if model else select_text_model("utility", auto_pull=True)
    use_model = model or (choice.name if choice else None)
    if not use_model:
        print("[UTILITY] ERREUR: aucun modèle utilitaire disponible")
        return None

    if not is_ollama_running():
        print(f"[UTILITY] ERREUR: Ollama non disponible")
        return None

    # Acquérir le verrou avant d'utiliser le modèle
    with _utility_lock:
        _utility_in_use = True
        try:
            raw_response = call_text_model(
                messages,
                purpose="utility",
                model=use_model,
                num_predict=num_predict,
                temperature=temperature,
                timeout=timeout
            )
            if raw_response:
                return raw_response
            print(f"[UTILITY] ERREUR: Réponse vide du modèle")
            return None

        except requests.exceptions.Timeout:
            print(f"[UTILITY] ERREUR: Timeout après {timeout}s - le modèle {use_model} est-il chargé?")
        except requests.exceptions.ConnectionError:
            print(f"[UTILITY] ERREUR: Impossible de se connecter à Ollama ({OLLAMA_BASE_URL})")
        except Exception as e:
            print(f"[UTILITY] ERREUR: {type(e).__name__}: {e}")
        finally:
            _utility_in_use = False

    return None


# translate_to_english() -> moved to core/prompt_ai.py (re-exported at bottom)


def wait_for_utility_free(timeout: float = 30.0) -> bool:
    """
    Attend que le utility model soit libre (plus en cours d'utilisation).
    Utilisé avant de décharger le modèle pour éviter les race conditions.

    Args:
        timeout: Temps max d'attente en secondes

    Returns:
        True si le modèle est libre, False si timeout
    """
    import time
    start = time.time()

    while _utility_in_use:
        if time.time() - start > timeout:
            print(f"[UTILITY] Timeout en attendant que le modèle soit libre")
            return False
        time.sleep(0.1)

    # Acquérir le verrou pour être sûr
    acquired = _utility_lock.acquire(timeout=max(0.1, timeout - (time.time() - start)))
    if acquired:
        _utility_lock.release()
        return True
    return False


# check_image_request(), check_needs_memory(), check_web_search(),
# extract_search_query(), generate_deep_search_queries(), analyze_search_results()
# -> moved to core/detection_ai.py (re-exported at bottom)

# enhance_prompt(), build_full_prompt(), extract_image_prompt(),
# _preprocess_french_prompt(), _strip_image_prefix(), _is_mostly_english()
# -> moved to core/prompt_ai.py (re-exported at bottom)

# [SMART ROUTER] Anciennes fonctions supprimées (remplacées par core/smart_router.py):
# analyze_prompt_for_segmentation, _extract_target_object, _analyze_prompt_with_ai,
# get_creative_mask_prompt, analyze_edit_type


# ============================================================
# TERMINAL MODE - Fonctions pour le mode joyboy run
# ============================================================

def detect_terminal_intent(user_message: str) -> bool:
    """
    Détecte si l'utilisateur veut activer le mode terminal.

    Returns:
        True si c'est une demande de mode terminal
    """
    if not user_message or len(user_message) < 3:
        return False

    msg_lower = user_message.lower().strip()

    # Patterns directs pour activer le mode terminal
    terminal_triggers = [
        'joyboy run', 'joyboy_run', 'mode terminal', 'terminal mode',
        'mode dev', 'dev mode', 'mode code', 'code mode',
        'lance le terminal', 'ouvre le terminal', 'active le terminal'
    ]

    return any(t in msg_lower for t in terminal_triggers)


def select_workspace_ai(user_message: str, workspaces: list) -> dict | None:
    """
    Utilise l'IA pour comprendre quel workspace l'utilisateur veut utiliser.

    Args:
        user_message: Message de l'utilisateur
        workspaces: Liste des workspaces [{name, path}, ...]

    Returns:
        Le workspace sélectionné ou None
    """
    if not workspaces:
        return None

    if len(workspaces) == 1:
        # Un seul workspace, le sélectionner automatiquement
        return workspaces[0]

    # Créer la liste des workspaces pour l'IA
    ws_list = "\n".join([f"- {ws['name']}" for ws in workspaces])

    prompt = f"""Message utilisateur: "{user_message}"

Workspaces disponibles:
{ws_list}

L'utilisateur veut travailler sur quel workspace? Réponds UNIQUEMENT avec le nom exact du workspace (une seule ligne).
Si le message ne mentionne pas de workspace spécifique, réponds "AUCUN".

Réponse:"""

    print(f"[TERMINAL] Sélection workspace pour: \"{user_message[:40]}...\"")

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=30,
        temperature=0.1,
        timeout=8
    )

    if response:
        response_clean = response.strip().lower()

        if response_clean == "aucun" or response_clean == "none":
            return None

        # Chercher une correspondance
        for ws in workspaces:
            if ws['name'].lower() in response_clean or response_clean in ws['name'].lower():
                print(f"[TERMINAL] Workspace sélectionné: {ws['name']}")
                return ws

    return None


def detect_workspace_intent(user_message: str) -> bool:
    """
    Détecte si le message parle de workspace/code/développement.

    Returns:
        True si l'utilisateur semble vouloir travailler sur du code
    """
    if not user_message or len(user_message) < 5:
        return False

    msg_lower = user_message.lower()

    # Les prompts créatifs ("créer un logo", "modifier une image") ne doivent
    # jamais ouvrir le sélecteur projet. Le mode workspace est réservé aux
    # demandes qui parlent clairement de code, repo, fichiers ou commandes.
    creative_keywords = [
        'logo', 'image', 'photo', 'illustration', 'dessin', 'visuel',
        'poster', 'affiche', 'banner', 'bannière', 'icone', 'icône',
        'avatar', 'wallpaper', 'fond d\'écran', 'video', 'vidéo',
        # EN/ES/IT creative terms. Keep these here so international users can
        # ask for visual assets without accidentally opening project mode.
        'picture', 'pic', 'visual', 'drawing', 'sketch', 'painting',
        'flyer', 'ad', 'advertisement', 'icon', 'mockup', 'brand',
        'imagen', 'foto', 'ilustración', 'ilustracion', 'dibujo',
        'cartel', 'anuncio', 'icono', 'marca',
        'immagine', 'foto', 'illustrazione', 'disegno', 'manifesto',
        'icona', 'marchio',
    ]

    strong_workspace_keywords = [
        'workspace', 'repo', 'repository', 'répository', 'depot', 'dépôt',
        'codebase', 'terminal', 'powershell', 'cmd', 'shell',
        'fichier', 'file', 'dossier', 'folder', 'répertoire', 'directory',
        'git', 'commit', 'push', 'pull', 'merge', 'branch', 'branche',
        'npm', 'pip', 'pnpm', 'yarn', 'package.json', 'requirements',
        'pyproject', 'dockerfile', 'compose.yml', 'unittest', 'jest', 'pytest',
        'stacktrace', 'traceback',
        'repositorio', 'carpeta', 'archivo', 'directorio', 'rama',
        'repository', 'cartella', 'file', 'directory', 'ramo',
    ]

    if any(kw in msg_lower for kw in strong_workspace_keywords):
        return True

    if any(kw in msg_lower for kw in creative_keywords):
        return False

    return False


# ============================================================
# VISION MODEL - Utilisé par expand image (pas body analysis)
# ============================================================

# Modèles vision connus (ordre de préférence: qwen2.5vl en premier = léger ~2GB VRAM)
# moondream est EXCLU car il censure le contenu NSFW
VISION_MODELS_PRIORITY = ['qwen2.5vl', 'minicpm-v']
CENSORED_VISION_MODELS = ['moondream']  # Ces modèles refusent le NSFW
DEFAULT_VISION_MODEL = 'qwen2.5vl:3b'


def find_vision_model(auto_install: bool = True) -> str | None:
    """
    Trouve un modèle vision installé dans Ollama.
    Priorité: qwen2.5vl (léger, ~2GB) > llava > autres (moondream ignoré car censuré)

    Si aucun modèle non-censuré trouvé et auto_install=True, télécharge qwen2.5vl:3b.

    Returns:
        Nom du modèle vision ou None si aucun trouvé
    """
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])

            # Chercher dans l'ordre de priorité (modèles non-censurés)
            # TOUJOURS utiliser la variante :3b pour économiser la VRAM (~2GB vs ~10GB pour 7B)
            for keyword in VISION_MODELS_PRIORITY:
                for model in models:
                    name = model.get("name", "").lower()
                    if keyword in name and ":3b" in name:
                        print(f"[VISION] Modèle trouvé: {model.get('name')}")
                        return model.get("name")

            # Si qwen2.5vl existe mais pas en :3b, installer le :3b
            for keyword in VISION_MODELS_PRIORITY:
                for model in models:
                    if keyword in model.get("name", "").lower():
                        # On a une variante non-3b (ex: 7b) → installer le 3b quand même
                        print(f"[VISION] {model.get('name')} trouvé mais trop lourd (9GB+), installation de {DEFAULT_VISION_MODEL}...")
                        if _install_vision_model(DEFAULT_VISION_MODEL):
                            return DEFAULT_VISION_MODEL
                        # PAS de fallback sur version lourde - ça bouffe trop de VRAM
                        print(f"[VISION] Installation {DEFAULT_VISION_MODEL} échouée, vision désactivée")
                        return None

            # Aucun modèle vision NON-CENSURÉ trouvé → installer qwen2.5vl:3b (léger)
            if auto_install:
                has_censored = any(
                    any(c in m.get("name", "").lower() for c in CENSORED_VISION_MODELS)
                    for m in models
                )
                if has_censored:
                    print(f"[VISION] Seul moondream trouvé (censuré NSFW), téléchargement de {DEFAULT_VISION_MODEL}...")
                else:
                    print(f"[VISION] Aucun modèle vision trouvé, téléchargement de {DEFAULT_VISION_MODEL}...")

                if _install_vision_model(DEFAULT_VISION_MODEL):
                    return DEFAULT_VISION_MODEL

    except Exception as e:
        print(f"[VISION] Erreur recherche modèle: {e}")
    return None


def _install_vision_model(model_name: str) -> bool:
    """
    Télécharge un modèle vision via Ollama avec barre de progression.

    Args:
        model_name: Nom du modèle à télécharger (ex: "llava:7b")

    Returns:
        True si succès, False sinon
    """
    import sys

    try:
        print(f"[VISION] ⬇️ Téléchargement de {model_name} (~4.7GB)...")

        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=600
        )

        if response.status_code != 200:
            print(f"[VISION] ❌ Erreur: {response.status_code}")
            return False

        last_percent = -1
        current_layer = ""

        for line in response.iter_lines():
            if line:
                try:
                    import json
                    data = json.loads(line)

                    status = data.get("status", "")
                    completed = data.get("completed", 0)
                    total = data.get("total", 0)

                    # Afficher la progression
                    if total > 0:
                        percent = int((completed / total) * 100)
                        if percent != last_percent:
                            # Barre de progression
                            bar_width = 30
                            filled = int(bar_width * percent / 100)
                            bar = "█" * filled + "░" * (bar_width - filled)
                            size_mb = completed / (1024 * 1024)
                            total_mb = total / (1024 * 1024)
                            sys.stdout.write(f"\r[VISION] [{bar}] {percent}% ({size_mb:.0f}/{total_mb:.0f} MB)")
                            sys.stdout.flush()
                            last_percent = percent
                    elif status:
                        # Status sans progression (ex: "verifying sha256")
                        if status != current_layer:
                            print(f"\n[VISION] {status}")
                            current_layer = status

                except Exception:
                    pass

        print(f"\n[VISION] ✅ {model_name} installé avec succès!")
        return True

    except requests.exceptions.Timeout:
        print(f"\n[VISION] ❌ Timeout - téléchargement trop long")
        return False
    except Exception as e:
        print(f"\n[VISION] ❌ Erreur installation: {e}")
        return False


def _unload_vision_model(model: str):
    """
    Décharge le modèle vision pour libérer la VRAM.
    Important: Le modèle vision est lourd, il faut le décharger après utilisation.
    """
    if not model:
        return

    try:
        # Décharger via Ollama API (keep_alive: 0)
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": [],
                "keep_alive": 0  # Décharge immédiatement
            },
            timeout=10
        )
        if response.status_code == 200:
            print(f"[VISION] Modèle {model} déchargé ✓")
        else:
            print(f"[VISION] Erreur déchargement: {response.status_code}")
    except Exception as e:
        print(f"[VISION] Erreur déchargement: {e}")


def describe_person_for_nudity(image) -> str:
    """
    Utilise Florence-2 pour décrire le corps de la personne.
    Retourne des attributs simples pour enrichir le prompt nudity.

    Returns:
        String d'attributs ou "" si échec
    """
    try:
        from core.florence import describe_person_for_nudity as florence_describe
        print("[BODY] Description via Florence-2...")
        result = florence_describe(image)
        if result:
            print(f"[BODY] Attributs: {result[:60]}...")
        return result
    except Exception as e:
        print(f"[BODY] Erreur Florence: {e}")
        return ""


# ============================================================
# CLEANUP - Nettoyer les modèles Ollama obsolètes
# ============================================================

# Modèles qu'on utilise réellement (à garder)
REQUIRED_OLLAMA_MODELS = [
    "dolphin-phi",        # Utility model (uncensored, enhance prompt, etc.)
    "dolphin-mistral",    # Chat model
]

# Modèles obsolètes (on utilise Florence-2 maintenant)
OBSOLETE_OLLAMA_MODELS = [
    "qwen2.5vl",         # Remplacé par Florence-2
    "llava",             # Remplacé par Florence-2
    "moondream",         # Censuré, jamais utilisé
    "minicpm-v",         # Remplacé par Florence-2
]


def cleanup_ollama_models(dry_run: bool = True) -> dict:
    """
    Supprime les modèles Ollama obsolètes pour libérer de l'espace disque.

    Args:
        dry_run: Si True, affiche ce qui serait supprimé sans supprimer

    Returns:
        Dict avec les modèles supprimés et l'espace libéré
    """
    if not is_ollama_running():
        return {"error": "Ollama n'est pas en cours d'exécution"}

    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code != 200:
            return {"error": "Impossible de récupérer la liste des modèles"}

        models = response.json().get("models", [])

        to_remove = []
        total_size = 0

        for model in models:
            name = model.get("name", "")
            size = model.get("size", 0)

            # Vérifier si c'est un modèle obsolète
            is_obsolete = any(obs in name.lower() for obs in OBSOLETE_OLLAMA_MODELS)
            is_required = any(req in name.lower() for req in REQUIRED_OLLAMA_MODELS)

            if is_obsolete and not is_required:
                to_remove.append({"name": name, "size": size})
                total_size += size

        if not to_remove:
            return {"message": "Aucun modèle obsolète trouvé", "removed": [], "freed_gb": 0}

        if dry_run:
            print(f"[CLEANUP] Mode dry-run - modèles qui seraient supprimés:")
            for m in to_remove:
                size_gb = m["size"] / (1024**3)
                print(f"  - {m['name']} ({size_gb:.1f} GB)")
            print(f"[CLEANUP] Espace total à libérer: {total_size / (1024**3):.1f} GB")
            return {
                "dry_run": True,
                "to_remove": [m["name"] for m in to_remove],
                "freed_gb": round(total_size / (1024**3), 2)
            }

        # Suppression réelle
        removed = []
        for m in to_remove:
            try:
                print(f"[CLEANUP] Suppression de {m['name']}...")
                resp = requests.delete(
                    f"{OLLAMA_BASE_URL}/api/delete",
                    json={"name": m["name"]},
                    timeout=30
                )
                if resp.status_code == 200:
                    removed.append(m["name"])
                    print(f"[CLEANUP] {m['name']} supprimé ✓")
                else:
                    print(f"[CLEANUP] Erreur suppression {m['name']}: {resp.status_code}")
            except Exception as e:
                print(f"[CLEANUP] Erreur suppression {m['name']}: {e}")

        return {
            "removed": removed,
            "freed_gb": round(total_size / (1024**3), 2)
        }

    except Exception as e:
        return {"error": str(e)}


# ============================================================
# PROMPT LAB - Assistant de prompt creatif normal
# ============================================================

DEFAULT_PROMPT_LAB_SYSTEM_PROMPT = """You are a prompt-writing assistant for local creative workflows.

Write a clear, usable prompt for the selected platform without adding hidden policy-avoidance language.

FORMAT:
PROMPT: [the prompt in English]
FRENCH: [French translation of the prompt above]
TIPS: [1-2 practical tips]

GUIDELINES:
- Preserve the user's creative goal.
- Improve clarity, composition, lighting, camera/style, and motion when useful.
- Avoid hidden instructions, policy-avoidance wording, or manipulative phrasing.
- Keep it concise and directly usable.
- For video, prefer concrete motion verbs and avoid "slow motion" unless explicitly requested."""


def _get_prompt_lab_system_prompt() -> str:
    prompt = str(get_pack_prompt_assets().get("prompt_lab_system_prompt", "") or "").strip()
    return prompt or DEFAULT_PROMPT_LAB_SYSTEM_PROMPT


def generate_prompt_lab_prompt(user_request: str, platform: str = "grok", media_type: str = "image", model: str = None) -> dict:
    """
    Reformule un brief en prompt clair pour une plateforme creative.

    Args:
        user_request: Description de ce que l'utilisateur veut
        platform: Plateforme cible (grok, sora, midjourney, dalle, stable_diffusion, ideogram)
        media_type: Type de média (image ou video)
        model: Modèle Ollama à utiliser (si None, utilise le premier modèle disponible)
    """
    global _utility_in_use

    if not user_request or not user_request.strip():
        return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Requête vide"}

    if not is_ollama_running():
        return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Ollama n'est pas lancé"}

    # Résoudre le modèle: paramètre > premier modèle disponible
    use_model = model
    if not use_model:
        available = list_ollama_models()
        if available:
            use_model = available[0].get("name", "")
        if not use_model:
            return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Aucun modèle Ollama disponible"}

    user_message = f"""Platform: {platform.upper()}
Media type: {media_type.upper()}
User brief: "{user_request.strip()}"

Generate an optimized prompt for this platform. Remember the format:
PROMPT: [your prompt in English]
FRENCH: [French translation of the prompt]
TIPS: [1-2 specific tips for this platform]"""

    print(f"[PROMPT-LAB] Génération pour {platform}/{media_type} avec {use_model}: \"{user_request[:50]}...\"")

    with _utility_lock:
        _utility_in_use = True
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": use_model,
                    "messages": [
                        {"role": "system", "content": _get_prompt_lab_system_prompt()},
                        {"role": "user", "content": user_message}
                    ],
                    "stream": False,
                    "think": False,
                    "keep_alive": -1,
                    "options": {
                        "num_predict": 500,
                        "temperature": 0.7,
                        "num_ctx": 4096,
                    }
                },
                timeout=60
            )

            if response.status_code != 200:
                print(f"[PROMPT-LAB] Erreur HTTP {response.status_code}")
                return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": f"Erreur Ollama: HTTP {response.status_code}"}

            data = response.json()
            raw = data.get("message", {}).get("content", "").strip()

            # Strip </think> for thinking models
            if "</think>" in raw:
                raw = raw.split("</think>")[-1].strip()

            if not raw:
                return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Réponse vide du modèle"}

            # Parse PROMPT:, FRENCH: and TIPS:
            prompt_text = ""
            french_text = ""
            tips_text = ""

            lines = raw.split("\n")
            current_section = None
            for line in lines:
                stripped = line.strip()
                upper = stripped.upper()
                if upper.startswith("PROMPT:"):
                    prompt_text = stripped.split(":", 1)[1].strip().strip('"\'')
                    current_section = "prompt"
                elif upper.startswith("FRENCH:") or upper.startswith("FRANÇAIS:") or upper.startswith("FRANCAIS:"):
                    french_text = stripped.split(":", 1)[1].strip().strip('"\'')
                    current_section = "french"
                elif upper.startswith("TIPS:") or upper.startswith("TIP:"):
                    tips_text = stripped.split(":", 1)[1].strip()
                    current_section = "tips"
                elif current_section == "tips" and stripped:
                    tips_text += "\n" + stripped
                elif current_section == "french" and stripped and not upper.startswith("TIP"):
                    french_text += " " + stripped
                elif current_section == "prompt" and stripped and not upper.startswith("TIP") and not upper.startswith("FRENCH") and not upper.startswith("FRANÇAIS"):
                    prompt_text += " " + stripped

            # Fallback: si pas de format trouvé, utiliser toute la réponse
            if not prompt_text:
                prompt_text = raw
                tips_text = ""

            prompt_text = prompt_text.strip()
            french_text = french_text.strip()
            tips_text = tips_text.strip()

            print(f"[PROMPT-LAB] → \"{prompt_text[:80]}...\"")
            return {"prompt": prompt_text, "prompt_fr": french_text, "tips": tips_text, "platform": platform, "error": None}

        except requests.exceptions.Timeout:
            print(f"[PROMPT-LAB] Timeout (60s)")
            return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Timeout — le modèle met trop de temps"}
        except requests.exceptions.ConnectionError:
            print(f"[PROMPT-LAB] Connexion impossible à Ollama")
            return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": "Impossible de se connecter à Ollama"}
        except Exception as e:
            print(f"[PROMPT-LAB] Erreur: {e}")
            return {"prompt": "", "prompt_fr": "", "tips": "", "platform": platform, "error": str(e)}
        finally:
            _utility_in_use = False


def list_ollama_models() -> list:
    """Liste tous les modèles Ollama installés."""
    if not is_ollama_running():
        return []

    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            result = []
            for m in models:
                name = m.get("name", "")
                size_gb = m.get("size", 0) / (1024**3)
                is_obsolete = any(obs in name.lower() for obs in OBSOLETE_OLLAMA_MODELS)
                result.append({
                    "name": name,
                    "size_gb": round(size_gb, 2),
                    "obsolete": is_obsolete
                })
            return result
    except Exception:
        pass
    return []


# ============================================================
# BACKWARD-COMPATIBLE RE-EXPORTS (lazy to avoid circular imports)
# ============================================================
# Functions extracted to dedicated modules but re-exported here
# so existing imports (from core.utility_ai import X) still work.
# Uses __getattr__ to defer imports until actually accessed.

def __getattr__(name):
    """Lazy re-exports from prompt_ai and detection_ai to avoid circular imports."""
    _prompt_names = {
        'enhance_prompt', 'build_full_prompt', 'extract_image_prompt',
        'translate_to_english', 'generate_image_prompt',
    }
    _detection_names = {
        'check_image_request', 'check_needs_memory', 'check_web_search',
        'extract_search_query', 'generate_deep_search_queries', 'analyze_search_results',
    }
    if name in _prompt_names:
        import core.prompt_ai as _pm
        val = getattr(_pm, name, None)
        if val is None and name == 'generate_image_prompt':
            val = _pm.extract_image_prompt
        return val
    if name in _detection_names:
        import core.detection_ai as _dm
        return getattr(_dm, name)
    raise AttributeError(f"module 'core.utility_ai' has no attribute {name!r}")
