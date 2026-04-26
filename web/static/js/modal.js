// ===== MODAL - Image view modal =====

function modalT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

let currentOriginalImage = null;
let currentModifiedImage = null;
let selectedCompareImage = null;  // Image sélectionnée pour comparaison (depuis la liste)
let videoFps = 14;  // FPS par défaut (14 = plus naturel, 20 = plus fluide)
let imageRotation = 0;  // Rotation courante en degrés

/**
 * Toggle entre 14fps et 20fps pour la génération vidéo
 */
function toggleVideoFps() {
    videoFps = videoFps === 14 ? 20 : 14;
    const fpsValue = document.getElementById('fps-value');
    if (fpsValue) {
        fpsValue.textContent = videoFps;
    }
}

function openModal(original, modified, showOriginal = false) {
    currentOriginalImage = original;
    currentModifiedImage = modified;
    const modal = document.getElementById('modal-view');
    const mainImg = document.getElementById('modal-main-image');
    const origThumb = document.getElementById('thumb-original');
    const modThumb = document.getElementById('thumb-modified');
    const compareContainer = document.getElementById('thumb-compare-container');

    // Réafficher les thumbnails (openModalSingle peut les avoir cachées)
    const thumbs = modal.querySelector('.modal-thumbs');
    if (thumbs) thumbs.style.display = '';

    // Afficher l'image demandée (original ou modified)
    if (showOriginal) {
        mainImg.src = original;
        origThumb?.classList.add('active');
        modThumb?.classList.remove('active');
    } else {
        mainImg.src = modified;
        modThumb?.classList.add('active');
        origThumb?.classList.remove('active');
    }

    if (origThumb) origThumb.src = original;
    if (modThumb) modThumb.src = modified;

    // Afficher le bouton comparer seulement si original != modified
    if (compareContainer) {
        compareContainer.style.display = (original !== modified) ? 'block' : 'none';
    }

    // Cacher le compare overlay si ouvert
    hideCompare();

    // Reset X-Ray overlay
    hideXRayOverlay();

    // Créer les contrôles X-Ray seulement si images différentes
    if (original !== modified) {
        createXRayControls();
    } else {
        // Supprimer les contrôles si images identiques
        const existingControls = document.getElementById('xray-controls');
        if (existingControls) existingControls.remove();
    }

    modal.style.display = 'flex';

    // Reset zoom + rotation
    zoomLevel = 1;
    panX = 0;
    panY = 0;
    imageRotation = 0;
    updateImageTransform();
}

function openModalSingle(image) {
    currentOriginalImage = image;
    currentModifiedImage = image;
    const modal = document.getElementById('modal-view');
    const mainImg = document.getElementById('modal-main-image');

    mainImg.src = image;

    // Cacher les thumbnails (pas de before/after pour une image seule)
    const thumbs = modal.querySelector('.modal-thumbs');
    if (thumbs) thumbs.style.display = 'none';

    // Cacher le compare overlay et reset X-Ray
    hideCompare();
    hideXRayOverlay();
    const existingControls = document.getElementById('xray-controls');
    if (existingControls) existingControls.remove();

    modal.style.display = 'flex';

    zoomLevel = 1;
    panX = 0;
    panY = 0;
    imageRotation = 0;
    updateImageTransform();
}

/**
 * Ouvre la modal depuis un clic sur une image inpainting (before/after).
 * Trouve automatiquement l'original et le modified dans le conteneur parent.
 * Évite de mettre du base64 dans les attributs onclick.
 */
function openModalFromPair(clickedImg, showOriginal) {
    const container = clickedImg.closest('.result-images');
    if (!container) {
        openModalSingle(clickedImg.src);
        return;
    }
    const images = container.querySelectorAll('.result-image');
    // Original = première image, Modified = dernière (skip mask si 3-image layout)
    const original = images[0]?.src || clickedImg.src;
    const modified = images[images.length - 1]?.src || clickedImg.src;
    openModal(original, modified, showOriginal);
}

function closeModal() {
    document.getElementById('modal-view').style.display = 'none';
    document.getElementById('compare-image-list')?.classList.remove('open');
    selectedCompareImage = null;  // Reset la sélection
    zoomLevel = 1;
    panX = 0;
    panY = 0;
}

// Ferme la modal si on clique dans le vide (pas sur l'image ou les contrôles)
function initModalClickOutside() {
    const modal = document.getElementById('modal-view');
    if (!modal) return;

    let mouseDownTarget = null;
    let mouseDownPos = { x: 0, y: 0 };

    // Tracker où le mousedown a commencé
    modal.addEventListener('mousedown', (e) => {
        mouseDownTarget = e.target;
        mouseDownPos = { x: e.clientX, y: e.clientY };
    });

    modal.addEventListener('click', (e) => {
        // Ne pas fermer si un drag vient de se terminer (évite fermeture accidentelle)
        if (wasDragging) {
            return;
        }

        // Vérifier si c'est un vrai clic (mousedown et mouseup sur le même élément, sans mouvement)
        const dx = Math.abs(e.clientX - mouseDownPos.x);
        const dy = Math.abs(e.clientY - mouseDownPos.y);
        const movedTooMuch = dx > 10 || dy > 10;

        // Si on a bougé de plus de 10px, c'est un drag pas un clic
        if (movedTooMuch) {
            return;
        }

        // Si le mousedown n'était pas sur le même élément, c'est un drag release
        if (mouseDownTarget !== e.target) {
            return;
        }

        // Éléments qui ferment la modal quand on clique dessus
        const closeTriggers = ['modal-view', 'modal-body', 'modal-image-wrapper', 'compare-overlay', 'compare-container'];

        // Si on clique sur le fond (pas sur l'image, boutons, thumbs, slider) -> fermer
        if (closeTriggers.some(cls => e.target.id === cls || e.target.classList.contains(cls))) {
            // Mais pas si on clique sur le slider ou une image
            if (!e.target.closest('.compare-slider') && !e.target.closest('.compare-image') && !e.target.closest('img')) {
                closeModal();
            }
        }
    });
}

function selectModalImage(src) {
    document.getElementById('modal-main-image').src = src;
    zoomLevel = 1;
    panX = 0;
    panY = 0;
    updateImageTransform();
}

function updateImageTransform() {
    const img = document.getElementById('modal-main-image');
    if (!img) return;
    const rotateStr = imageRotation ? ` rotate(${imageRotation}deg)` : '';
    const transform = `scale(${zoomLevel}) translate(${panX}px, ${panY}px)${rotateStr}`;
    img.style.transform = transform;

    // Appliquer le MÊME transform à l'overlay X-Ray (aligné sur l'image)
    const xrayOverlay = document.getElementById('xray-overlay');
    if (xrayOverlay) {
        xrayOverlay.style.transform = transform;
        xrayOverlay.style.left = img.offsetLeft + 'px';
        xrayOverlay.style.top = img.offsetTop + 'px';
    }
}

function downloadImage() {
    const img = document.getElementById('modal-main-image');
    if (!img || !img.src) return;

    // Si rotation appliquée, exporter le canvas tourné
    if (imageRotation % 360 !== 0) {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const rad = (imageRotation % 360) * Math.PI / 180;
        const abs90 = Math.abs(imageRotation % 360) === 90 || Math.abs(imageRotation % 360) === 270;
        canvas.width = abs90 ? img.naturalHeight : img.naturalWidth;
        canvas.height = abs90 ? img.naturalWidth : img.naturalHeight;
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate(rad);
        ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
        canvas.toBlob(blob => {
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = (APP_CONFIG?.name?.toLowerCase() || 'joyboy') + '_' + Date.now() + '.png';
            link.click();
            URL.revokeObjectURL(url);
        }, 'image/png');
        return;
    }

    const link = document.createElement('a');
    link.href = img.src;
    link.download = (APP_CONFIG?.name?.toLowerCase() || 'joyboy') + '_' + Date.now() + '.png';
    link.click();
}

