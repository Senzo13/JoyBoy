// ===== SETTINGS MCP PANEL =====
// MCP runtime rendering and config editor for the provider settings surface.

function renderMcpSettingsGroup(mcpData, loadError = '') {
    const title = t('providers.mcpTitle', 'MCP et outils externes');
    const description = t('providers.mcpDesc', 'Connecte des serveurs MCP locaux ou distants et expose leurs tools au terminal.');

    if (!mcpData) {
        return renderProviderSettingsGroup(
            title,
            description,
            [],
            `<div class="settings-info">${escapeHtml(t('providers.mcpLoadError', 'Impossible de charger la config MCP : {error}', { error: loadError || 'inconnue' }))}</div>`
        );
    }

    const runtime = mcpData.runtime || {};
    const servers = mcpData.mcp_servers || mcpData.mcpServers || {};
    const templates = mcpData.templates || {};
    const runtimeServers = runtime.servers || {};
    const configuredNames = Object.keys(servers).sort((a, b) => a.localeCompare(b));
    const templateNames = Object.keys(templates).sort((a, b) => a.localeCompare(b));

    const configuredCards = configuredNames.length
        ? configuredNames.map(name => renderMcpConfiguredServerCard(name, servers[name], runtimeServers[name] || null)).join('')
        : `<div class="settings-info">${escapeHtml(t('providers.mcpNoServers', 'Aucun serveur MCP configuré pour l’instant.'))}</div>`;

    const templateCards = templateNames.length
        ? templateNames.map(name => renderMcpTemplateCard(name, templates[name], servers[name] || null)).join('')
        : '';

    const summary = renderMcpRuntimeSummary(mcpData);

    return renderProviderSettingsGroup(
        title,
        description,
        [],
        `
            <div class="mcp-settings-stack">
                ${summary}
                ${renderMcpEditorCard(mcpData)}
                <div class="mcp-card-section">
                    <div class="settings-label">${escapeHtml(t('providers.mcpConfiguredTitle', 'Serveurs configurés'))}</div>
                    <div class="mcp-server-grid">${configuredCards}</div>
                </div>
                <div class="mcp-card-section">
                    <div class="settings-label">${escapeHtml(t('providers.mcpTemplatesTitle', 'Templates rapides'))}</div>
                    <div class="mcp-server-grid">${templateCards}</div>
                </div>
            </div>
        `
    );
}

function parseMcpLineList(raw) {
    return String(raw || '')
        .split(/\r?\n/)
        .map(item => String(item || '').trim())
        .filter(Boolean);
}

function parseMcpKeyValueLines(raw, label) {
    const lines = parseMcpLineList(raw);
    const entries = {};
    for (const line of lines) {
        const separator = line.indexOf('=');
        if (separator <= 0) {
            throw new Error(t('providers.mcpInvalidKeyValue', 'Format invalide dans {label} : {line}', {
                label,
                line,
            }));
        }
        const key = line.slice(0, separator).trim();
        const value = line.slice(separator + 1).trim();
        if (!key) {
            throw new Error(t('providers.mcpInvalidKeyValue', 'Format invalide dans {label} : {line}', {
                label,
                line,
            }));
        }
        entries[key] = value;
    }
    return entries;
}

function formatMcpLineList(items) {
    return Array.isArray(items) ? items.map(item => String(item || '').trim()).filter(Boolean).join('\n') : '';
}

function formatMcpKeyValueLines(items) {
    if (!items || typeof items !== 'object') return '';
    return Object.entries(items)
        .filter(([key]) => String(key || '').trim())
        .map(([key, value]) => `${key}=${value ?? ''}`)
        .join('\n');
}

function setMcpEditorToggleValue(id, value) {
    const toggle = document.getElementById(id);
    if (!toggle) return;
    toggle.classList.toggle('active', value === true);
    toggle.setAttribute('aria-pressed', value === true ? 'true' : 'false');
}

function getMcpEditorToggleValue(id) {
    const toggle = document.getElementById(id);
    return toggle ? toggle.classList.contains('active') : false;
}

function toggleMcpEditorBool(id) {
    setMcpEditorToggleValue(id, !getMcpEditorToggleValue(id));
    updateMcpEditorVisibility();
}

function updateMcpEditorVisibility() {
    const transport = document.getElementById('mcp-editor-transport')?.value || 'stdio';
    const oauthEnabled = getMcpEditorToggleValue('mcp-editor-oauth-enabled');
    document.querySelectorAll('[data-mcp-editor-transport]').forEach(node => {
        const allowed = String(node.getAttribute('data-mcp-editor-transport') || '')
            .split(',')
            .map(item => item.trim())
            .filter(Boolean);
        node.style.display = allowed.includes(transport) ? '' : 'none';
    });
    document.querySelectorAll('[data-mcp-editor-oauth]').forEach(node => {
        node.style.display = oauthEnabled ? '' : 'none';
    });
}

