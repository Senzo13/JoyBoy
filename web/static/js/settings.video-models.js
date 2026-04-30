// ===== SETTINGS VIDEO MODELS PANEL =====
// Video catalog rendering, download, and equip actions.

let allVideoModels = [];
let currentVideoFilter = 'all';
const videoModelDownloadPollers = new Map();
let currentVideoLoraImportJobId = null;

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
        window.videoModelRuntimeCatalog = { ...(window.videoModelRuntimeCatalog || {}), ...data, models: allVideoModels };
        if (typeof renderModelPickerList === 'function') {
            renderModelPickerList('home');
            renderModelPickerList('chat');
        }
        renderCachedVideoModelLists();
        if (typeof loadVideoLoras === 'function') loadVideoLoras();
    } catch (error) {
        const html = `<div class="settings-info">${escapeHtml(t('settings.models.genericError', 'Erreur : {error}', { error: error.message || String(error) }))}</div>`;
        if (installedList) DOM.setHtml(installedList, html);
        if (availableList) DOM.setHtml(availableList, html);
    }
}

function renderVideoLoraItem(lora) {
    const id = escapeHtml(String(lora.id || ''));
    const name = escapeHtml(String(lora.display_name || lora.name || lora.id || 'LoRA vidéo'));
    const base = escapeHtml(String(lora.base_model || 'Video LoRA'));
    const triggers = Array.isArray(lora.trigger_words || lora.trained_words)
        ? (lora.trigger_words || lora.trained_words).join(', ')
        : '';
    const compatible = Array.isArray(lora.compatible_models) && lora.compatible_models.length
        ? lora.compatible_models.join(', ')
        : 'best-effort';
    const enabled = lora.enabled === true;
    const scale = Math.round(Number(lora.scale || 1) * 100);
    const missing = lora.exists === false;
    return `
        <div class="ollama-model-item video-lora-item ${enabled ? 'equipped' : ''}" data-lora-id="${id}">
            <div class="model-info">
                <div class="model-name-row">
                    <span class="model-name">${name}</span>
                    ${enabled ? `<span class="uncensored-badge" style="background: rgba(34,197,94,0.15); color: #22c55e;">ACTIF</span>` : ''}
                    ${missing ? `<span class="uncensored-badge" style="background: rgba(239,68,68,0.15); color: #ef4444;">FICHIER MANQUANT</span>` : ''}
                </div>
                <span class="model-desc">${base} · ${escapeHtml(lora.size_label || '')}</span>
                <span class="model-size">Compatible: ${escapeHtml(compatible)}</span>
                ${triggers ? `<span class="model-size">Triggers: ${escapeHtml(triggers)}</span>` : ''}
                <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
                    <input type="range" class="settings-slider" min="0" max="200" value="${scale}" data-lora-id="${id}" oninput="setVideoLoraScaleFromSlider(this)" ${missing ? 'disabled' : ''}>
                    <span class="settings-slider-value" id="video-lora-scale-${id}">${scale}%</span>
                </div>
            </div>
            <div class="model-actions">
                <button class="btn-equip ${enabled ? 'equipped' : ''}" data-lora-id="${id}" onclick="toggleVideoLoraFromButton(this)" ${missing ? 'disabled' : ''}>
                    ${enabled ? 'Désactiver' : 'Activer'}
                </button>
            </div>
        </div>
    `;
}

async function loadVideoLoras() {
    const list = document.getElementById('video-lora-list');
    if (!list) return;
    list.innerHTML = `<div class="settings-info">${escapeHtml(t('common.loading', 'Chargement...'))}</div>`;
    try {
        const response = await fetch('/api/video-loras');
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
        const loras = Array.isArray(data.loras) ? data.loras : [];
        list.innerHTML = loras.length
            ? loras.map(renderVideoLoraItem).join('')
            : `<div class="settings-info">Aucun LoRA vidéo importé.</div>`;
    } catch (error) {
        list.innerHTML = `<div class="settings-info">${escapeHtml(t('settings.models.genericError', 'Erreur : {error}', { error: error.message || String(error) }))}</div>`;
    }
    if (window.lucide) lucide.createIcons();
}