function rotateImage(degrees) {
    imageRotation = (imageRotation + degrees) % 360;
    updateImageTransform();
}

function copyImageToClipboard() {
    const img = document.getElementById('modal-main-image');
    if (!img || !img.src) return;

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    // Appliquer la rotation si nécessaire
    const rad = (imageRotation % 360) * Math.PI / 180;
    const abs90 = Math.abs(imageRotation % 360) === 90 || Math.abs(imageRotation % 360) === 270;
    canvas.width = abs90 ? img.naturalHeight : img.naturalWidth;
    canvas.height = abs90 ? img.naturalWidth : img.naturalHeight;
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(rad);
    ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);

    canvas.toBlob(blob => {
        navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]).then(() => {
            // Feedback visuel temporaire sur le bouton
            const btn = document.querySelector('.modal-header [onclick*="copyImage"]');
            if (btn) {
                const orig = btn.innerHTML;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00d4aa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Copié';
                setTimeout(() => { btn.innerHTML = orig; }, 1500);
            }
        }).catch(() => {
            // Fallback: ouvrir dans un nouvel onglet
            window.open(img.src, '_blank');
        });
    }, 'image/png');
}

// ===== MODAL ZOOM/PAN =====
function initModalZoom() {
    const modal = document.getElementById('modal-view');
    if (!modal) return;

    // Initialiser le slider de comparaison
    initCompareSlider();

    // Initialiser click-outside-to-close
    initModalClickOutside();

    modal.addEventListener('wheel', function(e) {
        if (e.target.id !== 'modal-main-image') return;
        e.preventDefault();

        const zoomIndicator = document.getElementById('zoom-level');

        if (e.deltaY < 0) {
            zoomLevel = Math.min(5, zoomLevel + 0.2);
        } else {
            zoomLevel = Math.max(0.5, zoomLevel - 0.2);
        }

        if (zoomLevel <= 1) {
            panX = 0;
            panY = 0;
        }

        updateImageTransform();
        zoomIndicator.textContent = Math.round(zoomLevel * 100) + '%';
        zoomIndicator.classList.add('visible');

        clearTimeout(zoomTimeout);
        zoomTimeout = setTimeout(() => {
            zoomIndicator.classList.remove('visible');
        }, 1000);
    });

    const mainImg = document.getElementById('modal-main-image');
    if (mainImg) {
        mainImg.addEventListener('mousedown', function(e) {
            if (zoomLevel <= 1) return;
            isDragging = true;
            lastX = e.clientX;
            lastY = e.clientY;
            mainImg.classList.add('dragging');
            // Aussi pour l'overlay X-Ray
            const xrayOverlay = document.getElementById('xray-overlay');
            if (xrayOverlay) xrayOverlay.classList.add('dragging');
            e.preventDefault();
        });

        // Gérer le drag natif du navigateur (quand on drag une image pour la sauvegarder)
        mainImg.addEventListener('dragstart', function() {
            wasDragging = true;
        });
        mainImg.addEventListener('dragend', function() {
            // Reset après que l'event click soit passé
            setTimeout(() => { wasDragging = false; }, 100);
        });
    }

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        panX += dx / zoomLevel;
        panY += dy / zoomLevel;
        updateImageTransform();
    });

    document.addEventListener('mouseup', function() {
        if (isDragging) {
            isDragging = false;
            wasDragging = true;  // Marquer qu'un drag vient de se terminer
            document.getElementById('modal-main-image')?.classList.remove('dragging');
            // Aussi pour l'overlay X-Ray
            document.getElementById('xray-overlay')?.classList.remove('dragging');
            // Reset après un court délai (après que l'event click soit passé)
            setTimeout(() => { wasDragging = false; }, 50);
        }
    });
}

// ===== THUMBNAIL SELECTION =====
// (Fonctions showOriginal et showModified déplacées dans la section COMPARISON SLIDER)

// ===== COMPARISON SLIDER =====
let compareSliderActive = false;
let wasDragging = false;  // Track si un drag vient de se terminer (pour éviter fermeture accidentelle)

// Images actuellement comparées (pour le X-Ray)
let compareBeforeImage = null;
let compareAfterImage = null;

function showCompare() {
    // Utiliser l'image sélectionnée ou l'originale
    const compareWith = selectedCompareImage || currentOriginalImage;

    if (!compareWith || !currentModifiedImage || compareWith === currentModifiedImage) {
        return; // Pas de comparaison si même image
    }

    const overlay = document.getElementById('compare-overlay');
    const beforeImg = document.getElementById('compare-before');
    const afterImg = document.getElementById('compare-after');
    const origThumb = document.getElementById('thumb-original');
    const modThumb = document.getElementById('thumb-modified');
    const compareThumb = document.getElementById('thumb-compare');
    const mainWrapper = document.querySelector('.modal-image-wrapper');

    beforeImg.src = compareWith;
    afterImg.src = currentModifiedImage;

    // Stocker les images comparées pour le X-Ray
    compareBeforeImage = compareWith;
    compareAfterImage = currentModifiedImage;

    // Cacher l'image principale, montrer le comparateur
    mainWrapper.style.display = 'none';
    overlay.style.display = 'flex';

    // IMPORTANT: Cacher les contrôles X-Ray de la vue modale normale
    const modalXrayControls = document.getElementById('xray-controls');
    if (modalXrayControls) modalXrayControls.style.display = 'none';

    // Mettre à jour les thumbnails actifs
    origThumb?.classList.remove('active');
    modThumb?.classList.remove('active');
    compareThumb?.classList.add('active');

    // Reset slider à 50%
    updateCompareSlider(50);

    // Reset zoom du compare
    compareZoomLevel = 1;
    comparePanX = 0;
    comparePanY = 0;
    updateCompareZoom();

    // Activer le slider
    compareSliderActive = true;

    // Reset X-Ray du compare
    hideCompareXRayOverlay();

    // Créer les contrôles X-Ray pour le compare (si images différentes)
    createCompareXRayControls();
}

function hideCompare() {
    const overlay = document.getElementById('compare-overlay');
    const mainWrapper = document.querySelector('.modal-image-wrapper');
    const compareThumb = document.getElementById('thumb-compare');

    overlay.style.display = 'none';
    mainWrapper.style.display = 'flex';
    compareThumb?.classList.remove('active');
    compareSliderActive = false;

    // Reset les images comparées
    compareBeforeImage = null;
    compareAfterImage = null;

    // Cacher le X-Ray du compare
    hideCompareXRayOverlay();

    // Supprimer les contrôles X-Ray du compare
    const compareXrayControls = document.getElementById('compare-xray-controls');
    if (compareXrayControls) compareXrayControls.remove();

    // Réafficher les contrôles X-Ray de la modal normale (si images différentes)
    const modalXrayControls = document.getElementById('xray-controls');
    if (modalXrayControls && currentOriginalImage !== currentModifiedImage) {
        modalXrayControls.style.display = 'flex';
    }
}

function updateCompareSlider(percent) {
    const afterWrapper = document.querySelector('.compare-after-wrapper');
    const slider = document.querySelector('.compare-slider');

    if (afterWrapper && slider) {
        afterWrapper.style.clipPath = `inset(0 0 0 ${percent}%)`;
        slider.style.left = `${percent}%`;
    }
}

// Compare zoom state
let compareZoomLevel = 1;
let comparePanX = 0;
let comparePanY = 0;
let compareMagnifierActive = false;

