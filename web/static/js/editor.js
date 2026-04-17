// ===== EDITOR - Edit mode with canvas =====

let editCanvas = null;
let editCtx = null;
let isDrawing = false;
let brushSize = 30;
let canvasHistory = [];
const MAX_HISTORY = 30;
let isEditPanning = false;
let editPanStartX = 0;
let editPanStartY = 0;
let editModelSwitched = false;  // Track si on a switch les modèles pour l'edit
let editWasUsed = false;  // Track si l'utilisateur a fait quelque chose

function editT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) {
        return window.JoyBoyI18n.t(key, params, fallback);
    }
    return fallback || key;
}

function refreshEditChrome(root = document) {
    if (window.JoyBoyI18n?.applyTranslations) {
        window.JoyBoyI18n.applyTranslations(root);
    }
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    window.JoyTooltip?.rescan?.(root);
}

function renderEditActionButton(button, { icon, tooltipKey, fallback, extraClass = '' }) {
    if (!button) return;

    const label = editT(tooltipKey, fallback);
    button.type = 'button';
    button.className = `edit-action-btn icon-only ${extraClass}`.trim();
    button.setAttribute('data-tooltip', label);
    button.setAttribute('aria-label', label);
    button.removeAttribute('title');
    button.innerHTML = `<i data-lucide="${icon}"></i><span class="sr-only">${escapeHtml(label)}</span>`;
}

function hydrateEditToolbar() {
    const header = document.querySelector('#edit-modal .edit-header');
    const actions = document.querySelector('#edit-modal .edit-actions');
    if (!header || !actions) return;

    const title = header.querySelector(':scope > .edit-title');
    if (title && !header.querySelector(':scope > .edit-heading')) {
        const heading = document.createElement('div');
        heading.className = 'edit-heading';
        heading.innerHTML = `<span class="edit-kicker" id="edit-kicker">${escapeHtml(editT('editor.kicker', 'Image Lab'))}</span>`;
        header.insertBefore(heading, title);
        title.id = title.id || 'edit-title';
        heading.appendChild(title);
    }

    header.querySelector('.brush-size-control label')?.setAttribute('id', 'edit-brush-size-label');

    const actionConfigs = [
        ['downloadEditImage', { icon: 'download', tooltipKey: 'editor.downloadTooltip', fallback: 'Télécharger l’image actuelle' }],
        ['upscaleEditImage', { icon: 'image-upscale', tooltipKey: 'editor.upscaleTooltip', fallback: 'Améliorer la résolution x2' }],
        ['expandEditImage', { icon: 'maximize-2', tooltipKey: 'editor.expandTooltip', fallback: 'Agrandir la scène autour de l’image' }],
        ['undoCanvas', { icon: 'undo-2', tooltipKey: 'editor.undoTooltip', fallback: 'Annuler le dernier trait', extraClass: 'secondary' }],
        ['clearEditCanvas', { icon: 'eraser', tooltipKey: 'editor.clearTooltip', fallback: 'Effacer tout le masque', extraClass: 'secondary danger-soft' }],
        ['closeEditModal', { icon: 'x', tooltipKey: 'editor.closeTooltip', fallback: 'Quitter le mode édition', extraClass: 'secondary' }],
    ];

    actionConfigs.forEach(([handlerName, config]) => {
        const button = actions.querySelector(`button[onclick*="${handlerName}"]`);
        renderEditActionButton(button, config);
    });

    actions.querySelectorAll('.video-btn-edit, button[onclick*="generateVideoFromEdit"], button[onclick*="toggleEditVideoPrompt"]').forEach(element => {
        element.remove();
    });
    actions.querySelectorAll('.edit-actions-separator, .edit-actions-divider').forEach(element => element.remove());

    const videoPrompt = document.getElementById('edit-video-prompt');
    if (videoPrompt && videoPrompt.closest('.edit-actions')) {
        videoPrompt.remove();
    }

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    window.JoyTooltip?.rescan?.(header);
}

// ===== RESIZE IMAGE TO TARGET SIZE =====
// Resize l'image une seule fois au chargement pour que tout soit à la même taille
const TARGET_MAX_SIZE = 2048;  // 2K max - plus de détails pour crop-to-mask + ESRGAN
const TARGET_MIN_SIZE = 720;

/**
 * Resize une image pour qu'elle soit à la taille de génération (720p max, multiples de 8)
 * @param {string} imageSrc - Data URL ou URL de l'image
 * @returns {Promise<string>} - Data URL de l'image redimensionnée
 */
async function resizeImageToTarget(imageSrc) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            let { width, height } = img;

            // Calculer la nouvelle taille en gardant le ratio
            const ratio = width / height;

            if (width > height) {
                // Paysage
                if (width > TARGET_MAX_SIZE) {
                    width = TARGET_MAX_SIZE;
                    height = Math.round(width / ratio);
                }
            } else {
                // Portrait
                if (height > TARGET_MAX_SIZE) {
                    height = TARGET_MAX_SIZE;
                    width = Math.round(height * ratio);
                }
            }

            // Arrondir aux multiples de 8 (requis pour SDXL VAE)
            width = Math.round(width / 8) * 8;
            height = Math.round(height / 8) * 8;

            // Minimum 512 sur le plus grand côté (SDXL entraîné 512-1024)
            const maxSide = Math.max(width, height);
            if (maxSide < 512) {
                const scale = 512 / maxSide;
                width = Math.round((width * scale) / 8) * 8;
                height = Math.round((height * scale) / 8) * 8;
            }

            console.log(`[EDITOR] Resize: ${img.width}x${img.height} -> ${width}x${height}`);

            // Créer le canvas de resize
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');

            // Dessiner l'image redimensionnée
            ctx.drawImage(img, 0, 0, width, height);

            // Retourner en data URL (PNG pour qualité maximale)
            resolve(canvas.toDataURL('image/png'));
        };
        img.src = imageSrc;
    });
}

// Modes de pinceau
const BRUSH_MODES = {
    hard: { name: 'Pinceau', i18nKey: 'editor.brushMask', icon: 'paintbrush' },
    eraser: { name: 'Gomme', i18nKey: 'editor.brushEraser', icon: 'eraser' }
};
let currentBrushMode = 'hard';  // 'hard' ou 'soft'

