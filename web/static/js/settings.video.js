// ===== SETTINGS VIDEO PANEL =====
// Runtime video model catalog, audio availability, and quality control synchronization.

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