function updateCompareZoom() {
    const overlay = document.getElementById('compare-overlay');
    const beforeImg = document.getElementById('compare-before');
    const afterImg = document.getElementById('compare-after');
    const transform = `scale(${compareZoomLevel}) translate(${comparePanX}px, ${comparePanY}px)`;

    if (beforeImg) beforeImg.style.transform = transform;
    if (afterImg) afterImg.style.transform = transform;

    // Appliquer aussi à l'overlay X-Ray du compare
    const compareXrayOverlay = document.getElementById('compare-xray-overlay');
    if (compareXrayOverlay) {
        compareXrayOverlay.style.transform = transform;
    }

    // Ajouter/retirer la classe zoomed pour changer le curseur
    if (overlay) {
        if (compareZoomLevel > 1) {
            overlay.classList.add('zoomed');
        } else {
            overlay.classList.remove('zoomed');
        }
    }
}

function initCompareSlider() {
    const overlay = document.getElementById('compare-overlay');
    if (!overlay) return;

    let isDraggingSlider = false;
    let isDraggingCompare = false;
    let lastCompareX = 0;
    let lastCompareY = 0;

    const getPercent = (e) => {
        const container = overlay.querySelector('.compare-container');
        const rect = container.getBoundingClientRect();
        const x = (e.clientX || e.touches?.[0]?.clientX) - rect.left;
        return Math.max(0, Math.min(100, (x / rect.width) * 100));
    };

    const slider = overlay.querySelector('.compare-slider');

    // Curseur sur le slider handle
    if (slider) {
        slider.style.cursor = 'col-resize';

        slider.addEventListener('mousedown', (e) => {
            isDraggingSlider = true;
            overlay.style.cursor = 'col-resize';
            e.preventDefault();
            e.stopPropagation();
        });

        slider.addEventListener('touchstart', (e) => {
            isDraggingSlider = true;
            e.preventDefault();
        });
    }

    // Mousedown sur l'overlay (pas le slider) = pan si zoomé
    overlay.addEventListener('mousedown', (e) => {
        // Ignorer si c'est le slider
        if (e.target.closest('.compare-slider')) return;

        // Pan si zoomé
        if (compareZoomLevel > 1) {
            isDraggingCompare = true;
            lastCompareX = e.clientX;
            lastCompareY = e.clientY;
            overlay.style.cursor = 'grabbing';
        }
    });

    overlay.addEventListener('touchstart', (e) => {
        if (e.target.closest('.compare-slider')) return;

        if (compareZoomLevel > 1) {
            isDraggingCompare = true;
            lastCompareX = e.touches[0].clientX;
            lastCompareY = e.touches[0].clientY;
        }
    });

    // Mousemove global
    document.addEventListener('mousemove', (e) => {
        // Ignorer si on drag le slider d'opacité du ghost
        if (e.target.closest('.compare-xray-slider-container')) return;

        if (isDraggingSlider) {
            updateCompareSlider(getPercent(e));
        } else if (isDraggingCompare && compareZoomLevel > 1) {
            const dx = e.clientX - lastCompareX;
            const dy = e.clientY - lastCompareY;
            lastCompareX = e.clientX;
            lastCompareY = e.clientY;
            comparePanX += dx / compareZoomLevel;
            comparePanY += dy / compareZoomLevel;
            updateCompareZoom();
        }
    });

    document.addEventListener('touchmove', (e) => {
        if (e.target.closest('.compare-xray-slider-container')) return;

        if (isDraggingSlider) {
            updateCompareSlider(getPercent(e));
        } else if (isDraggingCompare && compareZoomLevel > 1) {
            const dx = e.touches[0].clientX - lastCompareX;
            const dy = e.touches[0].clientY - lastCompareY;
            lastCompareX = e.touches[0].clientX;
            lastCompareY = e.touches[0].clientY;
            comparePanX += dx / compareZoomLevel;
            comparePanY += dy / compareZoomLevel;
            updateCompareZoom();
        }
    });

    // Mouseup global
    document.addEventListener('mouseup', () => {
        const wasSlider = isDraggingSlider;
        isDraggingSlider = false;
        isDraggingCompare = false;
        // Remettre le bon curseur
        if (compareZoomLevel > 1) {
            overlay.style.cursor = 'grab';
        } else {
            overlay.style.cursor = '';
        }
    });

    document.addEventListener('touchend', () => {
        isDraggingSlider = false;
        isDraggingCompare = false;
    });

    // Zoom avec la molette
    overlay.addEventListener('wheel', (e) => {
        e.preventDefault();

        const zoomIndicator = document.getElementById('zoom-level');

        if (e.deltaY < 0) {
            compareZoomLevel = Math.min(5, compareZoomLevel + 0.2);
        } else {
            compareZoomLevel = Math.max(1, compareZoomLevel - 0.2);
        }

        // Reset pan si zoom <= 1
        if (compareZoomLevel <= 1) {
            comparePanX = 0;
            comparePanY = 0;
            overlay.style.cursor = '';
        } else {
            overlay.style.cursor = 'grab';
        }

        updateCompareZoom();

        // Afficher l'indicateur de zoom
        if (zoomIndicator) {
            zoomIndicator.textContent = Math.round(compareZoomLevel * 100) + '%';
            zoomIndicator.classList.add('visible');
            clearTimeout(zoomTimeout);
            zoomTimeout = setTimeout(() => {
                zoomIndicator.classList.remove('visible');
            }, 1000);
        }

        // Changer le curseur selon le zoom
        overlay.style.cursor = compareZoomLevel > 1 ? 'grab' : '';
    });
}

// ===== X-RAY / GHOST OVERLAY =====
// Affiche les éléments supprimés (ex: vêtements) en transparence par-dessus l'image modifiée
// Permet de "voir à travers" les modifications comme un effet X-Ray

let xrayOverlayActive = false;
let xrayOpacity = 0.4;  // Opacité par défaut (40%)
let xrayDifferenceCanvas = null;  // Canvas avec les différences calculées

/**
 * Cache l'overlay X-Ray et reset l'état
 */
function hideXRayOverlay() {
    const overlay = document.getElementById('xray-overlay');
    if (overlay) overlay.style.display = 'none';
    const btn = document.getElementById('xray-toggle-btn');
    if (btn) btn.classList.remove('active');
    xrayOverlayActive = false;
    xrayDifferenceCanvas = null;
    const sliderContainer = document.querySelector('.xray-slider-container');
    if (sliderContainer) sliderContainer.style.display = 'none';
}

// Modifier showOriginal et showModified pour cacher le compare et le X-Ray
function showOriginal() {
    hideCompare();
    hideXRayOverlay();  // Cacher le X-Ray quand on change d'image
    const mainImg = document.getElementById('modal-main-image');
    const origThumb = document.getElementById('thumb-original');
    const modThumb = document.getElementById('thumb-modified');

    if (currentOriginalImage) {
        mainImg.src = currentOriginalImage;
    }

    origThumb?.classList.add('active');
    modThumb?.classList.remove('active');

    // Cacher les contrôles X-Ray sur l'original (pas de sens de voir le ghost)
    const xrayControls = document.getElementById('xray-controls');
    if (xrayControls) xrayControls.style.display = 'none';

    zoomLevel = 1;
    panX = 0;
    panY = 0;
    updateImageTransform();
}

function showModified() {
    hideCompare();
    hideXRayOverlay();  // Cacher le X-Ray quand on change d'image
    const mainImg = document.getElementById('modal-main-image');
    const origThumb = document.getElementById('thumb-original');
    const modThumb = document.getElementById('thumb-modified');

    if (currentModifiedImage) {
        mainImg.src = currentModifiedImage;
    }

    modThumb?.classList.add('active');
    origThumb?.classList.remove('active');

    // Réafficher les contrôles X-Ray sur le modifié (si images différentes)
    const xrayControls = document.getElementById('xray-controls');
    if (xrayControls && currentOriginalImage !== currentModifiedImage) {
        xrayControls.style.display = 'flex';
    }

    zoomLevel = 1;
    panX = 0;
    panY = 0;
    updateImageTransform();
}

