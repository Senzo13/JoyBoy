// ===== WORKSPACE DEV MODE =====
// Mode "joyboy run" - comportement autonome type Codex/Claude Code.
// Important: ce mode doit rester attaché à une conversation + un workspace.
// Ne le remets pas en état global flottant, sinon les jobs et transcripts se
// mélangent entre chats.
console.log('[TERMINAL.JS] Fichier chargé');

function terminalT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function formatTerminalContextSize(size) {
    const parsed = Number.parseInt(size, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) return String(size || '');
    const config = window.JoyBoyContextSizes;
    if (config && parsed <= config.max) return config.format(parsed);
    if (parsed >= 1000000) return `${(parsed / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
    if (parsed >= 1024) return `${Math.round(parsed / 1024)}K`;
    return String(parsed);
}

// ===== CONTEXT SIZE POPUP =====

/**
 * Affiche un popup pour modifier la taille du contexte
 */
function showContextSizePopup() {
    const contextConfig = window.JoyBoyContextSizes;
    const currentSize = contextConfig?.normalize(userSettings.contextSize || 4096) || (userSettings.contextSize || 4096);

    const sizes = [
        { value: 2048, label: '2K', desc: terminalT('terminal.contextEconomy', 'Économe (~1GB)') },
        { value: 4096, label: '4K', desc: terminalT('terminal.contextStandard', 'Standard (~2GB)') },
        { value: 8192, label: '8K', desc: terminalT('terminal.contextMedium', 'Moyen (~3GB)') },
        { value: 16384, label: '16K', desc: terminalT('terminal.contextLarge', 'Grand (~5GB)') },
        { value: 32768, label: '32K', desc: terminalT('terminal.contextMax', 'Max (~8GB)') },
        { value: 65536, label: '64K', desc: terminalT('terminal.contextVeryLarge', 'Très grand (~16GB+)') },
        { value: 131072, label: '128K', desc: terminalT('terminal.contextHuge', 'Énorme (~32GB+)') },
        { value: 262144, label: '256K', desc: terminalT('terminal.contextUltra', 'Extrême (~64GB+)') },
    ];

    const optionsHtml = sizes.map(s => `
        <div class="context-size-option ${s.value === currentSize ? 'active' : ''}"
             onclick="setContextSize(${s.value})">
            <span class="size-label">${s.label}</span>
            <span class="size-desc">${s.desc}</span>
        </div>
    `).join('');

    // Créer l'overlay et le popup
    const overlay = document.createElement('div');
    overlay.className = 'context-size-overlay';
    overlay.onclick = () => overlay.remove();

    const popup = document.createElement('div');
    popup.className = 'context-size-popup';
    popup.innerHTML = `
        <h4><i data-lucide="database"></i> ${escapeHtml(terminalT('terminal.contextPopupTitle', 'Taille du contexte'))}</h4>
        <div class="context-size-options">
            ${optionsHtml}
        </div>
        <div class="context-size-note">${escapeHtml(terminalT('terminal.contextLocalNote', 'Ollama local : certains modèles refuseront les très grands contextes ou iront beaucoup plus lentement.'))}</div>
    `;
    popup.onclick = (e) => e.stopPropagation();

    overlay.appendChild(popup);
    document.body.appendChild(overlay);

    // Init Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Définit la nouvelle taille du contexte
 */
function setContextSize(size) {
    const normalizedSize = window.JoyBoyContextSizes?.normalize(size) || parseInt(size, 10) || 4096;
    userSettings.contextSize = normalizedSize;
    if (typeof tokenStats !== 'undefined') {
        tokenStats.maxContextSize = typeof getTerminalEffectiveContextSize === 'function'
            ? getTerminalEffectiveContextSize()
            : normalizedSize;
    }

    // Mettre à jour l'affichage
    const maxEl = document.getElementById('tokens-max');
    if (maxEl) maxEl.textContent = formatTerminalContextSize(tokenStats?.maxContextSize || normalizedSize);

    // Mettre à jour dans les settings si ouvert
    const settingsSelect = document.getElementById('settings-context-size');
    if (settingsSelect) settingsSelect.value = normalizedSize;
    const settingsValue = document.getElementById('settings-context-size-value');
    if (settingsValue) settingsValue.textContent = formatTerminalContextSize(normalizedSize);

    // Fermer le popup
    const overlay = document.querySelector('.context-size-overlay');
    if (overlay) overlay.remove();

    // Notification
    if (typeof Toast !== 'undefined') {
        Toast.success(terminalT('terminal.contextSizeToast', 'Contexte : {size} tokens', { size: formatTerminalContextSize(normalizedSize) }));
    }

    console.log(`[TERMINAL] Context size: ${normalizedSize}`);
}

/**
 * Met à jour l'affichage max des tokens au chargement
 */
function updateTokensMaxDisplay() {
    const maxEl = document.getElementById('tokens-max');
    if (maxEl) {
        const maxContext = typeof getTerminalEffectiveContextSize === 'function'
            ? getTerminalEffectiveContextSize()
            : (userSettings.contextSize || 4096);
        maxEl.textContent = formatTerminalContextSize(maxContext);
    }
}

// ===== TOOL RESULTS STORAGE (Ctrl+O to view) =====
let lastToolResults = [];  // Stocke les derniers résultats d'outils

/**
 * Ajoute un résultat d'outil au stockage
 */
function storeToolResult(toolCall, toolResult) {
    lastToolResults.push({
        timestamp: new Date().toLocaleTimeString(),
        tool: toolCall,
        result: toolResult
    });
    // Garder les 20 derniers
    if (lastToolResults.length > 20) {
        lastToolResults.shift();
    }
}

/**
 * Affiche les derniers résultats d'outils (Ctrl+O)
 */
function showToolResults() {
    // Créer les items HTML
    let itemsHtml = '';

    if (lastToolResults.length === 0) {
        itemsHtml = '<div class="tool-results-empty">Aucun résultat d\'outil à afficher</div>';
    } else {
        for (const item of lastToolResults.slice().reverse()) {
            const toolName = item.tool?.action || item.tool?.name || item.tool?.function?.name || 'unknown';
            const toolArgs = item.tool?.args || item.tool?.path || item.tool?.function?.arguments || {};
            const argsStr = typeof toolArgs === 'string' ? toolArgs : JSON.stringify(toolArgs, null, 2);

            let outputStr = '';
            if (item.result?.error) {
                outputStr = `ERROR: ${item.result.error}`;
            } else if (item.result?.content) {
                outputStr = item.result.content.substring(0, 1000);
            } else if (item.result?.items) {
                outputStr = item.result.items.slice(0, 20).map(i => i.name || i).join('\n');
            } else if (item.result?.output) {
                outputStr = item.result.output.substring(0, 1000);
            } else if (typeof item.result === 'string') {
                outputStr = item.result.substring(0, 1000);
            }

            itemsHtml += `
                <div class="tool-result-item">
                    <div class="tool-result-header">
                        <span class="tool-result-name">${toolName}</span>
                        <span class="tool-result-time">${item.timestamp}</span>
                    </div>
                    <div class="tool-result-args">${argsStr}</div>
                    <div class="tool-result-output">${outputStr || escapeHtml(terminalT('terminal.toolOutputEmpty', '(no output)'))}</div>
                </div>
            `;
        }
    }

    // Créer le modal
    const modal = document.createElement('div');
    modal.className = 'tool-results-modal';
    modal.innerHTML = `
        <div class="tool-results-content">
            <div class="tool-results-header">
                <h3><i data-lucide="terminal"></i> ${escapeHtml(terminalT('terminal.toolResultsTitle', 'Tool Results (Ctrl+O)'))}</h3>
                <button class="tool-results-close" onclick="this.closest('.tool-results-modal').remove()">
                    <i data-lucide="x"></i>
                </button>
            </div>
            <div class="tool-results-body">
                ${itemsHtml}
            </div>
        </div>
    `;

    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    document.body.appendChild(modal);

    // Init Lucide icons in modal
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Keyboard shortcut Ctrl+O
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'o' && terminalMode) {
        e.preventDefault();
        showToolResults();
    }
});

// ===== TERMINAL COMMAND HISTORY =====
// Historique des commandes avec navigation flèche haut/bas (comme un vrai terminal)
let terminalCommandHistory = [];
let terminalHistoryIndex = -1;
let terminalCurrentInput = '';  // Sauvegarde l'input actuel avant navigation
let terminalHistoryStore = {};
let terminalHistoryScope = '';
const MAX_TERMINAL_HISTORY = 100;
const TERMINAL_HISTORY_STORE_KEY = 'terminalHistoryByScope';

function getTerminalHistoryScope() {
    const chatId = (typeof currentChatId !== 'undefined' && currentChatId) ? currentChatId : 'global';
    const workspaceKey = terminalWorkspace?.path || terminalWorkspace?.name || 'no-workspace';
    return `${chatId}:${workspaceKey}`;
}

function syncTerminalHistoryScope() {
    const scope = getTerminalHistoryScope();
    if (terminalHistoryScope === scope) return;
    terminalHistoryScope = scope;
    terminalCommandHistory = Array.isArray(terminalHistoryStore[scope])
        ? [...terminalHistoryStore[scope]]
        : (Array.isArray(terminalHistoryStore.global) ? [...terminalHistoryStore.global] : []);
    terminalHistoryIndex = -1;
    terminalCurrentInput = '';
}

function saveTerminalHistoryScope() {
    syncTerminalHistoryScope();
    terminalHistoryStore[terminalHistoryScope] = terminalCommandHistory.slice(0, MAX_TERMINAL_HISTORY);
    localStorage.setItem(TERMINAL_HISTORY_STORE_KEY, JSON.stringify(terminalHistoryStore));
}

/**
 * Ajoute une commande à l'historique terminal
 * @param {string} command - Commande à ajouter
 */
function addToTerminalHistory(command) {
    if (!command.trim()) return;
    syncTerminalHistoryScope();

    // Éviter les doublons consécutifs
    if (terminalCommandHistory.length > 0 && terminalCommandHistory[0] === command) {
        return;
    }

    // Ajouter au début (plus récent en premier)
    terminalCommandHistory.unshift(command);

    // Limiter la taille
    if (terminalCommandHistory.length > MAX_TERMINAL_HISTORY) {
        terminalCommandHistory.pop();
    }

    // Reset l'index
    terminalHistoryIndex = -1;
    terminalCurrentInput = '';

    // Sauvegarder dans localStorage
    saveTerminalHistoryScope();
}

/**
 * Charge l'historique depuis localStorage
 */
function loadTerminalHistory() {
    try {
        const saved = localStorage.getItem(TERMINAL_HISTORY_STORE_KEY);
        if (saved) {
            terminalHistoryStore = JSON.parse(saved) || {};
        } else {
            const legacy = JSON.parse(localStorage.getItem('terminalHistory') || '[]');
            if (Array.isArray(legacy) && legacy.length) {
                terminalHistoryStore.global = legacy.slice(0, MAX_TERMINAL_HISTORY);
            }
        }
        syncTerminalHistoryScope();
    } catch (e) {
        console.error('[TERMINAL] Erreur chargement historique:', e);
        terminalHistoryStore = {};
        syncTerminalHistoryScope();
    }
}

/**
 * Navigue dans l'historique (flèche haut/bas)
 * @param {string} direction - 'up' ou 'down'
 * @param {HTMLInputElement} inputElement - L'élément input
 */
function navigateTerminalHistory(direction, inputElement) {
    syncTerminalHistoryScope();
    if (terminalCommandHistory.length === 0) return;

    // Sauvegarder l'input actuel si on commence la navigation
    if (terminalHistoryIndex === -1 && direction === 'up') {
        terminalCurrentInput = inputElement.value;
    }

    if (direction === 'up') {
        // Remonter dans l'historique (plus ancien)
        if (terminalHistoryIndex < terminalCommandHistory.length - 1) {
            terminalHistoryIndex++;
            inputElement.value = terminalCommandHistory[terminalHistoryIndex];
        }
    } else if (direction === 'down') {
        // Descendre dans l'historique (plus récent)
        if (terminalHistoryIndex > 0) {
            terminalHistoryIndex--;
            inputElement.value = terminalCommandHistory[terminalHistoryIndex];
        } else if (terminalHistoryIndex === 0) {
            // Retour à l'input original
            terminalHistoryIndex = -1;
            inputElement.value = terminalCurrentInput;
        }
    }

    // Placer le curseur à la fin
    setTimeout(() => {
        inputElement.selectionStart = inputElement.selectionEnd = inputElement.value.length;
    }, 0);
}

/**
 * Gestionnaire de touches pour le mode terminal
 * @param {KeyboardEvent} e - Événement clavier
 */
function handleTerminalKeydown(e) {
    if (!terminalMode) return;

    const input = e.target;
    if (input.id !== 'prompt-input' && input.id !== 'chat-prompt') return;

    // Flèche haut - historique précédent
    if (e.key === 'ArrowUp') {
        e.preventDefault();
        navigateTerminalHistory('up', input);
        return;
    }

    // Flèche bas - historique suivant
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        navigateTerminalHistory('down', input);
        return;
    }

    // Ctrl+C - Interrompre
    if (e.ctrlKey && e.key === 'c') {
        if (terminalWorking) {
            e.preventDefault();
            interruptTerminal();
        }
        return;
    }
}

// Charger l'historique au démarrage
loadTerminalHistory();

// Ajouter le listener global pour les touches
document.addEventListener('keydown', handleTerminalKeydown);

// ===== THINKING ANIMATION =====
// Animation "Thinking..." avec dots animés comme Claude Code

let thinkingInterval = null;
let thinkingElement = null;

/**
 * Affiche l'animation "Thinking..." dans le chat
 * @param {string} action - Action en cours (ex: "Thinking", "Reading", "Writing")
 * @returns {HTMLElement} L'élément créé (pour le supprimer plus tard)
 */
function showThinkingAnimation(action = 'Thinking') {
    // Supprimer une animation existante
    hideThinkingAnimation();

    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return null;

    // Créer l'élément
    thinkingElement = document.createElement('div');
    thinkingElement.className = 'terminal-thinking';
    thinkingElement.innerHTML = `
        <span class="thinking-text">${action}</span>
        <span class="thinking-dots">
            <span class="dot">.</span>
            <span class="dot">.</span>
            <span class="dot">.</span>
        </span>
    `;
    messagesDiv.appendChild(thinkingElement);
    scrollToBottom(true);

    return thinkingElement;
}

/**
 * Met à jour le texte de l'animation (ex: "Reading file.js...")
 * @param {string} action - Nouveau texte
 */
function updateThinkingText(action) {
    if (thinkingElement) {
        const textEl = thinkingElement.querySelector('.thinking-text');
        if (textEl) textEl.textContent = action;
    }
}

/**
 * Cache l'animation Thinking
 */
function hideThinkingAnimation() {
    if (thinkingElement) {
        thinkingElement.remove();
        thinkingElement = null;
    }
}

// ===== TERMINAL TASKS (like Claude Code) =====
// Système de tâches visuelles pour montrer ce que l'IA fait

let terminalTasks = [];
let terminalTasksElement = null;
let terminalToolTaskSeq = 0;
let terminalProgressElement = null;
let terminalProgressLogElement = null;
let terminalProgressTimerElement = null;
let terminalProgressStartedAt = 0;
let terminalProgressTimer = null;
let terminalProgressLogCount = 0;
let terminalProgressAutoHideTimer = null;
let terminalProgressRevealTimer = null;
let terminalProgressBufferedLogs = [];
let terminalProgressSessionActive = false;
let terminalProgressContentStarted = false;
let terminalProgressIntent = '';
let terminalProgressLogKeyElements = new Map();
let terminalContextActivity = null;
const TERMINAL_PROGRESS_AUTO_REVEAL_MS = 3500;

let terminalActivityCounters = null;
let terminalActivityElements = {};

function formatTerminalElapsed(seconds) {
    const safeSeconds = Math.max(0, Number(seconds) || 0);
    if (safeSeconds < 60) return `${safeSeconds}s`;
    const minutes = Math.floor(safeSeconds / 60);
    const remaining = safeSeconds % 60;
    return remaining ? `${minutes}m ${remaining}s` : `${minutes}m`;
}

function updateTerminalProgressTimer(done = false) {
    if (!terminalProgressTimerElement || !terminalProgressStartedAt) return;
    const elapsed = Math.floor((Date.now() - terminalProgressStartedAt) / 1000);
    const key = done ? 'terminal.progressDoneIn' : 'terminal.progressRunningFor';
    const fallback = done ? 'Terminé en {time}' : 'En cours depuis {time}';
    terminalProgressTimerElement.textContent = terminalT(key, fallback, {
        time: formatTerminalElapsed(elapsed)
    });
}

function keepTerminalMessagesAboveComposer() {
    const messagesDiv = document.getElementById('chat-messages');
    const inputBar = document.querySelector('#chat-view .chat-input-bar') || document.querySelector('.chat-input-bar');
    if (!messagesDiv || !inputBar || !document.body.classList.contains('terminal-mode')) return;

    const lastMessage = messagesDiv.lastElementChild;
    if (!lastMessage) return;

    const inputTop = inputBar.getBoundingClientRect().top;
    const lastBottom = lastMessage.getBoundingClientRect().bottom;
    const overlap = lastBottom - (inputTop - 28);
    if (overlap > 0) {
        messagesDiv.scrollTop += overlap;
    }
}

function refreshTerminalProgressLayout() {
    if (typeof updateComposerAttachmentState === 'function') {
        updateComposerAttachmentState();
    }
    if (typeof updateChatPadding === 'function') {
        updateChatPadding();
    }
    requestAnimationFrame(() => {
        if (typeof updateChatPadding === 'function') {
            updateChatPadding();
        }
        keepTerminalMessagesAboveComposer();
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
        if (typeof updateChatPadding === 'function') {
            updateChatPadding();
        }
        keepTerminalMessagesAboveComposer();
    }));
}

function showTerminalProgressPanel() {
    if (terminalProgressElement) return terminalProgressElement;

    const inputBar = document.querySelector('#chat-view .chat-input-bar') || document.querySelector('.chat-input-bar');
    const composer = inputBar?.querySelector('.input-bar');
    if (!inputBar || !composer) return null;

    clearTimeout(terminalProgressAutoHideTimer);
    terminalProgressAutoHideTimer = null;

    if (!terminalProgressStartedAt) {
        terminalProgressStartedAt = Date.now();
    }
    composer.classList.add('terminal-progress-active');

    terminalProgressElement = document.createElement('div');
    terminalProgressElement.className = 'terminal-progress-panel';
    terminalProgressElement.innerHTML = `
        <div class="terminal-progress-status">
            <div class="terminal-progress-status-main">
                <span class="terminal-progress-pulse" aria-hidden="true"></span>
                <span class="terminal-progress-timer"></span>
            </div>
            <button type="button" class="terminal-progress-toggle" onclick="toggleTerminalProgressPanel()" aria-label="${escapeHtml(terminalT('terminal.progressToggle', 'Réduire'))}">
                <i data-lucide="chevrons-up-down"></i>
            </button>
        </div>
        <div class="terminal-progress-divider"></div>
        <div class="terminal-progress-log"></div>
        <div class="terminal-progress-task-slot"></div>
    `;

    composer.insertBefore(terminalProgressElement, composer.firstChild);
    terminalProgressTimerElement = terminalProgressElement.querySelector('.terminal-progress-timer');
    terminalProgressLogElement = terminalProgressElement.querySelector('.terminal-progress-log');
    updateTerminalProgressTimer(false);

    terminalProgressTimer = setInterval(() => updateTerminalProgressTimer(false), 1000);
    if (window.lucide) lucide.createIcons();
    refreshTerminalProgressLayout();
    return terminalProgressElement;
}

function beginTerminalProgressSession() {
    clearTimeout(terminalProgressRevealTimer);
    terminalProgressRevealTimer = null;
    terminalProgressSessionActive = true;
    terminalProgressContentStarted = false;
    terminalProgressIntent = '';
    terminalProgressStartedAt = Date.now();
    terminalProgressLogCount = 0;
    terminalProgressBufferedLogs = [];
    terminalProgressLogKeyElements = new Map();
    resetTerminalContextActivity();
}

function scheduleTerminalProgressAutoReveal(delay = TERMINAL_PROGRESS_AUTO_REVEAL_MS) {
    clearTimeout(terminalProgressRevealTimer);
    terminalProgressRevealTimer = setTimeout(() => {
        if (!terminalProgressSessionActive || terminalProgressContentStarted || terminalProgressElement) return;
        revealTerminalProgressPanel();
    }, delay);
}

function revealTerminalProgressPanel() {
    clearTimeout(terminalProgressRevealTimer);
    terminalProgressRevealTimer = null;
    const panel = showTerminalProgressPanel();
    if (!panel) return null;

    const bufferedLogs = terminalProgressBufferedLogs.splice(0);
    bufferedLogs.forEach(entry => appendTerminalProgressLog(entry.label, entry.detail, entry.type, entry.key));
    refreshTerminalProgressLayout();
    return panel;
}

function renderTerminalProgressLogEntry(entry, label, detail = '', type = 'info') {
    entry.className = `terminal-progress-log-line is-${type}`;
    const safeDetail = detail ? `<span class="terminal-progress-log-detail">${escapeHtml(detail)}</span>` : '';
    const index = entry.dataset.progressIndex || '';
    entry.innerHTML = `
        <span class="terminal-progress-log-index">${escapeHtml(index)}</span>
        <span class="terminal-progress-log-text">${escapeHtml(label)}</span>
        ${safeDetail}
    `;
}

function appendTerminalProgressLog(label, detail = '', type = 'info', key = '') {
    if (!terminalProgressLogElement) return;

    const normalizedKey = String(key || '').trim();
    if (normalizedKey) {
        const existing = terminalProgressLogKeyElements.get(normalizedKey);
        if (existing && existing.isConnected) {
            renderTerminalProgressLogEntry(existing, label, detail, type);
            terminalProgressLogElement.scrollTop = terminalProgressLogElement.scrollHeight;
            refreshTerminalProgressLayout();
            return;
        }
    }

    terminalProgressLogCount += 1;
    const entry = document.createElement('div');
    entry.dataset.progressIndex = String(terminalProgressLogCount);
    if (normalizedKey) {
        entry.dataset.progressKey = normalizedKey;
        terminalProgressLogKeyElements.set(normalizedKey, entry);
    }
    renderTerminalProgressLogEntry(entry, label, detail, type);
    terminalProgressLogElement.appendChild(entry);

    while (terminalProgressLogElement.children.length > 8) {
        const removed = terminalProgressLogElement.firstElementChild;
        const removedKey = removed?.dataset?.progressKey;
        if (removedKey) terminalProgressLogKeyElements.delete(removedKey);
        terminalProgressLogElement.removeChild(removed);
    }

    terminalProgressLogElement.scrollTop = terminalProgressLogElement.scrollHeight;
    refreshTerminalProgressLayout();
}

function addTerminalProgressLog(label, detail = '', type = 'info', options = {}) {
    const shouldReveal = Boolean(options.reveal);
    const key = String(options.key || '').trim();
    if (shouldReveal) {
        revealTerminalProgressPanel();
    }

    if (!terminalProgressElement) {
        if (key) {
            const existing = terminalProgressBufferedLogs.find(entry => entry.key === key);
            if (existing) {
                existing.label = label;
                existing.detail = detail;
                existing.type = type;
                return;
            }
        }
        terminalProgressBufferedLogs.push({ label, detail, type, key });
        if (terminalProgressBufferedLogs.length > 10) {
            terminalProgressBufferedLogs.shift();
        }
        return;
    }

    appendTerminalProgressLog(label, detail, type, key);
}

function completeTerminalProgressPanel(success = true) {
    clearTimeout(terminalProgressRevealTimer);
    terminalProgressRevealTimer = null;
    terminalProgressSessionActive = false;
    terminalProgressContentStarted = false;
    terminalProgressIntent = '';
    terminalProgressBufferedLogs = [];
    if (!terminalProgressElement) return;
    clearInterval(terminalProgressTimer);
    terminalProgressTimer = null;
    terminalProgressElement.classList.toggle('is-complete', success);
    terminalProgressElement.classList.toggle('is-error', !success);
    if (success) {
        terminalProgressElement.classList.add('is-collapsed');
        if (terminalTasksElement) terminalTasksElement.classList.add('collapsed');
    }
    updateTerminalProgressTimer(true);
    refreshTerminalProgressLayout();
}

function hideTerminalProgressPanel() {
    clearInterval(terminalProgressTimer);
    clearTimeout(terminalProgressAutoHideTimer);
    clearTimeout(terminalProgressRevealTimer);
    terminalProgressTimer = null;
    terminalProgressAutoHideTimer = null;
    terminalProgressRevealTimer = null;
    if (terminalProgressElement) {
        terminalProgressElement.remove();
    }
    document.querySelectorAll('.input-bar.terminal-progress-active').forEach(bar => {
        bar.classList.remove('terminal-progress-active');
    });
    terminalProgressElement = null;
    terminalProgressLogElement = null;
    terminalProgressTimerElement = null;
    terminalProgressStartedAt = 0;
    terminalProgressLogCount = 0;
    terminalProgressBufferedLogs = [];
    terminalProgressLogKeyElements = new Map();
    terminalProgressSessionActive = false;
    terminalProgressContentStarted = false;
    terminalProgressIntent = '';
    terminalTasksElement = null;
    terminalTasks = [];
    terminalContextActivity = null;
    refreshTerminalProgressLayout();
}

function resetTerminalActivitySummaries() {
    terminalActivityCounters = {
        commands: 0,
        webSearches: 0,
        webFetches: 0,
        fileReads: 0,
        fileWrites: 0,
        searches: 0
    };
    terminalActivityElements = {};
    resetTerminalContextActivity();
}

function terminalPlural(count, singular, plural = null) {
    return `${count} ${count > 1 ? (plural || `${singular}s`) : singular}`;
}

function getTerminalActivityKind(action = '') {
    if (action === 'bash') return 'commands';
    if (action === 'web_search') return 'webSearches';
    if (action === 'web_fetch') return 'webFetches';
    if (action === 'read_file') return 'fileReads';
    if (['write_file', 'write_files', 'edit_file', 'delete_file', 'clear_workspace'].includes(action)) return 'fileWrites';
    if (['search', 'glob', 'list_files', 'tool_search'].includes(action)) return 'searches';
    return '';
}

const TERMINAL_CONTEXT_ACTIVITY_TOOLS = new Set([
    'list_files',
    'read_file',
    'search',
    'glob',
    'tool_search'
]);

const TERMINAL_SHELL_SEARCH_COMMANDS = new Set([
    'rg',
    'grep',
    'find',
    'findstr',
    'select-string',
    'sls',
    'where',
    'where.exe'
]);

const TERMINAL_SHELL_READ_COMMANDS = new Set([
    'cat',
    'head',
    'tail',
    'wc',
    'stat',
    'file',
    'strings',
    'ls',
    'dir',
    'tree',
    'du',
    'type',
    'get-content',
    'gc',
    'get-childitem',
    'gci',
    'get-item',
    'get-location',
    'pwd',
    'get-filehash',
    'git'
]);

const TERMINAL_SHELL_NEUTRAL_COMMANDS = new Set([
    'echo',
    'write-output',
    'write-host',
    'select-object',
    'select',
    'where-object',
    'foreach-object',
    'sort-object',
    'measure-object',
    'format-table',
    'format-list',
    'out-string',
    'true',
    'false'
]);

const TERMINAL_GIT_READ_SUBCOMMANDS = new Set([
    'status',
    'log',
    'show',
    'diff',
    'grep',
    'ls-files',
    'rev-parse',
    'describe'
]);

function resetTerminalContextActivity() {
    terminalContextActivity = {
        counts: {
            list: 0,
            read: 0,
            search: 0,
            toolSearch: 0,
            shell: 0
        },
        latestHint: '',
        hadError: false
    };
}

function isTerminalContextGatheringTool(action = '') {
    return TERMINAL_CONTEXT_ACTIVITY_TOOLS.has(String(action || ''));
}

function normalizeTerminalShellCommandName(command = '') {
    return String(command || '')
        .trim()
        .split(/\s+/, 1)[0]
        .toLowerCase();
}

function splitTerminalShellCommand(command = '') {
    const parts = [];
    let current = '';
    let quote = '';
    let escaping = false;
    const text = String(command || '');

    for (let i = 0; i < text.length; i += 1) {
        const char = text[i];
        const next = text[i + 1] || '';
        if (escaping) {
            current += char;
            escaping = false;
            continue;
        }
        if (char === '\\' && quote !== "'") {
            current += char;
            escaping = true;
            continue;
        }
        if ((char === '"' || char === "'") && !quote) {
            quote = char;
            current += char;
            continue;
        }
        if (quote && char === quote) {
            quote = '';
            current += char;
            continue;
        }
        if (!quote) {
            if ((char === '&' && next === '&') || (char === '|' && next === '|')) {
                if (current.trim()) parts.push(current.trim());
                current = '';
                i += 1;
                continue;
            }
            if (char === ';' || char === '|') {
                if (current.trim()) parts.push(current.trim());
                current = '';
                continue;
            }
        }
        current += char;
    }

    if (current.trim()) parts.push(current.trim());
    return parts;
}

function classifyTerminalShellContextCommand(command = '') {
    const text = String(command || '').trim();
    if (!text || /(^|[^>])>{1,2}[^>]/.test(text)) return '';

    const parts = splitTerminalShellCommand(text);
    if (!parts.length) return '';

    let hasSearch = false;
    let hasRead = false;
    for (const part of parts) {
        const base = normalizeTerminalShellCommandName(part).replace(/\.exe$/, '');
        if (!base || TERMINAL_SHELL_NEUTRAL_COMMANDS.has(base)) continue;

        if (base === 'git') {
            const tokens = part.trim().split(/\s+/);
            const subcommand = String(tokens[1] || '').toLowerCase();
            if (!TERMINAL_GIT_READ_SUBCOMMANDS.has(subcommand)) return '';
            hasRead = true;
            continue;
        }

        if (TERMINAL_SHELL_SEARCH_COMMANDS.has(base)) {
            hasSearch = true;
            continue;
        }
        if (TERMINAL_SHELL_READ_COMMANDS.has(base)) {
            hasRead = true;
            continue;
        }
        return '';
    }

    if (hasSearch) return 'search';
    if (hasRead) return 'read';
    return '';
}

function isTerminalContextGatheringToolCall(action = '', args = {}) {
    if (isTerminalContextGatheringTool(action)) return true;
    if (action !== 'bash') return false;
    return Boolean(classifyTerminalShellContextCommand(args?.command || ''));
}

function terminalContextCountKey(action = '', args = {}) {
    if (action === 'list_files') return 'list';
    if (action === 'read_file') return 'read';
    if (action === 'tool_search') return 'toolSearch';
    if (action === 'search' || action === 'glob') return 'search';
    if (action === 'bash') return 'shell';
    return '';
}

function getTerminalContextHint(action = '', target = '', args = {}, result = {}) {
    const normalizedArgs = args && typeof args === 'object' ? args : {};
    const normalizedResult = result && typeof result === 'object' ? result : {};
    const hint = target
        || normalizedResult.path
        || normalizedArgs.path
        || normalizedArgs.pattern
        || normalizedArgs.query
        || normalizedArgs.intent
        || '';
    return String(hint || '').trim();
}

function formatTerminalContextActivitySummary(activity = terminalContextActivity) {
    if (!activity) return '';
    const counts = activity.counts || {};
    const parts = [];
    if (counts.list) parts.push(terminalPlural(counts.list, 'exploration', 'explorations'));
    if (counts.read) parts.push(terminalPlural(counts.read, 'fichier lu', 'fichiers lus'));
    if (counts.search) parts.push(terminalPlural(counts.search, 'recherche', 'recherches'));
    if (counts.toolSearch) parts.push(terminalPlural(counts.toolSearch, 'outil chargé', 'outils chargés'));
    if (counts.shell) parts.push(terminalPlural(counts.shell, 'commande de contexte', 'commandes de contexte'));
    return parts.join(', ');
}

function hasTerminalContextActivity(activity = terminalContextActivity) {
    if (!activity || !activity.counts) return false;
    return Object.values(activity.counts).some(count => Number(count || 0) > 0);
}

function updateTerminalContextActivity(action = '', target = '', args = {}, state = 'running', result = {}) {
    if (!isTerminalContextGatheringToolCall(action, args)) return false;
    if (!terminalContextActivity) resetTerminalContextActivity();

    const countKey = terminalContextCountKey(action, args);
    if (state === 'running' && countKey) {
        terminalContextActivity.counts[countKey] += 1;
    }
    if (state === 'error') {
        terminalContextActivity.hadError = true;
    }

    const hint = getTerminalContextHint(action, target, args, result);
    if (hint) terminalContextActivity.latestHint = hint;

    const summary = formatTerminalContextActivitySummary();
    if (!summary) return true;
    const detailParts = [summary];
    if (terminalContextActivity.latestHint) {
        detailParts.push(terminalContextActivity.latestHint);
    }
    const detail = detailParts.join(' · ');
    const label = terminalT('terminal.contextActivity', 'Contexte');
    const progressType = state === 'error'
        ? 'error'
        : state === 'done'
            ? 'success'
            : 'running';

    addTerminalProgressLog(label, detail, progressType, { key: 'context-gathering' });

    if (!isTerminalReadOnlyTurn()) {
        const taskStatus = state === 'error' ? 'error' : 'running';
        const taskLabel = terminalT('terminal.taskGatherContext', 'Lecture du contexte');
        const existing = terminalTasks.find(task => task.id === 'context-gathering');
        if (existing) {
            updateTerminalTask('context-gathering', taskStatus, detail, taskLabel);
        } else {
            addTerminalTask('context-gathering', taskLabel, taskStatus, detail);
        }
    }
    return true;
}

function completeTerminalContextActivity() {
    if (!hasTerminalContextActivity()) return;
    const summary = formatTerminalContextActivitySummary();
    if (!summary) return;
    const detail = terminalContextActivity.latestHint ? `${summary} · ${terminalContextActivity.latestHint}` : summary;
    const type = terminalContextActivity.hadError ? 'warning' : 'success';
    addTerminalProgressLog(terminalT('terminal.contextActivity', 'Contexte'), detail, type, { key: 'context-gathering' });
    updateTerminalTask('context-gathering', terminalContextActivity.hadError ? 'error' : 'done', detail);
}

function isTerminalReadOnlyTurn() {
    return ['read', 'question'].includes(String(terminalProgressIntent || '').toLowerCase());
}

function isTerminalPassiveReadOnlyTool(action = '') {
    return TERMINAL_READ_ONLY_PROGRESS_TOOLS.has(String(action || ''));
}

function formatTerminalActivitySummary(kind, count) {
    if (kind === 'commands') return terminalT('terminal.activityCommands', 'Ran {count} commands', { count });
    if (kind === 'webSearches') return terminalT('terminal.activityWebSearches', 'Recherche Web effectuée {count} fois', { count });
    if (kind === 'webFetches') return terminalT('terminal.activityWebFetches', '{count} pages Web lues', { count });
    if (kind === 'fileReads') return terminalT('terminal.activityFileReads', `${terminalPlural(count, 'fichier lu', 'fichiers lus')}`, { count });
    if (kind === 'fileWrites') return terminalT('terminal.activityFileWrites', `${terminalPlural(count, 'changement fichier', 'changements fichiers')}`, { count });
    if (kind === 'searches') return terminalT('terminal.activitySearches', `${terminalPlural(count, 'recherche workspace', 'recherches workspace')}`, { count });
    return '';
}

function addOrUpdateTerminalActivitySummary(action = '', args = {}) {
    if (isTerminalPassiveReadOnlyTool(action) || isTerminalContextGatheringToolCall(action, args)) return;

    if (!terminalActivityCounters) resetTerminalActivitySummaries();
    const kind = getTerminalActivityKind(action);
    if (!kind) return;

    terminalActivityCounters[kind] += 1;
    const count = terminalActivityCounters[kind];
    const text = formatTerminalActivitySummary(kind, count);
    if (!text) return;

    const messagesDiv = getChatMessages();
    if (!messagesDiv) return;

    let el = terminalActivityElements[kind];
    if (!el || !el.isConnected) {
        el = document.createElement('div');
        el.className = 'terminal-activity-summary';
        terminalActivityElements[kind] = el;
        messagesDiv.appendChild(el);
    }
    el.textContent = text;
    scrollToBottom(document.body.classList.contains('terminal-mode'));
}

function toggleTerminalProgressPanel() {
    if (!terminalProgressElement) return;
    terminalProgressElement.classList.toggle('is-collapsed');
    refreshTerminalProgressLayout();
}

/**
 * Crée/affiche la barre de tâches terminal
 */
function showTerminalTasks() {
    if (terminalTasksElement) return terminalTasksElement;
    if (isTerminalReadOnlyTurn()) return null;

    const progressPanel = revealTerminalProgressPanel();
    const taskSlot = progressPanel?.querySelector('.terminal-progress-task-slot');
    if (!taskSlot) return null;

    terminalTasksElement = document.createElement('div');
    terminalTasksElement.className = 'terminal-tasks';
    terminalTasksElement.innerHTML = `
        <div class="terminal-tasks-header">
            <span class="tasks-count">${escapeHtml(terminalT('terminal.taskCount', '{done}/{total} tâches', { done: 0, total: 0 }))}</span>
            <span class="tasks-toggle" onclick="toggleTerminalTasks()">▼</span>
        </div>
        <div class="terminal-tasks-list"></div>
    `;
    taskSlot.appendChild(terminalTasksElement);
    refreshTerminalProgressLayout();
    return terminalTasksElement;
}

function normalizeTerminalTaskStatus(status) {
    const value = String(status || 'pending').toLowerCase();
    if (['completed', 'complete', 'done', 'success'].includes(value)) return 'done';
    if (['in_progress', 'running', 'active'].includes(value)) return 'running';
    if (['blocked', 'error', 'failed'].includes(value)) return 'error';
    return 'pending';
}

function summarizeTerminalPaths(paths, max = 4) {
    if (!Array.isArray(paths) || paths.length === 0) return '';
    const labels = paths
        .map(item => (typeof item === 'string' ? item : item?.path))
        .filter(Boolean)
        .slice(0, max);
    const suffix = paths.length > labels.length ? `, +${paths.length - labels.length}` : '';
    return `${labels.join(', ')}${suffix}`;
}

function describeTerminalToolCall(action, target = '', args = {}) {
    const normalizedArgs = args && typeof args === 'object' ? args : {};
    const displayTarget = target || normalizedArgs.path || normalizedArgs.pattern || normalizedArgs.command || '';
    const files = Array.isArray(normalizedArgs.files) ? normalizedArgs.files : [];

    if (action === 'write_files') {
        const fileSummary = summarizeTerminalPaths(files, 3);
        const count = files.length ? `${files.length} ` : '';
        return `${terminalT('terminal.taskWriteFiles', 'Écriture de fichiers')} ${count}${fileSummary ? `- ${fileSummary}` : ''}`.trim();
    }
    if (action === 'write_file') return `${terminalT('terminal.taskWriteFile', 'Écriture')} ${displayTarget}`.trim();
    if (action === 'edit_file') return `${terminalT('terminal.taskEditFile', 'Modification')} ${displayTarget}`.trim();
    if (action === 'delete_file') return `${terminalT('terminal.taskDeleteFile', 'Suppression')} ${displayTarget}`.trim();
    if (action === 'clear_workspace') return terminalT('terminal.taskClearWorkspace', 'Nettoyage du workspace');
    if (action === 'bash') return `${terminalT('terminal.taskRunCommand', 'Commande')} ${displayTarget}`.trim();
    if (action === 'read_file') return `${terminalT('terminal.taskReadFile', 'Lecture')} ${displayTarget}`.trim();
    if (action === 'list_files') return `${terminalT('terminal.taskListFiles', 'Exploration')} ${displayTarget || terminalT('terminal.taskCurrentWorkspace', 'du projet')}`.trim();
    if (action === 'search' || action === 'glob') return `${terminalT('terminal.taskSearchFiles', 'Recherche')} ${displayTarget}`.trim();
    if (action === 'tool_search') return `${terminalT('terminal.taskToolSearch', 'Recherche d’outils')} ${displayTarget}`.trim();
    if (action === 'write_todos') return terminalT('terminal.taskPlan', 'Planification');
    if (action === 'ask_clarification') return terminalT('terminal.taskClarification', 'Clarification');
    if (action === 'delegate_subagent') return terminalT('terminal.taskSubagent', 'Vérification déléguée');
    return `${action}${displayTarget ? ` ${displayTarget}` : ''}`;
}

function describeTerminalToolNote(action, target = '', args = {}) {
    const normalizedArgs = args && typeof args === 'object' ? args : {};
    if (action === 'delegate_subagent') {
        const agentType = String(normalizedArgs.agent_type || normalizedArgs.agentType || '').trim();
        const task = String(normalizedArgs.task || '').trim();
        return [agentType, task].filter(Boolean).join(' - ');
    }
    if (action === 'write_todos') {
        const todos = Array.isArray(normalizedArgs.todos) ? normalizedArgs.todos.length : 0;
        return todos ? terminalT('terminal.taskTodoCount', '{count} étape(s)', { count: todos }) : '';
    }
    if (action === 'tool_search') {
        return String(normalizedArgs.query || normalizedArgs.intent || '').trim();
    }
    return '';
}

function describeTerminalToolProgress(data = {}) {
    const action = data.action || '';
    const elapsed = formatTerminalElapsed(data.elapsed_seconds || 0);
    const target = data.path || '';
    const label = terminalT('terminal.progressToolRunning', 'Exécute {tool}', { tool: action || 'outil' });
    const detail = [elapsed, target].filter(Boolean).join(' · ');
    return { label, detail };
}

function terminalToolProgressKey(action = '') {
    return `tool-progress-${action || 'tool'}`;
}

function describeTerminalIntentTask(intent = '', autonomous = false) {
    if (autonomous) return terminalT('terminal.progressAutonomous', 'Mode autonome');
    if (intent === 'read') return terminalT('terminal.taskAnalyzeRequest', 'Analyse du projet');
    if (intent === 'write') return terminalT('terminal.taskModifyWorkspace', 'Modification du projet');
    if (intent === 'execute') return terminalT('terminal.taskExecuteProject', 'Exécution du projet');
    return terminalT('terminal.taskUnderstandRequest', 'Compréhension de la demande');
}

function describeTerminalModelCall(data = {}) {
    const iteration = Number(data.iteration || 1);
    const toolsCount = Number(data.tools_count || 0);
    if (iteration > 1 && toolsCount > 0) {
        return terminalT('terminal.taskContinueAfterTools', 'Analyse des résultats et prochaine action');
    }
    if (iteration > 1) {
        return terminalT('terminal.taskFinalSynthesis', 'Synthèse finale de la réponse');
    }
    if (toolsCount > 0) {
        return terminalT('terminal.taskRepoAnalysis', 'Analyse des fichiers du repository');
    }
    return terminalT('terminal.taskPrepareAnswer', 'Préparation de la réponse');
}

function shouldShowTerminalToolAsTask(action, args = {}) {
    if (action === 'ask_clarification') return false;
    if (isTerminalContextGatheringToolCall(action, args)) return false;
    if (isTerminalPassiveReadOnlyTool(action)) return false;
    return [
        'write_todos',
        'list_files',
        'read_file',
        'search',
        'glob',
        'tool_search',
        'write_file',
        'write_files',
        'edit_file',
        'delete_file',
        'clear_workspace',
        'bash',
        'delegate_subagent'
    ].includes(action);
}

const TERMINAL_READ_ONLY_PROGRESS_TOOLS = new Set([
    'list_files',
    'read_file',
    'search',
    'glob',
    'tool_search'
]);

function shouldRevealTerminalProgressForModelCall(data = {}) {
    const iteration = Number(data.iteration || 1);
    if (terminalProgressElement) return true;
    return iteration > 1 && !isTerminalReadOnlyTurn();
}

function shouldRevealTerminalProgressForTool(action = '', args = {}) {
    if (action === 'ask_clarification') return false;
    if (isTerminalContextGatheringToolCall(action, args)) return false;
    if (isTerminalPassiveReadOnlyTool(action)) return false;
    if (!isTerminalReadOnlyTurn()) return true;
    return !isTerminalPassiveReadOnlyTool(action);
}

function shouldShowTerminalToolResult(result = {}, args = {}) {
    if (!result || !result.success) return true;
    const action = result.action || result.tool_name;
    if (action === 'ask_clarification') return false;
    if (isTerminalContextGatheringToolCall(action, args)) return false;
    return !isTerminalPassiveReadOnlyTool(action);
}

function shouldShowTerminalToolCallLine(action = '', args = {}) {
    if (action === 'ask_clarification') return false;
    if (isTerminalContextGatheringToolCall(action, args)) return false;
    return !isTerminalPassiveReadOnlyTool(action);
}

function applyTerminalTodos(todos = []) {
    if (!Array.isArray(todos) || todos.length === 0) return;
    if (isTerminalReadOnlyTurn()) return;

    const todoTasks = todos
        .map((todo, index) => ({
            id: `todo-${todo?.id || index + 1}`,
            label: String(
                normalizeTerminalTaskStatus(todo?.status) === 'running'
                    ? (todo?.activeForm || todo?.active_form || todo?.content || todo?.title || '')
                    : (todo?.content || todo?.title || '')
            ).trim(),
            status: normalizeTerminalTaskStatus(todo?.status),
            note: String(todo?.note || todo?.result || '').trim()
        }))
        .filter(task => task.label);

    if (todoTasks.length === 0) return;

    const toolTasks = terminalTasks.filter(task => !String(task.id).startsWith('todo-'));
    terminalTasks = [...todoTasks, ...toolTasks];
    showTerminalTasks();
    renderTerminalTasks();
}

/**
 * Ajoute une tâche à la liste
 * @param {string} id - ID unique de la tâche
 * @param {string} label - Description courte
 * @param {string} status - 'pending', 'running', 'done', 'error'
 */
function addTerminalTask(id, label, status = 'pending', note = '') {
    // Créer la barre si elle n'existe pas
    const tasksEl = showTerminalTasks();
    if (!tasksEl) return;

    // Vérifier si la tâche existe déjà
    const existing = terminalTasks.find(t => t.id === id);
    if (existing) {
        updateTerminalTask(id, status, note, label);
        return;
    }

    terminalTasks.push({ id, label, status: normalizeTerminalTaskStatus(status), note });
    renderTerminalTasks();
}

/**
 * Met à jour le status d'une tâche
 */
function updateTerminalTask(id, status, note, label) {
    const task = terminalTasks.find(t => t.id === id);
    if (task) {
        task.status = normalizeTerminalTaskStatus(status);
        if (typeof note === 'string' && note.trim()) task.note = note.trim();
        if (typeof label === 'string' && label.trim()) task.label = label.trim();
        renderTerminalTasks();
    }
}

/**
 * Render la liste des tâches
 */
function renderTerminalTasks() {
    if (!terminalTasksElement) return;

    const list = terminalTasksElement.querySelector('.terminal-tasks-list');
    const count = terminalTasksElement.querySelector('.tasks-count');

    const done = terminalTasks.filter(t => t.status === 'done').length;
    const total = terminalTasks.length;
    count.textContent = terminalT('terminal.taskCount', '{done}/{total} tâches', { done, total });

    list.innerHTML = terminalTasks.map(task => {
        let iconName = 'square';
        let className = 'task-pending';
        if (task.status === 'running') {
            iconName = 'loader-2';
            className = 'task-running';
        } else if (task.status === 'done') {
            iconName = 'check';
            className = 'task-done';
        } else if (task.status === 'error') {
            iconName = 'x';
            className = 'task-error';
        }
        const note = task.note ? `<div class="terminal-task-note">${escapeHtml(task.note)}</div>` : '';
        return `
            <div class="terminal-task ${className}">
                <i data-lucide="${iconName}" class="task-icon ${task.status === 'running' ? 'spin' : ''}"></i>
                <div class="terminal-task-body">
                    <span>${escapeHtml(task.label)}</span>
                    ${note}
                </div>
            </div>
        `;
    }).join('');
    if (window.lucide) lucide.createIcons();

    refreshTerminalProgressLayout();
}

/**
 * Cache la barre de tâches
 */
function hideTerminalTasks() {
    if (terminalTasksElement) {
        terminalTasksElement.remove();
        terminalTasksElement = null;
    }
    terminalTasks = [];
    refreshTerminalProgressLayout();
}

/**
 * Toggle l'affichage des tâches
 */
function toggleTerminalTasks() {
    if (!terminalTasksElement) return;
    terminalTasksElement.classList.toggle('collapsed');
}

// ===== TERMINAL OUTPUT (streaming sans bubble) =====
let terminalOutputElement = null;
let terminalOutputRawText = '';

/**
 * Crée un élément pour afficher la réponse terminal en streaming
 * @returns {HTMLElement} L'élément créé
 */
function createTerminalOutput() {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return null;

    terminalOutputRawText = '';
    const messageEl = document.createElement('div');
    messageEl.className = 'message terminal-chat-message terminal-ai-message';
    messageEl.innerHTML = `
        <div class="ai-response">
            <div class="chat-bubble terminal-ai-output"><span class="cursor">|</span></div>
        </div>
    `;
    messagesDiv.appendChild(messageEl);
    terminalOutputElement = messageEl.querySelector('.terminal-ai-output');
    scrollToBottom(true);
    return terminalOutputElement;
}

/**
 * Ajoute du texte à la sortie terminal en streaming
 * @param {string} text - Texte à ajouter
 */
function appendTerminalOutput(text) {
    if (!terminalOutputElement) return;
    terminalOutputRawText += text;

    // Formater avec markdown basique et curseur
    let formatted = formatTerminalMarkdown(terminalOutputRawText);
    terminalOutputElement.innerHTML = formatted + '<span class="cursor">|</span>';
    scrollToBottom(true);
}

/**
 * Retourne un indicateur de vitesse basé sur le temps de réponse
 * @param {number} responseTime - Temps en ms
 * @returns {string} Indicateur de vitesse
 */
function getSpeedIndicator(responseTime) {
    const seconds = responseTime / 1000;
    if (seconds < 3) return 'ultra rapide';
    if (seconds < 6) return 'rapide';
    if (seconds < 12) return 'normal';
    if (seconds < 25) return 'lent';
    return 'très lent';
}

/**
 * Finalise la sortie terminal (retire le curseur, ajoute stats)
 * @param {number} responseTime - Temps de réponse en ms
 * @param {Object} tokenStats - Stats de tokens
 */
function finalizeTerminalOutput(responseTime, tokenStats) {
    if (!terminalOutputElement) return;

    // Retirer le curseur
    let formatted = formatTerminalMarkdown(terminalOutputRawText);
    terminalOutputElement.innerHTML = formatted;

    // Ajouter les stats
    if (responseTime || tokenStats) {
        const statsEl = document.createElement('div');
        statsEl.className = 'terminal-line terminal-dim';
        statsEl.style.marginTop = '8px';

        let statsText = '';
        if (responseTime) {
            const timeStr = `${(responseTime/1000).toFixed(1)}s`;
            const speedStr = getSpeedIndicator(responseTime);
            statsText += `${timeStr} - ${speedStr}`;
        }
        if (tokenStats?.total) statsText += ` · ${tokenStats.total} tokens`;
        statsEl.textContent = statsText;
        terminalOutputElement.parentNode.insertBefore(statsEl, terminalOutputElement.nextSibling);
    }

    terminalOutputElement = null;
    scrollToBottom(true);
}

/**
 * Ajoute un bloc de code au terminal (pour les sorties bash, etc.)
 * @param {string} code - Code à afficher
 * @param {string} lang - Langage (optionnel)
 */
function addTerminalCodeBlock(code, lang = '') {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;

    const codeBlock = document.createElement('div');
    codeBlock.className = 'terminal-code-block';
    codeBlock.innerHTML = `<pre><code>${escapeHtml(code)}</code></pre>`;
    messagesDiv.appendChild(codeBlock);
    scrollToBottom(true);
}

// escapeHtml() défini dans utils.js (chargé avant terminal.js)

/**
 * Formatage pour le terminal - style propre avec gras et tirets
 * Filtre aussi la syntaxe des tool calls (affichée séparément par addToolCall)
 */
function formatTerminalMarkdown(text) {
    const cleanedText = typeof sanitizeAssistantToolTraceText === 'function'
        ? sanitizeAssistantToolTraceText(text)
        : String(text || '');
    // Échapper le HTML
    let formatted = cleanedText
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // === FILTRER LA SYNTAXE DES TOOL CALLS ===
    // Ces patterns sont affichés séparément via addToolCall/addToolResult
    // Format: [ACTION: target] ou [ACTION:] ou [/ACTION]

    // Tool calls simples: [READ_FILE: chemin], [SEARCH: pattern], etc.
    formatted = formatted.replace(/\[READ_FILE:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[LIST_FILES:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[SEARCH:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[GLOB:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[EXPLORE:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[BASH:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[DELETE_FILE:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[CREATE_PLAN:\s*[^\]]*\]/gi, '');
    formatted = formatted.replace(/\[UPDATE_PLAN:\s*[^\]]*\]/gi, '');

    // Tool calls avec contenu: [WRITE_FILE: chemin]...[/WRITE_FILE]
    formatted = formatted.replace(/\[WRITE_FILE:\s*[^\]]*\][\s\S]*?\[\/WRITE_FILE\]/gi, '');
    formatted = formatted.replace(/\[EDIT_FILE:\s*[^\]]*\][\s\S]*?\[\/EDIT_FILE\]/gi, '');

    // Tags de fermeture orphelins
    formatted = formatted.replace(/\[\/WRITE_FILE\]/gi, '');
    formatted = formatted.replace(/\[\/EDIT_FILE\]/gi, '');

    // Tool calls partiels (streaming incomplet)
    formatted = formatted.replace(/\[WRITE_FILE:\s*[^\]]*\][\s\S]*$/gi, '');
    formatted = formatted.replace(/\[EDIT_FILE:\s*[^\]]*\][\s\S]*$/gi, '');

    const codeBlocks = [];
    formatted = formatted.replace(/```([a-zA-Z0-9_+-]*)[ \t]*\n?([\s\S]*?)```/g, (_, lang = '', code = '') => {
        const token = `@@TERMINAL_CODE_BLOCK_${codeBlocks.length}@@`;
        const safeLang = String(lang || '').trim().replace(/[^a-zA-Z0-9_+-]/g, '');
        const classAttr = safeLang ? ` class="language-${safeLang}"` : '';
        codeBlocks.push({
            token,
            html: `<pre><code${classAttr}>${String(code || '').replace(/^\n|\n$/g, '')}</code></pre>`
        });
        return token;
    });

    // Virer les ● que l'IA met dans son texte (réservé aux tool calls système)
    formatted = formatted.replace(/^●\s*/gm, '');
    formatted = formatted.replace(/\n●\s*/g, '\n');

    // Virer les ⎿ aussi (réservé aux résultats système)
    formatted = formatted.replace(/^⎿\s*/gm, '');
    formatted = formatted.replace(/\n⎿\s*/g, '\n');

    // Garder **gras** -> <strong>
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Virer le reste du markdown, en gardant les vrais blocs/inline code lisibles.
    // *italic* -> texte normal
    formatted = formatted.replace(/\*([^*]+)\*/g, '$1');
    // `code` -> badge code inline
    formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
    // # headers -> texte
    formatted = formatted.replace(/^#{1,6}\s+/gm, '');
    // > quotes -> texte
    formatted = formatted.replace(/^&gt;\s*/gm, '');
    // [text](url) -> text
    formatted = formatted.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    // --- separateurs -> ligne vide
    formatted = formatted.replace(/^-{3,}$/gm, '');

    // Nettoyer les lignes vides multiples
    formatted = formatted.replace(/(<br>\s*){3,}/g, '<br><br>');
    // Nettoyer le début et la fin
    formatted = formatted.replace(/^(<br>\s*)+/, '');
    formatted = formatted.replace(/(<br>\s*)+$/, '');

    // Line breaks
    formatted = formatted.replace(/\n/g, '<br>');

    for (const block of codeBlocks) {
        formatted = formatted.replace(block.token, block.html);
    }

    return formatted;
}

// ===== VISION MODELS =====
// Modèles Ollama qui supportent les images (llava, moondream, etc.)
// Note: VISION_MODELS et DEFAULT_VISION_MODEL sont définis dans state.js

/**
 * Liste des mots-clés pour identifier les modèles vision
 * (Utilisé pour filtrer les modèles dans le picker)
 */
const VISION_MODEL_KEYWORDS = ['llava', 'moondream', 'bakllava', 'minicpm-v', 'llava-llama3', 'llava-phi3'];

/**
 * Trouve un modèle vision installé parmi les modèles Ollama
 * @returns {string|null} Le nom du modèle vision trouvé, ou null
 */
function findInstalledVisionModel() {
    if (!CHAT_MODELS || CHAT_MODELS.length === 0) return null;

    for (const model of CHAT_MODELS) {
        const modelName = model.id.toLowerCase();
        for (const keyword of VISION_MODEL_KEYWORDS) {
            if (modelName.includes(keyword)) {
                console.log('[TERMINAL/VISION] Modèle vision trouvé:', model.id);
                return model.id;
            }
        }
    }
    return null;
}

/**
 * Filtre les modèles vision depuis la liste des modèles chat
 * Utilisé pour l'onglet Vision du model picker en mode terminal
 * @returns {Array} Liste des modèles vision formatés pour le picker
 */
function getVisionModels() {
    if (!CHAT_MODELS || CHAT_MODELS.length === 0) return [];

    const visionModels = CHAT_MODELS.filter(model => {
        const modelName = model.id.toLowerCase();
        return VISION_MODEL_KEYWORDS.some(keyword => modelName.includes(keyword));
    }).map(model => ({
        ...model,
        badge: 'vision',
        icon: 'eye'
    }));

    // Si aucun modèle vision trouvé, proposer d'en télécharger un
    if (visionModels.length === 0) {
        return [{
            id: 'download-vision',
            name: 'Télécharger moondream',
            desc: 'Modèle vision léger (~1.7GB)',
            badge: 'download',
            icon: 'download'
        }];
    }

    return visionModels;
}

/**
 * Télécharge un modèle vision (moondream par défaut)
 * Appelé quand l'utilisateur clique sur "Télécharger" dans le picker
 */
async function downloadVisionModel() {
    const model = DEFAULT_VISION_MODEL;

    if (typeof Toast !== 'undefined') {
        Toast.info(terminalT('models.downloadingModel', 'Téléchargement de {model}...', { model }));
    }

    // Fermer le picker
    document.querySelectorAll('.model-picker').forEach(p => p.classList.remove('open'));

    try {
        const result = await apiOllama.pull(model);
        if (result.ok) {
            if (typeof Toast !== 'undefined') {
                Toast.success(terminalT('models.modelInstalled', '{model} installé !', { model }));
            }

            // Rafraîchir la liste des modèles
            if (typeof loadTextModelsForPicker === 'function') {
                await loadTextModelsForPicker();
            }

            // Sélectionner le nouveau modèle
            selectedVisionModel = model;
            Settings.set('selectedVisionModel', model);
            terminalVisionModel = model;
        } else {
            if (typeof Toast !== 'undefined') {
                Toast.error(terminalT('common.errorWithMessage', 'Erreur : {error}', { error: result.error }));
            }
        }
    } catch (err) {
        console.error('[TERMINAL/VISION] Erreur téléchargement:', err);
        if (typeof Toast !== 'undefined') {
            Toast.error(terminalT('models.downloadError', 'Erreur de téléchargement'));
        }
    }
}

// TOOL_CAPABLE_KEYWORDS, TOOL_EXCLUDED_KEYWORDS, TOOL_TOO_SMALL_SIZES,
// isToolCapableModel(), isToolCapableModelStrict() defined in state.js

/**
 * Trouve un modèle tool-capable installé (minimum 7B)
 * @returns {string|null} Le nom du modèle trouvé, ou null
 */
function findInstalledToolCapableModel() {
    if (!CHAT_MODELS || CHAT_MODELS.length === 0) return null;

    for (const model of CHAT_MODELS) {
        if (isToolCapableModelStrict(model.id)) {
            console.log('[TERMINAL] Modèle tool-capable trouvé:', model.id);
            return model.id;
        }
    }
    return null;
}

// Variable pour le modèle terminal actif
let terminalToolModel = null;
let terminalInputLocked = false;
let terminalApprovalRequest = null;

function terminalUsesCloudModel(modelId) {
    return typeof isTerminalCloudModelId === 'function' && isTerminalCloudModelId(modelId);
}

function getActiveCloudChatModel() {
    const chatModel = userSettings?.chatModel;
    return terminalUsesCloudModel(chatModel) ? chatModel : null;
}

function getTerminalTextModelForRequest() {
    const activeCloudChatModel = getActiveCloudChatModel();
    if (activeCloudChatModel && (!terminalToolModel || !terminalUsesCloudModel(terminalToolModel))) {
        if (terminalToolModel && terminalToolModel !== activeCloudChatModel) {
            console.log('[TERMINAL] Modèle cloud chat prioritaire pour la requête:', activeCloudChatModel);
        }
        terminalToolModel = activeCloudChatModel;
        return activeCloudChatModel;
    }
    return terminalToolModel || userSettings?.terminalModel || userSettings?.chatModel || 'qwen3.5:2b';
}

const TERMINAL_PERMISSION_MODES = new Set(['default', 'full_access']);

function normalizeTerminalPermissionMode(mode) {
    const normalized = String(mode || 'default').trim().toLowerCase().replace('-', '_');
    return TERMINAL_PERMISSION_MODES.has(normalized) ? normalized : 'default';
}

function getTerminalPermissionMode() {
    return normalizeTerminalPermissionMode(userSettings?.terminalPermissionMode);
}

function getTerminalPermissionLabel(mode = getTerminalPermissionMode()) {
    return normalizeTerminalPermissionMode(mode) === 'full_access'
        ? terminalT('terminal.permissions.fullAccess', 'Accès complet')
        : terminalT('terminal.permissions.default', 'Autorisations par défaut');
}

function updateTerminalPermissionButton() {
    const mode = getTerminalPermissionMode();
    const picker = document.getElementById('terminal-permission-picker');
    const button = document.getElementById('terminal-permission-btn');
    const label = document.getElementById('terminal-permission-label');
    const defaultLabel = document.getElementById('terminal-permission-default-label');
    const fullLabel = document.getElementById('terminal-permission-full-label');

    if (picker) picker.dataset.mode = mode;
    if (button) {
        button.setAttribute('aria-expanded', picker?.classList.contains('open') ? 'true' : 'false');
        button.setAttribute('title', getTerminalPermissionLabel(mode));
        button.setAttribute('aria-label', terminalT('terminal.permissions.label', 'Autorisations'));
    }
    if (label) label.textContent = getTerminalPermissionLabel(mode);
    if (defaultLabel) defaultLabel.textContent = terminalT('terminal.permissions.default', 'Autorisations par défaut');
    if (fullLabel) fullLabel.textContent = terminalT('terminal.permissions.fullAccess', 'Accès complet');

    document.querySelectorAll('.terminal-permission-option').forEach(option => {
        const optionMode = normalizeTerminalPermissionMode(option.dataset.permissionMode);
        option.setAttribute('aria-checked', optionMode === mode ? 'true' : 'false');
    });
}

function closeTerminalPermissionMenu() {
    const picker = document.getElementById('terminal-permission-picker');
    const button = document.getElementById('terminal-permission-btn');
    if (picker) picker.classList.remove('open');
    if (button) button.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', closeTerminalPermissionMenuOnOutsideClick);
}

function closeTerminalPermissionMenuOnOutsideClick(event) {
    const picker = document.getElementById('terminal-permission-picker');
    if (!picker || picker.contains(event.target)) return;
    closeTerminalPermissionMenu();
}

function toggleTerminalPermissionMenu(event) {
    if (event?.stopPropagation) event.stopPropagation();
    const picker = document.getElementById('terminal-permission-picker');
    if (!picker) return;

    const isOpen = picker.classList.toggle('open');
    const button = document.getElementById('terminal-permission-btn');
    if (button) button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) {
        setTimeout(() => document.addEventListener('click', closeTerminalPermissionMenuOnOutsideClick), 0);
    } else {
        document.removeEventListener('click', closeTerminalPermissionMenuOnOutsideClick);
    }
}

function selectTerminalPermissionMode(mode, event) {
    if (event?.stopPropagation) event.stopPropagation();
    userSettings.terminalPermissionMode = normalizeTerminalPermissionMode(mode);
    if (typeof saveSettings === 'function') saveSettings();
    updateTerminalPermissionButton();
    closeTerminalPermissionMenu();
}

function formatTerminalApprovalAction(action) {
    const map = {
        clear_workspace: 'ClearWorkspace',
        delete_file: 'Delete',
        bash: 'Bash',
        write_file: 'Write',
        write_files: 'WriteFiles',
        edit_file: 'Edit',
    };
    return map[action] || String(action || 'Tool');
}

function summarizeTerminalApprovalArgs(args = {}) {
    const safeArgs = {};
    Object.entries(args || {}).forEach(([key, value]) => {
        if (key === 'content') {
            safeArgs[key] = terminalT('terminal.approvalLargeContent', '[contenu]');
        } else if (key === 'files' && Array.isArray(value)) {
            safeArgs[key] = terminalT('terminal.approvalFileCount', '{count} fichiers', { count: value.length });
        } else if (typeof value === 'string' && value.length > 140) {
            safeArgs[key] = `${value.slice(0, 137)}...`;
        } else {
            safeArgs[key] = value;
        }
    });

    try {
        return JSON.stringify(safeArgs);
    } catch (_err) {
        return '';
    }
}

function formatTerminalApprovalCommand(request = {}) {
    const action = request.action || request.tool_name || 'tool';
    if (action === 'clear_workspace') {
        return 'clear_workspace({ keep: [] })';
    }
    if (action === 'bash' && request.args?.command) {
        return request.args.command;
    }
    const target = request.path || request.args?.path || summarizeTerminalApprovalArgs(request.args);
    return `${action}(${target || ''})`;
}

function closeTerminalApprovalCard() {
    document.querySelectorAll('.terminal-approval-card').forEach(card => card.remove());
    document.querySelectorAll('.chat-input-bar.terminal-approval-active').forEach(bar => {
        bar.classList.remove('terminal-approval-active');
    });
    if (typeof updateComposerAttachmentState === 'function') {
        updateComposerAttachmentState();
    }
    if (typeof updateChatPadding === 'function') {
        updateChatPadding();
    }
}

function showTerminalApprovalCard(request = {}) {
    closeTerminalApprovalCard();
    hideTerminalProgressPanel();
    terminalApprovalRequest = { ...request };

    const inputBar = document.querySelector('#chat-view .chat-input-bar') || document.querySelector('.chat-input-bar');
    if (!inputBar) return;
    inputBar.classList.add('terminal-approval-active');

    const actionLabel = formatTerminalApprovalAction(terminalApprovalRequest.action);
    const commandText = formatTerminalApprovalCommand(terminalApprovalRequest);
    const reason = terminalApprovalRequest.reason || terminalApprovalRequest.permission?.reason || '';

    const card = document.createElement('div');
    card.className = 'terminal-approval-card terminal-approval-composer';
    card.innerHTML = `
        <div class="terminal-approval-head">
            <span class="terminal-approval-icon"><i data-lucide="shield-alert"></i></span>
            <div>
                <div class="terminal-approval-title">${escapeHtml(terminalT('terminal.approvalTitle', 'Autorisation requise'))}</div>
                <div class="terminal-approval-question">${escapeHtml(terminalT('terminal.approvalQuestion', 'Autoriser JoyBoy à exécuter cette action avec accès complet ?'))}</div>
            </div>
        </div>
        <div class="terminal-approval-command-label">${escapeHtml(terminalT('terminal.approvalCommandLabel', 'Action'))}</div>
        <div class="terminal-approval-command"><span>${escapeHtml(actionLabel)}</span>${escapeHtml(commandText)}</div>
        ${reason ? `<div class="terminal-approval-reason">${escapeHtml(reason)}</div>` : ''}
        <div class="terminal-approval-options">
            <button type="button" class="terminal-approval-option" data-approval-action="once">
                <span>1.</span>
                <strong>${escapeHtml(terminalT('terminal.approvalAllowOnce', 'Oui, cette fois'))}</strong>
            </button>
            <button type="button" class="terminal-approval-option terminal-approval-danger" data-approval-action="remember">
                <span>2.</span>
                <strong>${escapeHtml(terminalT('terminal.approvalAllowRemember', 'Oui, passer en accès complet'))}</strong>
            </button>
            <button type="button" class="terminal-approval-option terminal-approval-muted" data-approval-action="deny">
                <span>3.</span>
                <strong>${escapeHtml(terminalT('terminal.approvalDeny', 'Non, annuler'))}</strong>
            </button>
        </div>
    `;

    card.querySelector('[data-approval-action="once"]')?.addEventListener('click', () => approveTerminalPermission(false));
    card.querySelector('[data-approval-action="remember"]')?.addEventListener('click', () => approveTerminalPermission(true));
    card.querySelector('[data-approval-action="deny"]')?.addEventListener('click', denyTerminalPermission);

    inputBar.insertBefore(card, inputBar.firstChild);
    if (window.lucide) lucide.createIcons();
    if (typeof updateComposerAttachmentState === 'function') {
        updateComposerAttachmentState();
    }
    if (typeof updateChatPadding === 'function') {
        updateChatPadding();
    }
}

function approveTerminalPermission(remember = false) {
    const request = terminalApprovalRequest;
    if (!request?.message) return;

    terminalApprovalRequest = null;
    closeTerminalApprovalCard();

    if (remember) {
        userSettings.terminalPermissionMode = 'full_access';
        if (typeof saveSettings === 'function') saveSettings();
        updateTerminalPermissionButton();
    }

    const rerunApprovedRequest = () => {
        if (terminalWorking || isGenerating) {
            setTimeout(rerunApprovedRequest, 80);
            return;
        }
        streamTerminalChat(request.message, true, { permissionMode: 'full_access' });
    };

    rerunApprovedRequest();
}

function denyTerminalPermission() {
    terminalApprovalRequest = null;
    closeTerminalApprovalCard();
    addTerminalLine(terminalT('terminal.approvalDeniedLine', 'Action annulée.'), 'warning');
    refocusChatInput();
}

// ===== TERMINAL INPUT LOCK =====

/**
 * Verrouille l'input du terminal (pendant téléchargement)
 */
function lockTerminalInput(reason = terminalT('terminal.inputDownloadInProgress', 'Téléchargement en cours...')) {
    terminalInputLocked = true;
    const input = document.getElementById('chat-prompt');
    const sendBtn = document.getElementById('send-btn');

    if (input) {
        input.disabled = true;
        input.placeholder = reason;
        input.classList.add('terminal-locked');
    }
    if (sendBtn) {
        sendBtn.disabled = true;
    }
}

/**
 * Déverrouille l'input du terminal
 */
function unlockTerminalInput() {
    terminalInputLocked = false;
    const input = document.getElementById('chat-prompt');
    const sendBtn = document.getElementById('send-btn');

    if (input) {
        input.disabled = false;
        input.placeholder = terminalT('terminal.inputReady', 'Que veux-tu faire ?');
        input.classList.remove('terminal-locked');
    }
    if (sendBtn) {
        sendBtn.disabled = false;
    }
}

// ===== TERMINAL DOWNLOAD UI =====

/**
 * Affiche la barre de progression du téléchargement
 */
function showTerminalDownloadProgress(model) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;

    // Supprimer l'ancienne barre si elle existe
    const existing = document.getElementById('terminal-download-progress');
    if (existing) existing.remove();

    const progressHtml = `
        <div id="terminal-download-progress" class="terminal-download-box">
            <div class="terminal-download-header">
                <span class="terminal-download-icon"><i data-lucide="download"></i></span>
                <span class="terminal-download-title">${escapeHtml(terminalT('terminal.downloadRequiredTitle', 'Téléchargement requis'))}</span>
            </div>
            <div class="terminal-download-model">${model}</div>
            <div class="terminal-download-bar">
                <div class="terminal-download-fill" style="width: 0%"></div>
            </div>
            <div class="terminal-download-status">${escapeHtml(terminalT('terminal.connectionStatus', 'Connexion...'))}</div>
            <div class="terminal-download-hint">${escapeHtml(terminalT('terminal.downloadHint', 'Ce modèle est nécessaire pour le mode terminal. Ne ferme pas cette page.'))}</div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', progressHtml);
    scrollToBottom(true);
}

