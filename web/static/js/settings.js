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

async function loadProviderSettings() {
    const container = document.getElementById('provider-settings-list');
    const note = document.getElementById('provider-settings-note');
    if (!container) return;

    container.innerHTML = `<div class="settings-info">${t('providers.loading', 'Chargement des providers...')}</div>`;

    const result = await apiSettings.getProviderStatus();
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
    ].filter(Boolean);

    container.innerHTML = groups.join('') || `<div class="settings-info">${t('providers.empty', 'Aucun provider configuré')}</div>`;
    refreshSettingsActionChrome(container);
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

function selectTerminalCloudModel(modelId) {
    const cleanModelId = String(modelId || '').trim();
    if (!cleanModelId) return;

    userSettings.terminalModel = cleanModelId;
    const select = document.getElementById('terminal-model-select');
    if (select) {
        if (![...select.options].some(option => option.value === cleanModelId)) {
            const option = document.createElement('option');
            option.value = cleanModelId;
            option.textContent = cleanModelId;
            select.appendChild(option);
        }
        select.value = cleanModelId;
    }
    if (typeof terminalToolModel !== 'undefined') {
        terminalToolModel = cleanModelId;
    }
    saveSettings();
    if (typeof updateModelPickerDisplay === 'function') updateModelPickerDisplay();
    if (typeof Toast !== 'undefined') {
        Toast.success(t('providers.terminalModelSelected', 'Modèle terminal : {model}', { model: cleanModelId }));
    }
}

async function refreshCloudModelSurfaces() {
    if (typeof loadTextModelsForPicker === 'function') {
        await loadTextModelsForPicker();
    } else if (typeof loadTerminalCloudModelProfiles === 'function') {
        await loadTerminalCloudModelProfiles();
    }
    if (typeof populateTerminalModelSelect === 'function') {
        await populateTerminalModelSelect();
    }
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
    }
    if (typeof updateModelPickerDisplay === 'function') {
        updateModelPickerDisplay();
    }
}

function renderProviderSettingsLinks(provider) {
    const links = [];
    if (provider.key_url) {
        links.push(`
            <a class="settings-provider-link" href="${escapeHtml(provider.key_url)}" target="_blank" rel="noopener noreferrer">
                ${escapeHtml(t('providers.createKey', 'Créer une clé'))}
            </a>
        `);
    }
    if (provider.models_url) {
        links.push(`
            <a class="settings-provider-link" href="${escapeHtml(provider.models_url)}" target="_blank" rel="noopener noreferrer">
                ${escapeHtml(t('providers.viewModels', 'Voir les modèles'))}
            </a>
        `);
    }
    if (!links.length) return '';
    return `<div class="settings-provider-links">${links.join('')}</div>`;
}

function getProviderAuthModeLabel(mode) {
    const modeId = String(mode?.id || '').trim();
    return t(`providers.authMode_${modeId}`, mode?.label || modeId || 'API key');
}

function getProviderAuthStatusLabel(status) {
    const key = String(status || '').trim();
    const fallback = {
        configured: t('providers.authStatusConfigured', 'actif'),
        missing_key: t('providers.authStatusMissingKey', 'clé manquante'),
        ready: t('providers.authStatusReady', 'prêt'),
        connector_missing: t('providers.authStatusConnectorMissing', 'connecteur absent'),
        connector_pending: t('providers.authStatusConnectorPending', 'connecteur à brancher'),
    };
    return fallback[key] || key || t('providers.authStatusMissingKey', 'clé manquante');
}

function renderProviderAuthModeControls(provider) {
    const modes = Array.isArray(provider?.auth_modes) ? provider.auth_modes : [];
    if (modes.length <= 1) return '';

    const providerIdArg = escapeHtml(JSON.stringify(provider.provider_id || ''));
    const providerKeyArg = escapeHtml(JSON.stringify(provider.key || ''));
    const buttons = modes.map(mode => {
        const modeId = String(mode?.id || '').trim();
        const modeArg = escapeHtml(JSON.stringify(modeId));
        const selected = modeId && modeId === provider.auth_mode;
        const selectable = mode.selectable !== false;
        const statusLabel = getProviderAuthStatusLabel(mode.status);
        const label = getProviderAuthModeLabel(mode);
        const className = [
            'provider-auth-mode',
            selected ? 'active' : '',
            selectable ? '' : 'locked',
        ].filter(Boolean).join(' ');
        const click = selectable ? `setProviderAuthMode(${providerIdArg}, ${modeArg}, ${providerKeyArg})` : '';
        return `
            <button
                type="button"
                class="${className}"
                ${selected ? 'aria-pressed="true"' : 'aria-pressed="false"'}
                ${selectable ? `onclick="${click}"` : 'disabled aria-disabled="true"'}
                data-tooltip="${escapeHtml(statusLabel)}"
            >
                ${escapeHtml(label)}
            </button>
        `;
    }).join('');

    return `
        <div class="provider-auth-block">
            <div class="provider-auth-label">${escapeHtml(t('providers.authModeTitle', 'Accès'))}</div>
            <div class="provider-auth-modes">${buttons}</div>
        </div>
    `;
}

function renderProviderSettingsRow(provider) {
    const translatedLabel = t(`providerMeta.${provider.key}.label`, provider.label || provider.key);
    const translatedDescription = t(`providerMeta.${provider.key}.description`, provider.description || '');
    const providerKeyArg = JSON.stringify(provider.key);
    const saveTooltip = t('providers.saveTooltip', 'Enregistrer la clé {key}', { key: translatedLabel });
    const clearTooltip = t('providers.clearTooltip', 'Effacer la clé {key}', { key: translatedLabel });
    const sourceText = provider.source === 'env'
        ? t('providers.sourceEnv', 'via variable d’environnement (prioritaire)')
        : provider.source === 'local'
            ? t('providers.sourceLocal', 'stocké localement')
            : t('providers.sourceMissing', 'non configuré');
    const authStatusText = getProviderAuthStatusLabel(provider.auth_status);
    const sourceDetails = provider.auth_uses_api_key === false ? authStatusText : sourceText;
    const stateText = provider.configured
        ? t('providers.configured', 'Configuré {masked}', { masked: provider.masked ? `(${provider.masked})` : '' }).trim()
        : t('providers.notConfigured', 'Non configuré');
    const stateClass = provider.configured ? 'status-ok' : 'status-warn';
    const providerLinks = renderProviderSettingsLinks(provider);
    const authControls = renderProviderAuthModeControls(provider);
    const apiKeyActive = provider.auth_uses_api_key !== false;

    return `
        <div class="settings-card settings-provider-card">
            <div class="settings-card-body">
                <div style="min-width: 0; flex: 1;">
                    <div class="settings-label">${translatedLabel}</div>
                    <div class="settings-label-desc">${translatedDescription}</div>
                    <div class="settings-label-desc">
                        <span class="${stateClass}">${stateText}</span> · ${sourceDetails}
                    </div>
                </div>
                <div class="settings-card-controls">
                    ${authControls}
                    <input
                        type="password"
                        id="provider-input-${provider.key}"
                        class="settings-input"
                        placeholder="${provider.placeholder || ''}"
                        autocomplete="off"
                        ${apiKeyActive ? '' : 'disabled'}
                    >
                    ${providerLinks}
                    <div class="settings-inline-actions">
                        ${renderSettingsIconAction({
                            icon: 'save',
                            label: saveTooltip,
                            tooltip: saveTooltip,
                            onClick: `saveProviderSecret(${providerKeyArg})`,
                            disabled: !apiKeyActive,
                        })}
                        ${renderSettingsIconAction({
                            icon: 'trash-2',
                            label: clearTooltip,
                            tooltip: clearTooltip,
                            onClick: `clearProviderSecret(${providerKeyArg})`,
                            classes: 'subtle',
                        })}
                    </div>
                </div>
            </div>
        </div>
    `;
}

async function setProviderAuthMode(providerId, authMode, key = '') {
    const result = await apiSettings.setProviderAuthMode(providerId, authMode, key);
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('providers.authModeError', 'Impossible de changer le mode d’accès'));
        return;
    }

    await loadProviderSettings();
    await refreshCloudModelSurfaces();
    if (typeof checkModelsStatus === 'function') checkModelsStatus();
    Toast.success(t('providers.authModeSavedTitle', 'Accès mis à jour'), t('providers.authModeSavedBody', 'Le provider utilisera ce mode uniquement.'), 2200);
}

async function saveProviderSecret(key) {
    const input = document.getElementById(`provider-input-${key}`);
    const value = input?.value?.trim() || '';

    if (!value) {
        Toast.info(t('providers.emptyInputTitle', 'Clé vide'), t('providers.emptyInputBody', 'Colle une valeur avant d’enregistrer'), 2500);
        return;
    }

    const result = await apiSettings.saveProviderSecret(key, value);
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('providers.saveError', 'Impossible d’enregistrer la clé'));
        return;
    }

    if (input) input.value = '';
    await loadProviderSettings();
    await refreshCloudModelSurfaces();
    if (typeof checkModelsStatus === 'function') checkModelsStatus();
    Toast.success(t('providers.savedTitle', 'Provider enregistré'), t('providers.savedBody', '{key} est disponible localement', { key }), 2500);
}

async function clearProviderSecret(key) {
    const result = await apiSettings.clearProviderSecret(key);
    if (!result.ok || !result.data?.success) {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('providers.clearError', 'Impossible d’effacer la clé'));
        return;
    }

    const input = document.getElementById(`provider-input-${key}`);
    if (input) input.value = '';
    await loadProviderSettings();
    await refreshCloudModelSurfaces();
    if (typeof checkModelsStatus === 'function') checkModelsStatus();
    Toast.info(t('providers.clearedTitle', 'Provider effacé'), t('providers.clearedBody', '{key} a été retiré du stockage local', { key }), 2500);
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

// ===== VIDEO QUALITY VISIBILITY =====

let videoModelRuntimeDefaults = null;

function getVideoModelGroupLabel(category) {
    if (category === 'recommended') {
        return t('settings.generation.videoGroupRecommended', 'Recommandé pour cette machine');
    }
    if (category === 'compatible') {
        return t('settings.generation.videoGroupCompatible', 'Compatible');
    }
    if (category === 'try') {
        return t('settings.generation.videoGroupTry', 'Peut tourner, non recommandé');
    }
    if (category === 'unavailable') {
        return t('settings.generation.videoGroupUnavailable', 'Non disponible pour l’instant');
    }
    return t('settings.generation.videoGroupAdvanced', 'Avancé');
}

function isRuntimeVideoModelDisabled(model) {
    return model.launch_status === 'missing_backend'
        || (model.requires_experimental_env && !model.experimental_enabled);
}

function formatRuntimeVideoModelOption(model) {
    const parts = [model.name];
    const details = [];
    if (model.supports_image && model.supports_prompt) details.push('I2V + prompt');
    else if (model.supports_image) details.push('I2V');
    else if (model.supports_prompt) details.push('T2V');
    if (model.vram) details.push(model.vram);
    if (model.launch_status === 'missing_backend') {
        details.push(t('settings.generation.videoBackendMissing', 'moteur non intégré'));
    } else if (model.requires_experimental_env) {
        details.push(model.experimental_enabled
            ? t('settings.generation.videoManualTestEnabled', 'mode test actif')
            : t('settings.generation.videoManualTestDisabled', 'mode test à activer'));
    } else if (model.experimental_low_vram) {
        details.push(t('settings.generation.videoNonRecommended', 'non recommandé'));
    }
    if (details.length) parts.push(`- ${details.join(', ')}`);
    return parts.join(' ');
}

function updateVideoAudioAvailability(catalog) {
    const toggle = document.getElementById('toggle-video-audio');
    const row = toggle?.closest('.settings-row');
    if (!toggle) return;

    const disabledOnThisMachine = Boolean(catalog?.low_vram);
    if (disabledOnThisMachine && userSettings.videoAudio === true) {
        saveSetting('videoAudio', false);
    }

    const title = disabledOnThisMachine
        ? t(
            'settings.generation.videoAudioLowVramLocked',
            'MMAudio est désactivé automatiquement sur petite VRAM. Backend override: JOYBOY_ALLOW_MMAUDIO_LOW_VRAM=1.'
        )
        : t('settings.generation.videoAudioDesc', 'Option lourde, désactivée par défaut. Ignorée sur petite VRAM sauf override.');

    toggle.classList.toggle('disabled', disabledOnThisMachine);
    toggle.setAttribute('aria-disabled', disabledOnThisMachine ? 'true' : 'false');
    toggle.title = title;
    row?.classList.toggle('settings-row-disabled', disabledOnThisMachine);
}

function renderRuntimeVideoModels(catalog) {
    const select = document.getElementById('settings-video-model');
    if (!select || !catalog || !Array.isArray(catalog.models) || catalog.models.length === 0) return;

    videoModelRuntimeDefaults = Object.fromEntries(
        catalog.models.map(model => [model.id, {
            name: model.name,
            fps: model.default_fps,
            steps: model.default_steps,
            configurable: !catalog.low_vram && (model.id === 'wan22-5b' || model.id === 'svd'),
        }])
    );
    window.videoModelRuntimeDefaults = videoModelRuntimeDefaults;

    select.innerHTML = '';
    const groups = new Map();
    const selectableModels = [];
    for (const model of catalog.models) {
        const category = model.category || 'compatible';
        if (!groups.has(category)) {
            const group = document.createElement('optgroup');
            group.label = getVideoModelGroupLabel(category);
            groups.set(category, group);
            select.appendChild(group);
        }

        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = formatRuntimeVideoModelOption(model);
        option.title = model.description || option.textContent;
        option.disabled = isRuntimeVideoModelDisabled(model);
        option.dataset.launchStatus = model.launch_status || 'ready';
        if (!option.disabled) {
            selectableModels.push(model);
        }
        groups.get(category).appendChild(option);
    }

    const availableIds = new Set(selectableModels.map(model => model.id));
    const currentModel = userSettings.videoModel || catalog.default_model || 'svd';
    const fallbackModel = selectableModels.find(model => model.id === catalog.default_model)
        || selectableModels[0]
        || catalog.models[0];
    const nextModel = availableIds.has(currentModel) ? currentModel : (fallbackModel?.id || 'svd');
    if (nextModel !== currentModel) {
        saveSetting('videoModel', nextModel);
    }
    select.value = nextModel;

    const desc = document.getElementById('gen-video-model-desc');
    if (desc && catalog.low_vram) {
        const vram = Number(catalog.vram_gb || 0).toFixed(1);
        const count = catalog.advanced_count || 0;
        const advancedEnabled = userSettings.showAdvancedVideoModels === true;
        desc.textContent = advancedEnabled
            ? t(
                'settings.generation.videoModelDescLowVramAdvanced',
                `VRAM détectée: ${vram}GB. SVD est recommandé; les autres modèles sont séparés entre test manuel et non disponible.`,
                { vram, count }
            )
            : t(
                'settings.generation.videoModelDescLowVram',
                `VRAM détectée: ${vram}GB. La liste affiche les modèles sûrs; ${count} modèles de test sont masqués.`,
                { vram, count }
            );
    }

    updateVideoAudioAvailability(catalog);
    updateVideoQualityVisibility();
}