// Edit presets (illimités)
let editPresets = [];
// Edit model suit le main picker par défaut — reset au load
Settings.set('editSelectedModel', null);
let selectedEditModel = null;

// Sync edit model from Settings
Settings.subscribe('editSelectedModel', (val) => {
    // Si noMask (Flux Kontext), ignorer
    if (val && typeof INPAINT_MODELS !== 'undefined') {
        const isNoMask = INPAINT_MODELS.find(m => m.id === val)?.noMask;
        if (isNoMask) val = null;
    }
    selectedEditModel = val;
    const textSpan = document.getElementById('edit-selected-model-text');
    if (textSpan) {
        textSpan.textContent = val || (typeof getCurrentInpaintModel === 'function'
            ? getCurrentInpaintModel()
            : Settings.get('selectedInpaintModel'));
    }
});

// Sync: quand le main picker change, le edit picker suit toujours
Settings.subscribe('selectedInpaintModel', (val) => {
    selectedEditModel = null;
    Settings.set('editSelectedModel', null);
    const textSpan = document.getElementById('edit-selected-model-text');
    if (textSpan) textSpan.textContent = val;
});

// Cache des masques par image (hash de l'image -> mask data)
const maskCache = new Map();
const MAX_MASK_CACHE = 10;

/**
 * Génère un hash simple pour identifier une image
 */
function getImageHash(imageSrc) {
    // Prendre les 100 premiers et derniers caractères pour un hash rapide
    const str = imageSrc.substring(0, 100) + imageSrc.slice(-100);
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
    }
    return hash.toString();
}

/**
 * Sauvegarde le masque actuel pour l'image
 */
function saveMaskForImage(imageSrc) {
    if (!editCanvas || !editCtx || !imageSrc) return;

    const hash = getImageHash(imageSrc);
    const maskData = editCtx.getImageData(0, 0, editCanvas.width, editCanvas.height);

    // Vérifier si le masque n'est pas vide
    let hasContent = false;
    for (let i = 3; i < maskData.data.length; i += 4) {
        if (maskData.data[i] > 0) {
            hasContent = true;
            break;
        }
    }

    if (hasContent) {
        maskCache.set(hash, {
            data: maskData,
            width: editCanvas.width,
            height: editCanvas.height
        });

        // Limiter la taille du cache
        if (maskCache.size > MAX_MASK_CACHE) {
            const firstKey = maskCache.keys().next().value;
            maskCache.delete(firstKey);
        }
    }
}

/**
 * Restaure le masque pour une image si disponible
 */
function restoreMaskForImage(imageSrc) {
    if (!editCanvas || !editCtx || !imageSrc) return;

    const hash = getImageHash(imageSrc);
    const cached = maskCache.get(hash);

    if (cached && cached.width === editCanvas.width && cached.height === editCanvas.height) {
        editCtx.putImageData(cached.data, 0, 0);
        console.log('[EDIT] Masque restauré depuis le cache');
    }
}

// Ouvre l'éditeur avec switch de modèle (pour images générées par text2img)
async function openEditModalWithModelSwitch(imageSrc) {
    console.log('[EDIT] Ouverture avec switch de modèle...');
    editModelSwitched = true;
    editWasUsed = false;

    // Décharger le modèle texte et charger le modèle image
    await unloadTextModel();
    await preloadImageModel();

    // Ouvrir l'éditeur normalement
    await openEditModal(imageSrc);
}

async function openEditModal(imageSrc) {
    // Resize l'image UNE SEULE FOIS à la taille de génération (720p, multiples de 8)
    // Comme ça: image affichée = taille du masque = taille de génération = taille du résultat
    const resizedSrc = await resizeImageToTarget(imageSrc);
    editImageSrc = resizedSrc;

    canvasHistory = [];
    const modal = document.getElementById('edit-modal');
    const img = document.getElementById('edit-image');
    const canvas = document.getElementById('edit-canvas');

    resetEditZoom();

    img.src = resizedSrc;
    modal.classList.add('open');
    hydrateEditToolbar();

    // Initialiser les presets et icônes
    renderEditPresets();
    refreshEditChrome(modal);

    // Initialiser l'indicateur de mode pinceau
    updateBrushModeIndicator();

    img.onload = function() {
        // Utiliser les dimensions ORIGINALES de l'image, pas les dimensions affichées
        // Sinon le masque est capturé en basse résolution et les brush strokes sont trop fins
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        editCanvas = canvas;
        editCtx = canvas.getContext('2d');
        canvas.style.opacity = '0.4';  // Semi-transparent pour voir l'image (CSS = pas d'accumulation)
        editCtx.clearRect(0, 0, canvas.width, canvas.height);

        // Calculer le ratio d'échelle pour le dessin (display → canvas)
        // Protection contre division par zéro si l'image n'est pas encore rendue
        const displayWidth = img.offsetWidth || img.naturalWidth;
        const displayHeight = img.offsetHeight || img.naturalHeight;
        editCanvas._scaleX = img.naturalWidth / displayWidth;
        editCanvas._scaleY = img.naturalHeight / displayHeight;

        console.log(`[EDIT] Canvas: ${canvas.width}x${canvas.height}, Display: ${displayWidth}x${displayHeight}, Scale: ${editCanvas._scaleX.toFixed(2)}x${editCanvas._scaleY.toFixed(2)}`);

        // Restaurer le masque si on rouvre la même image
        restoreMaskForImage(imageSrc);

        // Sauvegarder l'état initial (pour pouvoir Ctrl+Z jusqu'à zéro)
        canvasHistory = [];
        saveCanvasState();

        canvas.addEventListener('mousedown', handleEditMouseDown);
        canvas.addEventListener('mousemove', handleEditMouseMove);
        canvas.addEventListener('mouseup', handleEditMouseUp);
        canvas.addEventListener('mouseleave', handleEditMouseUp);

        canvas.addEventListener('touchstart', handleTouchStart);
        canvas.addEventListener('touchmove', handleTouchMove);
        canvas.addEventListener('touchend', stopDrawing);

        // Mettre à jour le curseur pinceau
        updateBrushCursor();
    };

    document.getElementById('edit-prompt').focus();

    // Le prompt vidéo reste rangé tant que l'utilisateur ne le demande pas.
    document.getElementById('edit-video-prompt')?.classList.remove('is-open');
    updateEditVideoPromptVisibility();
}