/**
 * Met à jour la progression du téléchargement
 */
function updateTerminalDownloadProgress(progress, status) {
    const fill = document.querySelector('#terminal-download-progress .terminal-download-fill');
    const statusEl = document.querySelector('#terminal-download-progress .terminal-download-status');

    if (fill) {
        fill.style.width = `${progress}%`;
    }
    if (statusEl) {
        statusEl.textContent = status || `${progress}%`;
    }

    // Sauvegarder l'état
    terminalDownloadState.progress = progress;
    terminalDownloadState.status = status;
    saveTerminalDownloadState();
}

/**
 * Cache la barre de progression
 */
function hideTerminalDownloadProgress(success = true) {
    const progressBox = document.getElementById('terminal-download-progress');
    if (progressBox) {
        if (success) {
            progressBox.innerHTML = `
                <div class="terminal-download-header">
                    <span class="terminal-download-icon"><i data-lucide="check-circle"></i></span>
                    <span class="terminal-download-title">${escapeHtml(terminalT('terminal.modelInstalledTitle', 'Modèle installé !'))}</span>
                </div>
            `;
            if (window.lucide) lucide.createIcons();
            setTimeout(() => progressBox.remove(), 2000);
        } else {
            progressBox.remove();
        }
    }
    clearTerminalDownloadState();
}

