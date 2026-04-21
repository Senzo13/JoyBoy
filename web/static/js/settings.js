// ===== SETTINGS - User settings management =====
// Uses api.js for fetch calls and utils.js for Toast/DOM helpers

// ===== ACTIVE DOWNLOADS =====
let activeDownloads = {};
let lastDoctorReport = null;
let lastHarnessAudit = null;
let activeAddonsHubSection = 'library';

function t(key, fallback = '', params = {}) {
    return window.JoyBoyI18n?.t?.(key, params, fallback) || fallback || key;
}

function getCurrentLocale() {
    return window.JoyBoyI18n?.getLocale?.() || document.documentElement.lang || 'fr';
}

function syncLocaleSelectors(locale = getCurrentLocale()) {
    document.querySelectorAll('[data-locale-select]').forEach(select => {
        select.value = locale;
    });
}

async function changeLocale(locale) {
    const nextLocale = window.JoyBoyI18n?.normalizeLocale?.(locale) || locale || 'fr';
    window.JoyBoyI18n?.setLocale?.(nextLocale);
    syncLocaleSelectors(nextLocale);

    try {
        await apiSettings.setLocale(nextLocale);
    } catch (error) {
        console.warn('[I18N] Impossible de synchroniser la langue côté backend:', error);
    }
}

function setRuntimeText(target, key, fallback = '', params = {}) {
    const element = typeof target === 'string' ? document.getElementById(target) : target;
    if (!element) return;
    element.dataset.i18nRuntimeKey = key || '';
    element.dataset.i18nRuntimeFallback = fallback || '';
    element.dataset.i18nRuntimeParams = JSON.stringify(params || {});
    element.textContent = t(key, fallback, params);
}

function setPlainText(target, value) {
    const element = typeof target === 'string' ? document.getElementById(target) : target;
    if (!element) return;
    delete element.dataset.i18nRuntimeKey;
    delete element.dataset.i18nRuntimeFallback;
    delete element.dataset.i18nRuntimeParams;
    element.textContent = value;
}

function getOnboardingQualityLabel(level) {
    const labels = {
        low: t('onboarding.qualityLow', 'Rapide'),
        medium: t('onboarding.qualityMedium', 'Équilibré'),
        high: t('onboarding.qualityHigh', 'Qualité'),
        very_high: t('onboarding.qualityVeryHigh', 'Haute qualité'),
        ultra: t('onboarding.qualityUltra', 'Ultra'),
        extreme: t('onboarding.qualityExtreme', 'Maximum'),
    };
    return labels[level] || t('onboarding.qualityStandard', 'Standard');
}

function localizeModelDisplayName(name) {
    return String(name || '')
        .replace(/\(Fast\)/g, `(${t('modelLabels.fast', 'Fast')})`)
        .replace(/\(Moyen\)/g, `(${t('modelLabels.medium', 'Moyen')})`)
        .replace(/\(Normal\)/g, `(${t('modelLabels.normal', 'Normal')})`);
}

function refreshRuntimeTexts(root = document) {
    root.querySelectorAll('[data-i18n-runtime-key]').forEach(element => {
        const key = element.dataset.i18nRuntimeKey || '';
        const fallback = element.dataset.i18nRuntimeFallback || '';
        let params = {};
        try {
            params = JSON.parse(element.dataset.i18nRuntimeParams || '{}');
        } catch {
            params = {};
        }
        element.textContent = t(key, fallback, params);
    });
}

function updateModelImportFamilyLabels() {
    const select = document.getElementById('model-source-family');
    if (!select) return;

    const labels = {
        generic: t('settings.models.targetGeneric', 'Générique'),
        image: t('settings.models.targetImage', 'Image'),
        video: t('settings.models.targetVideo', 'Vidéo'),
        utility: t('settings.models.targetUtility', 'Utility'),
    };

    Array.from(select.options).forEach(option => {
        option.textContent = labels[option.value] || option.value;
    });
}

function updateSelectOptionLabels(selectId, labels = {}) {
    const select = document.getElementById(selectId);
    if (!select) return;
    Array.from(select.options).forEach(option => {
        if (labels[option.value]) {
            option.textContent = labels[option.value];
        }
    });
}

function hydrateExportGuidanceControls() {
    if (document.getElementById('settings-export-guidance-type')) return;

    const viewSelect = document.getElementById('settings-export-view');
    const poseSelect = document.getElementById('settings-export-pose');
    const viewSection = viewSelect?.closest('.settings-section');
    const poseSection = poseSelect?.closest('.settings-section');
    const viewRow = viewSelect?.closest('.settings-row');
    const poseRow = poseSelect?.closest('.settings-row');

    if (!viewSection || !poseSection || !viewRow || !poseRow) return;

    const guidanceSection = document.createElement('div');
    guidanceSection.className = 'settings-section export-guidance-section';
    guidanceSection.id = 'gen-export-guidance-section';
    guidanceSection.innerHTML = `
        <div class="settings-section-title" id="gen-export-guidance-title">${escapeHtml(t('settings.generation.exportGuidanceTitle', 'Guidage image'))}</div>
        <div class="settings-info" id="gen-export-guidance-desc">${escapeHtml(t('settings.generation.exportGuidanceDesc', 'Choisis si ce réglage pilote une pose humaine ou le cadrage caméra.'))}</div>
        <div class="settings-row">
            <div>
                <div class="settings-label" id="gen-export-guidance-label">${escapeHtml(t('settings.generation.exportGuidanceLabel', 'Type de guidage'))}</div>
                <div class="settings-label-desc" id="gen-export-guidance-help">${escapeHtml(t('settings.generation.exportGuidanceHelp', 'Choisis le guidage actif. L’autre réglage est ignoré pendant la génération.'))}</div>
            </div>
            <select class="settings-select" id="settings-export-guidance-type" onchange="updateExportGuidanceType(this.value)">
                <option value="human">${escapeHtml(t('settings.generation.exportGuidanceHuman', 'Pose humaine'))}</option>
                <option value="camera">${escapeHtml(t('settings.generation.exportGuidanceCamera', 'Cadrage / caméra'))}</option>
            </select>
        </div>
    `;

    viewRow.id = 'export-camera-guide-row';
    poseRow.id = 'export-human-pose-row';
    viewSection.parentNode.insertBefore(guidanceSection, viewSection);
    guidanceSection.appendChild(viewRow);
    guidanceSection.appendChild(poseRow);
    viewSection.remove();
    poseSection.remove();
}

function updateGenerationSelectLabels() {
    updateSelectOptionLabels('settings-backend', {
        diffusers: t('settings.generation.backendOptionDiffusers', 'Diffusers (standard)'),
        gguf: t('settings.generation.backendOptionGguf', 'GGUF (VRAM optimized)'),
    });

    updateSelectOptionLabels('settings-video-quality', {
        '720p': t('settings.generation.videoQuality720', '720p - High quality (1280×704)'),
        '480p': t('settings.generation.videoQuality480', '480p - Faster (832×480)'),
    });

    updateSelectOptionLabels('settings-face-restore', {
        off: t('settings.generation.faceRestoreOff', 'Disabled'),
        gfpgan: t('settings.generation.faceRestoreGfpgan', 'GFPGAN (recommended)'),
        codeformer: t('settings.generation.faceRestoreCodeformer', 'CodeFormer'),
    });

    updateSelectOptionLabels('settings-export-format', {
        auto: t('settings.generation.exportFormatAuto', 'Auto (prompt decides)'),
        '9:16': t('settings.generation.exportFormat916', '9:16 Portrait (768×1344)'),
        '16:9': t('settings.generation.exportFormat169', '16:9 Landscape (1344×768)'),
        '1:1': t('settings.generation.exportFormat11', '1:1 Square (1024×1024)'),
        '3:4': t('settings.generation.exportFormat34', '3:4 Portrait (896×1152)'),
        '4:3': t('settings.generation.exportFormat43', '4:3 Landscape (1152×896)'),
        custom: t('settings.generation.exportFormatCustom', 'Custom (W×H)'),
    });

    updateSelectOptionLabels('settings-export-guidance-type', {
        human: t('settings.generation.exportGuidanceHuman', 'Human pose'),
        camera: t('settings.generation.exportGuidanceCamera', 'Framing / camera'),
    });

    updateSelectOptionLabels('settings-export-view', {
        auto: t('settings.generation.exportViewAuto', 'Auto'),
        full_body: t('settings.generation.exportViewFullBody', 'Wide shot'),
        upper_body: t('settings.generation.exportViewUpperBody', 'Medium shot'),
        portrait_close: t('settings.generation.exportViewPortrait', 'Close-up'),
        low_angle: t('settings.generation.exportViewLowAngle', 'Low angle'),
        high_angle: t('settings.generation.exportViewHighAngle', 'High angle'),
        from_behind: t('settings.generation.exportViewBehind', 'From behind'),
    });

    updateSelectOptionLabels('settings-export-pose', {
        none: t('settings.generation.exportPoseNone', 'None'),
        legs_up: t('settings.generation.exportPoseLegsUp', 'Reclined, raised legs'),
        on_all_fours: t('settings.generation.exportPoseAllFours', 'Hands-and-knees support'),
        lying_down: t('settings.generation.exportPoseLyingDown', 'Reclined'),
        lying_face_up: t('settings.generation.exportPoseFaceUp', 'Lying on back'),
        lying_on_stomach: t('settings.generation.exportPoseOnStomach', 'Lying on stomach'),
        sitting: t('settings.generation.exportPoseSitting', 'Sitting'),
        kneeling: t('settings.generation.exportPoseKneeling', 'Low stance'),
        standing_spread: t('settings.generation.exportPoseStandingSpread', 'Wide standing stance'),
    });
}

function hydrateExportPresetControls() {
    const button = document.getElementById('gen-export-add-preset-btn');
    if (!button) return;

    const presetsSection = document.getElementById('gen-export-presets-title')?.closest('.settings-section');
    if (presetsSection) {
        presetsSection.classList.add('export-presets-section');
    }

    button.classList.remove('settings-subtab');
    button.classList.add('settings-action-btn', 'compact', 'settings-add-preset-btn');
    button.removeAttribute('style');

    const label = t('settings.generation.exportAddPreset', 'Ajouter un preset');
    if (!button.querySelector('[data-lucide]')) {
        button.innerHTML = `<i data-lucide="plus" aria-hidden="true"></i><span id="gen-export-add-preset-label">${escapeHtml(label)}</span>`;
    } else {
        const labelEl = button.querySelector('#gen-export-add-preset-label') || button.querySelector('span');
        if (labelEl) labelEl.textContent = label;
    }

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function removeLegacyInternalImageOptions() {
    const section = document.getElementById('gen-image-common-title')?.closest('.settings-section');
    if (section) section.remove();
}

function getExportGuidanceType() {
    if (userSettings.exportGuidanceType === 'camera' || userSettings.exportGuidanceType === 'human') {
        return userSettings.exportGuidanceType;
    }

    const view = userSettings.exportView || 'auto';
    const pose = userSettings.exportPose || 'none';
    if (view !== 'auto' && pose === 'none') {
        return 'camera';
    }
    return 'human';
}

function updateExportGuidanceVisibility() {
    const type = getExportGuidanceType();
    const select = document.getElementById('settings-export-guidance-type');
    const cameraRow = document.getElementById('export-camera-guide-row');
    const humanRow = document.getElementById('export-human-pose-row');

    if (select) select.value = type;
    if (cameraRow) cameraRow.style.display = type === 'camera' ? '' : 'none';
    if (humanRow) humanRow.style.display = type === 'human' ? '' : 'none';
}

function updateExportGuidanceType(value) {
    saveSetting('exportGuidanceType', value === 'camera' ? 'camera' : 'human');
    updateExportGuidanceVisibility();
}

function getModelImportTargetLabel(value) {
    const keyMap = {
        generic: 'settings.models.targetGeneric',
        image: 'settings.models.targetImage',
        video: 'settings.models.targetVideo',
        utility: 'settings.models.targetUtility',
    };
    const fallbackMap = {
        generic: 'Générique',
        image: 'Image',
        video: 'Vidéo',
        utility: 'Utility',
    };
    return t(keyMap[value] || '', fallbackMap[value] || value);
}

function refreshLocaleSensitiveSurfaces() {
    syncLocaleSelectors();
    refreshRuntimeTexts();
    updateModelImportFamilyLabels();
    removeLegacyInternalImageOptions();
    hydrateExportGuidanceControls();
    updateGenerationSelectLabels();
    updateExportGuidanceVisibility();
    hydrateExportPresetControls();

    if (typeof updateProfileUI === 'function') {
        updateProfileUI();
    }

    if (window.joyboyFeatureFlags || window.joyboyFeatureExposure || window.joyboyInstalledPacks) {
        applyFeatureFlagsToUI(
            window.joyboyFeatureFlags || {},
            window.joyboyFeatureExposure || null,
            window.joyboyInstalledPacks || null
        );
    }

    if (document.getElementById('provider-settings-list')) {
        loadProviderSettings();
    }
    if (document.getElementById('pack-settings-list')) {
        loadPackSettings();
    }
    if (typeof renderCachedImageModelLists === 'function') {
        renderCachedImageModelLists();
    }
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
        renderModelPickerList('edit');
    }
    if (typeof updateModelPickerDisplay === 'function') {
        updateModelPickerDisplay();
    }
    if (typeof updateActiveWorkspaceUI === 'function') {
        updateActiveWorkspaceUI();
    }
    if (lastDoctorReport) {
        renderDoctorReport(lastDoctorReport);
    }
    if (lastHarnessAudit) {
        renderHarnessAudit(lastHarnessAudit);
    }
    if (onboardingDoctor) {
        renderOnboardingReadiness(onboardingDoctor);
    }
    if (document.getElementById('memory-info') || document.getElementById('chats-info')) {
        initMemoryTab();
    }
}

window.addEventListener('joyboy:locale-changed', () => {
    refreshLocaleSensitiveSurfaces();
});

function resetAllSettings() {
    userSettings.maskEnabled = true;
    userSettings.dilation = DEFAULT_DILATION;
    userSettings.strength = DEFAULT_STRENGTH;
    userSettings.nsfwStrength = 0.90;
    userSettings.controlnetDepth = 0.54;
    userSettings.enhancePrompt = true;
    userSettings.steps = DEFAULT_STEPS;

    document.getElementById('mask-toggle').classList.add('active');

    document.getElementById('dilation-slider-container').style.opacity = '1';
    document.getElementById('dilation-slider-container').style.pointerEvents = 'auto';

    // Garder le modèle actuel ou utiliser le premier disponible
    const currentModel = userSettings.chatModel || 'qwen3.5:2b';
    const displayName = typeof _formatModelName === 'function' ? _formatModelName(currentModel) : currentModel;
    document.getElementById('model-select').value = currentModel;
    document.getElementById('selected-model-text').textContent = displayName;
    document.getElementById('chat-selected-model-text').textContent = displayName;

    saveSettings();
    applySettingsToUI();

    const btn = document.querySelector('.reset-settings-btn');
    if (btn) {
        btn.style.background = '#22c55e';
        setTimeout(() => btn.style.background = '', 500);
    }
}

