// ===== SETTINGS DIAGNOSTICS AND IMPORTS =====
// Doctor report, model source import flow, harness audit, and image-surface availability helpers.

async function loadDoctorReport() {
    const output = document.getElementById('doctor-report-output');
    if (!output) return;

    output.innerHTML = `<div class="settings-info">${t('doctor.loading', 'Diagnostic en cours...')}</div>`;
    const result = await apiSettings.getDoctorReport();
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('doctor.error', 'Erreur doctor : {error}', { error: result.data?.error || result.error || 'inconnue' })}</div>`;
        return;
    }

    lastDoctorReport = result.data;
    renderDoctorReport(lastDoctorReport);
}

function renderDoctorReport(data) {
    const output = document.getElementById('doctor-report-output');
    if (!output || !data) return;

    const checksHtml = (data.checks || []).map(check => {
        const status = _normalizeDoctorStatus(check.status);
        const detail = _doctorCheckDetail(check, 'onboarding.summaryUnavailable', 'Résumé indisponible.');
        return `
            <div class="settings-label-desc">
                <strong>${escapeHtml(_doctorCheckLabel(check))}</strong>:
                <span class="status-${status === 'ok' ? 'ok' : (status === 'warning' ? 'warn' : 'error')}">${escapeHtml(detail)}</span>
            </div>
        `;
    }).join('');

    output.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:10px;">
            <div class="settings-row">
                <div>
                    <div class="settings-label">${t('doctor.title', 'Doctor {status}', { status: String(data.status || '').toUpperCase() })}</div>
                    <div class="settings-label-desc">${escapeHtml(_doctorSummaryText(data))}</div>
                </div>
                <div class="status-${data.status === 'ok' ? 'ok' : (data.status === 'warning' ? 'warn' : 'error')}" style="font-weight:700;">${data.ready ? t('doctor.ready', 'READY') : t('doctor.action', 'ACTION')}</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">${checksHtml}</div>
        </div>
    `;
}

