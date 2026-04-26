// ===== BROWSER USE =====
// Local optional browser surface: @browser-use opens a resizable right dock.

const BROWSER_USE_MENTION_RE = /(^|\s)@(browser-use|browser use|browser|iab)\b/i;
let browserUseStatus = null;
let browserUseResizeState = null;
let browserUseMentionPopover = null;
let browserUseMentionInput = null;

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

function setBrowserUseStatusText(text = '', tone = '') {
    const node = document.getElementById('browser-use-status');
    if (!node) return;
    node.textContent = text;
    node.dataset.tone = tone || '';
}

function setBrowserUseBusy(busy = false) {
    const panel = getBrowserUsePanel();
    panel?.classList.toggle('is-busy', !!busy);
    document.querySelectorAll('[data-browser-use-action]').forEach(btn => {
        if (btn.dataset.browserUseAction !== 'install') btn.disabled = !!busy;
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
    }
}

function renderBrowserUseInstallState(status = browserUseStatus) {
    const panel = getBrowserUsePanel();
    const install = document.getElementById('browser-use-install');
    const tools = document.getElementById('browser-use-tools');
    const installed = !!status?.playwright_installed;
    panel?.classList.toggle('is-installed', installed);
    if (install) install.style.display = installed ? 'none' : '';
    if (tools) tools.style.display = installed ? '' : 'none';
    setBrowserUseStatusText(
        installed
            ? browserUseT('browserUse.ready', 'Runtime prêt')
            : browserUseT('browserUse.missing', 'Runtime à installer'),
        installed ? 'ok' : 'warn'
    );
}

async function refreshBrowserUseStatus() {
    try {
        const result = await apiSettings.getBrowserUseStatus();
        browserUseStatus = result.data || {};
        window.joyboyBrowserUseStatus = browserUseStatus;
        renderBrowserUseInstallState(browserUseStatus);
        return browserUseStatus;
    } catch (error) {
        browserUseStatus = { success: false, usable: false, error: error.message };
        renderBrowserUseInstallState(browserUseStatus);
        return browserUseStatus;
    }
}

function openBrowserUsePanel(options = {}) {
    const panel = getBrowserUsePanel();
    if (!panel) return;
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('browser-use-open');
    if (options.task) {
        const input = document.getElementById('browser-use-command');
        if (input) input.value = options.task;
    }
    refreshBrowserUseStatus();
    if (window.lucide) lucide.createIcons({ nodes: [panel] });
}

function closeBrowserUsePanel() {
    const panel = getBrowserUsePanel();
    if (!panel) return;
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('browser-use-open');
}

async function installBrowserUseRuntime(includeAgent = false) {
    setBrowserUseBusy(true);
    setBrowserUseStatusText(browserUseT('browserUse.installing', 'Installation du navigateur local...'), 'warn');
    try {
        const result = await apiSettings.installBrowserUse({ include_agent: includeAgent });
        browserUseStatus = result.data || {};
        window.joyboyBrowserUseStatus = browserUseStatus;
        if (!result.ok || !browserUseStatus.success) throw new Error(browserUseStatus.error || result.error || 'install failed');
        renderBrowserUseInstallState(browserUseStatus);
        Toast.success(browserUseT('browserUse.title', 'Browser Use'), browserUseT('browserUse.installDone', 'Runtime installé.'));
    } catch (error) {
        setBrowserUseStatusText(error.message || browserUseT('browserUse.installFailed', 'Installation échouée'), 'error');
        Toast.error(browserUseT('browserUse.installFailed', 'Installation échouée'), error.message || String(error));
    } finally {
        setBrowserUseBusy(false);
        if (typeof refreshExtensionsCatalog === 'function') refreshExtensionsCatalog(false);
    }
}

async function browserUseAction(action, payload = {}) {
    setBrowserUseBusy(true);
    setBrowserUseStatusText(browserUseT('browserUse.running', 'Navigation en cours...'), 'warn');
    try {
        const size = getBrowserUseViewportSize();
        const result = await apiSettings.browserUseAction(action, { ...payload, ...size });
        const data = result.data || {};
        if (!result.ok || !data.success) throw new Error(data.error || result.error || 'Browser Use error');
        renderBrowserUseShot(data);
        browserUseStatus = { ...(browserUseStatus || {}), running: true, url: data.url, title: data.title, playwright_installed: true, usable: true };
        window.joyboyBrowserUseStatus = browserUseStatus;
        setBrowserUseStatusText(data.title || browserUseT('browserUse.ready', 'Runtime prêt'), 'ok');
        return data;
    } catch (error) {
        setBrowserUseStatusText(error.message || String(error), 'error');
        throw error;
    } finally {
        setBrowserUseBusy(false);
    }
}

async function runBrowserUseTask(task = '') {
    openBrowserUsePanel({ task });
    const status = await refreshBrowserUseStatus();
    if (!status?.playwright_installed) {
        setBrowserUseStatusText(browserUseT('browserUse.needInstallForTask', 'Installe Browser Use pour lancer cette demande.'), 'warn');
        return { success: false, code: 'runtime_missing' };
    }
    return await browserUseAction('task', { task });
}

async function submitBrowserUseCommand() {
    const input = document.getElementById('browser-use-command');
    const task = String(input?.value || '').trim();
    if (!task) return;
    try {
        await runBrowserUseTask(task);
    } catch (error) {
        Toast.error(browserUseT('browserUse.title', 'Browser Use'), error.message || String(error));
    }
}

async function navigateBrowserUseUrl() {
    const input = document.getElementById('browser-use-url');
    const url = String(input?.value || '').trim();
    if (!url) return;
    try {
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
            Toast.error(browserUseT('browserUse.title', 'Browser Use'), error.message || String(error));
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

function buildBrowserUseUserPromptHtml(task = '') {
    const label = browserUseT('browserUse.title', 'Browser Use');
    const cleanTask = String(task || '').trim() || browserUseT('browserUse.openPanel', 'Ouvrir le navigateur');
    return `
        <div class="browser-use-chat-request">
            <span class="browser-use-chat-icon"><i data-lucide="mouse-pointer-click"></i></span>
            <span class="browser-use-chat-copy">
                <strong>${escapeHtml(label)}</strong>
                <span>${escapeHtml(cleanTask)}</span>
            </span>
        </div>
    `;
}

function addBrowserUseResultMessage(result = {}, task = '') {
    const ok = !!result.success;
    const text = ok
        ? browserUseT('browserUse.openedResult', 'Navigateur ouvert : {title}', { title: result.title || result.url || task || 'OK' })
        : browserUseT('browserUse.installHintResult', 'Browser Use est prêt dans le panneau droit. Installe le runtime si JoyBoy le demande.');
    if (typeof addAiMessageToChat === 'function') {
        addAiMessageToChat(text);
    }
}

async function maybeHandleBrowserUsePromptSubmit(inputOrId) {
    const input = typeof inputOrId === 'string' ? document.getElementById(inputOrId) : inputOrId;
    const parsed = parseBrowserUseMention(input?.value || '');
    if (!input || !parsed) return false;

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
            <button type="button" class="browser-use-mention-option">
                <span><i data-lucide="mouse-pointer-click"></i></span>
                <strong>Browser Use</strong>
                <small>@browser-use</small>
            </button>
        `;
        document.body.appendChild(browserUseMentionPopover);
        browserUseMentionPopover.querySelector('button')?.addEventListener('click', () => {
            const target = browserUseMentionInput;
            if (!target) return;
            target.value = target.value.replace(/(^|\s)@\S*$/i, '$1@browser-use ');
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
    if (/(^|\s)@(?:b|br|bro|brow|browser|browser-use|iab)?$/i.test(value)) {
        showBrowserUseMentionPopover(input);
    } else {
        hideBrowserUseMentionPopover();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    bindBrowserUsePanel();
    ['prompt-input', 'chat-prompt'].forEach(id => {
        const input = document.getElementById(id);
        input?.addEventListener('input', () => maybeShowBrowserUseMentionFromInput(input));
        input?.addEventListener('blur', () => window.setTimeout(hideBrowserUseMentionPopover, 140));
    });
    refreshBrowserUseStatus();
});

window.addEventListener('joyboy:locale-changed', () => {
    renderBrowserUseInstallState(browserUseStatus);
});

Object.assign(window, {
    openBrowserUsePanel,
    closeBrowserUsePanel,
    refreshBrowserUseStatus,
    installBrowserUseRuntime,
    browserUseAction,
    runBrowserUseTask,
    submitBrowserUseCommand,
    navigateBrowserUseUrl,
    maybeHandleBrowserUsePromptSubmit,
});
