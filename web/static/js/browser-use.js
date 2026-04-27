// ===== BROWSER USE =====
// Local optional browser surface: @browser-use opens a resizable right dock.

const BROWSER_USE_MENTION_RE = /(^|\s)@(browser-use|browser use|browser|iab)\b/i;
const COMPUTER_USE_MENTION_RE = /(^|\s)@(computer-use|computer use|computer|desktop-use|desktop)\b/i;
let browserUseStatus = null;
let browserUseMode = 'browser';
let browserUseResizeState = null;
let browserUseMentionPopover = null;
let browserUseMentionInput = null;
let browserUseInstallPollAbort = 0;
let browserUseCursorTimer = null;
let browserUseActionPollToken = 0;
const BROWSER_USE_MANUAL_ACTIONS = new Set(['click', 'scroll', 'type', 'press', 'back', 'forward', 'reload', 'open']);

function isComputerUseMode() {
    return browserUseMode === 'computer';
}

function browserUseT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function parseBrowserUseMention(text = '') {
    const raw = String(text || '');
    const match = raw.match(BROWSER_USE_MENTION_RE);
    if (!match) return null;
    const cleaned = raw.replace(BROWSER_USE_MENTION_RE, '$1').replace(/\s+/g, ' ').trim();
    return {
        task: cleaned,
        label: match[2],
    };
}

function parseComputerUseMention(text = '') {
    const raw = String(text || '');
    const match = raw.match(COMPUTER_USE_MENTION_RE);
    if (!match) return null;
    const cleaned = raw.replace(COMPUTER_USE_MENTION_RE, '$1').replace(/\s+/g, ' ').trim();
    return {
        task: cleaned,
        label: match[2],
    };
}

function getBrowserUsePanel() {
    return document.getElementById('browser-use-dock');
}

function getBrowserUseViewportSize() {
    const viewport = document.getElementById('browser-use-viewport');
    const rect = viewport?.getBoundingClientRect?.();
    return {
        width: Math.max(640, Math.round(rect?.width || 1180)),
        height: Math.max(420, Math.round(rect?.height || 760)),
    };
}

function getBrowserUseCurrentUrl(defaultLocal = false) {
    if (isComputerUseMode()) return 'computer://desktop';
    const value = String(document.getElementById('browser-use-url')?.value || '').trim();
    return value || (defaultLocal ? 'localhost:3000' : '');
}

function getBrowserUseCurrentTask() {
    return String(document.getElementById('browser-use-command')?.value || '').trim();
}

function getBrowserUseAgentModel() {
    if (typeof currentJoyBoyChatModel === 'function') return currentJoyBoyChatModel();
    if (typeof userSettings !== 'undefined' && userSettings?.chatModel) return String(userSettings.chatModel);
    return 'qwen3.5:2b';
}

function setBrowserUseStatusText(text = '', tone = '') {
    const node = document.getElementById('browser-use-status');
    if (!node) return;
    node.textContent = text;
    node.dataset.tone = tone || '';
}

function setBrowserUseProgress(options = {}) {
    const visible = !!options.visible;
    const percent = Math.max(0, Math.min(100, Number(options.percent || 0)));
    const label = options.label || browserUseT('browserUse.preparing', 'Préparation...');
    const detail = options.detail || '';
    const progress = document.getElementById('browser-use-progress');
    const installProgress = document.getElementById('browser-use-install-progress');
    const fill = document.getElementById('browser-use-progress-fill');
    const installFill = document.getElementById('browser-use-install-progress-fill');
    const labelNode = document.getElementById('browser-use-progress-label');
    const installLabel = document.getElementById('browser-use-install-progress-label');
    const detailNode = document.getElementById('browser-use-progress-detail');
    const installDetail = document.getElementById('browser-use-install-progress-detail');
    const percentNode = document.getElementById('browser-use-progress-percent');

    [progress, installProgress].forEach(node => {
        if (!node) return;
        node.hidden = !visible;
        node.style.setProperty('--browser-use-progress', `${percent}%`);
    });
    [fill, installFill].forEach(node => {
        if (node) node.style.width = `${percent}%`;
    });
    if (labelNode) labelNode.textContent = label;
    if (installLabel) installLabel.textContent = label;
    if (detailNode) detailNode.textContent = detail;
    if (installDetail) installDetail.textContent = detail;
    if (percentNode) percentNode.textContent = `${Math.round(percent)}%`;
}

