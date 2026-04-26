// ===== STATE - Variables globales et constantes =====

// App Config (loaded from API)
let APP_CONFIG = {
    name: 'JoyBoy',
    description: 'Harness IA local multimodal',
    logo: '/static/images/logo.png',
    monogram: '/static/images/monogramme.png'
};

// Images
let currentImage = null;
let currentVideoSource = null;
let originalImage = null;
let modifiedImage = null;
let pendingImage = null;
const MAX_FACE_REF_IMAGES = 5;
let faceRefImages = [];  // Base64 refs visage pour text2img (1-5 images)
let faceRefImage = null;  // Compat legacy: première image de faceRefImages
let styleRefImage = null;  // Base64 de l'image de style pour text2img (IP-Adapter CLIP)

function getFaceRefImages() {
    if (Array.isArray(faceRefImages)) {
        return faceRefImages.filter(Boolean).slice(0, MAX_FACE_REF_IMAGES);
    }
    return faceRefImage ? [faceRefImage] : [];
}

function syncFaceRefLegacy() {
    const refs = getFaceRefImages();
    faceRefImages = refs;
    faceRefImage = refs[0] || null;
}

function getFaceRefPayload() {
    return getFaceRefImages();
}

// Generation
let currentController = null;
let isGenerating = false;
let currentGenerationId = null;  // Pour tracking des générations d'images
let currentGenerationMode = null;  // 'image' ou 'chat' - pour savoir quel modèle recharger après stop
let currentGenerationChatId = null;  // Chat où la génération a été lancée (pour sauvegarder au bon endroit)

// ===== TERMINAL MODE (joyboy run) =====
// Variables d'état pour le mode terminal - logique dans terminal.js
let terminalMode = false;           // Mode terminal actif
let terminalWorkspace = null;       // Workspace actif {name, path}
let terminalInterrupted = false;    // Interruption demandée
let terminalWorking = false;        // IA en train de travailler (auto-continue)
let terminalVisionModel = null;     // Modèle vision actif (llava, moondream, etc.)

// ===== VISION MODELS =====
// Modèles Ollama qui supportent les images en entrée
// Utilisés en mode terminal pour analyser des images
const VISION_MODELS = ['llava', 'moondream', 'bakllava', 'llava-llama3', 'llava-phi3', 'minicpm-v'];
const DEFAULT_VISION_MODEL = 'moondream:1.8b';  // Le plus léger (~1.7GB)

// ===== TOOL-CAPABLE MODELS =====
// Modèles qui supportent le tool calling (mode terminal)
// Qwen 3.5 2B suffit largement pour les outils sans voler la VRAM aux images.
const DEFAULT_TERMINAL_MODEL = 'qwen3.5:2b';

// Centralized tool-capable keywords (used by ui.js, settings.js, terminal.js)
const TOOL_CAPABLE_KEYWORDS = [
    'llama3.1', 'llama3.2', 'llama3.3',
    'qwen2.5', 'qwen3',
    'mistral-nemo', 'mistral-small', 'mixtral',
    'granite3', 'granite3.2',
    'command-r', 'hermes3', 'hermes-3', 'nemotron', 'athene',
    'deepseek', 'deepseek-v2', 'deepseek-v3'
];

// Modèles exclus: finetunes incompatibles ou modèles "thinking" trop lents
const TOOL_EXCLUDED_KEYWORDS = [
    'dolphin', 'nous-hermes', 'openhermes',
    'deepseek-r1', 'r1'
];

const TOOL_SMALL_MODEL_ALLOWLIST = ['qwen3.5:2b'];

// Tailles trop petites pour le tool calling (hallucinent au lieu d'exécuter).
// Exception volontaire: qwen3.5:2b est notre modèle terminal léger recommandé.
const TOOL_TOO_SMALL_SIZES = [':0.5b', ':0.8b', ':1b', ':1.5b', ':2b'];

/**
 * Vérifie si un modèle supporte le tool calling
 * @param {string} modelName - Nom du modèle
 * @returns {boolean}
 */