async function setVideoLoraState(id, payload) {
    const response = await fetch('/api/video-loras/state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, ...payload }),
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
}

async function toggleVideoLoraFromButton(button) {
    const id = button?.dataset?.loraId || '';
    if (!id) return;
    const item = button.closest('.video-lora-item');
    const enabled = !item?.classList.contains('equipped');
    try {
        await setVideoLoraState(id, { enabled });
        Toast.success('LoRA vidéo', enabled ? 'LoRA activé pour les prochaines vidéos' : 'LoRA désactivé');
        loadVideoLoras();
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function setVideoLoraScaleFromSlider(slider) {
    const id = slider?.dataset?.loraId || '';
    if (!id) return;
    const scale = Number(slider.value || 100) / 100;
    const label = document.getElementById(`video-lora-scale-${id}`);
    if (label) label.textContent = `${Math.round(scale * 100)}%`;
    clearTimeout(slider._videoLoraTimer);
    slider._videoLoraTimer = setTimeout(async () => {
        try {
            await setVideoLoraState(id, { scale });
        } catch (error) {
            Toast.error(t('common.error', 'Erreur'), error.message || String(error));
        }
    }, 250);
}

async function resolveVideoLoraImportSource() {
    const input = document.getElementById('video-lora-source-input');
    const output = document.getElementById('video-lora-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) return;
    output.innerHTML = `<div class="settings-info">Analyse du LoRA vidéo...</div>`;
    const result = await apiSettings.resolveModelSource(source, 'video_lora');
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">Erreur : ${escapeHtml(result.data?.error || result.error || 'source invalide')}</div>`;
        return;
    }
    const info = result.data.resolved;
    const triggers = Array.isArray(info.trained_words) && info.trained_words.length
        ? `<div class="settings-label-desc">Triggers: ${escapeHtml(info.trained_words.join(', '))}</div>`
        : '';
    output.innerHTML = `
        <div class="settings-label"><strong>${escapeHtml(info.display_name || source)}</strong></div>
        <div class="settings-label-desc">${escapeHtml(info.provider || '')} · ${escapeHtml(info.model_type || 'LoRA')} · ${escapeHtml(info.base_model || '')}</div>
        ${info.file_name ? `<div class="settings-label-desc">${escapeHtml(info.file_name)} · ${escapeHtml(info.size_label || '')}</div>` : ''}
        ${triggers}
        ${info.warning ? `<div class="settings-label-desc status-warn">${escapeHtml(info.warning)}</div>` : ''}
        <div style="margin-top:10px;">
            <button class="settings-action-btn" onclick="startVideoLoraImport()">Importer ce LoRA vidéo</button>
        </div>
    `;
}

async function startVideoLoraImport() {
    const input = document.getElementById('video-lora-source-input');
    const output = document.getElementById('video-lora-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) return;
    const result = await apiSettings.startModelImport(source, 'video_lora', false);
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">Erreur : ${escapeHtml(result.data?.error || result.error || 'import impossible')}</div>`;
        return;
    }
    currentVideoLoraImportJobId = result.data.job?.job_id || null;
    output.innerHTML = `<div class="settings-info">Import LoRA vidéo lancé...</div>`;
    if (currentVideoLoraImportJobId) pollVideoLoraImportStatus(currentVideoLoraImportJobId);
}

async function pollVideoLoraImportStatus(jobId) {
    const output = document.getElementById('video-lora-source-output');
    if (!output || !jobId) return;
    const result = await apiSettings.getModelImportStatus(jobId);
    const job = result.data?.job;
    if (!result.ok || !job) {
        output.innerHTML = `<div class="settings-info">Import introuvable</div>`;
        return;
    }
    const downloadedMB = Math.round((job.downloaded_bytes || 0) / (1024 * 1024));
    const totalMB = Math.round((job.total_bytes || 0) / (1024 * 1024));
    const sizeChunk = totalMB ? ` · ${downloadedMB} MB / ${totalMB} MB` : '';
    output.innerHTML = `
        <div class="settings-label"><strong>${escapeHtml(job.resolved?.display_name || 'LoRA vidéo')}</strong></div>
        <div class="settings-label-desc">${escapeHtml(job.message || 'Import en cours')}</div>
        <div class="settings-label-desc">Progression : ${Number(job.progress || 0)}%${escapeHtml(sizeChunk)}</div>
        ${job.error ? `<div class="settings-label-desc status-error">${escapeHtml(job.error)}</div>` : ''}
    `;
    if (job.status === 'completed') {
        Toast.success('LoRA vidéo importé', 'Tu peux maintenant l’activer.');
        loadVideoLoras();
        return;
    }
    if (job.status === 'error') {
        Toast.error('Erreur import LoRA vidéo', job.error || 'Échec import');
        return;
    }
    setTimeout(() => pollVideoLoraImportStatus(jobId), 1200);
}

function renderVideoModelItem(model, isInstalled) {
    const activeModel = userSettings.videoModel || 'svd';
    const isEquipped = model.key === activeModel || model.id === activeModel;
    const modelKey = escapeHtml(String(model.key || model.id || ''));
    const modelName = escapeHtml(String(model.name || model.key || ''));
    const modelNameAttr = escapeHtml(String(model.name || model.key || model.id || ''));
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
            <button class="btn-delete-model" data-model-id="${modelKey}" data-model-name="${modelNameAttr}" onclick="deleteVideoModelFromButton(this)">
                <i data-lucide="trash-2"></i>
                <span>${escapeHtml(t('common.delete', 'Supprimer'))}</span>
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

function deleteVideoModelFromButton(button) {
    const modelId = button?.dataset?.modelId || '';
    const modelName = button?.dataset?.modelName || modelId;
    if (!modelId) return;
    deleteVideoModel(modelId, modelName, button);
}

async function deleteVideoModel(modelId, modelName, sourceButton = null) {
    const confirmed = await JoyDialog.confirm(
        t('settings.models.deleteImageConfirm', 'Supprimer le modèle "{model}" ?\n\nCela libérera l’espace disque.', { model: modelName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    const btn = sourceButton || (typeof event !== 'undefined' ? event?.target : null);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader-circle"></i><span>${escapeHtml(t('settings.models.deleting', 'Suppression...'))}</span>`;
        if (window.lucide) lucide.createIcons();
    }

    try {
        const response = await fetch('/api/video-models/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || `HTTP ${response.status}`);
        }

        if ((userSettings.videoModel || 'svd') === modelId) {
            saveSetting('videoModel', 'svd');
            if (typeof updateVideoQualityVisibility === 'function') updateVideoQualityVisibility();
            if (typeof loadVideoModelsForRuntime === 'function') loadVideoModelsForRuntime();
        }

        Toast.success(t('settings.models.deletedTitle', 'Supprimé'), t('settings.models.deletedBody', '{model} a été supprimé', { model: modelName }));
        checkVideoModelsStatus();
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="trash-2"></i><span>${escapeHtml(t('common.delete', 'Supprimer'))}</span>`;
            if (window.lucide) lucide.createIcons();
        }
    }
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