async function resolveModelImportSource() {
    const input = document.getElementById('model-source-input');
    const targetSelect = document.getElementById('model-source-family');
    const output = document.getElementById('model-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) {
        return;
    }

    output.innerHTML = `<div class="settings-info">${t('settings.models.sourceAnalyzing', 'Analyse de la source...')}</div>`;
    const targetFamily = targetSelect?.value || 'generic';
    const resolved = await apiSettings.resolveModelSource(source, targetFamily);
    if (!resolved.ok || !resolved.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('settings.models.sourceError', 'Erreur : {error}', { error: resolved.data?.error || resolved.error || 'source invalide' })}</div>`;
        return;
    }

    const info = resolved.data.resolved;
    const targetLabel = getModelImportTargetLabel(targetFamily);
    const recommended = Array.isArray(info.recommended_resources) ? info.recommended_resources : [];
    const resourceUsageLabel = (usage) => {
        if (usage === 'positive') return t('settings.models.usagePositive', 'prompt positif');
        if (usage === 'negative') return t('settings.models.usageNegative', 'prompt négatif');
        return usage || '';
    };
    const recommendedHtml = recommended.length ? `
        <div class="settings-info" style="margin-top:10px;">
            <div class="settings-label">${escapeHtml(t('settings.models.recommendedResourcesTitle', 'Ressources recommandées détectées'))}</div>
            ${recommended.map(res => `
                <div class="settings-label-desc">
                    ${escapeHtml(res.type || 'Resource')} · ${escapeHtml(res.label || res.name || '')}
                    ${res.usage ? ` · ${escapeHtml(resourceUsageLabel(res.usage))}` : ''}
                </div>
            `).join('')}
            <label class="settings-label-desc" style="display:flex; gap:8px; align-items:center; margin-top:8px;">
                <input type="checkbox" id="model-source-include-recommended" checked>
                <span>${escapeHtml(t('settings.models.installRecommendedResources', 'Installer aussi ces ressources si elles sont compatibles'))}</span>
            </label>
        </div>
    ` : '';
    const quantHtml = renderModelImportQuantPolicy(info);
    output.innerHTML = `
        <div class="settings-label"><strong>${escapeHtml(info.display_name || source)}</strong></div>
        <div class="settings-label-desc">${escapeHtml(info.provider || '')} · ${escapeHtml(info.model_type || info.source_type || '')} · ${escapeHtml(info.base_model || '')} · ${escapeHtml(t('settings.models.targetLabel', 'cible {target}', { target: targetLabel }))}</div>
        ${info.file_name ? `<div class="settings-label-desc">${escapeHtml(info.file_name)} · ${escapeHtml(info.size_label || '')}</div>` : ''}
        ${quantHtml}
        ${info.trained_words?.length ? `<div class="settings-label-desc">${escapeHtml(t('settings.models.triggerWords', 'Mots trigger : {words}', { words: info.trained_words.join(', ') }))}</div>` : ''}
        <div class="settings-label-desc">${escapeHtml(info.requires_auth ? t('settings.models.authRequired', 'Provider clé détectée ou recommandée.') : t('settings.models.authPublic', 'Téléchargement possible sans auth pour les ressources publiques.'))}</div>
        ${info.warning ? `<div class="settings-label-desc status-warn">${escapeHtml(info.warning)}</div>` : ''}
        ${recommendedHtml}
        <div style="margin-top:10px;">
            <button class="settings-action-btn" onclick="startResolvedModelImport()">${t('settings.models.importLocalButton', 'Importer localement')}</button>
        </div>
    `;
}

let currentModelImportJobId = null;

function renderModelImportQuantPolicy(info = {}) {
    const policy = info.quant_policy || {};
    const sourcePrecision = String(policy.source_precision || info.source_precision || '').trim();
    const runtimeQuant = String(policy.runtime_quant || info.runtime_quant || '').trim();
    if (!sourcePrecision && !runtimeQuant) return '';

    const source = (sourcePrecision || 'checkpoint').toUpperCase();
    const runtime = (runtimeQuant && runtimeQuant !== 'none') ? runtimeQuant.toUpperCase() : t('settings.models.quantRuntimeNative', 'natif');
    const vram = Number(policy.vram_gb || 0);
    const key = runtimeQuant && runtimeQuant !== 'none'
        ? 'settings.models.quantPolicyRuntime'
        : 'settings.models.quantPolicyNative';
    const fallback = runtimeQuant && runtimeQuant !== 'none'
        ? 'Profil local : source {source}, exécution {runtime} au chargement.'
        : 'Profil local : source {source}, exécution native au chargement.';
    const label = t(key, fallback, {
        source,
        runtime,
        vram: vram ? vram.toFixed(1) : '?',
    });
    return `<div class="settings-label-desc status-ok">${escapeHtml(label)}</div>`;
}

async function startResolvedModelImport() {
    const input = document.getElementById('model-source-input');
    const targetSelect = document.getElementById('model-source-family');
    const output = document.getElementById('model-source-output');
    const source = input?.value?.trim() || '';
    if (!source || !output) return;

    const includeRecommended = document.getElementById('model-source-include-recommended')?.checked !== false;
    const result = await apiSettings.startModelImport(source, targetSelect?.value || 'image', includeRecommended);
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('settings.models.sourceError', 'Erreur : {error}', { error: result.data?.error || result.error || 'import impossible' })}</div>`;
        return;
    }

    currentModelImportJobId = result.data.job?.job_id || null;
    output.innerHTML = `<div class="settings-info">${t('settings.models.importStarted', 'Import lancé...')}</div>`;
    if (currentModelImportJobId) {
        pollModelImportStatus(currentModelImportJobId);
    }
}

