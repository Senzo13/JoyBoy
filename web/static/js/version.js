// ===== APP VERSION / UPDATE STATUS =====

let appVersionStatus = null;
let appVersionStatusLoading = false;

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
    if (kind === 'commit') return 'is-info';
    if (status.update?.status === 'unknown') return 'is-error';
    return 'is-ok';
}

function versionStatusLabel(status = appVersionStatus) {
    if (appVersionStatusLoading) {
        return versionText('settings.version.statusChecking', 'Vérification...');
    }
    if (!status) return versionText('settings.version.statusOffline', 'Indisponible');

    const kind = versionStatusKind(status);
    if (kind === 'release') return versionText('settings.version.statusAvailable', 'Mise à jour');
    if (kind === 'commit') return versionText('settings.version.statusCommit', 'Main plus récent');
    if (status.update?.status === 'no_releases') return versionText('settings.version.statusNoRelease', 'Version locale');
    if (status.update?.status === 'unknown') return versionText('settings.version.statusOffline', 'Indisponible');
    return versionText('settings.version.statusCurrent', 'À jour');
}

function versionDetail(status = appVersionStatus) {
    const current = versionCurrentLabel(status);
    const latest = versionLatestLabel(status);
    const branch = status?.git?.target_branch || 'main';

    if (appVersionStatusLoading) {
        return versionText('settings.version.detailChecking', 'Recherche de release GitHub et comparaison du checkout local...');
    }
    if (!status) {
        return versionText('settings.version.detailOffline', 'Impossible de vérifier les mises à jour pour le moment.');
    }
    if (status.update?.kind === 'release') {
        return versionText(
            'settings.version.detailAvailable',
            'JoyBoy {latest} est disponible. Version installée : {current}.',
            { current, latest }
        );
    }
    if (status.update?.kind === 'commit') {
        const shortCommit = status.git?.short_commit || current;
        const latestCommit = status.git?.latest_short_commit || branch;
        return versionText(
            'settings.version.detailCommit',
            'Ton checkout est sur {current}; origin/{branch} pointe sur {latest}.',
            { current: shortCommit, latest: latestCommit, branch }
        );
    }
    if (status.update?.status === 'no_releases') {
        return versionText(
            'settings.version.detailNoRelease',
            'Aucune release GitHub publiée pour ce repo. Le checker surveillera les releases dès qu’une v0.x existe.',
        );
    }
    if (status.update?.status === 'unknown') {
        return versionText('settings.version.detailOffline', 'Impossible de vérifier les mises à jour pour le moment.');
    }
    return versionText('settings.version.detailCurrent', 'Version installée : {current}. Aucune mise à jour publiée détectée.', { current });
}

function setVersionElementText(id, text) {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
}

function renderVersionPills(status = appVersionStatus) {
    const shouldShow = Boolean(status?.update?.available);
    const kind = versionStatusKind(status);
    const label = kind === 'commit'
        ? versionText('settings.version.pillCommit', 'Main')
        : versionText('settings.version.pillRelease', 'Update');
    const title = versionDetail(status);

    document.querySelectorAll('.app-update-pill').forEach(pill => {
        pill.classList.toggle('hidden', !shouldShow);
        pill.classList.toggle('is-commit', kind === 'commit');
        pill.classList.toggle('is-release', kind === 'release');
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
}

function renderAppVersionStatus(status = appVersionStatus) {
    renderVersionPills(status);
    renderVersionSettings(status);
    if (window.lucide) lucide.createIcons();
}

async function loadAppVersionStatus(options = {}) {
    const refresh = options.refresh === true;
    if (appVersionStatusLoading) return appVersionStatus;

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
    loadAppVersionStatus({ refresh: false });
}

window.addEventListener('joyboy:locale-changed', () => {
    renderAppVersionStatus(appVersionStatus);
});