function loadPresets() {
    for (let i = 1; i <= 3; i++) {
        const saved = localStorage.getItem(`preset_${i}`);
        if (saved) {
            presets[i] = saved;
            document.getElementById(`preset-text-${i}`).textContent = saved || t('settings.generation.presetEditHint', 'Clic droit pour éditer');
        }
    }
}

function initSettingsFromCache() {
    document.getElementById('dilation-slider').value = userSettings.dilation;
    document.getElementById('dilation-value').textContent = userSettings.dilation + 'px';

    document.getElementById('strength-slider').value = userSettings.strength;
    document.getElementById('strength-value').textContent = Math.round(userSettings.strength * 100) + '%';

    document.getElementById('steps-slider').value = userSettings.steps;
    document.getElementById('steps-value').textContent = userSettings.steps;

    const maskToggle = document.getElementById('mask-toggle');
    const clothesToggle = document.getElementById('clothes-only-toggle');
    const enhanceToggle = document.getElementById('enhance-toggle');

    if (userSettings.maskEnabled) {
        maskToggle.classList.add('active');
    } else {
        maskToggle.classList.remove('active');
        document.getElementById('dilation-slider-container').style.opacity = '0.4';
        document.getElementById('dilation-slider-container').style.pointerEvents = 'none';
    }

    if (userSettings.enhancePrompt) enhanceToggle.classList.add('active');
    else enhanceToggle.classList.remove('active');

    // Modèle image (home picker)
    document.getElementById('model-select').value = lastModel;
    const modelText = document.getElementById('selected-model-text');
    if (modelText) modelText.textContent = lastModel;

    // Modèle chat (chat picker) - utiliser le chatModel des settings
    const chatModelText = document.getElementById('chat-selected-model-text');
    if (chatModelText && userSettings.chatModel) {
        chatModelText.textContent = typeof _formatModelName === 'function'
            ? _formatModelName(userSettings.chatModel)
            : userSettings.chatModel;
    }

    // Apply action bar visibility
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
        if (userSettings.showActionBar) {
            sidebar.classList.remove('hidden');
        } else {
            sidebar.classList.add('hidden');
        }
    }
}

function toggleMask() {
    userSettings.maskEnabled = !userSettings.maskEnabled;
    const toggle = document.getElementById('mask-toggle');
    const sliderContainer = document.getElementById('dilation-slider-container');

    if (userSettings.maskEnabled) {
        toggle.classList.add('active');
        sliderContainer.style.opacity = '1';
        sliderContainer.style.pointerEvents = 'auto';
    } else {
        toggle.classList.remove('active');
        sliderContainer.style.opacity = '0.4';
        sliderContainer.style.pointerEvents = 'none';
    }
    saveSettings();
}

function updateDilation(value) {
    userSettings.dilation = parseInt(value);
    document.getElementById('dilation-value').textContent = value + 'px';
    saveSettings();
}

function updateStrength(value) {
    userSettings.strength = parseFloat(value);
    document.getElementById('strength-value').textContent = Math.round(value * 100) + '%';
    saveSettings();
}

function toggleEnhance() {
    userSettings.enhancePrompt = !userSettings.enhancePrompt;
    const toggle = document.getElementById('enhance-toggle');
    if (userSettings.enhancePrompt) {
        toggle.classList.add('active');
    } else {
        toggle.classList.remove('active');
    }
    saveSettings();
}

function updateSteps(value) {
    userSettings.steps = parseInt(value);
    document.getElementById('steps-value').textContent = value;
    saveSettings();
}

function usePreset(num) {
    const prompt = presets[num];
    if (!prompt) {
        editPreset(num);
        return;
    }
    const homeView = document.getElementById('home-view');
    if (homeView.style.display !== 'none') {
        document.getElementById('prompt-input').value = prompt;
        document.getElementById('prompt-input').focus();
    } else {
        document.getElementById('chat-prompt').value = prompt;
        document.getElementById('chat-prompt').focus();
    }
}

function editPreset(num, event) {
    if (event) event.preventDefault();
    editingPresetNum = num;
    document.getElementById('editing-preset-num').textContent = num;
    document.getElementById('preset-edit-input').value = presets[num] || '';
    document.getElementById('preset-modal').classList.add('open');
    document.getElementById('preset-edit-input').focus();
}

function closePresetModal() {
    document.getElementById('preset-modal').classList.remove('open');
    editingPresetNum = null;
}

function savePreset() {
    if (editingPresetNum === null) return;
    const value = document.getElementById('preset-edit-input').value.trim();
    presets[editingPresetNum] = value;
    localStorage.setItem(`preset_${editingPresetNum}`, value);
    document.getElementById(`preset-text-${editingPresetNum}`).textContent = value || t('settings.generation.presetEditHint', 'Clic droit pour éditer');
    closePresetModal();
}

// saveSettings / loadSettings — now handled by SettingsContext (auto-save via Proxy)
function saveSettings() {
    // Legacy: sync lastModel from DOM if available
    const modelSelect = document.getElementById('model-select');
    if (modelSelect && modelSelect.value) {
        Settings.set('lastModel', modelSelect.value);
    }
    // The actual save happens automatically via SettingsContext debounce.
    // Force an immediate save for callers that expect synchronous persistence.
    Settings._save();
}

function applySettingsToUI() {
    initSettingsFromCache();
    // Init backend GGUF UI
    if (typeof initBackendUI === 'function') {
        initBackendUI();
    }
    // Re-render model picker avec le bon filtrage backend
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
    }
}

// ===== SETTINGS MODAL =====

function openSettings() {
    const modal = document.getElementById('settings-modal');
    document.querySelectorAll('.settings-title').forEach(title => {
        title.textContent = t('settings.title', 'Paramètres');
    });
    modal?.classList.add('open');
    initSettingsModal();
}

function closeSettings() {
    const modal = document.getElementById('settings-modal');
    modal?.classList.remove('open');
    document.querySelectorAll('.settings-title').forEach(title => {
        title.textContent = t('settings.title', 'Paramètres');
    });
}