function renderBrowserUseActionLog(status = {}) {
    const box = document.getElementById('browser-use-action-log');
    const list = document.getElementById('browser-use-action-log-list');
    if (!box || !list) return;

    const steps = Array.isArray(status.agent_steps) ? status.agent_steps : [];
    const rows = steps
        .map(step => String(step || '').trim())
        .filter(Boolean)
        .slice(-8);
    const statusText = String(status.status || '').trim();
    const detailText = String(status.detail || '').trim();
    if (!rows.length && (statusText || detailText)) {
        rows.push([statusText, detailText].filter(Boolean).join(' - '));
    }

    if (!rows.length) {
        box.hidden = true;
        list.innerHTML = '';
        return;
    }

    box.hidden = false;
    const baseIndex = Math.max(1, steps.length - rows.length + 1);
    list.innerHTML = rows.map((row, index) => `
        <div class="browser-use-log-row">
            <span class="browser-use-log-index">${baseIndex + index}</span>
            <span class="browser-use-log-text" title="${escapeHtml(row)}">${escapeHtml(row)}</span>
        </div>
    `).join('');
    list.scrollTop = list.scrollHeight;
}

function clearBrowserUseActionLog() {
    const box = document.getElementById('browser-use-action-log');
    const list = document.getElementById('browser-use-action-log-list');
    if (list) list.innerHTML = '';
    if (box) box.hidden = true;
}

function renderBrowserUseProgressFromStatus(status = browserUseStatus) {
    const install = status?.install || {};
    const installPrefix = isComputerUseMode() ? 'computerUse' : 'browserUse';
    if (install.active || (install.complete && !install.success)) {
        setBrowserUseProgress({
            visible: true,
            percent: install.progress || 4,
            label: install.step || browserUseT(`${installPrefix}.installing`, 'Installation du runtime local...'),
            detail: install.detail || install.error || browserUseT(`${installPrefix}.installDetail`, 'Préparation du runtime local...'),
        });
    } else {
        setBrowserUseProgress({ visible: false });
    }
    renderBrowserUseActionLog(status || {});
}

function setBrowserUseBusy(busy = false) {
    const panel = getBrowserUsePanel();
    panel?.classList.toggle('is-busy', !!busy);
    const installing = !!browserUseStatus?.install?.active;
    document.querySelectorAll('[data-browser-use-action]').forEach(btn => {
        btn.disabled = installing;
    });
}

function renderBrowserUseShot(data = {}) {
    const img = document.getElementById('browser-use-shot');
    const empty = document.getElementById('browser-use-empty');
    const urlInput = document.getElementById('browser-use-url');
    const title = document.getElementById('browser-use-title');
    if (urlInput && data.url) urlInput.value = data.url;
    if (title) title.textContent = data.title || browserUseT('browserUse.panelTitle', 'Browser Use');
    if (img && data.screenshot) {
        img.src = data.screenshot;
        img.style.display = 'block';
        if (empty) empty.style.display = 'none';
        const paintCursor = () => renderBrowserUseCursor(data.cursor);
        if (img.complete) requestAnimationFrame(paintCursor);
        else img.onload = paintCursor;
    }
}

function renderBrowserUseCursor(cursor = null) {
    const viewport = document.getElementById('browser-use-viewport');
    const img = document.getElementById('browser-use-shot');
    if (!viewport || !img || !cursor || !Number.isFinite(Number(cursor.x)) || !Number.isFinite(Number(cursor.y))) return;

    let node = document.getElementById('browser-use-cursor');
    if (!node) {
        node = document.createElement('div');
        node.id = 'browser-use-cursor';
        node.className = 'browser-use-cursor';
        viewport.appendChild(node);
    }

    const x = (Number(cursor.x) / Math.max(1, img.naturalWidth || img.width)) * img.clientWidth + img.offsetLeft;
    const y = (Number(cursor.y) / Math.max(1, img.naturalHeight || img.height)) * img.clientHeight + img.offsetTop;
    node.style.left = `${Math.round(x)}px`;
    node.style.top = `${Math.round(y)}px`;
    node.classList.add('is-visible', 'is-clicking');
    clearTimeout(browserUseCursorTimer);
    browserUseCursorTimer = setTimeout(() => node?.classList.remove('is-clicking'), 420);
}

function renderBrowserUseInstallState(status = browserUseStatus) {
    const panel = getBrowserUsePanel();
    const install = document.getElementById('browser-use-install');
    const tools = document.getElementById('browser-use-tools');
    const installed = isComputerUseMode() ? !!status?.usable : !!status?.playwright_installed;
    const installing = !!status?.install?.active;
    panel?.classList.toggle('is-installed', installed);
    panel?.classList.toggle('is-installing', installing);
    if (install) install.style.display = (installed && !installing) ? 'none' : '';
    if (tools) tools.style.display = installed ? '' : 'none';
    const error = String(status?.error || '').trim();
    setBrowserUseStatusText(
        error && !installing
            ? error
            : installing
            ? (status?.install?.step || browserUseT(isComputerUseMode() ? 'computerUse.installing' : 'browserUse.installing', 'Installation du runtime local...'))
            : installed
            ? browserUseT(isComputerUseMode() ? 'computerUse.ready' : 'browserUse.ready', 'Runtime prêt')
            : browserUseT(isComputerUseMode() ? 'computerUse.missing' : 'browserUse.missing', 'Runtime à installer'),
        error && !installing ? 'error' : installing ? 'warn' : installed ? 'ok' : 'warn'
    );
    renderBrowserUseProgressFromStatus(status);
    setBrowserUseBusy(false);
}

