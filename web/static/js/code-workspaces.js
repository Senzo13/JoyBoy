// ===== CODEATLAS / AGENTGUIDE WORKSPACES =====

let codeAtlasAudits = [];
let codeAtlasCurrentAudit = null;
let codeAtlasTimer = null;
let agentGuideAudits = [];
let agentGuideCurrentAudit = null;
let agentGuideTimer = null;

function codeWorkspaceT(key, fallback, params = {}) {
    if (typeof moduleT === 'function') return moduleT(key, fallback, params);
    if (typeof t === 'function') return t(key, fallback, params);
    return String(fallback || '').replace(/\{(\w+)\}/g, (_, name) => params[name] ?? '');
}

function codeWorkspaceEscape(value) {
    if (typeof escapeHtml === 'function') return escapeHtml(value);
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

function codeWorkspaceScoreClass(score) {
    const value = Number(score || 0);
    if (value >= 85) return 'good';
    if (value >= 65) return 'warn';
    return 'danger';
}

function codeWorkspaceStatusLabel(status) {
    const clean = String(status || '').toLowerCase();
    if (clean === 'done') return codeWorkspaceT('codework.done', 'Terminé');
    if (clean === 'running') return codeWorkspaceT('codework.running', 'En cours');
    if (clean === 'queued') return codeWorkspaceT('codework.queued', 'En attente');
    if (clean === 'error') return codeWorkspaceT('codework.error', 'Erreur');
    if (clean === 'cancelled') return codeWorkspaceT('codework.cancelled', 'Annulé');
    return clean || '-';
}

function codeWorkspaceInputHtml(moduleId, placeholder) {
    return `
        <div class="signalatlas-launch-card">
            <div class="signalatlas-form-grid">
                <label class="signalatlas-field">
                    <span>${codeWorkspaceEscape(codeWorkspaceT('codework.projectPath', 'Dossier projet local'))}</span>
                    <input id="${moduleId}-project-path" class="signalatlas-input" type="text" placeholder="${codeWorkspaceEscape(placeholder)}">
                </label>
                <button class="signalatlas-primary-btn" type="button" onclick="${moduleId === 'codeatlas' ? 'launchCodeAtlasAudit()' : 'launchAgentGuideAudit()'}">
                    <i data-lucide="${moduleId === 'codeatlas' ? 'scan-search' : 'bot'}"></i>
                    <span>${codeWorkspaceEscape(moduleId === 'codeatlas' ? codeWorkspaceT('codeatlas.launch', 'Auditer') : codeWorkspaceT('agentguide.launch', 'Générer'))}</span>
                </button>
            </div>
            <p class="signalatlas-muted">${codeWorkspaceEscape(codeWorkspaceT('codework.pathHelp', 'JoyBoy scanne le dossier local sans envoyer le code dans git ni copier les caches/modèles.'))}</p>
        </div>
    `;
}

function renderCodeWorkspaceScores(audit) {
    const scores = Array.isArray(audit?.scores) ? audit.scores : [];
    if (!scores.length) return '';
    return `
        <div class="signalatlas-score-grid">
            ${scores.map(score => `
                <div class="signalatlas-score-card is-${codeWorkspaceEscape(codeWorkspaceScoreClass(score.score))}">
                    <div class="signalatlas-score-label">${codeWorkspaceEscape(score.label || score.id)}</div>
                    <div class="signalatlas-score-value">${codeWorkspaceEscape(score.score ?? '--')}</div>
                    <div class="signalatlas-score-unit">/100</div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderCodeWorkspaceFindings(audit) {
    const findings = Array.isArray(audit?.findings) ? audit.findings : [];
    if (!findings.length) {
        return `<div class="signalatlas-empty">${codeWorkspaceEscape(codeWorkspaceT('codework.noFindings', 'Aucun problème majeur détecté.'))}</div>`;
    }
    return `
        <div class="signalatlas-findings-list">
            ${findings.slice(0, 12).map(item => `
                <div class="signalatlas-finding-card severity-${codeWorkspaceEscape(item.severity || 'low')}">
                    <div class="signalatlas-finding-top">
                        <strong>${codeWorkspaceEscape(item.title || 'Finding')}</strong>
                        <span>${codeWorkspaceEscape(String(item.severity || '').toUpperCase())}</span>
                    </div>
                    <p>${codeWorkspaceEscape(item.detail || '')}</p>
                </div>
            `).join('')}
        </div>
    `;
}

function renderCodeWorkspacePlan(audit) {
    const items = Array.isArray(audit?.remediation_items) ? audit.remediation_items : [];
    if (!items.length) return '';
    return `
        <div class="signalatlas-remediation-list">
            ${items.slice(0, 8).map(item => `
                <div class="signalatlas-remediation-card">
                    <div class="signalatlas-remediation-priority">${codeWorkspaceEscape(item.priority || 'P3')}</div>
                    <div>
                        <strong>${codeWorkspaceEscape(item.title || '')}</strong>
                        <p>${codeWorkspaceEscape(item.why || '')}</p>
                        ${(item.validation || []).slice(0, 4).map(command => `<code>${codeWorkspaceEscape(command)}</code>`).join('')}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderCodeWorkspaceHistory(moduleId, audits, currentId) {
    if (!audits.length) return `<div class="signalatlas-history-empty">${codeWorkspaceEscape(codeWorkspaceT('codework.noAudits', 'Aucun audit pour le moment.'))}</div>`;
    return audits.map(audit => `
        <button class="signalatlas-history-card${audit.id === currentId ? ' active' : ''}" type="button" onclick="${moduleId === 'codeatlas' ? 'loadCodeAtlasAudit' : 'loadAgentGuideAudit'}('${codeWorkspaceEscape(audit.id)}')">
            <div class="signalatlas-history-title">${codeWorkspaceEscape(audit.title || audit.host || 'Audit')}</div>
            <div class="signalatlas-history-status">${codeWorkspaceEscape(codeWorkspaceStatusLabel(audit.status))}</div>
            <div class="signalatlas-history-score">${codeWorkspaceEscape(audit.global_score ?? '--')}/100</div>
        </button>
    `).join('');
}

async function loadCodeAtlasBootstrap() {
    const result = await apiCodeAtlas.listAudits(80);
    codeAtlasAudits = Array.isArray(result.data?.audits) ? result.data.audits : [];
    if (!codeAtlasCurrentAudit && codeAtlasAudits[0]?.id) {
        await loadCodeAtlasAudit(codeAtlasAudits[0].id, { silent: true });
    }
}

async function loadAgentGuideBootstrap() {
    const result = await apiAgentGuide.listAudits(80);
    agentGuideAudits = Array.isArray(result.data?.audits) ? result.data.audits : [];
    if (!agentGuideCurrentAudit && agentGuideAudits[0]?.id) {
        await loadAgentGuideAudit(agentGuideAudits[0].id, { silent: true });
    }
}

function renderCodeAtlasWorkspace() {
    const host = document.getElementById('codeatlas-view-content');
    if (!host) return;
    const audit = codeAtlasCurrentAudit;
    const comparison = audit?.snapshot?.comparison || {};
    host.innerHTML = `
        <div class="modules-shell signalatlas-workspace-shell">
            <section class="modules-hero">
                <div class="modules-kicker">CodeAtlas</div>
                <h1 class="modules-title">${codeWorkspaceEscape(codeWorkspaceT('codeatlas.title', 'Audit code local'))}</h1>
                <p class="modules-description">${codeWorkspaceEscape(codeWorkspaceT('codeatlas.description', 'Notes backend/frontend, architecture, maintenabilité, régression et plan de correction.'))}</p>
            </section>
            ${codeWorkspaceInputHtml('codeatlas', 'C:\\\\Users\\\\you\\\\project')}
            <div class="signalatlas-layout">
                <aside class="signalatlas-history-panel">${renderCodeWorkspaceHistory('codeatlas', codeAtlasAudits, audit?.id)}</aside>
                <main class="signalatlas-report-panel">
                    ${audit ? `
                        <div class="signalatlas-report-header">
                            <div><h2>${codeWorkspaceEscape(audit.title || 'CodeAtlas')}</h2><p>${codeWorkspaceEscape(audit.target?.normalized_path || '')}</p></div>
                            <div class="signalatlas-status-pill">${codeWorkspaceEscape(codeWorkspaceStatusLabel(audit.status))}</div>
                        </div>
                        ${renderCodeWorkspaceScores(audit)}
                        ${comparison.available ? `<div class="signalatlas-provider-card">${codeWorkspaceEscape(codeWorkspaceT('codeatlas.delta', 'Comparaison avant/après disponible'))}: ${codeWorkspaceEscape(comparison.global_before ?? '--')} → ${codeWorkspaceEscape(comparison.global_after ?? '--')}</div>` : ''}
                        <h3>${codeWorkspaceEscape(codeWorkspaceT('codework.findings', 'Problèmes détectés'))}</h3>
                        ${renderCodeWorkspaceFindings(audit)}
                        <h3>${codeWorkspaceEscape(codeWorkspaceT('codework.plan', 'Plan de correction'))}</h3>
                        ${renderCodeWorkspacePlan(audit)}
                        <div class="signalatlas-actions-row">
                            <button class="signalatlas-secondary-btn" onclick="rerunCodeAtlasAudit('${codeWorkspaceEscape(audit.id)}')">${codeWorkspaceEscape(codeWorkspaceT('codeatlas.rerun', 'Relancer et comparer'))}</button>
                            <a class="signalatlas-secondary-btn" href="/api/codeatlas/audits/${codeWorkspaceEscape(audit.id)}/export/markdown">${codeWorkspaceEscape(codeWorkspaceT('codework.exportMd', 'Exporter MD'))}</a>
                        </div>
                    ` : `<div class="signalatlas-empty">${codeWorkspaceEscape(codeWorkspaceT('codeatlas.empty', 'Sélectionne un projet local pour lancer le premier audit.'))}</div>`}
                </main>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons({ nodes: [host] });
}

function renderAgentGuideWorkspace() {
    const host = document.getElementById('agentguide-view-content');
    if (!host) return;
    const audit = agentGuideCurrentAudit;
    const generated = Array.isArray(audit?.metadata?.generated_files) ? audit.metadata.generated_files : [];
    host.innerHTML = `
        <div class="modules-shell signalatlas-workspace-shell">
            <section class="modules-hero">
                <div class="modules-kicker">AgentGuide</div>
                <h1 class="modules-title">${codeWorkspaceEscape(codeWorkspaceT('agentguide.title', 'Guides IA pour projets'))}</h1>
                <p class="modules-description">${codeWorkspaceEscape(codeWorkspaceT('agentguide.description', 'Génère AGENTS.md et CLAUDE.md courts, spécifiques, anti-duplication et anti-régression.'))}</p>
            </section>
            ${codeWorkspaceInputHtml('agentguide', 'C:\\\\Users\\\\you\\\\project')}
            <div class="signalatlas-layout">
                <aside class="signalatlas-history-panel">${renderCodeWorkspaceHistory('agentguide', agentGuideAudits, audit?.id)}</aside>
                <main class="signalatlas-report-panel">
                    ${audit ? `
                        <div class="signalatlas-report-header">
                            <div><h2>${codeWorkspaceEscape(audit.title || 'AgentGuide')}</h2><p>${codeWorkspaceEscape(audit.target?.normalized_path || '')}</p></div>
                            <div class="signalatlas-status-pill">${codeWorkspaceEscape(codeWorkspaceStatusLabel(audit.status))}</div>
                        </div>
                        ${renderCodeWorkspaceScores(audit)}
                        <h3>${codeWorkspaceEscape(codeWorkspaceT('agentguide.generatedFiles', 'Fichiers proposés'))}</h3>
                        ${generated.map(file => `
                            <details class="signalatlas-provider-card" open>
                                <summary><strong>${codeWorkspaceEscape(file.path)}</strong> ${file.exists ? codeWorkspaceEscape(codeWorkspaceT('agentguide.exists', '(existe déjà)')) : ''}</summary>
                                <pre class="signalatlas-code-block">${codeWorkspaceEscape(file.diff || file.content || '')}</pre>
                            </details>
                        `).join('') || `<div class="signalatlas-empty">${codeWorkspaceEscape(codeWorkspaceT('agentguide.noGenerated', 'Aucun fichier généré pour le moment.'))}</div>`}
                        <h3>${codeWorkspaceEscape(codeWorkspaceT('codework.findings', 'Problèmes détectés'))}</h3>
                        ${renderCodeWorkspaceFindings(audit)}
                        <div class="signalatlas-actions-row">
                            <button class="signalatlas-primary-btn" onclick="applyAgentGuideFiles('${codeWorkspaceEscape(audit.id)}')">${codeWorkspaceEscape(codeWorkspaceT('agentguide.apply', 'Appliquer avec backup'))}</button>
                            <a class="signalatlas-secondary-btn" href="/api/agentguide/audits/${codeWorkspaceEscape(audit.id)}/export/markdown">${codeWorkspaceEscape(codeWorkspaceT('codework.exportMd', 'Exporter MD'))}</a>
                        </div>
                    ` : `<div class="signalatlas-empty">${codeWorkspaceEscape(codeWorkspaceT('agentguide.empty', 'Sélectionne un projet local pour générer AGENTS.md et CLAUDE.md.'))}</div>`}
                </main>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons({ nodes: [host] });
}

async function openCodeAtlasWorkspace(auditId = null) {
    hideModulesWorkspaces?.();
    applyModulesShellMode?.('sidebar-modules-btn', 'codeatlas-mode');
    const view = document.getElementById('codeatlas-view');
    if (view) view.style.display = 'flex';
    if (auditId) await loadCodeAtlasAudit(auditId, { silent: true });
    await loadCodeAtlasBootstrap();
    renderCodeAtlasWorkspace();
}

async function openAgentGuideWorkspace(auditId = null) {
    hideModulesWorkspaces?.();
    applyModulesShellMode?.('sidebar-modules-btn', 'agentguide-mode');
    const view = document.getElementById('agentguide-view');
    if (view) view.style.display = 'flex';
    if (auditId) await loadAgentGuideAudit(auditId, { silent: true });
    await loadAgentGuideBootstrap();
    renderAgentGuideWorkspace();
}

async function loadCodeAtlasAudit(auditId, options = {}) {
    const result = await apiCodeAtlas.getAudit(auditId);
    if (result.ok && result.data?.audit) {
        codeAtlasCurrentAudit = result.data.audit;
        renderCodeAtlasWorkspace();
        return result.data.audit;
    }
    if (!options.silent) Toast?.error?.(result.data?.error || 'CodeAtlas load failed');
    return null;
}

async function loadAgentGuideAudit(auditId, options = {}) {
    const result = await apiAgentGuide.getAudit(auditId);
    if (result.ok && result.data?.audit) {
        agentGuideCurrentAudit = result.data.audit;
        renderAgentGuideWorkspace();
        return result.data.audit;
    }
    if (!options.silent) Toast?.error?.(result.data?.error || 'AgentGuide load failed');
    return null;
}

function startCodeAtlasPolling(auditId) {
    clearInterval(codeAtlasTimer);
    codeAtlasTimer = setInterval(async () => {
        const audit = await loadCodeAtlasAudit(auditId, { silent: true });
        if (audit && ['done', 'error', 'cancelled'].includes(String(audit.status || '').toLowerCase())) {
            clearInterval(codeAtlasTimer);
            await loadCodeAtlasBootstrap();
            renderCodeAtlasWorkspace();
        }
    }, 1800);
}

function startAgentGuidePolling(auditId) {
    clearInterval(agentGuideTimer);
    agentGuideTimer = setInterval(async () => {
        const audit = await loadAgentGuideAudit(auditId, { silent: true });
        if (audit && ['done', 'error', 'cancelled'].includes(String(audit.status || '').toLowerCase())) {
            clearInterval(agentGuideTimer);
            await loadAgentGuideBootstrap();
            renderAgentGuideWorkspace();
        }
    }, 1500);
}

function stopCodeAtlasRefresh() {
    clearInterval(codeAtlasTimer);
    codeAtlasTimer = null;
}

function stopAgentGuideRefresh() {
    clearInterval(agentGuideTimer);
    agentGuideTimer = null;
}

async function launchCodeAtlasAudit() {
    const path = document.getElementById('codeatlas-project-path')?.value || '';
    const result = await apiCodeAtlas.createAudit({ project_path: path });
    if (!result.ok) {
        Toast?.error?.(result.data?.error || 'CodeAtlas failed');
        return;
    }
    codeAtlasCurrentAudit = result.data.audit;
    await loadCodeAtlasBootstrap();
    renderCodeAtlasWorkspace();
    startCodeAtlasPolling(result.data.audit.id);
}

async function launchAgentGuideAudit() {
    const path = document.getElementById('agentguide-project-path')?.value || '';
    const result = await apiAgentGuide.createAudit({ project_path: path });
    if (!result.ok) {
        Toast?.error?.(result.data?.error || 'AgentGuide failed');
        return;
    }
    agentGuideCurrentAudit = result.data.audit;
    await loadAgentGuideBootstrap();
    renderAgentGuideWorkspace();
    startAgentGuidePolling(result.data.audit.id);
}

async function rerunCodeAtlasAudit(auditId) {
    const result = await apiCodeAtlas.rerunAudit(auditId);
    if (!result.ok) {
        Toast?.error?.(result.data?.error || 'CodeAtlas rerun failed');
        return;
    }
    codeAtlasCurrentAudit = result.data.audit;
    await loadCodeAtlasBootstrap();
    renderCodeAtlasWorkspace();
    startCodeAtlasPolling(result.data.audit.id);
}

async function applyAgentGuideFiles(auditId) {
    const result = await apiAgentGuide.applyGeneratedFiles(auditId, {});
    if (!result.ok) {
        Toast?.error?.(result.data?.error || 'Apply failed');
        return;
    }
    Toast?.success?.(codeWorkspaceT('agentguide.applied', 'Fichiers appliqués avec backup si nécessaire.'));
    await loadAgentGuideAudit(auditId, { silent: true });
}

window.openCodeAtlasWorkspace = openCodeAtlasWorkspace;
window.openAgentGuideWorkspace = openAgentGuideWorkspace;
window.loadCodeAtlasAudit = loadCodeAtlasAudit;
window.loadAgentGuideAudit = loadAgentGuideAudit;
window.launchCodeAtlasAudit = launchCodeAtlasAudit;
window.launchAgentGuideAudit = launchAgentGuideAudit;
window.rerunCodeAtlasAudit = rerunCodeAtlasAudit;
window.applyAgentGuideFiles = applyAgentGuideFiles;
window.stopCodeAtlasRefresh = stopCodeAtlasRefresh;
window.stopAgentGuideRefresh = stopAgentGuideRefresh;
