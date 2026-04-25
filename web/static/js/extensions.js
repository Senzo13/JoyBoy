// ===== EXTENSIONS CATALOG =====
// Codex-like extension browser for JoyBoy. This is intentionally honest:
// installed states come from native JoyBoy capabilities, local packs, or MCP config.

const JOYBOY_EXTENSION_CATEGORIES = ['featured', 'coding', 'productivity', 'design', 'research'];

const JOYBOY_EXTENSION_CATALOG = [
    {
        id: 'web-research',
        name: 'Web Research',
        icon: 'search-check',
        category: 'featured',
        source: 'native',
        action: 'native',
        developer: 'JoyBoy',
        capabilities: ['web_search', 'web_fetch', 'searxng'],
    },
    {
        id: 'github',
        name: 'GitHub',
        icon: 'github',
        category: 'featured',
        source: 'mcp',
        action: 'mcp-template',
        template: 'github',
        developer: 'Model Context Protocol',
        capabilities: ['repos', 'issues', 'pull_requests', 'ci'],
    },
    {
        id: 'browser-use',
        name: 'Browser Run',
        icon: 'mouse-pointer-click',
        category: 'featured',
        source: 'mcp',
        action: 'mcp-template',
        template: 'cloudflare-browser',
        developer: 'Cloudflare MCP',
        capabilities: ['web_fetch', 'screenshots'],
    },
    {
        id: 'spreadsheets',
        name: 'Spreadsheets',
        icon: 'table-2',
        category: 'featured',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['xlsx', 'csv', 'charts'],
    },
    {
        id: 'presentations',
        name: 'Presentations',
        icon: 'presentation',
        category: 'featured',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['pptx', 'slides', 'export'],
    },
    {
        id: 'documents',
        name: 'Documents',
        icon: 'file-text',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['docx', 'redline', 'comments'],
    },
    {
        id: 'terminal-superpowers',
        name: 'Superpowers',
        icon: 'sparkles',
        category: 'coding',
        source: 'native',
        action: 'native',
        developer: 'JoyBoy',
        capabilities: ['ultrareview', 'subagents', 'safe_write', 'diffs'],
    },
    {
        id: 'local-packs',
        name: 'Local Packs',
        icon: 'package-plus',
        category: 'featured',
        source: 'pack',
        action: 'open-addons',
        developer: 'JoyBoy',
        capabilities: ['routing', 'prompts', 'ui_surfaces'],
    },
    {
        id: 'filesystem',
        name: 'Filesystem MCP',
        icon: 'folder-lock',
        category: 'coding',
        source: 'mcp',
        action: 'mcp-template',
        template: 'filesystem',
        developer: 'Model Context Protocol',
        capabilities: ['allowed_files', 'read_write', 'sandbox'],
    },
    {
        id: 'postgres',
        name: 'Neon / Postgres',
        icon: 'database',
        category: 'coding',
        source: 'mcp',
        action: 'mcp-template',
        template: 'postgres',
        developer: 'Model Context Protocol',
        capabilities: ['sql', 'schema', 'queries'],
    },
    {
        id: 'netlify',
        name: 'Netlify',
        icon: 'network',
        category: 'coding',
        source: 'mcp',
        action: 'mcp-template',
        template: 'netlify',
        developer: 'Netlify MCP',
        capabilities: ['deploys', 'logs', 'forms'],
    },
    {
        id: 'vercel',
        name: 'Vercel',
        icon: 'triangle',
        category: 'coding',
        source: 'mcp',
        action: 'mcp-template',
        template: 'vercel',
        developer: 'Vercel MCP',
        capabilities: ['deploys', 'projects', 'logs'],
    },
    {
        id: 'cloudflare',
        name: 'Cloudflare',
        icon: 'cloud',
        category: 'coding',
        source: 'mcp',
        action: 'mcp-template',
        template: 'cloudflare',
        developer: 'Cloudflare MCP',
        capabilities: ['workers', 'pages', 'dns'],
    },
    {
        id: 'hugging-face',
        name: 'Hugging Face',
        icon: 'badge-smile',
        category: 'coding',
        source: 'provider',
        action: 'open-models',
        developer: 'JoyBoy',
        capabilities: ['models', 'datasets', 'downloads'],
    },
    {
        id: 'code-review',
        name: 'CodeRabbit',
        icon: 'shield-check',
        category: 'coding',
        source: 'native',
        action: 'native',
        developer: 'JoyBoy',
        capabilities: ['ultrareview', 'security', 'quality'],
    },
    {
        id: 'circleci',
        name: 'CircleCI',
        icon: 'circle-dot',
        category: 'coding',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['builds', 'pipelines', 'artifacts'],
    },
    {
        id: 'sentry',
        name: 'Sentry',
        icon: 'activity',
        category: 'coding',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['issues', 'events', 'stacktraces'],
    },
    {
        id: 'build-web-apps',
        name: 'Build Web Apps',
        icon: 'app-window',
        category: 'coding',
        source: 'pack',
        action: 'open-addons',
        developer: 'JoyBoy packs',
        capabilities: ['frontend', 'browser_tests', 'delivery'],
    },
    {
        id: 'game-studio',
        name: 'Game Studio',
        icon: 'gamepad-2',
        category: 'coding',
        source: 'pack',
        action: 'open-addons',
        developer: 'JoyBoy packs',
        capabilities: ['gameplay', 'assets', 'playtests'],
    },
    {
        id: 'expo',
        name: 'Expo',
        icon: 'smartphone',
        category: 'coding',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['react_native', 'mobile', 'builds'],
    },
    {
        id: 'figma',
        name: 'Figma',
        icon: 'figma',
        category: 'design',
        source: 'mcp',
        action: 'mcp-template',
        template: 'figma',
        developer: 'Figma MCP',
        capabilities: ['design_to_code', 'tokens', 'frames'],
    },
    {
        id: 'canva',
        name: 'Canva',
        icon: 'pen-tool',
        category: 'design',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['designs', 'exports', 'brand_assets'],
    },
    {
        id: 'remotion',
        name: 'Remotion',
        icon: 'film',
        category: 'design',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['motion', 'video', 'render'],
    },
    {
        id: 'image-lab',
        name: 'Image Lab',
        icon: 'wand-sparkles',
        category: 'design',
        source: 'native',
        action: 'native',
        developer: 'JoyBoy',
        capabilities: ['inpainting', 'text2img', 'video'],
    },
    {
        id: 'linear',
        name: 'Linear',
        icon: 'list-checks',
        category: 'productivity',
        source: 'mcp',
        action: 'mcp-template',
        template: 'linear',
        developer: 'Linear MCP',
        capabilities: ['issues', 'projects', 'roadmap'],
    },
    {
        id: 'google-drive',
        name: 'Google Drive',
        icon: 'hard-drive',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['files', 'docs', 'sheets'],
    },
    {
        id: 'gmail',
        name: 'Gmail',
        icon: 'mail',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['email', 'drafts', 'triage'],
    },
    {
        id: 'slack',
        name: 'Slack',
        icon: 'message-square',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['channels', 'summaries', 'drafts'],
    },
    {
        id: 'notion',
        name: 'Notion',
        icon: 'notebook-tabs',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['pages', 'databases', 'notes'],
    },
    {
        id: 'stripe',
        name: 'Stripe',
        icon: 'credit-card',
        category: 'productivity',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['payments', 'customers', 'billing'],
    },
    {
        id: 'life-science',
        name: 'Life Science Research',
        icon: 'microscope',
        category: 'research',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['papers', 'evidence', 'synthesis'],
    },
    {
        id: 'finance-research',
        name: 'Market Research',
        icon: 'line-chart',
        category: 'research',
        source: 'planned',
        action: 'coming-soon',
        developer: 'Connector',
        capabilities: ['markets', 'companies', 'news'],
    },
];

