// ===== UI - Components, Navigation, Sidebar =====

function uiT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

// ===== GPU PROFILE (VRAM-aware model filtering) =====
window._gpuProfile = null;

fetch('/api/gpu-profile').then(r => r.json()).then(profile => {
    window._gpuProfile = profile;
    console.log('[GPU_PROFILE] Loaded:', profile._comment);
    // Re-render pickers if already displayed
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
    }
}).catch(err => console.warn('[GPU_PROFILE] Failed to load:', err));

// ===== VRAM/RAM MONITORING =====
let vramPollingInterval = null;
let ramPollingInterval = null;
let lastVramData = null;
let vramPanelVisible = false;
const VRAM_POLL_SLOW = 2000;   // 2s quand panel fermé
const VRAM_POLL_FAST = 800;    // 0.8s quand panel ouvert
const RAM_POLL_INTERVAL = 5000; // 5s pour RAM (moins fréquent)

/**
 * Démarre le polling VRAM et RAM
 */
function startVramMonitoring() {
    // Premier appel immédiat
    refreshVramStatus();
    refreshRamStatus();
    // Polling lent par défaut
    setVramPollingSpeed(false);
    // RAM polling séparé (moins fréquent)
    if (ramPollingInterval) clearInterval(ramPollingInterval);
    ramPollingInterval = setInterval(refreshRamStatus, RAM_POLL_INTERVAL);
}

/**
 * Change la vitesse du polling VRAM
 */
function setVramPollingSpeed(fast = false) {
    if (vramPollingInterval) {
        clearInterval(vramPollingInterval);
    }
    const interval = fast ? VRAM_POLL_FAST : VRAM_POLL_SLOW;
    vramPollingInterval = setInterval(refreshVramStatus, interval);
}

/**
 * Arrête le polling VRAM et RAM
 */
function stopVramMonitoring() {
    if (vramPollingInterval) {
        clearInterval(vramPollingInterval);
        vramPollingInterval = null;
    }
    if (ramPollingInterval) {
        clearInterval(ramPollingInterval);
        ramPollingInterval = null;
    }
}

/**
 * Récupère et affiche le status VRAM
 */
async function refreshVramStatus() {
    try {
        const response = await fetch('/api/vram/status');
        const data = await response.json();
        lastVramData = data;
        updateVramDisplay(data);
    } catch (err) {
        console.error('[VRAM] Erreur:', err);
    }
}

/**
 * Récupère et affiche le status RAM
 */
async function refreshRamStatus() {
    try {
        const response = await fetch('/api/ram/status');
        const data = await response.json();
        updateRamDisplay(data);
    } catch (err) {
        console.error('[RAM] Erreur:', err);
    }
}

/**
 * Met à jour l'affichage RAM (header chat + home)
 */
let ramPanelVisible = false;

function updateRamDisplay(data) {
    const { ram, models, models_ram_mb } = data;

    const updateBar = (fillId, textId) => {
        const fill = document.getElementById(fillId);
        const text = document.getElementById(textId);
        if (fill && text) {
            fill.style.width = `${ram.percent}%`;
            fill.className = 'ram-fill';
            if (ram.percent > 90) fill.classList.add('critical');
            else if (ram.percent > 80) fill.classList.add('high');
            else if (ram.percent > 60) fill.classList.add('medium');
            text.textContent = `${ram.used}/${ram.total}G`;
        }
    };

    // Chat header display
    updateBar('ram-fill', 'ram-text');
    // Home display
    updateBar('home-ram-fill', 'home-ram-text');

    // Panel gauge (si ouvert)
    const gaugeFill = document.getElementById('ram-gauge-fill');
    const usedText = document.getElementById('ram-used-text');
    const totalText = document.getElementById('ram-total-text');
    const freeText = document.getElementById('ram-free-text');
    const pythonText = document.getElementById('ram-python-text');

    if (gaugeFill) {
        gaugeFill.style.width = `${ram.percent}%`;
        gaugeFill.className = 'ram-gauge-fill';
        if (ram.percent > 90) gaugeFill.classList.add('critical');
        else if (ram.percent > 80) gaugeFill.classList.add('high');
        else if (ram.percent > 60) gaugeFill.classList.add('medium');
    }
    if (usedText) usedText.textContent = ram.used;
    if (totalText) totalText.textContent = ram.total;
    if (freeText) freeText.textContent = `${ram.free} GB`;
    if (pythonText && ram.python_gb !== undefined) pythonText.textContent = `${ram.python_gb} GB`;

    // Models list
    const modelsList = document.getElementById('ram-models-list');
    if (modelsList && models) {
        if (models.length > 0) {
            let html = '';
            for (const m of models) {
                const sizeMB = m.size_mb ? `${m.size_mb}M` : '';
                html += `<div class="ram-model-row">
                    <i data-lucide="${m.icon}" class="ram-icon"></i>
                    <span class="ram-name">${m.name}</span>
                    ${sizeMB ? `<span class="ram-size">${sizeMB}</span>` : ''}
                    <span class="ram-cat">${m.category}</span>
                </div>`;
            }
            if (models_ram_mb) {
                html += `<div class="ram-model-total">${uiT('ui.totalMb', '{mb} MB total', { mb: models_ram_mb })}</div>`;
            }
            modelsList.innerHTML = html;
            if (window.lucide) lucide.createIcons();
        } else {
            modelsList.innerHTML = `<div class="ram-model-row dim">${uiT('ui.noModel', 'Aucun modèle')}</div>`;
        }
    }
}

function formatDiskGb(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '--';
    const decimals = number >= 100 ? 0 : 1;
    return `${number.toFixed(decimals)}G`;
}

function updateDiskDisplay(disk) {
    const updateBar = (fillId, textId) => {
        const fill = document.getElementById(fillId);
        const text = document.getElementById(textId);
        const display = (fill && fill.closest('.disk-display')) || (text && text.closest('.disk-display'));
        if (!fill || !text) return;

        if (!disk || disk.error) {
            fill.style.width = '0%';
            fill.className = 'disk-fill';
            text.textContent = '--';
            if (display) display.title = 'Disque modèles: indisponible';
            return;
        }

        const percent = Math.max(0, Math.min(100, Number(disk.percent) || 0));
        const free = formatDiskGb(disk.free_gb);
        const total = formatDiskGb(disk.total_gb);
        const path = disk.path || disk.volume_path || '';

        fill.style.width = `${percent}%`;
        fill.className = 'disk-fill';
        if (percent > 95) fill.classList.add('critical');
        else if (percent > 85) fill.classList.add('high');
        else if (percent > 70) fill.classList.add('medium');

        text.textContent = `${free} libres`;
        if (display) {
            display.title = `Disque modèles: ${free} libres / ${total}${path ? `\n${path}` : ''}`;
        }
    };

    updateBar('disk-fill', 'disk-text');
    updateBar('home-disk-fill', 'home-disk-text');
}

function showRamPanel() {
    // Fermer le panel VRAM si ouvert
    hideVramPanel();
    const panel = document.getElementById('ram-panel');
    if (panel) {
        panel.classList.add('visible');
        ramPanelVisible = true;
        refreshRamStatus();
        if (window.lucide) lucide.createIcons();
    }
}

function hideRamPanel() {
    const panel = document.getElementById('ram-panel');
    if (panel) {
        panel.classList.remove('visible');
        ramPanelVisible = false;
    }
}

async function freeRam() {
    const btn = document.querySelector('.ram-action-btn');
    const originalHtml = btn ? btn.innerHTML : '';

    try {
        if (btn) {
            btn.innerHTML = `<i data-lucide="loader-2" class="spin"></i> ${uiT('ui.cleaning', 'Nettoyage...')}`;
            btn.disabled = true;
            if (window.lucide) lucide.createIcons();
        }

        const response = await fetch('/api/ram/free', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            Toast.success(uiT('ui.ramFreed', 'RAM libérée : {mb} MB récupérés', { mb: data.freed_mb }));
        } else {
            Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', { error: data.error || uiT('common.failed', 'Échec') }));
        }

        refreshRamStatus();
    } catch (err) {
        Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', { error: err.message }));
    } finally {
        if (btn) {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
            if (window.lucide) lucide.createIcons();
        }
    }
}

/**
 * Met à jour l'affichage VRAM (header chat + home)
 */
function updateVramDisplay(data) {
    const { vram, models, warnings = [], tips = [], resources = null } = data;

    // Fonction helper pour mettre à jour un display VRAM
    const updateBar = (fillId, textId) => {
        const fill = document.getElementById(fillId);
        const text = document.getElementById(textId);
        if (fill && text) {
            fill.style.width = `${vram.percent}%`;
            fill.className = 'vram-fill';
            if (vram.percent > 90) fill.classList.add('critical');
            else if (vram.percent > 75) fill.classList.add('high');
            else if (vram.percent > 50) fill.classList.add('medium');
            text.textContent = `${vram.used.toFixed(1)}/${vram.total.toFixed(1)}GB`;
        }
    };

    // Chat header display
    updateBar('vram-fill', 'vram-text');
    // Home display
    updateBar('home-vram-fill', 'home-vram-text');

    // Panel display
    const gaugeFill = document.getElementById('vram-gauge-fill');
    const usedText = document.getElementById('vram-used-text');
    const totalText = document.getElementById('vram-total-text');
    const modelsList = document.getElementById('vram-models-list');
    const tipsDiv = document.getElementById('vram-tips');

    if (gaugeFill) {
        gaugeFill.style.width = `${vram.percent}%`;
        gaugeFill.className = 'vram-gauge-fill';
        if (vram.percent > 90) gaugeFill.classList.add('critical');
        else if (vram.percent > 75) gaugeFill.classList.add('high');
        else if (vram.percent > 50) gaugeFill.classList.add('medium');
    }

    if (usedText) usedText.textContent = vram.used.toFixed(1);
    if (totalText) totalText.textContent = vram.total.toFixed(1);

    if (modelsList) {
        if (models && models.length > 0) {
            // Nouveau format avec détails et bouton de déchargement
            let html = '';
            for (const m of models) {
                const vramInfo = m.vram_gb ? `${m.vram_gb}G` : '';
                const paramsInfo = m.params || '';
                const fullName = m.full_name || m.name;

                html += `<div class="vram-model-row">
                    <button class="vram-unload-btn" onclick="unloadSingleModel('${fullName}', '${m.category}')" title="${uiT('ui.unloadModelTooltip', 'Décharger ce modèle')}">×</button>
                    <i data-lucide="${m.icon}" class="vram-icon"></i>
                    <span class="vram-name" title="${fullName}">${m.name}</span>
                    ${paramsInfo ? `<span class="vram-params">${paramsInfo}</span>` : ''}
                    ${vramInfo ? `<span class="vram-size">${vramInfo}</span>` : ''}
                    <span class="vram-cat">${m.category}</span>
                </div>`;
            }
            modelsList.innerHTML = html;
            // Refresh Lucide icons
            if (window.lucide) lucide.createIcons();
        } else {
            modelsList.innerHTML = `<div class="vram-model-row dim">${uiT('ui.noModel', 'Aucun modèle')}</div>`;
        }
    }

    if (tipsDiv) {
        let html = '';
        if (warnings.length > 0) {
            html += warnings.map(w => `<div class="vram-warning"><i data-lucide="alert-triangle" style="width:12px;height:12px;"></i> ${w}</div>`).join('');
        }
        if (tips.length > 0) {
            html += tips.map(t => `<div class="vram-tip"><i data-lucide="lightbulb" style="width:12px;height:12px;"></i> ${t}</div>`).join('');
        }
        tipsDiv.innerHTML = html;
        if (window.lucide) lucide.createIcons();
    }

    updateDiskDisplay(resources && resources.disk);
    updateRuntimeResourceDisplay(resources);
}

function updateRuntimeResourceDisplay(resources) {
    const container = document.getElementById('runtime-resource-list');
    if (!container) return;

    if (!resources || resources.error) {
        container.innerHTML = '';
        return;
    }

    const active = Array.isArray(resources.active) ? resources.active : [];
    const loadedGroups = Array.isArray(resources.loaded_groups) ? resources.loaded_groups : [];
    const pressure = resources.pressure || 'unknown';
    const title = uiT('ui.runtimeResourcesTitle', 'Orchestrateur runtime');

    const groupLabel = loadedGroups.length
        ? loadedGroups.map(group => escapeHtml(group)).join(', ')
        : uiT('ui.runtimeNoLoadedGroups', 'aucun groupe lourd chargé');

    let html = `
        <div class="runtime-resource-title">
            <i data-lucide="route"></i>
            <span>${escapeHtml(title)}</span>
            <span class="runtime-resource-pressure">${escapeHtml(pressure)}</span>
        </div>
        <div class="runtime-resource-groups">${groupLabel}</div>
    `;

    if (!active.length) {
        html += `<div class="runtime-resource-empty">${escapeHtml(uiT('ui.runtimeNoActiveResources', 'Aucun job lourd actif'))}</div>`;
    } else {
        html += active.map(lease => {
            const plan = lease.plan || {};
            const model = lease.model_name || lease.group || lease.task_type || 'runtime';
            const task = lease.task_type || lease.group || 'task';
            const unload = Array.isArray(plan.unload_groups) && plan.unload_groups.length
                ? `<span class="runtime-resource-unload">${escapeHtml(uiT('ui.runtimeWillUnload', 'libère'))}: ${plan.unload_groups.map(g => escapeHtml(g)).join(', ')}</span>`
                : `<span class="runtime-resource-keep">${escapeHtml(uiT('ui.runtimeKeepsReady', 'cohabitation OK'))}</span>`;
            return `
                <div class="runtime-resource-row">
                    <span class="runtime-resource-kind">${escapeHtml(task)}</span>
                    <span class="runtime-resource-model" title="${escapeHtml(model)}">${escapeHtml(model)}</span>
                    ${unload}
                </div>
            `;
        }).join('');
    }

    container.innerHTML = html;
    if (window.lucide) lucide.createIcons({ nodes: [container] });
}

/**
 * Affiche le panel VRAM
 */
function showVramPanel() {
    const panel = document.getElementById('vram-panel');
    if (panel) {
        panel.classList.add('visible');
        vramPanelVisible = true;
        refreshVramStatus();  // Refresh immédiat
        setVramPollingSpeed(true);  // Polling rapide
        if (window.lucide) lucide.createIcons();
    }
}

/**
 * Cache le panel VRAM
 */
function hideVramPanel() {
    const panel = document.getElementById('vram-panel');
    if (panel) {
        panel.classList.remove('visible');
        vramPanelVisible = false;
        setVramPollingSpeed(false);  // Retour au polling lent
    }
}

/**
 * HARD RESET - Arrête tout et libère toute la VRAM
 * Annule les générations, décharge tous les modèles, vide la mémoire
 */
async function unloadUnusedModels() {
    const btn = document.querySelector('.vram-action-btn');
    const originalHtml = btn ? btn.innerHTML : '';

    try {
        // Feedback visuel avec spinner
        if (btn) {
            btn.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Arrêt...';
            btn.disabled = true;
            if (window.lucide) lucide.createIcons();
        }

        // Annuler tout: abort controllers, vider la queue, libérer VRAM
        clearQueue();

        // Appeler le hard reset backend pour être sûr
        const result = await apiSystem.hardReset();

        if (result.ok && result.data?.success) {
            // Reset des flags frontend
            if (typeof isGenerating !== 'undefined') isGenerating = false;
            if (typeof currentGenerationId !== 'undefined') currentGenerationId = null;
            if (typeof currentGenerationChatId !== 'undefined') currentGenerationChatId = null;
            if (typeof currentGenerationMode !== 'undefined') currentGenerationMode = null;

            // Reset l'UI
            if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
            document.getElementById('loading')?.classList.add('hidden');
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) sendBtn.disabled = false;

            const count = result.data.results?.ollama_models_unloaded || 0;
            Toast.success(uiT('ui.vramFreed', 'VRAM libérée ({count} modèle(s) déchargé(s))', { count }));
        } else {
            Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', {
                error: result.data?.error || result.error || uiT('ui.resetFailed', 'Échec du reset'),
            }));
        }

        refreshVramStatus();
    } catch (err) {
        Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', { error: err.message }));
    } finally {
        // Restaurer le bouton
        if (btn) {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
            if (window.lucide) lucide.createIcons();
        }
    }
}

