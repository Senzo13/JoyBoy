// ===== SETTINGS VIDEO MODELS PANEL =====
// Video catalog rendering, download, and equip actions.

let allVideoModels = [];
let currentVideoFilter = 'all';
const videoModelDownloadPollers = new Map();

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

function formatVideoDownloadBytes(bytes) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return '';
    if (value >= 1024 ** 3) return `${(value / (1024 ** 3)).toFixed(1)} GB`;
    if (value >= 1024 ** 2) return `${(value / (1024 ** 2)).toFixed(0)} MB`;
    return `${Math.max(1, Math.round(value / 1024))} KB`;
}

function videoDownloadStageLabel(model) {
    const stage = String(model.stage || '').toLowerCase();
    if (stage === 'backend') return 'Installation du backend';
    if (stage === 'models') return 'Téléchargement des poids';
    if (stage === 'complete') return 'Prêt';
    if (stage === 'error') return 'Erreur';
    return 'Préparation';
}

function renderVideoDownloadProgress(model) {
    const progress = Math.max(0, Math.min(100, Number(model.progress || 0)));
    const downloaded = Number(model.downloaded_bytes || 0);
    const total = Number(model.total_bytes || 0);
    const hasMeasuredProgress = total > 0 && progress > 0;
    const label = model.download_message || videoDownloadStageLabel(model);
    const repo = model.download_repo || '';
    const byteText = total
        ? `${formatVideoDownloadBytes(downloaded)} / ${formatVideoDownloadBytes(total)}`
        : '';
    const detail = [repo, byteText].filter(Boolean).join(' · ');
    const progressClass = hasMeasuredProgress ? '' : ' indeterminate';
    const progressWidth = hasMeasuredProgress ? progress : Math.max(8, progress || 8);

    return `
        <div class="download-progress video-download-progress${progressClass}">
            <div class="download-progress-head">
                <span class="download-status">
                    <i data-lucide="loader-circle"></i>
                    ${escapeHtml(label)}
                </span>
                <span class="download-percent">${Math.round(progress)}%</span>
            </div>
            <div class="progress-bar"><div class="progress-bar-fill" style="width: ${progressWidth}%"></div></div>
            ${detail ? `<div class="download-detail">${escapeHtml(detail)}</div>` : ''}
        </div>
    `;
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
        model.launch_status === 'missing_backend' ? 'backend à installer' : '',
        model.experimental_low_vram ? 'test manuel' : '',
    ].filter(Boolean).join(' · ');

    const action = model.downloading
        ? `
            <button class="btn-install-model is-downloading" data-model-id="${modelKey}" disabled>
                <i data-lucide="loader-circle"></i>
                <span>${escapeHtml(t('settings.models.inProgress', 'En cours...'))}</span>
            </button>
        `
        : isInstalled
        ? `
            <button class="btn-equip ${isEquipped ? 'equipped' : ''}" data-model-id="${modelKey}" onclick="equipVideoModelFromButton(this)">
                ${isEquipped ? `<i data-lucide="check"></i> ${escapeHtml(t('settings.models.equipped', 'Équipé'))}` : escapeHtml(t('settings.models.equip', 'Équiper'))}
            </button>
        `
        : `
            <button class="btn-install-model" data-model-id="${modelKey}" onclick="downloadVideoModelFromButton(this)">
                <i data-lucide="download"></i>
                <span>${escapeHtml(t('settings.models.download', 'Télécharger'))}</span>
            </button>
        `;

    return `
        <div class="ollama-model-item video-model-item ${isEquipped ? 'equipped' : ''} ${model.downloading ? 'downloading' : ''}" data-model-id="${modelKey}">
            <div class="model-info">
                <div class="model-name-row">
                    <span class="model-name">${modelName}</span>
                    ${isEquipped ? `<span class="uncensored-badge" style="background: rgba(59,130,246,0.15); color: #3b82f6;">${escapeHtml(t('settings.models.activeBadge', 'ACTIF'))}</span>` : ''}
                </div>
                <span class="model-desc">${escapeHtml(model.description || '')}</span>
                <span class="model-size">${escapeHtml(caps || 'Vidéo')}</span>
                <span class="model-size">${escapeHtml(size || '~')} · ${repo}</span>
                ${statusBits ? `<span class="model-size">${escapeHtml(statusBits)}</span>` : ''}
                ${model.downloading ? renderVideoDownloadProgress(model) : ''}
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
    const btn = sourceButton || (typeof event !== 'undefined' ? event?.target : null);
    const modelItem = btn?.closest('.ollama-model-item');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-circle"></i><span>${escapeHtml(t('settings.models.checking', 'Vérification...'))}</span>`;
        if (window.lucide) lucide.createIcons();
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

        const optimistic = allVideoModels.find(item => item.key === modelId || item.id === modelId);
        if (optimistic) {
            optimistic.downloading = true;
            optimistic.progress = Math.max(optimistic.progress || 0, 1);
            optimistic.stage = optimistic.stage || 'queued';
            optimistic.download_message = optimistic.download_message || 'Préparation du téléchargement';
            renderCachedVideoModelLists();
        } else if (modelItem) {
            modelItem.classList.add('downloading');
        }
        Toast.info(t('settings.models.downloadStartedTitle', 'Téléchargement'), 'Installation lancée. Le statut se met à jour ici.', 5000);
        pollVideoModelDownload(modelId);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="download"></i><span>${escapeHtml(t('settings.models.download', 'Télécharger'))}</span>`;
            if (window.lucide) lucide.createIcons();
        }
        checkVideoModelsStatus();
    }
}

function pollVideoModelDownload(modelId) {
    if (videoModelDownloadPollers.has(modelId)) {
        clearInterval(videoModelDownloadPollers.get(modelId));
    }
    const interval = setInterval(async () => {
        try {
            const response = await fetch('/api/video-models/status?advanced=1&allow_experimental=1');
            const data = await response.json();
            if (!response.ok || !data.success) return;
            allVideoModels = Array.isArray(data.models) ? data.models : [];
            const model = allVideoModels.find(item => item.key === modelId || item.id === modelId);
            if (!model) return;
            renderCachedVideoModelLists();

            if (model.downloaded && !model.downloading) {
                clearInterval(interval);
                videoModelDownloadPollers.delete(modelId);
                Toast.success(t('settings.models.downloadDoneTitle', 'Téléchargement terminé'), t('settings.models.downloadDoneBody', '{model} est prêt', { model: model.name || modelId }));
                checkVideoModelsStatus();
            }
            if (model.error && !model.downloading) {
                clearInterval(interval);
                videoModelDownloadPollers.delete(modelId);
                Toast.error(t('common.error', 'Erreur'), model.error);
                checkVideoModelsStatus();
            }
        } catch (error) {
            console.warn('[VIDEO_MODELS] Poll error:', error);
        }
    }, 2500);
    videoModelDownloadPollers.set(modelId, interval);

    setTimeout(() => {
        if (videoModelDownloadPollers.get(modelId) === interval) {
            clearInterval(interval);
            videoModelDownloadPollers.delete(modelId);
            checkVideoModelsStatus();
        }
    }, 120 * 60 * 1000);
}