/**
 * Affiche ou masque le champ prompt vidéo selon le modèle vidéo sélectionné
 * CogVideoX supporte les prompts, SVD non
 */
function updateEditVideoPromptVisibility() {
    const promptInput = document.getElementById('edit-video-prompt');
    if (!promptInput) return;

    const videoModel = (typeof userSettings !== 'undefined' && userSettings.videoModel) || 'ltx';
    const supportsPrompt = videoModel !== 'svd';
    const isOpen = promptInput.classList.contains('is-open');

    promptInput.style.display = supportsPrompt && isOpen ? 'block' : 'none';
    promptInput.placeholder = editT('editor.videoPromptPlaceholder', 'Décris le mouvement vidéo...');
    if (!supportsPrompt) {
        promptInput.classList.remove('is-open');
    }
}

function toggleEditVideoPrompt() {
    const promptInput = document.getElementById('edit-video-prompt');
    if (!promptInput) {
        generateVideoFromEdit();
        return;
    }

    const videoModel = (typeof userSettings !== 'undefined' && userSettings.videoModel) || 'ltx';
    const supportsPrompt = videoModel !== 'svd';
    if (!supportsPrompt) {
        generateVideoFromEdit();
        return;
    }

    const isOpen = promptInput.classList.toggle('is-open');
    updateEditVideoPromptVisibility();
    if (isOpen) {
        promptInput.focus();
        return;
    }

    generateVideoFromEdit();
}

function resetEditZoom() {
    editZoomLevel = 1;
    editPanX = 0;
    editPanY = 0;
    const container = document.getElementById('edit-canvas-container');
    if (container) {
        container.style.transform = 'scale(1) translate(0px, 0px)';
        container.classList.remove('dragging');
    }
    const indicator = document.getElementById('edit-zoom-level');
    if (indicator) indicator.classList.remove('visible');
}

function updateEditTransform() {
    const container = document.getElementById('edit-canvas-container');
    if (!container) return;
    container.style.transform = `scale(${editZoomLevel}) translate(${editPanX}px, ${editPanY}px)`;
}

function handleEditMouseDown(e) {
    console.log('[EDIT] mousedown', { button: e.button, spacePressed, target: e.target.id || e.target.tagName });

    // Pan avec espace OU clic molette (button 1) - marche à tous les niveaux de zoom
    if (spacePressed || e.button === 1) {
        isEditPanning = true;
        editPanStartX = e.clientX - editPanX * editZoomLevel;
        editPanStartY = e.clientY - editPanY * editZoomLevel;
        document.getElementById('edit-canvas-container').classList.add('dragging');
        e.preventDefault();
        return;
    }
    startDrawing(e);
}

function handleEditMouseMove(e) {
    if (isEditPanning) {
        editPanX = (e.clientX - editPanStartX) / editZoomLevel;
        editPanY = (e.clientY - editPanStartY) / editZoomLevel;
        updateEditTransform();
        return;
    }
    const canvas = document.getElementById('edit-canvas');
    if (spacePressed) {
        canvas.classList.add('panning');
    } else {
        canvas.classList.remove('panning');
    }
    draw(e);
}

function handleEditMouseUp(e) {
    if (isEditPanning) {
        isEditPanning = false;
        document.getElementById('edit-canvas-container').classList.remove('dragging');
        return;
    }
    stopDrawing();
}

async function closeEditModal() {
    // Sauvegarder le masque avant de fermer
    if (editImageSrc) {
        saveMaskForImage(editImageSrc);
    }

    document.getElementById('edit-modal').classList.remove('open');
    editImageSrc = null;
    resetEditZoom();
    if (editCanvas) {
        editCanvas.removeEventListener('mousedown', handleEditMouseDown);
        editCanvas.removeEventListener('mousemove', handleEditMouseMove);
        editCanvas.removeEventListener('mouseup', handleEditMouseUp);
        editCanvas.removeEventListener('mouseleave', handleEditMouseUp);
    }

    // Si on avait switch les modèles et qu'on n'a rien fait, revenir au modèle texte
    if (editModelSwitched && !editWasUsed) {
        console.log('[EDIT] Fermeture sans modification -> retour au modèle texte');
        await unloadImageModel();
        await preloadTextModel();
    }

    // Reset les flags
    editModelSwitched = false;
    editWasUsed = false;
}

function updateBrushSize(value) {
    brushSize = parseInt(value);
    document.getElementById('brush-size-value').textContent = value + 'px';
    updateBrushCursor();
}

// Crée un curseur circulaire représentant la taille et le mode du pinceau
function updateBrushCursor() {
    const canvas = document.getElementById('edit-canvas');
    if (!canvas) return;

    const size = Math.max(brushSize / editZoomLevel, 4);
    const cursorCanvas = document.createElement('canvas');
    cursorCanvas.width = size + 6;
    cursorCanvas.height = size + 6;
    const ctx = cursorCanvas.getContext('2d');
    const centerX = cursorCanvas.width / 2;
    const centerY = cursorCanvas.height / 2;
    const radius = size / 2;

    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);

    if (currentBrushMode === 'eraser') {
        // Gomme : cercle rouge pointillé + point central
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = 'rgba(255, 100, 100, 0.8)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    } else {
        // Pinceau : cercle blanc sans remplissage + point central
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    // Point central
    ctx.beginPath();
    ctx.arc(centerX, centerY, 2, 0, Math.PI * 2);
    ctx.fillStyle = currentBrushMode === 'eraser' ? 'rgba(255, 100, 100, 0.9)' : 'rgba(255, 255, 255, 0.9)';
    ctx.fill();

    const cursorUrl = cursorCanvas.toDataURL();
    const hotspot = Math.round(cursorCanvas.width / 2);
    canvas.style.cursor = `url(${cursorUrl}) ${hotspot} ${hotspot}, crosshair`;
}