/**
 * Télécharge un modèle avec UI de progression
 */
async function downloadTerminalModelWithProgress(model) {
    // Sauvegarder l'état pour F5
    terminalDownloadState = {
        isDownloading: true,
        model: model,
        progress: 0,
        status: terminalT('terminal.downloadStarting', 'Démarrage...'),
        startedAt: Date.now()
    };
    saveTerminalDownloadState();

    // Verrouiller l'input
    lockTerminalInput(terminalT('terminal.downloadModel', 'Téléchargement de {model}...', { model }));

    // Afficher la UI
    showTerminalDownloadProgress(model);

    try {
        const response = await fetch('/ollama/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const data = JSON.parse(line);

                    if (data.total && data.completed) {
                        const progress = Math.round((data.completed / data.total) * 100);
                        const status = data.status || `${progress}%`;
                        updateTerminalDownloadProgress(progress, status);
                    } else if (data.status) {
                        updateTerminalDownloadProgress(
                            terminalDownloadState.progress,
                            data.status
                        );
                    }

                    if (data.error) {
                        throw new Error(data.error);
                    }
                } catch (e) {
                    if (e.message && !e.message.includes('JSON')) {
                        throw e;
                    }
                }
            }
        }

        // Succès
        hideTerminalDownloadProgress(true);
        unlockTerminalInput();

        // Rafraîchir les modèles
        if (typeof loadTextModelsForPicker === 'function') {
            await loadTextModelsForPicker();
        }

        return { ok: true };

    } catch (err) {
        console.error('[TERMINAL] Erreur téléchargement:', err);
        hideTerminalDownloadProgress(false);
        unlockTerminalInput();
        addTerminalLine(terminalT('terminal.downloadErrorLine', 'Erreur : {error}', { error: err.message }), 'error');
        addTerminalLine(terminalT('terminal.manualInstallLine', 'Installe manuellement : ollama pull {model}', { model }), 'code');
        return { ok: false, error: err.message };
    }
}

