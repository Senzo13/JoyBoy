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
const signalAtlasAnimatedScoreRingKeys = new Set();
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
            message: moduleT('signalatlas.targetRequired', 'Add a real domain or public URL first, for example https://nevomove.com/.'),
        };
    }

    const candidate = raw.includes('://') ? raw : `https://${raw}`;
    let parsed = null;
    try {
        parsed = new URL(candidate);
    } catch (error) {
        parsed = null;
    }

    const invalidMessage = moduleT('signalatlas.targetInvalid', 'Use a real domain or full public URL, for example https://nevomove.com/.');
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
    if (clean === 'target_mismatch') return moduleT('signalatlas.providerTargetMismatch', 'Target mismatch');
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
            return moduleT('signalatlas.providerSummaryGscConfirmed', 'Owner-mode confirmation is available for this target through Search Console.');
        }
        if (status === 'configured') {
            return moduleT('signalatlas.providerSummaryGscConfigured', 'Search Console is configured and ready for a verified-owner audit on a matching property.');
        }
        if (status === 'target_mismatch') {
            return moduleT('signalatlas.providerSummaryGscMismatch', 'Search Console is configured, but the saved property does not match the current target yet.');
        }
        if (status === 'connector_missing') {
            return moduleT('signalatlas.providerSummaryConnectorMissing', 'The provider is configured, but the required Python client package is not available in this runtime.');
        }
        return moduleT('signalatlas.providerSummaryGscMissing', 'Connect an official property to move Google-specific data from estimated to confirmed.');
    }
    if (status === 'configured') {
        return moduleT('signalatlas.providerSummaryConfigured', 'This integration is configured and can enrich relevant future audit layers.');
    }
    return moduleT('signalatlas.providerSummaryScaffolded', 'This integration is scaffolded in the architecture and will enrich later owner-mode passes.');
}

function signalAtlasRenderSummary(renderDetection = {}) {
    if (!renderDetection.render_js_requested) {
        return moduleT('signalatlas.renderSummaryNotRequested', 'Raw HTML baseline only.');
    }
    if (renderDetection.render_js_executed) {
        return moduleT('signalatlas.renderSummaryExecuted', 'JS render probes executed on {count} page(s).', {
            count: renderDetection.executed_page_count || 0,
        });
    }
    return moduleT('signalatlas.renderSummaryUnavailable', 'JS rendering was requested but could not run.');
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
        return moduleT('signalatlas.auditProfileUltraDesc', 'Passe la plus poussée: crawl large, rendu JS et pack IA complet.');
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
    return facts.slice(0, 4);
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
            return moduleT('signalatlas.visibilityNote_geo_strong', 'The site exposes strong public AI-visibility signals such as llms.txt or rich structured data coverage.');
        }
        if (status === 'partial signal') {
            return moduleT('signalatlas.visibilityNote_geo_partial', 'Some AI-visibility signals are present, but the public GEO surface is still partial.');
        }
        return moduleT('signalatlas.visibilityNote_geo_unknown', 'No strong public GEO signal was detected yet in this audit pass.');
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
                    <span>${escapeHtml(String(page.word_count || 0))} ${escapeHtml(moduleT('signalatlas.words', 'Words'))}</span>
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

