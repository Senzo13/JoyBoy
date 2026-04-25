// ===== MODULES / SIGNALATLAS =====

let joyboyModulesCatalog = [];
let signalAtlasAudits = [];
let signalAtlasCurrentAuditId = null;
let signalAtlasCurrentAudit = null;
let signalAtlasModelContext = null;
let signalAtlasProviders = [];
let signalAtlasActiveTab = 'overview';
let signalAtlasRefreshTimer = null;
let signalAtlasOpenPickerId = null;
let signalAtlasLaunchPending = false;
let signalAtlasAdvancedVisible = false;
let signalAtlasHistoryVisible = false;
let signalAtlasSeoDetailsVisible = false;
let signalAtlasAnimateHistoryDrawer = false;
let signalAtlasAnimateSeoDrawer = false;
let signalAtlasSerpPage = 1;
let signalAtlasLastInteractionAt = 0;
let signalAtlasDeferredRefreshTimer = null;
let signalAtlasPendingRefresh = false;
let signalAtlasInteractionTrackingReady = false;
let signalAtlasRefreshInFlight = false;
const signalAtlasCompletionNotifiedAuditIds = new Set();
const auditProgressDisplayState = new Map();
const SIGNALATLAS_SERP_PAGE_SIZE = 10;
const SIGNALATLAS_INTERACTION_IDLE_MS = 1400;
const SIGNALATLAS_DEFAULT_PAGE_BUDGET = 12;
const SIGNALATLAS_MAX_PAGE_BUDGET = 1500;
const SIGNALATLAS_UNLIMITED_PAGE_BUDGET = 'unlimited';
const SIGNALATLAS_PAGE_BUDGET_STEPS = [8, 12, 20, 30, 40, 50, 75, 100, 150, 250, 500, 750, 1000, 1500];
const SIGNALATLAS_HOST_LABEL_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;
const SIGNALATLAS_AUDIT_PROFILES = {
    basic: {
        max_pages: 12,
        depth: 2,
        render_js: false,
        preset: 'fast',
        level: 'basic_summary',
    },
    elevated: {
        max_pages: 20,
        depth: 3,
        render_js: true,
        preset: 'balanced',
        level: 'full_expert_analysis',
    },
    ultra: {
        max_pages: 1500,
        depth: 5,
        render_js: true,
        preset: 'expert',
        level: 'ai_remediation_pack',
    },
};
let signalAtlasDraft = {
    target: '',
    profile: 'elevated',
    mode: 'public',
    max_pages: 20,
    depth: 3,
    render_js: true,
    model: '',
    preset: 'balanced',
    level: 'full_expert_analysis',
    compare_model: '',
};
let perfAtlasAudits = [];
let perfAtlasCurrentAuditId = null;
let perfAtlasCurrentAudit = null;
let perfAtlasModelContext = null;
let perfAtlasProviders = [];
let perfAtlasActiveTab = 'overview';
let perfAtlasRefreshTimer = null;
let perfAtlasOpenPickerId = null;
let perfAtlasLaunchPending = false;
let perfAtlasAdvancedVisible = false;
let perfAtlasRefreshInFlight = false;
const PERFATLAS_DEFAULT_PAGE_BUDGET = 8;
const PERFATLAS_MAX_PAGE_BUDGET = 20;
const PERFATLAS_UNLIMITED_PAGE_BUDGET = 'unlimited';
const PERFATLAS_PAGE_BUDGET_STEPS = [3, 5, 8, 12, 16, 20];
const PERFATLAS_AUDIT_PROFILES = {
    basic: {
        max_pages: 3,
        preset: 'fast',
        level: 'basic_summary',
    },
    elevated: {
        max_pages: 8,
        preset: 'balanced',
        level: 'full_expert_analysis',
    },
    ultra: {
        max_pages: 20,
        preset: 'expert',
        level: 'ai_remediation_pack',
    },
};
let perfAtlasDraft = {
    target: '',
    profile: 'elevated',
    mode: 'public',
    max_pages: 8,
    model: '',
    preset: 'balanced',
    level: 'full_expert_analysis',
    compare_model: '',
};

const NATIVE_AUDIT_MODULE_FALLBACK_CATALOG = [
    {
        id: 'signalatlas',
        name: 'SignalAtlas',
        tagline: 'Deterministic SEO and web visibility intelligence',
        description: 'Technical crawl, indexability checks, architecture analysis, AI interpretation, and export-ready remediation packs.',
        icon: 'radar',
        status: 'active',
        entry_view: 'signalatlas-view',
        capabilities: ['technical_audit', 'crawlability', 'indexability', 'visibility', 'ai_remediation', 'exports'],
        premium: true,
        available: true,
        locked_reason: '',
        featured: true,
        theme: 'signalatlas',
        category: 'audit',
    },
    {
        id: 'perfatlas',
        name: 'PerfAtlas',
        tagline: 'Performance intelligence and remediation for production websites',
        description: 'Field data, lab probes, delivery diagnostics, owner-aware connectors, AI remediation packs, and export-ready performance reports.',
        icon: 'zap',
        status: 'active',
        entry_view: 'perfatlas-view',
        capabilities: ['core_web_vitals', 'lab_performance', 'delivery_diagnostics', 'owner_context', 'ai_remediation', 'exports'],
        premium: true,
        available: true,
        locked_reason: '',
        featured: true,
        theme: 'perfatlas',
        category: 'audit',
    },
    {
        id: 'cyberatlas',
        name: 'CyberAtlas',
        tagline: 'Defensive web and API security posture intelligence',
        description: 'TLS, security headers, exposure probes, OpenAPI surface mapping, session hygiene, evidence packs, and AI remediation reports.',
        icon: 'shield-check',
        status: 'active',
        entry_view: 'cyberatlas-view',
        capabilities: ['tls_security', 'security_headers', 'exposure_mapping', 'api_surface', 'ai_remediation', 'exports'],
        premium: true,
        available: true,
        locked_reason: '',
        featured: true,
        theme: 'cyberatlas',
        category: 'audit',
    },
    {
        id: 'deployatlas',
        name: 'DeployAtlas',
        tagline: 'AI-assisted VPS deployment with SSH, HTTPS and rollback',
        description: 'Project analysis, saved server profiles, SSH evidence, guided deployment plans, live terminal progress, HTTPS runbooks, and rollback snapshots.',
        icon: 'server-cog',
        status: 'active',
        entry_view: 'deployatlas-view',
        capabilities: ['vps_inventory', 'ssh_fingerprint', 'project_analysis', 'deployment_plan', 'https_ssl', 'rollback'],
        premium: true,
        available: true,
        locked_reason: '',
        featured: true,
        theme: 'deployatlas',
        category: 'deployment',
    },
];

function signalAtlasNormalizePageBudget(value, fallback = SIGNALATLAS_DEFAULT_PAGE_BUDGET) {
    const raw = String(value ?? '').trim().toLowerCase();
    if (raw === SIGNALATLAS_UNLIMITED_PAGE_BUDGET) return SIGNALATLAS_UNLIMITED_PAGE_BUDGET;
    const parsed = Number.parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
        return Math.min(parsed, SIGNALATLAS_MAX_PAGE_BUDGET);
    }
    return fallback;
}

function signalAtlasResolvedPageBudget(value, fallback = SIGNALATLAS_DEFAULT_PAGE_BUDGET) {
    const normalized = signalAtlasNormalizePageBudget(value, fallback);
    return normalized === SIGNALATLAS_UNLIMITED_PAGE_BUDGET
        ? SIGNALATLAS_MAX_PAGE_BUDGET
        : normalized;
}

function perfAtlasNormalizePageBudget(value, fallback = PERFATLAS_DEFAULT_PAGE_BUDGET) {
    const raw = String(value ?? '').trim().toLowerCase();
    if (raw === PERFATLAS_UNLIMITED_PAGE_BUDGET) return PERFATLAS_UNLIMITED_PAGE_BUDGET;
    const parsed = Number.parseInt(raw, 10);
    if (Number.isFinite(parsed) && parsed > 0) {
        return Math.min(parsed, PERFATLAS_MAX_PAGE_BUDGET);
    }
    return fallback;
}

function perfAtlasResolvedPageBudget(value, fallback = PERFATLAS_DEFAULT_PAGE_BUDGET) {
    const normalized = perfAtlasNormalizePageBudget(value, fallback);
    return normalized === PERFATLAS_UNLIMITED_PAGE_BUDGET
        ? PERFATLAS_MAX_PAGE_BUDGET
        : normalized;
}

function signalAtlasIsValidPublicHost(hostname) {
    const clean = String(hostname || '').trim().toLowerCase().replace(/\.+$/, '');
    if (!clean || !clean.includes('.')) return false;
    const labels = clean.split('.').filter(Boolean);
    if (labels.length < 2) return false;
    const tld = labels[labels.length - 1] || '';
    if (tld.length < 2 || /^\d+$/.test(tld)) return false;
    return labels.every(label => SIGNALATLAS_HOST_LABEL_RE.test(label));
}

function signalAtlasValidateTarget(value) {
    const raw = String(value || '').trim();
    if (!raw) {
        return {
            valid: false,
            present: false,
            normalized: '',
            message: moduleT('signalatlas.targetRequired', 'Ajoute d’abord un vrai domaine ou une URL publique, par exemple https://nevomove.com/.'),
        };
    }

    const candidate = raw.includes('://') ? raw : `https://${raw}`;
    let parsed = null;
    try {
        parsed = new URL(candidate);
    } catch (error) {
        parsed = null;
    }

    const invalidMessage = moduleT('signalatlas.targetInvalid', 'Utilise un vrai domaine ou une URL publique complète, par exemple https://nevomove.com/.');
    if (!parsed) {
        return { valid: false, present: true, normalized: '', message: invalidMessage };
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) {
        return { valid: false, present: true, normalized: '', message: invalidMessage };
    }
    if (parsed.username || parsed.password || !signalAtlasIsValidPublicHost(parsed.hostname)) {
        return { valid: false, present: true, normalized: '', message: invalidMessage };
    }

    return {
        valid: true,
        present: true,
        normalized: parsed.toString(),
        message: '',
    };
}

function renderSignalAtlasTargetValidationUi() {
    const input = document.getElementById('signalatlas-target-input');
    const feedback = document.getElementById('signalatlas-target-feedback');
    const launchButton = document.getElementById('signalatlas-launch-btn');
    const validation = signalAtlasValidateTarget(input?.value ?? signalAtlasDraft.target);
    const showError = validation.present && !validation.valid;

    if (input) {
        input.classList.toggle('is-invalid', showError);
        input.setAttribute('aria-invalid', showError ? 'true' : 'false');
    }
    if (feedback) {
        feedback.textContent = showError ? validation.message : '';
        feedback.classList.toggle('is-visible', showError);
    }
    if (launchButton) {
        launchButton.disabled = signalAtlasLaunchPending || !validation.valid;
    }

    return validation;
}

function signalAtlasMarkInteraction() {
    signalAtlasLastInteractionAt = Date.now();
}

function signalAtlasSupportsTextSelection(node) {
    return !!node
        && typeof node.selectionStart === 'number'
        && typeof node.selectionEnd === 'number'
        && typeof node.setSelectionRange === 'function';
}

function captureSignalAtlasUiState() {
    const view = getSignalAtlasView();
    const host = document.getElementById('signalatlas-view-content');
    const state = {
        viewScrollTop: view?.scrollTop ?? 0,
        scrollTops: {},
        focus: null,
    };
    if (host) {
        const serpResults = host.querySelector('.signalatlas-serp-results');
        const historyList = host.querySelector('.signalatlas-history-list');
        if (serpResults) state.scrollTops.serpResults = serpResults.scrollTop;
        if (historyList) state.scrollTops.historyList = historyList.scrollTop;
    }

    const active = document.activeElement;
    if (view && active && view.contains(active) && active.id) {
        state.focus = {
            id: active.id,
            value: 'value' in active ? active.value : null,
            scrollLeft: 'scrollLeft' in active ? active.scrollLeft : null,
            selectionStart: signalAtlasSupportsTextSelection(active) ? active.selectionStart : null,
            selectionEnd: signalAtlasSupportsTextSelection(active) ? active.selectionEnd : null,
            selectionDirection: signalAtlasSupportsTextSelection(active) ? active.selectionDirection : null,
        };
    }

    return state;
}

function restoreSignalAtlasUiState(state) {
    if (!state) return;
    const apply = () => {
        const view = getSignalAtlasView();
        const host = document.getElementById('signalatlas-view-content');
        if (view && Number.isFinite(state.viewScrollTop)) {
            view.scrollTop = state.viewScrollTop;
        }
        if (host) {
            const serpResults = host.querySelector('.signalatlas-serp-results');
            const historyList = host.querySelector('.signalatlas-history-list');
            if (serpResults && Number.isFinite(state.scrollTops?.serpResults)) {
                serpResults.scrollTop = state.scrollTops.serpResults;
            }
            if (historyList && Number.isFinite(state.scrollTops?.historyList)) {
                historyList.scrollTop = state.scrollTops.historyList;
            }
        }
        if (state.focus?.id) {
            const focusNode = document.getElementById(state.focus.id);
            if (focusNode && typeof focusNode.focus === 'function') {
                if ('value' in focusNode && typeof state.focus.value === 'string') {
                    focusNode.value = state.focus.value;
                }
                focusNode.focus({ preventScroll: true });
                if (Number.isFinite(state.focus.scrollLeft) && 'scrollLeft' in focusNode) {
                    focusNode.scrollLeft = state.focus.scrollLeft;
                }
                if (
                    signalAtlasSupportsTextSelection(focusNode)
                    && Number.isFinite(state.focus.selectionStart)
                    && Number.isFinite(state.focus.selectionEnd)
                ) {
                    focusNode.setSelectionRange(
                        state.focus.selectionStart,
                        state.focus.selectionEnd,
                        state.focus.selectionDirection || 'none'
                    );
                }
            }
        }
    };

    requestAnimationFrame(() => {
        apply();
        requestAnimationFrame(apply);
    });
}

function signalAtlasHasInteractiveFocus() {
    const view = getSignalAtlasView();
    const active = document.activeElement;
    if (!view || !active || !view.contains(active)) return false;
    if (active.isContentEditable) return true;
    const tagName = String(active.tagName || '').toLowerCase();
    return ['input', 'textarea', 'select'].includes(tagName);
}

function signalAtlasShouldDeferRefresh() {
    const recentlyInteracted = Date.now() - signalAtlasLastInteractionAt < SIGNALATLAS_INTERACTION_IDLE_MS;
    return signalAtlasHasInteractiveFocus() || recentlyInteracted || !!signalAtlasOpenPickerId;
}

function scheduleSignalAtlasDeferredRefresh() {
    if (signalAtlasDeferredRefreshTimer) {
        clearTimeout(signalAtlasDeferredRefreshTimer);
    }
    const delay = Math.max(180, SIGNALATLAS_INTERACTION_IDLE_MS - (Date.now() - signalAtlasLastInteractionAt) + 90);
    signalAtlasDeferredRefreshTimer = setTimeout(async () => {
        signalAtlasDeferredRefreshTimer = null;
        if (!signalAtlasPendingRefresh || !isSignalAtlasVisible()) return;
        if (signalAtlasShouldDeferRefresh()) {
            scheduleSignalAtlasDeferredRefresh();
            return;
        }
        signalAtlasPendingRefresh = false;
        await refreshSignalAtlasWorkspace({ allowDefer: false });
    }, delay);
}

function ensureSignalAtlasInteractionTracking() {
    if (signalAtlasInteractionTrackingReady) return;
    const view = getSignalAtlasView();
    if (!view) return;
    const markIfRelevant = (event) => {
        if (!isSignalAtlasVisible()) return;
        const target = event?.target;
        if (!target || (target !== view && !view.contains(target))) return;
        signalAtlasMarkInteraction();
    };
    view.addEventListener('focusin', markIfRelevant, true);
    view.addEventListener('input', markIfRelevant, true);
    view.addEventListener('pointerdown', markIfRelevant, true);
    view.addEventListener('wheel', markIfRelevant, { passive: true, capture: true });
    view.addEventListener('touchmove', markIfRelevant, { passive: true, capture: true });
    view.addEventListener('scroll', markIfRelevant, true);
    signalAtlasInteractionTrackingReady = true;
}

function signalAtlasProviderStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'executed') return moduleT('signalatlas.confirmed', 'Confirmed');
    if (clean === 'not_requested') return moduleT('signalatlas.no', 'No');
    if (clean === 'playwright_not_installed') return moduleT('signalatlas.providerConnectorMissing', 'Connector missing');
    if (clean === 'execution_failed') return moduleT('signalatlas.providerError', 'Error');
    if (clean === 'configured') return moduleT('signalatlas.providerConfigured', 'Configured');
    if (clean === 'confirmed') return moduleT('signalatlas.providerConfirmed', 'Confirmed');
    if (clean === 'not_configured') return moduleT('signalatlas.providerNotConfigured', 'Not configured');
    if (clean === 'target_mismatch') return moduleT('signalatlas.providerTargetMismatch', 'Cible non alignée');
    if (clean === 'property_unverified') return moduleT('signalatlas.providerUnverified', 'Property not verified');
    if (clean === 'connector_missing') return moduleT('signalatlas.providerConnectorMissing', 'Connector missing');
    if (clean === 'auth_error') return moduleT('signalatlas.providerAuthError', 'Auth error');
    if (clean === 'scaffolded') return moduleT('signalatlas.providerScaffolded', 'Scaffolded');
    if (clean === 'error') return moduleT('signalatlas.providerError', 'Error');
    return clean || moduleT('signalatlas.statusUnknown', 'Unknown');
}

function signalAtlasProviderTone(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'confirmed' || clean === 'configured') return 'is-good';
    if (clean === 'target_mismatch' || clean === 'property_unverified' || clean === 'scaffolded') return 'is-warn';
    if (clean === 'connector_missing' || clean === 'auth_error' || clean === 'error') return 'is-danger';
    return '';
}

function signalAtlasProviderSummary(provider) {
    const id = String(provider?.id || '').trim().toLowerCase();
    const status = String(provider?.status || '').trim().toLowerCase();
    if (id === 'google_search_console') {
        if (status === 'confirmed') {
            return moduleT('signalatlas.providerSummaryGscConfirmed', 'Une confirmation propriétaire est disponible pour cette cible via Search Console.');
        }
        if (status === 'configured') {
            return moduleT('signalatlas.providerSummaryGscConfigured', 'Search Console est configuré et prêt pour un audit propriétaire vérifié sur une propriété correspondante.');
        }
        if (status === 'target_mismatch') {
            return moduleT('signalatlas.providerSummaryGscMismatch', 'Search Console est configuré, mais la propriété enregistrée ne correspond pas encore à la cible courante.');
        }
        if (status === 'connector_missing') {
            return moduleT('signalatlas.providerSummaryConnectorMissing', 'Le provider est configuré, mais le client Python requis n’est pas disponible dans ce runtime.');
        }
        return moduleT('signalatlas.providerSummaryGscMissing', 'Connect an official property to move Google-specific data from estimated to confirmed.');
    }
    if (id === 'semrush') {
        return status === 'configured'
            ? moduleT('signalatlas.providerSummarySemrushReady', 'Semrush est configuré et pourra enrichir les prochaines passes potentiel organique avec de l’intelligence mots-clés externe.')
            : moduleT('signalatlas.providerSummarySemrushLocked', 'Semrush est préparé comme provider optionnel verrouillé pour volume, difficulté, concurrents et pages organiques externes.');
    }
    if (status === 'configured') {
        return moduleT('signalatlas.providerSummaryConfigured', 'Cette intégration est configurée et peut enrichir de futures couches d’audit.');
    }
    return moduleT('signalatlas.providerSummaryScaffolded', 'Cette intégration est prévue dans l’architecture et enrichira de futures passes propriétaire.');
}

function perfAtlasOwnerConnectorSummary(provider) {
    const name = provider?.name || provider?.id || 'Provider';
    const status = String(provider?.status || '').trim().toLowerCase();
    if (status === 'ready') {
        return moduleT('perfatlas.providerSummaryOwnerReady', '{provider} matches this host and can enrich deployment or edge context right now.', { provider: name });
    }
    if (status === 'target_mismatch') {
        return moduleT('perfatlas.providerSummaryOwnerMismatch', '{provider} is configured, but the saved project or zone does not match this host yet.', { provider: name });
    }
    if (status === 'configured') {
        return moduleT('perfatlas.providerSummaryOwnerConfigured', '{provider} is configured and will enrich the audit when verified-owner mode is used on a matching host.', { provider: name });
    }
    if (status === 'scaffolded') {
        return moduleT('perfatlas.providerSummaryOwnerScaffolded', '{provider} is available as an owner connector, but it is not configured yet.', { provider: name });
    }
    if (status === 'partial' || status === 'auth_error' || status === 'connector_missing' || status === 'error') {
        return moduleT('perfatlas.providerSummaryLimited', '{provider} is only partially available in this runtime, so PerfAtlas will keep the owner context conservative.', { provider: name });
    }
    return signalAtlasProviderSummary(provider);
}

function perfAtlasProviderSummary(provider) {
    const id = String(provider?.id || '').trim().toLowerCase();
    const status = String(provider?.status || '').trim().toLowerCase();
    if (id === 'google_search_console') {
        return signalAtlasProviderSummary(provider);
    }
    if (id === 'crux_api') {
        return status === 'configured' || status === 'confirmed'
            ? moduleT('perfatlas.providerSummaryCruxReady', 'CrUX can enrich the audit with public field metrics when Google has enough real-user data for this target.')
            : moduleT('perfatlas.providerSummaryCruxMissing', 'Add CRUX_API_KEY or GOOGLE_API_KEY to unlock stable CrUX field-metrics quota.');
    }
    if (id === 'crux_history_api') {
        return status === 'configured' || status === 'confirmed'
            ? moduleT('perfatlas.providerSummaryCruxHistoryReady', 'CrUX History can confirm whether Core Web Vitals are improving, stable, or regressing over time.')
            : moduleT('perfatlas.providerSummaryCruxHistoryMissing', 'CrUX History uses the same Google API key as CrUX and stays unavailable until that key is configured.');
    }
    if (id === 'pagespeed_insights') {
        return status === 'configured' || status === 'confirmed'
            ? moduleT('perfatlas.providerSummaryPagespeedReady', 'PageSpeed Insights can add remote Lighthouse runs and opportunity hints when local lab probes are limited.')
            : moduleT('perfatlas.providerSummaryPagespeedMissing', 'Add PAGESPEED_API_KEY or GOOGLE_API_KEY to stabilize PageSpeed Insights quota and richer lab checks.');
    }
    if (id === 'webpagetest') {
        return status === 'configured' || status === 'confirmed'
            ? moduleT('perfatlas.providerSummaryWebPageTestReady', 'WebPageTest is configured for future deep-lab waterfall and filmstrip enrichment.')
            : moduleT('perfatlas.providerSummaryWebPageTestMissing', 'Add WEBPAGETEST_API_KEY to prepare deep-lab waterfall, filmstrip, and location-based runs.');
    }
    if (id === 'vercel' || id === 'netlify' || id === 'cloudflare') {
        return perfAtlasOwnerConnectorSummary(provider);
    }
    if (status === 'partial' || status === 'auth_error' || status === 'connector_missing' || status === 'error') {
        return moduleT('perfatlas.providerSummaryLimited', '{provider} is only partially available in this runtime, so PerfAtlas will keep the owner context conservative.', {
            provider: provider?.name || provider?.id || 'Provider',
        });
    }
    return signalAtlasProviderSummary(provider);
}

function signalAtlasRenderSummary(renderDetection = {}) {
    if (!renderDetection.render_js_requested) {
        return moduleT('signalatlas.renderSummaryNotRequested', 'Raw HTML baseline only.');
    }
    if (renderDetection.render_js_executed) {
        return moduleT('signalatlas.renderSummaryExecuted', 'Sondes de rendu JS exécutées sur {count} page(s).', {
            count: renderDetection.executed_page_count || 0,
        });
    }
    return moduleT('signalatlas.renderSummaryUnavailable', 'Le rendu JS a été demandé mais n’a pas pu s’exécuter.');
}

function moduleT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function signalAtlasProfileConfig(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    return SIGNALATLAS_AUDIT_PROFILES[clean] || SIGNALATLAS_AUDIT_PROFILES.elevated;
}

function perfAtlasProfileConfig(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    return PERFATLAS_AUDIT_PROFILES[clean] || PERFATLAS_AUDIT_PROFILES.elevated;
}

function signalAtlasProfileLabel(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    if (clean === 'basic') return moduleT('signalatlas.auditProfileBasic', 'Basique');
    if (clean === 'ultra') return moduleT('signalatlas.auditProfileUltra', 'Ultra');
    return moduleT('signalatlas.auditProfileElevated', 'Élevé');
}

function signalAtlasProfileSummary(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    if (clean === 'basic') {
        return moduleT('signalatlas.auditProfileBasicDesc', 'Passe légère pour un premier diagnostic rapide.');
    }
    if (clean === 'ultra') {
        return moduleT('signalatlas.auditProfileUltraDesc', 'Passe la plus poussée : crawl large intelligent, rendu JS et pack IA complet. Si le site est petit, SignalAtlas s’arrête dès que le graphe est épuisé.');
    }
    return moduleT('signalatlas.auditProfileElevatedDesc', 'Bon équilibre entre profondeur technique, rendu JS et restitution IA.');
}

function perfAtlasProfileLabel(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    if (clean === 'basic') return moduleT('perfatlas.profileBasic', 'Basic');
    if (clean === 'ultra') return moduleT('perfatlas.profileUltra', 'Ultra');
    return moduleT('perfatlas.profileElevated', 'Elevated');
}

function perfAtlasProfileSummary(profileId) {
    const clean = String(profileId || '').trim().toLowerCase();
    if (clean === 'basic') {
        return moduleT('perfatlas.profileBasicDesc', 'Short pass on the homepage and a single representative lab probe.');
    }
    if (clean === 'ultra') {
        return moduleT('perfatlas.profileUltraDesc', 'Broadest pass with multi-run lab checks, richer owner context, and a full AI remediation pack.');
    }
    return moduleT('perfatlas.profileElevatedDesc', 'Balanced pass across field signals, representative lab runs, and actionable delivery diagnostics.');
}

function signalAtlasContextOptionLabel(collectionName, value, fallback = '') {
    const items = Array.isArray(signalAtlasModelContext?.[collectionName]) ? signalAtlasModelContext[collectionName] : [];
    const match = items.find(item => String(item?.id || '') === String(value || ''));
    return match?.label || fallback || value || '';
}

function signalAtlasLatestInterpretation(audit) {
    const items = Array.isArray(audit?.interpretations) ? audit.interpretations : [];
    return items.length ? items[items.length - 1] : null;
}

function signalAtlasReportModelInfo(audit) {
    const latest = signalAtlasLatestInterpretation(audit);
    const configured = audit?.metadata?.ai || {};
    if (!latest && String(configured?.level || '').toLowerCase() === 'no_ai') {
        return {
            state: 'none',
            label: moduleT('signalatlas.noAiGeneratedYet', 'Pas encore de lecture IA'),
            detail: moduleT('signalatlas.reportGeneratedWithoutAi', 'Ce rapport reste purement déterministe tant qu’aucune interprétation IA n’a été générée.'),
            meta: '',
        };
    }
    const model = latest?.model || configured?.model || '';
    if (!model) {
        return {
            state: 'none',
            label: moduleT('signalatlas.noAiGeneratedYet', 'Pas encore de lecture IA'),
            detail: moduleT('signalatlas.reportGeneratedWithoutAi', 'Ce rapport reste purement déterministe tant qu’aucune interprétation IA n’a été générée.'),
            meta: '',
        };
    }
    const level = latest?.level || configured?.level || '';
    const preset = latest?.preset || configured?.preset || '';
    const meta = [signalAtlasContextOptionLabel('levels', level), signalAtlasContextOptionLabel('presets', preset)]
        .filter(Boolean)
        .join(' · ');
    if (!latest) {
        return {
            state: 'planned',
            label: model,
            detail: moduleT('signalatlas.reportPlannedWithModel', 'La prochaine lecture IA utilisera {model}', { model }),
            meta,
        };
    }
    return {
        state: 'generated',
        label: model,
        detail: moduleT('signalatlas.generatedWithModel', 'Rapport IA généré avec {model}', { model }),
        meta,
    };
}

function signalAtlasCircularCircumference(radius = 46) {
    return 2 * Math.PI * radius;
}

function renderSignalAtlasScoreRing(scoreValue, statusLabel = '', ringKey = '') {
    const numeric = Number(scoreValue);
    const hasScore = Number.isFinite(numeric);
    const safeValue = hasScore ? Math.max(0, Math.min(100, Math.round(numeric))) : 0;
    const circumference = signalAtlasCircularCircumference();
    const dashOffset = hasScore
        ? circumference - (circumference * safeValue / 100)
        : circumference;
    return `
        <div class="signalatlas-score-ring-wrap">
            <div class="signalatlas-score-ring ${hasScore ? signalAtlasScoreTone(scoreValue) : 'is-empty'}" data-score="${hasScore ? safeValue : ''}" data-has-score="${hasScore ? 'true' : 'false'}" data-ring-key="${escapeHtml(hasScore ? (ringKey || String(safeValue)) : '')}">
                <svg viewBox="0 0 120 120" aria-hidden="true">
                    <circle class="signalatlas-score-ring-track" cx="60" cy="60" r="46"></circle>
                    <circle
                        class="signalatlas-score-ring-progress"
                        cx="60"
                        cy="60"
                        r="46"
                        data-circumference="${escapeHtml(String(circumference))}"
                        style="stroke-dasharray:${escapeHtml(String(circumference))};stroke-dashoffset:${escapeHtml(String(dashOffset))}"
                    ></circle>
                </svg>
                <div class="signalatlas-score-ring-center">
                    <div class="signalatlas-score-ring-value">${escapeHtml(String(Number.isFinite(numeric) ? safeValue : '--'))}</div>
                    <div class="signalatlas-score-ring-total">/100</div>
                </div>
            </div>
            <div class="signalatlas-score-ring-copy">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.scoreLabel', 'Score'))}</div>
                <div class="signalatlas-score-ring-status">${escapeHtml(statusLabel || moduleT('signalatlas.statusUnknown', 'Inconnu'))}</div>
            </div>
        </div>
    `;
}

function signalAtlasTrimText(value, maxLength = 160) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function signalAtlasSeverityLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'critical') return moduleT('signalatlas.severityCritical', 'Critique');
    if (clean === 'high') return moduleT('signalatlas.severityHigh', 'Élevé');
    if (clean === 'medium') return moduleT('signalatlas.severityMedium', 'Moyen');
    if (clean === 'low') return moduleT('signalatlas.severityLow', 'Faible');
    if (clean === 'info') return moduleT('signalatlas.severityInfo', 'Info');
    return value || moduleT('signalatlas.statusUnknown', 'Inconnu');
}

function signalAtlasConfidenceLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'confirmed') return moduleT('signalatlas.confirmed', 'Confirmé');
    if (clean === 'strong signal') return moduleT('signalatlas.strongSignal', 'Signal fort');
    if (clean === 'estimated') return moduleT('signalatlas.estimated', 'Estimé');
    if (clean === 'unknown') return moduleT('signalatlas.unknown', 'Inconnu');
    if (clean === 'blocked') return moduleT('signalatlas.blocked', 'Bloqué');
    return value || moduleT('signalatlas.statusUnknown', 'Inconnu');
}

function signalAtlasRiskLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'high') return moduleT('signalatlas.riskHigh', 'Risque élevé');
    if (clean === 'moderate') return moduleT('signalatlas.riskModerate', 'Risque modéré');
    if (clean === 'low') return moduleT('signalatlas.riskLow', 'Risque faible');
    return signalAtlasConfidenceLabel(value);
}

function signalAtlasModeLabel(value) {
    return String(value || '').trim().toLowerCase() === 'verified_owner'
        ? moduleT('signalatlas.ownerMode', 'Propriétaire vérifié')
        : moduleT('signalatlas.publicMode', 'Audit public');
}

function nativeAuditLocale() {
    const raw = String(
        window.currentLanguage
        || document.documentElement?.lang
        || navigator.language
        || 'en'
    ).trim();
    if (/^fr\b/i.test(raw)) return 'fr-FR';
    if (/^es\b/i.test(raw)) return 'es-ES';
    if (/^it\b/i.test(raw)) return 'it-IT';
    if (/^en\b/i.test(raw)) return 'en-US';
    return raw || 'en-US';
}

function formatNativeAuditTimestamp(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return '';
    try {
        return new Intl.DateTimeFormat(nativeAuditLocale(), {
            dateStyle: 'medium',
            timeStyle: 'short',
        }).format(parsed);
    } catch (error) {
        return parsed.toLocaleString();
    }
}

function nativeAuditTimestampLabel(namespace, audit) {
    const formatted = formatNativeAuditTimestamp(audit?.updated_at || audit?.created_at);
    if (!formatted) return '';
    return moduleT(`${namespace}.auditTimestampLabel`, 'Audit run {timestamp}', {
        timestamp: formatted,
    });
}

function signalAtlasRenderingLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'spa') return moduleT('signalatlas.renderingSpa', 'SPA');
    if (clean === 'hybrid') return moduleT('signalatlas.renderingHybrid', 'Hybride');
    if (clean === 'server_rendered') return moduleT('signalatlas.renderingServerRendered', 'Rendu serveur');
    if (clean === 'ssg') return moduleT('signalatlas.renderingSsg', 'SSG');
    if (clean === 'isr') return moduleT('signalatlas.renderingIsr', 'ISR');
    return value || moduleT('signalatlas.renderingUnknown', 'Rendu inconnu');
}

function signalAtlasPlatformLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (!clean || clean === 'custom') return moduleT('signalatlas.customStack', 'Stack custom');
    if (clean === 'custom react/vite') return moduleT('signalatlas.customReactVite', 'Custom React/Vite');
    return value;
}

function signalAtlasScoreLabel(score) {
    const id = String(score?.id || '').trim().toLowerCase();
    return moduleT(`signalatlas.scoreCategory_${id}`, score?.label || id || moduleT('signalatlas.scoreLabel', 'Score'));
}

function auditTranslationKey(value) {
    return String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '');
}

function perfAtlasScoreLabel(score) {
    const id = auditTranslationKey(score?.id || score?.label);
    return moduleT(`perfatlas.scoreCategory_${id}`, score?.label || id || moduleT('signalatlas.scoreLabel', 'Score'));
}

function perfAtlasFindingKey(item) {
    return auditTranslationKey(item?.id || item?.title);
}

function perfAtlasFindingTitle(item) {
    const key = perfAtlasFindingKey(item);
    return moduleT(`perfatlas.findingTitle_${key}`, item?.title || moduleT('perfatlas.findingFallbackTitle', 'Finding'));
}

function perfAtlasFindingDiagnostic(item) {
    const key = perfAtlasFindingKey(item);
    return moduleT(`perfatlas.findingDiagnostic_${key}`, item?.diagnostic || '');
}

function perfAtlasFindingFix(item) {
    const key = perfAtlasFindingKey(item);
    return moduleT(`perfatlas.findingFix_${key}`, item?.recommended_fix || '');
}

function perfAtlasCategoryLabel(value) {
    const key = auditTranslationKey(value);
    return moduleT(`perfatlas.category_${key}`, String(value || '').replace(/_/g, ' '));
}