/**
 * Crée un masque binaire dilaté à partir des différences
 * @param {Uint8ClampedArray} diffAlpha - Canal alpha des différences
 * @param {number} width - Largeur de l'image
 * @param {number} height - Hauteur de l'image
 * @param {number} radius - Rayon de dilatation
 * @returns {Uint8Array} Masque binaire dilaté (0 ou 255)
 */
function createDilatedMask(diffAlpha, width, height, radius = 2) {
    const mask = new Uint8Array(width * height);

    // Créer le masque initial
    for (let i = 0; i < diffAlpha.length; i++) {
        mask[i] = diffAlpha[i] > 0 ? 255 : 0;
    }

    // Dilater le masque
    const dilated = new Uint8Array(mask);
    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const idx = y * width + x;
            if (mask[idx] > 0) continue; // Déjà dans le masque

            // Chercher un voisin dans le rayon
            let found = false;
            for (let dy = -radius; dy <= radius && !found; dy++) {
                for (let dx = -radius; dx <= radius && !found; dx++) {
                    if (dx * dx + dy * dy > radius * radius) continue;
                    const nx = x + dx;
                    const ny = y + dy;
                    if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
                    if (mask[ny * width + nx] > 0) {
                        found = true;
                    }
                }
            }
            if (found) dilated[idx] = 255;
        }
    }

    return dilated;
}

/**
 * Calcule la différence entre deux images et retourne un canvas avec les parties "supprimées"
 * @param {string} originalSrc - URL de l'image originale
 * @param {string} modifiedSrc - URL de l'image modifiée
 * @returns {Promise<HTMLCanvasElement>} Canvas avec les différences
 */
async function computeImageDifference(originalSrc, modifiedSrc) {
    console.log('[X-RAY] Calcul des différences...');
    console.log('[X-RAY] Original type:', originalSrc?.startsWith('data:') ? 'data URL' : 'URL');
    console.log('[X-RAY] Modified type:', modifiedSrc?.startsWith('data:') ? 'data URL' : 'URL');

    return new Promise((resolve, reject) => {
        const origImg = new Image();
        const modImg = new Image();
        let loadCount = 0;
        let loadError = false;

        const onLoad = () => {
            if (loadError) return;
            loadCount++;
            console.log(`[X-RAY] Image chargée (${loadCount}/2) - orig: ${origImg.width}x${origImg.height}, mod: ${modImg.width}x${modImg.height}`);
            if (loadCount < 2) return;

            try {
                // Utiliser la taille de l'image modifiée comme référence
                const width = modImg.naturalWidth || modImg.width;
                const height = modImg.naturalHeight || modImg.height;

                if (width === 0 || height === 0) {
                    throw new Error(`Dimensions invalides: ${width}x${height}`);
                }

                console.log(`[X-RAY] Taille de travail: ${width}x${height}`);

                // Créer le canvas de sortie
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d', { willReadFrequently: true });
                canvas.width = width;
                canvas.height = height;

                // Canvas temporaires pour lire les pixels
                const origCanvas = document.createElement('canvas');
                const origCtx = origCanvas.getContext('2d', { willReadFrequently: true });
                origCanvas.width = width;
                origCanvas.height = height;
                origCtx.drawImage(origImg, 0, 0, width, height);

                const modCanvas = document.createElement('canvas');
                const modCtx = modCanvas.getContext('2d', { willReadFrequently: true });
                modCanvas.width = width;
                modCanvas.height = height;
                modCtx.drawImage(modImg, 0, 0, width, height);

                // Lire les pixels
                let origData, modData;
                try {
                    origData = origCtx.getImageData(0, 0, width, height);
                    modData = modCtx.getImageData(0, 0, width, height);
                } catch (securityError) {
                    console.error('[X-RAY] Erreur de sécurité lors de la lecture des pixels:', securityError);
                    throw new Error('Impossible de lire les pixels (CORS)');
                }

                // Étape 1: Détecter les pixels différents (masque binaire)
                const threshold = 25;
                const diffAlpha = new Uint8Array(width * height);
                let diffPixels = 0;
                const totalPixels = width * height;

                for (let i = 0; i < origData.data.length; i += 4) {
                    const pixelIdx = i / 4;
                    const rDiff = Math.abs(origData.data[i] - modData.data[i]);
                    const gDiff = Math.abs(origData.data[i + 1] - modData.data[i + 1]);
                    const bDiff = Math.abs(origData.data[i + 2] - modData.data[i + 2]);
                    const totalDiff = (rDiff + gDiff + bDiff) / 3;

                    if (totalDiff > threshold) {
                        diffAlpha[pixelIdx] = 255;
                        diffPixels++;
                    }
                }

                const diffPercent = ((diffPixels / totalPixels) * 100).toFixed(1);
                console.log(`[X-RAY] ${diffPixels} pixels différents (${diffPercent}%)`);

                if (diffPixels === 0) {
                    console.warn('[X-RAY] Aucune différence détectée!');
                }

                // Étape 2: Dilater le masque binaire (2px pour combler les petits trous)
                const dilatedMask = createDilatedMask(diffAlpha, width, height, 2);

                // Étape 3: Copier les pixels originaux là où le masque est actif
                const diffData = ctx.createImageData(width, height);
                let finalPixels = 0;

                for (let i = 0; i < origData.data.length; i += 4) {
                    const pixelIdx = i / 4;
                    if (dilatedMask[pixelIdx] > 0) {
                        // Copier le pixel original directement (bords nets)
                        diffData.data[i] = origData.data[i];
                        diffData.data[i + 1] = origData.data[i + 1];
                        diffData.data[i + 2] = origData.data[i + 2];
                        diffData.data[i + 3] = 220;  // Légèrement transparent
                        finalPixels++;
                    } else {
                        diffData.data[i + 3] = 0;  // Transparent
                    }
                }

                const finalPercent = ((finalPixels / totalPixels) * 100).toFixed(1);
                console.log(`[X-RAY] ${finalPixels} pixels après dilatation (${finalPercent}%)`);

                ctx.putImageData(diffData, 0, 0);
                resolve(canvas);
            } catch (e) {
                console.error('[X-RAY] Erreur traitement:', e);
                reject(e);
            }
        };

        const onError = (which) => (e) => {
            loadError = true;
            console.error(`[X-RAY] Erreur chargement image ${which}:`, e);
            reject(new Error(`Erreur chargement image ${which}`));
        };

        origImg.onload = onLoad;
        modImg.onload = onLoad;
        origImg.onerror = onError('originale');
        modImg.onerror = onError('modifiée');

        // Pour les data URLs, pas besoin de crossOrigin
        if (!originalSrc.startsWith('data:')) {
            origImg.crossOrigin = 'anonymous';
        }
        if (!modifiedSrc.startsWith('data:')) {
            modImg.crossOrigin = 'anonymous';
        }

        origImg.src = originalSrc;
        modImg.src = modifiedSrc;
    });
}

/**
 * Active/désactive l'overlay X-Ray sur l'image modifiée
 * Utilise SegFormer pour détecter les vêtements proprement
 */
