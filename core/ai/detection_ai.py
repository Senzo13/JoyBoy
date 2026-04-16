"""
Detection AI - AI-powered detection functions for user intent classification.

Extracted from utility_ai.py for separation of concerns.

Contains:
- check_image_request() - Detect if user is asking to generate an image
- check_needs_memory() - Detect if message needs personal memory context
- check_web_search() - Detect if user wants a web search
- extract_search_query() - Extract search query from user message
- generate_deep_search_queries() - Generate multiple search queries for deep research
- analyze_search_results() - Analyze web search results and summarize in French
"""

from __future__ import annotations

from core.utility_ai import _call_utility
from config import OLLAMA_BASE_URL


# ============================================================
# IMAGE CHECK - Detecter si l'utilisateur demande une image
# ============================================================

def check_image_request(user_message: str, model: str = None) -> bool:
    """
    Determine si le message demande de GENERER une image.

    Args:
        model: Modèle chat à utiliser (évite de charger un 2e modèle)

    Returns:
        True si c'est une demande d'image, False sinon
    """
    if not user_message or len(user_message) < 3:
        return False

    msg_lower = user_message.lower().strip()

    # === PRE-FILTRES (sans appel AI) ===

    # Demandes d'image EVIDENTES -> True immediat (pas besoin d'AI)
    image_triggers = [
        'g\u00e9n\u00e8re', 'genere', 'generer', 'g\u00e9n\u00e9rer',
        'g\u00e9n\u00e8re moi', 'genere moi', 'g\u00e9n\u00e8re-moi', 'genere-moi',
        'imagine', 'imagine moi', 'imagine-moi', 'imaginer',
        'dessine', 'dessiner', 'dessine moi', 'dessine-moi',
        'cr\u00e9\u00e9 une image', 'cree une image', 'cr\u00e9e une image',
        'cr\u00e9er une image', 'creer une image',
        'fais une image', 'fais moi une image', 'fais-moi une image',
        'montre moi', 'montre-moi', 'show me',
        'image de ', 'image d\'', 'une image de', 'une photo de',
        'generate', 'draw ', 'create an image', 'make an image',
        'generate an image', 'generate a photo', 'picture of',
    ]
    if any(t in msg_lower for t in image_triggers):
        print(f"[IMAGE-CHECK] Match direct (keyword trigger)")
        return True

    # Salutations -> pas d'image
    greetings = ['salut', 'hello', 'hi', 'hey', 'coucou', 'bonjour', 'bonsoir', 'yo', 'wesh', 'slt', 'cc']
    if len(msg_lower) < 20 and any(msg_lower.startswith(g) for g in greetings):
        print(f"[IMAGE-CHECK] Skip (salutation)")
        return False

    # Code -> pas d'image
    code_keywords = ['code', 'fonction', 'script', 'programme', 'class', 'api', 'bug', 'erreur', 'debug',
                     'variable', 'array', 'loop', 'boucle', 'if ', 'else', 'return', 'import', 'export',
                     'html', 'css', 'javascript', 'python', 'java', 'php', 'sql', 'react', 'vue', 'node',
                     'phaser', 'unity', 'godot', 'flutter', 'swift', 'kotlin', 'rust', 'go ', 'c++', 'typescript']
    if any(k in msg_lower for k in code_keywords):
        print(f"[IMAGE-CHECK] Skip (code)")
        return False

    # Recherche web -> pas d'image
    web_keywords = ['cherche sur internet', 'cherche sur le web', 'recherche sur internet',
                    'recherche sur le web', 'sur internet', 'sur le web', 'google',
                    'en ligne', 'actualité', 'news']
    if any(k in msg_lower for k in web_keywords):
        print(f"[IMAGE-CHECK] Skip (recherche web)")
        return False

    # Questions generales -> pas d'image
    questions = ['comment ', 'pourquoi ', 'qu\'est', "c'est quoi", 'explique', 'aide moi', 'peux-tu',
                 'comment faire', 'how to', 'what is', 'explain', 'help me']
    if any(q in msg_lower for q in questions):
        print(f"[IMAGE-CHECK] Skip (question)")
        return False

    # Mots descriptifs seuls (sans verbe d'action) -> pas une demande d'image
    # "nude", "sexy", "blonde" etc. ne sont PAS des demandes de generation
    words = msg_lower.split()
    action_verbs = {'g\u00e9n\u00e8re', 'genere', 'imagine', 'dessine',
                    'cr\u00e9e', 'cree', 'fais', 'montre', 'generate', 'draw', 'create', 'make', 'show'}
    has_action = any(w.rstrip('-') in action_verbs or w.lstrip('-') in action_verbs for w in words)
    if len(words) <= 3 and not has_action:
        print(f"[IMAGE-CHECK] Skip (descriptif sans verbe d'action: '{msg_lower}')")
        return False

    # === APPEL AI pour decider ===
    prompt = f"""Message: "{user_message}"

Est-ce que l'utilisateur demande EXPLICITEMENT de CR\u00c9ER/G\u00c9N\u00c9RER une image?
Il FAUT un verbe d'action (g\u00e9n\u00e8re, cr\u00e9e, dessine, fais, imagine, montre-moi, generate, draw, create...).
Un simple mot descriptif (nude, sexy, blonde, etc.) sans verbe N'EST PAS une demande d'image.
R\u00e9ponds UNIQUEMENT: OUI ou NON"""

    print(f"[IMAGE-CHECK] Analyse AI pour: \"{user_message[:50]}\"")

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=20,
        temperature=0.1,
        timeout=8,
        model=model
    )

    if response:
        result_lower = response.lower()
        is_yes = result_lower.startswith("oui") or result_lower.startswith("yes")
        status = "OUI" if is_yes else "NON"
        print(f"[IMAGE-CHECK] R\u00e9ponse: {status} ({response[:30]})")
        return is_yes

    print(f"[IMAGE-CHECK] Utility model indisponible")
    return False