function perfAtlasRuntimeLabel(value) {
    const key = auditTranslationKey(value);
    if (!key) return moduleT('perfatlas.runtimeUnknown', 'Indisponible');
    return moduleT(`perfatlas.runtime_${key}`, value || moduleT('perfatlas.runtimeUnknown', 'Indisponible'));
}

function perfAtlasAssetKindLabel(value) {
    const key = auditTranslationKey(value || 'asset');
    return moduleT(`perfatlas.assetKind_${key}`, value || moduleT('perfatlas.assetKind_asset', 'Ressource'));
}

function perfAtlasAvailabilityLabel(value) {
    return value
        ? moduleT('perfatlas.available', 'Disponible')
        : moduleT('perfatlas.notAvailable', 'Absent');
}

function perfAtlasScoreGuardrailMessage(summary = {}) {
    const guardrails = Array.isArray(summary.score_guardrails) ? summary.score_guardrails : [];
    if (!guardrails.length) return '';
    const hasGlobalCap = guardrails.some(item => String(item?.bucket || '') === 'global');
    if (!hasGlobalCap) return '';
    if (!summary.lab_data_available && !summary.field_data_available) {
        return moduleT('perfatlas.scoreGuardrailNoLabField', 'Score capped because neither lab nor field evidence was available.');
    }
    if (!summary.lab_data_available) {
        return moduleT('perfatlas.scoreGuardrailNoLab', 'Score capped because no reliable Lighthouse or PSI lab run was available.');
    }
    if (!summary.field_data_available) {
        return moduleT('perfatlas.scoreGuardrailNoField', 'Score capped because public field data was not available.');
    }
    return moduleT('perfatlas.scoreGuardrailAnchored', 'Score anchored to the representative Lighthouse or PSI performance result.');
}

function perfAtlasTrendDirectionLabel(value) {
    const key = auditTranslationKey(value || 'steady');
    return moduleT(`perfatlas.trend_${key}`, value || moduleT('perfatlas.trend_steady', 'Stable'));
}

function perfAtlasOpportunityTitle(item) {
    const key = auditTranslationKey(item?.id || item?.title);
    return moduleT(`perfatlas.opportunityTitle_${key}`, item?.title || item?.id || moduleT('perfatlas.opportunityFallbackTitle', 'Opportunité'));
}

function signalAtlasVisibilityLabel(key) {
    const clean = String(key || '').trim().toLowerCase();
    return moduleT(`signalatlas.visibilityLabel_${clean}`, clean.replace(/_/g, ' '));
}

function signalAtlasVisibilityStatusLabel(key, value = {}) {
    const cleanKey = String(key || '').trim().toLowerCase();
    if (cleanKey === 'js_render_risk') {
        return signalAtlasRiskLabel(value?.status || value?.confidence || '');
    }
    return signalAtlasConfidenceLabel(value?.confidence || value?.status || '');
}

function signalAtlasIndexableEstimate(audit) {
    const pages = Array.isArray(audit?.snapshot?.pages) ? audit.snapshot.pages : [];
    return pages.filter(page => {
        const status = Number(page?.status_code || 0);
        const contentType = String(page?.content_type || '').toLowerCase();
        return status >= 200
            && status < 400
            && !page?.noindex
            && (!contentType || contentType.includes('html'));
    }).length;
}

function signalAtlasSearchMetrics(audit) {
    const snapshot = audit?.snapshot || {};
    const rankedResults = signalAtlasSerpCandidates(audit);
    const discoveredCount = Array.isArray(snapshot.discovered_urls) ? snapshot.discovered_urls.length : Number(snapshot.page_count || 0);
    const sampledCount = Number(snapshot.page_count || (Array.isArray(snapshot.pages) ? snapshot.pages.length : 0));
    const issuesCount = Array.isArray(audit?.findings) ? audit.findings.length : 0;
    return [
        { label: moduleT('signalatlas.metricDiscoveredUrls', 'URLs découvertes'), value: discoveredCount },
        { label: moduleT('signalatlas.metricSampledPages', 'Pages analysées'), value: sampledCount },
        { label: moduleT('signalatlas.metricRankedResults', 'Résultats triés'), value: rankedResults.length },
        { label: moduleT('signalatlas.metricIssues', 'Problèmes détectés'), value: issuesCount },
    ];
}

function signalAtlasOverviewFacts(audit) {
    const summary = audit?.summary || {};
    const snapshot = audit?.snapshot || {};
    const renderDetection = snapshot.render_detection || {};
    const facts = [
        moduleT('signalatlas.overviewFactPages', '{sampled} page(s) analysée(s) sur {discovered} URL(s) découvertes.', {
            sampled: Number(snapshot.page_count || 0),
            discovered: Array.isArray(snapshot.discovered_urls) ? snapshot.discovered_urls.length : Number(snapshot.page_count || 0),
        }),
        moduleT('signalatlas.overviewFactIndexable', '{count} page(s) semblent indexables d’après les signaux publics actuels.', {
            count: signalAtlasIndexableEstimate(audit),
        }),
        moduleT('signalatlas.overviewFactIssues', '{count} problème(s) prioritaire(s) ressortent de cette passe.', {
            count: Array.isArray(audit?.findings) ? audit.findings.length : 0,
        }),
    ];
    if (summary.crawl_exhausted_early) {
        facts.push(moduleT('signalatlas.overviewFactSmartCrawlDone', 'Crawl terminé automatiquement : SignalAtlas s’est arrêté à {sampled} page(s), car aucun autre lien utile n’était disponible malgré un budget de {budget}.', {
            sampled: Number(snapshot.page_count || summary.pages_crawled || 0),
            budget: Number(summary.page_budget || 0),
        }));
    }
    if (summary.owner_confirmed) {
        facts.push(moduleT('signalatlas.overviewFactOwnerConfirmed', 'Une source propriétaire officielle confirme une partie du contexte de visibilité.'));
    } else {
        facts.push(moduleT('signalatlas.overviewFactOwnerPublic', 'Sans source propriétaire, la visibilité moteur reste estimée et jamais inventée.'));
    }
    if (renderDetection.render_js_executed) {
        facts.push(moduleT('signalatlas.overviewFactRenderConfirmed', 'Le rendu JS a été vérifié par une sonde réelle sur {count} page(s).', {
            count: Number(renderDetection.executed_page_count || 0),
        }));
    } else if (renderDetection.render_js_requested) {
        facts.push(moduleT('signalatlas.overviewFactRenderRequestedUnavailable', 'Le rendu JS a été demandé mais n’a pas pu être exécuté ici.'));
    } else {
        facts.push(moduleT('signalatlas.overviewFactRenderRaw', 'L’analyse de rendu repose uniquement sur le HTML brut de départ.'));
    }
    return facts.slice(0, 5);
}

function signalAtlasPriorityFindings(audit) {
    const severityOrder = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
    const findings = Array.isArray(audit?.findings) ? [...audit.findings] : [];
    return findings
        .sort((left, right) => {
            const leftRank = severityOrder[String(left?.severity || 'info').toLowerCase()] ?? 5;
            const rightRank = severityOrder[String(right?.severity || 'info').toLowerCase()] ?? 5;
            if (leftRank !== rightRank) return leftRank - rightRank;
            return String(left?.title || '').localeCompare(String(right?.title || ''));
        })
        .slice(0, 3);
}

function signalAtlasFindingKey(item) {
    return String(item?.id || '').trim().toLowerCase().replace(/-/g, '_');
}

function signalAtlasFindingTitle(item) {
    const key = signalAtlasFindingKey(item);
    return moduleT(`signalatlas.findingTitle_${key}`, item?.title || '');
}

function signalAtlasFindingSummary(item) {
    const key = signalAtlasFindingKey(item);
    return moduleT(`signalatlas.findingFix_${key}`, item?.recommended_fix || item?.diagnostic || '');
}

function signalAtlasVisibilityNote(key, value = {}, audit) {
    const cleanKey = String(key || '').trim().toLowerCase();
    const renderDetection = audit?.snapshot?.render_detection || {};
    const ownerMode = String(audit?.owner_context?.mode || audit?.summary?.mode || '').trim().toLowerCase();
    if (cleanKey === 'google') {
        if (String(value?.confidence || '').toLowerCase() === 'confirmed') {
            return moduleT('signalatlas.visibilityNote_google_ownerConfirmed', 'Une propriété Search Console officielle confirme ici un contexte propriétaire, sans inventer de volume d’indexation.');
        }
        if (ownerMode === 'verified_owner') {
            return moduleT('signalatlas.visibilityNote_google_ownerUnconfirmed', 'Le mode propriétaire a été demandé, mais aucune propriété officielle confirmée ne couvre encore cette cible.');
        }
        return moduleT('signalatlas.visibilityNote_google_public', 'Sans source propriétaire officielle, Google reste une estimation prudente basée sur des signaux publics.');
    }
    if (cleanKey === 'bing') {
        return moduleT('signalatlas.visibilityNote_bing', 'Le signal Bing est estimé à partir du crawl, des métadonnées et de la cohérence sitemap.');
    }
    if (cleanKey === 'indexnow') {
        return moduleT('signalatlas.visibilityNote_indexnow', 'IndexNow ne peut pas être confirmé en audit public sans validation côté propriétaire.');
    }
    if (cleanKey === 'geo') {
        const status = String(value?.status || '').trim().toLowerCase();
        if (status === 'strong signal' || status === 'confirmed') {
            return moduleT('signalatlas.visibilityNote_geo_strong', 'Le site expose des signaux publics forts pour la visibilité IA, comme llms.txt ou une bonne couverture de données structurées.');
        }
        if (status === 'partial signal') {
            return moduleT('signalatlas.visibilityNote_geo_partial', 'Certains signaux de visibilité IA sont présents, mais la surface GEO publique reste partielle.');
        }
        return moduleT('signalatlas.visibilityNote_geo_unknown', 'Aucun signal GEO public fort n’a été détecté sur cette passe d’audit.');
    }
    if (cleanKey === 'crawlability') {
        return String(value?.status || '').toLowerCase() === 'blocked'
            ? moduleT('signalatlas.visibilityNote_crawlability_blocked', 'Des signaux de blocage crawl ont été détectés depuis robots.txt ou la couche HTTP.')
            : moduleT('signalatlas.visibilityNote_crawlability_ok', 'Le crawl reste accessible à partir de robots.txt, des réponses HTTP et du maillage échantillonné.');
    }
    if (cleanKey === 'sitemap_coherence') {
        return ['confirmed', 'strong signal'].includes(String(value?.confidence || '').toLowerCase())
            ? moduleT('signalatlas.visibilityNote_sitemap_found', 'Le sitemap est cohérent avec le crawl observé sur cette passe.')
            : moduleT('signalatlas.visibilityNote_sitemap_missing', 'Le sitemap reste partiel, absent ou encore trop faible pour renforcer la découvrabilité.');
    }
    if (cleanKey === 'js_render_risk') {
        if (renderDetection.render_js_executed && Number(renderDetection.changed_page_count || 0) > 0) {
            return moduleT('signalatlas.visibilityNote_js_confirmed_changed', 'Le rendu JS a réellement modifié le contenu visible sur une partie des pages sondées.');
        }
        if (renderDetection.render_js_executed) {
            return moduleT('signalatlas.visibilityNote_js_confirmed_steady', 'La sonde JS a tourné, mais le contenu rendu reste proche du HTML brut échantillonné.');
        }
        if (renderDetection.render_js_requested) {
            return moduleT('signalatlas.visibilityNote_js_requested_unavailable', 'Le rendu JS a été demandé, mais indisponible dans ce runtime pour cette passe.');
        }
        return moduleT('signalatlas.visibilityNote_js_rawOnly', 'Ce risque est estimé uniquement à partir du HTML brut, des signatures framework et de la structure initiale.');
    }
    return String(value?.note || '').trim();
}

function signalAtlasSerpPageDepth(url) {
    try {
        const pathname = new URL(url).pathname || '/';
        return pathname.split('/').filter(Boolean).length;
    } catch (_) {
        return 99;
    }
}

function signalAtlasSerpResultScore(page) {
    const statusCode = Number(page?.status_code || 0);
    const contentType = String(page?.content_type || '').toLowerCase();
    const title = String(page?.title || '').trim();
    const description = String(
        page?.meta_description
        || page?.open_graph?.['og:description']
        || page?.twitter_cards?.['twitter:description']
        || ''
    ).trim();
    const wordCount = Number(page?.word_count || 0);
    const internalLinks = Number(page?.internal_links || 0);
    const imageTotal = Number(page?.image_total || 0);
    const imageMissingAlt = Number(page?.image_missing_alt || 0);
    const crawlDepth = Number(page?.crawl_depth ?? 99);
    const finalUrl = String(page?.final_url || page?.url || '').trim();
    let score = 62;

    if (statusCode >= 200 && statusCode < 400) score += 12;
    else if (statusCode >= 400) score -= 30;

    if (!page?.noindex) score += 8;
    else score -= 28;

    if (!contentType || contentType.includes('html')) score += 4;
    else score -= 12;

    if (title) {
        score += 8;
        if (title.length < 30 || title.length > 65) score -= 4;
    } else {
        score -= 16;
    }

    if (description) {
        score += 6;
        if (description.length < 70 || description.length > 165) score -= 3;
    } else {
        score -= 10;
    }

    if (page?.h1) score += 5;
    else score -= 8;

    if (page?.canonical) score += 3;
    else score -= 4;

    if (wordCount >= 600) score += 6;
    else if (wordCount >= 250) score += 3;
    else if (wordCount < 120) score -= 10;
    else if (wordCount < 250) score -= 4;

    if (Number(page?.structured_data_count || 0) > 0) score += 4;
    if (page?.open_graph) score += 2;
    if (page?.twitter_cards) score += 1;
    if (page?.hreflang) score += 1;
    if (page?.shell_like) score -= 14;

    if (Number.isFinite(crawlDepth)) {
        score += Math.max(0, 6 - (Math.max(crawlDepth, 0) * 2));
    }

    if (internalLinks >= 12) score += 6;
    else if (internalLinks >= 5) score += 3;
    else if (internalLinks === 0) score -= 6;

    if (imageTotal > 0) {
        const altCoverage = 1 - (imageMissingAlt / imageTotal);
        if (altCoverage < 0.5) score -= 5;
        else if (altCoverage > 0.85) score += 2;
    }

    if (page?.render_js_executed && page?.render_changed_content) score += 2;

    const pathDepth = signalAtlasSerpPageDepth(finalUrl);
    if (pathDepth === 0) score += 4;
    else if (pathDepth === 1) score += 2;

    return Math.max(0, Math.min(100, Math.round(score)));
}

function signalAtlasSerpReadiness(score) {
    const numeric = Number(score || 0);
    if (numeric >= 85) {
        return {
            tone: 'is-good',
            label: moduleT('signalatlas.serpReadinessStrong', 'Solide'),
        };
    }
    if (numeric >= 65) {
        return {
            tone: 'is-warn',
            label: moduleT('signalatlas.serpReadinessFair', 'À renforcer'),
        };
    }
    return {
        tone: 'is-danger',
        label: moduleT('signalatlas.serpReadinessWeak', 'Fragile'),
    };
}

function signalAtlasSerpCandidates(audit) {
    const pages = Array.isArray(audit?.snapshot?.pages) ? [...audit.snapshot.pages] : [];
    return pages
        .filter(page => page?.final_url || page?.url)
        .map(page => {
            const score = signalAtlasSerpResultScore(page);
            return {
                page,
                score,
                readiness: signalAtlasSerpReadiness(score),
            };
        })
        .sort((left, right) => {
            if (left.score !== right.score) return right.score - left.score;

            const leftDepth = Number(left?.page?.crawl_depth ?? 99);
            const rightDepth = Number(right?.page?.crawl_depth ?? 99);
            if (leftDepth !== rightDepth) return leftDepth - rightDepth;

            const leftLinks = Number(left?.page?.internal_links ?? 0);
            const rightLinks = Number(right?.page?.internal_links ?? 0);
            if (leftLinks !== rightLinks) return rightLinks - leftLinks;

            const leftWords = Number(left?.page?.word_count ?? 0);
            const rightWords = Number(right?.page?.word_count ?? 0);
            if (leftWords !== rightWords) return rightWords - leftWords;

            return String(left?.page?.final_url || left?.page?.url || '').localeCompare(
                String(right?.page?.final_url || right?.page?.url || '')
            );
        })
        .map((item, index) => ({
            ...item,
            position: index + 1,
        }));
}

function signalAtlasSerpSiteName(url) {
    try {
        const hostname = new URL(url).hostname.replace(/^www\./i, '');
        const base = hostname.split('.')[0] || hostname;
        return base
            .split(/[-_]+/g)
            .filter(Boolean)
            .map(chunk => chunk.charAt(0).toUpperCase() + chunk.slice(1))
            .join(' ');
    } catch (_) {
        return '';
    }
}

function signalAtlasSerpFaviconUrl(url) {
    try {
        const parsed = new URL(url);
        return `${parsed.origin}/favicon.ico`;
    } catch (_) {
        return '';
    }
}

function setSignalAtlasSerpPage(pageNumber) {
    const nextPage = Math.max(1, Number(pageNumber || 1));
    if (nextPage === signalAtlasSerpPage) return;
    signalAtlasSerpPage = nextPage;
    if (document.getElementById('signalatlas-view-content')) {
        renderSignalAtlasWorkspace();
    }
}

function renderSignalAtlasSerpPreview(audit, options = {}) {
    const compact = !!options.compact;
    const candidates = signalAtlasSerpCandidates(audit);
    const metrics = signalAtlasSearchMetrics(audit);
    const discoveredCount = Array.isArray(audit?.snapshot?.discovered_urls) ? audit.snapshot.discovered_urls.length : Number(audit?.snapshot?.page_count || 0);
    if (!candidates.length) {
        return `
            <section class="signalatlas-serp-card${compact ? ' compact' : ''}">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.searchPreviewKicker', 'Aperçu recherche'))}</div>
                <div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.searchPreviewNoData', 'L’audit n’a pas encore assez de pages pour générer une preview exploitable.'))}</div>
            </section>
        `;
    }

    const totalPages = Math.max(1, Math.ceil(candidates.length / SIGNALATLAS_SERP_PAGE_SIZE));
    const currentPage = Math.min(Math.max(signalAtlasSerpPage, 1), totalPages);
    if (currentPage !== signalAtlasSerpPage) signalAtlasSerpPage = currentPage;
    const pageStart = (currentPage - 1) * SIGNALATLAS_SERP_PAGE_SIZE;
    const pageItems = candidates.slice(pageStart, pageStart + SIGNALATLAS_SERP_PAGE_SIZE);

    const results = pageItems.map((item, index) => {
        const page = item.page;
        const url = String(page.final_url || page.url || '').trim();
        const title = signalAtlasTrimText(page.title || page.h1 || url, 68);
        const description = signalAtlasTrimText(
            page.meta_description
            || page.open_graph?.['og:description']
            || page.twitter_cards?.['twitter:description']
            || page.h1
            || moduleT('signalatlas.searchPreviewFallback', 'Cette page gagnerait à mieux expliciter son angle avec un title et une description plus solides.'),
            156
        );
        const hostname = (() => {
            try {
                return new URL(url).hostname.replace(/^www\./i, '');
            } catch (_) {
                return url;
            }
        })();
        const siteName = signalAtlasSerpSiteName(url) || hostname;
        const faviconUrl = signalAtlasSerpFaviconUrl(url);
        const faviconFallback = (siteName || hostname || '?').charAt(0).toUpperCase();
        const resultNumber = pageStart + index + 1;
        return `
            <article class="signalatlas-serp-result">
                <div class="signalatlas-serp-source">
                    <span class="signalatlas-serp-favicon-wrap" aria-hidden="true">
                        ${faviconUrl ? `<img class="signalatlas-serp-favicon" src="${escapeHtml(faviconUrl)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('.signalatlas-serp-favicon-wrap')?.classList.add('is-fallback'); this.remove();">` : ''}
                        <span class="signalatlas-serp-favicon-fallback">${escapeHtml(faviconFallback)}</span>
                    </span>
                    <div class="signalatlas-serp-source-copy">
                        <span class="signalatlas-serp-source-name">${escapeHtml(siteName)}</span>
                        <span class="signalatlas-serp-source-url">${escapeHtml(url)}</span>
                    </div>
                </div>
                <div class="signalatlas-serp-title">${escapeHtml(title)}</div>
                <div class="signalatlas-serp-description">${escapeHtml(description)}</div>
                <div class="signalatlas-serp-meta">
                    <span>${escapeHtml(moduleT('signalatlas.positionLabel', 'Résultat'))} ${resultNumber}</span>
                    <span class="signalatlas-serp-score-badge ${escapeHtml(item.readiness.tone)}">${escapeHtml(moduleT('signalatlas.serpSeoScore', 'SEO'))} ${escapeHtml(String(item.score))}</span>
                    <span>${escapeHtml(item.readiness.label)}</span>
                    <span>${escapeHtml(String(page.word_count || 0))} ${escapeHtml(moduleT('signalatlas.words', 'mots'))}</span>
                </div>
            </article>
        `;
    }).join('');

    const pageButtons = Array.from({ length: totalPages }, (_, index) => index + 1).map(pageNumber => `
        <button
            class="signalatlas-serp-page-btn${pageNumber === currentPage ? ' active' : ''}"
            type="button"
            onclick="setSignalAtlasSerpPage(${pageNumber})"
            ${pageNumber === currentPage ? 'aria-current="page"' : ''}
        >${pageNumber}</button>
    `).join('');

    return `
        <section class="signalatlas-serp-card${compact ? ' compact' : ''}">
            <div class="signalatlas-serp-head">
                <div>
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.searchPreviewKicker', 'Aperçu recherche'))}</div>
                    <div class="signalatlas-serp-title-main">${escapeHtml(moduleT('signalatlas.searchPreviewTitle', 'Preview type Google de tes pages les plus visibles'))}</div>
                </div>
                <div class="signalatlas-inline-chip">${escapeHtml(moduleT('signalatlas.searchPreviewLabel', 'Google-style preview'))}</div>
            </div>
            <div class="signalatlas-serp-layout">
                <aside class="signalatlas-serp-sidebar">
                    <div class="signalatlas-serp-sidebar-title">${escapeHtml(moduleT('signalatlas.searchPreviewSidebarTitle', 'Lecture moteur'))}</div>
                    <div class="signalatlas-serp-sidebar-copy">${escapeHtml(moduleT('signalatlas.searchPreviewResultsHint', '{ranked} résultat(s) trié(s) sur {total} URL(s) découvertes.', {
                        ranked: candidates.length,
                        total: discoveredCount,
                    }))}</div>
                    <div class="signalatlas-serp-sidebar-copy">${escapeHtml(moduleT('signalatlas.searchPreviewPageSummary', 'Page {current} sur {total} · {perPage} résultats par page.', {
                        current: currentPage,
                        total: totalPages,
                        perPage: SIGNALATLAS_SERP_PAGE_SIZE,
                    }))}</div>
                    <div class="signalatlas-serp-stats">
                        ${metrics.map(metric => `
                            <div class="signalatlas-serp-stat">
                                <span class="signalatlas-serp-stat-label">${escapeHtml(metric.label)}</span>
                                <strong class="signalatlas-serp-stat-value">${escapeHtml(String(metric.value))}</strong>
                            </div>
                        `).join('')}
                    </div>
                    <div class="signalatlas-serp-footnote">${escapeHtml(moduleT('signalatlas.searchPreviewOrderHint', 'Ordre simulé à partir des signaux techniques et SEO on-page de l’audit, pas d’un classement Google confirmé.'))}</div>
                    <div class="signalatlas-serp-footnote">${escapeHtml(moduleT('signalatlas.visibilityEstimateHint', 'Les chiffres moteurs restent prudents: sans source propriétaire officielle, SignalAtlas montre des estimations et jamais de faux volume indexé.'))}</div>
                </aside>
                <div class="signalatlas-serp-shell">
                    <div class="signalatlas-serp-topbar">
                    <div class="signalatlas-serp-query">${escapeHtml(audit?.target?.host || audit?.title || '')}</div>
                    </div>
                    <div class="signalatlas-serp-results">
                        ${results}
                    </div>
                    <div class="signalatlas-serp-pagination">
                        <div class="signalatlas-serp-page-status">${escapeHtml(moduleT('signalatlas.searchPreviewPageSummary', 'Page {current} sur {total} · {perPage} résultats par page.', {
                            current: currentPage,
                            total: totalPages,
                            perPage: SIGNALATLAS_SERP_PAGE_SIZE,
                        }))}</div>
                        <div class="signalatlas-serp-page-controls">
                            <button class="signalatlas-serp-page-btn nav" type="button" onclick="setSignalAtlasSerpPage(${Math.max(1, currentPage - 1)})" ${currentPage <= 1 ? 'disabled' : ''}>${escapeHtml(moduleT('signalatlas.searchPreviewPrevious', 'Précédent'))}</button>
                            ${pageButtons}
                            <button class="signalatlas-serp-page-btn nav" type="button" onclick="setSignalAtlasSerpPage(${Math.min(totalPages, currentPage + 1)})" ${currentPage >= totalPages ? 'disabled' : ''}>${escapeHtml(moduleT('signalatlas.searchPreviewNext', 'Suivant'))}</button>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    `;
}

function applySignalAtlasProfile(profileId) {
    const clean = String(profileId || 'elevated').trim().toLowerCase();
    const profile = signalAtlasProfileConfig(clean);
    signalAtlasDraft.profile = clean;
    signalAtlasDraft.max_pages = profile.max_pages;
    signalAtlasDraft.depth = profile.depth;
    signalAtlasDraft.render_js = profile.render_js;
    signalAtlasDraft.preset = profile.preset;
    signalAtlasDraft.level = profile.level;
}

function applyPerfAtlasProfile(profileId) {
    const clean = String(profileId || 'elevated').trim().toLowerCase();
    const profile = perfAtlasProfileConfig(clean);
    perfAtlasDraft.profile = clean;
    perfAtlasDraft.max_pages = profile.max_pages;
    perfAtlasDraft.preset = profile.preset;
    perfAtlasDraft.level = profile.level;
}

function renderSignalAtlasHelpButton(text, ariaLabel = '') {
    const tooltip = String(text || '').trim();
    if (!tooltip) return '';
    return `
        <button
            class="signalatlas-help-btn"
            type="button"
            data-tooltip="${escapeHtml(tooltip)}"
            aria-label="${escapeHtml(ariaLabel || tooltip)}"
        >?</button>
    `;
}

function renderSignalAtlasFieldLabel(label, helpText = '') {
    return `
        <span>${escapeHtml(label || '')}</span>
        ${renderSignalAtlasHelpButton(helpText, label)}
    `;
}

function signalAtlasIsActiveJob(job) {
    return !['done', 'error', 'cancelled'].includes(String(job?.status || '').toLowerCase());
}

function signalAtlasIsTerminalAuditStatus(status) {
    return ['done', 'error', 'cancelled'].includes(String(status || '').trim().toLowerCase());
}

function signalAtlasKnownAuditStatus(auditId) {
    const cleanAuditId = String(auditId || '').trim();
    if (!cleanAuditId) return '';
    const audit = (signalAtlasAudits || []).find(item => String(item?.id || '') === cleanAuditId);
    const summaryStatus = String(audit?.status || '').trim().toLowerCase();
    if (String(signalAtlasCurrentAudit?.id || '') === cleanAuditId) {
        const currentStatus = String(signalAtlasCurrentAudit?.status || '').trim().toLowerCase();
        if (signalAtlasIsTerminalAuditStatus(currentStatus)) return currentStatus;
        if (signalAtlasIsTerminalAuditStatus(summaryStatus)) return summaryStatus;
        return currentStatus || summaryStatus;
    }
    return summaryStatus;
}

