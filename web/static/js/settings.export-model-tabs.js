// ===== SETTINGS EXPORT AND MODEL TABS =====
// Export presets, model tabs, model availability validation, and no-model UI helpers.

// ===== EXPORT SETTINGS =====

function updateExportFormat(val) {
    saveSetting('exportFormat', val);
    const customRow = document.getElementById('export-custom-size-row');
    if (customRow) customRow.style.display = val === 'custom' ? '' : 'none';
}

function updateExportCustomSize(which, val) {
    const aligned = Math.max(64, Math.round(val / 64) * 64);
    const input = document.getElementById(which === 'width' ? 'settings-export-width' : 'settings-export-height');
    if (input) input.value = aligned;
    saveSetting(which === 'width' ? 'exportWidth' : 'exportHeight', aligned);
}



function addExportPreset() {
    const presets = userSettings.exportPresets || {};
    // Generate unique key like exp1, exp2...
    let idx = 1;
    while (presets['exp' + idx]) idx++;
    const key = 'exp' + idx;
    presets[key] = { format: 'auto', view: 'auto', pose: 'none', extraPrompt: '' };
    saveSetting('exportPresets', { ...presets });
    renderExportPresets();
}

function removeExportPreset(key) {
    const presets = { ...(userSettings.exportPresets || {}) };
    delete presets[key];
    saveSetting('exportPresets', presets);
    renderExportPresets();
}

function updateExportPreset(key, field, val) {
    const presets = { ...(userSettings.exportPresets || {}) };
    if (!presets[key]) return;
    presets[key] = { ...presets[key], [field]: val };
    saveSetting('exportPresets', presets);
}

function renameExportPreset(oldKey, newKey) {
    if (!newKey || newKey === oldKey) return;
    newKey = newKey.trim().toLowerCase().replace(/\s+/g, '_');
    if (!newKey) return;
    const presets = { ...(userSettings.exportPresets || {}) };
    if (presets[newKey]) return; // Already exists
    presets[newKey] = presets[oldKey];
    delete presets[oldKey];
    saveSetting('exportPresets', presets);
    renderExportPresets();
}

