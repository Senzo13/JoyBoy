// ===== SETTINGS WORKSPACE + TERMINAL PANEL =====
// Project workspace controls, terminal context settings, and terminal model selection.

// ===== WORKSPACE FUNCTIONS =====

// Ajouter un workspace
async function addWorkspace() {
    const input = DOM.get('workspace-path-input');
    const path = DOM.getValue(input);

    if (!path) {
        Toast.error(t('common.error', 'Erreur'), t('settings.workspace.pathRequired', 'Entre un chemin de dossier'));
        return;
    }

    // Valider le chemin côté serveur
    const result = await apiPost('/workspace/validate', { path: path });
    if (!result.ok) {
        Toast.error(t('common.error', 'Erreur'), result.error);
        return;
    }

    const data = result.data;
    if (!data.valid) {
        Toast.error(t('common.error', 'Erreur'), data.error || t('settings.workspace.invalidPath', 'Chemin invalide'));
        return;
    }

    // Vérifier si déjà ajouté
    if (userSettings.workspaces.some(w => w.path === data.path)) {
        Toast.info(t('common.notice', 'Information'), t('settings.workspace.exists', 'Ce workspace existe déjà'));
        return;
    }

    // Ajouter le workspace
    const workspace = {
        name: data.name,
        path: data.path,
        fileCount: data.file_count,
        dirCount: data.dir_count
    };

    userSettings.workspaces.push(workspace);
    saveSettings();

    // Rafraîchir la liste
    renderWorkspacesList();

    // Vider l'input
    DOM.setValue(input, '');

    Toast.success(
        t('settings.workspace.addedTitle', 'Workspace ajouté'),
        t('settings.workspace.addedBody', '{name} ({count} fichiers)', { name: workspace.name, count: workspace.fileCount })
    );
}

// Supprimer un workspace
function removeWorkspace(index) {
    const workspace = userSettings.workspaces[index];
    if (!workspace) return;

    // Si c'est le workspace actif, le désactiver
    if (userSettings.activeWorkspace === workspace.name) {
        userSettings.activeWorkspace = null;
    }

    userSettings.workspaces.splice(index, 1);
    saveSettings();
    renderWorkspacesList();
    updateActiveWorkspaceUI();

    Toast.info(t('settings.workspace.removedTitle', 'Workspace supprimé'), workspace.name);
}

// Activer un workspace
async function activateWorkspace(index) {
    const workspace = userSettings.workspaces[index];
    if (!workspace) return;

    userSettings.activeWorkspace = workspace.name;
    saveSettings();
    updateActiveWorkspaceUI();

    // Vérifier si le modèle supporte les outils
    await checkWorkspaceModelSupport();

    Toast.success(t('settings.workspace.activatedTitle', 'Workspace activé'), `${workspace.name}`);
}

// Désactiver le workspace actif
function clearActiveWorkspace() {
    userSettings.activeWorkspace = null;
    saveSettings();
    updateActiveWorkspaceUI();
    Toast.info(t('settings.workspace.deactivatedTitle', 'Workspace désactivé'), '');
}

// Mettre à jour l'UI du workspace actif
function updateActiveWorkspaceUI() {
    const nameEl = document.getElementById('active-workspace-name');
    const pathEl = document.getElementById('active-workspace-path');
    const clearBtn = document.getElementById('clear-workspace-btn');
    const warningEl = document.getElementById('workspace-model-warning');

    if (userSettings.activeWorkspace) {
        const workspace = userSettings.workspaces.find(w => w.name === userSettings.activeWorkspace);
        if (workspace) {
            nameEl.textContent = workspace.name;
            pathEl.textContent = workspace.path;
            clearBtn.style.display = 'block';
        } else {
            // Workspace n'existe plus
            userSettings.activeWorkspace = null;
            saveSettings();
            nameEl.textContent = t('settings.workspace.none', 'Aucun');
            pathEl.textContent = t('settings.workspace.selectToActivate', 'Sélectionne un workspace pour l’activer');
            clearBtn.style.display = 'none';
        }
    } else {
        nameEl.textContent = t('settings.workspace.none', 'Aucun');
        pathEl.textContent = t('settings.workspace.selectToActivate', 'Sélectionne un workspace pour l’activer');
        clearBtn.style.display = 'none';
    }

    // Réinitialiser le warning
    if (warningEl) warningEl.style.display = 'none';

    // Mettre à jour la liste pour montrer lequel est actif
    renderWorkspacesList();
}