/**
 * Décharge un modèle spécifique de la VRAM
 * @param {string} modelName - Nom complet du modèle
 * @param {string} category - Catégorie du modèle (chat, vision, utility, inpaint, text2img, upscale, video)
 */
async function unloadSingleModel(modelName, category) {
    console.log(`[VRAM] Déchargement de ${modelName} (${category})...`);

    try {
        let result;

        // Modèles Ollama (chat, vision, utility)
        if (['chat', 'vision', 'utility'].includes(category)) {
            result = await fetch('/ollama/unload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelName })
            });
        }
        // Modèles HuggingFace (inpaint, text2img, upscale, video)
        else if (category === 'inpaint' || category === 'text2img') {
            result = await fetch('/models/unload-image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        }
        // Upscale model
        else if (category === 'upscale') {
            result = await fetch('/models/unload-upscale', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        }
        // Video model
        else if (category === 'video') {
            result = await fetch('/models/unload-video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        }
        // LoRA
        else if (category === 'lora') {
            result = await fetch('/models/unload-lora', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: modelName })
            });
        }
        else {
            console.warn(`[VRAM] Catégorie inconnue: ${category}`);
            return;
        }

        const data = await result.json();
        if (data.success) {
            Toast.success(uiT('ui.modelUnloaded', '{model} déchargé', { model: modelName }));

        } else {
            Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', {
                error: data.error || uiT('ui.unloadFailed', 'Échec du déchargement'),
            }));
        }

        // Rafraîchir l'affichage VRAM
        refreshVramStatus();

    } catch (err) {
        console.error('[VRAM] Erreur déchargement:', err);
        Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', { error: err.message }));
    }
}

// Démarrer le monitoring au chargement
document.addEventListener('DOMContentLoaded', () => {
    startVramMonitoring();
    loadJoyboyFeatureFlags();

    // Scrollbar dimming : sombre quand curseur hors fenêtre, normal quand dedans
    document.addEventListener('mouseenter', () => document.body.classList.add('cursor-active'));
    document.addEventListener('mouseleave', () => document.body.classList.remove('cursor-active'));
});

// ===== UTILITY FUNCTIONS =====

/**
 * Formate un temps en millisecondes en affichage lisible avec label de vitesse
 * @param {number} ms - Temps en millisecondes
 * @param {number} fastThreshold - Seuil en ms pour "Rapide" (default: 2000)
 * @param {number} slowThreshold - Seuil en ms pour "Lent" (default: 8000)
 * @returns {string} HTML formaté
 */
function formatTimeDisplay(ms, fastThreshold = 2000, slowThreshold = 8000) {
    if (!ms) return '';
    const seconds = formatCompactDurationSeconds(ms / 1000);
    const speed = getTimingSpeedLabel(ms / 1000, fastThreshold / 1000, slowThreshold / 1000);
    return `<span class="time">${seconds}</span> - <span class="speed">${speed}</span>`;
}

/**
 * Formate un temps en secondes (pour génération d'images)
 * @param {number} seconds - Temps en secondes
 * @returns {string} HTML formaté
 */
function formatGenTimeDisplay(seconds) {
    if (!seconds) return '';
    const speed = getTimingSpeedLabel(seconds, 15, 60);
    return `<span class="time">${formatCompactDurationSeconds(seconds)}</span> - <span class="speed">${speed}</span>`;
}

function normalizePositiveNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
}

function formatCompactDurationSeconds(seconds) {
    const value = normalizePositiveNumber(seconds);
    if (value === null) return '';
    if (value < 0.1) return `${Math.round(value * 1000)}ms`;
    return `${(Math.round(value * 10) / 10).toFixed(1)}s`;
}

function getTimingSpeedLabel(seconds, fastThreshold, slowThreshold) {
    const value = normalizePositiveNumber(seconds);
    let key = 'normal';
    if (value !== null && value < fastThreshold) key = 'fast';
    else if (value !== null && value > slowThreshold) key = 'slow';

    const fallbacks = { fast: 'Rapide', normal: 'Normal', slow: 'Lent' };
    return uiT(`generation.timing.${key}`, fallbacks[key]);
}

function formatImageTimingDisplay(generationSeconds = null, totalSeconds = null) {
    const generationValue = normalizePositiveNumber(generationSeconds);
    const totalValue = normalizePositiveNumber(totalSeconds);
    const generationTime = formatCompactDurationSeconds(generationValue);
    const totalTime = formatCompactDurationSeconds(totalValue);

    if (generationTime && totalTime && Math.abs(generationValue - totalValue) > 0.1) {
        return uiT('generation.timing.imageBoth', 'Gén. {generationTime} · Total {totalTime}', {
            generationTime,
            totalTime,
        });
    }
    if (generationTime) {
        return uiT('generation.timing.imageGenerationOnly', 'Gén. {generationTime}', {
            generationTime,
        });
    }
    if (totalTime) {
        return uiT('generation.timing.imageTotalOnly', 'Total {totalTime}', {
            totalTime,
        });
    }
    return '';
}

/**
 * Met à jour l'affichage des tokens dans l'UI
 */
function updateTokenDisplay() {
    const used = tokenStats.sessionTotal;
    const terminalContextMax = typeof getTerminalEffectiveContextSize === 'function'
        ? getTerminalEffectiveContextSize()
        : (userSettings.contextSize || 4096);
    const max = tokenStats.maxContextSize || terminalContextMax || userSettings.contextSize || 4096;
    const lastReq = tokenStats.lastRequestTokens;
    const remaining = Math.max(0, max - used);
    const contextFormatter = window.JoyBoyContextSizes?.format;
    const formatContextMax = (value) => {
        const parsed = Number.parseInt(value, 10);
        if (!Number.isFinite(parsed) || parsed <= 0) return String(value || '');
        if (contextFormatter && parsed <= window.JoyBoyContextSizes.max) {
            return contextFormatter.call(window.JoyBoyContextSizes, parsed);
        }
        if (parsed >= 1000000) return `${(parsed / 1000000).toFixed(1).replace(/\.0$/, '')}M`;
        return formatTokenCount(parsed);
    };

    // Calculer le pourcentage d'utilisation
    const percentUsed = Math.min((used / max) * 100, 100);

    // Couleur selon l'usage (inversé pour remaining)
    let colorClass = 'tokens-high'; // beaucoup de tokens restants = vert
    if (percentUsed > 75) colorClass = 'tokens-low'; // peu de tokens restants = rouge
    else if (percentUsed > 50) colorClass = 'tokens-medium'; // moyen = orange

    // === Affichage dans le header chat (tokens utilisés / max) ===
    const el = document.getElementById('token-display');
    if (el) {
        el.innerHTML = `
            <div class="token-info ${colorClass.replace('tokens-', 'token-')}">
                <span class="token-used">${formatTokenCount(used)}</span>
                <span class="token-separator">/</span>
                <span class="token-max">${formatContextMax(max)}</span>
                ${lastReq ? `<span class="token-last">(+${lastReq})</span>` : ''}
            </div>
        `;
        el.style.display = 'flex';
        el.title = `Tokens utilisés: ${used}\nContexte max: ${max}\nRestant: ${remaining}\nDernière requête: ${lastReq || 0}`;
    }

    // === Affichage dans le header terminal (tokens utilisés / max) ===
    const terminalTokens = document.getElementById('terminal-tokens');
    const tokensUsed = document.getElementById('tokens-used');
    const tokensMax = document.getElementById('tokens-max');
    if (terminalTokens && tokensUsed) {
        tokensUsed.textContent = formatTokenCount(used);

        const contextMax = tokenStats.maxContextSize || terminalContextMax || userSettings.contextSize || 4096;
        if (tokensMax) tokensMax.textContent = formatContextMax(contextMax);

        // Couleur basée sur le % d'utilisation par rapport au max
        const usagePercent = (used / contextMax) * 100;
        let usageClass = 'tokens-low';  // vert
        if (usagePercent > 80) usageClass = 'tokens-high';  // rouge - presque plein!
        else if (usagePercent > 50) usageClass = 'tokens-medium';  // orange
        terminalTokens.className = `terminal-tokens ${usageClass}`;

        const remaining = Math.max(0, contextMax - used);
        terminalTokens.title = `Tokens: ${used} / ${contextMax}\nRestant: ${remaining}\nDernière requête: ${lastReq || 0}\nCliquer pour modifier`;
    }
}

/**
 * Formate un nombre de tokens (ex: 4096 -> "4K", 12500 -> "12.5K")
 */
function formatTokenCount(count) {
    if (count >= 1000) {
        return (count / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    }
    return count.toString();
}

/**
 * Réinitialise les stats de tokens pour une nouvelle session/chat
 */
function resetTokenStats() {
    tokenStats.sessionTotal = 0;
    tokenStats.lastRequestTokens = 0;
    tokenStats.promptTokens = 0;
    tokenStats.completionTokens = 0;
    tokenStats.maxContextSize = typeof getTerminalEffectiveContextSize === 'function'
        ? getTerminalEffectiveContextSize()
        : (userSettings.contextSize || 4096);
    updateTokenDisplay();
}

/**
 * Active ou désactive un toggle
 * @param {string} elementId - ID de l'élément toggle
 * @param {boolean} isActive - État actif ou non
 */
function setToggleActive(elementId, isActive) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (isActive) {
        el.classList.add('active');
    } else {
        el.classList.remove('active');
    }
}

