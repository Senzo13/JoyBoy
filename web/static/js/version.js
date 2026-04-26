// ===== APP VERSION / UPDATE STATUS =====

let appVersionStatus = null;
let appVersionStatusLoading = false;
let appVersionUpdating = false;

function versionText(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function versionCurrentLabel(status = appVersionStatus) {
    return status?.current?.version || '0.0.0-dev';
}

function versionLatestLabel(status = appVersionStatus) {
    return status?.latest_release?.tag || status?.latest_release?.version || '';
}

function versionStatusKind(status = appVersionStatus) {
    return status?.update?.kind || 'none';
}

function versionStatusClass(status = appVersionStatus) {
    if (!status) return 'is-muted';
    const kind = versionStatusKind(status);
    if (kind === 'release') return 'is-warning';
    if (kind === 'commit') return 'is-warning';
    if (status.update?.status === 'unknown') return 'is-error';
    return 'is-ok';
}

function versionStatusLabel(status = appVersionStatus) {
    if (appVersionStatusLoading) {
        return versionText('settings.version.statusChecking', 'Vérification...');
    }
    if (!status) return versionText('settings.version.statusOffline', 'Indisponible');

    const kind = versionStatusKind(status);
    if (kind === 'release' || kind === 'commit') {
        return versionText('settings.version.statusAvailable', 'Mise à jour disponible');
    }
    if (status.update?.status === 'no_releases') return versionText('settings.version.statusNoRelease', 'Version locale');
    if (status.update?.status === 'unknown') return versionText('settings.version.statusOffline', 'Indisponible');
    return versionText('settings.version.statusCurrent', 'À jour');
}

function versionDetail(status = appVersionStatus) {
    const current = versionCurrentLabel(status);
    const latest = versionLatestLabel(status);
    const branch = status?.git?.target_branch || 'main';

    if (appVersionStatusLoading) {
        return versionText('settings.version.detailChecking', 'Recherche d’une nouvelle version GitHub...');
    }
    if (!status) {
        return versionText('settings.version.detailOffline', 'Impossible de vérifier les mises à jour pour le moment.');
    }
    if (status.update?.kind === 'release') {
        return versionText(
            'settings.version.detailAvailable',
            'JoyBoy {latest} est disponible. Version installée : {current}. Ouvre GitHub pour voir la mise à jour.',
            { current, latest }
        );
    }
    if (status.update?.kind === 'commit') {
        const shortCommit = status.git?.short_commit || current;
        const latestCommit = status.git?.latest_short_commit || branch;
        return versionText(
            'settings.version.detailCommit',
            'Une mise à jour du code est disponible sur GitHub. Installation actuelle : {current}; dernier code : {latest}. Lance git pull dans le dossier JoyBoy, puis redémarre JoyBoy.',
            { current: shortCommit, latest: latestCommit, branch }
        );
    }
    if (status.update?.status === 'no_releases') {
        return versionText(
            'settings.version.detailNoRelease',
            'Aucune release GitHub publiée pour ce repo. JoyBoy vérifiera les releases dès qu’une version publique existe.',
        );
    }
    if (status.update?.status === 'unknown') {
        return versionText('settings.version.detailOffline', 'Impossible de vérifier les mises à jour pour le moment.');
    }
    return versionText('settings.version.detailCurrent', 'JoyBoy est à jour. Version installée : {current}.', { current });
}

function setVersionElementText(id, text) {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
}

function renderVersionPills(status = appVersionStatus) {
    const shouldShow = Boolean(status?.update?.available && status?.git?.is_git_checkout);
    const kind = versionStatusKind(status);
    const label = appVersionUpdating
        ? versionText('settings.version.updatingButton', 'Mise à jour...')
        : versionText('settings.version.pillUpdate', 'Update');
    const title = versionDetail(status);

    document.querySelectorAll('.app-update-pill').forEach(pill => {
        pill.classList.toggle('hidden', !shouldShow);
        pill.classList.toggle('is-commit', kind === 'commit');
        pill.classList.toggle('is-release', kind === 'release');
        pill.disabled = appVersionUpdating || appVersionStatusLoading;
        pill.title = title;
        pill.setAttribute('aria-label', title);
        const labelEl = pill.querySelector('.app-update-pill-label');
        if (labelEl) labelEl.textContent = label;
    });
}

function renderVersionSettings(status = appVersionStatus) {
    setVersionElementText('app-version-current', versionCurrentLabel(status));
    setVersionElementText('app-version-status-badge', versionStatusLabel(status));
    setVersionElementText('app-version-detail', versionDetail(status));

    const badge = document.getElementById('app-version-status-badge');
    if (badge) {
        badge.className = `settings-version-badge ${versionStatusClass(status)}`;
    }

    const releaseLink = document.getElementById('app-version-release-link');
    const releaseUrl = status?.update?.url || status?.links?.releases || '';
    if (releaseLink) {
        releaseLink.href = releaseUrl || '#';
        releaseLink.classList.toggle('hidden', !releaseUrl);
    }

    const updateButton = document.getElementById('app-version-update-btn');
    const updateLabel = document.getElementById('app-version-update-label');
    const checkButton = document.getElementById('app-version-check-btn');
    const isGitCheckout = Boolean(status?.git?.is_git_checkout);
    if (updateButton) {
        updateButton.classList.toggle('hidden', !isGitCheckout);
        updateButton.disabled = appVersionUpdating || appVersionStatusLoading;
    }
    if (checkButton) {
        checkButton.disabled = appVersionUpdating || appVersionStatusLoading;
    }
    if (updateLabel) {
        updateLabel.textContent = appVersionUpdating
            ? versionText('settings.version.updatingButton', 'Mise à jour...')
            : versionText('settings.version.updateButton', 'Mettre à jour');
    }
}

function renderAppVersionStatus(status = appVersionStatus) {
    renderVersionPills(status);
    renderVersionSettings(status);
    if (window.lucide) lucide.createIcons();
}

async function loadAppVersionStatus(options = {}) {
    const refresh = options.refresh === true;
    if (appVersionStatusLoading || appVersionUpdating) return appVersionStatus;

    appVersionStatusLoading = true;
    renderAppVersionStatus(appVersionStatus);

    try {
        const response = await apiApp.getVersionStatus(refresh);
        if (response.ok && response.data?.success !== false) {
            appVersionStatus = response.data;
        } else {
            appVersionStatus = {
                success: false,
                current: { version: versionCurrentLabel() },
                update: { status: 'unknown', kind: 'none', available: false },
            };
        }
    } catch (error) {
        console.warn('[VERSION] Update check failed:', error);
        appVersionStatus = {
            success: false,
            current: { version: versionCurrentLabel() },
            update: { status: 'unknown', kind: 'none', available: false },
        };
    } finally {
        appVersionStatusLoading = false;
        renderAppVersionStatus(appVersionStatus);
    }

    return appVersionStatus;
}

function refreshAppVersionStatus() {
    return loadAppVersionStatus({ refresh: true });
}

function sleepVersion(ms) {
    return new Promise(resolve => window.setTimeout(resolve, ms));
}

async function reloadWhenBackendReturns(timeoutMs = 90000) {
    const deadline = Date.now() + timeoutMs;
    await sleepVersion(4500);

    while (Date.now() < deadline) {
        try {
            const response = await fetch(`/api/version/status?refresh=1&t=${Date.now()}`, {
                cache: 'no-store',
            });
            if (response.ok) {
                window.location.reload();
                return;
            }
        } catch {
            // Backend is expected to disappear briefly during restart.
        }
        await sleepVersion(2000);
    }

    window.location.reload();
}

async function updateJoyBoyFromSettings() {
    if (appVersionUpdating) return;

    appVersionUpdating = true;
    renderAppVersionStatus(appVersionStatus);

    try {
        const response = await apiApp.updateAndRestart();
        if (!response.ok || response.data?.success === false) {
            const dirtyFiles = response.data?.dirty_files || [];
            const dirtyText = dirtyFiles.slice(0, 5).join(', ');
            const errorMessage = dirtyFiles.length
                ? versionText(
                    'settings.version.updateDirtyBody',
                    'Des fichiers locaux bloquent git pull : {files}',
                    { files: dirtyText }
                )
                : (response.data?.error || response.error || versionText('settings.version.updateFailedTitle', 'Mise à jour impossible'));
            throw new Error(errorMessage);
        }

        if (typeof Toast !== 'undefined') {
            Toast.info(
                versionText('settings.version.updateStartedTitle', 'Mise à jour'),
                versionText('settings.version.updateStartedBody', 'git pull terminé. JoyBoy redémarre...'),
                5000
            );
        }
        reloadWhenBackendReturns();
    } catch (error) {
        appVersionUpdating = false;
        renderAppVersionStatus(appVersionStatus);
        if (typeof Toast !== 'undefined') {
            Toast.error(
                versionText('settings.version.updateFailedTitle', 'Mise à jour impossible'),
                error.message || String(error)
            );
        } else {
            console.error('[VERSION] Update failed:', error);
        }
    }
}

function openVersionSettings() {
    if (typeof openSettings === 'function') openSettings();
    window.setTimeout(() => {
        const tab = document.getElementById('settings-tab-general');
        if (typeof switchSettingsTab === 'function') switchSettingsTab('general', tab);
        document.getElementById('app-version-section')?.scrollIntoView({ block: 'nearest' });
    }, 0);
}

function initAppVersionStatus() {
    renderAppVersionStatus(appVersionStatus);
    loadAppVersionStatus({ refresh: true });
    window.clearInterval(window.__joyboyVersionRefreshTimer);
    window.__joyboyVersionRefreshTimer = window.setInterval(() => {
        if (!document.hidden) loadAppVersionStatus({ refresh: true });
    }, 5 * 60 * 1000);
}

window.addEventListener('joyboy:locale-changed', () => {
    renderAppVersionStatus(appVersionStatus);
});
