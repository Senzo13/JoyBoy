// ===== SETTINGS ADDONS AND FEATURE FLAGS =====
// Feature exposure, local packs, provider group rendering helpers, and addon import controls.

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
