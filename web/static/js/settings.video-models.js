// ===== SETTINGS VIDEO MODELS PANEL =====
// Video catalog rendering, download, and equip actions.

let allVideoModels = [];
let currentVideoFilter = 'all';

function videoModelCapabilities(model) {
    const caps = [];
    if (model.supports_i2v || model.supports_image) caps.push('I2V');
    if (model.supports_t2v) caps.push('T2V');
    if (model.supports_continue) caps.push('Continue');
    if (model.supports_audio_native) caps.push('Audio');
    if (model.native_backend) caps.push('Natif');
    return caps;
}

function filterVideoModels(models) {
    if (currentVideoFilter === 'all') return models;
    return models.filter(model => {
        if (currentVideoFilter === 'i2v') return model.supports_i2v || model.supports_image;
        if (currentVideoFilter === 't2v') return model.supports_t2v;
        if (currentVideoFilter === 'native') return model.native_backend;
        if (currentVideoFilter === 'audio') return model.supports_audio_native;
        return true;
    });
}

async function checkVideoModelsStatus() {
    const installedList = DOM.get('video-installed-models');
    const availableList = DOM.get('video-available-models');

    if (installedList) DOM.setHtml(installedList, `<div class="settings-info">${escapeHtml(t('settings.models.checking', 'Vérification...'))}</div>`);
    if (availableList) DOM.setHtml(availableList, `<div class="settings-info">${escapeHtml(t('common.loading', 'Chargement...'))}</div>`);

    try {
        const response = await fetch('/api/video-models/status?advanced=1&allow_experimental=1');
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        allVideoModels = Array.isArray(data.models) ? data.models : [];
        renderCachedVideoModelLists();
    } catch (error) {
        const html = `<div class="settings-info">${escapeHtml(t('settings.models.genericError', 'Erreur : {error}', { error: error.message || String(error) }))}</div>`;
        if (installedList) DOM.setHtml(installedList, html);
        if (availableList) DOM.setHtml(availableList, html);
    }
}