function openAddonsHub() {
    const addonsView = document.getElementById('addons-view');
    const addonsHost = document.getElementById('addons-view-content');
    const addonsPanel = document.getElementById('settings-addons');
    if (!addonsView || !addonsHost || !addonsPanel) return;

    document.getElementById('settings-modal')?.classList.remove('open');
    addonsHost.appendChild(addonsPanel);
    addonsPanel.classList.remove('settings-panel');
    addonsPanel.classList.add('active', 'addons-view-panel');

    const adultSection = document.getElementById('adult-mode-section');
    const localRuntimePanel = document.getElementById('gen-nsfw');
    if (adultSection && localRuntimePanel && localRuntimePanel.parentElement !== adultSection) {
        adultSection.appendChild(localRuntimePanel);
    }

    const addonsExplorer = addonsPanel.querySelector('.addons-explorer') || addonsPanel;
    const helpPanel = document.getElementById('settings-help');
    if (helpPanel && helpPanel.parentElement !== addonsExplorer) {
        addonsExplorer.appendChild(helpPanel);
    }
    if (helpPanel) {
        helpPanel.classList.remove('settings-panel');
        helpPanel.classList.add('addons-help-panel');
    }

    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const modelsView = document.getElementById('models-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (modelsView) modelsView.style.display = 'none';
    addonsView.style.display = 'flex';
    document.body.classList.add('addons-mode');
    document.body.classList.remove('models-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('sidebar-addons-btn')?.classList.add('active');

    loadPackSettings();
    setAddonsHubSection(activeAddonsHubSection);
    if (window.lucide) lucide.createIcons();
}

function setAddonsHubSection(section = 'library', clickedEl = null) {
    const validSections = new Set(['library', 'runtime', 'help']);
    activeAddonsHubSection = validSections.has(section) ? section : 'library';

    document.querySelectorAll('[data-addons-tab]').forEach(tab => {
        const isActive = tab.dataset.addonsTab === activeAddonsHubSection;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    clickedEl?.classList.add('active');

    const libraryNodes = [
        document.querySelector('.addons-searchbar'),
        document.querySelector('.addons-filter-row'),
        document.getElementById('addons-packs-section'),
    ];
    libraryNodes.forEach(node => {
        if (node) node.style.display = activeAddonsHubSection === 'library' ? '' : 'none';
    });

    const runtimeNode = document.getElementById('adult-mode-section');
    if (runtimeNode) runtimeNode.style.display = activeAddonsHubSection === 'runtime' ? '' : 'none';

    const helpNode = document.getElementById('settings-help');
    if (helpNode) helpNode.style.display = activeAddonsHubSection === 'help' ? 'block' : 'none';

    if (window.lucide) lucide.createIcons();
}

function openModelsHub() {
    const modelsView = document.getElementById('models-view');
    const modelsHost = document.getElementById('models-view-content');
    const modelsPanel = document.getElementById('settings-models');
    if (!modelsView || !modelsHost || !modelsPanel) return;

    document.getElementById('settings-modal')?.classList.remove('open');
    modelsHost.appendChild(modelsPanel);
    modelsPanel.classList.remove('settings-panel');
    modelsPanel.classList.add('active', 'models-view-panel');

    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const addonsView = document.getElementById('addons-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (addonsView) addonsView.style.display = 'none';
    modelsView.style.display = 'flex';
    document.body.classList.add('models-mode');
    document.body.classList.remove('addons-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('sidebar-models-btn')?.classList.add('active');

    initOllamaTab();
    if (window.lucide) lucide.createIcons();
}

function initSettingsModal() {
    loadFeatureFlags();
    loadVideoModelsForRuntime();
    syncLocaleSelectors(getCurrentLocale());
    updateModelImportFamilyLabels();
    removeLegacyInternalImageOptions();
    hydrateExportGuidanceControls();
    updateGenerationSelectLabels();
    updateExportGuidanceVisibility();
    hydrateExportPresetControls();

    // Steps slider (inpainting)
    const stepsSlider = document.getElementById('settings-steps');
    const stepsValue = document.getElementById('settings-steps-value');
    if (stepsSlider) {
        stepsSlider.value = userSettings.steps;
        stepsValue.textContent = userSettings.steps;
    }

    // Text2Img Steps slider
    const text2imgStepsSlider = document.getElementById('settings-text2img-steps');
    const text2imgStepsValue = document.getElementById('settings-text2img-steps-value');
    if (text2imgStepsSlider) {
        text2imgStepsSlider.value = userSettings.text2imgSteps || 30;
        text2imgStepsValue.textContent = userSettings.text2imgSteps || 30;
    }

    // Text2Img Guidance slider
    const text2imgGuidanceSlider = document.getElementById('settings-text2img-guidance');
    const text2imgGuidanceValue = document.getElementById('settings-text2img-guidance-value');
    if (text2imgGuidanceSlider) {
        text2imgGuidanceSlider.value = userSettings.text2imgGuidance ?? 7.5;
        text2imgGuidanceValue.textContent = userSettings.text2imgGuidance ?? 7.5;
    }

    // Face Ref Scale slider
    const faceRefScaleSlider = document.getElementById('settings-face-ref-scale');
    const faceRefScaleValue = document.getElementById('settings-face-ref-scale-value');
    if (faceRefScaleSlider) {
        faceRefScaleSlider.value = userSettings.faceRefScale ?? 0.35;
        faceRefScaleValue.textContent = userSettings.faceRefScale ?? 0.35;
    }

    // Style Ref Scale slider
    const styleRefScaleSlider = document.getElementById('settings-style-ref-scale');
    const styleRefScaleValue = document.getElementById('settings-style-ref-scale-value');
    if (styleRefScaleSlider) {
        styleRefScaleSlider.value = userSettings.styleRefScale ?? 0.55;
        styleRefScaleValue.textContent = userSettings.styleRefScale ?? 0.55;
    }

    // ControlNet Depth scale slider (0-100 → 0.00-1.00)
    const ctrlDepthSlider = document.getElementById('settings-controlnet-depth');
    const ctrlDepthValue = document.getElementById('settings-controlnet-depth-value');
    if (ctrlDepthSlider) {
        const depthVal = userSettings.controlnetDepth;
        if (depthVal != null) {
            ctrlDepthSlider.value = Math.round(depthVal * 100);
            ctrlDepthValue.textContent = depthVal.toFixed(2);
        } else {
            ctrlDepthSlider.value = 0;
            ctrlDepthValue.textContent = 'Auto';
        }
    }

    // Composite Blur Radius slider (0=Auto, 1-64px)
    const compRadiusSlider = document.getElementById('settings-composite-radius');
    const compRadiusValue = document.getElementById('settings-composite-radius-value');
    if (compRadiusSlider) {
        const radiusVal = userSettings.compositeRadius;
        if (radiusVal != null) {
            compRadiusSlider.value = radiusVal;
            compRadiusValue.textContent = radiusVal + 'px';
        } else {
            compRadiusSlider.value = 0;
            compRadiusValue.textContent = 'Auto';
        }
    }

    // NSFW strength slider (slider 70-100, valeur réelle 0.70-1.0)
    const nsfwSlider = document.getElementById('settings-nsfw-strength');
    const nsfwValue = document.getElementById('settings-nsfw-strength-value');
    if (nsfwSlider) {
        nsfwSlider.value = (userSettings.nsfwStrength ?? 0.90) * 100;
        nsfwValue.textContent = Math.round((userSettings.nsfwStrength ?? 0.90) * 100) + '%';
    }

    // LoRA NSFW toggle & slider
    const loraNsfwToggle = document.getElementById('toggle-lora-nsfw');
    const loraNsfwSlider = document.getElementById('settings-lora-nsfw');
    const loraNsfwSliderRow = document.getElementById('lora-nsfw-slider-row');
    if (loraNsfwToggle) {
        // === true pour que undefined = désactivé
        if (userSettings.loraNsfwEnabled === true) {
            loraNsfwToggle.classList.add('active');
            if (loraNsfwSliderRow) loraNsfwSliderRow.style.opacity = '1';
        } else {
            loraNsfwToggle.classList.remove('active');
            if (loraNsfwSliderRow) loraNsfwSliderRow.style.opacity = '0.4';
        }
    }
    if (loraNsfwSlider) {
        const nsfwLoraVal = Math.round((userSettings.loraNsfwStrength ?? 0.5) * 100);
        loraNsfwSlider.value = nsfwLoraVal;
        document.getElementById('settings-lora-nsfw-value').textContent = nsfwLoraVal + '%';
    }

    // LoRA Skin toggle & slider
    const loraSkinToggle = document.getElementById('toggle-lora-skin');
    const loraSkinSlider = document.getElementById('settings-lora-skin');
    const loraSkinSliderRow = document.getElementById('lora-skin-slider-row');
    if (loraSkinToggle) {
        // === true pour que undefined = désactivé
        if (userSettings.loraSkinEnabled === true) {
            loraSkinToggle.classList.add('active');
            if (loraSkinSliderRow) loraSkinSliderRow.style.opacity = '1';
        } else {
            loraSkinToggle.classList.remove('active');
            if (loraSkinSliderRow) loraSkinSliderRow.style.opacity = '0.4';
        }
    }
    if (loraSkinSlider) {
        const skinLoraVal = Math.round((userSettings.loraSkinStrength ?? 0.3) * 100);
        loraSkinSlider.value = skinLoraVal;
        document.getElementById('settings-lora-skin-value').textContent = skinLoraVal + '%';
    }

    // LoRA Breasts toggle & slider
    const loraBreastsToggle = document.getElementById('toggle-lora-breasts');
    const loraBreastsSlider = document.getElementById('settings-lora-breasts');
    const loraBreastsSliderRow = document.getElementById('lora-breasts-slider-row');
    if (loraBreastsToggle) {
        if (userSettings.loraBreastsEnabled === true) {
            loraBreastsToggle.classList.add('active');
            if (loraBreastsSliderRow) loraBreastsSliderRow.style.opacity = '1';
        } else {
            loraBreastsToggle.classList.remove('active');
            if (loraBreastsSliderRow) loraBreastsSliderRow.style.opacity = '0.4';
        }
    }
    if (loraBreastsSlider) {
        const breastsLoraVal = Math.round((userSettings.loraBreastsStrength ?? 0.7) * 100);
        loraBreastsSlider.value = breastsLoraVal;
        document.getElementById('settings-lora-breasts-value').textContent = breastsLoraVal + '%';
    }

    // LoRA labels per model
    updateLoraLabelsForModel();

    // Action bar toggle
    const actionBarToggle = document.getElementById('toggle-show-action-bar');
    if (actionBarToggle) {
        if (userSettings.showActionBar) {
            actionBarToggle.classList.add('active');
        } else {
            actionBarToggle.classList.remove('active');
        }
    }

    // Enhance prompt toggle
    const enhanceToggle = document.getElementById('toggle-enhance-prompt');
    if (enhanceToggle) {
        if (userSettings.enhancePrompt) {
            enhanceToggle.classList.add('active');
        } else {
            enhanceToggle.classList.remove('active');
        }
    }

    // Privacy toggle — reflects the runtime privacyMode (synced by ghost button + settings toggle)
    const privacyToggle = document.getElementById('toggle-privacy-default');
    if (privacyToggle) {
        privacyToggle.classList.toggle('active', Settings.get('privacyMode'));
    }

    // Segmentation settings - toujours clothes_auto (SegFormer B2)
    const segMethodSelect = document.getElementById('settings-segmentation-method');
    if (segMethodSelect) {
        segMethodSelect.value = 'clothes_auto';  // Seule option pour nudité
    }
    const segPromptInput = document.getElementById('settings-segmentation-prompt');
    if (segPromptInput) {
        segPromptInput.value = userSettings.segmentationPrompt || '';
    }

    // Video Model select
    const videoModelSelect = document.getElementById('settings-video-model');
    if (videoModelSelect) {
        videoModelSelect.value = userSettings.videoModel || 'svd';
    }
    const advancedVideoToggle = document.getElementById('toggle-show-advanced-video-models');
    if (advancedVideoToggle) {
        advancedVideoToggle.classList.toggle('active', !!userSettings.showAdvancedVideoModels);
    }

    // Video Quality select
    const videoQualitySelect = document.getElementById('settings-video-quality');
    if (videoQualitySelect) {
        videoQualitySelect.value = userSettings.videoQuality || '720p';
    }
    // Video Duration slider
    const videoDurSlider = document.getElementById('settings-video-duration');
    const videoDurValue = document.getElementById('settings-video-duration-value');
    if (videoDurSlider) {
        videoDurSlider.value = userSettings.videoDuration ?? 5;
        if (videoDurValue) videoDurValue.textContent = (userSettings.videoDuration ?? 5) + 's';
    }

    // FPS et Steps sont gérés par updateVideoQualityVisibility() (valeurs par modèle)
    updateVideoQualityVisibility();

    // Face Restore select
    const faceRestoreSelect = document.getElementById('settings-face-restore');
    if (faceRestoreSelect) {
        // Migration: ancien booléen → nouveau string
        const val = userSettings.faceRestore;
        if (val === true) faceRestoreSelect.value = 'codeformer';
        else if (val === false) faceRestoreSelect.value = 'off';
        else faceRestoreSelect.value = val || 'off';
    }

    // Video Audio toggle
    const videoAudioToggle = document.getElementById('toggle-video-audio');
    if (videoAudioToggle) {
        if (userSettings.videoAudio) {
            videoAudioToggle.classList.add('active');
        } else {
            videoAudioToggle.classList.remove('active');
        }
    }

    // Load Ollama status and models (utilisé aussi dans l'onglet Général)
    checkOllamaStatus();
    loadOllamaModels();

    // Check tunnel status
    checkTunnelStatus();

    // Export settings
    initExportSettings();
}

function switchSettingsTab(tabName, clickedEl) {
    if (tabName === 'jailbreak') tabName = 'promptLab';
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.settings-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    // If clickedEl not passed, find by index
    if (clickedEl) {
        clickedEl.classList.add('active');
    } else {
        const tabs = document.querySelectorAll('.settings-tab');
        const tabNames = ['general', 'profile', 'generation', 'memory', 'storage', 'promptLab', 'terminal', 'training'];
        const idx = tabNames.indexOf(tabName);
        if (idx >= 0 && tabs[idx]) tabs[idx].classList.add('active');
    }
    const panelId = tabName === 'promptLab' ? 'settings-prompt-lab' : `settings-${tabName}`;
    document.getElementById(panelId)?.classList.add('active');

    // Init specific tabs
    if (tabName === 'profile') {
        initProfileTab();
    } else if (tabName === 'memory') {
        initMemoryTab();
    } else if (tabName === 'terminal') {
        initTerminalTab();
    } else if (tabName === 'storage') {
        refreshGallery();
    } else if (tabName === 'training') {
        initTrainingTab();
    } else if (tabName === 'addons') {
        loadPackSettings();
    }
}

function updateMemoryRuntimeCopy() {
    const memoryInfo = document.getElementById('memory-info');
    if (memoryInfo) {
        memoryInfo.innerHTML = `${t('settings.memory.localCount', 'Faits mémorisés localement')}: <span id="memory-count">${userMemories.length}</span>`;
    }

    const chatsInfo = document.getElementById('chats-info');
    if (chatsInfo) {
        const conversationCount = typeof getConversationCount === 'function' ? getConversationCount() : 0;
        chatsInfo.innerHTML = `${t('settings.memory.chatsCount', 'Conversations locales sauvegardées')}: <span id="chats-count">${conversationCount}</span>`;
    }
}

function initMemoryTab() {
    updateMemoryRuntimeCopy();
}

function updateSettingsChatModel(value) {
    userSettings.chatModel = value;
    saveSettings();
}

function updateSettingsSteps(value) {
    userSettings.steps = parseInt(value);
    document.getElementById('settings-steps-value').textContent = value;
    document.getElementById('steps-slider').value = value;
    document.getElementById('steps-value').textContent = value;
    saveSettings();
}

// Segmentation gérée automatiquement par Smart Router côté backend

function updateSettingsStrength(value) {
    userSettings.strength = parseFloat(value);
    document.getElementById('settings-strength-value').textContent = Math.round(value * 100) + '%';
    document.getElementById('strength-slider').value = value;
    document.getElementById('strength-value').textContent = Math.round(value * 100) + '%';
    saveSettings();
}

async function clearAllData() {
    const confirmed = await JoyDialog.confirm(
        t('settings.reset.confirmClearAllLocal', 'Supprimer toutes les conversations et les faits mémorisés localement ?'),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    await clearConversationCache();
    await clearAllMemories();
    await JoyDialog.alert(t('settings.reset.dataCleared', 'Données effacées'));
}

// Toggle individual settings
function toggleSetting(settingName) {
    const toggle = document.getElementById(`toggle-${settingName.replace(/([A-Z])/g, '-$1').toLowerCase()}`);
    if (!toggle) return;

    if (toggle.classList.contains('disabled') || toggle.getAttribute('aria-disabled') === 'true') {
        Toast.info(
            t('settings.disabledControlTitle', 'Option indisponible'),
            toggle.title || t('settings.disabledControlBody', 'Cette option est verrouillée pour la configuration actuelle.'),
            2200
        );
        return;
    }

    userSettings[settingName] = !userSettings[settingName];

    if (userSettings[settingName]) {
        toggle.classList.add('active');
    } else {
        toggle.classList.remove('active');
    }

    saveSettings();
    applySettingsToUI();
}

// Mapping nom LoRA → clés settings
function _loraSettingKey(loraName) {
    const cap = loraName.charAt(0).toUpperCase() + loraName.slice(1);
    return { enabled: `lora${cap}Enabled`, strength: `lora${cap}Strength` };
}

// Toggle LoRA enable/disable
function toggleLora(loraName) {
    const adultOnlyLoras = new Set(['nsfw', 'skin', 'breasts']);
    if (adultOnlyLoras.has(loraName) && !isAdultSurfaceEnabled()) {
        Toast.info(t('settings.generation.advancedTitle', 'Extensions locales avancées'), getAdultFeatureReason(), 2200);
        return;
    }

    const toggle = document.getElementById(`toggle-lora-${loraName}`);
    const sliderRow = document.getElementById(`lora-${loraName}-slider-row`);
    if (!toggle) return;

    const { enabled: settingKey } = _loraSettingKey(loraName);
    const currentValue = userSettings[settingKey] === true;
    userSettings[settingKey] = !currentValue;

    if (userSettings[settingKey]) {
        toggle.classList.add('active');
        if (sliderRow) sliderRow.style.opacity = '1';
    } else {
        toggle.classList.remove('active');
        if (sliderRow) sliderRow.style.opacity = '0.4';
    }

    saveSettings();
    console.log(`[Settings] LoRA ${loraName} ${userSettings[settingKey] ? 'activé' : 'désactivé'}`);
}

// Update LoRA strength slider
function updateLoraSlider(loraName, value) {
    const { strength: strengthKey } = _loraSettingKey(loraName);
    const floatVal = parseInt(value) / 100;
    userSettings[strengthKey] = floatVal;

    const valueEl = document.getElementById(`settings-lora-${loraName}-value`);
    if (valueEl) valueEl.textContent = `${value}%`;

    saveSettings();
}

// Save a single setting
function saveSetting(settingName, value) {
    userSettings[settingName] = value;
    saveSettings();
}

async function loadProviderSettings(options = {}) {
    const container = document.getElementById('provider-settings-list');
    const note = document.getElementById('provider-settings-note');
    if (!container) return;

    container.innerHTML = `<div class="settings-info">${t('providers.loading', 'Chargement des providers...')}</div>`;

    const [result, mcpResult] = await Promise.all([
        apiSettings.getProviderStatus(),
        apiSettings.getMcpConfig({ loadTools: options.loadMcpTools === true }),
    ]);
    window.joyboyMcpSnapshot = mcpResult.ok ? (mcpResult.data || null) : null;

    if (!result.ok) {
        container.innerHTML = `<div class="settings-info">${t('providers.error', 'Erreur providers : {error}', { error: result.error || 'inconnue' })}</div>`;
        return;
    }

    const data = result.data || {};
    const providers = Array.isArray(data.providers) ? data.providers : [];
    if (note) {
        const activeSource = data.active_source || data.config_path || '~/.joyboy/config.json';
        const legacyHint = data.uses_legacy_path ? t('providers.legacyHint', ' (ancien chemin local détecté)') : '';
        note.textContent = t(
            'providers.note',
            'Clés stockées localement hors git. Priorité : {precedence}. Source active : {source}{legacyHint}',
            {
                precedence: data.precedence || 'process env > .env > local UI',
                source: activeSource,
                legacyHint,
            }
        );
    }

    if (!providers.length) {
        container.innerHTML = `<div class="settings-info">${t('providers.empty', 'Aucun provider configuré')}</div>`;
        return;
    }

    const assetProviders = providers.filter(provider => getProviderSettingsScope(provider) === 'assets');
    const llmProviders = providers.filter(provider => getProviderSettingsScope(provider) === 'llm');
    const groups = [
        renderProviderSettingsGroup(
            t('providers.assetsTitle', 'Téléchargement de modèles'),
            t('providers.assetsDesc', 'Clés utilisées pour récupérer des poids, repos privés et assets image/video.'),
            assetProviders
        ),
        renderProviderSettingsGroup(
            t('providers.llmTitle', 'LLM cloud / terminal'),
            t('providers.llmDesc', 'Clés utilisées par le harnais terminal pour appeler des modèles cloud sans consommer ta VRAM.'),
            llmProviders,
            renderTerminalModelProfilesSummary(data)
        ),
        renderMcpSettingsGroup(mcpResult.ok ? (mcpResult.data || {}) : null, mcpResult.ok ? '' : (mcpResult.error || mcpResult.data?.error || 'inconnue')),
    ].filter(Boolean);

    container.innerHTML = groups.join('') || `<div class="settings-info">${t('providers.empty', 'Aucun provider configuré')}</div>`;
    refreshSettingsActionChrome(container);
    updateMcpEditorVisibility();
}

function getAdultFeatureState() {
    const features = window.joyboyFeatureFlags || {};
    const adultExposure = (window.joyboyFeatureExposure && window.joyboyFeatureExposure.adult) || {};
    return {
        featureEnabled: features.adult_features_enabled !== false,
        visible: adultExposure.visible !== false,
        locked: adultExposure.locked === true,
        runtimeAvailable: adultExposure.runtime_available === true,
        reason: adultExposure.reason || '',
        packInstalled: adultExposure.pack_installed === true,
        activePackId: adultExposure.active_pack_id || null,
        publicRepoMode: adultExposure.public_repo_mode === true,
    };
}

function getInstalledPacks() {
    return Array.isArray(window.joyboyInstalledPacks) ? window.joyboyInstalledPacks : [];
}

let addonExplorerFilter = 'all';

function getPackById(packId) {
    return getInstalledPacks().find(pack => String(pack?.id || '') === String(packId || '')) || null;
}

function getFirstPackByKind(kind) {
    return getInstalledPacks().find(pack => String(pack?.kind || '') === String(kind || '')) || null;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderSettingsIconAction({ icon, label, tooltip = label, onClick, classes = '', disabled = false }) {
    const safeIcon = String(icon || 'circle').replace(/[^a-z0-9-]/gi, '');
    const safeLabel = escapeHtml(label || tooltip || '');
    const safeTooltip = escapeHtml(tooltip || label || '');
    const safeOnClick = escapeHtml(onClick || '');
    const safeClasses = escapeHtml(classes || '');
    const disabledAttr = disabled ? ' disabled aria-disabled="true"' : '';

    return `
        <button
            type="button"
            class="settings-action-btn compact icon-only ${safeClasses}"
            onclick="${safeOnClick}"
            aria-label="${safeLabel}"
            data-tooltip="${safeTooltip}"
            ${disabledAttr}
        >
            <i data-lucide="${safeIcon}" aria-hidden="true"></i>
            <span class="sr-only">${safeLabel}</span>
        </button>
    `;
}

function refreshSettingsActionChrome(root = document) {
    if (window.lucide) lucide.createIcons();
    window.JoyTooltip?.rescan?.(root);
}

function getPackKindLabel(kind) {
    const safeKind = String(kind || 'pack').toLowerCase();
    const key = `packs.kind${safeKind.charAt(0).toUpperCase()}${safeKind.slice(1)}`;
    return t(key, safeKind);
}

function getPackDisplayName(pack) {
    return String(pack?.name || pack?.id || 'Pack');
}

function getPackDisplayDescription(pack) {
    return String(pack?.description || '').trim();
}

function getPackSummaryMeta(pack, options = {}) {
    if (!pack) {
        return t('settings.addons.packSummaryMetaMissing', 'Gestion centralisée dans l’onglet Addons.');
    }

    const kind = getPackKindLabel(pack.kind || 'pack');
    const version = pack.version || '0.0.0';
    const capabilityCount = Array.isArray(pack.capabilities) ? pack.capabilities.length : 0;
    const params = { kind, version, count: capabilityCount };

    if (options.bridge) {
        return t(
            'settings.generation.packSummaryMetaBridge',
            '{kind} • bridge local privé • v{version}',
            params
        );
    }

    if (options.active) {
        return t(
            'settings.generation.packSummaryMetaActive',
            '{kind} • v{version} • {count} capacités locales',
            params
        );
    }

    return t(
        'settings.generation.packSummaryMetaInactive',
        '{kind} • v{version} • pack installé localement',
        params
    );
}

function spotlightSettingsSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;

    section.classList.remove('is-spotlighted');
    void section.offsetWidth;
    section.classList.add('is-spotlighted');
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.setTimeout(() => {
        section.classList.remove('is-spotlighted');
    }, 2200);
}

function getPackCapabilityLabel(capability) {
    const safeCapability = String(capability || '').trim();
    if (!safeCapability) return '';
    return t(`packs.capability_${safeCapability}`, safeCapability.replace(/_/g, ' '));
}

function renderPackCapabilityChips(capabilities = [], options = {}) {
    const chips = Array.isArray(capabilities) ? capabilities : [];
    const max = Number.isFinite(options.max) ? options.max : chips.length;
    return chips
        .slice(0, max)
        .map(capability => `<span class="settings-pack-chip">${escapeHtml(getPackCapabilityLabel(capability))}</span>`)
        .join('');
}

function renderAdultPackSummary(adultState = getAdultFeatureState()) {
    const card = document.getElementById('adult-pack-summary-card');
    const body = document.getElementById('adult-pack-summary-body');
    const chips = document.getElementById('adult-pack-summary-chips');
    const title = document.getElementById('adult-pack-summary-title');
    const meta = document.getElementById('adult-pack-summary-meta');
    const manageBtn = document.getElementById('adult-pack-summary-manage-btn');
    if (!card || !body || !chips) return;

    if (title) {
        setRuntimeText(title, 'settings.generation.packSummaryTitle', 'Pack local actif');
    }
    if (manageBtn) {
        setRuntimeText(manageBtn, 'settings.addons.packSummaryManage', 'Voir les addons');
    }

    const activePack = adultState.activePackId ? getPackById(adultState.activePackId) : null;
    const installedAdultPack = activePack || getFirstPackByKind('adult');

    let summaryKey = 'settings.generation.packSummaryMissing';
    let summaryFallback = 'Aucun pack local avancé actif. Active un pack pour enrichir le routeur, les prompts et l’interface locale.';
    let summaryParams = {};
    let chipMarkup = '';
    let plainSummary = '';

    if (activePack) {
        summaryKey = 'settings.generation.packSummaryActive';
        summaryFallback = '{name} étend le routage, les prompts, les sources modèles et l’interface locale.';
        summaryParams = { name: getPackDisplayName(activePack) };
        plainSummary = getPackDisplayDescription(activePack);
        if (title) setPlainText(title, getPackDisplayName(activePack));
        if (meta) setPlainText(meta, getPackSummaryMeta(activePack, { active: true }));
        chipMarkup = [
            `<span class="settings-pack-chip settings-pack-chip-state">${escapeHtml(t('packs.active', 'Actif localement'))}</span>`,
            `<span class="settings-pack-chip">${escapeHtml(getPackKindLabel(activePack.kind))}</span>`,
            `<span class="settings-pack-chip">v${escapeHtml(activePack.version || '0.0.0')}</span>`,
            renderPackCapabilityChips(activePack.capabilities, { max: 4 }),
        ].filter(Boolean).join('');
    } else if (adultState.publicRepoMode && adultState.packInstalled && !adultState.runtimeAvailable) {
        summaryKey = 'settings.generation.packSummaryInactive';
        summaryFallback = 'Un pack local avancé est installé mais inactif. Active-le dans Addons pour déverrouiller cette surface.';
        const installedDescription = getPackDisplayDescription(installedAdultPack);
        if (title) {
            setPlainText(title, installedAdultPack ? getPackDisplayName(installedAdultPack) : t('settings.generation.packSummaryTitle', 'Pack local actif'));
        }
        if (meta) {
            setPlainText(
                meta,
                installedAdultPack
                    ? getPackSummaryMeta(installedAdultPack, { active: false })
                    : t('settings.addons.packSummaryMetaMissing', 'Gestion centralisée dans l’onglet Addons.')
            );
        }
        if (installedDescription) {
            plainSummary = `${installedDescription} ${t('packs.activateToUse', 'Active-le dans Addons pour l’utiliser ici.')}`;
        }
        if (installedAdultPack) {
            chipMarkup = [
                `<span class="settings-pack-chip settings-pack-chip-state is-warning">${escapeHtml(t('packs.installed', 'Installé, non actif'))}</span>`,
                `<span class="settings-pack-chip">${escapeHtml(getPackKindLabel(installedAdultPack.kind))}</span>`,
                `<span class="settings-pack-chip">v${escapeHtml(installedAdultPack.version || '0.0.0')}</span>`,
                renderPackCapabilityChips(installedAdultPack.capabilities, { max: 4 }),
            ].filter(Boolean).join('');
        }
    } else if (!adultState.publicRepoMode && adultState.runtimeAvailable && !adultState.packInstalled) {
        summaryKey = 'settings.generation.packSummaryBridge';
        summaryFallback = 'Le bridge local privé continue d’alimenter cette surface tant que le mode public n’est pas activé.';
        if (title) setRuntimeText(title, 'packs.bridge', 'Bridge privé local');
        if (meta) setRuntimeText(meta, 'settings.generation.packSummaryMetaBridgeFallback', 'Bridge local privé disponible sur cette machine.');
        chipMarkup = `<span class="settings-pack-chip settings-pack-chip-state is-bridge">${escapeHtml(t('packs.bridge', 'Bridge privé local'))}</span>`;
    } else {
        if (title) setRuntimeText(title, 'settings.generation.packSummaryTitle', 'Pack local actif');
        if (meta) setRuntimeText(meta, 'settings.addons.packSummaryMetaMissing', 'Gestion centralisée dans l’onglet Addons.');
    }

    if (plainSummary) {
        setPlainText(body, plainSummary);
    } else {
        setRuntimeText(body, summaryKey, summaryFallback, summaryParams);
    }
    chips.innerHTML = chipMarkup;
}

function getAdultFeatureReason(adultState = getAdultFeatureState()) {
    if (!adultState.featureEnabled) {
        return t('settings.generation.notes.disabled', 'Désactivé : les routes spécialisées, le panneau local dédié et les surfaces optionnelles sont masqués localement.');
    }
    if (adultState.publicRepoMode && !adultState.packInstalled) {
        return t('settings.generation.notes.packMissing', 'Importe un pack local avancé pour déverrouiller ces outils sur cette machine.');
    }
    if (adultState.publicRepoMode && adultState.packInstalled && !adultState.runtimeAvailable) {
        return t('settings.generation.notes.packInactive', 'Un pack local avancé est installé. Active-le pour déverrouiller ces outils.');
    }
    if (adultState.activePackId) {
        const pack = getPackById(adultState.activePackId);
        return t('settings.generation.notes.packActive', 'Pack local avancé actif : {packId}', {
            packId: pack?.name || adultState.activePackId,
        });
    }
    if (!adultState.publicRepoMode) {
        return t('settings.generation.notes.bridge', 'Le bridge privé local reste disponible tant que le mode public n’est pas activé.');
    }
    return t('settings.generation.notes.enabled', 'Actif : le routeur spécialisé et les contrôles avancés restent disponibles uniquement sur cette machine.');
}

function getPublicCoreState() {
    const features = window.joyboyFeatureFlags || {};
    return {
        enabled: features.public_repo_mode === true,
        reason: features.public_repo_mode === true
            ? t('settings.general.publicModeEnabled', 'Actif : JoyBoy se comporte comme un core public, les extensions locales restent opt-in.')
            : t('settings.general.publicModeDisabled', 'Désactivé : le bridge privé local reste autorisé sur cette machine.')
    };
}

function getProviderSettingsScope(provider) {
    if (provider?.scope) return provider.scope;
    return String(provider?.key || '').includes('API_KEY') ? 'llm' : 'assets';
}

function renderProviderSettingsGroup(title, description, providers, extraHtml = '') {
    if (!providers.length && !extraHtml) return '';
    return `
        <div class="provider-settings-group">
            <div class="provider-settings-group-head">
                <div>
                    <div class="settings-label">${escapeHtml(title)}</div>
                    <div class="settings-label-desc">${escapeHtml(description)}</div>
                </div>
            </div>
            ${providers.length ? `<div class="provider-settings-grid">${providers.map(renderProviderSettingsRow).join('')}</div>` : ''}
            ${extraHtml || ''}
        </div>
    `;
}

function renderTerminalModelProfilesSummary(data) {
    const profiles = Array.isArray(data?.terminal_model_profiles) ? data.terminal_model_profiles : [];
    const cloudProfiles = profiles.filter(profile => profile.provider !== 'ollama' && profile.terminal_runtime);
    if (!cloudProfiles.length) return '';

    const configuredProfiles = cloudProfiles.filter(profile => profile.configured);
    const visibleProfiles = (configuredProfiles.length ? configuredProfiles : cloudProfiles).slice(0, 8);
    const statusText = configuredProfiles.length
        ? t('providers.cloudReady', '{count} profils cloud prêts pour le terminal', { count: configuredProfiles.length })
        : t('providers.cloudNeedsKey', 'Ajoute une clé pour activer les profils cloud terminal.');

    const pills = visibleProfiles.map(profile => {
        const modelId = String(profile.id || '');
        const modelIdArg = escapeHtml(JSON.stringify(modelId));
        const label = profile.configured
            ? t('providers.cloudProfileReady', 'prêt')
            : t('providers.cloudProfileLocked', 'clé manquante');
        const button = profile.configured ? `
            <button class="llm-profile-action" type="button" onclick="selectTerminalCloudModel(${modelIdArg})">
                ${escapeHtml(t('providers.useInTerminal', 'Terminal'))}
            </button>
        ` : '';
        return `
            <span class="llm-profile-pill ${profile.configured ? 'ready' : 'locked'}" title="${escapeHtml(modelId)}">
                <strong>${escapeHtml(profile.provider_label || profile.provider || '')}</strong>
                <span>${escapeHtml(profile.model || modelId)}</span>
                <em>${escapeHtml(label)}</em>
                ${button}
            </span>
        `;
    }).join('');

    return `
        <div class="llm-provider-summary">
            <div class="settings-label-desc">${escapeHtml(statusText)}</div>
            <div class="llm-profile-pills">${pills}</div>
        </div>
    `;
}

function applyFeatureFlagsToUI(features = {}, exposure = null, packs = null) {
    window.joyboyFeatureFlags = { ...(window.joyboyFeatureFlags || {}), ...features };
    if (exposure) window.joyboyFeatureExposure = exposure;
    if (packs) window.joyboyInstalledPacks = packs;
    const adultState = getAdultFeatureState();
    const adultEnabled = adultState.featureEnabled;

    const toggle = document.getElementById('toggle-adult-mode');
    if (toggle) toggle.classList.toggle('active', adultEnabled);

    const publicState = getPublicCoreState();
    const publicToggle = document.getElementById('toggle-public-repo-mode');
    if (publicToggle) publicToggle.classList.toggle('active', publicState.enabled);
    const publicNote = document.getElementById('public-repo-mode-note');
    if (publicNote) publicNote.textContent = publicState.reason;

    const note = document.getElementById('adult-mode-note');
    if (note) {
        note.textContent = getAdultFeatureReason(adultState);
    }
    renderAdultPackSummary(adultState);

    const nsfwTab = document.getElementById('settings-gen-tab-nsfw');
    const nsfwPanel = document.getElementById('gen-nsfw');
    const nsfwPanelContent = document.getElementById('gen-nsfw-content');
    const nsfwLockBanner = document.getElementById('gen-nsfw-locked-banner');
    const nsfwFilter = document.getElementById('models-image-filter-nsfw');
    const nsfwStrengthRow = document.getElementById('settings-nsfw-strength')?.closest('.settings-slider-row');
    const loraNsfwRow = document.getElementById('toggle-lora-nsfw')?.closest('.settings-row');
    const loraNsfwSliderRow = document.getElementById('lora-nsfw-slider-row');
    const loraSkinRow = document.getElementById('toggle-lora-skin')?.closest('.settings-row');
    const loraSkinSliderRow = document.getElementById('lora-skin-slider-row');
    const loraBreastsRow = document.getElementById('toggle-lora-breasts')?.closest('.settings-row');
    const loraBreastsSliderRow = document.getElementById('lora-breasts-slider-row');

    if (nsfwTab) {
        nsfwTab.style.display = adultState.visible ? '' : 'none';
        nsfwTab.classList.toggle('locked', adultState.locked);
        nsfwTab.title = adultState.locked ? getAdultFeatureReason(adultState) : '';
    }
    if (nsfwPanel) nsfwPanel.style.display = adultState.visible ? '' : 'none';
    if (nsfwFilter) nsfwFilter.style.display = adultState.visible ? '' : 'none';
    if (nsfwPanelContent) {
        nsfwPanelContent.style.opacity = adultState.runtimeAvailable ? '1' : '0.45';
        nsfwPanelContent.style.pointerEvents = adultState.runtimeAvailable ? 'auto' : 'none';
    }
    if (nsfwLockBanner) {
        nsfwLockBanner.style.display = adultState.locked ? '' : 'none';
        nsfwLockBanner.innerHTML = adultState.locked
            ? `<i data-lucide="lock"></i><span>${getAdultFeatureReason(adultState)}</span>`
            : '';
    }
    if (nsfwStrengthRow) nsfwStrengthRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraNsfwRow) loraNsfwRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraNsfwSliderRow) loraNsfwSliderRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraSkinRow) loraSkinRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraSkinSliderRow) loraSkinSliderRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraBreastsRow) loraBreastsRow.style.display = adultState.runtimeAvailable ? '' : 'none';
    if (loraBreastsSliderRow) loraBreastsSliderRow.style.display = adultState.runtimeAvailable ? '' : 'none';

    if (typeof window.applyJoyboyFeatureFlags === 'function') {
        window.applyJoyboyFeatureFlags(window.joyboyFeatureFlags);
    }
    if (window.lucide) lucide.createIcons();
}

async function loadFeatureFlags() {
    const result = await apiSettings.getFeatureFlags();
    if (!result.ok || !result.data?.success) {
        console.warn('[FEATURES] Failed to load feature flags:', result.error || result.data?.error);
        applyFeatureFlagsToUI(
            window.joyboyFeatureFlags || { adult_features_enabled: true },
            window.joyboyFeatureExposure || null,
            window.joyboyInstalledPacks || null
        );
        return window.joyboyFeatureFlags || { adult_features_enabled: true };
    }

    window.joyboyFeatureExposure = result.data.feature_exposure || {};
    window.joyboyInstalledPacks = result.data.packs || [];
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    applyFeatureFlagsToUI(
        result.data.features || {},
        window.joyboyFeatureExposure,
        window.joyboyInstalledPacks
    );
    return result.data.features || {};
}

async function toggleAdultMode() {
    const current = window.joyboyFeatureFlags?.adult_features_enabled !== false;
    const nextValue = !current;
    const result = await apiSettings.setFeatureFlag('adult_features_enabled', nextValue);

    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('settings.generation.advancedToggleError', 'Impossible de changer le mode local avancé'));
        return;
    }

    window.joyboyFeatureExposure = result.data.feature_exposure || window.joyboyFeatureExposure || {};
    window.joyboyInstalledPacks = result.data.packs || window.joyboyInstalledPacks || [];
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    applyFeatureFlagsToUI(
        result.data.features || {},
        window.joyboyFeatureExposure,
        window.joyboyInstalledPacks
    );
    Toast.info(
        t('settings.generation.advancedTitle', 'Extensions locales avancées'),
        nextValue
            ? getAdultFeatureReason({
                ...getAdultFeatureState(),
                featureEnabled: true,
            })
            : t('settings.generation.notes.disabled', 'Désactivé : les routes spécialisées, le panneau local dédié et les surfaces optionnelles sont masqués localement.'),
        2600
    );
}

