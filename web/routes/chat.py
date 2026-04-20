"""
Blueprint pour les routes chat (chat, chat-stream, get-suggestions, chat-stream/cancel).
"""
from flask import Blueprint, request, jsonify
import os
import threading

chat_bp = Blueprint('chat', __name__)


_CHAT_LOCALES = {"fr", "en", "es", "it"}
_CHAT_COPY = {
    "image_generate_pending": {
        "fr": "Je génère cette image pour toi...",
        "en": "I'm generating this image for you...",
        "es": "Estoy generando esta imagen para ti...",
        "it": "Sto generando questa immagine per te...",
    },
}


def _normalize_chat_locale(locale):
    raw = str(locale or "").split(",", 1)[0].strip().replace("_", "-").lower()
    lang = raw.split("-", 1)[0]
    return lang if lang in _CHAT_LOCALES else "fr"


def _chat_copy(key, locale):
    messages = _CHAT_COPY.get(key, {})
    lang = _normalize_chat_locale(locale)
    return messages.get(lang) or messages.get("fr") or key


# ─── Suggestions lock (thread safety for BLIP analysis) ───

suggestions_lock = threading.Lock()


# ─── Helper: lazy imports from web.app to avoid circular imports ───

def _get_state():
    from web.app import state
    return state


def _base64_to_pil(b64_string):
    from web.app import base64_to_pil
    return base64_to_pil(b64_string)


def _build_image_context(image, message=""):
    """Return a compact text context for image-aware chat turns."""
    if image is None:
        return ""

    description = ""
    try:
        from core.florence import describe_image
        description = describe_image(image, task="<CAPTION>")
        if description:
            print(f"[IMAGE-CONTEXT] Florence: {description[:120]}")
    except Exception as exc:
        print(f"[IMAGE-CONTEXT] Florence unavailable: {exc}")

    food_result = None
    try:
        from core.food_vision import analyze_food_image, format_food_context, should_run_foodextract

        if should_run_foodextract(description, user_message=message):
            print("[FOODEXTRACT] Food/drink context requested")
            food_result = analyze_food_image(image)
            if food_result.success:
                print(
                    f"[FOODEXTRACT] is_food={food_result.is_food} "
                    f"foods={len(food_result.food_items)} drinks={len(food_result.drink_items)}"
                )
            else:
                print(f"[FOODEXTRACT] unavailable: {food_result.error}")
            return "\n\n" + format_food_context(description, food_result)
    except Exception as exc:
        print(f"[FOODEXTRACT] skipped: {exc}")

    if not description:
        return ""

    return (
        "\n\n=== IMAGE CONTEXT ===\n"
        f"Florence caption: {description}\n"
        "Use this image context to answer the user. Do not claim certainty beyond what is visible."
    )


def _set_chat_stream_cancelled(value):
    import web.app as app_module
    app_module.chat_stream_cancelled = value


def _get_chat_stream_cancelled():
    from web.app import chat_stream_cancelled
    return chat_stream_cancelled


# ─── log_chat (used only by chat routes) ───

def log_chat(event_type, message, model=None, extra=None):
    """
    Log formaté pour le debug du chat.
    event_type: 'USER', 'AI', 'CHECK', 'ERROR', 'INFO'
    """
    from config import AI_NAME

    separator = "─" * 50

    if event_type == 'USER':
        print(f"\n┌{separator}")
        print(f"│ 👤 QUESTION DE L'UTILISATEUR")
        print(f"├{separator}")
        for line in message.split('\n'):
            print(f"│ {line}")
        if model:
            print(f"│ 📦 Modèle: {model}")
        print(f"└{separator}")

    elif event_type in [AI_NAME, 'AI', 'ASSISTANT']:
        print(f"\n┌{separator}")
        model_info = f" (via {model})" if model else ""
        print(f"│ 🤖 RÉPONSE DE {AI_NAME.upper()}{model_info}")
        print(f"├{separator}")
        # Afficher la réponse complète
        for line in message.split('\n'):
            print(f"│ {line}")
        print(f"│ 📏 Longueur: {len(message)} caractères")
        print(f"└{separator}")

    elif event_type == 'CHECK':
        print(f"│ ✓ {message}")

    elif event_type == 'ERROR':
        print(f"\n⚠️  ERREUR: {message}")

    elif event_type == 'INFO':
        print(f"ℹ️  {message}")

    if extra:
        for key, value in extra.items():
            print(f"   {key}: {value}")


# ─── Workspace helpers (used only by chat-stream) ───

