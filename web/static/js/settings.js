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