async function refreshBrowserUseStatus() {
    try {
        const result = isComputerUseMode()
            ? await apiSettings.getComputerUseStatus()
            : await apiSettings.getBrowserUseStatus();
        const data = result.data || {};
        if (!result.ok || data.success === false) {
            browserUseStatus = {
                ...data,
                success: false,
                usable: false,
                error: data.error || result.error || browserUseT(isComputerUseMode() ? 'computerUse.missing' : 'browserUse.missing', 'Runtime indisponible'),
            };
            if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
            else window.joyboyBrowserUseStatus = browserUseStatus;
            renderBrowserUseInstallState(browserUseStatus);
            return browserUseStatus;
        }
        browserUseStatus = data;
        if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
        else window.joyboyBrowserUseStatus = browserUseStatus;
        renderBrowserUseInstallState(browserUseStatus);
        return browserUseStatus;
    } catch (error) {
        browserUseStatus = { success: false, usable: false, error: error.message };
        renderBrowserUseInstallState(browserUseStatus);
        return browserUseStatus;
    }
}

function setBrowserUseMode(mode = 'browser') {
    browserUseMode = mode === 'computer' ? 'computer' : 'browser';
    const panel = getBrowserUsePanel();
    panel?.classList.toggle('is-computer-use', isComputerUseMode());

    const name = panel?.querySelector('.browser-use-name');
    const subtitle = document.getElementById('browser-use-title');
    const logo = panel?.querySelector('.browser-use-logo');
    const toolbar = panel?.querySelector('.browser-use-toolbar');
    const installTitle = panel?.querySelector('#browser-use-install h3');
    const installBody = panel?.querySelector('#browser-use-install p');
    const installAction = panel?.querySelector('[data-browser-use-action="install"]');
    const installButton = installAction?.querySelector('span');
    const emptyTitle = panel?.querySelector('#browser-use-empty strong');
    const emptyBody = panel?.querySelector('#browser-use-empty span');
    const emptyIcon = panel?.querySelector('.browser-use-empty-icon');
    const command = document.getElementById('browser-use-command');
    const sendAction = panel?.querySelector('[data-browser-use-action="task"]');
    const hint = panel?.querySelector('.browser-use-hint span');
    const prefix = isComputerUseMode() ? 'computerUse' : 'browserUse';
    const textFor = (key, fallback) => browserUseT(`${prefix}.${key}`, fallback);
    const setTranslatedText = (node, key, fallback) => {
        if (!node) return;
        node.setAttribute('data-i18n', `${prefix}.${key}`);
        node.textContent = textFor(key, fallback);
    };

    setTranslatedText(name, 'title', isComputerUseMode() ? 'Computer Use' : 'Browser Use');
    setTranslatedText(subtitle, 'subtitle', isComputerUseMode() ? 'Contrôle local de l’ordinateur' : 'Navigateur local pilotable par JoyBoy');
    if (logo) logo.innerHTML = `<i data-lucide="${isComputerUseMode() ? 'monitor' : 'mouse-pointer-click'}"></i>`;
    if (toolbar) toolbar.style.display = isComputerUseMode() ? 'none' : '';
    if (installAction) installAction.setAttribute('data-i18n-tooltip', `${prefix}.installTooltip`);
    setTranslatedText(installTitle, 'installTitle', isComputerUseMode() ? 'Installer le runtime desktop' : 'Installer le runtime navigateur');
    setTranslatedText(installBody, 'installBody', isComputerUseMode() ? 'JoyBoy installe pyautogui, Pillow et mss localement pour capturer l’écran et piloter souris/clavier.' : 'JoyBoy installe Playwright et Chromium localement. Rien n’est committé dans le repo.');
    setTranslatedText(installButton, 'installButton', 'Installer');
    setTranslatedText(emptyTitle, 'emptyTitle', isComputerUseMode() ? 'Prêt à capturer le desktop' : 'Prêt à ouvrir une page');
    setTranslatedText(emptyBody, 'emptyBody', isComputerUseMode() ? 'Tape @computer-use dans le chat, puis clique dans la capture pour piloter l’ordinateur.' : 'Tape @browser-use dans le chat, colle une URL, ou clique sur une capture pour piloter la page.');
    if (emptyIcon) emptyIcon.innerHTML = `<i data-lucide="${isComputerUseMode() ? 'monitor' : 'mouse-pointer-click'}"></i>`;
    if (command) {
        command.setAttribute('data-i18n', `${prefix}.commandPlaceholder`);
        command.setAttribute('data-i18n-attr', 'placeholder');
        command.placeholder = textFor('commandPlaceholder', isComputerUseMode() ? 'Ex : clique ici, tape ce texte, appuie sur enter' : 'Ex : ouvre localhost:3000 et vérifie le bouton principal');
    }
    if (sendAction) sendAction.setAttribute('data-i18n-tooltip', `${prefix}.sendTooltip`);
    setTranslatedText(hint, 'hint', isComputerUseMode() ? 'Clique dans la capture pour cliquer l’ordinateur. Molette pour scroller.' : 'Clique dans la capture pour cliquer la page. Molette pour scroller.');
    if (window.lucide && panel) lucide.createIcons({ nodes: [panel] });
}