async function loadVideoModelsForRuntime() {
    try {
        const includeAdvanced = userSettings.showAdvancedVideoModels === true;
        const query = includeAdvanced ? '?advanced=1&allow_experimental=1' : '';
        const response = await fetch(`/api/video-models${query}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        renderRuntimeVideoModels(await response.json());
    } catch (error) {
        console.warn('[VIDEO] Impossible de charger le catalogue runtime:', error);
    }
}

function updateVideoQualityVisibility() {
    const qualityRow = document.getElementById('video-quality-row');
    const model = userSettings.videoModel || 'svd';

    // Afficher le sélecteur de qualité uniquement pour les modèles 5B
    if (qualityRow) {
        qualityRow.style.display = (model === 'wan22-5b' || model === 'fastwan') ? '' : 'none';
    }

    const modelDefaults = {
        'wan22': { fps: 16, steps: 40, configurable: false },
        'wan': { fps: 16, steps: 50, configurable: false },
        'wan22-5b': { fps: 24, steps: 30, configurable: true },
        'fastwan': { fps: 24, steps: 8, configurable: false },
        'hunyuan': { fps: 15, steps: 12, configurable: false },
        'framepack': { fps: 18, steps: 9, configurable: false },
        'framepack-fast': { fps: 12, steps: 7, configurable: false },
        'ltx': { fps: 8, steps: 8, configurable: false },
        'ltx2': { fps: 24, steps: 8, configurable: false },
        'ltx2_fp8': { fps: 24, steps: 40, configurable: false },
        'svd': { fps: 8, steps: 10, configurable: true },
        'cogvideox': { fps: 8, steps: 50, configurable: false },
        'cogvideox-q4': { fps: 8, steps: 50, configurable: false },
        'cogvideox-2b': { fps: 8, steps: 50, configurable: false },
    };
    const runtimeDefaults = videoModelRuntimeDefaults && videoModelRuntimeDefaults[model];
    const md = runtimeDefaults || modelDefaults[model] || modelDefaults['ltx'];
    const isFramePack = model === 'framepack' || model === 'framepack-fast';
    const isFramePackFast = model === 'framepack-fast';

    const durationSlider = document.getElementById('settings-video-duration');
    const durationValue = document.getElementById('settings-video-duration-value');
    if (durationSlider) {
        if (isFramePackFast) {
            durationSlider.min = '5';
            durationSlider.max = '5';
            durationSlider.step = '5';
            durationSlider.value = '5';
            if (durationValue) {
                durationValue.textContent = t('settings.generation.videoFramepackFastDuration', '5s rapide · 60 frames');
            }
        } else if (isFramePack) {
            durationSlider.min = '5';
            durationSlider.max = '10';
            durationSlider.step = '5';
            const snappedDuration = (userSettings.videoDuration ?? 5) >= 8 ? 10 : 5;
            durationSlider.value = snappedDuration;
            if (durationValue) {
                durationValue.textContent = snappedDuration === 10
                    ? t('settings.generation.videoFramepackLongDuration', '10s · 180 frames')
                    : t('settings.generation.videoFramepackNormalDuration', '5s · 90 frames');
            }
        } else {
            durationSlider.min = '2';
            durationSlider.max = '15';
            durationSlider.step = '1';
            durationSlider.value = userSettings.videoDuration ?? 5;
            if (durationValue) {
                durationValue.textContent = `${userSettings.videoDuration ?? 5}s`;
            }
        }
    }

    // Mettre à jour FPS slider (toujours fixe — natif au modèle)
    const fpsSlider = document.getElementById('settings-video-fps');
    const fpsValue = document.getElementById('settings-video-fps-value');
    if (fpsSlider) {
        fpsSlider.value = md.fps;
        fpsSlider.disabled = true;
        fpsSlider.style.opacity = '0.4';
        if (fpsValue) fpsValue.textContent = md.fps;
    }

    // Mettre à jour Steps slider
    const stepsSlider = document.getElementById('settings-video-steps');
    const stepsValue = document.getElementById('settings-video-steps-value');
    if (stepsSlider) {
        let steps = md.configurable ? (userSettings.videoSteps || md.steps) : md.steps;
        if (isFramePackFast) {
            steps = 7;
        } else if (isFramePack) {
            steps = 9;
        }
        stepsSlider.value = steps;
        stepsSlider.disabled = !md.configurable;
        stepsSlider.style.opacity = md.configurable ? '1' : '0.4';
        if (stepsValue) stepsValue.textContent = steps;
    }

    // Afficher le slider Refine uniquement pour LTX
    const refineRow = document.getElementById('video-refine-row');
    if (refineRow) {
        refineRow.style.display = (model === 'ltx') ? '' : 'none';
    }
    const refineSlider = document.getElementById('settings-video-refine');
    const refineValue = document.getElementById('settings-video-refine-value');
    if (refineSlider) {
        refineSlider.value = userSettings.videoRefine ?? 0;
        if (refineValue) refineValue.textContent = userSettings.videoRefine ?? 0;
    }
}

// ===== BACKEND GGUF =====

async function changeBackend(backend) {
    const quantRow = document.getElementById('gguf-quant-row');
    const statusEl = document.getElementById('gguf-status');

    if (backend === 'gguf') {
        if (quantRow) quantRow.style.display = 'flex';
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.innerHTML = `<span style="color:#f59e0b;">${escapeHtml(t('settings.gguf.checking', 'Vérification du backend GGUF...'))}</span>`;
        }

        try {
            const res = await fetch('/api/backend/gguf/status');
            const data = await res.json();

            if (data.available) {
                const inpaintCount = data.local_models?.inpaint?.length || 0;
                const videoCount = data.local_models?.video?.length || 0;
                statusEl.innerHTML = `<span style="color:#22c55e;">${escapeHtml(t('settings.gguf.available', 'GGUF disponible'))}</span><br>
                    <span style="color:#a1a1aa;">${escapeHtml(t('settings.gguf.localModels', 'Modèles locaux : {inpaint} inpaint, {video} vidéo', { inpaint: inpaintCount, video: videoCount }))}</span>`;
            } else {
                statusEl.innerHTML = `<span style="color:#f59e0b;">${escapeHtml(t('settings.gguf.installRequired', 'Installation requise'))}</span><br>
                    <span style="color:#a1a1aa;">${escapeHtml(t('settings.gguf.installFirstUse', 'Le backend GGUF sera installé au premier usage'))}</span>`;
            }
        } catch (e) {
            statusEl.innerHTML = `<span style="color:#ef4444;">${escapeHtml(t('settings.gguf.backendError', 'Erreur connexion backend'))}</span>`;
        }
    } else {
        if (quantRow) quantRow.style.display = 'none';
        if (statusEl) statusEl.style.display = 'none';
    }

    userSettings.backend = backend;
    saveSettings();

    // Rafraîchir le model picker pour afficher les bons modèles
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
    }

    // Notifier le backend
    try {
        await fetch('/api/backend/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backend })
        });
    } catch (e) {
        console.error('[SETTINGS] Erreur changement backend:', e);
    }
}

function changeGGUFQuant(quant) {
    userSettings.ggufQuant = quant;
    saveSettings();
    console.log(`[SETTINGS] GGUF Quantization -> ${quant}`);
}

function initBackendUI() {
    const backendSelect = document.getElementById('settings-backend');
    const quantSelect = document.getElementById('settings-gguf-quant');

    if (backendSelect && userSettings.backend) {
        backendSelect.value = userSettings.backend;
        if (userSettings.backend === 'gguf') {
            changeBackend('gguf'); // Affiche les options GGUF
        }
    }

    if (quantSelect && userSettings.ggufQuant) {
        quantSelect.value = userSettings.ggufQuant;
    }
}

// ===== SEGMENTATION MAINTENANCE =====

function _segStatusMsg(text, color) {
    const el = document.getElementById('seg-model-status');
    if (el) {
        el.style.display = 'block';
        el.style.color = color || '#a1a1aa';
        el.textContent = text;
    }
}

async function deleteSegModel() {
    const modelName = 'Fusion (B2+B4+SCHP)';
    const confirmed = await JoyDialog.confirm(
        t('settings.segmentation.deleteConfirm', 'Supprimer "{model}" du cache ?', { model: modelName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    const btn = document.getElementById('btn-delete-seg');
    if (btn) btn.textContent = t('settings.segmentation.deleting', 'Suppression...');
    _segStatusMsg(t('settings.segmentation.deleteProgress', 'Suppression en cours...'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/delete', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success(t('settings.segmentation.deleted', 'Supprimé'), data.message);
        } else {
            _segStatusMsg(data.error || t('common.error', 'Erreur'), '#ef4444');
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationDelete', 'Supprimer du cache');
}

async function reinstallSegModel() {
    const modelName = 'Fusion (B2+B4+SCHP)';
    const confirmed = await JoyDialog.confirm(
        t('settings.segmentation.reinstallConfirm', 'Réinstaller "{model}" ? (supprime + retélécharge)', { model: modelName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    const btn = document.getElementById('btn-reinstall-seg');
    if (btn) btn.textContent = t('settings.segmentation.reinstalling', 'Réinstallation...');
    _segStatusMsg(t('settings.segmentation.reinstallProgress', 'Suppression + retéléchargement en cours... (peut prendre quelques minutes)'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/reinstall', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success(t('settings.segmentation.reinstalled', 'Réinstallé'), data.message);
        } else {
            _segStatusMsg(data.error || t('common.error', 'Erreur'), '#ef4444');
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationReinstall', 'Réinstaller le modèle');
}

async function verifySegModel() {
    const btn = document.getElementById('btn-verify-seg');
    if (btn) btn.textContent = t('settings.segmentation.verifying', 'Vérification...');
    _segStatusMsg(t('settings.segmentation.verifyProgress', 'Vérification en cours...'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/verify', { method: 'POST' });
        const data = await res.json();
        if (data.healthy) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success('OK', data.message);
        } else {
            const issueText = data.issues?.join(', ') || t('settings.segmentation.issueDetected', 'Problème détecté');
            _segStatusMsg(`${data.label}: ${issueText} — ${data.recommendation}`, '#ef4444');
            if (typeof Toast !== 'undefined') Toast.error(t('settings.segmentation.issueTitle', 'Problème'), issueText);
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationVerify', "Vérifier l'intégrité");
}

// ===== TUNNEL CLOUDFLARE =====

async function toggleTunnel() {
    const toggle = document.getElementById('toggle-tunnel');
    const statusRow = document.getElementById('tunnel-status-row');
    const statusText = document.getElementById('tunnel-status-text');
    const urlRow = document.getElementById('tunnel-url-row');
    const urlInput = document.getElementById('tunnel-url');

    const isActive = toggle.classList.contains('active');

    if (isActive) {
        // Arrêter le tunnel
        toggle.classList.remove('active');
        statusRow.style.display = 'none';
        urlRow.style.display = 'none';
        userSettings.tunnelEnabled = false;
        saveSettings();

        try {
            await fetch('/api/tunnel/stop', { method: 'POST' });
        } catch (e) {
            console.error('[TUNNEL] Erreur stop:', e);
        }
    } else {
        // Démarrer le tunnel
        toggle.classList.add('active');
        statusRow.style.display = 'block';
        statusText.style.color = '#f59e0b';
        statusText.textContent = t('settings.tunnel.starting', 'Téléchargement et démarrage du tunnel...');
        urlRow.style.display = 'none';

        try {
            const res = await fetch('/api/tunnel/start', { method: 'POST' });
            const data = await res.json();

            if (data.success) {
                statusText.style.color = '#22c55e';
                statusText.textContent = t('settings.tunnel.active', 'Tunnel actif');
                urlRow.style.display = 'flex';
                urlInput.value = data.url;
                userSettings.tunnelEnabled = true;
                saveSettings();
            } else {
                statusText.style.color = '#ef4444';
                statusText.textContent = t('settings.tunnel.errorPrefix', 'Erreur : {error}', {
                    error: data.error || t('settings.tunnel.unknown', 'inconnu'),
                });
                toggle.classList.remove('active');
                userSettings.tunnelEnabled = false;
                saveSettings();
            }
        } catch (e) {
            console.error('[TUNNEL] Erreur start:', e);
            statusText.style.color = '#ef4444';
            statusText.textContent = t('settings.tunnel.networkError', 'Erreur réseau');
            toggle.classList.remove('active');
        }
    }
}

async function checkTunnelStatus() {
    try {
        const res = await fetch('/api/tunnel/status');
        const data = await res.json();

        const toggle = document.getElementById('toggle-tunnel');
        const statusRow = document.getElementById('tunnel-status-row');
        const statusText = document.getElementById('tunnel-status-text');
        const urlRow = document.getElementById('tunnel-url-row');
        const urlInput = document.getElementById('tunnel-url');

        if (!toggle) return;

        if (data.running && data.url) {
            toggle.classList.add('active');
            statusRow.style.display = 'block';
            statusText.style.color = '#22c55e';
            statusText.textContent = t('settings.tunnel.active', 'Tunnel actif');
            urlRow.style.display = 'flex';
            urlInput.value = data.url;
        } else {
            toggle.classList.remove('active');
            statusRow.style.display = 'none';
        }
    } catch (e) {
        console.error('[TUNNEL] Erreur check status:', e);
    }
}

function copyTunnelUrl() {
    const urlInput = document.getElementById('tunnel-url');
    if (urlInput && urlInput.value) {
        navigator.clipboard.writeText(urlInput.value).then(() => {
            if (typeof Toast !== 'undefined') {
                Toast.success(
                    t('settings.tunnel.copiedTitle', 'Copié'),
                    t('settings.tunnel.copiedBody', 'URL copiée dans le presse-papier'),
                    2000
                );
            }
        }).catch(() => {
            // Fallback
            urlInput.select();
            document.execCommand('copy');
        });
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
let allImageModels = [];
let currentImageFilter = 'all';

async function checkModelsStatus() {
    const installedList = DOM.get('image-installed-models');
    const availableList = DOM.get('image-available-models');

    if (installedList) DOM.setHtml(installedList, `<div class="settings-info">${escapeHtml(t('settings.models.checking', 'Vérification...'))}</div>`);
    if (availableList) DOM.setHtml(availableList, `<div class="settings-info">${escapeHtml(t('common.loading', 'Chargement...'))}</div>`);

    const result = await apiModels.checkModels();
    if (!result.ok) {
        const errorText = escapeHtml(t('settings.models.genericError', 'Erreur : {error}', { error: result.error || '' }));
        if (installedList) DOM.setHtml(installedList, `<div class="settings-info">${errorText}</div>`);
        if (availableList) DOM.setHtml(availableList, `<div class="settings-info">${errorText}</div>`);
        return;
    }

    const data = result.data;
    if (data.success && data.models && data.models.length > 0) {
        allImageModels = data.models;

        // Séparer installés et non installés
        const installed = data.models.filter(m => m.downloaded && (isAdultSurfaceEnabled() || !isAdultImageSurfaceModel(m)));
        const available = data.models.filter(m => !m.downloaded && (isAdultSurfaceEnabled() || !isAdultImageSurfaceModel(m)));

        // Afficher les installés
        if (installedList) {
            if (installed.length > 0) {
                DOM.setHtml(installedList, installed.map(model => renderImageModelItem(model, true)).join(''));
                if (window.lucide) lucide.createIcons();
            } else {
                DOM.setHtml(installedList, `<div class="settings-info">${escapeHtml(t('settings.models.noInstalled', 'Aucun modèle local'))}</div>`);
            }
        }

        // Afficher les disponibles (avec filtre)
        renderAvailableImageModels();
    } else {
        const emptyText = escapeHtml(t('settings.models.noModels', 'Aucun modèle'));
        if (installedList) DOM.setHtml(installedList, `<div class="settings-info">${emptyText}</div>`);
        if (availableList) DOM.setHtml(availableList, `<div class="settings-info">${emptyText}</div>`);
    }
}

function renderImageModelItem(model, isInstalled) {
    const isNsfw = isAdultImageSurfaceModel(model);
    const categoryBadge = imageModelCategoryLabel(model.category);
    const capabilities = Array.isArray(model.capabilities) && model.capabilities.length
        ? model.capabilities
        : (model.category === 'image' ? ['inpaint', 'txt2img'] : [model.category]);

    // Vérifier si c'est le modèle équipé (inpaint ou text2img)
    const currentInpaint = typeof selectedInpaintModel !== 'undefined' ? selectedInpaintModel : null;
    const currentText2Img = typeof selectedText2ImgModel !== 'undefined' ? selectedText2ImgModel : null;
    const isEquipped = isInstalled && (currentInpaint === model.name || currentText2Img === model.name);
    const inpaintEquipped = isInstalled && currentInpaint === model.name;
    const txt2imgEquipped = isInstalled && currentText2Img === model.name;
    const modelNameAttr = escapeHtml(String(model.name || ''));
    const modelKeyAttr = escapeHtml(String(model.key || ''));
    const translatedDesc = translateImageModelDesc(model, categoryBadge);
    const providerLine = model.provider_label
        ? `<span class="model-size">${escapeHtml(model.provider_label)} · ${escapeHtml(imageProviderHint(model))}</span>`
        : '';
    const installedActions = capabilities.includes('inpaint') && capabilities.includes('txt2img')
        ? `
            <button class="btn-equip ${inpaintEquipped ? 'equipped' : ''}" data-model-name="${modelNameAttr}" data-model-mode="inpaint" onclick="equipImageModelFromButton(this)">
                ${inpaintEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equippedInpaint', 'Inpaint actif'))}` : escapeHtml(t('settings.models.equipInpaint', 'Équiper Inpaint'))}
            </button>
            <button class="btn-equip ${txt2imgEquipped ? 'equipped' : ''}" data-model-name="${modelNameAttr}" data-model-mode="txt2img" onclick="equipImageModelFromButton(this)">
                ${txt2imgEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equippedText2Img', 'Text2Img actif'))}` : escapeHtml(t('settings.models.equipText2Img', 'Équiper Text2Img'))}
            </button>
            <button class="btn-delete-model" data-model-key="${modelKeyAttr}" data-model-name="${modelNameAttr}" onclick="deleteImageModelFromButton(this)">${escapeHtml(t('common.delete', 'Supprimer'))}</button>
        `
        : `
            <button class="btn-equip ${isEquipped ? 'equipped' : ''}" data-model-name="${modelNameAttr}" onclick="equipImageModelFromButton(this)">
                ${isEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equipped', 'Équipé'))}` : escapeHtml(t('settings.models.equip', 'Équiper'))}
            </button>
            <button class="btn-delete-model" data-model-key="${modelKeyAttr}" data-model-name="${modelNameAttr}" onclick="deleteImageModelFromButton(this)">${escapeHtml(t('common.delete', 'Supprimer'))}</button>
        `;

    return `
        <div class="ollama-model-item ${isNsfw ? 'uncensored' : ''} ${isEquipped ? 'equipped' : ''}">
            <div class="model-info">
                <div class="model-name-row">
                    <span class="model-name">${escapeHtml(model.name || '')}</span>
                ${isNsfw ? '<span class="uncensored-badge">LOCAL+</span>' : ''}
                    ${isEquipped ? `<span class="uncensored-badge" style="background: rgba(59,130,246,0.15); color: #3b82f6;">${escapeHtml(t('settings.models.activeBadge', 'ACTIF'))}</span>` : ''}
                </div>
                <span class="model-desc">${escapeHtml(translatedDesc)}</span>
                <span class="model-size">${escapeHtml(model.size || '~6 GB')}</span>
                ${providerLine}
            </div>
            <div class="model-actions">
                ${isInstalled ? `
                    ${installedActions}
                ` : `
                    <button class="btn-install-model" data-model-key="${modelKeyAttr}" onclick="downloadImageModelFromButton(this)">${escapeHtml(t('settings.models.download', 'Télécharger'))}</button>
                `}
            </div>
        </div>
    `;
}

function renderAvailableImageModels() {
    const availableList = document.getElementById('image-available-models');
    if (!availableList) return;

    let available = allImageModels.filter(m => !m.downloaded);
    if (!isAdultSurfaceEnabled()) {
        available = available.filter(model => !isAdultImageSurfaceModel(model));
    }

    // Appliquer le filtre
    if (currentImageFilter !== 'all') {
        available = available.filter(model => {
            const name = model.name.toLowerCase();
            const desc = (model.desc || '').toLowerCase();
            const category = (model.category || '').toLowerCase();

            switch(currentImageFilter) {
                case 'inpaint':
                    return category === 'inpaint' || category === 'image' || name.includes('inpaint');
                case 'txt2img':
                    return category === 'txt2img' || category === 'image' || (!name.includes('inpaint') && category !== 'utils');
                case 'nsfw':
                    return isAdultSurfaceEnabled() && isAdultImageSurfaceModel(model);
                default:
                    return true;
            }
        });
    }

    if (available.length > 0) {
        availableList.innerHTML = available.map(model => renderImageModelItem(model, false)).join('');
        if (window.lucide) lucide.createIcons();
    } else {
        availableList.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.models.noAvailableForFilter', 'Aucun modèle disponible avec ce filtre'))}</div>`;
    }
}

function renderCachedImageModelLists() {
    if (!Array.isArray(allImageModels) || !allImageModels.length) return;
    const installedList = document.getElementById('image-installed-models');
    if (installedList) {
        const installed = allImageModels.filter(m => m.downloaded && (isAdultSurfaceEnabled() || !isAdultImageSurfaceModel(m)));
        DOM.setHtml(installedList, installed.length
            ? installed.map(model => renderImageModelItem(model, true)).join('')
            : `<div class="settings-info">${escapeHtml(t('settings.models.noInstalled', 'Aucun modèle local'))}</div>`
        );
    }
    renderAvailableImageModels();
    if (window.lucide) lucide.createIcons();
}

function toggleImageModelFilter(filter) {
    if (filter === 'nsfw' && !isAdultSurfaceEnabled()) {
        filter = 'all';
    }
    currentImageFilter = filter;

    // Update UI
    document.querySelectorAll('#models-image-panel .filter-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.filter === filter);
    });

    renderAvailableImageModels();
}

const IMAGE_MODEL_DESC_KEYS = new Map([
    ['int4 - ultra rapide, qualite reduite', 'int4FastReduced'],
    ['int8 - bon compromis vitesse/qualite', 'int8Balanced'],
    ['fp16 - qualite maximale', 'fp16MaxQuality'],
    ['int8 - local pack ready, meilleure anatomie', 'int8LocalBetterAnatomy'],
    ['rapide et polyvalent', 'fastVersatile'],
    ['meilleur global, anatomie parfaite', 'bestOverallAnatomy'],
    ['ultra realiste, textures top', 'ultraRealisticTextures'],
    ['tres rapide (4 steps)', 'veryFastFourSteps'],
    ['int8 - local pack specialist, anatomie top', 'int8LocalSpecialistAnatomy'],
    ['fp16 - local pack specialist, qualite max', 'fp16LocalSpecialistMaxQuality'],
    ['int8 - pony xl v16, realiste + mignon', 'int8PonyRealCute'],
    ['fp16 - pony xl v16, qualite maximale', 'fp16PonyMaxQuality'],
]);

function normalizeModelText(value) {
    return String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}

function imageModelCategoryLabel(category) {
    const key = String(category || '').toLowerCase();
    if (key === 'inpaint') return t('settings.models.categoryInpaint', 'Inpaint');
    if (key === 'txt2img') return t('settings.models.categoryText2Img', 'Text2Img');
    if (key === 'image') return t('settings.models.categoryImage', 'Image');
    return t('settings.models.categoryUtils', 'Utils');
}

function translateImportedModelDescPart(part) {
    const raw = String(part || '').trim();
    const normalized = normalizeModelText(raw);
    if (!raw) return '';
    if (normalized === 'civitai import') {
        return t('settings.models.descPartCivitaiImport', 'Import CivitAI');
    }
    if (normalized === 'huggingface import') {
        return t('settings.models.descPartHuggingFaceImport', 'Import Hugging Face');
    }
    if (normalized === 'checkpoint') {
        return t('settings.models.descPartCheckpoint', 'Checkpoint');
    }
    if (normalized === 'runtime natif' || normalized === 'runtime native') {
        return t('settings.models.descPartRuntimeNative', 'exécution native');
    }
    const sourceMatch = raw.match(/^source\s+(.+)$/i);
    if (sourceMatch) {
        return t('settings.models.descPartSourcePrecision', 'source {precision}', {
            precision: sourceMatch[1].trim().toUpperCase(),
        });
    }
    const runtimeMatch = raw.match(/^runtime\s+(.+)$/i);
    if (runtimeMatch) {
        return t('settings.models.descPartRuntimeQuant', 'exécution {quant}', {
            quant: runtimeMatch[1].trim().toUpperCase(),
        });
    }
    return raw;
}

function translateImageModelDesc(model, categoryLabel) {
    const raw = String(model?.desc || '').trim();
    if (!raw) return categoryLabel;
    const knownKey = IMAGE_MODEL_DESC_KEYS.get(normalizeModelText(raw));
    if (knownKey) {
        return t(`settings.models.catalogDescriptions.${knownKey}`, raw);
    }
    if (model?.imported || raw.includes(' · ')) {
        return raw.split(' · ').map(translateImportedModelDescPart).filter(Boolean).join(' · ');
    }
    return raw;
}

function imageProviderHint(model) {
    if (model?.provider_configured) {
        return t('settings.models.providerKeyReady', 'clé prête');
    }
    const provider = String(model?.provider || '').toLowerCase();
    if (provider === 'local') {
        return t('settings.models.providerLocalReady', 'déjà présent localement');
    }
    if (provider === 'civitai') {
        return t('settings.models.providerCivitaiHint', 'clé utile pour CivitAI');
    }
    return t('settings.models.providerKeyOptional', 'clé optionnelle');
}

// Équiper un modèle image (inpaint ou text2img selon le type)
function equipImageModelFromButton(button) {
    const modelName = button?.dataset?.modelName || '';
    const mode = button?.dataset?.modelMode || null;
    if (!modelName) return;
    equipImageModel(modelName, mode);
}

function equipImageModel(modelName, preferredMode = null) {
    // Déterminer le type de modèle
    const modelMeta = allImageModels.find(m => m.name === modelName);
    const capabilities = Array.isArray(modelMeta?.capabilities) ? modelMeta.capabilities : [];
    const mode = preferredMode || (modelName.toLowerCase().includes('inpaint') ? 'inpaint' : (capabilities.includes('inpaint') && !capabilities.includes('txt2img') ? 'inpaint' : 'txt2img'));
    const isInpaint = mode === 'inpaint';
    let previousModel = null;

    if (isInpaint) {
        // C'est un modèle inpaint
        previousModel = typeof selectedInpaintModel !== 'undefined' ? selectedInpaintModel : null;
        if (previousModel === modelName) {
            Toast.info(t('settings.models.alreadyActiveTitle', 'Déjà actif'), t('settings.models.imageAlreadyActiveBody', '{model} est déjà le modèle image actif', { model: modelName }), 2000);
            return;
        }
        if (typeof selectedInpaintModel !== 'undefined') {
            selectedInpaintModel = modelName;
            selectedImageModel = modelName;  // Compat
        }
        Settings.set('selectedInpaintModel', modelName);
    } else {
        // C'est un modèle text2img
        previousModel = typeof selectedText2ImgModel !== 'undefined' ? selectedText2ImgModel : null;
        if (previousModel === modelName) {
            Toast.info(t('settings.models.alreadyActiveTitle', 'Déjà actif'), t('settings.models.imageAlreadyActiveBody', '{model} est déjà le modèle image actif', { model: modelName }), 2000);
            return;
        }
        if (typeof selectedText2ImgModel !== 'undefined') {
            selectedText2ImgModel = modelName;
        }
        Settings.set('selectedText2ImgModel', modelName);
    }

    // Reset le flag de préchargement pour forcer le rechargement du bon modèle
    if (typeof resetImageModelLoaded === 'function') {
        resetImageModelLoaded();
    }

    // Notifier le serveur du changement
    apiPost('/api/log/model-change', { model: modelName, type: 'image', previous: previousModel }).catch(() => {});

    // Mettre à jour l'UI du picker (seulement le picker home, pas le chat!)
    const displayName = modelName.replace(' Inpaint', '').replace(' v9', '');
    const homeText = document.getElementById('selected-model-text');
    if (homeText) homeText.textContent = displayName;
    const modelSelect = document.getElementById('model-select');
    if (modelSelect) modelSelect.value = modelName;
    // Note: Ne PAS toucher à chat-selected-model-text ici, c'est pour le chat model

    // Re-render la liste pour mettre à jour les boutons
    const installedList = document.getElementById('image-installed-models');
    if (installedList && allImageModels.length > 0) {
        const installed = allImageModels.filter(m => m.downloaded && (isAdultSurfaceEnabled() || !isAdultImageSurfaceModel(m)));
        installedList.innerHTML = installed.map(model => renderImageModelItem(model, true)).join('');
        if (window.lucide) lucide.createIcons();
    }

    Toast.success(t('settings.models.imageEquippedTitle', 'Modèle équipé'), t('settings.models.imageEquippedBody', '{model} est maintenant actif', { model: modelName }), 2000);
}

// Télécharger un modèle image avec suivi de progression
function downloadImageModelFromButton(button) {
    const modelKey = button?.dataset?.modelKey || '';
    if (!modelKey) return;
    downloadImageModel(modelKey, button);
}

async function downloadImageModel(modelKey, sourceButton = null) {
    const btn = sourceButton || event?.target;
    const modelItem = btn?.closest('.ollama-model-item');

    if (btn) {
        btn.disabled = true;
        btn.textContent = t('settings.models.checking', 'Vérification...');
    }

    const result = await apiModels.download(modelKey);
    if (!result.ok) {
        Toast.error(t('common.error', 'Erreur'), result.error);
        if (btn) {
            btn.disabled = false;
            btn.textContent = t('settings.models.download', 'Télécharger');
        }
        return;
    }

    const data = result.data;
    if (data.success) {
        // Cas 1: Modèle déjà en cache
        if (data.message === 'already_cached') {
            Toast.success(t('settings.models.alreadyInstalledTitle', 'Déjà présent'), t('settings.models.alreadyInstalledBody', 'Ce modèle est déjà sur la machine'), 3000);
            // Rafraîchir la liste locale.
            checkModelsStatus();
            return;
        }

        // Cas 2: Téléchargement démarré
        // Ajouter la classe downloading et la barre de progression
        if (modelItem) {
            modelItem.classList.add('downloading');
            if (!modelItem.querySelector('.download-progress')) {
                const progressHtml = `
                    <div class="download-progress">
                        <div class="download-status">${escapeHtml(t('settings.models.downloadInProgress', 'Téléchargement en cours...'))}</div>
                        <div class="progress-bar">
                            <div class="progress-bar-fill" style="width: 0%"></div>
                        </div>
                        <div class="progress-text">0%</div>
                    </div>
                `;
                modelItem.insertAdjacentHTML('beforeend', progressHtml);
            }
        }
        if (btn) btn.textContent = t('settings.models.inProgress', 'En cours...');

        Toast.info(t('settings.models.downloadStartedTitle', 'Téléchargement'), t('settings.models.downloadStartedBody', 'Téléchargement démarré (~6 GB)'), 5000);

        // Polling pour vérifier quand c'est terminé
        pollImageModelDownload(modelKey, btn, modelItem);
    } else {
        Toast.error(t('common.error', 'Erreur'), data.error || t('settings.models.startFailed', 'Échec du démarrage'));
        if (btn) {
            btn.disabled = false;
            btn.textContent = t('settings.models.download', 'Télécharger');
        }
    }
}

// Polling pour suivre le téléchargement d'un modèle image
async function pollImageModelDownload(modelKey, btn, modelItem) {
    let lastProgress = 0;

    const checkInterval = setInterval(async () => {
        const result = await apiModels.checkModels();
        if (!result.ok) {
            console.error('Poll error:', result.error);
            return;
        }

        const data = result.data;
        if (data.success && data.models) {
            const model = data.models.find(m => m.key === modelKey);

            if (model) {
                // Mettre à jour la progress bar si downloading
                if (model.downloading && modelItem) {
                    const progressFill = modelItem.querySelector('.progress-bar-fill');
                    const statusText = modelItem.querySelector('.download-status');
                    const progressText = modelItem.querySelector('.progress-text');

                    const progress = model.progress || 0;
                    if (progressFill) progressFill.style.width = `${progress}%`;

                    // Afficher la taille téléchargée / totale
                    const downloadedGB = (model.downloaded_bytes || 0) / (1024 * 1024 * 1024);
                    const totalGB = (model.total_bytes || 0) / (1024 * 1024 * 1024);

                    if (totalGB > 0) {
                        if (statusText) statusText.textContent = `${downloadedGB.toFixed(1)} GB / ${totalGB.toFixed(1)} GB`;
                        if (progressText) progressText.textContent = `${progress}%`;
                    } else {
                        if (statusText) statusText.textContent = t('settings.models.downloadInProgress', 'Téléchargement en cours...');
                        if (progressText) progressText.textContent = `${progress}%`;
                    }

                    lastProgress = progress;
                }

                // Téléchargement terminé ! (vérifié côté serveur avec check_model_downloaded)
                if (model.downloaded && !model.downloading) {
                    clearInterval(checkInterval);
                    Toast.success(t('settings.models.downloadDoneTitle', 'Téléchargement terminé'), t('settings.models.imageDownloadedBody', '{model} téléchargé avec succès !', { model: model.name }));

                    // Rafraîchir la liste
                    checkModelsStatus();
                }
            }
        }
    }, 2000); // Vérifier toutes les 2 secondes

    // Timeout après 30 minutes (modèles ~6GB)
    setTimeout(() => {
        clearInterval(checkInterval);
        if (btn && btn.textContent === t('settings.models.inProgress', 'En cours...')) {
            btn.textContent = t('settings.models.verifyAction', 'Vérifier');
            btn.disabled = false;
            Toast.info(t('onboarding.statusInfo', 'Info'), t('settings.models.verifyDownloadInfo', 'Vérifiez si le téléchargement est terminé'));
        }
    }, 30 * 60 * 1000);
}

// Supprimer un modèle image HuggingFace
function deleteImageModelFromButton(button) {
    const modelKey = button?.dataset?.modelKey || '';
    const modelName = button?.dataset?.modelName || '';
    if (!modelKey) return;
    deleteImageModel(modelKey, modelName, button);
}

async function deleteImageModel(modelKey, modelName, sourceButton = null) {
    const confirmed = await JoyDialog.confirm(t('settings.models.deleteImageConfirm', 'Supprimer le modèle "{model}" ?\n\nCela libérera l’espace disque.', { model: modelName }), { variant: 'danger' });
    if (!confirmed) return;

    const btn = sourceButton || event?.target;
    if (btn) {
        btn.disabled = true;
        btn.textContent = t('settings.models.deleting', 'Suppression...');
    }

    const result = await apiModels.delete(modelKey);
    if (result.ok && result.data?.success) {
        Toast.success(t('settings.models.deletedTitle', 'Supprimé'), t('settings.models.deletedBody', '{model} a été supprimé', { model: modelName }));
        // Rafraîchir la liste
        checkModelsStatus();
    } else {
        Toast.error(t('common.error', 'Erreur'), result.data?.error || result.error || t('settings.models.deleteFailed', 'Échec de la suppression'));
        if (btn) {
            btn.disabled = false;
            btn.textContent = t('common.delete', 'Supprimer');
        }
    }
}

// ========== OLLAMA MODELS ==========

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

        if (data.models && data.models.length > 0) {
            listEl.innerHTML = data.models.map(model => {
                const isEquipped = model.name === userSettings.chatModel;
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
                selectEl.innerHTML = data.models.map(model => {
                    const dn = typeof _formatModelName === 'function' ? _formatModelName(model.name) : model.name;
                    return `<option value="${model.name}">${dn}</option>`;
                }).join('');

                // Vérifier si le modèle sélectionné existe toujours
                const modelExists = data.models.some(m => m.name === userSettings.chatModel);
                if (!modelExists) {
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
                selectEl.innerHTML = `<option value="">${escapeHtml(t('settings.models.noModels', 'Aucun modèle'))}</option>`;
                userSettings.chatModel = '';
                saveSettings();
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
    if (oldModel) {
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
    const selectedModel = userSettings.chatModel;
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
    const result = await apiOllama.getModels();
    if (!result.ok) {
        console.error('Erreur validation modèle:', result.error);
        return;
    }

    const data = result.data;
    const selectEl = DOM.get('settings-chat-model');
    if (!selectEl) return;

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

let currentOnboardingStep = 1;
let selectedProfileType = null;
let onboardingDoctor = null;

function syncOnboardingProfileFromBackend(onboarding) {
    if (!onboarding) return;

    if (typeof onboarding.completed === 'boolean') {
        userProfile.hasCompletedOnboarding = onboarding.completed;
    }
    if (onboarding.profile_type) {
        userProfile.type = onboarding.profile_type;
    }
    if (typeof onboarding.profile_name === 'string') {
        userProfile.name = onboarding.profile_name;
    }

    const backendLocale = window.JoyBoyI18n?.normalizeLocale?.(onboarding.locale || '') || '';
    if (backendLocale) {
        const hasStoredLocale = window.JoyBoyI18n?.hasStoredLocale?.() === true;
        if (!hasStoredLocale && (onboarding.completed || backendLocale !== 'fr')) {
            window.JoyBoyI18n?.setLocale?.(backendLocale, { persist: true });
        } else {
            syncLocaleSelectors(getCurrentLocale());
        }
    }
    saveProfile();
}

function setOnboardingButtonState(step = currentOnboardingStep) {
    const nextBtn = document.getElementById('onboarding-next-btn');
    const skipBtn = document.getElementById('onboarding-skip-btn');
    if (!nextBtn || !skipBtn) return;

    nextBtn.classList.remove('hidden');
    skipBtn.classList.remove('hidden');

    if (step === 1) {
        setRuntimeText(nextBtn, 'onboarding.step1Continue', 'Continuer');
        setRuntimeText(skipBtn, 'onboarding.skip', 'Passer');
        nextBtn.disabled = !selectedProfileType;
    } else if (step === 2) {
        setRuntimeText(nextBtn, 'onboarding.step2Continue', 'Continuer');
        setRuntimeText(skipBtn, 'onboarding.skip', 'Passer');
        nextBtn.disabled = false;
    } else if (step === 3) {
        if (!nextBtn.classList.contains('hidden')) {
            setRuntimeText(skipBtn, 'onboarding.step3Skip', 'Installer plus tard');
        }
    }
}

async function checkOnboarding() {
    const forceOnboarding = sessionStorage.getItem('forceOnboardingAfterReset') === '1';
    if (forceOnboarding) {
        sessionStorage.removeItem('forceOnboardingAfterReset');
        try {
            await apiSettings.resetOnboarding();
            userProfile.hasCompletedOnboarding = false;
            saveProfile();
        } catch (error) {
            console.warn('[ONBOARDING] Reset forcé impossible:', error);
        }
    }

    // Charger le profil sauvegardé
    const savedProfile = localStorage.getItem('userProfile');
    if (savedProfile) {
        try {
            userProfile = JSON.parse(savedProfile);
        } catch (e) {
            console.error('Erreur chargement profil:', e);
        }
    }

    const localNeedsOnboarding = !userProfile.hasCompletedOnboarding;
    if (localNeedsOnboarding) {
        // Show the setup UI immediately from local state. The backend sync runs
        // after this, so first launch no longer waits for Doctor/model checks.
        document.body.classList.add('app-hidden');
        openOnboarding();
    }

    try {
        const result = await apiSettings.getOnboardingStatus();
        if (result.ok && result.data?.success) {
            syncOnboardingProfileFromBackend(result.data.onboarding);
            onboardingDoctor = result.data.doctor || null;
        }
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de charger l’état backend:', error);
    }

    if (userProfile.hasCompletedOnboarding) {
        // Local storage can be stale after resets, browser clears, or public-core
        // regeneration. If we opened instantly from stale local state, tear it down
        // without replaying the full close animation.
        if (localNeedsOnboarding) {
            const modal = document.getElementById('onboarding-modal');
            modal?.classList.remove('open', 'closing');
            document.removeEventListener('keydown', handleOnboardingKeydown);
            document.querySelectorAll('.lightning-bolt').forEach(bolt => bolt.remove());
        }
        document.body.classList.remove('app-hidden');
        return;
    }

    // If the backend says onboarding is still needed but localStorage was stale,
    // open it now. Usually the local path above already handled this instantly.
    if (!localNeedsOnboarding) {
        document.body.classList.add('app-hidden');
        openOnboarding();
    } else {
        document.body.classList.add('app-hidden');
    }
}

function createLightningBolt() {
    const bolt = document.createElement('div');
    bolt.className = 'lightning-bolt';
    // Realistic zigzag lightning path from top to bottom-right
    bolt.innerHTML = `
        <svg viewBox="0 0 300 500" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="lightning-gradient" x1="0%" y1="0%" x2="50%" y2="100%">
                    <stop offset="0%" style="stop-color:#fff;stop-opacity:1" />
                    <stop offset="40%" style="stop-color:#93c5fd;stop-opacity:1" />
                    <stop offset="100%" style="stop-color:#3b82f6;stop-opacity:1" />
                </linearGradient>
            </defs>
            <path d="M50,0 L60,80 L30,85 L70,160 L35,170 L90,260 L50,270 L120,360 L75,375 L150,500" />
        </svg>
    `;
    document.body.appendChild(bolt);

    // Strike quickly after the modal appears; the old multi-second delay made
    // first setup feel like it was waiting on work that had already finished.
    setTimeout(() => {
        bolt.classList.add('strike');
    }, 430);

    // Remove after animation
    setTimeout(() => {
        bolt.remove();
    }, 980);
}

// Keyboard handler for onboarding
function handleOnboardingKeydown(e) {
    if (e.key === 'Enter') {
        const nextBtn = document.getElementById('onboarding-next-btn');
        if (nextBtn && !nextBtn.disabled && !nextBtn.classList.contains('hidden')) {
            e.preventDefault();
            nextOnboardingStep();
        }
    }
}

function ensureOnboardingLayout() {
    const content = document.querySelector('.onboarding-content');
    if (!content || content.querySelector('.onboarding-scroll')) return;

    const actions = content.querySelector('.onboarding-actions');
    const directSteps = Array.from(content.children).filter(child => child.classList?.contains('onboarding-step'));
    if (!actions || directSteps.length === 0) return;

    const scroll = document.createElement('div');
    scroll.className = 'onboarding-scroll';
    content.insertBefore(scroll, actions);
    directSteps.forEach(step => scroll.appendChild(step));
}

function resetOnboardingScroll() {
    const scroll = document.querySelector('.onboarding-scroll');
    if (scroll) scroll.scrollTo({ top: 0, behavior: 'smooth' });
}

function openOnboarding() {
    currentOnboardingStep = 1;
    selectedProfileType = userProfile.type || 'casual';
    benchmarkData = null;

    // Hide the app while onboarding is active
    document.body.classList.add('app-hidden');

    // Save and clear placeholder for later animation
    const input = document.getElementById('prompt-input');
    if (input) {
        originalPlaceholder = input.placeholder;
        input.placeholder = '';
    }

    ensureOnboardingLayout();
    resetOnboardingScroll();
    document.getElementById('onboarding-modal').classList.add('open');
    syncLocaleSelectors(getCurrentLocale());

    // Create lightning effect
    createLightningBolt();

    // Add keyboard listener for Enter key
    document.addEventListener('keydown', handleOnboardingKeydown);
    document.getElementById('onboarding-step-1').classList.remove('hidden');
    document.getElementById('onboarding-step-2').classList.add('hidden');
    document.getElementById('onboarding-step-3').classList.add('hidden');

    setOnboardingButtonState(1);

    // Reset step 3 UI
    const circularProgress = document.getElementById('setup-progress');
    circularProgress.classList.remove('analyzing', 'complete', 'error');
    setProgress(0);
    setRuntimeText('setup-label', 'onboarding.analysing', 'Analyse...');
    document.getElementById('hardware-info').classList.add('hidden');
    document.getElementById('setup-eta').classList.add('hidden');
    setRuntimeText('setup-status', 'onboarding.detectHardware', 'Détection du matériel...');

    // Reset selections & dots
    document.querySelectorAll('.profile-option').forEach(opt => {
        const selected = opt.dataset.type === selectedProfileType;
        opt.classList.toggle('selected', selected);
    });
    document.getElementById('onboarding-name').value = userProfile.name || '';
    updateOnboardingDots(1);
    initOnboardingDots();
    setOnboardingButtonState(1);
}

function closeOnboarding() {
    const modal = document.getElementById('onboarding-modal');
    modal.classList.add('closing');

    // Remove keyboard listener
    document.removeEventListener('keydown', handleOnboardingKeydown);

    // Keep the close transition snappy; onboarding is a setup utility, not a cutscene.
    setTimeout(() => {
        modal.classList.remove('open');
        modal.classList.remove('closing');

        // Reveal the app with animation
        document.body.classList.remove('app-hidden');
        document.body.classList.add('app-revealing');

        // Start placeholder animation sooner (during reveal)
        setTimeout(() => {
            animatePlaceholder();
        }, 80);

        // Clean up after reveal animation
        setTimeout(() => {
            document.body.classList.remove('app-revealing');
        }, 450);
    }, 190);
}

// Store original placeholder for typing animation
let originalPlaceholder = '';
let placeholderAnimationRunning = false;

// Typing animation for placeholder
function animatePlaceholder() {
    const input = document.getElementById('prompt-input');
    if (!input || !originalPlaceholder) return;

    // Éviter les animations multiples simultanées
    if (placeholderAnimationRunning) {
        console.log('[ANIM] Animation déjà en cours, skip');
        return;
    }
    placeholderAnimationRunning = true;

    input.placeholder = '';
    let index = 0;

    function typeChar() {
        if (index < originalPlaceholder.length) {
            input.placeholder += originalPlaceholder[index];
            index++;
            setTimeout(typeChar, 30 + Math.random() * 20);
        } else {
            placeholderAnimationRunning = false;
            // Activate send button glow + pulse
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) {
                sendBtn.classList.add('invite-glow');
                setTimeout(() => {
                    sendBtn.classList.add('entrance-pulse');
                    setTimeout(() => sendBtn.classList.remove('entrance-pulse'), 600);
                }, 50);
                // Focus input to invite user to type
                input.focus();
                // Remove invite glow once user starts typing
                input.addEventListener('input', function removeGlow() {
                    sendBtn.classList.remove('invite-glow');
                    input.removeEventListener('input', removeGlow);
                }, { once: true });
            }
        }
    }

    // Start typing after a small delay
    setTimeout(typeChar, 300);
}

function selectProfileType(type) {
    selectedProfileType = type;

    // Update UI
    document.querySelectorAll('.profile-option').forEach(opt => {
        opt.classList.remove('selected');
        if (opt.dataset.type === type) {
            opt.classList.add('selected');
        }
    });

    // Enable next button
    document.getElementById('onboarding-next-btn').disabled = false;
}

function updateOnboardingDots(step) {
    document.querySelectorAll('.onboarding-dot').forEach(dot => {
        const dotStep = parseInt(dot.dataset.step);
        dot.classList.remove('active', 'done');
        if (dotStep === step) {
            dot.classList.add('active');
        } else if (dotStep < step) {
            dot.classList.add('done');
        }
    });
}

function goToOnboardingStep(targetStep) {
    if (targetStep >= currentOnboardingStep || targetStep < 1) return;

    const currentEl = document.getElementById(`onboarding-step-${currentOnboardingStep}`);
    const targetEl = document.getElementById(`onboarding-step-${targetStep}`);

    // Fade out current (slide right = going back)
    currentEl.classList.add('fade-out-reverse');
    setTimeout(() => {
        currentEl.classList.add('hidden');
        currentEl.classList.remove('fade-out-reverse');
        targetEl.classList.remove('hidden');
        // Re-init lucide icons if needed
        if (window.lucide) lucide.createIcons({ nodes: [targetEl] });

        // Restore button states for target step
        const nextBtn = document.getElementById('onboarding-next-btn');
        const skipBtn = document.getElementById('onboarding-skip-btn');
        nextBtn.classList.remove('hidden');

        if (targetStep === 1) {
            setOnboardingButtonState(1);
        } else if (targetStep === 2) {
            setOnboardingButtonState(2);
        }

        currentOnboardingStep = targetStep;
        updateOnboardingDots(targetStep);
        resetOnboardingScroll();
    }, 250);
}

// Init dot click listeners
function initOnboardingDots() {
    document.querySelectorAll('.onboarding-dot').forEach(dot => {
        dot.addEventListener('click', () => {
            const targetStep = parseInt(dot.dataset.step);
            if (targetStep < currentOnboardingStep) {
                goToOnboardingStep(targetStep);
            }
        });
    });
}

function nextOnboardingStep() {
    const step1 = document.getElementById('onboarding-step-1');
    const step2 = document.getElementById('onboarding-step-2');
    const step3 = document.getElementById('onboarding-step-3');

    if (currentOnboardingStep === 1) {
        step1.classList.add('fade-out');
        setTimeout(() => {
            step1.classList.add('hidden');
            step1.classList.remove('fade-out');
            step2.classList.remove('hidden');
            if (window.lucide) lucide.createIcons({ nodes: [step2] });
            setOnboardingButtonState(2);
            resetOnboardingScroll();
            document.getElementById('onboarding-name').focus();
        }, 250);
        currentOnboardingStep = 2;
        updateOnboardingDots(2);
    } else if (currentOnboardingStep === 2) {
        step2.classList.add('fade-out');
        setTimeout(() => {
            step2.classList.add('hidden');
            step2.classList.remove('fade-out');
            step3.classList.remove('hidden');
            document.getElementById('onboarding-next-btn').classList.add('hidden');
            setOnboardingButtonState(3);
            resetOnboardingScroll();
            startBenchmark();
        }, 250);
        currentOnboardingStep = 3;
        updateOnboardingDots(3);
    } else {
        completeOnboarding();
    }
}

// ========== HARDWARE BENCHMARK & SETUP ==========

let benchmarkData = null;
let hardwareInfo = null;
let setupCheckInterval = null;

// Tailles approximatives des modèles (en GB)
const MODEL_SIZES = {
    'qwen3.5:0.8b': 1.0,
    'qwen3.5:2b': 2.7,
    'qwen3.5:4b': 3.4,
    'qwen3.5:9b': 6.6,
    'qwen3:0.6b': 0.6,
    'qwen3:1.7b': 1.4,
    'qwen3:4b': 2.6,
    'qwen2.5:0.5b': 0.4,
    'qwen2.5:1.5b': 1.0,
    'qwen2.5:3b': 2.0,
    'qwen2.5:7b': 4.5,
    'qwen2.5-coder:1.5b': 1.0,
    'qwen2.5-coder:3b': 2.0,
    'qwen2.5-coder:7b': 4.5,
    'mistral:7b': 4.1,
    'dolphin-mistral:7b': 4.1,
};

function getModelSize(modelName) {
    return MODEL_SIZES[modelName] || 2.0; // Default 2GB
}

function calculateETA(modelNames) {
    // Calculer la taille totale
    let totalGB = 0;
    for (const model of modelNames) {
        totalGB += getModelSize(model);
    }
    // Estimation: ~1-2 min par GB (connexion moyenne)
    const minutes = Math.ceil(totalGB * 1.5);
    if (minutes < 1) return '< 1 min';
    if (minutes === 1) return '~1 min';
    return `~${minutes} min`;
}

function _doctorStatusLabel(status) {
    if (status === 'ok') return t('onboarding.statusOk', 'OK');
    if (status === 'warning') return t('onboarding.statusWarning', 'À revoir');
    if (status === 'error') return t('onboarding.statusError', 'Bloquant');
    return t('onboarding.statusInfo', 'Info');
}

function _normalizeDoctorStatus(status) {
    return ['ok', 'warning', 'error'].includes(status) ? status : 'warning';
}

function _doctorSummaryText(doctorData) {
    const status = _normalizeDoctorStatus(doctorData?.status);
    if (status === 'ok') {
        return t('onboarding.doctorSummaryOk', 'JoyBoy est prêt sur cette machine.');
    }
    if (status === 'error' || doctorData?.ready === false) {
        return t('onboarding.doctorSummaryError', 'JoyBoy a besoin de corrections avant de démarrer correctement.');
    }
    return t('onboarding.doctorSummaryWarningReady', 'JoyBoy peut démarrer, mais quelques points méritent d’être corrigés pour un setup public propre.');
}

function _doctorCheckDetail(check, fallbackKey, fallbackText) {
    if (!check) return t(fallbackKey, fallbackText);

    const detail = String(check.detail || '');
    const status = _normalizeDoctorStatus(check.status);

    if (check.key === 'providers') {
        const configured = detail.match(/(?:configurés?|configured)\s*:?\s*(.+)$/i);
        if (configured?.[1]) {
            return t('onboarding.providersConfigured', 'Configurés : {providers}', { providers: configured[1].trim() });
        }
        return status === 'ok'
            ? t('onboarding.providersReady', 'Providers configurés.')
            : t('onboarding.providersHint', 'Configure Hugging Face ou CivitAI dans Paramètres > Modèles.');
    }

    if (check.key === 'ollama') {
        const lower = detail.toLowerCase();
        if (lower.includes('non démarr') || lower.includes('not running')) {
            return t('onboarding.ollamaInstalledStopped', 'Ollama est installé mais non démarré.');
        }
        if (lower.includes('pas installé') || lower.includes('not installed')) {
            return t('onboarding.ollamaMissing', 'Service non détecté.');
        }
        return status === 'ok'
            ? t('onboarding.ollamaReady', 'Ollama est prêt.')
            : (detail || t('onboarding.ollamaMissing', 'Service non détecté.'));
    }

    if (check.key === 'packs') {
        const activePack = detail.match(/(?:pack local avanc[ée] actif|active local pack)\s*:?\s*(.+)$/i);
        if (activePack?.[1]) {
            return t('onboarding.packsActive', 'Pack local actif : {pack}', { pack: activePack[1].trim() });
        }
        return status === 'ok'
            ? t('onboarding.packsReady', 'Packs locaux prêts.')
            : t('onboarding.packsMissing', 'Aucun pack local actif.');
    }

    if (check.key === 'storage') {
        const storage = detail.match(/([\d.,]+)\s*GB\s+(?:libres|free)\s*[·-]\s*(?:config locale|local config)\s*(.+)$/i);
        if (storage?.[1]) {
            return t('onboarding.storageReady', '{free} GB libres · config locale {path}', {
                free: storage[1],
                path: storage[2]?.trim() || '',
            });
        }
        return status === 'ok'
            ? t('onboarding.storageOk', 'Stockage prêt.')
            : t('onboarding.storageUnknown', 'État stockage indisponible.');
    }

    if (check.key === 'models') {
        return status === 'ok'
            ? t('onboarding.modelsReady', 'Modèles de base détectés.')
            : t('onboarding.modelsMissing', 'Aucun modèle de base détecté.');
    }

    return detail || t(fallbackKey, fallbackText);
}

function _doctorCheckLabel(check) {
    if (!check) return '';
    return t(`doctor.check.${check.key}`, check.label || check.key);
}

function renderOnboardingReadiness(doctorData) {
    const wrapper = document.getElementById('onboarding-readiness');
    const grid = document.getElementById('onboarding-readiness-grid');
    const note = document.getElementById('onboarding-readiness-note');
    if (!wrapper || !grid) return;

    if (!doctorData || !Array.isArray(doctorData.checks)) {
        wrapper.classList.add('hidden');
        grid.innerHTML = '';
        return;
    }

    const checksByKey = Object.fromEntries(
        doctorData.checks.map(check => [check.key, check])
    );

    const cards = [
        {
            label: t('onboarding.doctorCard', 'Doctor'),
            status: _normalizeDoctorStatus(doctorData.status),
            detail: _doctorSummaryText(doctorData),
            full: true,
        },
        {
            label: t('onboarding.providersCard', 'Providers'),
            status: _normalizeDoctorStatus(checksByKey.providers?.status),
            detail: _doctorCheckDetail(checksByKey.providers, 'onboarding.providersHint', 'Configure Hugging Face ou CivitAI dans Paramètres > Modèles.'),
        },
        {
            label: t('onboarding.ollamaCard', 'Ollama'),
            status: _normalizeDoctorStatus(checksByKey.ollama?.status),
            detail: _doctorCheckDetail(checksByKey.ollama, 'onboarding.ollamaMissing', 'Service non détecté.'),
        },
        {
            label: t('onboarding.packsCard', 'Packs'),
            status: _normalizeDoctorStatus(checksByKey.packs?.status),
            detail: _doctorCheckDetail(checksByKey.packs, 'onboarding.packsMissing', 'Aucun pack local actif.'),
        },
        {
            label: t('onboarding.storageCard', 'Stockage'),
            status: _normalizeDoctorStatus(checksByKey.storage?.status),
            detail: _doctorCheckDetail(checksByKey.storage, 'onboarding.storageUnknown', 'État stockage indisponible.'),
        },
    ];

    grid.innerHTML = cards.map(card => `
        <div class="onboarding-readiness-card ${card.full ? 'full' : ''}">
            <div class="onboarding-readiness-head">
                <div class="onboarding-readiness-label">${escapeHtml(card.label)}</div>
                <div class="onboarding-status-pill ${escapeHtml(card.status)}">${escapeHtml(_doctorStatusLabel(card.status))}</div>
            </div>
            <div class="onboarding-readiness-detail">${escapeHtml(card.detail)}</div>
        </div>
    `).join('');

    if (note) {
        note.textContent = doctorData.status === 'ok'
            ? t('onboarding.setupNoteReady', 'Tout est déjà bien aligné. Tu pourras toujours affiner providers, modèles et packs dans Paramètres > Modèles.')
            : t('onboarding.setupNoteAction', 'Le wizard prépare le terrain. Tu pourras finaliser providers, packs locaux et imports de modèles dans Paramètres > Modèles.');
    }

    wrapper.classList.remove('hidden');
}

async function startBenchmark() {
    const progressLabel = document.getElementById('setup-label');
    const setupStatus = document.getElementById('setup-status');
    const circularProgress = document.getElementById('setup-progress');

    // Start analyzing animation
    circularProgress.classList.add('analyzing');
    setProgress(10);
    setRuntimeText(progressLabel, 'onboarding.analysing', 'Analyse...');
    renderOnboardingReadiness(onboardingDoctor);

    // Profil sélectionné (ou casual par défaut)
    const profile = selectedProfileType || 'casual';

    try {
        const onboardingStatus = await apiSettings.getOnboardingStatus();
        if (onboardingStatus.ok && onboardingStatus.data?.doctor) {
            onboardingDoctor = onboardingStatus.data.doctor;
            renderOnboardingReadiness(onboardingDoctor);
        }

        // Step 1: Get hardware info and profile-based recommendations
        setRuntimeText(setupStatus, 'onboarding.detectHardware', 'Détection du matériel...');
        const hwResult = await apiGet('/api/hardware/info');
        if (!hwResult.ok) throw new Error(hwResult.error || 'Hardware info failed');
        hardwareInfo = hwResult.data;

        setProgress(30);

        // Le modèle recommandé pour ce profil + VRAM
        const recommendedModel = hardwareInfo.recommendations[profile] || hardwareInfo.recommendations['casual'];

        // Show hardware info
        document.getElementById('hw-gpu').textContent = hardwareInfo.gpu || 'CPU';
        document.getElementById('hw-vram').textContent = hardwareInfo.vram_gb > 0
            ? `${hardwareInfo.vram_gb.toFixed(1)} GB (${hardwareInfo.vram_level})`
            : '-';
        document.getElementById('hw-ram').textContent = hardwareInfo.ram_gb
            ? `${hardwareInfo.ram_gb} GB`
            : '-';
        document.getElementById('hw-model').textContent = recommendedModel;

        // Show quality level based on VRAM
        const genSettings = hardwareInfo.generation_settings;
        const qualityEl = document.getElementById('hw-quality');
        if (qualityEl && genSettings) {
            qualityEl.textContent = `${getOnboardingQualityLabel(hardwareInfo.vram_level)} (${genSettings.steps} steps)`;
        }

        // Show image model
        const imageModels = hardwareInfo.image_models;
        const imageModelEl = document.getElementById('hw-image-model');
        if (imageModelEl && imageModels) {
            imageModelEl.textContent = localizeModelDisplayName(imageModels.inpainting?.replace(' Inpaint', '') || '-');
        }

        // Estimated inpainting time (first run / after warmup)
        // Calibrated on RTX 3070 Ti (8GB, "high"): ~16s first, ~12s after
        const genTimeEstimates = {
            'low': '~40s / ~30s',
            'medium': '~25s / ~18s',
            'high': '~16s / ~12s',
            'very_high': '~10s / ~7s',
            'ultra': '~6s / ~4s',
            'extreme': '~4s / ~3s'
        };
        const genTimeEl = document.getElementById('hw-gen-time');
        if (genTimeEl) {
            genTimeEl.textContent = genTimeEstimates[hardwareInfo.vram_level] || '~16s / ~12s';
        }

        document.getElementById('hardware-info').classList.remove('hidden');

        setProgress(40);
        circularProgress.classList.remove('analyzing');

        // Step 2: Check if models already installed
        setRuntimeText(setupStatus, 'onboarding.checkingModels', 'Vérification des modèles...');
        const modelsResult = await apiOllama.getModels();
        const modelsData = modelsResult.ok ? modelsResult.data : { models: [] };

        const utilityInstalled = modelsData.models?.some(m =>
            m.name === hardwareInfo.utility_model ||
            m.name.startsWith(hardwareInfo.utility_model.split(':')[0])
        );
        const chatInstalled = modelsData.models?.some(m =>
            m.name === recommendedModel ||
            m.name.startsWith(recommendedModel.split(':')[0])
        );

        if (utilityInstalled && chatInstalled) {
            // Both models already installed
            setProgress(100);
            circularProgress.classList.add('complete');
            setRuntimeText(progressLabel, 'common.ready', 'PRÊT');
            setRuntimeText(setupStatus, 'onboarding.modelsAlreadyInstalled', 'Modèles déjà installés!');
            setRuntimeText('setup-status', 'onboarding.allReady', 'Tout est prêt!');

            const doctorResult = await apiSettings.getDoctorReport();
            if (doctorResult.ok && doctorResult.data?.success) {
                onboardingDoctor = doctorResult.data;
                renderOnboardingReadiness(onboardingDoctor);
            }

            // Apply all recommended settings based on VRAM level
            userSettings.chatModel = recommendedModel;
            applyGenerationSettings(hardwareInfo.generation_settings);
            applyImageModels(hardwareInfo.image_models);
            saveSettings();

            // Show finish button
            setTimeout(() => {
                document.getElementById('onboarding-next-btn').classList.remove('hidden');
                setRuntimeText('onboarding-next-btn', 'onboarding.start', 'Commencer');
                document.getElementById('onboarding-next-btn').disabled = false;
                document.getElementById('onboarding-skip-btn').classList.add('hidden');
            }, 500);
        } else {
            // Need to download models
            setProgress(50);

            if (!utilityInstalled && !chatInstalled) {
                setRuntimeText(setupStatus, 'onboarding.downloadTwoModels', 'Téléchargement de 2 modèles...');
            } else if (!utilityInstalled) {
                setRuntimeText(setupStatus, 'onboarding.downloadUtility', 'Téléchargement du modèle utility...');
            } else {
                setRuntimeText(setupStatus, 'onboarding.downloadChat', 'Téléchargement du modèle chat...');
            }

            setRuntimeText('setup-status', 'onboarding.installInProgress', 'Installation en cours...');
            document.getElementById('setup-eta').classList.remove('hidden');

            // Calculer l'ETA basé sur les modèles à télécharger
            const modelsToDownload = [];
            if (!utilityInstalled) modelsToDownload.push(hardwareInfo.utility_model);
            if (!chatInstalled) modelsToDownload.push(recommendedModel);
            const etaText = calculateETA(modelsToDownload);
            const setupEta = document.getElementById('setup-eta');
            if (setupEta) {
                setRuntimeText(setupEta, 'onboarding.estimatedTime', 'Temps estimé : {eta}', { eta: etaText });
            }

            // Start profile-based download (utility + chat model)
            const setupResult = await apiPost('/api/setup/profile', { profile: profile });
            if (!setupResult.ok) throw new Error(setupResult.error || 'Setup failed');
            const setupData = setupResult.data;
            console.log('[SETUP] Started:', setupData);

            // Save the chat model that will be installed + generation settings
            benchmarkData = {
                recommended_text_model: setupData.chat_model,
                utility_model: setupData.utility_model,
                generation_settings: hardwareInfo.generation_settings,
                image_models: hardwareInfo.image_models
            };

            // Poll for progress
            setupCheckInterval = setInterval(checkSetupProgress, 500);
        }
    } catch (error) {
        console.error('Benchmark error:', error);
        circularProgress.classList.remove('analyzing');
        circularProgress.classList.add('error');
        setRuntimeText(progressLabel, 'onboarding.errorShort', 'Erreur');
        setPlainText(setupStatus, 'Erreur: ' + error.message);

        // Allow skip
        document.getElementById('onboarding-next-btn').classList.remove('hidden');
        setRuntimeText('onboarding-next-btn', 'onboarding.continueAnyway', 'Continuer quand même');
        document.getElementById('onboarding-next-btn').disabled = false;
    }
}

async function checkSetupProgress() {
    try {
        const result = await apiGet('/api/setup/progress');
        if (!result.ok) throw new Error(result.error);
        const data = result.data;

        const progressLabel = document.getElementById('setup-label');
        const setupStatus = document.getElementById('setup-status');
        const circularProgress = document.getElementById('setup-progress');

        if (data.status === 'downloading_utility') {
            // 0-40% pour utility model
            const visualProgress = Math.min(40, data.progress * 0.4);
            setProgress(50 + visualProgress * 0.5); // 50-70%
            progressLabel.textContent = data.progress + '%';
            setRuntimeText(setupStatus, 'onboarding.utilityProgress', 'Modèle utility : {message}', { message: data.message });
        } else if (data.status === 'downloading_chat') {
            // 40-100% pour chat model
            const visualProgress = 70 + (data.progress - 40) * 0.5; // 70-100%
            setProgress(Math.min(95, visualProgress));
            progressLabel.textContent = data.progress + '%';
            setRuntimeText(setupStatus, 'onboarding.chatProgress', 'Modèle chat : {message}', { message: data.message });
        } else if (data.status === 'downloading_text') {
            // Legacy: Map 0-100 download progress to 50-95 visual progress
            const visualProgress = 50 + (data.progress * 0.45);
            setProgress(visualProgress);
            progressLabel.textContent = data.progress + '%';
            setPlainText(setupStatus, data.message);
        } else if (data.status === 'complete') {
            clearInterval(setupCheckInterval);
            setProgress(100);
            circularProgress.classList.add('complete');
            setRuntimeText(progressLabel, 'common.ready', 'PRÊT');
            setRuntimeText(setupStatus, 'onboarding.completed', 'Installation terminée!');
            setRuntimeText('setup-status', 'onboarding.allReady', 'Tout est prêt!');
            document.getElementById('setup-eta').classList.add('hidden');

            const doctorResult = await apiSettings.getDoctorReport();
            if (doctorResult.ok && doctorResult.data?.success) {
                onboardingDoctor = doctorResult.data;
                renderOnboardingReadiness(onboardingDoctor);
            }

            // Apply all recommended settings based on VRAM level
            if (benchmarkData?.recommended_text_model) {
                userSettings.chatModel = benchmarkData.recommended_text_model;
            } else if (data.text_model) {
                userSettings.chatModel = data.text_model;
            }
            // Apply generation settings (steps, strength, segmentation method)
            if (benchmarkData?.generation_settings) {
                applyGenerationSettings(benchmarkData.generation_settings);
            }
            // Apply image models (inpainting, text2img)
            if (benchmarkData?.image_models) {
                applyImageModels(benchmarkData.image_models);
            }
            saveSettings();

            // Show finish button
            document.getElementById('onboarding-next-btn').classList.remove('hidden');
            setRuntimeText('onboarding-next-btn', 'onboarding.start', 'Commencer');
            document.getElementById('onboarding-next-btn').disabled = false;
            document.getElementById('onboarding-skip-btn').classList.add('hidden');
        } else if (data.status === 'error') {
            clearInterval(setupCheckInterval);
            circularProgress.classList.add('error');
            setRuntimeText(progressLabel, 'onboarding.errorShort', 'Erreur');
            setPlainText(setupStatus, data.error || t('onboarding.downloadError', 'Erreur de téléchargement'));
            document.getElementById('setup-eta').classList.add('hidden');

            // Allow continue anyway
            document.getElementById('onboarding-next-btn').classList.remove('hidden');
            setRuntimeText('onboarding-next-btn', 'onboarding.continueAnyway', 'Continuer quand même');
            document.getElementById('onboarding-next-btn').disabled = false;
        }
    } catch (e) {
        console.error('Progress check error:', e);
    }
}

function setProgress(percent) {
    const circle = document.getElementById('progress-circle');
    const percentEl = document.getElementById('setup-percent');

    // Circumference = 2 * PI * r = 2 * 3.14159 * 52 = 326.73
    const circumference = 326.73;
    const offset = circumference - (percent / 100) * circumference;

    circle.style.strokeDashoffset = offset;
    percentEl.textContent = Math.round(percent) + '%';
}

/**
 * Applique les paramètres de génération recommandés basés sur le niveau VRAM
 * @param {Object} settings - {steps, text2imgSteps, strength}
 */
function applyGenerationSettings(settings) {
    if (!settings) return;

    console.log('[SETUP] Application des paramètres optimisés:', settings);

    // Inpainting steps
    if (settings.steps) {
        userSettings.steps = settings.steps;
    }

    // Text2Img steps
    if (settings.text2imgSteps) {
        userSettings.text2imgSteps = settings.text2imgSteps;
    }

    // Denoising strength
    if (settings.strength) {
        userSettings.strength = settings.strength;
    }

    // NSFW strength
    if (settings.nsfwStrength) {
        userSettings.nsfwStrength = settings.nsfwStrength;
    }

    // Log le résumé
    console.log(`[SETUP] Config appliquée:
   • Inpaint steps: ${userSettings.steps}
   • Text2Img steps: ${userSettings.text2imgSteps}
   • Strength: ${Math.round(userSettings.strength * 100)}%
   • NSFW: ${Math.round((userSettings.nsfwStrength || 0.90) * 100)}%`);
}

/**
 * Applique les modèles image recommandés basés sur le niveau VRAM
 * @param {Object} imageModels - {inpainting, generation}
 */
function applyImageModels(imageModels) {
    if (!imageModels) return;

    console.log('[SETUP] Application des modèles image:', imageModels);

    // Modèle inpainting
    if (imageModels.inpainting) {
        if (typeof selectedInpaintModel !== 'undefined') {
            selectedInpaintModel = imageModels.inpainting;
        }
        Settings.set('selectedInpaintModel', imageModels.inpainting);
    }

    // Modèle text2img
    if (imageModels.generation) {
        if (typeof selectedText2ImgModel !== 'undefined') {
            selectedText2ImgModel = imageModels.generation;
        }
        Settings.set('selectedText2ImgModel', imageModels.generation);
    }

    console.log(`[SETUP] Modèles image:
   • Inpaint: ${imageModels.inpainting}
   • Text2Img: ${imageModels.generation}`);
}

async function skipOnboarding() {
    // Stop any running setup
    if (setupCheckInterval) {
        clearInterval(setupCheckInterval);
        setupCheckInterval = null;
    }
    apiPost('/api/setup/skip', {}).catch(() => {});

    // Si on a détecté le hardware, appliquer quand même les paramètres optimisés
    if (hardwareInfo?.generation_settings) {
        applyGenerationSettings(hardwareInfo.generation_settings);
        if (hardwareInfo?.image_models) {
            applyImageModels(hardwareInfo.image_models);
        }
        saveSettings();
        console.log('[SETUP] Paramètres optimisés appliqués malgré le skip');
    }

    userProfile.hasCompletedOnboarding = true;
    userProfile.type = selectedProfileType || 'casual';
    saveProfile();

    try {
        await apiSettings.completeOnboarding({
            completed: true,
            locale: document.documentElement.lang || 'fr',
            profile_type: userProfile.type,
            profile_name: userProfile.name || ''
        });
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de marquer le skip côté backend:', error);
    }

    // Close and reveal
    closeOnboarding();
}

async function completeOnboarding() {
    const name = document.getElementById('onboarding-name').value.trim();

    userProfile.hasCompletedOnboarding = true;
    userProfile.type = selectedProfileType || 'casual';
    userProfile.name = name;

    saveProfile();

    try {
        await apiSettings.completeOnboarding({
            completed: true,
            locale: document.documentElement.lang || 'fr',
            profile_type: userProfile.type,
            profile_name: userProfile.name || ''
        });
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de finaliser côté backend:', error);
    }

    closeOnboarding();

    // Petit message de bienvenue
    console.log(`Profil configuré: ${userProfile.type}${name ? `, ${name}` : ''}`);
}

function saveProfile() {
    localStorage.setItem('userProfile', JSON.stringify(userProfile));
}

function loadProfile() {
    const saved = localStorage.getItem('userProfile');
    if (saved) {
        try {
            userProfile = { ...userProfile, ...JSON.parse(saved) };
        } catch (e) {
            console.error('Erreur chargement profil:', e);
        }
    }
}

// Récupérer le system prompt basé sur le profil
function getProfileSystemPrompt() {
    const basePrompt = PROFILE_PROMPTS[userProfile.type] || PROFILE_PROMPTS.casual;

    if (userProfile.name) {
        return basePrompt + `\n\nIMPORTANT: La personne qui te parle s'appelle ${userProfile.name}. Utilise son prénom quand c'est approprié. Toi tu es ${APP_CONFIG.name}, un assistant IA.`;
    }

    return basePrompt;
}

// Récupérer les infos de profil pour l'API
function getProfileForAI() {
    return {
        type: userProfile.type,
        name: userProfile.name,
        systemPrompt: getProfileSystemPrompt()
    };
}

// Changer le type de profil depuis les settings
function changeProfileType(type) {
    userProfile.type = type;
    saveProfile();
    updateProfileUI();
}

// Changer le prénom depuis les settings
function changeProfileName(name) {
    userProfile.name = name.trim();
    saveProfile();
}

// Mettre à jour l'UI du profil dans les settings
function updateProfileUI() {
    // Mettre à jour les options de profil
    document.querySelectorAll('.settings-profile-option').forEach(opt => {
        opt.classList.remove('selected');
        if (opt.dataset.type === userProfile.type) {
            opt.classList.add('selected');
        }
    });

    // Mettre à jour le champ nom
    const nameInput = document.getElementById('settings-profile-name');
    if (nameInput) {
        nameInput.value = userProfile.name || '';
    }
    syncLocaleSelectors(getCurrentLocale());
}

// Relancer l'onboarding
async function restartOnboarding() {
    userProfile.hasCompletedOnboarding = false;
    saveProfile();
    try {
        await apiSettings.resetOnboarding();
    } catch (error) {
        console.warn('[ONBOARDING] Reset backend impossible:', error);
    }
    closeSettings();
    openOnboarding();
}

// Initialiser l'onglet profil quand on l'ouvre
function initProfileTab() {
    updateProfileUI();
}

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

// Initialiser l'onglet terminal
function initTerminalTab() {
    // Peupler le select des modèles terminal
    populateTerminalModelSelect();

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


// ===== GALLERY / STORAGE =====

let _galleryFiles = [];
let _galleryFilter = 'all';
let _galleryCurrentItem = null;
let _galleryCurrentList = [];
let _galleryCurrentIndex = -1;
let _galleryStats = null;
let _galleryViewerZoom = 1;

function galleryT(key, params = {}, fallback = '') {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function getGallerySourceLabel(source) {
    const mapping = {
        imagine: galleryT('settings.storage.sourceImagine', {}, 'Générée'),
        modified: galleryT('settings.storage.sourceModified', {}, 'Modifiée'),
        video: galleryT('settings.storage.sourceVideo', {}, 'Vidéo'),
    };
    return mapping[source] || source;
}

function escapeGalleryHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getGalleryModelLabel(file) {
    return file?.model || file?.model_id || file?.metadata?.model || file?.metadata?.model_id || '';
}

function getGalleryPrompt(file) {
    return file?.prompt || file?.metadata?.prompt || file?.final_prompt || file?.metadata?.final_prompt || '';
}

function resetGalleryViewerZoom() {
    _galleryViewerZoom = 1;
    applyGalleryViewerZoom();
}

function applyGalleryViewerZoom(origin = '50% 50%') {
    const stage = document.getElementById('gallery-viewer-stage');
    const media = stage?.querySelector('.gallery-viewer-media');
    const hint = stage?.querySelector('.gallery-viewer-zoom-hint');
    if (!media) return;
    media.style.transform = `scale(${_galleryViewerZoom})`;
    media.style.transformOrigin = origin;
    media.classList.toggle('is-zoomed', _galleryViewerZoom !== 1);
    if (hint) {
        const base = galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer');
        hint.textContent = `${base} · ${Math.round(_galleryViewerZoom * 100)}%`;
    }
}

function handleGalleryViewerWheel(event) {
    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    if (!viewer?.classList.contains('is-open') || !stage?.contains(event.target) || !event.altKey) return;

    event.preventDefault();
    const media = stage.querySelector('.gallery-viewer-media');
    if (!media) return;

    const zoomFactor = event.deltaY < 0 ? 1.12 : 0.88;
    _galleryViewerZoom = Math.min(5, Math.max(0.5, _galleryViewerZoom * zoomFactor));
    if (Math.abs(_galleryViewerZoom - 1) < 0.04) _galleryViewerZoom = 1;

    const rect = media.getBoundingClientRect();
    const originX = rect.width ? ((event.clientX - rect.left) / rect.width) * 100 : 50;
    const originY = rect.height ? ((event.clientY - rect.top) / rect.height) * 100 : 50;
    applyGalleryViewerZoom(`${Math.max(0, Math.min(100, originX))}% ${Math.max(0, Math.min(100, originY))}%`);
}

function renderGalleryStats(stats = null) {
    const statsEl = document.getElementById('gallery-stats');
    if (!statsEl) return;

    if (!stats) {
        statsEl.innerHTML = `
            <div class="gallery-stat-card" style="--gallery-accent: rgba(96,165,250,0.22);">
                <span class="gallery-stat-value">...</span>
                <span class="gallery-stat-label">${galleryT('settings.storage.loading', {}, 'Chargement de la galerie...')}</span>
            </div>
        `;
        return;
    }

    const cards = [
        { value: stats.total, label: galleryT('settings.storage.totalLabel', {}, 'Fichiers'), accent: 'rgba(34,197,94,0.2)' },
        { value: stats.images, label: galleryT('settings.storage.imagesLabel', {}, 'Images'), accent: 'rgba(59,130,246,0.2)' },
        { value: stats.videos, label: galleryT('settings.storage.videosLabel', {}, 'Vidéos'), accent: 'rgba(245,158,11,0.2)' },
        { value: `${stats.total_size_mb} MB`, label: galleryT('settings.storage.sizeLabel', {}, 'Stockage'), accent: 'rgba(168,85,247,0.22)' },
    ];

    statsEl.innerHTML = cards.map(card => `
        <div class="gallery-stat-card" style="--gallery-accent: ${card.accent};">
            <span class="gallery-stat-value">${card.value}</span>
            <span class="gallery-stat-label">${card.label}</span>
        </div>
    `).join('');
}

async function refreshGallery() {
    const gridEl = document.getElementById('gallery-grid');
    const refreshBtn = document.getElementById('gallery-refresh-btn');

    if (!gridEl) return;

    renderGalleryStats();
    if (gridEl) {
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="loader-2" class="spin"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.loading', {}, 'Chargement de la galerie...')}</div>
                <div class="gallery-empty-desc">${galleryT('settings.storage.subtitle', {}, '')}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
    }

    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const resp = await fetch('/api/gallery/list');
        const data = await resp.json();
        _galleryStats = data.stats;
        renderGalleryStats(data.stats);

        _galleryFiles = data.files;
        renderGalleryGrid();

    } catch (e) {
        console.error('[GALLERY] Error:', e);
        _galleryStats = {
            total: 0,
            images: 0,
            videos: 0,
            total_size_mb: 0,
        };
        renderGalleryStats({
            total: 0,
            images: 0,
            videos: 0,
            total_size_mb: 0,
        });
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="alert-triangle"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.loadError', {}, 'Erreur de chargement')}</div>
                <div class="gallery-empty-desc">${e?.message || ''}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function filterGallery(filter, btn) {
    _galleryFilter = filter;
    document.querySelectorAll('#gallery-filters .filter-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderGalleryGrid();
}

function getFilteredGalleryFiles() {
    return _galleryFilter === 'all'
        ? _galleryFiles
        : _galleryFiles.filter(f => f.source === _galleryFilter);
}

function renderGalleryGrid() {
    const gridEl = document.getElementById('gallery-grid');
    if (!gridEl) return;

    const filtered = getFilteredGalleryFiles();
    _galleryCurrentList = filtered;

    if (filtered.length === 0) {
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="images"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.emptyTitle', {}, 'La galerie est vide')}</div>
                <div class="gallery-empty-desc">${galleryT('settings.storage.emptyDesc', {}, 'Les générations sauvegardées apparaîtront ici avec aperçu, filtres et actions rapides.')}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
        return;
    }

    gridEl.innerHTML = filtered.map((file, index) => {
        const badgeIcon = file.type === 'video' ? 'clapperboard' : (file.source === 'modified' ? 'wand-sparkles' : 'sparkles');
        const badgeLabel = escapeGalleryHtml(getGallerySourceLabel(file.source));
        const previewAlt = file.type === 'video'
            ? escapeGalleryHtml(galleryT('settings.storage.previewVideo', {}, 'Aperçu vidéo'))
            : escapeGalleryHtml(galleryT('settings.storage.previewImage', {}, 'Aperçu image'));
        const safePath = escapeGalleryHtml(file.path);
        const safeName = escapeGalleryHtml(file.name);
        const safeCreated = escapeGalleryHtml(file.created_str);
        const modelLabel = getGalleryModelLabel(file);
        const safeModel = escapeGalleryHtml(modelLabel);
        return `
            <article class="gallery-card" data-gallery-index="${index}">
                <div class="gallery-card-media">
                    ${file.type === 'video'
                        ? `<video src="${safePath}" muted preload="metadata" playsinline></video>`
                        : `<img src="${safePath}" alt="${previewAlt}">`
                    }
                    <div class="gallery-card-overlay"></div>
                    <div class="gallery-card-topbar">
                        <div class="gallery-kind-badge">
                            <i data-lucide="${badgeIcon}"></i>
                            <span>${badgeLabel}</span>
                        </div>
                        <div class="gallery-card-actions">
                            <button class="gallery-card-icon-btn" type="button" data-gallery-action="download" data-gallery-index="${index}" aria-label="${galleryT('settings.storage.downloadLabel', {}, 'Télécharger')}">
                                <i data-lucide="download"></i>
                            </button>
                            <button class="gallery-card-icon-btn danger" type="button" data-gallery-action="delete" data-gallery-index="${index}" aria-label="${galleryT('settings.storage.deleteLabel', {}, 'Supprimer')}">
                                <i data-lucide="trash-2"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="gallery-card-body">
                    <div class="gallery-card-name" title="${safeName}">${safeName}</div>
                    <div class="gallery-card-meta">
                        ${modelLabel ? `<span class="gallery-meta-pill gallery-meta-pill-model" title="${safeModel}"><i data-lucide="cpu"></i>${safeModel}</span>` : ''}
                        <span class="gallery-meta-pill"><i data-lucide="hard-drive"></i>${file.size_mb} MB</span>
                        <span class="gallery-meta-pill"><i data-lucide="calendar-days"></i>${safeCreated}</span>
                    </div>
                </div>
            </article>
        `;
    }).join('');

    gridEl.querySelectorAll('.gallery-card').forEach(card => {
        const index = Number(card.dataset.galleryIndex);
        const file = filtered[index];
        card.addEventListener('click', () => openGalleryItem(file, undefined, index, filtered));
    });

    gridEl.querySelectorAll('[data-gallery-action]').forEach(btn => {
        btn.addEventListener('click', async (event) => {
            event.stopPropagation();
            const index = Number(btn.dataset.galleryIndex);
            const file = filtered[index];
            if (!file) return;
            if (btn.dataset.galleryAction === 'download') {
                downloadGalleryItem(file.path, file.name);
                return;
            }
            if (btn.dataset.galleryAction === 'delete') {
                await deleteGalleryItem(file.path);
            }
        });
    });

    if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
}

function downloadGalleryItem(path, name) {
    const a = document.createElement('a');
    a.href = path;
    a.download = name || path.split('/').pop();
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function openGalleryItem(file, type, index = null, list = null) {
    const normalized = typeof file === 'string'
        ? { path: file, type: type || 'image', name: file.split('/').pop() || '' }
        : file;
    if (!normalized?.path) return;

    _galleryCurrentItem = normalized;
    if (Array.isArray(list)) {
        _galleryCurrentList = list;
    } else if (!_galleryCurrentList.length) {
        _galleryCurrentList = getFilteredGalleryFiles();
    }
    _galleryCurrentIndex = Number.isInteger(index)
        ? index
        : _galleryCurrentList.findIndex(item => item.path === normalized.path);

    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    const title = document.getElementById('gallery-viewer-title');
    const name = document.getElementById('gallery-viewer-name');
    const meta = document.getElementById('gallery-viewer-meta');
    const counter = document.getElementById('gallery-viewer-counter');

    if (!viewer || !stage || !title || !name || !meta) return;

    const isVideo = normalized.type === 'video';
    const modelLabel = getGalleryModelLabel(normalized);
    const promptText = getGalleryPrompt(normalized);
    resetGalleryViewerZoom();
    title.textContent = galleryT(isVideo ? 'settings.storage.previewVideo' : 'settings.storage.previewImage', {}, isVideo ? 'Aperçu vidéo' : 'Aperçu image');
    name.textContent = normalized.name || normalized.path.split('/').pop() || '';
    stage.innerHTML = isVideo
        ? `<div class="gallery-viewer-media-shell">
                <video class="gallery-viewer-media" src="${escapeGalleryHtml(normalized.path)}" controls autoplay playsinline></video>
                <span class="gallery-viewer-zoom-hint">${escapeGalleryHtml(galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer'))} · 100%</span>
           </div>`
        : `<div class="gallery-viewer-media-shell">
                <img class="gallery-viewer-media" src="${escapeGalleryHtml(normalized.path)}" alt="${escapeGalleryHtml(title.textContent)}">
                <span class="gallery-viewer-zoom-hint">${escapeGalleryHtml(galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer'))} · 100%</span>
           </div>`;
    meta.innerHTML = `
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.sourceLabel', {}, 'Source')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(getGallerySourceLabel(normalized.source || normalized.type))}</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.modelLabel', {}, 'Modèle')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(modelLabel || galleryT('settings.storage.metadataMissing', {}, 'Non enregistré'))}</span>
        </div>
        <div class="gallery-viewer-meta-row gallery-viewer-meta-row-full">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.promptLabel', {}, 'Prompt')}</span>
            <span class="gallery-viewer-meta-value gallery-viewer-prompt">${escapeGalleryHtml(promptText || galleryT('settings.storage.metadataMissing', {}, 'Non enregistré'))}</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.sizeLabel', {}, 'Stockage')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(normalized.size_mb ?? '—')} MB</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.createdLabel', {}, 'Créé')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(normalized.created_str || '—')}</span>
        </div>
    `;
    if (counter) {
        const total = _galleryCurrentList.length;
        counter.textContent = total > 1 && _galleryCurrentIndex >= 0
            ? `${_galleryCurrentIndex + 1} / ${total}`
            : '';
    }
    updateGalleryViewerNav();

    viewer.classList.add('is-open');
    viewer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('gallery-viewer-open');
    if (window.lucide) lucide.createIcons({ nodes: [viewer] });
}

function updateGalleryViewerNav() {
    const hasNavigation = _galleryCurrentList.length > 1;
    document.querySelectorAll('.gallery-viewer-nav').forEach(btn => {
        btn.hidden = !hasNavigation;
        btn.disabled = !hasNavigation;
    });
}

function showAdjacentGalleryItem(direction) {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer?.classList.contains('is-open')) return;

    if (!_galleryCurrentList.length) {
        _galleryCurrentList = getFilteredGalleryFiles();
    }
    if (_galleryCurrentList.length <= 1) return;

    if (_galleryCurrentIndex < 0 && _galleryCurrentItem?.path) {
        _galleryCurrentIndex = _galleryCurrentList.findIndex(item => item.path === _galleryCurrentItem.path);
    }

    const currentIndex = _galleryCurrentIndex >= 0 ? _galleryCurrentIndex : 0;
    const nextIndex = (currentIndex + direction + _galleryCurrentList.length) % _galleryCurrentList.length;
    openGalleryItem(_galleryCurrentList[nextIndex], undefined, nextIndex, _galleryCurrentList);
}

async function deleteGalleryItem(path) {
    const confirmed = await JoyDialog.confirm(galleryT('settings.storage.deleteConfirm', {}, 'Supprimer ce fichier ?'), { variant: 'danger' });
    if (!confirmed) return;

    const deleteBtn = document.getElementById('gallery-viewer-delete-btn');
    if (deleteBtn) deleteBtn.disabled = true;

    try {
        const resp = await fetch('/api/gallery/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const data = await resp.json().catch(() => ({}));

        if (resp.ok && data.success !== false) {
            if (_galleryCurrentItem?.path === path) closeGalleryViewer();
            Toast.success(galleryT('settings.storage.deleted', {}, 'Fichier supprimé'));
            refreshGallery();
        } else {
            Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'), data.error || `${resp.status}`);
        }
    } catch (e) {
        console.error('[GALLERY] Delete error:', e);
        Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'), e?.message || '');
    } finally {
        if (deleteBtn) deleteBtn.disabled = false;
    }
}

async function clearAllGallery() {
    const confirmed = await JoyDialog.confirm(galleryT('settings.storage.clearConfirm', {}, 'Supprimer tous les fichiers générés ? Cette action est irréversible.'), { variant: 'danger' });
    if (!confirmed) return;

    try {
        const resp = await fetch('/api/gallery/list');
        const data = await resp.json();

        for (const file of data.files) {
            await fetch('/api/gallery/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: file.path })
            });
        }

        closeGalleryViewer();
        Toast.success(galleryT('settings.storage.cleared', {}, 'Galerie vidée'));
        refreshGallery();
    } catch (e) {
        console.error('[GALLERY] Clear error:', e);
        Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'));
    }
}

function closeGalleryViewer() {
    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    const counter = document.getElementById('gallery-viewer-counter');
    if (!viewer || !stage) return;
    viewer.classList.remove('is-open');
    viewer.setAttribute('aria-hidden', 'true');
    stage.innerHTML = '';
    if (counter) counter.textContent = '';
    _galleryCurrentItem = null;
    _galleryCurrentIndex = -1;
    document.body.classList.remove('gallery-viewer-open');
    resetGalleryViewerZoom();
    updateGalleryViewerNav();
}

function downloadCurrentGalleryItem() {
    if (!_galleryCurrentItem) return;
    downloadGalleryItem(_galleryCurrentItem.path, _galleryCurrentItem.name);
}

async function deleteCurrentGalleryItem() {
    if (!_galleryCurrentItem?.path) return;
    await deleteGalleryItem(_galleryCurrentItem.path);
}

document.addEventListener('click', (event) => {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer || !viewer.classList.contains('is-open')) return;
    if (event.target === viewer) {
        closeGalleryViewer();
    }
});

document.addEventListener('keydown', (event) => {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer?.classList.contains('is-open')) return;

    if (event.key === 'Escape') {
        closeGalleryViewer();
        return;
    }

    if (event.key === 'ArrowLeft') {
        event.preventDefault();
        showAdjacentGalleryItem(-1);
        return;
    }

    if (event.key === 'ArrowRight') {
        event.preventDefault();
        showAdjacentGalleryItem(1);
    }
});

document.addEventListener('wheel', handleGalleryViewerWheel, { passive: false });

window.addEventListener('joyboy:locale-changed', () => {
    renderGalleryStats(_galleryStats || {
        total: _galleryFiles.length,
        images: _galleryFiles.filter(file => file.type === 'image').length,
        videos: _galleryFiles.filter(file => file.type === 'video').length,
        total_size_mb: Math.round((_galleryFiles.reduce((total, file) => total + (file.size || 0), 0) / (1024 * 1024)) * 100) / 100,
    });
    renderGalleryGrid();

    if (_galleryCurrentItem) {
        openGalleryItem(_galleryCurrentItem);
    }
});

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


// ========== TRAINING ==========

let _trainingPollInterval = null;

function initTrainingTab() {
    // Vérifier VRAM pour Flux
    const gpuProfile = window._gpuProfile;
    const fluxOption = document.querySelector('#training-base-model option[value="flux"]');
    if (fluxOption && gpuProfile && gpuProfile.vram_gb < 20) {
        fluxOption.disabled = true;
        fluxOption.textContent = t('settings.training.fluxDevRequired', 'Flux Dev (20GB+ requis)');
    }

    // Charger la liste des custom LoRAs
    loadCustomLoras();

    // Si un entraînement est en cours, reprendre le polling
    pollTrainingProgress();
}

async function loadTrainingImages() {
    const folder = document.getElementById('training-folder').value.trim();
    if (!folder) return;

    const grid = document.getElementById('training-images-grid');
    grid.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.training.loadingImages', 'Chargement...'))}</div>`;

    try {
        // Validation d'abord
        const valResp = await fetch(`/api/training/validate?folder=${encodeURIComponent(folder)}`);
        const valData = await valResp.json();

        if (!valResp.ok) {
            grid.innerHTML = `<div class="training-alert training-alert-error">${valData.error}</div>`;
            return;
        }

        // Afficher warnings/errors
        let alertHtml = '';
        if (valData.errors.length > 0) {
            alertHtml += valData.errors.map(e => `<div class="training-alert training-alert-error">${e}</div>`).join('');
        }
        if (valData.warnings.length > 0) {
            alertHtml += valData.warnings.map(w => `<div class="training-alert training-alert-warn">${w}</div>`).join('');
        }
        if (valData.valid && valData.errors.length === 0 && valData.warnings.length === 0) {
            alertHtml = `<div class="training-alert training-alert-ok">${escapeHtml(t('settings.training.imagesOk', '{count} images OK', { count: valData.image_count }))}</div>`;
        }

        // Charger les images
        const resp = await fetch(`/api/training/images?folder=${encodeURIComponent(folder)}`);
        const data = await resp.json();

        if (!resp.ok || !data.images || data.images.length === 0) {
            grid.innerHTML = alertHtml || `<div class="settings-info">${escapeHtml(t('settings.training.noImages', 'Aucune image trouvée'))}</div>`;
            return;
        }

        grid.innerHTML = alertHtml + data.images.map(img => `
            <div class="training-image-item">
                <img src="data:image/jpeg;base64,${img.thumbnail_b64}" alt="${img.name}" title="${img.name}">
                <div class="training-image-name">${img.name}</div>
            </div>
        `).join('');

        // Mettre à jour la liste des captions si elles existent
        const withCaptions = data.images.filter(img => img.caption);
        if (withCaptions.length > 0) {
            _renderCaptions(data.images);
        }
    } catch (e) {
        grid.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.training.loadImagesError', 'Erreur : {error}', { error: e.message }))}</div>`;
    }
}

async function applyCommonCaption() {
    const folder = document.getElementById('training-folder').value.trim();
    const caption = document.getElementById('training-common-caption').value.trim();
    if (!folder) {
        Toast.show(t('settings.training.captionFolderRequired', 'Spécifie un dossier d’abord'), 'error');
        return;
    }
    if (!caption) {
        Toast.show(t('settings.training.captionTextRequired', 'Écris une légende d’abord'), 'error');
        return;
    }

    try {
        const resp = await fetch('/api/training/caption/common', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({folder, caption}),
        });
        const data = await resp.json();

        if (!resp.ok) {
            Toast.show(data.error || t('common.error', 'Erreur'), 'error');
            return;
        }

        await loadTrainingImages();
        Toast.show(t('settings.training.captionApplied', 'Légende appliquée à {count} images', { count: data.count }), 'success');
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
    }
}

async function autoCaptionImages() {
    const folder = document.getElementById('training-folder').value.trim();
    if (!folder) {
        Toast.show(t('settings.training.captionFolderRequired', 'Spécifie un dossier d’abord'), 'error');
        return;
    }

    const btn = document.getElementById('btn-autocaption');
    btn.disabled = true;
    btn.textContent = t('settings.training.captioning', 'Captioning...');

    try {
        const resp = await fetch('/api/training/caption', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({folder}),
        });
        const data = await resp.json();

        if (!resp.ok) {
            Toast.show(data.error || t('settings.training.captioningError', 'Erreur captioning'), 'error');
            return;
        }

        // Recharger les images (qui incluent maintenant les captions)
        await loadTrainingImages();
        Toast.show(t('settings.training.captionedImages', '{count} images légendées', { count: data.captions.length }), 'success');
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = t('settings.training.autoCaption', 'Auto-caption');
    }
}

function _renderCaptions(images) {
    const list = document.getElementById('training-captions-list');
    list.innerHTML = images.map(img => `
        <div class="training-caption-item">
            <img src="data:image/jpeg;base64,${img.thumbnail_b64}" alt="${img.name}" class="training-caption-thumb">
            <div class="training-caption-edit">
                <div class="training-caption-name">${img.name}</div>
                <textarea class="training-caption-text" data-path="${img.path}" onchange="saveCaptionEdit(this)">${img.caption || ''}</textarea>
            </div>
        </div>
    `).join('');
}

async function saveCaptionEdit(textarea) {
    const imagePath = textarea.dataset.path;
    const caption = textarea.value.trim();

    try {
        await fetch('/api/training/caption/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({image_path: imagePath, caption}),
        });
    } catch (e) {
        console.error('Erreur sauvegarde caption:', e);
    }
}

async function startLoraTraining() {
    const folder = document.getElementById('training-folder').value.trim();
    const baseModel = document.getElementById('training-base-model').value;
    const loraName = document.getElementById('training-lora-name').value.trim() || 'my_lora';
    const steps = parseInt(document.getElementById('training-steps').value);
    const rank = parseInt(document.getElementById('training-rank').value);

    if (!folder) {
        Toast.show(t('settings.training.folderRequired', 'Spécifie un dossier d’images'), 'error');
        return;
    }

    const startBtn = document.getElementById('btn-start-training');
    const stopBtn = document.getElementById('btn-stop-training');
    const progressDiv = document.getElementById('training-progress');

    startBtn.disabled = true;
    stopBtn.classList.add('visible');
    progressDiv.classList.add('visible');
    document.getElementById('training-status').textContent = t('settings.training.starting', 'Démarrage...');
    document.getElementById('training-log').textContent = '';
    document.getElementById('training-progress-fill').style.width = '0%';

    try {
        const resp = await fetch('/api/training/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({folder, base_model: baseModel, lora_name: loraName, steps, rank}),
        });
        const data = await resp.json();

        if (!resp.ok) {
            Toast.show(data.error || t('settings.training.startError', 'Erreur au démarrage'), 'error');
            startBtn.disabled = false;
            stopBtn.classList.remove('visible');
            return;
        }

        Toast.show(t('settings.training.launched', 'Entraînement lancé'), 'success');
        _startTrainingPoll();
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
        startBtn.disabled = false;
        stopBtn.classList.remove('visible');
    }
}

async function stopLoraTraining() {
    try {
        await fetch('/api/training/stop', {method: 'POST'});
        Toast.show(t('settings.training.stopRequested', 'Arrêt demandé...'), 'info');
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
    }
}

function _startTrainingPoll() {
    if (_trainingPollInterval) clearInterval(_trainingPollInterval);
    _trainingPollInterval = setInterval(pollTrainingProgress, 2000);
}

async function loadCustomLoras() {
    const list = document.getElementById('custom-loras-list');
    if (!list) return;

    try {
        const resp = await fetch('/api/training/loras');
        const data = await resp.json();

        if (!data.loras || data.loras.length === 0) {
            list.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.training.emptyLoras', 'Aucun LoRA entraîné'))}</div>`;
            return;
        }

        list.innerHTML = data.loras.map(lora => {
            const pendingLabel = escapeHtml(t('settings.training.pending', 'en attente'));
            const loraName = escapeHtml(lora.name);
            const loraFilename = escapeHtml(lora.filename);
            const activateLabel = escapeHtml(t('settings.training.activate', 'Activer'));
            const deactivateLabel = escapeHtml(t('settings.training.deactivate', 'Désactiver'));
            return `
            <div class="custom-lora-item" id="custom-lora-${lora.name}">
                <div class="custom-lora-info">
                    <div class="custom-lora-name">${loraName}${lora.pending ? `<span class="custom-lora-pending">${pendingLabel}</span>` : ''}</div>
                    <div class="custom-lora-meta">${loraFilename} (${lora.size_mb} MB)</div>
                </div>
                <div class="custom-lora-controls">
                    <input type="range" class="settings-slider custom-lora-slider" min="0" max="100" value="${Math.round(lora.scale * 100)}"
                        data-lora="${lora.name}"
                        oninput="updateCustomLoraScale(this)"
                        ${lora.loaded ? '' : 'disabled'}>
                    <span class="custom-lora-scale-val" id="lora-scale-${lora.name}">${Math.round(lora.scale * 100)}%</span>
                    ${lora.loaded
                        ? `<button class="settings-action-btn custom-lora-deactivate" onclick="deactivateCustomLora('${lora.name}')">${deactivateLabel}</button>`
                        : `<button class="settings-action-btn custom-lora-activate" onclick="activateCustomLora('${lora.name}')">${activateLabel}</button>`
                    }
                </div>
            </div>`;
        }).join('');
    } catch (e) {
        list.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.training.loadError', 'Erreur chargement'))}</div>`;
    }
}

async function activateCustomLora(name) {
    try {
        const resp = await fetch('/api/training/lora/activate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, scale: 0.8}),
        });
        const data = await resp.json();

        if (!resp.ok) {
            Toast.show(data.error || t('settings.training.activationError', 'Erreur activation'), 'error');
            return;
        }

        const msg = data.pending
            ? t('settings.training.activatedPending', 'LoRA "{name}" activé (chargement à la prochaine génération)', { name })
            : t('settings.training.activated', 'LoRA "{name}" activé', { name });
        Toast.show(msg, 'success');
        loadCustomLoras();
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
    }
}

async function deactivateCustomLora(name) {
    try {
        await fetch('/api/training/lora/deactivate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name}),
        });
        Toast.show(t('settings.training.deactivated', 'LoRA "{name}" désactivé', { name }), 'info');
        loadCustomLoras();
    } catch (e) {
        Toast.show(t('settings.training.errorWithMessage', 'Erreur : {error}', { error: e.message }), 'error');
    }
}

async function updateCustomLoraScale(slider) {
    const name = slider.dataset.lora;
    const scale = parseInt(slider.value) / 100;
    const label = document.getElementById(`lora-scale-${name}`);
    if (label) label.textContent = Math.round(scale * 100) + '%';

    try {
        await fetch('/api/training/lora/scale', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, scale}),
        });
    } catch (e) {
        // Silently fail
    }
}