async function pollModelImportStatus(jobId) {
    const output = document.getElementById('model-source-output');
    if (!output || !jobId) return;

    const poll = async () => {
        const result = await apiSettings.getModelImportStatus(jobId);
        const job = result.data?.job;
        if (!result.ok || !job) {
            output.innerHTML = `<div class="settings-info">${t('settings.models.importMissing', 'Import introuvable')}</div>`;
            return;
        }

        const downloadedMB = Math.round((job.downloaded_bytes || 0) / (1024 * 1024));
        const totalMB = Math.round((job.total_bytes || 0) / (1024 * 1024));
        const sizeChunk = totalMB ? ` · ${downloadedMB} MB / ${totalMB} MB` : '';
        const quantHtml = renderModelImportQuantPolicy(job.resolved || {});
        output.innerHTML = `
            <div class="settings-label"><strong>${job.resolved?.display_name || t('settings.models.importModelTitle', 'Import modèle')}</strong></div>
            <div class="settings-label-desc">${job.message || t('settings.models.importInProgress', 'Import en cours')}</div>
            <div class="settings-label-desc">${t('settings.models.importProgress', 'Progression : {progress}%{size}', { progress: job.progress || 0, size: sizeChunk })}</div>
            ${quantHtml}
            ${job.target_path ? `<div class="settings-label-desc">${t('settings.models.destination', 'Destination : {path}', { path: job.target_path })}</div>` : ''}
            ${job.error ? `<div class="settings-label-desc status-error">${job.error}</div>` : ''}
        `;

        if (job.status === 'completed') {
            Toast.success(t('settings.models.importedTitle', 'Modèle importé'), t('settings.models.importedBody', 'Import provider terminé'), 2600);
            if (typeof loadFeatureFlags === 'function') {
                loadFeatureFlags().then(() => {
                    if (typeof renderModelPickerList === 'function') {
                        renderModelPickerList('home');
                        renderModelPickerList('chat');
                    }
                }).catch(() => {});
            }
            if (typeof checkModelsStatus === 'function') checkModelsStatus();
            return;
        }
        if (job.status === 'error') {
            Toast.error(t('settings.models.importErrorTitle', 'Erreur import'), job.error || t('settings.models.importErrorBody', 'Échec import provider'));
            return;
        }
        setTimeout(poll, 1500);
    };

    await poll();
}

async function runHarnessAudit() {
    const output = document.getElementById('harness-audit-output');
    if (!output) return;

    output.innerHTML = `<div class="settings-info">${t('audit.loading', 'Audit en cours...')}</div>`;

    const result = await apiSettings.getHarnessAudit();
    if (!result.ok || !result.data?.success) {
        output.innerHTML = `<div class="settings-info">${t('audit.error', 'Erreur audit : {error}', { error: result.data?.error || result.error || 'inconnue' })}</div>`;
        return;
    }

    lastHarnessAudit = result.data;
    renderHarnessAudit(lastHarnessAudit);
}

function renderHarnessAudit(audit) {
    const output = document.getElementById('harness-audit-output');
    if (!output || !audit) return;

    const sectionLabels = {
        install: 'Install',
        secrets: 'Secrets',
        ux: 'UX',
        release: 'Release'
    };
    const scoreClass = audit.score >= 80 ? 'status-ok' : 'status-warn';
    const sections = Object.entries(audit.sections || {}).map(([key, value]) => (
        `<div class="settings-label-desc"><strong>${sectionLabels[key] || key}</strong>: ${value}/100</div>`
    )).join('');
    const actions = (audit.top_actions || []).length
        ? `<ul style="margin: 8px 0 0 18px;">${audit.top_actions.map(action => `<li>${action}</li>`).join('')}</ul>`
        : `<div class="settings-label-desc">${t('audit.noBlocking', 'Aucune priorité bloquante détectée.')}</div>`;
    const highlights = (audit.checks || [])
        .filter(check => check.status !== 'pass')
        .slice(0, 3)
        .map(check => `<li><strong>${check.label}</strong>: ${check.detail}</li>`)
        .join('');

    output.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 10px;">
            <div class="settings-row">
                <div>
                    <div class="settings-label">Score ${audit.score}/100 (${audit.grade})</div>
                    <div class="settings-label-desc">${audit.summary}</div>
                </div>
                <div class="${scoreClass}" style="font-weight: 700;">${audit.grade}</div>
            </div>
            <div>${sections}</div>
            <div>
                <div class="settings-label">${t('audit.priorities', 'Priorités')}</div>
                ${actions}
            </div>
            ${highlights ? `
                <div>
                    <div class="settings-label">${t('audit.watch', 'Points à surveiller')}</div>
                    <ul style="margin: 8px 0 0 18px;">${highlights}</ul>
                </div>
            ` : ''}
        </div>
    `;
}

function isAdultSurfaceEnabled() {
    return getAdultFeatureState().runtimeAvailable;
}

function isAdultImageSurfaceModel(model) {
    if (!model) return false;
    const name = (model.name || '').toLowerCase();
    const desc = (model.desc || '').toLowerCase();
    return model.adult === true
        || name.includes('lustify')
        || name.includes('juggernaut')
        || name.includes('flux kontext nsfw')
        || desc.includes('nsfw');
}