function openBrowserUsePanel(options = {}) {
    const panel = getBrowserUsePanel();
    if (!panel) return;
    const mode = options.mode || 'browser';
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('browser-use-open');
    if (options.task) {
        const input = document.getElementById('browser-use-command');
        if (input) input.value = options.task;
    }
    window.JoyBoyI18n?.applyTranslations?.(panel);
    setBrowserUseMode(mode);
    refreshBrowserUseStatus();
    if (window.lucide) lucide.createIcons({ nodes: [panel] });
    window.JoyTooltip?.rescan?.(panel);
}

function closeBrowserUsePanel() {
    const panel = getBrowserUsePanel();
    if (!panel) return;
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('browser-use-open');
}

async function pollBrowserUseInstallUntilDone(token) {
    const started = Date.now();
    let lastStatus = browserUseStatus;
    while (browserUseInstallPollAbort === token && Date.now() - started < 20 * 60 * 1000) {
        await new Promise(resolve => setTimeout(resolve, 1200));
        lastStatus = await refreshBrowserUseStatus();
        const install = lastStatus?.install || {};
        if (!install.active) return lastStatus;
    }
    return lastStatus || browserUseStatus;
}

async function installBrowserUseRuntime(includeAgent = false, options = {}) {
    const token = Date.now();
    browserUseInstallPollAbort = token;
    const taskAfterInstall = String(options.afterTask || (options.afterCurrent ? getBrowserUseCurrentTask() : '') || '').trim();
    setBrowserUseBusy(true);
    setBrowserUseStatusText(browserUseT(isComputerUseMode() ? 'computerUse.installing' : 'browserUse.installing', 'Installation du runtime local...'), 'warn');
    setBrowserUseProgress({
        visible: true,
        percent: 2,
        label: browserUseT(isComputerUseMode() ? 'computerUse.installing' : 'browserUse.installing', 'Installation du runtime local...'),
        detail: browserUseT(isComputerUseMode() ? 'computerUse.installDetail' : 'browserUse.installDetail', 'Préparation du runtime local...'),
    });
    try {
        const result = isComputerUseMode()
            ? await apiSettings.installComputerUse({ background: true })
            : await apiSettings.installBrowserUse({ include_agent: includeAgent, background: true });
        browserUseStatus = result.data || {};
        if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
        else window.joyboyBrowserUseStatus = browserUseStatus;
        if (!result.ok || !browserUseStatus.success) throw new Error(browserUseStatus.error || result.error || 'install failed');
        renderBrowserUseInstallState(browserUseStatus);
        browserUseStatus = await pollBrowserUseInstallUntilDone(token);
        if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
        else window.joyboyBrowserUseStatus = browserUseStatus;
        const install = browserUseStatus?.install || {};
        if (install.complete && !install.success) {
            throw new Error(install.error || browserUseT(isComputerUseMode() ? 'computerUse.installFailed' : 'browserUse.installFailed', 'Installation échouée'));
        }
        await refreshBrowserUseStatus();
        renderBrowserUseInstallState(browserUseStatus);
        Toast.success(browserUseT(isComputerUseMode() ? 'computerUse.title' : 'browserUse.title', 'Browser Use'), browserUseT(isComputerUseMode() ? 'computerUse.installDone' : 'browserUse.installDone', 'Runtime installé.'));
        if (taskAfterInstall) {
            setBrowserUseStatusText(browserUseT(isComputerUseMode() ? 'computerUse.runningQueuedTask' : 'browserUse.runningQueuedTask', 'Lancement de la demande...'), 'warn');
            return await browserUseAction('task', { task: taskAfterInstall, url: getBrowserUseCurrentUrl(false) });
        }
        const currentUrl = getBrowserUseCurrentUrl(true);
        if (options.afterCurrent && currentUrl) {
            return await browserUseAction('open', { url: currentUrl });
        }
        return browserUseStatus;
    } catch (error) {
        const titleKey = isComputerUseMode() ? 'computerUse.title' : 'browserUse.title';
        setBrowserUseStatusText(error.message || browserUseT(isComputerUseMode() ? 'computerUse.installFailed' : 'browserUse.installFailed', 'Installation échouée'), 'error');
        Toast.error(browserUseT(titleKey, isComputerUseMode() ? 'Computer Use' : 'Browser Use'), error.message || String(error));
        throw error;
    } finally {
        if (browserUseInstallPollAbort === token) browserUseInstallPollAbort = 0;
        setBrowserUseBusy(false);
        renderBrowserUseProgressFromStatus(browserUseStatus);
        if (typeof refreshExtensionsCatalog === 'function') refreshExtensionsCatalog(false);
    }
}