// ===== VIEW NAVIGATION =====
function showHome(options = {}) {
    const { cancelActive = false, clearImage = true } = options;

    // Navigation must not be destructive. Generations can outlive the visible
    // view now, so only explicit stop/reset actions are allowed to cancel them.
    if (cancelActive && typeof cancelCurrentGenerations === 'function') {
        cancelCurrentGenerations();
    }

    if (clearImage && typeof currentImage !== 'undefined') {
        currentImage = null;
        updateImagePreviews();
    }

    document.getElementById('home-view').style.display = 'flex';
    document.getElementById('chat-view').style.display = 'none';
    document.getElementById('modal-view').style.display = 'none';
    const addonsView = document.getElementById('addons-view');
    if (addonsView) addonsView.style.display = 'none';
    const extensionsView = document.getElementById('extensions-view');
    if (extensionsView) extensionsView.style.display = 'none';
    const deployAtlasView = document.getElementById('deployatlas-view');
    if (deployAtlasView) deployAtlasView.style.display = 'none';
    const modelsView = document.getElementById('models-view');
    if (modelsView) modelsView.style.display = 'none';
    if (typeof hideModulesWorkspaces === 'function') hideModulesWorkspaces();
    if (typeof hideProjectView === 'function') hideProjectView();
    if (typeof applyTerminalChatState === 'function') {
        applyTerminalChatState(null);
    }
    document.body.classList.remove('addons-mode');
    document.body.classList.remove('extensions-mode');
    document.body.classList.remove('models-mode');
    document.body.classList.remove('projects-mode');
    document.body.classList.remove('modules-mode');
    document.body.classList.remove('signalatlas-mode');
    document.body.classList.remove('perfatlas-mode');
    document.body.classList.remove('cyberatlas-mode');
    document.body.classList.remove('deployatlas-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
}

function showChat() {
    document.getElementById('home-view').style.display = 'none';
    document.getElementById('chat-view').style.display = 'flex';
    document.getElementById('modal-view').style.display = 'none';
    const addonsView = document.getElementById('addons-view');
    if (addonsView) addonsView.style.display = 'none';
    const extensionsView = document.getElementById('extensions-view');
    if (extensionsView) extensionsView.style.display = 'none';
    const deployAtlasView = document.getElementById('deployatlas-view');
    if (deployAtlasView) deployAtlasView.style.display = 'none';
    const modelsView = document.getElementById('models-view');
    if (modelsView) modelsView.style.display = 'none';
    if (typeof hideModulesWorkspaces === 'function') hideModulesWorkspaces();
    if (typeof hideProjectView === 'function') hideProjectView();
    document.body.classList.remove('addons-mode');
    document.body.classList.remove('extensions-mode');
    document.body.classList.remove('models-mode');
    document.body.classList.remove('modules-mode');
    document.body.classList.remove('signalatlas-mode');
    document.body.classList.remove('perfatlas-mode');
    document.body.classList.remove('cyberatlas-mode');
    document.body.classList.remove('deployatlas-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
    updateChatPadding();
    scrollToBottom(true);
}

// =============================================================================
// ANCHORED SCROLL — Pattern de scroll "ancré" pour le chat
// =============================================================================
//
// Principe : chaque nouveau bloc message (user + AI) apparaît en haut du
// viewport, exactement à la même position que le tout premier message.
// Les messages précédents sont poussés au-dessus, hors de vue.
// L'utilisateur scroll vers le haut pour revoir les anciens messages.
//
// Demande initiale : "je veux que chaque nouveau message fasse comme si
// c'était le premier — le message d'avant doit simplement être au-dessus
// mais pas visible, l'utilisateur devra scroller pour le voir."
//
// Composants :
//   1. addChatSkeletonMessage() — scroll le nouveau message au "naturalTop"
//      (position du 1er message). Premier message = pas de scroll.
//   2. createStreamingMessage() — pas de scroll (déjà positionné par #1)
//   3. scrollToBottom() — suit le contenu qui grandit (streaming), ne
//      remonte jamais. Recalcule le padding dynamique à chaque appel.
//   4. updateChatPadding() — ajuste padding-bottom pour que le scroll max
//      corresponde exactement à la position du dernier message. Empêche
//      de scroller dans le vide.
//   5. finalizeStreamingMessage() — recalcule le padding après le formatage
//      markdown final + ajout des boutons d'action.
//
// Le CSS .chat-messages a un padding-bottom: calc(100vh - ...) statique,
// qui est ÉCRASÉ dynamiquement par updateChatPadding() via style.paddingBottom.
// =============================================================================

let scrollRAF = null;
let lastScrollTop = 0;

/**
 * Ajuste le padding-bottom de .chat-messages dynamiquement.
 *
 * Le but : le scroll maximum doit correspondre exactement à la position où
 * le dernier vrai message (pas le skeleton) s'affiche au "naturalTop"
 * (= position du premier message dans le viewport). Cela empêche l'utilisateur
 * de scroller dans le vide du padding CSS.
 *
 * Formule : padding = idealMax + clientHeight - contentEnd
 *   - idealMax = lastRealMsg.offsetTop - naturalTop (scroll cible du dernier msg)
 *   - contentEnd = bottom du dernier élément DOM (skeleton inclus)
 *   - Résultat : scrollHeight - clientHeight = idealMax
 */
function updateChatPadding() {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;
    if (document.body.classList.contains('terminal-mode')) {
        const inputBar = document.querySelector('.chat-input-bar');
        const minPad = inputBar ? (inputBar.offsetHeight + 96) : 188;
        messagesDiv.style.setProperty('padding-bottom', `${minPad}px`, 'important');
        return;
    }
    const lastChild = messagesDiv.lastElementChild;
    if (!lastChild) return;
    const firstChild = messagesDiv.firstElementChild;
    const requestedTop = firstChild ? firstChild.offsetTop : 40;
    const minRequestTop = window.matchMedia?.('(max-width: 768px)').matches ? 80 : 112;
    const naturalTop = Math.max(requestedTop, minRequestTop);

    // Les skeletons sont temporaires : le vrai dernier message détermine le scroll max.
    const realMsgs = messagesDiv.querySelectorAll(
        '.message:not(.skeleton-message):not(.image-skeleton-message):not(.video-skeleton-message)'
    );
    const lastRealMsg = realMsgs.length ? realMsgs[realMsgs.length - 1] : lastChild;

    const contentEnd = lastChild.offsetTop + lastChild.offsetHeight;
    const idealMax = lastRealMsg.offsetTop - naturalTop;
    const padding = idealMax + messagesDiv.clientHeight - contentEnd;
    // Minimum = hauteur input bar + bottom offset + barre d'actions (~44px) + marge
    // pour que le dernier message + sa barre d'actions ne passent jamais sous l'input
    const inputBar = document.querySelector('.chat-input-bar');
    const ACTIONS_BAR_H = 44;
    const minPad = inputBar ? (inputBar.offsetHeight + 20 + ACTIONS_BAR_H + 24) : 160;
    messagesDiv.style.paddingBottom = Math.max(minPad, padding) + 'px';
}

/**
 * Scroll intelligent pour le streaming.
 *
 * - Recalcule le padding à chaque appel (le contenu change pendant le streaming)
 * - Si le contenu tient dans le viewport ET scrollTop=0 : verrouille le scroll
 *   (premier message, pas de vide accessible)
 * - Si le contenu déborde : déverrouille le scroll, suit le contenu vers le bas
 * - Ne remonte JAMAIS automatiquement (seul l'utilisateur scroll vers le haut)
 */
function scrollToBottom(force = false) {
    if (scrollRAF) return;

    scrollRAF = requestAnimationFrame(() => {
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) {
            const lastChild = messagesDiv.lastElementChild;
            if (!lastChild) { scrollRAF = null; return; }

            // Toujours scrollable
            messagesDiv.style.overflowY = 'auto';

            // Synchronise le padding avec le contenu actuel
            updateChatPadding();

            // Si l'utilisateur a scrollé vers le haut, ne pas forcer
            if (!force) {
                const distFromBottom = messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight;
                if (distFromBottom > 150) {
                    scrollRAF = null;
                    return;
                }
            }

            // Scroll smooth vers le bas — le container se scroll lui-même
            messagesDiv.scrollTo({ top: messagesDiv.scrollHeight, behavior: 'smooth' });
        }
        setTimeout(() => { scrollRAF = null; }, 200);
    });
}


// ===== SIDEBAR =====
function toggleSidebarCollapse() {
    const sidebar = document.getElementById('conversations-sidebar');
    const isCollapsed = sidebar.classList.toggle('collapsed');
    document.body.classList.toggle('sidebar-collapsed', isCollapsed);
    Settings.set('sidebarCollapsed', isCollapsed);
}

function initSidebarState() {
    // Default collapsed, expand only if user explicitly opened it
    const isExpanded = Settings.get('sidebarCollapsed') === false;
    if (!isExpanded) {
        document.getElementById('conversations-sidebar').classList.add('collapsed');
        document.body.classList.add('sidebar-collapsed');
    }
}

// ===== MOBILE SIDEBAR =====
function isMobileSidebarViewport() {
    return window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
}

function restoreSavedSidebarState() {
    const sidebar = document.getElementById('conversations-sidebar');
    if (!sidebar) return;

    const shouldCollapse = Settings.get('sidebarCollapsed') !== false;
    sidebar.classList.toggle('collapsed', shouldCollapse);
    document.body.classList.toggle('sidebar-collapsed', shouldCollapse);
}

function setMobileSidebarOpen(open) {
    const sidebar = document.getElementById('conversations-sidebar');
    if (!sidebar) return;

    sidebar.classList.toggle('mobile-open', open);

    if (!isMobileSidebarViewport()) return;

    if (open) {
        sidebar.classList.remove('collapsed');
        document.body.classList.remove('sidebar-collapsed');
        return;
    }

    restoreSavedSidebarState();
}

function toggleMobileSidebar() {
    const sidebar = document.getElementById('conversations-sidebar');
    if (!sidebar) return;

    setMobileSidebarOpen(!sidebar.classList.contains('mobile-open'));
}

// Close mobile sidebar when clicking outside
document.addEventListener('click', function(e) {
    const sidebar = document.getElementById('conversations-sidebar');
    const menuBtn = document.getElementById('mobile-menu-btn');

    if (sidebar && sidebar.classList.contains('mobile-open')) {
        if (!sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
            setMobileSidebarOpen(false);
        }
    }
});

// ===== DROPDOWNS =====
function toggleDropdown() {
    document.getElementById('model-dropdown').classList.toggle('open');
    document.getElementById('chat-model-dropdown')?.classList.remove('open');
}

function selectModel(value) {
    document.getElementById('model-select').value = value;
    document.getElementById('selected-model-text').textContent = value;
    document.getElementById('model-dropdown').classList.remove('open');
    syncModelSelection(value);
    saveSettings();
}

function toggleChatDropdown() {
    document.getElementById('chat-model-dropdown').classList.toggle('open');
    document.getElementById('model-dropdown')?.classList.remove('open');
}

function selectChatModel(value) {
    // Legacy function - met à jour le chat model
    document.getElementById('chat-selected-model-text').textContent = value;
    document.getElementById('chat-model-dropdown')?.classList.remove('open');
    userSettings.chatModel = value;
    if (typeof selectedChatModel !== 'undefined') selectedChatModel = value;
    saveSettings();
}

function syncModelSelection(value) {
    // Legacy - synchronise seulement le picker home (pas le chat!)
    const homeText = document.getElementById('selected-model-text');
    if (homeText) homeText.textContent = value;
}

// Met à jour l'affichage du picker selon le contexte (image ou chat)
/**
 * Détermine le mode actuel (inpaint, text2img, chat, terminal)
 * Centralisé pour tous les pickers
 */
function getCurrentMode() {
    // Terminal mode a priorité
    if (typeof terminalMode !== 'undefined' && terminalMode) {
        return 'terminal';
    }
    // Si image dans l'INPUT -> inpaint
    const hasInputImage = !!currentImage;
    if (hasInputImage) {
        return 'inpaint';
    }
    // Sinon chat par défaut (ou text2img si sur home sans conversation)
    return 'chat';
}

/**
 * Format "qwen2.5:7b" → "qwen2.5 7b", "dolphin-mistral:latest" → "dolphin-mistral"
 */
function _formatModelName(modelId) {
    if (!modelId) return 'Auto';
    if (isTerminalCloudModelId(modelId)) return formatTerminalCloudModelName(modelId);
    const parts = modelId.split(':');
    const tag = parts[1] || 'latest';
    return tag === 'latest' ? parts[0] : `${parts[0]} ${tag}`;
}

const TERMINAL_CLOUD_PROVIDER_IDS = new Set([
    'openai',
    'openrouter',
    'anthropic',
    'gemini',
    'deepseek',
    'moonshot',
    'novita',
    'minimax',
    'volcengine',
    'glm',
    'vllm'
]);
let TERMINAL_CLOUD_MODELS = [];
window.joyboyTerminalCloudModels = TERMINAL_CLOUD_MODELS;
let modelPickerChatSource = Settings.get('modelPickerChatSource') || 'local';
let modelPickerChatFamily = Settings.get('modelPickerChatFamily') || 'all';

const CLOUD_FAMILY_ORDER = [
    'gpt',
    'codex',
    'claude',
    'gemini',
    'deepseek',
    'kimi',
    'glm',
    'qwen',
    'llama',
    'mistral',
    'openrouter',
    'other',
];

const DEFAULT_CLOUD_CONTEXT_SIZE = 262144;
const DEFAULT_CLOUD_REASONING_EFFORT = 'medium';

function isTerminalCloudModelId(modelId) {
    const raw = String(modelId || '').trim();
    const providerId = raw.includes(':') ? raw.split(':', 1)[0].toLowerCase() : '';
    return TERMINAL_CLOUD_PROVIDER_IDS.has(providerId);
}

function getTerminalSelectedModelId(explicitModelId = null) {
    if (explicitModelId) return explicitModelId;
    if (typeof terminalToolModel !== 'undefined' && terminalToolModel) {
        const activeCloudChatModel = typeof getActiveCloudChatModel === 'function'
            ? getActiveCloudChatModel()
            : null;
        if (activeCloudChatModel && !isTerminalCloudModelId(terminalToolModel)) {
            return activeCloudChatModel;
        }
        return terminalToolModel;
    }
    if (typeof userSettings !== 'undefined') {
        return userSettings.terminalModel || userSettings.chatModel || null;
    }
    return null;
}

function getTerminalCloudModelProfile(modelId) {
    const raw = String(modelId || '').trim();
    if (!raw) return null;
    const models = Array.isArray(window.joyboyTerminalCloudModels)
        ? window.joyboyTerminalCloudModels
        : [];
    return models.find(model => model?.id === raw) || null;
}

function getTerminalEffectiveContextSize(modelId = null) {
    const activeModel = getTerminalSelectedModelId(modelId);
    if (isTerminalCloudModelId(activeModel)) {
        const profile = getTerminalCloudModelProfile(activeModel);
        const cloudContext = Number.parseInt(profile?.contextSize || profile?.context_size, 10);
        if (Number.isFinite(cloudContext) && cloudContext > 0) return cloudContext;
        const lower = String(activeModel || '').trim().toLowerCase();
        if (lower === 'openai:gpt-5.5' || lower === 'openai:gpt-5.4') return 1000000;
        if (lower.startsWith('openai:gpt-5')) return 400000;
        if (lower.startsWith('gemini:')) return 1000000;
        return DEFAULT_CLOUD_CONTEXT_SIZE;
    }
    return window.JoyBoyContextSizes?.normalize(userSettings.contextSize || 4096) || (userSettings.contextSize || 4096);
}

function getTerminalReasoningEffort(modelId = null) {
    const activeModel = getTerminalSelectedModelId(modelId);
    if (!isTerminalCloudModelId(activeModel)) return null;
    const profile = getTerminalCloudModelProfile(activeModel);
    const allowed = Array.isArray(profile?.reasoningEfforts) ? profile.reasoningEfforts : [];
    const saved = String(userSettings.terminalReasoningEffort || profile?.defaultReasoningEffort || DEFAULT_CLOUD_REASONING_EFFORT).trim();
    return allowed.length && !allowed.includes(saved)
        ? (profile?.defaultReasoningEffort || DEFAULT_CLOUD_REASONING_EFFORT)
        : (saved || DEFAULT_CLOUD_REASONING_EFFORT);
}

function getReasoningLabelForPicker(effort) {
    if (typeof terminalReasoningLabel === 'function') return terminalReasoningLabel(effort);
    const labels = {
        low: uiT('settings.terminal.reasoningLow', 'Bas'),
        medium: uiT('settings.terminal.reasoningMedium', 'Moyen'),
        high: uiT('settings.terminal.reasoningHigh', 'Élevé'),
        xhigh: uiT('settings.terminal.reasoningXhigh', 'Très approfondi'),
    };
    return labels[effort] || labels.medium;
}

function buildCloudReasoningPickerControl(pickerId = 'chat') {
    const selected = String(userSettings.terminalReasoningEffort || DEFAULT_CLOUD_REASONING_EFFORT).trim();
    const options = ['low', 'medium', 'high', 'xhigh'].map(effort => `
        <option value="${effort}" ${selected === effort ? 'selected' : ''}>${getReasoningLabelForPicker(effort)}</option>
    `).join('');
    return `
        <div class="model-picker-reasoning" onclick="stopModelPickerControlEvent(event)">
            <label for="${pickerId}-reasoning-select">${uiT('settings.terminal.reasoningLabel', 'Raisonnement cloud')}</label>
            <select id="${pickerId}-reasoning-select" class="model-picker-reasoning-select terminal-reasoning-control" onchange="updateTerminalReasoningEffort(this.value)">
                ${options}
            </select>
        </div>
    `;
}

function formatTerminalCloudModelName(modelId) {
    const raw = String(modelId || '').trim();
    if (!raw.includes(':')) return raw || 'Cloud';
    const [providerId, ...modelParts] = raw.split(':');
    const providerLabels = {
        openai: 'OpenAI',
        openrouter: 'OpenRouter',
        deepseek: 'DeepSeek',
        moonshot: 'Kimi',
        novita: 'Novita',
        minimax: 'MiniMax',
        anthropic: 'Claude',
        gemini: 'Gemini',
        volcengine: 'Doubao',
        glm: 'GLM',
        vllm: 'vLLM',
    };
    return `${providerLabels[providerId.toLowerCase()] || providerId} ${modelParts.join(':')}`;
}

function getCloudModelFamily(modelOrProfile) {
    const provider = String(modelOrProfile?.provider || '').toLowerCase();
    const rawId = String(modelOrProfile?.id || '').toLowerCase();
    const modelName = String(modelOrProfile?.model || rawId.split(':').slice(1).join(':')).toLowerCase();
    const parts = modelName.includes('/') ? modelName.split('/') : ['', modelName];
    const vendor = parts[0] || provider;
    const name = parts.slice(1).join('/') || modelName;

    if (name.includes('codex')) return 'codex';
    if (name.startsWith('gpt-') || name.includes('/gpt-') || provider === 'openai') return 'gpt';
    if (name.startsWith('o') && /^o\d/.test(name)) return 'gpt';
    if (name.includes('claude') || provider === 'anthropic' || vendor === 'anthropic') return 'claude';
    if (name.includes('gemini') || provider === 'gemini' || vendor === 'google') return 'gemini';
    if (name.includes('deepseek') || provider === 'deepseek' || vendor === 'deepseek') return 'deepseek';
    if (name.includes('kimi') || provider === 'moonshot' || vendor === 'moonshotai') return 'kimi';
    if (name.includes('glm') || provider === 'glm' || vendor === 'zhipu') return 'glm';
    if (name.includes('qwen') || vendor === 'qwen') return 'qwen';
    if (name.includes('llama') || vendor === 'meta-llama') return 'llama';
    if (name.includes('mistral') || vendor === 'mistralai') return 'mistral';
    if (provider === 'openrouter') return 'openrouter';
    return 'other';
}

function getCloudFamilyLabel(familyId) {
    const fallback = {
        all: 'Tout',
        gpt: 'GPT',
        codex: 'Codex',
        claude: 'Claude',
        gemini: 'Gemini',
        deepseek: 'DeepSeek',
        kimi: 'Kimi',
        glm: 'GLM',
        qwen: 'Qwen',
        llama: 'Llama',
        mistral: 'Mistral',
        openrouter: 'OpenRouter',
        other: 'Autres',
    };
    return uiT(`modelPicker.cloudFamilies.${familyId}`, fallback[familyId] || familyId);
}

async function loadTerminalCloudModelProfiles() {
    try {
        const result = await apiSettings.getProviderStatus({ discoverModels: true });
        if (!result.ok || !result.data) return TERMINAL_CLOUD_MODELS;

        const profiles = Array.isArray(result.data.terminal_model_profiles)
            ? result.data.terminal_model_profiles
            : [];
        TERMINAL_CLOUD_MODELS = profiles
            .filter(profile => profile.provider !== 'ollama' && profile.terminal_runtime && profile.configured)
            .map(profile => ({
                id: profile.id,
                name: formatTerminalCloudModelName(profile.id),
                desc: `${profile.provider_label || profile.provider} · Cloud · ${profile.discovered ? 'Live' : 'Preset'} · VRAM libre`,
                badge: 'cloud',
                icon: 'cloud',
                toolCapable: true,
                cloud: true,
                provider: profile.provider,
                providerLabel: profile.provider_label,
                family: getCloudModelFamily(profile),
                discovered: profile.discovered === true,
                discoveryError: profile.discovery_error || '',
                contextSize: Number.parseInt(profile.context_size || 0, 10) || DEFAULT_CLOUD_CONTEXT_SIZE,
                maxOutputTokens: Number.parseInt(profile.max_output_tokens || 0, 10) || 0,
                reasoningEfforts: Array.isArray(profile.reasoning_efforts) ? profile.reasoning_efforts : [],
                defaultReasoningEffort: profile.default_reasoning_effort || DEFAULT_CLOUD_REASONING_EFFORT,
            }));
        window.joyboyTerminalCloudModels = TERMINAL_CLOUD_MODELS;
    } catch (err) {
        console.warn('[PICKER] Erreur chargement profils cloud:', err);
    }
    return TERMINAL_CLOUD_MODELS;
}

function dedupeModelsById(models) {
    const seen = new Map();
    for (const model of models || []) {
        if (!model?.id || seen.has(model.id)) continue;
        seen.set(model.id, model);
    }
    return Array.from(seen.values());
}

function mergeCloudChatModels(models, cloudModels) {
    const cloud = Array.isArray(cloudModels) ? cloudModels : [];
    const baseModels = (models || []).filter(model => model?.id !== 'none' || cloud.length === 0);
    return dedupeModelsById([...baseModels, ...cloud]);
}

function isCloudPickerModel(model) {
    return model?.cloud === true || isTerminalCloudModelId(model?.id);
}

function limitCloudModelsByFamily(models, limit = 5) {
    const counts = new Map();
    const limited = [];
    for (const model of models || []) {
        const family = model.family || getCloudModelFamily(model);
        const count = counts.get(family) || 0;
        if (count >= limit) continue;
        counts.set(family, count + 1);
        limited.push({ ...model, family });
    }
    return limited;
}

function sortCloudFamilies(families) {
    return [...families].sort((a, b) => {
        const ai = CLOUD_FAMILY_ORDER.indexOf(a);
        const bi = CLOUD_FAMILY_ORDER.indexOf(b);
        if (ai !== -1 || bi !== -1) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        return getCloudFamilyLabel(a).localeCompare(getCloudFamilyLabel(b));
    });
}

function setModelPickerChatSource(source, pickerId = 'chat', event = null) {
    stopModelPickerControlEvent(event);
    modelPickerChatSource = source === 'cloud' ? 'cloud' : 'local';
    if (modelPickerChatSource === 'local') {
        modelPickerChatFamily = 'all';
    }
    Settings.set('modelPickerChatSource', modelPickerChatSource);
    Settings.set('modelPickerChatFamily', modelPickerChatFamily);
    renderModelPickerList(pickerId);
}

function setModelPickerChatFamily(family, pickerId = 'chat', event = null) {
    stopModelPickerControlEvent(event);
    modelPickerChatFamily = String(family || 'all');
    Settings.set('modelPickerChatFamily', modelPickerChatFamily);
    renderModelPickerList(pickerId);
}

/**
 * Retourne le nom du modèle actif selon le mode
 */
function getActiveModelName(mode) {
    switch (mode) {
        case 'terminal':
            const termModel = (typeof terminalToolModel !== 'undefined' && terminalToolModel)
                || (typeof userSettings !== 'undefined' ? (userSettings.terminalModel || userSettings.chatModel) : null);
            return termModel ? _formatModelName(termModel) : 'Terminal';

        case 'inpaint':
            const inpaintModel = typeof getInpaintModels === 'function'
                ? getInpaintModels().find(m => m.id === selectedInpaintModel)
                : null;
            return inpaintModel?.name || selectedInpaintModel || 'Inpaint';

        case 'text2img':
            const t2iModel = typeof getText2ImgModels === 'function'
                ? getText2ImgModels().find(m => m.id === selectedText2ImgModel)
                : null;
            return t2iModel?.name || selectedText2ImgModel || 'Text2Img';

        case 'chat':
        default:
            if (typeof selectedChatModel !== 'undefined' && selectedChatModel) {
                const chatModel = CHAT_MODELS?.find(m => m.id === selectedChatModel);
                return chatModel?.name || _formatModelName(selectedChatModel);
            }
            if (typeof userSettings !== 'undefined' && userSettings.chatModel) {
                return _formatModelName(userSettings.chatModel);
            }
            return 'Auto';
    }
}

/**
 * Met à jour l'affichage de TOUS les pickers selon le contexte
 * Centralisé pour home, chat et terminal
 */
function updateModelPickerDisplay() {
    const mode = getCurrentMode();
    const hasImage = mode === 'inpaint';

    const homeText = document.getElementById('selected-model-text');
    const chatText = document.getElementById('chat-selected-model-text');

    // Déterminer le bon onglet selon le mode
    let newTab = mode;
    if (mode === 'terminal') newTab = 'chat';  // Terminal utilise l'onglet chat

    // Afficher le modèle approprié selon le mode
    let displayName;
    if (hasImage) {
        displayName = getActiveModelName('inpaint');
    } else if (mode === 'terminal') {
        displayName = getActiveModelName('terminal');
    } else {
        // Déterminer si on est en mode home (text2img) ou chat
        const isHome = document.getElementById('home')?.classList.contains('active');
        displayName = isHome ? getActiveModelName('text2img') : getActiveModelName('chat');
        if (isHome) newTab = 'text2img';
    }

    // Mettre à jour l'onglet actif pour les deux pickers
    const updatePickerTabs = (pickerId) => {
        const picker = document.getElementById(pickerId);
        if (picker) {
            picker.querySelectorAll('.model-picker-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.type === newTab);
            });
        }
    };

    // Auto-switch seulement si on était sur inpaint ou text2img (pas chat manuel)
    if (currentModelTab !== newTab && (currentModelTab === 'inpaint' || currentModelTab === 'text2img' || hasImage)) {
        currentModelTab = newTab;
        updatePickerTabs('model-picker');
        updatePickerTabs('chat-model-picker');
    }

    // Mettre à jour les textes affichés
    if (homeText) homeText.textContent = displayName;
    if (chatText) chatText.textContent = displayName;
}