function saveCanvasState() {
    if (!editCanvas || !editCtx) return;
    const imageData = editCtx.getImageData(0, 0, editCanvas.width, editCanvas.height);
    canvasHistory.push(imageData);
    if (canvasHistory.length > MAX_HISTORY) {
        canvasHistory.shift();
    }
}

function undoCanvas() {
    if (!editCanvas || !editCtx || canvasHistory.length === 0) return;
    const previousState = canvasHistory.pop();
    editCtx.putImageData(previousState, 0, 0);
}

function startDrawing(e) {
    console.log('[EDIT] startDrawing called', { editCanvas: !!editCanvas, editCtx: !!editCtx });
    if (!editCanvas || !editCtx) {
        console.error('[EDIT] Canvas not initialized!');
        return;
    }
    saveCanvasState();
    isDrawing = true;
    draw(e);
}

function stopDrawing() {
    isDrawing = false;
    if (editCtx) editCtx.beginPath();
}

function draw(e) {
    if (!isDrawing || !editCanvas || !editCtx) return;

    const rect = editCanvas.getBoundingClientRect();
    // Scaler les coordonnées pour correspondre à la résolution du canvas (originale)
    // Protection: si scale invalide (Infinity ou NaN), utiliser 1
    let scaleX = editCanvas._scaleX || 1;
    let scaleY = editCanvas._scaleY || 1;
    if (!isFinite(scaleX) || scaleX <= 0) scaleX = 1;
    if (!isFinite(scaleY) || scaleY <= 0) scaleY = 1;

    const x = ((e.clientX - rect.left) / editZoomLevel) * scaleX;
    const y = ((e.clientY - rect.top) / editZoomLevel) * scaleY;
    // Le radius doit aussi être scalé pour dessiner à la bonne taille
    const radius = (brushSize / 2 / editZoomLevel) * Math.max(scaleX, scaleY);

    if (currentBrushMode === 'eraser') {
        editCtx.globalCompositeOperation = 'destination-out';
    } else {
        editCtx.globalCompositeOperation = 'source-over';
    }
    editCtx.fillStyle = 'rgba(255, 255, 255, 1.0)';

    editCtx.beginPath();
    editCtx.arc(x, y, radius, 0, Math.PI * 2);
    editCtx.fill();
}

function handleTouchStart(e) {
    e.preventDefault();
    saveCanvasState();
    isDrawing = true;
    handleTouchMove(e);
}

function handleTouchMove(e) {
    if (!isDrawing || !editCanvas || !editCtx) return;
    e.preventDefault();

    const rect = editCanvas.getBoundingClientRect();
    const touch = e.touches[0];
    const scaleX = editCanvas._scaleX || 1;
    const scaleY = editCanvas._scaleY || 1;
    const x = ((touch.clientX - rect.left) / editZoomLevel) * scaleX;
    const y = ((touch.clientY - rect.top) / editZoomLevel) * scaleY;
    const radius = (brushSize / 2 / editZoomLevel) * Math.max(scaleX, scaleY);

    if (currentBrushMode === 'eraser') {
        editCtx.globalCompositeOperation = 'destination-out';
    } else {
        editCtx.globalCompositeOperation = 'source-over';
    }
    editCtx.fillStyle = 'rgba(255, 255, 255, 1.0)';

    editCtx.beginPath();
    editCtx.arc(x, y, radius, 0, Math.PI * 2);
    editCtx.fill();
}

function clearEditCanvas() {
    if (editCtx && editCanvas) {
        saveCanvasState();
        editCtx.clearRect(0, 0, editCanvas.width, editCanvas.height);
    }
}

// Anti double-submit flag for editor
let _editSubmitLock = false;

const EDITOR_DEFAULT_AUTO_FILL_PROMPT = "seamless fill matching surrounding area, natural blend, same lighting, same style, realistic texture, RAW photo, high quality";

async function resolveEditorAutoFillPrompt() {
    try {
        if (typeof apiSettings === 'undefined' || !apiSettings.getPackEditorPrompts) {
            return EDITOR_DEFAULT_AUTO_FILL_PROMPT;
        }

        const result = await apiSettings.getPackEditorPrompts();
        const prompt = result?.data?.editor_prompts?.auto_fill_prompt;
        if (result?.ok && result.data?.adult_runtime_available === true && typeof prompt === 'string' && prompt.trim()) {
            return prompt.trim();
        }
    } catch (error) {
        console.warn('[EDIT] Pack auto-fill prompt unavailable, using neutral default:', error);
    }

    return EDITOR_DEFAULT_AUTO_FILL_PROMPT;
}