async function pollTrainingProgress() {
    try {
        const resp = await fetch('/api/training/status');
        const data = await resp.json();

        const progressDiv = document.getElementById('training-progress');
        const startBtn = document.getElementById('btn-start-training');
        const stopBtn = document.getElementById('btn-stop-training');

        if (!progressDiv) return;

        if (data.running) {
            progressDiv.classList.add('visible');
            stopBtn.classList.add('visible');
            startBtn.disabled = true;

            const pct = Math.round(data.progress * 100);
            document.getElementById('training-progress-fill').style.width = pct + '%';
            document.getElementById('training-status').textContent =
                `Step ${data.step}/${data.total_steps} (${pct}%) | loss: ${data.loss?.toFixed(4) || '...'} | ETA: ${data.eta || '...'}`;

            // Log
            if (data.log_lines && data.log_lines.length > 0) {
                const logDiv = document.getElementById('training-log');
                logDiv.textContent = data.log_lines.slice(-20).join('\n');
                logDiv.scrollTop = logDiv.scrollHeight;
            }

            // Continuer le poll
            if (!_trainingPollInterval) _startTrainingPoll();
        } else {
            // Entraînement terminé
            if (_trainingPollInterval) {
                clearInterval(_trainingPollInterval);
                _trainingPollInterval = null;
            }
            startBtn.disabled = false;
            stopBtn.classList.remove('visible');

            if (data.step > 0 && data.step >= data.total_steps) {
                document.getElementById('training-status').textContent = t('settings.training.completed', 'Entraînement terminé !');
                document.getElementById('training-progress-fill').style.width = '100%';
                Toast.show(t('settings.training.success', 'LoRA entraîné avec succès !'), 'success');
            }

            // Afficher les derniers logs
            if (data.log_lines && data.log_lines.length > 0) {
                const logDiv = document.getElementById('training-log');
                logDiv.textContent = data.log_lines.slice(-20).join('\n');
            }
        }
    } catch (e) {
        // Silently fail - server might not be ready
    }
}