// TOOL_CAPABLE_KEYWORDS, TOOL_EXCLUDED_KEYWORDS, isToolCapableModel() defined in state.js

function isToolCapable(modelName) {
    return isToolCapableModel(modelName);
}

/**
 * Build a human-readable description for an Ollama model.
 * Uses backend details (params, quant, vision) when available.
 * e.g. "3.8B · Q4_K_M · Tools · 3.0GB" or "7B · Q4_0 · Vision · 4.4GB"
 */
function _buildModelDesc(modelData, toolCapable) {
    const lower = (modelData.name || '').toLowerCase();
    const parts = [];

    // 1. Parameter count (from backend details)
    if (modelData.params) {
        parts.push(modelData.params);
    }

    // 2. Quantization level (from backend details)
    if (modelData.quant) {
        parts.push(modelData.quant);
    }

    // 3. Capabilities
    if (toolCapable) parts.push('Tools');
    if (modelData.vision || lower.includes('llava') || lower.includes('moondream')) parts.push('Vision');
                if (lower.includes('dolphin') || lower.includes('uncensored')) parts.push('Open');
    if (lower.includes('coder') || lower.includes('code')) parts.push('Code');

    // 4. Disk size
    if (modelData.size) parts.push(modelData.size);

    return parts.join(' · ') || 'Modèle local';
}

// Charge les modèles Ollama installés pour le picker
async function loadTextModelsForPicker() {
    try {
        const [installedResponse, availableResponse] = await Promise.all([
            fetch('/ollama/models'),
            fetch('/ollama/search?q=').catch(() => null),
        ]);
        const data = await installedResponse.json();
        const models = data.models || [];
        let availableModels = [];
        if (availableResponse?.ok) {
            const availableData = await availableResponse.json();
            availableModels = Array.isArray(availableData.models) ? availableData.models : [];
        }
        const installedNames = new Set(models.map(model => model.name));

        const installedChatModels = models.map(m => {
            const toolCapable = isToolCapable(m.name);
            const parts = m.name.split(':');
            const baseName = parts[0];           // qwen2.5
            const tag = parts[1] || 'latest';    // 7b, latest, etc.

            // Display name: "qwen2.5 7b" instead of just "qwen2.5"
            const displayName = tag === 'latest' ? baseName : `${baseName} ${tag}`;

            // Build a useful description from backend data
            const desc = _buildModelDesc(m, toolCapable);

            let badge = 'balanced';
            if (toolCapable) badge = 'tools';
            else if (m.name.includes('dolphin')) badge = 'powerful';
            else if (m.name.includes('coder')) badge = 'fast';

            // Icon: vision models get eye, tool-capable get wrench, coders get zap
            let icon = 'brain';
            if (m.vision) icon = 'eye';
            else if (toolCapable) icon = 'wrench';
            else if (m.name.includes('coder')) icon = 'zap';

            return {
                id: m.name,
                name: displayName,
                desc: desc,
                badge: badge,
                icon: icon,
                toolCapable: toolCapable,
                downloaded: true,
                downloadable: false,
                downloadType: 'ollama',
                downloadKey: m.name,
            };
        });
        const availableChatModels = availableModels
            .filter(m => m?.name && !installedNames.has(m.name))
            .map(m => {
                const toolCapable = isToolCapable(m.name);
                const displayName = typeof _formatModelName === 'function' ? _formatModelName(m.name) : m.name;
                let badge = 'download';
                if (m.vision) badge = 'vision';
                else if (m.powerful) badge = 'powerful';
                else if (m.fast) badge = 'fast';
                let icon = 'download';
                if (m.vision) icon = 'eye';
                else if (toolCapable) icon = 'wrench';
                else if (m.fast) icon = 'zap';
                return {
                    id: m.name,
                    name: displayName,
                    desc: [m.desc, m.size].filter(Boolean).join(' · ') || 'Modèle Ollama à télécharger',
                    badge,
                    icon,
                    toolCapable,
                    vision: m.vision === true,
                    downloaded: false,
                    downloadable: true,
                    downloadType: 'ollama',
                    downloadKey: m.name,
                };
            });

        if (installedChatModels.length > 0 || availableChatModels.length > 0) {
            CHAT_MODELS = [...installedChatModels, ...availableChatModels];

            // Trier: installés en premier, puis tool-capable.
            CHAT_MODELS.sort((a, b) => {
                if (a.downloaded && !b.downloaded) return -1;
                if (!a.downloaded && b.downloaded) return 1;
                if (a.toolCapable && !b.toolCapable) return -1;
                if (!a.toolCapable && b.toolCapable) return 1;
                return 0;
            });

            TEXT_MODELS = CHAT_MODELS;  // Alias
        } else {
            // Fallback si aucun modèle
            CHAT_MODELS = [
                { id: 'none', name: 'Aucun modèle', desc: 'Installez un modèle Ollama', badge: 'balanced', icon: 'brain', downloaded: false, downloadable: false }
            ];
            TEXT_MODELS = CHAT_MODELS;
        }

        const cloudProfiles = await loadTerminalCloudModelProfiles();
        CHAT_MODELS = mergeCloudChatModels(CHAT_MODELS, cloudProfiles);
        TEXT_MODELS = CHAT_MODELS;

        // Mettre à jour selectedChatModel depuis les settings
        if (userSettings.chatModel) {
            selectedChatModel = userSettings.chatModel;
            selectedTextModel = selectedChatModel;  // Alias
        } else {
            const firstInstalled = CHAT_MODELS.find(model => model.downloaded && model.id !== 'none');
            if (firstInstalled) {
                selectedChatModel = firstInstalled.id;
                selectedTextModel = selectedChatModel;
            }
        }

        // Re-render les pickers pour afficher les modèles
        renderModelPickerList('home');
        renderModelPickerList('chat');

        console.log('[PICKER] Modèles texte chargés:', TEXT_MODELS.length);
    } catch (e) {
        console.log('[PICKER] Erreur chargement modèles:', e);
        TEXT_MODELS = [
            { id: 'error', name: 'Erreur', desc: 'Impossible de charger les modèles', badge: 'balanced', icon: 'brain' }
        ];
    }
}

// ===== MODEL PICKER (Custom) =====
let currentModelTab = 'inpaint';  // 'inpaint', 'text2img', 'chat'
let selectedInpaintModel = Settings.get('selectedInpaintModel');
let selectedText2ImgModel = Settings.get('selectedText2ImgModel');
let selectedChatModel = null;  // Sera défini depuis userSettings.chatModel

// Modèles INPAINT (avec image en entrée)
// backend: 'gguf' = GGUF uniquement, 'diffusers' = Diffusers, 'both' = les deux
const INPAINT_MODELS = [
// === FLUX KONTEXT GGUF (pour GPUs plus petits) ===
    { id: 'Flux Kontext Q2', name: 'Flux Kontext Q2', desc: '4GB • petite VRAM', badge: 'fast', icon: 'brain', backend: 'gguf', noMask: true },
    { id: 'Flux Kontext Q4', name: 'Flux Kontext Q4', desc: '6.8GB • Recommandé', badge: 'supreme', icon: 'brain', backend: 'gguf', noMask: true },
    { id: 'Flux Kontext Q6', name: 'Flux Kontext Q6', desc: '9.8GB • Haute qualité', badge: 'supreme', icon: 'brain', backend: 'gguf', noMask: true },
    { id: 'Flux Kontext Q8', name: 'Flux Kontext Q8', desc: '12.7GB • Max qualité', badge: 'supreme', icon: 'brain', backend: 'gguf', noMask: true },
    // === SUPRÊME (12B, Diffusers) ===
    { id: 'Flux.1 Fill Dev', name: 'Flux.1 Fill 12B', desc: '12B • Suprême • Lent (~45s)', badge: 'supreme', icon: 'star', backend: 'diffusers' },
    { id: 'Flux Fill INT4', name: 'Flux Fill INT4', desc: '12B • INT4 ~6GB VRAM • 8GB GPU', badge: 'powerful', icon: 'star', backend: 'diffusers' },
    { id: 'Flux Fill INT8', name: 'Flux Fill INT8', desc: '12B • INT8 • Rapide', badge: 'supreme', icon: 'star', backend: 'diffusers' },
    // === epiCRealism XL - 3 niveaux de quantification ===
    { id: 'epiCRealism XL (Fast)', name: 'epiCRealism (Fast)', desc: 'INT4 • Ultra rapide', badge: 'fast', icon: 'zap', backend: 'diffusers' },
    { id: 'epiCRealism XL (Moyen)', name: 'epiCRealism (Moyen)', desc: 'INT8 • Recommandé', badge: 'balanced', icon: 'zap', backend: 'diffusers' },
    { id: 'epiCRealism XL (Normal)', name: 'epiCRealism (Normal)', desc: 'FP16 • Max qualité', badge: 'powerful', icon: 'zap', backend: 'diffusers' },
    // === CyberRealistic Pony XL v16 ===
    { id: 'CyberRealistic Pony (Moyen)', name: 'CyberRealistic Pony (Moyen)', desc: 'INT8 • Pony XL v16', badge: 'balanced', icon: 'sparkles', backend: 'diffusers' },
    { id: 'CyberRealistic Pony (Normal)', name: 'CyberRealistic Pony (Normal)', desc: 'FP16 • Pony XL v16', badge: 'powerful', icon: 'sparkles', backend: 'diffusers' },
];

// Modèles TEXT2IMG (génération depuis texte seul)
const TEXT2IMG_MODELS = [
    { id: 'epiCRealism XL', name: 'epiCRealism (Moyen)', desc: 'INT8 • Recommandé', badge: 'balanced', icon: 'zap' },
    { id: 'CyberRealistic Pony (Moyen)', name: 'CyberRealistic Pony (Moyen)', desc: 'INT8 • Pony XL v16', badge: 'balanced', icon: 'sparkles' },
    // === Flux ===
    { id: 'Flux Dev INT4', name: 'Flux Dev INT4', desc: 'NF4 12B • Top qualité', badge: 'powerful', icon: 'sparkles' },
    { id: 'Flux Dev INT8', name: 'Flux Dev INT8', desc: 'INT8 12B • Rapide', badge: 'supreme', icon: 'sparkles' },
    // === Standard ===
    { id: 'SDXL Turbo', name: 'SDXL Turbo', desc: 'Rapide (4 steps)', badge: 'fast', icon: 'feather' },
];

function getPackUiOverrides() {
    return window.joyboyPackUiOverrides || {};
}

function mergeModelCatalog(baseModels = [], extraModels = []) {
    const merged = new Map();
    [...(baseModels || []), ...(extraModels || [])].forEach(model => {
        if (!model || !model.id) return;
        merged.set(model.id, { ...merged.get(model.id), ...model });
    });
    return Array.from(merged.values());
}

function getPackModelEntries(bucket) {
    const imageModels = getPackUiOverrides().image_models || {};
    const entries = imageModels?.[bucket];
    return Array.isArray(entries) ? entries.filter(model => model && model.id) : [];
}

function getInpaintModels() {
    return mergeModelCatalog(INPAINT_MODELS, getPackModelEntries('inpaint'));
}

function getText2ImgModels() {
    return mergeModelCatalog(TEXT2IMG_MODELS, getPackModelEntries('text2img'));
}

const MODEL_PICKER_DESC_KEYS = new Map([
    ['6.8gb • recommande', 'recommended6gb'],
    ['9.8gb • haute qualite', 'highQuality9gb'],
    ['12.7gb • max qualite', 'maxQuality12gb'],
    ['12b • supreme • lent (~45s)', 'supremeSlow'],
    ['12b • int8 • rapide', 'int8Fast'],
    ['int4 • ultra rapide', 'int4UltraFast'],
    ['int8 • recommande', 'int8Recommended'],
    ['fp16 • max qualite', 'fp16MaxQuality'],
    ['realiste', 'realistic'],
    ['pony xl v16 • realiste', 'ponyRealistic'],
    ['nf4 12b • top qualite', 'nf4TopQuality'],
    ['int8 12b • rapide', 'int8DevFast'],
    ['rapide (4 steps)', 'fastFourSteps'],
]);

function normalizePickerText(value) {
    return String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}