async function generateEdit() {
    // Anti double-submit: verrou immédiat
    if (_editSubmitLock) {
        console.log('[EDIT] Double-submit bloqué');
        return;
    }
    _editSubmitLock = true;
    setTimeout(() => { _editSubmitLock = false; }, 500);

    let prompt = document.getElementById('edit-prompt').value.trim();

    if (!editCanvas || !editImageSrc) {
        await JoyDialog.alert(editT('editor.noImageToEdit', 'Pas d’image à modifier'), { variant: 'danger' });
        _editSubmitLock = false;
        return;
    }

    // Marquer qu'on a utilisé l'éditeur (pour ne pas recharger le modèle texte à la fermeture)
    editWasUsed = true;

    const isGenerativeFill = !prompt;
    if (isGenerativeFill) {
        // Auto-fill stays neutral in core, but an active local pack can replace
        // the prompt via /api/packs/editor-prompts without hardcoding pack text here.
        prompt = await resolveEditorAutoFillPrompt();
    }

    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = editCanvas.width;
    maskCanvas.height = editCanvas.height;
    const maskCtx = maskCanvas.getContext('2d');

    maskCtx.fillStyle = 'black';
    maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);

    const imageData = editCtx.getImageData(0, 0, editCanvas.width, editCanvas.height);
    const maskData = maskCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height);

    // Convertir le dessin en masque avec niveaux de gris
    // Le pinceau doux crée des transitions plus douces dans le masque
    for (let i = 0; i < imageData.data.length; i += 4) {
        const alpha = imageData.data[i + 3];
        if (alpha > 0) {
            // Mapper l'alpha du dessin vers l'intensité du masque
            // Alpha 0 = noir (pas de modification), Alpha 255 = blanc (modification complète)
            const intensity = Math.round((alpha / 255) * 255);
            maskData.data[i] = intensity;
            maskData.data[i + 1] = intensity;
            maskData.data[i + 2] = intensity;
            maskData.data[i + 3] = 255;
        }
    }
    maskCtx.putImageData(maskData, 0, 0);

    const maskDataUrl = maskCanvas.toDataURL('image/png');
    const savedEditImageSrc = editImageSrc;

    closeEditModal();
    document.getElementById('edit-prompt').value = '';

    // Créer un chat si nécessaire AVANT d'ajouter les messages
    // Ceci permet aux actions suivantes (expand, upscale) de conserver l'historique
    if (!currentChatId) {
        await createNewChat();
    }

    showChat();

    const displayPrompt = isGenerativeFill ? editT('editor.autoFillLabel', 'Remplissage auto') : prompt;
    // Passer le masque au skeleton pour l'afficher en overlay sur l'image originale
    addSkeletonMessage(displayPrompt, savedEditImageSrc, true, maskDataUrl);

    // Activer le mode génération (bouton stop)
    isGenerating = true;
    currentGenerationMode = 'image';
    currentController = new AbortController();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);

    // Le backend charge le modèle inpaint à la demande
    const editModel = getEditModel();

    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    try {
        const adultPayload = window.getAdultGenerationPayload ? window.getAdultGenerationPayload() : {};
        const result = await apiGeneration.generateEdit({
            image: savedEditImageSrc,
            mask: maskDataUrl,
            prompt: prompt,
            model: editModel,
            strength: userSettings.strength,
            enhance: isGenerativeFill ? false : userSettings.enhancePrompt,
            enhance_mode: isGenerativeFill ? 'none' : (userSettings.enhanceMode || 'light'),
            steps: userSettings.steps,
            skip_auto_refine: userSettings.skipAutoRefine === true,
            ...adultPayload,
        }, currentController.signal);

        stopPreviewPolling();

        if (result.aborted || currentController?.signal?.aborted) {
            removeSkeletonMessage();
            return;
        }

        const data = result.data;

        if (data?.success) {
            const newImage = 'data:image/png;base64,' + data.modified;
            const genTime = data.generationTime || null;
            addMessage(displayPrompt, savedEditImageSrc, savedEditImageSrc, newImage, genTime);
        } else {
            removeSkeletonMessage();
            Toast.error(editT('common.errorWithMessage', 'Erreur : {error}', {
                error: data?.error || result.error || editT('common.unknownError', 'Erreur inconnue'),
            }));
        }
    } catch (err) {
        stopPreviewPolling();
        removeSkeletonMessage();
        if (err.name !== 'AbortError') {
            Toast.error(editT('common.errorWithMessage', 'Erreur : {error}', { error: err.message }));
        }
    } finally {
        // Désactiver le mode génération
        isGenerating = false;
        currentController = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);

        // Traiter le prochain élément de la queue
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') {
                processNextInQueue();
            }
        }, 100);
    }
}

/**
 * Fix Details (ADetailer): detects faces in the editor image and re-inpaints each
 * at high resolution via crop-to-mask + Fooocus pipeline.
 */
async function fixDetailsEdit() {
    // Activer le mode génération
    isGenerating = true;
    currentGenerationMode = 'image';
    currentController = new AbortController();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);

    // Afficher un indicateur de chargement sur l'image de l'éditeur
    const editImg = document.getElementById('edit-image');
    const editContainer = editImg?.parentElement;
    let loadingOverlay = null;

    if (editContainer) {
        loadingOverlay = document.createElement('div');
        loadingOverlay.className = 'refine-loading-overlay';
        loadingOverlay.innerHTML = `
            <div class="refine-loading-spinner"></div>
            <div class="refine-loading-text">Fix Details...</div>
        `;
        loadingOverlay.style.cssText = `
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.7); display: flex; flex-direction: column;
            align-items: center; justify-content: center; z-index: 100;
            border-radius: 8px;
        `;
        loadingOverlay.querySelector('.refine-loading-spinner').style.cssText = `
            width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.3);
            border-top-color: #fff; border-radius: 50%; animation: spin 1s linear infinite;
        `;
        loadingOverlay.querySelector('.refine-loading-text').style.cssText = `
            color: #fff; margin-top: 12px; font-size: 14px;
        `;
        editContainer.style.position = 'relative';
        editContainer.appendChild(loadingOverlay);
    }

    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    try {
        const result = await apiGeneration.fixDetails({}, currentController.signal);

        stopPreviewPolling();

        if (result.aborted || currentController?.signal?.aborted) {
            if (loadingOverlay) loadingOverlay.remove();
            return;
        }

        const data = result.data;

        if (loadingOverlay) loadingOverlay.remove();

        if (data?.success) {
            const newImage = 'data:image/png;base64,' + data.modified;

            if (editImg) {
                editImg.src = newImage;
            }

            const fixedParts = [];
            if (data.faces_fixed) {
                fixedParts.push(editT('editor.facesFixed', '{count} visage(s)', { count: data.faces_fixed }));
            }
            if (data.hands_fixed) {
                fixedParts.push(editT('editor.handsFixed', '{count} main(s)', { count: data.hands_fixed }));
            }
            const facesMsg = fixedParts.length ? ` (${fixedParts.join(', ')})` : '';
            Toast.success(editT('editor.detailsFixed', 'Détails corrigés en {seconds}s{faces}', {
                seconds: data.generationTime?.toFixed(1) || '?',
                faces: facesMsg,
            }));
        } else {
            Toast.error(editT('common.errorWithMessage', 'Erreur : {error}', {
                error: data?.error || editT('editor.fixDetailsFailed', 'Échec fix details'),
            }));
        }
    } catch (err) {
        stopPreviewPolling();
        if (loadingOverlay) loadingOverlay.remove();
        if (err.name !== 'AbortError') {
            Toast.error(editT('editor.fixDetailsError', 'Erreur Fix Details : {error}', { error: err.message }));
        }
    } finally {
        isGenerating = false;
        currentController = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
    }
}