function scrollMcpEditorIntoView() {
    const editor = document.getElementById('mcp-editor-card');
    if (!editor) return;
    editor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderMcpEditorCard(mcpData) {
    return `
        <div class="mcp-card-section">
            <div class="settings-section-heading">
                <div>
                    <div class="settings-label">${escapeHtml(t('providers.mcpEditorTitle', 'Éditeur de serveur MCP'))}</div>
                    <div class="settings-label-desc">${escapeHtml(t('providers.mcpEditorDesc', 'Crée ou modifie un serveur MCP complet sans éditer le JSON à la main.'))}</div>
                </div>
                <button class="settings-action-btn compact subtle" type="button" onclick="resetMcpEditor()">
                    <i data-lucide="plus" aria-hidden="true"></i>
                    <span>${escapeHtml(t('providers.mcpEditorNew', 'Nouveau serveur'))}</span>
                </button>
            </div>
            <div class="settings-card mcp-editor-card" id="mcp-editor-card">
                <div class="settings-card-body">
                    <div class="mcp-editor-grid">
                        <input type="hidden" id="mcp-editor-original-name" value="">
                        <div class="mcp-editor-field">
                            <label class="settings-label" for="mcp-editor-name">${escapeHtml(t('providers.mcpEditorName', 'Nom du serveur'))}</label>
                            <input type="text" id="mcp-editor-name" class="settings-input" placeholder="${escapeHtml(t('providers.mcpEditorNamePlaceholder', 'ex: github'))}" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field">
                            <label class="settings-label" for="mcp-editor-transport">${escapeHtml(t('providers.mcpEditorTransport', 'Transport'))}</label>
                            <select id="mcp-editor-transport" class="settings-select" onchange="updateMcpEditorVisibility()">
                                <option value="stdio">STDIO</option>
                                <option value="http">HTTP</option>
                                <option value="sse">SSE</option>
                            </select>
                        </div>
                        <div class="mcp-editor-field">
                            <label class="settings-label" for="mcp-editor-description">${escapeHtml(t('providers.mcpEditorDescription', 'Description'))}</label>
                            <input type="text" id="mcp-editor-description" class="settings-input" placeholder="${escapeHtml(t('providers.mcpEditorDescriptionPlaceholder', 'Décris brièvement ce que ce serveur expose.'))}" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field mcp-editor-toggle-row">
                            <div>
                                <div class="settings-label">${escapeHtml(t('providers.mcpEditorEnabled', 'Activé'))}</div>
                                <div class="settings-label-desc">${escapeHtml(t('providers.mcpEditorEnabledDesc', 'Désactive-le ici sans le retirer de la config locale.'))}</div>
                            </div>
                            <div class="settings-toggle active" id="mcp-editor-enabled" onclick="toggleMcpEditorBool('mcp-editor-enabled')" aria-pressed="true"></div>
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-transport="stdio">
                            <label class="settings-label" for="mcp-editor-command">${escapeHtml(t('providers.mcpEditorCommand', 'Commande'))}</label>
                            <input type="text" id="mcp-editor-command" class="settings-input" placeholder="npx" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-transport="http,sse">
                            <label class="settings-label" for="mcp-editor-url">${escapeHtml(t('providers.mcpEditorUrl', 'URL'))}</label>
                            <input type="text" id="mcp-editor-url" class="settings-input" placeholder="https://example.com/mcp" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field mcp-editor-field-span" data-mcp-editor-transport="stdio">
                            <label class="settings-label" for="mcp-editor-args">${escapeHtml(t('providers.mcpEditorArgs', 'Arguments'))}</label>
                            <textarea id="mcp-editor-args" class="settings-input mcp-editor-textarea" placeholder="${escapeHtml(t('providers.mcpEditorArgsPlaceholder', 'Un argument par ligne'))}"></textarea>
                        </div>
                        <div class="mcp-editor-field mcp-editor-field-span">
                            <label class="settings-label" for="mcp-editor-env">${escapeHtml(t('providers.mcpEditorEnv', 'Variables d’environnement'))}</label>
                            <textarea id="mcp-editor-env" class="settings-input mcp-editor-textarea" placeholder="${escapeHtml(t('providers.mcpEditorEnvPlaceholder', 'KEY=value une ligne par variable'))}"></textarea>
                        </div>
                        <div class="mcp-editor-field mcp-editor-field-span" data-mcp-editor-transport="http,sse">
                            <label class="settings-label" for="mcp-editor-headers">${escapeHtml(t('providers.mcpEditorHeaders', 'Headers HTTP'))}</label>
                            <textarea id="mcp-editor-headers" class="settings-input mcp-editor-textarea" placeholder="${escapeHtml(t('providers.mcpEditorHeadersPlaceholder', 'Authorization=Bearer ...'))}"></textarea>
                        </div>
                        <div class="mcp-editor-field mcp-editor-toggle-row">
                            <div>
                                <div class="settings-label">${escapeHtml(t('providers.mcpEditorOauth', 'OAuth'))}</div>
                                <div class="settings-label-desc">${escapeHtml(t('providers.mcpEditorOauthDesc', 'Active l’injection de token pour HTTP ou SSE si le serveur le demande.'))}</div>
                            </div>
                            <div class="settings-toggle" id="mcp-editor-oauth-enabled" onclick="toggleMcpEditorBool('mcp-editor-oauth-enabled')" aria-pressed="false"></div>
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-token-url">${escapeHtml(t('providers.mcpEditorOauthTokenUrl', 'Token URL'))}</label>
                            <input type="text" id="mcp-editor-oauth-token-url" class="settings-input" placeholder="https://auth.example.com/oauth/token" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-grant-type">${escapeHtml(t('providers.mcpEditorOauthGrantType', 'Grant type'))}</label>
                            <select id="mcp-editor-oauth-grant-type" class="settings-select">
                                <option value="client_credentials">client_credentials</option>
                                <option value="refresh_token">refresh_token</option>
                            </select>
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-client-id">${escapeHtml(t('providers.mcpEditorOauthClientId', 'Client ID'))}</label>
                            <input type="text" id="mcp-editor-oauth-client-id" class="settings-input" placeholder="$MCP_CLIENT_ID" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-client-secret">${escapeHtml(t('providers.mcpEditorOauthClientSecret', 'Client secret'))}</label>
                            <input type="text" id="mcp-editor-oauth-client-secret" class="settings-input" placeholder="$MCP_CLIENT_SECRET" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-refresh-token">${escapeHtml(t('providers.mcpEditorOauthRefreshToken', 'Refresh token'))}</label>
                            <input type="text" id="mcp-editor-oauth-refresh-token" class="settings-input" placeholder="$MCP_REFRESH_TOKEN" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-scope">${escapeHtml(t('providers.mcpEditorOauthScope', 'Scope'))}</label>
                            <input type="text" id="mcp-editor-oauth-scope" class="settings-input" placeholder="mcp.read" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-audience">${escapeHtml(t('providers.mcpEditorOauthAudience', 'Audience'))}</label>
                            <input type="text" id="mcp-editor-oauth-audience" class="settings-input" placeholder="https://api.example.com" autocomplete="off">
                        </div>
                        <div class="mcp-editor-field mcp-editor-field-span" data-mcp-editor-oauth="true">
                            <label class="settings-label" for="mcp-editor-oauth-extra">${escapeHtml(t('providers.mcpEditorOauthExtra', 'Extra token params'))}</label>
                            <textarea id="mcp-editor-oauth-extra" class="settings-input mcp-editor-textarea" placeholder="${escapeHtml(t('providers.mcpEditorOauthExtraPlaceholder', 'resource=...\ncustom=value'))}"></textarea>
                        </div>
                    </div>
                    <div class="settings-label-desc mcp-editor-help">${escapeHtml(t('providers.mcpEditorHelp', 'Astuce: args, env, headers et extra params se remplissent une ligne par entrée. Exemple: KEY=value.'))}</div>
                    <div class="settings-inline-actions mcp-editor-actions">
                        <button class="settings-action-btn compact subtle" type="button" onclick="resetMcpEditor()">
                            <i data-lucide="rotate-ccw" aria-hidden="true"></i>
                            <span>${escapeHtml(t('providers.mcpEditorReset', 'Réinitialiser'))}</span>
                        </button>
                        <button class="settings-action-btn compact" type="button" onclick="saveMcpEditorServer()">
                            <i data-lucide="save" aria-hidden="true"></i>
                            <span>${escapeHtml(t('providers.mcpEditorSave', 'Enregistrer le serveur'))}</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderMcpRuntimeSummary(mcpData) {
    const runtime = mcpData?.runtime || {};
    const configuredCount = Number(runtime.configured_count || 0);
    const enabledCount = Number(runtime.enabled_count || 0);
    const cachedToolCount = Number(runtime.cached_tool_count || 0);
    const packageAvailable = runtime.package_available !== false;
    const packageState = runtime.package_state || {};
    const missingPackages = Object.entries(packageState)
        .filter(([, available]) => !available)
        .map(([name]) => name);
    const summaryText = packageAvailable
        ? t('providers.mcpSummaryReady', '{configured} serveurs configurés • {enabled} activés • {cached} tools MCP en cache', {
            configured: configuredCount,
            enabled: enabledCount,
            cached: cachedToolCount,
        })
        : t('providers.mcpSummaryMissingPackages', 'Runtime MCP incomplet : {packages}', {
            packages: missingPackages.join(', ') || 'packages manquants',
        });
    const summaryTone = packageAvailable ? 'ok' : 'error';
    const source = mcpData?.active_source || mcpData?.config_path || '~/.joyboy/config.json';
    const loadedTools = Array.isArray(runtime.loaded_tools) ? runtime.loaded_tools : [];
    const toolChips = loadedTools.slice(0, 10).map(tool => (
        `<span class="settings-pack-chip">${escapeHtml(tool.name || '')}</span>`
    )).join('');
    const errorBlock = runtime.last_error
        ? `<div class="mcp-status-line error">${escapeHtml(t('providers.mcpRuntimeError', 'Dernière erreur runtime : {error}', { error: runtime.last_error }))}</div>`
        : '';

    return `
        <div class="llm-provider-summary mcp-runtime-summary">
            <div class="mcp-runtime-summary-head">
                <div class="mcp-status-line ${summaryTone}">${escapeHtml(summaryText)}</div>
                <div class="settings-inline-actions mcp-summary-actions">
                    <button class="settings-action-btn compact subtle" type="button" onclick="copyMcpExtensionsConfig()">
                        <i data-lucide="copy" aria-hidden="true"></i>
                        <span>${escapeHtml(t('providers.mcpCopyDeerflowConfig', 'Copier format DeerFlow'))}</span>
                    </button>
                    <button class="settings-action-btn compact subtle" type="button" onclick="refreshMcpRuntime()">
                        <i data-lucide="refresh-cw" aria-hidden="true"></i>
                        <span>${escapeHtml(t('providers.mcpRefreshRuntime', 'Tester le runtime'))}</span>
                    </button>
                </div>
            </div>
            <div class="settings-label-desc">${escapeHtml(t('providers.mcpConfigSource', 'Config locale : {source}', { source }))}</div>
            ${errorBlock}
            ${toolChips ? `<div class="settings-pack-chip-row mcp-chip-row">${toolChips}</div>` : ''}
        </div>
    `;
}

function summarizeMcpResolvedTarget(serverStatus = {}) {
    const resolved = serverStatus?.resolved || {};
    const transport = String(resolved.transport || serverStatus.transport || '').trim().toUpperCase();
    const command = String(resolved.command || '').trim();
    const url = String(resolved.url || '').trim();
    const args = Array.isArray(resolved.args) ? resolved.args : [];
    if (command) return `${transport} · ${command}${args.length ? ` ${args.join(' ')}` : ''}`.trim();
    if (url) return `${transport} · ${url}`.trim();
    return transport || '';
}

function renderMcpConfiguredServerCard(serverName, serverConfig = {}, serverStatus = null) {
    const safeName = String(serverName || '').trim();
    const nameArg = escapeHtml(JSON.stringify(safeName));
    const enabled = serverConfig.enabled !== false;
    const valid = serverStatus?.valid !== false;
    const loadedToolCount = Number(serverStatus?.loaded_tool_count || 0);
    const loadedTools = Array.isArray(serverStatus?.loaded_tools) ? serverStatus.loaded_tools : [];
    const issues = Array.isArray(serverStatus?.issues) ? serverStatus.issues.filter(Boolean) : [];
    const warnings = Array.isArray(serverStatus?.warnings) ? serverStatus.warnings.filter(Boolean) : [];
    const missingEnv = Array.isArray(serverStatus?.missing_env) ? serverStatus.missing_env.filter(Boolean) : [];
    const summaryTarget = summarizeMcpResolvedTarget(serverStatus || serverConfig);
    const chips = [
        `<span class="settings-pack-chip settings-pack-chip-state ${enabled ? '' : 'is-warning'}">${escapeHtml(enabled ? t('providers.mcpServerEnabled', 'Actif') : t('providers.mcpServerDisabled', 'Désactivé'))}</span>`,
        `<span class="settings-pack-chip">${escapeHtml(String(serverConfig.type || serverStatus?.transport || 'stdio').toUpperCase())}</span>`,
        `<span class="settings-pack-chip ${valid ? '' : 'settings-pack-chip-state is-warning'}">${escapeHtml(valid ? t('providers.mcpServerValid', 'Valide') : t('providers.mcpServerInvalid', 'À corriger'))}</span>`,
        loadedToolCount
            ? `<span class="settings-pack-chip">${escapeHtml(t('providers.mcpServerLoadedTools', '{count} tools chargés', { count: loadedToolCount }))}</span>`
            : `<span class="settings-pack-chip">${escapeHtml(t('providers.mcpServerNoTools', 'Aucun tool chargé'))}</span>`,
    ].filter(Boolean).join('');

    const loadedToolChips = loadedTools.length
        ? `<div class="settings-pack-chip-row mcp-chip-row">${loadedTools.slice(0, 8).map(name => `<span class="settings-pack-chip">${escapeHtml(name)}</span>`).join('')}</div>`
        : '';

    const notes = [
        summaryTarget ? `<div class="mcp-status-line">${escapeHtml(t('providers.mcpResolvedVia', 'Connexion : {summary}', { summary: summaryTarget }))}</div>` : '',
        missingEnv.length ? `<div class="mcp-status-line warning">${escapeHtml(t('providers.mcpServerMissingEnv', 'Variables manquantes : {items}', { items: missingEnv.join(', ') }))}</div>` : '',
        warnings.length ? `<div class="mcp-status-line warning">${escapeHtml(t('providers.mcpServerWarnings', 'À surveiller : {items}', { items: warnings.join(' • ') }))}</div>` : '',
        issues.length ? `<div class="mcp-status-line error">${escapeHtml(t('providers.mcpServerIssues', 'Points à corriger : {items}', { items: issues.join(' • ') }))}</div>` : '',
    ].filter(Boolean).join('');

    return `
        <div class="settings-card mcp-server-card">
            <div class="settings-card-body">
                <div class="mcp-card-copy">
                    <div class="settings-label">${escapeHtml(safeName)}</div>
                    <div class="settings-label-desc">${escapeHtml(serverConfig.description || '')}</div>
                    <div class="settings-pack-chip-row mcp-chip-row">${chips}</div>
                    ${loadedToolChips}
                    ${notes}
                </div>
                <div class="settings-inline-actions">
                    ${renderSettingsIconAction({
                        icon: enabled ? 'pause' : 'play',
                        label: enabled ? t('providers.mcpDisableServer', 'Désactiver') : t('providers.mcpEnableServer', 'Activer'),
                        tooltip: enabled ? t('providers.mcpDisableServer', 'Désactiver') : t('providers.mcpEnableServer', 'Activer'),
                        onClick: `toggleMcpServer(${nameArg}, ${enabled ? 'false' : 'true'})`,
                    })}
                    ${renderSettingsIconAction({
                        icon: 'square-pen',
                        label: t('providers.mcpEditServer', 'Éditer'),
                        tooltip: t('providers.mcpEditServer', 'Éditer'),
                        onClick: `fillMcpEditor(${nameArg})`,
                        classes: 'subtle',
                    })}
                    ${renderSettingsIconAction({
                        icon: 'copy',
                        label: t('providers.mcpCopyConfig', 'Copier JSON'),
                        tooltip: t('providers.mcpCopyConfig', 'Copier JSON'),
                        onClick: `copyMcpServerJson(${nameArg})`,
                        classes: 'subtle',
                    })}
                    ${renderSettingsIconAction({
                        icon: 'trash-2',
                        label: t('providers.mcpRemoveServer', 'Retirer'),
                        tooltip: t('providers.mcpRemoveServer', 'Retirer'),
                        onClick: `removeMcpServer(${nameArg})`,
                        classes: 'subtle',
                    })}
                </div>
            </div>
        </div>
    `;
}

function renderMcpTemplateCard(templateName, templateConfig = {}, existingConfig = null) {
    const safeName = String(templateName || '').trim();
    const nameArg = escapeHtml(JSON.stringify(safeName));
    const existingEnabled = existingConfig && existingConfig.enabled !== false;
    const primaryLabel = existingConfig
        ? (existingEnabled ? t('providers.mcpTemplatesConfigured', 'Déjà configuré') : t('providers.mcpEnableServer', 'Activer'))
        : t('providers.mcpInstallTemplate', 'Ajouter');
    const primaryIcon = existingConfig ? (existingEnabled ? 'check' : 'play') : 'plus';
    const primaryClick = existingConfig
        ? (existingEnabled ? '' : `toggleMcpServer(${nameArg}, true)`)
        : `installMcpTemplate(${nameArg})`;
    const transport = String(templateConfig.type || 'stdio').toUpperCase();

    return `
        <div class="settings-card mcp-template-card">
            <div class="settings-card-body">
                <div class="mcp-card-copy">
                    <div class="settings-label">${escapeHtml(safeName)}</div>
                    <div class="settings-label-desc">${escapeHtml(templateConfig.description || t('providers.mcpTemplateReady', 'Template prêt à copier dans ta config locale.'))}</div>
                    <div class="settings-pack-chip-row mcp-chip-row">
                        <span class="settings-pack-chip">${escapeHtml(transport)}</span>
                        ${existingConfig ? `<span class="settings-pack-chip settings-pack-chip-state">${escapeHtml(t('providers.mcpTemplatesConfigured', 'Déjà configuré'))}</span>` : ''}
                    </div>
                </div>
                <div class="settings-inline-actions">
                    ${renderSettingsIconAction({
                        icon: primaryIcon,
                        label: primaryLabel,
                        tooltip: primaryLabel,
                        onClick: primaryClick || 'void(0)',
                        disabled: Boolean(existingConfig && existingEnabled),
                    })}
                    ${renderSettingsIconAction({
                        icon: 'square-pen',
                        label: t('providers.mcpEditTemplate', 'Charger dans l’éditeur'),
                        tooltip: t('providers.mcpEditTemplate', 'Charger dans l’éditeur'),
                        onClick: `fillMcpEditor(${nameArg}, true)`,
                        classes: 'subtle',
                    })}
                    ${renderSettingsIconAction({
                        icon: 'copy',
                        label: t('providers.mcpCopyConfig', 'Copier JSON'),
                        tooltip: t('providers.mcpCopyConfig', 'Copier JSON'),
                        onClick: `copyMcpServerJson(${nameArg}, true)`,
                        classes: 'subtle',
                    })}
                </div>
            </div>
        </div>
    `;
}

async function fetchMcpConfigSnapshot(options = {}) {
    const result = await apiSettings.getMcpConfig(options);
    if (!result.ok || !result.data?.success) {
        throw new Error(result.data?.error || result.error || t('providers.mcpLoadError', 'Impossible de charger la config MCP : {error}', { error: 'inconnue' }));
    }
    return result.data;
}

function getCurrentMcpSnapshot() {
    return window.joyboyMcpSnapshot || null;
}

function getMcpEditorFormData() {
    return {
        originalName: document.getElementById('mcp-editor-original-name')?.value?.trim() || '',
        name: document.getElementById('mcp-editor-name')?.value?.trim() || '',
        type: document.getElementById('mcp-editor-transport')?.value || 'stdio',
        description: document.getElementById('mcp-editor-description')?.value?.trim() || '',
        enabled: getMcpEditorToggleValue('mcp-editor-enabled'),
        command: document.getElementById('mcp-editor-command')?.value?.trim() || '',
        url: document.getElementById('mcp-editor-url')?.value?.trim() || '',
        args: parseMcpLineList(document.getElementById('mcp-editor-args')?.value || ''),
        env: parseMcpKeyValueLines(document.getElementById('mcp-editor-env')?.value || '', t('providers.mcpEditorEnv', 'Variables d’environnement')),
        headers: parseMcpKeyValueLines(document.getElementById('mcp-editor-headers')?.value || '', t('providers.mcpEditorHeaders', 'Headers HTTP')),
        oauthEnabled: getMcpEditorToggleValue('mcp-editor-oauth-enabled'),
        oauthTokenUrl: document.getElementById('mcp-editor-oauth-token-url')?.value?.trim() || '',
        oauthGrantType: document.getElementById('mcp-editor-oauth-grant-type')?.value || 'client_credentials',
        oauthClientId: document.getElementById('mcp-editor-oauth-client-id')?.value?.trim() || '',
        oauthClientSecret: document.getElementById('mcp-editor-oauth-client-secret')?.value?.trim() || '',
        oauthRefreshToken: document.getElementById('mcp-editor-oauth-refresh-token')?.value?.trim() || '',
        oauthScope: document.getElementById('mcp-editor-oauth-scope')?.value?.trim() || '',
        oauthAudience: document.getElementById('mcp-editor-oauth-audience')?.value?.trim() || '',
        oauthExtra: parseMcpKeyValueLines(document.getElementById('mcp-editor-oauth-extra')?.value || '', t('providers.mcpEditorOauthExtra', 'Extra token params')),
    };
}

function applyMcpEditorData(data = {}, options = {}) {
    const editorData = data && typeof data === 'object' ? data : {};
    const originalName = options.originalName ?? '';
    const setValue = (id, value) => {
        const field = document.getElementById(id);
        if (field) field.value = value;
    };

    setValue('mcp-editor-original-name', originalName);
    setValue('mcp-editor-name', options.name ?? '');
    setValue('mcp-editor-transport', editorData.type || 'stdio');
    setValue('mcp-editor-description', editorData.description || '');
    setMcpEditorToggleValue('mcp-editor-enabled', editorData.enabled !== false);
    setValue('mcp-editor-command', editorData.command || '');
    setValue('mcp-editor-url', editorData.url || '');
    setValue('mcp-editor-args', formatMcpLineList(editorData.args || []));
    setValue('mcp-editor-env', formatMcpKeyValueLines(editorData.env || {}));
    setValue('mcp-editor-headers', formatMcpKeyValueLines(editorData.headers || {}));

    const oauth = editorData.oauth && typeof editorData.oauth === 'object' ? editorData.oauth : null;
    setMcpEditorToggleValue('mcp-editor-oauth-enabled', Boolean(oauth && oauth.enabled !== false));
    setValue('mcp-editor-oauth-token-url', oauth?.token_url || '');
    setValue('mcp-editor-oauth-grant-type', oauth?.grant_type || 'client_credentials');
    setValue('mcp-editor-oauth-client-id', oauth?.client_id || '');
    setValue('mcp-editor-oauth-client-secret', oauth?.client_secret || '');
    setValue('mcp-editor-oauth-refresh-token', oauth?.refresh_token || '');
    setValue('mcp-editor-oauth-scope', oauth?.scope || '');
    setValue('mcp-editor-oauth-audience', oauth?.audience || '');
    setValue('mcp-editor-oauth-extra', formatMcpKeyValueLines(oauth?.extra_token_params || {}));
    updateMcpEditorVisibility();
}

function resetMcpEditor() {
    applyMcpEditorData({}, { name: '', originalName: '' });
    scrollMcpEditorIntoView();
}

function fillMcpEditor(serverName, preferTemplate = false) {
    const snapshot = getCurrentMcpSnapshot();
    if (!snapshot) return;

    const servers = snapshot.mcp_servers || snapshot.mcpServers || {};
    const templates = snapshot.templates || {};
    const source = preferTemplate ? (templates[serverName] || servers[serverName]) : (servers[serverName] || templates[serverName]);
    if (!source) return;

    applyMcpEditorData(source, {
        name: serverName,
        originalName: preferTemplate ? '' : serverName,
    });
    scrollMcpEditorIntoView();
}

async function saveMcpServersConfig(servers) {
    const result = await apiSettings.updateMcpConfig({ mcp_servers: servers });
    if (!result.ok || !result.data?.success) {
        throw new Error(result.data?.error || result.error || t('providers.mcpSaveError', 'Impossible de sauvegarder la config MCP : {error}', { error: 'inconnue' }));
    }
    return result.data;
}

async function saveMcpEditorServer() {
    try {
        const payload = getMcpEditorFormData();
        if (!payload.name) {
            throw new Error(t('providers.mcpEditorNameRequired', 'Donne un nom au serveur MCP avant d’enregistrer.'));
        }
        if (payload.type === 'stdio' && !payload.command) {
            throw new Error(t('providers.mcpEditorCommandRequired', 'Le transport STDIO demande une commande.'));
        }
        if ((payload.type === 'http' || payload.type === 'sse') && !payload.url) {
            throw new Error(t('providers.mcpEditorUrlRequired', 'Le transport HTTP/SSE demande une URL.'));
        }
        if (payload.oauthEnabled && !payload.oauthTokenUrl) {
            throw new Error(t('providers.mcpEditorOauthTokenRequired', 'OAuth activé: token_url requis.'));
        }

        const snapshot = await fetchMcpConfigSnapshot();
        const servers = { ...(snapshot.mcp_servers || snapshot.mcpServers || {}) };
        const cleanServer = {
            enabled: payload.enabled,
            type: payload.type,
            description: payload.description,
            command: payload.type === 'stdio' ? payload.command : '',
            args: payload.type === 'stdio' ? payload.args : [],
            env: payload.env,
            url: payload.type === 'stdio' ? '' : payload.url,
            headers: payload.type === 'stdio' ? {} : payload.headers,
        };

        if (payload.oauthEnabled) {
            cleanServer.oauth = {
                enabled: true,
                token_url: payload.oauthTokenUrl,
                grant_type: payload.oauthGrantType,
                client_id: payload.oauthClientId,
                client_secret: payload.oauthClientSecret,
                refresh_token: payload.oauthRefreshToken,
                scope: payload.oauthScope,
                audience: payload.oauthAudience,
                extra_token_params: payload.oauthExtra,
            };
        }

        if (payload.originalName && payload.originalName !== payload.name) {
            delete servers[payload.originalName];
        }
        servers[payload.name] = cleanServer;

        await saveMcpServersConfig(servers);
        await loadProviderSettings();
        fillMcpEditor(payload.name);
        Toast.success(t('providers.mcpSavedTitle', 'MCP mis à jour'), t('providers.mcpSavedBody', 'La configuration MCP locale a été rafraîchie.'), 2200);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function refreshMcpRuntime(loadTools = true) {
    await loadProviderSettings({ loadMcpTools: loadTools === true });
    Toast.info(t('providers.mcpSavedTitle', 'MCP mis à jour'), t('providers.mcpSavedBody', 'La configuration MCP locale a été rafraîchie.'), 2200);
}

async function installMcpTemplate(templateName) {
    try {
        const snapshot = await fetchMcpConfigSnapshot();
        const servers = { ...(snapshot.mcp_servers || snapshot.mcpServers || {}) };
        const templates = snapshot.templates || {};
        const template = templates[templateName];
        if (!template) {
            throw new Error(t('providers.mcpLoadError', 'Impossible de charger la config MCP : {error}', { error: templateName }));
        }
        if (servers[templateName]) {
            Toast.info(t('providers.mcpSavedTitle', 'MCP mis à jour'), t('providers.mcpTemplateAlreadyExists', '{name} existe déjà dans la config locale.', { name: templateName }), 2200);
            return;
        }

        servers[templateName] = { ...template };
        await saveMcpServersConfig(servers);
        await loadProviderSettings();
        Toast.success(t('providers.mcpAddedTitle', 'Serveur MCP ajouté'), t('providers.mcpAddedBody', '{name} est maintenant dans la config locale.', { name: templateName }), 2200);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function toggleMcpServer(serverName, enabled) {
    try {
        const snapshot = await fetchMcpConfigSnapshot();
        const servers = { ...(snapshot.mcp_servers || snapshot.mcpServers || {}) };
        if (!servers[serverName]) {
            throw new Error(serverName);
        }

        servers[serverName] = {
            ...servers[serverName],
            enabled: enabled === true || enabled === 'true',
        };
        await saveMcpServersConfig(servers);
        await loadProviderSettings();
        Toast.success(t('providers.mcpSavedTitle', 'MCP mis à jour'), t('providers.mcpSavedBody', 'La configuration MCP locale a été rafraîchie.'), 2200);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function removeMcpServer(serverName) {
    const confirmed = await JoyDialog.confirm(
        t('providers.mcpConfirmRemove', 'Retirer le serveur MCP "{name}" de la config locale ?', { name: serverName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    try {
        const snapshot = await fetchMcpConfigSnapshot();
        const servers = { ...(snapshot.mcp_servers || snapshot.mcpServers || {}) };
        delete servers[serverName];
        await saveMcpServersConfig(servers);
        await loadProviderSettings();
        Toast.info(t('providers.mcpRemovedTitle', 'Serveur MCP retiré'), t('providers.mcpRemovedBody', '{name} a été retiré de la config locale.', { name: serverName }), 2200);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function copyMcpServerJson(serverName, preferTemplate = false) {
    try {
        const snapshot = await fetchMcpConfigSnapshot();
        const servers = snapshot.mcp_servers || snapshot.mcpServers || {};
        const templates = snapshot.templates || {};
        const source = preferTemplate ? (templates[serverName] || servers[serverName]) : (servers[serverName] || templates[serverName]);
        if (!source) {
            throw new Error(serverName);
        }

        const text = JSON.stringify({ [serverName]: source }, null, 2);
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }
        Toast.success(t('providers.mcpCopiedTitle', 'JSON copié'), t('providers.mcpCopiedBody', 'Le JSON de {name} est prêt dans le presse-papiers.', { name: serverName }), 2200);
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}

async function copyMcpExtensionsConfig() {
    try {
        const snapshot = await fetchMcpConfigSnapshot();
        const config = snapshot.extensions_config || snapshot.extensionsConfig || { mcpServers: {}, skills: {} };
        const text = JSON.stringify(config, null, 2);
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }
        Toast.success(
            t('providers.mcpCopiedTitle', 'JSON copié'),
            t('providers.mcpCopiedDeerflowBody', 'Le fichier extensions_config.json compatible DeerFlow est prêt dans le presse-papiers.'),
            2200
        );
    } catch (error) {
        Toast.error(t('common.error', 'Erreur'), error.message || String(error));
    }
}
