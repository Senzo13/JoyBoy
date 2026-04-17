/**
 * Preload System - Gère l'écran de chargement et le préchargement des modèles
 */

let preloadComplete = false;

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
}

/**
 * Cache l'écran de chargement avec une animation
 */
function hideLoadingScreen() {
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.classList.add('loaded');
        preloadComplete = true;

        // Supprimer du DOM après l'animation blackhole
        setTimeout(() => {
            loadingScreen.remove();
        }, 1400);
    }
}

// Lancer au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
    // Petit délai pour que le CSS soit chargé
    setTimeout(initPreload, 100);
});