function signalAtlasRuntimeJobs() {
    if (typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return [];
    return runtimeJobsCache.filter(job => job?.metadata?.module_id === 'signalatlas');
}

function activeSignalAtlasJobs() {
    return signalAtlasRuntimeJobs()
        .filter(job => signalAtlasIsActiveJob(job) && !signalAtlasIsTerminalAuditStatus(signalAtlasKnownAuditStatus(job?.metadata?.audit_id)))
        .sort((left, right) => String(right?.updated_at || '').localeCompare(String(left?.updated_at || '')));
}

function signalAtlasJobProgress(job) {
    const value = Number(job?.progress ?? 0);
    if (Number.isFinite(value)) return Math.max(0, Math.min(100, Math.round(value)));
    return 0;
}

function signalAtlasFormatDuration(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    if (value < 45) return moduleT('signalatlas.etaLessThanMinute', 'moins d’une minute');
    const minutes = Math.max(1, Math.round(value / 60));
    if (minutes < 60) {
        return moduleT('signalatlas.etaMinutes', 'env. {minutes} min', { minutes });
    }
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (!rest) return moduleT('signalatlas.etaHours', 'env. {hours} h', { hours });
    return moduleT('signalatlas.etaHoursMinutes', 'env. {hours} h {minutes} min', { hours, minutes: rest });
}

function signalAtlasEstimateSecondsForAudit(audit = null) {
    const options = audit?.options || signalAtlasDraft || {};
    const metadata = audit?.metadata || {};
    const metadataEstimate = Number(metadata.estimated_seconds);
    if (Number.isFinite(metadataEstimate) && metadataEstimate > 0) return metadataEstimate;
    const maxPages = signalAtlasResolvedPageBudget(options.max_pages ?? signalAtlasDraft.max_pages, SIGNALATLAS_DEFAULT_PAGE_BUDGET);
    const renderJs = options.render_js ?? signalAtlasDraft.render_js;
    const aiLevel = String(metadata.ai?.level || signalAtlasDraft.level || 'basic_summary').toLowerCase();
    const crawlSeconds = 12
        + Math.min(maxPages, 40) * 1.5
        + Math.max(0, Math.min(maxPages, 250) - 40) * 0.55
        + Math.max(0, Math.min(maxPages, SIGNALATLAS_MAX_PAGE_BUDGET) - 250) * 0.18;
    const renderSeconds = renderJs ? 30 : 0;
    const aiSeconds = aiLevel === 'no_ai'
        ? 0
        : aiLevel === 'ai_remediation_pack'
            ? 70
            : aiLevel === 'full_expert_analysis'
                ? 45
                : 18;
    return Math.max(35, Math.min(1200, crawlSeconds + renderSeconds + aiSeconds));
}

function signalAtlasJobStartedAt(job) {
    const raw = String(job?.started_at || job?.created_at || '').trim();
    if (!raw) return null;
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function auditProgressKey(namespace, progressState) {
    const job = progressState?.job || progressState || {};
    const auditId = String(progressState?.auditId || job?.metadata?.audit_id || '').trim();
    const jobId = String(job?.id || job?.job_id || job?.task_id || '').trim();
    return `${namespace}:${auditId || jobId || 'launch'}`;
}

function auditProgressRawPhase(progressState) {
    return String(progressState?.job?.phase || progressState?.status || '').trim().toLowerCase();
}

function auditProgressPhaseRange(namespace, phase) {
    const clean = String(phase || '').toLowerCase();
    if (namespace === 'perfatlas') {
        if (clean === 'queued') return [3, 7];
        if (clean === 'crawl') return [7, 30];
        if (clean === 'extract') return [30, 40];
        if (clean === 'field') return [40, 52];
        if (clean === 'lab') return [52, 72];
        if (clean === 'owner') return [72, 78];
        if (clean === 'score') return [78, 84];
        if (clean === 'ai' || clean === 'report') return [84, 98.6];
        if (clean === 'cancelling') return [90, 99];
        return [8, 90];
    }
    if (clean === 'queued') return [3, 7];
    if (clean === 'crawl') return [7, 48];
    if (clean === 'render') return [48, 62];
    if (clean === 'extract') return [62, 72];
    if (clean === 'score') return [72, 80];
    if (clean === 'report') return [80, 84];
    if (clean === 'ai') return [84, 98.6];
    if (clean === 'cancelling') return [90, 99];
    return [8, 90];
}

function auditProgressPhaseDurationSeconds(namespace, phase, audit = null) {
    const clean = String(phase || '').toLowerCase();
    const estimate = namespace === 'perfatlas'
        ? perfAtlasEstimateSecondsForAudit(audit)
        : signalAtlasEstimateSecondsForAudit(audit);
    const base = Math.max(35, Number(estimate) || 90);
    if (clean === 'queued') return 10;
    if (clean === 'crawl') return Math.max(18, base * (namespace === 'perfatlas' ? 0.24 : 0.36));
    if (clean === 'render') return Math.max(20, base * 0.16);
    if (clean === 'extract') return Math.max(12, base * 0.09);
    if (clean === 'field') return Math.max(12, base * 0.10);
    if (clean === 'lab') return Math.max(28, base * 0.30);
    if (clean === 'owner') return Math.max(10, base * 0.08);
    if (clean === 'score') return Math.max(10, base * 0.08);
    if (clean === 'report') return Math.max(12, base * 0.08);
    if (clean === 'ai') return Math.max(55, base * 0.34);
    return Math.max(20, base * 0.18);
}

function auditDisplayProgress(namespace, progressState, audit = null, launchPending = false) {
    if (!progressState && !launchPending) return 0;
    if (launchPending && !progressState) return 4;
    const raw = signalAtlasJobProgress(progressState);
    const status = String(progressState?.status || '').toLowerCase();
    const key = auditProgressKey(namespace, progressState);
    if (!signalAtlasIsLiveProgressStatus(status) || raw >= 100) {
        auditProgressDisplayState.delete(key);
        return raw;
    }
    const phase = auditProgressRawPhase(progressState) || 'running';
    const [start, end] = auditProgressPhaseRange(namespace, phase);
    const now = Date.now();
    const previous = auditProgressDisplayState.get(key);
    const phaseStartedAt = previous?.phase === phase ? previous.phaseStartedAt : now;
    const duration = auditProgressPhaseDurationSeconds(namespace, phase, audit);
    const elapsed = Math.max(0, (now - phaseStartedAt) / 1000);
    const ratio = Math.max(0, Math.min(0.96, elapsed / Math.max(1, duration)));
    const eased = 1 - Math.pow(1 - ratio, 2);
    const phaseProgress = start + (end - start) * eased;
    const floor = previous?.phase === phase ? Number(previous.value) || start : start;
    const value = Math.max(floor, phaseProgress);
    const capped = Math.min(raw >= 99 ? 99 : end, value);
    auditProgressDisplayState.set(key, { phase, phaseStartedAt, value: capped, updatedAt: now });
    return Math.max(0, Math.min(99, Math.floor(capped)));
}

function auditProgressRemainingSeconds(namespace, progressState, audit = null, displayProgress = null) {
    if (!progressState) return namespace === 'perfatlas'
        ? perfAtlasEstimateSecondsForAudit(audit)
        : signalAtlasEstimateSecondsForAudit(audit);
    const phase = auditProgressRawPhase(progressState) || 'running';
    const key = auditProgressKey(namespace, progressState);
    const state = auditProgressDisplayState.get(key);
    const duration = auditProgressPhaseDurationSeconds(namespace, phase, audit);
    const elapsed = state?.phase === phase ? Math.max(0, (Date.now() - state.phaseStartedAt) / 1000) : 0;
    const phaseRemaining = Math.max(8, duration - elapsed);
    const estimate = namespace === 'perfatlas'
        ? perfAtlasEstimateSecondsForAudit(audit)
        : signalAtlasEstimateSecondsForAudit(audit);
    const progress = Math.max(1, Number(displayProgress) || signalAtlasJobProgress(progressState));
    const globalRemaining = estimate * ((99 - progress) / Math.max(progress, 1));
    return Math.max(8, Math.min(estimate * 1.8, Math.max(phaseRemaining, globalRemaining)));
}

function signalAtlasProgressEtaLabel(progressState, audit = null, displayProgress = null) {
    const status = String(progressState?.status || '').toLowerCase();
    if (!progressState && signalAtlasLaunchPending) {
        return moduleT('signalatlas.etaInitial', 'durée estimée {duration}', {
            duration: signalAtlasFormatDuration(signalAtlasEstimateSecondsForAudit(audit)),
        });
    }
    if (!progressState || !signalAtlasIsLiveProgressStatus(status)) return '';
    const progress = Number.isFinite(Number(displayProgress)) ? Number(displayProgress) : signalAtlasJobProgress(progressState);
    if (progress >= 96) return moduleT('signalatlas.etaFinalizing', 'finalisation');
    const remainingSeconds = auditProgressRemainingSeconds('signalatlas', progressState, audit, progress);
    if (Number.isFinite(remainingSeconds) && remainingSeconds > 0) {
        return moduleT('signalatlas.etaRemaining', 'reste {duration}', {
            duration: signalAtlasFormatDuration(remainingSeconds),
        });
    }
    return moduleT('signalatlas.etaInitial', 'durée estimée {duration}', {
        duration: signalAtlasFormatDuration(signalAtlasEstimateSecondsForAudit(audit)),
    });
}

function signalAtlasJobPhaseLabel(phase) {
    const clean = String(phase || '').trim().toLowerCase();
    if (clean === 'crawl') return moduleT('signalatlas.phaseCrawl', 'Crawl');
    if (clean === 'render') return moduleT('signalatlas.phaseRender', 'Rendu JS');
    if (clean === 'extract') return moduleT('signalatlas.phaseExtract', 'Extraction');
    if (clean === 'score') return moduleT('signalatlas.phaseScore', 'Scoring');
    if (clean === 'report') return moduleT('signalatlas.phaseReport', 'Rapport');
    if (clean === 'ai') return moduleT('signalatlas.phaseAi', 'Interprétation IA');
    if (clean === 'queued') return moduleT('signalatlas.phaseQueued', 'En file');
    if (clean === 'cancelling') return moduleT('signalatlas.phaseCancelling', 'Annulation');
    if (clean === 'cancelled') return moduleT('signalatlas.phaseCancelled', 'Annulé');
    if (clean === 'done') return moduleT('signalatlas.phaseDone', 'Terminé');
    if (clean === 'error') return moduleT('signalatlas.phaseError', 'Erreur');
    return signalAtlasStatusLabel(clean || 'unknown');
}

function signalAtlasIsLiveProgressStatus(status) {
    const clean = String(status || '').trim().toLowerCase();
    return ['queued', 'running', 'cancelling'].includes(clean);
}

function signalAtlasJobMessage(job) {
    const raw = String(job?.message || '').trim();
    if (!raw) return signalAtlasJobPhaseLabel(job?.phase || job?.status);
    if (/^Preparing crawl target$/i.test(raw)) {
        return moduleT('signalatlas.progressPreparing', 'Préparation de la cible');
    }
    if (/^Discovering sitemap signals$/i.test(raw)) {
        return moduleT('signalatlas.progressDiscoveringSitemap', 'Recherche des sitemaps');
    }
    if (/^Extracting technical signals$/i.test(raw)) {
        return moduleT('signalatlas.progressExtracting', 'Extraction des signaux techniques');
    }
    if (/^Scoring technical findings$/i.test(raw)) {
        return moduleT('signalatlas.progressScoring', 'Calcul du score technique');
    }
    if (/^Building audit report$/i.test(raw)) {
        return moduleT('signalatlas.progressBuildingReport', 'Construction du rapport');
    }
    if (/^Generating AI interpretation$/i.test(raw)) {
        return moduleT('signalatlas.progressGeneratingAi', 'Génération de l’interprétation IA');
    }
    if (/^Preparing deterministic audit excerpt$/i.test(raw)) {
        return moduleT('signalatlas.progressPreparingAiExcerpt', 'Préparation du contexte d’audit pour l’IA');
    }
    if (/^Generating first interpretation$/i.test(raw)) {
        return moduleT('signalatlas.progressGeneratingFirstInterpretation', 'Génération de la première interprétation');
    }
    if (/^Generating second interpretation$/i.test(raw)) {
        return moduleT('signalatlas.progressGeneratingSecondInterpretation', 'Génération de la seconde interprétation');
    }
    if (/^SignalAtlas AI interpretation ready$/i.test(raw)) {
        return moduleT('signalatlas.progressAiReady', 'Interprétation IA prête');
    }
    if (/^SignalAtlas audit complete$/i.test(raw)) {
        return moduleT('signalatlas.progressAuditComplete', 'Audit SignalAtlas terminé');
    }
    if (/^SignalAtlas audit ready$/i.test(raw)) {
        return moduleT('signalatlas.progressReady', 'Rapport prêt');
    }
    if (/^Crawling /i.test(raw)) {
        return moduleT('signalatlas.progressCrawling', 'Crawl de {target}', {
            target: raw.replace(/^Crawling /i, '').trim(),
        });
    }
    if (/^Rendering JS for /i.test(raw)) {
        return moduleT('signalatlas.progressRendering', 'Rendu JS sur {target}', {
            target: raw.replace(/^Rendering JS for /i, '').trim(),
        });
    }
    if (/^Validating TLS and canonical entrypoint$/i.test(raw)) {
        return moduleT('cyberatlas.progressTls', 'Validation TLS et point d’entrée canonique');
    }
    if (/^Sampling public pages and forms$/i.test(raw)) {
        return moduleT('cyberatlas.progressCrawl', 'Échantillonnage des pages et formulaires publics');
    }
    if (/^Sampling /i.test(raw)) {
        return moduleT('cyberatlas.progressSampling', 'Échantillonnage de {target}', {
            target: raw.replace(/^Sampling /i, '').trim(),
        });
    }
    if (/^Analyzing security headers and browser hardening$/i.test(raw)) {
        return moduleT('cyberatlas.progressHeaders', 'Analyse des headers sécurité et du durcissement navigateur');
    }
    if (/^Running safe public exposure probes$/i.test(raw)) {
        return moduleT('cyberatlas.progressExposure', 'Sondes publiques sûres sur l’exposition');
    }
    if (/^Parsing OpenAPI and API surface signals$/i.test(raw)) {
        return moduleT('cyberatlas.progressApi', 'Analyse OpenAPI et surface API');
    }
    if (/^Scoring defensive security posture$/i.test(raw)) {
        return moduleT('cyberatlas.progressScore', 'Calcul de la posture sécurité défensive');
    }
    if (/^Generating defensive AI interpretation$/i.test(raw)) {
        return moduleT('cyberatlas.progressAi', 'Génération de l’interprétation IA défensive');
    }
    if (/^Preparing defensive audit excerpt$/i.test(raw)) {
        return moduleT('cyberatlas.progressPreparingAi', 'Préparation de l’extrait d’audit défensif');
    }
    if (/^Generating first defensive interpretation$/i.test(raw)) {
        return moduleT('cyberatlas.progressFirstAi', 'Génération de la première interprétation défensive');
    }
    if (/^Generating second defensive interpretation$/i.test(raw)) {
        return moduleT('cyberatlas.progressSecondAi', 'Génération de la seconde interprétation défensive');
    }
    if (/^CyberAtlas audit complete$/i.test(raw)) {
        return moduleT('cyberatlas.progressComplete', 'Audit CyberAtlas terminé');
    }
    return raw;
}

function signalAtlasProgressSupportCopy(progressState, fallbackHint = '') {
    const clean = String(progressState?.job?.phase || progressState?.status || '').trim().toLowerCase();
    if (!progressState && signalAtlasLaunchPending) {
        return moduleT('signalatlas.progressLaunchingCopy', 'SignalAtlas prépare le runtime, les options et la première passe d’analyse.');
    }
    if (clean === 'queued') {
        return moduleT('signalatlas.progressQueuedCopy', 'L’audit attend son créneau de calcul avant de démarrer les premières vérifications.');
    }
    if (clean === 'crawl') {
        return moduleT('signalatlas.progressCrawlCopy', 'Le crawler suit les liens internes, consolide les URL utiles et relève les premiers signaux techniques.');
    }
    if (clean === 'render') {
        return moduleT('signalatlas.progressRenderCopy', 'SignalAtlas compare le HTML brut avec le rendu navigateur quand la sonde JavaScript est disponible.');
    }
    if (clean === 'extract') {
        return moduleT('signalatlas.progressExtractCopy', 'Les métadonnées, headings, liens, images et signaux de structure sont en cours d’extraction.');
    }
    if (clean === 'score') {
        return moduleT('signalatlas.progressScoreCopy', 'Les findings sont pondérés pour distinguer le blocage racine des symptômes secondaires.');
    }
    if (clean === 'report') {
        return moduleT('signalatlas.progressReportCopy', 'Le rapport déterministe se met en forme avant l’éventuelle couche d’interprétation IA.');
    }
    if (clean === 'ai') {
        return moduleT('signalatlas.progressAiCopy', 'Le modèle lit les findings, regroupe les causes racines et rédige le rapport IA. Cette étape peut rester un moment sur le même pourcentage.');
    }
    if (clean === 'cancelling') {
        return moduleT('signalatlas.progressCancellingCopy', 'L’annulation est en cours. SignalAtlas arrête proprement les écritures restantes.');
    }
    if (clean === 'running') {
        return moduleT('signalatlas.progressWorkingCopy', 'SignalAtlas continue d’analyser la cible et mettra le rapport à jour dès que cette étape se termine.');
    }
    return fallbackHint || moduleT('signalatlas.backgroundResumeHint', 'Cet audit continue en arrière-plan si tu quittes cette vue.');
}

function signalAtlasAuditProgressState(audit) {
    const auditId = typeof audit === 'string' ? audit : audit?.id;
    const localStatus = String((typeof audit === 'object' && audit?.status) || '').trim().toLowerCase();
    const resolvedStatus = signalAtlasKnownAuditStatus(auditId);
    const knownStatus = signalAtlasIsTerminalAuditStatus(resolvedStatus)
        ? resolvedStatus
        : (localStatus || resolvedStatus);
    if (signalAtlasIsTerminalAuditStatus(knownStatus)) {
        return null;
    }
    const liveJob = auditId ? activeSignalAtlasJobForAudit(auditId) : null;
    if (liveJob) {
        return {
            job: liveJob,
            auditId,
            status: String(liveJob.status || 'running').toLowerCase(),
            phase: signalAtlasJobPhaseLabel(liveJob.phase || liveJob.status),
            progress: signalAtlasJobProgress(liveJob),
            message: signalAtlasJobMessage(liveJob),
        };
    }
    const currentStatus = knownStatus;
    if (currentStatus === 'running' || currentStatus === 'queued') {
        return {
            job: null,
            auditId,
            status: currentStatus,
            phase: signalAtlasJobPhaseLabel(currentStatus),
            progress: currentStatus === 'running' ? 8 : 2,
            message: currentStatus === 'running'
                ? moduleT('signalatlas.auditRunning', 'Audit en cours...')
                : moduleT('signalatlas.phaseQueued', 'En file'),
        };
    }
    return null;
}

function signalAtlasAnyProgressState() {
    const current = signalAtlasCurrentAudit ? signalAtlasAuditProgressState(signalAtlasCurrentAudit) : null;
    if (current) return current;
    for (const audit of signalAtlasAudits) {
        const state = signalAtlasAuditProgressState(audit);
        if (state) return state;
    }
    const fallbackJob = activeSignalAtlasJobs()[0] || null;
    if (fallbackJob) {
        return {
            job: fallbackJob,
            auditId: fallbackJob?.metadata?.audit_id || null,
            status: String(fallbackJob.status || 'running').toLowerCase(),
            phase: signalAtlasJobPhaseLabel(fallbackJob.phase || fallbackJob.status),
            progress: signalAtlasJobProgress(fallbackJob),
            message: signalAtlasJobMessage(fallbackJob),
        };
    }
    return null;
}

function signalAtlasPickerInputId(pickerId) {
    if (pickerId === 'profile') return 'signalatlas-profile-select';
    if (pickerId === 'mode') return 'signalatlas-mode-select';
    if (pickerId === 'max_pages') return 'signalatlas-max-pages';
    if (pickerId === 'depth') return 'signalatlas-depth';
    if (pickerId === 'model') return 'signalatlas-model-select';
    if (pickerId === 'preset') return 'signalatlas-preset-select';
    if (pickerId === 'level') return 'signalatlas-level-select';
    if (pickerId === 'compare_model') return 'signalatlas-compare-model-select';
    return '';
}

function getAuditPickerState(moduleId) {
    const cleanModuleId = String(moduleId || '').trim().toLowerCase();
    if (cleanModuleId === 'cyberatlas' && typeof window.getCyberAtlasPickerState === 'function') {
        return window.getCyberAtlasPickerState();
    }
    if (cleanModuleId === 'deployatlas' && typeof window.getDeployAtlasPickerState === 'function') {
        return window.getDeployAtlasPickerState();
    }
    return cleanModuleId === 'perfatlas'
        ? perfAtlasOpenPickerId
        : signalAtlasOpenPickerId;
}

function setAuditPickerState(moduleId, value) {
    const cleanModuleId = String(moduleId || '').trim().toLowerCase();
    if (cleanModuleId === 'cyberatlas' && typeof window.setCyberAtlasPickerState === 'function') {
        window.setCyberAtlasPickerState(value);
        return;
    }
    if (cleanModuleId === 'deployatlas' && typeof window.setDeployAtlasPickerState === 'function') {
        window.setDeployAtlasPickerState(value);
        return;
    }
    if (cleanModuleId === 'perfatlas') {
        perfAtlasOpenPickerId = value;
        return;
    }
    signalAtlasOpenPickerId = value;
}

function rerenderAuditWorkspace(moduleId) {
    const cleanModuleId = String(moduleId || '').trim().toLowerCase();
    if (cleanModuleId === 'cyberatlas' && typeof window.renderCyberAtlasWorkspace === 'function') {
        window.renderCyberAtlasWorkspace();
        return;
    }
    if (cleanModuleId === 'deployatlas' && typeof window.renderDeployAtlasWorkspace === 'function') {
        window.renderDeployAtlasWorkspace();
        return;
    }
    if (cleanModuleId === 'perfatlas') {
        if (isPerfAtlasVisible()) renderPerfAtlasWorkspace();
        return;
    }
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

function closeAuditPicker(moduleId) {
    if (!getAuditPickerState(moduleId)) return;
    setAuditPickerState(moduleId, null);
    rerenderAuditWorkspace(moduleId);
}

function toggleAuditPicker(moduleId, pickerId, event) {
    event?.stopPropagation?.();
    const current = getAuditPickerState(moduleId);
    setAuditPickerState(moduleId, current === pickerId ? null : pickerId);
    rerenderAuditWorkspace(moduleId);
}

function closeSignalAtlasPicker() {
    closeAuditPicker('signalatlas');
}

function toggleSignalAtlasPicker(pickerId, event) {
    toggleAuditPicker('signalatlas', pickerId, event);
}

function togglePerfAtlasPicker(pickerId, event) {
    toggleAuditPicker('perfatlas', pickerId, event);
}

function toggleCyberAtlasPicker(pickerId, event) {
    toggleAuditPicker('cyberatlas', pickerId, event);
}

function toggleDeployAtlasPicker(pickerId, event) {
    toggleAuditPicker('deployatlas', pickerId, event);
}

async function selectSignalAtlasPickerOption(pickerId, value, event) {
    event?.stopPropagation?.();
    setAuditPickerState('signalatlas', null);

    if (pickerId === 'profile') applySignalAtlasProfile(String(value || 'elevated'));
    if (pickerId === 'mode') signalAtlasDraft.mode = String(value || 'public');
    if (pickerId === 'max_pages') signalAtlasDraft.max_pages = signalAtlasNormalizePageBudget(value, signalAtlasDraft.max_pages);
    if (pickerId === 'depth') signalAtlasDraft.depth = Number.parseInt(value, 10) || signalAtlasDraft.depth;
    if (pickerId === 'model') signalAtlasDraft.model = String(value || currentJoyBoyChatModel());
    if (pickerId === 'preset') signalAtlasDraft.preset = String(value || 'balanced');
    if (pickerId === 'level') signalAtlasDraft.level = String(value || 'basic_summary');
    if (pickerId === 'compare_model') signalAtlasDraft.compare_model = String(value || fallbackSignalAtlasCompareModel());

    const hiddenInputId = signalAtlasPickerInputId(pickerId);
    if (hiddenInputId) {
        const hiddenInput = document.getElementById(hiddenInputId);
        if (hiddenInput) hiddenInput.value = String(value ?? '');
    }

    if (pickerId === 'mode') {
        await refreshSignalAtlasProviderStatus(signalAtlasDraft.target, signalAtlasDraft.mode);
    }
    rerenderAuditWorkspace('signalatlas');
}

function signalAtlasSelectBadgeClass(option) {
    const tone = String(option?.tone || '').trim().toLowerCase();
    if (tone === 'cloud') return 'cloud';
    if (tone === 'local') return 'balanced';
    if (tone === 'expert') return 'powerful';
    if (tone === 'private') return 'tools';
    return 'fast';
}

function auditModuleCurrentProfiles(modelContext) {
    const profiles = Array.isArray(modelContext?.terminal_model_profiles)
        ? modelContext.terminal_model_profiles
        : [];
    const filtered = profiles.filter(profile => profile?.id);
    const current = currentJoyBoyChatModel();
    if (current && !filtered.some(profile => profile.id === current)) {
        filtered.unshift({
            id: current,
            provider: current.includes(':') && !/^qwen|^llama|^mistral|^gemma|^deepseek|^dolphin|^tiny|^llava|^moondream/i.test(current)
                ? current.split(':', 1)[0]
                : 'ollama',
            model: current.includes(':') ? current.split(':').slice(1).join(':') : current,
            configured: true,
            terminal_runtime: true,
            label: current,
        });
    }
    return filtered;
}

function buildAuditModelOptions(profiles, selectedValue = '') {
    return profiles.map(profile => {
        const description = describeSignalAtlasModel(profile);
        const provider = String(profile?.provider || 'ollama').toLowerCase();
        const isCloud = provider !== 'ollama';
        const configured = profile.configured !== false;
        return {
            value: profile.id,
            label: description.label,
            description: configured
                ? description.capability
                : moduleT('signalatlas.modelNotConfigured', 'not configured'),
            meta: `${description.privacy} · ${description.time}`,
            badge: isCloud
                ? moduleT('modelPicker.sources.cloud', 'Cloud')
                : moduleT('modelPicker.sources.local', 'Local'),
            tone: isCloud ? 'cloud' : 'local',
            section: isCloud
                ? moduleT('signalatlas.cloudModels', 'Cloud models')
                : moduleT('signalatlas.localModels', 'Local models'),
            selected: String(profile.id) === String(selectedValue || ''),
        };
    });
}

function buildSignalAtlasModelOptions(selectedValue = '') {
    return buildAuditModelOptions(signalAtlasCurrentProfiles(), selectedValue);
}

function buildPerfAtlasModelOptions(selectedValue = '') {
    return buildAuditModelOptions(perfAtlasCurrentProfiles(), selectedValue);
}

function buildSignalAtlasSimpleOptions(items, selectedValue, tone = '') {
    return (items || []).map(item => ({
        value: item.value,
        label: item.label,
        description: item.description || '',
        meta: item.meta || '',
        badge: item.badge || '',
        tone: item.tone || tone || '',
        selected: String(item.value) === String(selectedValue),
    }));
}

function signalAtlasPickerOptions(pickerId) {
    if (pickerId === 'profile') {
        return buildSignalAtlasSimpleOptions([
            {
                value: 'basic',
                label: signalAtlasProfileLabel('basic'),
                description: moduleT('signalatlas.auditProfileBasicDesc', 'Passe légère pour un premier diagnostic rapide.'),
                tone: 'fast',
            },
            {
                value: 'elevated',
                label: signalAtlasProfileLabel('elevated'),
                description: moduleT('signalatlas.auditProfileElevatedDesc', 'Bon équilibre entre profondeur technique, rendu JS et restitution IA.'),
                tone: 'local',
            },
            {
                value: 'ultra',
                label: signalAtlasProfileLabel('ultra'),
                description: moduleT('signalatlas.auditProfileUltraDesc', 'Passe la plus poussée : crawl large intelligent, rendu JS et pack IA complet. Si le site est petit, SignalAtlas s’arrête dès que le graphe est épuisé.'),
                tone: 'expert',
            },
        ], signalAtlasDraft.profile || 'elevated');
    }
    if (pickerId === 'mode') {
        return buildSignalAtlasSimpleOptions([
            {
                value: 'public',
                label: moduleT('signalatlas.publicMode', 'Audit public'),
                description: moduleT('signalatlas.publicModeHint', 'Crawl, rendu et signaux ouverts uniquement.'),
            },
            {
                value: 'verified_owner',
                label: moduleT('signalatlas.ownerMode', 'Propriétaire vérifié'),
                description: moduleT('signalatlas.ownerModeHint', 'Enrichit l’audit avec des données officielles connectées quand elles sont disponibles.'),
            },
        ], signalAtlasDraft.mode);
    }
    if (pickerId === 'max_pages') {
        const budgetOptions = SIGNALATLAS_PAGE_BUDGET_STEPS.map(value => ({
            value,
            label: String(value),
            description: moduleT('signalatlas.pageBudgetHint', 'Nombre maximum de pages échantillonnées sur cette passe d’audit.'),
        }));
        budgetOptions.push({
            value: SIGNALATLAS_UNLIMITED_PAGE_BUDGET,
            label: moduleT('signalatlas.pageBudgetUnlimited', '∞ Illimité'),
            description: moduleT(
                'signalatlas.pageBudgetUnlimitedHint',
                `Utilise le plafond du runtime pour cette passe (${SIGNALATLAS_MAX_PAGE_BUDGET} pages), avec arrêt automatique si le site est plus petit.`
            ),
            tone: 'expert',
        });
        return buildSignalAtlasSimpleOptions(
            budgetOptions,
            signalAtlasNormalizePageBudget(signalAtlasDraft.max_pages, SIGNALATLAS_DEFAULT_PAGE_BUDGET)
        );
    }
    if (pickerId === 'depth') {
        return buildSignalAtlasSimpleOptions([1, 2, 3, 4, 5].map(value => ({
            value,
            label: String(value),
            description: moduleT('signalatlas.depthHint', 'Contrôle jusqu’où le crawler déterministe peut suivre les liens internes.'),
        })), signalAtlasDraft.depth);
    }
    if (pickerId === 'model') {
        return buildSignalAtlasModelOptions(signalAtlasDraft.model || currentJoyBoyChatModel());
    }
    if (pickerId === 'compare_model') {
        return buildSignalAtlasModelOptions(signalAtlasDraft.compare_model || fallbackSignalAtlasCompareModel());
    }
    if (pickerId === 'preset') {
        return buildSignalAtlasSimpleOptions((signalAtlasModelContext?.presets || []).map(preset => ({
            value: preset.id,
            label: preset.label,
            description: preset.summary || '',
            tone: preset.id === 'expert' ? 'expert' : (preset.id === 'local_private' ? 'private' : ''),
        })), signalAtlasDraft.preset || 'balanced');
    }
    if (pickerId === 'level') {
        return buildSignalAtlasSimpleOptions((signalAtlasModelContext?.levels || []).map(level => ({
            value: level.id,
            label: level.label,
            description: moduleT(`signalatlas.levelHint_${level.id}`, ''),
        })), signalAtlasDraft.level || 'basic_summary');
    }
    return [];
}

function perfAtlasPickerInputId(pickerId) {
    if (pickerId === 'profile') return 'perfatlas-profile-select';
    if (pickerId === 'mode') return 'perfatlas-mode-select';
    if (pickerId === 'max_pages') return 'perfatlas-max-pages';
    if (pickerId === 'model') return 'perfatlas-model-select';
    if (pickerId === 'preset') return 'perfatlas-preset-select';
    if (pickerId === 'level') return 'perfatlas-level-select';
    if (pickerId === 'compare_model') return 'perfatlas-compare-model-select';
    return '';
}

function perfAtlasPickerOptions(pickerId) {
    if (pickerId === 'profile') {
        return buildSignalAtlasSimpleOptions([
            {
                value: 'basic',
                label: perfAtlasProfileLabel('basic'),
                description: perfAtlasProfileSummary('basic'),
                tone: 'fast',
            },
            {
                value: 'elevated',
                label: perfAtlasProfileLabel('elevated'),
                description: perfAtlasProfileSummary('elevated'),
                tone: 'local',
            },
            {
                value: 'ultra',
                label: perfAtlasProfileLabel('ultra'),
                description: perfAtlasProfileSummary('ultra'),
                tone: 'expert',
            },
        ], perfAtlasDraft.profile || 'elevated');
    }
    if (pickerId === 'mode') {
        return buildSignalAtlasSimpleOptions([
            {
                value: 'public',
                label: moduleT('perfatlas.publicMode', 'Public audit'),
                description: moduleT('perfatlas.publicModeHint', 'Field and lab signals available from public probes only.'),
            },
            {
                value: 'verified_owner',
                label: moduleT('perfatlas.ownerMode', 'Verified owner'),
                description: moduleT('perfatlas.ownerModeHint', 'Enrich diagnostics with platform and deployment context when connectors match.'),
            },
        ], perfAtlasDraft.mode || 'public');
    }
    if (pickerId === 'max_pages') {
        const budgetOptions = PERFATLAS_PAGE_BUDGET_STEPS.map(value => ({
            value,
            label: String(value),
            description: moduleT('perfatlas.pageBudgetHint', 'Representative pages sampled for delivery and resource analysis.'),
        }));
        budgetOptions.push({
            value: PERFATLAS_UNLIMITED_PAGE_BUDGET,
            label: moduleT('perfatlas.pageBudgetUnlimited', '∞ Max runtime'),
            description: moduleT('perfatlas.pageBudgetUnlimitedHint', `Uses the runtime ceiling for this pass (${PERFATLAS_MAX_PAGE_BUDGET} pages).`),
            tone: 'expert',
        });
        return buildSignalAtlasSimpleOptions(
            budgetOptions,
            perfAtlasNormalizePageBudget(perfAtlasDraft.max_pages, PERFATLAS_DEFAULT_PAGE_BUDGET)
        );
    }
    if (pickerId === 'model') {
        return buildPerfAtlasModelOptions(perfAtlasDraft.model || currentJoyBoyChatModel());
    }
    if (pickerId === 'compare_model') {
        return buildPerfAtlasModelOptions(perfAtlasDraft.compare_model || fallbackPerfAtlasCompareModel());
    }
    if (pickerId === 'preset') {
        return buildSignalAtlasSimpleOptions((perfAtlasModelContext?.presets || []).map(preset => ({
            value: preset.id,
            label: preset.label,
            description: preset.summary || '',
            tone: preset.id === 'expert' ? 'expert' : (preset.id === 'local_private' ? 'private' : ''),
        })), perfAtlasDraft.preset || 'balanced');
    }
    if (pickerId === 'level') {
        return buildSignalAtlasSimpleOptions((perfAtlasModelContext?.levels || []).map(level => ({
            value: level.id,
            label: level.label,
            description: moduleT(`perfatlas.levelHint_${level.id}`, '') || moduleT(`signalatlas.levelHint_${level.id}`, ''),
        })), perfAtlasDraft.level || 'full_expert_analysis');
    }
    return [];
}

async function selectPerfAtlasPickerOption(pickerId, value, event) {
    event?.stopPropagation?.();
    setAuditPickerState('perfatlas', null);

    if (pickerId === 'profile') applyPerfAtlasProfile(String(value || 'elevated'));
    if (pickerId === 'mode') perfAtlasDraft.mode = String(value || 'public');
    if (pickerId === 'max_pages') perfAtlasDraft.max_pages = perfAtlasNormalizePageBudget(value, perfAtlasDraft.max_pages);
    if (pickerId === 'model') perfAtlasDraft.model = String(value || currentJoyBoyChatModel());
    if (pickerId === 'preset') perfAtlasDraft.preset = String(value || 'balanced');
    if (pickerId === 'level') perfAtlasDraft.level = String(value || 'full_expert_analysis');
    if (pickerId === 'compare_model') perfAtlasDraft.compare_model = String(value || fallbackPerfAtlasCompareModel());

    const hiddenInputId = perfAtlasPickerInputId(pickerId);
    if (hiddenInputId) {
        const hiddenInput = document.getElementById(hiddenInputId);
        if (hiddenInput) hiddenInput.value = String(value ?? '');
    }

    if (pickerId === 'mode') {
        await refreshPerfAtlasProviderStatus(perfAtlasDraft.target, perfAtlasDraft.mode);
    }
    rerenderAuditWorkspace('perfatlas');
}

function renderAuditPicker(moduleId, pickerId, inputId, options, selectedValue) {
    const items = Array.isArray(options) ? options : [];
    const selected = items.find(option => String(option.value) === String(selectedValue)) || items[0] || {
        value: selectedValue,
        label: selectedValue,
        description: '',
        meta: '',
        badge: '',
        tone: '',
    };
    const cleanModuleId = String(moduleId || 'signalatlas').trim().toLowerCase();
    const isOpen = getAuditPickerState(cleanModuleId) === pickerId;
    const toggleFn = cleanModuleId === 'cyberatlas'
        ? 'toggleCyberAtlasPicker'
        : (cleanModuleId === 'deployatlas'
            ? 'toggleDeployAtlasPicker'
            : (cleanModuleId === 'perfatlas' ? 'togglePerfAtlasPicker' : 'toggleSignalAtlasPicker'));
    const selectFn = cleanModuleId === 'cyberatlas'
        ? 'selectCyberAtlasPickerOption'
        : (cleanModuleId === 'deployatlas'
            ? 'selectDeployAtlasPickerOption'
            : (cleanModuleId === 'perfatlas' ? 'selectPerfAtlasPickerOption' : 'selectSignalAtlasPickerOption'));
    let lastSection = '';
    const menuItems = items.map(option => {
        const currentSection = String(option.section || '');
        const sectionHeader = currentSection && currentSection !== lastSection
            ? `<div class="signalatlas-picker-section">${escapeHtml(currentSection)}</div>`
            : '';
        lastSection = currentSection;
        const jsValue = escapeHtml(JSON.stringify(String(option.value)));
        return `
            ${sectionHeader}
            <button
                class="signalatlas-picker-option model-picker-item${String(option.value) === String(selectedValue) ? ' active' : ''}"
                type="button"
                onclick="${selectFn}('${escapeHtml(pickerId)}', ${jsValue}, event)"
            >
                <div class="model-picker-info">
                    <div class="model-picker-name">${escapeHtml(option.label || '')}</div>
                    ${option.description ? `<div class="model-picker-desc">${escapeHtml(option.description)}</div>` : ''}
                    ${option.meta ? `<div class="model-picker-meta">${escapeHtml(option.meta)}</div>` : ''}
                </div>
                ${option.badge ? `<span class="model-picker-badge ${signalAtlasSelectBadgeClass(option)}">${escapeHtml(option.badge)}</span>` : ''}
            </button>
        `;
    }).join('');

    return `
        <div class="signalatlas-picker model-picker${isOpen ? ' open' : ''}">
            <input type="hidden" id="${escapeHtml(inputId)}" value="${escapeHtml(String(selected.value ?? ''))}">
            <button
                class="signalatlas-picker-btn model-picker-btn"
                type="button"
                onclick="${toggleFn}('${escapeHtml(pickerId)}', event)"
                aria-expanded="${isOpen ? 'true' : 'false'}"
            >
                <span class="signalatlas-picker-copy">
                    <span class="signalatlas-picker-value">${escapeHtml(selected.label || '')}</span>
                    ${selected.description || selected.meta ? `<span class="signalatlas-picker-meta">${escapeHtml(selected.description || selected.meta)}</span>` : ''}
                </span>
                <i data-lucide="chevron-down" class="arrow"></i>
            </button>
            <div class="signalatlas-picker-menu model-picker-popup">
                <div class="signalatlas-picker-list model-picker-list">
                    ${menuItems}
                </div>
            </div>
        </div>
    `;
}

function renderSignalAtlasPicker(pickerId, inputId, options, selectedValue) {
    return renderAuditPicker('signalatlas', pickerId, inputId, options, selectedValue);
}

function renderPerfAtlasPicker(pickerId, inputId, options, selectedValue) {
    return renderAuditPicker('perfatlas', pickerId, inputId, options, selectedValue);
}

function renderAuditFindingMeta(metaItems = []) {
    const items = (Array.isArray(metaItems) ? metaItems : [])
        .map(item => String(item ?? '').trim())
        .filter(Boolean);
    if (!items.length) return '';
    return `<div class="signalatlas-finding-meta">${items.map(item => `<span>${escapeHtml(item)}</span>`).join('')}</div>`;
}

function renderAuditEvidenceRows(evidenceItems = []) {
    const items = (Array.isArray(evidenceItems) ? evidenceItems : [])
        .map(item => String(item ?? '').trim())
        .filter(Boolean);
    if (!items.length) return '';
    return `
        <div class="cyberatlas-evidence-list">
            ${items.map(item => `
                <div class="cyberatlas-evidence-card">
                    <div class="cyberatlas-evidence-meta">${escapeHtml(item)}</div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderAuditFindingCard({
    title = '',
    summary = '',
    fix = '',
    severity = '',
    severityLabel = '',
    severityTone = '',
    meta = [],
    evidence = [],
    className = '',
    extraHtml = '',
} = {}) {
    const cleanSeverity = String(severity || '').trim();
    const tagLabel = severityLabel || (typeof signalAtlasSeverityLabel === 'function'
        ? signalAtlasSeverityLabel(cleanSeverity)
        : cleanSeverity);
    const tagTone = severityTone || (typeof signalAtlasSeverityTone === 'function'
        ? signalAtlasSeverityTone(cleanSeverity)
        : '');
    const cleanClassName = String(className || '').trim();
    return `
        <article class="signalatlas-finding-card${cleanClassName ? ` ${escapeHtml(cleanClassName)}` : ''}">
            <div class="signalatlas-finding-top">
                <div>
                    <div class="signalatlas-finding-title">${escapeHtml(title || '')}</div>
                    ${summary ? `<div class="signalatlas-finding-copy">${escapeHtml(summary)}</div>` : ''}
                </div>
                ${tagLabel ? `<span class="signalatlas-tag ${escapeHtml(tagTone)}">${escapeHtml(tagLabel)}</span>` : ''}
            </div>
            ${fix ? `<div class="signalatlas-mini-finding-copy">${escapeHtml(fix)}</div>` : ''}
            ${renderAuditFindingMeta(meta)}
            ${extraHtml || ''}
            ${renderAuditEvidenceRows(evidence)}
        </article>
    `;
}

function renderAuditFindingCards(items, mapItem, emptyHtml = '', limit = 8) {
    const source = Array.isArray(items) ? items.slice(0, limit) : [];
    if (!source.length) return emptyHtml;
    return source.map(item => renderAuditFindingCard(mapItem(item))).join('');
}

function renderAuditProgressBanner({
    namespace,
    progressState,
    launchPending = false,
    displayProgress = null,
    targetLabel = '',
    statusLabel,
    supportCopy,
    launchingLabel,
    launchingMessage,
    etaLabel = '',
}) {
    if (!progressState && !launchPending) return '';
    const progress = Number.isFinite(Number(displayProgress))
        ? Math.max(0, Math.min(100, Math.round(Number(displayProgress))))
        : launchPending && !progressState ? 4 : signalAtlasJobProgress(progressState);
    const phase = launchPending && !progressState ? launchingLabel : progressState.phase;
    const message = launchPending && !progressState ? launchingMessage : progressState.message;
    const liveStatus = launchPending && !progressState
        ? 'queued'
        : String(progressState?.status || '').toLowerCase();
    const isLive = launchPending || signalAtlasIsLiveProgressStatus(liveStatus);
    return `
        <div class="signalatlas-progress-surface">
            <div class="signalatlas-progress-top">
                <div class="signalatlas-progress-heading">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT(`${namespace}.progressTitle`, 'Audit activity'))}</div>
                    <div class="signalatlas-progress-title" aria-live="polite">
                        <span class="signalatlas-progress-spinner" aria-hidden="true"></span>
                        <span class="signalatlas-progress-message${isLive ? ' signalatlas-shimmer-text' : ''}">${escapeHtml(message)}</span>
                    </div>
                    <div class="signalatlas-progress-support">${escapeHtml(supportCopy)}</div>
                </div>
                <div class="signalatlas-progress-top-actions">
                    <span class="signalatlas-progress-chip">${escapeHtml(statusLabel(liveStatus || 'running'))}</span>
                    <span class="signalatlas-progress-chip is-phase">${escapeHtml(phase)}</span>
                    <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT(`${namespace}.progressPercent`, '{value}%', { value: progress }))}</span>
                    ${etaLabel ? `<span class="signalatlas-progress-chip is-eta">${escapeHtml(etaLabel)}</span>` : ''}
                </div>
            </div>
            <div class="signalatlas-progress-bar${isLive ? ' is-live' : ''}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${escapeHtml(String(progress))}">
                <div class="signalatlas-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(progress))}%"></div>
            </div>
            <div class="signalatlas-progress-meta">
                <span class="signalatlas-progress-meta-copy">${escapeHtml(targetLabel || moduleT(`${namespace}.backgroundResumeHint`, 'Cet audit continue en arrière-plan si tu quittes cette vue.'))}</span>
            </div>
        </div>
    `;
}

function renderSignalAtlasProgressBanner(progressState, targetLabel = '') {
    const displayProgress = auditDisplayProgress('signalatlas', progressState, signalAtlasCurrentAudit, signalAtlasLaunchPending);
    return renderAuditProgressBanner({
        namespace: 'signalatlas',
        progressState,
        launchPending: signalAtlasLaunchPending,
        displayProgress,
        targetLabel,
        statusLabel: signalAtlasStatusLabel,
        supportCopy: signalAtlasProgressSupportCopy(progressState, targetLabel),
        launchingLabel: moduleT('signalatlas.launching', 'Lancement'),
        launchingMessage: moduleT('signalatlas.launchingAudit', 'Démarrage du runtime d’audit...'),
        etaLabel: signalAtlasProgressEtaLabel(progressState, signalAtlasCurrentAudit, displayProgress),
    });
}

function hydrateSignalAtlasMotion(scope) {
    const root = scope || document;
    requestAnimationFrame(() => {
        root.querySelectorAll('.signalatlas-score-ring').forEach(node => {
            const hasScore = String(node.dataset.hasScore || '').toLowerCase() === 'true';
            const progress = Math.max(0, Math.min(100, Number(node.dataset.score || 0)));
            const circle = node.querySelector('.signalatlas-score-ring-progress');
            const circumference = Number(circle?.dataset?.circumference || 0);
            if (!circle || !Number.isFinite(circumference) || circumference <= 0) return;
            circle.style.strokeDasharray = String(circumference);
            if (!hasScore) {
                circle.style.strokeDashoffset = String(circumference);
                return;
            }
            const target = circumference - (circumference * progress / 100);
            circle.style.strokeDashoffset = String(target);
        });
    });
}

function getModulesView() {
    return document.getElementById('modules-view');
}

function toggleSignalAtlasAdvancedSettings() {
    signalAtlasAdvancedVisible = !signalAtlasAdvancedVisible;
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

function toggleSignalAtlasHistoryDrawer() {
    const nextValue = !signalAtlasHistoryVisible;
    signalAtlasHistoryVisible = nextValue;
    signalAtlasAnimateHistoryDrawer = nextValue;
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

function toggleSignalAtlasSeoDetails() {
    const nextValue = !signalAtlasSeoDetailsVisible;
    signalAtlasSeoDetailsVisible = nextValue;
    signalAtlasAnimateSeoDrawer = nextValue;
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

function getSignalAtlasView() {
    return document.getElementById('signalatlas-view');
}

function isSignalAtlasVisible() {
    const view = getSignalAtlasView();
    return !!view && view.style.display !== 'none';
}

function getPerfAtlasView() {
    return document.getElementById('perfatlas-view');
}

function isPerfAtlasVisible() {
    const view = getPerfAtlasView();
    return !!view && view.style.display !== 'none';
}

function currentJoyBoyChatModel() {
    if (typeof getSelectedModelForTab === 'function') {
        const selected = getSelectedModelForTab('chat');
        if (selected) return String(selected);
    }
    if (typeof userSettings !== 'undefined' && userSettings?.chatModel) {
        return String(userSettings.chatModel);
    }
    return 'qwen3.5:2b';
}

function moduleViewIds() {
    return ['modules-view', 'signalatlas-view', 'perfatlas-view', 'cyberatlas-view', 'deployatlas-view'];
}

function hideModulesWorkspaces() {
    signalAtlasOpenPickerId = null;
    perfAtlasOpenPickerId = null;
    moduleViewIds().forEach(id => {
        const node = document.getElementById(id);
        if (node) node.style.display = 'none';
    });
    stopSignalAtlasRefresh();
    stopPerfAtlasRefresh();
    window.stopCyberAtlasRefresh?.();
}

function hideOtherJoyBoyViews() {
    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const addonsView = document.getElementById('addons-view');
    const extensionsView = document.getElementById('extensions-view');
    const modelsView = document.getElementById('models-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (addonsView) addonsView.style.display = 'none';
    if (extensionsView) extensionsView.style.display = 'none';
    if (modelsView) modelsView.style.display = 'none';
    if (typeof hideProjectView === 'function') hideProjectView();
}

function clearActiveHubButtons() {
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
}

function applyModulesShellMode(activeButtonId, bodyClass) {
    hideOtherJoyBoyViews();
    clearActiveHubButtons();
    document.getElementById(activeButtonId)?.classList.add('active');
    document.body.classList.remove('addons-mode', 'extensions-mode', 'models-mode', 'projects-mode', 'modules-mode', 'signalatlas-mode', 'perfatlas-mode', 'cyberatlas-mode', 'deployatlas-mode');
    document.body.classList.add(bodyClass);
}

function activeAuditModuleJobs(moduleId) {
    const clean = String(moduleId || '').trim().toLowerCase();
    if (!clean || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return [];
    return runtimeJobsCache.filter(job =>
        !['done', 'error', 'cancelled'].includes(String(job?.status || '').toLowerCase())
        && String(job?.metadata?.module_id || job?.kind || '').trim().toLowerCase() === clean
    );
}

function syncSignalAtlasDraftFromDom() {
    const targetInput = document.getElementById('signalatlas-target-input');
    const profile = document.getElementById('signalatlas-profile-select');
    const modeSelect = document.getElementById('signalatlas-mode-select');
    const maxPages = document.getElementById('signalatlas-max-pages');
    const depth = document.getElementById('signalatlas-depth');
    const renderJs = document.getElementById('signalatlas-render-js');
    const model = document.getElementById('signalatlas-model-select');
    const preset = document.getElementById('signalatlas-preset-select');
    const level = document.getElementById('signalatlas-level-select');
    const compareModel = document.getElementById('signalatlas-compare-model-select');

    if (targetInput) signalAtlasDraft.target = targetInput.value;
    if (profile) signalAtlasDraft.profile = profile.value;
    if (modeSelect) signalAtlasDraft.mode = modeSelect.value;
    if (maxPages) signalAtlasDraft.max_pages = signalAtlasNormalizePageBudget(maxPages.value, signalAtlasDraft.max_pages);
    if (depth) signalAtlasDraft.depth = Number.parseInt(depth.value, 10) || signalAtlasDraft.depth;
    if (renderJs) signalAtlasDraft.render_js = !!renderJs.checked;
    if (model) signalAtlasDraft.model = model.value;
    if (preset) signalAtlasDraft.preset = preset.value;
    if (level) signalAtlasDraft.level = level.value;
    if (compareModel) signalAtlasDraft.compare_model = compareModel.value;
}

async function refreshSignalAtlasProviderStatus(target = signalAtlasDraft.target, mode = signalAtlasDraft.mode) {
    if (typeof apiSignalAtlas === 'undefined') return [];
    const validation = signalAtlasValidateTarget(target);
    if (!validation.valid) {
        signalAtlasProviders = [];
        return signalAtlasProviders;
    }
    const providerResult = await apiSignalAtlas.getProviderStatus(validation.normalized || target || '', mode || 'public');
    signalAtlasProviders = Array.isArray(providerResult.data?.providers) ? providerResult.data.providers : [];
    return signalAtlasProviders;
}

async function signalAtlasControlsChanged() {
    syncSignalAtlasDraftFromDom();
    await refreshSignalAtlasProviderStatus(signalAtlasDraft.target, signalAtlasDraft.mode);
    renderSignalAtlasWorkspace();
}

function signalAtlasTargetInputChanged(event) {
    signalAtlasMarkInteraction();
    signalAtlasDraft.target = String(event?.target?.value || '');
    renderSignalAtlasTargetValidationUi();
}

async function loadModulesCatalog() {
    if (typeof apiModules === 'undefined') {
        joyboyModulesCatalog = [...NATIVE_AUDIT_MODULE_FALLBACK_CATALOG];
        return joyboyModulesCatalog;
    }
    const mergeCatalog = (entries, options = {}) => {
        const backendSynchronized = options.backendSynchronized === true;
        const merged = new Map();
        const backendIds = new Set();
        NATIVE_AUDIT_MODULE_FALLBACK_CATALOG.forEach(module => {
            merged.set(String(module.id || '').trim().toLowerCase(), { ...module });
        });
        (Array.isArray(entries) ? entries : []).forEach(module => {
            const moduleId = String(module?.id || '').trim().toLowerCase();
            if (!moduleId) return;
            backendIds.add(moduleId);
            merged.set(moduleId, {
                ...(merged.get(moduleId) || {}),
                ...module,
                backend_ready: true,
            });
        });
        if (backendSynchronized) {
            NATIVE_AUDIT_MODULE_FALLBACK_CATALOG.forEach(module => {
                const moduleId = String(module.id || '').trim().toLowerCase();
                if (!moduleId || backendIds.has(moduleId)) return;
                merged.set(moduleId, {
                    ...(merged.get(moduleId) || {}),
                    available: false,
                    backend_ready: false,
                    status: 'restart_required',
                    locked_reason: moduleT(
                        'modules.restartRequired',
                        'Restart JoyBoy to activate this module in the running app.'
                    ),
                });
            });
        }
        return Array.from(merged.values());
    };

    try {
        const result = await apiModules.list();
        joyboyModulesCatalog = mergeCatalog(result.ok ? result.data?.modules : [], {
            backendSynchronized: result.ok,
        });
    } catch (error) {
        console.error('[MODULES] catalog refresh failed:', error);
        joyboyModulesCatalog = mergeCatalog(joyboyModulesCatalog);
    }
    return joyboyModulesCatalog;
}

async function loadSignalAtlasBootstrap() {
    const tasks = [
        apiSignalAtlas.listAudits(60),
        apiSignalAtlas.getModelContext(),
    ];
    const [auditsResult, modelResult] = await Promise.all(tasks);
    signalAtlasAudits = Array.isArray(auditsResult.data?.audits) ? auditsResult.data.audits : [];
    signalAtlasModelContext = modelResult.ok ? modelResult.data : null;
    await refreshSignalAtlasProviderStatus(signalAtlasDraft.target, signalAtlasDraft.mode);

    if (!signalAtlasDraft.profile) {
        applySignalAtlasProfile('elevated');
    }
    if (!signalAtlasDraft.model) {
        signalAtlasDraft.model = currentJoyBoyChatModel();
    }
    if (!signalAtlasDraft.compare_model) {
        signalAtlasDraft.compare_model = fallbackSignalAtlasCompareModel();
    }

    if (signalAtlasCurrentAuditId) {
        await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
    } else if (signalAtlasAudits.length) {
        signalAtlasCurrentAuditId = signalAtlasAudits[0].id;
        await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
    }
}

async function loadSignalAtlasAudit(auditId, options = {}) {
    if (!auditId || typeof apiSignalAtlas === 'undefined') return null;
    const previousAuditId = signalAtlasCurrentAuditId;
    const result = await apiSignalAtlas.getAudit(auditId);
    if (!result.ok || !result.data?.audit) {
        if (!options.silent && typeof Toast !== 'undefined') {
        Toast.error(result.data?.error || moduleT('signalatlas.loadError', 'Impossible de charger cet audit.'));
        }
        return null;
    }
    signalAtlasCurrentAuditId = auditId;
    if (previousAuditId !== auditId) {
        signalAtlasSerpPage = 1;
    }
    signalAtlasCurrentAudit = result.data.audit;
    if (signalAtlasIsTerminalAuditStatus(signalAtlasCurrentAudit.status)) {
        clearSignalAtlasRuntimeJobsForAudit(auditId);
    }
    const existing = signalAtlasAudits.findIndex(item => item.id === auditId);
    const summaryCard = summarizeSignalAtlasAudit(signalAtlasCurrentAudit);
    if (existing >= 0) signalAtlasAudits.splice(existing, 1, summaryCard);
    else signalAtlasAudits.unshift(summaryCard);
    signalAtlasAudits.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    return signalAtlasCurrentAudit;
}

function summarizeSignalAtlasAudit(audit) {
    const summary = audit?.summary || {};
    const target = audit?.target || {};
    const reportModel = signalAtlasReportModelInfo(audit);
    return {
        id: audit?.id,
        title: audit?.title || target.host || target.normalized_url || moduleT('signalatlas.untitledAudit', 'Audit sans titre'),
        status: audit?.status || 'unknown',
        updated_at: audit?.updated_at,
        created_at: audit?.created_at,
        target_url: target.normalized_url || target.raw || '',
        host: target.host || '',
        mode: target.mode || summary.mode || 'public',
        global_score: summary.global_score,
        pages_crawled: summary.pages_crawled || 0,
        top_risk: summary.top_risk || '',
        has_ai: Array.isArray(audit?.interpretations) && audit.interpretations.length > 0,
        report_model_label: reportModel.label || '',
        report_model_meta: reportModel.meta || '',
        report_model_state: reportModel.state || 'none',
    };
}

function syncPerfAtlasDraftFromDom() {
    const targetInput = document.getElementById('perfatlas-target-input');
    const profile = document.getElementById('perfatlas-profile-select');
    const modeSelect = document.getElementById('perfatlas-mode-select');
    const maxPages = document.getElementById('perfatlas-max-pages');
    const model = document.getElementById('perfatlas-model-select');
    const preset = document.getElementById('perfatlas-preset-select');
    const level = document.getElementById('perfatlas-level-select');
    const compareModel = document.getElementById('perfatlas-compare-model-select');

    if (targetInput) perfAtlasDraft.target = targetInput.value;
    if (profile) perfAtlasDraft.profile = profile.value;
    if (modeSelect) perfAtlasDraft.mode = modeSelect.value;
    if (maxPages) perfAtlasDraft.max_pages = perfAtlasNormalizePageBudget(maxPages.value, perfAtlasDraft.max_pages);
    if (model) perfAtlasDraft.model = model.value;
    if (preset) perfAtlasDraft.preset = preset.value;
    if (level) perfAtlasDraft.level = level.value;
    if (compareModel) perfAtlasDraft.compare_model = compareModel.value;
}

async function refreshPerfAtlasProviderStatus(target = perfAtlasDraft.target, mode = perfAtlasDraft.mode) {
    if (typeof apiPerfAtlas === 'undefined') return [];
    const validation = perfAtlasValidateTarget(target);
    if (!validation.valid) {
        perfAtlasProviders = [];
        return perfAtlasProviders;
    }
    const providerResult = await apiPerfAtlas.getProviderStatus(validation.normalized || target || '', mode || 'public');
    perfAtlasProviders = Array.isArray(providerResult.data?.providers) ? providerResult.data.providers : [];
    return perfAtlasProviders;
}

async function perfAtlasControlsChanged() {
    syncPerfAtlasDraftFromDom();
    await refreshPerfAtlasProviderStatus(perfAtlasDraft.target, perfAtlasDraft.mode);
    renderPerfAtlasWorkspace();
}

function perfAtlasTargetInputChanged(event) {
    perfAtlasDraft.target = String(event?.target?.value || '');
    renderPerfAtlasTargetValidationUi();
}

async function loadPerfAtlasBootstrap() {
    const tasks = [
        apiPerfAtlas.listAudits(60),
        apiPerfAtlas.getModelContext(),
    ];
    const [auditsResult, modelResult] = await Promise.all(tasks);
    perfAtlasAudits = Array.isArray(auditsResult.data?.audits) ? auditsResult.data.audits : [];
    perfAtlasModelContext = modelResult.ok ? modelResult.data : null;
    await refreshPerfAtlasProviderStatus(perfAtlasDraft.target, perfAtlasDraft.mode);

    if (!perfAtlasDraft.profile) {
        applyPerfAtlasProfile('elevated');
    }
    if (!perfAtlasDraft.model) {
        perfAtlasDraft.model = currentJoyBoyChatModel();
    }
    if (!perfAtlasDraft.compare_model) {
        perfAtlasDraft.compare_model = fallbackPerfAtlasCompareModel();
    }

    if (perfAtlasCurrentAuditId) {
        await loadPerfAtlasAudit(perfAtlasCurrentAuditId, { silent: true });
    } else if (perfAtlasAudits.length) {
        perfAtlasCurrentAuditId = perfAtlasAudits[0].id;
        await loadPerfAtlasAudit(perfAtlasCurrentAuditId, { silent: true });
    }
}

async function loadPerfAtlasAudit(auditId, options = {}) {
    if (!auditId || typeof apiPerfAtlas === 'undefined') return null;
    const result = await apiPerfAtlas.getAudit(auditId);
    if (!result.ok || !result.data?.audit) {
        if (!options.silent && typeof Toast !== 'undefined') {
            Toast.error(result.data?.error || moduleT('perfatlas.loadError', 'Unable to load this audit.'));
        }
        return null;
    }
    perfAtlasCurrentAuditId = auditId;
    perfAtlasCurrentAudit = result.data.audit;
    if (perfAtlasIsTerminalStatus(perfAtlasCurrentAudit.status)) {
        clearPerfAtlasRuntimeJobsForAudit(auditId);
    }
    const existing = perfAtlasAudits.findIndex(item => item.id === auditId);
    const summaryCard = summarizePerfAtlasAudit(perfAtlasCurrentAudit);
    if (existing >= 0) perfAtlasAudits.splice(existing, 1, summaryCard);
    else perfAtlasAudits.unshift(summaryCard);
    perfAtlasAudits.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    return perfAtlasCurrentAudit;
}

function summarizePerfAtlasAudit(audit) {
    const summary = audit?.summary || {};
    const target = audit?.target || {};
    const reportModel = perfAtlasReportModelInfo(audit);
    return {
        id: audit?.id,
        title: audit?.title || target.host || target.normalized_url || moduleT('perfatlas.untitledAudit', 'Untitled audit'),
        status: audit?.status || 'unknown',
        updated_at: audit?.updated_at,
        created_at: audit?.created_at,
        target_url: target.normalized_url || target.raw || '',
        host: target.host || '',
        mode: target.mode || summary.mode || 'public',
        global_score: summary.global_score,
        pages_crawled: summary.pages_crawled || 0,
        lab_pages_analyzed: summary.lab_pages_analyzed || 0,
        top_risk: summary.top_risk || '',
        field_data_available: !!summary.field_data_available,
        lab_data_available: !!summary.lab_data_available,
        report_model_label: reportModel.label || '',
        report_model_meta: reportModel.meta || '',
        report_model_state: reportModel.state || 'none',
    };
}

function activeSignalAtlasJobForAudit(auditId) {
    const jobs = activeSignalAtlasJobs();
    if (!jobs.length) return null;
    return jobs.find(job =>
        String(job?.metadata?.audit_id || '') === String(auditId || '')
    ) || null;
}

function activePerfAtlasJobForAudit(auditId) {
    const jobs = activePerfAtlasJobs();
    if (!jobs.length) return null;
    return jobs.find(job =>
        String(job?.metadata?.audit_id || '') === String(auditId || '')
    ) || null;
}

function seedAuditModuleRuntimeJob(job, moduleId, fallbackAuditId = '', launchMessage = '') {
    if (!job || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return;
    const cleanModuleId = String(moduleId || '').trim().toLowerCase();
    const seeded = {
        ...job,
        kind: job.kind || cleanModuleId,
        status: job.status || 'queued',
        phase: job.phase || job.status || 'queued',
        progress: Number.isFinite(Number(job.progress)) ? Number(job.progress) : 2,
        message: job.message || launchMessage,
        metadata: {
            ...(job.metadata || {}),
            module_id: cleanModuleId,
            audit_id: job?.metadata?.audit_id || fallbackAuditId || '',
        },
    };
    const existing = runtimeJobsCache.findIndex(item => String(item?.id || '') === String(seeded.id || ''));
    if (existing >= 0) runtimeJobsCache.splice(existing, 1, seeded);
    else runtimeJobsCache.unshift(seeded);
    if (typeof renderRuntimeJobs === 'function') renderRuntimeJobs();
}

function clearSignalAtlasRuntimeJobsForAudit(auditId) {
    const cleanAuditId = String(auditId || '').trim();
    if (!cleanAuditId || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return;
    const before = runtimeJobsCache.length;
    runtimeJobsCache = runtimeJobsCache.filter(job =>
        job?.metadata?.module_id !== 'signalatlas'
        || String(job?.metadata?.audit_id || '') !== cleanAuditId
        || !signalAtlasIsActiveJob(job)
    );
    if (runtimeJobsCache.length !== before && typeof renderRuntimeJobs === 'function') renderRuntimeJobs();
}

function seedSignalAtlasRuntimeJob(job, fallbackAuditId = '') {
    seedAuditModuleRuntimeJob(job, 'signalatlas', fallbackAuditId, moduleT('signalatlas.launchingAudit', 'Démarrage du runtime d’audit...'));
}

function seedPerfAtlasRuntimeJob(job, fallbackAuditId = '') {
    seedAuditModuleRuntimeJob(job, 'perfatlas', fallbackAuditId, moduleT('perfatlas.launchingAudit', 'Starting the performance runtime...'));
}

function clearPerfAtlasRuntimeJobsForAudit(auditId) {
    const cleanAuditId = String(auditId || '').trim();
    if (!cleanAuditId || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return;
    const before = runtimeJobsCache.length;
    runtimeJobsCache = runtimeJobsCache.filter(job =>
        job?.metadata?.module_id !== 'perfatlas'
        || String(job?.metadata?.audit_id || '') !== cleanAuditId
        || !signalAtlasIsActiveJob(job)
    );
    if (runtimeJobsCache.length !== before && typeof renderRuntimeJobs === 'function') renderRuntimeJobs();
}

function signalAtlasStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'queued') return moduleT('signalatlas.statusQueued', 'En file');
    if (clean === 'running') return moduleT('signalatlas.statusRunning', 'En cours');
    if (clean === 'done') return moduleT('signalatlas.statusDone', 'Prêt');
    if (clean === 'error') return moduleT('signalatlas.statusError', 'Erreur');
    if (clean === 'cancelled') return moduleT('signalatlas.statusCancelled', 'Annulé');
    return clean || moduleT('signalatlas.statusUnknown', 'Inconnu');
}

function signalAtlasSeverityTone(value) {
    const clean = String(value || '').toLowerCase();
    if (clean === 'critical' || clean === 'high') return 'is-danger';
    if (clean === 'medium') return 'is-warn';
    if (clean === 'low') return 'is-soft';
    return '';
}

function signalAtlasScoreTone(score) {
    const numeric = Number(score || 0);
    if (numeric >= 85) return 'is-good';
    if (numeric >= 65) return 'is-warn';
    return 'is-danger';
}

function signalAtlasCurrentProfiles() {
    return auditModuleCurrentProfiles(signalAtlasModelContext);
}

function perfAtlasCurrentProfiles() {
    return auditModuleCurrentProfiles(perfAtlasModelContext);
}

function perfAtlasEstimateSecondsForAudit(audit = null) {
    const options = audit?.options || perfAtlasDraft || {};
    const metadata = audit?.metadata || {};
    const metadataEstimate = Number(metadata.estimated_seconds);
    if (Number.isFinite(metadataEstimate) && metadataEstimate > 0) return metadataEstimate;
    const maxPages = perfAtlasResolvedPageBudget(options.max_pages ?? perfAtlasDraft.max_pages, PERFATLAS_DEFAULT_PAGE_BUDGET);
    const aiLevel = String(metadata.ai?.level || perfAtlasDraft.level || 'basic_summary').toLowerCase();
    const crawlSeconds = 10 + Math.min(maxPages, PERFATLAS_MAX_PAGE_BUDGET) * 4;
    const fieldSeconds = 8;
    const labProbeRuns = maxPages <= 3 ? 1 : maxPages <= 8 ? 3 : 7;
    const labSeconds = labProbeRuns * 10;
    const ownerSeconds = 6;
    const aiSeconds = aiLevel === 'no_ai'
        ? 0
        : aiLevel === 'ai_remediation_pack'
            ? 70
            : aiLevel === 'full_expert_analysis'
                ? 45
                : 18;
    return Math.max(35, Math.min(900, crawlSeconds + fieldSeconds + labSeconds + ownerSeconds + aiSeconds));
}

function perfAtlasProgressEtaLabel(progressState, audit = null, displayProgress = null) {
    const status = String(progressState?.status || '').toLowerCase();
    if (!progressState && perfAtlasLaunchPending) {
        return moduleT('perfatlas.etaInitial', 'estimated {duration}', {
            duration: signalAtlasFormatDuration(perfAtlasEstimateSecondsForAudit(audit)),
        });
    }
    if (!progressState || !signalAtlasIsLiveProgressStatus(status)) return '';
    const progress = Number.isFinite(Number(displayProgress)) ? Number(displayProgress) : signalAtlasJobProgress(progressState);
    if (progress >= 96) return moduleT('perfatlas.etaFinalizing', 'finalizing');
    const remainingSeconds = auditProgressRemainingSeconds('perfatlas', progressState, audit, progress);
    if (Number.isFinite(remainingSeconds) && remainingSeconds > 0) {
        return moduleT('perfatlas.etaRemaining', 'remaining {duration}', {
            duration: signalAtlasFormatDuration(remainingSeconds),
        });
    }
    return moduleT('perfatlas.etaInitial', 'estimated {duration}', {
        duration: signalAtlasFormatDuration(perfAtlasEstimateSecondsForAudit(audit)),
    });
}

function activePerfAtlasJobs() {
    return activeAuditModuleJobs('perfatlas')
        .filter(job => {
            const auditId = String(job?.metadata?.audit_id || '').trim();
            return auditId && !perfAtlasIsTerminalStatus(perfAtlasKnownAuditStatus(auditId));
        })
        .sort((left, right) => String(right?.updated_at || '').localeCompare(String(left?.updated_at || '')));
}

function perfAtlasIsTerminalStatus(status) {
    return ['done', 'error', 'cancelled'].includes(String(status || '').trim().toLowerCase());
}

function perfAtlasKnownAuditStatus(auditId) {
    const cleanId = String(auditId || '').trim();
    if (!cleanId) return '';
    const summary = Array.isArray(perfAtlasAudits)
        ? perfAtlasAudits.find(item => String(item?.id || '').trim() === cleanId)
        : null;
    const summaryStatus = String(summary?.status || '').trim().toLowerCase();
    if (String(perfAtlasCurrentAudit?.id || '').trim() === cleanId) {
        const currentStatus = String(perfAtlasCurrentAudit?.status || '').trim().toLowerCase();
        if (perfAtlasIsTerminalStatus(currentStatus)) return currentStatus;
        if (perfAtlasIsTerminalStatus(summaryStatus)) return summaryStatus;
        return currentStatus || summaryStatus;
    }
    return summaryStatus;
}

function perfAtlasStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'queued') return moduleT('perfatlas.statusQueued', 'Queued');
    if (clean === 'running') return moduleT('perfatlas.statusRunning', 'Running');
    if (clean === 'done') return moduleT('perfatlas.statusDone', 'Ready');
    if (clean === 'error') return moduleT('perfatlas.statusError', 'Error');
    if (clean === 'cancelling') return moduleT('perfatlas.statusCancelling', 'Cancelling');
    if (clean === 'cancelled') return moduleT('perfatlas.statusCancelled', 'Cancelled');
    return clean || moduleT('perfatlas.statusUnknown', 'Unknown');
}

function perfAtlasFallbackJobForAudit(audit, status = '') {
    const auditId = typeof audit === 'string' ? audit : audit?.id;
    if (!auditId) return null;
    const cleanStatus = String(status || (typeof audit === 'object' ? audit?.status : '') || 'running').toLowerCase();
    const target = typeof audit === 'object'
        ? (audit?.target?.normalized_url || audit?.target_url || audit?.host || audit?.title || '')
        : (perfAtlasDraft.target || 'PerfAtlas');
    return {
        id: `perfatlas-audit-${auditId}`,
        kind: 'perfatlas',
        status: cleanStatus,
        phase: cleanStatus,
        progress: cleanStatus === 'queued' ? 2 : 8,
        prompt: target || 'PerfAtlas',
        message: cleanStatus === 'queued'
            ? moduleT('perfatlas.phaseQueued', 'Queued')
            : moduleT('perfatlas.auditRunning', 'Audit running...'),
        metadata: {
            module_id: 'perfatlas',
            audit_id: auditId,
        },
        synthetic: true,
    };
}

function ensurePerfAtlasRuntimeJobForProgress(progressState) {
    if (!progressState?.job?.synthetic) return;
    seedAuditModuleRuntimeJob(
        progressState.job,
        'perfatlas',
        progressState.auditId,
        progressState.message || moduleT('perfatlas.auditRunning', 'Audit running...')
    );
}

function perfAtlasJobPhaseLabel(phase) {
    const clean = String(phase || '').trim().toLowerCase();
    if (clean === 'crawl') return moduleT('perfatlas.phaseCrawl', 'Sampling');
    if (clean === 'extract') return moduleT('perfatlas.phaseExtract', 'Delivery scan');
    if (clean === 'field') return moduleT('perfatlas.phaseField', 'Field data');
    if (clean === 'lab') return moduleT('perfatlas.phaseLab', 'Lab probes');
    if (clean === 'owner') return moduleT('perfatlas.phaseOwner', 'Owner context');
    if (clean === 'score') return moduleT('perfatlas.phaseScore', 'Scoring');
    if (clean === 'ai') return moduleT('perfatlas.phaseAi', 'AI interpretation');
    if (clean === 'queued') return moduleT('perfatlas.phaseQueued', 'Queued');
    if (clean === 'cancelling') return moduleT('perfatlas.statusCancelling', 'Cancelling');
    if (clean === 'done') return moduleT('perfatlas.phaseDone', 'Done');
    if (clean === 'error') return moduleT('perfatlas.phaseError', 'Error');
    if (clean === 'cancelled') return moduleT('perfatlas.phaseCancelled', 'Cancelled');
    return perfAtlasStatusLabel(clean || 'unknown');
}

function perfAtlasJobMessage(job) {
    const raw = String(job?.message || '').trim();
    if (!raw) return perfAtlasJobPhaseLabel(job?.phase || job?.status);
    if (/^Preparing performance target$/i.test(raw)) {
        return moduleT('perfatlas.progressPreparing', 'Preparing the target');
    }
    if (/^Collecting delivery and resource signals$/i.test(raw)) {
        return moduleT('perfatlas.progressCollectingDelivery', 'Collecting delivery and resource signals');
    }
    if (/^Collecting field performance signals$/i.test(raw)) {
        return moduleT('perfatlas.progressCollectingField', 'Collecting public field signals');
    }
    if (/^Running lab performance probes$/i.test(raw)) {
        return moduleT('perfatlas.progressRunningLab', 'Running representative lab probes');
    }
    if (/^Collecting owner context$/i.test(raw)) {
        return moduleT('perfatlas.progressCollectingOwner', 'Collecting owner deployment context');
    }
    if (/^Scoring performance findings$/i.test(raw)) {
        return moduleT('perfatlas.progressScoring', 'Scoring the sampled performance findings');
    }
    if (/^Generating AI interpretation$/i.test(raw)) {
        return moduleT('perfatlas.progressGeneratingAi', 'Generating the AI remediation pack');
    }
    if (/^Preparing deterministic audit excerpt$/i.test(raw)) {
        return moduleT('perfatlas.progressPreparingAiExcerpt', 'Preparing the deterministic excerpt for AI');
    }
    if (/^Generating first interpretation$/i.test(raw)) {
        return moduleT('perfatlas.progressGeneratingFirstInterpretation', 'Generating the first interpretation');
    }
    if (/^Generating second interpretation$/i.test(raw)) {
        return moduleT('perfatlas.progressGeneratingSecondInterpretation', 'Generating the second interpretation');
    }
    if (/^PerfAtlas audit complete$/i.test(raw)) {
        return moduleT('perfatlas.progressAuditComplete', 'PerfAtlas audit complete');
    }
    if (/^PerfAtlas AI interpretation ready$/i.test(raw)) {
        return moduleT('perfatlas.progressAiReady', 'AI interpretation ready');
    }
    if (/^PerfAtlas model comparison ready$/i.test(raw)) {
        return moduleT('perfatlas.progressCompareReady', 'Model comparison ready');
    }
    if (/^Crawling /i.test(raw)) {
        return moduleT('perfatlas.progressSampling', 'Sampling {target}', {
            target: raw.replace(/^Crawling /i, '').trim(),
        });
    }
    return raw;
}

function perfAtlasProgressSupportCopy(progressState, fallbackHint = '') {
    const clean = String(progressState?.job?.phase || progressState?.status || '').trim().toLowerCase();
    if (!progressState && perfAtlasLaunchPending) {
        return moduleT('perfatlas.progressLaunchingCopy', 'PerfAtlas is preparing the runtime, the representative page set, and the first probes.');
    }
    if (clean === 'crawl') {
        return moduleT('perfatlas.progressCrawlCopy', 'PerfAtlas picks a representative page sample from the target, its navigation, and the first crawl frontier.');
    }
    if (clean === 'extract') {
        return moduleT('perfatlas.progressExtractCopy', 'Headers, assets, resource hints, cache policies, and delivery signals are being collected.');
    }
    if (clean === 'field') {
        return moduleT('perfatlas.progressFieldCopy', 'Public field data is being checked first so the report can separate real-user signals from lab-only diagnostics.');
    }
    if (clean === 'lab') {
        return moduleT('perfatlas.progressLabCopy', 'Representative lab probes are running. Multi-run medians can make this step pause on the same percentage for a while.');
    }
    if (clean === 'owner') {
        return moduleT('perfatlas.progressOwnerCopy', 'Owner connectors are being matched so deployment, CDN, and platform context can sharpen the remediation plan.');
    }
    if (clean === 'score') {
        return moduleT('perfatlas.progressScoreCopy', 'PerfAtlas is weighting confirmed issues and separating blocking risks from secondary symptoms.');
    }
    if (clean === 'ai') {
        return moduleT('perfatlas.progressAiCopy', 'The model is turning deterministic evidence into an implementation-ready remediation pack.');
    }
    if (clean === 'queued') {
        return moduleT('perfatlas.progressQueuedCopy', 'The audit is queued and will start the next performance pass as soon as the worker is free.');
    }
    return fallbackHint || moduleT('perfatlas.backgroundResumeHint', 'This audit keeps running if you leave the view.');
}

function perfAtlasValidateTarget(value) {
    return signalAtlasValidateTarget(value);
}

function renderPerfAtlasTargetValidationUi() {
    const input = document.getElementById('perfatlas-target-input');
    const feedback = document.getElementById('perfatlas-target-feedback');
    const launchButton = document.getElementById('perfatlas-launch-btn');
    const validation = perfAtlasValidateTarget(input?.value ?? perfAtlasDraft.target);
    const showError = validation.present && !validation.valid;

    if (input) {
        input.classList.toggle('is-invalid', showError);
        input.setAttribute('aria-invalid', showError ? 'true' : 'false');
    }
    if (feedback) {
        feedback.textContent = showError ? validation.message : '';
        feedback.classList.toggle('is-visible', showError);
    }
    if (launchButton && launchButton.dataset.action !== 'cancel') {
        launchButton.disabled = perfAtlasLaunchPending || !validation.valid;
    }
    return validation;
}

function perfAtlasLatestInterpretation(audit) {
    const items = Array.isArray(audit?.interpretations) ? audit.interpretations : [];
    return items.length ? items[items.length - 1] : null;
}

function perfAtlasReportModelInfo(audit) {
    const latest = perfAtlasLatestInterpretation(audit);
    const configured = audit?.metadata?.ai || {};
    const model = latest?.model || configured?.model || '';
    if (!model) {
        return {
            state: 'none',
            label: moduleT('perfatlas.noAiGeneratedYet', 'No AI remediation yet'),
            detail: moduleT('perfatlas.reportGeneratedWithoutAi', 'This report is still deterministic until an AI interpretation is generated.'),
            meta: '',
        };
    }
    const level = latest?.level || configured?.level || '';
    const preset = latest?.preset || configured?.preset || '';
    const meta = [signalAtlasContextOptionLabel('levels', level), signalAtlasContextOptionLabel('presets', preset)]
        .filter(Boolean)
        .join(' · ');
    if (!latest) {
        return {
            state: 'planned',
            label: model,
            detail: moduleT('perfatlas.reportPlannedWithModel', 'The next remediation run will use {model}.', { model }),
            meta,
        };
    }
    return {
        state: 'generated',
        label: model,
        detail: moduleT('perfatlas.generatedWithModel', 'AI remediation generated with {model}.', { model }),
        meta,
    };
}

function perfAtlasFormatMs(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return 'n/a';
    return `${Math.round(numeric)} ms`;
}

function perfAtlasFormatCls(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) return 'n/a';
    return numeric.toFixed(3);
}

function perfAtlasFormatPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 'n/a';
    return `${Math.round(numeric)}%`;
}

function perfAtlasFormatBytes(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric <= 0) return 'n/a';
    if (numeric >= 1024 * 1024) return `${(numeric / (1024 * 1024)).toFixed(1)} MB`;
    if (numeric >= 1024) return `${Math.round(numeric / 1024)} KB`;
    return `${Math.round(numeric)} B`;
}

function perfAtlasAuditProgressState(audit) {
    const auditId = typeof audit === 'string' ? audit : audit?.id;
    const localStatus = String((typeof audit === 'object' && audit?.status) || '').trim().toLowerCase();
    const resolvedStatus = perfAtlasKnownAuditStatus(auditId);
    const currentStatus = perfAtlasIsTerminalStatus(resolvedStatus)
        ? resolvedStatus
        : (localStatus || resolvedStatus);
    if (perfAtlasIsTerminalStatus(currentStatus)) {
        return null;
    }
    const liveJob = auditId ? activePerfAtlasJobForAudit(auditId) : null;
    if (liveJob) {
        return {
            job: liveJob,
            auditId,
            status: String(liveJob.status || 'running').toLowerCase(),
            phase: perfAtlasJobPhaseLabel(liveJob.phase || liveJob.status),
            progress: signalAtlasJobProgress(liveJob),
            message: perfAtlasJobMessage(liveJob),
        };
    }
    if (currentStatus === 'running' || currentStatus === 'queued') {
        const fallbackJob = perfAtlasFallbackJobForAudit(audit, currentStatus);
        return {
            job: fallbackJob,
            auditId,
            status: currentStatus,
            phase: perfAtlasJobPhaseLabel(currentStatus),
            progress: currentStatus === 'running' ? 8 : 2,
            message: currentStatus === 'running'
                ? moduleT('perfatlas.auditRunning', 'Audit running...')
                : moduleT('perfatlas.phaseQueued', 'Queued'),
        };
    }
    return null;
}

function perfAtlasAnyProgressState() {
    const current = perfAtlasCurrentAudit ? perfAtlasAuditProgressState(perfAtlasCurrentAudit) : null;
    if (current) return current;
    for (const audit of perfAtlasAudits) {
        const state = perfAtlasAuditProgressState(audit);
        if (state) return state;
    }
    const fallbackJob = activePerfAtlasJobs()[0] || null;
    if (fallbackJob) {
        return {
            job: fallbackJob,
            auditId: fallbackJob?.metadata?.audit_id || null,
            status: String(fallbackJob.status || 'running').toLowerCase(),
            phase: perfAtlasJobPhaseLabel(fallbackJob.phase || fallbackJob.status),
            progress: signalAtlasJobProgress(fallbackJob),
            message: perfAtlasJobMessage(fallbackJob),
        };
    }
    return null;
}

function describeSignalAtlasModel(profile) {
    const provider = String(profile?.provider || 'ollama').toLowerCase();
    const isCloud = provider !== 'ollama';
    return {
        label: profile?.label || profile?.display_name || profile?.name || profile?.id || 'Modèle',
        privacy: isCloud
            ? moduleT('signalatlas.privacyCloud', 'Traitement cloud')
            : moduleT('signalatlas.privacyLocal', 'Traitement local'),
        time: isCloud
            ? moduleT('signalatlas.timeCloud', 'Rapide, dépend de la latence provider')
            : moduleT('signalatlas.timeLocal', 'Dépend du matériel local'),
        cost: isCloud
            ? moduleT('signalatlas.costCloud', 'Coût provider/API possible')
            : moduleT('signalatlas.costLocal', 'Aucun coût API'),
        capability: isCloud
            ? moduleT('signalatlas.capabilityCloud', 'Idéal pour les synthèses profondes et les longs rapports')
            : moduleT('signalatlas.capabilityLocal', 'Idéal pour une interprétation privée et des flux 100 % locaux'),
    };
}

function fallbackAuditCompareModel(profiles, currentModel) {
    const alternative = (profiles || []).find(profile => profile.id !== currentModel && profile.configured !== false);
    return alternative?.id || currentModel;
}

function fallbackSignalAtlasCompareModel() {
    const profiles = signalAtlasCurrentProfiles();
    const current = signalAtlasDraft.model || currentJoyBoyChatModel();
    return fallbackAuditCompareModel(profiles, current);
}

function fallbackPerfAtlasCompareModel() {
    const profiles = perfAtlasCurrentProfiles();
    const current = perfAtlasDraft.model || currentJoyBoyChatModel();
    return fallbackAuditCompareModel(profiles, current);
}

function signalAtlasModelOptionsHtml(selectedValue) {
    const profiles = signalAtlasCurrentProfiles();
    const local = profiles.filter(profile => String(profile.provider || 'ollama').toLowerCase() === 'ollama');
    const cloud = profiles.filter(profile => String(profile.provider || 'ollama').toLowerCase() !== 'ollama');
    const renderOption = (profile) => {
        const description = describeSignalAtlasModel(profile);
        const configured = profile.configured === false
            ? ` - ${moduleT('signalatlas.modelNotConfigured', 'not configured')}`
            : '';
        return `<option value="${escapeHtml(profile.id)}" ${profile.id === selectedValue ? 'selected' : ''}>${escapeHtml(description.label + configured)}</option>`;
    };

    let html = '';
    if (local.length) {
        html += `<optgroup label="${escapeHtml(moduleT('signalatlas.localModels', 'Local models'))}">${local.map(renderOption).join('')}</optgroup>`;
    }
    if (cloud.length) {
        html += `<optgroup label="${escapeHtml(moduleT('signalatlas.cloudModels', 'Cloud models'))}">${cloud.map(renderOption).join('')}</optgroup>`;
    }
    return html;
}

function moduleHubOutcome(moduleId) {
    if (moduleId === 'perfatlas') {
        return moduleT('modules.module_perfatlas_outcome', 'Mesure vitesse, Core Web Vitals et pistes de correction.');
    }
    if (moduleId === 'cyberatlas') {
        return moduleT('modules.module_cyberatlas_outcome', 'Cartographie TLS, headers, exposition publique et surface API.');
    }
    if (moduleId === 'deployatlas') {
        return moduleT('modules.module_deployatlas_outcome', 'Analyse projet, SSH, HTTPS et runbook de déploiement.');
    }
    return moduleT('modules.module_signalatlas_outcome', 'Analyse crawl, indexation et visibilité SEO.');
}

function moduleHubPoints(moduleId) {
    if (moduleId === 'perfatlas') {
        return [
            moduleT('modules.module_perfatlas_point_1', 'Sondes lab sur pages représentatives'),
            moduleT('modules.module_perfatlas_point_2', 'Plan de correction performance exportable'),
        ];
    }
    if (moduleId === 'cyberatlas') {
        return [
            moduleT('modules.module_cyberatlas_point_1', 'Preuves sécurité défensives et score de posture'),
            moduleT('modules.module_cyberatlas_point_2', 'Pack de remédiation prêt pour dev ou IA'),
        ];
    }
    if (moduleId === 'deployatlas') {
        return [
            moduleT('modules.module_deployatlas_point_1', 'Serveurs VPS enregistrés avec fingerprint SSH'),
            moduleT('modules.module_deployatlas_point_2', 'Terminal visuel, HTTPS et rollback guidé'),
        ];
    }
    return [
        moduleT('modules.module_signalatlas_point_1', 'Crawl technique et indexabilité'),
        moduleT('modules.module_signalatlas_point_2', 'Brief SEO prêt pour dev ou IA'),
    ];
}

function renderModulesHub() {
    const host = document.getElementById('modules-view-content');
    if (!host) return;
    const cards = joyboyModulesCatalog.map(module => {
        const moduleId = auditTranslationKey(module?.id || '');
        const activeJobs = activeAuditModuleJobs(module?.id || '');
        const featuredJob = activeJobs[0] || null;
        const isLocked = module.available === false || module.backend_ready === false;
        const status = isLocked
            ? moduleT('modules.restartRequiredShort', 'Restart required')
            : activeJobs.length
            ? signalAtlasStatusLabel(featuredJob?.status || 'running')
            : signalAtlasStatusLabel(module.status);
        const name = moduleT(`modules.module_${moduleId}_name`, module.name || 'Module');
        const tagline = moduleT(`modules.module_${moduleId}_tagline`, module.tagline || '');
        const lockedReason = module.locked_reason ? `<div class="modules-card-note">${escapeHtml(module.locked_reason)}</div>` : '';
        const outcome = moduleHubOutcome(moduleId);
        const points = moduleHubPoints(moduleId);
        const statusChip = isLocked || activeJobs.length ? `
            <div class="modules-card-status status-${escapeHtml(String(module.status || 'active').toLowerCase())}">${escapeHtml(status)}</div>
        ` : '';
        const runtimeNote = activeJobs.length ? `
            <div class="modules-card-runtime">
                <div class="modules-card-runtime-copy">${escapeHtml(moduleT('signalatlas.moduleRuntimeCount', '{count} active audit(s)', { count: activeJobs.length }))}</div>
                <div class="modules-card-runtime-message">${escapeHtml(signalAtlasJobMessage(featuredJob))}</div>
                <div class="modules-card-runtime-bar"><div class="modules-card-runtime-fill" style="width:${escapeHtml(String(signalAtlasJobProgress(featuredJob)))}%"></div></div>
            </div>
        ` : '';
        return `
            <button
                class="modules-card modules-card-${escapeHtml(moduleId)}${module.featured ? ' featured' : ''}${isLocked ? ' is-locked' : ''}"
                type="button"
                onclick="openNativeModule('${escapeHtml(module.id)}')"
                ${isLocked ? 'disabled' : ''}
            >
                <div class="modules-card-main">
                    <div class="modules-card-icon"><i data-lucide="${escapeHtml(module.icon || 'blocks')}"></i></div>
                    <div class="modules-card-copy">
                        <div class="modules-card-title">${escapeHtml(name)}</div>
                        <div class="modules-card-tagline">${escapeHtml(tagline)}</div>
                    </div>
                    ${statusChip}
                </div>
                <div class="modules-card-outcome">${escapeHtml(outcome)}</div>
                <div class="modules-card-points">
                    ${points.map(point => `
                        <div class="modules-card-point">
                            <i data-lucide="check"></i>
                            <span>${escapeHtml(point)}</span>
                        </div>
                    `).join('')}
                </div>
                <div class="modules-card-action">
                    <span>${escapeHtml(moduleT('modules.openModule', 'Ouvrir'))}</span>
                    <i data-lucide="arrow-right"></i>
                </div>
                ${runtimeNote}
                ${lockedReason}
            </button>
        `;
    }).join('');

    host.innerHTML = `
        <div class="modules-shell">
            <section class="modules-hero">
                <div class="modules-kicker">${escapeHtml(moduleT('modules.kicker', 'Native modules'))}</div>
                <h1 class="modules-title">${escapeHtml(moduleT('modules.title', 'Expert workspaces inside JoyBoy'))}</h1>
                <p class="modules-description">${escapeHtml(moduleT('modules.description', 'Launch integrated products built on JoyBoy’s local/cloud orchestration, routing, and runtime infrastructure.'))}</p>
            </section>
            <section class="modules-grid">
                ${cards || `<div class="modules-empty">${escapeHtml(moduleT('modules.empty', 'No module is available yet.'))}</div>`}
            </section>
        </div>
    `;
    if (window.lucide) lucide.createIcons({ nodes: [host] });
}

function renderSignalAtlasHistory() {
    if (!signalAtlasAudits.length) {
        return `<div class="signalatlas-history-empty">${escapeHtml(moduleT('signalatlas.noAudits', 'Aucun audit pour le moment. Lance-en un pour créer ton premier rapport déterministe.'))}</div>`;
    }
    return signalAtlasAudits.map(audit => {
        const active = audit.id === signalAtlasCurrentAuditId;
        const score = audit.global_score ?? '--';
        const progressState = signalAtlasAuditProgressState(audit);
        const canDelete = !progressState;
        const isLive = signalAtlasIsLiveProgressStatus(progressState?.status || '');
        const displayProgress = progressState ? auditDisplayProgress('signalatlas', progressState, audit, false) : 0;
        const supportCopy = progressState ? signalAtlasProgressSupportCopy(progressState) : '';
        const auditTimestamp = nativeAuditTimestampLabel('signalatlas', audit);
        return `
            <div
                class="signalatlas-history-card${active ? ' active' : ''}"
                role="button"
                tabindex="0"
                onclick="openSignalAtlasWorkspace('${escapeHtml(audit.id)}')"
                onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openSignalAtlasWorkspace('${escapeHtml(audit.id)}');}"
            >
                <div class="signalatlas-history-top">
                    <div class="signalatlas-history-title-wrap">
                        <div class="signalatlas-history-title">${escapeHtml(audit.title || audit.host || audit.target_url || 'Audit')}</div>
                        <div class="signalatlas-history-status">${escapeHtml(signalAtlasStatusLabel(audit.status))}</div>
                    </div>
                    <button
                        class="signalatlas-history-delete"
                        type="button"
                        onclick="deleteSignalAtlasAudit('${escapeHtml(audit.id)}', event)"
                        aria-label="${escapeHtml(canDelete
                            ? moduleT('signalatlas.deleteAudit', 'Supprimer l’audit')
                            : moduleT('signalatlas.deleteAuditBlocked', 'Annule cet audit avant de le supprimer'))}"
                        title="${escapeHtml(canDelete
                            ? moduleT('signalatlas.deleteAudit', 'Supprimer l’audit')
                            : moduleT('signalatlas.deleteAuditBlocked', 'Annule cet audit avant de le supprimer'))}"
                        ${canDelete ? '' : 'disabled'}
                    >
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
                <div class="signalatlas-history-meta">
                    <span>${escapeHtml(audit.host || '')}</span>
                    <span>${escapeHtml(signalAtlasModeLabel(audit.mode || 'public'))}</span>
                </div>
                ${auditTimestamp ? `<div class="signalatlas-history-timestamp">${escapeHtml(auditTimestamp)}</div>` : ''}
                ${audit.report_model_label ? `
                    <div class="signalatlas-history-model">
                        <span class="signalatlas-history-model-label">${escapeHtml(audit.report_model_state === 'planned'
                            ? moduleT('signalatlas.requestedModelLabel', 'Modèle demandé')
                            : moduleT('signalatlas.reportModelLabel', 'Modèle du rapport'))}</span>
                        <span class="signalatlas-history-model-value">${escapeHtml(audit.report_model_label)}</span>
                    </div>
                ` : ''}
                <div class="signalatlas-history-footer">
                    <span>${escapeHtml(moduleT('signalatlas.scoreLabel', 'Score'))}: ${escapeHtml(String(score))}</span>
                    <span>${escapeHtml(String(audit.pages_crawled || 0))} ${escapeHtml(moduleT('signalatlas.pagesShort', 'pages'))}</span>
                </div>
                ${progressState ? `
                    <div class="signalatlas-history-progress-meta">
                        <span class="signalatlas-progress-chip is-phase">${escapeHtml(progressState.phase)}</span>
                        <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT('signalatlas.progressPercent', '{value}%', { value: displayProgress }))}</span>
                    </div>
                    <div class="signalatlas-history-progress-bar${isLive ? ' is-live' : ''}">
                        <div class="signalatlas-history-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(displayProgress))}%"></div>
                    </div>
                    <div class="signalatlas-history-progress-copy${isLive ? ' signalatlas-shimmer-text' : ''}" aria-live="polite">${escapeHtml(progressState.message)}</div>
                    <div class="signalatlas-history-progress-detail">${escapeHtml(supportCopy)}</div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function renderSignalAtlasScoreCards(audit) {
    const scores = Array.isArray(audit?.scores) ? audit.scores : [];
    return scores.map(score => `
        <div class="signalatlas-score-card ${signalAtlasScoreTone(score.score)}">
            <div class="signalatlas-score-label">${escapeHtml(signalAtlasScoreLabel(score))}</div>
            <div class="signalatlas-score-value">${escapeHtml(String(score.score ?? '--'))}</div>
            <div class="signalatlas-score-meta">${escapeHtml(signalAtlasConfidenceLabel(score.confidence || ''))}</div>
        </div>
    `).join('');
}

function renderSignalAtlasOverview(audit) {
    const facts = signalAtlasOverviewFacts(audit);
    const priorities = signalAtlasPriorityFindings(audit);
    return `
        <div class="signalatlas-overview-stack">
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.quickRead', 'Lecture rapide'))}</div>
                    <ul class="signalatlas-notes-list">
                        ${facts.map(note => `<li>${escapeHtml(note)}</li>`).join('')}
                    </ul>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.priorityFixes', 'À corriger d’abord'))}</div>
                    ${priorities.length ? priorities.map(item => `
                        <div class="signalatlas-mini-finding">
                            <div class="signalatlas-mini-finding-head">
                                <div class="signalatlas-mini-finding-title">${escapeHtml(signalAtlasFindingTitle(item))}</div>
                                <span class="signalatlas-tag ${signalAtlasSeverityTone(item.severity)}">${escapeHtml(signalAtlasSeverityLabel(item.severity || ''))}</span>
                            </div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(signalAtlasFindingSummary(item))}</div>
                        </div>
                    `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.priorityFixesEmpty', 'Aucun problème prioritaire ne ressort pour l’instant sur cette passe.'))}</div>`}
                </section>
            </div>
            ${renderSignalAtlasSerpPreview(audit, { compact: true })}
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.scoreBreakdown', 'Décomposition du score'))}</div>
                <div class="signalatlas-score-grid">
                    ${renderSignalAtlasScoreCards(audit)}
                </div>
            </section>
        </div>
    `;
}

function renderSignalAtlasTechnical(audit) {
    const findings = Array.isArray(audit?.findings) ? audit.findings : [];
    if (!findings.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noFindings', 'Aucun finding pour cet audit.'))}</div>`;
    }
    return findings.map(item => `
        <article class="signalatlas-finding-card">
            <div class="signalatlas-finding-top">
                <div>
                    <div class="signalatlas-finding-title">${escapeHtml(signalAtlasFindingTitle(item))}</div>
                    <div class="signalatlas-finding-meta">${escapeHtml(item.category || '')}</div>
                </div>
                <div class="signalatlas-finding-tags">
                    <span class="signalatlas-tag ${signalAtlasSeverityTone(item.severity)}">${escapeHtml(signalAtlasSeverityLabel(item.severity || ''))}</span>
                    <span class="signalatlas-tag">${escapeHtml(signalAtlasConfidenceLabel(item.confidence || ''))}</span>
                </div>
            </div>
            <div class="signalatlas-finding-url">${escapeHtml(item.url || item.scope || '')}</div>
            <p class="signalatlas-finding-copy">${escapeHtml(signalAtlasFindingSummary(item))}</p>
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.probableCause', 'Cause probable'))}:</strong> ${escapeHtml(item.probable_cause || '')}</div>
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.recommendedFix', 'Correctif recommandé'))}:</strong> ${escapeHtml(signalAtlasFindingSummary(item))}</div>
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.acceptance', 'Critère d’acceptation'))}:</strong> ${escapeHtml(item.acceptance_criteria || '')}</div>
        </article>
    `).join('');
}

function renderSignalAtlasCrawl(audit) {
    const snapshot = audit?.snapshot || {};
    const robots = snapshot.robots || {};
    const sitemaps = snapshot.sitemaps || {};
    const visibility = snapshot.visibility_signals || {};
    const renderDetection = snapshot.render_detection || {};
    return `
        <div class="signalatlas-detail-grid">
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.crawlLayer', 'Couche crawl'))}</div>
                <div class="signalatlas-metric-row"><span>robots.txt</span><strong>${escapeHtml(robots.found ? moduleT('signalatlas.confirmed', 'Confirmé') : moduleT('signalatlas.unknown', 'Inconnu'))}</strong></div>
                <div class="signalatlas-metric-row"><span>Sitemap</span><strong>${escapeHtml(sitemaps.found ? moduleT('signalatlas.strongSignal', 'Signal fort') : moduleT('signalatlas.estimated', 'Estimé'))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.pagesSampled', 'Pages échantillonnées'))}</span><strong>${escapeHtml(String(snapshot.page_count || 0))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.renderingProbe', 'Sonde de rendu JS'))}</span><strong>${escapeHtml(renderDetection.render_js_executed ? moduleT('signalatlas.confirmed', 'Confirmé') : signalAtlasProviderStatusLabel(renderDetection.reason || 'not_configured'))}</strong></div>
                <div class="signalatlas-visibility-note">${escapeHtml(signalAtlasRenderSummary(renderDetection))}</div>
            </section>
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.visibilityLayer', 'Couche visibilité'))}</div>
                ${Object.entries(visibility).map(([key, value]) => `
                    <div class="signalatlas-visibility-row">
                        <div>
                            <div class="signalatlas-visibility-name">${escapeHtml(signalAtlasVisibilityLabel(key))}</div>
                            <div class="signalatlas-visibility-note">${escapeHtml(signalAtlasVisibilityNote(key, value, audit))}</div>
                        </div>
                        <div class="signalatlas-visibility-confidence">${escapeHtml(signalAtlasVisibilityStatusLabel(key, value))}</div>
                    </div>
                `).join('')}
            </section>
        </div>
    `;
}

function renderSignalAtlasVisibility(audit) {
    const snapshot = audit?.snapshot || {};
    const visibility = snapshot.visibility_signals || {};
    const ownerIntegrations = Array.isArray(audit?.owner_context?.integrations) ? audit.owner_context.integrations : [];
    return `
        <div class="signalatlas-detail-grid">
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.visibilityLayer', 'Lecture moteurs'))}</div>
                ${Object.entries(visibility).map(([key, value]) => `
                    <div class="signalatlas-visibility-row">
                        <div>
                            <div class="signalatlas-visibility-name">${escapeHtml(signalAtlasVisibilityLabel(key))}</div>
                            <div class="signalatlas-visibility-note">${escapeHtml(signalAtlasVisibilityNote(key, value, audit))}</div>
                        </div>
                        <div class="signalatlas-visibility-confidence">${escapeHtml(signalAtlasVisibilityStatusLabel(key, value))}</div>
                    </div>
                `).join('')}
                ${ownerIntegrations.length ? `
                    <div class="signalatlas-owner-inline">
                        <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.ownerEvidence', 'Sources officielles'))}</div>
                        ${ownerIntegrations.map(item => `
                            <div class="signalatlas-owner-evidence-row">
                                <div>
                                    <div class="signalatlas-visibility-name">${escapeHtml(item.site_url || item.id || '')}</div>
                                    <div class="signalatlas-visibility-note">${escapeHtml(signalAtlasProviderSummary(item))}</div>
                                </div>
                                <div class="signalatlas-visibility-confidence">${escapeHtml(signalAtlasProviderStatusLabel(item.status))}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </section>
            ${renderSignalAtlasSerpPreview(audit)}
        </div>
    `;
}

function renderSignalAtlasPages(audit) {
    const pages = Array.isArray(audit?.snapshot?.pages) ? audit.snapshot.pages : [];
    if (!pages.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noPages', 'Aucune page échantillonnée pour le moment.'))}</div>`;
    }
    return `
        <div class="signalatlas-table-wrap">
            <table class="signalatlas-table">
                <thead>
                    <tr>
                        <th>${escapeHtml(moduleT('signalatlas.page', 'Page'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.status', 'Statut'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.words', 'Mots'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.rendering', 'Rendu'))}</th>
                    </tr>
                </thead>
                <tbody>
                    ${pages.map(page => `
                        <tr>
                            <td>
                                <div class="signalatlas-table-title">${escapeHtml(page.title || page.final_url || page.url || '')}</div>
                                <div class="signalatlas-table-subtitle">${escapeHtml(page.final_url || page.url || '')}</div>
                            </td>
                            <td>${escapeHtml(String(page.status_code || '--'))}</td>
                            <td>${escapeHtml(String(page.word_count || 0))}</td>
                            <td>${escapeHtml(page.shell_like ? moduleT('signalatlas.jsRisk', 'Risque JS') : moduleT('signalatlas.serverReady', 'Prêt côté serveur'))}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderSignalAtlasTemplates(audit) {
    const templates = Array.isArray(audit?.snapshot?.template_clusters) ? audit.snapshot.template_clusters : [];
    if (!templates.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noTemplates', 'Aucun cluster de template pour le moment.'))}</div>`;
    }
    return templates.map(template => `
        <article class="signalatlas-template-card">
            <div class="signalatlas-template-top">
                <div class="signalatlas-template-signature">${escapeHtml(template.signature || '/')}</div>
                <div class="signalatlas-inline-chip">${escapeHtml(moduleT('signalatlas.templatePages', '{count} page(s)', { count: template.count || 0 }))}</div>
            </div>
            <div class="signalatlas-template-meta">${escapeHtml(moduleT('signalatlas.avgContentUnits', 'Unités de contenu moyennes : {count}', { count: template.avg_content_units || template.avg_word_count || 0 }))}</div>
            <div class="signalatlas-template-samples">
                ${(template.sample_urls || []).map(url => `<span class="signalatlas-inline-chip">${escapeHtml(url)}</span>`).join('')}
            </div>
        </article>
    `).join('');
}

function renderSignalAtlasContent(audit) {
    const summary = audit?.summary || {};
    const contentFindings = (audit?.findings || []).filter(item => {
        const bucket = String(item.bucket || '');
        return bucket === 'content_depth_blog' || bucket === 'architecture_linking';
    });
    return `
        <div class="signalatlas-detail-grid">
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.contentSignals', 'Signaux contenu & blog'))}</div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.blogDetected', 'Blog détecté'))}</span><strong>${escapeHtml(summary.blog_detected ? moduleT('common.ready', 'PRÊT') : moduleT('signalatlas.no', 'Non'))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.topRisk', 'Risque principal'))}</span><strong>${escapeHtml(signalAtlasRiskLabel(summary.top_risk || '--'))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.platform', 'Plateforme'))}</span><strong>${escapeHtml(summary.platform || '--')}</strong></div>
            </section>
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.contentFindings', 'Findings contenu'))}</div>
                ${(contentFindings.length ? contentFindings : [{ title: moduleT('signalatlas.noneDetected', 'Aucun problème contenu spécifique détecté pour l’instant.'), diagnostic: '' }]).map(item => `
                    <div class="signalatlas-mini-finding">
                        <div class="signalatlas-mini-finding-title">${escapeHtml(item.title || '')}</div>
                        <div class="signalatlas-mini-finding-copy">${escapeHtml(item.diagnostic || '')}</div>
                    </div>
                `).join('')}
            </section>
        </div>
    `;
}

function renderSignalAtlasAiTab(audit) {
    const interpretations = Array.isArray(audit?.interpretations) ? audit.interpretations : [];
    return `
        <div class="signalatlas-ai-grid">
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.aiControls', 'Interprétation IA'))}</div>
                <div class="signalatlas-control-stack">
                    <div class="signalatlas-ai-note">${escapeHtml(moduleT('signalatlas.aiControlsHint', 'Utilise les contrôles du haut pour garder le modèle JoyBoy, le preset et le niveau IA synchronisés avec cet audit.'))}</div>
                    <div class="signalatlas-actions">
                        <button class="signalatlas-btn" type="button" onclick="rerunSignalAtlasAi()">${escapeHtml(moduleT('signalatlas.rerunAi', 'Relancer l’IA seule'))}</button>
                    </div>
                </div>
                <div class="signalatlas-compare-box">
                    <div class="signalatlas-field">
                        <label>${escapeHtml(moduleT('signalatlas.compareModelLabel', 'Comparer avec'))}</label>
                        ${renderSignalAtlasPicker('compare_model', 'signalatlas-compare-model-select', signalAtlasPickerOptions('compare_model'), signalAtlasDraft.compare_model || fallbackSignalAtlasCompareModel())}
                    </div>
                    <button class="signalatlas-btn secondary" type="button" onclick="compareSignalAtlasAi()">${escapeHtml(moduleT('signalatlas.compareAi', 'Comparer les interprétations'))}</button>
                </div>
            </section>
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.interpretations', 'Interprétations'))}</div>
                ${interpretations.length ? interpretations.slice().reverse().map(item => `
                    <article class="signalatlas-interpretation-card">
                        <div class="signalatlas-interpretation-top">
                            <div>
                                <div class="signalatlas-interpretation-model">${escapeHtml(item.model || '')}</div>
                                <div class="signalatlas-interpretation-meta">${escapeHtml(item.level || '')} · ${escapeHtml(item.preset || '')}</div>
                            </div>
                            <div class="signalatlas-inline-chip">${escapeHtml(item.mode || '')}</div>
                        </div>
                        <div class="signalatlas-markdown-lite">${escapeHtml(item.content || '')}</div>
                    </article>
                `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noInterpretations', 'Aucune interprétation IA pour le moment.'))}</div>`}
            </section>
        </div>
    `;
}

function renderSignalAtlasExports(audit) {
    if (!audit?.id) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noAuditSelected', 'Sélectionne un audit pour l’exporter.'))}</div>`;
    }
    return `
        <div class="signalatlas-export-grid">
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'json')">
                <div class="signalatlas-export-title">JSON</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportJson', 'Structured machine-readable export.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'markdown')">
                <div class="signalatlas-export-title">Markdown</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportMarkdown', 'Rapport lisible pour humain ou outil IA.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'prompt')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.promptForAiFix', 'Prompt pour correction IA'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportPrompt', 'Handoff direct pour un modèle dev/contenu/SEO.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'remediation')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.remediationPack', 'AI remediation pack'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportRemediation', 'Tous les findings avec prompts et critères d’acceptation.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'pdf')">
                <div class="signalatlas-export-title">PDF</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportPdf', 'PDF premium rendu à partir du même modèle de rapport.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="openSignalAtlasPromptInChat('${escapeHtml(audit.id)}')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.openInChat', 'Open in JoyBoy chat'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportToChat', 'Injecter le prompt d’audit dans une conversation JoyBoy classique.'))}</div>
            </button>
        </div>
    `;
}

function signalAtlasOrganicFormatNumber(value, maximumFractionDigits = 0) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '0';
    try {
        return new Intl.NumberFormat(nativeAuditLocale(), { maximumFractionDigits }).format(numeric);
    } catch (error) {
        return maximumFractionDigits > 0 ? numeric.toFixed(maximumFractionDigits) : String(Math.round(numeric));
    }
}

function signalAtlasOrganicFormatPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '0%';
    try {
        return new Intl.NumberFormat(nativeAuditLocale(), {
            style: 'percent',
            minimumFractionDigits: 1,
            maximumFractionDigits: 2,
        }).format(numeric);
    } catch (error) {
        return `${(numeric * 100).toFixed(1)}%`;
    }
}

function signalAtlasOrganicOpportunityLabel(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'quick_win') return moduleT('signalatlas.organicTypeQuickWin', 'Gain rapide');
    if (clean === 'ctr_gap') return moduleT('signalatlas.organicTypeCtrGap', 'CTR à corriger');
    if (clean === 'ranking_distance') return moduleT('signalatlas.organicTypeRankingDistance', 'Distance de classement');
    if (clean === 'content_gap') return moduleT('signalatlas.organicTypeContentGap', 'Manque contenu');
    if (clean === 'low_value') return moduleT('signalatlas.organicTypeLowValue', 'Faible priorité');
    if (clean === 'brand_query') return moduleT('signalatlas.organicTypeBrandQuery', 'Marque');
    if (clean === 'non_brand_query') return moduleT('signalatlas.organicTypeNonBrandQuery', 'Hors marque');
    return value || moduleT('signalatlas.statusUnknown', 'Inconnu');
}

function signalAtlasOrganicCanImport(audit) {
    return ['done', 'completed', 'ready'].includes(String(audit?.status || '').trim().toLowerCase());
}

function signalAtlasSafeDomId(value) {
    return String(value || 'audit').trim().replace(/[^a-z0-9_-]+/gi, '-') || 'audit';
}

function renderSignalAtlasOrganicImportControl(audit, compact = false, placement = 'default') {
    const canImport = signalAtlasOrganicCanImport(audit);
    const auditId = String(audit?.id || '');
    const inputId = `signalatlas-organic-files-${signalAtlasSafeDomId(auditId)}-${signalAtlasSafeDomId(placement)}`;
    return `
        <div class="signalatlas-organic-import">
            <input id="${escapeHtml(inputId)}" type="file" accept=".csv,.zip,text/csv,application/zip" multiple hidden onchange="importSignalAtlasOrganicPotential('${escapeHtml(auditId)}', this)">
            <button class="signalatlas-btn secondary" type="button" onclick="document.getElementById('${escapeHtml(inputId)}')?.click()" ${canImport ? '' : 'disabled'}>
                ${escapeHtml(compact ? moduleT('signalatlas.organicReimportButton', 'Réimporter GSC') : moduleT('signalatlas.organicImportButton', 'Importer GSC / Analyser le potentiel'))}
            </button>
            <div class="signalatlas-visibility-note">${escapeHtml(canImport
                ? moduleT('signalatlas.organicImportHint', 'Accepte les CSV GSC ou un ZIP qui contient Chart, Pages, Queries, Devices, Countries, Search appearance et Filters.')
                : moduleT('signalatlas.organicImportBlocked', 'Termine d’abord l’audit SignalAtlas, puis importe les exports Search Console.'))}</div>
        </div>
    `;
}

function renderSignalAtlasOrganicMainCta(audit) {
    if (!audit?.id || !signalAtlasOrganicCanImport(audit)) return '';
    const organicReady = !!audit.organic_potential;
    return `
        <section class="signalatlas-panel signalatlas-organic-main-cta${organicReady ? ' is-ready' : ''}">
            <div class="signalatlas-organic-main-copy">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicMainCtaKicker', 'Données Google réelles'))}</div>
                <div class="signalatlas-panel-title">${escapeHtml(organicReady
                    ? moduleT('signalatlas.organicMainReadyTitle', 'Potentiel organique prêt')
                    : moduleT('signalatlas.organicMainCtaTitle', 'Ajoute les CSV Google Search Console'))}</div>
                <p class="signalatlas-panel-copy">${escapeHtml(organicReady
                    ? moduleT('signalatlas.organicMainReadyCopy', 'Les données GSC sont déjà croisées avec cet audit. Tu peux consulter le potentiel organique ou réimporter un export plus récent.')
                    : moduleT('signalatlas.organicMainCtaCopy', 'Importe les CSV GSC séparés ou un ZIP qui les contient pour transformer ce crawl en plan SEO basé sur les vraies impressions, clics, CTR et positions.'))}</p>
            </div>
            <div class="signalatlas-organic-main-actions">
                ${renderSignalAtlasOrganicImportControl(audit, organicReady, 'main-cta')}
                ${organicReady ? `<button class="signalatlas-btn secondary" type="button" onclick="setSignalAtlasTab('organic')">${escapeHtml(moduleT('signalatlas.organicOpenTab', 'Voir le potentiel'))}</button>` : ''}
            </div>
        </section>
    `;
}

function renderSignalAtlasOrganicPotential(audit) {
    if (!audit?.id) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noAuditSelected', 'Sélectionne un audit pour l’enrichir.'))}</div>`;
    }
    const organic = audit.organic_potential || null;
    if (!organic) {
        return `
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicPotentialKicker', 'Données réelles Google'))}</div>
                <div class="signalatlas-panel-title">${escapeHtml(moduleT('signalatlas.organicPotentialTitle', 'Potentiel organique'))}</div>
                <p class="signalatlas-panel-copy">${escapeHtml(moduleT('signalatlas.organicPotentialEmptyCopy', 'Importe les CSV Google Search Console pour transformer le crawl SignalAtlas en plan de croissance: pages prioritaires, requêtes à pousser, CTR anormal, clics manqués et cannibalisation probable.'))}</p>
                ${renderSignalAtlasOrganicImportControl(audit, false, 'organic-empty')}
            </section>
        `;
    }

    const summary = organic.summary || {};
    const opportunities = Array.isArray(organic.opportunities) ? organic.opportunities : [];
    const pages = Array.isArray(organic.pages) ? organic.pages : [];
    const queries = Array.isArray(organic.queries) ? organic.queries : [];
    const cannibalization = Array.isArray(organic.cannibalization_candidates) ? organic.cannibalization_candidates : [];
    const sourceFiles = Array.isArray(organic.source_files) ? organic.source_files : [];
    const cardItems = [
        [moduleT('signalatlas.organicClicks', 'Clics'), signalAtlasOrganicFormatNumber(summary.clicks), moduleT('signalatlas.organicConfirmed', 'Confirmé GSC')],
        [moduleT('signalatlas.organicImpressions', 'Impressions'), signalAtlasOrganicFormatNumber(summary.impressions), moduleT('signalatlas.organicConfirmed', 'Confirmé GSC')],
        ['CTR', signalAtlasOrganicFormatPercent(summary.ctr), moduleT('signalatlas.organicCtrMeta', 'Clics / impressions')],
        [moduleT('signalatlas.organicPosition', 'Position'), signalAtlasOrganicFormatNumber(summary.average_position, 2), moduleT('signalatlas.organicWeighted', 'Pondérée impressions')],
        [moduleT('signalatlas.organicMissedClicks', 'Clics manqués'), signalAtlasOrganicFormatNumber(summary.missed_clicks, 1), moduleT('signalatlas.organicEstimated', 'Estimé par CTR attendu')],
        [moduleT('signalatlas.organicOpportunities', 'Opportunités'), signalAtlasOrganicFormatNumber(summary.opportunity_count), moduleT('signalatlas.organicPriorityRows', 'Lignes prioritaires')],
    ];

    return `
        <div class="signalatlas-overview-stack">
            <section class="signalatlas-panel">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicPotentialKicker', 'Données réelles Google'))}</div>
                        <div class="signalatlas-panel-title">${escapeHtml(moduleT('signalatlas.organicPotentialTitle', 'Potentiel organique'))}</div>
                        <p class="signalatlas-panel-copy">${escapeHtml(moduleT('signalatlas.organicPotentialReadyCopy', 'Analyse basée sur les exports GSC importés localement. Les rapprochements page/requête restent marqués inferred quand les CSV sont séparés.'))}</p>
                    </div>
                    ${renderSignalAtlasOrganicImportControl(audit, true, 'organic-ready')}
                </div>
                <div class="signalatlas-score-grid">
                    ${cardItems.map(([label, value, meta]) => `
                        <div class="signalatlas-score-card">
                            <div class="signalatlas-score-label">${escapeHtml(label)}</div>
                            <div class="signalatlas-score-value">${escapeHtml(String(value))}</div>
                            <div class="signalatlas-score-meta">${escapeHtml(meta)}</div>
                        </div>
                    `).join('')}
                </div>
                <div class="signalatlas-visibility-note">
                    ${escapeHtml(moduleT('signalatlas.organicMappingMode', 'Mode mapping'))}: ${escapeHtml(organic.mapping_mode || 'separate_gsc_exports')}
                    ${sourceFiles.length ? ` · ${escapeHtml(sourceFiles.filter(item => item.accepted).map(item => item.filename).join(', '))}` : ''}
                </div>
            </section>

            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicTopOpportunities', 'Priorités growth'))}</div>
                ${opportunities.length ? `
                    <div class="signalatlas-table-wrap">
                        <table class="signalatlas-table">
                            <thead>
                                <tr>
                                    <th>${escapeHtml(moduleT('signalatlas.kind', 'Type'))}</th>
                                    <th>${escapeHtml(moduleT('signalatlas.organicTarget', 'Page / requête'))}</th>
                                    <th>${escapeHtml(moduleT('signalatlas.organicOpportunity', 'Opportunité'))}</th>
                                    <th>${escapeHtml(moduleT('signalatlas.organicPriority', 'Priorité'))}</th>
                                    <th>${escapeHtml(moduleT('signalatlas.organicMissedClicks', 'Clics manqués'))}</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${opportunities.slice(0, 20).map(item => `
                                    <tr>
                                        <td>${escapeHtml(item.kind || '')}</td>
                                        <td>
                                            <div class="signalatlas-table-title">${escapeHtml(signalAtlasTrimText(item.label || '', 96))}</div>
                                            <div class="signalatlas-table-subtitle">${escapeHtml(item.recommended_action || '')}</div>
                                        </td>
                                        <td>${escapeHtml(signalAtlasOrganicOpportunityLabel(item.opportunity_type))}</td>
                                        <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.priority_score, 1))}</td>
                                        <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.missed_clicks, 1))}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                ` : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.organicNoOpportunities', 'Aucune opportunité prioritaire détectée dans cet import.'))}</div>`}
            </section>

            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicPageTable', 'Pages à travailler'))}</div>
                    ${renderSignalAtlasOrganicRows(pages, 'page')}
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicQueryTable', 'Requêtes à pousser'))}</div>
                    ${renderSignalAtlasOrganicRows(queries, 'query')}
                </section>
            </div>

            ${cannibalization.length ? `
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.organicCannibalization', 'Cannibalisation probable'))}</div>
                    <div class="signalatlas-table-wrap">
                        <table class="signalatlas-table">
                            <thead>
                                <tr>
                                    <th>Signature</th>
                                    <th>URLs</th>
                                    <th>Impressions</th>
                                    <th>${escapeHtml(moduleT('signalatlas.organicConfidence', 'Confiance'))}</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${cannibalization.slice(0, 10).map(item => `
                                    <tr>
                                        <td>${escapeHtml(item.signature || '')}</td>
                                        <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.url_count))}</td>
                                        <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.impressions))}</td>
                                        <td>${escapeHtml(item.mapping_confidence || 'inferred')}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </section>
            ` : ''}
        </div>
    `;
}