function translateModelPickerDesc(model) {
    const raw = String(model?.desc || '');
    const key = MODEL_PICKER_DESC_KEYS.get(normalizePickerText(raw));
    return key ? uiT(`modelPicker.descriptions.${key}`, raw) : raw;
}

function modelPickerBadgeLabel(model) {
    if (model?.badge === 'fast') return uiT('modelPicker.badges.fast', 'Rapide');
    if (model?.badge === 'powerful') return uiT('modelPicker.badges.powerful', 'Fort');
    if (model?.badge === 'vision') return uiT('modelPicker.badges.vision', 'Vision');
    if (model?.badge === 'download') return uiT('modelPicker.badges.download', 'Télécharger');
    if (model?.badge === 'tools') return uiT('modelPicker.badges.tools', 'Tools');
    if (model?.badge === 'cloud') return uiT('modelPicker.badges.cloud', 'Cloud');
    if (model?.imported) return uiT('modelPicker.badges.local', 'Local');
    return uiT('modelPicker.badges.balanced', 'Équilibré');
}

const modelPickerInstallRefreshInFlight = new Map();

function pickerEscapeHtml(value) {
    if (typeof escapeHtml === 'function') return escapeHtml(String(value ?? ''));
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getModelInstallKindForTab(tab) {
    if (tab === 'inpaint' || tab === 'text2img') return 'image';
    if (tab === 'video') return 'video';
    return 'ollama';
}

function hasPickerInstallStatusForTab(tab) {
    const kind = getModelInstallKindForTab(tab);
    if (kind === 'image') {
        return typeof allImageModels !== 'undefined' && Array.isArray(allImageModels) && allImageModels.length > 0;
    }
    if (kind === 'video') {
        const runtimeModels = window.videoModelRuntimeCatalog?.models;
        return (typeof allVideoModels !== 'undefined' && Array.isArray(allVideoModels) && allVideoModels.length > 0)
            || (Array.isArray(runtimeModels) && runtimeModels.length > 0);
    }
    return Array.isArray(CHAT_MODELS) && CHAT_MODELS.some(model => model.downloaded === true || model.downloaded === false || model.cloud === true);
}

function findImageModelStatusForPicker(model) {
    if (typeof allImageModels === 'undefined' || !Array.isArray(allImageModels)) return null;
    const id = String(model?.id || model?.name || '').trim();
    const key = String(model?.downloadKey || model?.key || '').trim();
    return allImageModels.find(item =>
        item?.name === id
        || item?.key === id
        || (key && item?.key === key)
        || (key && item?.name === key)
    ) || null;
}

function findVideoModelStatusForPicker(modelOrId) {
    const id = String(modelOrId?.id || modelOrId?.key || modelOrId || '').trim();
    const runtimeModels = Array.isArray(window.videoModelRuntimeCatalog?.models) ? window.videoModelRuntimeCatalog.models : [];
    const statusModels = (typeof allVideoModels !== 'undefined' && Array.isArray(allVideoModels)) ? allVideoModels : [];
    return [...statusModels, ...runtimeModels].find(item =>
        item?.id === id || item?.key === id || item?.repo === id || item?.repo_id === id
    ) || null;
}

function getPickerModelInstallInfo(model, tab) {
    const kind = getModelInstallKindForTab(tab);
    const modelId = String(model?.id || model?.key || model?.name || '').trim();
    if (!modelId || modelId === 'loading') {
        return { kind, installed: false, downloadable: false, status: 'unknown', label: uiT('modelPicker.install.checking', 'Vérif...') };
    }
    if (isCloudPickerModel(model)) {
        return { kind, installed: true, downloadable: false, status: 'cloud', label: uiT('modelPicker.install.cloud', 'Cloud') };
    }

    if (kind === 'image') {
        const meta = findImageModelStatusForPicker(model);
        if (!meta) {
            return { kind, installed: true, downloadable: false, status: 'external', label: uiT('modelPicker.install.local', 'Local') };
        }
        if (meta.downloading) {
            return { kind, installed: false, downloadable: false, status: 'downloading', label: uiT('modelPicker.install.downloading', 'Téléchargement'), downloadKey: meta.key, meta };
        }
        return {
            kind,
            installed: meta.downloaded === true,
            downloadable: meta.downloaded !== true,
            status: meta.downloaded === true ? 'installed' : 'missing',
            label: meta.downloaded === true ? uiT('modelPicker.install.installed', 'Installé') : uiT('modelPicker.install.missing', 'À télécharger'),
            downloadKey: meta.key,
            meta,
        };
    }

    if (kind === 'video') {
        const meta = findVideoModelStatusForPicker(model);
        if (!meta) {
            return { kind, installed: true, downloadable: false, status: 'unknown', label: uiT('modelPicker.install.local', 'Local') };
        }
        if (meta.downloading) {
            return { kind, installed: false, downloadable: false, status: 'downloading', label: uiT('modelPicker.install.downloading', 'Téléchargement'), downloadKey: meta.key || meta.id, meta };
        }
        return {
            kind,
            installed: meta.downloaded === true,
            downloadable: meta.downloaded !== true,
            status: meta.downloaded === true ? 'installed' : 'missing',
            label: meta.downloaded === true ? uiT('modelPicker.install.installed', 'Installé') : uiT('modelPicker.install.missing', 'À télécharger'),
            downloadKey: meta.key || meta.id,
            meta,
        };
    }

    if (modelId === 'download-vision') {
        return { kind, installed: false, downloadable: true, status: 'missing', label: uiT('modelPicker.install.missing', 'À télécharger'), downloadKey: 'moondream:1.8b' };
    }
    if (model.downloaded === false || model.downloadable === true) {
        return { kind, installed: false, downloadable: true, status: 'missing', label: uiT('modelPicker.install.missing', 'À télécharger'), downloadKey: model.downloadKey || modelId, meta: model };
    }
    if (model.downloaded === true) {
        return { kind, installed: true, downloadable: false, status: 'installed', label: uiT('modelPicker.install.installed', 'Installé'), downloadKey: model.downloadKey || modelId, meta: model };
    }
    return { kind, installed: true, downloadable: false, status: 'installed', label: uiT('modelPicker.install.installed', 'Installé'), downloadKey: modelId, meta: model };
}

function renderPickerInstallBadge(installInfo) {
    if (!installInfo) return '';
    return `<span class="model-picker-install ${installInfo.status}">${pickerEscapeHtml(installInfo.label)}</span>`;
}

async function refreshModelPickerInstallStateForTab(tab, pickerId = 'home', force = false) {
    const kind = getModelInstallKindForTab(tab);
    if (!force && hasPickerInstallStatusForTab(tab)) return;
    if (modelPickerInstallRefreshInFlight.has(kind)) {
        await modelPickerInstallRefreshInFlight.get(kind);
        return;
    }
    const refreshPromise = (async () => {
        try {
            if (kind === 'image' && typeof apiModels !== 'undefined' && apiModels?.checkModels) {
                const result = await apiModels.checkModels();
                if (result.ok && result.data?.success && Array.isArray(result.data.models) && typeof allImageModels !== 'undefined') {
                    allImageModels = result.data.models;
                }
            } else if (kind === 'video') {
                const response = await fetch('/api/video-models/status?advanced=1&allow_experimental=1');
                const data = await response.json();
                if (response.ok && data?.success && Array.isArray(data.models)) {
                    if (typeof allVideoModels !== 'undefined') allVideoModels = data.models;
                    window.videoModelRuntimeCatalog = { ...(window.videoModelRuntimeCatalog || {}), ...data, models: data.models };
                }
            } else if (kind === 'ollama' && typeof loadTextModelsForPicker === 'function') {
                await loadTextModelsForPicker();
                return;
            }
        } catch (error) {
            console.warn('[PICKER] Statut modèles indisponible:', error);
        } finally {
            modelPickerInstallRefreshInFlight.delete(kind);
        }
        renderModelPickerList(pickerId);
    })();
    modelPickerInstallRefreshInFlight.set(kind, refreshPromise);
    await refreshPromise;
}

function getInstallDialogTypeLabel(kind) {
    if (kind === 'image') return 'Image';
    if (kind === 'video') return 'Vidéo';
    return 'LLM local';
}

function showModelInstallDialog(model, installInfo) {
    return new Promise(resolve => {
        const existing = document.querySelector('.model-install-overlay');
        if (existing) existing.remove();
        const kindLabel = getInstallDialogTypeLabel(installInfo.kind);
        const modelName = model?.name || model?.id || installInfo.downloadKey || 'Modèle';
        const modelDesc = model?.desc || installInfo.meta?.description || installInfo.meta?.desc || '';
        const overlay = document.createElement('div');
        overlay.className = 'model-install-overlay';
        overlay.innerHTML = `
            <div class="model-install-dialog" role="dialog" aria-modal="true">
                <button type="button" class="model-install-close" aria-label="Fermer">
                    <i data-lucide="x"></i>
                </button>
                <div class="model-install-icon">
                    <i data-lucide="${installInfo.kind === 'video' ? 'clapperboard' : installInfo.kind === 'image' ? 'image' : 'download'}"></i>
                </div>
                <div class="model-install-kicker">${pickerEscapeHtml(kindLabel)} · ${pickerEscapeHtml(installInfo.label)}</div>
                <h3>${pickerEscapeHtml(modelName)}</h3>
                <p>${pickerEscapeHtml(modelDesc || `Ce modèle n'est pas encore installé sur cette machine.`)}</p>
                <div class="model-install-note">
                    <i data-lucide="hard-drive-download"></i>
                    <span>Pour l'utiliser, JoyBoy doit d'abord ouvrir la page Modèles et lancer le téléchargement.</span>
                </div>
                <div class="model-install-actions">
                    <button type="button" class="model-install-btn ghost" data-action="cancel">Annuler</button>
                    <button type="button" class="model-install-btn primary" data-action="download">
                        <i data-lucide="download"></i>
                        Télécharger
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        if (window.lucide) lucide.createIcons();

        const close = (value) => {
            overlay.classList.remove('open');
            setTimeout(() => overlay.remove(), 120);
            resolve(value);
        };
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay || event.target.closest('[data-action="cancel"]') || event.target.closest('.model-install-close')) {
                close(false);
            }
            if (event.target.closest('[data-action="download"]')) {
                close(true);
            }
        });
        requestAnimationFrame(() => overlay.classList.add('open'));
    });
}

function openModelInstallDestination(installInfo, model, tab) {
    if (typeof openModelsHub === 'function') openModelsHub();
    setTimeout(() => {
        if (installInfo.kind === 'image') {
            const subtab = document.getElementById('models-subtab-image');
            if (typeof switchModelsSubtab === 'function') switchModelsSubtab('image', subtab);
            const inner = document.getElementById('models-image-tab-catalog');
            if (typeof switchModelsInnerTab === 'function') switchModelsInnerTab('models-image-panel', 'catalog', inner);
            if (typeof toggleImageModelFilter === 'function') {
                toggleImageModelFilter(tab === 'text2img' ? 'txt2img' : 'inpaint');
            }
        } else if (installInfo.kind === 'video') {
            const subtab = document.getElementById('models-subtab-video');
            if (typeof switchModelsSubtab === 'function') switchModelsSubtab('video', subtab);
            const inner = document.getElementById('models-video-tab-catalog');
            if (typeof switchModelsInnerTab === 'function') switchModelsInnerTab('models-video-panel', 'catalog', inner);
        } else {
            const subtab = document.getElementById('models-subtab-text');
            if (typeof switchModelsSubtab === 'function') switchModelsSubtab('text', subtab);
            const inner = document.getElementById('models-text-tab-available');
            if (typeof switchModelsInnerTab === 'function') switchModelsInnerTab('models-text-panel', 'install', inner);
            const input = document.getElementById('ollama-search-input');
            if (input && installInfo.downloadKey) input.value = installInfo.downloadKey;
            if (typeof searchOllamaModels === 'function') searchOllamaModels();
        }
    }, 80);
}

async function startPickerModelDownload(installInfo, model, tab) {
    const downloadKey = installInfo.downloadKey || model?.downloadKey || model?.key || model?.id;
    if (!downloadKey) {
        if (typeof Toast !== 'undefined') Toast.error('Téléchargement impossible', 'Modèle introuvable dans le catalogue local.');
        return;
    }
    setTimeout(async () => {
        try {
            if (installInfo.kind === 'image' && typeof downloadImageModel === 'function') {
                if (typeof checkModelsStatus === 'function') await checkModelsStatus();
                const button = [...document.querySelectorAll('#models-image-panel .btn-install-model')]
                    .find(btn => btn.dataset?.modelKey === downloadKey);
                await downloadImageModel(downloadKey, button || null);
            } else if (installInfo.kind === 'video' && typeof downloadVideoModel === 'function') {
                if (typeof checkVideoModelsStatus === 'function') await checkVideoModelsStatus();
                const button = [...document.querySelectorAll('#models-video-panel .btn-install-model')]
                    .find(btn => btn.dataset?.modelId === downloadKey);
                await downloadVideoModel(downloadKey, button || null);
            } else if (installInfo.kind === 'ollama' && typeof pullOllamaModel === 'function') {
                if (typeof searchOllamaModels === 'function') await searchOllamaModels();
                const button = [...document.querySelectorAll('#ollama-search-results .btn-install-model')]
                    .find(btn => btn.getAttribute('onclick')?.includes(downloadKey));
                await pullOllamaModel(downloadKey, button || null);
            }
        } catch (error) {
            if (typeof Toast !== 'undefined') Toast.error('Erreur', error.message || String(error));
        } finally {
            refreshModelPickerInstallStateForTab(tab, activePickerId || 'home', true);
        }
    }, 220);
}

async function handleMissingPickerModel(model, tab, pickerId = 'home') {
    const installInfo = getPickerModelInstallInfo(model, tab);
    document.querySelectorAll('.model-picker').forEach(p => p.classList.remove('open'));
    activePickerId = null;
    document.removeEventListener('click', closeModelPickerOnClickOutside);

    if (installInfo.status === 'downloading') {
        openModelInstallDestination(installInfo, model, tab);
        if (typeof Toast !== 'undefined') Toast.info('Téléchargement déjà en cours', `${model?.name || model?.id || 'Ce modèle'} est déjà en téléchargement.`);
        return false;
    }

    const confirmed = await showModelInstallDialog(model, installInfo);
    if (!confirmed) return false;
    openModelInstallDestination(installInfo, model, tab);
    await startPickerModelDownload(installInfo, model, tab);
    return false;
}

window.ensureJoyboyModelInstalledForUse = async function ensureJoyboyModelInstalledForUse(kind, modelId, options = {}) {
    const tab = options.tab || (kind === 'image' ? (options.hasImage ? 'inpaint' : 'text2img') : kind === 'video' ? 'video' : 'chat');
    if (!hasPickerInstallStatusForTab(tab)) {
        await refreshModelPickerInstallStateForTab(tab, options.pickerId || 'home', true);
    }
    let model = options.model || null;
    if (!model && tab === 'video') model = findVideoModelStatusForPicker(modelId);
    if (!model && tab !== 'video') model = getModelsForTab(tab).find(item => item.id === modelId || item.name === modelId);
    model = model || { id: modelId, name: modelId };
    const installInfo = getPickerModelInstallInfo(model, tab);
    if (installInfo.installed) return true;
    await handleMissingPickerModel(model, tab, options.pickerId || 'home');
    return false;
};

// Compat: selectedImageModel pointe vers inpaint par défaut
let selectedImageModel = selectedInpaintModel;

// Vision model (pour terminal mode avec images)
let selectedVisionModel = Settings.get('selectedVisionModel');

// CHAT_MODELS - chargé dynamiquement depuis Ollama
let CHAT_MODELS = [
    { id: 'loading', name: 'Chargement...', desc: 'Récupération des modèles', badge: 'balanced', icon: 'brain' }
];

// VISION_MODELS - filtré dynamiquement depuis CHAT_MODELS
let VISION_MODELS_LIST = [];

// Alias pour compat
let TEXT_MODELS = CHAT_MODELS;
let selectedTextModel = selectedChatModel;

function isAdultModeEnabled() {
    const adultExposure = window.joyboyFeatureExposure?.adult;
    if (adultExposure && typeof adultExposure.runtime_available === 'boolean') {
        return adultExposure.runtime_available === true;
    }
    return !(window.joyboyFeatureFlags && window.joyboyFeatureFlags.adult_features_enabled === false);
}