async function browserUseAction(action, payload = {}) {
    const actionName = String(action || '').toLowerCase();
    if (browserUseActionPollToken && BROWSER_USE_MANUAL_ACTIONS.has(actionName)) {
        try {
            if (isComputerUseMode()) await apiSettings.computerUseAction('cancel', {});
            else await apiSettings.browserUseAction('cancel', {});
        } catch (error) {
            // Best effort: the manual action will still be queued if the agent is finishing.
        }
    }
    const token = Date.now();
    browserUseActionPollToken = token;
    setBrowserUseBusy(true);
    setBrowserUseStatusText(browserUseT(isComputerUseMode() ? 'computerUse.running' : 'browserUse.running', isComputerUseMode() ? 'Contrôle en cours...' : 'Navigation en cours...'), 'warn');
    setBrowserUseProgress({
        visible: true,
        percent: 35,
        label: browserUseT(isComputerUseMode() ? 'computerUse.running' : 'browserUse.running', isComputerUseMode() ? 'Contrôle en cours...' : 'Navigation en cours...'),
        detail: payload.url || payload.task || browserUseT(isComputerUseMode() ? 'computerUse.capturing' : 'browserUse.capturing', isComputerUseMode() ? 'Capture de l’écran...' : 'Capture de la page...'),
    });
    renderBrowserUseActionLog({
        status: browserUseT(isComputerUseMode() ? 'computerUse.running' : 'browserUse.running', isComputerUseMode() ? 'Contrôle en cours...' : 'Navigation en cours...'),
        detail: payload.url || payload.task || '',
        agent_steps: [],
    });
    pollBrowserUseLiveUntilDone(token);
    try {
        const size = getBrowserUseViewportSize();
        const modelPayload = payload.model ? {} : { model: getBrowserUseAgentModel() };
        const runtimePayload = {
            ...payload,
            ...modelPayload,
            ...size,
            max_steps: Object.prototype.hasOwnProperty.call(payload, 'max_steps') ? payload.max_steps : (actionName === 'task' ? 0 : undefined),
        };
        const result = isComputerUseMode()
            ? await apiSettings.computerUseAction(action, runtimePayload)
            : await apiSettings.browserUseAction(action, runtimePayload);
        const data = result.data || {};
        if (data.screenshot) renderBrowserUseShot(data);
        renderBrowserUseActionLog(data);
        if (!result.ok || !data.success) throw new Error(data.error || result.error || (isComputerUseMode() ? 'Computer Use error' : 'Browser Use error'));
        browserUseStatus = { ...(browserUseStatus || {}), running: true, url: data.url, title: data.title, playwright_installed: !isComputerUseMode() || browserUseStatus?.playwright_installed, usable: true };
        if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
        else window.joyboyBrowserUseStatus = browserUseStatus;
        setBrowserUseStatusText(data.title || browserUseT(isComputerUseMode() ? 'computerUse.ready' : 'browserUse.ready', 'Runtime prêt'), 'ok');
        setBrowserUseProgress({ visible: false });
        return data;
    } catch (error) {
        setBrowserUseStatusText(error.message || String(error), 'error');
        setBrowserUseProgress({ visible: false });
        throw error;
    } finally {
        if (browserUseActionPollToken === token) browserUseActionPollToken = 0;
        setBrowserUseBusy(false);
    }
}

async function cancelBrowserUseAction() {
    browserUseActionPollToken = 0;
    setBrowserUseStatusText(browserUseT(isComputerUseMode() ? 'computerUse.interrupting' : 'browserUse.interrupting', 'Interruption...'), 'warn');
    try {
        if (isComputerUseMode()) await apiSettings.computerUseAction('cancel', {});
        else await apiSettings.browserUseAction('cancel', {});
        setBrowserUseProgress({ visible: false });
    } catch (error) {
        Toast.error(browserUseT(isComputerUseMode() ? 'computerUse.title' : 'browserUse.title', isComputerUseMode() ? 'Computer Use' : 'Browser Use'), error.message || String(error));
    } finally {
        setBrowserUseBusy(false);
    }
}