function renderSignalAtlasOrganicRows(items, kind) {
    const rows = Array.isArray(items) ? items.slice(0, 18) : [];
    if (!rows.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.organicNoRows', 'Aucune ligne exploitable dans cet import.'))}</div>`;
    }
    return `
        <div class="signalatlas-table-wrap">
            <table class="signalatlas-table">
                <thead>
                    <tr>
                        <th>${escapeHtml(kind === 'query' ? moduleT('signalatlas.query', 'Requête') : moduleT('signalatlas.page', 'Page'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.organicClicks', 'Clics'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.organicImpressions', 'Impr.'))}</th>
                        <th>CTR</th>
                        <th>${escapeHtml(moduleT('signalatlas.organicPositionShort', 'Pos.'))}</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(item => {
                        const label = kind === 'query' ? item.query : item.url;
                        const subtitle = kind === 'query'
                            ? `${signalAtlasOrganicOpportunityLabel(item.opportunity_type)} · ${signalAtlasOrganicOpportunityLabel(item.query_family || '')} · ${item.intent || ''}`
                            : `${signalAtlasOrganicOpportunityLabel(item.opportunity_type)} · ${(item.content_flags || []).join(', ')}`;
                        return `
                            <tr>
                                <td>
                                    <div class="signalatlas-table-title">${escapeHtml(signalAtlasTrimText(label || '', 90))}</div>
                                    <div class="signalatlas-table-subtitle">${escapeHtml(signalAtlasTrimText(subtitle, 120))}</div>
                                </td>
                                <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.clicks))}</td>
                                <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.impressions))}</td>
                                <td>${escapeHtml(signalAtlasOrganicFormatPercent(item.ctr))}</td>
                                <td>${escapeHtml(signalAtlasOrganicFormatNumber(item.position, 2))}</td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderSignalAtlasTabContent(audit) {
    if (!audit) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.emptyWorkspace', 'Choisis un domaine ou un audit existant pour commencer.'))}</div>`;
    }
    switch (signalAtlasActiveTab) {
        case 'technical':
            return renderSignalAtlasTechnical(audit);
        case 'crawl':
            return renderSignalAtlasCrawl(audit);
        case 'pages':
            return renderSignalAtlasPages(audit);
        case 'templates':
            return renderSignalAtlasTemplates(audit);
        case 'content':
            return renderSignalAtlasContent(audit);
        case 'visibility':
            return renderSignalAtlasVisibility(audit);
        case 'organic':
            return renderSignalAtlasOrganicPotential(audit);
        case 'ai':
            return renderSignalAtlasAiTab(audit);
        case 'exports':
            return renderSignalAtlasExports(audit);
        default:
            return renderSignalAtlasOverview(audit);
    }
}