function renderExportPresets() {
    const container = document.getElementById('export-presets-list');
    if (!container) return;
    const presets = userSettings.exportPresets || {};
    const keys = Object.keys(presets);

    if (keys.length === 0) {
        container.innerHTML = `<div class="settings-label-desc">${escapeHtml(t('settings.generation.exportPresetsEmpty', 'Aucun preset. Clique sur Ajouter pour créer une règle.'))}</div>`;
        return;
    }

    container.innerHTML = keys.map(key => {
        const p = presets[key];
        return `<div class="export-preset-card" style="background:#111; border:1px solid #222; border-radius:8px; padding:12px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="color:#666; font-size:12px;">Mot-clé:</span>
                    <input type="text" value="${key}" class="settings-input" style="width:100px; font-size:13px; font-weight:600; color:#3b82f6;"
                        onchange="renameExportPreset('${key}', this.value)">
                </div>
                <button onclick="removeExportPreset('${key}')" style="background:#dc2626; border:none; border-radius:6px; color:white; padding:4px 10px; font-size:11px; cursor:pointer;">×</button>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                <select class="settings-select" onchange="updateExportPreset('${key}', 'format', this.value)" style="font-size:12px;">
                    <option value="auto" ${p.format === 'auto' ? 'selected' : ''}>Format: Auto</option>
                    <option value="9:16" ${p.format === '9:16' ? 'selected' : ''}>9:16</option>
                    <option value="16:9" ${p.format === '16:9' ? 'selected' : ''}>16:9</option>
                    <option value="1:1" ${p.format === '1:1' ? 'selected' : ''}>1:1</option>
                    <option value="3:4" ${p.format === '3:4' ? 'selected' : ''}>3:4</option>
                    <option value="4:3" ${p.format === '4:3' ? 'selected' : ''}>4:3</option>
                </select>
                <select class="settings-select" onchange="updateExportPreset('${key}', 'view', this.value)" style="font-size:12px;">
                    <option value="auto" ${p.view === 'auto' ? 'selected' : ''}>Vue: Auto</option>
                    <option value="full_body" ${p.view === 'full_body' ? 'selected' : ''}>${t('settings.generation.exportViewFullBody', 'Plan large')}</option>
                    <option value="upper_body" ${p.view === 'upper_body' ? 'selected' : ''}>${t('settings.generation.exportViewUpperBody', 'Plan moyen')}</option>
                    <option value="portrait_close" ${p.view === 'portrait_close' ? 'selected' : ''}>${t('settings.generation.exportViewPortrait', 'Gros plan')}</option>
                    <option value="low_angle" ${p.view === 'low_angle' ? 'selected' : ''}>${t('settings.generation.exportViewLowAngle', 'Contre-plongée')}</option>
                    <option value="high_angle" ${p.view === 'high_angle' ? 'selected' : ''}>${t('settings.generation.exportViewHighAngle', 'Plongée')}</option>
                    <option value="from_behind" ${p.view === 'from_behind' ? 'selected' : ''}>${t('settings.generation.exportViewBehind', 'Vue arrière')}</option>
                </select>
                <select class="settings-select" onchange="updateExportPreset('${key}', 'pose', this.value)" style="font-size:12px;">
                    <option value="none" ${p.pose === 'none' ? 'selected' : ''}>Pose: Aucune</option>
                    <option value="legs_up" ${p.pose === 'legs_up' ? 'selected' : ''}>${t('settings.generation.exportPoseLegsUp', 'Recliné, jambes relevées')}</option>
                    <option value="on_all_fours" ${p.pose === 'on_all_fours' ? 'selected' : ''}>${t('settings.generation.exportPoseAllFours', 'Appui mains/genoux')}</option>
                    <option value="lying_down" ${p.pose === 'lying_down' ? 'selected' : ''}>${t('settings.generation.exportPoseLyingDown', 'Allongé')}</option>
                    <option value="lying_face_up" ${p.pose === 'lying_face_up' ? 'selected' : ''}>${t('settings.generation.exportPoseFaceUp', 'Allongé sur le dos')}</option>
                    <option value="lying_on_stomach" ${p.pose === 'lying_on_stomach' ? 'selected' : ''}>${t('settings.generation.exportPoseOnStomach', 'Allongé sur le ventre')}</option>
                    <option value="sitting" ${p.pose === 'sitting' ? 'selected' : ''}>${t('settings.generation.exportPoseSitting', 'Assis')}</option>
                    <option value="kneeling" ${p.pose === 'kneeling' ? 'selected' : ''}>${t('settings.generation.exportPoseKneeling', 'Posture basse')}</option>
                    <option value="standing_spread" ${p.pose === 'standing_spread' ? 'selected' : ''}>${t('settings.generation.exportPoseStandingSpread', 'Debout, appui large')}</option>
                </select>
                <input type="text" class="settings-input" placeholder="Extra prompt..." value="${p.extraPrompt || ''}" style="font-size:12px;"
                    onchange="updateExportPreset('${key}', 'extraPrompt', this.value)">
            </div>
        </div>`;
    }).join('');
}

function initExportSettings() {
    hydrateExportGuidanceControls();

    // Format select
    const formatSel = document.getElementById('settings-export-format');
    if (formatSel) formatSel.value = userSettings.exportFormat || 'auto';

    // Custom size row visibility
    const customRow = document.getElementById('export-custom-size-row');
    if (customRow) customRow.style.display = (userSettings.exportFormat === 'custom') ? '' : 'none';

    // Custom W×H values
    const wInput = document.getElementById('settings-export-width');
    const hInput = document.getElementById('settings-export-height');
    if (wInput) wInput.value = userSettings.exportWidth || 768;
    if (hInput) hInput.value = userSettings.exportHeight || 1344;

    // View select
    const viewSel = document.getElementById('settings-export-view');
    if (viewSel) viewSel.value = userSettings.exportView || 'auto';

    // Pose select
    const poseSel = document.getElementById('settings-export-pose');
    if (poseSel) poseSel.value = userSettings.exportPose || 'none';

    updateExportGuidanceVisibility();

    // Pose strength slider
    const poseStrSlider = document.getElementById('settings-pose-strength');
    const poseStrValue = document.getElementById('settings-pose-strength-value');
    if (poseStrSlider) {
        poseStrSlider.value = userSettings.poseStrength ?? 0.5;
        if (poseStrValue) poseStrValue.textContent = poseStrSlider.value;
    }

    // Render presets
    renderExportPresets();
}

function switchModelsSubtab(type, clickedEl) {
    // Update tabs
    document.querySelectorAll('.models-subtab').forEach(tab => tab.classList.remove('active'));
    clickedEl?.classList.add('active');

    // Update panels
    document.querySelectorAll('.models-subpanel').forEach(panel => panel.classList.remove('active'));

    if (type === 'text') {
        document.getElementById('models-text-panel')?.classList.add('active');
    } else if (type === 'image') {
        document.getElementById('models-image-panel')?.classList.add('active');
        // Auto-charger les modèles image
        checkModelsStatus();
    } else if (type === 'video') {
        document.getElementById('models-video-panel')?.classList.add('active');
        if (typeof checkVideoModelsStatus === 'function') {
            checkVideoModelsStatus();
        }
    }
}