function isAdultImageModel(model) {
    return model?.adult === true;
}

window.isAdultModeEnabled = isAdultModeEnabled;

function getAdultGenerationPayload() {
    const adultEnabled = isAdultModeEnabled();
    return {
        nsfw_strength: adultEnabled ? (userSettings.nsfwStrength ?? 0.90) : null,
        lora_nsfw_enabled: adultEnabled && userSettings.loraNsfwEnabled === true,
        lora_nsfw_strength: userSettings.loraNsfwStrength ?? 0.5,
        lora_skin_enabled: adultEnabled && userSettings.loraSkinEnabled === true,
        lora_skin_strength: userSettings.loraSkinStrength ?? 0.3,
        lora_breasts_enabled: adultEnabled && userSettings.loraBreastsEnabled === true,
        lora_breasts_strength: userSettings.loraBreastsStrength ?? 0.7,
    };
}

window.getAdultGenerationPayload = getAdultGenerationPayload;

function getFirstVisibleModelId(models) {
    const visible = (models || []).filter(model => !isAdultImageModel(model) || isAdultModeEnabled());
    return visible[0]?.id || models?.[0]?.id || null;
}

function getModelPickerHelper(tab, pickerId) {
    const adultEnabled = isAdultModeEnabled();
    if (pickerId === 'edit') {
        return adultEnabled
            ? uiT('modelPicker.helper.editAdvanced', 'Edition locale avec masque. Les modèles sans masque sont retirés ici pour éviter les faux choix.')
            : uiT('modelPicker.helper.editPublic', 'Edition locale avec masque. Les modèles et contrôles avancés sont masqués sur cette machine.');
    }
    if (tab === 'inpaint') {
        return adultEnabled
            ? uiT('modelPicker.helper.inpaintAdvanced', 'Inpaint = modifier une image existante. Flux Kontext pilote mieux les edits par prompt, SDXL reste plus local et stable.')
            : uiT('modelPicker.helper.inpaintPublic', 'Inpaint = modifier une image existante. Les surfaces avancées sont retirées, seuls les modèles généralistes restent visibles.');
    }
    if (tab === 'text2img') {
        return uiT('modelPicker.helper.text2img', 'Text2Img = créer depuis le prompt seul. Choisis surtout selon vitesse, rendu photo et VRAM.');
    }
    if (tab === 'vision') {
        return uiT('modelPicker.helper.vision', 'Vision = analyser une image, pas la générer. Pratique pour décrire, router et comprendre une scène.');
    }
    if (tab === 'chat') {
        return uiT('modelPicker.helper.chat', 'Chat = conversation et orchestration. Le picker suit ton mode courant pour éviter les mauvais modèles.');
    }
    return "";
}

function getModelPickerUseCase(model, tab, pickerId) {
    if (!model) return "";

    const hints = [];
    if (pickerId === 'edit' && !model.noMask) hints.push(uiT('modelPicker.useCase.maskCompatible', 'compatible masque'));
    if (model.noMask) hints.push(uiT('modelPicker.useCase.promptDriven', 'pilotage prompt'));
    if (model.backend === 'gguf') hints.push(uiT('modelPicker.useCase.lightVram', 'VRAM légère'));
    if (model.backend === 'diffusers' && tab === 'inpaint') hints.push(uiT('modelPicker.useCase.localRetouch', 'retouche locale'));
    if (tab === 'text2img') hints.push(uiT('modelPicker.useCase.pureCreation', 'création pure'));
    if (model.badge === 'fast') hints.push(uiT('modelPicker.useCase.fastStartup', 'startup rapide'));
    if (model.badge === 'powerful') hints.push(uiT('modelPicker.useCase.betterFidelity', 'meilleure fidélité'));
    if (model.badge === 'vision') hints.push(uiT('modelPicker.useCase.imageAnalysis', 'analyse image'));
    if (model.cloud) hints.push(uiT('modelPicker.useCase.cloudRuntime', 'LLM cloud'));
    if (model.adult === true && isAdultModeEnabled()) hints.push(uiT('modelPicker.useCase.localPack', 'pack local'));

    return hints.slice(0, 2).join(' • ');
}

window.applyJoyboyFeatureFlags = function applyJoyboyFeatureFlags(features = {}) {
    window.joyboyFeatureFlags = { ...(window.joyboyFeatureFlags || {}), ...features };

    if (!isAdultModeEnabled()) {
        if (isAdultImageModel(getInpaintModels().find(model => model.id === selectedInpaintModel))) {
            const safeInpaint = getFirstVisibleModelId(getInpaintModels());
            if (safeInpaint) Settings.set('selectedInpaintModel', safeInpaint);
        }
        if (isAdultImageModel(getText2ImgModels().find(model => model.id === selectedText2ImgModel))) {
            const safeText2Img = getFirstVisibleModelId(getText2ImgModels());
            if (safeText2Img) Settings.set('selectedText2ImgModel', safeText2Img);
        }
        if (typeof currentImageFilter !== 'undefined' && currentImageFilter === 'nsfw') {
            currentImageFilter = 'all';
        }
    }

    updateModelPickerDisplay();
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
        renderModelPickerList('edit');
    }
    if (typeof renderAvailableImageModels === 'function') {
        renderAvailableImageModels();
    }
};

async function loadJoyboyFeatureFlags() {
    try {
        const result = await apiSettings.getFeatureFlags();
        if (result.ok && result.data?.success) {
            window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
            window.applyJoyboyFeatureFlags(result.data.features || {});
        }
    } catch (err) {
        console.warn('[FEATURES] Failed to hydrate UI feature flags:', err);
    }
}

// ===== SETTINGS SUBSCRIBERS — sync local vars + UI when Settings change =====
Settings.subscribe('selectedInpaintModel', (val) => {
    selectedInpaintModel = val;
    selectedImageModel = val;  // Compat
    updateModelPickerDisplay();
    renderModelPickerList('home');
    renderModelPickerList('chat');
});

Settings.subscribe('selectedText2ImgModel', (val) => {
    selectedText2ImgModel = val;
    updateModelPickerDisplay();
    renderModelPickerList('home');
    renderModelPickerList('chat');
});

Settings.subscribe('selectedVisionModel', (val) => {
    selectedVisionModel = val;
    if (typeof terminalMode !== 'undefined' && terminalMode) {
        terminalVisionModel = val;
    }
    updateModelPickerDisplay();
    renderModelPickerList('home');
    renderModelPickerList('chat');
});

Settings.subscribe('chatModel', (val) => {
    selectedChatModel = val;
    selectedTextModel = val;  // Compat
    // Update settings modal select
    const settingsSelect = document.getElementById('settings-chat-model');
    if (settingsSelect) settingsSelect.value = val;
    // Update picker display
    updateModelPickerDisplay();
    renderModelPickerList('home');
    renderModelPickerList('chat');
});

Settings.subscribe('videoModel', (val) => {
    // Sync settings modal select
    const videoSelect = document.getElementById('settings-video-model');
    if (videoSelect) videoSelect.value = val;
    if (typeof updateVideoQualityVisibility === 'function') updateVideoQualityVisibility();
});

Settings.subscribe('videoQuality', (val) => {
    const qualitySelect = document.getElementById('settings-video-quality');
    if (qualitySelect) qualitySelect.value = val;
});

Settings.subscribe('showActionBar', (val) => {
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
        sidebar.classList.toggle('hidden', !val);
    }
    const toggle = document.getElementById('toggle-show-action-bar');
    if (toggle) toggle.classList.toggle('active', val);
});

Settings.subscribe('sidebarCollapsed', (val) => {
    const sidebar = document.getElementById('conversations-sidebar');
    if (sidebar) {
        sidebar.classList.toggle('collapsed', val);
        document.body.classList.toggle('sidebar-collapsed', val);
    }
});

/**
 * Filtre les modèles vision depuis la liste des modèles chat
 */
function filterVisionModels() {
    if (!CHAT_MODELS || CHAT_MODELS.length === 0) return [];

    const visionKeywords = ['llava', 'moondream', 'bakllava', 'minicpm-v', 'llava-llama3', 'llava-phi3'];

    VISION_MODELS_LIST = CHAT_MODELS.filter(model => {
        const modelName = model.id.toLowerCase();
        return visionKeywords.some(keyword => modelName.includes(keyword));
    }).map(model => ({
        ...model,
        badge: 'vision',
        icon: 'eye'
    }));

    // Si aucun modèle vision trouvé, ajouter une option pour en télécharger
    if (VISION_MODELS_LIST.length === 0) {
        VISION_MODELS_LIST = [{
            id: 'download-vision',
            name: 'Télécharger moondream',
            desc: 'Modèle vision léger (~1.7GB)',
            badge: 'download',
            icon: 'download'
        }];
    }

    return VISION_MODELS_LIST;
}

function getModelIcon(iconType) {
    const icons = {
        'auto': '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
        'camera': '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
        'star': '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
        'image': '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
        'brain': '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/><path d="M12 10v8"/>',
        'zap': '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
        'feather': '<path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"/><line x1="16" y1="8" x2="2" y2="22"/><line x1="17.5" y1="15" x2="9" y2="15"/>',
        'eye': '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
        'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
        'wrench': '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
        'cloud': '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    };
    return icons[iconType] || icons['auto'];
}

/**
 * Télécharge un modèle vision (moondream par défaut)
 */
async function downloadVisionModel() {
    const model = 'moondream:1.8b';

    // Afficher un message
    if (typeof Toast !== 'undefined') {
        Toast.info(uiT('models.downloadingModel', 'Téléchargement de {model}...', { model }));
    }

    // Fermer le picker
    document.querySelectorAll('.model-picker').forEach(p => p.classList.remove('open'));

    try {
        const result = await apiOllama.pull(model);
        if (result.ok) {
            if (typeof Toast !== 'undefined') {
                Toast.success(uiT('models.modelInstalled', '{model} installé !', { model }));
            }

            // Rafraîchir la liste des modèles
            await loadTextModelsForPicker();

            // Sélectionner le nouveau modèle
            selectedVisionModel = model;
            Settings.set('selectedVisionModel', model);

            if (typeof terminalMode !== 'undefined' && terminalMode) {
                terminalVisionModel = model;
            }
        } else {
            if (typeof Toast !== 'undefined') {
                Toast.error(uiT('common.errorWithMessage', 'Erreur : {error}', { error: result.error }));
            }
        }
    } catch (err) {
        console.error('[VISION] Erreur téléchargement:', err);
        if (typeof Toast !== 'undefined') {
            Toast.error(uiT('models.downloadError', 'Erreur de téléchargement'));
        }
    }
}

let activePickerId = null;

function stopModelPickerControlEvent(event) {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
}

function toggleModelPicker(pickerId = 'home') {
    const pickerElement = pickerId === 'chat' ?
        document.getElementById('chat-model-picker') :
        document.getElementById('model-picker');

    if (!pickerElement) return;

    // Close any other open picker
    document.querySelectorAll('.model-picker.open').forEach(p => {
        if (p !== pickerElement) p.classList.remove('open');
    });

    const isOpen = pickerElement.classList.toggle('open');
    activePickerId = isOpen ? pickerId : null;

    if (isOpen) {
        const isTerminalPicker = typeof terminalMode !== 'undefined' && terminalMode;
        const tabsContainer = pickerElement.querySelector('.model-picker-tabs');

        if (pickerId === 'chat' && !isTerminalPicker) {
            const validChatTabs = ['inpaint', 'text2img', 'chat'];
            if (!validChatTabs.includes(currentModelTab)) {
                currentModelTab = 'chat';
            }
            if (tabsContainer) {
                tabsContainer.innerHTML = `
                    <button class="model-picker-tab ${currentModelTab === 'inpaint' ? 'active' : ''}" data-type="inpaint" onclick="switchModelTab(event, 'inpaint', '${pickerId}')">
                        <i data-lucide="eraser"></i>
                        Inpaint
                    </button>
                    <button class="model-picker-tab ${currentModelTab === 'text2img' ? 'active' : ''}" data-type="text2img" onclick="switchModelTab(event, 'text2img', '${pickerId}')">
                        <i data-lucide="image"></i>
                        Text2Img
                    </button>
                    <button class="model-picker-tab ${currentModelTab === 'chat' ? 'active' : ''}" data-type="chat" onclick="switchModelTab(event, 'chat', '${pickerId}')">
                        <i data-lucide="message-square"></i>
                        Chat
                    </button>
                `;
                if (window.lucide) lucide.createIcons();
            }
        }

        // En mode terminal, afficher Chat + Vision tabs
        if (isTerminalPicker) {
            // Mettre à jour les tabs pour le mode terminal
            if (tabsContainer) {
                tabsContainer.innerHTML = `
                    <button class="model-picker-tab ${currentModelTab === 'chat' ? 'active' : ''}" data-type="chat" onclick="switchModelTab(event, 'chat', '${pickerId}')">
                        <i data-lucide="message-square"></i>
                        Chat
                    </button>
                    <button class="model-picker-tab ${currentModelTab === 'vision' ? 'active' : ''}" data-type="vision" onclick="switchModelTab(event, 'vision', '${pickerId}')">
                        <i data-lucide="eye"></i>
                        Vision
                    </button>
                `;
                // Réinitialiser les icônes Lucide
                if (window.lucide) lucide.createIcons();
            }

            // Par défaut sur chat, sauf si une image est présente
            if (currentModelTab !== 'chat' && currentModelTab !== 'vision') {
                currentModelTab = (typeof currentImage !== 'undefined' && currentImage) ? 'vision' : 'chat';
            }
        }

        renderModelPickerList(pickerId);
        refreshModelPickerInstallStateForTab(getPickerEffectiveTab(pickerId), pickerId);
        setTimeout(() => {
            document.addEventListener('click', closeModelPickerOnClickOutside);
        }, 10);
    } else {
        document.removeEventListener('click', closeModelPickerOnClickOutside);
    }
}

function closeModelPickerOnClickOutside(e) {
    const pickers = document.querySelectorAll('.model-picker');
    let clickedInside = false;

    pickers.forEach(picker => {
        if (picker.contains(e.target)) clickedInside = true;
    });

    if (!clickedInside) {
        pickers.forEach(p => p.classList.remove('open'));
        activePickerId = null;
        document.removeEventListener('click', closeModelPickerOnClickOutside);
    }
}

function switchModelTab(typeOrEvent, pickerIdOrType = 'home', maybePickerId = 'home') {
    let type = typeOrEvent;
    let pickerId = pickerIdOrType;
    if (typeOrEvent && typeof typeOrEvent === 'object') {
        stopModelPickerControlEvent(typeOrEvent);
        type = pickerIdOrType;
        pickerId = maybePickerId || 'home';
    }
    currentModelTab = type;

    // Update tab UI for the specific picker
    const pickerElement = pickerId === 'chat' ?
        document.getElementById('chat-model-picker') :
        document.getElementById('model-picker');

    if (pickerElement) {
        pickerElement.querySelectorAll('.model-picker-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.type === type);
        });
    }

    renderModelPickerList(pickerId);
}

function getPickerEffectiveTab(pickerId = 'home') {
    if (pickerId === 'edit') {
        return 'inpaint';
    }
    if (pickerId === 'chat') {
        if (typeof terminalMode !== 'undefined' && terminalMode) {
            return currentModelTab === 'vision' ? 'vision' : 'chat';
        }
        return ['inpaint', 'text2img', 'chat'].includes(currentModelTab) ? currentModelTab : 'chat';
    }
    return currentModelTab;
}

function getModelsForTab(tab) {
    if (tab === 'inpaint') {
        // Filtrer selon le backend sélectionné dans settings
        const currentBackend = (typeof userSettings !== 'undefined' && userSettings.backend) || 'diffusers';
    let models = getInpaintModels().filter(m => !m.backend || m.backend === currentBackend || m.backend === 'both');
        if (!isAdultModeEnabled()) {
            models = models.filter(model => !isAdultImageModel(model));
        }
        // Filtrer par profil GPU (VRAM-aware)
        const visible = window._gpuProfile?.image?.visible_models;
        if (visible) {
            models = models.filter(m => m.imported || visible.includes(m.id));
        }
        return models;
    }
    if (tab === 'text2img') {
    let models = getText2ImgModels();
        if (!isAdultModeEnabled()) {
            models = models.filter(model => !isAdultImageModel(model));
        }
        const visible = window._gpuProfile?.image?.visible_models;
        if (visible) {
            return models.filter(m => m.imported || visible.includes(m.id));
        }
        return models;
    }
    if (tab === 'vision') {
        filterVisionModels();
        return VISION_MODELS_LIST;
    }

    // En mode terminal: filtrer pour n'afficher que les tool-capable et dédupliquer
    if (typeof terminalMode !== 'undefined' && terminalMode) {
        return filterTerminalModels(CHAT_MODELS);
    }

    return CHAT_MODELS;
}

