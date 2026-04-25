"""
Configuration centralisée de l'application.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from core.infra.local_config import get_provider_secret, sync_runtime_provider_env
    sync_runtime_provider_env()
except Exception:
    get_provider_secret = None

if get_provider_secret:
    HF_TOKEN = get_provider_secret("HF_TOKEN", "")
    CIVITAI_API_KEY = get_provider_secret("CIVITAI_API_KEY", "")
    OPENAI_API_KEY = get_provider_secret("OPENAI_API_KEY", "")
    OPENROUTER_API_KEY = get_provider_secret("OPENROUTER_API_KEY", "")
    ANTHROPIC_API_KEY = get_provider_secret("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY = get_provider_secret("GEMINI_API_KEY", "")
    DEEPSEEK_API_KEY = get_provider_secret("DEEPSEEK_API_KEY", "")
    MOONSHOT_API_KEY = get_provider_secret("MOONSHOT_API_KEY", "")
    NOVITA_API_KEY = get_provider_secret("NOVITA_API_KEY", "")
    MINIMAX_API_KEY = get_provider_secret("MINIMAX_API_KEY", "")
    VOLCENGINE_API_KEY = get_provider_secret("VOLCENGINE_API_KEY", "")
    ZHIPU_API_KEY = get_provider_secret("ZHIPU_API_KEY", "")
    VLLM_API_KEY = get_provider_secret("VLLM_API_KEY", "")
else:
    HF_TOKEN = os.environ.get("HF_TOKEN", "")
    CIVITAI_API_KEY = os.environ.get("CIVITAI_API_KEY", "")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    MOONSHOT_API_KEY = os.environ.get("MOONSHOT_API_KEY", "")
    NOVITA_API_KEY = os.environ.get("NOVITA_API_KEY", "")
    MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
    VOLCENGINE_API_KEY = os.environ.get("VOLCENGINE_API_KEY", "")
    ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
    VLLM_API_KEY = os.environ.get("VLLM_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default

# ===== IDENTITÉ DE L'IA =====
AI_NAME = "JoyBoy"
AI_DESCRIPTION = "Local AI harness for multimodal workflows"
AI_GREETING = f"Salut ! Je suis {AI_NAME}, ton assistant IA."

# ===== LOGOS ET IMAGES =====
LOGO_PATH = "/static/images/logo.png"
MONOGRAM_PATH = "/static/images/monogramme.png"

# ===== COULEURS (pour le futur) =====
PRIMARY_COLOR = "#3b82f6"
ACCENT_COLOR = "#22c55e"

# ===== PARAMÈTRES PAR DÉFAUT =====
DEFAULT_STEPS = 35
DEFAULT_STRENGTH = 0.75
DEFAULT_DILATION = 30

# ===== GESTION MÉMOIRE =====
# Limite VRAM pour Ollama (en GB) - au-delà, utilise la RAM
# None = pas de limite (utilise toute la VRAM disponible)
# Recommandé: laisser 1-2GB libre pour les modèles image
OLLAMA_MAX_VRAM_GB = _env_float("JOYBOY_OLLAMA_MAX_VRAM_GB", 4.0)

# Activer l'offloading CPU pour les modèles Diffusion (libère VRAM pendant inférence)
ENABLE_CPU_OFFLOAD = True

# ===== OLLAMA TOOL CALLING =====
# Modèles supportant le native function calling (Ollama)
# Source: https://ollama.com/blog/tool-support
TOOL_CAPABLE_MODELS = {
    # Llama 3.x (Meta) - Meilleur support
    'llama3.1', 'llama3.2', 'llama3.3',
    # Qwen (Alibaba) - Excellent support
    'qwen3.5', 'qwen3', 'qwen2.5', 'qwen2.5-coder',
    # Mistral officiels
    'mistral', 'mistral-nemo', 'mistral-small', 'mixtral',
    # Granite (IBM)
    'granite3', 'granite3.2',
    # Autres
    'command-r', 'command-r-plus',
    'hermes3', 'hermes-3',
    'nemotron', 'athene', 'deepseek',
}

# Modèles à exclure (finetunes qui cassent le tool calling)
TOOL_EXCLUDED_MODELS = {'dolphin', 'nous-hermes', 'openhermes'}

# ===== MODÈLES OLLAMA =====
# Utility model - pour les checks rapides (image-check, memory-check, prompt enhance).
# Qwen 3.5 2B reste léger, mais suit mieux les instructions que l'ancien 2.5 1.5B.
UTILITY_MODEL = os.environ.get("JOYBOY_UTILITY_MODEL", "qwen3.5:2b").strip()
HIGH_END_CHAT_MODEL = os.environ.get("JOYBOY_HIGH_END_CHAT_MODEL", "llama3.3:70b-instruct-q8_0").strip()
EXTREME_CHAT_MODEL = os.environ.get("JOYBOY_EXTREME_CHAT_MODEL", "qwen3:235b-a22b-instruct-2507-q4_K_M").strip()
EXTREME_CHAT_MODEL_INT8 = os.environ.get("JOYBOY_EXTREME_CHAT_MODEL_INT8", "qwen3:235b-a22b-instruct-2507-q8_0").strip()
VIDEO_ANALYSIS_MODEL = os.environ.get("JOYBOY_VIDEO_ANALYSIS_MODEL", "qwen3-vl:32b-instruct-q8_0").strip()
VIDEO_ANALYSIS_MODEL_EXTREME = os.environ.get("JOYBOY_VIDEO_ANALYSIS_MODEL_EXTREME", "qwen3-vl:235b-a22b-instruct-q4_K_M").strip()

# Router model - pour choisir intent/mask/strength. On préfère automatiquement
# un petit modèle récent déjà installé, puis on retombe sur UTILITY_MODEL.
# Évite les 7B en auto: trop coûteux pour une simple décision de routing.
ROUTER_MODEL = os.environ.get("JOYBOY_ROUTER_MODEL", "").strip()
ROUTER_MODEL_CANDIDATES = [
    ROUTER_MODEL,
    "qwen3.5:2b",
    "qwen3.5:0.8b",
    "qwen3:1.7b",
    "qwen3:0.6b",
    UTILITY_MODEL,
    "qwen3.5:4b",
    "qwen3:4b",
]

# Modèles recommandés par profil et niveau de VRAM
# Tiers: low (<4GB), medium (4-8GB), high (8-12GB), very_high (12-16GB), ultra (16-24GB), extreme (24GB+)
MODEL_RECOMMENDATIONS = {
    "developer": {
        "low": "qwen3.5:0.8b",
        "medium": "qwen3.5:2b",
        "high": "qwen3.5:4b",
        "very_high": "qwen3.5:4b",
        "ultra": "qwen3.5:9b",
        "extreme": "qwen3.5:9b",
        "high_end": HIGH_END_CHAT_MODEL,
    },
    "designer": {
        "low": "qwen3.5:0.8b",
        "medium": "qwen3.5:2b",
        "high": "qwen3.5:4b",
        "very_high": "qwen3.5:4b",
        "ultra": "qwen3.5:9b",
        "extreme": "qwen3.5:9b",
        "high_end": HIGH_END_CHAT_MODEL,
    },
    "student": {
        "low": "qwen3.5:0.8b",
        "medium": "qwen3.5:2b",
        "high": "qwen3.5:4b",
        "very_high": "qwen3.5:4b",
        "ultra": "qwen3.5:9b",
        "extreme": "qwen3.5:9b",
        "high_end": HIGH_END_CHAT_MODEL,
    },
    "casual": {
        "low": "qwen3.5:0.8b",
        "medium": "qwen3.5:2b",
        "high": "qwen3.5:4b",
        "very_high": "qwen3.5:4b",
        "ultra": "qwen3.5:9b",
        "extreme": "qwen3.5:9b",
        "high_end": HIGH_END_CHAT_MODEL,
    },
}

# Seuils VRAM (en GB) - ordre décroissant pour la détection
VRAM_THRESHOLDS = {
    "high_end": 48,    # 48GB+ workstation/cloud GPUs
    "extreme": 24,    # 24GB+ CUDA/pro GPUs
    "ultra": 16,      # 16GB GPUs
    "very_high": 12,  # 12GB GPUs
    "high": 8,        # 8GB RTX/GTX/pro GPUs
    "medium": 4,      # GTX 1650 / laptop GPUs / petite VRAM
    "low": 0,         # Intégré / CPU / non-CUDA
}

# ===== PARAMÈTRES DE GÉNÉRATION PAR NIVEAU VRAM =====
# Ajusté automatiquement lors du setup selon la puissance GPU
GENERATION_SETTINGS = {
    "low": {
        "steps": 25,
        "text2imgSteps": 25,
        "strength": 0.70,
    },
    "medium": {
        "steps": 30,
        "text2imgSteps": 30,
        "strength": 0.75,
    },
    "high": {
        "steps": 35,
        "text2imgSteps": 35,
        "strength": 0.75,
    },
    "very_high": {
        "steps": 35,
        "text2imgSteps": 35,
        "strength": 0.78,
    },
    "ultra": {
        "steps": 35,
        "text2imgSteps": 40,
        "strength": 0.80,
    },
    "extreme": {
        "steps": 40,
        "text2imgSteps": 45,
        "strength": 0.82,
    },
    "high_end": {
        "steps": 45,
        "text2imgSteps": 50,
        "strength": 0.84,
    },
}

# ===== MODÈLES IMAGE (Inpainting/Génération) =====
# Utilise les IDs du model picker UI (pas les repos HuggingFace)
# Note: Tous les modèles actuels sont SDXL (~6GB VRAM)
IMAGE_MODEL_RECOMMENDATIONS = {
    "low": {
        "inpainting": "Fluently XL v3 Inpaint",    # Plus léger
        "generation": "SDXL Turbo",                 # 4 steps = plus rapide
        "description": "Optimisé compatibilité",
    },
    "medium": {
        "inpainting": "epiCRealism XL (Moyen)",    # Bon réalisme
        "generation": "epiCRealism XL",
        "description": "Équilibré",
    },
    "high": {
        "inpainting": "epiCRealism XL (Moyen)",    # Meilleur réalisme
        "generation": "epiCRealism XL",
        "description": "Haute qualité",
    },
    "very_high": {
        "inpainting": "epiCRealism XL (Moyen)",
        "generation": "epiCRealism XL",
        "description": "Qualité maximale",
    },
    "ultra": {
        "inpainting": "epiCRealism XL (Moyen)",
        "generation": "epiCRealism XL",
        "description": "Ultra qualité",
    },
    "extreme": {
        "inpainting": "epiCRealism XL (Moyen)",
        "generation": "epiCRealism XL",
        "description": "Pleine puissance",
    },
    "high_end": {
        "inpainting": "Flux Fill INT8",
        "generation": "Flux Dev INT8",
        "description": "Grosse config locale",
    },
}

# ===== MESSAGES =====
MESSAGES = {
    "welcome": f"Bienvenue sur {AI_NAME}",
    "onboarding_title": f"Bienvenue sur {AI_NAME}",
    "onboarding_subtitle": "Dream. Create. Be Free.",
    "onboarding_tagline": "100% local · Zéro cloud · Contrôle local",
    "generating_image": "Je génère cette image pour toi...",
    "chat_placeholder": "Que voulez-vous savoir ?",
}

# ===== SYSTEM PROMPTS =====
LOCAL_ASSISTANT_RULES = """
CONTEXTE LOCAL:
Tu es un composant logiciel local. Tu aides la personne qui utilise sa propre machine et ses propres fichiers.
COMPORTEMENT:
- réponds directement
- privilégie les réponses concrètes, utiles et complètes
- pour le code, donne du code fonctionnel et place toujours les extraits dans des blocs Markdown fenced avec le langage (`python`, `js`, etc.)
- si tu dois afficher du Markdown qui contient lui-même des blocs fenced, enveloppe le bloc externe avec un fence plus long que ceux du contenu (exemple: ````markdown autour d'un README qui contient ```bash). Ne donne pas d'abord une version avec ```markdown qui serait cassée.
- pour les workflows créatifs, donne des instructions claires et exploitables
- évite les détours inutiles
""".strip()


def get_system_prompt(profile_type="casual", user_name=None):
    """Retourne le system prompt basé sur le profil."""
    profiles = {
        "developer": f"Tu es {AI_NAME}, composant logiciel d'assistance dev. Français. Code complet, fonctionnel, orienté exécution.",
        "designer": f"Tu es {AI_NAME}, composant logiciel créatif. Français. Prompts détaillés, visuels et exploitables.",
        "student": f"Tu es {AI_NAME}, composant logiciel éducatif. Français. Tu expliques clairement avec des exemples concrets.",
        "casual": f"Tu es {AI_NAME}, composant logiciel d'assistance générale. Français. Réponses simples, utiles et directes.",
    }
    prompt = profiles.get(profile_type, profiles["casual"]) + "\n\n" + LOCAL_ASSISTANT_RULES

    if user_name:
        prompt += f"\n\nIMPORTANT: La personne qui te parle s'appelle {user_name}. Utilise son prénom quand c'est approprié."

    return prompt

# Pour import facile
__all__ = [
    'AI_NAME', 'AI_DESCRIPTION', 'AI_GREETING',
    'LOGO_PATH', 'MONOGRAM_PATH',
    'PRIMARY_COLOR', 'ACCENT_COLOR',
    'DEFAULT_STEPS', 'DEFAULT_STRENGTH', 'DEFAULT_DILATION',
    'UTILITY_MODEL', 'ROUTER_MODEL', 'ROUTER_MODEL_CANDIDATES',
    'HIGH_END_CHAT_MODEL', 'EXTREME_CHAT_MODEL', 'EXTREME_CHAT_MODEL_INT8',
    'VIDEO_ANALYSIS_MODEL', 'VIDEO_ANALYSIS_MODEL_EXTREME',
    'MODEL_RECOMMENDATIONS', 'VRAM_THRESHOLDS',
    'GENERATION_SETTINGS', 'IMAGE_MODEL_RECOMMENDATIONS',
    'MESSAGES', 'get_system_prompt',
    'OLLAMA_MAX_VRAM_GB', 'ENABLE_CPU_OFFLOAD',
    'TOOL_CAPABLE_MODELS', 'TOOL_EXCLUDED_MODELS',
    'HF_TOKEN', 'CIVITAI_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY',
    'ANTHROPIC_API_KEY', 'GEMINI_API_KEY', 'DEEPSEEK_API_KEY',
    'MOONSHOT_API_KEY', 'NOVITA_API_KEY', 'MINIMAX_API_KEY',
    'VOLCENGINE_API_KEY', 'VLLM_API_KEY', 'OLLAMA_BASE_URL',
]