// ===== TERMINAL MODE LIFECYCLE =====

function isTerminalWorkspaceRecord(record) {
    return record?.mode === 'terminal' && !!record.workspace?.path;
}

function terminalChatTitle(workspace) {
    const name = workspace?.name || workspace?.path || 'workspace';
    return name;
}

function setTerminalBodyState(active, workspace = null) {
    terminalMode = !!active;
    terminalWorkspace = terminalMode ? workspace : null;
    document.body.classList.toggle('terminal-mode', terminalMode);

    const wsNameEl = document.getElementById('terminal-workspace-name');
    if (wsNameEl) {
        wsNameEl.textContent = terminalMode
            ? (workspace?.name || workspace?.path || 'Workspace')
            : terminalT('terminal.noWorkspace', 'Aucun workspace');
    }

    if (typeof updateModelPickerDisplay === 'function') {
        updateModelPickerDisplay();
    }

    updateTerminalPermissionButton();
}

window.addEventListener('joyboy:locale-changed', () => {
    setTerminalBodyState(terminalMode, terminalWorkspace);
    updateTerminalPermissionButton();
});

document.addEventListener('DOMContentLoaded', () => {
    updateTerminalPermissionButton();
});

function applyTerminalChatState(record = null) {
    if (isTerminalWorkspaceRecord(record)) {
        setTerminalBodyState(true, record.workspace);
    } else {
        setTerminalBodyState(false, null);
    }
}

