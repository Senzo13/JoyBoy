// ===== SETTINGS MAINTENANCE PANEL =====
// Backend selector, segmentation cache maintenance, and Cloudflare tunnel controls.

// ===== BACKEND GGUF =====

async function changeBackend(backend) {
    const quantRow = document.getElementById('gguf-quant-row');
    const statusEl = document.getElementById('gguf-status');

    if (backend === 'gguf') {
        if (quantRow) quantRow.style.display = 'flex';
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.innerHTML = `<span style="color:#f59e0b;">${escapeHtml(t('settings.gguf.checking', 'Vérification du backend GGUF...'))}</span>`;
        }

        try {
            const res = await fetch('/api/backend/gguf/status');
            const data = await res.json();

            if (data.available) {
                const inpaintCount = data.local_models?.inpaint?.length || 0;
                const videoCount = data.local_models?.video?.length || 0;
                statusEl.innerHTML = `<span style="color:#22c55e;">${escapeHtml(t('settings.gguf.available', 'GGUF disponible'))}</span><br>
                    <span style="color:#a1a1aa;">${escapeHtml(t('settings.gguf.localModels', 'Modèles locaux : {inpaint} inpaint, {video} vidéo', { inpaint: inpaintCount, video: videoCount }))}</span>`;
            } else {
                statusEl.innerHTML = `<span style="color:#f59e0b;">${escapeHtml(t('settings.gguf.installRequired', 'Installation requise'))}</span><br>
                    <span style="color:#a1a1aa;">${escapeHtml(t('settings.gguf.installFirstUse', 'Le backend GGUF sera installé au premier usage'))}</span>`;
            }
        } catch (e) {
            statusEl.innerHTML = `<span style="color:#ef4444;">${escapeHtml(t('settings.gguf.backendError', 'Erreur connexion backend'))}</span>`;
        }
    } else {
        if (quantRow) quantRow.style.display = 'none';
        if (statusEl) statusEl.style.display = 'none';
    }

    userSettings.backend = backend;
    saveSettings();

    // Rafraîchir le model picker pour afficher les bons modèles
    if (typeof renderModelPickerList === 'function') {
        renderModelPickerList('home');
        renderModelPickerList('chat');
    }

    // Notifier le backend
    try {
        await fetch('/api/backend/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backend })
        });
    } catch (e) {
        console.error('[SETTINGS] Erreur changement backend:', e);
    }
}

function changeGGUFQuant(quant) {
    userSettings.ggufQuant = quant;
    saveSettings();
    console.log(`[SETTINGS] GGUF Quantization -> ${quant}`);
}

function initBackendUI() {
    const backendSelect = document.getElementById('settings-backend');
    const quantSelect = document.getElementById('settings-gguf-quant');

    if (backendSelect && userSettings.backend) {
        backendSelect.value = userSettings.backend;
        if (userSettings.backend === 'gguf') {
            changeBackend('gguf'); // Affiche les options GGUF
        }
    }

    if (quantSelect && userSettings.ggufQuant) {
        quantSelect.value = userSettings.ggufQuant;
    }
}

// ===== SEGMENTATION MAINTENANCE =====

function _segStatusMsg(text, color) {
    const el = document.getElementById('seg-model-status');
    if (el) {
        el.style.display = 'block';
        el.style.color = color || '#a1a1aa';
        el.textContent = text;
    }
}

