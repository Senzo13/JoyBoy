/**
 * Preload System - Gère l'écran de chargement et le préchargement des modèles
 */

let preloadComplete = false;
let loadingTipIndex = 0;
let loadingTipTimer = null;

const LOADING_STAGES = [
    { id: 'core', threshold: 0, labelKey: 'loading.stages.core', labelFallback: 'Core' },
    { id: 'cache', threshold: 22, labelKey: 'loading.stages.cache', labelFallback: 'Cache' },
    { id: 'models', threshold: 55, labelKey: 'loading.stages.models', labelFallback: 'Modèles' },
    { id: 'ready', threshold: 90, labelKey: 'loading.stages.ready', labelFallback: 'Prêt' },
];

const LOADING_TIPS = [
    {
        kickerKey: 'loading.tips.create.kicker',
        kickerFallback: 'Image',
        titleKey: 'loading.tips.create.title',
        titleFallback: 'Créer une image depuis une idée simple',
        bodyKey: 'loading.tips.create.body',
        bodyFallback: 'Décris ton visuel, JoyBoy choisit le mode adapté et garde la génération dans la conversation.',
    },
    {
        kickerKey: 'loading.tips.edit.kicker',
        kickerFallback: 'Retouche',
        titleKey: 'loading.tips.edit.title',
        titleFallback: 'Modifier seulement la zone utile',
        bodyKey: 'loading.tips.edit.body',
        bodyFallback: 'Ajoute une image, masque une partie et demande un changement précis sans casser le reste.',
    },
    {
        kickerKey: 'loading.tips.video.kicker',
        kickerFallback: 'Vidéo',
        titleKey: 'loading.tips.video.title',
        titleFallback: 'Animer une image ou continuer une vidéo',
        bodyKey: 'loading.tips.video.body',
        bodyFallback: 'Les modèles vidéo se pilotent depuis le même prompt, avec file d’attente et aperçu de progression.',
    },
    {
        kickerKey: 'loading.tips.models.kicker',
        kickerFallback: 'Modèles',
        titleKey: 'loading.tips.models.title',
        titleFallback: 'Installer seulement ce dont tu as besoin',
        bodyKey: 'loading.tips.models.body',
        bodyFallback: 'Le catalogue affiche les modèles locaux, les downloads et l’espace disque restant.',
    },
];

function preloadT(key, fallback, params = {}) {
    return window.JoyBoyI18n?.t?.(key, params, fallback) || fallback;
}

function buildCacheSummary(summary, ready = false) {
    if (!summary) {
        return preloadT('loading.cacheSummaryFallback', 'Vérification du cache local et des dépendances…');
    }

    const requiredCached = summary.required_cached ?? 0;
    const requiredTotal = summary.required_total ?? 0;
    const optionalCached = summary.optional_cached ?? 0;
    const optionalTotal = summary.optional_total ?? 0;

    if (ready) {
        return preloadT(
            'loading.cacheSummaryReady',
            '{requiredCached}/{requiredTotal} modules principaux prêts • {optionalCached}/{optionalTotal} assets locaux détectés',
            { requiredCached, requiredTotal, optionalCached, optionalTotal }
        );
    }

    return preloadT(
        'loading.cacheSummaryPending',
        '{requiredCached}/{requiredTotal} modules principaux prêts • {optionalCached}/{optionalTotal} assets locaux déjà en cache',
        { requiredCached, requiredTotal, optionalCached, optionalTotal }
    );
}

function buildProgressDetail(progress, data) {
    const current = Math.min((data?.progress ?? 0) + 1, data?.total_steps || 1);
    const total = data?.total_steps || 1;

    return preloadT(
        'loading.progressDetail',
        'Étape {current}/{total} • {progress}% terminé',
        { current, total, progress }
    );
}

function localizeLoadingShell() {
    const subtitle = document.getElementById('loading-subtitle');
    if (subtitle) {
        subtitle.textContent = preloadT('loading.subtitle', 'Préparation des modèles IA...');
    }

    LOADING_STAGES.forEach(stage => {
        const label = document.getElementById(`loading-stage-${stage.id}`);
        if (label) {
            label.textContent = preloadT(stage.labelKey, stage.labelFallback);
        }
    });
}

function getLocalizedLoadingTip(index) {
    const tip = LOADING_TIPS[index % LOADING_TIPS.length];
    return {
        kicker: preloadT(tip.kickerKey, tip.kickerFallback),
        title: preloadT(tip.titleKey, tip.titleFallback),
        body: preloadT(tip.bodyKey, tip.bodyFallback),
    };
}

function renderLoadingTip(index) {
    const card = document.getElementById('loading-tip-card');
    const kicker = document.getElementById('loading-tip-kicker');
    const title = document.getElementById('loading-tip-title');
    const body = document.getElementById('loading-tip-body');
    if (!card || !kicker || !title || !body) return;

    const nextTip = getLocalizedLoadingTip(index);
    card.classList.remove('is-changing');
    void card.offsetWidth;
    kicker.textContent = nextTip.kicker;
    title.textContent = nextTip.title;
    body.textContent = nextTip.body;
    card.classList.add('is-changing');
}

function startLoadingTips() {
    if (loadingTipTimer) return;
    renderLoadingTip(0);
    loadingTipTimer = setInterval(() => {
        loadingTipIndex = (loadingTipIndex + 1) % LOADING_TIPS.length;
        renderLoadingTip(loadingTipIndex);
    }, 3200);
}