function switchModelsInnerTab(panelId, tabName, clickedEl) {
    const panel = document.getElementById(panelId);
    if (!panel) return;

    panel.querySelectorAll('.models-inner-tab').forEach(tab => {
        tab.classList.toggle('active', tab === clickedEl);
    });
    panel.querySelectorAll('.models-inner-panel').forEach(innerPanel => {
        innerPanel.classList.toggle('active', innerPanel.dataset.innerPanel === tabName);
    });

    if (panelId === 'models-image-panel' && (tabName === 'catalog' || tabName === 'installed')) {
        checkModelsStatus();
    }
    if (panelId === 'models-video-panel' && (tabName === 'catalog' || tabName === 'installed')) {
        if (typeof checkVideoModelsStatus === 'function') {
            checkVideoModelsStatus();
        }
    }
}

// Vérifier si un modèle Ollama est disponible
async function checkOllamaModelAvailable() {
    const selectedModel = userSettings.chatModel;
    if (settingsIsCloudTextModel(selectedModel)) {
        return { available: true, cloud: true };
    }

    // Vérifier si Ollama est installé et tourne
    const statusResult = await apiOllama.getStatus();
    if (!statusResult.ok) {
        return {
            available: false,
            message: t('settings.models.ollamaContactError', 'Impossible de contacter Ollama. Vérifie que le serveur est lancé.')
        };
    }

    const status = statusResult.data;
    if (!status.installed) {
        return {
            available: false,
            message: t('settings.models.ollamaInstallHint', "Ollama n'est pas installé. Télécharge-le sur ollama.ai")
        };
    }

    if (!status.running) {
        return {
            available: false,
            message: t('settings.models.ollamaStartHint', "Ollama n'est pas démarré. Lance 'ollama serve' ou redémarre l'app.")
        };
    }

    // Vérifier si des modèles sont installés
    const modelsResult = await apiOllama.getModels();
    if (!modelsResult.ok) {
        return {
            available: false,
            message: t('settings.models.modelListError', 'Impossible de récupérer la liste des modèles.')
        };
    }

    const modelsData = modelsResult.data;
    if (!modelsData.models || modelsData.models.length === 0) {
        return {
            available: false,
            message: t('settings.models.noInstalledSettingsHint', 'Aucun modèle sur la machine. Va dans Modèles > Disponibles.')
        };
    }

    // Vérifier si le modèle sélectionné existe
    const modelExists = modelsData.models.some(m => m.name === selectedModel);

    if (!modelExists) {
        // Le modèle sélectionné n'existe pas, utiliser le premier disponible
        userSettings.chatModel = modelsData.models[0].name;
        saveSettings();
    }

    return { available: true };
}

// Afficher erreur quand pas de modèle
function showNoModelError(message) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) {
        JoyDialog.alert(message, { variant: 'danger' });
        return;
    }

    const errorHtml = `
        <div class="message no-model-error">
            <div class="ai-response">
                <div class="chat-bubble error-bubble">
                    <div class="error-icon"><i data-lucide="alert-triangle"></i></div>
                    <div class="error-text">${message}</div>
                    <button class="error-settings-btn" onclick="openModelsHub();">
                        ${escapeHtml(t('settings.models.openSettings', 'Ouvrir les paramètres'))}
                    </button>
                </div>
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', errorHtml);
    if (window.lucide) lucide.createIcons();
    scrollToBottom();
}

// Mettre à jour le sélecteur de modèle si le modèle n'existe plus
async function validateSelectedModel() {
    const selectEl = DOM.get('settings-chat-model');
    if (!selectEl) return;

    if (settingsIsCloudTextModel(userSettings.chatModel)) {
        settingsRenderCloudChatOption(selectEl, userSettings.chatModel);
        return;
    }

    const result = await apiOllama.getModels();
    if (!result.ok) {
        console.error('Erreur validation modèle:', result.error);
        return;
    }

    const data = result.data;
    if (!data.models || data.models.length === 0) {
        selectEl.innerHTML = `<option value="">${escapeHtml(t('settings.models.noModels', 'Aucun modèle'))}</option>`;
        userSettings.chatModel = '';
        saveSettings();
    } else {
        const modelExists = data.models.some(m => m.name === userSettings.chatModel);
        if (!modelExists) {
            userSettings.chatModel = data.models[0].name;
            saveSettings();
        }
        selectEl.value = userSettings.chatModel;
    }
}