async function toggleXRayOverlay() {
    const btn = document.getElementById('xray-toggle-btn');
    const mainImg = document.getElementById('modal-main-image');

    if (xrayOverlayActive) {
        // Désactiver
        const overlay = document.getElementById('xray-overlay');
        if (overlay) overlay.style.display = 'none';
        if (btn) btn.classList.remove('active');
        xrayOverlayActive = false;
        // Cacher le slider
        const sliderContainer = document.querySelector('.xray-slider-container');
        if (sliderContainer) sliderContainer.style.display = 'none';
        console.log('[X-RAY] Désactivé');
        return;
    }

    // Activer
    if (!currentOriginalImage || !currentModifiedImage) {
        console.log('[X-RAY] Pas d\'images à comparer');
        return;
    }

    if (currentOriginalImage === currentModifiedImage) {
        console.log('[X-RAY] Images identiques, pas de différence');
        return;
    }

    // Afficher un loading
    if (btn) btn.classList.add('loading');

    try {
        const result = await apiGeneration.xrayMask({ image: currentOriginalImage });

        if (!result.data?.success) {
            throw new Error(result.data?.error || 'Erreur serveur');
        }

        const data = result.data;

        // Créer/mettre à jour l'overlay
        let overlayEl = document.getElementById('xray-overlay');
        const wrapper = document.querySelector('.modal-image-wrapper');

        if (!wrapper) {
            throw new Error('modal-image-wrapper non trouvé');
        }

        if (!overlayEl) {
            overlayEl = document.createElement('img');
            overlayEl.id = 'xray-overlay';
            overlayEl.className = 'xray-overlay';
            wrapper.appendChild(overlayEl);
        }

        // Utiliser l'image des vêtements retournée par le serveur
        overlayEl.src = 'data:image/png;base64,' + data.mask;
        overlayEl.style.opacity = xrayOpacity;
        overlayEl.style.display = 'block';

        // Positionner l'overlay exactement sur l'image principale
        // L'image est centrée par flexbox → utiliser offsetLeft/offsetTop pour aligner
        if (mainImg) {
            overlayEl.style.width = mainImg.offsetWidth + 'px';
            overlayEl.style.height = mainImg.offsetHeight + 'px';
            overlayEl.style.left = mainImg.offsetLeft + 'px';
            overlayEl.style.top = mainImg.offsetTop + 'px';
            overlayEl.style.transform = `scale(${zoomLevel}) translate(${panX}px, ${panY}px)`;
            overlayEl.style.transformOrigin = 'center center';
        }

        xrayOverlayActive = true;
        if (btn) {
            btn.classList.remove('loading');
            btn.classList.add('active');
        }

        // Afficher le slider d'opacité
        const sliderContainer = document.querySelector('.xray-slider-container');
        if (sliderContainer) sliderContainer.style.display = 'flex';

        console.log('[X-RAY] Overlay activé avec SegFormer');

    } catch (e) {
        console.error('[X-RAY] Erreur:', e);
        if (btn) btn.classList.remove('loading');
        await JoyDialog.alert(modalT('modal.xrayError', 'Erreur X-Ray : {error}', { error: e.message }), { variant: 'danger' });
    }
}

/**
 * Change l'opacité de l'overlay X-Ray
 * @param {number} opacity - Valeur entre 0 et 1
 */
function setXRayOpacity(opacity) {
    xrayOpacity = Math.max(0, Math.min(1, opacity));
    const overlay = document.getElementById('xray-overlay');
    if (overlay) {
        overlay.style.opacity = xrayOpacity;
        console.log('[X-RAY] Opacité:', xrayOpacity);
    }

    // Mettre à jour le slider si présent
    const slider = document.getElementById('xray-opacity-slider');
    if (slider && parseFloat(slider.value) / 100 !== xrayOpacity) {
        slider.value = xrayOpacity * 100;
    }
}

/**
 * Crée les contrôles X-Ray dans la modal
 */
function createXRayControls() {
    console.log('[X-RAY] Création des contrôles...');

    // Supprimer l'ancien si existe pour recréer proprement
    const existingControls = document.getElementById('xray-controls');
    if (existingControls) existingControls.remove();

    const imageWrapper = document.querySelector('#modal-view .modal-image-wrapper');
    if (!imageWrapper) {
        console.log('[X-RAY] modal-image-wrapper non trouvé');
        return;
    }

    const controls = document.createElement('div');
    controls.id = 'xray-controls';
    controls.className = 'xray-controls';
    controls.innerHTML = `
        <button id="xray-toggle-btn" class="xray-btn" onclick="toggleXRayOverlay()" title="Effet Ghost (voir les vêtements supprimés)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            Ghost
        </button>
        <div class="xray-slider-container" style="display: none;">
            <label>Opacité:</label>
            <input type="range" id="xray-opacity-slider" min="0" max="100" value="40"
                   oninput="setXRayOpacity(this.value / 100); document.getElementById('xray-opacity-value').textContent = this.value + '%';">
            <span id="xray-opacity-value">40%</span>
        </div>
    `;

    // Ajouter dans modal-image-wrapper pour être centré juste sous l'image
    imageWrapper.appendChild(controls);
    console.log('[X-RAY] Contrôles ajoutés');
}

/**
 * Affiche/cache les contrôles de slider d'opacité
 */
function toggleXRaySlider() {
    const container = document.querySelector('.xray-slider-container');
    if (container) {
        container.style.display = container.style.display === 'none' ? 'flex' : 'none';
    }
}

// ===== COMPARE X-RAY / GHOST =====
// Version du X-Ray pour le mode comparaison

let compareXrayOverlayActive = false;
let compareXrayDifferenceCanvas = null;

/**
 * Cache l'overlay X-Ray du mode compare
 */
function hideCompareXRayOverlay() {
    const overlay = document.getElementById('compare-xray-overlay');
    if (overlay) overlay.style.display = 'none';
    const btn = document.getElementById('compare-xray-toggle-btn');
    if (btn) btn.classList.remove('active');
    compareXrayOverlayActive = false;
    compareXrayDifferenceCanvas = null;
    const sliderContainer = document.querySelector('.compare-xray-slider-container');
    if (sliderContainer) sliderContainer.style.display = 'none';
}

/**
 * Crée les contrôles X-Ray pour le mode compare
 */
function createCompareXRayControls() {
    console.log('[COMPARE X-RAY] Création des contrôles...');

    // Supprimer l'ancien si existe
    const existingControls = document.getElementById('compare-xray-controls');
    if (existingControls) existingControls.remove();

    const compareOverlay = document.getElementById('compare-overlay');
    if (!compareOverlay) {
        console.log('[COMPARE X-RAY] compare-overlay non trouvé');
        return;
    }

    const controls = document.createElement('div');
    controls.id = 'compare-xray-controls';
    controls.className = 'xray-controls';
    controls.innerHTML = `
        <button id="compare-xray-toggle-btn" class="xray-btn" onclick="toggleCompareXRayOverlay()" title="Effet Ghost (voir les différences)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            Ghost
        </button>
        <div class="compare-xray-slider-container xray-slider-container" style="display: none;">
            <label>Opacité:</label>
            <input type="range" id="compare-xray-opacity-slider" min="0" max="100" value="40"
                   oninput="setCompareXRayOpacity(this.value / 100); document.getElementById('compare-xray-opacity-value').textContent = this.value + '%';">
            <span id="compare-xray-opacity-value">40%</span>
        </div>
    `;

    compareOverlay.appendChild(controls);
    console.log('[COMPARE X-RAY] Contrôles ajoutés');
}

/**
 * Active/désactive l'overlay X-Ray en mode compare
 * Utilise SegFormer pour détecter les vêtements
 */