function isToolCapableModel(modelName) {
    const name = modelName.toLowerCase();
    if (TOOL_EXCLUDED_KEYWORDS.some(ex => name.includes(ex))) return false;
    return TOOL_CAPABLE_KEYWORDS.some(kw => name.includes(kw));
}

/**
 * Vérifie si un modèle est assez gros pour le tool calling
 * @param {string} modelId - ID du modèle (ex: "qwen3.5:2b")
 * @returns {boolean}
 */
function isToolCapableModelStrict(modelId) {
    const lower = modelId.toLowerCase();
    if (TOOL_EXCLUDED_KEYWORDS.some(ex => lower.includes(ex))) return false;
    const explicitlyAllowedSmallModel = TOOL_SMALL_MODEL_ALLOWLIST.some(model => lower.includes(model));
    if (!explicitlyAllowedSmallModel && TOOL_TOO_SMALL_SIZES.some(size => lower.includes(size))) return false;
    return TOOL_CAPABLE_KEYWORDS.some(kw => lower.includes(kw));
}

// ===== TERMINAL DOWNLOAD STATE =====
// Persiste l'état du téléchargement pour survivre aux F5
let terminalDownloadState = {
    isDownloading: false,
    model: null,
    progress: 0,
    status: '',
    startedAt: null
};

/**
 * Sauvegarde l'état du téléchargement terminal dans localStorage
 */
function saveTerminalDownloadState() {
    localStorage.setItem('terminalDownloadState', JSON.stringify(terminalDownloadState));
}

/**
 * Charge l'état du téléchargement terminal depuis localStorage
 */
function loadTerminalDownloadState() {
    try {
        const saved = localStorage.getItem('terminalDownloadState');
        if (saved) {
            const state = JSON.parse(saved);
            // Vérifier si le téléchargement est toujours en cours (moins de 30 min)
            if (state.isDownloading && state.startedAt) {
                const elapsed = Date.now() - state.startedAt;
                if (elapsed < 30 * 60 * 1000) { // 30 minutes max
                    terminalDownloadState = state;
                    return true;
                }
            }
        }
    } catch (e) {
        console.error('[TERMINAL] Erreur chargement état download:', e);
    }
    return false;
}

/**
 * Réinitialise l'état du téléchargement
 */
function clearTerminalDownloadState() {
    terminalDownloadState = {
        isDownloading: false,
        model: null,
        progress: 0,
        status: '',
        startedAt: null
    };
    localStorage.removeItem('terminalDownloadState');
}

// ===== SIMPLE QUEUE =====
// Queue simple séquentielle côté navigateur. Les longues générations sont
// maintenant suivies par le runtime job store persistant.
let globalQueue = [];
let activeQueueItem = null;

// escapeHtml() moved to utils.js (loaded before state.js)

function queueT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function normalizeQueueImageSrc(image = '') {
    const value = String(image || '').trim();
    if (!value) return '';
    if (value.startsWith('data:') || value.startsWith('http://') || value.startsWith('https://') || value.startsWith('/')) {
        return value;
    }
    return `data:image/png;base64,${value}`;
}

function getActiveQueueComposerTarget() {
    const chatView = document.getElementById('chat-view');
    const chatVisible = chatView && chatView.style.display !== 'none';
    const chatInputBar = document.querySelector('.chat-input-bar');
    const homeInputBar = document.querySelector('#home-view .input-bar');
    const anchor = chatVisible ? chatInputBar : homeInputBar?.parentElement;
    const input = chatVisible
        ? document.getElementById('chat-prompt')
        : document.getElementById('prompt-input');
    return {
        chatVisible,
        anchor,
        input: input || document.getElementById('chat-prompt') || document.getElementById('prompt-input'),
        homeInputBar,
    };
}

function refreshQueueComposerLayout() {
    requestAnimationFrame(() => {
        const chatInputBar = document.querySelector('.chat-input-bar');
        const nextHeight = Math.max(80, Math.ceil(chatInputBar?.offsetHeight || 80));
        document.documentElement.style.setProperty('--chat-input-h', `${nextHeight}px`);
        if (typeof updateChatPadding === 'function') updateChatPadding();
    });
}