async function openTerminalWorkspacePicker(pendingMessage = '') {
    openProjectLauncher(pendingMessage);
}

/**
 * Active le mode dev/workspace.
 * On refuse volontairement l'activation sans workspace: un agent qui lit/écrit
 * des fichiers sans racine projet claire finit par appeler list_files('.') en
 * boucle ou toucher le mauvais dossier.
 * @param {Object|null} workspace - Workspace à utiliser {name, path}
 */
async function enterTerminalMode(workspace = null, pendingMessage = '') {
    if (!workspace?.path) {
        await openTerminalWorkspacePicker(pendingMessage);
        return;
    }

    rememberTerminalWorkspace(workspace);
    closeProjectLauncher();
    setTerminalBodyState(true, workspace);

    // ===== TERMINAL MODE: Arrêter TOUT et vider la queue =====
    // Quand on entre en mode terminal:
    // 1. Toutes les générations en cours sont annulées
    // 2. La queue globale est vidée (terminal = workspace isolé)
    // 3. La VRAM est libérée pour le modèle terminal

    console.log('[TERMINAL] Entrée en mode terminal - clear all générations');

    // Tout arrêter et vider la queue
    clearQueue();
    if (typeof cancelCurrentGenerations === 'function') {
        await cancelCurrentGenerations();
    }
    try {
        await fetch('/models/unload-all', { method: 'POST' });
    } catch (e) {
        console.error('[TERMINAL] Erreur déchargement modèles:', e);
    }

    // Créer une conversation dev explicite: le mode terminal ne vit plus dans
    // un état global flottant, il est attaché au workspace de ce chat.
    await createNewChat({
        mode: 'terminal',
        workspace,
        title: terminalChatTitle(workspace)
    });

    // Ouvrir le chat
    showChat();
    setTerminalBodyState(true, workspace);

    // Réinitialiser les stats de tokens pour la nouvelle session terminal
    if (typeof resetTokenStats === 'function') {
        resetTokenStats();
    }

    // === VÉRIFIER SI UN TÉLÉCHARGEMENT ÉTAIT EN COURS (F5) ===
    if (loadTerminalDownloadState() && terminalDownloadState.isDownloading) {
        console.log('[TERMINAL] Reprise du téléchargement après F5:', terminalDownloadState.model);
        addTerminalLine(terminalT('terminal.resumeDownload', 'Reprise du téléchargement de {model}...', { model: terminalDownloadState.model }), 'info');

        const result = await downloadTerminalModelWithProgress(terminalDownloadState.model);
        if (result.ok) {
            terminalToolModel = terminalDownloadState.model;
        }
    }

    // === VÉRIFIER ET TÉLÉCHARGER UN MODÈLE TOOL-CAPABLE ===
    let toolModel = null;
    const activeCloudChatModel = getActiveCloudChatModel();

    // 1. Vérifier si l'utilisateur a choisi un modèle dans les settings
    const savedTerminalModel = userSettings?.terminalModel;
    if (savedTerminalModel) {
        // Vérifier si ce modèle est installé ou si c'est un profil cloud configuré.
        const savedTerminalIsCloud = terminalUsesCloudModel(savedTerminalModel);
        const savedTerminalIsLocal = CHAT_MODELS?.some(m => m.id === savedTerminalModel);
        if (savedTerminalIsCloud) {
            console.log('[TERMINAL] Utilisation du modèle configuré:', savedTerminalModel);
            toolModel = savedTerminalModel;
        } else if (activeCloudChatModel) {
            console.log('[TERMINAL] Modèle chat cloud prioritaire sur le terminal local:', activeCloudChatModel);
        } else if (savedTerminalIsLocal) {
            console.log('[TERMINAL] Utilisation du modèle configuré:', savedTerminalModel);
            toolModel = savedTerminalModel;
        } else {
            console.log('[TERMINAL] Modèle configuré non installé:', savedTerminalModel);
        }
    }

    // 2. Sinon, reprendre le modèle cloud déjà choisi dans le chat.
    if (!toolModel) {
        if (activeCloudChatModel) {
            console.log('[TERMINAL] Utilisation du modèle cloud chat actif:', activeCloudChatModel);
            toolModel = activeCloudChatModel;
        }
    }

    // 3. Sinon, auto-détecter un modèle tool-capable local
    if (!toolModel) {
        toolModel = findInstalledToolCapableModel();
    }

    // 4. Si aucun trouvé, télécharger le défaut
    if (!toolModel) {
        console.log('[TERMINAL] Aucun modèle tool-capable, téléchargement de', DEFAULT_TERMINAL_MODEL);

        addTerminalLine(``, 'blank');
        addTerminalLine(terminalT('terminal.requiredModelTitle', 'Modèle terminal requis'), 'warning');
        addTerminalLine(terminalT('terminal.requiredModelBody', 'Le mode terminal nécessite un modèle capable de lire/écrire des fichiers.'), 'dim');
        addTerminalLine(``, 'blank');

        const result = await downloadTerminalModelWithProgress(DEFAULT_TERMINAL_MODEL);

        if (result.ok) {
            toolModel = DEFAULT_TERMINAL_MODEL;
            addTerminalLine(terminalT('terminal.modelReadyLine', 'Modèle {model} prêt !', { model: DEFAULT_TERMINAL_MODEL }), 'success');
        } else {
            addTerminalLine(``, 'blank');
            addTerminalLine(terminalT('terminal.limitedWithoutModel', 'Le mode terminal est limité sans ce modèle.'), 'warning');
        }
    }

    // Sauvegarder le modèle tool-capable pour ce mode
    terminalToolModel = toolModel;
    if (typeof tokenStats !== 'undefined' && typeof getTerminalEffectiveContextSize === 'function') {
        tokenStats.maxContextSize = getTerminalEffectiveContextSize(toolModel);
    }

    if (toolModel) {
        if (terminalUsesCloudModel(toolModel)) {
            addTerminalLine(terminalT('terminal.cloudModelReady', 'LLM cloud prêt : {model}', { model: toolModel }), 'success');
        } else {
            // D'abord décharger tous les autres modèles Ollama pour libérer la VRAM
            console.log('[TERMINAL] Déchargement des modèles existants...');
            await apiModels.unloadAll();

            // Précharger le modèle tool-capable avec loading animé
            const loadingEl = showTerminalLoading(terminalT('terminal.loadingModel', 'Chargement de {model}...', { model: toolModel }));
            const warmupResult = await apiOllama.warmup(toolModel, true);
            if (warmupResult.ok) {
                // Affiche "Prêt !" puis disparaît avec animation
                await hideTerminalLoading(loadingEl, terminalT('terminal.readyModel', 'Prêt ! Modèle : {model}', { model: toolModel }));
            } else {
                // En cas d'erreur, juste supprimer le loading
                await hideTerminalLoading(loadingEl);
            }
        }
    }

    // Mettre à jour le model picker pour afficher le modèle terminal
    if (typeof updateModelPickerDisplay === 'function') {
        updateModelPickerDisplay();
    }

    // Mettre à jour l'affichage du contexte max
    updateTokensMaxDisplay();

    // Ré-initialiser les icônes Lucide
    if (window.lucide) lucide.createIcons();

    // Message de bienvenue - workspace déjà affiché dans le header
    if (pendingMessage) {
        await sendTerminalMessage(pendingMessage);
    } else if (workspace) {
        const welcome = terminalT('terminal.workspaceOpened', 'Projet **{name}** ouvert. Je travaille dans ce dossier.', { name: workspace.name || workspace.path });
        chatHistory.push({ role: 'assistant', content: welcome });
        addAiMessageToChat(welcome);
        persistCurrentChat({ html: getCurrentChatHtml(), messages: chatHistory })
            .catch(e => console.warn('[TERMINAL] Welcome persist failed:', e));
    } else {
        addTerminalLine(``, 'blank');
        addTerminalLine(terminalT('terminal.noWorkspaceSelected', 'Aucun workspace sélectionné.'), 'warning');
        addTerminalLine(terminalT('terminal.projectPrompt', 'Sur quel projet veux-tu travailler ?'), 'prompt');
    }

    scrollToBottom(true);

    console.log('[TERMINAL] Mode activé', workspace ? `(${workspace.name})` : '(pas de workspace)');
}