async function togglePublicRepoMode() {
    const current = window.joyboyFeatureFlags?.public_repo_mode === true;
    const nextValue = !current;
    const result = await apiSettings.setFeatureFlag('public_repo_mode', nextValue);

    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('settings.general.publicModeToggleError', 'Impossible de changer le mode core public'));
        return;
    }

    window.joyboyFeatureExposure = result.data.feature_exposure || window.joyboyFeatureExposure || {};
    window.joyboyInstalledPacks = result.data.packs || window.joyboyInstalledPacks || [];
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    applyFeatureFlagsToUI(
        result.data.features || {},
        window.joyboyFeatureExposure,
        window.joyboyInstalledPacks
    );
    Toast.info(
        t('settings.general.coreTitle', 'Mode du core'),
        nextValue
            ? t('settings.general.publicModeEnabled', 'Actif : JoyBoy se comporte comme un core public, les extensions locales restent opt-in.')
            : t('settings.general.publicModeDisabled', 'Désactivé : le bridge privé local reste autorisé sur cette machine.'),
        2600
    );
}

async function loadPackSettings() {
    const container = document.getElementById('pack-settings-list');
    const note = document.getElementById('pack-settings-note');
    if (!container) return;

    container.innerHTML = `<div class="settings-info">${t('packs.loading', 'Chargement des packs locaux...')}</div>`;
    const result = await apiSettings.getPacksStatus();
    if (!result.ok || !result.data?.success) {
        container.innerHTML = `<div class="settings-info">${t('packs.error', 'Erreur packs : {error}', { error: result.data?.error || result.error || 'inconnue' })}</div>`;
        return;
    }

    const packs = Array.isArray(result.data.packs) ? result.data.packs : [];
    window.joyboyInstalledPacks = packs;
    window.joyboyFeatureExposure = result.data.feature_exposure || window.joyboyFeatureExposure || {};
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    if (note) {
        note.textContent = t('packs.note', 'Packs locaux dans {path}. Le core public reste neutre ; les packs étendent le comportement local.', {
            path: result.data.packs_dir,
        });
    }

    renderPackSettingsList(packs);
    applyFeatureFlagsToUI(window.joyboyFeatureFlags || {}, window.joyboyFeatureExposure, packs);
}

