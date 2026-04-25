// ===== CYBERATLAS WORKSPACE =====

(function () {
    const CYBERATLAS_DEFAULT_PAGE_BUDGET = 8;
    const CYBERATLAS_MAX_PAGE_BUDGET = 24;
    const CYBERATLAS_DEFAULT_ENDPOINT_BUDGET = 32;
    const CYBERATLAS_MAX_ENDPOINT_BUDGET = 80;
    const CYBERATLAS_PAGE_BUDGET_STEPS = [3, 5, 8, 12, 16, 24];
    const CYBERATLAS_ENDPOINT_BUDGET_STEPS = [12, 24, 32, 48, 64, 80];
    const CYBERATLAS_AUDIT_PROFILES = {
        basic: {
            max_pages: 3,
            max_endpoints: 12,
            preset: 'fast',
            level: 'basic_summary',
            active_checks: false,
        },
        elevated: {
            max_pages: 8,
            max_endpoints: 32,
            preset: 'balanced',
            level: 'full_expert_analysis',
            active_checks: false,
        },
        ultra: {
            max_pages: 24,
            max_endpoints: 80,
            preset: 'expert',
            level: 'ai_remediation_pack',
            active_checks: false,
        },
    };

    let cyberAtlasAudits = [];
    let cyberAtlasCurrentAuditId = null;
    let cyberAtlasCurrentAudit = null;
    let cyberAtlasModelContext = null;
    let cyberAtlasProviders = [];
    let cyberAtlasActiveTab = 'overview';
    let cyberAtlasRefreshTimer = null;
    let cyberAtlasLaunchPending = false;
    let cyberAtlasAdvancedVisible = false;
    let cyberAtlasRefreshInFlight = false;
    let cyberAtlasDraft = {
        target: '',
        profile: 'elevated',
        mode: 'public',
        max_pages: CYBERATLAS_DEFAULT_PAGE_BUDGET,
        max_endpoints: CYBERATLAS_DEFAULT_ENDPOINT_BUDGET,
        active_checks: false,
        model: '',
        preset: 'balanced',
        level: 'full_expert_analysis',
        compare_model: '',
    };

    function cyberAtlasText(key, fallback = '', params = {}) {
        if (typeof moduleT === 'function') return moduleT(key, fallback, params);
        let text = fallback || key;
        Object.entries(params || {}).forEach(([name, value]) => {
            text = String(text).replace(new RegExp(`\\{${name}\\}`, 'g'), String(value));
        });
        return text;
    }

    function cyberAtlasEscape(value) {
        if (typeof escapeHtml === 'function') return escapeHtml(value);
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function cyberAtlasAuditKey(value) {
        if (typeof auditTranslationKey === 'function') return auditTranslationKey(value);
        return String(value || '')
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_+|_+$/g, '');
    }

    function cyberAtlasCurrentChatModel() {
        if (typeof currentJoyBoyChatModel === 'function') return currentJoyBoyChatModel();
        return 'qwen3.5:2b';
    }

    function getCyberAtlasView() {
        return document.getElementById('cyberatlas-view');
    }

    function isCyberAtlasVisible() {
        const view = getCyberAtlasView();
        return !!view && view.style.display !== 'none';
    }

    function cyberAtlasNormalizeBudget(value, fallback, maximum) {
        const parsed = Number.parseInt(String(value ?? '').trim(), 10);
        if (Number.isFinite(parsed) && parsed > 0) return Math.min(parsed, maximum);
        return fallback;
    }

    function cyberAtlasValidateTarget(value) {
        if (typeof signalAtlasValidateTarget === 'function') {
            const result = signalAtlasValidateTarget(value);
            if (!result.valid && !result.present) {
                return {
                    ...result,
                    message: cyberAtlasText('cyberatlas.targetRequired', 'Add a real domain or full public URL first.'),
                };
            }
            if (!result.valid) {
                return {
                    ...result,
                    message: cyberAtlasText('cyberatlas.targetInvalid', 'Use a real public domain or URL.'),
                };
            }
            return result;
        }
        const raw = String(value || '').trim();
        if (!raw) {
            return { valid: false, present: false, normalized: '', message: cyberAtlasText('cyberatlas.targetRequired', 'Add a real domain or full public URL first.') };
        }
        try {
            const candidate = raw.includes('://') ? raw : `https://${raw}`;
            const parsed = new URL(candidate);
            const valid = ['http:', 'https:'].includes(parsed.protocol) && parsed.hostname.includes('.');
            return {
                valid,
                present: true,
                normalized: valid ? parsed.href : '',
                message: valid ? '' : cyberAtlasText('cyberatlas.targetInvalid', 'Use a real public domain or URL.'),
            };
        } catch (error) {
            return { valid: false, present: true, normalized: '', message: cyberAtlasText('cyberatlas.targetInvalid', 'Use a real public domain or URL.') };
        }
    }

    function cyberAtlasCurrentProfiles() {
        const profiles = cyberAtlasModelContext?.profiles;
        if (Array.isArray(profiles) && profiles.length) return profiles;
        const model = cyberAtlasCurrentChatModel();
        return [{ id: model, label: model, provider: 'ollama', configured: true }];
    }

    function fallbackCyberAtlasCompareModel() {
        const current = cyberAtlasDraft.model || cyberAtlasCurrentChatModel();
        const alternative = cyberAtlasCurrentProfiles().find(profile => profile.id !== current && profile.configured !== false);
        return alternative?.id || current;
    }

    function cyberAtlasModelOptionsHtml(selectedValue) {
        const profiles = cyberAtlasCurrentProfiles();
        const renderOption = (profile) => {
            const label = profile.label || profile.display_name || profile.name || profile.id || 'Model';
            const configured = profile.configured === false
                ? ` - ${cyberAtlasText('signalatlas.modelNotConfigured', 'not configured')}`
                : '';
            return `<option value="${cyberAtlasEscape(profile.id)}" ${profile.id === selectedValue ? 'selected' : ''}>${cyberAtlasEscape(label + configured)}</option>`;
        };
        return profiles.map(renderOption).join('');
    }

    function cyberAtlasProfileOptionsHtml(selectedValue) {
        return ['basic', 'elevated', 'ultra'].map(profile => {
            const label = cyberAtlasProfileLabel(profile);
            return `<option value="${profile}" ${profile === selectedValue ? 'selected' : ''}>${cyberAtlasEscape(label)}</option>`;
        }).join('');
    }

    function cyberAtlasBudgetOptionsHtml(steps, selectedValue) {
        const selected = Number(selectedValue);
        return steps.map(value => `<option value="${value}" ${Number(value) === selected ? 'selected' : ''}>${value}</option>`).join('');
    }

    function cyberAtlasAiLevelOptionsHtml(selectedValue) {
        const options = [
            ['no_ai', cyberAtlasText('cyberatlas.aiLevelNone', 'No AI')],
            ['basic_summary', cyberAtlasText('signalatlas.levelBasic', 'Basic summary')],
            ['full_expert_analysis', cyberAtlasText('signalatlas.levelFull', 'Full expert analysis')],
            ['ai_remediation_pack', cyberAtlasText('signalatlas.levelRemediation', 'AI remediation pack')],
        ];
        return options.map(([value, label]) => `<option value="${value}" ${value === selectedValue ? 'selected' : ''}>${cyberAtlasEscape(label)}</option>`).join('');
    }

    function cyberAtlasPresetOptionsHtml(selectedValue) {
        const options = [
            ['fast', cyberAtlasText('signalatlas.presetFast', 'Fast')],
            ['balanced', cyberAtlasText('signalatlas.presetBalanced', 'Balanced')],
            ['expert', cyberAtlasText('signalatlas.presetExpert', 'Expert')],
            ['local_private', cyberAtlasText('signalatlas.presetLocalPrivate', 'Local private')],
        ];
        return options.map(([value, label]) => `<option value="${value}" ${value === selectedValue ? 'selected' : ''}>${cyberAtlasEscape(label)}</option>`).join('');
    }

    function cyberAtlasProfileLabel(profile) {
        const clean = String(profile || '').trim().toLowerCase();
        if (clean === 'basic') return cyberAtlasText('cyberatlas.profileBasic', 'Basic');
        if (clean === 'ultra') return cyberAtlasText('cyberatlas.profileUltra', 'Ultra');
        return cyberAtlasText('cyberatlas.profileElevated', 'Elevated');
    }

    function cyberAtlasModeLabel(mode) {
        const clean = String(mode || '').trim().toLowerCase();
        if (clean === 'verified_owner') return cyberAtlasText('cyberatlas.ownerMode', 'Verified owner');
        return cyberAtlasText('cyberatlas.publicMode', 'Public audit');
    }

    function cyberAtlasStatusLabel(status) {
        const clean = String(status || '').trim().toLowerCase();
        if (clean === 'queued') return cyberAtlasText('cyberatlas.statusQueued', 'Queued');
        if (clean === 'running') return cyberAtlasText('cyberatlas.statusRunning', 'Running');
        if (['done', 'active', 'configured', 'ready'].includes(clean)) return cyberAtlasText('cyberatlas.statusDone', 'Ready');
        if (clean === 'error') return cyberAtlasText('cyberatlas.statusError', 'Error');
        if (clean === 'cancelled') return cyberAtlasText('cyberatlas.statusCancelled', 'Cancelled');
        if (clean === 'cancelling') return cyberAtlasText('cyberatlas.statusCancelling', 'Cancelling');
        return cyberAtlasText('cyberatlas.statusUnknown', 'Unknown');
    }

    function cyberAtlasSeverityLabel(value) {
        const clean = String(value || 'info').trim().toLowerCase();
        return cyberAtlasText(`cyberatlas.severity_${cyberAtlasAuditKey(clean)}`, clean || 'info');
    }

    function cyberAtlasSeverityTone(value) {
        if (typeof signalAtlasSeverityTone === 'function') return signalAtlasSeverityTone(value);
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'critical' || clean === 'high') return 'is-danger';
        if (clean === 'medium') return 'is-warn';
        return 'is-good';
    }

    function cyberAtlasScoreTone(score) {
        if (typeof signalAtlasScoreTone === 'function') return signalAtlasScoreTone(score);
        const numeric = Number(score || 0);
        if (numeric >= 85) return 'is-good';
        if (numeric >= 65) return 'is-warn';
        return 'is-danger';
    }

    function cyberAtlasConfidenceLabel(value) {
        if (typeof signalAtlasConfidenceLabel === 'function') return signalAtlasConfidenceLabel(value);
        const key = cyberAtlasAuditKey(value || 'unknown');
        return cyberAtlasText(`cyberatlas.confidence_${key}`, value || 'Unknown');
    }

    function cyberAtlasBoolLabel(value) {
        return value ? cyberAtlasText('cyberatlas.yes', 'Yes') : cyberAtlasText('cyberatlas.no', 'No');
    }

    function cyberAtlasNoneLabel() {
        return cyberAtlasText('cyberatlas.none', 'None');
    }

    function cyberAtlasSurfaceStatusLabel(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'ok') return cyberAtlasText('cyberatlas.surfaceOk', 'OK');
        if (clean === 'review') return cyberAtlasText('cyberatlas.surfaceReview', 'Review');
        if (clean === 'weak') return cyberAtlasText('cyberatlas.surfaceWeak', 'Weak');
        return cyberAtlasText('cyberatlas.statusUnknown', 'Unknown');
    }

    function cyberAtlasSurfaceStatusTone(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'ok') return 'is-good';
        if (clean === 'review') return 'is-warn';
        return 'is-danger';
    }

    function cyberAtlasStandardStatusLabel(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'attention') return cyberAtlasText('cyberatlas.statusAttention', 'Needs attention');
        if (clean === 'owner_review') return cyberAtlasText('cyberatlas.statusOwnerReview', 'Owner review');
        if (clean === 'clear') return cyberAtlasText('cyberatlas.statusClear', 'Clear');
        return cyberAtlasText('cyberatlas.statusUnknown', 'Unknown');
    }

    function cyberAtlasStandardStatusTone(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'attention') return 'is-danger';
        if (clean === 'owner_review') return 'is-warn';
        return 'is-good';
    }

    function cyberAtlasComparisonLabel(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'regressed') return cyberAtlasText('cyberatlas.comparisonRegressed', 'Regressed');
        if (clean === 'improved') return cyberAtlasText('cyberatlas.comparisonImproved', 'Improved');
        if (clean === 'stable') return cyberAtlasText('cyberatlas.comparisonStable', 'Stable');
        return cyberAtlasText('cyberatlas.comparisonBaseline', 'Baseline');
    }

    function cyberAtlasComparisonTone(value) {
        const clean = String(value || '').trim().toLowerCase();
        if (clean === 'improved') return 'is-good';
        if (clean === 'regressed') return 'is-danger';
        return 'is-warn';
    }

    function cyberAtlasPhaseLabel(phase) {
        const clean = String(phase || '').trim().toLowerCase();
        if (clean === 'tls') return cyberAtlasText('cyberatlas.phaseTls', 'TLS');
        if (clean === 'crawl') return cyberAtlasText('cyberatlas.phaseCrawl', 'Sampling');
        if (clean === 'headers') return cyberAtlasText('cyberatlas.phaseHeaders', 'Headers');
        if (clean === 'exposure') return cyberAtlasText('cyberatlas.phaseExposure', 'Exposure');
        if (clean === 'api') return cyberAtlasText('cyberatlas.phaseApi', 'API surface');
        if (clean === 'score') return cyberAtlasText('cyberatlas.phaseScore', 'Scoring');
        if (clean === 'ai') return cyberAtlasText('cyberatlas.phaseAi', 'AI interpretation');
        if (clean === 'queued') return cyberAtlasText('cyberatlas.phaseQueued', 'Queued');
        if (clean === 'cancelling') return cyberAtlasText('cyberatlas.phaseCancelling', 'Cancelling');
        if (clean === 'cancelled') return cyberAtlasText('cyberatlas.phaseCancelled', 'Cancelled');
        if (clean === 'done') return cyberAtlasText('cyberatlas.phaseDone', 'Done');
        if (clean === 'error') return cyberAtlasText('cyberatlas.phaseError', 'Error');
        return cyberAtlasStatusLabel(clean || 'unknown');
    }

    function cyberAtlasJobMessage(job) {
        const raw = String(job?.message || '').trim();
        if (!raw) return cyberAtlasPhaseLabel(job?.phase || job?.status);
        if (/^Validating TLS and canonical entrypoint$/i.test(raw)) return cyberAtlasText('cyberatlas.progressTls', 'Validating TLS and the canonical entrypoint');
        if (/^Sampling public pages and forms$/i.test(raw)) return cyberAtlasText('cyberatlas.progressCrawl', 'Sampling public pages and forms');
        if (/^Sampling /i.test(raw)) return cyberAtlasText('cyberatlas.progressSampling', 'Sampling {target}', { target: raw.replace(/^Sampling\s+/i, '') });
        if (/^Analyzing security headers and browser hardening$/i.test(raw)) return cyberAtlasText('cyberatlas.progressHeaders', 'Analyzing security headers and browser hardening');
        if (/^Running safe public exposure probes$/i.test(raw)) return cyberAtlasText('cyberatlas.progressExposure', 'Running safe public exposure probes');
        if (/^Extracting frontend API and stack hints$/i.test(raw)) return cyberAtlasText('cyberatlas.progressFrontend', 'Extracting frontend API and stack hints');
        if (/^Parsing OpenAPI and API surface signals$/i.test(raw)) return cyberAtlasText('cyberatlas.progressApi', 'Parsing OpenAPI and API surface signals');
        if (/^Scoring defensive security posture$/i.test(raw)) return cyberAtlasText('cyberatlas.progressScore', 'Scoring defensive security posture');
        if (/^Building remediation action plan$/i.test(raw)) return cyberAtlasText('cyberatlas.progressActionPlan', 'Building remediation action plan');
        if (/^Generating defensive AI interpretation$/i.test(raw)) return cyberAtlasText('cyberatlas.progressAi', 'Generating defensive AI interpretation');
        if (/^Preparing defensive audit excerpt$/i.test(raw)) return cyberAtlasText('cyberatlas.progressPreparingAi', 'Preparing defensive audit excerpt');
        if (/^Generating first defensive interpretation$/i.test(raw)) return cyberAtlasText('cyberatlas.progressFirstAi', 'Generating first defensive interpretation');
        if (/^Generating second defensive interpretation$/i.test(raw)) return cyberAtlasText('cyberatlas.progressSecondAi', 'Generating second defensive interpretation');
        if (/^CyberAtlas audit complete$/i.test(raw)) return cyberAtlasText('cyberatlas.progressComplete', 'CyberAtlas audit complete');
        return raw;
    }

    function cyberAtlasIsTerminalStatus(status) {
        return ['done', 'error', 'cancelled'].includes(String(status || '').trim().toLowerCase());
    }

    function cyberAtlasKnownAuditStatus(auditId) {
        const cleanId = String(auditId || '').trim();
        if (!cleanId) return '';
        const summary = cyberAtlasAudits.find(item => String(item?.id || '').trim() === cleanId);
        if (summary?.status) return String(summary.status).toLowerCase();
        if (String(cyberAtlasCurrentAudit?.id || '') === cleanId && cyberAtlasCurrentAudit?.status) {
            return String(cyberAtlasCurrentAudit.status).toLowerCase();
        }
        return '';
    }

    function activeCyberAtlasJobs() {
        if (typeof activeAuditModuleJobs === 'function') {
            return activeAuditModuleJobs('cyberatlas')
                .filter(job => {
                    const auditId = String(job?.metadata?.audit_id || '').trim();
                    return auditId && !cyberAtlasIsTerminalStatus(cyberAtlasKnownAuditStatus(auditId));
                })
                .sort((left, right) => String(right?.updated_at || '').localeCompare(String(left?.updated_at || '')));
        }
        return [];
    }

    function activeCyberAtlasJobForAudit(auditId) {
        return activeCyberAtlasJobs().find(job => String(job?.metadata?.audit_id || '') === String(auditId || '')) || null;
    }

    function cyberAtlasJobProgress(job) {
        if (typeof signalAtlasJobProgress === 'function') return signalAtlasJobProgress(job);
        const value = Number(job?.progress ?? 0);
        return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0;
    }

    function cyberAtlasAuditProgressState(audit) {
        const auditId = typeof audit === 'string' ? audit : audit?.id;
        const localStatus = String((typeof audit === 'object' && audit?.status) || '').trim().toLowerCase();
        const currentStatus = cyberAtlasIsTerminalStatus(cyberAtlasKnownAuditStatus(auditId))
            ? cyberAtlasKnownAuditStatus(auditId)
            : (localStatus || cyberAtlasKnownAuditStatus(auditId));
        if (cyberAtlasIsTerminalStatus(currentStatus)) return null;
        const liveJob = auditId ? activeCyberAtlasJobForAudit(auditId) : null;
        if (liveJob) {
            return {
                job: liveJob,
                auditId,
                status: String(liveJob.status || 'running').toLowerCase(),
                phase: cyberAtlasPhaseLabel(liveJob.phase || liveJob.status),
                progress: cyberAtlasJobProgress(liveJob),
                message: cyberAtlasJobMessage(liveJob),
            };
        }
        if (['queued', 'running', 'cancelling'].includes(currentStatus)) {
            return {
                job: null,
                auditId,
                status: currentStatus,
                phase: cyberAtlasPhaseLabel(currentStatus),
                progress: currentStatus === 'queued' ? 3 : 18,
                message: cyberAtlasStatusLabel(currentStatus),
            };
        }
        return null;
    }

    function cyberAtlasAnyProgressState() {
        const current = cyberAtlasCurrentAudit ? cyberAtlasAuditProgressState(cyberAtlasCurrentAudit) : null;
        if (current) return current;
        for (const audit of cyberAtlasAudits) {
            const state = cyberAtlasAuditProgressState(audit);
            if (state) return state;
        }
        const fallbackJob = activeCyberAtlasJobs()[0] || null;
        if (!fallbackJob) return null;
        return {
            job: fallbackJob,
            auditId: fallbackJob?.metadata?.audit_id || null,
            status: String(fallbackJob.status || 'running').toLowerCase(),
            phase: cyberAtlasPhaseLabel(fallbackJob.phase || fallbackJob.status),
            progress: cyberAtlasJobProgress(fallbackJob),
            message: cyberAtlasJobMessage(fallbackJob),
        };
    }

    function seedCyberAtlasRuntimeJob(job, fallbackAuditId = '') {
        if (typeof seedAuditModuleRuntimeJob === 'function') {
            seedAuditModuleRuntimeJob(
                job,
                'cyberatlas',
                fallbackAuditId,
                cyberAtlasText('cyberatlas.launchingAudit', 'Starting the security runtime...')
            );
        }
    }

    function clearCyberAtlasRuntimeJobsForAudit(auditId) {
        const cleanAuditId = String(auditId || '').trim();
        if (!cleanAuditId || typeof runtimeJobsCache === 'undefined' || !Array.isArray(runtimeJobsCache)) return;
        const before = runtimeJobsCache.length;
        runtimeJobsCache = runtimeJobsCache.filter(job =>
            job?.metadata?.module_id !== 'cyberatlas'
            || String(job?.metadata?.audit_id || '') !== cleanAuditId
            || !['queued', 'running', 'cancelling'].includes(String(job?.status || '').toLowerCase())
        );
        if (runtimeJobsCache.length !== before && typeof renderRuntimeJobs === 'function') renderRuntimeJobs();
    }

    function summarizeCyberAtlasAudit(audit) {
        const summary = audit?.summary || {};
        const target = audit?.target || {};
        return {
            id: audit?.id,
            title: audit?.title || target.host || target.normalized_url || cyberAtlasText('cyberatlas.untitledAudit', 'Untitled audit'),
            status: audit?.status || 'unknown',
            updated_at: audit?.updated_at,
            created_at: audit?.created_at,
            target_url: target.normalized_url || target.raw || summary.target || '',
            host: target.host || '',
            mode: target.mode || summary.mode || 'public',
            global_score: summary.global_score,
            security_grade: summary.security_grade || '',
            pages_crawled: summary.pages_crawled || 0,
            endpoint_count: summary.endpoint_count || 0,
            exposure_count: summary.exposure_count || 0,
            public_sensitive_endpoint_count: summary.public_sensitive_endpoint_count || 0,
            source_map_count: summary.source_map_count || 0,
            critical_count: summary.critical_count || 0,
            high_count: summary.high_count || 0,
            risk_level: summary.risk_level || 'unknown',
            top_risk: summary.top_risk || '',
            comparison_status: audit?.comparison?.status || '',
            score_delta: audit?.comparison?.score_delta || 0,
            high_delta: audit?.comparison?.high_delta || 0,
            has_ai: Array.isArray(audit?.interpretations) && audit.interpretations.length > 0,
            report_model_label: ((audit?.interpretations || [])[audit?.interpretations?.length - 1] || {}).model || ((audit?.metadata || {}).ai || {}).model || '',
            report_model_state: (audit?.interpretations || []).length ? 'generated' : (((audit?.metadata || {}).ai || {}).model ? 'planned' : 'none'),
        };
    }

    async function loadCyberAtlasBootstrap() {
        if (typeof apiCyberAtlas === 'undefined') return;
        const [auditsResult, modelResult] = await Promise.all([
            apiCyberAtlas.listAudits(60),
            apiCyberAtlas.getModelContext(),
        ]);
        cyberAtlasAudits = Array.isArray(auditsResult.data?.audits) ? auditsResult.data.audits : [];
        cyberAtlasModelContext = modelResult.ok ? modelResult.data : null;
        await refreshCyberAtlasProviderStatus();

        if (!cyberAtlasDraft.model) cyberAtlasDraft.model = cyberAtlasCurrentChatModel();
        if (!cyberAtlasDraft.compare_model) cyberAtlasDraft.compare_model = fallbackCyberAtlasCompareModel();

        if (cyberAtlasCurrentAuditId) {
            await loadCyberAtlasAudit(cyberAtlasCurrentAuditId, { silent: true });
        } else if (cyberAtlasAudits.length) {
            cyberAtlasCurrentAuditId = cyberAtlasAudits[0].id;
            await loadCyberAtlasAudit(cyberAtlasCurrentAuditId, { silent: true });
        }
    }

    async function refreshCyberAtlasProviderStatus() {
        if (typeof apiCyberAtlas === 'undefined') return [];
        const result = await apiCyberAtlas.getProviderStatus(cyberAtlasDraft.target || '', cyberAtlasDraft.mode || 'public');
        cyberAtlasProviders = Array.isArray(result.data?.providers) ? result.data.providers : [];
        return cyberAtlasProviders;
    }

    async function loadCyberAtlasAudit(auditId, options = {}) {
        if (!auditId || typeof apiCyberAtlas === 'undefined') return null;
        const result = await apiCyberAtlas.getAudit(auditId);
        if (!result.ok || !result.data?.audit) {
            if (!options.silent) Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.loadError', 'Unable to load this audit.'));
            return null;
        }
        cyberAtlasCurrentAuditId = auditId;
        cyberAtlasCurrentAudit = result.data.audit;
        if (cyberAtlasIsTerminalStatus(cyberAtlasCurrentAudit.status)) {
            clearCyberAtlasRuntimeJobsForAudit(auditId);
        }
        const existing = cyberAtlasAudits.findIndex(item => item.id === auditId);
        const summaryCard = summarizeCyberAtlasAudit(cyberAtlasCurrentAudit);
        if (existing >= 0) cyberAtlasAudits.splice(existing, 1, summaryCard);
        else cyberAtlasAudits.unshift(summaryCard);
        cyberAtlasAudits.sort((left, right) => String(right.updated_at || '').localeCompare(String(left.updated_at || '')));
        return cyberAtlasCurrentAudit;
    }

    function syncCyberAtlasDraftFromDom() {
        const targetInput = document.getElementById('cyberatlas-target-input');
        const profile = document.getElementById('cyberatlas-profile-select');
        const modeSelect = document.getElementById('cyberatlas-mode-select');
        const maxPages = document.getElementById('cyberatlas-max-pages');
        const maxEndpoints = document.getElementById('cyberatlas-max-endpoints');
        const activeChecks = document.getElementById('cyberatlas-active-checks');
        const model = document.getElementById('cyberatlas-model-select');
        const preset = document.getElementById('cyberatlas-preset-select');
        const level = document.getElementById('cyberatlas-level-select');
        const compareModel = document.getElementById('cyberatlas-compare-model-select');

        if (targetInput) cyberAtlasDraft.target = targetInput.value;
        if (profile) cyberAtlasDraft.profile = profile.value;
        if (modeSelect) cyberAtlasDraft.mode = modeSelect.value;
        if (maxPages) cyberAtlasDraft.max_pages = cyberAtlasNormalizeBudget(maxPages.value, cyberAtlasDraft.max_pages, CYBERATLAS_MAX_PAGE_BUDGET);
        if (maxEndpoints) cyberAtlasDraft.max_endpoints = cyberAtlasNormalizeBudget(maxEndpoints.value, cyberAtlasDraft.max_endpoints, CYBERATLAS_MAX_ENDPOINT_BUDGET);
        if (activeChecks) cyberAtlasDraft.active_checks = !!activeChecks.checked;
        if (model) cyberAtlasDraft.model = model.value;
        if (preset) cyberAtlasDraft.preset = preset.value;
        if (level) cyberAtlasDraft.level = level.value;
        if (compareModel) cyberAtlasDraft.compare_model = compareModel.value;
    }

    function applyCyberAtlasProfile(profile) {
        const preset = CYBERATLAS_AUDIT_PROFILES[profile] || CYBERATLAS_AUDIT_PROFILES.elevated;
        cyberAtlasDraft.profile = profile || 'elevated';
        cyberAtlasDraft.max_pages = preset.max_pages;
        cyberAtlasDraft.max_endpoints = preset.max_endpoints;
        cyberAtlasDraft.preset = preset.preset;
        cyberAtlasDraft.level = preset.level;
        cyberAtlasDraft.active_checks = preset.active_checks;
    }

    function cyberAtlasProfileChanged(event) {
        applyCyberAtlasProfile(String(event?.target?.value || 'elevated'));
        renderCyberAtlasWorkspace();
    }

    async function cyberAtlasControlsChanged() {
        syncCyberAtlasDraftFromDom();
        await refreshCyberAtlasProviderStatus();
        renderCyberAtlasWorkspace();
    }

    function cyberAtlasTargetInputChanged(event) {
        cyberAtlasDraft.target = String(event?.target?.value || '');
        renderCyberAtlasTargetValidationUi();
    }

    function renderCyberAtlasTargetValidationUi() {
        const validation = cyberAtlasValidateTarget(cyberAtlasDraft.target);
        const input = document.getElementById('cyberatlas-target-input');
        const feedback = document.getElementById('cyberatlas-target-feedback');
        const launch = document.getElementById('cyberatlas-launch-btn');
        if (input) {
            input.classList.toggle('is-invalid', validation.present && !validation.valid);
            input.setAttribute('aria-invalid', validation.present && !validation.valid ? 'true' : 'false');
        }
        if (feedback) {
            feedback.classList.toggle('is-visible', validation.present && !validation.valid);
            feedback.textContent = validation.present && !validation.valid ? validation.message : '';
        }
        if (launch?.dataset?.action === 'launch') {
            launch.disabled = cyberAtlasLaunchPending || !validation.valid;
        }
    }

    function renderCyberAtlasProviderStrip() {
        if (!Array.isArray(cyberAtlasProviders) || !cyberAtlasProviders.length) return '';
        return `
            <section class="signalatlas-owner-strip cyberatlas-provider-strip">
                ${cyberAtlasProviders.map(provider => `
                    <div class="signalatlas-owner-card">
                        <div class="signalatlas-owner-card-top">
                            <span class="signalatlas-owner-name">${cyberAtlasEscape(provider.name || provider.id || 'Provider')}</span>
                            <span class="signalatlas-tag is-good">${cyberAtlasEscape(cyberAtlasStatusLabel(provider.status || 'configured'))}</span>
                        </div>
                        <div class="signalatlas-owner-note">${cyberAtlasEscape(provider.detail || cyberAtlasText('cyberatlas.providerSafeEvidence', 'Defensive HTTP evidence is available.'))}</div>
                    </div>
                `).join('')}
            </section>
        `;
    }

    function renderCyberAtlasHistory() {
        if (!cyberAtlasAudits.length) {
            return `<div class="signalatlas-history-empty">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noAudits', 'No audits yet. Launch one to create the first security report.'))}</div>`;
        }
        return cyberAtlasAudits.map(audit => {
            const active = audit.id === cyberAtlasCurrentAuditId;
            const progressState = cyberAtlasAuditProgressState(audit);
            const canDelete = !progressState;
            const displayProgress = progressState && typeof auditDisplayProgress === 'function'
                ? auditDisplayProgress('cyberatlas', progressState, audit, false)
                : cyberAtlasJobProgress(progressState);
            const timestamp = typeof nativeAuditTimestampLabel === 'function'
                ? nativeAuditTimestampLabel('cyberatlas', audit)
                : '';
            return `
                <div
                    class="signalatlas-history-card${active ? ' active' : ''}"
                    role="button"
                    tabindex="0"
                    onclick="openCyberAtlasWorkspace('${cyberAtlasEscape(audit.id)}')"
                    onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openCyberAtlasWorkspace('${cyberAtlasEscape(audit.id)}');}"
                >
                    <div class="signalatlas-history-top">
                        <div class="signalatlas-history-title-wrap">
                            <div class="signalatlas-history-title">${cyberAtlasEscape(audit.title || audit.host || audit.target_url || 'Audit')}</div>
                            <div class="signalatlas-history-status">${cyberAtlasEscape(cyberAtlasStatusLabel(audit.status))}</div>
                        </div>
                        <button
                            class="signalatlas-history-delete"
                            type="button"
                            onclick="deleteCyberAtlasAudit('${cyberAtlasEscape(audit.id)}', event)"
                            aria-label="${cyberAtlasEscape(canDelete ? cyberAtlasText('cyberatlas.deleteAudit', 'Delete audit') : cyberAtlasText('cyberatlas.deleteAuditBlocked', 'Cancel this audit before deleting it.'))}"
                            title="${cyberAtlasEscape(canDelete ? cyberAtlasText('cyberatlas.deleteAudit', 'Delete audit') : cyberAtlasText('cyberatlas.deleteAuditBlocked', 'Cancel this audit before deleting it.'))}"
                            ${canDelete ? '' : 'disabled'}
                        >
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                    <div class="signalatlas-history-meta">
                        <span>${cyberAtlasEscape(audit.host || '')}</span>
                        <span>${cyberAtlasEscape(cyberAtlasModeLabel(audit.mode || 'public'))}</span>
                    </div>
                    ${timestamp ? `<div class="signalatlas-history-timestamp">${cyberAtlasEscape(timestamp)}</div>` : ''}
                    <div class="signalatlas-history-footer">
                        <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.scoreShort', 'Score'))}: ${cyberAtlasEscape(String(audit.global_score ?? '--'))}</span>
                        <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.securityGrade', 'Grade'))}: ${cyberAtlasEscape(audit.security_grade || '--')}</span>
                        <span>${cyberAtlasEscape(cyberAtlasComparisonLabel(audit.comparison_status || 'baseline'))}</span>
                        <span>${cyberAtlasEscape(String(audit.endpoint_count || 0))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.endpointsShort', 'endpoints'))}</span>
                    </div>
                    ${progressState ? `
                        <div class="signalatlas-history-progress-meta">
                            <span class="signalatlas-progress-chip is-phase">${cyberAtlasEscape(progressState.phase)}</span>
                            <span class="signalatlas-progress-chip is-percent">${cyberAtlasEscape(cyberAtlasText('cyberatlas.progressPercent', '{value}%', { value: displayProgress }))}</span>
                        </div>
                        <div class="signalatlas-history-progress-bar is-live">
                            <div class="signalatlas-history-progress-fill is-live" style="width:${cyberAtlasEscape(String(displayProgress))}%"></div>
                        </div>
                        <div class="signalatlas-history-progress-copy signalatlas-shimmer-text" aria-live="polite">${cyberAtlasEscape(progressState.message)}</div>
                    ` : ''}
                </div>
            `;
        }).join('');
    }

    function renderCyberAtlasScoreCards(audit) {
        const scores = Array.isArray(audit?.scores) ? audit.scores : [];
        if (!scores.length) return '';
        return scores.map(score => `
            <div class="signalatlas-score-card ${cyberAtlasScoreTone(score.score)}">
                <div class="signalatlas-score-label">${cyberAtlasEscape(score.label || score.id || 'Score')}</div>
                <div class="signalatlas-score-value">${cyberAtlasEscape(String(score.score ?? '--'))}</div>
                <div class="signalatlas-score-meta">${cyberAtlasEscape(cyberAtlasConfidenceLabel(score.confidence || ''))}</div>
            </div>
        `).join('');
    }

    function renderCyberAtlasFindings(audit, limit = 8) {
        const items = Array.isArray(audit?.findings) ? audit.findings.slice(0, limit) : [];
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noFindings', 'No blocking cyber finding was detected in the sampled evidence.'))}</div>`;
        }
        return items.map(item => `
            <article class="signalatlas-finding-card">
                <div class="signalatlas-finding-top">
                    <div>
                        <div class="signalatlas-finding-title">${cyberAtlasEscape(item.title || item.id || 'Finding')}</div>
                        <div class="signalatlas-finding-copy">${cyberAtlasEscape(item.diagnostic || item.relationship_summary || '')}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasSeverityTone(item.severity)}">${cyberAtlasEscape(cyberAtlasSeverityLabel(item.severity || 'info'))}</span>
                </div>
                <div class="signalatlas-mini-finding-copy">${cyberAtlasEscape(item.recommended_fix || '')}</div>
                <div class="signalatlas-finding-meta">
                    <span>${cyberAtlasEscape(item.category || item.bucket || '')}</span>
                    <span>${cyberAtlasEscape(cyberAtlasConfidenceLabel(item.confidence || ''))}</span>
                    <span>${cyberAtlasEscape(item.scope || '')}</span>
                </div>
                ${(item.evidence || []).length ? `
                    <div class="cyberatlas-evidence-list">
                        ${(item.evidence || []).slice(0, 3).map(evidence => `
                            <div class="cyberatlas-evidence-card">
                                <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(evidence)}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </article>
        `).join('');
    }

    function renderCyberAtlasActionPlan(audit, limit = 8) {
        const items = Array.isArray(audit?.action_plan) ? audit.action_plan.slice(0, limit) : [];
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noActionPlan', 'No action plan is available yet.'))}</div>`;
        }
        return items.map(item => `
            <article class="signalatlas-finding-card cyberatlas-action-card">
                <div class="signalatlas-finding-top">
                    <div>
                        <div class="signalatlas-finding-title">${cyberAtlasEscape(item.order ? `${item.order}. ${item.title || item.id || ''}` : (item.title || item.id || ''))}</div>
                        <div class="signalatlas-finding-copy">${cyberAtlasEscape(item.description || '')}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasSeverityTone(item.priority)}">${cyberAtlasEscape(cyberAtlasSeverityLabel(item.priority || 'low'))}</span>
                </div>
                <div class="signalatlas-mini-finding-copy"><strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.action', 'Action'))}:</strong> ${cyberAtlasEscape(item.action || '')}</div>
                <div class="signalatlas-mini-finding-copy"><strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.validation', 'Validation'))}:</strong> ${cyberAtlasEscape(item.validation || '')}</div>
                ${(item.evidence || []).length ? `
                    <div class="cyberatlas-evidence-list">
                        ${(item.evidence || []).slice(0, 3).map(evidence => `
                            <div class="cyberatlas-evidence-card">
                                <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(evidence)}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </article>
        `).join('');
    }

    function renderCyberAtlasSurfaceMatrix(audit) {
        const items = Array.isArray(audit?.snapshot?.surface_matrix) ? audit.snapshot.surface_matrix : [];
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noSurfaceMatrix', 'No attack surface matrix is available yet.'))}</div>`;
        }
        return `
            <div class="cyberatlas-surface-grid">
                ${items.map(item => `
                    <article class="cyberatlas-surface-card ${cyberAtlasSurfaceStatusTone(item.status)}">
                        <div class="cyberatlas-surface-top">
                            <strong>${cyberAtlasEscape(item.label || item.id || '')}</strong>
                            <span class="signalatlas-tag ${cyberAtlasSurfaceStatusTone(item.status)}">${cyberAtlasEscape(cyberAtlasSurfaceStatusLabel(item.status))}</span>
                        </div>
                        <div class="cyberatlas-surface-signals">
                            ${(item.signals || []).slice(0, 4).map(signal => `<span>${cyberAtlasEscape(signal)}</span>`).join('')}
                        </div>
                        <p>${cyberAtlasEscape(item.next_action || '')}</p>
                    </article>
                `).join('')}
            </div>
        `;
    }

    function renderCyberAtlasOwnerVerification(audit) {
        const items = Array.isArray(audit?.owner_verification_plan)
            ? audit.owner_verification_plan
            : (Array.isArray(audit?.snapshot?.owner_verification_plan) ? audit.snapshot.owner_verification_plan : []);
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noOwnerVerificationPlan', 'No owner verification plan is available yet.'))}</div>`;
        }
        return items.slice(0, 12).map(item => `
            <article class="signalatlas-finding-card cyberatlas-owner-check-card">
                <div class="signalatlas-finding-top">
                    <div>
                        <div class="signalatlas-finding-title">${cyberAtlasEscape(item.title || item.id || '')}</div>
                        <div class="signalatlas-finding-copy">${cyberAtlasEscape(item.why || '')}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasSeverityTone(item.priority)}">${cyberAtlasEscape(cyberAtlasSeverityLabel(item.priority || 'low'))}</span>
                </div>
                <div class="signalatlas-finding-meta">
                    <span>${cyberAtlasEscape(item.category || '')}</span>
                    <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.ownerModeRequired', 'Owner mode required'))}</span>
                </div>
                ${(item.safe_steps || []).length ? `
                    <div class="cyberatlas-evidence-list">
                        ${(item.safe_steps || []).slice(0, 4).map(step => `
                            <div class="cyberatlas-evidence-card">
                                <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(step)}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                <div class="signalatlas-mini-finding-copy"><strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.validation', 'Validation'))}:</strong> ${cyberAtlasEscape(item.validation || '')}</div>
            </article>
        `).join('');
    }

    function renderCyberAtlasRiskPaths(audit) {
        const items = Array.isArray(audit?.attack_paths)
            ? audit.attack_paths
            : (Array.isArray(audit?.snapshot?.attack_paths) ? audit.snapshot.attack_paths : []);
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noRiskPaths', 'No chained risk path was generated from the sampled evidence.'))}</div>`;
        }
        return items.slice(0, 8).map(item => `
            <article class="signalatlas-finding-card cyberatlas-risk-path-card">
                <div class="signalatlas-finding-top">
                    <div>
                        <div class="signalatlas-finding-title">${cyberAtlasEscape(item.title || item.id || '')}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasSeverityTone(item.severity)}">${cyberAtlasEscape(cyberAtlasSeverityLabel(item.severity || 'medium'))}</span>
                </div>
                <div class="cyberatlas-risk-path-columns">
                    <div>
                        <div class="signalatlas-mini-finding-title">${cyberAtlasEscape(cyberAtlasText('cyberatlas.riskChain', 'Risk chain'))}</div>
                        ${(item.chain || []).map(link => `<div class="cyberatlas-path-step">${cyberAtlasEscape(link)}</div>`).join('')}
                    </div>
                    <div>
                        <div class="signalatlas-mini-finding-title">${cyberAtlasEscape(cyberAtlasText('cyberatlas.breakpoints', 'Breakpoints'))}</div>
                        ${(item.breakpoints || []).map(link => `<div class="cyberatlas-path-step is-break">${cyberAtlasEscape(link)}</div>`).join('')}
                    </div>
                </div>
            </article>
        `).join('');
    }

    function renderCyberAtlasCoverage(audit) {
        const coverage = audit?.coverage || audit?.snapshot?.coverage || {};
        const checks = Array.isArray(coverage.checks) ? coverage.checks : [];
        if (!checks.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noCoverage', 'No coverage summary is available yet.'))}</div>`;
        }
        return `
            <div class="signalatlas-metric-grid">
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.coverageConfidence', 'Coverage confidence'))}</span><strong>${cyberAtlasEscape(String(coverage.confidence_score ?? '--'))}</strong></div>
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.confirmedFindings', 'Confirmed findings'))}</span><strong>${cyberAtlasEscape(String(coverage.confirmed_findings || 0))}</strong></div>
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.strongSignals', 'Strong signals'))}</span><strong>${cyberAtlasEscape(String(coverage.strong_signal_findings || 0))}</strong></div>
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.estimatedFindings', 'Estimated findings'))}</span><strong>${cyberAtlasEscape(String(coverage.estimated_findings || 0))}</strong></div>
            </div>
            <div class="cyberatlas-surface-grid">
                ${checks.map(item => `
                    <article class="cyberatlas-surface-card ${item.status === 'covered' ? 'is-good' : 'is-warn'}">
                        <div class="cyberatlas-surface-top">
                            <strong>${cyberAtlasEscape(item.label || item.id || '')}</strong>
                            <span class="signalatlas-tag ${item.status === 'covered' ? 'is-good' : 'is-warn'}">${cyberAtlasEscape(item.status || '')}</span>
                        </div>
                        <div class="cyberatlas-surface-signals">
                            <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.evidenceCount', 'Evidence count'))}: ${cyberAtlasEscape(String(item.evidence_count || 0))}</span>
                            <span>${cyberAtlasEscape(item.limit || '')}</span>
                        </div>
                    </article>
                `).join('')}
            </div>
            <div class="signalatlas-panel-copy">${cyberAtlasEscape(coverage.public_mode_limit || '')}</div>
        `;
    }

    function renderCyberAtlasStandards(audit) {
        const items = Array.isArray(audit?.standard_map)
            ? audit.standard_map
            : (Array.isArray(audit?.snapshot?.standard_map) ? audit.snapshot.standard_map : []);
        const visible = items.filter(item => item.status !== 'clear');
        if (!visible.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noStandardsMap', 'No standard mapping requires attention yet.'))}</div>`;
        }
        return `
            <div class="cyberatlas-standard-grid">
                ${visible.slice(0, 16).map(item => `
                    <article class="cyberatlas-standard-card ${cyberAtlasStandardStatusTone(item.status)}">
                        <div class="cyberatlas-standard-top">
                            <div>
                                <div class="cyberatlas-standard-ref">${cyberAtlasEscape(item.framework || '')} ${cyberAtlasEscape(item.id || '')}</div>
                                <strong>${cyberAtlasEscape(item.label || '')}</strong>
                            </div>
                            <span class="signalatlas-tag ${cyberAtlasStandardStatusTone(item.status)}">${cyberAtlasEscape(cyberAtlasStandardStatusLabel(item.status))}</span>
                        </div>
                        <div class="cyberatlas-surface-signals">
                            <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.severityLabel', 'Severity'))}: ${cyberAtlasEscape(cyberAtlasSeverityLabel(item.severity || 'info'))}</span>
                            <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.findingCount', 'Finding count'))}: ${cyberAtlasEscape(String(item.finding_count || 0))}</span>
                            ${(item.finding_ids || []).length ? `<span>${cyberAtlasEscape((item.finding_ids || []).slice(0, 5).join(', '))}</span>` : ''}
                        </div>
                        <p>${cyberAtlasEscape(item.action || '')}</p>
                    </article>
                `).join('')}
            </div>
        `;
    }

    function renderCyberAtlasSecurityTickets(audit) {
        const items = Array.isArray(audit?.security_tickets)
            ? audit.security_tickets
            : (Array.isArray(audit?.snapshot?.security_tickets) ? audit.snapshot.security_tickets : []);
        if (!items.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noSecurityTickets', 'No security ticket has been generated yet.'))}</div>`;
        }
        return items.slice(0, 16).map(item => `
            <article class="signalatlas-finding-card cyberatlas-ticket-card">
                <div class="signalatlas-finding-top">
                    <div>
                        <div class="signalatlas-finding-title">${cyberAtlasEscape(item.title || item.id || '')}</div>
                        <div class="signalatlas-finding-copy">${cyberAtlasEscape(item.summary || '')}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasSeverityTone(item.priority)}">${cyberAtlasEscape(cyberAtlasSeverityLabel(item.priority || 'medium'))}</span>
                </div>
                <div class="signalatlas-finding-meta">
                    <span>${cyberAtlasEscape(item.type || '')}</span>
                    <span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.effort', 'Effort'))}: ${cyberAtlasEscape(item.effort || 'M')}</span>
                    ${item.owner_mode_required ? `<span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.ownerModeRequired', 'Owner mode required'))}</span>` : ''}
                </div>
                <div class="signalatlas-mini-finding-copy"><strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.implementationPrompt', 'Implementation prompt'))}:</strong> ${cyberAtlasEscape(item.implementation_prompt || item.implementation || '')}</div>
                <div class="signalatlas-mini-finding-copy"><strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.acceptanceCriteria', 'Acceptance criteria'))}:</strong> ${cyberAtlasEscape(item.acceptance_criteria || '')}</div>
                ${(item.validation_steps || []).length ? `
                    <div class="cyberatlas-evidence-list">
                        ${(item.validation_steps || []).slice(0, 4).map(step => `
                            <div class="cyberatlas-evidence-card">
                                <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(step)}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                ${(item.standards || []).length || (item.related_finding_ids || []).length ? `
                    <div class="signalatlas-finding-meta">
                        ${(item.standards || []).slice(0, 4).map(ref => `<span>${cyberAtlasEscape(ref)}</span>`).join('')}
                        ${(item.related_finding_ids || []).slice(0, 4).map(ref => `<span>${cyberAtlasEscape(ref)}</span>`).join('')}
                    </div>
                ` : ''}
            </article>
        `).join('');
    }

    function renderCyberAtlasEvidenceGraph(audit) {
        const graph = audit?.evidence_graph || audit?.snapshot?.evidence_graph || {};
        const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
        const edges = Array.isArray(graph.edges) ? graph.edges : [];
        if (!nodes.length && !edges.length) {
            return `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noEvidenceGraph', 'No evidence graph has been generated yet.'))}</div>`;
        }
        return `
            <div class="signalatlas-metric-grid">
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.graphNodes', 'Graph nodes'))}</span><strong>${cyberAtlasEscape(String(nodes.length))}</strong></div>
                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.graphEdges', 'Graph edges'))}</span><strong>${cyberAtlasEscape(String(edges.length))}</strong></div>
            </div>
            ${graph.note ? `<div class="signalatlas-panel-copy">${cyberAtlasEscape(graph.note)}</div>` : ''}
            <div class="cyberatlas-graph-grid">
                ${nodes.slice(0, 20).map(node => `
                    <div class="cyberatlas-graph-node ${node.kind === 'finding' ? cyberAtlasSeverityTone(node.severity) : ''}">
                        <strong>${cyberAtlasEscape(node.label || node.id || '')}</strong>
                        <span>${cyberAtlasEscape(node.kind || '')} · ${cyberAtlasEscape(cyberAtlasText('cyberatlas.weight', 'weight'))} ${cyberAtlasEscape(String(node.weight ?? 0))}</span>
                    </div>
                `).join('')}
            </div>
            ${edges.length ? `
                <div class="cyberatlas-evidence-list">
                    ${edges.slice(0, 24).map(edge => `
                        <div class="cyberatlas-evidence-card">
                            <div class="cyberatlas-evidence-title">${cyberAtlasEscape(edge.from || '')} -> ${cyberAtlasEscape(edge.to || '')}</div>
                            <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(edge.label || '')}</div>
                        </div>
                    `).join('')}
                </div>
            ` : ''}
        `;
    }

    function renderCyberAtlasComparison(audit) {
        const comparison = audit?.comparison || {};
        const status = comparison.status || 'baseline';
        return `
            <section class="signalatlas-panel">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.previousComparison', 'Previous comparison'))}</div>
                        <div class="signalatlas-panel-title">${cyberAtlasEscape(cyberAtlasComparisonLabel(status))}</div>
                    </div>
                    <span class="signalatlas-tag ${cyberAtlasComparisonTone(status)}">${cyberAtlasEscape(cyberAtlasComparisonLabel(status))}</span>
                </div>
                <div class="signalatlas-metric-grid">
                    <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.scoreDelta', 'Score delta'))}</span><strong>${cyberAtlasEscape(String(comparison.score_delta ?? 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.criticalDelta', 'Critical delta'))}</span><strong>${cyberAtlasEscape(String(comparison.critical_delta ?? 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.highDelta', 'High delta'))}</span><strong>${cyberAtlasEscape(String(comparison.high_delta ?? 0))}</strong></div>
                    <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.fixedFindings', 'Fixed findings'))}</span><strong>${cyberAtlasEscape(String((comparison.fixed_finding_ids || []).length))}</strong></div>
                </div>
                <div class="signalatlas-panel-copy">${cyberAtlasEscape(comparison.previous_audit_id ? cyberAtlasText('cyberatlas.comparedToPrevious', 'Compared with previous audit {id}', { id: comparison.previous_audit_id }) : cyberAtlasText('cyberatlas.noPreviousAudit', 'No previous completed audit for this target yet.'))}</div>
            </section>
        `;
    }

    function renderCyberAtlasOverview(audit) {
        const summary = audit?.summary || {};
        const snapshot = audit?.snapshot || {};
        const tls = snapshot.tls || {};
        const blockingRisk = summary.blocking_risk || {};
        const score = summary.global_score ?? '--';
        const ring = typeof renderSignalAtlasScoreRing === 'function'
            ? renderSignalAtlasScoreRing(summary.global_score, cyberAtlasText('cyberatlas.scoreShort', 'Score'), `cyberatlas-${audit.id}`)
            : `<div class="signalatlas-score-value">${cyberAtlasEscape(String(score))}</div>`;
        return `
            <div class="signalatlas-overview-stack">
                <section class="signalatlas-panel">
                    <div class="signalatlas-section-top">
                        <div>
                            <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.quickRead', 'Quick read'))}</div>
                            <div class="signalatlas-panel-title">${cyberAtlasEscape(cyberAtlasText('cyberatlas.executiveSummary', 'Defensive security posture'))}</div>
                        </div>
                        <div class="signalatlas-summary-badges">
                            <span class="signalatlas-inline-chip">${cyberAtlasEscape(cyberAtlasText('cyberatlas.riskLevel', 'Risk'))}: ${cyberAtlasEscape(summary.risk_level || 'Unknown')}</span>
                            <span class="signalatlas-inline-chip">${cyberAtlasEscape(cyberAtlasModeLabel(summary.mode || audit?.target?.mode || 'public'))}</span>
                        </div>
                    </div>
                    <div class="signalatlas-summary-grid">
                        <div class="signalatlas-score-wrap">${ring}</div>
                        <div class="signalatlas-summary-copy">
                            <p>${cyberAtlasEscape(blockingRisk.summary || summary.top_risk || cyberAtlasText('cyberatlas.noBlockingRisk', 'No blocking cyber exposure was detected in the sampled evidence.'))}</p>
                            <div class="signalatlas-metric-grid">
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.securityGrade', 'Grade'))}</span><strong>${cyberAtlasEscape(summary.security_grade || '--')}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.pagesSampled', 'Pages'))}</span><strong>${cyberAtlasEscape(String(summary.pages_crawled || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.exposures', 'Exposures'))}</span><strong>${cyberAtlasEscape(String(summary.exposure_count || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.endpoints', 'Endpoints'))}</span><strong>${cyberAtlasEscape(String(summary.endpoint_count || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.coverageConfidence', 'Coverage confidence'))}</span><strong>${cyberAtlasEscape(String(summary.coverage_confidence || '--'))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.ownerChecks', 'Owner checks'))}</span><strong>${cyberAtlasEscape(String(summary.owner_verification_count || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.standardAttention', 'Standards attention'))}</span><strong>${cyberAtlasEscape(String(summary.standard_attention_count || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.securityTickets', 'Security tickets'))}</span><strong>${cyberAtlasEscape(String(summary.security_ticket_count || 0))}</strong></div>
                                <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.tls', 'TLS'))}</span><strong>${cyberAtlasEscape(tls.available ? (tls.protocol || 'OK') : cyberAtlasText('cyberatlas.notAvailable', 'Unavailable'))}</strong></div>
                            </div>
                        </div>
                    </div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.actionPlan', 'Action plan'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasActionPlan(audit, 4)}</div>
                </section>
                ${renderCyberAtlasComparison(audit)}
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.scoreBreakdown', 'Score breakdown'))}</div>
                    <div class="signalatlas-score-card-grid">${renderCyberAtlasScoreCards(audit)}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.topPriorities', 'Top priorities'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasFindings(audit, 4)}</div>
                </section>
            </div>
        `;
    }

    function renderCyberAtlasEvidence(audit) {
        const snapshot = audit?.snapshot || {};
        const tls = snapshot.tls || {};
        const headers = snapshot.security_headers || {};
        const missing = Array.isArray(snapshot.missing_security_headers) ? snapshot.missing_security_headers : [];
        const probes = Array.isArray(snapshot.exposure_probes) ? snapshot.exposure_probes : [];
        const protections = snapshot.protections || {};
        const recon = snapshot.recon_summary || {};
        const frontend = snapshot.frontend_hints || {};
        return `
            <div class="signalatlas-detail-grid">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.tls', 'TLS'))}</div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.protocol', 'Protocol'))}</span><strong>${cyberAtlasEscape(tls.protocol || 'n/a')}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.daysRemaining', 'Days left'))}</span><strong>${cyberAtlasEscape(String(tls.days_remaining ?? 'n/a'))}</strong></div>
                    </div>
                    <div class="signalatlas-panel-copy">${cyberAtlasEscape(tls.error || tls.issuer || '')}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.securityHeaders', 'Security headers'))}</div>
                    <div class="signalatlas-finding-list">
                        ${Object.keys(headers).length ? Object.entries(headers).map(([key, value]) => `
                            <div class="signalatlas-mini-finding-card">
                                <div class="signalatlas-mini-finding-title">${cyberAtlasEscape(key)}</div>
                                <div class="signalatlas-mini-finding-copy">${cyberAtlasEscape(String(value).slice(0, 220))}</div>
                            </div>
                        `).join('') : `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noHeaders', 'No response headers were captured.'))}</div>`}
                    </div>
                    ${missing.length ? `<div class="signalatlas-panel-copy">${cyberAtlasEscape(cyberAtlasText('cyberatlas.missingHeaders', 'Missing headers'))}: ${cyberAtlasEscape(missing.join(', '))}</div>` : ''}
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.reconSummary', 'Recon summary'))}</div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.framework', 'Framework'))}</span><strong>${cyberAtlasEscape(recon.framework || 'n/a')}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.databaseHint', 'Database hint'))}</span><strong>${cyberAtlasEscape(recon.database_type || 'Unknown')}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.wafSignal', 'WAF'))}</span><strong>${cyberAtlasEscape(cyberAtlasBoolLabel(protections.waf_detected))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.rateLimitSignal', 'Rate limit'))}</span><strong>${cyberAtlasEscape(cyberAtlasBoolLabel(protections.rate_limit_detected))}</strong></div>
                    </div>
                    <div class="signalatlas-panel-copy">${cyberAtlasEscape(cyberAtlasText('cyberatlas.cdnSignals', 'CDN signals'))}: ${cyberAtlasEscape((protections.cdn || []).join(', ') || cyberAtlasNoneLabel())}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.frontendHints', 'Frontend hints'))}</div>
                    <div class="signalatlas-metric-grid">
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.apiReferences', 'API references'))}</span><strong>${cyberAtlasEscape(String(frontend.api_reference_count || 0))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.backendHosts', 'Backend hosts'))}</span><strong>${cyberAtlasEscape(String((frontend.backend_hosts || []).length))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.privateBackends', 'Private backends'))}</span><strong>${cyberAtlasEscape(String((frontend.private_backend_hosts || []).length))}</strong></div>
                        <div class="signalatlas-metric-card"><span>${cyberAtlasEscape(cyberAtlasText('cyberatlas.sourceMaps', 'Source maps'))}</span><strong>${cyberAtlasEscape(String(frontend.source_map_count || 0))}</strong></div>
                    </div>
                    ${(frontend.backend_hosts || []).length ? `<div class="signalatlas-panel-copy">${cyberAtlasEscape((frontend.backend_hosts || []).slice(0, 8).join(', '))}</div>` : ''}
                </section>
                <section class="signalatlas-panel signalatlas-report-panel-wide">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.exposureProbes', 'Exposure probes'))}</div>
                    <div class="cyberatlas-evidence-list">
                        ${probes.length ? probes.map(probe => `
                            <div class="cyberatlas-evidence-card">
                                <div class="cyberatlas-evidence-title">${cyberAtlasEscape(probe.path || probe.url || '')}</div>
                                <div class="cyberatlas-evidence-meta">${cyberAtlasEscape(probe.exists ? cyberAtlasText('cyberatlas.reachable', 'reachable') : cyberAtlasText('cyberatlas.notReachable', 'not reachable'))} · HTTP ${cyberAtlasEscape(String(probe.status_code ?? 'n/a'))} · ${cyberAtlasEscape(probe.content_type || cyberAtlasText('cyberatlas.unknownType', 'unknown type'))}</div>
                            </div>
                        `).join('') : `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noExposureProbes', 'No exposure probe result is available.'))}</div>`}
                    </div>
                </section>
            </div>
        `;
    }

    function renderCyberAtlasApiSurface(audit) {
        const openapi = audit?.snapshot?.openapi || {};
        const endpoints = Array.isArray(openapi.endpoints) ? openapi.endpoints : [];
        const inventory = audit?.snapshot?.api_inventory || {};
        const discovered = Array.isArray(inventory.endpoints) ? inventory.endpoints : [];
        return `
            <section class="signalatlas-panel">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.apiSurface', 'API surface'))}</div>
                        <div class="signalatlas-panel-title">${cyberAtlasEscape(openapi.available ? (openapi.title || openapi.source_url || 'OpenAPI') : cyberAtlasText('cyberatlas.apiInventory', 'API inventory'))}</div>
                    </div>
                    <div class="signalatlas-summary-badges">
                        <span class="signalatlas-inline-chip">${cyberAtlasEscape(String(openapi.endpoint_count || endpoints.length))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.endpointsShort', 'endpoints'))}</span>
                        <span class="signalatlas-inline-chip">${cyberAtlasEscape(String(openapi.unauthenticated_count || 0))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.noAuthDeclared', 'without declared auth'))}</span>
                    </div>
                </div>
                ${openapi.available ? `
                    <div class="signalatlas-finding-list">
                        ${endpoints.slice(0, 60).map(endpoint => `
                            <div class="signalatlas-mini-finding-card">
                                <div class="signalatlas-mini-finding-title">${cyberAtlasEscape((endpoint.method || 'GET').toUpperCase())} ${cyberAtlasEscape(endpoint.path || '')}</div>
                                <div class="signalatlas-mini-finding-copy">${cyberAtlasEscape(endpoint.security_declared ? cyberAtlasText('cyberatlas.authDeclared', 'auth declared') : cyberAtlasText('cyberatlas.noAuthDeclared', 'without declared auth'))}</div>
                            </div>
                        `).join('')}
                    </div>
                ` : `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noOpenApi', 'No public OpenAPI document was parsed in this audit.'))}</div>`}
            </section>
            <section class="signalatlas-panel">
                <div class="signalatlas-section-top">
                    <div>
                        <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.apiInventory', 'API inventory'))}</div>
                        <div class="signalatlas-panel-title">${cyberAtlasEscape(String(inventory.endpoint_count || discovered.length))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.endpointsShort', 'endpoints'))}</div>
                    </div>
                    <div class="signalatlas-summary-badges">
                        <span class="signalatlas-inline-chip">${cyberAtlasEscape(String(inventory.auth_protected_count || 0))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.authProtected', 'auth protected'))}</span>
                        <span class="signalatlas-inline-chip">${cyberAtlasEscape(String(inventory.public_sensitive_count || 0))} ${cyberAtlasEscape(cyberAtlasText('cyberatlas.publicSensitive', 'public sensitive'))}</span>
                    </div>
                </div>
                <div class="signalatlas-finding-list">
                    ${discovered.length ? discovered.slice(0, 80).map(endpoint => `
                        <div class="signalatlas-mini-finding-card">
                            <div class="signalatlas-mini-finding-title">${cyberAtlasEscape(endpoint.path || endpoint.url || '')}</div>
                            <div class="signalatlas-mini-finding-copy">HTTP ${cyberAtlasEscape(String(endpoint.status_code ?? 'n/a'))} · ${cyberAtlasEscape(endpoint.response_type || endpoint.content_type || '')} · ${cyberAtlasEscape(endpoint.category || '')} · ${cyberAtlasEscape(endpoint.requires_auth ? cyberAtlasText('cyberatlas.authProtected', 'auth protected') : cyberAtlasText('cyberatlas.publicMode', 'public'))}</div>
                            ${(endpoint.risk_reasons || []).length ? `<div class="signalatlas-finding-meta">${(endpoint.risk_reasons || []).slice(0, 4).map(reason => `<span>${cyberAtlasEscape(reason)}</span>`).join('')}</div>` : ''}
                        </div>
                    `).join('') : `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.noApiInventory', 'No additional API inventory signal was found.'))}</div>`}
                </div>
            </section>
        `;
    }

    function renderCyberAtlasPlan(audit) {
        return `
            <div class="signalatlas-overview-stack">
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.actionPlan', 'Action plan'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasActionPlan(audit, 12)}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.standardsMap', 'Standards map'))}</div>
                    ${renderCyberAtlasStandards(audit)}
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.securityTickets', 'Security tickets'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasSecurityTickets(audit)}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.ownerVerificationPlan', 'Owner verification plan'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasOwnerVerification(audit)}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.riskPaths', 'Risk paths'))}</div>
                    <div class="signalatlas-finding-list">${renderCyberAtlasRiskPaths(audit)}</div>
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.attackSurfaceMatrix', 'Attack surface matrix'))}</div>
                    ${renderCyberAtlasSurfaceMatrix(audit)}
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.auditCoverage', 'Audit coverage'))}</div>
                    ${renderCyberAtlasCoverage(audit)}
                </section>
                <section class="signalatlas-panel">
                    <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.evidenceGraph', 'Evidence graph'))}</div>
                    ${renderCyberAtlasEvidenceGraph(audit)}
                </section>
            </div>
        `;
    }

    function renderCyberAtlasAi(audit) {
        const interpretations = Array.isArray(audit?.interpretations) ? audit.interpretations : [];
        const latest = interpretations[interpretations.length - 1] || null;
        return `
            <div class="signalatlas-overview-stack">
                <section class="signalatlas-panel">
                    <div class="signalatlas-section-top">
                        <div>
                            <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.aiInterpretation', 'AI interpretation'))}</div>
                            <div class="signalatlas-panel-title">${cyberAtlasEscape(latest ? cyberAtlasText('cyberatlas.latestAi', 'Latest defensive read') : cyberAtlasText('cyberatlas.noAiGeneratedYet', 'No AI interpretation yet'))}</div>
                        </div>
                        <div class="signalatlas-report-toolbar">
                            <button class="signalatlas-btn secondary" type="button" onclick="rerunCyberAtlasAi()">${cyberAtlasEscape(cyberAtlasText('cyberatlas.rerunAi', 'Re-run AI'))}</button>
                            <button class="signalatlas-btn secondary" type="button" onclick="compareCyberAtlasAi()">${cyberAtlasEscape(cyberAtlasText('cyberatlas.compareAi', 'Compare models'))}</button>
                        </div>
                    </div>
                    ${latest ? `
                        <article class="signalatlas-interpretation-card">
                            <div class="signalatlas-model-used-card">
                                <div class="signalatlas-model-used-meta">${cyberAtlasEscape(cyberAtlasText('cyberatlas.generatedWithModel', 'Generated with {model}', { model: latest.model || '' }))}</div>
                            </div>
                            <pre class="signalatlas-interpretation-body">${cyberAtlasEscape(latest.content || '')}</pre>
                        </article>
                    ` : `<div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.aiPending', 'Generate a remediation narrative when you want a dev-ready security plan.'))}</div>`}
                </section>
            </div>
        `;
    }

    function renderCyberAtlasExports(audit) {
        const exports = [
            ['markdown', cyberAtlasText('cyberatlas.exportMarkdown', 'Markdown')],
            ['json', cyberAtlasText('cyberatlas.exportJson', 'JSON')],
            ['prompt', cyberAtlasText('cyberatlas.exportPrompt', 'AI prompt')],
            ['remediation', cyberAtlasText('cyberatlas.exportRemediation', 'Remediation')],
            ['tickets', cyberAtlasText('cyberatlas.exportSecurityTickets', 'Security tickets')],
            ['standards', cyberAtlasText('cyberatlas.exportStandardsMap', 'Standards map')],
            ['evidence', cyberAtlasText('cyberatlas.exportEvidencePack', 'Evidence pack')],
            ['gate', cyberAtlasText('cyberatlas.exportSecurityGate', 'Security gate')],
            ['pdf', cyberAtlasText('cyberatlas.exportPdf', 'PDF')],
        ];
        return `
            <section class="signalatlas-panel">
                <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.tabExports', 'Exports'))}</div>
                <div class="perfatlas-export-grid">
                    ${exports.map(([formatName, label]) => `
                        <button class="perfatlas-export-btn" type="button" onclick="downloadCyberAtlasExport('${cyberAtlasEscape(audit.id)}', '${cyberAtlasEscape(formatName)}')">
                            <i data-lucide="download"></i>
                            <span>${cyberAtlasEscape(label)}</span>
                        </button>
                    `).join('')}
                </div>
                <button class="signalatlas-btn secondary" type="button" onclick="openCyberAtlasPromptInChat('${cyberAtlasEscape(audit.id)}')">${cyberAtlasEscape(cyberAtlasText('cyberatlas.openPromptInChat', 'Open prompt in chat'))}</button>
            </section>
        `;
    }

    function renderCyberAtlasTabContent(audit) {
        if (cyberAtlasActiveTab === 'plan') return renderCyberAtlasPlan(audit);
        if (cyberAtlasActiveTab === 'findings') return `<div class="signalatlas-finding-list">${renderCyberAtlasFindings(audit, 20)}</div>`;
        if (cyberAtlasActiveTab === 'evidence') return renderCyberAtlasEvidence(audit);
        if (cyberAtlasActiveTab === 'api') return renderCyberAtlasApiSurface(audit);
        if (cyberAtlasActiveTab === 'ai') return renderCyberAtlasAi(audit);
        if (cyberAtlasActiveTab === 'exports') return renderCyberAtlasExports(audit);
        return renderCyberAtlasOverview(audit);
    }

    function renderCyberAtlasProgressBanner(progressState, audit) {
        const displayProgress = typeof auditDisplayProgress === 'function'
            ? auditDisplayProgress('cyberatlas', progressState, audit, cyberAtlasLaunchPending)
            : cyberAtlasJobProgress(progressState);
        if (typeof renderAuditProgressBanner === 'function') {
            return renderAuditProgressBanner({
                namespace: 'cyberatlas',
                progressState,
                launchPending: cyberAtlasLaunchPending,
                displayProgress,
                targetLabel: cyberAtlasDraft.target,
                statusLabel: cyberAtlasStatusLabel,
                supportCopy: cyberAtlasText('cyberatlas.backgroundResumeHint', 'This audit keeps running if you leave the view.'),
                launchingLabel: cyberAtlasText('cyberatlas.launching', 'Launching'),
                launchingMessage: cyberAtlasText('cyberatlas.launchingAudit', 'Starting the security runtime...'),
                etaLabel: '',
            });
        }
        if (!progressState && !cyberAtlasLaunchPending) return '';
        return `
            <div class="signalatlas-progress-panel">
                <div class="signalatlas-progress-copy">${cyberAtlasEscape(progressState?.message || cyberAtlasText('cyberatlas.launchingAudit', 'Starting the security runtime...'))}</div>
                <div class="signalatlas-progress-bar"><div class="signalatlas-progress-fill" style="width:${cyberAtlasEscape(String(displayProgress || 4))}%"></div></div>
            </div>
        `;
    }

    function renderCyberAtlasWorkspace() {
        syncCyberAtlasDraftFromDom();
        const host = document.getElementById('cyberatlas-view-content');
        if (!host) return;
        const audit = cyberAtlasCurrentAudit;
        const progressState = cyberAtlasAuditProgressState(audit) || cyberAtlasAnyProgressState();
        const progressStatus = String(progressState?.status || '').toLowerCase();
        const canCancelAudit = !!progressState && ['queued', 'running', 'cancelling'].includes(progressStatus);
        const targetValidation = cyberAtlasValidateTarget(cyberAtlasDraft.target);
        const selectedProfile = cyberAtlasDraft.profile || 'elevated';
        const tabs = [
            ['overview', cyberAtlasText('cyberatlas.tabOverview', 'Overview')],
            ['plan', cyberAtlasText('cyberatlas.tabPlan', 'Plan')],
            ['findings', cyberAtlasText('cyberatlas.tabFindings', 'Findings')],
            ['evidence', cyberAtlasText('cyberatlas.tabEvidence', 'Evidence')],
            ['api', cyberAtlasText('cyberatlas.tabApi', 'API surface')],
            ['ai', cyberAtlasText('cyberatlas.tabAi', 'AI')],
            ['exports', cyberAtlasText('cyberatlas.tabExports', 'Exports')],
        ];
        if (!tabs.some(([id]) => id === cyberAtlasActiveTab)) cyberAtlasActiveTab = 'overview';

        host.innerHTML = `
            <div class="signalatlas-shell cyberatlas-shell">
                <section class="signalatlas-control-surface cyberatlas-control-surface">
                    <div class="signalatlas-input-row">
                        <input id="cyberatlas-target-input" class="signalatlas-target-input${targetValidation.present && !targetValidation.valid ? ' is-invalid' : ''}" type="text" value="${cyberAtlasEscape(cyberAtlasDraft.target)}" placeholder="${cyberAtlasEscape(cyberAtlasText('cyberatlas.targetPlaceholder', 'Example: https://example.com/'))}" oninput="cyberAtlasTargetInputChanged(event)" onblur="cyberAtlasControlsChanged()" aria-invalid="${targetValidation.present && !targetValidation.valid ? 'true' : 'false'}" inputmode="url" autocapitalize="off" spellcheck="false">
                        ${canCancelAudit ? `
                            <button
                                id="cyberatlas-launch-btn"
                                class="signalatlas-btn launch signalatlas-stop-btn"
                                type="button"
                                data-action="cancel"
                                onclick="cancelCyberAtlasAudit('${cyberAtlasEscape(progressState?.auditId || cyberAtlasCurrentAuditId || '')}')"
                                aria-label="${cyberAtlasEscape(progressStatus === 'cancelling' ? cyberAtlasText('cyberatlas.cancelling', 'Cancelling...') : cyberAtlasText('cyberatlas.cancelAudit', 'Cancel audit'))}"
                                title="${cyberAtlasEscape(progressStatus === 'cancelling' ? cyberAtlasText('cyberatlas.cancelling', 'Cancelling...') : cyberAtlasText('cyberatlas.cancelAudit', 'Cancel audit'))}"
                                ${progressStatus === 'cancelling' ? 'disabled' : ''}
                            >
                                <i data-lucide="square"></i>
                            </button>
                        ` : `
                            <button id="cyberatlas-launch-btn" class="signalatlas-btn" type="button" data-action="launch" onclick="launchCyberAtlasAudit()" ${cyberAtlasLaunchPending || !targetValidation.valid ? 'disabled' : ''}>${cyberAtlasEscape(cyberAtlasText('cyberatlas.runAudit', 'Launch audit'))}</button>
                        `}
                        <div id="cyberatlas-target-feedback" class="signalatlas-target-feedback${targetValidation.present && !targetValidation.valid ? ' is-visible' : ''}">${cyberAtlasEscape(targetValidation.present && !targetValidation.valid ? targetValidation.message : '')}</div>
                    </div>
                    <div class="signalatlas-primary-grid">
                        <div class="signalatlas-field">
                            <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.profileLabel', 'Audit level'))}</label>
                            <select id="cyberatlas-profile-select" class="signalatlas-target-input" onchange="cyberAtlasProfileChanged(event)">${cyberAtlasProfileOptionsHtml(selectedProfile)}</select>
                        </div>
                        <div class="signalatlas-field">
                            <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.modelLabel', 'Model'))}</label>
                            <select id="cyberatlas-model-select" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasModelOptionsHtml(cyberAtlasDraft.model || cyberAtlasCurrentChatModel())}</select>
                        </div>
                        <div class="signalatlas-field signalatlas-field-action">
                            <button class="signalatlas-advanced-toggle${cyberAtlasAdvancedVisible ? ' is-open' : ''}" type="button" onclick="toggleCyberAtlasAdvancedSettings()">
                                <span>${cyberAtlasEscape(cyberAtlasAdvancedVisible ? cyberAtlasText('cyberatlas.advancedSettingsClose', 'Hide customization') : cyberAtlasText('cyberatlas.advancedSettingsOpen', 'Customize'))}</span>
                                <i data-lucide="${cyberAtlasAdvancedVisible ? 'chevron-up' : 'chevron-down'}"></i>
                            </button>
                        </div>
                    </div>
                    ${cyberAtlasAdvancedVisible ? `
                        <div class="signalatlas-advanced-panel">
                            <div class="signalatlas-controls-grid">
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.auditMode', 'Audit mode'))}</label>
                                    <select id="cyberatlas-mode-select" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">
                                        <option value="public" ${cyberAtlasDraft.mode === 'public' ? 'selected' : ''}>${cyberAtlasEscape(cyberAtlasText('cyberatlas.publicMode', 'Public audit'))}</option>
                                        <option value="verified_owner" ${cyberAtlasDraft.mode === 'verified_owner' ? 'selected' : ''}>${cyberAtlasEscape(cyberAtlasText('cyberatlas.ownerMode', 'Verified owner'))}</option>
                                    </select>
                                </div>
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.maxPages', 'Page budget'))}</label>
                                    <select id="cyberatlas-max-pages" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasBudgetOptionsHtml(CYBERATLAS_PAGE_BUDGET_STEPS, cyberAtlasDraft.max_pages)}</select>
                                </div>
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.maxEndpoints', 'Endpoint budget'))}</label>
                                    <select id="cyberatlas-max-endpoints" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasBudgetOptionsHtml(CYBERATLAS_ENDPOINT_BUDGET_STEPS, cyberAtlasDraft.max_endpoints)}</select>
                                </div>
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.presetLabel', 'Preset'))}</label>
                                    <select id="cyberatlas-preset-select" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasPresetOptionsHtml(cyberAtlasDraft.preset)}</select>
                                </div>
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.levelLabel', 'AI level'))}</label>
                                    <select id="cyberatlas-level-select" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasAiLevelOptionsHtml(cyberAtlasDraft.level)}</select>
                                </div>
                                <div class="signalatlas-field">
                                    <label class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.compareModelLabel', 'Comparison model'))}</label>
                                    <select id="cyberatlas-compare-model-select" class="signalatlas-target-input" onchange="cyberAtlasControlsChanged()">${cyberAtlasModelOptionsHtml(cyberAtlasDraft.compare_model || fallbackCyberAtlasCompareModel())}</select>
                                </div>
                                <label class="signalatlas-field signalatlas-toggle-field">
                                    <span class="signalatlas-field-head">${cyberAtlasEscape(cyberAtlasText('cyberatlas.activeChecks', 'Expanded safe probes'))}</span>
                                    <input id="cyberatlas-active-checks" type="checkbox" ${cyberAtlasDraft.active_checks ? 'checked' : ''} onchange="cyberAtlasControlsChanged()" ${cyberAtlasDraft.mode === 'verified_owner' ? '' : 'disabled'}>
                                </label>
                            </div>
                        </div>
                    ` : ''}
                    ${renderCyberAtlasProgressBanner(progressState, audit)}
                </section>

                ${renderCyberAtlasProviderStrip()}

                <section class="signalatlas-report-panel signalatlas-report-panel-wide">
                    <div class="signalatlas-section-top signalatlas-report-heading">
                        <div class="signalatlas-report-heading-copy">
                            <div>
                                <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.workspace', 'Report'))}</div>
                                <div class="signalatlas-panel-title">${cyberAtlasEscape(audit?.title || cyberAtlasText('cyberatlas.selectAudit', 'Select or launch an audit'))}</div>
                                ${audit ? `<div class="signalatlas-panel-copy signalatlas-report-heading-copytext">${cyberAtlasEscape(cyberAtlasText('cyberatlas.reportHeaderCopy', 'Start with posture, then inspect evidence, API surface, and remediation exports.'))}</div>` : ''}
                            </div>
                        </div>
                        ${audit ? `
                            <div class="signalatlas-report-toolbar">
                                <button class="signalatlas-btn secondary" type="button" onclick="refreshCyberAtlasWorkspace()">${cyberAtlasEscape(cyberAtlasText('common.refresh', 'Refresh'))}</button>
                                <button class="signalatlas-report-download" type="button" onclick="downloadCyberAtlasExport('${cyberAtlasEscape(audit.id)}', 'markdown')">
                                    <span class="signalatlas-report-download-icon"><i data-lucide="download-cloud"></i></span>
                                    <span class="signalatlas-report-download-copy">
                                        <strong>${cyberAtlasEscape(cyberAtlasText('cyberatlas.exportForAi', 'Export for an AI'))}</strong>
                                        <small>${cyberAtlasEscape(cyberAtlasText('cyberatlas.exportForAiMeta', 'Markdown ready to hand off'))}</small>
                                    </span>
                                </button>
                            </div>
                        ` : ''}
                    </div>
                    <div class="signalatlas-drawer-panel">
                        <div class="signalatlas-section-top">
                            <div>
                                <div class="signalatlas-panel-kicker">${cyberAtlasEscape(cyberAtlasText('cyberatlas.auditHistory', 'Audit history'))}</div>
                                <div class="signalatlas-panel-title">${cyberAtlasEscape(cyberAtlasText('cyberatlas.recentRuns', 'Recent runs'))}</div>
                            </div>
                        </div>
                        <div class="signalatlas-history-list">${renderCyberAtlasHistory()}</div>
                    </div>
                    ${audit ? `
                        <div class="signalatlas-tabs">
                            ${tabs.map(([id, label]) => `<button class="signalatlas-tab${cyberAtlasActiveTab === id ? ' active' : ''}" type="button" onclick="setCyberAtlasTab('${id}')">${cyberAtlasEscape(label)}</button>`).join('')}
                        </div>
                        <div class="signalatlas-tab-panel">
                            ${renderCyberAtlasTabContent(audit)}
                        </div>
                    ` : `
                        <div class="signalatlas-empty-panel">${cyberAtlasEscape(cyberAtlasText('cyberatlas.emptyWorkspace', 'Choose a domain or an existing audit to begin.'))}</div>
                    `}
                </section>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [host] });
        if (typeof hydrateSignalAtlasMotion === 'function') hydrateSignalAtlasMotion(host);
        renderCyberAtlasTargetValidationUi();
    }

    async function openCyberAtlasWorkspace(auditId = null) {
        if (auditId) cyberAtlasCurrentAuditId = auditId;
        if (typeof hideModulesWorkspaces === 'function') hideModulesWorkspaces();
        if (typeof applyModulesShellMode === 'function') {
            applyModulesShellMode('sidebar-modules-btn', 'cyberatlas-mode');
        } else {
            document.body.classList.add('cyberatlas-mode');
        }
        const view = getCyberAtlasView();
        if (view) view.style.display = 'flex';
        await loadCyberAtlasBootstrap();
        renderCyberAtlasWorkspace();
        startCyberAtlasRefresh();
    }

    async function launchCyberAtlasAudit() {
        syncCyberAtlasDraftFromDom();
        const validation = cyberAtlasValidateTarget(cyberAtlasDraft.target);
        if (!validation.present) {
            Toast?.warning?.(cyberAtlasText('cyberatlas.targetRequired', 'Add a real domain or full public URL first.'));
            renderCyberAtlasTargetValidationUi();
            return;
        }
        if (!validation.valid) {
            Toast?.warning?.(cyberAtlasText('cyberatlas.targetInvalid', 'Use a real public domain or URL.'));
            renderCyberAtlasTargetValidationUi();
            return;
        }
        cyberAtlasLaunchPending = true;
        renderCyberAtlasWorkspace();
        const payload = {
            target: String(cyberAtlasDraft.target || '').trim(),
            mode: cyberAtlasDraft.mode || 'public',
            options: {
                max_pages: cyberAtlasNormalizeBudget(cyberAtlasDraft.max_pages, CYBERATLAS_DEFAULT_PAGE_BUDGET, CYBERATLAS_MAX_PAGE_BUDGET),
                max_endpoints: cyberAtlasNormalizeBudget(cyberAtlasDraft.max_endpoints, CYBERATLAS_DEFAULT_ENDPOINT_BUDGET, CYBERATLAS_MAX_ENDPOINT_BUDGET),
                active_checks: cyberAtlasDraft.mode === 'verified_owner' && !!cyberAtlasDraft.active_checks,
            },
            ai: {
                model: cyberAtlasDraft.model || cyberAtlasCurrentChatModel(),
                preset: cyberAtlasDraft.preset || 'balanced',
                level: cyberAtlasDraft.level || 'full_expert_analysis',
            },
        };
        try {
            const result = await apiCyberAtlas.createAudit(payload);
            if (!result.ok) {
                Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.auditCreateFailed', 'Unable to launch the audit.'));
                return;
            }
            cyberAtlasCurrentAuditId = result.data?.audit?.id || cyberAtlasCurrentAuditId;
            cyberAtlasCurrentAudit = result.data?.audit || cyberAtlasCurrentAudit;
            if (result.data?.job) seedCyberAtlasRuntimeJob(result.data.job, cyberAtlasCurrentAuditId);
            await loadCyberAtlasBootstrap();
            if (cyberAtlasCurrentAuditId) await loadCyberAtlasAudit(cyberAtlasCurrentAuditId, { silent: true });
            renderCyberAtlasWorkspace();
            startCyberAtlasRefresh();
            Toast?.success?.(cyberAtlasText('cyberatlas.auditStarted', 'CyberAtlas audit started.'));
        } finally {
            cyberAtlasLaunchPending = false;
        }
        if (isCyberAtlasVisible()) renderCyberAtlasWorkspace();
    }

    async function deleteCyberAtlasAudit(auditId = '', event = null) {
        event?.preventDefault?.();
        event?.stopPropagation?.();
        const targetAuditId = String(auditId || '').trim();
        if (!targetAuditId) return;
        if (cyberAtlasAuditProgressState(targetAuditId)) {
            Toast?.warning?.(cyberAtlasText('cyberatlas.deleteAuditBlocked', 'Cancel this audit before deleting it.'));
            return;
        }
        const audit = cyberAtlasAudits.find(item => String(item?.id || '') === targetAuditId);
        const title = audit?.title || audit?.host || cyberAtlasText('cyberatlas.auditItem', 'this audit');
        if (!window.confirm(cyberAtlasText('cyberatlas.deleteAuditConfirm', 'Delete {title} permanently?', { title }))) return;
        const result = await apiCyberAtlas.deleteAudit(targetAuditId);
        if (!result.ok) {
            Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.deleteAuditFailed', 'Unable to delete this audit.'));
            return;
        }
        cyberAtlasAudits = cyberAtlasAudits.filter(item => String(item?.id || '') !== targetAuditId);
        if (String(cyberAtlasCurrentAuditId || '') === targetAuditId) {
            cyberAtlasCurrentAuditId = cyberAtlasAudits[0]?.id || null;
            cyberAtlasCurrentAudit = null;
        }
        await loadCyberAtlasBootstrap();
        renderCyberAtlasWorkspace();
        Toast?.success?.(cyberAtlasText('cyberatlas.deleteAuditSuccess', 'Audit deleted.'));
    }

    async function cancelCyberAtlasAudit(auditId = '') {
        const targetAuditId = String(auditId || cyberAtlasCurrentAuditId || '').trim();
        if (!targetAuditId || typeof apiRuntime === 'undefined') return;
        const progressState = cyberAtlasAuditProgressState(targetAuditId);
        const jobId = String(progressState?.job?.id || `cyberatlas-audit-${targetAuditId}`).trim();
        if (!jobId) return;
        const result = await apiRuntime.cancelJob(jobId, {});
        if (!result.ok || !result.data?.job) {
            Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.cancelAuditFailed', 'Unable to cancel this audit.'));
            return;
        }
        seedCyberAtlasRuntimeJob(result.data.job, targetAuditId);
        if (cyberAtlasCurrentAudit && String(cyberAtlasCurrentAudit.id || '') === targetAuditId) {
            cyberAtlasCurrentAudit.status = String(result.data.job.status || 'cancelling').toLowerCase();
        }
        Toast?.success?.(cyberAtlasText('cyberatlas.cancelAuditRequested', 'Cancellation requested.'));
        await refreshCyberAtlasWorkspace();
    }

    async function rerunCyberAtlasAi() {
        if (!cyberAtlasCurrentAuditId) return;
        syncCyberAtlasDraftFromDom();
        const result = await apiCyberAtlas.rerunAi(cyberAtlasCurrentAuditId, {
            model: cyberAtlasDraft.model || cyberAtlasCurrentChatModel(),
            preset: cyberAtlasDraft.preset || 'balanced',
            level: cyberAtlasDraft.level || 'full_expert_analysis',
        });
        if (!result.ok) {
            Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.rerunFailed', 'Unable to re-run the AI interpretation.'));
            return;
        }
        if (result.data?.job) seedCyberAtlasRuntimeJob(result.data.job, cyberAtlasCurrentAuditId);
        renderCyberAtlasWorkspace();
        startCyberAtlasRefresh();
        Toast?.success?.(cyberAtlasText('cyberatlas.rerunStarted', 'AI interpretation started.'));
    }

    async function compareCyberAtlasAi() {
        if (!cyberAtlasCurrentAuditId) return;
        syncCyberAtlasDraftFromDom();
        const result = await apiCyberAtlas.compareAi(cyberAtlasCurrentAuditId, {
            left_model: cyberAtlasDraft.model || cyberAtlasCurrentChatModel(),
            right_model: cyberAtlasDraft.compare_model || fallbackCyberAtlasCompareModel(),
            preset: cyberAtlasDraft.preset || 'expert',
            level: cyberAtlasDraft.level || 'full_expert_analysis',
        });
        if (!result.ok) {
            Toast?.error?.(result.data?.error || cyberAtlasText('cyberatlas.compareFailed', 'Unable to compare AI outputs.'));
            return;
        }
        if (result.data?.job) seedCyberAtlasRuntimeJob(result.data.job, cyberAtlasCurrentAuditId);
        renderCyberAtlasWorkspace();
        startCyberAtlasRefresh();
        Toast?.success?.(cyberAtlasText('cyberatlas.compareStarted', 'CyberAtlas comparison started.'));
    }

    function downloadCyberAtlasExport(auditId, formatName) {
        if (!auditId) return;
        window.location.href = `/api/cyberatlas/audits/${encodeURIComponent(auditId)}/export/${encodeURIComponent(formatName)}`;
    }

    async function openCyberAtlasPromptInChat(auditId) {
        if (!auditId) return;
        const result = await apiCyberAtlas.fetchExportText(auditId, 'prompt');
        if (!result.ok) {
            Toast?.error?.(cyberAtlasText('cyberatlas.promptLoadFailed', 'Unable to load the AI-fix prompt.'));
            return;
        }
        if (typeof createNewChat === 'function') await createNewChat();
        if (typeof showChat === 'function') showChat();
        const input = document.getElementById('chat-prompt');
        if (input) {
            input.value = result.data || '';
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.focus();
        }
    }

    async function refreshCyberAtlasWorkspace() {
        await loadCyberAtlasBootstrap();
        if (cyberAtlasCurrentAuditId) await loadCyberAtlasAudit(cyberAtlasCurrentAuditId, { silent: true });
        renderCyberAtlasWorkspace();
    }

    function startCyberAtlasRefresh() {
        stopCyberAtlasRefresh();
        cyberAtlasRefreshTimer = setInterval(async () => {
            if (!isCyberAtlasVisible()) {
                stopCyberAtlasRefresh();
                return;
            }
            if (cyberAtlasRefreshInFlight) return;
            cyberAtlasRefreshInFlight = true;
            try {
                await refreshCyberAtlasWorkspace();
            } finally {
                cyberAtlasRefreshInFlight = false;
            }
            if (!cyberAtlasAnyProgressState()) stopCyberAtlasRefresh();
        }, 3500);
    }

    function stopCyberAtlasRefresh() {
        if (cyberAtlasRefreshTimer) {
            clearInterval(cyberAtlasRefreshTimer);
            cyberAtlasRefreshTimer = null;
        }
        cyberAtlasRefreshInFlight = false;
    }

    function handleCyberAtlasRuntimeJobsUpdated() {
        if (!isCyberAtlasVisible()) return;
        renderCyberAtlasWorkspace();
        startCyberAtlasRefresh();
    }

    function setCyberAtlasTab(tabId) {
        cyberAtlasActiveTab = String(tabId || 'overview');
        renderCyberAtlasWorkspace();
    }

    function toggleCyberAtlasAdvancedSettings() {
        cyberAtlasAdvancedVisible = !cyberAtlasAdvancedVisible;
        renderCyberAtlasWorkspace();
    }

    window.openCyberAtlasWorkspace = openCyberAtlasWorkspace;
    window.renderCyberAtlasWorkspace = renderCyberAtlasWorkspace;
    window.refreshCyberAtlasWorkspace = refreshCyberAtlasWorkspace;
    window.startCyberAtlasRefresh = startCyberAtlasRefresh;
    window.stopCyberAtlasRefresh = stopCyberAtlasRefresh;
    window.handleCyberAtlasRuntimeJobsUpdated = handleCyberAtlasRuntimeJobsUpdated;
    window.setCyberAtlasTab = setCyberAtlasTab;
    window.toggleCyberAtlasAdvancedSettings = toggleCyberAtlasAdvancedSettings;
    window.cyberAtlasControlsChanged = cyberAtlasControlsChanged;
    window.cyberAtlasTargetInputChanged = cyberAtlasTargetInputChanged;
    window.cyberAtlasProfileChanged = cyberAtlasProfileChanged;
    window.launchCyberAtlasAudit = launchCyberAtlasAudit;
    window.deleteCyberAtlasAudit = deleteCyberAtlasAudit;
    window.cancelCyberAtlasAudit = cancelCyberAtlasAudit;
    window.rerunCyberAtlasAi = rerunCyberAtlasAi;
    window.compareCyberAtlasAi = compareCyberAtlasAi;
    window.downloadCyberAtlasExport = downloadCyberAtlasExport;
    window.openCyberAtlasPromptInChat = openCyberAtlasPromptInChat;
})();
