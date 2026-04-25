// ===== DEPLOYATLAS WORKSPACE =====

(function () {
    let deployAtlasServers = [];
    let deployAtlasDeployments = [];
    let deployAtlasCurrentDeploymentId = null;
    let deployAtlasCurrentDeployment = null;
    let deployAtlasProjectAnalysis = null;
    let deployAtlasModelContext = null;
    let deployAtlasProviders = [];
    let deployAtlasRuntimeJobsCache = [];
    let deployAtlasLoading = false;
    let deployAtlasLaunchPending = false;
    let deployAtlasRefreshTimer = null;
    let deployAtlasSecretVisible = {
        password: false,
        private_key: false,
        passphrase: false,
    };
    let deployAtlasDraft = {
        server_id: '',
        name: '',
        host: '',
        port: 22,
        username: 'root',
        auth_type: 'password',
        password: '',
        private_key: '',
        passphrase: '',
        sudo_mode: 'ask',
        domain: '',
        ssl_enabled: true,
        execute_remote: false,
        trust_host_key: false,
        model: '',
        project_name: '',
    };

    function deployT(key, fallback = '', params = {}) {
        const fullKey = key.startsWith('deployatlas.') ? key : `deployatlas.${key}`;
        if (typeof moduleT === 'function') return moduleT(fullKey, fallback, params);
        let text = fallback || fullKey;
        Object.entries(params || {}).forEach(([name, value]) => {
            text = String(text).replace(new RegExp(`\\{${name}\\}`, 'g'), String(value));
        });
        return text;
    }

    function esc(value) {
        if (typeof escapeHtml === 'function') return escapeHtml(value);
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#039;');
    }

    function currentModel() {
        if (deployAtlasDraft.model) return deployAtlasDraft.model;
        if (typeof currentJoyBoyChatModel === 'function') return currentJoyBoyChatModel();
        return 'openai:gpt-5.5';
    }

    function getDeployAtlasView() {
        return document.getElementById('deployatlas-view');
    }

    function isDeployAtlasVisible() {
        const view = getDeployAtlasView();
        return !!view && view.style.display !== 'none';
    }

    function deployAtlasRuntimeJobs() {
        const jobs = Array.isArray(deployAtlasRuntimeJobsCache) ? deployAtlasRuntimeJobsCache : [];
        return jobs.filter(job => String(job?.metadata?.module_id || '').toLowerCase() === 'deployatlas');
    }

    function liveJobForDeployment(deploymentId) {
        const id = String(deploymentId || '').trim();
        return deployAtlasRuntimeJobs().find(job => String(job?.metadata?.deployment_id || '') === id) || null;
    }

    function isTerminalStatus(status) {
        return ['done', 'error', 'cancelled'].includes(String(status || '').toLowerCase());
    }

    function deploymentProgress(deployment) {
        const job = liveJobForDeployment(deployment?.id);
        const value = Number(job?.progress ?? deployment?.progress ?? 0);
        return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
    }

    function syncDraftFromDom() {
        const read = id => document.getElementById(id)?.value ?? '';
        const checked = id => !!document.getElementById(id)?.checked;
        deployAtlasDraft = {
            ...deployAtlasDraft,
            server_id: read('deployatlas-server-id'),
            name: read('deployatlas-server-name'),
            host: read('deployatlas-host'),
            port: Number.parseInt(read('deployatlas-port') || '22', 10) || 22,
            username: read('deployatlas-username') || 'root',
            auth_type: read('deployatlas-auth-type') || 'password',
            password: read('deployatlas-password'),
            private_key: read('deployatlas-private-key'),
            passphrase: read('deployatlas-passphrase'),
            sudo_mode: read('deployatlas-sudo-mode') || 'ask',
            domain: read('deployatlas-domain'),
            ssl_enabled: checked('deployatlas-ssl-enabled'),
            execute_remote: checked('deployatlas-execute-remote'),
            trust_host_key: checked('deployatlas-trust-host-key'),
            model: read('deployatlas-model') || currentModel(),
            project_name: read('deployatlas-project-name'),
        };
    }

    function applyServerToDraft(server) {
        if (!server) return;
        deployAtlasDraft = {
            ...deployAtlasDraft,
            server_id: server.id || '',
            name: server.name || '',
            host: server.host || '',
            port: server.port || 22,
            username: server.username || 'root',
            auth_type: server.auth_type || 'password',
            sudo_mode: server.sudo_mode || 'ask',
            domain: server.domain || '',
            ssl_enabled: server.ssl_enabled !== false,
            trust_host_key: Boolean(server.host_fingerprint),
        };
    }

    async function loadDeployAtlasBootstrap() {
        if (deployAtlasLoading) return;
        deployAtlasLoading = true;
        try {
            const [servers, deployments, models, providers] = await Promise.all([
                apiDeployAtlas.listServers(),
                apiDeployAtlas.listDeployments(40),
                apiDeployAtlas.getModelContext(),
                apiDeployAtlas.getProviderStatus(),
            ]);
            deployAtlasServers = Array.isArray(servers.data?.servers) ? servers.data.servers : [];
            deployAtlasDeployments = Array.isArray(deployments.data?.deployments) ? deployments.data.deployments : [];
            deployAtlasModelContext = models.data || deployAtlasModelContext;
            deployAtlasProviders = Array.isArray(providers.data?.providers) ? providers.data.providers : [];
            if (deployAtlasCurrentDeploymentId) {
                const found = deployAtlasDeployments.find(item => item.id === deployAtlasCurrentDeploymentId);
                if (found) deployAtlasCurrentDeployment = found;
            } else if (!deployAtlasCurrentDeployment && deployAtlasDeployments.length) {
                deployAtlasCurrentDeployment = deployAtlasDeployments[0];
                deployAtlasCurrentDeploymentId = deployAtlasCurrentDeployment.id;
            }
        } catch (error) {
            console.warn('[DeployAtlas] bootstrap failed:', error);
        } finally {
            deployAtlasLoading = false;
        }
    }

    function renderServerList() {
        if (!deployAtlasServers.length) {
            return `<div class="deployatlas-muted">${esc(deployT('noServers', 'Aucun serveur enregistré. Ajoute ton premier VPS, teste la fingerprint, puis lance un run.'))}</div>`;
        }
        return deployAtlasServers.map(server => {
            const active = String(server.id) === String(deployAtlasDraft.server_id);
            return `
                <button class="deployatlas-server-card${active ? ' active' : ''}" type="button" onclick="selectDeployAtlasServer('${esc(server.id)}')">
                    <div class="deployatlas-server-name">${esc(server.name || server.host || 'VPS')}</div>
                    <div class="deployatlas-server-meta">${esc(server.username || 'root')}@${esc(server.host || '')}:${esc(server.port || 22)}</div>
                    <div class="deployatlas-chip-row">
                        <span class="deployatlas-chip ${server.host_fingerprint ? 'good' : 'warn'}">${esc(server.host_fingerprint ? deployT('fingerprintTrusted', 'Fingerprint OK') : deployT('fingerprintMissing', 'Fingerprint à valider'))}</span>
                    </div>
                </button>
            `;
        }).join('');
    }

    function renderRecentDeployments() {
        if (!deployAtlasDeployments.length) {
            return `<div class="deployatlas-muted">${esc(deployT('noDeployments', 'Aucun run DeployAtlas pour le moment.'))}</div>`;
        }
        return deployAtlasDeployments.slice(0, 8).map(deployment => {
            const active = deployment.id === deployAtlasCurrentDeploymentId;
            const progress = deploymentProgress(deployment);
            return `
                <button class="deployatlas-run-card${active ? ' active' : ''}" type="button" onclick="openDeployAtlasWorkspace('${esc(deployment.id)}')">
                    <div class="deployatlas-run-name">${esc(deployment.title || 'Deployment')}</div>
                    <div class="deployatlas-run-meta">${esc(deployment.status || 'queued')} · ${esc(deployment.phase || '')} · ${Math.round(progress)}%</div>
                </button>
            `;
        }).join('');
    }

    function renderModelSelect() {
        const profiles = Array.isArray(deployAtlasModelContext?.profiles) && deployAtlasModelContext.profiles.length
            ? deployAtlasModelContext.profiles
            : [{ id: currentModel(), label: currentModel(), provider: 'current' }];
        const selected = currentModel();
        return profiles.map(profile => {
            const value = profile.id || profile.name || profile.label || '';
            const label = profile.label || profile.display_name || profile.name || value;
            return `<option value="${esc(value)}" ${String(value) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`;
        }).join('');
    }

    function secretInput(id, label, type = 'password') {
        const visible = !!deployAtlasSecretVisible[id];
        const inputType = visible ? 'text' : type;
        const value = deployAtlasDraft[id] || '';
        const isTextarea = id === 'private_key';
        return `
            <div class="deployatlas-field ${isTextarea ? 'full' : ''}">
                <label for="deployatlas-${id.replace('_', '-')}">${esc(label)}</label>
                <div class="deployatlas-secret-field">
                    ${isTextarea
                        ? `<textarea class="deployatlas-textarea" id="deployatlas-private-key" spellcheck="false" ${visible ? '' : 'style="-webkit-text-security:disc;"'}>${esc(value)}</textarea>`
                        : `<input class="deployatlas-input" id="deployatlas-${id.replace('_', '-')}" type="${esc(inputType)}" value="${esc(value)}" autocomplete="off">`
                    }
                    <button class="deployatlas-icon-btn" type="button" onclick="toggleDeployAtlasSecret('${esc(id)}')" title="${esc(deployT('toggleSecret', 'Afficher / masquer'))}">
                        <i data-lucide="${visible ? 'eye-off' : 'eye'}"></i>
                    </button>
                </div>
            </div>
        `;
    }

    function renderServerForm() {
        const authType = deployAtlasDraft.auth_type || 'password';
        const providerReady = deployAtlasProviders.find(item => item.id === 'ssh_runtime')?.configured !== false;
        return `
            <div class="deployatlas-form-grid">
                <input type="hidden" id="deployatlas-server-id" value="${esc(deployAtlasDraft.server_id)}">
                <div class="deployatlas-field">
                    <label for="deployatlas-server-name">${esc(deployT('serverName', 'Nom serveur'))}</label>
                    <input class="deployatlas-input" id="deployatlas-server-name" value="${esc(deployAtlasDraft.name)}" placeholder="Production VPS">
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-host">${esc(deployT('host', 'Hostname / IP'))}</label>
                    <input class="deployatlas-input" id="deployatlas-host" value="${esc(deployAtlasDraft.host)}" placeholder="vps.example.com">
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-port">${esc(deployT('port', 'Port'))}</label>
                    <input class="deployatlas-input" id="deployatlas-port" type="number" min="1" max="65535" value="${esc(deployAtlasDraft.port || 22)}">
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-username">${esc(deployT('username', 'Utilisateur'))}</label>
                    <input class="deployatlas-input" id="deployatlas-username" value="${esc(deployAtlasDraft.username || 'root')}" placeholder="root">
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-auth-type">${esc(deployT('authType', 'Authentification'))}</label>
                    <select class="deployatlas-select" id="deployatlas-auth-type" onchange="syncDeployAtlasDraftAndRender()">
                        <option value="password" ${authType === 'password' ? 'selected' : ''}>${esc(deployT('passwordAuth', 'Mot de passe'))}</option>
                        <option value="ssh_key" ${authType === 'ssh_key' ? 'selected' : ''}>${esc(deployT('keyAuth', 'Clé SSH'))}</option>
                    </select>
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-sudo-mode">${esc(deployT('sudoMode', 'Sudo'))}</label>
                    <select class="deployatlas-select" id="deployatlas-sudo-mode">
                        <option value="ask" ${deployAtlasDraft.sudo_mode === 'ask' ? 'selected' : ''}>${esc(deployT('sudoAsk', 'Demander / session'))}</option>
                        <option value="passwordless" ${deployAtlasDraft.sudo_mode === 'passwordless' ? 'selected' : ''}>${esc(deployT('sudoPasswordless', 'Sans mot de passe'))}</option>
                        <option value="root" ${deployAtlasDraft.sudo_mode === 'root' ? 'selected' : ''}>root</option>
                    </select>
                </div>
                ${authType === 'ssh_key'
                    ? `${secretInput('private_key', deployT('privateKey', 'Clé privée SSH'), 'password')}${secretInput('passphrase', deployT('passphrase', 'Passphrase'), 'password')}`
                    : secretInput('password', deployT('password', 'Mot de passe'), 'password')
                }
                <div class="deployatlas-field">
                    <label for="deployatlas-domain">${esc(deployT('domain', 'Domaine'))}</label>
                    <input class="deployatlas-input" id="deployatlas-domain" value="${esc(deployAtlasDraft.domain)}" placeholder="app.example.com">
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-model">${esc(deployT('agentModel', 'Agent'))}</label>
                    <select class="deployatlas-select" id="deployatlas-model">${renderModelSelect()}</select>
                </div>
                <div class="deployatlas-field full">
                    <label class="deployatlas-toggle-label"><input id="deployatlas-ssl-enabled" type="checkbox" ${deployAtlasDraft.ssl_enabled ? 'checked' : ''}> ${esc(deployT('installSsl', 'Installer HTTPS automatiquement si le domaine est public'))}</label>
                    <label class="deployatlas-toggle-label"><input id="deployatlas-trust-host-key" type="checkbox" ${deployAtlasDraft.trust_host_key ? 'checked' : ''}> ${esc(deployT('trustHostKey', 'Faire confiance à la fingerprint affichée'))}</label>
                    <label class="deployatlas-toggle-label"><input id="deployatlas-execute-remote" type="checkbox" ${deployAtlasDraft.execute_remote ? 'checked' : ''}> ${esc(deployT('executeRemote', 'Autoriser l’exécution distante réelle'))}</label>
                    <div class="deployatlas-muted">${esc(providerReady ? deployT('sshReady', 'SSH prêt côté JoyBoy. Les secrets restent en session et ne partent pas vers l’IA.') : deployT('sshMissing', 'Paramiko manque côté JoyBoy: installe les dépendances pour tester SSH.'))}</div>
                </div>
            </div>
            <div class="deployatlas-actions">
                <button class="deployatlas-btn secondary" type="button" onclick="saveDeployAtlasServer()"><i data-lucide="save"></i>${esc(deployT('saveServer', 'Enregistrer'))}</button>
                <button class="deployatlas-btn secondary" type="button" onclick="testDeployAtlasServer()"><i data-lucide="shield-check"></i>${esc(deployT('testServer', 'Tester SSH'))}</button>
            </div>
        `;
    }

    function renderProjectPanel() {
        const analysis = deployAtlasProjectAnalysis;
        return `
            <div class="deployatlas-form-grid">
                <div class="deployatlas-field full">
                    <label for="deployatlas-project-name">${esc(deployT('projectName', 'Nom projet'))}</label>
                    <input class="deployatlas-input" id="deployatlas-project-name" value="${esc(deployAtlasDraft.project_name)}" placeholder="mon-app">
                </div>
                <label class="deployatlas-dropzone full" for="deployatlas-project-files">
                    <input id="deployatlas-project-files" type="file" multiple webkitdirectory style="display:none">
                    <span><strong>${esc(deployT('folderDrop', 'Choisir un dossier projet'))}</strong>${esc(deployT('folderDropHint', 'JoyBoy exclut .git, node_modules, caches et secrets évidents.'))}</span>
                </label>
                <label class="deployatlas-dropzone full" for="deployatlas-project-archive">
                    <input id="deployatlas-project-archive" type="file" accept=".zip,.tar,.tar.gz,.tgz,.rar" style="display:none">
                    <span><strong>${esc(deployT('archiveDrop', 'Ou envoyer une archive'))}</strong>${esc(deployT('archiveDropHint', 'ZIP/TAR.GZ supportés, RAR si 7z est disponible.'))}</span>
                </label>
            </div>
            ${analysis ? `
                <div class="deployatlas-chip-row">
                    <span class="deployatlas-chip good">${esc(analysis.stack || 'stack')}</span>
                    <span class="deployatlas-chip">${esc(analysis.strategy || 'strategy')}</span>
                    <span class="deployatlas-chip">${esc(deployT('fileCount', '{count} fichiers', { count: analysis.file_count || 0 }))}</span>
                    ${(analysis.frameworks || []).map(item => `<span class="deployatlas-chip">${esc(item)}</span>`).join('')}
                </div>
                ${(analysis.warnings || []).map(item => `<div class="deployatlas-muted">${esc(item)}</div>`).join('')}
            ` : `<div class="deployatlas-muted">${esc(deployT('analysisEmpty', 'Ajoute un projet pour générer le manifeste de déploiement.'))}</div>`}
            <div class="deployatlas-actions">
                <button class="deployatlas-btn secondary" type="button" onclick="analyzeDeployAtlasProject()"><i data-lucide="scan-search"></i>${esc(deployT('analyzeProject', 'Analyser'))}</button>
                <button class="deployatlas-btn" type="button" onclick="launchDeployAtlasDeployment()" ${deployAtlasLaunchPending ? 'disabled' : ''}><i data-lucide="rocket"></i>${esc(deployT('launchDeployment', 'Lancer le déploiement'))}</button>
            </div>
        `;
    }

    function renderProgress(deployment) {
        if (!deployment) {
            return `<div class="deployatlas-muted">${esc(deployT('terminalEmpty', 'Le terminal visuel apparaîtra dès qu’un run démarre.'))}</div>`;
        }
        const progress = deploymentProgress(deployment);
        const job = liveJobForDeployment(deployment.id);
        const phase = job?.phase || deployment.phase || deployment.status || 'ready';
        const message = job?.message || (deployment.logs || []).slice(-1)[0]?.message || deployT('ready', 'Prêt');
        return `
            <div class="deployatlas-progress-panel">
                <div class="deployatlas-progress-top">
                    <span>${esc(phase)}</span>
                    <span>${Math.round(progress)}%</span>
                </div>
                <div class="deployatlas-progress-bar"><div class="deployatlas-progress-fill" style="width:${progress}%"></div></div>
                <div class="deployatlas-shimmer">${esc(message)}</div>
            </div>
        `;
    }

    function renderTerminal(deployment) {
        if (!deployment) return `<div class="deployatlas-terminal">${esc(deployT('terminalWaiting', 'Aucun run sélectionné.'))}</div>`;
        const logs = Array.isArray(deployment.logs) ? deployment.logs : [];
        const lines = logs.length ? logs : [{ phase: deployment.phase || 'ready', message: deployT('terminalReady', 'DeployAtlas est prêt.'), at: '' }];
        return `
            <div class="deployatlas-terminal">
                ${lines.map(line => `
                    <div class="deployatlas-log-line">
                        <span class="deployatlas-log-phase">${esc(line.phase || 'log')}</span>
                        <span>${esc(line.message || '')}</span>
                    </div>
                `).join('')}
            </div>
        `;
    }

    function renderPlan(deployment) {
        const plan = deployment?.plan || {};
        const commands = Array.isArray(plan.commands) ? plan.commands : [];
        if (!commands.length) return '';
        return `
            <div class="deployatlas-plan">
                <div class="deployatlas-panel-kicker">${esc(deployT('runbook', 'Runbook'))}</div>
                ${commands.map(command => `<div class="deployatlas-command">${esc(command)}</div>`).join('')}
            </div>
        `;
    }

    function renderDeployAtlasWorkspace() {
        const host = document.getElementById('deployatlas-view-content');
        if (!host) return;
        const deployment = deployAtlasCurrentDeployment;
        host.innerHTML = `
            <div class="deployatlas-shell">
                <section class="deployatlas-hero">
                    <div>
                        <div class="deployatlas-kicker">DEPLOYATLAS</div>
                        <h1 class="deployatlas-title">${esc(deployT('title', 'Déployer un projet sur VPS'))}</h1>
                        <p class="deployatlas-subtitle">${esc(deployT('subtitle', 'Analyse ton projet, valide le serveur, prépare HTTPS et suis chaque étape dans un terminal visuel propre.'))}</p>
                    </div>
                    <button class="deployatlas-btn secondary" type="button" onclick="refreshDeployAtlasWorkspace()"><i data-lucide="refresh-cw"></i>${esc(deployT('refresh', 'Rafraîchir'))}</button>
                </section>
                <section class="deployatlas-grid">
                    <aside class="deployatlas-panel">
                        <div class="deployatlas-panel-head">
                            <div><div class="deployatlas-panel-kicker">${esc(deployT('servers', 'Serveurs'))}</div><div class="deployatlas-panel-title">${esc(deployT('savedServers', 'VPS enregistrés'))}</div></div>
                            <button class="deployatlas-icon-btn" type="button" onclick="newDeployAtlasServer()"><i data-lucide="plus"></i></button>
                        </div>
                        <div class="deployatlas-panel-body">
                            <div class="deployatlas-server-list">${renderServerList()}</div>
                            <div class="deployatlas-panel-kicker" style="margin-top:16px">${esc(deployT('recentRuns', 'Runs récents'))}</div>
                            <div class="deployatlas-run-list" style="margin-top:8px">${renderRecentDeployments()}</div>
                        </div>
                    </aside>
                    <main class="deployatlas-panel">
                        <div class="deployatlas-panel-head">
                            <div><div class="deployatlas-panel-kicker">${esc(deployT('composer', 'Composer'))}</div><div class="deployatlas-panel-title">${esc(deployT('serverAndProject', 'Serveur + projet'))}</div></div>
                        </div>
                        <div class="deployatlas-panel-body">
                            ${renderServerForm()}
                            <div style="height:14px"></div>
                            ${renderProjectPanel()}
                        </div>
                    </main>
                    <aside class="deployatlas-panel">
                        <div class="deployatlas-panel-head">
                            <div><div class="deployatlas-panel-kicker">${esc(deployT('live', 'Live'))}</div><div class="deployatlas-panel-title">${esc(deployT('visualTerminal', 'Terminal visuel'))}</div></div>
                            ${deployment && !isTerminalStatus(deployment.status) ? `<button class="deployatlas-icon-btn" type="button" onclick="cancelDeployAtlasDeployment('${esc(deployment.id)}')"><i data-lucide="square"></i></button>` : ''}
                        </div>
                        <div class="deployatlas-panel-body">
                            ${renderProgress(deployment)}
                            <div style="height:12px"></div>
                            ${renderTerminal(deployment)}
                            ${renderPlan(deployment)}
                        </div>
                    </aside>
                </section>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [host] });
    }

    async function refreshDeployAtlasWorkspace() {
        await loadDeployAtlasBootstrap();
        if (deployAtlasCurrentDeploymentId) {
            const result = await apiDeployAtlas.getDeployment(deployAtlasCurrentDeploymentId);
            if (result.ok && result.data?.deployment) deployAtlasCurrentDeployment = result.data.deployment;
        }
        renderDeployAtlasWorkspace();
    }

    function selectedProjectFiles() {
        const archive = document.getElementById('deployatlas-project-archive');
        const folder = document.getElementById('deployatlas-project-files');
        if (archive?.files?.length) return Array.from(archive.files);
        if (folder?.files?.length) return Array.from(folder.files);
        return [];
    }

    async function analyzeDeployAtlasProject() {
        syncDraftFromDom();
        const files = selectedProjectFiles();
        if (!files.length) {
            Toast?.warning?.(deployT('projectRequired', 'Ajoute une archive ou un dossier projet.'));
            return null;
        }
        const form = new FormData();
        form.set('name', deployAtlasDraft.project_name || files[0]?.name || 'Projet');
        files.forEach(file => form.append('files', file, file.webkitRelativePath || file.name));
        const result = await apiDeployAtlas.analyzeProject(form);
        if (!result.ok || !result.data?.success) {
            Toast?.error?.(result.data?.error || deployT('analysisFailed', 'Analyse projet impossible.'));
            return null;
        }
        deployAtlasProjectAnalysis = result.data.analysis;
        Toast?.success?.(deployT('analysisReady', 'Analyse projet prête.'));
        renderDeployAtlasWorkspace();
        return deployAtlasProjectAnalysis;
    }

    async function saveDeployAtlasServer() {
        syncDraftFromDom();
        const result = await apiDeployAtlas.saveServer({
            id: deployAtlasDraft.server_id || undefined,
            name: deployAtlasDraft.name,
            host: deployAtlasDraft.host,
            port: deployAtlasDraft.port,
            username: deployAtlasDraft.username,
            auth_type: deployAtlasDraft.auth_type,
            sudo_mode: deployAtlasDraft.sudo_mode,
            domain: deployAtlasDraft.domain,
            ssl_enabled: deployAtlasDraft.ssl_enabled,
        });
        if (!result.ok || !result.data?.server) {
            Toast?.error?.(result.data?.error || deployT('saveFailed', 'Impossible d’enregistrer ce serveur.'));
            return;
        }
        applyServerToDraft(result.data.server);
        await refreshDeployAtlasWorkspace();
        Toast?.success?.(deployT('serverSaved', 'Serveur enregistré.'));
    }

    async function testDeployAtlasServer() {
        syncDraftFromDom();
        const serverId = deployAtlasDraft.server_id || 'new';
        const payload = {
            ...deployAtlasDraft,
            credentials: {
                password: deployAtlasDraft.password,
                private_key: deployAtlasDraft.private_key,
                passphrase: deployAtlasDraft.passphrase,
            },
        };
        const result = await apiDeployAtlas.testServer(serverId, payload);
        const status = result.data?.result?.status || result.data?.status;
        if (status === 'requires_trust') {
            deployAtlasDraft.trust_host_key = true;
            Toast?.warning?.(`${deployT('fingerprintNeedsTrust', 'Fingerprint à valider')}: ${result.data?.result?.fingerprint || ''}`);
            renderDeployAtlasWorkspace();
            return;
        }
        if (!result.ok || !result.data?.success) {
            Toast?.error?.(result.data?.result?.message || result.data?.error || deployT('sshFailed', 'Test SSH échoué.'));
            return;
        }
        Toast?.success?.(deployT('sshOk', 'Connexion SSH validée.'));
        await refreshDeployAtlasWorkspace();
    }

    async function launchDeployAtlasDeployment() {
        syncDraftFromDom();
        let analysis = deployAtlasProjectAnalysis;
        if (!analysis) analysis = await analyzeDeployAtlasProject();
        if (!analysis) return;
        deployAtlasLaunchPending = true;
        renderDeployAtlasWorkspace();
        const result = await apiDeployAtlas.createDeployment({
            title: deployAtlasDraft.project_name || analysis.name || 'DeployAtlas',
            server_id: deployAtlasDraft.server_id,
            server: {
                name: deployAtlasDraft.name,
                host: deployAtlasDraft.host,
                port: deployAtlasDraft.port,
                username: deployAtlasDraft.username,
                auth_type: deployAtlasDraft.auth_type,
                sudo_mode: deployAtlasDraft.sudo_mode,
                domain: deployAtlasDraft.domain,
                ssl_enabled: deployAtlasDraft.ssl_enabled,
            },
            project_analysis: analysis,
            options: {
                model: deployAtlasDraft.model || currentModel(),
                domain: deployAtlasDraft.domain,
                ssl_enabled: deployAtlasDraft.ssl_enabled,
                execute_remote: deployAtlasDraft.execute_remote,
                trust_host_key: deployAtlasDraft.trust_host_key,
            },
            credentials: {
                password: deployAtlasDraft.password,
                private_key: deployAtlasDraft.private_key,
                passphrase: deployAtlasDraft.passphrase,
            },
        });
        deployAtlasLaunchPending = false;
        if (!result.ok || !result.data?.deployment) {
            Toast?.error?.(result.data?.error || deployT('launchFailed', 'Impossible de lancer le run DeployAtlas.'));
            renderDeployAtlasWorkspace();
            return;
        }
        deployAtlasCurrentDeployment = result.data.deployment;
        deployAtlasCurrentDeploymentId = deployAtlasCurrentDeployment.id;
        Toast?.success?.(deployT('deploymentStarted', 'Run DeployAtlas lancé.'));
        startDeployAtlasRefresh();
        await refreshDeployAtlasWorkspace();
    }

    async function cancelDeployAtlasDeployment(deploymentId) {
        if (!deploymentId) return;
        await apiDeployAtlas.cancelDeployment(deploymentId);
        await refreshDeployAtlasWorkspace();
        Toast?.info?.(deployT('cancelRequested', 'Arrêt demandé.'));
    }

    function startDeployAtlasRefresh() {
        if (deployAtlasRefreshTimer) return;
        deployAtlasRefreshTimer = setInterval(async () => {
            if (!isDeployAtlasVisible()) return;
            await refreshDeployAtlasWorkspace();
            const active = deployAtlasDeployments.some(item => !isTerminalStatus(item.status));
            if (!active && deployAtlasRefreshTimer) {
                clearInterval(deployAtlasRefreshTimer);
                deployAtlasRefreshTimer = null;
            }
        }, 2000);
    }

    async function openDeployAtlasWorkspace(deploymentId = null) {
        if (deploymentId) deployAtlasCurrentDeploymentId = deploymentId;
        if (typeof hideModulesWorkspaces === 'function') hideModulesWorkspaces();
        if (typeof applyModulesShellMode === 'function') {
            applyModulesShellMode('sidebar-modules-btn', 'deployatlas-mode');
        }
        const view = getDeployAtlasView();
        if (view) view.style.display = 'flex';
        await loadDeployAtlasBootstrap();
        if (deploymentId) {
            const result = await apiDeployAtlas.getDeployment(deploymentId);
            if (result.ok && result.data?.deployment) deployAtlasCurrentDeployment = result.data.deployment;
        }
        renderDeployAtlasWorkspace();
        startDeployAtlasRefresh();
    }

    function selectDeployAtlasServer(serverId) {
        const server = deployAtlasServers.find(item => String(item.id) === String(serverId));
        applyServerToDraft(server);
        renderDeployAtlasWorkspace();
    }

    function newDeployAtlasServer() {
        deployAtlasDraft = {
            ...deployAtlasDraft,
            server_id: '',
            name: '',
            host: '',
            port: 22,
            username: 'root',
            password: '',
            private_key: '',
            passphrase: '',
            trust_host_key: false,
        };
        renderDeployAtlasWorkspace();
    }

    function toggleDeployAtlasSecret(field) {
        deployAtlasSecretVisible[field] = !deployAtlasSecretVisible[field];
        syncDraftFromDom();
        renderDeployAtlasWorkspace();
    }

    function syncDeployAtlasDraftAndRender() {
        syncDraftFromDom();
        renderDeployAtlasWorkspace();
    }

    window.openDeployAtlasWorkspace = openDeployAtlasWorkspace;
    window.renderDeployAtlasWorkspace = renderDeployAtlasWorkspace;
    window.refreshDeployAtlasWorkspace = refreshDeployAtlasWorkspace;
    window.selectDeployAtlasServer = selectDeployAtlasServer;
    window.newDeployAtlasServer = newDeployAtlasServer;
    window.saveDeployAtlasServer = saveDeployAtlasServer;
    window.testDeployAtlasServer = testDeployAtlasServer;
    window.analyzeDeployAtlasProject = analyzeDeployAtlasProject;
    window.launchDeployAtlasDeployment = launchDeployAtlasDeployment;
    window.cancelDeployAtlasDeployment = cancelDeployAtlasDeployment;
    window.toggleDeployAtlasSecret = toggleDeployAtlasSecret;
    window.syncDeployAtlasDraftAndRender = syncDeployAtlasDraftAndRender;

    window.addEventListener('joyboy:runtime-jobs-updated', event => {
        deployAtlasRuntimeJobsCache = Array.isArray(event?.detail?.jobs) ? event.detail.jobs : [];
        if (isDeployAtlasVisible()) refreshDeployAtlasWorkspace();
    });
})();