function setAddonFilter(filter, clickedEl) {
    addonExplorerFilter = String(filter || 'all');
    document.querySelectorAll('.addons-filter').forEach(button => {
        button.classList.toggle('active', button === clickedEl || button.dataset.addonFilter === addonExplorerFilter);
    });
    renderPackSettingsList();
}

function getAddonSearchQuery() {
    return String(document.getElementById('addons-search-input')?.value || '').trim().toLowerCase();
}

function getPackSearchHaystack(pack) {
    return [
        pack?.id,
        getPackDisplayName(pack),
        getPackDisplayDescription(pack),
        pack?.kind,
        pack?.version,
        ...(Array.isArray(pack?.capabilities) ? pack.capabilities : []),
    ].filter(Boolean).join(' ').toLowerCase();
}

function packMatchesAddonFilter(pack) {
    if (addonExplorerFilter === 'active') return pack?.active === true;
    if (addonExplorerFilter === 'installed') return pack?.valid !== false && pack?.active !== true;
    if (addonExplorerFilter === 'invalid') return pack?.valid === false || (Array.isArray(pack?.errors) && pack.errors.length > 0);
    return true;
}

function renderPackSettingsList(packs = getInstalledPacks()) {
    const container = document.getElementById('pack-settings-list');
    if (!container) return;

    const allPacks = Array.isArray(packs) ? packs : [];
    const query = getAddonSearchQuery();
    const visiblePacks = allPacks.filter(pack => {
        if (!packMatchesAddonFilter(pack)) return false;
        return !query || getPackSearchHaystack(pack).includes(query);
    });

    container.classList.toggle('is-empty', visiblePacks.length === 0);

    if (!allPacks.length) {
        container.innerHTML = `
            <div class="addons-empty-state">
                <i data-lucide="package-open" aria-hidden="true"></i>
                <div>
                    <strong>${escapeHtml(t('packs.emptyTitle', 'Aucun addon local'))}</strong>
                    <p>${escapeHtml(t('packs.empty', 'Aucun pack local détecté. Importe un zip, indique un dossier local, ou utilise `python scripts/bootstrap.py pack-install` sur une machine privée.'))}</p>
                </div>
            </div>
        `;
        refreshSettingsActionChrome(container);
        return;
    }

    if (!visiblePacks.length) {
        container.innerHTML = `
            <div class="addons-empty-state">
                <i data-lucide="search-x" aria-hidden="true"></i>
                <div>
                    <strong>${escapeHtml(t('packs.noResultsTitle', 'Aucun addon trouvé'))}</strong>
                    <p>${escapeHtml(t('packs.noResultsBody', 'Essaie un autre filtre ou une autre recherche.'))}</p>
                </div>
            </div>
        `;
        refreshSettingsActionChrome(container);
        return;
    }

    container.innerHTML = visiblePacks.map(renderPackRow).join('');
    refreshSettingsActionChrome(container);
}

function renderPackRow(pack) {
    const packIdArg = JSON.stringify(String(pack.id || ''));
    const packName = getPackDisplayName(pack);
    const errors = Array.isArray(pack.errors) && pack.errors.length
        ? `<div class="settings-label-desc status-error">${escapeHtml(pack.errors.join(' · '))}</div>`
        : '';
    const capabilities = Array.isArray(pack.capabilities) && pack.capabilities.length
        ? renderPackCapabilityChips(pack.capabilities, { max: 6 })
        : `<span class="settings-pack-chip">${escapeHtml(t('packs.noCapabilities', 'Aucune capacité déclarée'))}</span>`;
    const stateClass = pack.valid ? (pack.active ? 'status-ok' : 'status-warn') : 'status-error';
    const stateText = pack.valid
        ? (pack.active ? t('packs.active', 'Actif localement') : t('packs.installed', 'Installé, non actif'))
        : t('packs.invalid', 'Pack invalide');
    const translatedKind = getPackKindLabel(pack.kind || 'pack');
    const actionTooltip = pack.active
        ? t('packs.deactivateTooltip', 'Désactiver {name}', { name: packName })
        : t('packs.activateTooltip', 'Activer {name}', { name: packName });
    const iconName = pack.active ? 'sparkles' : (pack.valid ? 'blocks' : 'triangle-alert');
    const cardClass = pack.active ? 'is-active' : (pack.valid ? 'is-installed' : 'is-invalid');

    return `
        <div class="settings-card settings-pack-card addon-card ${cardClass}">
            <div class="addon-card-top">
                <div class="addon-icon" aria-hidden="true">
                    <i data-lucide="${iconName}"></i>
                </div>
                <div class="addon-card-title">
                    <div class="settings-label">${escapeHtml(packName)}</div>
                    <div class="settings-label-desc">${escapeHtml(pack.id)} · ${escapeHtml(translatedKind)} · v${escapeHtml(pack.version || '0.0.0')}</div>
                </div>
                <span class="addon-state ${stateClass}">${escapeHtml(stateText)}</span>
            </div>
            ${getPackDisplayDescription(pack) ? `<div class="addon-card-description">${escapeHtml(getPackDisplayDescription(pack))}</div>` : ''}
            <div class="settings-pack-chip-row">
                ${capabilities}
            </div>
            ${errors}
            <div class="addon-card-footer">
                <span>${escapeHtml(t('packs.localOnly', 'Local uniquement'))}</span>
                ${renderSettingsIconAction({
                    icon: pack.active ? 'power-off' : 'power',
                    label: actionTooltip,
                    tooltip: actionTooltip,
                    onClick: `togglePackActive(${packIdArg}, ${pack.active ? 'false' : 'true'})`,
                    classes: pack.active ? 'subtle' : '',
                    disabled: !pack.valid,
                })}
            </div>
        </div>
    `;
}

function openModelsPacksSettings() {
    openAddonsHub();
    setAddonsHubSection('library');
    window.setTimeout(() => {
        spotlightSettingsSection('addons-packs-section');
    }, 80);
}

function openAddonGuide() {
    openAddonsHub();
    setAddonsHubSection('help');
    window.setTimeout(() => {
        spotlightSettingsSection('help-addons-section');
    }, 80);
}

async function togglePackActive(packId, enabled) {
    const result = await apiSettings.setPackActive(packId, enabled);
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('packs.toggleError', 'Impossible de changer l’état du pack'));
        return;
    }
    window.joyboyInstalledPacks = result.data.packs || [];
    window.joyboyFeatureExposure = result.data.feature_exposure || window.joyboyFeatureExposure || {};
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    await loadPackSettings();
    applyFeatureFlagsToUI(window.joyboyFeatureFlags || {}, window.joyboyFeatureExposure, window.joyboyInstalledPacks);
    Toast.info(
        t('packs.toggledTitle', 'Pack local'),
        enabled ? t('packs.toggledEnabled', 'Pack activé localement') : t('packs.toggledDisabled', 'Pack désactivé localement'),
        2400
    );
}

async function importPackFromPath() {
    const input = document.getElementById('pack-source-path');
    const sourcePath = input?.value?.trim() || '';
    if (!sourcePath) {
        Toast.info(t('packs.importHintTitle', 'Pack local'), t('packs.importHintBody', 'Indique un dossier local ou importe une archive zip.'), 2500);
        return;
    }

    const result = await apiSettings.importPackFromPath(sourcePath);
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('packs.importError', 'Import impossible'));
        return;
    }

    if (input) input.value = '';
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    await loadPackSettings();
    Toast.success(t('packs.importedTitle', 'Pack importé'), t('packs.importedBody', '{name} installé localement', { name: result.data.pack?.name || 'Pack' }), 2600);
}

function triggerPackArchiveImport() {
    document.getElementById('pack-archive-input')?.click();
}

async function handlePackArchiveSelected(event) {
    const file = event?.target?.files?.[0];
    if (!file) return;
    const result = await apiSettings.importPackArchive(file);
    event.target.value = '';
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('packs.importError', 'Import impossible'));
        return;
    }
    window.joyboyPackUiOverrides = result.data.pack_ui_overrides || window.joyboyPackUiOverrides || {};
    await loadPackSettings();
    Toast.success(t('packs.importedTitle', 'Pack importé'), t('packs.importedBody', '{name} installé localement', { name: result.data.pack?.name || file.name }), 2600);
}

async function loadDoctorReport() {
    const output = document.getElementById('doctor-report-output');
    if (!output) return;

    output.innerHTML = `<div class="settings-info">${t('doctor.loading', 'Diagnostic en cours...')}</div>`;
    const result = await apiSettings.getDoctorReport();
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('doctor.error', 'Erreur doctor : {error}', { error: result.data?.error || result.error || 'inconnue' })}</div>`;
        return;
    }

    lastDoctorReport = result.data;
    renderDoctorReport(lastDoctorReport);
}

function renderDoctorReport(data) {
    const output = document.getElementById('doctor-report-output');
    if (!output || !data) return;

    const checksHtml = (data.checks || []).map(check => {
        const status = _normalizeDoctorStatus(check.status);
        const detail = _doctorCheckDetail(check, 'onboarding.summaryUnavailable', 'Résumé indisponible.');
        return `
            <div class="settings-label-desc">
                <strong>${escapeHtml(_doctorCheckLabel(check))}</strong>:
                <span class="status-${status === 'ok' ? 'ok' : (status === 'warning' ? 'warn' : 'error')}">${escapeHtml(detail)}</span>
            </div>
        `;
    }).join('');

    output.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px;">
            <div class="settings-row">
                <div>
                    <div class="settings-label">${t('doctor.title', 'Doctor {status}', { status: String(data.status || '').toUpperCase() })}</div>
                    <div class="settings-label-desc">${escapeHtml(_doctorSummaryText(data))}</div>
                </div>
                <div class="status-${data.status === 'ok' ? 'ok' : (data.status === 'warning' ? 'warn' : 'error')}" style="font-weight:700;">${data.ready ? t('doctor.ready', 'READY') : t('doctor.action', 'ACTION')}</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">${checksHtml}</div>
        </div>
    `;
}