async function deleteSegModel() {
    const modelName = 'Fusion (B2+B4+SCHP)';
    const confirmed = await JoyDialog.confirm(
        t('settings.segmentation.deleteConfirm', 'Supprimer "{model}" du cache ?', { model: modelName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    const btn = document.getElementById('btn-delete-seg');
    if (btn) btn.textContent = t('settings.segmentation.deleting', 'Suppression...');
    _segStatusMsg(t('settings.segmentation.deleteProgress', 'Suppression en cours...'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/delete', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success(t('settings.segmentation.deleted', 'Supprimé'), data.message);
        } else {
            _segStatusMsg(data.error || t('common.error', 'Erreur'), '#ef4444');
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationDelete', 'Supprimer du cache');
}

async function reinstallSegModel() {
    const modelName = 'Fusion (B2+B4+SCHP)';
    const confirmed = await JoyDialog.confirm(
        t('settings.segmentation.reinstallConfirm', 'Réinstaller "{model}" ? (supprime + retélécharge)', { model: modelName }),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    const btn = document.getElementById('btn-reinstall-seg');
    if (btn) btn.textContent = t('settings.segmentation.reinstalling', 'Réinstallation...');
    _segStatusMsg(t('settings.segmentation.reinstallProgress', 'Suppression + retéléchargement en cours... (peut prendre quelques minutes)'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/reinstall', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success(t('settings.segmentation.reinstalled', 'Réinstallé'), data.message);
        } else {
            _segStatusMsg(data.error || t('common.error', 'Erreur'), '#ef4444');
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationReinstall', 'Réinstaller le modèle');
}

async function verifySegModel() {
    const btn = document.getElementById('btn-verify-seg');
    if (btn) btn.textContent = t('settings.segmentation.verifying', 'Vérification...');
    _segStatusMsg(t('settings.segmentation.verifyProgress', 'Vérification en cours...'), '#f59e0b');

    try {
        const res = await fetch('/api/segformer/verify', { method: 'POST' });
        const data = await res.json();
        if (data.healthy) {
            _segStatusMsg(data.message, '#22c55e');
            if (typeof Toast !== 'undefined') Toast.success('OK', data.message);
        } else {
            const issueText = data.issues?.join(', ') || t('settings.segmentation.issueDetected', 'Problème détecté');
            _segStatusMsg(`${data.label}: ${issueText} — ${data.recommendation}`, '#ef4444');
            if (typeof Toast !== 'undefined') Toast.error(t('settings.segmentation.issueTitle', 'Problème'), issueText);
        }
    } catch (e) {
        _segStatusMsg(t('settings.segmentation.networkError', 'Erreur réseau'), '#ef4444');
    }
    if (btn) btn.textContent = t('settings.generation.segmentationVerify', "Vérifier l'intégrité");
}

// ===== TUNNEL CLOUDFLARE =====

async function toggleTunnel() {
    const toggle = document.getElementById('toggle-tunnel');
    const statusRow = document.getElementById('tunnel-status-row');
    const statusText = document.getElementById('tunnel-status-text');
    const urlRow = document.getElementById('tunnel-url-row');
    const urlInput = document.getElementById('tunnel-url');

    const isActive = toggle.classList.contains('active');

    if (isActive) {
        // Arrêter le tunnel
        toggle.classList.remove('active');
        statusRow.style.display = 'none';
        urlRow.style.display = 'none';
        userSettings.tunnelEnabled = false;
        saveSettings();

        try {
            await fetch('/api/tunnel/stop', { method: 'POST' });
        } catch (e) {
            console.error('[TUNNEL] Erreur stop:', e);
        }
    } else {
        // Démarrer le tunnel
        toggle.classList.add('active');
        statusRow.style.display = 'block';
        statusText.style.color = '#f59e0b';
        statusText.textContent = t('settings.tunnel.starting', 'Téléchargement et démarrage du tunnel...');
        urlRow.style.display = 'none';

        try {
            const res = await fetch('/api/tunnel/start', { method: 'POST' });
            const data = await res.json();

            if (data.success) {
                statusText.style.color = '#22c55e';
                statusText.textContent = t('settings.tunnel.active', 'Tunnel actif');
                urlRow.style.display = 'flex';
                urlInput.value = data.url;
                userSettings.tunnelEnabled = true;
                saveSettings();
            } else {
                statusText.style.color = '#ef4444';
                statusText.textContent = t('settings.tunnel.errorPrefix', 'Erreur : {error}', {
                    error: data.error || t('settings.tunnel.unknown', 'inconnu'),
                });
                toggle.classList.remove('active');
                userSettings.tunnelEnabled = false;
                saveSettings();
            }
        } catch (e) {
            console.error('[TUNNEL] Erreur start:', e);
            statusText.style.color = '#ef4444';
            statusText.textContent = t('settings.tunnel.networkError', 'Erreur réseau');
            toggle.classList.remove('active');
        }
    }
}

async function checkTunnelStatus() {
    try {
        const res = await fetch('/api/tunnel/status');
        const data = await res.json();

        const toggle = document.getElementById('toggle-tunnel');
        const statusRow = document.getElementById('tunnel-status-row');
        const statusText = document.getElementById('tunnel-status-text');
        const urlRow = document.getElementById('tunnel-url-row');
        const urlInput = document.getElementById('tunnel-url');

        if (!toggle) return;

        if (data.running && data.url) {
            toggle.classList.add('active');
            statusRow.style.display = 'block';
            statusText.style.color = '#22c55e';
            statusText.textContent = t('settings.tunnel.active', 'Tunnel actif');
            urlRow.style.display = 'flex';
            urlInput.value = data.url;
        } else {
            toggle.classList.remove('active');
            statusRow.style.display = 'none';
        }
    } catch (e) {
        console.error('[TUNNEL] Erreur check status:', e);
    }
}

function copyTunnelUrl() {
    const urlInput = document.getElementById('tunnel-url');
    if (urlInput && urlInput.value) {
        navigator.clipboard.writeText(urlInput.value).then(() => {
            if (typeof Toast !== 'undefined') {
                Toast.success(
                    t('settings.tunnel.copiedTitle', 'Copié'),
                    t('settings.tunnel.copiedBody', 'URL copiée dans le presse-papier'),
                    2000
                );
            }
        }).catch(() => {
            // Fallback
            urlInput.select();
            document.execCommand('copy');
        });
    }
}