async function toggleCompareXRayOverlay() {
    const btn = document.getElementById('compare-xray-toggle-btn');
    const afterImg = document.getElementById('compare-after');

    if (compareXrayOverlayActive) {
        // Désactiver
        hideCompareXRayOverlay();
        console.log('[COMPARE X-RAY] Désactivé');
        return;
    }

    // Activer
    if (!compareBeforeImage || !compareAfterImage) {
        console.log('[COMPARE X-RAY] Pas d\'images à comparer');
        return;
    }

    if (btn) btn.classList.add('loading');

    try {
        const result = await apiGeneration.xrayMask({ image: compareBeforeImage });

        if (!result.data?.success) {
            throw new Error(result.data?.error || 'Erreur serveur');
        }

        const data = result.data;

        // Créer/mettre à jour l'overlay
        let overlayEl = document.getElementById('compare-xray-overlay');
        const container = document.querySelector('.compare-container');

        if (!container) {
            throw new Error('compare-container non trouvé');
        }

        if (!overlayEl) {
            overlayEl = document.createElement('img');
            overlayEl.id = 'compare-xray-overlay';
            overlayEl.className = 'xray-overlay compare-xray-overlay';
            container.appendChild(overlayEl);
        }

        // Utiliser l'image des vêtements retournée par le serveur
        overlayEl.src = 'data:image/png;base64,' + data.mask;
        overlayEl.style.opacity = xrayOpacity;
        overlayEl.style.display = 'block';

        // Appliquer le même transform que les images compare
        overlayEl.style.transform = `scale(${compareZoomLevel}) translate(${comparePanX}px, ${comparePanY}px)`;

        // Taille
        if (afterImg) {
            overlayEl.style.width = afterImg.offsetWidth + 'px';
            overlayEl.style.height = afterImg.offsetHeight + 'px';
        }

        compareXrayOverlayActive = true;
        if (btn) {
            btn.classList.remove('loading');
            btn.classList.add('active');
        }

        // Afficher le slider
        const sliderContainer = document.querySelector('.compare-xray-slider-container');
        if (sliderContainer) sliderContainer.style.display = 'flex';

        console.log('[COMPARE X-RAY] Overlay activé avec SegFormer');

    } catch (e) {
        console.error('[COMPARE X-RAY] Erreur:', e);
        if (btn) btn.classList.remove('loading');
        await JoyDialog.alert(modalT('modal.xrayCompareError', 'Erreur X-Ray Compare : {error}', { error: e.message }), { variant: 'danger' });
    }
}

/**
 * Change l'opacité de l'overlay X-Ray du compare
 */
function setCompareXRayOpacity(opacity) {
    const overlayOpacity = Math.max(0, Math.min(1, opacity));
    const overlay = document.getElementById('compare-xray-overlay');
    if (overlay) {
        overlay.style.opacity = overlayOpacity;
    }
}

// ===== IMAGE ACTIONS =====

/**
 * Upscale l'image avec Real-ESRGAN x2
 * Affiche la génération dans le chat comme les autres
 */