let joyboyExtensionsFilter = 'all';
let joyboyExtensionsSearch = '';
let joyboyExtensionsSnapshotLoading = false;
let joyboySelectedExtensionId = null;

function extensionT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    if (typeof t === 'function') return t(key, fallback, params);
    return fallback || key;
}

function extensionEscapeHtml(value) {
    if (typeof escapeHtml === 'function') return escapeHtml(value);
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function extensionSafeIcon(icon) {
    return String(icon || 'plug').replace(/[^a-z0-9-]/gi, '') || 'plug';
}

function extensionCatalogKey(item, field) {
    return `extensions.catalog.${item.id}.${field}`;
}

function extensionDescription(item) {
    return extensionT(extensionCatalogKey(item, 'desc'), item.name);
}

function extensionAbout(item) {
    return extensionT(extensionCatalogKey(item, 'about'), extensionDescription(item));
}

function extensionCategoryLabel(category) {
    return extensionT(`extensions.categories.${category}`, category);
}

function extensionSourceLabel(source) {
    return extensionT(`extensions.sources.${source}`, source);
}

function extensionCapabilityLabel(capability) {
    const clean = String(capability || '').trim();
    if (!clean) return '';
    return extensionT(`extensions.capabilities.${clean}`, clean.replace(/_/g, ' '));
}

function getExtensionsSnapshot() {
    return window.joyboyExtensionMcpSnapshot || window.joyboyMcpSnapshot || null;
}

function getExtensionMcpServers() {
    const snapshot = getExtensionsSnapshot();
    return snapshot?.mcp_servers || snapshot?.mcpServers || {};
}

function getExtensionMcpTemplates() {
    const snapshot = getExtensionsSnapshot();
    return snapshot?.templates || {};
}

function getExtensionRuntime() {
    return getExtensionsSnapshot()?.runtime || {};
}

function getExtensionState(item) {
    const snapshot = getExtensionsSnapshot();
    const servers = getExtensionMcpServers();
    const templates = getExtensionMcpTemplates();
    const server = item.template ? servers[item.template] : null;
    const templateAvailable = item.template ? Boolean(templates[item.template]) : false;

    if (item.action === 'mcp-template') {
        if (!snapshot) {
            return {
                id: 'loading',
                label: extensionT('extensions.status.loading', 'Vérification MCP'),
                icon: 'loader',
                className: 'is-available',
                primaryLabel: extensionT('extensions.status.loading', 'Vérification MCP'),
                primaryDisabled: true,
            };
        }
        if (server && server.enabled !== false) {
            return {
                id: 'installed',
                label: extensionT('extensions.status.installed', 'Installé'),
                icon: 'check',
                className: 'is-installed',
                primaryLabel: extensionT('extensions.actions.openMcp', 'Ouvrir la config MCP'),
                primaryDisabled: false,
            };
        }
        if (server) {
            return {
                id: 'configured',
                label: extensionT('extensions.status.configured', 'Configuré, désactivé'),
                icon: 'play',
                className: 'is-available',
                primaryLabel: extensionT('extensions.actions.enableMcp', 'Activer'),
                primaryDisabled: false,
            };
        }
        if (templateAvailable) {
            return {
                id: 'available',
                label: extensionT('extensions.status.available', 'Disponible'),
                icon: 'plus',
                className: 'is-available',
                primaryLabel: extensionT('extensions.actions.installMcp', 'Ajouter à la config MCP'),
                primaryDisabled: false,
            };
        }
        return {
            id: 'planned',
            label: extensionT('extensions.status.needsTemplate', 'Template manquant'),
            icon: 'lock',
            className: 'is-planned',
            primaryLabel: extensionT('extensions.actions.comingSoon', 'À brancher'),
            primaryDisabled: true,
        };
    }

    if (item.action === 'native') {
        return {
            id: 'installed',
            label: extensionT('extensions.status.included', 'Inclus'),
            icon: 'check',
            className: 'is-installed',
            primaryLabel: extensionT('extensions.actions.included', 'Inclus dans JoyBoy'),
            primaryDisabled: true,
        };
    }

    if (item.action === 'open-addons') {
        return {
            id: 'available',
            label: extensionT('extensions.status.localPack', 'Pack local'),
            icon: 'plus',
            className: 'is-available',
            primaryLabel: extensionT('extensions.actions.openAddons', 'Ouvrir les packs locaux'),
            primaryDisabled: false,
        };
    }

    if (item.action === 'open-models') {
        return {
            id: 'available',
            label: extensionT('extensions.status.provider', 'Provider'),
            icon: 'settings',
            className: 'is-available',
            primaryLabel: extensionT('extensions.actions.openModels', 'Ouvrir les providers'),
            primaryDisabled: false,
        };
    }

    return {
        id: 'planned',
        label: extensionT('extensions.status.planned', 'À brancher'),
        icon: 'plus',
        className: 'is-planned',
        primaryLabel: extensionT('extensions.actions.comingSoon', 'À brancher via MCP custom'),
        primaryDisabled: true,
    };
}

function extensionMatchesFilter(item) {
    const state = getExtensionState(item);
    if (joyboyExtensionsFilter === 'installed') return ['installed', 'configured'].includes(state.id);
    if (joyboyExtensionsFilter === 'available') return ['available'].includes(state.id);
    if (joyboyExtensionsFilter === 'mcp') return item.source === 'mcp';
    if (joyboyExtensionsFilter === 'native') return ['native', 'pack', 'provider'].includes(item.source);
    if (joyboyExtensionsFilter === 'planned') return state.id === 'planned';
    return true;
}

function extensionSearchHaystack(item) {
    return [
        item.name,
        item.id,
        item.category,
        item.source,
        item.developer,
        extensionDescription(item),
        extensionAbout(item),
        ...(Array.isArray(item.capabilities) ? item.capabilities : []),
    ].filter(Boolean).join(' ').toLowerCase();
}

function getVisibleExtensions() {
    const query = String(joyboyExtensionsSearch || '').trim().toLowerCase();
    return JOYBOY_EXTENSION_CATALOG.filter(item => {
        if (!extensionMatchesFilter(item)) return false;
        return !query || extensionSearchHaystack(item).includes(query);
    });
}

function renderExtensionFilterButton(filter, labelKey, fallback) {
    const active = joyboyExtensionsFilter === filter;
    return `
        <button
            class="extensions-filter ${active ? 'active' : ''}"
            type="button"
            data-extension-filter="${extensionEscapeHtml(filter)}"
            onclick="setExtensionsFilter('${extensionEscapeHtml(filter)}')"
        >
            ${extensionEscapeHtml(extensionT(labelKey, fallback))}
        </button>
    `;
}

function renderExtensionsRuntimeSummary() {
    const snapshot = getExtensionsSnapshot();
    const hasSnapshot = Boolean(snapshot);
    const runtime = getExtensionRuntime();
    const servers = getExtensionMcpServers();
    const configured = Number(runtime.configured_count ?? Object.keys(servers).length ?? 0);
    const enabled = Number(runtime.enabled_count ?? Object.values(servers).filter(server => server?.enabled !== false).length ?? 0);
    const tools = Number(runtime.cached_tool_count || 0);
    const templates = Object.keys(getExtensionMcpTemplates()).length;
    const packageAvailable = hasSnapshot && runtime.package_available !== false;
    const packageClass = packageAvailable ? 'is-ok' : 'is-warn';
    const packageText = packageAvailable
        ? extensionT('extensions.runtimeReady', 'Runtime MCP prêt')
        : extensionT('extensions.runtimeMissing', 'Runtime MCP incomplet');

    return `
        <div class="extensions-info-strip">
            <div>
                <div class="extensions-info-title">${extensionEscapeHtml(extensionT('extensions.mcpTitle', 'MCP, c’est quoi ?'))}</div>
                <div class="extensions-info-body">${extensionEscapeHtml(extensionT('extensions.mcpBody', 'MCP est le protocole qui permet à JoyBoy de brancher des outils externes : GitHub, fichiers autorisés, bases de données, services SaaS, etc. Une extension peut aussi être un pack local ou une capacité native.'))}</div>
            </div>
            <div class="extensions-runtime-badges">
                <span class="extension-chip ${packageClass}">${extensionEscapeHtml(packageText)}</span>
                <span class="extension-chip">${extensionEscapeHtml(extensionT('extensions.runtimeServers', '{count} serveurs', { count: configured }))}</span>
                <span class="extension-chip">${extensionEscapeHtml(extensionT('extensions.runtimeEnabled', '{count} actifs', { count: enabled }))}</span>
                <span class="extension-chip">${extensionEscapeHtml(extensionT('extensions.runtimeTools', '{count} tools', { count: tools }))}</span>
                <span class="extension-chip is-muted">${extensionEscapeHtml(extensionT('extensions.runtimeTemplates', '{count} templates', { count: templates }))}</span>
            </div>
        </div>
    `;
}

function renderExtensionCard(item) {
    const state = getExtensionState(item);
    const actionLabel = state.label;
    return `
        <button class="extension-card" type="button" onclick="openExtensionModal('${extensionEscapeHtml(item.id)}')">
            <span class="extension-card-icon" aria-hidden="true">
                <i data-lucide="${extensionSafeIcon(item.icon)}"></i>
            </span>
            <span class="extension-card-copy">
                <span class="extension-card-name">${extensionEscapeHtml(item.name)}</span>
                <span class="extension-card-description">${extensionEscapeHtml(extensionDescription(item))}</span>
            </span>
            <span
                class="extension-card-action ${state.className}"
                title="${extensionEscapeHtml(actionLabel)}"
                aria-label="${extensionEscapeHtml(actionLabel)}"
            >
                <i data-lucide="${extensionSafeIcon(state.icon)}"></i>
            </span>
        </button>
    `;
}

function renderExtensionsSections(items) {
    if (!items.length) {
        return `
            <div class="extensions-empty-state">
                <i data-lucide="search-x" aria-hidden="true"></i>
                <div>
                    <strong>${extensionEscapeHtml(extensionT('extensions.emptyTitle', 'Aucune extension trouvée'))}</strong>
                    <div>${extensionEscapeHtml(extensionT('extensions.emptyBody', 'Essaie un autre filtre ou une autre recherche.'))}</div>
                </div>
            </div>
        `;
    }

    return JOYBOY_EXTENSION_CATEGORIES.map(category => {
        const categoryItems = items.filter(item => item.category === category);
        if (!categoryItems.length) return '';
        return `
            <section class="extensions-section">
                <div class="extensions-section-head">
                    <h2 class="extensions-section-title">${extensionEscapeHtml(extensionCategoryLabel(category))}</h2>
                    <span class="extensions-section-count">${categoryItems.length}</span>
                </div>
                <div class="extensions-grid">
                    ${categoryItems.map(renderExtensionCard).join('')}
                </div>
            </section>
        `;
    }).join('');
}

function renderExtensionsHub() {
    const host = document.getElementById('extensions-view-content');
    if (!host) return;

    const visibleItems = getVisibleExtensions();
    host.innerHTML = `
        <div class="extensions-shell">
            <div class="extensions-hero">
                <div>
                    <div class="extensions-kicker">${extensionEscapeHtml(extensionT('extensions.kicker', 'Extensions'))}</div>
                    <h1 class="extensions-title">${extensionEscapeHtml(extensionT('extensions.title', 'Adapte JoyBoy à tes workflows'))}</h1>
                    <p class="extensions-description">${extensionEscapeHtml(extensionT('extensions.description', 'Installe ou prépare des connecteurs façon Codex : MCP pour les outils externes, packs locaux pour les workflows privés, capacités natives pour ce que JoyBoy sait déjà faire.'))}</p>
                </div>
                <div class="extensions-hero-actions">
                    <button class="settings-action-btn compact subtle" type="button" onclick="openModelsHub()">
                        <i data-lucide="key-round" aria-hidden="true"></i>
                        <span>${extensionEscapeHtml(extensionT('extensions.providersButton', 'Providers'))}</span>
                    </button>
                    <button class="settings-action-btn compact" type="button" onclick="refreshExtensionsCatalog(true)">
                        <i data-lucide="refresh-cw" aria-hidden="true"></i>
                        <span>${extensionEscapeHtml(extensionT('extensions.refresh', 'Rafraîchir'))}</span>
                    </button>
                </div>
            </div>

            <div class="extensions-toolbar">
                <label class="extensions-search">
                    <i data-lucide="search" aria-hidden="true"></i>
                    <input
                        id="extensions-search-input"
                        type="search"
                        value="${extensionEscapeHtml(joyboyExtensionsSearch)}"
                        placeholder="${extensionEscapeHtml(extensionT('extensions.searchPlaceholder', 'Rechercher une extension...'))}"
                        oninput="setExtensionsSearch(this.value)"
                    >
                </label>
                <div class="extensions-filter-row" aria-label="${extensionEscapeHtml(extensionT('extensions.filtersLabel', 'Filtres extensions'))}">
                    ${renderExtensionFilterButton('all', 'extensions.filters.all', 'Tout')}
                    ${renderExtensionFilterButton('installed', 'extensions.filters.installed', 'Installés')}
                    ${renderExtensionFilterButton('available', 'extensions.filters.available', 'Disponibles')}
                    ${renderExtensionFilterButton('mcp', 'extensions.filters.mcp', 'MCP')}
                    ${renderExtensionFilterButton('native', 'extensions.filters.native', 'JoyBoy')}
                    ${renderExtensionFilterButton('planned', 'extensions.filters.planned', 'À brancher')}
                </div>
            </div>

            ${renderExtensionsRuntimeSummary()}
            <div id="extensions-catalog-sections">
                ${renderExtensionsSections(visibleItems)}
            </div>
        </div>
        ${renderExtensionModalShell()}
    `;

    if (window.lucide) lucide.createIcons();
    window.JoyTooltip?.rescan?.(host);
}

function renderExtensionModalShell() {
    return `
        <div class="extension-modal-backdrop" id="extension-modal" aria-hidden="true" onclick="if(event.target === this) closeExtensionModal()">
            <div class="extension-modal-panel" role="dialog" aria-modal="true" aria-labelledby="extension-modal-title">
                <button class="extension-modal-close" type="button" onclick="closeExtensionModal()" aria-label="${extensionEscapeHtml(extensionT('common.close', 'Fermer'))}">
                    <i data-lucide="x"></i>
                </button>
                <div class="extension-modal-body" id="extension-modal-body"></div>
            </div>
        </div>
    `;
}

function getExtensionById(extensionId) {
    return JOYBOY_EXTENSION_CATALOG.find(item => item.id === extensionId) || null;
}

function renderExtensionModalBody(item) {
    const state = getExtensionState(item);
    const developer = item.developer || 'JoyBoy';
    const source = extensionSourceLabel(item.source);
    const capabilities = (Array.isArray(item.capabilities) ? item.capabilities : [])
        .map(capability => `<span class="extension-chip">${extensionEscapeHtml(extensionCapabilityLabel(capability))}</span>`)
        .join('');
    const sourceChips = [
        `<span class="extension-chip">${extensionEscapeHtml(source)}</span>`,
        item.template ? `<span class="extension-chip">MCP: ${extensionEscapeHtml(item.template)}</span>` : '',
        `<span class="extension-chip ${state.id === 'installed' ? 'is-ok' : state.id === 'planned' ? 'is-warn' : ''}">${extensionEscapeHtml(state.label)}</span>`,
    ].filter(Boolean).join('');
    const actionAttr = state.primaryDisabled ? 'disabled aria-disabled="true"' : `onclick="runExtensionPrimaryAction('${extensionEscapeHtml(item.id)}')"`;

    return `
        <div class="extension-modal-identity">
            <div class="extension-modal-icon-row">
                <span class="extension-modal-icon"><i data-lucide="blocks"></i></span>
                <span>•••</span>
                <span class="extension-modal-icon"><i data-lucide="${extensionSafeIcon(item.icon)}"></i></span>
            </div>
            <h2 class="extension-modal-title" id="extension-modal-title">${extensionEscapeHtml(extensionT('extensions.installTitle', 'Installer {name}', { name: item.name }))}</h2>
            <div class="extension-modal-subtitle">${extensionEscapeHtml(extensionT('extensions.developedBy', 'Développé par {developer}', { developer }))}</div>
        </div>
        <div class="extension-modal-card">
            <div class="extension-modal-meta">
                <div><strong>${extensionEscapeHtml(item.name)}</strong> <span class="extension-chip">${extensionEscapeHtml(source)}</span></div>
                <div>${extensionEscapeHtml(extensionT('extensions.categoryLine', 'Catégorie : {category}', { category: extensionCategoryLabel(item.category) }))}</div>
            </div>
            <div class="extension-modal-divider"></div>
            <div class="extension-modal-section">
                <div class="extension-modal-section-title">${extensionEscapeHtml(extensionT('extensions.about', 'À propos'))}</div>
                <div class="extension-modal-about">${extensionEscapeHtml(extensionAbout(item))}</div>
            </div>
            <div class="extension-modal-section">
                <div class="extension-modal-section-title">${extensionEscapeHtml(extensionT('extensions.includes', 'Comprend'))}</div>
                <div class="extension-chip-row">${capabilities || `<span class="extension-chip">${extensionEscapeHtml(extensionT('extensions.noCapabilities', 'Capacités à préciser'))}</span>`}</div>
            </div>
            <div class="extension-modal-section">
                <div class="extension-modal-section-title">${extensionEscapeHtml(extensionT('extensions.access', 'Accès'))}</div>
                <div class="extension-chip-row">${sourceChips}</div>
            </div>
        </div>
        <div class="extension-modal-footer">
            <button class="extension-modal-secondary" type="button" onclick="closeExtensionModal()">${extensionEscapeHtml(extensionT('common.cancel', 'Annuler'))}</button>
            <button class="extension-modal-primary" type="button" ${actionAttr}>${extensionEscapeHtml(state.primaryLabel)}</button>
        </div>
    `;
}

function openExtensionModal(extensionId) {
    const item = getExtensionById(extensionId);
    const modal = document.getElementById('extension-modal');
    const body = document.getElementById('extension-modal-body');
    if (!item || !modal || !body) return;
    joyboySelectedExtensionId = item.id;
    body.innerHTML = renderExtensionModalBody(item);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    if (window.lucide) lucide.createIcons({ nodes: [modal] });
}

function closeExtensionModal() {
    const modal = document.getElementById('extension-modal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    joyboySelectedExtensionId = null;
}

async function runExtensionPrimaryAction(extensionId) {
    const item = getExtensionById(extensionId);
    if (!item) return;
    const state = getExtensionState(item);
    if (state.primaryDisabled) return;

    if (item.action === 'mcp-template' && item.template) {
        const servers = getExtensionMcpServers();
        if (servers[item.template]) {
            if (servers[item.template].enabled === false && typeof toggleMcpServer === 'function') {
                await toggleMcpServer(item.template, true);
            } else {
                closeExtensionModal();
                openModelsHub();
            }
        } else if (typeof installMcpTemplate === 'function') {
            await installMcpTemplate(item.template);
        }
        await refreshExtensionsCatalog(false);
        openExtensionModal(item.id);
        return;
    }

    if (item.action === 'open-addons') {
        closeExtensionModal();
        openAddonsHub();
        return;
    }

    if (item.action === 'open-models') {
        closeExtensionModal();
        openModelsHub();
    }
}

function setExtensionsSearch(value) {
    joyboyExtensionsSearch = String(value || '');
    renderExtensionsHub();
    const input = document.getElementById('extensions-search-input');
    if (input) {
        input.focus();
        const length = input.value.length;
        input.setSelectionRange(length, length);
    }
}

function setExtensionsFilter(filter) {
    joyboyExtensionsFilter = String(filter || 'all');
    renderExtensionsHub();
}

async function refreshExtensionsCatalog(showToast = false) {
    if (joyboyExtensionsSnapshotLoading) return;
    joyboyExtensionsSnapshotLoading = true;
    try {
        if (apiSettings?.getMcpConfig) {
            const result = await apiSettings.getMcpConfig({ loadTools: false });
            if (result.ok && result.data?.success) {
                window.joyboyExtensionMcpSnapshot = result.data;
                window.joyboyMcpSnapshot = result.data;
            } else if (showToast) {
                Toast.error(extensionT('common.error', 'Erreur'), result.data?.error || result.error || extensionT('extensions.refreshError', 'Impossible de rafraîchir MCP'));
            }
        }
        renderExtensionsHub();
        if (showToast) {
            Toast.info(extensionT('extensions.kicker', 'Extensions'), extensionT('extensions.refreshed', 'Catalogue rafraîchi'), 1800);
        }
    } catch (error) {
        if (showToast) {
            Toast.error(extensionT('common.error', 'Erreur'), error.message || String(error));
        }
    } finally {
        joyboyExtensionsSnapshotLoading = false;
    }
}

function hideExtensionsHub() {
    const view = document.getElementById('extensions-view');
    if (view) view.style.display = 'none';
    document.body.classList.remove('extensions-mode');
}

function openExtensionsHub() {
    const view = document.getElementById('extensions-view');
    if (!view) return;

    document.getElementById('settings-modal')?.classList.remove('open');
    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const addonsView = document.getElementById('addons-view');
    const modelsView = document.getElementById('models-view');
    const projectsView = document.getElementById('projects-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (addonsView) addonsView.style.display = 'none';
    if (modelsView) modelsView.style.display = 'none';
    if (typeof hideModulesWorkspaces === 'function') hideModulesWorkspaces();
    if (typeof hideProjectView === 'function') hideProjectView();
    else if (projectsView) projectsView.style.display = 'none';

    view.style.display = 'flex';
    document.body.classList.add('extensions-mode');
    document.body.classList.remove('addons-mode', 'models-mode', 'projects-mode', 'modules-mode', 'signalatlas-mode', 'perfatlas-mode', 'cyberatlas-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById('sidebar-extensions-btn')?.classList.add('active');

    renderExtensionsHub();
    refreshExtensionsCatalog(false);
}

window.addEventListener('joyboy:locale-changed', () => {
    const view = document.getElementById('extensions-view');
    if (view && view.style.display !== 'none') {
        renderExtensionsHub();
    }
});