/**
 * Quitte le mode terminal
 */
function exitTerminalMode() {
    const activeRecord = (typeof chatRecordsCache !== 'undefined' && currentChatId)
        ? chatRecordsCache.find(record => record.id === currentChatId)
        : null;
    if (terminalWorkspace?.path || isTerminalWorkspaceRecord(activeRecord)) {
        console.warn('[TERMINAL] Exit ignored: project terminal chats stay bound to their workspace.');
        if (typeof Toast !== 'undefined') {
            Toast.error(terminalT('terminal.projectModeLocked', 'L’espace de travail dev reste attaché à ce chat.'));
        }
        return;
    }

    const wasTerminalChat = terminalMode && currentChatId;
    setTerminalBodyState(false, null);
    terminalVisionModel = null;

    if (wasTerminalChat) {
        persistCurrentChat({ mode: 'chat', workspace: null })
            .catch(e => console.warn('[TERMINAL] Persist exit failed:', e));
    }

    addAiMessageToChat(terminalT('terminal.terminalDisabled', 'Mode terminal désactivé. Je redeviens JoyBoy normal !'));
    scrollToBottom(true);

    console.log('[TERMINAL] Mode désactivé');
}

/**
 * Interrompt le mode terminal (Ctrl+C)
 */
function interruptTerminal() {
    if (terminalWorking) {
        console.log('[TERMINAL] Ctrl+C - Interruption...');
        terminalInterrupted = true;
        if (currentController) {
            currentController.abort();
        }
    }
}

/**
 * Stop le chat terminal (appelé par le bouton stop)
 */
function stopTerminalChat() {
    console.log('[TERMINAL] Stop button pressed');
    terminalInterrupted = true;
    if (currentController) {
        currentController.abort();
        currentController = null;
    }
    terminalWorking = false;
    isGenerating = false;
    hideThinkingAnimation();
    setSendButtonsMode(false);

    // Hide autonomous indicator
    const autoIndicator = document.getElementById('autonomous-indicator');
    if (autoIndicator) autoIndicator.style.display = 'none';

    addTerminalLine(terminalT('terminal.interrupted', 'Génération interrompue.'), 'warning');
}

// ===== TERMINAL IMAGE HANDLING =====
// Gestion des images en mode terminal avec modèles vision

/**
 * Appelé quand une image est ajoutée en mode terminal
 * Utilise le modèle vision sélectionné ou auto-détecte
 */
async function onImageAddedTerminal() {
    console.log('[TERMINAL/VISION] Image ajoutée');

    // Utiliser le modèle sélectionné par l'utilisateur si disponible
    let visionModel = selectedVisionModel || findInstalledVisionModel();

    if (!visionModel) {
        // Aucun modèle vision installé -> proposer d'en télécharger un
        console.log('[TERMINAL/VISION] Aucun modèle vision, téléchargement de', DEFAULT_VISION_MODEL);

        addTerminalLine(terminalT('terminal.visionDownload', 'Téléchargement du modèle vision ({model})...', { model: DEFAULT_VISION_MODEL }), 'system');

        try {
            const result = await apiOllama.pull(DEFAULT_VISION_MODEL);
            if (result.ok) {
                visionModel = DEFAULT_VISION_MODEL;
                console.log('[TERMINAL/VISION] Modèle téléchargé:', visionModel);

                if (typeof loadTextModelsForPicker === 'function') {
                    await loadTextModelsForPicker();
                }

                addTerminalLine(terminalT('terminal.visionInstalled', 'Modèle {model} installé !', { model: DEFAULT_VISION_MODEL }), 'success');
            } else {
                console.error('[TERMINAL/VISION] Erreur téléchargement:', result.error);
                addTerminalLine(terminalT('terminal.visionManualInstall', 'Impossible de télécharger. Installe manuellement :'), 'error');
                addTerminalLine(`ollama pull ${DEFAULT_VISION_MODEL}`, 'code');
                return;
            }
        } catch (err) {
            console.error('[TERMINAL/VISION] Erreur téléchargement:', err);
            return;
        }
    }

    // Activer le modèle vision
    terminalVisionModel = visionModel;
    console.log('[TERMINAL/VISION] Activation:', visionModel);

    // Précharger le modèle vision
    const warmupResult = await apiOllama.warmup(visionModel, true);
    if (warmupResult.ok) {
        console.log('[TERMINAL/VISION] Modèle préchargé:', visionModel);

        // Mettre à jour l'affichage du modèle dans le header terminal
        const modelDisplay = document.querySelector('.terminal-header .model-picker-btn span');
        if (modelDisplay) {
            modelDisplay.textContent = typeof _formatModelName === 'function' ? _formatModelName(visionModel) : visionModel;
        }
    } else {
        console.error('[TERMINAL/VISION] Erreur préchargement:', warmupResult.error);
    }
}

/**
 * Appelé quand l'image est retirée en mode terminal
 * Restaure le modèle chat normal
 */
async function onImageRemovedTerminal() {
    if (!terminalVisionModel) return;

    console.log('[TERMINAL/VISION] Image retirée, restauration du modèle terminal');

    // Décharger le modèle vision
    await apiOllama.unload(terminalVisionModel);
    terminalVisionModel = null;

    // Recharger le modèle tool-capable (ou chat par défaut)
    const modelToReload = terminalToolModel || userSettings.chatModel || 'qwen3.5:2b';
    if (!terminalUsesCloudModel(modelToReload)) {
        await apiOllama.warmup(modelToReload, true);
    }

    // Restaurer l'affichage du modèle
    const modelDisplay = document.querySelector('.terminal-header .model-picker-btn span');
    if (modelDisplay) {
        modelDisplay.textContent = typeof _formatModelName === 'function' ? _formatModelName(modelToReload) : modelToReload;
    }
}

// ===== TERMINAL CHAT =====

let terminalPendingWorkspaceMessage = '';

function rememberTerminalWorkspace(workspace) {
    if (!workspace?.path) return;
    userSettings.workspaces = userSettings.workspaces || [];
    const existing = userSettings.workspaces.find(w => w.path === workspace.path);
    if (existing) {
        existing.name = workspace.name || existing.name || workspace.path;
    } else {
        userSettings.workspaces.push(workspace);
    }
    userSettings.activeWorkspace = workspace.path;
    if (typeof saveSettings === 'function') saveSettings();
    if (typeof renderWorkspacesList === 'function') renderWorkspacesList();
    if (typeof updateActiveWorkspaceUI === 'function') updateActiveWorkspaceUI();
}

function closeProjectLauncher() {
    document.querySelector('.project-launcher-overlay')?.remove();
}

function setProjectLauncherError(message = '') {
    const panel = document.querySelector('.project-launcher-panel');
    if (!panel) return;
    let errorEl = panel.querySelector('.project-launcher-error');
    if (!message) {
        errorEl?.remove();
        return;
    }
    if (!errorEl) {
        errorEl = document.createElement('div');
        errorEl.className = 'project-launcher-error';
        const anchor = panel.querySelector('.project-launcher-browse-btn') || panel.querySelector('.project-launcher-list');
        if (anchor) {
            anchor.before(errorEl);
        } else {
            panel.appendChild(errorEl);
        }
    }
    errorEl.textContent = message;
}

function openProjectLauncher(pendingMessage = '') {
    terminalPendingWorkspaceMessage = pendingMessage || '';
    closeProjectLauncher();

    const workspaces = userSettings.workspaces || [];
    const projectItems = workspaces.map((workspace, index) => `
        <button class="project-launcher-item" onclick="selectTerminalWorkspaceFromPicker(${index})">
            <i data-lucide="folder-code"></i>
            <span class="project-launcher-item-main">
                <span class="project-launcher-item-name">${escapeHtml(workspace.name || workspace.path)}</span>
                <span class="project-launcher-item-path">${escapeHtml(workspace.path)}</span>
            </span>
        </button>
    `).join('');

    const overlay = document.createElement('div');
    overlay.className = 'project-launcher-overlay';
    overlay.onclick = (event) => {
        if (event.target === overlay) closeProjectLauncher();
    };
    overlay.innerHTML = `
        <div class="project-launcher-panel" role="dialog" aria-modal="true" aria-label="${escapeHtml(terminalT('terminal.projectLauncherAria', 'Ouvrir un projet'))}">
            <div class="project-launcher-header">
                <div>
                    <div class="project-launcher-kicker">${escapeHtml(terminalT('terminal.projectLauncherKicker', 'Mode projet'))}</div>
                    <div class="project-launcher-title">${escapeHtml(terminalT('terminal.projectLauncherTitle', 'Ouvrir un projet'))}</div>
                </div>
                <button class="project-launcher-close" onclick="closeProjectLauncher()" title="${escapeHtml(terminalT('terminal.close', 'Fermer'))}">
                    <i data-lucide="x"></i>
                </button>
            </div>
            <div class="project-launcher-copy">
                ${escapeHtml(terminalT('terminal.projectLauncherCopy', 'Parcours tes dossiers pour créer une nouvelle conversation dev avec le nom du projet au-dessus.'))}
            </div>
            <div class="project-launcher-list">
                ${projectItems || `<div class="project-launcher-empty">${escapeHtml(terminalT('terminal.noSavedProjects', 'Aucun projet enregistré pour l’instant.'))}</div>`}
            </div>
            <button class="project-launcher-browse-btn" onclick="browseProjectFolder()">
                <i data-lucide="folder-open"></i>
                    ${escapeHtml(terminalT('terminal.chooseProjectFolder', 'Choisir un dossier de travail'))}
            </button>
        </div>
    `;

    document.body.appendChild(overlay);
    if (window.lucide) lucide.createIcons();
}

async function openWorkspaceConversation(workspace, pendingMessage = '') {
    if (!workspace?.path) {
        openProjectLauncher(pendingMessage);
        return;
    }
    await enterTerminalMode(workspace, pendingMessage);
}

async function browseProjectFolder() {
    setProjectLauncherError('');
    const button = document.querySelector('.project-launcher-browse-btn');
    const manualPath = (document.getElementById('project-launcher-path-input')?.value || '').trim();
    const previousHtml = button?.innerHTML;
    if (button) {
        button.disabled = true;
        button.innerHTML = `<i data-lucide="loader-2" class="spin"></i> ${escapeHtml(terminalT('terminal.selectingFolder', 'Sélection du dossier...'))}`;
        if (window.lucide) lucide.createIcons();
    }

    try {
        const response = await fetch('/workspace/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initial_dir: manualPath || userSettings?.activeWorkspace || '' })
        });
        const data = await response.json().catch(() => ({}));

        if (data.cancelled) return;
        if (!response.ok || !data.valid) {
            setProjectLauncherError(data.error || terminalT('terminal.folderSelectorError', 'Impossible d’ouvrir le sélecteur de dossier.'));
            return;
        }

        const workspace = { name: data.name, path: data.path };
        const pending = terminalPendingWorkspaceMessage;
        terminalPendingWorkspaceMessage = '';
        await openWorkspaceConversation(workspace, pending);
    } catch (err) {
        console.error('[TERMINAL] Erreur parcours dossier:', err);
        setProjectLauncherError(terminalT('terminal.folderSelectorErrorWithMessage', 'Impossible d’ouvrir le sélecteur de dossier : {error}', { error: err.message }));
    } finally {
        if (button) {
            button.disabled = false;
            button.innerHTML = previousHtml;
            if (window.lucide) lucide.createIcons();
        }
    }
}