async function pollBrowserUseLiveUntilDone(token) {
    let lastProgress = 35;
    while (browserUseActionPollToken === token) {
        await new Promise(resolve => setTimeout(resolve, 550));
        if (browserUseActionPollToken !== token) break;
        try {
            const result = isComputerUseMode()
                ? await apiSettings.getComputerUseStatus()
                : await apiSettings.getBrowserUseStatus();
            const data = result.data || {};
            if (!result.ok || !data.success) continue;
            browserUseStatus = { ...(browserUseStatus || {}), ...data };
            if (isComputerUseMode()) window.joyboyComputerUseStatus = browserUseStatus;
            else window.joyboyBrowserUseStatus = browserUseStatus;
            if (data.screenshot) renderBrowserUseShot(data);
            renderBrowserUseActionLog(data);
            const progress = Number.isFinite(Number(data.progress))
                ? Math.max(lastProgress, Math.min(98, Number(data.progress)))
                : Math.min(98, lastProgress + 2);
            lastProgress = progress;
            setBrowserUseStatusText(data.status || data.title || browserUseT(isComputerUseMode() ? 'computerUse.running' : 'browserUse.running', isComputerUseMode() ? 'Contrôle en cours...' : 'Navigation en cours...'), data.action_active ? 'warn' : 'ok');
            setBrowserUseProgress({
                visible: true,
                percent: progress,
                label: data.status || browserUseT(isComputerUseMode() ? 'computerUse.running' : 'browserUse.running', isComputerUseMode() ? 'Contrôle en cours...' : 'Navigation en cours...'),
                detail: data.detail || data.url || data.task || browserUseT(isComputerUseMode() ? 'computerUse.capturing' : 'browserUse.capturing', isComputerUseMode() ? 'Capture de l’écran...' : 'Capture de la page...'),
            });
        } catch (error) {
            // Polling is only for live preview; the main action request owns errors.
        }
    }
}

async function runBrowserUseTask(task = '') {
    openBrowserUsePanel({ task, mode: 'browser' });
    const status = await refreshBrowserUseStatus();
    if (!status?.playwright_installed) {
        setBrowserUseStatusText(browserUseT('browserUse.needInstallForTask', 'Installe Browser Use pour lancer cette demande.'), 'warn');
        return await installBrowserUseRuntime(false, { afterTask: task });
    }
    return await browserUseAction('task', { task, url: getBrowserUseCurrentUrl(false) });
}

async function runComputerUseTask(task = '') {
    openBrowserUsePanel({ task, mode: 'computer' });
    const status = await refreshBrowserUseStatus();
    if (status?.success === false && status?.error) {
        throw new Error(status.error);
    }
    if (!status?.usable) {
        setBrowserUseStatusText(browserUseT('computerUse.needInstallForTask', 'Installe Computer Use pour lancer cette demande.'), 'warn');
        return await installBrowserUseRuntime(false, { afterTask: task });
    }
    return await browserUseAction(task ? 'task' : 'screenshot', { task });
}

async function submitBrowserUseCommand() {
    const input = document.getElementById('browser-use-command');
    const task = String(input?.value || '').trim();
    if (!task) return;
    try {
        if (isComputerUseMode()) await runComputerUseTask(task);
        else await runBrowserUseTask(task);
    } catch (error) {
        Toast.error(browserUseT(isComputerUseMode() ? 'computerUse.title' : 'browserUse.title', isComputerUseMode() ? 'Computer Use' : 'Browser Use'), error.message || String(error));
    }
}

async function navigateBrowserUseUrl() {
    const input = document.getElementById('browser-use-url');
    const url = String(input?.value || '').trim();
    if (!url) return;
    try {
        const status = await refreshBrowserUseStatus();
        if (!status?.playwright_installed) {
            await installBrowserUseRuntime(false, { afterCurrent: true });
            return;
        }
        await browserUseAction('open', { url });
    } catch (error) {
        Toast.error(browserUseT('browserUse.title', 'Browser Use'), error.message || String(error));
    }
}

function bindBrowserUsePanel() {
    const img = document.getElementById('browser-use-shot');
    img?.addEventListener('click', async event => {
        if (!img.src) return;
        const rect = img.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * img.naturalWidth;
        const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * img.naturalHeight;
        try {
            await browserUseAction('click', { x, y });
        } catch (error) {
            Toast.error(browserUseT(isComputerUseMode() ? 'computerUse.title' : 'browserUse.title', isComputerUseMode() ? 'Computer Use' : 'Browser Use'), error.message || String(error));
        }
    });

    img?.addEventListener('wheel', async event => {
        event.preventDefault();
        try {
            await browserUseAction('scroll', { deltaY: event.deltaY });
        } catch (error) {
            setBrowserUseStatusText(error.message || String(error), 'error');
        }
    }, { passive: false });

    document.getElementById('browser-use-url')?.addEventListener('keydown', event => {
        if (event.key === 'Enter') navigateBrowserUseUrl();
    });
    document.getElementById('browser-use-command')?.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submitBrowserUseCommand();
        }
    });

    const handle = document.getElementById('browser-use-resize');
    handle?.addEventListener('mousedown', event => {
        const panel = getBrowserUsePanel();
        if (!panel) return;
        const rect = panel.getBoundingClientRect();
        browserUseResizeState = {
            startX: event.clientX,
            startWidth: rect.width,
        };
        document.body.classList.add('browser-use-resizing');
        event.preventDefault();
    });

    document.addEventListener('mousemove', event => {
        if (!browserUseResizeState) return;
        const nextWidth = Math.max(360, Math.min(window.innerWidth - 260, browserUseResizeState.startWidth + (browserUseResizeState.startX - event.clientX)));
        getBrowserUsePanel()?.style.setProperty('--browser-use-width', `${Math.round(nextWidth)}px`);
    });
    document.addEventListener('mouseup', () => {
        if (!browserUseResizeState) return;
        browserUseResizeState = null;
        document.body.classList.remove('browser-use-resizing');
    });
}