function renderSignalAtlasWorkspace() {
    syncSignalAtlasDraftFromDom();
    const host = document.getElementById('signalatlas-view-content');
    if (!host) return;
    const uiState = captureSignalAtlasUiState();
    const audit = signalAtlasCurrentAudit;
    const summary = audit?.summary || {};
    const progressState = signalAtlasAuditProgressState(audit) || signalAtlasAnyProgressState();
    const progressStatus = String(progressState?.status || '').toLowerCase();
    const canCancelAudit = !!progressState?.job && ['queued', 'running', 'cancelling'].includes(progressStatus);
    const targetValidation = signalAtlasValidateTarget(signalAtlasDraft.target);
    const selectedProfile = signalAtlasDraft.profile || 'elevated';
    const reportModelInfo = signalAtlasReportModelInfo(audit);
    const currentModelLabel = signalAtlasDraft.model || currentJoyBoyChatModel();
    const tabs = [
        ['technical', moduleT('signalatlas.tabTechnical', 'Technique')],
        ['crawl', moduleT('signalatlas.tabCrawl', 'Crawl & indexation')],
        ['pages', moduleT('signalatlas.tabPages', 'Pages')],
        ['templates', moduleT('signalatlas.tabTemplates', 'Templates')],
        ['content', moduleT('signalatlas.tabContent', 'Contenu & blog')],
        ['visibility', moduleT('signalatlas.tabVisibility', 'Visibilité')],
        ['organic', moduleT('signalatlas.tabOrganicPotential', 'Potentiel organique')],
        ['ai', moduleT('signalatlas.tabAi', 'AI')],
        ['exports', moduleT('signalatlas.tabExports', 'Exports')],
    ];
    if (!tabs.some(([id]) => id === signalAtlasActiveTab)) {
        signalAtlasActiveTab = 'technical';
    }

    host.innerHTML = `
        <div class="signalatlas-shell">
            <section class="signalatlas-control-surface">
                <div class="signalatlas-input-row">
                    <input id="signalatlas-target-input" class="signalatlas-target-input${targetValidation.present && !targetValidation.valid ? ' is-invalid' : ''}" type="text" value="${escapeHtml(signalAtlasDraft.target)}" placeholder="${escapeHtml(moduleT('signalatlas.targetPlaceholder', 'Exemple : https://nevomove.com/'))}" oninput="signalAtlasTargetInputChanged(event)" onblur="signalAtlasControlsChanged()" aria-invalid="${targetValidation.present && !targetValidation.valid ? 'true' : 'false'}" inputmode="url" autocapitalize="off" spellcheck="false">
                    ${canCancelAudit ? `
                        <button
                            class="signalatlas-btn launch signalatlas-stop-btn"
                            type="button"
                            onclick="cancelSignalAtlasAudit('${escapeHtml(String(progressState?.auditId || ''))}')"
                            aria-label="${escapeHtml(progressStatus === 'cancelling' ? moduleT('signalatlas.cancelling', 'Annulation...') : moduleT('signalatlas.cancelAudit', 'Annuler l’audit'))}"
                            title="${escapeHtml(progressStatus === 'cancelling' ? moduleT('signalatlas.cancelling', 'Annulation...') : moduleT('signalatlas.cancelAudit', 'Annuler l’audit'))}"
                            ${progressStatus === 'cancelling' ? 'disabled' : ''}
                        >
                            <i data-lucide="square"></i>
                        </button>
                    ` : `
                        <button id="signalatlas-launch-btn" class="signalatlas-btn launch" type="button" onclick="launchSignalAtlasAudit()" ${(signalAtlasLaunchPending || !targetValidation.valid) ? 'disabled' : ''}>${escapeHtml(signalAtlasLaunchPending ? moduleT('signalatlas.launching', 'Lancement') : moduleT('signalatlas.runAudit', 'Lancer l’audit'))}</button>
                    `}
                    <div id="signalatlas-target-feedback" class="signalatlas-target-feedback${targetValidation.present && !targetValidation.valid ? ' is-visible' : ''}">${escapeHtml(targetValidation.present && !targetValidation.valid ? targetValidation.message : '')}</div>
                </div>
                <div class="signalatlas-primary-grid">
                    <div class="signalatlas-field">
                        <label class="signalatlas-field-head"><span>${escapeHtml(moduleT('signalatlas.auditProfileLabel', 'Niveau d’audit'))}</span></label>
                        ${renderSignalAtlasPicker('profile', 'signalatlas-profile-select', signalAtlasPickerOptions('profile'), selectedProfile)}
                    </div>
                    <div class="signalatlas-field">
                        <label class="signalatlas-field-head"><span>${escapeHtml(moduleT('signalatlas.modelLabel', 'Modèle'))}</span></label>
                        ${renderSignalAtlasPicker('model', 'signalatlas-model-select', signalAtlasPickerOptions('model'), currentModelLabel)}
                    </div>
                    <div class="signalatlas-field signalatlas-field-action">
                        <button class="signalatlas-advanced-toggle${signalAtlasAdvancedVisible ? ' is-open' : ''}" type="button" onclick="toggleSignalAtlasAdvancedSettings()">
                            <span>${escapeHtml(signalAtlasAdvancedVisible ? moduleT('signalatlas.advancedSettingsClose', 'Masquer les réglages détaillés') : moduleT('signalatlas.advancedSettingsOpen', 'Personnaliser'))}</span>
                            <i data-lucide="${signalAtlasAdvancedVisible ? 'chevron-up' : 'chevron-down'}"></i>
                        </button>
                    </div>
                </div>
                ${renderSignalAtlasProgressBanner(progressState, moduleT('signalatlas.backgroundResumeHint', 'Cet audit continue en arrière-plan si tu quittes cette vue.'))}
                ${signalAtlasAdvancedVisible ? `
                    <div class="signalatlas-advanced-panel">
                        <div class="signalatlas-controls-grid">
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.dataSourcesLabel', 'Sources de données'),
                                        moduleT('signalatlas.modeHelp', 'Audit public: seulement les signaux visibles publiquement. Propriétaire vérifié: enrichit l’audit avec des sources officielles reliées quand elles existent.')
                                    )}
                                </label>
                                ${renderSignalAtlasPicker('mode', 'signalatlas-mode-select', signalAtlasPickerOptions('mode'), signalAtlasDraft.mode)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.maxPages', 'Page budget'),
                                        moduleT('signalatlas.pageBudgetHint', 'Nombre maximum de pages échantillonnées sur cette passe d’audit. Ultra s’arrête automatiquement si le site est plus petit que le budget.')
                                    )}
                                </label>
                                ${renderSignalAtlasPicker('max_pages', 'signalatlas-max-pages', signalAtlasPickerOptions('max_pages'), signalAtlasDraft.max_pages)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.crawlDepth', 'Crawl depth'),
                                        moduleT('signalatlas.depthHint', 'Contrôle jusqu’où le crawler déterministe peut suivre les liens internes.')
                                    )}
                                </label>
                                ${renderSignalAtlasPicker('depth', 'signalatlas-depth', signalAtlasPickerOptions('depth'), signalAtlasDraft.depth)}
                            </div>
                            <div class="signalatlas-field is-toggle">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.renderJs', 'Rendu JS'),
                                        moduleT('signalatlas.renderJsHelp', 'Active des sondes de rendu JavaScript pour mieux détecter les SPA, shells HTML vides et écarts entre HTML brut et rendu client.')
                                    )}
                                </label>
                                <label class="signalatlas-switch">
                                    <input id="signalatlas-render-js" type="checkbox" ${signalAtlasDraft.render_js ? 'checked' : ''} onchange="syncSignalAtlasDraftFromDom(); renderSignalAtlasWorkspace();">
                                    <span></span>
                                </label>
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.presetLabel', 'Preset'),
                                        moduleT('signalatlas.presetHelp', 'Ajuste la quantité d’effort du modèle pour l’interprétation: rapide, équilibré, expert ou local privé.')
                                    )}
                                </label>
                                ${renderSignalAtlasPicker('preset', 'signalatlas-preset-select', signalAtlasPickerOptions('preset'), signalAtlasDraft.preset)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(
                                        moduleT('signalatlas.levelLabel', 'AI level'),
                                        moduleT('signalatlas.levelHelp', 'Choisit jusqu’où l’IA va: simple résumé, analyse experte complète ou pack de remédiation prêt à exécuter.')
                                    )}
                                </label>
                                ${renderSignalAtlasPicker('level', 'signalatlas-level-select', signalAtlasPickerOptions('level'), signalAtlasDraft.level)}
                            </div>
                        </div>
                    </div>
                ` : ''}
            </section>

            <section class="signalatlas-report-panel signalatlas-report-panel-wide">
                <div class="signalatlas-section-top signalatlas-report-heading">
                    <div class="signalatlas-report-heading-copy">
                        <div>
                            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.workspace', 'Rapport'))}</div>
                            <div class="signalatlas-panel-title">${escapeHtml(audit?.title || moduleT('signalatlas.selectAudit', 'Sélectionner ou lancer un audit'))}</div>
                            ${audit ? `<div class="signalatlas-panel-copy signalatlas-report-heading-copytext">${escapeHtml(moduleT('signalatlas.reportHeaderCopy', 'Lis le rapport simple d’abord, puis ouvre les détails SEO uniquement quand tu veux aller plus loin.'))}</div>` : ''}
                        </div>
                    </div>
                    ${audit ? `
                        <div class="signalatlas-report-toolbar">
                            <button class="signalatlas-btn secondary" type="button" onclick="toggleSignalAtlasHistoryDrawer()">${escapeHtml(signalAtlasHistoryVisible ? moduleT('signalatlas.hideAuditHistory', 'Masquer les audits récents') : moduleT('signalatlas.viewAuditHistory', 'Audits récents'))}</button>
                            <button class="signalatlas-btn secondary" type="button" onclick="toggleSignalAtlasSeoDetails()">${escapeHtml(signalAtlasSeoDetailsVisible ? moduleT('signalatlas.hideSeoActions', 'Masquer le détail SEO') : moduleT('signalatlas.viewSeoActions', 'Voir le détail SEO'))}</button>
                            <button class="signalatlas-report-download" type="button" onclick="downloadSignalAtlasAiReport('${escapeHtml(audit.id)}')">
                                <span class="signalatlas-report-download-icon"><i data-lucide="download-cloud"></i></span>
                                <span class="signalatlas-report-download-copy">
                                    <strong>${escapeHtml(moduleT('signalatlas.exportForAi', 'Exporter pour une IA'))}</strong>
                                    <small>${escapeHtml(moduleT('signalatlas.exportForAiMeta', 'Markdown prêt à transmettre'))}</small>
                                </span>
                            </button>
                        </div>
                    ` : ''}
                </div>
                ${signalAtlasHistoryVisible ? `
                    <div class="signalatlas-drawer-panel signalatlas-history-drawer${signalAtlasAnimateHistoryDrawer ? ' is-entering' : ''}">
                        <div class="signalatlas-section-top">
                            <div>
                                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.auditHistory', 'Historique des audits'))}</div>
                                <div class="signalatlas-panel-title">${escapeHtml(moduleT('signalatlas.recentRuns', 'Exécutions récentes'))}</div>
                            </div>
                            <button class="signalatlas-icon-btn" type="button" onclick="refreshSignalAtlasWorkspace()" aria-label="${escapeHtml(moduleT('common.refresh', 'Refresh'))}">
                                <i data-lucide="refresh-cw"></i>
                            </button>
                        </div>
                        <div class="signalatlas-history-list">${renderSignalAtlasHistory()}</div>
                    </div>
                ` : ''}
                ${audit ? `
                    <div class="signalatlas-report-hero">
                        <section class="signalatlas-panel signalatlas-report-summary-panel">
                            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.quickRead', 'Lecture rapide'))}</div>
                            <h2 class="signalatlas-report-summary-title">${escapeHtml(summary.target || audit?.title || '')}</h2>
                            <p class="signalatlas-panel-copy">${escapeHtml(moduleT('signalatlas.overviewLead', 'SignalAtlas te montre d’abord ce qui bloque la visibilité, puis te laisse exporter un rapport propre à donner à ton IA ou à ton dev.'))}</p>
                            <div class="signalatlas-summary-badges">
                                <span class="signalatlas-inline-chip">${escapeHtml(signalAtlasPlatformLabel(summary.platform || ''))}</span>
                                <span class="signalatlas-inline-chip">${escapeHtml(signalAtlasRenderingLabel(summary.rendering || ''))}</span>
                                <span class="signalatlas-inline-chip">${escapeHtml(signalAtlasModeLabel(summary.mode || 'public'))}</span>
                            </div>
                        </section>
                        <aside class="signalatlas-panel signalatlas-report-score-panel">
                            ${renderSignalAtlasScoreRing(summary.global_score, signalAtlasStatusLabel(audit.status), `${audit.id || 'audit'}:${summary.global_score ?? '--'}`)}
                            <div class="signalatlas-model-used-card">
                                <div class="signalatlas-panel-kicker">${escapeHtml(reportModelInfo.state === 'planned'
                                    ? moduleT('signalatlas.requestedModelLabel', 'Modèle demandé')
                                    : moduleT('signalatlas.reportModelLabel', 'Modèle du rapport'))}</div>
                                <div class="signalatlas-model-used-value">${escapeHtml(reportModelInfo.label)}</div>
                                <div class="signalatlas-model-used-copy">${escapeHtml(reportModelInfo.detail)}</div>
                                ${reportModelInfo.meta ? `<div class="signalatlas-model-used-meta">${escapeHtml(reportModelInfo.meta)}</div>` : ''}
                            </div>
                        </aside>
                    </div>
                    ${renderSignalAtlasOrganicMainCta(audit)}
                    ${renderSignalAtlasOverview(audit)}
                    ${signalAtlasSeoDetailsVisible ? `
                        <div class="signalatlas-drawer-panel signalatlas-seo-drawer${signalAtlasAnimateSeoDrawer ? ' is-entering' : ''}">
                            <div class="signalatlas-section-top">
                                <div>
                                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.seoActions', 'Détail SEO'))}</div>
                                    <div class="signalatlas-panel-title">${escapeHtml(moduleT('signalatlas.seoActionsCopy', 'Le détail technique complet reste ici quand tu veux passer du rapport simple à l’audit expert.'))}</div>
                                </div>
                            </div>
                            <div class="signalatlas-tabs">
                                ${tabs.map(([id, label]) => `<button class="signalatlas-tab${signalAtlasActiveTab === id ? ' active' : ''}" type="button" onclick="setSignalAtlasTab('${id}')">${escapeHtml(label)}</button>`).join('')}
                            </div>
                            <div class="signalatlas-tab-panel">
                                ${renderSignalAtlasTabContent(audit)}
                            </div>
                        </div>
                    ` : ''}
                ` : `
                    <div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.emptyWorkspace', 'Choisis un domaine ou un audit existant pour commencer.'))}</div>
                `}
            </section>
        </div>
    `;
    if (window.lucide) lucide.createIcons({ nodes: [host] });
    hydrateSignalAtlasMotion(host);
    renderSignalAtlasTargetValidationUi();
    restoreSignalAtlasUiState(uiState);
    signalAtlasAnimateHistoryDrawer = false;
    signalAtlasAnimateSeoDrawer = false;
}