async function upscaleImage() {
    const img = document.getElementById('modal-main-image');
    if (!img || !img.src) return;

    // Sauvegarder l'image source et le modèle actuel
    const sourceImage = img.src;
    const model = typeof getCurrentImageModel === 'function' ? getCurrentImageModel() : 'epiCRealism XL (Moyen)';

    // Fermer le modal et afficher le chat
    closeModal();
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

        const genTime = Date.now() - startTime;

        if (result.data?.success && result.data?.image) {
            const resultImage = 'data:image/png;base64,' + result.data.image;
            replaceImageSkeletonWithReal(resultImage, genTime);
            modifiedImage = resultImage;
        } else {
            replaceImageSkeletonWithError(result.data?.error || 'Erreur upscale');
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
 * Expand/Outpaint l'image avec ControlNets
 * Affiche la génération dans le chat comme les autres
 */
async function expandImage() {
    const img = document.getElementById('modal-main-image');
    if (!img || !img.src) return;

    // Sauvegarder l'image source
    const sourceImage = img.src;
    const model = typeof getCurrentImageModel === 'function' ? getCurrentImageModel() : 'epiCRealism XL (Moyen)';

    // Fermer le modal et afficher le chat
    closeModal();
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

        const genTime = Date.now() - startTime;

        if (result.data?.success && result.data?.image) {
            const resultImage = 'data:image/png;base64,' + result.data.image;
            replaceImageSkeletonWithReal(resultImage, genTime);
            modifiedImage = resultImage;
        } else {
            replaceImageSkeletonWithError(result.data?.error || 'Erreur expansion');
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
 * Génère une vidéo à partir de l'image
 * Supporte SVD, CogVideoX-5B, CogVideoX-2B
 */
async function generateVideoFromImage() {
    const img = document.getElementById('modal-main-image');
    if (!img || !img.src) return;

    // Lire les paramètres
    const durationInput = document.getElementById('video-duration');
    const duration = durationInput ? parseInt(durationInput.value) || 4 : 4;
        const videoModel = userSettings.videoModel || 'svd';
    const videoDefaults = getVideoModelDefaults(videoModel);

    // Sauvegarder l'image source
    const sourceImage = img.src;

    // Fermer le modal et afficher le chat
    closeModal();
    showChat();

    // Créer un chat si nécessaire
    if (!currentChatId) {
        await createNewChat();
    }

    // Calculer les params selon le modèle
    const fps = videoDefaults.fps;
    const totalFrames = videoDefaults.frames;
    const numSteps = videoDefaults.steps;
    const modelName = videoDefaults.name;

    addUserMessageWithThumb(`🎬 ${modelName} - ${duration}s`, sourceImage);

    // Ajouter skeleton pour le résultat (vidéo)
    addVideoSkeletonToChat(sourceImage);

    isGenerating = true;
    currentGenerationMode = 'video';
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);
    if (typeof startVideoProgressPolling === 'function') startVideoProgressPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.generateVideo({
            image: sourceImage,
            video_model: videoModel,
            target_frames: totalFrames,
            num_steps: numSteps,
            fps: videoDefaults.fps,
            add_audio: userSettings.videoAudio === true,
            audio_engine: userSettings.videoAudioEngine || 'auto',
            face_restore: userSettings.faceRestore || 'off',
            chat_model: userSettings.chatModel || 'qwen3.5:2b',
            chatId: typeof currentChatId !== 'undefined' ? currentChatId : null,
            quality: userSettings.videoQuality || '720p',
            refine_passes: parseInt(userSettings.videoRefine) || 0,
            allow_experimental_video: userSettings.showAdvancedVideoModels === true
        });

        const genTime = Date.now() - startTime;

        if (result.data?.success && result.data?.video) {
            const videoFormat = result.data.format || 'mp4';
            if (typeof updateLastVideoContextFromResult === 'function') {
                updateLastVideoContextFromResult(result.data, '', sourceImage, currentChatId);
            }
            replaceVideoSkeletonWithReal(null, videoFormat, genTime, currentChatId, result.data);
        } else {
            replaceVideoSkeletonWithError(result.data?.error || 'Erreur génération vidéo');
        }
    } catch (e) {
        replaceVideoSkeletonWithError('Erreur: ' + e.message);
    } finally {
        if (typeof stopVideoProgressPolling === 'function') stopVideoProgressPolling();
        isGenerating = false;
        currentGenerationId = null;
        currentGenerationMode = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
    }
}

/**
 * Ajoute un skeleton loading pour une vidéo
 */
function addVideoSkeletonToChat(imageSrc, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null), options = {}) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;

    const startedAt = Date.now();
    const skeletonId = String(options?.skeletonId || `video-skeleton-${startedAt}-${Math.random().toString(36).slice(2, 8)}`);
    const label = options?.label ? escapeHtml(options.label) : '';
    const skeletonHtml = `
        <div class="message video-skeleton-message" data-chat-id="${chatId || ''}" data-skeleton-id="${skeletonId}" data-started-at="${startedAt}">
            <div class="ai-message">
                <div class="video-skeleton">
                    ${imageSrc ? `<img src="${imageSrc}" class="video-skeleton-thumb">` : ''}
                    <div class="video-skeleton-surface">
                        <div class="video-skeleton-grid"></div>
                    </div>
                    <div class="generation-progress-bar-container">
                        <div class="generation-progress-bar" style="width: 0%"></div>
                    </div>
                    <div class="generation-step-text">${label || 'Préparation...'}</div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', skeletonHtml);
    if (typeof saveCurrentChatHtml === 'function') {
        saveCurrentChatHtml('', messagesDiv.innerHTML, chatId);
    }
    scrollToBottom();
    return skeletonId;
}

/**
 * Remplace le skeleton vidéo par la vraie vidéo
 * Utilise l'URL serveur pour la persistance (pas le base64)
 */
function replaceVideoSkeletonWithReal(videoSrc, format, genTime, chatId, metadata = {}) {
    // Multiple generations can exist in one chat. Replace the newest active
    // video skeleton for this chat, not the first historical result from
    // another conversation.
    let scopedMessages = Array.from(document.querySelectorAll('.video-skeleton-message'))
        .filter(node => !chatId || node.dataset?.chatId === chatId);
    let skeletonHost = scopedMessages.at(-1) || (!chatId ? document : null);
    let skeleton = skeletonHost?.querySelector?.('.video-skeleton');
    if (!skeleton) {
        addVideoSkeletonToChat(metadata?.sourceImage || null, chatId, { label: 'Finalisation vidéo...' });
        scopedMessages = Array.from(document.querySelectorAll('.video-skeleton-message'))
            .filter(node => !chatId || node.dataset?.chatId === chatId);
        skeletonHost = scopedMessages.at(-1) || (!chatId ? document : null);
        skeleton = skeletonHost?.querySelector?.('.video-skeleton');
    }
    if (!skeleton) return false;

    const messageDiv = skeleton.closest('.message');
    if (!messageDiv) return false;
    // Once replaced, this message must no longer receive progress updates from
    // the global video-progress poller.
    messageDiv.classList.remove('video-skeleton-message');

    const isGif = format === 'gif';
    const timeText = genTime ? `${Math.round(genTime / 1000)}s` : '';
    const cacheTag = Date.now();

    // Utiliser l'URL serveur pour la persistance (le fichier est sauvé sur le serveur)
    const metadataSessionId = metadata?.videoSessionId || metadata?.video_session_id || null;
    const sourceSessionId = metadata?.sourceVideoSessionId || metadata?.source_video_session_id || null;
    const exactVideoUrl = metadataSessionId && metadataSessionId !== sourceSessionId
        ? `/videos/session/${metadataSessionId}?t=${cacheTag}`
        : null;
    const videoUrl = exactVideoUrl || (chatId ? `/videos/${chatId}?t=${cacheTag}` : videoSrc);
    const downloadUrl = videoUrl;
    const sourceType = format === 'webm' ? 'video/webm' : 'video/mp4';

    // Bouton Continuer si la continuation est dispo
    if (typeof updateLastVideoContextFromResult === 'function' && metadata && Object.keys(metadata).length) {
        updateLastVideoContextFromResult(metadata, metadata.prompt || '', null, chatId);
    }
    const canContinue = typeof _lastVideoContext !== 'undefined' && _lastVideoContext.canContinue;
    const videoSessionId = typeof _lastVideoContext !== 'undefined' ? _lastVideoContext.videoSessionId : null;
    const keyframeRail = typeof buildVideoKeyframeRail === 'function' && typeof _lastVideoContext !== 'undefined'
        ? buildVideoKeyframeRail(_lastVideoContext.anchors || [], videoSessionId)
        : '';
    const continueBtn = canContinue ? `
        <button class="video-control-btn video-control-btn-wide video-continue-btn" onclick="openVideoContinuationPanel({ videoSessionId: '${videoSessionId || ''}' })" title="Continuer la vidéo">
            <i data-lucide="play"></i> Continuer
        </button>
    ` : '';
    const continuationTools = typeof buildVideoContinuationTools === 'function'
        ? buildVideoContinuationTools(
            typeof _lastVideoContext !== 'undefined' ? (_lastVideoContext.anchors || []) : [],
            videoSessionId,
            continueBtn
        )
        : `
            <div class="video-continuation-tools">
                ${keyframeRail}
                ${continueBtn}
            </div>
        `;

    if (isGif) {
        // GIF - afficher comme image
        messageDiv.innerHTML = `
            <div class="ai-message">
                <img src="${videoUrl}" class="result-video-gif" alt="Animation générée">
                <div class="generation-time">${timeText}</div>
            </div>
        `;
    } else {
        // MP4 - player vidéo avec contrôles
        messageDiv.innerHTML = `
            <div class="ai-message">
                <div class="video-container video-result-container">
                    <div class="video-player-shell">
                        <video class="result-video" controls autoplay loop muted playsinline preload="auto" src="${videoUrl}" type="${sourceType}"></video>
                        <div class="video-controls">
                            <button class="video-control-btn" onclick="toggleVideoPlay(this)" data-playing="true"><i data-lucide="pause"></i></button>
                            <button class="video-control-btn" onclick="toggleVideoMute(this)" data-muted="true"><i data-lucide="volume-x"></i></button>
                            <button class="video-control-btn" onclick="toggleVideoFullscreen(this)"><i data-lucide="maximize"></i></button>
                            <a class="video-control-btn" href="${downloadUrl}" download="animation.mp4"><i data-lucide="download"></i></a>
                        </div>
                    </div>
                    ${continuationTools}
                </div>
                <div class="generation-time">${timeText}</div>
            </div>
        `;
    }
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [messageDiv] });
    const renderedVideo = messageDiv.querySelector('video.result-video');
    if (renderedVideo) {
        renderedVideo.load();
        renderedVideo.play?.().catch(() => {});
    }
    if (typeof saveCurrentChatHtml === 'function') {
        const messagesDiv = document.getElementById('chat-messages');
        const html = typeof getChatHtmlWithoutSkeleton === 'function' ? getChatHtmlWithoutSkeleton() : (messagesDiv?.innerHTML || '');
        saveCurrentChatHtml('', html, chatId);
    }
    scrollToBottom();
    return true;
}

/**
 * Remplace le skeleton vidéo par une erreur
 */
function replaceVideoSkeletonWithError(errorMsg, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    // Keep error handling aligned with success handling: target the newest
    // active skeleton for this chat and remove it from future progress updates.
    const scopedMessages = Array.from(document.querySelectorAll('.video-skeleton-message'))
        .filter(node => !chatId || node.dataset?.chatId === chatId);
    const skeletonHost = scopedMessages.at(-1) || (!chatId ? document : null);
    const skeleton = skeletonHost?.querySelector?.('.video-skeleton');
    if (!skeleton) return;

    const messageDiv = skeleton.closest('.message');
    if (!messageDiv) return;
    messageDiv.classList.remove('video-skeleton-message');

    messageDiv.innerHTML = `
        <div class="ai-message">
            <div class="error-message"><i data-lucide="x-circle" style="width:16px;height:16px;vertical-align:middle;margin-right:4px;"></i>${errorMsg}</div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
    if (typeof saveCurrentChatHtml === 'function') {
        const messagesDiv = document.getElementById('chat-messages');
        const html = typeof getChatHtmlWithoutSkeleton === 'function' ? getChatHtmlWithoutSkeleton() : (messagesDiv?.innerHTML || '');
        saveCurrentChatHtml('', html, chatId);
    }
    scrollToBottom();
}

/**
 * Toggle play/pause de la vidéo
 */