function buildAutomationUseUserPromptHtml(options = {}) {
    const label = options.label || browserUseT('browserUse.title', 'Browser Use');
    const icon = options.icon || 'mouse-pointer-click';
    const cleanTask = String(options.task || '').trim() || options.fallback || '';
    return `
        <div class="browser-use-chat-request">
            <span class="browser-use-chat-icon"><i data-lucide="${escapeHtml(icon)}"></i></span>
            <span class="browser-use-chat-copy">
                <strong>${escapeHtml(label)}</strong>
                <span>${escapeHtml(cleanTask)}</span>
            </span>
        </div>
    `;
}

function buildBrowserUseUserPromptHtml(task = '') {
    return buildAutomationUseUserPromptHtml({
        label: browserUseT('browserUse.title', 'Browser Use'),
        icon: 'mouse-pointer-click',
        task,
        fallback: browserUseT('browserUse.openPanel', 'Ouvrir le navigateur'),
    });
}

function buildComputerUseUserPromptHtml(task = '') {
    return buildAutomationUseUserPromptHtml({
        label: browserUseT('computerUse.title', 'Computer Use'),
        icon: 'monitor',
        task,
        fallback: browserUseT('computerUse.openPanel', 'Contrôler l’ordinateur'),
    });
}

function addBrowserUseResultMessage(result = {}, task = '') {
    const ok = !!result.success;
    const computerResult = String(result.url || '').startsWith('computer://') || isComputerUseMode();
    const text = ok
        ? (result.answer || browserUseT(computerResult ? 'computerUse.openedResult' : 'browserUse.openedResult', computerResult ? 'Computer Use prêt : {title}' : 'Navigateur ouvert : {title}', { title: result.title || result.url || task || 'OK' }))
        : (result.error || browserUseT(computerResult ? 'computerUse.installHintResult' : 'browserUse.installHintResult', computerResult ? 'Computer Use est prêt dans le panneau droit. Installe le runtime si JoyBoy le demande.' : 'Browser Use est prêt dans le panneau droit. Installe le runtime si JoyBoy le demande.'));
    if (typeof addAiMessageToChat === 'function') {
        addAiMessageToChat(text);
    }
}

async function maybeHandleBrowserUsePromptSubmit(inputOrId) {
    const input = typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    const parsed = parseBrowserUseMention(input?.value || '');
    const computerParsed = parsed ? null : parseComputerUseMention(input?.value || '');
    if (!input || (!parsed && !computerParsed)) return false;

    if (computerParsed) {
        const task = computerParsed.task || browserUseT('computerUse.openPanel', 'Contrôler l’ordinateur');
        if (typeof ensureVisibleChatForRequest === 'function') {
            await ensureVisibleChatForRequest({ title: task });
        } else if (typeof showChat === 'function') {
            showChat();
        }
        if (typeof addUserMessageToChat === 'function') {
            addUserMessageToChat(buildComputerUseUserPromptHtml(task), {
                renderedHtml: true,
                fullPrompt: `@computer-use ${task}`,
            });
        }
        if (typeof resetComposerTextarea === 'function') resetComposerTextarea(input);
        try {
            const result = await runComputerUseTask(task);
            addBrowserUseResultMessage(result, task);
        } catch (error) {
            addBrowserUseResultMessage({ success: false, error: error.message }, task);
            Toast.error(browserUseT('computerUse.title', 'Computer Use'), error.message || String(error));
        }
        if (typeof saveCurrentChatHtml === 'function') {
            saveCurrentChatHtml(task, getChatHtmlWithoutSkeleton?.() || '', currentChatId);
        }
        return true;
    }

    const task = parsed.task || browserUseT('browserUse.openPanel', 'Ouvrir le navigateur');
    if (typeof ensureVisibleChatForRequest === 'function') {
        await ensureVisibleChatForRequest({ title: task });
    } else if (typeof showChat === 'function') {
        showChat();
    }
    if (typeof addUserMessageToChat === 'function') {
        addUserMessageToChat(buildBrowserUseUserPromptHtml(task), {
            renderedHtml: true,
            fullPrompt: `@browser-use ${task}`,
        });
    }
    if (typeof resetComposerTextarea === 'function') resetComposerTextarea(input);
    try {
        const result = await runBrowserUseTask(task);
        addBrowserUseResultMessage(result, task);
    } catch (error) {
        addBrowserUseResultMessage({ success: false, error: error.message }, task);
        Toast.error(browserUseT('browserUse.title', 'Browser Use'), error.message || String(error));
    }
    if (typeof saveCurrentChatHtml === 'function') {
        saveCurrentChatHtml(task, getChatHtmlWithoutSkeleton?.() || '', currentChatId);
    }
    return true;
}

