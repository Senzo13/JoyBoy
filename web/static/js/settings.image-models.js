// ===== SETTINGS IMAGE MODELS PANEL =====
// Image model catalog rendering, download, equip, and delete actions.

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