function toggleVideoPlay(btn) {
    const video = btn.closest('.video-container').querySelector('video');
    if (video.paused) {
        video.play();
        btn.innerHTML = '<i data-lucide="pause"></i>';
        btn.dataset.playing = 'true';
    } else {
        video.pause();
        btn.innerHTML = '<i data-lucide="play"></i>';
        btn.dataset.playing = 'false';
    }
    if (window.lucide) lucide.createIcons();
}

/**
 * Toggle mute de la vidéo
 */
function toggleVideoMute(btn) {
    const video = btn.closest('.video-container').querySelector('video');
    video.muted = !video.muted;
    btn.innerHTML = video.muted ? '<i data-lucide="volume-x"></i>' : '<i data-lucide="volume-2"></i>';
    btn.dataset.muted = video.muted ? 'true' : 'false';
    if (window.lucide) lucide.createIcons();
}

/**
 * Toggle fullscreen de la vidéo
 */
function toggleVideoFullscreen(btn) {
    const video = btn.closest('.video-container').querySelector('video');
    if (document.fullscreenElement) {
        document.exitFullscreen();
    } else {
        video.requestFullscreen().catch(e => console.log('Fullscreen error:', e));
    }
}

/**
 * Ajoute un message utilisateur simple avec une miniature
 */
function addUserMessageWithThumb(text, imageSrc, options = {}) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;

    const bubbleHtml = options.renderedHtml === true && typeof buildRenderedUserBubble === 'function'
        ? buildRenderedUserBubble(text, options.fullPrompt || text)
        : (typeof buildUserPromptBubble === 'function'
            ? buildUserPromptBubble(text, options.fullPrompt || text)
            : `<div class="user-bubble">${text}</div>`);
    const messageHtml = `
        <div class="message">
            <div class="user-message">
                ${bubbleHtml}
                <img src="${imageSrc}" class="user-thumb" onclick="openModalSingle(this.src)">
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    if (typeof saveCurrentChatHtml === 'function') {
        const html = typeof getChatHtmlWithoutSkeleton === 'function' ? getChatHtmlWithoutSkeleton() : messagesDiv.innerHTML;
        saveCurrentChatHtml('', html);
    }
    scrollToBottom();
}

// ===== COMPARE IMAGE SELECTION =====

function toggleCompareImageList(event) {
    event.stopPropagation();
    const list = document.getElementById('compare-image-list');
    const isOpen = list.classList.contains('open');

    if (isOpen) {
        list.classList.remove('open');
    } else {
        // Remplir la liste avec les images du chat
        populateCompareImageList();
        list.classList.add('open');
    }
}

function populateCompareImageList() {
    const container = document.getElementById('compare-image-items');
    if (!container) return;

    // Collecter toutes les images du chat
    const chatImages = [];
    const seenSrcs = new Set();  // Éviter les doublons

    // Helper pour ajouter une image sans doublon
    function addImage(src, label, type, isBase = false) {
        if (!src || seenSrcs.has(src) || src === currentModifiedImage) return false;
        if (src.includes('logo') || src.includes('monogramme')) return false;
        seenSrcs.add(src);
        chatImages.push({ src, label, type, isBase });
        return true;
    }

    // 1. TOUJOURS en premier: BASE IMAGE - la toute première image originale de la conversation
    // Chercher la première user-thumb (premier upload utilisateur)
    const firstUserThumb = document.querySelector('#chat-messages .user-thumb');
    if (firstUserThumb && firstUserThumb.src) {
        addImage(firstUserThumb.src, 'BASE IMAGE', 'original', true);
    }

    // 2. L'image originale actuelle (si différente de BASE et de modified)
    if (currentOriginalImage && currentOriginalImage !== currentModifiedImage) {
        addImage(currentOriginalImage, 'Image originale', 'original');
    }

    // 3. Les autres user-thumb (miniatures d'input utilisateur) - sauf le premier déjà ajouté
    const userThumbs = document.querySelectorAll('#chat-messages .user-thumb');
    userThumbs.forEach((img, index) => {
        if (index > 0) {  // Skip le premier, déjà ajouté comme BASE
            addImage(img.src, `Input ${index + 1}`, 'input');
        }
    });

    // 4. Toutes les images result-image du chat (générées)
    const resultImages = document.querySelectorAll('#chat-messages .result-image');
    resultImages.forEach((img, index) => {
        const isOriginal = img.classList.contains('original-preview-image');
        if (!isOriginal) {  // Seulement les générées, pas les originaux
            addImage(img.src, `Génération ${index + 1}`, 'générée');
        }
    });

    // 5. Image en cours dans l'input (si présente)
    if (typeof currentImage !== 'undefined' && currentImage) {
        addImage(currentImage, 'Image input actuel', 'input');
    }

    // Générer le HTML
    if (chatImages.length === 0) {
        container.innerHTML = '<div class="compare-image-item" style="color: #888; justify-content: center;">Aucune image disponible</div>';
        return;
    }

    container.innerHTML = chatImages.map((img, index) => `
        <div class="compare-image-item ${selectedCompareImage === img.src ? 'selected' : ''} ${img.isBase ? 'base-image' : ''}"
             onclick="selectCompareImage('${index}', event)">
            <img src="${img.src}" alt="${img.label}">
            <div class="compare-item-info">
                <div class="compare-item-label">${img.label}</div>
                <div class="compare-item-type">${img.type}</div>
            </div>
        </div>
    `).join('');

    // Stocker les images pour la sélection
    container._images = chatImages;
}

function selectCompareImage(index, event) {
    event.stopPropagation();
    const container = document.getElementById('compare-image-items');
    const images = container._images;

    if (images && images[index]) {
        selectedCompareImage = images[index].src;

        // Mettre à jour la sélection visuelle
        container.querySelectorAll('.compare-image-item').forEach((item, i) => {
            item.classList.toggle('selected', i === parseInt(index));
        });

        // Fermer la liste après un court délai
        setTimeout(() => {
            document.getElementById('compare-image-list').classList.remove('open');
            // Lancer directement la comparaison
            showCompareWithSelected();
        }, 200);
    }
}

function showCompareWithSelected() {
    if (!selectedCompareImage || !currentModifiedImage) return;

    const overlay = document.getElementById('compare-overlay');
    const beforeImg = document.getElementById('compare-before');
    const afterImg = document.getElementById('compare-after');
    const origThumb = document.getElementById('thumb-original');
    const modThumb = document.getElementById('thumb-modified');
    const compareThumb = document.getElementById('thumb-compare');
    const mainWrapper = document.querySelector('.modal-image-wrapper');

    // Utiliser l'image sélectionnée comme "before"
    beforeImg.src = selectedCompareImage;
    afterImg.src = currentModifiedImage;

    // Stocker pour le X-Ray
    compareBeforeImage = selectedCompareImage;
    compareAfterImage = currentModifiedImage;

    mainWrapper.style.display = 'none';
    overlay.style.display = 'flex';

    // IMPORTANT: Cacher les contrôles X-Ray de la vue modale normale
    const modalXrayControls = document.getElementById('xray-controls');
    if (modalXrayControls) modalXrayControls.style.display = 'none';

    origThumb?.classList.remove('active');
    modThumb?.classList.remove('active');
    compareThumb?.classList.add('active');

    updateCompareSlider(50);
    compareZoomLevel = 1;
    comparePanX = 0;
    comparePanY = 0;
    updateCompareZoom();
    compareSliderActive = true;

    // Reset X-Ray du compare
    hideCompareXRayOverlay();

    // Créer les contrôles X-Ray pour le compare
    createCompareXRayControls();
}

// Fermer la liste si clic en dehors
document.addEventListener('click', function(e) {
    const list = document.getElementById('compare-image-list');
    const btn = document.getElementById('compare-select-btn');
    if (list && !list.contains(e.target) && e.target !== btn && !btn?.contains(e.target)) {
        list.classList.remove('open');
    }
});