function isTerminalQueueItem(item = {}) {
    return String(item.mode || '').toLowerCase() === 'terminal'
        || String(item.type || '').toLowerCase() === 'terminal';
}

function canOrientQueueItem(item = {}) {
    return isTerminalQueueItem(item)
        && !normalizeQueueImageSrc(item.options?.image || '')
        && typeof terminalMode !== 'undefined'
        && terminalMode
        && typeof terminalWorking !== 'undefined'
        && terminalWorking;
}

function renderQueueForCurrentChat() {
    // Nettoyer les éléments existants
    const oldContainer = document.getElementById('prompt-queue');
    if (oldContainer) oldContainer.remove();
    const oldBubble = document.getElementById('queue-bubble');
    if (oldBubble) oldBubble.remove();

    const pending = globalQueue.filter(item => item.status === 'pending');
    if (pending.length === 0) {
        refreshQueueComposerLayout();
        return;
    }

    const { chatVisible, anchor, homeInputBar } = getActiveQueueComposerTarget();
    if (!anchor) return;

    const container = document.createElement('div');
    container.id = 'prompt-queue';
    container.className = 'prompt-queue';
    container.dataset.count = String(pending.length);
    const visibleItems = pending.slice(0, 5);
    const remaining = Math.max(0, pending.length - visibleItems.length);
    container.innerHTML = `
        <div class="queue-items" role="list" aria-label="${escapeHtml(queueT('composer.queueLabel', 'File d’attente'))}">
            ${visibleItems.map((item, index) => {
                const imageSrc = normalizeQueueImageSrc(item.options?.image || item.options?.videoSource?.thumbnail || '');
                const text = String(item.prompt || '').trim();
                const orientAction = canOrientQueueItem(item)
                    ? `<button class="queue-btn queue-orient" type="button" onclick="orientQueueItem('${item.id}')" title="${escapeHtml(queueT('composer.queueOrientTitle', 'Envoyer comme orientation au travail en cours'))}">
                            <i data-lucide="corner-down-left"></i>
                            <span>${escapeHtml(queueT('composer.queueOrient', 'Orienter'))}</span>
                        </button>`
                    : '';
                return `
                <div class="queue-item${imageSrc ? ' has-image' : ''}" data-id="${item.id}" role="listitem">
                    ${imageSrc ? `<img class="queue-thumb" src="${escapeHtml(imageSrc)}" alt="">` : `<span class="queue-index">${index + 1}</span>`}
                    <span class="queue-text">${escapeHtml(text.substring(0, 96))}${text.length > 96 ? '...' : ''}</span>
                    <div class="queue-actions">
                        ${orientAction}
                        <button class="queue-btn queue-remove" type="button" onclick="removeFromQueue('${item.id}')" title="${escapeHtml(queueT('composer.queueRemoveTitle', 'Retirer'))}">
                            <i data-lucide="trash-2"></i>
                        </button>
                        <button class="queue-btn queue-clear" type="button" onclick="clearQueue()" title="${escapeHtml(queueT('composer.queueClearTitle', 'Vider la file'))}">
                            <i data-lucide="ellipsis"></i>
                        </button>
                    </div>
                </div>`;
            }).join('')}
            ${remaining ? `<div class="queue-more-count">${escapeHtml(queueT('composer.queueMore', '+{count} en attente', { count: remaining }))}</div>` : ''}
        </div>
    `;

    if (chatVisible) {
        anchor.insertBefore(container, anchor.firstChild);
    } else if (homeInputBar?.parentElement) {
        homeInputBar.parentElement.insertBefore(container, homeInputBar);
    }

    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [container] });
    refreshQueueComposerLayout();
}

async function orientQueueItem(id) {
    const item = globalQueue.find(entry => entry.id === id);
    if (!item) return;
    if (canOrientQueueItem(item) && typeof sendTerminalGuidance === 'function') {
        const sent = await sendTerminalGuidance(item.prompt || '');
        if (sent) {
            removeFromQueue(id);
        }
        return;
    }
    const { input } = getActiveQueueComposerTarget();
    if (input) {
        input.value = item.prompt || '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
    }
    if (item.options?.image) {
        currentImage = item.options.image;
        if (typeof updateImagePreviews === 'function') updateImagePreviews();
    }
}