function setTerminalWorkspace(workspace, persist = true) {
    setTerminalBodyState(!!workspace?.path, workspace || null);

    if (workspace?.path && !terminalToolModel) {
        const configuredTerminalModel = userSettings?.terminalModel;
        const activeCloudChatModel = getActiveCloudChatModel();
        const configuredCloudModel = configuredTerminalModel && terminalUsesCloudModel(configuredTerminalModel);
        const configuredLocalModel = configuredTerminalModel && CHAT_MODELS?.some(m => m.id === configuredTerminalModel);
        terminalToolModel = (configuredCloudModel ? configuredTerminalModel : null)
            || activeCloudChatModel
            || (configuredLocalModel ? configuredTerminalModel : null)
            || findInstalledToolCapableModel()
            || userSettings?.chatModel
            || 'qwen3.5:2b';
        if (typeof tokenStats !== 'undefined' && typeof getTerminalEffectiveContextSize === 'function') {
            tokenStats.maxContextSize = getTerminalEffectiveContextSize(terminalToolModel);
        }
    }

    if (workspace && persist) {
        rememberTerminalWorkspace(workspace);

        if (currentChatId) {
            // Le workspace est la frontière de sécurité du mode dev: on persiste
            // cette association pour que le chat se recharge comme un vrai chat Codex.
            persistCurrentChat({
                mode: 'terminal',
                workspace,
                title: terminalChatTitle(workspace)
            }).catch(e => console.warn('[TERMINAL] Workspace chat persist failed:', e));
        }
    }

    document.querySelector('.terminal-workspace-picker')?.remove();
    renderChatList();
}

async function selectTerminalWorkspaceFromPicker(index) {
    const workspace = (userSettings.workspaces || [])[index];
    if (!workspace) return;

    const pending = terminalPendingWorkspaceMessage;
    terminalPendingWorkspaceMessage = '';
    await openWorkspaceConversation(workspace, pending);
}

async function addTerminalWorkspaceFromPicker() {
    const input = document.getElementById('project-launcher-path-input') || document.getElementById('terminal-workspace-path-input');
    const path = (input?.value || '').trim();
    if (!path) {
        await browseProjectFolder();
        return;
    }

    try {
        const response = await fetch('/workspace/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const data = await response.json();
        if (!data.valid) {
            setProjectLauncherError(`Projet invalide: ${data.error || 'chemin illisible'}`);
            return;
        }

        const workspace = { name: data.name, path: data.path };
        const pending = terminalPendingWorkspaceMessage;
        terminalPendingWorkspaceMessage = '';
        await openWorkspaceConversation(workspace, pending);
    } catch (err) {
        console.error('[TERMINAL] Erreur validation workspace:', err);
        setProjectLauncherError(`Impossible de valider le workspace: ${err.message}`);
        if (typeof Toast !== 'undefined') {
            Toast.error(`Impossible de valider le workspace: ${err.message}`);
        }
    }
}

function showTerminalWorkspacePicker(pendingMessage = '') {
    openProjectLauncher(pendingMessage);
}

/**
 * Gère l'envoi de message en mode terminal
 * @param {string} message - Message de l'utilisateur
 */
async function sendTerminalMessage(message) {
    if (!message.trim()) return;

    // Ajouter à l'historique terminal
    addToTerminalHistory(message);

    // Si pas de workspace, on le choisit dans la conversation au lieu de
    // renvoyer l'utilisateur dans les paramètres. Ça évite le vieux flux où
    // JoyBoy tentait d'analyser sans racine projet claire puis bouclait.
    if (!terminalWorkspace) {
        openProjectLauncher(message);
        return;
    }

    // Envoyer au chat terminal
    await streamTerminalChat(message);
}

/**
 * Chat streaming en mode dev avec auto-continue.
 * Le rendu reste volontairement proche du chat normal; seuls les outils et le
 * workspace changent.
 * @param {string} message - Message à envoyer
 * @param {boolean} isAutoContinue - Si c'est un auto-continue après action workspace
 */
async function streamTerminalChat(message, isAutoContinue = false, options = {}) {
    if (isGenerating && !isAutoContinue) return;

    isGenerating = true;
    terminalWorking = true;
    terminalInterrupted = false;
    setSendButtonsMode(true);

    const permissionModeOverride = options.permissionMode
        ? normalizeTerminalPermissionMode(options.permissionMode)
        : null;
    const permissionModeForRequest = permissionModeOverride || getTerminalPermissionMode();

    // Ajouter le message utilisateur dans le rendu chat normal (pas de skeleton).
    if (!isAutoContinue) {
        addTerminalUserLine(message);
        chatHistory.push({ role: 'user', content: message });
    }

    const startTime = Date.now();
    let fullResponse = '';
    let outputElement = null;
    let firstContentReceived = false;
    let approvalRequiredThisTurn = false;

    try {
        const controller = new AbortController();
        currentController = controller;

        // Afficher l'animation de travail (pas de skeleton bubble)
        const analyzingLabel = terminalT('terminal.progressThinking', 'Analyse en cours');
        showThinkingAnimation(analyzingLabel);

        // Réinitialiser les tâches pour cette requête
        hideTerminalProgressPanel();
        hideTerminalTasks();
        beginTerminalProgressSession();
        resetTerminalActivitySummaries();
        addTerminalProgressLog(analyzingLabel, message, 'thinking');
        let taskCounter = 0;

        // Préparer l'image si présente (pour les modèles vision)
        let imageData = null;
        if (currentImage && !isAutoContinue) {
            imageData = currentImage.includes(',') ? currentImage.split(',')[1] : currentImage;
        }

        // Utiliser le modèle dans l'ordre de priorité:
        // 1. Vision model si image présente
        // 2. Tool-capable model qu'on a téléchargé/trouvé
        // 3. Modèle chat par défaut (fallback)
        const modelToUse = (imageData && terminalVisionModel)
            ? terminalVisionModel
            : getTerminalTextModelForRequest();
        const effectiveContextSize = typeof getTerminalEffectiveContextSize === 'function'
            ? getTerminalEffectiveContextSize(modelToUse)
            : (userSettings.contextSize || 8192);
        const reasoningEffort = typeof getTerminalReasoningEffort === 'function'
            ? getTerminalReasoningEffort(modelToUse)
            : null;

        const response = await fetch('/terminal/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chatId: currentChatId,
                message,
                image: imageData,
                history: chatHistory.slice(-20),
                workspace: terminalWorkspace,
                chatModel: modelToUse,
                contextSize: effectiveContextSize,
                reasoningEffort,
                permissionMode: permissionModeForRequest
            }),
            signal: controller.signal
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            if (errorData.code === 'workspace_required') {
                hideThinkingAnimation();
                showTerminalWorkspacePicker(message);
                isGenerating = false;
                terminalWorking = false;
                currentController = null;
                setSendButtonsMode(false);
                return;
            }
            throw new Error(errorData.message || errorData.error || `HTTP ${response.status}`);
        }

        // Effacer l'image après envoi et restaurer le modèle chat
        if (imageData && !isAutoContinue) {
            currentImage = null;
            updateImagePreviews();
            onImageRemovedTerminal();
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            if (terminalInterrupted) {
                console.log('[TERMINAL] Interrompu par Ctrl+C');
                break;
            }

            const text = decoder.decode(value);
            const lines = text.split('\n');

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;

                try {
                    const data = JSON.parse(line.slice(6));

                    // Debug: log tous les événements non-content reçus
                    const eventType = Object.keys(data)[0];
                    if (eventType !== 'content') {
                        console.log(`%c[TERMINAL] Event: ${eventType}`, 'color: #f59e0b; background: #1a1a1a; padding: 2px 6px; border-radius: 3px;', data);
                    }

                    // === BOUCLE AGENTIQUE - Nouveaux events ===

                    // Intent détecté - afficher mode autonome si actif
                    if (data.intent) {
                        console.log(`[TERMINAL] Intent: ${data.intent} (read_only: ${data.read_only}, autonomous: ${data.autonomous})`);
                        terminalProgressIntent = String(data.intent || '').toLowerCase();
                        const intentLabel = data.autonomous
                            ? terminalT('terminal.progressAutonomous', 'Mode autonome')
                            : terminalT('terminal.progressIntent', 'Intention détectée');
                        addTerminalProgressLog(intentLabel, data.intent, 'info');
                        if (data.autonomous) {
                            addTerminalTask('terminal-intent', describeTerminalIntentTask(terminalProgressIntent, data.autonomous), 'running');
                        }
                        if (data.autonomous) {
                            scheduleTerminalProgressAutoReveal();
                        }
                        const autoIndicator = document.getElementById('autonomous-indicator');
                        if (autoIndicator) {
                            if (data.autonomous) {
                                autoIndicator.style.display = 'flex';
                                window.autonomousStartTime = Date.now();
                                window.autonomousIterations = 0;
                                // Refresh Lucide icons
                                if (typeof lucide !== 'undefined') lucide.createIcons();
                            } else {
                                autoIndicator.style.display = 'none';
                            }
                        }
                        continue;
                    }

                    // Thinking - L'IA réfléchit (nouvelle itération)
                    if (data.thinking) {
                        console.log(`[TERMINAL] Iteration ${data.iteration}`);
                        updateThinkingText(
                            terminalT('terminal.progressThinkingIteration', 'Préparation du tour {iteration}', { iteration: data.iteration })
                        );
                        addTerminalProgressLog(
                            terminalT('terminal.progressThinkingIteration', 'Préparation du tour {iteration}', { iteration: data.iteration }),
                            '',
                            'thinking',
                            { reveal: Number(data.iteration) > 1 }
                        );

                        // Update autonomous progress
                        window.autonomousIterations = data.iteration;
                        const progressEl = document.getElementById('autonomous-progress');
                        const timeEl = document.getElementById('autonomous-time');
                        if (progressEl && window.autonomousStartTime) {
                            progressEl.textContent = `#${data.iteration}`;
                            // Estimate time
                            const elapsed = (Date.now() - window.autonomousStartTime) / 1000;
                            const avgPerIter = elapsed / data.iteration;
                            if (timeEl) {
                                if (elapsed < 60) {
                                    timeEl.textContent = `${Math.round(elapsed)}s`;
                                } else {
                                    timeEl.textContent = `${Math.round(elapsed / 60)}m`;
                                }
                            }
                        }
                        continue;
                    }

                    // Model call - le backend vient d'appeler le modèle cloud/local.
                    if (data.model_call) {
                        const modelCallLabel = describeTerminalModelCall(data.model_call);
                        const modelName = data.model_call.model || '';
                        if (Number(data.model_call.iteration || 1) > 1) {
                            completeTerminalContextActivity();
                        }
                        updateThinkingText(modelCallLabel);
                        addTerminalProgressLog(
                            modelCallLabel,
                            modelName,
                            'thinking',
                            { reveal: shouldRevealTerminalProgressForModelCall(data.model_call) }
                        );
                        if (terminalProgressElement && shouldRevealTerminalProgressForModelCall(data.model_call)) {
                            addTerminalTask('model-call', modelCallLabel, 'running', modelName);
                        }
                        continue;
                    }

                    // Loop warning - Boucle détectée
                    if (data.loop_warning) {
                        console.log(`[TERMINAL] Boucle détectée: ${data.action}`);
                        hideThinkingAnimation();
                        const reason = data.reason ? `: ${data.reason}` : '';
                        addTerminalLine(`Boucle évitée (${data.action})${reason}`, 'warning');
                        addTerminalProgressLog(
                            terminalT('terminal.progressLoopAvoided', 'Boucle évitée'),
                            `${data.action || ''}${reason}`,
                            'warning',
                            { reveal: true }
                        );
                        showThinkingAnimation(terminalT('terminal.progressRethinking', 'Réévaluation'));
                        continue;
                    }

                    // Tool call - Un outil a été appelé (style Claude Code)
                    if (data.tool_call) {
                        taskCounter++;
                        const action = data.tool_call.action;
                        const path = data.tool_call.path || '';
                        const args = data.tool_call.args || {};
                        const toolTaskId = `tool-${++terminalToolTaskSeq}`;
                        const taskLabel = describeTerminalToolCall(action, path, args);

                        // Stocker pour référence quand le résultat arrive (Ctrl+O)
                        window.lastToolCall = { ...data.tool_call, taskId: toolTaskId };

                        console.log(`%c[TERMINAL] ● Tool call reçu: ${action} → ${path}`, 'color: #3b82f6; font-weight: bold;');
                        hideThinkingAnimation();
                        updateTerminalContextActivity(action, path, args, 'running');
                        addOrUpdateTerminalActivitySummary(action, args);

                        // Style Claude Code: ● Action(target)
                        if (shouldShowTerminalToolCallLine(action, args) && typeof addToolCall === 'function') {
                            addToolCall(action, path, args);
                        } else if (shouldShowTerminalToolCallLine(action, args)) {
                            console.error('[TERMINAL] addToolCall function not found!');
                        }

                        const revealToolProgress = shouldRevealTerminalProgressForTool(action, args);
                        if (revealToolProgress) {
                            addTerminalProgressLog(
                                terminalT('terminal.progressToolRunning', 'Exécute {tool}', { tool: action }),
                                path,
                                'running',
                                { reveal: true, key: terminalToolProgressKey(action) }
                            );
                        }
                        if (shouldShowTerminalToolAsTask(action, args)) {
                            updateTerminalTask('model-call', 'done', terminalT('terminal.taskToolSelected', 'Outil choisi'));
                            addTerminalTask(toolTaskId, taskLabel, 'running', describeTerminalToolNote(action, path, args));
                        }
                        showThinkingAnimation(taskLabel || action);
                        continue;
                    }

                    // Tool progress - Un outil long est toujours en cours.
                    if (data.tool_progress) {
                        const progress = data.tool_progress;
                        const { label, detail } = describeTerminalToolProgress(progress);
                        updateThinkingText(label);
                        addTerminalProgressLog(label, detail, 'running', {
                            reveal: true,
                            key: terminalToolProgressKey(progress.action)
                        });
                        if (window.lastToolCall?.taskId && window.lastToolCall.action === progress.action) {
                            updateTerminalTask(window.lastToolCall.taskId, 'running', detail);
                        }
                        continue;
                    }

                    // Tool result - Résultat d'un outil (style Claude Code)
                    if (data.tool_result) {
                        const result = data.tool_result;
                        console.log(`%c[TERMINAL] ⎿ Tool result reçu: ${result.action} → ${result.success ? 'OK' : result.error}`, 'color: #22c55e; font-weight: bold;');

                        // Stocker pour Ctrl+O
                        storeToolResult(window.lastToolCall || {action: result.action}, result);

                        hideThinkingAnimation();

                        // Écriture bloquée
                        if (result.write_blocked) {
                            addToolResult('Write blocked (read-only mode)', 'error');
                            addTerminalProgressLog(
                                terminalT('terminal.progressToolFailed', 'Échec {tool}', { tool: result.action || '' }),
                                terminalT('terminal.writeBlockedShort', 'Écriture bloquée'),
                                'error',
                                { reveal: true, key: terminalToolProgressKey(result.action) }
                            );
                            if (window.lastToolCall?.taskId) {
                                updateTerminalTask(window.lastToolCall.taskId, 'error', terminalT('terminal.writeBlockedShort', 'Écriture bloquée'));
                            }
                            showThinkingAnimation(terminalT('terminal.progressThinking', 'Analyse en cours'));
                            continue;
                        }

                        // Erreur
                        if (!result.success) {
                            updateTerminalContextActivity(result.action, result.path || window.lastToolCall?.path || '', window.lastToolCall?.args || {}, 'error', result);
                            if (result.permission?.requires_confirmation) {
                                addToolResult(terminalT('terminal.approvalRequiredLine', 'Autorisation requise'), 'warning');
                                addTerminalProgressLog(
                                    terminalT('terminal.progressApprovalRequired', 'Autorisation requise'),
                                    result.action || '',
                                    'warning',
                                    { reveal: true, key: terminalToolProgressKey(result.action) }
                                );
                                if (window.lastToolCall?.taskId) {
                                    updateTerminalTask(window.lastToolCall.taskId, 'error', terminalT('terminal.approvalRequiredLine', 'Autorisation requise'));
                                }
                                showThinkingAnimation(terminalT('terminal.approvalWaiting', 'En attente d’autorisation'));
                                continue;
                            }
                            const errorText = result.error || 'Error';
                            addToolResult(errorText, 'error');
                            addTerminalProgressLog(
                                terminalT('terminal.progressToolFailed', 'Échec {tool}', { tool: result.action || '' }),
                                errorText,
                                'error',
                                { reveal: true, key: terminalToolProgressKey(result.action) }
                            );
                            if (window.lastToolCall?.taskId) {
                                updateTerminalTask(window.lastToolCall.taskId, 'error', errorText);
                            }
                            showThinkingAnimation(terminalT('terminal.progressRetrying', 'Nouvelle tentative'));
                            continue;
                        }

                        // Succès - afficher un résumé compact style Claude Code
                        updateTerminalContextActivity(result.action, result.path || window.lastToolCall?.path || '', window.lastToolCall?.args || {}, 'done', result);
                        if (result.action === 'write_todos' && Array.isArray(result.todos)) {
                            applyTerminalTodos(result.todos);
                        }

                        let resultSummary = '';
                        const lastToolArgs = window.lastToolCall?.args || {};
                        const showToolResult = shouldShowTerminalToolResult(result, lastToolArgs);
                        if (result.summary) {
                            resultSummary = result.summary;
                            if (showToolResult) {
                                addToolResult(result.summary, result.action === 'write_files' || result.action === 'clear_workspace' ? 'success' : 'info');
                            }
                        } else if (result.lines_added !== undefined || result.lines_removed !== undefined) {
                            // Format diff: "Added X lines, removed Y lines"
                            const parts = [];
                            if (result.lines_added > 0) parts.push(`Added ${result.lines_added} lines`);
                            if (result.lines_removed > 0) parts.push(`removed ${result.lines_removed} lines`);
                            if (parts.length > 0) {
                                resultSummary = parts.join(', ');
                                if (showToolResult) addToolResult(resultSummary, 'success');
                            }
                        } else if (result.lines) {
                            resultSummary = `${result.lines} lines`;
                            if (showToolResult) addToolResult(resultSummary, 'info');
                        }
                        if (!resultSummary && Array.isArray(result.files) && result.files.length > 0) {
                            resultSummary = summarizeTerminalPaths(result.files, 5);
                        }
                        if (window.lastToolCall?.taskId) {
                            updateTerminalTask(window.lastToolCall.taskId, 'done', resultSummary);
                        }
                        const revealResultProgress = shouldRevealTerminalProgressForTool(result.action, lastToolArgs);
                        if (revealResultProgress) {
                            addTerminalProgressLog(
                                terminalT('terminal.progressToolDone', 'Terminé {tool}', { tool: result.action || '' }),
                                resultSummary,
                                'success',
                                { reveal: true, key: terminalToolProgressKey(result.action) }
                            );
                        }
                        // Sinon pas d'affichage (l'IA donnera la réponse à la fin)

                        showThinkingAnimation(terminalT('terminal.progressThinking', 'Analyse en cours'));
                        continue;
                    }

                    // Approval required - show a JoyBoy-native card and pause.
                    if (data.approval_required) {
                        approvalRequiredThisTurn = true;
                        hideThinkingAnimation();
                        completeTerminalProgressPanel(false);
                        showTerminalApprovalCard({
                            ...data.approval_required,
                            message
                        });
                        continue;
                    }

                    // Auto-correction - L'IA va réessayer après une erreur
                    if (data.auto_correction) {
                        console.log(`[TERMINAL] Auto-correction: ${data.error}`);
                        addTerminalProgressLog(
                            terminalT('terminal.progressCorrection', 'Correction'),
                            data.error || '',
                            'warning',
                            { reveal: true }
                        );
                        updateThinkingText(terminalT('terminal.progressCorrecting', 'Correction en cours'));
                        continue;
                    }

                    // Content - Texte de réponse
                    if (data.content) {
                        // Créer l'output terminal au premier contenu reçu
                        if (!firstContentReceived) {
                            firstContentReceived = true;
                            terminalProgressContentStarted = true;
                            completeTerminalContextActivity();
                            updateTerminalTask('model-call', 'done', terminalT('terminal.taskAnswerStarted', 'Réponse commencée'));
                            if (isTerminalReadOnlyTurn()) {
                                hideTerminalProgressPanel();
                                hideTerminalTasks();
                            } else if (!terminalProgressElement) {
                                clearTimeout(terminalProgressRevealTimer);
                                terminalProgressRevealTimer = null;
                                terminalProgressBufferedLogs = [];
                            }
                            hideThinkingAnimation();
                            createTerminalOutput();
                        }
                        fullResponse += data.content;
                        appendTerminalOutput(data.content);
                        continue;
                    }

                    // Done - Réponse finale
                    if (data.done) {
                        hideThinkingAnimation();
                        const responseTime = Date.now() - startTime;
                        const serverFinalText = (data.full_response || '').trim();
                        const isWaitingForApproval = approvalRequiredThisTurn || Boolean(data.approval_required);
                        completeTerminalProgressPanel(!isWaitingForApproval);
                        updateTerminalTask('terminal-intent', isWaitingForApproval ? 'error' : 'done');

                        // Hide autonomous indicator
                        const autoIndicator = document.getElementById('autonomous-indicator');
                        if (autoIndicator) {
                            autoIndicator.style.display = 'none';
                        }

                        if (data.token_stats) {
                            console.log('[TERMINAL] Token stats:', data.token_stats);
                            tokenStats.maxContextSize = data.token_stats.context_size
                                || (typeof getTerminalEffectiveContextSize === 'function'
                                    ? getTerminalEffectiveContextSize(modelToUse)
                                    : (userSettings.contextSize || 4096));
                            if (data.token_stats.total) {
                                tokenStats.sessionTotal += data.token_stats.total;
                                tokenStats.lastRequestTokens = data.token_stats.total;
                            }
                            updateTokenDisplay();
                        }

                        // Protection anti-écran vide: certains petits modèles
                        // Ollama peuvent finir avec `content=null` malgré des
                        // tokens consommés. Le backend renvoie alors un fallback
                        // durable; sinon on crée quand même une vraie bulle.
                        if (!fullResponse.trim() && !isWaitingForApproval) {
                            const fallbackText = serverFinalText || terminalT('terminal.noReadableResponse', 'Le modèle local a terminé sans produire de réponse lisible. Relance avec une demande plus ciblée ou choisis un modèle terminal plus robuste.');
                            firstContentReceived = true;
                            createTerminalOutput();
                            fullResponse = fallbackText;
                            appendTerminalOutput(fallbackText);
                        }

                        if (!isWaitingForApproval) {
                            finalizeTerminalOutput(responseTime, data.token_stats);
                            const cleanFullResponse = typeof sanitizeAssistantToolTraceText === 'function'
                                ? sanitizeAssistantToolTraceText(fullResponse)
                                : fullResponse;

                            if (cleanFullResponse) {
                                chatHistory.push({ role: 'assistant', content: cleanFullResponse });
                            }

                            // Sauvegarder le chat
                            const finalHtml = getChatHtmlWithoutSkeleton();
                            saveCurrentChatHtml('', finalHtml);
                        }
                        continue;
                    }

                    // Error
                    if (data.error) {
                        hideThinkingAnimation();
                        completeTerminalProgressPanel(false);
                        updateTerminalTask('terminal-intent', 'error');
                        // Hide autonomous indicator on error
                        const autoIndicator = document.getElementById('autonomous-indicator');
                        if (autoIndicator) autoIndicator.style.display = 'none';
                        addTerminalLine(`Erreur: ${data.error}`, 'error');
                        finalizeTerminalOutput(Date.now() - startTime, null);
                    }
                } catch (e) {
                    console.error('[TERMINAL] Parse error:', e);
                }
            }
        }

    } catch (err) {
        hideThinkingAnimation();
        if (err.name !== 'AbortError') {
            console.error('[TERMINAL] Erreur chat:', err);
            completeTerminalProgressPanel(false);
            updateTerminalTask('terminal-intent', 'error');
            addTerminalLine(`Erreur: ${err.message}`, 'error');
        }
    }

    // Reset les flags
    hideThinkingAnimation();
    isGenerating = false;
    terminalWorking = false;
    currentController = null;
    setSendButtonsMode(false);

    if (terminalInterrupted) {
        addTerminalLine(terminalT('terminal.interruptedContinue', 'Interrompu (Ctrl+C) - écris "continue" pour reprendre'), 'warning');
        terminalInterrupted = false;
    } else {
        // Traiter le prochain élément de la queue (sauf si interrompu)
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') {
                processNextInQueue();
            }
        }, 100);
    }

    refocusChatInput();
}