async function resolveModelImportSource() {
    const input = document.getElementById('model-source-input');
    const targetSelect = document.getElementById('model-source-family');
    const output = document.getElementById('model-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) {
        return;
    }

    output.innerHTML = `<div class="settings-info">${t('settings.models.sourceAnalyzing', 'Analyse de la source...')}</div>`;
    const targetFamily = targetSelect?.value || 'generic';
    const resolved = await apiSettings.resolveModelSource(source, targetFamily);
    if (!resolved.ok || !resolved.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('settings.models.sourceError', 'Erreur : {error}', { error: resolved.data?.error || resolved.error || 'source invalide' })}</div>`;
        return;
    }

    const info = resolved.data.resolved;
    const targetLabel = getModelImportTargetLabel(targetFamily);
    const recommended = Array.isArray(info.recommended_resources) ? info.recommended_resources : [];
    const resourceUsageLabel = (usage) => {
        if (usage === 'positive') return t('settings.models.usagePositive', 'prompt positif');
        if (usage === 'negative') return t('settings.models.usageNegative', 'prompt négatif');
        return usage || '';
    };
    const recommendedHtml = recommended.length ? `
        <div class="settings-info" style="margin-top:10px;">
            <div class="settings-label">${escapeHtml(t('settings.models.recommendedResourcesTitle', 'Ressources recommandées détectées'))}</div>
            ${recommended.map(res => `
                <div class="settings-label-desc">
                    ${escapeHtml(res.type || 'Resource')} · ${escapeHtml(res.label || res.name || '')}
                    ${res.usage ? ` · ${escapeHtml(resourceUsageLabel(res.usage))}` : ''}
                </div>
            `).join('')}
            <label class="settings-label-desc" style="display:flex; gap:8px; align-items:center; margin-top:8px;">
                <input type="checkbox" id="model-source-include-recommended" checked>
                <span>${escapeHtml(t('settings.models.installRecommendedResources', 'Installer aussi ces ressources si elles sont compatibles'))}</span>
            </label>
        </div>
    ` : '';
    const quantHtml = renderModelImportQuantPolicy(info);
    output.innerHTML = `
        <div class="settings-label"><strong>${escapeHtml(info.display_name || source)}</strong></div>
        <div class="settings-label-desc">${escapeHtml(info.provider || '')} · ${escapeHtml(info.model_type || info.source_type || '')} · ${escapeHtml(info.base_model || '')} · ${escapeHtml(t('settings.models.targetLabel', 'cible {target}', { target: targetLabel }))}</div>
        ${info.file_name ? `<div class="settings-label-desc">${escapeHtml(info.file_name)} · ${escapeHtml(info.size_label || '')}</div>` : ''}
        ${quantHtml}
        ${info.trained_words?.length ? `<div class="settings-label-desc">${escapeHtml(t('settings.models.triggerWords', 'Mots trigger : {words}', { words: info.trained_words.join(', ') }))}</div>` : ''}
        <div class="settings-label-desc">${escapeHtml(info.requires_auth ? t('settings.models.authRequired', 'Provider clé détectée ou recommandée.') : t('settings.models.authPublic', 'Téléchargement possible sans auth pour les ressources publiques.'))}</div>
        ${info.warning ? `<div class="settings-label-desc status-warn">${escapeHtml(info.warning)}</div>` : ''}
        ${recommendedHtml}
        <div style="margin-top:10px;">
            <button class="settings-action-btn" onclick="startResolvedModelImport()">${t('settings.models.importLocalButton', 'Importer localement')}</button>
        </div>
    `;
}

let currentModelImportJobId = null;

function renderModelImportQuantPolicy(info = {}) {
    const policy = info.quant_policy || {};
    const sourcePrecision = String(policy.source_precision || info.source_precision || '').trim();
    const runtimeQuant = String(policy.runtime_quant || info.runtime_quant || '').trim();
    if (!sourcePrecision && !runtimeQuant) return '';

    const source = (sourcePrecision || 'checkpoint').toUpperCase();
    const runtime = (runtimeQuant && runtimeQuant !== 'none') ? runtimeQuant.toUpperCase() : t('settings.models.quantRuntimeNative', 'natif');
    const vram = Number(policy.vram_gb || 0);
    const key = runtimeQuant && runtimeQuant !== 'none'
        ? 'settings.models.quantPolicyRuntime'
        : 'settings.models.quantPolicyNative';
    const fallback = runtimeQuant && runtimeQuant !== 'none'
        ? 'Profil local : source {source}, exécution {runtime} au chargement.'
        : 'Profil local : source {source}, exécution native au chargement.';
    const label = t(key, fallback, {
        source,
        runtime,
        vram: vram ? vram.toFixed(1) : '?',
    });
    return `<div class="settings-label-desc status-ok">${escapeHtml(label)}</div>`;
}

async function startResolvedModelImport() {
    const input = document.getElementById('model-source-input');
    const targetSelect = document.getElementById('model-source-family');
    const output = document.getElementById('model-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) return;

    const includeRecommended = document.getElementById('model-source-include-recommended')?.checked !== false;
    const result = await apiSettings.startModelImport(source, targetSelect?.value || 'image', includeRecommended);
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('settings.models.sourceError', 'Erreur : {error}', { error: result.data?.error || result.error || 'import impossible' })}</div>`;
        return;
    }

    currentModelImportJobId = result.data.job?.job_id || null;
    output.innerHTML = `<div class="settings-info">${t('settings.models.importStarted', 'Import lancé...')}</div>`;
    if (currentModelImportJobId) {
        pollModelImportStatus(currentModelImportJobId);
    }
}

async function pollModelImportStatus(jobId) {
    const output = document.getElementById('model-source-output');
    if (!output || !jobId) return;

    const poll = async () => {
        const result = await apiSettings.getModelImportStatus(jobId);
        const job = result.data?.job;
        if (!result.ok || !job) {
            output.innerHTML = `<div class="settings-info">${t('settings.models.importMissing', 'Import introuvable')}</div>`;
            return;
        }

        const downloadedMB = Math.round((job.downloaded_bytes || 0) / (1024 * 1024));
        const totalMB = Math.round((job.total_bytes || 0) / (1024 * 1024));
        const sizeChunk = totalMB ? ` · ${downloadedMB} MB / ${totalMB} MB` : '';
        const quantHtml = renderModelImportQuantPolicy(job.resolved || {});
        output.innerHTML = `
            <div class="settings-label"><strong>${job.resolved?.display_name || t('settings.models.importModelTitle', 'Import modèle')}</strong></div>
            <div class="settings-label-desc">${job.message || t('settings.models.importInProgress', 'Import en cours')}</div>
            <div class="settings-label-desc">${t('settings.models.importProgress', 'Progression : {progress}%{size}', { progress: job.progress || 0, size: sizeChunk })}</div>
            ${quantHtml}
            ${job.target_path ? `<div class="settings-label-desc">${t('settings.models.destination', 'Destination : {path}', { path: job.target_path })}</div>` : ''}
            ${job.error ? `<div class="settings-label-desc status-error">${job.error}</div>` : ''}
        `;

        if (job.status === 'completed') {
            Toast.success(t('settings.models.importedTitle', 'Modèle importé'), t('settings.models.importedBody', 'Import provider terminé'), 2600);
            if (typeof loadFeatureFlags === 'function') {
                loadFeatureFlags().then(() => {
                    if (typeof renderModelPickerList === 'function') {
                        renderModelPickerList('home');
                        renderModelPickerList('chat');
                    }
                }).catch(() => {});
            }
            if (typeof checkModelsStatus === 'function') checkModelsStatus();
            return;
        }
        if (job.status === 'error') {
            Toast.error(t('settings.models.importErrorTitle', 'Erreur import'), job.error || t('settings.models.importErrorBody', 'Échec import provider'));
            return;
        }
        setTimeout(poll, 1500);
    };

    await poll();
}

async function runHarnessAudit() {
    const output = document.getElementById('harness-audit-output');
    if (!output) return;

    output.innerHTML = `<div class="settings-info">${t('audit.loading', 'Audit en cours...')}</div>`;

    const result = await apiSettings.getHarnessAudit();
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('audit.error', 'Erreur audit : {error}', { error: result.data?.error || result.error || 'inconnue' })}</div>`;
        return;
    }

    lastHarnessAudit = result.data;
    renderHarnessAudit(lastHarnessAudit);
}

function renderHarnessAudit(audit) {
    const output = document.getElementById('harness-audit-output');
    if (!output || !audit) return;

    const sectionLabels = {
        install: 'Install',
        secrets: 'Secrets',
        ux: 'UX',
        release: 'Release'
    };
    const scoreClass = audit.score >= 80 ? 'status-ok' : 'status-warn';
    const sections = Object.entries(audit.sections || {}).map(([key, value]) => (
        `<div class="settings-label-desc"><strong>${sectionLabels[key] || key}</strong>: ${value}/100</div>`
    )).join('');
    const actions = (audit.top_actions || []).length
        ? `<ul style="margin: 8px 0 0 18px;">${audit.top_actions.map(action => `<li>${action}</li>`).join('')}</ul>`
        : `<div class="settings-label-desc">${t('audit.noBlocking', 'Aucune priorité bloquante détectée.')}</div>`;
    const highlights = (audit.checks || [])
        .filter(check => check.status !== 'pass')
        .slice(0, 3)
        .map(check => `<li><strong>${check.label}</strong>: ${check.detail}</li>`)
        .join('');

    output.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 10px;">
            <div class="settings-row">
                <div>
                    <div class="settings-label">Score ${audit.score}/100 (${audit.grade})</div>
                    <div class="settings-label-desc">${audit.summary}</div>
                </div>
                <div class="${scoreClass}" style="font-weight: 700;">${audit.grade}</div>
            </div>
            <div>${sections}</div>
            <div>
                <div class="settings-label">${t('audit.priorities', 'Priorités')}</div>
                ${actions}
            </div>
            ${highlights ? `
                <div>
                    <div class="settings-label">${t('audit.watch', 'Points à surveiller')}</div>
                    <ul style="margin: 8px 0 0 18px;">${highlights}</ul>
                </div>
            ` : ''}
        </div>
    `;
}

function isAdultSurfaceEnabled() {
    return getAdultFeatureState().runtimeAvailable;
}

function isAdultImageSurfaceModel(model) {
    if (!model) return false;
    const name = (model.name || '').toLowerCase();
    const desc = (model.desc || '').toLowerCase();
    return model.adult === true
        || name.includes('lustify')
        || name.includes('juggernaut')
        || name.includes('flux kontext nsfw')
        || desc.includes('nsfw');
}

// ===== LORA LABELS PER MODEL =====
// Met à jour les labels LoRA selon le modèle inpaint sélectionné
function updateLoraLabelsForModel() {
    // Utiliser le modèle effectivement sélectionné (variable globale ui.js), pas le setting sauvegardé
    const model = (typeof selectedInpaintModel !== 'undefined' ? selectedInpaintModel : null)
        || Settings.get('selectedInpaintModel') || '';
    const isFlux = model.toLowerCase().includes('flux');

    const nsfwLabel = document.getElementById('lora-nsfw-label');
    const nsfwDesc = document.getElementById('lora-nsfw-desc');
    const nsfwSliderLabel = document.getElementById('lora-nsfw-slider-label');
    const skinLabel = document.getElementById('lora-skin-label');
    const skinDesc = document.getElementById('lora-skin-desc');
    const skinSliderLabel = document.getElementById('lora-skin-slider-label');

    const breastsLabel = document.getElementById('lora-breasts-label');
    const breastsDesc = document.getElementById('lora-breasts-desc');
    const breastsSliderLabel = document.getElementById('lora-breasts-slider-label');

    if (isFlux) {
        if (nsfwLabel) nsfwLabel.textContent = 'LoRA Local Unlock';
        if (nsfwDesc) nsfwDesc.textContent = t('settings.localAdvanced.fluxUnlockDesc', 'Étend les capacités locales avancées pour Flux');
        if (nsfwSliderLabel) nsfwSliderLabel.textContent = t('settings.localAdvanced.fluxUnlockForce', 'Force LoRA Local Unlock');
        if (skinLabel) skinLabel.textContent = 'LoRA Apparel Shift';
        if (skinDesc) skinDesc.textContent = t('settings.localAdvanced.fluxApparelDesc', 'Ajuste finement les couches de vêtements via Flux');
        if (skinSliderLabel) skinSliderLabel.textContent = t('settings.localAdvanced.fluxApparelForce', 'Force LoRA Apparel');
        if (breastsLabel) breastsLabel.textContent = 'LoRA Detail Enhancer';
        if (breastsDesc) breastsDesc.textContent = t('settings.localAdvanced.fluxDetailDesc', 'Renforce les détails fins et le micro-contraste pour Flux');
        if (breastsSliderLabel) breastsSliderLabel.textContent = t('settings.localAdvanced.fluxDetailForce', 'Force LoRA Detail');
    } else {
        if (nsfwLabel) nsfwLabel.textContent = 'LoRA Local XL';
        if (nsfwDesc) nsfwDesc.textContent = t('settings.localAdvanced.xlLocalDesc', 'Améliore le réalisme des workflows locaux avancés');
        if (nsfwSliderLabel) nsfwSliderLabel.textContent = t('settings.localAdvanced.xlLocalForce', 'Force LoRA Local');
        if (skinLabel) skinLabel.textContent = 'LoRA Skin Realism';
        if (skinDesc) skinDesc.textContent = t('settings.localAdvanced.skinDesc', 'Texture de peau réaliste avec imperfections');
        if (skinSliderLabel) skinSliderLabel.textContent = t('settings.localAdvanced.skinForce', 'Force LoRA Skin');
        if (breastsLabel) breastsLabel.textContent = 'LoRA Anatomy Detail';
        if (breastsDesc) breastsDesc.textContent = t('settings.localAdvanced.anatomyDesc', 'Détails anatomiques réalistes, sans artefacts');
        if (breastsSliderLabel) breastsSliderLabel.textContent = t('settings.localAdvanced.anatomyForce', 'Force LoRA Anatomy');
    }
}

