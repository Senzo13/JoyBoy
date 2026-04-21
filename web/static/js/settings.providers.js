// ===== SETTINGS PROVIDERS PANEL =====
// Cloud provider auth rows, provider actions, and terminal cloud model selection.

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
    if (typeof tokenStats !== 'undefined' && typeof getTerminalEffectiveContextSize === 'function') {
        tokenStats.maxContextSize = getTerminalEffectiveContextSize(cleanModelId);
        if (typeof updateTokenDisplay === 'function') updateTokenDisplay();
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
        auth_missing: t('providers.authStatusAuthMissing', 'connexion absente'),
        auth_invalid: t('providers.authStatusAuthInvalid', 'auth invalide'),
        auth_expired: t('providers.authStatusAuthExpired', 'session expirée'),
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