function updateLoadingStage(progress) {
    if (typeof progress !== 'number') return;
    const activeIndex = LOADING_STAGES.reduce((selected, stage, index) => {
        return progress >= stage.threshold ? index : selected;
    }, 0);

    LOADING_STAGES.forEach((stage, index) => {
        const el = document.querySelector(`[data-loading-stage="${stage.id}"]`);
        if (!el) return;
        el.classList.toggle('done', index < activeIndex || progress >= 100);
        el.classList.toggle('active', progress < 100 && index === activeIndex);
    });
}

/**
 * Vérifie si le préchargement est nécessaire et le lance si besoin
 */
async function initPreload() {
    const loadingScreen = document.getElementById('loading-screen');
    if (!loadingScreen) {
        console.warn('[PRELOAD] Loading screen not found');
        return;
    }

    try {
        // Vérifier si le préchargement est nécessaire
        const checkResponse = await fetch('/api/preload/check');
        const checkData = await checkResponse.json();
        const cacheSummary = buildCacheSummary(checkData.summary, checkData.ready);

        if (!checkData.needs_preload) {
            // Tout est déjà en cache, afficher le site directement
            console.log('[PRELOAD] Cache complet, skip preload');
            const skippedNonCuda = checkData.skipped && checkData.skip_reason === 'no_cuda_or_mps';
            updateLoadingStatus(
                skippedNonCuda
                    ? preloadT('loading.nonCudaReady', 'Profil CPU/non-CUDA prêt')
                    : preloadT('loading.cached', 'Modèles en cache !'),
                100,
                skippedNonCuda
                    ? preloadT('loading.nonCudaSummary', 'Préchargement image lourd ignoré sur cette machine.')
                    : cacheSummary,
                preloadT('loading.progress.ready', 'Prêt au lancement')
            );
            setTimeout(() => hideLoadingScreen(), 500);
            return;
        }

        // Lancer le préchargement avec SSE
        console.log('[PRELOAD] Démarrage du préchargement...');
        updateLoadingStatus(
            preloadT('loading.preparing', 'Préparation locale requise'),
            8,
            cacheSummary,
            preloadT('loading.progress.checkingCache', 'Analyse du cache local')
        );
        startPreloadStream(checkData.summary);

    } catch (error) {
        console.error('[PRELOAD] Erreur:', error);
        // En cas d'erreur, afficher le site quand même
        updateLoadingStatus(
            preloadT('loading.generic', 'Chargement...'),
            100,
            preloadT('loading.cacheSummaryFallback', 'Vérification du cache local et des dépendances…'),
            preloadT('loading.progress.ready', 'Prêt au lancement')
        );
        setTimeout(() => hideLoadingScreen(), 1000);
    }
}

/**
 * Lance le stream SSE pour le préchargement
 */
function startPreloadStream(initialSummary = null) {
    const eventSource = new EventSource('/api/preload/stream');

    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            const progress = data.total_steps > 0
                ? Math.round((data.progress / data.total_steps) * 100)
                : 0;
            const details = data.done
                ? buildCacheSummary(initialSummary, true)
                : buildProgressDetail(progress, data);

            updateLoadingStatus(
                data.current_step,
                progress,
                details,
                data.done
                    ? preloadT('loading.progress.ready', 'Prêt au lancement')
                    : preloadT('loading.progress.preparing', 'Préparation locale')
            );

            if (data.done) {
                eventSource.close();
                setTimeout(() => hideLoadingScreen(), 800);
            }

            if (data.error) {
                console.error('[PRELOAD] Erreur:', data.error);
            }
        } catch (e) {
            console.error('[PRELOAD] Parse error:', e);
        }
    };

    eventSource.onerror = function(error) {
        console.error('[PRELOAD] SSE error:', error);
        eventSource.close();
        // Afficher le site malgré l'erreur
        updateLoadingStatus(
            preloadT('loading.done', 'Chargement terminé'),
            100,
            buildCacheSummary(initialSummary, false),
            preloadT('loading.progress.ready', 'Prêt au lancement')
        );
        setTimeout(() => hideLoadingScreen(), 500);
    };
}

/**
 * Met à jour l'affichage du loading screen
 */
function updateLoadingStatus(status, progress, details = '', progressLabel = '') {
    const statusEl = document.getElementById('loading-status');
    const progressBar = document.getElementById('loading-progress-bar');
    const detailsEl = document.getElementById('loading-details');
    const progressValueEl = document.getElementById('loading-progress-value');
    const progressLabelEl = document.getElementById('loading-progress-label');

    if (statusEl) {
        statusEl.textContent = status;
    }

    if (progressBar && typeof progress === 'number') {
        progressBar.style.width = `${progress}%`;
    }

    if (detailsEl) {
        detailsEl.textContent = details;
    }

    if (progressValueEl && typeof progress === 'number') {
        progressValueEl.textContent = `${progress}%`;
    }

    if (progressLabelEl && progressLabel) {
        progressLabelEl.textContent = progressLabel;
    }

    updateLoadingStage(progress);
}

/**
 * Cache l'écran de chargement avec une animation
 */
function hideLoadingScreen() {
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.classList.add('loaded');
        preloadComplete = true;
        if (loadingTipTimer) {
            clearInterval(loadingTipTimer);
            loadingTipTimer = null;
        }

        // Supprimer du DOM après l'animation blackhole
        setTimeout(() => {
            loadingScreen.remove();
        }, 1400);
    }
}

// Lancer au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    // Petit délai pour que le CSS soit chargé
    localizeLoadingShell();
    startLoadingTips();
    setTimeout(initPreload, 100);
});
