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
    let deployAtlasOpenPickerId = null;
    let deployAtlasComposerTab = 'server';
    let deployAtlasSelectedFiles = [];
    let deployAtlasSelectedSource = '';
    let deployAtlasRefreshInFlight = false;
    let deployAtlasPendingRefresh = false;
    let deployAtlasDeferredRefreshTimer = null;
    let deployAtlasLastInteractionAt = 0;
    const DEPLOYATLAS_REFRESH_IDLE_MS = 700;
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

    function markDeployAtlasInteraction() {
        deployAtlasLastInteractionAt = Date.now();
    }

    function deployAtlasIsEditing() {
        if (deployAtlasOpenPickerId) return true;
        const view = getDeployAtlasView();
        const active = document.activeElement;
        if (!view || !active || !view.contains(active)) return false;
        if (active.matches?.('input, textarea, select')) return true;
        if (active.closest?.('.signalatlas-picker.open, .model-picker.open')) return true;
        return Date.now() - deployAtlasLastInteractionAt < DEPLOYATLAS_REFRESH_IDLE_MS;
    }

    function scheduleDeployAtlasDeferredRefresh() {
        if (deployAtlasDeferredRefreshTimer) clearTimeout(deployAtlasDeferredRefreshTimer);
        deployAtlasDeferredRefreshTimer = setTimeout(async () => {
            deployAtlasDeferredRefreshTimer = null;
            if (!deployAtlasPendingRefresh || !isDeployAtlasVisible()) return;
            if (deployAtlasIsEditing()) {
                scheduleDeployAtlasDeferredRefresh();
                return;
            }
            deployAtlasPendingRefresh = false;
            await refreshDeployAtlasWorkspace({ force: true });
        }, DEPLOYATLAS_REFRESH_IDLE_MS);
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
        const read = (id, fallback = '') => {
            const element = document.getElementById(id);
            return element ? element.value : fallback;
        };
        const checked = (id, fallback = false) => {
            const element = document.getElementById(id);
            return element ? !!element.checked : fallback;
        };
        const portValue = read('deployatlas-port', deployAtlasDraft.port || 22);
        deployAtlasDraft = {
            ...deployAtlasDraft,
            server_id: read('deployatlas-server-id', deployAtlasDraft.server_id),
            name: read('deployatlas-server-name', deployAtlasDraft.name),
            host: read('deployatlas-host', deployAtlasDraft.host),
            port: Number.parseInt(portValue || '22', 10) || 22,
            username: read('deployatlas-username', deployAtlasDraft.username || 'root') || 'root',
            auth_type: read('deployatlas-auth-type', deployAtlasDraft.auth_type || 'password') || 'password',
            password: read('deployatlas-password', deployAtlasDraft.password),
            private_key: read('deployatlas-private-key', deployAtlasDraft.private_key),
            passphrase: read('deployatlas-passphrase', deployAtlasDraft.passphrase),
            sudo_mode: read('deployatlas-sudo-mode', deployAtlasDraft.sudo_mode || 'ask') || 'ask',
            domain: read('deployatlas-domain', deployAtlasDraft.domain),
            ssl_enabled: checked('deployatlas-ssl-enabled', deployAtlasDraft.ssl_enabled),
            execute_remote: checked('deployatlas-execute-remote', deployAtlasDraft.execute_remote),
            trust_host_key: checked('deployatlas-trust-host-key', deployAtlasDraft.trust_host_key),
            model: read('deployatlas-model', deployAtlasDraft.model || currentModel()) || currentModel(),
            project_name: read('deployatlas-project-name', deployAtlasDraft.project_name),
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

    function deployAtlasModelProfiles() {
        if (typeof auditModuleCurrentProfiles === 'function') {
            const sharedProfiles = auditModuleCurrentProfiles(deployAtlasModelContext);
            if (sharedProfiles.length) return sharedProfiles;
        }
        const profiles = Array.isArray(deployAtlasModelContext?.terminal_model_profiles) && deployAtlasModelContext.terminal_model_profiles.length
            ? deployAtlasModelContext.terminal_model_profiles
            : (Array.isArray(deployAtlasModelContext?.profiles) && deployAtlasModelContext.profiles.length
                ? deployAtlasModelContext.profiles
                : [{ id: currentModel(), label: currentModel(), provider: 'current', configured: true }]);
        const normalized = profiles
            .map(profile => {
                const id = profile.id || profile.name || profile.label || '';
                if (!id) return null;
                return {
                    ...profile,
                    id,
                    label: profile.label || profile.display_name || profile.name || id,
                    provider: profile.provider || (String(id).includes(':') ? String(id).split(':', 1)[0] : 'ollama'),
                    configured: profile.configured !== false,
                    terminal_runtime: profile.terminal_runtime !== false,
                };
            })
            .filter(Boolean);
        const selected = currentModel();
        if (selected && !normalized.some(profile => String(profile.id) === String(selected))) {
            normalized.unshift({
                id: selected,
                label: selected,
                provider: String(selected).includes(':') ? String(selected).split(':', 1)[0] : 'current',
                configured: true,
                terminal_runtime: true,
            });
        }
        return normalized;
    }

    function deployAtlasSimpleOptions(items, selectedValue) {
        if (typeof buildSignalAtlasSimpleOptions === 'function') {
            return buildSignalAtlasSimpleOptions(items, selectedValue);
        }
        return (items || []).map(item => ({
            value: item.value,
            label: item.label,
            description: item.description || '',
            meta: item.meta || '',
            badge: item.badge || '',
            tone: item.tone || '',
            selected: String(item.value) === String(selectedValue),
        }));
    }

    function deployAtlasPickerOptions(pickerId) {
        if (pickerId === 'auth_type') {
            return deployAtlasSimpleOptions([
                {
                    value: 'password',
                    label: deployT('passwordAuth', 'Mot de passe'),
                    description: deployT('passwordAuthHint', 'Saisie masquée, gardée en session uniquement.'),
                },
                {
                    value: 'ssh_key',
                    label: deployT('keyAuth', 'Clé SSH'),
                    description: deployT('keyAuthHint', 'Clé privée jamais transmise au modèle IA.'),
                    tone: 'private',
                },
            ], deployAtlasDraft.auth_type || 'password');
        }
        if (pickerId === 'sudo_mode') {
            return deployAtlasSimpleOptions([
                {
                    value: 'ask',
                    label: deployT('sudoAsk', 'Demander / session'),
                    description: deployT('sudoAskHint', 'Le mot de passe sudo reste local à cette session.'),
                },
                {
                    value: 'passwordless',
                    label: deployT('sudoPasswordless', 'Sans mot de passe'),
                    description: deployT('sudoPasswordlessHint', 'Pour les VPS déjà configurés en sudo NOPASSWD.'),
                },
                {
                    value: 'root',
                    label: 'root',
                    description: deployT('sudoRootHint', 'Utilise la session root sans élévation supplémentaire.'),
                },
            ], deployAtlasDraft.sudo_mode || 'ask');
        }
        if (pickerId === 'model') {
            const profiles = deployAtlasModelProfiles();
            if (typeof buildAuditModelOptions === 'function') {
                return buildAuditModelOptions(profiles, currentModel());
            }
            return deployAtlasSimpleOptions(profiles.map(profile => ({
                value: profile.id,
                label: profile.label || profile.id,
                description: profile.configured ? deployT('modelReady', 'Agent disponible') : deployT('modelMissing', 'Agent non configuré'),
                badge: profile.provider || '',
            })), currentModel());
        }
        return [];
    }

    function renderDeployAtlasPicker(pickerId, inputId, options, selectedValue) {
        if (typeof renderAuditPicker === 'function') {
            return renderAuditPicker('deployatlas', pickerId, inputId, options, selectedValue);
        }
        const items = Array.isArray(options) ? options : [];
        return `<select class="deployatlas-select" id="${esc(inputId)}">${items.map(option => (
            `<option value="${esc(option.value)}" ${String(option.value) === String(selectedValue) ? 'selected' : ''}>${esc(option.label || option.value)}</option>`
        )).join('')}</select>`;
    }

    function renderModelSelect() {
        return renderDeployAtlasPicker('model', 'deployatlas-model', deployAtlasPickerOptions('model'), currentModel());
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
                    ${renderDeployAtlasPicker('auth_type', 'deployatlas-auth-type', deployAtlasPickerOptions('auth_type'), authType)}
                </div>
                <div class="deployatlas-field">
                    <label for="deployatlas-sudo-mode">${esc(deployT('sudoMode', 'Sudo'))}</label>
                    ${renderDeployAtlasPicker('sudo_mode', 'deployatlas-sudo-mode', deployAtlasPickerOptions('sudo_mode'), deployAtlasDraft.sudo_mode || 'ask')}
                </div>
                ${authType === 'ssh_key'
                    ? `${secretInput('private_key', deployT('privateKey', 'Clé privée SSH'), 'password')}${secretInput('passphrase', deployT('passphrase', 'Passphrase'), 'password')}`
                    : secretInput('password', deployT('password', 'Mot de passe'), 'password')
                }
            </div>
            <div class="deployatlas-actions">
                <button class="deployatlas-btn secondary" type="button" onclick="saveDeployAtlasServer()"><i data-lucide="save"></i>${esc(deployT('saveServer', 'Enregistrer'))}</button>
                <button class="deployatlas-btn secondary" type="button" onclick="testDeployAtlasServer()"><i data-lucide="shield-check"></i>${esc(deployT('testServer', 'Tester SSH'))}</button>
            </div>
        `;
    }

    function renderProjectPanel() {
        const analysis = deployAtlasProjectAnalysis;
        const fileCount = deployAtlasSelectedFiles.length;
        const fileLabel = fileCount
            ? deployT('selectedFiles', '{count} fichier(s) prêts', { count: fileCount })
            : deployT('analysisEmpty', 'Ajoute un projet pour générer le manifeste de déploiement.');
        return `
            <div class="deployatlas-form-grid">
                <div class="deployatlas-field full">
                    <label for="deployatlas-project-name">${esc(deployT('projectName', 'Nom projet'))}</label>
                    <input class="deployatlas-input" id="deployatlas-project-name" value="${esc(deployAtlasDraft.project_name)}" placeholder="mon-app">
                </div>
                <label class="deployatlas-dropzone full" for="deployatlas-project-files">
                    <input id="deployatlas-project-files" type="file" multiple webkitdirectory style="display:none" onchange="setDeployAtlasProjectFiles('folder')">
                    <span><strong>${esc(deployT('folderDrop', 'Choisir un dossier projet'))}</strong>${esc(deployT('folderDropHint', 'JoyBoy exclut .git, node_modules, caches et secrets évidents.'))}</span>
                </label>
                <label class="deployatlas-dropzone full" for="deployatlas-project-archive">
                    <input id="deployatlas-project-archive" type="file" accept=".zip,.tar,.tar.gz,.tgz,.rar" style="display:none" onchange="setDeployAtlasProjectFiles('archive')">
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
            ` : `<div class="deployatlas-muted">${esc(fileLabel)}</div>`}
            <div class="deployatlas-actions">
                <button class="deployatlas-btn secondary" type="button" onclick="analyzeDeployAtlasProject()"><i data-lucide="scan-search"></i>${esc(deployT('analyzeProject', 'Analyser'))}</button>
            </div>
        `;
    }

    function renderRunOptionsPanel() {
        const providerReady = deployAtlasProviders.find(item => item.id === 'ssh_runtime')?.configured !== false;
        return `
            <div class="deployatlas-form-grid">
                <div class="deployatlas-field">
                    <label for="deployatlas-domain">${esc(deployT('domain', 'Domaine'))}</label>
                    <input class="deployatlas-input" id="deployatlas-domain" value="${esc(deployAtlasDraft.domain)}" placeholder="app.example.com">
                </div>
                <div class="deployatlas-field deployatlas-picker-field">
                    <label for="deployatlas-model">${esc(deployT('agentModel', 'Agent'))}</label>
                    ${renderModelSelect()}
                </div>
                <div class="deployatlas-field full">
                    <div class="deployatlas-options-box">
                        <label class="deployatlas-toggle-label"><input id="deployatlas-ssl-enabled" type="checkbox" ${deployAtlasDraft.ssl_enabled ? 'checked' : ''}> ${esc(deployT('installSsl', 'Installer HTTPS automatiquement si le domaine est public'))}</label>
                        <label class="deployatlas-toggle-label"><input id="deployatlas-trust-host-key" type="checkbox" ${deployAtlasDraft.trust_host_key ? 'checked' : ''}> ${esc(deployT('trustHostKey', 'Faire confiance à la fingerprint affichée'))}</label>
                        <label class="deployatlas-toggle-label"><input id="deployatlas-execute-remote" type="checkbox" ${deployAtlasDraft.execute_remote ? 'checked' : ''}> ${esc(deployT('executeRemote', 'Autoriser l’exécution distante réelle'))}</label>
                    </div>
                    <div class="deployatlas-muted">${esc(providerReady ? deployT('sshReady', 'SSH prêt côté JoyBoy. Les secrets restent en session et ne partent pas vers l’IA.') : deployT('sshMissing', 'Paramiko manque côté JoyBoy: installe les dépendances pour tester SSH.'))}</div>
                </div>
            </div>
            <div class="deployatlas-actions">
                <button class="deployatlas-btn" type="button" onclick="launchDeployAtlasDeployment()" ${deployAtlasLaunchPending ? 'disabled' : ''}><i data-lucide="rocket"></i>${esc(deployT('launchDeployment', 'Lancer le déploiement'))}</button>
            </div>
        `;
    }

    function renderDeployAtlasComposerTabs() {
        const tabs = [
            { id: 'server', label: deployT('tabServer', 'Serveur'), icon: 'server-cog' },
            { id: 'project', label: deployT('tabProject', 'Projet'), icon: 'folder-up' },
            { id: 'run', label: deployT('tabRun', 'Exécution'), icon: 'rocket' },
        ];
        return `
            <div class="deployatlas-tabs" role="tablist">
                ${tabs.map(tab => `
                    <button
                        class="deployatlas-tab${deployAtlasComposerTab === tab.id ? ' active' : ''}"
                        type="button"
                        role="tab"
                        aria-selected="${deployAtlasComposerTab === tab.id ? 'true' : 'false'}"
                        onclick="setDeployAtlasComposerTab('${esc(tab.id)}')"
                    >
                        <i data-lucide="${esc(tab.icon)}"></i>
                        <span>${esc(tab.label)}</span>
                    </button>
                `).join('')}
            </div>
        `;
    }

    function renderDeployAtlasComposerPanel() {
        if (deployAtlasComposerTab === 'project') return renderProjectPanel();
        if (deployAtlasComposerTab === 'run') return renderRunOptionsPanel();
        return renderServerForm();
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
        const splash = message => `
            <div class="deployatlas-terminal-splash">
                <img src="/static/images/monogramme.png" alt="" aria-hidden="true">
                <div>
                    <div class="deployatlas-terminal-brand">JoyBoy DeployAtlas</div>
                    <div class="deployatlas-terminal-muted">${esc(message)}</div>
                </div>
            </div>
        `;
        if (!deployment) {
            return `
                <div class="deployatlas-terminal">
                    <div class="deployatlas-terminal-chrome">
                        <span class="deployatlas-terminal-dot red"></span>
                        <span class="deployatlas-terminal-dot amber"></span>
                        <span class="deployatlas-terminal-dot green"></span>
                        <span class="deployatlas-terminal-title">joyboy@deployatlas:~</span>
                    </div>
                    <div class="deployatlas-terminal-screen">
                        ${splash(deployT('terminalWaiting', 'Terminal prêt. Lance un run pour ouvrir une session.'))}
                    </div>
                </div>
            `;
        }
        const logs = Array.isArray(deployment.logs) ? deployment.logs : [];
        const lines = logs.length ? logs : [{ phase: deployment.phase || 'ready', message: deployT('terminalReady', 'Session DeployAtlas prête.'), at: '' }];
        return `
            <div class="deployatlas-terminal">
                <div class="deployatlas-terminal-chrome">
                    <span class="deployatlas-terminal-dot red"></span>
                    <span class="deployatlas-terminal-dot amber"></span>
                    <span class="deployatlas-terminal-dot green"></span>
                    <span class="deployatlas-terminal-title">joyboy@deployatlas:${esc(deployment.phase || 'run')}</span>
                </div>
                <div class="deployatlas-terminal-screen">
                    ${logs.length ? `
                        <div class="deployatlas-terminal-boot">
                            <img src="/static/images/monogramme.png" alt="" aria-hidden="true">
                            <span>${esc(deployT('terminalBoot', 'Session JoyBoy active'))}</span>
                            <span class="deployatlas-terminal-cursor"></span>
                        </div>
                    ` : splash(deployT('terminalReady', 'Session DeployAtlas prête.'))}
                    ${lines.map(line => `
                        <div class="deployatlas-log-line">
                            <span class="deployatlas-log-prompt">$</span>
                            <span class="deployatlas-log-phase">${esc(line.phase || 'log')}</span>
                            <span>${esc(line.message || '')}</span>
                        </div>
                    `).join('')}
                </div>
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
                    <button class="deployatlas-btn secondary" type="button" onclick="refreshDeployAtlasWorkspace({ force: true })"><i data-lucide="refresh-cw"></i>${esc(deployT('refresh', 'Rafraîchir'))}</button>
                </section>
                <section class="deployatlas-workbench">
                    <aside class="deployatlas-panel deployatlas-sidebar-panel">
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
                    <main class="deployatlas-panel deployatlas-composer-panel">
                        <div class="deployatlas-panel-head">
                            <div><div class="deployatlas-panel-kicker">${esc(deployT('composer', 'Composer'))}</div><div class="deployatlas-panel-title">${esc(deployT('serverAndProject', 'Serveur + projet'))}</div></div>
                        </div>
                        <div class="deployatlas-panel-body">
                            ${renderDeployAtlasComposerTabs()}
                            <div class="deployatlas-tab-panel">
                                ${renderDeployAtlasComposerPanel()}
                            </div>
                        </div>
                    </main>
                </section>
                <section class="deployatlas-panel deployatlas-terminal-panel">
                    <div class="deployatlas-panel-head">
                        <div><div class="deployatlas-panel-kicker">${esc(deployT('live', 'Live'))}</div><div class="deployatlas-panel-title">${esc(deployT('visualTerminal', 'Terminal'))}</div></div>
                        ${deployment && !isTerminalStatus(deployment.status) ? `<button class="deployatlas-icon-btn" type="button" onclick="cancelDeployAtlasDeployment('${esc(deployment.id)}')"><i data-lucide="square"></i></button>` : ''}
                    </div>
                    <div class="deployatlas-panel-body">
                        ${renderProgress(deployment)}
                        <div class="deployatlas-terminal-wrap">
                            ${renderTerminal(deployment)}
                        </div>
                        ${renderPlan(deployment)}
                    </div>
                </section>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [host] });
    }

    async function refreshDeployAtlasWorkspace(options = {}) {
        const force = options === true || options?.force === true;
        if (!force && deployAtlasIsEditing()) {
            deployAtlasPendingRefresh = true;
            scheduleDeployAtlasDeferredRefresh();
            return;
        }
        if (deployAtlasRefreshInFlight) {
            deployAtlasPendingRefresh = true;
            return;
        }
        deployAtlasRefreshInFlight = true;
        try {
            await loadDeployAtlasBootstrap();
            if (deployAtlasCurrentDeploymentId) {
                const result = await apiDeployAtlas.getDeployment(deployAtlasCurrentDeploymentId);
                if (result.ok && result.data?.deployment) deployAtlasCurrentDeployment = result.data.deployment;
            }
            renderDeployAtlasWorkspace();
        } finally {
            deployAtlasRefreshInFlight = false;
        }
    }

    function selectedProjectFiles() {
        if (deployAtlasSelectedFiles.length) return deployAtlasSelectedFiles;
        const archive = document.getElementById('deployatlas-project-archive');
        const folder = document.getElementById('deployatlas-project-files');
        if (archive?.files?.length) return Array.from(archive.files);
        if (folder?.files?.length) return Array.from(folder.files);
        return [];
    }

    function setDeployAtlasProjectFiles(source = '') {
        const inputId = source === 'archive' ? 'deployatlas-project-archive' : 'deployatlas-project-files';
        const input = document.getElementById(inputId);
        deployAtlasSelectedFiles = Array.from(input?.files || []);
        deployAtlasSelectedSource = source;
        deployAtlasProjectAnalysis = null;
        syncDraftFromDom();
        renderDeployAtlasWorkspace();
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
        await refreshDeployAtlasWorkspace({ force: true });
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
        await refreshDeployAtlasWorkspace({ force: true });
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
        await refreshDeployAtlasWorkspace({ force: true });
    }

    async function cancelDeployAtlasDeployment(deploymentId) {
        if (!deploymentId) return;
        await apiDeployAtlas.cancelDeployment(deploymentId);
        await refreshDeployAtlasWorkspace({ force: true });
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

    function setDeployAtlasComposerTab(tabId) {
        syncDraftFromDom();
        deployAtlasComposerTab = ['server', 'project', 'run'].includes(String(tabId)) ? String(tabId) : 'server';
        renderDeployAtlasWorkspace();
    }

    function getDeployAtlasPickerState() {
        return deployAtlasOpenPickerId;
    }

    function setDeployAtlasPickerState(value) {
        deployAtlasOpenPickerId = value;
    }

    function closeDeployAtlasPicker() {
        if (!deployAtlasOpenPickerId) return;
        deployAtlasOpenPickerId = null;
        renderDeployAtlasWorkspace();
    }

    function toggleDeployAtlasPicker(pickerId, event) {
        event?.stopPropagation?.();
        markDeployAtlasInteraction();
        syncDraftFromDom();
        if (typeof toggleAuditPicker === 'function') {
            toggleAuditPicker('deployatlas', pickerId, event);
            return;
        }
        deployAtlasOpenPickerId = deployAtlasOpenPickerId === pickerId ? null : pickerId;
        renderDeployAtlasWorkspace();
    }

    function selectDeployAtlasPickerOption(pickerId, value, event) {
        event?.stopPropagation?.();
        markDeployAtlasInteraction();
        syncDraftFromDom();
        deployAtlasOpenPickerId = null;
        if (pickerId === 'auth_type') deployAtlasDraft.auth_type = String(value || 'password');
        if (pickerId === 'sudo_mode') deployAtlasDraft.sudo_mode = String(value || 'ask');
        if (pickerId === 'model') deployAtlasDraft.model = String(value || currentModel());
        const hiddenInputId = pickerId === 'auth_type'
            ? 'deployatlas-auth-type'
            : (pickerId === 'sudo_mode' ? 'deployatlas-sudo-mode' : (pickerId === 'model' ? 'deployatlas-model' : ''));
        const hiddenInput = hiddenInputId ? document.getElementById(hiddenInputId) : null;
        if (hiddenInput) hiddenInput.value = String(value ?? '');
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
    window.setDeployAtlasComposerTab = setDeployAtlasComposerTab;
    window.setDeployAtlasProjectFiles = setDeployAtlasProjectFiles;
    window.getDeployAtlasPickerState = getDeployAtlasPickerState;
    window.setDeployAtlasPickerState = setDeployAtlasPickerState;
    window.closeDeployAtlasPicker = closeDeployAtlasPicker;
    window.toggleDeployAtlasPicker = toggleDeployAtlasPicker;
    window.selectDeployAtlasPickerOption = selectDeployAtlasPickerOption;

    const handleDeployAtlasInteraction = event => {
        const view = getDeployAtlasView();
        const target = event?.target;
        if (!view || !target || !view.contains(target)) return;
        markDeployAtlasInteraction();
        if (target.matches?.('input, textarea, select') && target.type !== 'file') {
            syncDraftFromDom();
        }
    };
    document.addEventListener('focusin', handleDeployAtlasInteraction, true);
    document.addEventListener('input', handleDeployAtlasInteraction, true);
    document.addEventListener('change', handleDeployAtlasInteraction, true);
    document.addEventListener('pointerdown', handleDeployAtlasInteraction, true);
    document.addEventListener('focusout', () => {
        if (deployAtlasPendingRefresh) scheduleDeployAtlasDeferredRefresh();
    }, true);

    window.addEventListener('joyboy:runtime-jobs-updated', event => {
        deployAtlasRuntimeJobsCache = Array.isArray(event?.detail?.jobs) ? event.detail.jobs : [];
        if (isDeployAtlasVisible()) refreshDeployAtlasWorkspace();
    });
})();
