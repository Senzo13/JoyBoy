// ===== SETTINGS OLLAMA TEXT MODELS =====
// Ollama status, local text-model search/download/equip/delete, and generation subtab switching.

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