# ============================================================
# MEMORY CHECK - Detecter si le message a besoin de la memoire
# ============================================================

def check_needs_memory(user_message: str, model: str = None) -> bool:
    """
    Determine si le message a besoin d'infos personnelles (nom, preferences).

    Args:
        model: Modèle chat à utiliser (évite de charger un 2e modèle)

    Returns:
        True si besoin de memoire, False sinon
    """
    if not user_message or len(user_message) < 3:
        return False

    prompt = f"""Message: "{user_message}"

Ce message a-t-il besoin d'infos personnelles (nom, pr\u00e9f\u00e9rences)?
R\u00e9ponds: OUI ou NON"""

    print(f"[MEMORY-CHECK] V\u00e9rification pour: \"{user_message[:30]}...\"")

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=20,
        temperature=0.0,
        timeout=5,
        model=model
    )

    if response:
        result_lower = response.lower()
        is_yes = "oui" in result_lower or "yes" in result_lower
        status = "OUI" if is_yes else "NON"
        print(f"[MEMORY-CHECK] R\u00e9ponse: {status}")
        return is_yes

    return False


# ============================================================
# WEB SEARCH CHECK - Detecter si l'utilisateur veut une recherche web
# ============================================================

def check_web_search(user_message: str, model: str = None) -> tuple[bool, str, str]:
    """
    Determine si le message demande une recherche sur internet.
    Utilise l'IA pour comprendre meme si mal ecrit.

    Args:
        user_message: Le message de l'utilisateur
        model: Modele chat a utiliser pour la traduction (evite la censure du utility model)

    Returns:
        tuple(is_web_search, query, mode)
        - mode: 'normal'
    """
    if not user_message or len(user_message) < 5:
        return False, "", "normal"

    msg_lower = user_message.lower().strip()

    # === RECHERCHE WEB UNIQUEMENT SUR DEMANDE EXPLICITE ===
    # L'utilisateur DOIT demander explicitement une recherche web
    explicit_web_keywords = [
        'cherche sur internet', 'cherche sur le web', 'recherche sur internet',
        'recherche sur le web', 'cherche en ligne', 'recherche en ligne',
        'google', 'sur internet', 'sur le web',
        'search online', 'search the web', 'web search',
    ]

    if not any(kw in msg_lower for kw in explicit_web_keywords):
        return False, "", "normal"

    # === MODE UNIQUE: recherche web publique ===
    mode = "normal"

    # === EXTRAIRE LA QUERY AVEC L'IA ===
    # Utiliser le modele chat si fourni (evite la censure du utility model)
    query = _extract_search_query_ai(user_message, model=model)

    print(f"[WEB-CHECK] Recherche confirm\u00e9e: \"{query[:50]}\" (mode: {mode})")
    return True, query, mode