function renderVideoModelItem(model, isInstalled) {
    const activeModel = userSettings.videoModel || 'svd';
    const isEquipped = model.key === activeModel || model.id === activeModel;
    const modelKey = escapeHtml(String(model.key || model.id || ''));
    const modelName = escapeHtml(String(model.name || model.key || ''));
    const repo = escapeHtml(String(model.repo || model.id || ''));
    const caps = videoModelCapabilities(model).join(' · ');
    const size = model.total_bytes ? `${(model.total_bytes / (1024 ** 3)).toFixed(1)} GB` : (model.vram || '');
    const statusBits = [
        model.category,
        model.launch_status === 'missing_backend' ? 'backend manquant' : '',
        model.experimental_low_vram ? 'test manuel' : '',
    ].filter(Boolean).join(' · ');

    const action = isInstalled
        ? `
            <button class="btn-equip ${isEquipped ? 'equipped' : ''}" data-model-id="${modelKey}" onclick="equipVideoModelFromButton(this)">
                ${isEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equipped', 'Équipé'))}` : escapeHtml(t('settings.models.equip', 'Équiper'))}
            </button>
        `
        : `
            <button class="btn-install-model" data-model-id="${modelKey}" onclick="downloadVideoModelFromButton(this)">
                ${escapeHtml(t('settings.models.download', 'Télécharger'))}
            </button>
        `;

    return `
        <div class="ollama-model-item ${isEquipped ? 'equipped' : ''}">
            <div class="model-info">
                <div class="model-name-row">
                    <span class="model-name">${modelName}</span>
                    ${isEquipped ? `<span class="uncensored-badge" style="background: rgba(59,130,246,0.15); color: #3b82f6;">${escapeHtml(t('settings.models.activeBadge', 'ACTIF'))}</span>` : ''}
                </div>
                <span class="model-desc">${escapeHtml(model.description || '')}</span>
                <span class="model-size">${escapeHtml(caps || 'Vidéo')}</span>
                <span class="model-size">${escapeHtml(size || '~')} · ${repo}</span>
                ${statusBits ? `<span class="model-size">${escapeHtml(statusBits)}</span>` : ''}
            </div>
            <div class="model-actions">${action}</div>
        </div>
    `;
}

function renderAvailableVideoModels() {
    const availableList = document.getElementById('video-available-models');
    if (!availableList) return;

    const available = filterVideoModels(allVideoModels.filter(model => !model.downloaded));
    availableList.innerHTML = available.length
        ? available.map(model => renderVideoModelItem(model, false)).join('')
        : `<div class="settings-info">${escapeHtml(t('settings.models.noAvailableForFilter', 'Aucun modèle disponible avec ce filtre'))}</div>`;
    if (window.lucide) lucide.createIcons();
}

function renderCachedVideoModelLists() {
    const installedList = document.getElementById('video-installed-models');
    if (installedList) {
        const installed = allVideoModels.filter(model => model.downloaded);
        DOM.setHtml(installedList, installed.length
            ? installed.map(model => renderVideoModelItem(model, true)).join('')
            : `<div class="settings-info">${escapeHtml(t('settings.models.noInstalled', 'Aucun modèle local'))}</div>`
        );
    }
    renderAvailableVideoModels();
    if (window.lucide) lucide.createIcons();
}

function toggleVideoModelFilter(filter) {
    currentVideoFilter = filter;
    document.querySelectorAll('#models-video-panel .filter-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.filter === filter);
    });
    renderAvailableVideoModels();
}

function equipVideoModelFromButton(button) {
    const modelId = button?.dataset?.modelId || '';
    if (!modelId) return;
    const previousModel = userSettings.videoModel || 'svd';
    if (previousModel === modelId) {
        Toast.info(t('settings.models.alreadyActiveTitle', 'Déjà actif'), t('settings.models.alreadyActiveBody', '{model} est déjà le modèle actif', { model: modelId }), 2000);
        return;
    }

    saveSetting('videoModel', modelId);
    if (typeof updateVideoQualityVisibility === 'function') updateVideoQualityVisibility();
    if (typeof loadVideoModelsForRuntime === 'function') loadVideoModelsForRuntime();
    renderCachedVideoModelLists();
    apiPost('/api/log/model-change', { model: modelId, type: 'video', previous: previousModel }).catch(() => {});
    Toast.success(t('settings.models.imageEquippedTitle', 'Modèle équipé'), t('settings.models.imageEquippedBody', '{model} est maintenant actif', { model: modelId }), 2000);
}

function downloadVideoModelFromButton(button) {
    const modelId = button?.dataset?.modelId || '';
    if (!modelId) return;
    downloadVideoModel(modelId, button);
}

async function downloadVideoModel(modelId, sourceButton = null) {
    const btn = sourceButton || event?.target;
    const modelItem = btn?.closest('.ollama-model-item');
    if (btn) {
        btn.disabled = true;
        btn.textContent = t('settings.models.checking', 'Vérification...');
    }

    try {
        const response = await fetch('/api/video-models/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);

        if (data.message === 'already_cached') {
            Toast.success(t('settings.models.alreadyInstalledTitle', 'Déjà présent'), t('settings.models.alreadyInstalledBody', 'Ce modèle est déjà sur la machine'), 3000);
            checkVideoModelsStatus();
            return;
        }

        if (modelItem && !modelItem.querySelector('.download-progress')) {
            modelItem.insertAdjacentHTML('beforeend', `
                <div class="download-progress">
                    <div class="download-status">${escapeHtml(t('settings.models.downloadInProgress', 'Téléchargement en cours...'))}</div>
                    <div class="progress-bar"><div class="progress-bar-fill" style="width: 0%"></div></div>
                    <div class="progress-text">0%</div>
                </div>
            `);
        }
        if (btn) btn.textContent = t('settings.models.inProgress', 'En cours...');
        Toast.info(t('settings.models.downloadStartedTitle', 'Téléchargement'), t('settings.models.downloadStartedBody', 'Téléchargement démarré (~6 GB)'), 5000);
        pollVideoModelDownload(modelId, btn, modelItem);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
        if (btn) {
            btn.disabled = false;
            btn.textContent = t('settings.models.download', 'Télécharger');
        }
    }
}

function pollVideoModelDownload(modelId, btn, modelItem) {
    const interval = setInterval(async () => {
        try {
            const response = await fetch('/api/video-models/status?advanced=1&allow_experimental=1');
            const data = await response.json();
            if (!response.ok || !data.success) return;
            allVideoModels = Array.isArray(data.models) ? data.models : [];
            const model = allVideoModels.find(item => item.key === modelId || item.id === modelId);
            if (!model) return;

            if (model.downloading && modelItem) {
                const progress = model.progress || 0;
                const fill = modelItem.querySelector('.progress-bar-fill');
                const status = modelItem.querySelector('.download-status');
                const text = modelItem.querySelector('.progress-text');
                if (fill) fill.style.width = `${progress}%`;
                if (text) text.textContent = `${progress}%`;
                if (status && model.total_bytes) {
                    const downloaded = (model.downloaded_bytes || 0) / (1024 ** 3);
                    const total = model.total_bytes / (1024 ** 3);
                    status.textContent = `${downloaded.toFixed(1)} GB / ${total.toFixed(1)} GB`;
                }
            }

            if (model.downloaded && !model.downloading) {
                clearInterval(interval);
                Toast.success(t('settings.models.downloadDoneTitle', 'Téléchargement terminé'), t('settings.models.downloadDoneBody', '{model} est prêt', { model: model.name || modelId }));
                checkVideoModelsStatus();
            }
            if (model.error && !model.downloading) {
                clearInterval(interval);
                Toast.error(t('common.error', 'Erreur'), model.error);
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = t('settings.models.download', 'Télécharger');
                }
            }
        } catch (error) {
            console.warn('[VIDEO_MODELS] Poll error:', error);
        }
    }, 2500);

    setTimeout(() => {
        clearInterval(interval);
        if (btn && btn.disabled) {
            btn.disabled = false;
            btn.textContent = t('settings.models.verifyAction', 'Vérifier');
        }
    }, 120 * 60 * 1000);
}