function setSignalAtlasTab(tabId) {
    signalAtlasActiveTab = String(tabId || 'technical');
    signalAtlasSeoDetailsVisible = true;
    signalAtlasAnimateSeoDrawer = false;
    renderSignalAtlasWorkspace();
}

async function importSignalAtlasOrganicPotential(auditId, input) {
    const files = Array.from(input?.files || []);
    if (input) input.value = '';
    if (!auditId || !files.length) return;
    const acceptedFiles = files.filter(file => /\.(csv|zip)$/i.test(file.name || ''));
    if (acceptedFiles.length !== files.length) {
        Toast?.warning?.(moduleT('signalatlas.organicCsvOnly', 'Importe uniquement des fichiers CSV ou ZIP Google Search Console.'));
        return;
    }
    const formData = new FormData();
    acceptedFiles.forEach(file => formData.append('files', file, file.name));
    Toast?.info?.(moduleT('signalatlas.organicImportRunning', 'Import GSC en cours...'));
    const result = await apiSignalAtlas.importOrganicPotential(auditId, formData);
    if (!result.ok || !result.data?.audit) {
        Toast?.error?.(result.data?.error || moduleT('signalatlas.organicImportFailed', 'Impossible d’importer ces CSV GSC.'));
        return;
    }
    signalAtlasCurrentAudit = result.data.audit;
    signalAtlasCurrentAuditId = result.data.audit.id;
    const existing = signalAtlasAudits.findIndex(item => item.id === signalAtlasCurrentAuditId);
    const summaryCard = summarizeSignalAtlasAudit(signalAtlasCurrentAudit);
    if (existing >= 0) signalAtlasAudits.splice(existing, 1, summaryCard);
    else signalAtlasAudits.unshift(summaryCard);
    signalAtlasActiveTab = 'organic';
    signalAtlasSeoDetailsVisible = true;
    signalAtlasAnimateSeoDrawer = false;
    Toast?.success?.(moduleT('signalatlas.organicImportSuccess', 'Potentiel organique généré avec les données GSC.'));
    renderSignalAtlasWorkspace();
}

async function openModulesHub() {
    hideModulesWorkspaces();
    applyModulesShellMode('sidebar-modules-btn', 'modules-mode');
    const view = getModulesView();
    if (view) view.style.display = 'flex';
    await loadModulesCatalog();
    renderModulesHub();
}

async function openSignalAtlasWorkspace(auditId = null) {
    if (auditId) signalAtlasCurrentAuditId = auditId;
    hideModulesWorkspaces();
    applyModulesShellMode('sidebar-modules-btn', 'signalatlas-mode');
    const view = getSignalAtlasView();
    if (view) view.style.display = 'flex';
    ensureSignalAtlasInteractionTracking();
    await loadSignalAtlasBootstrap();
    renderSignalAtlasWorkspace();
    startSignalAtlasRefresh();
}

async function openAuditModuleWorkspace(moduleId, auditId = null) {
    const clean = String(moduleId || '').trim().toLowerCase();
    if (clean === 'signalatlas') {
        await openSignalAtlasWorkspace(auditId);
        return;
    }
    if (clean === 'perfatlas') {
        await openPerfAtlasWorkspace(auditId);
        return;
    }
    if (clean === 'cyberatlas') {
        await window.openCyberAtlasWorkspace?.(auditId);
        return;
    }
    if (clean === 'deployatlas') {
        await window.openDeployAtlasWorkspace?.(auditId);
    }
}

function openNativeModule(moduleId) {
    const module = (joyboyModulesCatalog || []).find(item => String(item?.id || '').trim().toLowerCase() === String(moduleId || '').trim().toLowerCase());
    if (module && (module.available === false || module.backend_ready === false)) {
        Toast?.warning?.(module.locked_reason || moduleT('modules.restartRequired', 'Restart JoyBoy to activate this module in the running app.'));
        return;
    }
    openAuditModuleWorkspace(moduleId);
}

async function launchSignalAtlasAudit() {
    syncSignalAtlasDraftFromDom();
    const targetValidation = signalAtlasValidateTarget(signalAtlasDraft.target);
    if (!targetValidation.present) {
        Toast?.warning?.(moduleT('signalatlas.targetRequired', 'Ajoute d’abord un vrai domaine ou une URL publique, par exemple https://nevomove.com/.'));
        renderSignalAtlasTargetValidationUi();
        return;
    }
    if (!targetValidation.valid) {
        Toast?.warning?.(moduleT('signalatlas.targetInvalid', 'Utilise un vrai domaine ou une URL publique complète, par exemple https://nevomove.com/.'));
        renderSignalAtlasTargetValidationUi();
        return;
    }
    signalAtlasLaunchPending = true;
    renderSignalAtlasWorkspace();
    const payload = {
        target: String(signalAtlasDraft.target || '').trim(),
        mode: signalAtlasDraft.mode || 'public',
        options: {
            max_pages: signalAtlasResolvedPageBudget(signalAtlasDraft.max_pages, SIGNALATLAS_DEFAULT_PAGE_BUDGET),
            depth: signalAtlasDraft.depth || 2,
            render_js: !!signalAtlasDraft.render_js,
        },
        ai: {
            model: signalAtlasDraft.model || currentJoyBoyChatModel(),
            preset: signalAtlasDraft.preset || 'balanced',
            level: signalAtlasDraft.level || 'basic_summary',
        },
    };
    try {
        const result = await apiSignalAtlas.createAudit(payload);
        if (!result.ok) {
            Toast?.error?.(result.data?.error || moduleT('signalatlas.auditCreateFailed', 'Impossible de lancer l’audit.'));
            return;
        }
        signalAtlasCurrentAuditId = result.data?.audit?.id || signalAtlasCurrentAuditId;
        signalAtlasCurrentAudit = result.data?.audit || signalAtlasCurrentAudit;
        if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
        await loadSignalAtlasBootstrap();
        if (signalAtlasCurrentAuditId) {
            await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
        }
        notifySignalAtlasAuditCompleted(signalAtlasCurrentAudit, { status: 'running', hadProgress: true });
        renderSignalAtlasWorkspace();
        startSignalAtlasRefresh();
        Toast?.success?.(moduleT('signalatlas.auditStarted', 'Audit SignalAtlas lancé.'));
    } finally {
        signalAtlasLaunchPending = false;
    }
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

async function cancelSignalAtlasAudit(auditId = '') {
    const targetAuditId = String(auditId || signalAtlasCurrentAuditId || '').trim();
    if (!targetAuditId || typeof apiRuntime === 'undefined') return;
    const progressState = signalAtlasAuditProgressState(targetAuditId);
    const jobId = String(progressState?.job?.id || '').trim();
    if (!jobId) return;

    const result = await apiRuntime.cancelJob(jobId, {});
    if (!result.ok || !result.data?.job) {
        Toast?.error?.(result.data?.error || moduleT('signalatlas.cancelAuditFailed', 'Impossible d’annuler cet audit.'));
        return;
    }

    seedSignalAtlasRuntimeJob(result.data.job, targetAuditId);
    if (signalAtlasCurrentAudit && String(signalAtlasCurrentAudit.id || '') === targetAuditId) {
        signalAtlasCurrentAudit.status = String(result.data.job.status || 'cancelling').toLowerCase();
    }
    Toast?.success?.(moduleT('signalatlas.cancelAuditRequested', 'Demande d’annulation envoyée.'));
    await refreshSignalAtlasWorkspace();
}

async function deleteSignalAtlasAudit(auditId = '', event = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const targetAuditId = String(auditId || '').trim();
    if (!targetAuditId) return;
    const progressState = signalAtlasAuditProgressState(targetAuditId);
    if (progressState) {
        Toast?.warning?.(moduleT('signalatlas.deleteAuditBlocked', 'Annule cet audit avant de le supprimer.'));
        return;
    }
    const audit = (signalAtlasAudits || []).find(item => String(item?.id || '') === targetAuditId);
    const title = audit?.title || audit?.host || moduleT('signalatlas.auditItem', 'cet audit');
    const confirmed = await JoyDialog.confirm(
        moduleT('signalatlas.deleteAuditConfirm', 'Supprimer définitivement {title} ?', { title }),
        { variant: 'danger' }
    );
    if (!confirmed) return;
    const result = await apiSignalAtlas.deleteAudit(targetAuditId);
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('signalatlas.deleteAuditFailed', 'Impossible de supprimer cet audit.'));
        return;
    }
    signalAtlasAudits = (signalAtlasAudits || []).filter(item => String(item?.id || '') !== targetAuditId);
    if (String(signalAtlasCurrentAuditId || '') === targetAuditId) {
        signalAtlasCurrentAuditId = signalAtlasAudits[0]?.id || null;
        signalAtlasCurrentAudit = null;
    }
    await loadSignalAtlasBootstrap();
    if (signalAtlasCurrentAuditId) {
        await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
    }
    renderSignalAtlasWorkspace();
    Toast?.success?.(moduleT('signalatlas.deleteAuditSuccess', 'Audit supprimé.'));
}