function signalAtlasRuntimeJobs() {
    if (typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return [];
    return runtimeJobsCache.filter(job => job?.metadata?.module_id === 'signalatlas');
}

function activeSignalAtlasJobs() {
    return signalAtlasRuntimeJobs()
        .filter(signalAtlasIsActiveJob)
        .sort((left, right) => String(right?.updated_at || '').localeCompare(String(left?.updated_at || '')));
}

function signalAtlasJobProgress(job) {
    const value = Number(job?.progress ?? 0);
    if (Number.isFinite(value)) return Math.max(0, Math.min(100, Math.round(value)));
    return 0;
}

function signalAtlasJobPhaseLabel(phase) {
    const clean = String(phase || '').trim().toLowerCase();
    if (clean === 'crawl') return moduleT('signalatlas.phaseCrawl', 'Crawl');
    if (clean === 'render') return moduleT('signalatlas.phaseRender', 'JS render');
    if (clean === 'extract') return moduleT('signalatlas.phaseExtract', 'Extraction');
    if (clean === 'score') return moduleT('signalatlas.phaseScore', 'Scoring');
    if (clean === 'report') return moduleT('signalatlas.phaseReport', 'Report');
    if (clean === 'ai') return moduleT('signalatlas.phaseAi', 'AI interpretation');
    if (clean === 'queued') return moduleT('signalatlas.phaseQueued', 'Queued');
    if (clean === 'cancelling') return moduleT('signalatlas.phaseCancelling', 'Cancelling');
    if (clean === 'cancelled') return moduleT('signalatlas.phaseCancelled', 'Cancelled');
    if (clean === 'done') return moduleT('signalatlas.phaseDone', 'Done');
    if (clean === 'error') return moduleT('signalatlas.phaseError', 'Error');
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
    return fallbackHint || moduleT('signalatlas.backgroundResumeHint', 'This audit keeps running if you leave the view.');
}

function signalAtlasAuditProgressState(audit) {
    const auditId = typeof audit === 'string' ? audit : audit?.id;
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
    const currentStatus = String((typeof audit === 'object' && audit?.status) || '').toLowerCase();
    if (currentStatus === 'running' || currentStatus === 'queued') {
        return {
            job: null,
            auditId,
            status: currentStatus,
            phase: signalAtlasJobPhaseLabel(currentStatus),
            progress: currentStatus === 'running' ? 8 : 2,
            message: currentStatus === 'running'
                ? moduleT('signalatlas.auditRunning', 'Audit running...')
                : moduleT('signalatlas.phaseQueued', 'Queued'),
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
    return String(moduleId || '').trim().toLowerCase() === 'perfatlas'
        ? perfAtlasOpenPickerId
        : signalAtlasOpenPickerId;
}

function setAuditPickerState(moduleId, value) {
    if (String(moduleId || '').trim().toLowerCase() === 'perfatlas') {
        perfAtlasOpenPickerId = value;
        return;
    }
    signalAtlasOpenPickerId = value;
}

function rerenderAuditWorkspace(moduleId) {
    if (String(moduleId || '').trim().toLowerCase() === 'perfatlas') {
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

function buildSignalAtlasModelOptions(selectedValue = '') {
    const profiles = signalAtlasCurrentProfiles();
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
                description: moduleT('signalatlas.auditProfileUltraDesc', 'Passe la plus poussée: crawl large, rendu JS et pack IA complet.'),
                tone: 'expert',
            },
        ], signalAtlasDraft.profile || 'elevated');
    }
    if (pickerId === 'mode') {
        return buildSignalAtlasSimpleOptions([
            {
                value: 'public',
                label: moduleT('signalatlas.publicMode', 'Public audit'),
                description: moduleT('signalatlas.publicModeHint', 'Crawl, rendering and open signals only.'),
            },
            {
                value: 'verified_owner',
                label: moduleT('signalatlas.ownerMode', 'Verified owner'),
                description: moduleT('signalatlas.ownerModeHint', 'Enrich with official connected data when available.'),
            },
        ], signalAtlasDraft.mode);
    }
    if (pickerId === 'max_pages') {
        const budgetOptions = SIGNALATLAS_PAGE_BUDGET_STEPS.map(value => ({
            value,
            label: String(value),
            description: moduleT('signalatlas.pageBudgetHint', 'Maximum number of pages sampled for this audit pass.'),
        }));
        budgetOptions.push({
            value: SIGNALATLAS_UNLIMITED_PAGE_BUDGET,
            label: moduleT('signalatlas.pageBudgetUnlimited', '∞ Unlimited'),
            description: moduleT(
                'signalatlas.pageBudgetUnlimitedHint',
                `Uses the runtime ceiling for this pass (${SIGNALATLAS_MAX_PAGE_BUDGET} pages).`
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
            description: moduleT('signalatlas.depthHint', 'Controls how deep the deterministic crawler can follow internal links.'),
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
        return buildSignalAtlasModelOptions(perfAtlasDraft.model || currentJoyBoyChatModel());
    }
    if (pickerId === 'compare_model') {
        return buildSignalAtlasModelOptions(perfAtlasDraft.compare_model || fallbackSignalAtlasCompareModel());
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
    if (pickerId === 'compare_model') perfAtlasDraft.compare_model = String(value || fallbackSignalAtlasCompareModel());

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
    const toggleFn = cleanModuleId === 'perfatlas' ? 'togglePerfAtlasPicker' : 'toggleSignalAtlasPicker';
    const selectFn = cleanModuleId === 'perfatlas' ? 'selectPerfAtlasPickerOption' : 'selectSignalAtlasPickerOption';
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

function renderAuditProgressBanner({
    namespace,
    progressState,
    launchPending = false,
    targetLabel = '',
    statusLabel,
    supportCopy,
    launchingLabel,
    launchingMessage,
}) {
    if (!progressState && !launchPending) return '';
    const progress = launchPending && !progressState ? 4 : signalAtlasJobProgress(progressState);
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
                </div>
            </div>
            <div class="signalatlas-progress-bar${isLive ? ' is-live' : ''}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${escapeHtml(String(progress))}">
                <div class="signalatlas-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(progress))}%"></div>
            </div>
            <div class="signalatlas-progress-meta">
                <span class="signalatlas-progress-meta-copy">${escapeHtml(targetLabel || moduleT(`${namespace}.backgroundResumeHint`, 'This audit keeps running if you leave the view.'))}</span>
            </div>
        </div>
    `;
}

function renderSignalAtlasProgressBanner(progressState, targetLabel = '') {
    return renderAuditProgressBanner({
        namespace: 'signalatlas',
        progressState,
        launchPending: signalAtlasLaunchPending,
        targetLabel,
        statusLabel: signalAtlasStatusLabel,
        supportCopy: signalAtlasProgressSupportCopy(progressState, targetLabel),
        launchingLabel: moduleT('signalatlas.launching', 'Launching'),
        launchingMessage: moduleT('signalatlas.launchingAudit', 'Starting the audit runtime...'),
    });
}

function hydrateSignalAtlasMotion(scope) {
    const root = scope || document;
    requestAnimationFrame(() => {
        root.querySelectorAll('.signalatlas-score-ring').forEach(node => {
            const hasScore = String(node.dataset.hasScore || '').toLowerCase() === 'true';
            const progress = Math.max(0, Math.min(100, Number(node.dataset.score || 0)));
            const ringKey = String(node.dataset.ringKey || node.dataset.score || '');
            const circle = node.querySelector('.signalatlas-score-ring-progress');
            const circumference = Number(circle?.dataset?.circumference || 0);
            if (!circle || !Number.isFinite(circumference) || circumference <= 0) return;
            circle.style.strokeDasharray = String(circumference);
            if (!hasScore) {
                circle.style.strokeDashoffset = String(circumference);
                return;
            }
            const target = circumference - (circumference * progress / 100);
            if (signalAtlasAnimatedScoreRingKeys.has(ringKey)) {
                circle.style.strokeDashoffset = String(target);
                return;
            }
            circle.style.strokeDashoffset = String(circumference);
            requestAnimationFrame(() => {
                circle.style.strokeDashoffset = String(target);
                signalAtlasAnimatedScoreRingKeys.add(ringKey);
            });
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
    return ['modules-view', 'signalatlas-view', 'perfatlas-view'];
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
}

function hideOtherJoyBoyViews() {
    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const addonsView = document.getElementById('addons-view');
    const modelsView = document.getElementById('models-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (addonsView) addonsView.style.display = 'none';
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
    document.body.classList.remove('addons-mode', 'models-mode', 'projects-mode', 'modules-mode', 'signalatlas-mode', 'perfatlas-mode');
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
            Toast.error(result.data?.error || moduleT('signalatlas.loadError', 'Unable to load this audit.'));
        }
        return null;
    }
    signalAtlasCurrentAuditId = auditId;
    if (previousAuditId !== auditId) {
        signalAtlasSerpPage = 1;
    }
    signalAtlasCurrentAudit = result.data.audit;
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
        title: audit?.title || target.host || target.normalized_url || moduleT('signalatlas.untitledAudit', 'Untitled audit'),
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
        perfAtlasDraft.compare_model = fallbackSignalAtlasCompareModel();
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

function seedSignalAtlasRuntimeJob(job, fallbackAuditId = '') {
    seedAuditModuleRuntimeJob(job, 'signalatlas', fallbackAuditId, moduleT('signalatlas.launchingAudit', 'Starting the audit runtime...'));
}

function seedPerfAtlasRuntimeJob(job, fallbackAuditId = '') {
    seedAuditModuleRuntimeJob(job, 'perfatlas', fallbackAuditId, moduleT('perfatlas.launchingAudit', 'Starting the performance runtime...'));
}

function signalAtlasStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'queued') return moduleT('signalatlas.statusQueued', 'Queued');
    if (clean === 'running') return moduleT('signalatlas.statusRunning', 'Running');
    if (clean === 'done') return moduleT('signalatlas.statusDone', 'Ready');
    if (clean === 'error') return moduleT('signalatlas.statusError', 'Error');
    if (clean === 'cancelled') return moduleT('signalatlas.statusCancelled', 'Cancelled');
    return clean || moduleT('signalatlas.statusUnknown', 'Unknown');
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
    const profiles = Array.isArray(signalAtlasModelContext?.terminal_model_profiles)
        ? signalAtlasModelContext.terminal_model_profiles
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

function activePerfAtlasJobs() {
    return activeAuditModuleJobs('perfatlas')
        .filter(job => String(job?.metadata?.audit_id || '').trim())
        .sort((left, right) => String(right?.updated_at || '').localeCompare(String(left?.updated_at || '')));
}

function perfAtlasStatusLabel(status) {
    const clean = String(status || '').trim().toLowerCase();
    if (clean === 'queued') return moduleT('perfatlas.statusQueued', 'Queued');
    if (clean === 'running') return moduleT('perfatlas.statusRunning', 'Running');
    if (clean === 'done') return moduleT('perfatlas.statusDone', 'Ready');
    if (clean === 'error') return moduleT('perfatlas.statusError', 'Error');
    if (clean === 'cancelled') return moduleT('perfatlas.statusCancelled', 'Cancelled');
    return clean || moduleT('perfatlas.statusUnknown', 'Unknown');
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
    if (launchButton) {
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
    const currentStatus = String((typeof audit === 'object' && audit?.status) || '').toLowerCase();
    if (currentStatus === 'running' || currentStatus === 'queued') {
        return {
            job: null,
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
        label: profile?.label || profile?.display_name || profile?.name || profile?.id || 'Model',
        privacy: isCloud
            ? moduleT('signalatlas.privacyCloud', 'Cloud processing')
            : moduleT('signalatlas.privacyLocal', 'Local processing'),
        time: isCloud
            ? moduleT('signalatlas.timeCloud', 'Fast, depends on provider latency')
            : moduleT('signalatlas.timeLocal', 'Depends on local hardware'),
        cost: isCloud
            ? moduleT('signalatlas.costCloud', 'Provider/API cost may apply')
            : moduleT('signalatlas.costLocal', 'No API cost'),
        capability: isCloud
            ? moduleT('signalatlas.capabilityCloud', 'Great for deeper synthesis and long reports')
            : moduleT('signalatlas.capabilityLocal', 'Best for private interpretation and local-only flows'),
    };
}

function fallbackSignalAtlasCompareModel() {
    const profiles = signalAtlasCurrentProfiles();
    const current = signalAtlasDraft.model || currentJoyBoyChatModel();
    const alternative = profiles.find(profile => profile.id !== current && profile.configured !== false);
    return alternative?.id || current;
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

function renderModulesHub() {
    const host = document.getElementById('modules-view-content');
    if (!host) return;
    const cards = joyboyModulesCatalog.map(module => {
        const activeJobs = activeAuditModuleJobs(module?.id || '');
        const featuredJob = activeJobs[0] || null;
        const isLocked = module.available === false || module.backend_ready === false;
        const status = isLocked
            ? moduleT('modules.restartRequiredShort', 'Restart required')
            : activeJobs.length
            ? signalAtlasStatusLabel(featuredJob?.status || 'running')
            : signalAtlasStatusLabel(module.status);
        const premium = module.premium ? `<span class="modules-chip premium">${escapeHtml(moduleT('modules.premium', 'Premium'))}</span>` : '';
        const lockedReason = module.locked_reason ? `<div class="modules-card-note">${escapeHtml(module.locked_reason)}</div>` : '';
        const runtimeNote = activeJobs.length ? `
            <div class="modules-card-runtime">
                <div class="modules-card-runtime-copy">${escapeHtml(moduleT('signalatlas.moduleRuntimeCount', '{count} active audit(s)', { count: activeJobs.length }))}</div>
                <div class="modules-card-runtime-message">${escapeHtml(signalAtlasJobMessage(featuredJob))}</div>
                <div class="modules-card-runtime-bar"><div class="modules-card-runtime-fill" style="width:${escapeHtml(String(signalAtlasJobProgress(featuredJob)))}%"></div></div>
            </div>
        ` : '';
        return `
            <button
                class="modules-card${module.featured ? ' featured' : ''}${isLocked ? ' is-locked' : ''}"
                type="button"
                onclick="openNativeModule('${escapeHtml(module.id)}')"
                ${isLocked ? 'disabled' : ''}
            >
                <div class="modules-card-top">
                    <div class="modules-card-icon"><i data-lucide="${escapeHtml(module.icon || 'blocks')}"></i></div>
                    <div class="modules-card-status status-${escapeHtml(String(module.status || 'active').toLowerCase())}">${escapeHtml(status)}</div>
                </div>
                <div class="modules-card-title-row">
                    <div>
                        <div class="modules-card-title">${escapeHtml(module.name || 'Module')}</div>
                        <div class="modules-card-tagline">${escapeHtml(module.tagline || '')}</div>
                    </div>
                    ${premium}
                </div>
                <div class="modules-card-description">${escapeHtml(module.description || '')}</div>
                <div class="modules-card-capabilities">
                    ${(module.capabilities || []).slice(0, 4).map(cap => `<span class="modules-chip">${escapeHtml(cap.replace(/_/g, ' '))}</span>`).join('')}
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
        return `<div class="signalatlas-history-empty">${escapeHtml(moduleT('signalatlas.noAudits', 'No audits yet. Launch one to create your first deterministic report.'))}</div>`;
    }
    return signalAtlasAudits.map(audit => {
        const active = audit.id === signalAtlasCurrentAuditId;
        const score = audit.global_score ?? '--';
        const progressState = signalAtlasAuditProgressState(audit);
        const canDelete = !progressState;
        const isLive = signalAtlasIsLiveProgressStatus(progressState?.status || '');
        const supportCopy = progressState ? signalAtlasProgressSupportCopy(progressState) : '';
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
                        <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT('signalatlas.progressPercent', '{value}%', { value: progressState.progress }))}</span>
                    </div>
                    <div class="signalatlas-history-progress-bar${isLive ? ' is-live' : ''}">
                        <div class="signalatlas-history-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(progressState.progress))}%"></div>
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
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noFindings', 'No findings yet for this audit.'))}</div>`;
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
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.probableCause', 'Probable cause'))}:</strong> ${escapeHtml(item.probable_cause || '')}</div>
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.recommendedFix', 'Recommended fix'))}:</strong> ${escapeHtml(signalAtlasFindingSummary(item))}</div>
            <div class="signalatlas-finding-detail"><strong>${escapeHtml(moduleT('signalatlas.acceptance', 'Acceptance'))}:</strong> ${escapeHtml(item.acceptance_criteria || '')}</div>
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
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.pagesSampled', 'Pages sampled'))}</span><strong>${escapeHtml(String(snapshot.page_count || 0))}</strong></div>
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
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noPages', 'No sampled pages yet.'))}</div>`;
    }
    return `
        <div class="signalatlas-table-wrap">
            <table class="signalatlas-table">
                <thead>
                    <tr>
                        <th>${escapeHtml(moduleT('signalatlas.page', 'Page'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.status', 'Status'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.words', 'Words'))}</th>
                        <th>${escapeHtml(moduleT('signalatlas.rendering', 'Rendering'))}</th>
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
                            <td>${escapeHtml(page.shell_like ? moduleT('signalatlas.jsRisk', 'JS risk') : moduleT('signalatlas.serverReady', 'Server-ready'))}</td>
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
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noTemplates', 'No template clusters yet.'))}</div>`;
    }
    return templates.map(template => `
        <article class="signalatlas-template-card">
            <div class="signalatlas-template-top">
                <div class="signalatlas-template-signature">${escapeHtml(template.signature || '/')}</div>
                <div class="signalatlas-inline-chip">${escapeHtml(moduleT('signalatlas.templatePages', '{count} page(s)', { count: template.count || 0 }))}</div>
            </div>
            <div class="signalatlas-template-meta">${escapeHtml(moduleT('signalatlas.avgContentUnits', 'Average content units: {count}', { count: template.avg_content_units || template.avg_word_count || 0 }))}</div>
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
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.contentSignals', 'Content & blog signals'))}</div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.blogDetected', 'Blog detected'))}</span><strong>${escapeHtml(summary.blog_detected ? moduleT('common.ready', 'READY') : moduleT('signalatlas.no', 'No'))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.topRisk', 'Top risk'))}</span><strong>${escapeHtml(signalAtlasRiskLabel(summary.top_risk || '--'))}</strong></div>
                <div class="signalatlas-metric-row"><span>${escapeHtml(moduleT('signalatlas.platform', 'Platform'))}</span><strong>${escapeHtml(summary.platform || '--')}</strong></div>
            </section>
            <section class="signalatlas-panel compact">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.contentFindings', 'Content findings'))}</div>
                ${(contentFindings.length ? contentFindings : [{ title: moduleT('signalatlas.noneDetected', 'No content-specific issue detected yet.'), diagnostic: '' }]).map(item => `
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
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.aiControls', 'AI interpretation'))}</div>
                <div class="signalatlas-control-stack">
                    <div class="signalatlas-ai-note">${escapeHtml(moduleT('signalatlas.aiControlsHint', 'Use the controls above to keep the selected JoyBoy model, preset, and AI level in sync with this audit.'))}</div>
                    <div class="signalatlas-actions">
                        <button class="signalatlas-btn" type="button" onclick="rerunSignalAtlasAi()">${escapeHtml(moduleT('signalatlas.rerunAi', 'Re-run AI only'))}</button>
                    </div>
                </div>
                <div class="signalatlas-compare-box">
                    <div class="signalatlas-field">
                        <label>${escapeHtml(moduleT('signalatlas.compareModelLabel', 'Compare with'))}</label>
                        ${renderSignalAtlasPicker('compare_model', 'signalatlas-compare-model-select', signalAtlasPickerOptions('compare_model'), signalAtlasDraft.compare_model || fallbackSignalAtlasCompareModel())}
                    </div>
                    <button class="signalatlas-btn secondary" type="button" onclick="compareSignalAtlasAi()">${escapeHtml(moduleT('signalatlas.compareAi', 'Compare interpretations'))}</button>
                </div>
            </section>
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.interpretations', 'Interpretations'))}</div>
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
                `).join('') : `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noInterpretations', 'No AI interpretation yet.'))}</div>`}
            </section>
        </div>
    `;
}

function renderSignalAtlasExports(audit) {
    if (!audit?.id) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.noAuditSelected', 'Select an audit to export it.'))}</div>`;
    }
    return `
        <div class="signalatlas-export-grid">
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'json')">
                <div class="signalatlas-export-title">JSON</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportJson', 'Structured machine-readable export.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'markdown')">
                <div class="signalatlas-export-title">Markdown</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportMarkdown', 'Readable report for humans or AI tools.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'prompt')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.promptForAiFix', 'Prompt for AI fix'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportPrompt', 'One-shot handoff for a dev/content/SEO model.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'remediation')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.remediationPack', 'AI remediation pack'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportRemediation', 'All findings with prompts and acceptance criteria.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="downloadSignalAtlasExport('${escapeHtml(audit.id)}', 'pdf')">
                <div class="signalatlas-export-title">PDF</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportPdf', 'Premium PDF rendered from the same report model.'))}</div>
            </button>
            <button class="signalatlas-export-card" type="button" onclick="openSignalAtlasPromptInChat('${escapeHtml(audit.id)}')">
                <div class="signalatlas-export-title">${escapeHtml(moduleT('signalatlas.openInChat', 'Open in JoyBoy chat'))}</div>
                <div class="signalatlas-export-copy">${escapeHtml(moduleT('signalatlas.exportToChat', 'Push the audit prompt into a normal JoyBoy conversation.'))}</div>
            </button>
        </div>
    `;
}

function renderSignalAtlasTabContent(audit) {
    if (!audit) {
        return `<div class="signalatlas-empty-panel">${escapeHtml(moduleT('signalatlas.emptyWorkspace', 'Choose a domain or pick a past audit to start.'))}</div>`;
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
        ['visibility', moduleT('signalatlas.tabVisibility', 'Visibility')],
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
                    <input id="signalatlas-target-input" class="signalatlas-target-input${targetValidation.present && !targetValidation.valid ? ' is-invalid' : ''}" type="text" value="${escapeHtml(signalAtlasDraft.target)}" placeholder="${escapeHtml(moduleT('signalatlas.targetPlaceholder', 'Example: https://nevomove.com/'))}" oninput="signalAtlasTargetInputChanged(event)" onblur="signalAtlasControlsChanged()" aria-invalid="${targetValidation.present && !targetValidation.valid ? 'true' : 'false'}" inputmode="url" autocapitalize="off" spellcheck="false">
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
                        <button id="signalatlas-launch-btn" class="signalatlas-btn launch" type="button" onclick="launchSignalAtlasAudit()" ${(signalAtlasLaunchPending || !targetValidation.valid) ? 'disabled' : ''}>${escapeHtml(signalAtlasLaunchPending ? moduleT('signalatlas.launching', 'Launching') : moduleT('signalatlas.runAudit', 'Run audit'))}</button>
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
                ${renderSignalAtlasProgressBanner(progressState, moduleT('signalatlas.backgroundResumeHint', 'This audit keeps running if you leave the view.'))}
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
                                        moduleT('signalatlas.pageBudgetHint', 'Nombre maximum de pages échantillonnées sur cette passe d’audit.')
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
                                        moduleT('signalatlas.renderJs', 'Render JS (scaffolded)'),
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
                            <div class="signalatlas-panel-title">${escapeHtml(audit?.title || moduleT('signalatlas.selectAudit', 'Select or launch an audit'))}</div>
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
        Toast?.warning?.(moduleT('signalatlas.targetRequired', 'Add a real domain or public URL first, for example https://nevomove.com/.'));
        renderSignalAtlasTargetValidationUi();
        return;
    }
    if (!targetValidation.valid) {
        Toast?.warning?.(moduleT('signalatlas.targetInvalid', 'Use a real domain or full public URL, for example https://nevomove.com/.'));
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
            Toast?.error?.(result.data?.error || moduleT('signalatlas.auditCreateFailed', 'Unable to launch the audit.'));
            return;
        }
        signalAtlasCurrentAuditId = result.data?.audit?.id || signalAtlasCurrentAuditId;
        signalAtlasCurrentAudit = result.data?.audit || signalAtlasCurrentAudit;
        if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
        await loadSignalAtlasBootstrap();
        if (signalAtlasCurrentAuditId) {
            await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
        }
        renderSignalAtlasWorkspace();
        startSignalAtlasRefresh();
        Toast?.success?.(moduleT('signalatlas.auditStarted', 'SignalAtlas audit started.'));
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
    const confirmed = window.confirm(
        moduleT('signalatlas.deleteAuditConfirm', 'Supprimer définitivement {title} ?', { title })
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
        Toast?.error?.(result.data?.error || moduleT('signalatlas.rerunFailed', 'Unable to re-run the AI interpretation.'));
        return;
    }
    if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
    renderSignalAtlasWorkspace();
    startSignalAtlasRefresh();
    Toast?.success?.(moduleT('signalatlas.rerunStarted', 'AI interpretation started.'));
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
        Toast?.error?.(result.data?.error || moduleT('signalatlas.compareFailed', 'Unable to compare interpretations.'));
        return;
    }
    if (result.data?.job) seedSignalAtlasRuntimeJob(result.data.job, signalAtlasCurrentAuditId);
    renderSignalAtlasWorkspace();
    startSignalAtlasRefresh();
    Toast?.success?.(moduleT('signalatlas.compareStarted', 'SignalAtlas comparison started.'));
}

async function refreshSignalAtlasWorkspace(options = {}) {
    const allowDefer = options.allowDefer !== false;
    if (allowDefer && signalAtlasShouldDeferRefresh()) {
        signalAtlasPendingRefresh = true;
        scheduleSignalAtlasDeferredRefresh();
        return;
    }
    signalAtlasPendingRefresh = false;
    await loadSignalAtlasBootstrap();
    if (signalAtlasCurrentAuditId) {
        await loadSignalAtlasAudit(signalAtlasCurrentAuditId, { silent: true });
    }
    renderSignalAtlasWorkspace();
}

function startSignalAtlasRefresh() {
    stopSignalAtlasRefresh();
    signalAtlasRefreshTimer = setInterval(async () => {
        if (!isSignalAtlasVisible()) {
            stopSignalAtlasRefresh();
            return;
        }
        const activeJob = signalAtlasCurrentAuditId ? activeSignalAtlasJobForAudit(signalAtlasCurrentAuditId) : null;
        if (!activeJob && !(signalAtlasAudits || []).some(audit => signalAtlasAuditProgressState(audit))) {
            stopSignalAtlasRefresh();
            return;
        }
        await refreshSignalAtlasWorkspace({ allowDefer: true });
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
        Toast?.error?.(moduleT('signalatlas.promptLoadFailed', 'Unable to load the AI-fix prompt.'));
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
    return `
        <section class="signalatlas-owner-strip perfatlas-owner-strip">
            ${perfAtlasProviders.map(provider => `
                <div class="signalatlas-owner-card">
                    <div class="signalatlas-owner-card-top">
                        <span class="signalatlas-owner-name">${escapeHtml(provider.name || provider.id || 'Provider')}</span>
                        <span class="signalatlas-tag ${signalAtlasProviderTone(provider.status)}">${escapeHtml(signalAtlasProviderStatusLabel(provider.status || 'unknown'))}</span>
                    </div>
                    <div class="signalatlas-owner-note">${escapeHtml(provider.detail || signalAtlasProviderSummary(provider))}</div>
                </div>
            `).join('')}
        </section>
    `;
}

function renderPerfAtlasScoreCards(audit) {
    const scores = Array.isArray(audit?.scores) ? audit.scores : [];
    return scores.map(score => `
        <div class="signalatlas-score-card ${signalAtlasScoreTone(score.score)}">
            <div class="signalatlas-score-label">${escapeHtml(score.label || score.id || 'Score')}</div>
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
    return items.map(item => `
        <article class="signalatlas-finding-card">
            <div class="signalatlas-finding-top">
                <div>
                    <div class="signalatlas-finding-title">${escapeHtml(item.title || 'Finding')}</div>
                    <div class="signalatlas-finding-copy">${escapeHtml(item.diagnostic || '')}</div>
                </div>
                <span class="signalatlas-tag ${signalAtlasSeverityTone(item.severity)}">${escapeHtml(signalAtlasSeverityLabel(item.severity || ''))}</span>
            </div>
            <div class="signalatlas-mini-finding-copy">${escapeHtml(item.recommended_fix || '')}</div>
            <div class="signalatlas-finding-meta">
                <span>${escapeHtml(item.category || '')}</span>
                <span>${escapeHtml(signalAtlasConfidenceLabel(item.confidence || ''))}</span>
                <span>${escapeHtml(item.url || item.scope || '')}</span>
            </div>
        </article>
    `).join('');
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
                                    <div class="signalatlas-mini-finding-copy">${escapeHtml(String(trend.direction || 'steady'))} · ${escapeHtml(String(trend.earliest ?? 'n/a'))} → ${escapeHtml(String(trend.latest ?? 'n/a'))}</div>
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
                    <div class="signalatlas-panel-kicker">${escapeHtml(item.runner || 'lab')}</div>
                    <div class="signalatlas-panel-title">${escapeHtml(item.url || '')}</div>
                </div>
                <div class="signalatlas-summary-badges">
                    <span class="signalatlas-inline-chip">${escapeHtml(moduleT('perfatlas.scoreShort', 'Score'))}: ${escapeHtml(String(item.score ?? 'n/a'))}</span>
                    <span class="signalatlas-inline-chip">${escapeHtml(item.strategy || 'mobile')}</span>
                </div>
            </div>
            <div class="signalatlas-metric-grid">
                <div class="signalatlas-metric-card"><span>LCP</span><strong>${escapeHtml(perfAtlasFormatMs(item.largest_contentful_paint_ms))}</strong></div>
                <div class="signalatlas-metric-card"><span>TBT</span><strong>${escapeHtml(perfAtlasFormatMs(item.total_blocking_time_ms))}</strong></div>
                <div class="signalatlas-metric-card"><span>Req</span><strong>${escapeHtml(String(item.request_count ?? 'n/a'))}</strong></div>
                <div class="signalatlas-metric-card"><span>Weight</span><strong>${escapeHtml(perfAtlasFormatBytes(item.total_byte_weight))}</strong></div>
            </div>
            ${item.note ? `<div class="signalatlas-panel-copy">${escapeHtml(item.note)}</div>` : ''}
            ${(item.opportunities || []).length ? `
                <div class="signalatlas-finding-list">
                    ${(item.opportunities || []).slice(0, 5).map(opp => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">${escapeHtml(opp.title || opp.id || 'Opportunity')}</div>
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
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(perfAtlasFormatMs(page.ttfb_ms))} · ${escapeHtml(String(page.script_count || 0))} JS · ${escapeHtml(String(page.stylesheet_count || 0))} CSS · ${escapeHtml(String(page.image_count || 0))} img</div>
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
                            <div class="signalatlas-mini-finding-copy">${escapeHtml(asset.kind || 'asset')} · cache ${escapeHtml(asset.cache_control || 'none')} · encoding ${escapeHtml(asset.content_encoding || 'none')}</div>
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
                    <div class="signalatlas-panel-copy">${escapeHtml(item.detail || '')}</div>
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
    const compareModel = perfAtlasDraft.compare_model || fallbackSignalAtlasCompareModel();
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
    return `
        <div class="signalatlas-overview-stack">
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('perfatlas.quickRead', 'Quick read'))}</div>
                    <div class="signalatlas-panel-title">${escapeHtml(moduleT('perfatlas.executiveSummary', 'Executive summary'))}</div>
                    <div class="signalatlas-panel-copy">${escapeHtml(summary.target || '')}</div>
                    <div class="signalatlas-summary-badges">
                        <span class="signalatlas-inline-chip">${escapeHtml(summary.platform || 'Custom')}</span>
                        <span class="signalatlas-inline-chip">${escapeHtml(summary.runtime_runner || 'unavailable')}</span>
                        <span class="signalatlas-inline-chip">${escapeHtml(summary.mode || 'public')}</span>
                    </div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.pagesSampled', 'Pages sampled'))}</span><strong>${escapeHtml(String(summary.pages_crawled || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.labPagesAnalyzed', 'Lab pages'))}</span><strong>${escapeHtml(String(summary.lab_pages_analyzed || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.fieldReady', 'Field ready'))}</span><strong>${escapeHtml(summary.field_data_available ? moduleT('common.ok', 'OK') : moduleT('common.none', 'None'))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${escapeHtml(moduleT('perfatlas.labReady', 'Lab ready'))}</span><strong>${escapeHtml(summary.lab_data_available ? moduleT('common.ok', 'OK') : moduleT('common.none', 'None'))}</strong></div>
                    </div>
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
        const supportCopy = progressState ? perfAtlasProgressSupportCopy(progressState) : '';
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
                <div class="signalatlas-history-footer">
                    <span>${escapeHtml(moduleT('perfatlas.scoreShort', 'Score'))}: ${escapeHtml(String(audit.global_score ?? '--'))}</span>
                    <span>${escapeHtml(String(audit.lab_pages_analyzed || 0))} ${escapeHtml(moduleT('perfatlas.labPagesShort', 'lab'))}</span>
                </div>
                ${progressState ? `
                    <div class="signalatlas-history-progress-meta">
                        <span class="signalatlas-progress-chip is-phase">${escapeHtml(progressState.phase)}</span>
                        <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT('perfatlas.progressPercent', '{value}%', { value: progressState.progress }))}</span>
                    </div>
                    <div class="signalatlas-history-progress-bar${isLive ? ' is-live' : ''}">
                        <div class="signalatlas-history-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(progressState.progress))}%"></div>
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
    const progressStatus = String(progressState?.status || '').toLowerCase();
    const canCancelAudit = !!progressState?.job && ['queued', 'running', 'cancelling'].includes(progressStatus);
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
                        <button id="perfatlas-launch-btn" class="signalatlas-btn secondary" type="button" onclick="cancelPerfAtlasAudit('${escapeHtml(progressState?.auditId || perfAtlasCurrentAuditId || '')}')" ${!progressState?.job ? 'disabled' : ''}>${escapeHtml(moduleT('perfatlas.cancelAudit', 'Cancel audit'))}</button>
                    ` : `
                        <button id="perfatlas-launch-btn" class="signalatlas-btn" type="button" onclick="launchPerfAtlasAudit()" ${perfAtlasLaunchPending || !targetValidation.valid ? 'disabled' : ''}>${escapeHtml(moduleT('perfatlas.runAudit', 'Launch audit'))}</button>
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
                    targetLabel: perfAtlasDraft.target,
                    statusLabel: perfAtlasStatusLabel,
                    supportCopy: perfAtlasProgressSupportCopy(progressState, perfAtlasDraft.target),
                    launchingLabel: moduleT('perfatlas.launching', 'Launching'),
                    launchingMessage: moduleT('perfatlas.launchingAudit', 'Starting the performance runtime...'),
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
    const confirmed = window.confirm(moduleT('perfatlas.deleteAuditConfirm', 'Delete {title} permanently?', { title }));
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
    const jobId = String(progressState?.job?.id || '').trim();
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
    const rightModel = perfAtlasDraft.compare_model || fallbackSignalAtlasCompareModel();
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
        const activeJob = perfAtlasCurrentAuditId ? activePerfAtlasJobForAudit(perfAtlasCurrentAuditId) : null;
        if (!activeJob && !(perfAtlasAudits || []).some(audit => perfAtlasAuditProgressState(audit))) {
            stopPerfAtlasRefresh();
            return;
        }
        await refreshPerfAtlasWorkspace();
    }, 3500);
}

function stopPerfAtlasRefresh() {
    if (perfAtlasRefreshTimer) {
        clearInterval(perfAtlasRefreshTimer);
        perfAtlasRefreshTimer = null;
    }
}

window.addEventListener('joyboy:locale-changed', () => {
    if (getModulesView()?.style.display !== 'none') renderModulesHub();
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
    if (isPerfAtlasVisible()) renderPerfAtlasWorkspace();
});

window.addEventListener('click', (event) => {
    if (event.target?.closest?.('.signalatlas-picker')) return;
    if (signalAtlasOpenPickerId) closeSignalAtlasPicker();
    if (perfAtlasOpenPickerId) closeAuditPicker('perfatlas');
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