// Update setting slider value
function updateSettingSlider(settingName, value) {
    const valueEl = document.getElementById(`settings-${settingName}-value`);

    if (settingName === 'steps') {
        userSettings.steps = parseInt(value);
        if (valueEl) valueEl.textContent = value;
        document.getElementById('steps-slider').value = value;
        document.getElementById('steps-value').textContent = value;
    } else if (settingName === 'text2imgSteps') {
        userSettings.text2imgSteps = parseInt(value);
        const text2imgValueEl = document.getElementById('settings-text2img-steps-value');
        if (text2imgValueEl) text2imgValueEl.textContent = value;
    } else if (settingName === 'text2imgGuidance') {
        userSettings.text2imgGuidance = parseFloat(value);
        const guidanceEl = document.getElementById('settings-text2img-guidance-value');
        if (guidanceEl) guidanceEl.textContent = value;
    } else if (settingName === 'faceRefScale') {
        userSettings.faceRefScale = parseFloat(value);
        const faceRefEl = document.getElementById('settings-face-ref-scale-value');
        if (faceRefEl) faceRefEl.textContent = value;
    } else if (settingName === 'styleRefScale') {
        userSettings.styleRefScale = parseFloat(value);
        const styleRefEl = document.getElementById('settings-style-ref-scale-value');
        if (styleRefEl) styleRefEl.textContent = value;
    } else if (settingName === 'nsfwStrength') {
        const floatVal = parseInt(value) / 100;
        userSettings.nsfwStrength = floatVal;
        const nsfwValueEl = document.getElementById('settings-nsfw-strength-value');
        if (nsfwValueEl) nsfwValueEl.textContent = Math.round(floatVal * 100) + '%';
    } else if (settingName === 'dilation') {
        userSettings.dilation = parseInt(value);
        if (valueEl) valueEl.textContent = value;
        document.getElementById('dilation-slider').value = value;
        document.getElementById('dilation-value').textContent = value + 'px';
    } else if (settingName === 'videoDuration') {
        userSettings.videoDuration = parseInt(value);
        const durEl = document.getElementById('settings-video-duration-value');
        if (durEl) {
            const currentVideoModel = userSettings.videoModel || 'svd';
            if (currentVideoModel === 'framepack-fast') {
                durEl.textContent = t('settings.generation.videoFramepackFastDuration', '5s rapide · 60 frames');
            } else if (currentVideoModel === 'framepack') {
                durEl.textContent = userSettings.videoDuration >= 8
                    ? t('settings.generation.videoFramepackLongDuration', '10s · 180 frames')
                    : t('settings.generation.videoFramepackNormalDuration', '5s · 90 frames');
            } else {
                durEl.textContent = value + 's';
            }
        }
        if ((userSettings.videoModel || 'svd').startsWith('framepack') && typeof updateVideoQualityVisibility === 'function') {
            updateVideoQualityVisibility();
        }
    } else if (settingName === 'videoFps') {
        userSettings.videoFps = parseInt(value);
        const fpsEl = document.getElementById('settings-video-fps-value');
        if (fpsEl) fpsEl.textContent = value;
    } else if (settingName === 'videoSteps') {
        userSettings.videoSteps = parseInt(value);
        const stepsEl = document.getElementById('settings-video-steps-value');
        if (stepsEl) stepsEl.textContent = value;
    } else if (settingName === 'videoRefine') {
        userSettings.videoRefine = parseInt(value);
        const refineEl = document.getElementById('settings-video-refine-value');
        if (refineEl) refineEl.textContent = value;
    } else if (settingName === 'poseStrength') {
        userSettings.poseStrength = parseFloat(value);
        const poseStrEl = document.getElementById('settings-pose-strength-value');
        if (poseStrEl) poseStrEl.textContent = value;
    }

    saveSettings();
}

// ControlNet Depth scale (0-100 slider → 0.00-1.00 float)
function updateControlnetDepth(value) {
    const intVal = parseInt(value);
    const el = document.getElementById('settings-controlnet-depth-value');
    if (intVal === 0) {
        userSettings.controlnetDepth = null;
        if (el) el.textContent = 'Auto';
    } else {
        const floatVal = intVal / 100;
        userSettings.controlnetDepth = floatVal;
        if (el) el.textContent = floatVal.toFixed(2);
    }
}

// Composite Blur Radius (0=Auto, 1-64px)
function updateCompositeRadius(value) {
    const intVal = parseInt(value);
    const el = document.getElementById('settings-composite-radius-value');
    if (intVal === 0) {
        userSettings.compositeRadius = null;
        if (el) el.textContent = 'Auto';
    } else {
        userSettings.compositeRadius = intVal;
        if (el) el.textContent = intVal + 'px';
    }
}

// Confirm clear memory
async function confirmClearMemory() {
    const confirmed = await JoyDialog.confirm(
        t('settings.memory.confirmClear', 'Voulez-vous vraiment supprimer tous les faits mémorisés localement ?'),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    await clearAllMemories();
    initMemoryTab();
    await JoyDialog.alert(t('settings.memory.cleared', 'Mémoire locale effacée'));
}

// Reset complet - efface TOUT et repart à zéro
async function confirmFullReset() {
    const confirmed = await JoyDialog.confirm(
        t(
            'settings.reset.fullConfirm',
            'ATTENTION : cette action va tout effacer :\n\n' +
            '- Toutes les conversations\n' +
            '- Tous les faits mémorisés localement\n' +
            '- Tous les paramètres\n' +
            '- Le profil utilisateur\n' +
            '- Le cache local\n\n' +
            'Tu devras refaire le setup initial.\n\n' +
            'Continuer ?'
        ),
        { variant: 'danger' }
    );

    if (!confirmed) return;

    // Double confirmation
    const doubleConfirm = await JoyDialog.confirm(
        t('settings.reset.fullDoubleConfirm', 'Dernière chance : es-tu vraiment sûr de vouloir tout effacer ?'),
        { variant: 'danger' }
    );
    if (!doubleConfirm) return;

    console.log('[RESET] Reset complet en cours...');

    try {
        // 1. Vider IndexedDB (conversations, mémoires, settings)
        if (typeof clearCacheDB === 'function') {
            await clearCacheDB();
            console.log('[RESET] IndexedDB vidée');
        }

        // 2. Vider localStorage
        localStorage.clear();
        console.log('[RESET] localStorage vidé');

        // 3. Vider sessionStorage
        sessionStorage.clear();
        console.log('[RESET] sessionStorage vidé');

        // 4. Supprimer les cookies du domaine (si existants)
        document.cookie.split(";").forEach(c => {
            document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
        });
        console.log('[RESET] Cookies supprimés');

        // 5. Réinitialiser aussi l'onboarding backend/local config hors navigateur.
        // Sinon l'app peut rester cachée après un reset navigateur complet.
        try {
            sessionStorage.setItem('forceOnboardingAfterReset', '1');
            await apiSettings.resetOnboarding();
            console.log('[RESET] onboarding backend réinitialisé');
        } catch (error) {
            console.warn('[RESET] Reset onboarding backend impossible:', error);
        }

        await JoyDialog.alert(t('settings.reset.fullDone', 'Reset complet terminé. La page va se recharger.'));

        // 6. Recharger la page (va redéclencher l'onboarding)
        window.location.reload();

    } catch (err) {
        console.error('[RESET] Erreur:', err);
        await JoyDialog.alert(t('settings.reset.fullError', 'Erreur pendant le reset : {error}', { error: err.message }), { variant: 'danger' });
    }
}

// Confirm clear all chats
async function confirmClearChats() {
    const confirmed = await JoyDialog.confirm(
        t('settings.memory.confirmClearChats', 'Voulez-vous vraiment supprimer toutes les conversations locales ?'),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    await clearCacheDB();
    initMemoryTab();
    showHome();
    await JoyDialog.alert(t('settings.memory.clearedChats', 'Conversations locales supprimées'));
}

// Check models status - séparer installés et disponibles

async function checkOllamaStatus() {
    const result = await apiOllama.getStatus();
    const data = result.data || { installed: false, running: false };

    const statusEl = DOM.get('ollama-status');
    if (!statusEl) return data;

    if (data.installed && data.running) {
        DOM.setHtml(statusEl, `<span class="status-ok">${escapeHtml(t('settings.models.ollamaActive', 'Ollama actif'))}</span>`);
    } else if (data.installed) {
        DOM.setHtml(statusEl, `<span class="status-warn">${escapeHtml(t('settings.models.ollamaStopped', 'Ollama installé mais non démarré'))}</span>`);
    } else {
        DOM.setHtml(statusEl, `<span class="status-error">${escapeHtml(t('settings.models.ollamaMissing', 'Ollama non installé'))}</span> <a href="https://ollama.ai/download" target="_blank">${escapeHtml(t('settings.models.download', 'Télécharger'))}</a>`);
    }

    return data;
}

function settingsIsCloudTextModel(modelId) {
    const raw = String(modelId || '').trim();
    if (!raw) return false;
    if (typeof isTerminalCloudModelId === 'function') {
        return isTerminalCloudModelId(raw);
    }
    const providerId = raw.includes(':') ? raw.split(':', 1)[0].toLowerCase() : '';
    return ['openai', 'openrouter', 'anthropic', 'gemini', 'deepseek', 'moonshot', 'novita', 'minimax', 'volcengine', 'glm', 'vllm'].includes(providerId);
}

function settingsFormatTextModelName(modelId) {
    return typeof _formatModelName === 'function' ? _formatModelName(modelId) : modelId;
}

function settingsRenderCloudChatOption(selectEl, modelId) {
    if (!selectEl || !modelId) return;
    const label = settingsFormatTextModelName(modelId);
    selectEl.innerHTML = `<option value="${escapeHtml(modelId)}">${escapeHtml(label)}</option>`;
    selectEl.value = modelId;
}

async function loadOllamaModels() {
    const listEl = DOM.get('ollama-installed-models');
    const selectEl = DOM.get('settings-chat-model');
    if (!listEl) return;

    DOM.setHtml(listEl, `<div class="settings-info">${escapeHtml(t('common.loading', 'Chargement...'))}</div>`);

    const result = await apiOllama.getModels();
    if (!result.ok) {
        DOM.setHtml(listEl, `<div class="settings-info">${escapeHtml(t('settings.models.connectionError', 'Erreur de connexion'))}</div>`);
        return;
    }

    const data = result.data;
    try {
        const activeChatModel = userSettings.chatModel;
        const activeChatIsCloud = settingsIsCloudTextModel(activeChatModel);

        if (data.models && data.models.length > 0) {
            listEl.innerHTML = data.models.map(model => {
                const isEquipped = !activeChatIsCloud && model.name === activeChatModel;
                const displayName = typeof _formatModelName === 'function' ? _formatModelName(model.name) : model.name;
                return `
                <div class="ollama-model-item ${isEquipped ? 'equipped' : ''}">
                    <div class="model-info">
                        <div class="model-name-row">
                            <span class="model-name">${displayName}</span>
                            ${isEquipped ? `<span class="uncensored-badge" style="background: rgba(59,130,246,0.15); color: #3b82f6;">${escapeHtml(t('settings.models.activeBadge', 'ACTIF'))}</span>` : ''}
                        </div>
                        <span class="model-size">${model.size}</span>
                    </div>
                    <div class="model-actions">
                        <button class="btn-equip ${isEquipped ? 'equipped' : ''}" onclick="equipModel('${model.name}')">
                            ${isEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equipped', 'Équipé'))}` : escapeHtml(t('settings.models.equip', 'Équiper'))}
                        </button>
                        <button class="btn-delete-model" onclick="deleteOllamaModel('${model.name}')">${escapeHtml(t('common.delete', 'Supprimer'))}</button>
                    </div>
                </div>
            `}).join('');
            if (window.lucide) lucide.createIcons();

            // Update chat model select
            if (selectEl) {
                const localOptions = data.models.map(model => {
                    const dn = typeof _formatModelName === 'function' ? _formatModelName(model.name) : model.name;
                    return `<option value="${escapeHtml(model.name)}">${escapeHtml(dn)}</option>`;
                }).join('');
                const cloudOption = activeChatIsCloud
                    ? `<option value="${escapeHtml(activeChatModel)}">${escapeHtml(settingsFormatTextModelName(activeChatModel))}</option>`
                    : '';
                selectEl.innerHTML = `${cloudOption}${localOptions}`;

                // Vérifier si le modèle sélectionné existe toujours
                const modelExists = data.models.some(m => m.name === activeChatModel);
                if (!modelExists && !activeChatIsCloud) {
                    userSettings.chatModel = data.models[0].name;
                    saveSettings();
                }
                selectEl.value = userSettings.chatModel;

                // Synchroniser avec le picker
                if (typeof selectedChatModel !== 'undefined') {
                    selectedChatModel = userSettings.chatModel;
                }
                if (typeof updateModelPickerDisplay === 'function') {
                    updateModelPickerDisplay();
                }
            }
        } else {
            listEl.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.models.noInstalledInstallBelow', 'Aucun modèle sur la machine. Choisis-en un dans Disponibles.'))}</div>`;

            // Mettre à jour le select pour indiquer qu'il n'y a pas de modèle
            if (selectEl) {
                if (activeChatIsCloud) {
                    settingsRenderCloudChatOption(selectEl, activeChatModel);
                } else {
                    selectEl.innerHTML = `<option value="">${escapeHtml(t('settings.models.noModels', 'Aucun modèle'))}</option>`;
                    userSettings.chatModel = '';
                    saveSettings();
                }
            }
        }
    } catch (e) {
        DOM.setHtml(listEl, `<div class="settings-info">${escapeHtml(t('settings.models.genericError', 'Erreur : {error}', { error: e.message || '' }))}</div>`);
    }
}

// Filtres multiples pour les modèles
let activeModelFilters = new Set();

function toggleModelFilter(filter) {
    const chip = document.querySelector(`.filter-chip[data-filter="${filter}"]`);

    if (filter === 'all') {
        // "Tous" désélectionne les autres
        activeModelFilters.clear();
        document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        chip?.classList.add('active');
    } else {
        // Désélectionner "Tous" si on clique sur un autre filtre
        document.querySelector('.filter-chip[data-filter="all"]')?.classList.remove('active');

        if (activeModelFilters.has(filter)) {
            activeModelFilters.delete(filter);
            chip?.classList.remove('active');
        } else {
            activeModelFilters.add(filter);
            chip?.classList.add('active');
        }

        // Si aucun filtre actif, réactiver "Tous"
        if (activeModelFilters.size === 0) {
            document.querySelector('.filter-chip[data-filter="all"]')?.classList.add('active');
        }
    }

    searchOllamaModels();
}

async function searchOllamaModels() {
    const query = DOM.getValue('ollama-search-input') || '';
    const resultsEl = DOM.get('ollama-search-results');
    if (!resultsEl) return;

    DOM.setHtml(resultsEl, `<div class="settings-info">${escapeHtml(t('settings.models.searching', 'Recherche...'))}</div>`);

    const result = await apiOllama.search(query);
    if (!result.ok) {
        DOM.setHtml(resultsEl, `<div class="settings-info">${escapeHtml(t('settings.models.searchError', 'Erreur de recherche'))}</div>`);
        return;
    }

    const data = result.data;
    try {

        if (data.models && data.models.length > 0) {
            // Appliquer les filtres multiples
            let filtered = data.models;

            if (activeModelFilters.size > 0) {
                filtered = filtered.filter(m => {
                    // Le modèle doit correspondre à TOUS les filtres actifs
                    for (const filter of activeModelFilters) {
                        if (filter === 'vision' && !m.vision) return false;
                        if (filter === 'uncensored' && !m.uncensored) return false;
                        if (filter === 'fast' && !m.fast) return false;
                        if (filter === 'powerful' && !m.powerful) return false;
                    }
                    return true;
                });
            }

            if (filtered.length === 0) {
                resultsEl.innerHTML = `<div class="settings-info">${t('settings.models.noFilteredResults', 'Aucun modèle avec ces filtres')}</div>`;
                return;
            }

            resultsEl.innerHTML = filtered.map(model => {
                const badges = [];
                if (model.vision) badges.push('<span class="model-badge vision"><i data-lucide="eye" style="width:12px;height:12px;"></i> VISION</span>');
                if (model.uncensored) badges.push('<span class="uncensored-badge">OPEN</span>');
                if (model.fast) badges.push(`<span class="model-badge fast">${t('settings.models.fastBadge', 'RAPIDE')}</span>`);
                if (model.powerful) badges.push(`<span class="model-badge powerful">${t('settings.models.powerfulBadge', 'PUISSANT')}</span>`);

                return `
                <div class="ollama-model-item search-result ${model.uncensored ? 'uncensored' : ''} ${model.vision ? 'vision-model' : ''}">
                    <div class="model-info">
                        <div class="model-name-row">
                            <span class="model-name">${model.name}</span>
                            ${badges.join('')}
                        </div>
                        <span class="model-desc">${model.desc}</span>
                        <span class="model-size">${model.size}</span>
                    </div>
                    <button class="btn-install-model" onclick="pullOllamaModel('${model.name}')">${escapeHtml(t('settings.models.installAction', 'Télécharger'))}</button>
                </div>
            `}).join('');
        } else {
            DOM.setHtml(resultsEl, `<div class="settings-info">${escapeHtml(t('settings.models.noResults', 'Aucun résultat'))}</div>`);
        }
    } catch (e) {
        DOM.setHtml(resultsEl, `<div class="settings-info">${escapeHtml(t('settings.models.searchError', 'Erreur de recherche'))}</div>`);
    }
}

async function pullOllamaModel(modelName) {
    const btn = event?.target;
    const modelItem = btn?.closest('.ollama-model-item');

    // Track download
    activeDownloads[modelName] = { progress: 0, status: 'starting' };

    if (btn) {
        btn.disabled = true;
        btn.textContent = t('settings.models.downloading', 'Téléchargement...');
    }

    // Add progress bar to the model item
    if (modelItem) {
        modelItem.classList.add('downloading');
        let progressDiv = modelItem.querySelector('.download-progress');
        if (!progressDiv) {
            progressDiv = document.createElement('div');
            progressDiv.className = 'download-progress';
            progressDiv.innerHTML = `
                <div class="download-status">${escapeHtml(t('settings.models.starting', 'Démarrage...'))}</div>
                <div class="progress-bar"><div class="progress-bar-fill" style="width: 0%"></div></div>
                <div class="progress-text">0%</div>
            `;
            modelItem.appendChild(progressDiv);
        }
    }

    try {
        const response = await fetch('/ollama/pull-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelName })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));

                        if (data.error) {
                            throw new Error(data.error);
                        }

                        // Update progress
                        const progress = data.progress || 0;
                        const status = data.status || '';
                        activeDownloads[modelName] = { progress, status };

                        if (modelItem) {
                            const progressDiv = modelItem.querySelector('.download-progress');
                            if (progressDiv) {
                                progressDiv.querySelector('.download-status').textContent = status;
                                progressDiv.querySelector('.progress-bar-fill').style.width = `${progress}%`;
                                progressDiv.querySelector('.progress-text').textContent = `${progress}%`;
                            }
                        }

                        if (data.done) {
                            // Download complete
                            delete activeDownloads[modelName];
                            Toast.success(t('settings.models.downloadDoneTitle', 'Téléchargement terminé'), t('settings.models.downloadDoneBody', '{model} est prêt', { model: modelName }));

                            if (modelItem) {
                                modelItem.classList.remove('downloading');
                                const progressDiv = modelItem.querySelector('.download-progress');
                                if (progressDiv) progressDiv.remove();
                            }

                            if (btn) btn.textContent = t('settings.models.installedAction', 'Prêt');
                            loadOllamaModels();
                        }
                    } catch (e) {
                        console.error('Parse error:', e);
                    }
                }
            }
        }

    } catch (e) {
        delete activeDownloads[modelName];
        Toast.error(t('settings.models.downloadErrorTitle', 'Erreur de téléchargement'), e.message);

        if (modelItem) {
            modelItem.classList.remove('downloading');
            const progressDiv = modelItem.querySelector('.download-progress');
            if (progressDiv) progressDiv.remove();
        }

        if (btn) {
            btn.disabled = false;
            btn.textContent = t('settings.models.installAction', 'Télécharger');
        }
    }
}