function addToQueue(prompt, mode = 'chat', options = {}) {
    const id = 'q_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
    const normalizedMode = String(mode || 'chat').toLowerCase();
    const type = normalizedMode === 'video' || options.videoSource
        ? 'video'
        : ((options.image || currentImage) ? 'image' : (normalizedMode === 'terminal' ? 'terminal' : 'text'));
    globalQueue.push({
        id, prompt, type, mode: normalizedMode,
        options: { ...options, image: options.image || currentImage },
        status: 'pending',
        addedAt: Date.now()
    });
    renderQueueForCurrentChat();
    return id;
}

function removeFromQueue(id) {
    globalQueue = globalQueue.filter(item => item.id !== id);
    renderQueueForCurrentChat();
}

function clearQueue() {
    globalQueue = [];
    activeQueueItem = null;
    renderQueueForCurrentChat();
}

async function processNextInQueue() {
    if (isGenerating) return;
    const next = globalQueue.find(item => item.status === 'pending');
    if (!next) return;

    next.status = 'processing';
    activeQueueItem = next;
    renderQueueForCurrentChat();

    console.log(`[QUEUE] Traitement: ${next.type} - "${next.prompt.substring(0, 30)}..."`);

    try {
        if (next.type === 'video' && typeof generateVideoFromImageWithPrompt === 'function') {
            executingFromQueue = true;
            if (next.options?.image) {
                await generateVideoFromImageWithPrompt(next.options.image, next.prompt || '');
            } else if (next.options?.videoSource?.videoSessionId && typeof runVideoContinuation === 'function') {
                currentVideoSource = { ...next.options.videoSource };
                if (typeof updateVideoSourcePreviews === 'function') updateVideoSourcePreviews();
                await runVideoContinuation({
                    prompt: next.prompt || '',
                    videoSessionId: currentVideoSource.videoSessionId,
                });
            } else if (typeof generateVideoFromText === 'function') {
                await generateVideoFromText(next.prompt || '');
            }
        } else if ((next.type === 'image' || next.type === 'inpainting') && typeof generate === 'function') {
            // Image: mettre l'image + prompt dans le home input, appeler generate()
            executingFromQueue = true;
            if (next.options?.image) {
                currentImage = next.options.image;
                if (typeof updateImagePreviews === 'function') updateImagePreviews();
            }
            const input = document.getElementById('prompt-input');
            if (input) input.value = next.prompt;
            await generate();
        } else if (typeof continueChat === 'function') {
            // Texte: mettre le prompt dans le chat input, appeler continueChat()
            executingFromQueueChat = true;
            const input = document.getElementById('chat-prompt') || document.getElementById('prompt-input');
            if (input) input.value = next.prompt;
            await continueChat();
        }
    } catch (e) {
        console.error('[QUEUE] Erreur traitement:', e);
    }

    // Cleanup après que la génération est terminée
    executingFromQueue = false;
    executingFromQueueChat = false;
    next.status = 'completed';
    activeQueueItem = null;
    globalQueue = globalQueue.filter(i => i.status !== 'completed');
    renderQueueForCurrentChat();

    // Traiter le prochain item après un court délai
    setTimeout(() => processNextInQueue(), 200);
}

// Token Tracking
let tokenStats = {
    sessionTotal: 0,        // Total tokens utilisés cette session
    lastRequestTokens: 0,   // Tokens de la dernière requête
    promptTokens: 0,        // Tokens du prompt (input)
    completionTokens: 0,    // Tokens de la réponse (output)
    maxContextSize: 4096    // Taille max du contexte (depuis userSettings.contextSize)
};

// Defaults — synced from config.py via /api/config, fallback values below
let DEFAULT_DILATION = 30;
let DEFAULT_STRENGTH = 0.75;
let DEFAULT_STEPS = 60;
// Segmentation gérée automatiquement par Smart Router côté backend

// Model — now managed by SettingsContext (backward compat getter)
Object.defineProperty(window, 'lastModel', {
    get() { return Settings.get('lastModel'); },
    set(v) { Settings.set('lastModel', v); },
    configurable: true
});