// Vérifier si le modèle supporte les outils workspace
async function checkWorkspaceModelSupport() {
    if (!userSettings.activeWorkspace) return;

    const result = await apiPost('/workspace/check-model', { model: userSettings.chatModel });
    if (!result.ok) {
        console.error('[WORKSPACE] Erreur check model:', result.error);
        return;
    }

    const warningEl = DOM.get('workspace-model-warning');
    if (warningEl) {
        warningEl.style.display = result.data?.tool_capable ? 'none' : 'flex';
    }
}

// Rendu de la liste des workspaces
function renderWorkspacesList() {
    const container = document.getElementById('workspaces-list');
    if (!container) return;

    if (!userSettings.workspaces || userSettings.workspaces.length === 0) {
        container.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.workspace.empty', 'Aucun workspace configuré'))}</div>`;
        return;
    }

    let html = '';
    userSettings.workspaces.forEach((workspace, index) => {
        const isActive = userSettings.activeWorkspace === workspace.name;
        const workspaceName = escapeHtml(workspace.name);
        const workspacePath = escapeHtml(workspace.path);
        const activeBadge = `<span class="workspace-active-badge">${escapeHtml(t('settings.workspace.active', 'Actif'))}</span>`;
        const removeTooltip = escapeHtml(t('settings.workspace.removeTooltip', 'Supprimer ce workspace'));
        html += `
            <div class="workspace-item ${isActive ? 'active' : ''}">
                <div class="workspace-info" onclick="activateWorkspace(${index})">
                    <div class="workspace-name">${workspaceName}</div>
                    <div class="workspace-path">${workspacePath}</div>
                </div>
                <div class="workspace-actions">
                    ${isActive ? activeBadge : ''}
                    <button class="workspace-remove-btn" onclick="removeWorkspace(${index})" data-tooltip="${removeTooltip}" aria-label="${removeTooltip}">
                        <i data-lucide="x"></i>
                    </button>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;

    // Réinitialiser les icônes Lucide
    if (window.lucide) lucide.createIcons();
}

// Mettre à jour la taille du contexte
function updateContextSize(value) {
    const contextConfig = window.JoyBoyContextSizes;
    const contextSize = contextConfig?.normalize(value) || parseInt(value, 10) || 4096;
    userSettings.contextSize = contextSize;

    const valueEl = document.getElementById('settings-context-size-value');
    if (valueEl) valueEl.textContent = contextConfig?.format(contextSize) || String(contextSize);

    // Mettre à jour l'info
    const infoEl = document.getElementById('context-size-info');
    if (infoEl) {
        const vramInfo = {
            2048: t('settings.terminal.vramExtra0', '~0 GB VRAM en plus'),
            4096: t('settings.terminal.vramExtra1', '~1-2 GB VRAM en plus'),
            8192: t('settings.terminal.vramExtra2', '~2-4 GB VRAM en plus'),
            16384: t('settings.terminal.vramExtra4', '~4-8 GB VRAM en plus'),
            32768: t('settings.terminal.vramExtra8', '~8-16 GB VRAM en plus'),
            65536: t('settings.terminal.vramExtra16', '~16-24 GB VRAM/RAM en plus'),
            131072: t('settings.terminal.vramExtra32', '~32 GB+ VRAM/RAM en plus'),
            262144: t('settings.terminal.vramExtra64', '~64 GB+ VRAM/RAM en plus')
        };
        infoEl.textContent = vramInfo[contextSize] || t('settings.terminal.moreTokensMoreVram', 'Plus de tokens = plus de VRAM');
    }

    saveSettings();
}

function terminalReasoningLabel(effort) {
    const labels = {
        low: t('settings.terminal.reasoningLow', 'Bas'),
        medium: t('settings.terminal.reasoningMedium', 'Moyen'),
        high: t('settings.terminal.reasoningHigh', 'Élevé'),
        xhigh: t('settings.terminal.reasoningXhigh', 'Très approfondi'),
    };
    return labels[effort] || labels.medium;
}

function updateTerminalReasoningEffort(value) {
    const allowed = ['low', 'medium', 'high', 'xhigh'];
    const effort = allowed.includes(String(value || '').trim()) ? String(value).trim() : 'medium';
    userSettings.terminalReasoningEffort = effort;
    document.querySelectorAll('#terminal-reasoning-select, .terminal-reasoning-control').forEach(select => {
        select.value = effort;
    });
    saveSettings();
    if (typeof Toast !== 'undefined') {
        Toast.success(t('settings.terminal.reasoningToast', 'Raisonnement : {mode}', {
            mode: terminalReasoningLabel(effort),
        }));
    }
}

// Initialiser l'onglet terminal
function initTerminalTab() {
    // Peupler le select des modèles terminal
    populateTerminalModelSelect();

    const reasoningSelect = document.getElementById('terminal-reasoning-select');
    if (reasoningSelect) {
        reasoningSelect.value = userSettings.terminalReasoningEffort || 'medium';
    }
    const reasoningLabel = document.getElementById('terminal-reasoning-label');
    if (reasoningLabel) reasoningLabel.textContent = t('settings.terminal.reasoningLabel', 'Raisonnement cloud');
    const reasoningHint = document.getElementById('terminal-reasoning-hint');
    if (reasoningHint) reasoningHint.textContent = t('settings.terminal.reasoningHint', 'Utilisé par les connecteurs compatibles, comme Codex CLI.');
    ['low', 'medium', 'high', 'xhigh'].forEach(effort => {
        const option = document.getElementById(`terminal-reasoning-${effort}`);
        if (option) option.textContent = terminalReasoningLabel(effort);
    });

    // Slider contexte
    const contextSlider = document.getElementById('settings-context-size');
    const contextValue = document.getElementById('settings-context-size-value');
    if (contextSlider) {
        const contextConfig = window.JoyBoyContextSizes;
        if (contextConfig) {
            contextSlider.min = contextConfig.min;
            contextSlider.max = contextConfig.max;
            contextSlider.step = contextConfig.step;
        }
        const contextSize = contextConfig?.normalize(userSettings.contextSize ?? 4096) || (userSettings.contextSize ?? 4096);
        contextSlider.value = contextSize;
        if (contextValue) contextValue.textContent = contextConfig?.format(contextSize) || String(contextSize);
        updateContextSize(contextSize);
    }

    // Liste des workspaces
    renderWorkspacesList();
    updateActiveWorkspaceUI();

    // Vérifier le support du modèle si workspace actif
    if (userSettings.activeWorkspace) {
        checkWorkspaceModelSupport();
    }
}

// ===== TERMINAL MODEL SELECT =====

// TOOL_CAPABLE_KEYWORDS, TOOL_EXCLUDED_KEYWORDS, TOOL_TOO_SMALL_SIZES,
// isToolCapableModel(), isToolCapableModelStrict() defined in state.js

function isTerminalToolCapable(modelId) {
    return isToolCapableModelStrict(modelId);
}

/**
 * Peuple le select des modèles terminal
 */
async function populateTerminalModelSelect() {
    const select = document.getElementById('terminal-model-select');
    if (!select) return;

    // Garder l'option Auto
    select.innerHTML = `<option value="auto">${escapeHtml(t('settings.terminal.autoOption', 'Auto (premier compatible)'))}</option>`;
    const localGroup = document.createElement('optgroup');
    localGroup.label = t('settings.terminal.localGroup', 'Ollama local');
    const cloudGroup = document.createElement('optgroup');
    cloudGroup.label = t('settings.terminal.cloudGroup', 'LLM cloud');

    // Récupérer les modèles Ollama installés
    const result = await apiOllama.getModels();
    const models = result.ok && result.data.models ? result.data.models : [];
    const toolCapableModels = [];

    for (const model of models) {
        if (isTerminalToolCapable(model.name)) {
            toolCapableModels.push(model.name);
        }
    }

    // Trier: Qwen récent en premier (recommandé)
    toolCapableModels.sort((a, b) => {
        const priority = (model) => {
            const lower = model.toLowerCase();
            if (lower.includes('qwen3.5')) return 0;
            if (lower.includes('qwen3')) return 1;
            if (lower.includes('qwen2.5')) return 2;
            if (lower.includes('llama3')) return 3;
            return 4;
        };
        const diff = priority(a) - priority(b);
        if (diff !== 0) return diff;
        return a.localeCompare(b);
    });

    // Ajouter au select
    for (const modelName of toolCapableModels) {
        const option = document.createElement('option');
        option.value = modelName;
        option.textContent = modelName;
        // Marquer le recommandé
        const lowerName = modelName.toLowerCase();
        if (lowerName.includes('qwen3.5:2b') || lowerName.includes('qwen3.5:4b')) {
            option.textContent += ` ${t('settings.terminal.recommendedSuffix', '(recommandé)')}`;
        }
        localGroup.appendChild(option);
    }

    if (localGroup.children.length > 0) {
        select.appendChild(localGroup);
    }

    const cloudModels = typeof loadTerminalCloudModelProfiles === 'function'
        ? await loadTerminalCloudModelProfiles()
        : (Array.isArray(window.joyboyTerminalCloudModels) ? window.joyboyTerminalCloudModels : []);
    for (const model of cloudModels || []) {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = `${model.name} ${t('settings.terminal.cloudSuffix', '(cloud)')}`;
        cloudGroup.appendChild(option);
    }

    if (cloudGroup.children.length > 0) {
        select.appendChild(cloudGroup);
    }

    // Sélectionner le modèle sauvegardé
    const savedModel = userSettings.terminalModel || 'auto';
    select.value = savedModel;

    // Si le modèle sauvegardé n'existe plus, revenir à auto
    if (select.value !== savedModel) {
        select.value = 'auto';
    }
}

/**
 * Met à jour le modèle terminal dans les settings
 */
function updateTerminalModel(value) {
    userSettings.terminalModel = value === 'auto' ? null : value;
    if (typeof terminalToolModel !== 'undefined') {
        terminalToolModel = userSettings.terminalModel || terminalToolModel;
    }
    if (typeof tokenStats !== 'undefined' && typeof getTerminalEffectiveContextSize === 'function') {
        tokenStats.maxContextSize = getTerminalEffectiveContextSize(userSettings.terminalModel || terminalToolModel);
        if (typeof updateTokenDisplay === 'function') updateTokenDisplay();
    }

    // Mettre à jour l'info
    const infoEl = document.getElementById('terminal-model-info');
    if (infoEl) {
        if (value === 'auto') {
            infoEl.innerHTML = t(
                'settings.terminal.recommendedInfo',
                'Recommandés : <strong>qwen3.5:2b</strong> ou <strong>qwen3.5:4b</strong><br>Éviter : 7B+ pour le router si tu génères aussi des images'
            );
        } else {
            infoEl.innerHTML = t('settings.terminal.modelInfo', 'Modèle terminal : <strong>{model}</strong>', {
                model: escapeHtml(value),
            });
        }
    }

    Toast.success(t('settings.terminal.modelToast', 'Modèle terminal : {model}', {
        model: value === 'auto' ? 'Auto' : value,
    }));
    saveSettings();
    if (typeof updateModelPickerDisplay === 'function') updateModelPickerDisplay();
}

// Obtenir le workspace actif (pour le chat)
function getActiveWorkspace() {
    if (!userSettings.activeWorkspace) return null;
    return userSettings.workspaces.find(w => w.name === userSettings.activeWorkspace) || null;
}

// Switch vers un workspace par son nom (appelé par l'IA)
function switchToWorkspace(workspaceName) {
    const workspace = userSettings.workspaces.find(w => w.name === workspaceName);
    if (!workspace) {
        console.error('[WORKSPACE] Workspace non trouvé:', workspaceName);
        return false;
    }

    userSettings.activeWorkspace = workspaceName;
    saveSettings();

    // Afficher un toast
    Toast.success(t('settings.workspace.activatedTitle', 'Workspace activé'), workspaceName, 3000);

    console.log('[WORKSPACE] Switched to:', workspaceName);
    return true;
}
