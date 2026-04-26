// ===== Runtime Console Overlay (F10) =====

(function () {
    let overlay = null;
    let output = null;
    let pollTimer = null;
    let lastSeq = 0;
    let isOpen = false;
    const maxDomLines = 900;

    function escapeConsoleText(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function ensureRuntimeConsoleOverlay() {
        if (overlay) return overlay;

        document.body.insertAdjacentHTML('beforeend', `
            <div id="runtime-console-overlay" class="runtime-console-overlay runtime-console-hidden" aria-hidden="true">
                <section class="runtime-console-panel" role="dialog" aria-modal="true" aria-label="Terminal JoyBoy">
                    <header class="runtime-console-header">
                        <div class="runtime-console-title">
                            <i data-lucide="square-terminal"></i>
                            <span>Terminal JoyBoy</span>
                            <kbd>F10</kbd>
                        </div>
                        <div class="runtime-console-actions">
                            <button type="button" class="runtime-console-icon-btn" id="runtime-console-copy" title="Copier les logs">
                                <i data-lucide="copy"></i>
                            </button>
                            <button type="button" class="runtime-console-icon-btn" id="runtime-console-close" title="Fermer">
                                <i data-lucide="x"></i>
                            </button>
                        </div>
                    </header>
                    <pre id="runtime-console-output" class="runtime-console-output">Connexion au terminal JoyBoy...</pre>
                </section>
            </div>
        `);

        overlay = document.getElementById('runtime-console-overlay');
        output = document.getElementById('runtime-console-output');
        overlay?.addEventListener('click', (event) => {
            if (event.target === overlay) closeRuntimeConsole();
        });
        document.getElementById('runtime-console-close')?.addEventListener('click', closeRuntimeConsole);
        document.getElementById('runtime-console-copy')?.addEventListener('click', copyRuntimeConsole);
        if (window.lucide?.createIcons) window.lucide.createIcons();
        return overlay;
    }

    function appendConsoleEntries(entries = []) {
        if (!output || !entries.length) return;
        const wasNearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 80;
        const html = entries.map((entry) => {
            const ts = String(entry.ts || '').slice(11, 19) || '--:--:--';
            const stream = String(entry.stream || 'log').toUpperCase().slice(0, 6);
            return `<span class="runtime-console-line runtime-console-${stream.toLowerCase()}">[${ts}] [${stream}] ${escapeConsoleText(entry.text)}</span>`;
        }).join('\n');

        if (!output.dataset.ready) {
            output.textContent = '';
            output.dataset.ready = '1';
        }
        output.insertAdjacentHTML('beforeend', `${output.textContent || output.innerHTML ? '\n' : ''}${html}`);

        const lines = output.querySelectorAll('.runtime-console-line');
        if (lines.length > maxDomLines) {
            const removeCount = lines.length - maxDomLines;
            for (let i = 0; i < removeCount; i += 1) lines[i].remove();
        }
        if (wasNearBottom) output.scrollTop = output.scrollHeight;
    }

    async function fetchRuntimeConsole(reset = false) {
        if (!isOpen) return;
        try {
            const after = reset ? 0 : lastSeq;
            const response = await fetch(`/api/runtime-console?after=${after}&limit=400&t=${Date.now()}`, { cache: 'no-store' });
            const data = await response.json();
            if (!data?.success) return;
            lastSeq = data.nextSeq || lastSeq;
            appendConsoleEntries(data.entries || []);
        } catch (error) {
            appendConsoleEntries([{ ts: new Date().toISOString(), stream: 'stderr', text: `Impossible de lire les logs: ${error.message}` }]);
        }
    }

    function openRuntimeConsole() {
        ensureRuntimeConsoleOverlay();
        if (!overlay || !output) return;
        isOpen = true;
        overlay.classList.remove('runtime-console-hidden');
        overlay.setAttribute('aria-hidden', 'false');
        output.dataset.ready = '';
        output.textContent = 'Connexion au terminal JoyBoy...';
        lastSeq = 0;
        fetchRuntimeConsole(true);
        clearInterval(pollTimer);
        pollTimer = setInterval(() => fetchRuntimeConsole(false), 1000);
    }

    function closeRuntimeConsole() {
        isOpen = false;
        clearInterval(pollTimer);
        pollTimer = null;
        overlay?.classList.add('runtime-console-hidden');
        overlay?.setAttribute('aria-hidden', 'true');
    }

    function toggleRuntimeConsole() {
        if (isOpen) closeRuntimeConsole();
        else openRuntimeConsole();
    }

    async function copyRuntimeConsole() {
        const text = output?.innerText || '';
        if (!text.trim()) return;
        try {
            await navigator.clipboard.writeText(text);
            if (typeof Toast !== 'undefined') Toast.success('Logs copiés');
        } catch (error) {
            if (typeof Toast !== 'undefined') Toast.error('Copie impossible');
        }
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'F10') {
            event.preventDefault();
            toggleRuntimeConsole();
        } else if (event.key === 'Escape' && isOpen) {
            closeRuntimeConsole();
        }
    });

    window.openRuntimeConsole = openRuntimeConsole;
    window.closeRuntimeConsole = closeRuntimeConsole;
    window.toggleRuntimeConsole = toggleRuntimeConsole;
})();