async function equipModel(modelName) {
    const oldModel = userSettings.chatModel;

    // Si c'est le même modèle, ne rien faire
    if (oldModel === modelName) {
        Toast.info(t('settings.models.alreadyActiveTitle', 'Déjà actif'), t('settings.models.alreadyActiveBody', '{model} est déjà le modèle actif', { model: modelName }), 2000);
        return;
    }

    Toast.info(t('settings.models.switchingTitle', 'Changement de modèle'), t('settings.models.switchingBody', '{from} → {to}...', { from: oldModel || t('settings.models.none', 'aucun'), to: modelName }), 3000);
    console.log(`[MODEL] Changement: ${oldModel} -> ${modelName}`);

    // 1. Décharger l'ancien modèle pour libérer la mémoire
    if (oldModel && !settingsIsCloudTextModel(oldModel)) {
        console.log(`[MODEL] Déchargement de ${oldModel}...`);
        await apiOllama.unload(oldModel);
        console.log(`[MODEL] ${oldModel} déchargé`);
    }

    // 2. Mettre à jour le setting et la variable globale
    userSettings.chatModel = modelName;
    if (typeof selectedChatModel !== 'undefined') {
        selectedChatModel = modelName;
    }
    if (typeof selectedTextModel !== 'undefined') {
        selectedTextModel = modelName;
    }
    saveSettings();
    loadOllamaModels();

    // 3. Effacer l'historique de chat (nouveau modèle = nouveau contexte)
    chatHistory = [];
    console.log('[MODEL] Historique de chat effacé');

    // Mettre à jour l'affichage du picker
    if (typeof updateModelPickerDisplay === 'function') {
        updateModelPickerDisplay();
    }

    // 4. Préchauffer le nouveau modèle (force=true pour ignorer le cache)
    if (settingsIsCloudTextModel(modelName)) {
        console.log(`[MODEL] Warmup ignoré pour le modèle cloud ${modelName}`);
        return;
    }
    console.log(`[MODEL] Préchauffage de ${modelName}...`);
    const warmupResult = await apiOllama.warmup(modelName, true);
    if (warmupResult.ok && warmupResult.data?.success) {
        console.log(`[MODEL] ${modelName} prêt!`);
        Toast.success(t('settings.models.modelReadyTitle', 'Modèle prêt'), t('settings.models.modelReadyBody', '{model} chargé et prêt', { model: modelName }), 2000);
    } else {
        console.log(`[MODEL] Erreur warmup: ${warmupResult.data?.error || warmupResult.error}`);
        Toast.info(t('common.warning', 'Attention'), t('settings.models.warmupFailed', 'Modèle actif mais warmup échoué'), 3000);
    }
}

async function deleteOllamaModel(modelName) {
    const confirmed = await JoyDialog.confirm(t('settings.models.deleteConfirm', 'Supprimer le modèle {model} ?', { model: modelName }), { variant: 'danger' });
    if (!confirmed) return;

    const result = await apiOllama.delete(modelName);
    if (result.ok && result.data?.success) {
        loadOllamaModels();
    } else {
        await JoyDialog.alert(t('settings.models.deleteError', 'Erreur de suppression'), { variant: 'danger' });
    }
}

function initOllamaTab() {
    checkOllamaStatus();
    loadOllamaModels();
    loadFeatureFlags();
    loadProviderSettings();
    loadPackSettings();
    loadDoctorReport();
    runHarnessAudit();
    searchOllamaModels(); // Show popular models by default
}

// Switch entre les sous-onglets Texte/Image
function switchGenSubtab(tab, btn) {
    const adultState = getAdultFeatureState();
    if (tab === 'nsfw' && !adultState.visible) {
        const fallbackBtn = document.getElementById('settings-gen-tab-image');
        if (fallbackBtn && btn !== fallbackBtn) {
            switchGenSubtab('image', fallbackBtn);
        }
        return;
    }

    // Update tabs — scoped to #settings-generation
    const panel = document.getElementById('settings-generation');
    if (!panel) return;
    panel.querySelectorAll('.settings-subtab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    // Update subpanels
    panel.querySelectorAll('.settings-subpanel').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('gen-' + tab);
    if (target) target.classList.add('active');
}

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

// ========== ONBOARDING ==========

// ===== SETTINGS SUBSCRIBERS — bidirectional sync sidebar ↔ modal =====

// Steps: sidebar slider ↔ modal slider
Settings.subscribe('steps', (val) => {
    const sidebarSlider = document.getElementById('steps-slider');
    const sidebarValue = document.getElementById('steps-value');
    const modalSlider = document.getElementById('settings-steps');
    const modalValue = document.getElementById('settings-steps-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = val;
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = val;
});

// Strength: sidebar slider ↔ modal slider
Settings.subscribe('strength', (val) => {
    const pct = Math.round(val * 100) + '%';
    const sidebarSlider = document.getElementById('strength-slider');
    const sidebarValue = document.getElementById('strength-value');
    const modalSlider = document.getElementById('settings-strength');
    const modalValue = document.getElementById('settings-strength-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = pct;
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = pct;
});

// Dilation: sidebar slider ↔ modal slider
Settings.subscribe('dilation', (val) => {
    const sidebarSlider = document.getElementById('dilation-slider');
    const sidebarValue = document.getElementById('dilation-value');
    const modalSlider = document.getElementById('settings-dilation');
    const modalValue = document.getElementById('settings-dilation-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = val + 'px';
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = val;
});

// Mask toggle: sidebar ↔ modal
Settings.subscribe('maskEnabled', (val) => {
    const sidebarToggle = document.getElementById('mask-toggle');
    const sliderContainer = document.getElementById('dilation-slider-container');
    if (sidebarToggle) sidebarToggle.classList.toggle('active', val);
    if (sliderContainer) {
        sliderContainer.style.opacity = val ? '1' : '0.4';
        sliderContainer.style.pointerEvents = val ? 'auto' : 'none';
    }
});

// Enhance prompt toggle: sidebar ↔ modal
Settings.subscribe('enhancePrompt', (val) => {
    const sidebarToggle = document.getElementById('enhance-toggle');
    const modalToggle = document.getElementById('toggle-enhance-prompt');
    if (sidebarToggle) sidebarToggle.classList.toggle('active', val);
    if (modalToggle) modalToggle.classList.toggle('active', val);
});

// Video settings
Settings.subscribe('videoDuration', (val) => {
    const slider = document.getElementById('settings-video-duration');
    const display = document.getElementById('settings-video-duration-value');
    if (slider) slider.value = val;
    if (display) display.textContent = val + 's';
});

Settings.subscribe('videoSteps', (val) => {
    const slider = document.getElementById('settings-video-steps');
    const display = document.getElementById('settings-video-steps-value');
    if (slider) slider.value = val;
    if (display) display.textContent = val;
});

// LoRA toggles
Settings.subscribe('loraNsfwEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-nsfw');
    const sliderRow = document.getElementById('lora-nsfw-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

Settings.subscribe('loraSkinEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-skin');
    const sliderRow = document.getElementById('lora-skin-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

Settings.subscribe('loraBreastsEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-breasts');
    const sliderRow = document.getElementById('lora-breasts-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

// LoRA labels update on model change
Settings.subscribe('selectedInpaintModel', () => updateLoraLabelsForModel());

// Video audio toggle
Settings.subscribe('videoAudio', (val) => {
    const toggle = document.getElementById('toggle-video-audio');
    if (toggle) toggle.classList.toggle('active', val === true);
});

Settings.subscribe('showAdvancedVideoModels', (val) => {
    const toggle = document.getElementById('toggle-show-advanced-video-models');
    if (toggle) toggle.classList.toggle('active', val);
    if (typeof loadVideoModelsForRuntime === 'function') {
        loadVideoModelsForRuntime();
    }
});

// ===== PROMPT LAB =====
// Legacy DOM ids still contain "jailbreak" to avoid a risky template-wide
// migration; all user-facing copy and navigation now call this Prompt Lab.

let _jailbreakMediaType = 'image';

function toggleJailbreakMediaType(type) {
    _jailbreakMediaType = type;
    document.getElementById('prompt-lab-type-image').classList.toggle('active', type === 'image');
    document.getElementById('prompt-lab-type-video').classList.toggle('active', type === 'video');
}

async function generatePromptLabPrompt() {
    const input = document.getElementById('jailbreak-input');
    const text = input.value.trim();
    if (!text) {
        Toast.error(t('settings.promptLab.emptyTitle', 'Brief vide'), t('settings.promptLab.emptyBody', 'Décris ce que tu veux générer avant de lancer l’assistant de prompt.'));
        return;
    }

    const platform = document.getElementById('jailbreak-platform').value;
    const btn = document.getElementById('jailbreak-generate-btn');
    const resultSection = document.getElementById('jailbreak-result-section');

    // Loading state
    btn.disabled = true;
    btn.textContent = t('settings.promptLab.generating', 'Génération...');

    // Envoyer le modèle chat de l'utilisateur pour éviter les 404
    const chatModel = userSettings.chatModel || null;

    const { data, ok } = await apiSettings.generatePromptHelper({
        request: text,
        platform: platform,
        media_type: _jailbreakMediaType,
        model: chatModel
    });

    btn.disabled = false;
    btn.textContent = t('settings.promptLab.generate', 'Générer');

    if (!ok || !data?.success) {
        Toast.error(data?.error || t('settings.promptLab.generationError', 'Erreur de génération'));
        return;
    }

    // Display result
    const platformNames = {
        grok: 'Grok', sora: 'Sora', midjourney: 'Midjourney',
        dalle: 'DALL-E', stable_diffusion: 'Stable Diffusion', ideogram: 'Ideogram'
    };
    document.getElementById('jailbreak-badge-platform').textContent = platformNames[platform] || platform;
    document.getElementById('jailbreak-badge-type').textContent = _jailbreakMediaType === 'image'
        ? t('settings.promptLab.image', 'Image')
        : t('settings.promptLab.video', 'Vidéo');
    document.getElementById('jailbreak-output').textContent = data.prompt;
    // Afficher la version française si disponible
    const frenchEl = document.getElementById('jailbreak-output-fr');
    if (frenchEl) {
        frenchEl.textContent = data.prompt_fr || '';
        frenchEl.style.display = data.prompt_fr ? '' : 'none';
    }
    document.getElementById('jailbreak-tips').textContent = data.tips || '';
    resultSection.style.display = '';
}

async function copyJailbreakPrompt() {
    const text = document.getElementById('jailbreak-output').textContent;
    if (!text) return;

    const btn = document.getElementById('jailbreak-copy-btn');
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        // Fallback for non-HTTPS
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    }
    btn.textContent = `${t('settings.promptLab.copy', 'Copier')} !`;
    btn.style.background = '#22c55e';
    setTimeout(() => { btn.textContent = t('settings.promptLab.copy', 'Copier'); btn.style.background = ''; }, 1500);
}

const generateJailbreakPrompt = generatePromptLabPrompt;