function showBrowserUseMentionPopover(input) {
    if (!input) return;
    if (!browserUseMentionPopover) {
        browserUseMentionPopover = document.createElement('div');
        browserUseMentionPopover.className = 'browser-use-mention-popover';
        browserUseMentionPopover.innerHTML = `
            <button type="button" class="browser-use-mention-option" data-mention="@browser-use">
                <span><i data-lucide="mouse-pointer-click"></i></span>
                <strong>Browser Use</strong>
                <small>@browser-use</small>
            </button>
            <button type="button" class="browser-use-mention-option" data-mention="@computer-use">
                <span><i data-lucide="monitor"></i></span>
                <strong>Computer Use</strong>
                <small>@computer-use</small>
            </button>
        `;
        document.body.appendChild(browserUseMentionPopover);
        browserUseMentionPopover.addEventListener('click', event => {
            const button = event.target.closest('[data-mention]');
            if (!button) return;
            const target = browserUseMentionInput;
            if (!target) return;
            const mention = button.dataset.mention || '@browser-use';
            target.value = target.value.replace(/(^|\s)@\S*$/i, `$1${mention} `);
            target.dispatchEvent(new Event('input', { bubbles: true }));
            target.focus();
            hideBrowserUseMentionPopover();
        });
        if (window.lucide) lucide.createIcons({ nodes: [browserUseMentionPopover] });
    }
    browserUseMentionInput = input;
    const rect = input.getBoundingClientRect();
    browserUseMentionPopover.style.left = `${Math.max(12, rect.left)}px`;
    browserUseMentionPopover.style.top = `${Math.max(12, rect.top - 64)}px`;
    browserUseMentionPopover.classList.add('open');
}

function hideBrowserUseMentionPopover() {
    browserUseMentionPopover?.classList.remove('open');
    browserUseMentionInput = null;
}

function maybeShowBrowserUseMentionFromInput(input) {
    const value = String(input?.value || '');
    renderBrowserUseMentionChip(input);
    if (/(^|\s)@(?:b|br|bro|brow|browser|browser-use|iab|c|co|com|computer|computer-use|d|de|desk|desktop|desktop-use)?$/i.test(value)) {
        showBrowserUseMentionPopover(input);
    } else {
        hideBrowserUseMentionPopover();
    }
}

function renderBrowserUseMentionChip(input) {
    if (!input) return;
    const wrapper = input.closest('.prompt-input-wrapper');
    if (!wrapper) return;
    const browserMention = parseBrowserUseMention(input.value || '');
    const computerMention = browserMention ? null : parseComputerUseMention(input.value || '');
    const active = browserMention || computerMention;
    let chip = wrapper.querySelector('.browser-use-mention-chip');
    if (!active) {
        wrapper.classList.remove('has-browser-use-mention');
        chip?.remove();
        return;
    }

    if (!chip) {
        chip = document.createElement('span');
        chip.className = 'browser-use-mention-chip';
        wrapper.insertBefore(chip, input);
    }
    const label = browserMention
        ? '@browser-use'
        : '@computer-use';
    const icon = browserMention ? 'mouse-pointer-click' : 'monitor';
    chip.innerHTML = `<i data-lucide="${icon}"></i><span>${escapeHtml(label)}</span>`;
    wrapper.classList.add('has-browser-use-mention');
    if (window.lucide) lucide.createIcons({ nodes: [chip] });
}

document.addEventListener('DOMContentLoaded', () => {
    bindBrowserUsePanel();
    ['prompt-input', 'chat-prompt'].forEach(id => {
        const input = document.getElementById(id);
        input?.addEventListener('input', () => maybeShowBrowserUseMentionFromInput(input));
        input?.addEventListener('change', () => renderBrowserUseMentionChip(input));
        input?.addEventListener('blur', () => window.setTimeout(hideBrowserUseMentionPopover, 140));
    });
    refreshBrowserUseStatus();
});

window.addEventListener('joyboy:locale-changed', () => {
    setBrowserUseMode(browserUseMode);
    renderBrowserUseInstallState(browserUseStatus);
});

Object.assign(window, {
    openBrowserUsePanel,
    closeBrowserUsePanel,
    refreshBrowserUseStatus,
    installBrowserUseRuntime,
    browserUseAction,
    cancelBrowserUseAction,
    clearBrowserUseActionLog,
    runBrowserUseTask,
    runComputerUseTask,
    submitBrowserUseCommand,
    navigateBrowserUseUrl,
    maybeHandleBrowserUsePromptSubmit,
});