async function rerunSignalAtlasAi() {
    if (!signalAtlasCurrentAuditId) return;
    syncSignalAtlasDraftFromDom();
    const payload = {
        model: signalAtlasDraft.model || currentJoyBoyChatModel(),
        preset: signalAtlasDraft.preset || 'balanced',
        level: signalAtlasDraft.level || 'basic_summary',
    };
    const result = await apiSignalAtlas.rerunAi(signalAtlasCurrentAuditId, payload);
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('signalatlas.rerunFailed', 'Impossible de relancer l’interprétation IA.'));
        return;
    }
    if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
    renderSignalAtlasWorkspace();
    startSignalAtlasRefresh();
    Toast?.success?.(moduleT('signalatlas.rerunStarted', 'Interprétation IA lancée.'));
}

async function compareSignalAtlasAi() {
    if (!signalAtlasCurrentAuditId) return;
    syncSignalAtlasDraftFromDom();
    const leftModel = signalAtlasDraft.model || currentJoyBoyChatModel();
    const rightModel = signalAtlasDraft.compare_model || fallbackSignalAtlasCompareModel();
    const result = await apiSignalAtlas.compareAi(signalAtlasCurrentAuditId, {
        left_model: leftModel,
        right_model: rightModel,
        preset: signalAtlasDraft.preset || 'expert',
        level: signalAtlasDraft.level === 'no_ai' ? 'full_expert_analysis' : signalAtlasDraft.level,
    });
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('signalatlas.compareFailed', 'Impossible de comparer les interprétations.'));
        return;
    }
    if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
    renderSignalAtlasWorkspace();
    startSignalAtlasRefresh();
    Toast?.success?.(moduleT('signalatlas.compareStarted', 'Comparaison SignalAtlas lancée.'));
}

function notifySignalAtlasAuditCompleted(audit, previousState = {}) {
    const auditId = String(audit?.id || '').trim();
    if (!auditId || signalAtlasCompletionNotifiedAuditIds.has(auditId)) return;
    const status = String(audit?.status || '').trim().toLowerCase();
    if (status !== 'done') return;
    const previousStatus = String(previousState.status || '').trim().toLowerCase();
    const wasActive = previousState.hadProgress || ['queued', 'running', 'cancelling'].includes(previousStatus);
    if (!wasActive) return;
    signalAtlasCompletionNotifiedAuditIds.add(auditId);
    const summary = audit.summary || {};
    const crawlCopy = summary.crawl_exhausted_early
        ? moduleT('signalatlas.auditCompleteSmallSite', 'Crawl terminé proprement : le site n’avait plus d’URLs utiles à suivre, donc Ultra s’est arrêté sans attendre le budget maximal.')
        : moduleT('signalatlas.auditCompleteReadyCopy', 'Le rapport est prêt avec le crawl, les priorités SEO, les exports et la couche IA demandée.');
    Toast?.success?.(
        moduleT('signalatlas.auditCompleteToastTitle', 'Audit SignalAtlas terminé'),
        crawlCopy,
        9000
    );
}

async function refreshSignalAtlasWorkspace(options = {}) {
    const allowDefer = options.allowDefer !== false;
    if (allowDefer && signalAtlasShouldDeferRefresh()) {
        signalAtlasPendingRefresh = true;
        scheduleSignalAtlasDeferredRefresh();
        return { deferred: true };
    }
    const previousState = {
        auditId: signalAtlasCurrentAuditId,
        status: signalAtlasCurrentAudit?.status || '',
        hadProgress: !!(signalAtlasCurrentAuditId && signalAtlasAuditProgressState(signalAtlasCurrentAuditId)),
    };
    signalAtlasPendingRefresh = false;
    await loadSignalAtlasBootstrap();
    if (signalAtlasCurrentAuditId) {
        await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
    }
    if (previousState.auditId && String(previousState.auditId) === String(signalAtlasCurrentAudit?.id || '')) {
        notifySignalAtlasAuditCompleted(signalAtlasCurrentAudit, previousState);
    }
    renderSignalAtlasWorkspace();
    return { refreshed: true };
}

function startSignalAtlasRefresh() {
    stopSignalAtlasRefresh();
    signalAtlasRefreshTimer = setInterval(async () => {
        if (!isSignalAtlasVisible()) {
            stopSignalAtlasRefresh();
            return;
        }
        if (signalAtlasRefreshInFlight) return;
        signalAtlasRefreshInFlight = true;
        let refreshResult = null;
        try {
            refreshResult = await refreshSignalAtlasWorkspace({ allowDefer: true });
        } finally {
            signalAtlasRefreshInFlight = false;
        }
        if (refreshResult?.deferred) return;
        if (!signalAtlasAnyProgressState()) {
            stopSignalAtlasRefresh();
        }
    }, 3500);
}

function stopSignalAtlasRefresh() {
    if (signalAtlasRefreshTimer) {
        clearInterval(signalAtlasRefreshTimer);
        signalAtlasRefreshTimer = null;
    }
    if (signalAtlasDeferredRefreshTimer) {
        clearTimeout(signalAtlasDeferredRefreshTimer);
        signalAtlasDeferredRefreshTimer = null;
    }
    signalAtlasPendingRefresh = false;
    signalAtlasRefreshInFlight = false;
}

function downloadSignalAtlasExport(auditId, formatName) {
    if (!auditId) return;
    window.location.href = `/api/signalatlas/audits/${encodeURIComponent(auditId)}/export/${encodeURIComponent(formatName)}`;
}

function downloadSignalAtlasAiReport(auditId) {
    if (!auditId) return;
    downloadSignalAtlasExport(auditId, 'markdown');
}

async function openSignalAtlasPromptInChat(auditId) {
    if (!auditId) return;
    const result = await apiSignalAtlas.fetchExportText(auditId, 'prompt');
    if (!result.ok) {
        Toast?.error?.(moduleT('signalatlas.promptLoadFailed', 'Impossible de charger le prompt de correction IA.'));
        return;
    }
    if (typeof createNewChat === 'function') {
        await createNewChat();
    }
    if (typeof showChat === 'function') showChat();
    const input = document.getElementById('chat-prompt');
    if (input) {
        input.value = result.data || '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
    }
}

function renderPerfAtlasProviderStrip() {
    if (!Array.isArray(perfAtlasProviders) || !perfAtlasProviders.length) return '';
    const visibleProviders = perfAtlasProviders.filter(provider => {
        const status = String(provider?.status || '').trim().toLowerCase();
        return Boolean(provider?.configured)
            || ['confirmed', 'configured', 'ready', 'target_mismatch', 'property_unverified', 'auth_error', 'connector_missing', 'error'].includes(status);
    });
    if (!visibleProviders.length) return '';
    return `
        <section class="signalatlas-owner-strip perfatlas-owner-strip">
            ${visibleProviders.map(provider => `
                <div class="signalatlas-owner-card">
                    <div class="signalatlas-owner-card-top">
                        <span class="signalatlas-owner-name">${escapeHtml(provider.name || provider.id || 'Provider')}</span>
                        <span class="signalatlas-tag ${signalAtlasProviderTone(provider.status)}">${escapeHtml(signalAtlasProviderStatusLabel(provider.status || 'unknown'))}</span>
                    </div>
                    <div class="signalatlas-owner-note">${escapeHtml(perfAtlasProviderSummary(provider))}</div>
                </div>
            `).join('')}
        </section>
    `;
}

function renderPerfAtlasScoreCards(audit) {
    const scores = Array.isArray(audit?.scores) ? audit.scores : [];
    return scores.map(score => `
        <div class="signalatlas-score-card ${signalAtlasScoreTone(score.score)}">
            <div class="signalatlas-score-label">${escapeHtml(perfAtlasScoreLabel(score))}</div>
            <div class="signalatlas-score-value">${escapeHtml(String(score.score ?? '--'))}</div>
            <div class="signalatlas-score-meta">${escapeHtml(signalAtlasConfidenceLabel(score.confidence || ''))}</div>
        </div>
    `).join('');
}

function renderPerfAtlasFindings(audit, limit = 6) {
    const items = Array.isArray(audit?.findings) ? audit.findings.slice(0, limit) : [];
    if (!items.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noFindings', 'No major performance findings were detected in the sampled coverage.'))}</div>`;
    }
    return renderAuditFindingCards(items, item => ({
        title: perfAtlasFindingTitle(item),
        summary: perfAtlasFindingDiagnostic(item),
        fix: perfAtlasFindingFix(item),
        severity: item.severity,
        severityLabel: signalAtlasSeverityLabel(item.severity || ''),
        severityTone: signalAtlasSeverityTone(item.severity),
        meta: [
            perfAtlasCategoryLabel(item.category || ''),
            signalAtlasConfidenceLabel(item.confidence || ''),
            item.url || item.scope || '',
        ],
    }), '', limit);
}

function renderPerfAtlasFieldData(audit) {
    const items = Array.isArray(audit?.snapshot?.field_data) ? audit.snapshot.field_data : [];
    if (!items.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noFieldData', 'No public field dataset was confirmed in this pass.'))}</div>`;
    }
    return `
        <div class="signalatlas-detail-grid">
            ${items.map(item => `
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml((item.scope || 'field').toUpperCase())}</div>
                    <div class="signalatlas-panel-title">${escapeHtml(item.source || 'crux_api')}</div>
                    <div class="signalatlas-panel-copy">${escapeHtml(moduleT('perfatlas.fieldFormFactor', 'Form factor'))}: ${escapeHtml(String(item.form_factor || 'all').toUpperCase())}</div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>LCP p75</span><strong>${escapeHtml(perfAtlasFormatMs(item.lcp_ms))}</strong></div>
                        <div class="signalatlas-metric-card"><span>INP p75</span><strong>${escapeHtml(perfAtlasFormatMs(item.inp_ms))}</strong></div>
                        <div class="signalatlas-metric-card"><span>CLS p75</span><strong>${escapeHtml(perfAtlasFormatCls(item.cls))}</strong></div>
                        <div class="signalatlas-metric-card"><span>TTFB p75</span><strong>${escapeHtml(perfAtlasFormatMs(item.ttfb_ms))}</strong></div>
                    </div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.goodLcpShare', 'Good LCP share'))}</span><strong>${escapeHtml(perfAtlasFormatPercent(item.good_lcp_fraction))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.goodInpShare', 'Good INP share'))}</span><strong>${escapeHtml(perfAtlasFormatPercent(item.good_inp_fraction))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.goodClsShare', 'Good CLS share'))}</span><strong>${escapeHtml(perfAtlasFormatPercent(item.good_cls_fraction))}</strong></div>
                    </div>
                    ${item.history && Object.keys(item.history).length ? `
                        <div class="signalatlas-finding-list">
                            ${Object.entries(item.history).map(([metricKey, trend]) => `
                                <div class="signalatlas-mini-finding-card">
                                    <div class="signalatlas-mini-finding-title">${escapeHtml(metricKey)}</div>
                                    <div class="signalatlas-mini-finding-copy">${escapeHtml(perfAtlasTrendDirectionLabel(trend.direction || 'steady'))} · ${escapeHtml(String(trend.earliest ?? 'n/a'))} → ${escapeHtml(String(trend.latest ?? 'n/a'))}</div>
                                </div>
                            `).join('')}
                        </div>
                    ` : ''}
                    <div class="signalatlas-panel-copy">${escapeHtml(item.note || '')}</div>
                </section>
            `).join('')}
        </div>
    `;
}

function renderPerfAtlasLabRuns(audit) {
    const items = Array.isArray(audit?.snapshot?.lab_runs) ? audit.snapshot.lab_runs : [];
    if (!items.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noLabData', 'No representative lab run completed in this pass.'))}</div>`;
    }
    return items.map(item => `
        <section class="signalatlas-panel perfatlas-lab-card">
            <div class="signalatlas-section-top">
                <div>
                    <div class="signalatlas-panel-kicker">${escapeHtml(perfAtlasRuntimeLabel(item.runner || 'lab'))}</div>
                    <div class="signalatlas-panel-title">${escapeHtml(item.url || '')}</div>
                </div>
                <div class="signalatlas-summary-badges">
                    <span class="signalatlas-inline-chip">${escapeHtml(moduleT('perfatlas.scoreShort', 'Score'))}: ${escapeHtml(String(item.score ?? 'n/a'))}</span>
                    <span class="signalatlas-inline-chip">${escapeHtml(moduleT(`perfatlas.strategy_${auditTranslationKey(item.strategy || 'mobile')}`, item.strategy || 'mobile'))}</span>
                </div>
            </div>
            <div class="signalatlas-metric-grid">
                <div class="signalatlas-metric-card"><span>LCP</span><strong>${escapeHtml(perfAtlasFormatMs(item.largest_contentful_paint_ms))}</strong></div>
                <div class="signalatlas-metric-card"><span>TBT</span><strong>${escapeHtml(perfAtlasFormatMs(item.total_blocking_time_ms))}</strong></div>
                <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.requestShort', 'Req'))}</span><strong>${escapeHtml(String(item.request_count ?? 'n/a'))}</strong></div>
                <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.weightLabel', 'Weight'))}</span><strong>${escapeHtml(perfAtlasFormatBytes(item.total_byte_weight))}</strong></div>
            </div>
            ${item.note ? `<div class="signalatlas-panel-copy">${escapeHtml(item.note)}</div>` : ''}
            ${(item.opportunities || []).length ? `
                <div class="signalatlas-finding-list">
                    ${(item.opportunities || []).slice(0, 5).map(opp => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">${escapeHtml(perfAtlasOpportunityTitle(opp))}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(String(opp.display_value || opp.numeric_value || ''))}</div>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        </section>
    `).join('');
}

function renderPerfAtlasDelivery(audit) {
    const pages = Array.isArray(audit?.snapshot?.pages) ? audit.snapshot.pages.slice(0, 8) : [];
    const assets = Array.isArray(audit?.snapshot?.asset_samples) ? audit.snapshot.asset_samples.slice(0, 10) : [];
    return `
        <div class="signalatlas-detail-grid">
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.sampledPages', 'Sampled pages'))}</div>
                <div class="signalatlas-finding-list">
                    ${pages.length ? pages.map(page => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">${escapeHtml(page.final_url || page.url || '')}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(perfAtlasFormatMs(page.ttfb_ms))} · ${escapeHtml(String(page.script_count || 0))} JS · ${escapeHtml(String(page.stylesheet_count || 0))} CSS · ${escapeHtml(String(page.image_count || 0))} ${escapeHtml(moduleT('perfatlas.imageShort', 'img'))}</div>
                        </div>
                    `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noSampledPages', 'No sampled page snapshot is available.'))}</div>`}
                </div>
            </section>
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.sampledAssets', 'Sampled assets'))}</div>
                <div class="signalatlas-finding-list">
                    ${assets.length ? assets.map(asset => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">${escapeHtml(asset.url || '')}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(perfAtlasAssetKindLabel(asset.kind || 'asset'))} · ${escapeHtml(moduleT('perfatlas.cacheHeader', 'cache'))} ${escapeHtml(asset.cache_control || moduleT('perfatlas.noHeaderValue', 'aucun'))} · ${escapeHtml(moduleT('perfatlas.encodingHeader', 'encodage'))} ${escapeHtml(asset.content_encoding || moduleT('perfatlas.noHeaderValue', 'aucun'))}</div>
                        </div>
                    `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noAssets', 'No sampled asset headers were collected.'))}</div>`}
                </div>
            </section>
        </div>
    `;
}

function renderPerfAtlasResources(audit) {
    const templates = Array.isArray(audit?.snapshot?.template_clusters) ? audit.snapshot.template_clusters : [];
    if (!templates.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noTemplateClusters', 'No template clusters were derived from the sampled pages.'))}</div>`;
    }
    return `
        <div class="signalatlas-template-grid">
            ${templates.map(cluster => `
                <article class="signalatlas-template-card">
                    <div class="signalatlas-template-title">${escapeHtml(cluster.template || '/')}</div>
                    <div class="signalatlas-template-meta">${escapeHtml(moduleT('perfatlas.clusterCount', '{count} page(s)', { count: cluster.count || 0 }))}</div>
                    <div class="signalatlas-metric-row"><span>TTFB</span><strong>${escapeHtml(perfAtlasFormatMs(cluster.avg_ttfb_ms))}</strong></div>
                    <div class="signalatlas-metric-row"><span>HTML</span><strong>${escapeHtml(perfAtlasFormatBytes((Number(cluster.avg_html_kb) || 0) * 1024))}</strong></div>
                </article>
            `).join('')}
        </div>
    `;
}

function perfAtlasPerformanceIntelligence(audit) {
    const intelligence = audit?.snapshot?.performance_intelligence;
    return intelligence && typeof intelligence === 'object' ? intelligence : null;
}

function perfAtlasRegression(audit) {
    const regression = audit?.snapshot?.regression;
    return regression && typeof regression === 'object' ? regression : null;
}

function perfAtlasRegressionTone(value) {
    const clean = String(value || '').trim().toLowerCase();
    if (clean === 'improved') return 'is-good';
    if (clean === 'regressed') return 'is-danger';
    if (clean === 'stable') return 'is-warn';
    return '';
}

function perfAtlasRegressionLabel(value) {
    const key = auditTranslationKey(value || 'unknown');
    return moduleT(`perfatlas.regression_${key}`, value || moduleT('perfatlas.diagnosticUnknown', 'Inconnu'));
}

function perfAtlasDiagnosticStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'ok' || clean === 'good') return moduleT('perfatlas.diagnosticGood', 'Bon');
    if (clean === 'warn') return moduleT('perfatlas.diagnosticWarn', 'À surveiller');
    if (clean === 'fail' || clean === 'bad') return moduleT('perfatlas.diagnosticBad', 'Critique');
    return moduleT('perfatlas.diagnosticUnknown', 'Inconnu');
}

function perfAtlasDiagnosticTone(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'ok' || clean === 'good') return 'is-good';
    if (clean === 'warn') return 'is-warn';
    if (clean === 'fail' || clean === 'bad') return 'is-danger';
    return '';
}

function perfAtlasFormatBudgetValue(value, unit) {
    if (value === null || value === undefined || value === '') return 'n/a';
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return String(value);
    if (unit === 'bytes') return perfAtlasFormatBytes(numeric);
    if (unit === 'ms') return perfAtlasFormatMs(numeric);
    if (unit === 'score') return String(Math.round(numeric * 1000) / 1000);
    return String(Math.round(numeric * 10) / 10);
}

function renderPerfAtlasIntelligence(audit) {
    const intelligence = perfAtlasPerformanceIntelligence(audit);
    if (!intelligence) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noPerformanceIntelligence', 'Aucune intelligence performance structurée n’est attachée à cet audit.'))}</div>`;
    }
    const summary = intelligence.summary || {};
    const budgets = Array.isArray(intelligence.budgets) ? intelligence.budgets : [];
    const detectives = Array.isArray(intelligence.detectives) ? intelligence.detectives : [];
    const actions = Array.isArray(intelligence.action_plan) ? intelligence.action_plan : [];
    const waterfall = intelligence.waterfall || {};
    const thirdParty = intelligence.third_party_tax || {};
    const cache = intelligence.cache_simulation || {};
    const regression = perfAtlasRegression(audit);
    const pageTypes = Array.isArray(intelligence.page_types) ? intelligence.page_types : [];
    const topHosts = Array.isArray(thirdParty.top_hosts) ? thirdParty.top_hosts : [];
    return `
        <div class="signalatlas-overview-stack">
            <section class="signalatlas-panel">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.intelligenceKicker', 'Performance Intelligence'))}</div>
                        <div class="signalatlas-panel-title">${escapeHtml(moduleT('perfatlas.intelligenceTitle', 'Lecture technique exploitable'))}</div>
                    </div>
                    <span class="signalatlas-tag ${summary.diagnostic_confidence === 'high' ? 'is-good' : summary.diagnostic_confidence === 'limited' ? 'is-warn' : ''}">
                        ${escapeHtml(moduleT(`perfatlas.confidence_${auditTranslationKey(summary.diagnostic_confidence || 'limited')}`, summary.diagnostic_confidence || 'limited'))}
                    </span>
                </div>
                <div class="signalatlas-metric-grid">
                    <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.failedBudgets', 'Budgets rouges'))}</span><strong>${escapeHtml(String(summary.failed_budget_count || 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.warningBudgets', 'Budgets orange'))}</span><strong>${escapeHtml(String(summary.warning_budget_count || 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.redDetectives', 'Détectives rouges'))}</span><strong>${escapeHtml(String(summary.bad_detector_count || 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.thirdPartyHosts', 'Tiers'))}</span><strong>${escapeHtml(String(thirdParty.host_count || 0))}</strong></div>
                </div>
                ${summary.top_action ? `<div class="signalatlas-panel-copy">${escapeHtml(moduleT('perfatlas.topActionLabel', 'Action prioritaire'))}: ${escapeHtml(summary.top_action)}</div>` : ''}
            </section>
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.budgetsTitle', 'Budgets de performance'))}</div>
                    <div class="signalatlas-finding-list">
                        ${budgets.map(item => `
                            <div class="signalatlas-mini-finding-card">
                                <div class="signalatlas-mini-finding-title">
                                    ${escapeHtml(item.label || item.id || '')}
                                    <span class="signalatlas-tag ${perfAtlasDiagnosticTone(item.status)}">${escapeHtml(perfAtlasDiagnosticStatusLabel(item.status))}</span>
                                </div>
                                <div class="signalatlas-mini-finding-copy">${escapeHtml(perfAtlasFormatBudgetValue(item.actual, item.unit))} / ${escapeHtml(perfAtlasFormatBudgetValue(item.limit, item.unit))}</div>
                            </div>
                        `).join('')}
                    </div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.detectivesTitle', 'Détectives'))}</div>
                    <div class="signalatlas-finding-list">
                        ${detectives.map(item => `
                            <div class="signalatlas-mini-finding-card">
                                <div class="signalatlas-mini-finding-title">
                                    ${escapeHtml(item.title || item.id || '')}
                                    <span class="signalatlas-tag ${perfAtlasDiagnosticTone(item.status)}">${escapeHtml(perfAtlasDiagnosticStatusLabel(item.status))}</span>
                                </div>
                                <div class="signalatlas-mini-finding-copy">${escapeHtml(item.summary || '')}</div>
                                ${(item.evidence || []).length ? `<div class="signalatlas-mini-finding-copy">${escapeHtml((item.evidence || []).slice(0, 3).join(' · '))}</div>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </section>
            </div>
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.waterfallTitle', 'Waterfall & cache'))}</div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.sampledAssets', 'Ressources échantillonnées'))}</span><strong>${escapeHtml(String(waterfall.asset_count || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.firstPartyBytes', 'First-party'))}</span><strong>${escapeHtml(perfAtlasFormatBytes(waterfall.first_party_bytes || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.thirdPartyBytes', 'Third-party'))}</span><strong>${escapeHtml(perfAtlasFormatBytes(waterfall.third_party_bytes || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.repeatVisitRisk', 'Risque cache'))}</span><strong>${escapeHtml(perfAtlasDiagnosticStatusLabel(cache.repeat_visit_risk === 'high' ? 'bad' : cache.repeat_visit_risk === 'medium' ? 'warn' : 'good'))}</strong></div>
                    </div>
                    <div class="signalatlas-panel-copy">${escapeHtml(cache.summary || '')}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.thirdPartyTaxTitle', 'Taxe third-party'))}</div>
                    <div class="signalatlas-finding-list">
                        ${topHosts.length ? topHosts.slice(0, 6).map(host => `
                            <div class="signalatlas-mini-finding-card">
                                <div class="signalatlas-mini-finding-title">
                                    ${escapeHtml(host.host || '')}
                                    <span class="signalatlas-tag ${perfAtlasDiagnosticTone(host.risk === 'high' ? 'bad' : host.risk === 'medium' ? 'warn' : 'good')}">${escapeHtml(perfAtlasDiagnosticStatusLabel(host.risk === 'high' ? 'bad' : host.risk === 'medium' ? 'warn' : 'good'))}</span>
                                </div>
                                <div class="signalatlas-mini-finding-copy">${escapeHtml(String(host.page_mentions || 0))} ${escapeHtml(moduleT('perfatlas.pageMentions', 'mentions'))} · ${escapeHtml(perfAtlasFormatBytes(host.sampled_bytes || 0))}</div>
                            </div>
                        `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noThirdPartyHotspot', 'Aucun hotspot tiers dominant confirmé.'))}</div>`}
                    </div>
                </section>
            </div>
            ${regression ? `
                <section class="signalatlas-panel">
                    <div class="signalatlas-section-top">
                        <div>
                            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.regressionTitle', 'Comparaison précédente'))}</div>
                            <div class="signalatlas-panel-title">${escapeHtml(regression.summary || '')}</div>
                        </div>
                        <span class="signalatlas-tag ${perfAtlasRegressionTone(regression.risk)}">${escapeHtml(perfAtlasRegressionLabel(regression.risk))}</span>
                    </div>
                    ${regression.available ? `
                        <div class="signalatlas-metric-grid">
                            ${Object.entries(regression.deltas || {}).slice(0, 6).map(([key, value]) => `
                                <div class="signalatlas-metric-card">
                                    <span>${escapeHtml(moduleT(`perfatlas.regressionMetric_${auditTranslationKey(key)}`, key.replace(/_/g, ' ')))}</span>
                                    <strong>${escapeHtml(String(value?.delta ?? 'n/a'))}</strong>
                                    <small>${escapeHtml(String(value?.previous ?? 'n/a'))} → ${escapeHtml(String(value?.current ?? 'n/a'))}</small>
                                </div>
                            `).join('')}
                        </div>
                        ${(regression.regressions || []).length ? `
                            <div class="signalatlas-finding-list">
                                ${(regression.regressions || []).map(item => `
                                    <div class="signalatlas-mini-finding-card">
                                        <div class="signalatlas-mini-finding-title">${escapeHtml(moduleT('perfatlas.regressionDetected', 'Régression détectée'))}</div>
                                        <div class="signalatlas-mini-finding-copy">${escapeHtml(item)}</div>
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}
                        ${(regression.improvements || []).length ? `
                            <div class="signalatlas-finding-list">
                                ${(regression.improvements || []).map(item => `
                                    <div class="signalatlas-mini-finding-card">
                                        <div class="signalatlas-mini-finding-title">${escapeHtml(moduleT('perfatlas.improvementDetected', 'Amélioration détectée'))}</div>
                                        <div class="signalatlas-mini-finding-copy">${escapeHtml(item)}</div>
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}
                    ` : `<div class="signalatlas-panel-copy">${escapeHtml(regression.summary || moduleT('perfatlas.noRegressionBaseline', 'Aucun audit précédent terminé pour comparer.'))}</div>`}
                </section>
            ` : ''}
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.actionPlanTitle', 'Plan d’action'))}</div>
                <div class="signalatlas-finding-list">
                    ${actions.length ? actions.map(action => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">P${escapeHtml(String(action.priority || ''))} · ${escapeHtml(action.title || '')}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(moduleT('perfatlas.impactLabel', 'Impact'))}: ${escapeHtml(action.impact || '')} · ${escapeHtml(moduleT('perfatlas.effortLabel', 'Effort'))}: ${escapeHtml(action.effort || '')}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(action.dev_prompt || '')}</div>
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(moduleT('perfatlas.validationLabel', 'Validation'))}: ${escapeHtml(action.validation || '')}</div>
                        </div>
                    `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noActionPlan', 'Aucun plan prioritaire généré.'))}</div>`}
                </div>
            </section>
            ${pageTypes.length ? `
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.pageTypesTitle', 'Types de pages'))}</div>
                    <div class="signalatlas-template-grid">
                        ${pageTypes.map(item => `
                            <article class="signalatlas-template-card">
                                <div class="signalatlas-template-title">${escapeHtml(moduleT(`perfatlas.pageType_${auditTranslationKey(item.type)}`, item.type || 'page'))}</div>
                                <div class="signalatlas-template-meta">${escapeHtml(moduleT('perfatlas.clusterCount', '{count} page(s)', { count: item.count || 0 }))}</div>
                                <div class="signalatlas-metric-row"><span>TTFB</span><strong>${escapeHtml(perfAtlasFormatMs(item.avg_ttfb_ms))}</strong></div>
                                <div class="signalatlas-metric-row"><span>HTML</span><strong>${escapeHtml(perfAtlasFormatBytes((Number(item.avg_html_kb) || 0) * 1024))}</strong></div>
                            </article>
                        `).join('')}
                    </div>
                </section>
            ` : ''}
        </div>
    `;
}

function perfAtlasOwnerContextLabel(key) {
    const labels = {
        project_id: moduleT('perfatlas.ownerProjectId', 'Project ID'),
        site_id: moduleT('perfatlas.ownerSiteId', 'Site ID'),
        zone_id: moduleT('perfatlas.ownerZoneId', 'Zone ID'),
        framework: moduleT('perfatlas.ownerFramework', 'Framework'),
        custom_domain: moduleT('perfatlas.ownerCustomDomain', 'Custom domain'),
        production_branch: moduleT('perfatlas.ownerProductionBranch', 'Production branch'),
        build_command: moduleT('perfatlas.ownerBuildCommand', 'Build command'),
        publish_dir: moduleT('perfatlas.ownerPublishDir', 'Publish dir'),
        published_deploy: moduleT('perfatlas.ownerPublishedDeploy', 'Published deploy'),
        production_domain_count: moduleT('perfatlas.ownerProductionDomains', 'Production domains'),
        recent_non_ready_count: moduleT('perfatlas.ownerRecentNonReady', 'Recent non-ready deploys'),
        snippet_count: moduleT('perfatlas.ownerSnippetCount', 'Injected snippets'),
        snippet_head_count: moduleT('perfatlas.ownerHeadSnippets', 'Head snippets'),
        snippet_footer_count: moduleT('perfatlas.ownerFooterSnippets', 'Footer snippets'),
        snippet_script_count: moduleT('perfatlas.ownerScriptSnippets', 'Script snippets'),
    };
    if (labels[key]) return labels[key];
    return String(key || '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
}

function renderPerfAtlasOwnerKeyValueGrid(context) {
    if (!context || typeof context !== 'object') return '';
    const keys = [
        'project_id',
        'site_id',
        'zone_id',
        'framework',
        'custom_domain',
        'production_branch',
        'build_command',
        'publish_dir',
        'published_deploy',
        'production_domain_count',
        'recent_non_ready_count',
        'snippet_count',
        'snippet_head_count',
        'snippet_footer_count',
        'snippet_script_count',
    ];
    const rows = keys
        .map(key => {
            const value = context[key];
            if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return '';
            return `
                <div class="perfatlas-owner-row">
                    <span>${escapeHtml(perfAtlasOwnerContextLabel(key))}</span>
                    <strong>${escapeHtml(String(value))}</strong>
                </div>
            `;
        })
        .filter(Boolean);
    if (!rows.length) return '';
    return `<div class="perfatlas-owner-grid">${rows.join('')}</div>`;
}

function renderPerfAtlasOwnerPills(title, values) {
    const items = Array.isArray(values)
        ? values.map(value => String(value || '').trim()).filter(Boolean)
        : [];
    if (!items.length) return '';
    return `
        <div class="perfatlas-owner-section">
            <div class="signalatlas-panel-kicker">${escapeHtml(title)}</div>
            <div class="perfatlas-owner-pill-list">
                ${items.map(value => `<span class="signalatlas-inline-chip">${escapeHtml(value)}</span>`).join('')}
            </div>
        </div>
    `;
}

function renderPerfAtlasPlatformSignals(signals) {
    if (!signals || typeof signals !== 'object') return '';
    const entries = Object.entries(signals)
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([key, value]) => `
            <div class="perfatlas-owner-row">
                <span>${escapeHtml(perfAtlasOwnerContextLabel(key))}</span>
                <strong>${escapeHtml(String(value))}</strong>
            </div>
        `);
    if (!entries.length) return '';
    return `
        <div class="perfatlas-owner-section">
            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.ownerPlatformSignals', 'Platform signals'))}</div>
            <div class="perfatlas-owner-grid">${entries.join('')}</div>
        </div>
    `;
}

function renderPerfAtlasRecentDeployments(items) {
    const deployments = Array.isArray(items) ? items.filter(item => item && typeof item === 'object') : [];
    if (!deployments.length) return '';
    return `
        <div class="perfatlas-owner-section">
            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.ownerRecentDeployments', 'Recent deployments'))}</div>
            <div class="perfatlas-owner-deploy-list">
                ${deployments.slice(0, 4).map(item => `
                    <article class="perfatlas-owner-deploy-card">
                        <div class="perfatlas-owner-deploy-top">
                            <strong>${escapeHtml(String(item.state || item.context || 'unknown'))}</strong>
                            <span>${escapeHtml(String(item.target || item.branch || item.context || 'default'))}</span>
                        </div>
                        ${(item.url || item.deploy_url)
                            ? `<div class="perfatlas-owner-deploy-copy">${escapeHtml(String(item.url || item.deploy_url))}</div>`
                            : ''}
                        ${(item.created_at || item.published_at)
                            ? `<div class="perfatlas-owner-deploy-meta">${escapeHtml(String(item.created_at || item.published_at))}</div>`
                            : ''}
                    </article>
                `).join('')}
            </div>
        </div>
    `;
}

function renderPerfAtlasOwnerContext(audit) {
    const integrations = Array.isArray(audit?.owner_context?.integrations) ? audit.owner_context.integrations : [];
    if (!integrations.length) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.noOwnerContext', 'No owner context is attached to this audit.'))}</div>`;
    }
    return `
        <div class="signalatlas-detail-grid">
            ${integrations.map(item => `
                <section class="signalatlas-panel">
                    <div class="signalatlas-section-top">
                        <div>
                            <div class="signalatlas-panel-kicker">${escapeHtml(item.name || item.id || 'Integration')}</div>
                            <div class="signalatlas-panel-title">${escapeHtml(signalAtlasProviderStatusLabel(item.status || 'unknown'))}</div>
                        </div>
                        <span class="signalatlas-tag ${signalAtlasProviderTone(item.status)}">${escapeHtml(item.source || '')}</span>
                    </div>
                    <div class="signalatlas-panel-copy">${escapeHtml(perfAtlasProviderSummary(item))}</div>
                    ${item.context ? `
                        ${renderPerfAtlasOwnerKeyValueGrid(item.context)}
                        ${renderPerfAtlasOwnerPills(moduleT('perfatlas.ownerDomains', 'Domains'), item.context.domains)}
                        ${renderPerfAtlasOwnerPills(moduleT('perfatlas.ownerNameServers', 'Name servers'), item.context.name_servers)}
                        ${renderPerfAtlasOwnerPills(moduleT('perfatlas.ownerSnippetTitles', 'Snippet titles'), item.context.snippet_titles)}
                        ${renderPerfAtlasPlatformSignals(item.context.platform_signals)}
                        ${renderPerfAtlasRecentDeployments(item.context.recent_deployments)}
                        ${item.context.deployments_error
                            ? `<div class="signalatlas-panel-copy perfatlas-owner-warning">${escapeHtml(String(item.context.deployments_error))}</div>`
                            : ''}
                        ${item.context.settings_error
                            ? `<div class="signalatlas-panel-copy perfatlas-owner-warning">${escapeHtml(String(item.context.settings_error))}</div>`
                            : ''}
                    ` : ''}
                </section>
            `).join('')}
        </div>
    `;
}