def check_workspace_switch(message, all_workspaces):
    """
    Vérifie si l'utilisateur veut changer de workspace.
    Ex: "travaille dans mon-projet", "utilise le workspace crock", "ouvre le projet X"
    """
    if not all_workspaces:
        return None

    message_lower = message.lower()

    # Patterns pour détecter une demande de switch
    switch_patterns = [
        'travaille dans', 'travaille sur', 'utilise le workspace', 'utilise le projet',
        'ouvre le projet', 'ouvre le workspace', 'switch to', 'switch vers',
        'va dans', 'passe sur', 'passe dans', 'change pour', 'prends le projet',
        'dans mon workspace', 'dans mon projet'
    ]

    # Vérifier si c'est une demande de switch
    is_switch_request = any(pattern in message_lower for pattern in switch_patterns)

    if not is_switch_request:
        return None

    # Trouver quel workspace est mentionné
    for ws in all_workspaces:
        ws_name_lower = ws.get('name', '').lower()
        if ws_name_lower and ws_name_lower in message_lower:
            print(f"[WORKSPACE] Switch détecté vers: {ws['name']}")
            return ws

    return None


def parse_workspace_action(response, workspace_path):
    """Parse les commandes workspace dans la réponse de l'IA"""
    import re
    from core.workspace_tools import list_files, read_file, search_files, glob_files, write_file, edit_file, delete_file
    from core.terminal_brain import get_brain

    brain = get_brain()

    # === COMMANDES MULTI-LIGNES (prioritaires) ===

    # WRITE_FILE: [WRITE_FILE: path]content[/WRITE_FILE]
    write_match = re.search(r'\[WRITE_FILE:\s*([^\]]+)\](.*?)\[/WRITE_FILE\]', response, re.DOTALL | re.IGNORECASE)
    if write_match:
        path = write_match.group(1).strip()
        content = write_match.group(2)
        # Enlever le premier saut de ligne si présent
        if content.startswith('\n'):
            content = content[1:]

        # BRAIN: Créer un snapshot si le fichier existe déjà
        full_path = os.path.join(workspace_path, path)
        if os.path.exists(full_path):
            try:
                brain._create_snapshot(full_path, path)

                # Valider l'action d'écriture
                is_valid, message = brain._validate_write(full_path, content)
                if not is_valid:
                    print(f"[BRAIN] Action WRITE bloquée: {message}")
                    return {'action': 'write_file', 'arg': path, 'result': {'success': False, 'error': message}}
            except Exception as e:
                print(f"[BRAIN] Erreur lecture snapshot: {e}")

        print(f"[WORKSPACE] WRITE_FILE: {path} ({len(content)} caractères)")
        result = write_file(workspace_path, path, content)
        brain._log_action('write_file', path, result.get('success', False))
        return {'action': 'write_file', 'arg': path, 'result': result}

    # EDIT_FILE: [EDIT_FILE: path]<<<OLD>>>old<<<NEW>>>new[/EDIT_FILE]
    edit_match = re.search(r'\[EDIT_FILE:\s*([^\]]+)\](.*?)\[/EDIT_FILE\]', response, re.DOTALL | re.IGNORECASE)
    if edit_match:
        path = edit_match.group(1).strip()
        content = edit_match.group(2)

        # BRAIN: Créer un snapshot avant édition
        full_path = os.path.join(workspace_path, path)
        if os.path.exists(full_path):
            try:
                brain._create_snapshot(full_path, path)
            except Exception as e:
                print(f"[BRAIN] Erreur lecture snapshot: {e}")

        # Parser OLD et NEW
        old_new_match = re.search(r'<<<OLD>>>(.*?)<<<NEW>>>(.*)', content, re.DOTALL)
        if old_new_match:
            old_text = old_new_match.group(1)
            new_text = old_new_match.group(2)
            # Nettoyer les sauts de ligne en début/fin
            if old_text.startswith('\n'):
                old_text = old_text[1:]
            if old_text.endswith('\n'):
                old_text = old_text[:-1]
            if new_text.startswith('\n'):
                new_text = new_text[1:]
            if new_text.endswith('\n'):
                new_text = new_text[:-1]

            print(f"[WORKSPACE] EDIT_FILE: {path}")
            print(f"  OLD: {old_text[:50]}..." if len(old_text) > 50 else f"  OLD: {old_text}")
            print(f"  NEW: {new_text[:50]}..." if len(new_text) > 50 else f"  NEW: {new_text}")
            result = edit_file(workspace_path, path, old_text, new_text)
            brain._log_action('edit_file', path, result.get('success', False))
            return {'action': 'edit_file', 'arg': path, 'result': result}
        else:
            return {'action': 'edit_file', 'arg': path, 'result': {'success': False, 'error': 'Format invalide: utilise <<<OLD>>>...<<<NEW>>>...'}}

    # DELETE_FILE simple
    delete_match = re.search(r'\[DELETE_FILE:\s*([^\]]+)\]', response, re.IGNORECASE)
    if delete_match:
        path = delete_match.group(1).strip()
        print(f"[WORKSPACE] DELETE_FILE: {path}")
        result = delete_file(workspace_path, path)
        return {'action': 'delete_file', 'arg': path, 'result': result}

    # === COMMANDES SIMPLES (lecture) ===
    patterns = [
        (r'\[LIST_FILES:\s*([^\]]*)\]', 'list_files'),
        (r'\[READ_FILE:\s*([^\]]+)\]', 'read_file'),
        (r'\[SEARCH:\s*([^\]]+)\]', 'search'),
        (r'\[GLOB:\s*([^\]]+)\]', 'glob'),
    ]

    for pattern, action in patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            arg = match.group(1).strip()
            print(f"[WORKSPACE] Action détectée: {action}({arg})")

            # Exécuter l'action
            if action == 'list_files':
                result = list_files(workspace_path, arg)
            elif action == 'read_file':
                result = read_file(workspace_path, arg)
            elif action == 'search':
                result = search_files(workspace_path, arg)
            elif action == 'glob':
                result = glob_files(workspace_path, arg)
            else:
                result = {'success': False, 'error': 'Action inconnue'}

            return {
                'action': action,
                'arg': arg,
                'result': result
            }

    return None


