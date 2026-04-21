// ===== SETTINGS TRAINING PANEL =====
// LoRA training tab helpers, captioning, custom LoRA controls, and polling.

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
