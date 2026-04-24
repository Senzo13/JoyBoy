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
        max_pages: 50,
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

function closeSignalAtlasPicker() {
    if (!signalAtlasOpenPickerId) return;
    signalAtlasOpenPickerId = null;
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

function toggleSignalAtlasPicker(pickerId, event) {
    event?.stopPropagation?.();
    signalAtlasOpenPickerId = signalAtlasOpenPickerId === pickerId ? null : pickerId;
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
}

async function selectSignalAtlasPickerOption(pickerId, value, event) {
    event?.stopPropagation?.();
    signalAtlasOpenPickerId = null;

    if (pickerId === 'profile') applySignalAtlasProfile(String(value || 'elevated'));
    if (pickerId === 'mode') signalAtlasDraft.mode = String(value || 'public');
    if (pickerId === 'max_pages') signalAtlasDraft.max_pages = Number.parseInt(value, 10) || signalAtlasDraft.max_pages;
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
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
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
        return buildSignalAtlasSimpleOptions([8, 12, 20, 30, 40, 50].map(value => ({
            value,
            label: String(value),
            description: moduleT('signalatlas.pageBudgetHint', 'Maximum number of pages sampled for this audit pass.'),
        })), signalAtlasDraft.max_pages);
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

function renderSignalAtlasPicker(pickerId, inputId, options, selectedValue) {
    const items = Array.isArray(options) ? options : [];
    const selected = items.find(option => String(option.value) === String(selectedValue)) || items[0] || {
        value: selectedValue,
        label: selectedValue,
        description: '',
        meta: '',
        badge: '',
        tone: '',
    };
    const isOpen = signalAtlasOpenPickerId === pickerId;
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
                onclick="selectSignalAtlasPickerOption('${escapeHtml(pickerId)}', ${jsValue}, event)"
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
                onclick="toggleSignalAtlasPicker('${escapeHtml(pickerId)}', event)"
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

function renderSignalAtlasProgressBanner(progressState, targetLabel = '') {
    if (!progressState && !signalAtlasLaunchPending) return '';
    const progress = signalAtlasLaunchPending && !progressState ? 4 : signalAtlasJobProgress(progressState);
    const phase = signalAtlasLaunchPending && !progressState
        ? moduleT('signalatlas.launching', 'Launching')
        : progressState.phase;
    const message = signalAtlasLaunchPending && !progressState
        ? moduleT('signalatlas.launchingAudit', 'Starting the audit runtime...')
        : progressState.message;
    const liveStatus = signalAtlasLaunchPending && !progressState
        ? 'queued'
        : String(progressState?.status || '').toLowerCase();
    const isLive = signalAtlasLaunchPending || signalAtlasIsLiveProgressStatus(liveStatus);
    const supportCopy = signalAtlasProgressSupportCopy(progressState, targetLabel);
    return `
        <div class="signalatlas-progress-surface">
            <div class="signalatlas-progress-top">
                <div class="signalatlas-progress-heading">
                    <div class="signalatlas-panel-kicker">${escapeHtml(moduleT('signalatlas.progressTitle', 'Audit activity'))}</div>
                    <div class="signalatlas-progress-title" aria-live="polite">
                        <span class="signalatlas-progress-spinner" aria-hidden="true"></span>
                        <span class="signalatlas-progress-message${isLive ? ' signalatlas-shimmer-text' : ''}">${escapeHtml(message)}</span>
                    </div>
                    <div class="signalatlas-progress-support">${escapeHtml(supportCopy)}</div>
                </div>
                <div class="signalatlas-progress-top-actions">
                    <span class="signalatlas-progress-chip">${escapeHtml(signalAtlasStatusLabel(liveStatus || 'running'))}</span>
                    <span class="signalatlas-progress-chip is-phase">${escapeHtml(phase)}</span>
                    <span class="signalatlas-progress-chip is-percent">${escapeHtml(moduleT('signalatlas.progressPercent', '{value}%', { value: progress }))}</span>
                </div>
            </div>
            <div class="signalatlas-progress-bar${isLive ? ' is-live' : ''}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${escapeHtml(String(progress))}">
                <div class="signalatlas-progress-fill${isLive ? ' is-live' : ''}" style="width:${escapeHtml(String(progress))}%"></div>
            </div>
            <div class="signalatlas-progress-meta">
                <span class="signalatlas-progress-meta-copy">${escapeHtml(targetLabel || moduleT('signalatlas.backgroundResumeHint', 'This audit keeps running if you leave the view.'))}</span>
            </div>
        </div>
    `;
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
    return ['modules-view', 'signalatlas-view'];
}

function hideModulesWorkspaces() {
    signalAtlasOpenPickerId = null;
    moduleViewIds().forEach(id => {
        const node = document.getElementById(id);
        if (node) node.style.display = 'none';
    });
    stopSignalAtlasRefresh();
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
    document.body.classList.remove('addons-mode', 'models-mode', 'projects-mode', 'modules-mode', 'signalatlas-mode');
    document.body.classList.add(bodyClass);
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
    if (maxPages) signalAtlasDraft.max_pages = Number.parseInt(maxPages.value, 10) || signalAtlasDraft.max_pages;
    if (depth) signalAtlasDraft.depth = Number.parseInt(depth.value, 10) || signalAtlasDraft.depth;
    if (renderJs) signalAtlasDraft.render_js = !!renderJs.checked;
    if (model) signalAtlasDraft.model = model.value;
    if (preset) signalAtlasDraft.preset = preset.value;
    if (level) signalAtlasDraft.level = level.value;
    if (compareModel) signalAtlasDraft.compare_model = compareModel.value;
}

async function refreshSignalAtlasProviderStatus(target = signalAtlasDraft.target, mode = signalAtlasDraft.mode) {
    if (typeof apiSignalAtlas === 'undefined') return [];
    const providerResult = await apiSignalAtlas.getProviderStatus(target || '', mode || 'public');
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
}

async function loadModulesCatalog() {
    if (typeof apiModules === 'undefined') return [];
    const result = await apiModules.list();
    joyboyModulesCatalog = Array.isArray(result.data?.modules) ? result.data.modules : [];
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

function activeSignalAtlasJobForAudit(auditId) {
    const jobs = activeSignalAtlasJobs();
    if (!jobs.length) return null;
    return jobs.find(job =>
        String(job?.metadata?.audit_id || '') === String(auditId || '')
    ) || null;
}

function seedSignalAtlasRuntimeJob(job, fallbackAuditId = '') {
    if (!job || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return;
    const seeded = {
        ...job,
        status: job.status || 'queued',
        phase: job.phase || job.status || 'queued',
        progress: Number.isFinite(Number(job.progress)) ? Number(job.progress) : 2,
        message: job.message || moduleT('signalatlas.launchingAudit', 'Starting the audit runtime...'),
        metadata: {
            ...(job.metadata || {}),
            module_id: 'signalatlas',
            audit_id: job?.metadata?.audit_id || fallbackAuditId || '',
        },
    };
    const existing = runtimeJobsCache.findIndex(item => String(item?.id || '') === String(seeded.id || ''));
    if (existing >= 0) runtimeJobsCache.splice(existing, 1, seeded);
    else runtimeJobsCache.unshift(seeded);
    if (typeof renderRuntimeJobs === 'function') renderRuntimeJobs();
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
        const activeJobs = String(module?.id || '').toLowerCase() === 'signalatlas' ? activeSignalAtlasJobs() : [];
        const featuredJob = activeJobs[0] || null;
        const status = activeJobs.length
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
            <button class="modules-card${module.featured ? ' featured' : ''}" type="button" onclick="openNativeModule('${escapeHtml(module.id)}')">
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
            <div class="signalatlas-template-meta">${escapeHtml(moduleT('signalatlas.avgWords', 'Average words: {count}', { count: template.avg_word_count || 0 }))}</div>
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
                    <input id="signalatlas-target-input" class="signalatlas-target-input" type="text" value="${escapeHtml(signalAtlasDraft.target)}" placeholder="${escapeHtml(moduleT('signalatlas.targetPlaceholder', 'Enter a domain or URL'))}" oninput="signalAtlasTargetInputChanged(event)" onblur="signalAtlasControlsChanged()">
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
                        <button class="signalatlas-btn launch" type="button" onclick="launchSignalAtlasAudit()" ${signalAtlasLaunchPending ? 'disabled' : ''}>${escapeHtml(signalAtlasLaunchPending ? moduleT('signalatlas.launching', 'Launching') : moduleT('signalatlas.runAudit', 'Run audit'))}</button>
                    `}
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
    if (!joyboyModulesCatalog.length) {
        await loadModulesCatalog();
    }
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

function openNativeModule(moduleId) {
    if (String(moduleId || '').toLowerCase() === 'signalatlas') {
        openSignalAtlasWorkspace();
    }
}

async function launchSignalAtlasAudit() {
    syncSignalAtlasDraftFromDom();
    const target = String(signalAtlasDraft.target || '').trim();
    if (!target) {
        Toast?.warning?.(moduleT('signalatlas.targetRequired', 'Add a domain or URL first.'));
        return;
    }
    signalAtlasLaunchPending = true;
    renderSignalAtlasWorkspace();
    const payload = {
        target,
        mode: signalAtlasDraft.mode || 'public',
        options: {
            max_pages: signalAtlasDraft.max_pages || 12,
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

window.addEventListener('joyboy:locale-changed', () => {
    if (getModulesView()?.style.display !== 'none') renderModulesHub();
    if (isSignalAtlasVisible()) renderSignalAtlasWorkspace();
});

window.addEventListener('click', (event) => {
    if (!signalAtlasOpenPickerId) return;
    if (event.target?.closest?.('.signalatlas-picker')) return;
    closeSignalAtlasPicker();
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
});

window.openModulesHub = openModulesHub;
window.openNativeModule = openNativeModule;
window.openSignalAtlasWorkspace = openSignalAtlasWorkspace;
window.setSignalAtlasTab = setSignalAtlasTab;
window.signalAtlasControlsChanged = signalAtlasControlsChanged;
window.launchSignalAtlasAudit = launchSignalAtlasAudit;
window.rerunSignalAtlasAi = rerunSignalAtlasAi;
window.compareSignalAtlasAi = compareSignalAtlasAi;
window.refreshSignalAtlasWorkspace = refreshSignalAtlasWorkspace;
window.downloadSignalAtlasExport = downloadSignalAtlasExport;
window.openSignalAtlasPromptInChat = openSignalAtlasPromptInChat;
window.toggleSignalAtlasPicker = toggleSignalAtlasPicker;
window.selectSignalAtlasPickerOption = selectSignalAtlasPickerOption;
window.signalAtlasTargetInputChanged = signalAtlasTargetInputChanged;
window.toggleSignalAtlasAdvancedSettings = toggleSignalAtlasAdvancedSettings;
window.toggleSignalAtlasHistoryDrawer = toggleSignalAtlasHistoryDrawer;
window.toggleSignalAtlasSeoDetails = toggleSignalAtlasSeoDetails;
window.downloadSignalAtlasAiReport = downloadSignalAtlasAiReport;
window.cancelSignalAtlasAudit = cancelSignalAtlasAudit;
window.deleteSignalAtlasAudit = deleteSignalAtlasAudit;