# ─── Routes ───

@chat_bp.route('/chat-stream/cancel', methods=['POST'])
def cancel_chat_stream():
    """Annule le streaming chat en cours"""
    _set_chat_stream_cancelled(True)
    print(f"[CANCEL] Chat stream cancelled by user")
    return jsonify({'success': True})


@chat_bp.route('/get-suggestions', methods=['POST'])
def get_suggestions():
    """Analyse l'image et retourne des suggestions de prompts contextuelles"""
    from core.infra.packs import is_adult_runtime_available
    from core.suggestions import get_suggestions_for_description

    # Verrou pour éviter les appels concurrents à BLIP
    if not suggestions_lock.acquire(blocking=False):
        return jsonify({'error': 'Analyse déjà en cours'}), 429

    try:
        data = request.json
        image_b64 = data.get('image')
        locale = data.get('locale') or request.headers.get('Accept-Language', 'fr')

        if not image_b64:
            return jsonify({'error': 'Image requise'}), 400

        # Valider que le base64 est assez long pour être une vraie image
        raw_b64 = image_b64.split(',')[1] if ',' in image_b64 else image_b64
        if len(raw_b64) < 100:
            return jsonify({'error': 'Image base64 invalide'}), 400

        print(f"\n{'─'*50}")
        print("🎯 SUGGESTIONS | Analyse de l'image...")

        # Analyser l'image avec Florence-2
        image = _base64_to_pil(image_b64)

        from core.florence import describe_image
        description = describe_image(image, task="<CAPTION>")
        # Florence reste en RAM (~500MB CPU) — rechargement coûteux

        print(f"   Description: {description}")

        food_analysis = None
        try:
            from core.food_vision import analyze_food_image, enrich_food_description, should_run_foodextract

            if should_run_foodextract(description, user_message=data.get('message') or data.get('prompt')):
                print("   FoodExtract: analyse food/drink...")
                food_result = analyze_food_image(image)
                food_analysis = food_result.to_dict()
                if food_result.success and food_result.is_food:
                    description = enrich_food_description(description, food_result)
                    print(f"   FoodExtract: {food_analysis}")
                elif food_result.error:
                    print(f"   FoodExtract: indisponible ({food_result.error})")
        except Exception as exc:
            print(f"   FoodExtract: skip ({exc})")

        suggestion_payload = get_suggestions_for_description(
            description,
            adult_runtime_enabled=is_adult_runtime_available(),
            locale=locale,
        )
        suggestions = suggestion_payload["suggestions"]
        content_type = suggestion_payload["content_type"]
        scene_type = suggestion_payload.get("scene_type", "generic")
        clothing_state = suggestion_payload.get("clothing_state", "unknown")
        suggestion_mode = suggestion_payload["suggestion_mode"]

        if content_type == "woman":
            if suggestion_mode == "adult_local":
                print("   Type détecté: Femme -> suggestions locales avancées")
            else:
                print("   Type détecté: Femme -> suggestions style")
        elif content_type == "man":
            print("   Type détecté: Homme -> suggestions mode")
        elif content_type == "person":
            print("   Type détecté: Personne -> suggestions contextuelles")
        else:
            print("   Type détecté: Autre -> suggestions styles")

        print(f"{'─'*50}\n")

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'contentType': content_type,
            'sceneType': scene_type,
            'clothingState': clothing_state,
            'description': description,
            'foodAnalysis': food_analysis,
        })

    except Exception as e:
        print(f"❌ [SUGGESTIONS] Erreur: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        suggestions_lock.release()


@chat_bp.route('/chat', methods=['POST'])
def chat():
    """Chat conversationnel avec Ollama (rapide et local)"""
    from config import AI_NAME
    from core import ollama_service

    try:
        data = request.json
        message = data.get('message', '')
        image_b64 = data.get('image')
        history = data.get('history', [])
        memories = data.get('memories', [])
        chat_model = data.get('chatModel', 'qwen3.5:2b')
        reasoning_effort = data.get('reasoningEffort')
        profile = data.get('profile', {})
        all_conversations = data.get('allConversations', [])
        locale = data.get('locale') or request.headers.get('Accept-Language', 'fr')
        from core.agent_runtime import CloudModelError, chat_with_cloud_model, is_cloud_model_name
        use_cloud_model = is_cloud_model_name(chat_model)
        routing_model = chat_model

        if not message:
            return jsonify({'error': 'Message requis'}), 400

        state = _get_state()

        # Log la question de l'utilisateur
        log_chat('USER', message, model=chat_model)

        image = None
        # Sauvegarder l'image si fournie
        if image_b64:
            image = _base64_to_pil(image_b64)
            state.last_user_image = image

        image_analysis_request = False
        if image is not None:
            try:
                from core.food_vision import is_image_analysis_request
                image_analysis_request = is_image_analysis_request(message)
            except Exception:
                image_analysis_request = False

        # ===== ÉTAPE 1: Vérifier si c'est une demande d'IMAGE AVANT tout =====
        if not image_analysis_request and ollama_service.check_image_request(message, model=routing_model):
            image_prompt = ollama_service.generate_image_prompt(message, model=routing_model)
            if not image_prompt:
                image_prompt = message
                print(f"[CHAT] Fallback: utilisation du message original comme prompt")
            response_text = _chat_copy("image_generate_pending", locale)
            log_chat(AI_NAME, response_text, model=chat_model)

            return jsonify({
                'success': True,
                'response': response_text,
                'intent': 'image_generate_pending',
                'gen_prompt': image_prompt,
                'new_memories': []
            })

        # ===== ÉTAPE 1.5: Vérifier si c'est une demande de RECHERCHE WEB =====
        from core.utility_ai import check_web_search, generate_deep_search_queries
        from core.web_search import deep_search

        is_web_search_request, search_query, search_mode = check_web_search(message, model=routing_model)
        web_context = ""

        if is_web_search_request and search_query:
            print(f"[WEB-SEARCH] Recherche détectée: '{search_query}' (mode: {search_mode})")

            # Générer plusieurs requêtes pour recherche approfondie
            search_queries = generate_deep_search_queries(message, search_query, model=routing_model)
            print(f"[WEB-SEARCH] Recherche profonde: {len(search_queries)} requêtes")

            all_pages_content = []
            all_results = []

            for i, query in enumerate(search_queries, 1):
                print(f"[WEB-SEARCH] [{i}/{len(search_queries)}] '{query[:40]}...'")

                # Recherche profonde: recherche + lecture des pages
                deep_results = deep_search(
                    query,
                    num_results=5,
                    num_pages_to_read=2  # Lire 2 pages par requête
                )

                if deep_results.get('success'):
                    # Collecter les résultats
                    for r in deep_results.get('results', []):
                        if not any(existing.get('url') == r.get('url') for existing in all_results):
                            all_results.append(r)

                    # Collecter le contenu des pages lues
                    for page in deep_results.get('pages_content', []):
                        if not any(p.get('url') == page.get('url') for p in all_pages_content):
                            all_pages_content.append(page)

            if all_pages_content or all_results:
                print(f"[WEB-SEARCH] Total: {len(all_results)} résultats, {len(all_pages_content)} pages lues")

                # Construire le contexte avec le contenu des pages
                web_context = f"=== RECHERCHE WEB APPROFONDIE: {search_query} ===\n\n"

                # Contenu des pages lues (le plus important)
                if all_pages_content:
                    web_context += "## CONTENU DES PAGES CONSULTÉES:\n\n"
                    for i, page in enumerate(all_pages_content[:5], 1):  # Max 5 pages
                        web_context += f"### Source {i}: {page.get('title', 'Sans titre')}\n"
                        web_context += f"URL: {page.get('url', '')}\n\n"
                        # Limiter le contenu par page
                        content = page.get('content', '')[:2500]
                        web_context += f"{content}\n\n"
                        web_context += "-" * 50 + "\n\n"

                # Résumé des autres résultats
                other_results = [r for r in all_results if r.get('url') not in [p.get('url') for p in all_pages_content]]
                if other_results:
                    web_context += "\n## AUTRES SOURCES TROUVÉES:\n"
                    for r in other_results[:5]:
                        web_context += f"- {r.get('title', '')}: {r.get('url', '')}\n"

                source = search_mode if search_mode != "normal" else "web"
                print(f"[WEB-SEARCH] Contexte: {len(web_context)} chars, {len(all_pages_content)} pages lues")
            else:
                print(f"[WEB-SEARCH] Aucun résultat trouvé")

        # ===== ÉTAPE 2: Pas une demande d'image -> Chat normal =====

        # Construire les messages pour Ollama
        chat_messages = []

        # System prompt - profile-aware local assistant baseline
        if profile.get('systemPrompt'):
            base_system = profile['systemPrompt']
        else:
            from config import get_system_prompt

            profile_type = str(profile.get('type', 'casual') or 'casual')
            profile_name = str(profile.get('name', '') or '').strip() or None
            base_system = get_system_prompt(profile_type, profile_name)

        system_content = ollama_service.get_enhanced_system_prompt(base_system)

        # Ajouter les résultats de recherche web si disponibles
        if web_context:
            system_content += f"\n\n=== RÉSULTATS DE RECHERCHE WEB ===\n{web_context}\n\nIMPORTANT: Utilise ces informations pour répondre à l'utilisateur. La recherche a été faite en anglais pour plus de résultats, mais tu DOIS répondre EN FRANÇAIS. Donne une réponse complète et détaillée basée sur le contenu des pages consultées."

        if image is not None:
            image_context = _build_image_context(image, message)
            if image_context:
                system_content += image_context

        chat_messages.append({"role": "system", "content": system_content})

        # L'historique contient déjà le message actuel (ajouté côté frontend)
        recent_history = history[-10:] if len(history) > 10 else history
        for msg in recent_history:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

        # DEBUG: Afficher ce qu'on envoie au modèle
        print("\n" + "=" * 60)
        print(f"[CHAT DEBUG] Modèle: {chat_model} | Messages: {len(chat_messages)}")
        print("=" * 60)
        for i, msg in enumerate(chat_messages):
            role = msg['role'].upper()
            content = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
            print(f"\n[{i+1}] {role}:")
            print(f"{content}")
        print("\n" + "=" * 60 + "\n")

        if use_cloud_model:
            try:
                cloud_response = chat_with_cloud_model(
                    chat_model,
                    messages=chat_messages,
                    tools=[],
                    max_tokens=4096,
                    temperature=0.5,
                    reasoning_effort=reasoning_effort,
                )
            except CloudModelError as exc:
                return jsonify({'success': False, 'error': str(exc)}), 500

            message_payload = cloud_response.get("message") or {}
            response = str(message_payload.get("content") or "")
            log_chat(AI_NAME, response, model=chat_model)
            return jsonify({
                'success': True,
                'response': response,
                'intent': 'chat',
                'new_memories': [],
                'token_stats': {
                    'prompt_tokens': int(cloud_response.get('prompt_eval_count') or 0),
                    'completion_tokens': int(cloud_response.get('eval_count') or 0),
                    'total_tokens': int(cloud_response.get('prompt_eval_count') or 0) + int(cloud_response.get('eval_count') or 0),
                },
            })

        # Appel à Ollama
        response, success = ollama_service.chat(chat_messages, model=chat_model, max_tokens=-1)

        if not success:
            if not ollama_service.is_ollama_installed():
                return jsonify({
                    'success': False,
                    'error': 'Ollama non installé. Va sur https://ollama.ai/download'
                }), 500
            elif not ollama_service.is_ollama_running():
                if ollama_service.start_ollama():
                    response, success = ollama_service.chat(chat_messages, model=chat_model, max_tokens=-1)
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Impossible de démarrer Ollama'
                    }), 500

        if not success:
            log_chat('ERROR', response)
            return jsonify({'success': False, 'error': response}), 500

        # Log la réponse de l'IA
        log_chat(AI_NAME, response, model=chat_model)

        return jsonify({
            'success': True,
            'response': response,
            'intent': 'chat',
            'new_memories': []
        })

    except Exception as e:
        print(f"Error in chat: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@chat_bp.route('/chat-stream', methods=['POST'])
def chat_stream():
    """Chat avec streaming - réponse en temps réel"""
    from flask import Response, stream_with_context
    from config import AI_NAME, get_system_prompt
    from core import ollama_service
    import json

    _set_chat_stream_cancelled(False)  # Reset au début de la requête (pas dans le générateur)

    data = request.json
    message = data.get('message', '')
    image_b64 = data.get('image')
    history = data.get('history', [])
    memories = data.get('memories', [])
    chat_model = data.get('chatModel', 'qwen3.5:2b')
    reasoning_effort = data.get('reasoningEffort')
    profile = data.get('profile', {})
    all_conversations = data.get('allConversations', [])
    workspace = data.get('workspace')  # {name, path} ou null
    context_size = data.get('contextSize', 4096)
    locale = data.get('locale') or request.headers.get('Accept-Language', 'fr')
    from core.agent_runtime import CloudModelError, chat_with_cloud_model, is_cloud_model_name
    use_cloud_model = is_cloud_model_name(chat_model)
    routing_model = chat_model

    if not message:
        return jsonify({'error': 'Message requis'}), 400

    # Récupérer tous les workspaces disponibles
    all_workspaces = data.get('allWorkspaces', [])

    # Log la question de l'utilisateur
    log_chat('USER', message, model=chat_model)

    image = None
    image_analysis_request = False
    if image_b64:
        try:
            image = _base64_to_pil(image_b64)
            _get_state().last_user_image = image
            from core.food_vision import is_image_analysis_request
            image_analysis_request = is_image_analysis_request(message)
        except Exception as exc:
            print(f"[IMAGE-CONTEXT] Invalid image payload: {exc}")
            image = None
            image_analysis_request = False

    # ===== ÉTAPE 0: Vérifier si l'utilisateur veut changer de workspace =====
    workspace_switch = check_workspace_switch(message, all_workspaces)
    if workspace_switch:
        def generate_switch_response():
            response_text = f"OK, je travaille maintenant dans le workspace **{workspace_switch['name']}**. Qu'est-ce que tu veux que je fasse ?"
            log_chat(AI_NAME, response_text, model=chat_model)
            yield f"data: {json.dumps({'content': response_text})}\n\n"
            yield f"data: {json.dumps({'done': True, 'new_memories': [], 'switch_workspace': workspace_switch})}\n\n"

        return Response(
            stream_with_context(generate_switch_response()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )

    # ===== ÉTAPE 1: Vérifier si c'est une demande d'IMAGE AVANT tout =====
    is_image_request = False if image_analysis_request else ollama_service.check_image_request(message, model=routing_model)

    # Bail out si annulé pendant IMAGE-CHECK
    if _get_chat_stream_cancelled():
        print(f"[CANCEL] Chat stream cancelled during pre-processing")
        return Response("data: " + json.dumps({'done': True, 'cancelled': True, 'new_memories': []}) + "\n\n",
                        mimetype='text/event-stream')

    if is_image_request:
        # C'est une demande d'image -> Réponse rapide + génération
        image_prompt = ollama_service.generate_image_prompt(message, model=routing_model)

        # Fallback: si l'extraction a échoué, utiliser le message original
        if not image_prompt:
            image_prompt = message
            print(f"[CHAT-STREAM] Fallback: utilisation du message original comme prompt")

        # ModelManager.load_for_task() déchargera Ollama automatiquement quand le frontend lancera /generate
        print(f"[CHAT-STREAM] Demande d'image détectée -> prompt: \"{image_prompt[:60]}...\"")

        def generate_image_response():
            # Réponse courte
            response_text = _chat_copy("image_generate_pending", locale)
            log_chat(AI_NAME, response_text, model=chat_model)

            yield f"data: {json.dumps({'content': response_text})}\n\n"
            yield f"data: {json.dumps({'done': True, 'new_memories': [], 'generate_image': True, 'image_prompt': image_prompt})}\n\n"

        return Response(
            stream_with_context(generate_image_response()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )

    # ===== ÉTAPE 1.5: Décharger les modèles image pour libérer la VRAM pour le LLM =====
    try:
        from core.models.manager import ModelManager
        mgr = ModelManager.get()
        if mgr._inpaint_pipe is not None:
            print(f"[CHAT] Déchargement modèles image (libération VRAM pour LLM)...")
            mgr._unload_diffusers()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            print(f"[CHAT] VRAM libérée pour le LLM")
    except Exception as _e:
        print(f"[CHAT] Skip unload: {_e}")

    # ===== ÉTAPE 1.6: Vérifier si c'est une demande de RECHERCHE WEB =====
    print(f"[WEB-CHECK] Vérification recherche web pour: '{message[:50]}...'")
    from core.utility_ai import check_web_search, generate_deep_search_queries
    from core.web_search import deep_search

    # Utiliser le modèle chat pour la traduction (évite la censure du utility model)
    is_web_search_request, search_query, search_mode = check_web_search(message, model=routing_model)
    print(f"[WEB-CHECK] Résultat: is_search={is_web_search_request}, query='{search_query}', mode={search_mode}")

    # ===== ÉTAPE 2: Chat normal (recherche web faite DANS le générateur pour feedback temps réel) =====

    def generate():
        # Vérifier si déjà annulé avant de commencer
        if _get_chat_stream_cancelled():
            print(f"[CANCEL] Chat stream cancelled before generation started")
            yield f"data: {json.dumps({'done': True, 'cancelled': True, 'new_memories': []})}\n\n"
            return

        # --- Recherche web (dans le générateur pour envoyer le statut en temps réel) ---
        web_context = ""

        if is_web_search_request and search_query:
            print(f"[WEB-SEARCH] Recherche détectée: '{search_query}' (mode: {search_mode})")

            # Générer plusieurs requêtes pour recherche approfondie
            search_queries = generate_deep_search_queries(message, search_query, model=routing_model)
            total_queries = len(search_queries)
            print(f"[WEB-SEARCH] Recherche profonde: {total_queries} requêtes")

            # Envoyer le statut initial avec le total
            yield f"data: {json.dumps({'status': 'searching', 'query': search_query, 'current': 0, 'total': total_queries})}\n\n"

            all_pages_content = []
            all_results = []

            for i, query in enumerate(search_queries, 1):
                print(f"[WEB-SEARCH] [{i}/{total_queries}] '{query[:40]}...'")

                # Envoyer la progression pour chaque requête
                yield f"data: {json.dumps({'status': 'searching', 'query': query, 'current': i, 'total': total_queries})}\n\n"

                deep_results = deep_search(
                    query,
                    num_results=5,
                    num_pages_to_read=2
                )

                if deep_results.get('success'):
                    for r in deep_results.get('results', []):
                        if not any(existing.get('url') == r.get('url') for existing in all_results):
                            all_results.append(r)
                    for page in deep_results.get('pages_content', []):
                        if not any(p.get('url') == page.get('url') for p in all_pages_content):
                            all_pages_content.append(page)

            if all_pages_content or all_results:
                print(f"[WEB-SEARCH] Total: {len(all_results)} résultats, {len(all_pages_content)} pages lues")

                # Construire le contexte web
                web_context = "\n\n=== RÉSULTATS DE RECHERCHE WEB ===\n"
                for page in all_pages_content[:5]:
                    web_context += f"\n--- {page.get('title', 'Sans titre')} ---\n"
                    web_context += f"URL: {page.get('url', '')}\n"
                    content = page.get('content', '')[:2000]
                    web_context += f"{content}\n"

                if not all_pages_content:
                    for r in all_results[:10]:
                        web_context += f"\n- {r.get('title', '')}: {r.get('snippet', '')}\n  URL: {r.get('url', '')}\n"

                web_context += "\n=== FIN DES RÉSULTATS ===\n"
                web_context += "Utilise ces informations pour répondre à l'utilisateur.\n"

            # Signaler la fin de la recherche
            yield f"data: {json.dumps({'status': 'search_done', 'results_count': len(all_results)})}\n\n"

        # --- Construire les messages ---
        chat_messages = []

        # System prompt
        if profile.get('systemPrompt'):
            base_system = profile['systemPrompt']
        else:
            profile_type = str(profile.get('type', 'casual') or 'casual')
            profile_name = str(profile.get('name', '') or '').strip() or None
            base_system = get_system_prompt(profile_type, profile_name)

        system_content = ollama_service.get_enhanced_system_prompt(base_system)

        # Ajouter les infos workspace si actif
        if workspace and workspace.get('path'):
            from core.workspace_tools import is_model_tool_capable, get_workspace_summary

            workspace_path = workspace['path']
            workspace_name = workspace.get('name', os.path.basename(workspace_path))

            # Obtenir un résumé du workspace
            summary = get_workspace_summary(workspace_path)

            # Ajouter le contexte workspace au system prompt
            workspace_info = f"""

You have access to workspace "{workspace_name}" ({workspace_path}).
Structure: {summary.get('total_files', 0)} files, folders: {', '.join(summary.get('root_dirs', [])[:10])}
Important root files: {', '.join(summary.get('root_files', []))}

=== READ COMMANDS ===
- [LIST_FILES: path] - List files, for example [LIST_FILES: src]
- [READ_FILE: path] - Read a file, for example [READ_FILE: src/main.py]
- [SEARCH: pattern] - Search in files, for example [SEARCH: function login]
- [GLOB: pattern] - Find files by pattern, for example [GLOB: **/*.py]

=== WRITE COMMANDS ===
- [WRITE_FILE: path]
complete file content
[/WRITE_FILE]

- [EDIT_FILE: path]
<<<OLD>>>
exact text to replace
<<<NEW>>>
replacement text
[/EDIT_FILE]

- [DELETE_FILE: path] - Delete a file.

=== IMPORTANT RULES ===
- Always read a file with READ_FILE before editing it with EDIT_FILE.
- For EDIT_FILE, OLD must be an exact copy from the file, including whitespace and indentation.
- One workspace command per message. Wait for the tool result before the next one.
- Do not claim that a file/project was created or modified unless a workspace command actually succeeded.
- Answer in the user's language, but follow these workspace guardrails exactly.
"""
            system_content += workspace_info
            print(f"[WORKSPACE] Contexte ajouté pour: {workspace_name}")

        # Ajouter le contexte web si recherche effectuée
        if web_context:
            system_content += web_context
            print(f"[WEB-SEARCH] Contexte web ajouté au prompt")

        if image is not None:
            image_context = _build_image_context(image, message)
            if image_context:
                system_content += image_context

        chat_messages.append({"role": "system", "content": system_content})

        # L'historique contient déjà le message actuel (ajouté côté frontend)
        recent_history = history[-10:] if len(history) > 10 else history
        for msg in recent_history:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

        # DEBUG: Afficher ce qu'on envoie au modèle
        print("\n" + "=" * 60)
        print(f"[STREAM DEBUG] Modèle: {chat_model} | Contexte: {context_size} | Messages: {len(chat_messages)}")
        if workspace:
            print(f"[STREAM DEBUG] Workspace: {workspace.get('name', 'N/A')}")
        print("=" * 60)
        for i, msg in enumerate(chat_messages):
            role = msg['role'].upper()
            content_preview = msg['content'][:300] + "..." if len(msg['content']) > 300 else msg['content']
            print(f"\n[{i+1}] {role}:")
            print(f"{content_preview}")
        print("\n" + "=" * 60 + "\n")

        # --- Streaming LLM ---
        full_response = ""
        if use_cloud_model:
            try:
                cloud_response = chat_with_cloud_model(
                    chat_model,
                    messages=chat_messages,
                    tools=[],
                    max_tokens=4096,
                    temperature=0.5,
                    reasoning_effort=reasoning_effort,
                )
            except CloudModelError as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                return

            message_payload = cloud_response.get("message") or {}
            full_response = str(message_payload.get("content") or "")
            if full_response:
                yield f"data: {json.dumps({'content': full_response})}\n\n"

            log_chat(AI_NAME, full_response, model=chat_model)
            done_data = {
                'done': True,
                'new_memories': [],
                'token_stats': {
                    'prompt_tokens': int(cloud_response.get('prompt_eval_count') or 0),
                    'completion_tokens': int(cloud_response.get('eval_count') or 0),
                    'total_tokens': int(cloud_response.get('prompt_eval_count') or 0) + int(cloud_response.get('eval_count') or 0),
                    'context_size': context_size,
                },
            }
            yield f"data: {json.dumps(done_data)}\n\n"
            return

        for chunk in ollama_service.chat_stream_with_context(chat_messages, model=chat_model, max_tokens=-1, context_size=context_size):
            # Vérifier annulation
            if _get_chat_stream_cancelled():
                print(f"[CANCEL] Chat stream interrupted by user after {len(full_response)} chars")
                yield f"data: {json.dumps({'done': True, 'cancelled': True, 'new_memories': []})}\n\n"
                return

            if "error" in chunk:
                yield f"data: {json.dumps({'error': chunk['error']})}\n\n"
                return
            elif "content" in chunk:
                full_response += chunk["content"]
                yield f"data: {json.dumps({'content': chunk['content']})}\n\n"
            elif chunk.get("done"):
                # Log la réponse complète
                log_chat(AI_NAME, full_response, model=chat_model)

                # Vérifier si l'IA demande une action workspace
                workspace_action = None
                if workspace and workspace.get('path'):
                    workspace_action = parse_workspace_action(full_response, workspace['path'])

                # Envoyer done avec l'action workspace et les stats de tokens
                done_data = {'done': True, 'new_memories': []}
                if workspace_action:
                    done_data['workspace_action'] = workspace_action

                # Inclure les stats de tokens si disponibles
                if chunk.get('token_stats'):
                    done_data['token_stats'] = chunk['token_stats']

                yield f"data: {json.dumps(done_data)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