/**
 * Filtre les modèles pour le mode terminal:
 * - Garde uniquement les tool-capable
 * - Déduplique par famille (qwen2.5:7b, qwen2.5:latest → garde un seul)
 */
function filterTerminalModels(models) {
    const cloudModels = Array.isArray(window.joyboyTerminalCloudModels)
        ? window.joyboyTerminalCloudModels
        : TERMINAL_CLOUD_MODELS;
    if (!models || models.length === 0) return cloudModels || [];

    // 1. Filtrer les tool-capable
    const toolCapable = models.filter(m => m.toolCapable === true);
    const selectedLocalModelId =
        (typeof terminalToolModel !== 'undefined' && terminalToolModel && !isTerminalCloudModelId(terminalToolModel) && terminalToolModel)
        || (userSettings.terminalModel && !isTerminalCloudModelId(userSettings.terminalModel) && userSettings.terminalModel)
        || (selectedChatModel && !isTerminalCloudModelId(selectedChatModel) && selectedChatModel)
        || null;
    const selectedLocalModel = selectedLocalModelId
        ? (models || []).find(model => model.id === selectedLocalModelId)
        : null;

    // 2. Dédupliquer par famille de modèle
    const seen = new Map();  // baseName → model

    for (const model of toolCapable) {
        // Extraire le nom de base (ex: qwen2.5:7b → qwen2.5, llama3.1:8b → llama3.1)
        const parts = model.id.split(':');
        const baseName = parts[0];  // qwen2.5, llama3.1, etc.
        const variant = parts[1] || 'latest';

        // Priorité: version avec taille explicite > latest > autres
        const hasSizeB = /^\d+(\.\d+)?b/.test(variant);  // 7b, 8b, 70b, etc.

        if (!seen.has(baseName)) {
            seen.set(baseName, { model, hasSizeB, variant });
        } else {
            const existing = seen.get(baseName);
            // Préférer la version avec taille explicite
            if (hasSizeB && !existing.hasSizeB) {
                seen.set(baseName, { model, hasSizeB, variant });
            }
            // Si les deux ont une taille, préférer la plus petite pour la vitesse
            else if (hasSizeB && existing.hasSizeB) {
                const newSize = parseFloat(variant);
                const oldSize = parseFloat(existing.variant);
                if (newSize < oldSize) {
                    seen.set(baseName, { model, hasSizeB, variant });
                }
            }
        }
    }

    // 3. Retourner la liste dédupliquée
    const filtered = [
        ...(selectedLocalModel && !selectedLocalModel.toolCapable
            ? [{ ...selectedLocalModel, badge: selectedLocalModel.badge || 'balanced' }]
            : []),
        ...Array.from(seen.values()).map(v => v.model),
        ...(cloudModels || []),
    ];
    return dedupeModelsById(filtered);
}

function getSelectedModelForTab(tab) {
    if (tab === 'inpaint') return selectedInpaintModel;
    if (tab === 'text2img') return selectedText2ImgModel;
    if (tab === 'vision') return selectedVisionModel || (VISION_MODELS_LIST[0]?.id);
    if (tab === 'chat' && typeof terminalMode !== 'undefined' && terminalMode) {
        const activeCloudChatModel = typeof getActiveCloudChatModel === 'function'
            ? getActiveCloudChatModel()
            : null;
        if (activeCloudChatModel && (!terminalToolModel || !isTerminalCloudModelId(terminalToolModel))) {
            return activeCloudChatModel;
        }
        return (typeof terminalToolModel !== 'undefined' && terminalToolModel)
            || userSettings.terminalModel
            || selectedChatModel;
    }
    return selectedChatModel;
}

function buildChatPickerFilters(models, pickerId) {
    const localModels = (models || []).filter(model => !isCloudPickerModel(model));
    const cloudModels = limitCloudModelsByFamily((models || []).filter(isCloudPickerModel), 5);
    let source = modelPickerChatSource === 'cloud' ? 'cloud' : 'local';
    if (source === 'cloud' && !cloudModels.length) source = 'local';
    if (source === 'local' && !localModels.length && cloudModels.length) source = 'cloud';

    const sourceButtons = [
        {
            id: 'local',
            label: uiT('modelPicker.sources.local', 'Local'),
            count: localModels.length,
        },
        {
            id: 'cloud',
            label: uiT('modelPicker.sources.cloud', 'Cloud'),
            count: cloudModels.length,
        },
    ].map(item => `
        <button
            type="button"
            class="model-picker-filter ${source === item.id ? 'active' : ''}"
            onclick="setModelPickerChatSource('${item.id}', '${pickerId}', event)"
        >
            <span>${item.label}</span>
            <em>${item.count}</em>
        </button>
    `).join('');

    let familyFilters = '';
    let filteredModels = source === 'cloud' ? cloudModels : localModels;
    if (source === 'cloud' && cloudModels.length) {
        const families = sortCloudFamilies(new Set(cloudModels.map(model => model.family || getCloudModelFamily(model))));
        if (modelPickerChatFamily !== 'all' && !families.includes(modelPickerChatFamily)) {
            modelPickerChatFamily = 'all';
            Settings.set('modelPickerChatFamily', modelPickerChatFamily);
        }
        const familyButtons = ['all', ...families].map(family => {
            const count = family === 'all'
                ? cloudModels.length
                : cloudModels.filter(model => (model.family || getCloudModelFamily(model)) === family).length;
            return `
                <button
                    type="button"
                    class="model-picker-family ${modelPickerChatFamily === family ? 'active' : ''}"
                    onclick="setModelPickerChatFamily('${family}', '${pickerId}', event)"
                >
                    <span>${getCloudFamilyLabel(family)}</span>
                    <em>${count}</em>
                </button>
            `;
        }).join('');
        familyFilters = `<div class="model-picker-family-tabs">${familyButtons}</div>`;
        if (modelPickerChatFamily !== 'all') {
            filteredModels = cloudModels.filter(model => (model.family || getCloudModelFamily(model)) === modelPickerChatFamily);
        }
    }

    const emptyText = source === 'cloud'
        ? uiT('modelPicker.emptyCloud', 'Aucun modèle cloud configuré.')
        : uiT('modelPicker.emptyLocal', 'Aucun modèle local disponible.');
    const reasoningControl = source === 'cloud' ? buildCloudReasoningPickerControl(pickerId) : '';

    return {
        models: filteredModels,
        controls: `
            <div class="model-picker-filters">
                <div class="model-picker-source-tabs">${sourceButtons}</div>
                ${familyFilters}
                ${reasoningControl}
            </div>
        `,
        emptyText,
    };
}

function renderModelPickerList(pickerId = 'home') {
    const listId = pickerId === 'edit' ? 'edit-model-picker-list' :
                   pickerId === 'chat' ? 'chat-model-picker-list' : 'model-picker-list';
    const list = document.getElementById(listId);
    if (!list) return;

    // Edit mode = forcé sur inpaint, chat input = forcé sur modèles chat.
    const tab = getPickerEffectiveTab(pickerId);
    let models = getModelsForTab(tab);
    if (pickerId === 'edit') {
        models = models.filter(m => !m.noMask);
    }

    let selectedModel;
    if (pickerId === 'edit') {
        let editSel = typeof selectedEditModel !== 'undefined' && selectedEditModel ? selectedEditModel : getSelectedModelForTab('inpaint');
        // Si le modèle sélectionné est noMask, fallback sur le premier compatible
    const isNoMask = getInpaintModels().find(m => m.id === editSel)?.noMask;
        selectedModel = isNoMask ? (models[0]?.id || editSel) : editSel;
    } else {
        selectedModel = getSelectedModelForTab(tab);
    }

    let filterControls = '';
    let emptyText = uiT('modelPicker.empty', 'Aucun modèle disponible.');
    if (tab === 'chat') {
        const filtered = buildChatPickerFilters(models, pickerId);
        models = filtered.models;
        filterControls = filtered.controls;
        emptyText = filtered.emptyText;
    }

    // Trier: modèle sélectionné en premier
    const sortedModels = [...models].sort((a, b) => {
        if (a.id === selectedModel && b.id !== selectedModel) return -1;
        if (a.id !== selectedModel && b.id === selectedModel) return 1;
        return 0;
    });
    const helperText = getModelPickerHelper(tab, pickerId);

    list.innerHTML = `
        ${helperText ? `<div class="model-picker-helper">${helperText}</div>` : ''}
        ${filterControls}
        ${sortedModels.length ? '' : `<div class="model-picker-empty">${emptyText}</div>`}
        ${sortedModels.map(model => {
        let badgeClass = model.badge || 'balanced';
        const badgeText = modelPickerBadgeLabel(model);
        const useCase = getModelPickerUseCase(model, tab, pickerId);
        const modelDesc = translateModelPickerDesc(model);
        const installInfo = getPickerModelInstallInfo(model, tab);
        const installClass = installInfo.installed ? 'installed' : installInfo.status;

        return `
        <div class="model-picker-item ${model.id === selectedModel ? 'active' : ''} install-${installClass}"
             onclick="selectPickerModel('${model.id}', '${pickerId}')">
            <div class="model-picker-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    ${getModelIcon(model.icon)}
                </svg>
            </div>
            <div class="model-picker-info">
                <div class="model-picker-name">${model.name}</div>
                <div class="model-picker-desc">${modelDesc}</div>
                ${useCase ? `<div class="model-picker-meta">${useCase}</div>` : ''}
            </div>
            <span class="model-picker-pills">
                <span class="model-picker-badge ${badgeClass}">${badgeText}</span>
                ${renderPickerInstallBadge(installInfo)}
            </span>
        </div>
    `;
    }).join('')}
    `;
}

function unloadPreviousLocalTextModelWhenUsingCloud(previousModel, nextModel) {
    if (!previousModel || previousModel === nextModel) return;
    if (!isTerminalCloudModelId(nextModel) || isTerminalCloudModelId(previousModel)) return;
    if (typeof apiOllama === 'undefined' || typeof apiOllama.unload !== 'function') return;

    console.log('[MODEL] Switch vers cloud, déchargement du modèle local:', previousModel);
    apiOllama.unload(previousModel).then(result => {
        if (result?.ok) {
            console.log('[MODEL] Modèle local déchargé après switch cloud:', previousModel);
        }
    }).catch(err => {
        console.warn('[MODEL] Déchargement local après switch cloud ignoré:', err);
    });
}

async function selectPickerModel(modelId, pickerId = 'home') {
    // Edit picker = sélection indépendante pour l'éditeur
    if (pickerId === 'edit') {
        if (!hasPickerInstallStatusForTab('inpaint')) {
            await refreshModelPickerInstallStateForTab('inpaint', pickerId, true);
        }
        const editModel = getInpaintModels().find(model => model.id === modelId) || { id: modelId, name: modelId };
        const editInstallInfo = getPickerModelInstallInfo(editModel, 'inpaint');
        if (!editInstallInfo.installed) {
            await handleMissingPickerModel(editModel, 'inpaint', pickerId);
            return;
        }
        selectedEditModel = modelId;
        Settings.set('editSelectedModel', modelId);
        const textSpan = document.getElementById('edit-selected-model-text');
        if (textSpan) textSpan.textContent = modelId;
        renderModelPickerList('edit');
        const picker = document.getElementById('edit-model-picker');
        if (picker) picker.classList.remove('open');
        return;
    }

    const modelType = getPickerEffectiveTab(pickerId);
    if (!hasPickerInstallStatusForTab(modelType)) {
        await refreshModelPickerInstallStateForTab(modelType, pickerId, true);
    }
    const pickedModel = getModelsForTab(modelType).find(model => model.id === modelId) || { id: modelId, name: modelId };
    const installInfo = getPickerModelInstallInfo(pickedModel, modelType);
    if (!installInfo.installed) {
        await handleMissingPickerModel(pickedModel, modelType, pickerId);
        return;
    }
    const previousModel = getSelectedModelForTab(modelType);

    if (modelType === 'inpaint') {
        selectedInpaintModel = modelId;
        selectedImageModel = modelId;  // Compat
        Settings.set('selectedInpaintModel', modelId);

        // Reset le flag et précharger immédiatement le nouveau modèle
        if (previousModel !== modelId) {
            if (typeof resetImageModelLoaded === 'function') {
                resetImageModelLoaded();
            }
            // Précharger le nouveau modèle immédiatement
            if (typeof preloadImageModel === 'function') {
                preloadImageModel();
            }
        }

        // Mettre à jour le picker du mode Edit si pas de modèle spécifique sélectionné
        if (typeof selectedEditModel === 'undefined' || !selectedEditModel) {
            const editTextSpan = document.getElementById('edit-selected-model-text');
            if (editTextSpan) {
                editTextSpan.textContent = modelId;
            }
        }
    } else if (modelType === 'text2img') {
        selectedText2ImgModel = modelId;
        Settings.set('selectedText2ImgModel', modelId);

        // Reset aussi pour text2img (préchargement géré à la génération)
        if (previousModel !== modelId && typeof resetImageModelLoaded === 'function') {
            resetImageModelLoaded();
        }
    } else if (modelType === 'vision') {
        // Gestion spéciale pour télécharger un modèle vision
        if (modelId === 'download-vision') {
            downloadVisionModel();
            return;
        }

        selectedVisionModel = modelId;
        Settings.set('selectedVisionModel', modelId);

        // En mode terminal, mettre à jour terminalVisionModel et précharger
        if (typeof terminalMode !== 'undefined' && terminalMode) {
            terminalVisionModel = modelId;
            // Précharger le nouveau modèle vision
            apiOllama.warmup(modelId, true).then(result => {
                if (result.ok) {
                    console.log('[VISION] Modèle vision préchargé:', modelId);
                }
            });
        }
    } else if (typeof terminalMode !== 'undefined' && terminalMode) {
        terminalToolModel = modelId;
        userSettings.terminalModel = modelId;
        if (typeof tokenStats !== 'undefined') {
            tokenStats.maxContextSize = getTerminalEffectiveContextSize(modelId);
            updateTokenDisplay();
        }
    } else {
        selectedChatModel = modelId;
        selectedTextModel = modelId;  // Compat
        userSettings.chatModel = modelId;
    }

    if (modelType === 'chat') {
        unloadPreviousLocalTextModelWhenUsingCloud(previousModel, modelId);
    }

    // Log côté serveur
    if (previousModel !== modelId) {
        fetch('/api/log/model-change', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId, type: modelType, previous: previousModel })
        }).catch(() => {});
    }

    // Update UI
    updateModelPickerDisplay();

    // Render both lists to update active state
    renderModelPickerList('home');
    renderModelPickerList('chat');

    // Close picker
    setTimeout(() => {
        document.querySelectorAll('.model-picker').forEach(p => p.classList.remove('open'));
        activePickerId = null;
        document.removeEventListener('click', closeModelPickerOnClickOutside);
    }, 150);

    saveSettings();
}

function getCurrentImageModel() {
    // Retourne inpaint ou text2img selon s'il y a une image
    const hasImage = typeof currentImage !== 'undefined' && currentImage !== null;
    if (hasImage) {
        const defaultModel = window._gpuProfile?.image?.default_inpaint_model || 'epiCRealism XL (Moyen)';
        return selectedInpaintModel || defaultModel;
    }
    return selectedText2ImgModel || 'epiCRealism XL';
}

function getCurrentInpaintModel() {
    const defaultModel = window._gpuProfile?.image?.default_inpaint_model || 'epiCRealism XL (Moyen)';
    const model = selectedInpaintModel || defaultModel;
    console.log(`[UI] getCurrentInpaintModel: ${model} (selectedInpaintModel=${selectedInpaintModel})`);
    return model;
}

function getCurrentText2ImgModel() {
    return selectedText2ImgModel || 'epiCRealism XL';
}