// Presets
let presets = { 1: "", 2: "", 3: "" };
let editingPresetNum = null;

// Conversations - durable multi-chat state in IndexedDB
// privacyMode — now managed by SettingsContext (backward compat getter)
Object.defineProperty(window, 'privacyMode', {
    get() { return Settings.get('privacyMode'); },
    set(v) { Settings.set('privacyMode', v); },
    configurable: true
});
let cacheDB = null;
const DB_NAME = 'JoyBoyDB';
const DB_VERSION = 7;  // v7: durable projects + conversation grouping
const MEMORIES_STORE = 'memories';
const SETTINGS_STORE = 'settings';

// Conversation state - durable per-chat history in IndexedDB
let currentChatId = null;
let chatHistory = [];
let userMemories = [];

let MAX_MEMORIES = 100;
const CLEANUP_KEEP = 50;

// User settings — managed by SettingsContext (settings-context.js)
// `window.userSettings` is a Proxy defined in settings-context.js
// All reads/writes (userSettings.steps, userSettings.steps = 35) work transparently.

// User profile (for onboarding)
let userProfile = {
    hasCompletedOnboarding: false,
    type: 'casual',  // developer, designer, student, casual
    name: '',
    customPrompt: ''
};

// Profile types and their system prompts
const LOCAL_ASSISTANT_RULES = `
CONTEXTE LOCAL:
Tu es un composant logiciel local. Tu aides la personne qui utilise sa propre machine et ses propres fichiers.
COMPORTEMENT:
- réponds directement
- évite les refus génériques qui ne correspondent pas à un usage local légitime
- privilégie les réponses concrètes, utiles et complètes
- pour le code, donne du code fonctionnel
- pour les workflows créatifs, donne des prompts clairs et exploitables
- évite les détours moralisants et les disclaimers inutiles`;

function getProfilePrompt(type) {
    const name = APP_CONFIG.name;
    const prompts = {
        developer: `Tu es ${name}, composant logiciel d'assistance dev. Français. Code complet, fonctionnel, orienté exécution.\n${LOCAL_ASSISTANT_RULES}`,
        designer: `Tu es ${name}, composant logiciel créatif. Français. Prompts détaillés, visuels et directement exploitables.\n${LOCAL_ASSISTANT_RULES}`,
        student: `Tu es ${name}, composant logiciel éducatif. Français. Tu expliques clairement avec des exemples concrets.\n${LOCAL_ASSISTANT_RULES}`,
        casual: `Tu es ${name}, composant logiciel d'assistance générale. Français. Réponses simples, utiles et directes.\n${LOCAL_ASSISTANT_RULES}`
    };
    return prompts[type] || prompts.casual;
}

// For backwards compatibility
const PROFILE_PROMPTS = {
    get developer() { return getProfilePrompt('developer'); },
    get designer() { return getProfilePrompt('designer'); },
    get student() { return getProfilePrompt('student'); },
    get casual() { return getProfilePrompt('casual'); }
};

// Edit mode
let editZoomLevel = 1;
let editPanX = 0;
let editPanY = 0;
let editIsDragging = false;
let editLastX = 0;
let editLastY = 0;
let editZoomTimeout = null;
let spacePressed = false;
const EDIT_MIN_ZOOM = 0.5;
const EDIT_MAX_ZOOM = 5;
let editImageSrc = null;

// Modal zoom
let zoomLevel = 1;
let panX = 0;
let panY = 0;
let isDragging = false;
let lastX = 0;
let lastY = 0;
let zoomTimeout = null;

// Immediately hide app if onboarding not completed (prevents flash)
(function() {
    const savedProfile = localStorage.getItem('userProfile');
    if (!savedProfile) {
        document.body.classList.add('app-hidden');
    } else {
        try {
            const profile = JSON.parse(savedProfile);
            if (!profile.hasCompletedOnboarding) {
                document.body.classList.add('app-hidden');
            }
        } catch (e) {
            document.body.classList.add('app-hidden');
        }
    }
})();