function initEditorZoom() {
    const wrapper = document.getElementById('edit-canvas-wrapper');
    if (!wrapper) return;

    wrapper.addEventListener('wheel', function(e) {
        e.preventDefault();
        const zoomIndicator = document.getElementById('edit-zoom-level');

        if (e.deltaY < 0) {
            editZoomLevel = Math.min(EDIT_MAX_ZOOM, editZoomLevel + 0.2);
        } else {
            editZoomLevel = Math.max(EDIT_MIN_ZOOM, editZoomLevel - 0.2);
        }

        if (editZoomLevel <= 1) {
            editPanX = 0;
            editPanY = 0;
        }

        updateEditTransform();
        zoomIndicator.textContent = Math.round(editZoomLevel * 100) + '%';
        zoomIndicator.classList.add('visible');

        // Mettre à jour le curseur pinceau pour le nouveau zoom
        updateBrushCursor();

        clearTimeout(editZoomTimeout);
        editZoomTimeout = setTimeout(() => {
            zoomIndicator.classList.remove('visible');
        }, 1000);
    });
}

function initEditorKeyboard() {
    document.addEventListener('keydown', function(e) {
        const editModal = document.getElementById('edit-modal');
        if (!editModal?.classList.contains('open')) return;

        // Ne pas capturer les touches si on est dans un input ou textarea
        const activeEl = document.activeElement;
        const isInInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA');

        // Ctrl+Z = Undo (sauf dans input)
        if (e.ctrlKey && e.key === 'z' && !isInInput) {
            e.preventDefault();
            undoCanvas();
            return;
        }

        // ALT+R = Switch brush mode (sauf dans input)
        if (e.altKey && e.key.toLowerCase() === 'r' && !isInInput) {
            e.preventDefault();
            toggleBrushMode();
            return;
        }

        // Space = Pan mode (sauf dans input)
        if (e.code === 'Space' && !isInInput) {
            if (!spacePressed) {
                spacePressed = true;
                document.getElementById('edit-canvas')?.classList.add('panning');
                e.preventDefault();
            }
        }
    });

    document.addEventListener('keyup', function(e) {
        if (e.code === 'Space') {
            spacePressed = false;
            document.getElementById('edit-canvas')?.classList.remove('panning');
        }
    });
}

/**
 * Switch entre les modes de pinceau (dur/doux)
 */
function toggleBrushMode() {
    currentBrushMode = currentBrushMode === 'hard' ? 'eraser' : 'hard';
    const mode = BRUSH_MODES[currentBrushMode];

    // Mettre à jour le curseur
    updateBrushCursor();

    // Mettre à jour l'indicateur visuel
    updateBrushModeIndicator();

    // Afficher un toast de feedback
    showBrushModeToast(mode);

    console.log(`[EDIT] Brush mode: ${currentBrushMode}`);
}

/**
 * Affiche un toast temporaire pour le changement de mode
 */
function showBrushModeToast(mode) {
    // Supprimer l'ancien toast s'il existe
    const existingToast = document.getElementById('brush-mode-toast');
    if (existingToast) existingToast.remove();

    // Créer le toast
    const toast = document.createElement('div');
    toast.id = 'brush-mode-toast';
    toast.className = 'brush-mode-toast';
    const modeLabel = editT(mode.i18nKey, mode.name);
    toast.innerHTML = `
        <span class="brush-mode-icon"><i data-lucide="${mode.icon}"></i></span>
        <span class="brush-mode-name">${editT('editor.brushToast', 'Mode {mode}', { mode: modeLabel })}</span>
    `;

    // Ajouter au modal
    const editModal = document.getElementById('edit-modal');
    if (editModal) {
        editModal.appendChild(toast);
        refreshEditChrome(toast);

        // Animation d'entrée
        requestAnimationFrame(() => {
            toast.classList.add('visible');
        });

        // Supprimer après 1.5s
        setTimeout(() => {
            toast.classList.remove('visible');
            setTimeout(() => toast.remove(), 300);
        }, 1500);
    }
}

/**
 * Met à jour l'indicateur de mode dans le header
 */
function updateBrushModeIndicator() {
    let indicator = document.getElementById('brush-mode-indicator');

    if (!indicator) {
        // Créer l'indicateur s'il n'existe pas
        const brushControl = document.querySelector('.brush-size-control');
        if (brushControl) {
            indicator = document.createElement('button');
            indicator.id = 'brush-mode-indicator';
            indicator.className = 'brush-mode-indicator';
            indicator.onclick = toggleBrushMode;
            indicator.title = 'Changer le mode (Alt+R)';
            brushControl.parentNode.insertBefore(indicator, brushControl);
        }
    }

    if (indicator) {
        const mode = BRUSH_MODES[currentBrushMode];
        const modeLabel = editT(mode.i18nKey, mode.name);
        indicator.innerHTML = `<span class="indicator-icon"><i data-lucide="${mode.icon}"></i></span><span class="indicator-text">${modeLabel}</span>`;
        indicator.className = `brush-mode-indicator mode-${currentBrushMode}`;
        indicator.setAttribute('data-tooltip', editT('editor.brushModeTooltip', 'Changer le mode de pinceau (Alt+R)'));
        indicator.setAttribute('aria-label', editT('editor.brushModeTooltip', 'Changer le mode de pinceau (Alt+R)'));
        indicator.removeAttribute('title');
        refreshEditChrome(indicator);
    }
}

// ===== EDIT PRESETS =====

/**
 * Charge les presets depuis localStorage
 */
function loadEditPresets() {
    try {
        const saved = localStorage.getItem('editPresets');
        if (saved) {
            editPresets = JSON.parse(saved);
        } else {
            // Presets par défaut
            editPresets = [
                { id: 1, text: '' },
                { id: 2, text: '' },
                { id: 3, text: '' }
            ];
        }
    } catch (e) {
        console.error('[EDIT] Erreur chargement presets:', e);
        editPresets = [{ id: 1, text: '' }, { id: 2, text: '' }, { id: 3, text: '' }];
    }
    renderEditPresets();
}

/**
 * Sauvegarde les presets dans localStorage
 */
function saveEditPresets() {
    try {
        localStorage.setItem('editPresets', JSON.stringify(editPresets));
    } catch (e) {
        console.error('[EDIT] Erreur sauvegarde presets:', e);
    }
}

/**
 * Affiche la liste des presets
 */