def _extract_search_query_ai(user_message: str, model: str = None) -> str:
    """
    Utilise l'IA pour extraire la requete de recherche du message
    ET LA TRADUIRE EN ANGLAIS pour de meilleurs resultats.

    Args:
        user_message: Le message de l'utilisateur
        model: Modele a utiliser (si None, utilise le utility model)
    """
    prompt = f"""Message: "{user_message}"

1. Extrais ce que l'utilisateur veut chercher sur internet
2. TRADUIS la requ\u00eate EN ANGLAIS (les recherches en anglais donnent plus de r\u00e9sultats)
3. Enl\u00e8ve les mots comme "cherche", "sur internet", "google" - garde juste le sujet

R\u00e9ponds UNIQUEMENT avec la requ\u00eate en anglais, rien d'autre.

Exemples:
- "cherche sur internet comment faire des cr\u00eapes" -> how to make crepes
- "google moi les derni\u00e8res news sur l'IA" -> latest AI news
- "je veux savoir c'est quoi le bitcoin" -> what is bitcoin
- "cherche sur internet les meilleurs réglages SVD" -> best SVD settings

Requ\u00eate en anglais:"""

    # Utiliser le modele specifie ou le utility model
    if model:
        # Appel direct a Ollama avec le modele chat
        try:
            import requests
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 50, "temperature": 0.1}
                },
                timeout=10
            )
            if response.status_code == 200:
                response = response.json().get("response", "").strip()
            else:
                response = None
        except Exception:
            response = None
    else:
        response = _call_utility(
            messages=[{"role": "user", "content": prompt}],
            num_predict=50,
            temperature=0.1,
            timeout=5
        )

    if response:
        # Nettoyer la reponse
        query = response.strip().strip('"\'.-:')
        # Enlever les prefixes courants que l'IA pourrait ajouter
        prefixes = ['requ\u00eate:', 'query:', 'recherche:', 'search:', 'requ\u00eate en anglais:']
        for p in prefixes:
            if query.lower().startswith(p):
                query = query[len(p):].strip()
        print(f"[SEARCH-QUERY] Traduit en anglais: '{query}'")
        return query

    # Fallback: nettoyer manuellement (sans traduction)
    msg_lower = user_message.lower()
    prefixes_to_remove = [
        'cherche sur internet', 'cherche sur le web', 'recherche sur internet',
        'google', 'google moi', 'trouve moi', 'search',
        'cherche', 'recherche', 'trouve',
    ]
    query = user_message
    for prefix in prefixes_to_remove:
        if msg_lower.startswith(prefix):
            query = user_message[len(prefix):].strip()
            break

    return query.strip('"\'.:!? ')


def generate_deep_search_queries(user_message: str, initial_query: str) -> list:
    """
    Genere plusieurs requetes de recherche EN ANGLAIS pour une recherche approfondie.
    L'IA analyse la demande et genere des variations pour couvrir tous les angles.

    Returns:
        Liste de requetes de recherche en anglais (max 5)
    """
    prompt = f"""User request (French): "{user_message}"
Initial query: "{initial_query}"

Generate 3-5 different ENGLISH search queries to deeply research this topic:
1. Main query
2. Different angles
3. Synonyms/alternative terms
4. Related questions

IMPORTANT:
- Write queries IN ENGLISH (better search results)
- One query per line
- No numbering, no explanations

Queries:"""

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=150,
        temperature=0.3,
        timeout=8
    )

    queries = [initial_query]  # Toujours inclure la requete initiale

    if response:
        lines = response.strip().split('\n')
        for line in lines:
            line = line.strip().strip('-\u2022*0123456789.):')
            if line and len(line) > 3 and line.lower() != initial_query.lower():
                queries.append(line)

    # Limiter a 5 requetes max
    return queries[:5]


def analyze_search_results(user_question: str, search_results: list) -> str:
    """
    Analyse les resultats de recherche et extrait les informations pertinentes.
    Repond EN FRANCAIS meme si les resultats sont en anglais.

    Args:
        user_question: La question originale de l'utilisateur
        search_results: Liste de resultats [{title, url, snippet}]

    Returns:
        Resume des informations pertinentes EN FRANCAIS
    """
    if not search_results:
        return "Aucun r\u00e9sultat trouv\u00e9."

    # Construire le contexte des resultats
    results_text = ""
    for i, r in enumerate(search_results[:10], 1):
        results_text += f"\n{i}. {r.get('title', 'Sans titre')}\n"
        results_text += f"   {r.get('snippet', '')}\n"

    prompt = f"""Question de l'utilisateur (fran\u00e7ais): "{user_question}"

R\u00e9sultats de recherche web (peuvent \u00eatre en anglais):
{results_text}

INSTRUCTIONS:
1. Analyse ces r\u00e9sultats
2. Extrais les informations pertinentes pour r\u00e9pondre \u00e0 la question
3. R\u00c9PONDS EN FRAN\u00c7AIS (m\u00eame si les r\u00e9sultats sont en anglais)
4. Donne un r\u00e9sum\u00e9 clair et complet

Analyse en fran\u00e7ais:"""

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=300,
        temperature=0.2,
        timeout=15
    )

    return response if response else "Impossible d'analyser les r\u00e9sultats."


def extract_search_query(user_message: str) -> str:
    """
    Extrait la requete de recherche d'un message utilisateur.
    Utilise l'IA si necessaire pour extraire la query.
    """
    # D'abord essayer extraction simple
    is_search, query, _mode = check_web_search(user_message)
    if query:
        return query

    # Si pas de query claire, utiliser l'IA
    prompt = f"""Message: "{user_message}"

Extrais la requ\u00eate de recherche de ce message.
R\u00e9ponds UNIQUEMENT avec la requ\u00eate, rien d'autre.
Exemple: "cherche python tutorial" -> python tutorial"""

    response = _call_utility(
        messages=[{"role": "user", "content": prompt}],
        num_predict=50,
        temperature=0.1,
        timeout=5
    )

    if response:
        return response.strip().strip('"\'')

    return user_message  # Fallback: utiliser le message entier