function renderPerfAtlasAiTab(audit) {
    const latest = perfAtlasLatestInterpretation(audit);
    const compareModel = perfAtlasDraft.compare_model || fallbackPerfAtlasCompareModel();
    return `
        <div class="signalatlas-detail-grid">
            <section class="signalatlas-interpretation-card">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.aiInterpretation', 'AI interpretation'))}</div>
                        <div class="signalatlas-panel-title">${escapeHtml(latest?.model || moduleT('perfatlas.noAiGeneratedYet', 'No AI remediation yet'))}</div>
                    </div>
                    <div class="signalatlas-report-toolbar">
                        <button class="signalatlas-btn secondary" type="button" onclick="rerunPerfAtlasAi()">${escapeHtml(moduleT('perfatlas.rerunAi', 'Re-run AI'))}</button>
                        <button class="signalatlas-btn secondary" type="button" onclick="comparePerfAtlasAi()">${escapeHtml(moduleT('perfatlas.compareAi', 'Compare models'))}</button>
                        <button class="signalatlas-btn secondary" type="button" onclick="openPerfAtlasPromptInChat('${escapeHtml(audit.id || '')}')">${escapeHtml(moduleT('perfatlas.openPromptInChat', 'Open fix prompt in chat'))}</button>
                    </div>
                </div>
                <div class="signalatlas-field">
                    <label class="signalatlas-field-head">
                        ${renderSignalAtlasFieldLabel(
                            moduleT('perfatlas.compareModelLabel', 'Comparison model'),
                            moduleT('perfatlas.compareModelHelp', 'Choose the second model used for the side-by-side remediation comparison.')
                        )}
                    </label>
                    ${renderPerfAtlasPicker('compare_model', 'perfatlas-compare-model-select', perfAtlasPickerOptions('compare_model'), compareModel)}
                </div>
                ${latest?.content
                    ? `<div class="signalatlas-markdown-lite">${typeof formatMarkdown === 'function' ? formatMarkdown(latest.content) : escapeHtml(latest.content)}</div>`
                    : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.aiPending', 'Generate the first AI remediation pack when you want a dev-ready narrative.'))}</div>`}
            </section>
        </div>
    `;
}

function renderPerfAtlasExports(audit) {
    const formats = [
        ['json', moduleT('perfatlas.exportJson', 'JSON')],
        ['markdown', moduleT('perfatlas.exportMarkdown', 'Markdown')],
        ['prompt', moduleT('perfatlas.exportPrompt', 'AI prompt')],
        ['remediation', moduleT('perfatlas.exportRemediation', 'Remediation plan')],
        ['ci', moduleT('perfatlas.exportCiGate', 'CI gate')],
        ['evidence', moduleT('perfatlas.exportEvidencePack', 'Evidence pack')],
        ['pdf', moduleT('perfatlas.exportPdf', 'PDF')],
    ];
    return `
        <div class="perfatlas-export-grid">
            ${formats.map(([formatName, label]) => `
                <button class="signalatlas-btn secondary perfatlas-export-btn" type="button" onclick="downloadPerfAtlasExport('${escapeHtml(audit.id || '')}', '${escapeHtml(formatName)}')">
                    ${escapeHtml(label)}
                </button>
            `).join('')}
            <button class="signalatlas-btn perfatlas-export-btn" type="button" onclick="openPerfAtlasPromptInChat('${escapeHtml(audit.id || '')}')">
                ${escapeHtml(moduleT('perfatlas.openPromptInChat', 'Open fix prompt in chat'))}
            </button>
        </div>
    `;
}

function renderPerfAtlasOverview(audit) {
    const summary = audit?.summary || {};
    const reportModelInfo = perfAtlasReportModelInfo(audit);
    const scoreGuardrailMessage = perfAtlasScoreGuardrailMessage(summary);
    return `
        <div class="signalatlas-overview-stack">
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.quickRead', 'Quick read'))}</div>
                    <div class="signalatlas-panel-title">${escapeHtml(moduleT('perfatlas.executiveSummary', 'Executive summary'))}</div>
                    <div class="signalatlas-panel-copy">${escapeHtml(summary.target || '')}</div>
                    <div class="signalatlas-summary-badges">
                        <span class="signalatlas-inline-chip">${escapeHtml(summary.platform || 'Custom')}</span>
                        <span class="signalatlas-inline-chip">${escapeHtml(perfAtlasRuntimeLabel(summary.runtime_runner || 'unavailable'))}</span>
                        <span class="signalatlas-inline-chip">${escapeHtml(signalAtlasModeLabel(summary.mode || 'public'))}</span>
                    </div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.pagesSampled', 'Pages sampled'))}</span><strong>${escapeHtml(String(summary.pages_crawled || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.labPagesAnalyzed', 'Lab pages'))}</span><strong>${escapeHtml(String(summary.lab_pages_analyzed || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.fieldReady', 'Field ready'))}</span><strong>${escapeHtml(perfAtlasAvailabilityLabel(summary.field_data_available))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.labReady', 'Lab ready'))}</span><strong>${escapeHtml(perfAtlasAvailabilityLabel(summary.lab_data_available))}</strong></div>
                    </div>
                    ${scoreGuardrailMessage ? `<div class="signalatlas-panel-copy">${escapeHtml(scoreGuardrailMessage)}</div>` : ''}
                </section>
                <aside class="signalatlas-panel signalatlas-report-score-panel">
                    ${renderSignalAtlasScoreRing(summary.global_score, perfAtlasStatusLabel(audit?.status), `${audit?.id || 'perfatlas'}:${summary.global_score ?? '--'}`)}
                    <div class="signalatlas-model-used-card">
                        <div class="signalatlas-panel-kicker">${escapeHtml(reportModelInfo.state === 'generated'
                            ? moduleT('perfatlas.reportModelLabel', 'Report model')
                            : moduleT('perfatlas.requestedModelLabel', 'Requested model'))}</div>
                        <div class="signalatlas-model-used-value">${escapeHtml(reportModelInfo.label)}</div>
                        <div class="signalatlas-model-used-copy">${escapeHtml(reportModelInfo.detail)}</div>
                        ${reportModelInfo.meta ? `<div class="signalatlas-model-used-meta">${escapeHtml(reportModelInfo.meta)}</div>` : ''}
                    </div>
                </aside>
            </div>
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.scoreBreakdown', 'Score breakdown'))}</div>
                <div class="signalatlas-score-grid">${renderPerfAtlasScoreCards(audit)}</div>
            </section>
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.topPriorities', 'Top priorities'))}</div>
                <div class="signalatlas-finding-list">${renderPerfAtlasFindings(audit, 5)}</div>
            </section>
        </div>
    `;
}

function renderPerfAtlasTabContent(audit) {
    if (!audit) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.emptyWorkspace', 'Choose a domain or pick a past audit to start.'))}</div>`;
    }
    switch (perfAtlasActiveTab) {
        case 'field':
            return renderPerfAtlasFieldData(audit);
        case 'lab':
            return renderPerfAtlasLabRuns(audit);
        case 'opportunities':
            return `<div class="signalatlas-finding-list">${renderPerfAtlasFindings(audit, 12)}</div>`;
        case 'delivery':
            return renderPerfAtlasDelivery(audit);
        case 'resources':
            return renderPerfAtlasResources(audit);
        case 'intelligence':
            return renderPerfAtlasIntelligence(audit);
        case 'owner':
            return renderPerfAtlasOwnerContext(audit);
        case 'ai':
            return renderPerfAtlasAiTab(audit);
        case 'exports':
            return renderPerfAtlasExports(audit);
        default:
            return renderPerfAtlasOverview(audit);
    }
}

function renderPerfAtlasHistory() {
    if (!perfAtlasAudits.length) {
        return `<div class="signalatlas-history-empty">${escapeHtml(moduleT('perfatlas.noAudits', 'No audits yet. Launch one to create your first performance report.'))}</div>`;
    }
    return perfAtlasAudits.map(audit => {
        const active = audit.id === perfAtlasCurrentAuditId;
        const progressState = perfAtlasAuditProgressState(audit);
        const isLive = signalAtlasIsLiveProgressStatus(progressState?.status || '');
        const displayProgress = progressState ? auditDisplayProgress('perfatlas', progressState, audit, false) : 0;
        const supportCopy = progressState ? perfAtlasProgressSupportCopy(progressState) : '';
        const auditTimestamp = nativeAuditTimestampLabel('perfatlas', audit);
        return `
            <div
                class="signalatlas-history-card${active ? ' active' : ''}"
                role="button"
                tabindex="0"
                onclick="openPerfAtlasWorkspace('${escapeHtml(audit.id)}')"
                onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openPerfAtlasWorkspace('${escapeHtml(audit.id)}');}"
            >
                <div class="signalatlas-history-top">
                    <div class="signalatlas-history-title-wrap">
                        <div class="signalatlas-history-title">${escapeHtml(audit.title || audit.host || audit.target_url || 'Audit')}</div>
                        <div class="signalatlas-history-status">${escapeHtml(perfAtlasStatusLabel(audit.status))}</div>
                    </div>
                    <button
                        class="signalatlas-history-delete"
                        type="button"
                        onclick="deletePerfAtlasAudit('${escapeHtml(audit.id)}', event)"
                        aria-label="${escapeHtml(moduleT('perfatlas.deleteAudit', 'Delete audit'))}"
                        title="${escapeHtml(moduleT('perfatlas.deleteAudit', 'Delete audit'))}"
                    >
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
                <div class="signalatlas-history-meta">
                    <span>${escapeHtml(audit.host || '')}</span>
                    <span>${escapeHtml(audit.mode || 'public')}</span>
                </div>
                ${auditTimestamp ? `<div class="signalatlas-history-timestamp">${escapeHtml(auditTimestamp)}</div>` : ''}
                <div class="signalatlas-history-footer">
                    <span>${escapeHtml(moduleT('perfatlas.scoreShort', 'Score'))}: ${escapeHtml(String(audit.global_score ?? '--'))}</span>
                    <span>${escapeHtml(String(audit.lab_pages_analyzed || 0))} ${escapeHtml(moduleT('perfatlas.labPagesShort', 'lab'))}</span>
                </div>
                ${progressState ? `
                    <div class="signalatlas-history-progress-meta">
                        <span class="signalatlas-progress-chip is-phase">${escapeHtml(progressState.phase)}</span>
                        <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT('perfatlas.progressPercent', '{value}%', { value: displayProgress }))}</span>
                    </div>
                    <div class="signalatlas-history-progress-bar${isLive ? ' is-live' : ''}">
                        <div class="signalatlas-history-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(displayProgress))}%"></div>
                    </div>
                    <div class="signalatlas-history-progress-copy${isLive ? ' signalatlas-shimmer-text' : ''}" aria-live="polite">${escapeHtml(progressState.message)}</div>
                    <div class="signalatlas-history-progress-detail">${escapeHtml(supportCopy)}</div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function togglePerfAtlasAdvancedSettings() {
    perfAtlasAdvancedVisible = !perfAtlasAdvancedVisible;
    if (isPerfAtlasVisible()) renderPerfAtlasWorkspace();
}

function setPerfAtlasTab(tabId) {
    perfAtlasActiveTab = String(tabId || 'overview');
    renderPerfAtlasWorkspace();
}

function renderPerfAtlasWorkspace() {
    syncPerfAtlasDraftFromDom();
    const host = document.getElementById('perfatlas-view-content');
    if (!host) return;
    const audit = perfAtlasCurrentAudit;
    const summary = audit?.summary || {};
    const progressState = perfAtlasAuditProgressState(audit) || perfAtlasAnyProgressState();
    const displayProgress = auditDisplayProgress('perfatlas', progressState, audit, perfAtlasLaunchPending);
    const progressStatus = String(progressState?.status || '').toLowerCase();
    const canCancelAudit = !!progressState && ['queued', 'running', 'cancelling'].includes(progressStatus);
    ensurePerfAtlasRuntimeJobForProgress(progressState);
    const targetValidation = perfAtlasValidateTarget(perfAtlasDraft.target);
    const reportModelInfo = perfAtlasReportModelInfo(audit);
    const selectedProfile = perfAtlasDraft.profile || 'elevated';
    const tabs = [
        ['overview', moduleT('perfatlas.tabOverview', 'Overview')],
        ['field', moduleT('perfatlas.tabField', 'Field')],
        ['lab', moduleT('perfatlas.tabLab', 'Lab')],
        ['opportunities', moduleT('perfatlas.tabOpportunities', 'Opportunities')],
        ['delivery', moduleT('perfatlas.tabDelivery', 'Delivery')],
        ['resources', moduleT('perfatlas.tabResources', 'Resources')],
        ['intelligence', moduleT('perfatlas.tabIntelligence', 'Intelligence')],
        ['owner', moduleT('perfatlas.tabOwner', 'Owner context')],
        ['ai', moduleT('perfatlas.tabAi', 'AI')],
        ['exports', moduleT('perfatlas.tabExports', 'Exports')],
    ];
    if (!tabs.some(([id]) => id === perfAtlasActiveTab)) {
        perfAtlasActiveTab = 'overview';
    }

    host.innerHTML = `
        <div class="signalatlas-shell perfatlas-shell">
            <section class="signalatlas-control-surface perfatlas-control-surface">
                <div class="signalatlas-input-row">
                    <input id="perfatlas-target-input" class="signalatlas-target-input${targetValidation.present && !targetValidation.valid ? ' is-invalid' : ''}" type="text" value="${escapeHtml(perfAtlasDraft.target)}" placeholder="${escapeHtml(moduleT('perfatlas.targetPlaceholder', 'Example: https://nevomove.com/'))}" oninput="perfAtlasTargetInputChanged(event)" onblur="perfAtlasControlsChanged()" aria-invalid="${targetValidation.present && !targetValidation.valid ? 'true' : 'false'}" inputmode="url" autocapitalize="off" spellcheck="false">
                    ${canCancelAudit ? `
                        <button
                            id="perfatlas-launch-btn"
                            class="signalatlas-btn launch signalatlas-stop-btn"
                            type="button"
                            data-action="cancel"
                            onclick="cancelPerfAtlasAudit('${escapeHtml(progressState?.auditId || perfAtlasCurrentAuditId || '')}')"
                            aria-label="${escapeHtml(progressStatus === 'cancelling' ? moduleT('perfatlas.cancelling', 'Cancelling...') : moduleT('perfatlas.cancelAudit', 'Cancel audit'))}"
                            title="${escapeHtml(progressStatus === 'cancelling' ? moduleT('perfatlas.cancelling', 'Cancelling...') : moduleT('perfatlas.cancelAudit', 'Cancel audit'))}"
                            ${progressStatus === 'cancelling' ? 'disabled' : ''}
                        >
                            <i data-lucide="square"></i>
                        </button>
                    ` : `
                        <button id="perfatlas-launch-btn" class="signalatlas-btn" type="button" data-action="launch" onclick="launchPerfAtlasAudit()" ${perfAtlasLaunchPending || !targetValidation.valid ? 'disabled' : ''}>${escapeHtml(moduleT('perfatlas.runAudit', 'Launch audit'))}</button>
                    `}
                    <div id="perfatlas-target-feedback" class="signalatlas-target-feedback${targetValidation.present && !targetValidation.valid ? ' is-visible' : ''}">${escapeHtml(targetValidation.present && !targetValidation.valid ? targetValidation.message : '')}</div>
                </div>
                <div class="signalatlas-primary-grid">
                    <div class="signalatlas-field">
                        <label class="signalatlas-field-head">
                            ${renderSignalAtlasFieldLabel(moduleT('perfatlas.profileLabel', 'Audit level'), moduleT('perfatlas.profileHelp', 'Choose how far PerfAtlas pushes the representative sampling, lab probing, and AI remediation layer.'))}
                        </label>
                        ${renderPerfAtlasPicker('profile', 'perfatlas-profile-select', perfAtlasPickerOptions('profile'), selectedProfile)}
                    </div>
                    <div class="signalatlas-field">
                        <label class="signalatlas-field-head">
                            ${renderSignalAtlasFieldLabel(moduleT('perfatlas.modelLabel', 'Model'), moduleT('perfatlas.modelHelp', 'Choose which JoyBoy model interprets the deterministic PerfAtlas findings.'))}
                        </label>
                        ${renderPerfAtlasPicker('model', 'perfatlas-model-select', perfAtlasPickerOptions('model'), perfAtlasDraft.model || currentJoyBoyChatModel())}
                    </div>
                    <div class="signalatlas-field signalatlas-field-action">
                        <button class="signalatlas-advanced-toggle${perfAtlasAdvancedVisible ? ' is-open' : ''}" type="button" onclick="togglePerfAtlasAdvancedSettings()">
                            <span>${escapeHtml(perfAtlasAdvancedVisible ? moduleT('perfatlas.advancedSettingsClose', 'Hide customization') : moduleT('perfatlas.advancedSettingsOpen', 'Customize'))}</span>
                            <i data-lucide="${perfAtlasAdvancedVisible ? 'chevron-up' : 'chevron-down'}"></i>
                        </button>
                    </div>
                </div>
                ${perfAtlasAdvancedVisible ? `
                    <div class="signalatlas-advanced-panel">
                        <div class="signalatlas-controls-grid">
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(moduleT('perfatlas.auditMode', 'Audit mode'), moduleT('perfatlas.modeHelp', 'Public mode uses open signals only. Verified owner enriches the report with deployment and platform context when the connectors match.'))}
                                </label>
                                ${renderPerfAtlasPicker('mode', 'perfatlas-mode-select', perfAtlasPickerOptions('mode'), perfAtlasDraft.mode)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(moduleT('perfatlas.maxPages', 'Sampling budget'), moduleT('perfatlas.pageBudgetHint', 'Representative pages sampled for delivery, resource, and template analysis.'))}
                                </label>
                                ${renderPerfAtlasPicker('max_pages', 'perfatlas-max-pages', perfAtlasPickerOptions('max_pages'), perfAtlasDraft.max_pages)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(moduleT('perfatlas.presetLabel', 'Preset'), moduleT('perfatlas.presetHelp', 'Controls how much effort the model spends on the interpretation layer.'))}
                                </label>
                                ${renderPerfAtlasPicker('preset', 'perfatlas-preset-select', perfAtlasPickerOptions('preset'), perfAtlasDraft.preset)}
                            </div>
                            <div class="signalatlas-field">
                                <label class="signalatlas-field-head">
                                    ${renderSignalAtlasFieldLabel(moduleT('perfatlas.levelLabel', 'AI level'), moduleT('perfatlas.levelHelp', 'Choose whether the AI returns a concise summary, a full expert analysis, or a remediation pack.'))}
                                </label>
                                ${renderPerfAtlasPicker('level', 'perfatlas-level-select', perfAtlasPickerOptions('level'), perfAtlasDraft.level)}
                            </div>
                        </div>
                    </div>
                ` : ''}
                ${renderAuditProgressBanner({
                    namespace: 'perfatlas',
                    progressState,
                    launchPending: perfAtlasLaunchPending,
                    displayProgress,
                    targetLabel: perfAtlasDraft.target,
                    statusLabel: perfAtlasStatusLabel,
                    supportCopy: perfAtlasProgressSupportCopy(progressState, perfAtlasDraft.target),
                    launchingLabel: moduleT('perfatlas.launching', 'Launching'),
                    launchingMessage: moduleT('perfatlas.launchingAudit', 'Starting the performance runtime...'),
                    etaLabel: perfAtlasProgressEtaLabel(progressState, audit, displayProgress),
                })}
            </section>

            ${renderPerfAtlasProviderStrip()}

            <section class="signalatlas-report-panel signalatlas-report-panel-wide">
                <div class="signalatlas-section-top signalatlas-report-heading">
                    <div class="signalatlas-report-heading-copy">
                        <div>
                            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.workspace', 'Report'))}</div>
                            <div class="signalatlas-panel-title">${escapeHtml(audit?.title || moduleT('perfatlas.selectAudit', 'Select or launch an audit'))}</div>
                            ${audit ? `<div class="signalatlas-panel-copy signalatlas-report-heading-copytext">${escapeHtml(moduleT('perfatlas.reportHeaderCopy', 'Start with the overview, then move into field, lab, and owner context when you want implementation detail.'))}</div>` : ''}
                        </div>
                    </div>
                    ${audit ? `
                        <div class="signalatlas-report-toolbar">
                            <button class="signalatlas-btn secondary" type="button" onclick="refreshPerfAtlasWorkspace()">${escapeHtml(moduleT('common.refresh', 'Refresh'))}</button>
                            <button class="signalatlas-report-download" type="button" onclick="downloadPerfAtlasExport('${escapeHtml(audit.id)}', 'markdown')">
                                <span class="signalatlas-report-download-icon"><i data-lucide="download-cloud"></i></span>
                                <span class="signalatlas-report-download-copy">
                                    <strong>${escapeHtml(moduleT('perfatlas.exportForAi', 'Export for an AI'))}</strong>
                                    <small>${escapeHtml(moduleT('perfatlas.exportForAiMeta', 'Markdown ready to hand off'))}</small>
                                </span>
                            </button>
                        </div>
                    ` : ''}
                </div>
                <div class="signalatlas-drawer-panel">
                    <div class="signalatlas-section-top">
                        <div>
                            <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.auditHistory', 'Audit history'))}</div>
                            <div class="signalatlas-panel-title">${escapeHtml(moduleT('perfatlas.recentRuns', 'Recent runs'))}</div>
                        </div>
                    </div>
                    <div class="signalatlas-history-list">${renderPerfAtlasHistory()}</div>
                </div>
                ${audit ? `
                    <div class="signalatlas-tabs">
                        ${tabs.map(([id, label]) => `<button class="signalatlas-tab${perfAtlasActiveTab === id ? ' active' : ''}" type="button" onclick="setPerfAtlasTab('${id}')">${escapeHtml(label)}</button>`).join('')}
                    </div>
                    <div class="signalatlas-tab-panel">
                        ${renderPerfAtlasTabContent(audit)}
                    </div>
                ` : `
                    <div class="signalatlas-empty-panel">${escapeHtml(moduleT('perfatlas.emptyWorkspace', 'Choose a domain or an existing audit to begin.'))}</div>
                `}
            </section>
        </div>
    `;
    if (window.lucide) lucide.createIcons({ nodes: [host] });
    hydrateSignalAtlasMotion(host);
    renderPerfAtlasTargetValidationUi();
}

async function openPerfAtlasWorkspace(auditId = null) {
    if (auditId) perfAtlasCurrentAuditId = auditId;
    hideModulesWorkspaces();
    applyModulesShellMode('sidebar-modules-btn', 'perfatlas-mode');
    const view = getPerfAtlasView();
    if (view) view.style.display = 'flex';
    await loadPerfAtlasBootstrap();
    renderPerfAtlasWorkspace();
    startPerfAtlasRefresh();
}

async function launchPerfAtlasAudit() {
    syncPerfAtlasDraftFromDom();
    const targetValidation = perfAtlasValidateTarget(perfAtlasDraft.target);
    if (!targetValidation.present) {
        Toast?.warning?.(moduleT('perfatlas.targetRequired', 'Add a real domain or public URL first, for example https://nevomove.com/.'));
        renderPerfAtlasTargetValidationUi();
        return;
    }
    if (!targetValidation.valid) {
        Toast?.warning?.(moduleT('perfatlas.targetInvalid', 'Use a real domain or full public URL, for example https://nevomove.com/.'));
        renderPerfAtlasTargetValidationUi();
        return;
    }
    perfAtlasLaunchPending = true;
    renderPerfAtlasWorkspace();
    const payload = {
        target: String(perfAtlasDraft.target || '').trim(),
        mode: perfAtlasDraft.mode || 'public',
        options: {
            max_pages: perfAtlasResolvedPageBudget(perfAtlasDraft.max_pages, PERFATLAS_DEFAULT_PAGE_BUDGET),
        },
        ai: {
            model: perfAtlasDraft.model || currentJoyBoyChatModel(),
            preset: perfAtlasDraft.preset || 'balanced',
            level: perfAtlasDraft.level || 'full_expert_analysis',
        },
    };
    try {
        const result = await apiPerfAtlas.createAudit(payload);
        if (!result.ok) {
            Toast?.error?.(result.data?.error || moduleT('perfatlas.auditCreateFailed', 'Unable to launch the audit.'));
            return;
        }
        perfAtlasCurrentAuditId = result.data?.audit?.id || perfAtlasCurrentAuditId;
        perfAtlasCurrentAudit = result.data?.audit || perfAtlasCurrentAudit;
        if (result.data?.job) seedPerfAtlasRuntimeJob(result.data.job, perfAtlasCurrentAuditId);
        await loadPerfAtlasBootstrap();
        if (perfAtlasCurrentAuditId) {
            await loadPerfAtlasAudit(perfAtlasCurrentAuditId, { silent: true });
        }
        renderPerfAtlasWorkspace();
        startPerfAtlasRefresh();
        Toast?.success?.(moduleT('perfatlas.auditStarted', 'PerfAtlas audit started.'));
    } finally {
        perfAtlasLaunchPending = false;
    }
    if (isPerfAtlasVisible()) renderPerfAtlasWorkspace();
}

async function deletePerfAtlasAudit(auditId = '', event = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const targetAuditId = String(auditId || '').trim();
    if (!targetAuditId) return;
    const progressState = perfAtlasAuditProgressState(targetAuditId);
    if (progressState) {
        Toast?.warning?.(moduleT('perfatlas.deleteAuditBlocked', 'Cancel this audit before deleting it.'));
        return;
    }
    const audit = (perfAtlasAudits || []).find(item => String(item?.id || '') === targetAuditId);
    const title = audit?.title || audit?.host || moduleT('perfatlas.auditItem', 'this audit');
    const confirmed = await JoyDialog.confirm(
        moduleT('perfatlas.deleteAuditConfirm', 'Delete {title} permanently?', { title }),
        { variant: 'danger' }
    );
    if (!confirmed) return;
    const result = await apiPerfAtlas.deleteAudit(targetAuditId);
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('perfatlas.deleteAuditFailed', 'Unable to delete this audit.'));
        return;
    }
    perfAtlasAudits = (perfAtlasAudits || []).filter(item => String(item?.id || '') !== targetAuditId);
    if (String(perfAtlasCurrentAuditId || '') === targetAuditId) {
        perfAtlasCurrentAuditId = perfAtlasAudits[0]?.id || null;
        perfAtlasCurrentAudit = null;
    }
    await loadPerfAtlasBootstrap();
    if (perfAtlasCurrentAuditId) {
        await loadPerfAtlasAudit(perfAtlasCurrentAuditId, { silent: true });
    }
    renderPerfAtlasWorkspace();
    Toast?.success?.(moduleT('perfatlas.deleteAuditSuccess', 'Audit deleted.'));
}

async function cancelPerfAtlasAudit(auditId = '') {
    const targetAuditId = String(auditId || perfAtlasCurrentAuditId || '').trim();
    if (!targetAuditId || typeof apiRuntime === 'undefined') return;
    const progressState = perfAtlasAuditProgressState(targetAuditId);
    const jobId = String(progressState?.job?.id || `perfatlas-audit-${targetAuditId}`).trim();
    if (!jobId) return;

    const result = await apiRuntime.cancelJob(jobId, {});
    if (!result.ok || !result.data?.job) {
        Toast?.error?.(result.data?.error || moduleT('perfatlas.cancelAuditFailed', 'Unable to cancel this audit.'));
        return;
    }

    seedPerfAtlasRuntimeJob(result.data.job, targetAuditId);
    if (perfAtlasCurrentAudit && String(perfAtlasCurrentAudit.id || '') === targetAuditId) {
        perfAtlasCurrentAudit.status = String(result.data.job.status || 'cancelling').toLowerCase();
    }
    Toast?.success?.(moduleT('perfatlas.cancelAuditRequested', 'Cancellation requested.'));
    await refreshPerfAtlasWorkspace();
}

async function rerunPerfAtlasAi() {
    if (!perfAtlasCurrentAuditId) return;
    syncPerfAtlasDraftFromDom();
    const payload = {
        model: perfAtlasDraft.model || currentJoyBoyChatModel(),
        preset: perfAtlasDraft.preset || 'balanced',
        level: perfAtlasDraft.level || 'full_expert_analysis',
    };
    const result = await apiPerfAtlas.rerunAi(perfAtlasCurrentAuditId, payload);
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('perfatlas.rerunFailed', 'Unable to re-run the AI remediation.'));
        return;
    }
    if (result.data?.job) seedPerfAtlasRuntimeJob(result.data.job, perfAtlasCurrentAuditId);
    renderPerfAtlasWorkspace();
    startPerfAtlasRefresh();
    Toast?.success?.(moduleT('perfatlas.rerunStarted', 'AI remediation started.'));
}

async function comparePerfAtlasAi() {
    if (!perfAtlasCurrentAuditId) return;
    syncPerfAtlasDraftFromDom();
    const leftModel = perfAtlasDraft.model || currentJoyBoyChatModel();
    const rightModel = perfAtlasDraft.compare_model || fallbackPerfAtlasCompareModel();
    const result = await apiPerfAtlas.compareAi(perfAtlasCurrentAuditId, {
        left_model: leftModel,
        right_model: rightModel,
        preset: perfAtlasDraft.preset || 'expert',
        level: perfAtlasDraft.level || 'full_expert_analysis',
    });
    if (!result.ok) {
        Toast?.error?.(result.data?.error || moduleT('perfatlas.compareFailed', 'Unable to compare remediation outputs.'));
        return;
    }
    if (result.data?.job) seedPerfAtlasRuntimeJob(result.data.job, perfAtlasCurrentAuditId);
    renderPerfAtlasWorkspace();
    startPerfAtlasRefresh();
    Toast?.success?.(moduleT('perfatlas.compareStarted', 'PerfAtlas comparison started.'));
}

function downloadPerfAtlasExport(auditId, formatName) {
    if (!auditId) return;
    window.location.href = `/api/perfatlas/audits/${encodeURIComponent(auditId)}/export/${encodeURIComponent(formatName)}`;
}

async function openPerfAtlasPromptInChat(auditId) {
    if (!auditId) return;
    const result = await apiPerfAtlas.fetchExportText(auditId, 'prompt');
    if (!result.ok) {
        Toast?.error?.(moduleT('perfatlas.promptLoadFailed', 'Unable to load the AI-fix prompt.'));
        return;
    }
    if (typeof createNewChat === 'function') {
        await createNewChat();
    }
    if (typeof showChat === 'function') showChat();
    const input = document.getElementById('chat-prompt');
    if (input) {
        input.value = result.data || '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
    }
}

async function refreshPerfAtlasWorkspace() {
    await loadPerfAtlasBootstrap();
    if (perfAtlasCurrentAuditId) {
        await loadPerfAtlasAudit(perfAtlasCurrentAuditId, { silent: true });
    }
    renderPerfAtlasWorkspace();
}

function startPerfAtlasRefresh() {
    stopPerfAtlasRefresh();
    perfAtlasRefreshTimer = setInterval(async () => {
        if (!isPerfAtlasVisible()) {
            stopPerfAtlasRefresh();
            return;
        }
        if (perfAtlasRefreshInFlight) return;
        perfAtlasRefreshInFlight = true;
        try {
            await refreshPerfAtlasWorkspace();
        } finally {
            perfAtlasRefreshInFlight = false;
        }
        if (!perfAtlasAnyProgressState()) {
            stopPerfAtlasRefresh();
        }
    }, 3500);
}

function stopPerfAtlasRefresh() {
    if (perfAtlasRefreshTimer) {
        clearInterval(perfAtlasRefreshTimer);
        perfAtlasRefreshTimer = null;
    }
    perfAtlasRefreshInFlight = false;
}

window.addEventListener('joyboy:locale-changed', () => {
    if (getModulesView()?.style.display !== 'none') renderModulesHub();
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
    if (isPerfAtlasVisible()) renderPerfAtlasWorkspace();
    window.renderCyberAtlasWorkspace?.();
    window.renderDeployAtlasWorkspace?.();
});

window.addEventListener('click', (event) => {
    if (event.target?.closest?.('.signalatlas-picker')) return;
    if (signalAtlasOpenPickerId) closeSignalAtlasPicker();
    if (perfAtlasOpenPickerId) closeAuditPicker('perfatlas');
    window.closeCyberAtlasPicker?.();
    window.closeDeployAtlasPicker?.();
});

window.addEventListener('joyboy:runtime-jobs-updated', () => {
    if (getModulesView()?.style.display !== 'none') renderModulesHub();
    if (isSignalAtlasVisible() && !signalAtlasOpenPickerId) {
        if (signalAtlasShouldDeferRefresh()) {
            signalAtlasPendingRefresh = true;
            scheduleSignalAtlasDeferredRefresh();
        } else {
            renderSignalAtlasWorkspace();
        }
        startSignalAtlasRefresh();
    }
    if (isPerfAtlasVisible() && !perfAtlasOpenPickerId) {
        renderPerfAtlasWorkspace();
        startPerfAtlasRefresh();
    }
    window.handleCyberAtlasRuntimeJobsUpdated?.();
    if (document.body.classList.contains('deployatlas-mode')) window.refreshDeployAtlasWorkspace?.();
});

window.openModulesHub = openModulesHub;
window.openNativeModule = openNativeModule;
window.openAuditModuleWorkspace = openAuditModuleWorkspace;
window.openSignalAtlasWorkspace = openSignalAtlasWorkspace;
window.openPerfAtlasWorkspace = openPerfAtlasWorkspace;
window.setSignalAtlasTab = setSignalAtlasTab;
window.setPerfAtlasTab = setPerfAtlasTab;
window.signalAtlasControlsChanged = signalAtlasControlsChanged;
window.perfAtlasControlsChanged = perfAtlasControlsChanged;
window.launchSignalAtlasAudit = launchSignalAtlasAudit;
window.launchPerfAtlasAudit = launchPerfAtlasAudit;
window.rerunSignalAtlasAi = rerunSignalAtlasAi;
window.rerunPerfAtlasAi = rerunPerfAtlasAi;
window.compareSignalAtlasAi = compareSignalAtlasAi;
window.comparePerfAtlasAi = comparePerfAtlasAi;
window.refreshSignalAtlasWorkspace = refreshSignalAtlasWorkspace;
window.refreshPerfAtlasWorkspace = refreshPerfAtlasWorkspace;
window.downloadSignalAtlasExport = downloadSignalAtlasExport;
window.downloadPerfAtlasExport = downloadPerfAtlasExport;
window.openSignalAtlasPromptInChat = openSignalAtlasPromptInChat;
window.openPerfAtlasPromptInChat = openPerfAtlasPromptInChat;
window.toggleSignalAtlasPicker = toggleSignalAtlasPicker;
window.togglePerfAtlasPicker = togglePerfAtlasPicker;
window.toggleCyberAtlasPicker = toggleCyberAtlasPicker;
window.selectSignalAtlasPickerOption = selectSignalAtlasPickerOption;
window.selectPerfAtlasPickerOption = selectPerfAtlasPickerOption;
window.signalAtlasTargetInputChanged = signalAtlasTargetInputChanged;
window.perfAtlasTargetInputChanged = perfAtlasTargetInputChanged;
window.toggleSignalAtlasAdvancedSettings = toggleSignalAtlasAdvancedSettings;
window.togglePerfAtlasAdvancedSettings = togglePerfAtlasAdvancedSettings;
window.toggleSignalAtlasHistoryDrawer = toggleSignalAtlasHistoryDrawer;
window.toggleSignalAtlasSeoDetails = toggleSignalAtlasSeoDetails;
window.downloadSignalAtlasAiReport = downloadSignalAtlasAiReport;
window.cancelSignalAtlasAudit = cancelSignalAtlasAudit;
window.deleteSignalAtlasAudit = deleteSignalAtlasAudit;
window.cancelPerfAtlasAudit = cancelPerfAtlasAudit;
window.deletePerfAtlasAudit = deletePerfAtlasAudit;