function getCurrentTextModel() {
    return selectedTextModel || userSettings.chatModel || null;
}

// ===== IMAGE PREVIEWS =====
function updateComposerAttachmentState() {
    const refs = typeof getFaceRefImages === 'function'
        ? getFaceRefImages()
        : (faceRefImage ? [faceRefImage] : []);
    const hasAttachments = Boolean(currentImage || currentVideoSource || styleRefImage || refs.length);
    document.querySelectorAll('.input-bar').forEach((bar) => {
        bar.classList.toggle('has-attachments', hasAttachments);
    });
    requestAnimationFrame(() => {
        const chatInputBar = document.querySelector('.chat-input-bar');
        const nextHeight = Math.max(80, Math.ceil(chatInputBar?.offsetHeight || 80));
        document.documentElement.style.setProperty('--chat-input-h', `${nextHeight}px`);
    });
}

function updateImagePreviews() {
    const homePreview = document.getElementById('image-preview');
    const homeClearBtn = document.getElementById('clear-image-btn');
    if (homePreview) {
        homePreview.src = currentImage || '';
        homePreview.style.display = currentImage ? 'block' : 'none';
    }
    if (homeClearBtn) {
        homeClearBtn.style.display = currentImage ? 'flex' : 'none';
    }
    const chatPreview = document.getElementById('chat-image-preview');
    const chatClearBtn = document.getElementById('chat-clear-image-btn');
    if (chatPreview) {
        chatPreview.src = currentImage || '';
        chatPreview.style.display = currentImage ? 'block' : 'none';
    }
    if (chatClearBtn) {
        chatClearBtn.style.display = currentImage ? 'flex' : 'none';
    }
    updateComposerAttachmentState();
}

function updateVideoSourcePreviews() {
    const pairs = [
        {
            container: document.getElementById('video-source-preview-container'),
            preview: document.getElementById('video-source-preview'),
            name: document.getElementById('video-source-name'),
            duration: document.getElementById('video-source-duration'),
            clear: document.getElementById('clear-video-source-btn'),
        },
        {
            container: document.getElementById('chat-video-source-preview-container'),
            preview: document.getElementById('chat-video-source-preview'),
            name: document.getElementById('chat-video-source-name'),
            duration: document.getElementById('chat-video-source-duration'),
            clear: document.getElementById('chat-clear-video-source-btn'),
        },
    ];
    const thumb = currentVideoSource?.thumbnail || currentVideoSource?.continuationAnchors?.[0]?.thumbnail || '';
    const durationText = currentVideoSource?.durationSec
        ? `${Number(currentVideoSource.durationSec).toFixed(1)}s`
        : 'Source vidéo';
    for (const item of pairs) {
        if (!item.container) continue;
        item.container.classList.toggle('has-video', Boolean(currentVideoSource));
        if (item.preview) {
            item.preview.src = thumb || '';
            item.preview.style.display = currentVideoSource ? 'block' : 'none';
        }
        if (item.name) item.name.textContent = currentVideoSource?.fileName || 'Vidéo';
        if (item.duration) item.duration.textContent = durationText;
        if (item.clear) item.clear.style.display = currentVideoSource ? 'flex' : 'none';
    }
    updateComposerAttachmentState();
}

function clearVideoSource() {
    const clearedSessionId = currentVideoSource?.videoSessionId || null;
    currentVideoSource = null;
    if (typeof _lastVideoContext !== 'undefined') {
        const activeSessionId = _lastVideoContext.videoSessionId || null;
        if (clearedSessionId && activeSessionId === clearedSessionId) {
            _lastVideoContext.canContinue = false;
            _lastVideoContext.videoSessionId = null;
            _lastVideoContext.anchors = [];
        }
    }
    updateVideoSourcePreviews();
    if (typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }
}

function clearImage() {
    currentImage = null;

    updateImagePreviews();
    document.getElementById('file-input').value = '';

    // Update send button state
    if (typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }

    // Mettre à jour le picker (afficher modèle chat)
    updateModelPickerDisplay();
}

// ===== FACE REF PREVIEWS =====
function updateFaceRefPreviews() {
    const ids = [
        { slots: 'face-ref-slots', clear: 'clear-face-ref-btn', container: 'face-ref-container' },
        { slots: 'chat-face-ref-slots', clear: 'chat-clear-face-ref-btn', container: 'chat-face-ref-container' },
    ];
    const refs = typeof getFaceRefImages === 'function'
        ? getFaceRefImages()
        : (faceRefImage ? [faceRefImage] : []);
    const maxRefs = typeof MAX_FACE_REF_IMAGES !== 'undefined' ? MAX_FACE_REF_IMAGES : 5;

    for (const { slots, clear, container } of ids) {
        const slotsWrap = document.getElementById(slots);
        const btn = document.getElementById(clear);
        const wrap = document.getElementById(container);
        if (slotsWrap) {
            slotsWrap.innerHTML = '';
            refs.forEach((src, index) => {
                const slot = document.createElement('button');
                slot.type = 'button';
                slot.className = 'face-ref-slot has-image';
                slot.title = uiT('composer.menu.faceRefSlotTitle', 'Face reference {count}/{max}', {
                    count: index + 1,
                    max: maxRefs,
                });
                slot.onclick = () => document.getElementById('face-ref-input')?.click();

                const img = document.createElement('img');
                img.src = src;
                img.alt = uiT('composer.menu.faceRefAlt', 'Face reference {count}', { count: index + 1 });
                slot.appendChild(img);
                slotsWrap.appendChild(slot);
            });

            for (let slotIndex = refs.length; refs.length > 0 && slotIndex < maxRefs; slotIndex += 1) {
                const addSlot = document.createElement('button');
                addSlot.type = 'button';
                addSlot.className = `face-ref-slot empty${slotIndex === refs.length ? ' next' : ''}`;
                addSlot.title = uiT('composer.menu.faceRefAddTitle', '{count}/{max} face refs - add another', {
                    count: refs.length,
                    max: maxRefs,
                });
                addSlot.textContent = slotIndex === refs.length ? '+' : '';
                addSlot.onclick = () => document.getElementById('face-ref-input')?.click();
                slotsWrap.appendChild(addSlot);
            }
        }
        if (btn) {
            btn.style.display = refs.length ? 'flex' : 'none';
        }
        if (wrap) {
            wrap.classList.toggle('has-image', refs.length > 0);
            wrap.title = refs.length
                ? uiT('composer.menu.faceRefsSummary', '{count}/{max} face references. 2-5 clear photos can stabilize identity.', {
                    count: refs.length,
                    max: maxRefs,
                })
                : '';
        }
    }
    updateComposerAttachmentState();
}

function clearFaceRef() {
    faceRefImages = [];
    faceRefImage = null;
    if (typeof syncFaceRefLegacy === 'function') syncFaceRefLegacy();
    updateFaceRefPreviews();
    const input = document.getElementById('face-ref-input');
    if (input) input.value = '';
    if (typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }
}

// ===== STYLE REF PREVIEWS =====
function updateStyleRefPreviews() {
    const ids = [
        { preview: 'style-ref-preview', clear: 'clear-style-ref-btn', container: 'style-ref-container' },
        { preview: 'chat-style-ref-preview', clear: 'chat-clear-style-ref-btn', container: 'chat-style-ref-container' },
    ];
    for (const { preview, clear, container } of ids) {
        const img = document.getElementById(preview);
        const btn = document.getElementById(clear);
        const wrap = document.getElementById(container);
        if (img) {
            img.src = styleRefImage || '';
            img.style.display = styleRefImage ? 'block' : 'none';
        }
        if (btn) {
            btn.style.display = styleRefImage ? 'flex' : 'none';
        }
        if (wrap) {
            wrap.classList.toggle('has-image', !!styleRefImage);
        }
    }
    updateComposerAttachmentState();
}

function clearStyleRef() {
    styleRefImage = null;
    updateStyleRefPreviews();
    const input = document.getElementById('style-ref-input');
    if (input) input.value = '';
}

// ===== SEND BUTTONS MODE =====
function setSendButtonsMode(isStop) {
    const sendBtn = document.getElementById('send-btn');
    const chatSendBtn = document.getElementById('chat-send-btn');

    [sendBtn, chatSendBtn].forEach(btn => {
        if (!btn) return;
        const sendIcon = btn.querySelector('.send-icon');
        const stopIcon = btn.querySelector('.stop-icon');

        if (isStop) {
            btn.classList.add('stop-mode');
            btn.classList.remove('empty'); // Always clickable in stop mode
            btn.disabled = false;
            if (sendIcon) sendIcon.style.display = 'none';
            if (stopIcon) stopIcon.style.display = 'block';
        } else {
            btn.classList.remove('stop-mode');
            if (sendIcon) sendIcon.style.display = 'block';
            if (stopIcon) stopIcon.style.display = 'none';
        }
    });

    // Re-evaluate empty state when leaving stop mode
    if (!isStop && typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }
}

// ===== CLIPBOARD & SPEECH =====
function copyText(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        navigator.clipboard.writeText(element.textContent);
    }
}

function copyImagePrompt(prompt) {
    navigator.clipboard.writeText(`I generated an image with the prompt: '${prompt}'`);
    Toast.success(uiT('common.copied', 'Copié'));
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text);
    Toast.success(uiT('ui.seedCopied', 'Seed copiée'));
}

let currentSpeechTargetId = null;
let currentSpeechUtterance = null;

function getSpeechLocale() {
    const locale = window.JoyBoyI18n?.getLocale?.() || document.documentElement.lang || navigator.language || 'fr';
    const normalized = String(locale).toLowerCase().split(/[-_]/)[0];
    const localeMap = {
        fr: 'fr-FR',
        en: 'en-US',
        es: 'es-ES',
        it: 'it-IT',
    };
    return localeMap[normalized] || locale || 'fr-FR';
}

function getSpeakButtonsForTarget(elementId, clickedButton = null) {
    const buttons = Array.from(document.querySelectorAll('[data-speak-target]'))
        .filter(btn => btn.dataset.speakTarget === elementId);
    if (clickedButton && !buttons.includes(clickedButton)) {
        buttons.push(clickedButton);
    }
    return buttons;
}

function setSpeakButtonsState(elementId, isSpeaking, clickedButton = null) {
    const title = isSpeaking
        ? uiT('common.stop', 'Stop')
        : uiT('common.readAloud', 'Lire');

    getSpeakButtonsForTarget(elementId, clickedButton).forEach(btn => {
        btn.classList.toggle('active', isSpeaking);
        btn.setAttribute('aria-pressed', isSpeaking ? 'true' : 'false');
        btn.setAttribute('title', title);
        btn.setAttribute('aria-label', title);
    });
}

function getReadableSpeechText(element) {
    const clone = element.cloneNode(true);
    clone.querySelectorAll('.code-header, .chat-actions, button, script, style').forEach(node => node.remove());
    return clone.textContent.replace(/\s+/g, ' ').trim();
}

function resetSpeechState(clickedButton = null) {
    if (currentSpeechTargetId) {
        setSpeakButtonsState(currentSpeechTargetId, false, clickedButton);
    }
    currentSpeechTargetId = null;
    currentSpeechUtterance = null;
}

function stopSpeaking(clickedButton = null) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
    resetSpeechState(clickedButton);
}

function speakText(elementId, clickedButton = null) {
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
        return;
    }

    if (currentSpeechTargetId === elementId && currentSpeechUtterance) {
        stopSpeaking(clickedButton);
        return;
    }

    if (currentSpeechUtterance || window.speechSynthesis.speaking || window.speechSynthesis.pending) {
        stopSpeaking();
    }

    const element = document.getElementById(elementId);
    if (!element) return;

    const text = getReadableSpeechText(element);
    if (!text) return;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = getSpeechLocale();
    currentSpeechTargetId = elementId;
    currentSpeechUtterance = utterance;
    setSpeakButtonsState(elementId, true, clickedButton);

    utterance.onend = () => {
        if (currentSpeechUtterance === utterance) {
            resetSpeechState(clickedButton);
        }
    };
    utterance.onerror = () => {
        if (currentSpeechUtterance === utterance) {
            resetSpeechState(clickedButton);
        }
    };

    window.speechSynthesis.cancel();
    setTimeout(() => {
        if (currentSpeechUtterance === utterance) {
            window.speechSynthesis.speak(utterance);
        }
    }, 0);
}

function likeMessage(btn) {
    btn.classList.toggle('active');
}

function dislikeMessage(btn) {
    btn.classList.toggle('active');
}

// ===== PROMPT HISTORY =====
const PROMPT_HISTORY_STORE_KEY = 'promptHistoryByScope';
let promptHistoryStore = {};
let historyIndex = -1;
let currentTypedPrompt = '';
let currentPromptHistoryScope = '';
const MAX_PROMPT_HISTORY = 10;

try {
    promptHistoryStore = JSON.parse(localStorage.getItem(PROMPT_HISTORY_STORE_KEY) || '{}') || {};
} catch (_err) {
    promptHistoryStore = {};
}

function getPromptHistoryScope(inputElement = null) {
    const chatId = (typeof currentChatId !== 'undefined' && currentChatId) ? currentChatId : 'global';
    const id = inputElement?.id || document.activeElement?.id || 'prompt';
    if (id === 'edit-prompt') return `edit:${chatId}`;
    if (id === 'prompt-input') return `image:${chatId}`;
    return `chat:${chatId}`;
}

function getScopedPromptHistory(inputElement = null) {
    const scope = getPromptHistoryScope(inputElement);
    if (currentPromptHistoryScope !== scope) {
        currentPromptHistoryScope = scope;
        historyIndex = -1;
        currentTypedPrompt = '';
    }
    if (!Array.isArray(promptHistoryStore[scope])) {
        promptHistoryStore[scope] = [];
    }
    return promptHistoryStore[scope];
}

function saveScopedPromptHistory(scope, history) {
    promptHistoryStore[scope] = history.slice(-MAX_PROMPT_HISTORY);
    localStorage.setItem(PROMPT_HISTORY_STORE_KEY, JSON.stringify(promptHistoryStore));
}

function addToPromptHistory(prompt, inputElement = null) {
    if (!prompt.trim()) return;
    const scope = getPromptHistoryScope(inputElement);
    const promptHistory = getScopedPromptHistory(inputElement);
    if (promptHistory.length === 0 || promptHistory[promptHistory.length - 1] !== prompt) {
        promptHistory.push(prompt);
        saveScopedPromptHistory(scope, promptHistory);
    }
    historyIndex = -1;
    currentTypedPrompt = '';
}

function handlePromptKeydown(e, inputElement) {
    if (
        typeof terminalMode !== 'undefined'
        && terminalMode
        && (inputElement.id === 'prompt-input' || inputElement.id === 'chat-prompt')
    ) {
        return;
    }

    // Désactiver l'historique si le texte contient plusieurs lignes
    const isMultiline = inputElement.value.includes('\n');
    const promptHistory = getScopedPromptHistory(inputElement);

    if (e.key === 'ArrowUp' && !isMultiline) {
        e.preventDefault();
        e.stopPropagation();
        if (promptHistory.length === 0) return;

        if (historyIndex === -1) {
            currentTypedPrompt = inputElement.value;
        }

        if (historyIndex < promptHistory.length - 1) {
            historyIndex++;
            inputElement.value = promptHistory[promptHistory.length - 1 - historyIndex];
            inputElement.setSelectionRange?.(inputElement.value.length, inputElement.value.length);
            // Resize après changement
            if (typeof autoResizeTextarea === 'function') autoResizeTextarea(inputElement);
        }
    } else if (e.key === 'ArrowDown' && !isMultiline) {
        e.preventDefault();
        e.stopPropagation();
        if (historyIndex > 0) {
            historyIndex--;
            inputElement.value = promptHistory[promptHistory.length - 1 - historyIndex];
            inputElement.setSelectionRange?.(inputElement.value.length, inputElement.value.length);
            if (typeof autoResizeTextarea === 'function') autoResizeTextarea(inputElement);
        } else if (historyIndex === 0) {
            historyIndex = -1;
            inputElement.value = currentTypedPrompt;
            inputElement.setSelectionRange?.(inputElement.value.length, inputElement.value.length);
            if (typeof autoResizeTextarea === 'function') autoResizeTextarea(inputElement);
        } else {
            inputElement.value = '';
            currentTypedPrompt = '';
        }
    }
}