// ===== TERMINAL TRIGGER DETECTION =====

/**
 * Vérifie si le message doit activer le mode terminal
 * @param {string} message - Message de l'utilisateur
 * @returns {boolean} True si le mode terminal doit être activé
 */
async function checkTerminalTrigger(message) {
    console.log('[TERMINAL] Vérification du message:', message);

    // Vérification rapide côté client
    const msgLower = message.toLowerCase().trim();
    const directTriggers = ['joyboy run', 'joyboy_run', 'mode terminal', 'terminal mode', 'mode dev', 'dev mode'];

    if (directTriggers.some(t => msgLower.includes(t))) {
        console.log('[TERMINAL] Trigger direct détecté!');
        openProjectLauncher();
        return true;
    }

    // Ne jamais détourner une génération image/inpaint vers le mode projet.
    // Le backend a aussi une garde, mais celle-ci évite l'aller-retour API et
    // surtout empêche des prompts comme "créer un logo pour une app" d'ouvrir
    // le sélecteur projet avant même que le routeur image/chat travaille.
    if ((typeof currentImage !== 'undefined' && currentImage) || isCreativeGenerationPrompt(msgLower)) {
        console.log('[TERMINAL] Skip trigger: prompt créatif/image');
        return false;
    }

    // Sinon, vérifier via l'API
    try {
        const response = await fetch('/terminal/detect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });

        const data = await response.json();
        console.log('[TERMINAL] Réponse API:', data);

        if (data.terminal_trigger) {
            openProjectLauncher(message);
            return true;
        }

        if (!terminalMode && data.workspace_intent) {
            openProjectLauncher(message);
            return true;
        }

        return false;
    } catch (err) {
        console.error('[TERMINAL] Erreur détection API:', err);
        return false;
    }
}

function isCreativeGenerationPrompt(msgLower) {
    if (typeof promptLooksCreativeImageRequest === 'function') {
        return promptLooksCreativeImageRequest(msgLower);
    }

    const creativeTerms = [
        'logo', 'image', 'photo', 'illustration', 'dessin', 'visuel',
        'poster', 'affiche', 'banner', 'bannière', 'icone', 'icône',
        'avatar', 'wallpaper', 'fond d\'écran', 'design', 'maquette',
        'video', 'vidéo',
        'picture', 'pic', 'visual', 'drawing', 'sketch', 'painting',
        'flyer', 'ad', 'advertisement', 'icon', 'mockup', 'brand',
        'portrait', 'scène', 'scene', 'concept art',
        'imagen', 'foto', 'ilustración', 'ilustracion', 'dibujo',
        'cartel', 'anuncio', 'icono', 'marca',
        'immagine', 'illustrazione', 'disegno', 'manifesto', 'icona', 'marchio'
    ];
    const generationTerms = [
        'crée', 'créer', 'cree', 'creer', 'génère', 'genere', 'générer',
        'generer', 'fais', 'faire', 'imagine', 'imaginer', 'dessine',
        'dessiner', 'make', 'create', 'generate', 'draw',
        'crear', 'crea', 'generar', 'genera', 'hacer', 'haz', 'imagina',
        'imaginar', 'dibujar', 'dibuja',
        'creare', 'crea', 'generare', 'genera', 'fare', 'fai', 'immagina',
        'immaginare', 'disegnare', 'disegna'
    ];
    const visualSubjectTerms = [
        'voiture', 'auto', 'véhicule', 'vehicule', 'car', 'vehicle',
        'coche', 'automóvil', 'automovil', 'vehículo', 'vehiculo',
        'macchina', 'automobile', 'veicolo',
        'train', 'locomotive', 'rail', 'rails', 'chemin de fer',
        'montagnes russes', 'roller coaster', 'chat', 'cat', 'chien',
        'dog', 'animal', 'créature', 'creature', 'dragon', 'robot',
        'personnage', 'character', 'paysage', 'landscape', 'montagne',
        'mountain', 'ciel', 'sky', 'maison', 'house', 'ville', 'city'
    ];
    const devTerms = [
        'repo', 'repository', 'codebase', 'fichier', 'file', 'dossier',
        'folder', 'git', 'commit', 'npm', 'pip', 'bug', 'stacktrace',
        'terminal', 'powershell',
        'repositorio', 'archivo', 'carpeta', 'directorio',
        'codice', 'cartella', 'directory'
    ];

    const includesTerm = (terms) => terms.some(term => {
        const normalized = String(term || '').trim().toLowerCase();
        if (!normalized) return false;
        const escaped = normalized.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return new RegExp(`(^|[^\\p{L}\\p{N}_-])${escaped}(?=$|[^\\p{L}\\p{N}_-])`, 'iu').test(msgLower);
    });

    return (includesTerm(creativeTerms) || includesTerm(visualSubjectTerms))
        && includesTerm(generationTerms)
        && !includesTerm(devTerms);
}

// ===== TERMINAL MODEL PICKER =====
// Gestion de l'onglet Vision dans le model picker en mode terminal

/**
 * Met à jour les tabs du model picker pour le mode terminal
 * Affiche Chat + Vision au lieu de Inpaint/Text2Img/Chat
 * @param {HTMLElement} pickerElement - Élément du picker
 * @param {string} pickerId - ID du picker ('home' ou 'chat')
 */
function updateTerminalModelPickerTabs(pickerElement, pickerId) {
    const tabsContainer = pickerElement.querySelector('.model-picker-tabs');
    if (!tabsContainer) return;

    tabsContainer.innerHTML = `
        <button class="model-picker-tab ${currentModelTab === 'chat' ? 'active' : ''}"
                data-type="chat" onclick="switchModelTab(event, 'chat', '${pickerId}')">
            <i data-lucide="message-square"></i>
            Chat
        </button>
        <button class="model-picker-tab ${currentModelTab === 'vision' ? 'active' : ''}"
                data-type="vision" onclick="switchModelTab(event, 'vision', '${pickerId}')">
            <i data-lucide="eye"></i>
            Vision
        </button>
    `;

    // Réinitialiser les icônes Lucide
    if (window.lucide) lucide.createIcons();
}

/**
 * Sélectionne un modèle vision depuis le picker
 * @param {string} modelId - ID du modèle sélectionné
 */
function selectVisionModel(modelId) {
    // Gestion spéciale pour télécharger un modèle vision
    if (modelId === 'download-vision') {
        downloadVisionModel();
        return;
    }

    selectedVisionModel = modelId;
    Settings.set('selectedVisionModel', modelId);

    // Mettre à jour terminalVisionModel si en mode terminal
    if (terminalMode) {
        terminalVisionModel = modelId;
        // Précharger le nouveau modèle vision
        apiOllama.warmup(modelId, true).then(result => {
            if (result.ok) {
                console.log('[TERMINAL/VISION] Modèle préchargé:', modelId);
            }
        });
    }
}

// Log de fin de chargement
console.log('[TERMINAL.JS] Toutes les fonctions chargées - checkTerminalTrigger:', typeof checkTerminalTrigger);