function renderEditPresets() {
    const list = document.getElementById('edit-presets-list');
    if (!list) return;

    const emptyLabel = editT('editor.editPresetHint', 'Clic droit pour éditer');
    const deleteLabel = editT('editor.deletePresetTooltip', 'Supprimer le preset');
    const safeEmptyLabel = escapeHtml(emptyLabel);
    const safeDeleteLabel = escapeHtml(deleteLabel);

    list.innerHTML = editPresets.map((preset, index) => `
        <div class="edit-preset-item" onclick="useEditPreset(${preset.id})" oncontextmenu="editEditPreset(${preset.id}, event)">
            <span class="edit-preset-num">${index + 1}</span>
            <span class="edit-preset-text ${!preset.text ? 'empty' : ''}">${preset.text ? escapeHtml(preset.text) : safeEmptyLabel}</span>
            <button class="edit-preset-remove" onclick="removeEditPreset(${preset.id}, event)" data-tooltip="${safeDeleteLabel}" aria-label="${safeDeleteLabel}">
                <i data-lucide="x"></i>
            </button>
        </div>
    `).join('');

    refreshEditChrome(list);
}

/**
 * Ajoute un nouveau preset
 */
function addEditPreset() {
    const newId = editPresets.length > 0 ? Math.max(...editPresets.map(p => p.id)) + 1 : 1;
    editPresets.push({ id: newId, text: '' });
    saveEditPresets();
    renderEditPresets();
}

/**
 * Supprime un preset
 */
function removeEditPreset(id, event) {
    event.stopPropagation();
    if (editPresets.length <= 1) {
        console.log('[EDIT] Au moins un preset doit rester');
        return;
    }
    editPresets = editPresets.filter(p => p.id !== id);
    saveEditPresets();
    renderEditPresets();
}

/**
 * Utilise un preset (met le texte dans l'input)
 */
function useEditPreset(id) {
    const preset = editPresets.find(p => p.id === id);
    if (preset && preset.text) {
        const input = document.getElementById('edit-prompt');
        if (input) {
            input.value = preset.text;
            input.focus();
        }
    }
}

/**
 * Édite un preset (clic droit)
 */
function editEditPreset(id, event) {
    event.preventDefault();
    const preset = editPresets.find(p => p.id === id);
    if (!preset) return;

    const newText = prompt(editT('editor.editPresetPrompt', 'Texte du preset :'), preset.text || '');
    if (newText !== null) {
        preset.text = newText;
        saveEditPresets();
        renderEditPresets();
    }
}

// ===== EDIT MODEL PICKER =====

/**
 * Toggle le model picker de l'éditeur
 */
function toggleEditModelPicker() {
    const picker = document.getElementById('edit-model-picker');
    if (!picker) return;

    picker.classList.toggle('open');

    if (picker.classList.contains('open')) {
        renderModelPickerList('edit');
        setTimeout(() => {
            document.addEventListener('click', closeEditModelPickerOnClickOutside);
        }, 0);
    } else {
        document.removeEventListener('click', closeEditModelPickerOnClickOutside);
    }
}

function closeEditModelPickerOnClickOutside(e) {
    const picker = document.getElementById('edit-model-picker');
    if (picker && !picker.contains(e.target)) {
        picker.classList.remove('open');
        document.removeEventListener('click', closeEditModelPickerOnClickOutside);
    }
}

// renderEditModelList() et selectEditModel() supprimés — réutilise renderModelPickerList('edit') et selectPickerModel() de ui.js

/**
 * Charge le modèle sélectionné depuis SettingsContext
 * Affiche toujours le vrai nom du modèle (jamais "Auto")
 */
function loadEditSelectedModel() {
    let saved = Settings.get('editSelectedModel');
    const textSpan = document.getElementById('edit-selected-model-text');

    // Si le modèle sauvegardé est noMask (Flux Kontext), reset
    if (saved && typeof INPAINT_MODELS !== 'undefined') {
        const isNoMask = INPAINT_MODELS.find(m => m.id === saved)?.noMask;
        if (isNoMask) {
            saved = null;
            Settings.set('editSelectedModel', null);
        }
    }

    if (saved) {
        selectedEditModel = saved;
        if (textSpan) {
            textSpan.textContent = saved;
        }
    } else {
        selectedEditModel = null;
        if (textSpan) {
            const defaultModel = typeof getCurrentInpaintModel === 'function'
                ? getCurrentInpaintModel()
                : (typeof selectedInpaintModel !== 'undefined' ? selectedInpaintModel : 'epiCRealism XL (Moyen)');
            textSpan.textContent = defaultModel;
        }
    }
}

/**
 * Retourne le modèle à utiliser pour l'édition
 * En mode EDIT, on fait toujours de l'inpainting donc on utilise le modèle inpaint
 */
function getEditModel() {
    // Priorité: modèle sélectionné dans l'éditeur > modèle inpaint global
    if (selectedEditModel) {
        console.log(`[EDIT] Modèle sélectionné dans l'éditeur: ${selectedEditModel}`);
        return selectedEditModel;
    }
    // Utiliser getCurrentInpaintModel() car en mode EDIT c'est toujours de l'inpainting
    const model = typeof getCurrentInpaintModel === 'function'
        ? getCurrentInpaintModel()
        : (selectedInpaintModel || 'epiCRealism XL (Moyen)');
    console.log(`[EDIT] Modèle inpaint par défaut: ${model}`);
    return model;
}

// Initialiser les presets et model au chargement
document.addEventListener('DOMContentLoaded', function() {
    hydrateEditToolbar();
    loadEditPresets();
    loadEditSelectedModel();
    refreshEditChrome(document.getElementById('edit-modal') || document);
    const videoPrompt = document.getElementById('edit-video-prompt');
    videoPrompt?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            generateVideoFromEdit();
        }
        if (event.key === 'Escape') {
            videoPrompt.classList.remove('is-open');
            updateEditVideoPromptVisibility();
        }
    });
});

window.addEventListener('joyboy:locale-changed', () => {
    hydrateEditToolbar();
    updateBrushModeIndicator();
    renderEditPresets();
    updateEditVideoPromptVisibility();
});

// ===== EDIT IMAGE ACTIONS =====

