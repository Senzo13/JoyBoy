// ===== SETTINGS GALLERY PANEL =====
// Storage gallery rendering, viewer, filters, and destructive gallery actions.

// ===== GALLERY / STORAGE =====

let _galleryFiles = [];
let _galleryFilter = 'all';
let _galleryCurrentItem = null;
let _galleryCurrentList = [];
let _galleryCurrentIndex = -1;
let _galleryStats = null;
let _galleryViewerZoom = 1;

function galleryT(key, params = {}, fallback = '') {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function getGallerySourceLabel(source) {
    const mapping = {
        imagine: galleryT('settings.storage.sourceImagine', {}, 'Générée'),
        modified: galleryT('settings.storage.sourceModified', {}, 'Modifiée'),
        video: galleryT('settings.storage.sourceVideo', {}, 'Vidéo'),
    };
    return mapping[source] || source;
}

function escapeGalleryHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getGalleryModelLabel(file) {
    return file?.model || file?.model_id || file?.metadata?.model || file?.metadata?.model_id || '';
}

function getGalleryPrompt(file) {
    return file?.prompt || file?.metadata?.prompt || file?.final_prompt || file?.metadata?.final_prompt || '';
}

function resetGalleryViewerZoom() {
    _galleryViewerZoom = 1;
    applyGalleryViewerZoom();
}

function applyGalleryViewerZoom(origin = '50% 50%') {
    const stage = document.getElementById('gallery-viewer-stage');
    const media = stage?.querySelector('.gallery-viewer-media');
    const hint = stage?.querySelector('.gallery-viewer-zoom-hint');
    if (!media) return;
    media.style.transform = `scale(${_galleryViewerZoom})`;
    media.style.transformOrigin = origin;
    media.classList.toggle('is-zoomed', _galleryViewerZoom !== 1);
    if (hint) {
        const base = galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer');
        hint.textContent = `${base} · ${Math.round(_galleryViewerZoom * 100)}%`;
    }
}

function handleGalleryViewerWheel(event) {
    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    if (!viewer?.classList.contains('is-open') || !stage?.contains(event.target) || !event.altKey) return;

    event.preventDefault();
    const media = stage.querySelector('.gallery-viewer-media');
    if (!media) return;

    const zoomFactor = event.deltaY < 0 ? 1.12 : 0.88;
    _galleryViewerZoom = Math.min(5, Math.max(0.5, _galleryViewerZoom * zoomFactor));
    if (Math.abs(_galleryViewerZoom - 1) < 0.04) _galleryViewerZoom = 1;

    const rect = media.getBoundingClientRect();
    const originX = rect.width ? ((event.clientX - rect.left) / rect.width) * 100 : 50;
    const originY = rect.height ? ((event.clientY - rect.top) / rect.height) * 100 : 50;
    applyGalleryViewerZoom(`${Math.max(0, Math.min(100, originX))}% ${Math.max(0, Math.min(100, originY))}%`);
}

function renderGalleryStats(stats = null) {
    const statsEl = document.getElementById('gallery-stats');
    if (!statsEl) return;

    if (!stats) {
        statsEl.innerHTML = `
            <div class="gallery-stat-card" style="--gallery-accent: rgba(96,165,250,0.22);">
                <span class="gallery-stat-value">...</span>
                <span class="gallery-stat-label">${galleryT('settings.storage.loading', {}, 'Chargement de la galerie...')}</span>
            </div>
        `;
        return;
    }

    const cards = [
        { value: stats.total, label: galleryT('settings.storage.totalLabel', {}, 'Fichiers'), accent: 'rgba(34,197,94,0.2)' },
        { value: stats.images, label: galleryT('settings.storage.imagesLabel', {}, 'Images'), accent: 'rgba(59,130,246,0.2)' },
        { value: stats.videos, label: galleryT('settings.storage.videosLabel', {}, 'Vidéos'), accent: 'rgba(245,158,11,0.2)' },
        { value: `${stats.total_size_mb} MB`, label: galleryT('settings.storage.sizeLabel', {}, 'Stockage'), accent: 'rgba(168,85,247,0.22)' },
    ];

    statsEl.innerHTML = cards.map(card => `
        <div class="gallery-stat-card" style="--gallery-accent: ${card.accent};">
            <span class="gallery-stat-value">${card.value}</span>
            <span class="gallery-stat-label">${card.label}</span>
        </div>
    `).join('');
}

async function refreshGallery() {
    const gridEl = document.getElementById('gallery-grid');
    const refreshBtn = document.getElementById('gallery-refresh-btn');

    if (!gridEl) return;

    renderGalleryStats();
    if (gridEl) {
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="loader-2" class="spin"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.loading', {}, 'Chargement de la galerie...')}</div>
                <div class="gallery-empty-desc">${galleryT('settings.storage.subtitle', {}, '')}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
    }

    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const resp = await fetch('/api/gallery/list');
        const data = await resp.json();
        _galleryStats = data.stats;
        renderGalleryStats(data.stats);

        _galleryFiles = data.files;
        renderGalleryGrid();

    } catch (e) {
        console.error('[GALLERY] Error:', e);
        _galleryStats = {
            total: 0,
            images: 0,
            videos: 0,
            total_size_mb: 0,
        };
        renderGalleryStats({
            total: 0,
            images: 0,
            videos: 0,
            total_size_mb: 0,
        });
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="alert-triangle"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.loadError', {}, 'Erreur de chargement')}</div>
                <div class="gallery-empty-desc">${e?.message || ''}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

function filterGallery(filter, btn) {
    _galleryFilter = filter;
    document.querySelectorAll('#gallery-filters .filter-chip').forEach(c => c.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderGalleryGrid();
}

function getFilteredGalleryFiles() {
    return _galleryFilter === 'all'
        ? _galleryFiles
        : _galleryFiles.filter(f => f.source === _galleryFilter);
}

function renderGalleryGrid() {
    const gridEl = document.getElementById('gallery-grid');
    if (!gridEl) return;

    const filtered = getFilteredGalleryFiles();
    _galleryCurrentList = filtered;

    if (filtered.length === 0) {
        gridEl.innerHTML = `
            <div class="gallery-empty">
                <div class="gallery-empty-icon"><i data-lucide="images"></i></div>
                <div class="gallery-empty-title">${galleryT('settings.storage.emptyTitle', {}, 'La galerie est vide')}</div>
                <div class="gallery-empty-desc">${galleryT('settings.storage.emptyDesc', {}, 'Les générations sauvegardées apparaîtront ici avec aperçu, filtres et actions rapides.')}</div>
            </div>
        `;
        if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
        return;
    }

    gridEl.innerHTML = filtered.map((file, index) => {
        const badgeIcon = file.type === 'video' ? 'clapperboard' : (file.source === 'modified' ? 'wand-sparkles' : 'sparkles');
        const badgeLabel = escapeGalleryHtml(getGallerySourceLabel(file.source));
        const previewAlt = file.type === 'video'
            ? escapeGalleryHtml(galleryT('settings.storage.previewVideo', {}, 'Aperçu vidéo'))
            : escapeGalleryHtml(galleryT('settings.storage.previewImage', {}, 'Aperçu image'));
        const safePath = escapeGalleryHtml(file.path);
        const safeName = escapeGalleryHtml(file.name);
        const safeCreated = escapeGalleryHtml(file.created_str);
        const modelLabel = getGalleryModelLabel(file);
        const safeModel = escapeGalleryHtml(modelLabel);
        return `
            <article class="gallery-card" data-gallery-index="${index}">
                <div class="gallery-card-media">
                    ${file.type === 'video'
                        ? `<video src="${safePath}" muted preload="metadata" playsinline></video>`
                        : `<img src="${safePath}" alt="${previewAlt}">`
                    }
                    <div class="gallery-card-overlay"></div>
                    <div class="gallery-card-topbar">
                        <div class="gallery-kind-badge">
                            <i data-lucide="${badgeIcon}"></i>
                            <span>${badgeLabel}</span>
                        </div>
                        <div class="gallery-card-actions">
                            <button class="gallery-card-icon-btn" type="button" data-gallery-action="download" data-gallery-index="${index}" aria-label="${galleryT('settings.storage.downloadLabel', {}, 'Télécharger')}">
                                <i data-lucide="download"></i>
                            </button>
                            <button class="gallery-card-icon-btn danger" type="button" data-gallery-action="delete" data-gallery-index="${index}" aria-label="${galleryT('settings.storage.deleteLabel', {}, 'Supprimer')}">
                                <i data-lucide="trash-2"></i>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="gallery-card-body">
                    <div class="gallery-card-name" title="${safeName}">${safeName}</div>
                    <div class="gallery-card-meta">
                        ${modelLabel ? `<span class="gallery-meta-pill gallery-meta-pill-model" title="${safeModel}"><i data-lucide="cpu"></i>${safeModel}</span>` : ''}
                        <span class="gallery-meta-pill"><i data-lucide="hard-drive"></i>${file.size_mb} MB</span>
                        <span class="gallery-meta-pill"><i data-lucide="calendar-days"></i>${safeCreated}</span>
                    </div>
                </div>
            </article>
        `;
    }).join('');

    gridEl.querySelectorAll('.gallery-card').forEach(card => {
        const index = Number(card.dataset.galleryIndex);
        const file = filtered[index];
        card.addEventListener('click', () => openGalleryItem(file, undefined, index, filtered));
    });

    gridEl.querySelectorAll('[data-gallery-action]').forEach(btn => {
        btn.addEventListener('click', async (event) => {
            event.stopPropagation();
            const index = Number(btn.dataset.galleryIndex);
            const file = filtered[index];
            if (!file) return;
            if (btn.dataset.galleryAction === 'download') {
                downloadGalleryItem(file.path, file.name);
                return;
            }
            if (btn.dataset.galleryAction === 'delete') {
                await deleteGalleryItem(file.path);
            }
        });
    });

    if (window.lucide) lucide.createIcons({ nodes: [gridEl] });
}

function downloadGalleryItem(path, name) {
    const a = document.createElement('a');
    a.href = path;
    a.download = name || path.split('/').pop();
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function openGalleryItem(file, type, index = null, list = null) {
    const normalized = typeof file === 'string'
        ? { path: file, type: type || 'image', name: file.split('/').pop() || '' }
        : file;
    if (!normalized?.path) return;

    _galleryCurrentItem = normalized;
    if (Array.isArray(list)) {
        _galleryCurrentList = list;
    } else if (!_galleryCurrentList.length) {
        _galleryCurrentList = getFilteredGalleryFiles();
    }
    _galleryCurrentIndex = Number.isInteger(index)
        ? index
        : _galleryCurrentList.findIndex(item => item.path === normalized.path);

    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    const title = document.getElementById('gallery-viewer-title');
    const name = document.getElementById('gallery-viewer-name');
    const meta = document.getElementById('gallery-viewer-meta');
    const counter = document.getElementById('gallery-viewer-counter');

    if (!viewer || !stage || !title || !name || !meta) return;

    const isVideo = normalized.type === 'video';
    const modelLabel = getGalleryModelLabel(normalized);
    const promptText = getGalleryPrompt(normalized);
    resetGalleryViewerZoom();
    title.textContent = galleryT(isVideo ? 'settings.storage.previewVideo' : 'settings.storage.previewImage', {}, isVideo ? 'Aperçu vidéo' : 'Aperçu image');
    name.textContent = normalized.name || normalized.path.split('/').pop() || '';
    stage.innerHTML = isVideo
        ? `<div class="gallery-viewer-media-shell">
                <video class="gallery-viewer-media" src="${escapeGalleryHtml(normalized.path)}" controls autoplay playsinline></video>
                <span class="gallery-viewer-zoom-hint">${escapeGalleryHtml(galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer'))} · 100%</span>
           </div>`
        : `<div class="gallery-viewer-media-shell">
                <img class="gallery-viewer-media" src="${escapeGalleryHtml(normalized.path)}" alt="${escapeGalleryHtml(title.textContent)}">
                <span class="gallery-viewer-zoom-hint">${escapeGalleryHtml(galleryT('settings.storage.zoomHint', {}, 'Alt + molette pour zoomer'))} · 100%</span>
           </div>`;
    meta.innerHTML = `
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.sourceLabel', {}, 'Source')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(getGallerySourceLabel(normalized.source || normalized.type))}</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.modelLabel', {}, 'Modèle')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(modelLabel || galleryT('settings.storage.metadataMissing', {}, 'Non enregistré'))}</span>
        </div>
        <div class="gallery-viewer-meta-row gallery-viewer-meta-row-full">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.promptLabel', {}, 'Prompt')}</span>
            <span class="gallery-viewer-meta-value gallery-viewer-prompt">${escapeGalleryHtml(promptText || galleryT('settings.storage.metadataMissing', {}, 'Non enregistré'))}</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.sizeLabel', {}, 'Stockage')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(normalized.size_mb ?? '—')} MB</span>
        </div>
        <div class="gallery-viewer-meta-row">
            <span class="gallery-viewer-meta-label">${galleryT('settings.storage.createdLabel', {}, 'Créé')}</span>
            <span class="gallery-viewer-meta-value">${escapeGalleryHtml(normalized.created_str || '—')}</span>
        </div>
    `;
    if (counter) {
        const total = _galleryCurrentList.length;
        counter.textContent = total > 1 && _galleryCurrentIndex >= 0
            ? `${_galleryCurrentIndex + 1} / ${total}`
            : '';
    }
    updateGalleryViewerNav();

    viewer.classList.add('is-open');
    viewer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('gallery-viewer-open');
    if (window.lucide) lucide.createIcons({ nodes: [viewer] });
}

function updateGalleryViewerNav() {
    const hasNavigation = _galleryCurrentList.length > 1;
    document.querySelectorAll('.gallery-viewer-nav').forEach(btn => {
        btn.hidden = !hasNavigation;
        btn.disabled = !hasNavigation;
    });
}

function showAdjacentGalleryItem(direction) {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer?.classList.contains('is-open')) return;

    if (!_galleryCurrentList.length) {
        _galleryCurrentList = getFilteredGalleryFiles();
    }
    if (_galleryCurrentList.length <= 1) return;

    if (_galleryCurrentIndex < 0 && _galleryCurrentItem?.path) {
        _galleryCurrentIndex = _galleryCurrentList.findIndex(item => item.path === _galleryCurrentItem.path);
    }

    const currentIndex = _galleryCurrentIndex >= 0 ? _galleryCurrentIndex : 0;
    const nextIndex = (currentIndex + direction + _galleryCurrentList.length) % _galleryCurrentList.length;
    openGalleryItem(_galleryCurrentList[nextIndex], undefined, nextIndex, _galleryCurrentList);
}

async function deleteGalleryItem(path) {
    const confirmed = await JoyDialog.confirm(galleryT('settings.storage.deleteConfirm', {}, 'Supprimer ce fichier ?'), { variant: 'danger' });
    if (!confirmed) return;

    const deleteBtn = document.getElementById('gallery-viewer-delete-btn');
    if (deleteBtn) deleteBtn.disabled = true;

    try {
        const resp = await fetch('/api/gallery/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const data = await resp.json().catch(() => ({}));

        if (resp.ok && data.success !== false) {
            if (_galleryCurrentItem?.path === path) closeGalleryViewer();
            Toast.success(galleryT('settings.storage.deleted', {}, 'Fichier supprimé'));
            refreshGallery();
        } else {
            Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'), data.error || `${resp.status}`);
        }
    } catch (e) {
        console.error('[GALLERY] Delete error:', e);
        Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'), e?.message || '');
    } finally {
        if (deleteBtn) deleteBtn.disabled = false;
    }
}

async function clearAllGallery() {
    const confirmed = await JoyDialog.confirm(galleryT('settings.storage.clearConfirm', {}, 'Supprimer tous les fichiers générés ? Cette action est irréversible.'), { variant: 'danger' });
    if (!confirmed) return;

    try {
        const resp = await fetch('/api/gallery/list');
        const data = await resp.json();

        for (const file of data.files) {
            await fetch('/api/gallery/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: file.path })
            });
        }

        closeGalleryViewer();
        Toast.success(galleryT('settings.storage.cleared', {}, 'Galerie vidée'));
        refreshGallery();
    } catch (e) {
        console.error('[GALLERY] Clear error:', e);
        Toast.error(galleryT('settings.storage.deleteError', {}, 'Erreur de suppression'));
    }
}

function closeGalleryViewer() {
    const viewer = document.getElementById('gallery-viewer');
    const stage = document.getElementById('gallery-viewer-stage');
    const counter = document.getElementById('gallery-viewer-counter');
    if (!viewer || !stage) return;
    viewer.classList.remove('is-open');
    viewer.setAttribute('aria-hidden', 'true');
    stage.innerHTML = '';
    if (counter) counter.textContent = '';
    _galleryCurrentItem = null;
    _galleryCurrentIndex = -1;
    document.body.classList.remove('gallery-viewer-open');
    resetGalleryViewerZoom();
    updateGalleryViewerNav();
}

function downloadCurrentGalleryItem() {
    if (!_galleryCurrentItem) return;
    downloadGalleryItem(_galleryCurrentItem.path, _galleryCurrentItem.name);
}

async function deleteCurrentGalleryItem() {
    if (!_galleryCurrentItem?.path) return;
    await deleteGalleryItem(_galleryCurrentItem.path);
}

document.addEventListener('click', (event) => {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer || !viewer.classList.contains('is-open')) return;
    if (event.target === viewer) {
        closeGalleryViewer();
    }
});

document.addEventListener('keydown', (event) => {
    const viewer = document.getElementById('gallery-viewer');
    if (!viewer?.classList.contains('is-open')) return;

    if (event.key === 'Escape') {
        closeGalleryViewer();
        return;
    }

    if (event.key === 'ArrowLeft') {
        event.preventDefault();
        showAdjacentGalleryItem(-1);
        return;
    }

    if (event.key === 'ArrowRight') {
        event.preventDefault();
        showAdjacentGalleryItem(1);
    }
});

document.addEventListener('wheel', handleGalleryViewerWheel, { passive: false });

window.addEventListener('joyboy:locale-changed', () => {
    renderGalleryStats(_galleryStats || {
        total: _galleryFiles.length,
        images: _galleryFiles.filter(file => file.type === 'image').length,
        videos: _galleryFiles.filter(file => file.type === 'video').length,
        total_size_mb: Math.round((_galleryFiles.reduce((total, file) => total + (file.size || 0), 0) / (1024 * 1024)) * 100) / 100,
    });
    renderGalleryGrid();

    if (_galleryCurrentItem) {
        openGalleryItem(_galleryCurrentItem);
    }
});