/**
 * Télécharge l'image de l'éditeur
 */
function downloadEditImage() {
    const img = document.getElementById('edit-image');
    if (!img || !img.src) return;

    const link = document.createElement('a');
    link.href = img.src;
    link.download = (APP_CONFIG?.name?.toLowerCase() || 'joyboy') + '_' + Date.now() + '.png';
    link.click();
}

/**
 * Upscale l'image de l'éditeur avec Real-ESRGAN x2
 */
async function upscaleEditImage() {
    const img = document.getElementById('edit-image');
    if (!img || !img.src) return;

    // Sauvegarder l'image source et le modèle actuel
    const sourceImage = img.src;
    const model = typeof getCurrentImageModel === 'function' ? getCurrentImageModel() : 'epiCRealism XL (Moyen)';

    // Fermer l'éditeur et afficher le chat
    closeEditModal();
    showChat();

    // Créer un chat si nécessaire
    if (!currentChatId) {
        await createNewChat();
    }

    // Ajouter message utilisateur avec miniature
    addUserMessageWithThumb('Upscale x2', sourceImage);

    // Ajouter skeleton pour le résultat
    addImageSkeletonToChat();

    isGenerating = true;
    currentGenerationMode = 'image';
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);

    // Démarrer le polling de preview
    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.upscale({
            image: sourceImage,
            model: model,
            chat_model: userSettings.chatModel || 'qwen3.5:2b'
        });

        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();

        const data = result.data;
        const genTime = Date.now() - startTime;

        if (data?.success && data.image) {
            const resultImage = 'data:image/png;base64,' + data.image;
            replaceImageSkeletonWithReal(resultImage, genTime);
            modifiedImage = resultImage;
        } else {
            replaceImageSkeletonWithError(data?.error || 'Erreur upscale');
        }
    } catch (e) {
        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();
        replaceImageSkeletonWithError('Erreur: ' + e.message);
    } finally {
        isGenerating = false;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
    }
}

/**
 * Agrandit l'image de l'éditeur avec outpainting
 */
async function expandEditImage() {
    const img = document.getElementById('edit-image');
    if (!img || !img.src) return;

    // Sauvegarder l'image source
    const sourceImage = img.src;
    const model = typeof getCurrentImageModel === 'function' ? getCurrentImageModel() : 'epiCRealism XL (Moyen)';

    // Fermer l'éditeur et afficher le chat
    closeEditModal();
    showChat();

    // Créer un chat si nécessaire
    if (!currentChatId) {
        await createNewChat();
    }

    // Ajouter message utilisateur avec miniature
    addUserMessageWithThumb('Agrandir l\'image', sourceImage);

    // Ajouter skeleton pour le résultat
    addImageSkeletonToChat();

    isGenerating = true;
    currentGenerationMode = 'image';
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);

    // Démarrer le polling de preview
    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.expand({
            image: sourceImage,
            model: model,
            chat_model: userSettings.chatModel || 'qwen3.5:2b'
        });

        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();

        const data = result.data;
        const genTime = Date.now() - startTime;

        if (data?.success && data.image) {
            const resultImage = 'data:image/png;base64,' + data.image;
            replaceImageSkeletonWithReal(resultImage, genTime);
            modifiedImage = resultImage;
        } else {
            replaceImageSkeletonWithError(data?.error || 'Erreur expansion');
        }
    } catch (e) {
        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();
        replaceImageSkeletonWithError('Erreur: ' + e.message);
    } finally {
        isGenerating = false;
        currentGenerationId = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
    }
}


/**
 * Génère une vidéo depuis l'éditeur d'image
 */
async function generateVideoFromEdit() {
    const img = document.getElementById('edit-image');
    if (!img || !img.src) return;

    const sourceImage = img.src;
        const videoModel = userSettings.videoModel || 'svd';
    const videoDefaults = getVideoModelDefaults(videoModel);
    const supportsPrompt = videoModel !== 'svd';

    // Lire le prompt si le modèle le supporte
    const promptInput = document.getElementById('edit-video-prompt');
    const prompt = (promptInput && supportsPrompt) ? promptInput.value.trim() : '';

    // Params selon le modèle
    const targetFrames = videoDefaults.frames;
    const numSteps = videoDefaults.steps;
    const modelName = videoDefaults.name;

    // Fermer l'éditeur et afficher le chat
    closeEditModal();
    showChat();

    if (!currentChatId) {
        await createNewChat();
    }

    const promptText = prompt ? prompt.substring(0, 40) + '...' : '';
    addUserMessageWithThumb(`🎬 ${modelName}${promptText ? ' - ' + promptText : ''}`, sourceImage);

    addVideoSkeletonToChat(sourceImage);

    isGenerating = true;
    currentGenerationMode = 'video';
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);

    startVideoProgressPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.generateVideo({
            image: sourceImage,
            prompt: prompt,
            video_model: videoModel,
            target_frames: targetFrames,
            num_steps: numSteps,
            fps: videoDefaults.fps,
            add_audio: userSettings.videoAudio === true,
            face_restore: userSettings.faceRestore || 'off',
            chat_model: userSettings.chatModel || 'qwen3.5:2b',
            chatId: typeof currentChatId !== 'undefined' ? currentChatId : null,
            quality: userSettings.videoQuality || '720p',
            refine_passes: parseInt(userSettings.videoRefine) || 0,
            allow_experimental_video: userSettings.showAdvancedVideoModels === true
        });

        stopVideoProgressPolling();
        const data = result.data;
        const genTime = Date.now() - startTime;

        if (data?.success && data.video) {
            const videoFormat = data.format || 'mp4';
            if (typeof _lastVideoContext !== 'undefined') {
                _lastVideoContext.prompt = prompt;
                _lastVideoContext.canContinue = data.canContinue;
            }
            replaceVideoSkeletonWithReal(null, videoFormat, genTime, currentChatId);
        } else {
            replaceVideoSkeletonWithError(data?.error || 'Erreur génération vidéo');
        }
    } catch (e) {
        stopVideoProgressPolling();
        replaceVideoSkeletonWithError('Erreur: ' + e.message);
    } finally {
        isGenerating = false;
        currentGenerationId = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
    }
}
