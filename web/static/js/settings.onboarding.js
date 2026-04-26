// ===== SETTINGS ONBOARDING PANEL =====
// First-run setup, doctor readiness, benchmark flow, profile, and setup completion.

let currentOnboardingStep = 1;
let selectedProfileType = null;
let onboardingDoctor = null;
let onboardingPreviewMode = false;
let onboardingPreviewTimer = null;

const ONBOARDING_PREVIEW_FEATURES = {
    chat: { icon: 'messages-square', suffix: 'Chat' },
    web: { icon: 'globe', suffix: 'Web' },
    image: { icon: 'wand-sparkles', suffix: 'Image' },
    video: { icon: 'clapperboard', suffix: 'Video' },
    adaptive: { icon: 'gauge', suffix: 'Adaptive' },
};

const ONBOARDING_SETUP_STAGES = [
    { id: 'runtime', threshold: 0, key: 'onboarding.setupStageRuntime', fallback: 'Initialisation locale' },
    { id: 'hardware', threshold: 25, key: 'onboarding.setupStageHardware', fallback: 'Détection matériel' },
    { id: 'models', threshold: 48, key: 'onboarding.setupStageModels', fallback: 'Préparation modèles' },
    { id: 'ready', threshold: 96, key: 'onboarding.setupStageReady', fallback: 'Prêt à démarrer' },
];

function getOnboardingPreviewFeature() {
    if (!onboardingPreviewMode) return '';
    try {
        const params = new URLSearchParams(window.location.search);
        const feature = String(params.get('feature') || params.get('onboarding_feature') || '').trim().toLowerCase();
        return ONBOARDING_PREVIEW_FEATURES[feature] ? feature : '';
    } catch (_) {
        return '';
    }
}

function setOnboardingSpotlightText(id, key, fallback) {
    const el = document.getElementById(id);
    if (el) setRuntimeText(el, key, fallback);
}

function clearOnboardingFeatureSpotlight() {
    const content = document.querySelector('#onboarding-modal .onboarding-content');
    const spotlight = document.getElementById('onboarding-feature-spotlight');
    content?.classList.remove('feature-preview-active');
    spotlight?.classList.add('hidden');
    document.querySelectorAll('[data-onboarding-feature]').forEach(card => {
        card.classList.remove('is-spotlight');
    });
}

function applyOnboardingFeatureSpotlight() {
    const feature = getOnboardingPreviewFeature();
    if (!feature) {
        clearOnboardingFeatureSpotlight();
        return;
    }

    const meta = ONBOARDING_PREVIEW_FEATURES[feature];
    const content = document.querySelector('#onboarding-modal .onboarding-content');
    const spotlight = document.getElementById('onboarding-feature-spotlight');
    const icon = document.getElementById('onboarding-feature-spotlight-icon');
    if (!spotlight || !meta) return;

    document.querySelectorAll('[data-onboarding-feature]').forEach(card => {
        card.classList.toggle('is-spotlight', card.dataset.onboardingFeature === feature);
    });

    if (icon) {
        icon.innerHTML = `<i data-lucide="${meta.icon}"></i>`;
    }

    setOnboardingSpotlightText(
        'onboarding-feature-spotlight-kicker',
        `onboarding.spotlight${meta.suffix}Kicker`,
        'Focus'
    );
    setOnboardingSpotlightText(
        'onboarding-feature-spotlight-title',
        `onboarding.spotlight${meta.suffix}Title`,
        'JoyBoy s’adapte à ton usage'
    );
    setOnboardingSpotlightText(
        'onboarding-feature-spotlight-body',
        `onboarding.spotlight${meta.suffix}Body`,
        'Choisis une surface pour voir ce qu’elle apporte dès le premier lancement.'
    );

    content?.classList.add('feature-preview-active');
    spotlight.classList.remove('hidden');
    if (window.lucide) lucide.createIcons({ nodes: [spotlight] });
}

function setOnboardingSetupCopy() {
    const stageLabels = {
        runtime: ['onboarding.setupStageRuntimeShort', 'Runtime'],
        hardware: ['onboarding.setupStageHardwareShort', 'Matériel'],
        models: ['onboarding.setupStageModelsShort', 'Modèles'],
        ready: ['onboarding.setupStageReadyShort', 'Prêt'],
    };

    Object.entries(stageLabels).forEach(([id, [key, fallback]]) => {
        setRuntimeText(`onboarding-setup-stage-${id}`, key, fallback);
    });
}

function isOnboardingPreviewRequested() {
    try {
        const params = new URLSearchParams(window.location.search);
        return params.get('onboarding') === 'preview' || params.get('setup') === 'preview';
    } catch (_) {
        return false;
    }
}

function getOnboardingPreviewInitialStep() {
    if (!onboardingPreviewMode) return 1;
    try {
        const params = new URLSearchParams(window.location.search);
        const value = (params.get('preview_step') || params.get('onboarding_step') || '').toLowerCase();
        if (value === 'setup' || value === '3') return 3;
        if (value === 'profile' || value === '2') return 2;
        return 1;
    } catch (_) {
        return 1;
    }
}

function clearOnboardingPreviewTimer() {
    if (onboardingPreviewTimer) {
        clearInterval(onboardingPreviewTimer);
        onboardingPreviewTimer = null;
    }
}

function applyOnboardingPreviewInitialStep() {
    const targetStep = getOnboardingPreviewInitialStep();
    if (!onboardingPreviewMode || targetStep <= 1) return;

    [1, 2, 3].forEach(step => {
        const el = document.getElementById(`onboarding-step-${step}`);
        if (el) el.classList.toggle('hidden', step !== targetStep);
    });

    currentOnboardingStep = targetStep;
    updateOnboardingDots(targetStep);
    setOnboardingButtonState(targetStep);
    resetOnboardingScroll();

    if (targetStep === 2) {
        document.getElementById('onboarding-name')?.focus();
    } else if (targetStep === 3) {
        document.getElementById('onboarding-next-btn')?.classList.add('hidden');
        startOnboardingPreviewSetup();
    }
}

function setSetupProgressLabel(key, fallback, params = {}) {
    const label = document.getElementById('onboarding-setup-progress-label');
    if (label) {
        setRuntimeText(label, key, fallback, params);
    }
}

function setSetupProgressPlainLabel(value) {
    const label = document.getElementById('onboarding-setup-progress-label');
    if (label) {
        setPlainText(label, value);
    }
}

function updateOnboardingSetupStage(percent) {
    const clamped = Math.max(0, Math.min(100, Number(percent) || 0));
    const activeIndex = ONBOARDING_SETUP_STAGES.reduce((selected, stage, index) => {
        return clamped >= stage.threshold ? index : selected;
    }, 0);

    ONBOARDING_SETUP_STAGES.forEach((stage, index) => {
        const el = document.querySelector(`[data-setup-stage="${stage.id}"]`);
        if (!el) return;
        el.classList.toggle('done', index < activeIndex || clamped >= 100);
        el.classList.toggle('active', clamped < 100 && index === activeIndex);
    });
}

function syncOnboardingProfileFromBackend(onboarding) {
    if (!onboarding) return;

    if (typeof onboarding.completed === 'boolean') {
        userProfile.hasCompletedOnboarding = onboarding.completed;
    }
    if (onboarding.profile_type) {
        userProfile.type = onboarding.profile_type;
    }
    if (typeof onboarding.profile_name === 'string') {
        userProfile.name = onboarding.profile_name;
    }

    const backendLocale = window.JoyBoyI18n?.normalizeLocale?.(onboarding.locale || '') || '';
    if (backendLocale) {
        const hasStoredLocale = window.JoyBoyI18n?.hasStoredLocale?.() === true;
        if (!hasStoredLocale && (onboarding.completed || backendLocale !== 'fr')) {
            window.JoyBoyI18n?.setLocale?.(backendLocale, { persist: true });
        } else {
            syncLocaleSelectors(getCurrentLocale());
        }
    }
    saveProfile();
}

function setOnboardingButtonState(step = currentOnboardingStep) {
    const nextBtn = document.getElementById('onboarding-next-btn');
    const skipBtn = document.getElementById('onboarding-skip-btn');
    if (!nextBtn || !skipBtn) return;

    nextBtn.classList.remove('hidden');
    skipBtn.classList.remove('hidden');

    if (step === 1) {
        setRuntimeText(nextBtn, 'onboarding.step1Continue', 'Continuer');
        setRuntimeText(skipBtn, 'onboarding.skip', 'Passer');
        nextBtn.disabled = !selectedProfileType;
    } else if (step === 2) {
        setRuntimeText(nextBtn, 'onboarding.step2Continue', 'Continuer');
        setRuntimeText(skipBtn, 'onboarding.skip', 'Passer');
        nextBtn.disabled = false;
    } else if (step === 3) {
        if (!nextBtn.classList.contains('hidden')) {
            setRuntimeText(skipBtn, 'onboarding.step3Skip', 'Installer plus tard');
        }
    }
}

async function checkOnboarding() {
    if (isOnboardingPreviewRequested()) {
        onboardingPreviewMode = true;
        loadProfile();
        document.body.classList.add('app-hidden');
        openOnboarding();
        return;
    }
    onboardingPreviewMode = false;

    const forceOnboarding = sessionStorage.getItem('forceOnboardingAfterReset') === '1';
    if (forceOnboarding) {
        sessionStorage.removeItem('forceOnboardingAfterReset');
        try {
            await apiSettings.resetOnboarding();
            userProfile.hasCompletedOnboarding = false;
            saveProfile();
        } catch (error) {
            console.warn('[ONBOARDING] Reset forcé impossible:', error);
        }
    }

    // Charger le profil sauvegardé
    const savedProfile = localStorage.getItem('userProfile');
    if (savedProfile) {
        try {
            userProfile = JSON.parse(savedProfile);
        } catch (e) {
            console.error('Erreur chargement profil:', e);
        }
    }

    const localNeedsOnboarding = !userProfile.hasCompletedOnboarding;
    if (localNeedsOnboarding) {
        // Show the setup UI immediately from local state. The backend sync runs
        // after this, so first launch no longer waits for Doctor/model checks.
        document.body.classList.add('app-hidden');
        openOnboarding();
    }

    try {
        const result = await apiSettings.getOnboardingStatus();
        if (result.ok && result.data?.success) {
            syncOnboardingProfileFromBackend(result.data.onboarding);
            onboardingDoctor = result.data.doctor || null;
        }
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de charger l’état backend:', error);
    }

    if (userProfile.hasCompletedOnboarding) {
        // Local storage can be stale after resets, browser clears, or public-core
        // regeneration. If we opened instantly from stale local state, tear it down
        // without replaying the full close animation.
        if (localNeedsOnboarding) {
            const modal = document.getElementById('onboarding-modal');
            modal?.classList.remove('open', 'closing');
            document.removeEventListener('keydown', handleOnboardingKeydown);
            document.querySelectorAll('.lightning-bolt').forEach(bolt => bolt.remove());
        }
        document.body.classList.remove('app-hidden');
        return;
    }

    // If the backend says onboarding is still needed but localStorage was stale,
    // open it now. Usually the local path above already handled this instantly.
    if (!localNeedsOnboarding) {
        document.body.classList.add('app-hidden');
        openOnboarding();
    } else {
        document.body.classList.add('app-hidden');
    }
}

function createLightningBolt() {
    const bolt = document.createElement('div');
    bolt.className = 'lightning-bolt';
    // Realistic zigzag lightning path from top to bottom-right
    bolt.innerHTML = `
        <svg viewBox="0 0 300 500" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="lightning-gradient" x1="0%" y1="0%" x2="50%" y2="100%">
                    <stop offset="0%" style="stop-color:#fff;stop-opacity:1" />
                    <stop offset="40%" style="stop-color:#93c5fd;stop-opacity:1" />
                    <stop offset="100%" style="stop-color:#3b82f6;stop-opacity:1" />
                </linearGradient>
            </defs>
            <path d="M50,0 L60,80 L30,85 L70,160 L35,170 L90,260 L50,270 L120,360 L75,375 L150,500" />
        </svg>
    `;
    document.body.appendChild(bolt);

    // Strike quickly after the modal appears; the old multi-second delay made
    // first setup feel like it was waiting on work that had already finished.
    setTimeout(() => {
        bolt.classList.add('strike');
    }, 430);

    // Remove after animation
    setTimeout(() => {
        bolt.remove();
    }, 980);
}

// Keyboard handler for onboarding
function handleOnboardingKeydown(e) {
    if (e.key === 'Enter') {
        const nextBtn = document.getElementById('onboarding-next-btn');
        if (nextBtn && !nextBtn.disabled && !nextBtn.classList.contains('hidden')) {
            e.preventDefault();
            nextOnboardingStep();
        }
    }
}

function ensureOnboardingLayout() {
    const content = document.querySelector('.onboarding-content');
    if (!content || content.querySelector('.onboarding-scroll')) return;

    const actions = content.querySelector('.onboarding-actions');
    const directSteps = Array.from(content.children).filter(child => child.classList?.contains('onboarding-step'));
    if (!actions || directSteps.length === 0) return;

    const scroll = document.createElement('div');
    scroll.className = 'onboarding-scroll';
    content.insertBefore(scroll, actions);
    directSteps.forEach(step => scroll.appendChild(step));
}

function resetOnboardingScroll() {
    const scroll = document.querySelector('.onboarding-scroll');
    if (scroll) scroll.scrollTo({ top: 0, behavior: 'smooth' });
}

function openOnboarding() {
    currentOnboardingStep = 1;
    selectedProfileType = userProfile.type || 'casual';
    benchmarkData = null;
    clearOnboardingPreviewTimer();

    // Hide the app while onboarding is active
    document.body.classList.add('app-hidden');

    // Save and clear placeholder for later animation
    const input = document.getElementById('prompt-input');
    if (input) {
        originalPlaceholder = input.placeholder;
        input.placeholder = '';
    }

    ensureOnboardingLayout();
    resetOnboardingScroll();
    document.getElementById('onboarding-modal').classList.add('open');
    syncLocaleSelectors(getCurrentLocale());

    // Create lightning effect
    createLightningBolt();

    // Add keyboard listener for Enter key
    document.addEventListener('keydown', handleOnboardingKeydown);
    document.getElementById('onboarding-step-1').classList.remove('hidden');
    document.getElementById('onboarding-step-2').classList.add('hidden');
    document.getElementById('onboarding-step-3').classList.add('hidden');

    setOnboardingButtonState(1);

    // Reset step 3 UI
    const circularProgress = document.getElementById('setup-progress');
    circularProgress.classList.remove('analyzing', 'complete', 'error');
    setOnboardingSetupCopy();
    setProgress(0);
    setSetupProgressLabel('onboarding.setupStageRuntime', 'Initialisation locale');
    setRuntimeText('setup-label', 'onboarding.analysing', 'Analyse...');
    document.getElementById('hardware-info').classList.add('hidden');
    document.getElementById('setup-eta').classList.add('hidden');
    renderOnboardingReadiness(null);
    setRuntimeText('setup-status', 'onboarding.detectHardware', 'Détection du matériel...');

    // Reset selections & dots
    document.querySelectorAll('.profile-option').forEach(opt => {
        const selected = opt.dataset.type === selectedProfileType;
        opt.classList.toggle('selected', selected);
    });
    document.getElementById('onboarding-name').value = userProfile.name || '';
    updateOnboardingDots(1);
    initOnboardingDots();
    setOnboardingButtonState(1);
    applyOnboardingFeatureSpotlight();
    applyOnboardingPreviewInitialStep();
}

function closeOnboarding() {
    const modal = document.getElementById('onboarding-modal');
    modal.classList.add('closing');
    clearOnboardingPreviewTimer();
    clearOnboardingFeatureSpotlight();

    // Remove keyboard listener
    document.removeEventListener('keydown', handleOnboardingKeydown);

    // Keep the close transition snappy; onboarding is a setup utility, not a cutscene.
    setTimeout(() => {
        modal.classList.remove('open');
        modal.classList.remove('closing');

        // Reveal the app with animation
        document.body.classList.remove('app-hidden');
        document.body.classList.add('app-revealing');

        // Start placeholder animation sooner (during reveal)
        setTimeout(() => {
            animatePlaceholder();
        }, 80);

        // Clean up after reveal animation
        setTimeout(() => {
            document.body.classList.remove('app-revealing');
        }, 450);
    }, 190);
}

// Store original placeholder for typing animation
let originalPlaceholder = '';
let placeholderAnimationRunning = false;

// Typing animation for placeholder
function animatePlaceholder() {
    const input = document.getElementById('prompt-input');
    if (!input || !originalPlaceholder) return;

    // Éviter les animations multiples simultanées
    if (placeholderAnimationRunning) {
        console.log('[ANIM] Animation déjà en cours, skip');
        return;
    }
    placeholderAnimationRunning = true;

    input.placeholder = '';
    let index = 0;

    function typeChar() {
        if (index < originalPlaceholder.length) {
            input.placeholder += originalPlaceholder[index];
            index++;
            setTimeout(typeChar, 30 + Math.random() * 20);
        } else {
            placeholderAnimationRunning = false;
            // Activate send button glow + pulse
            const sendBtn = document.getElementById('send-btn');
            if (sendBtn) {
                sendBtn.classList.add('invite-glow');
                setTimeout(() => {
                    sendBtn.classList.add('entrance-pulse');
                    setTimeout(() => sendBtn.classList.remove('entrance-pulse'), 600);
                }, 50);
                // Focus input to invite user to type
                input.focus();
                // Remove invite glow once user starts typing
                input.addEventListener('input', function removeGlow() {
                    sendBtn.classList.remove('invite-glow');
                    input.removeEventListener('input', removeGlow);
                }, { once: true });
            }
        }
    }

    // Start typing after a small delay
    setTimeout(typeChar, 300);
}

function selectProfileType(type) {
    selectedProfileType = type;

    // Update UI
    document.querySelectorAll('.profile-option').forEach(opt => {
        opt.classList.remove('selected');
        if (opt.dataset.type === type) {
            opt.classList.add('selected');
        }
    });

    // Enable next button
    document.getElementById('onboarding-next-btn').disabled = false;
}

function updateOnboardingDots(step) {
    document.querySelectorAll('.onboarding-dot').forEach(dot => {
        const dotStep = parseInt(dot.dataset.step);
        dot.classList.remove('active', 'done');
        if (dotStep === step) {
            dot.classList.add('active');
        } else if (dotStep < step) {
            dot.classList.add('done');
        }
    });
}

function goToOnboardingStep(targetStep) {
    if (targetStep >= currentOnboardingStep || targetStep < 1) return;
    if (onboardingPreviewMode && targetStep < 3) {
        clearOnboardingPreviewTimer();
    }

    const currentEl = document.getElementById(`onboarding-step-${currentOnboardingStep}`);
    const targetEl = document.getElementById(`onboarding-step-${targetStep}`);

    // Fade out current (slide right = going back)
    currentEl.classList.add('fade-out-reverse');
    setTimeout(() => {
        currentEl.classList.add('hidden');
        currentEl.classList.remove('fade-out-reverse');
        targetEl.classList.remove('hidden');
        // Re-init lucide icons if needed
        if (window.lucide) lucide.createIcons({ nodes: [targetEl] });

        // Restore button states for target step
        const nextBtn = document.getElementById('onboarding-next-btn');
        const skipBtn = document.getElementById('onboarding-skip-btn');
        nextBtn.classList.remove('hidden');

        if (targetStep === 1) {
            setOnboardingButtonState(1);
        } else if (targetStep === 2) {
            setOnboardingButtonState(2);
        }

        currentOnboardingStep = targetStep;
        updateOnboardingDots(targetStep);
        resetOnboardingScroll();
    }, 250);
}

// Init dot click listeners
function initOnboardingDots() {
    document.querySelectorAll('.onboarding-dot').forEach(dot => {
        dot.addEventListener('click', () => {
            const targetStep = parseInt(dot.dataset.step);
            if (targetStep < currentOnboardingStep) {
                goToOnboardingStep(targetStep);
            }
        });
    });
}

function nextOnboardingStep() {
    const step1 = document.getElementById('onboarding-step-1');
    const step2 = document.getElementById('onboarding-step-2');
    const step3 = document.getElementById('onboarding-step-3');

    if (currentOnboardingStep === 1) {
        step1.classList.add('fade-out');
        setTimeout(() => {
            step1.classList.add('hidden');
            step1.classList.remove('fade-out');
            step2.classList.remove('hidden');
            if (window.lucide) lucide.createIcons({ nodes: [step2] });
            setOnboardingButtonState(2);
            resetOnboardingScroll();
            document.getElementById('onboarding-name').focus();
        }, 250);
        currentOnboardingStep = 2;
        updateOnboardingDots(2);
    } else if (currentOnboardingStep === 2) {
        step2.classList.add('fade-out');
        setTimeout(() => {
            step2.classList.add('hidden');
            step2.classList.remove('fade-out');
            step3.classList.remove('hidden');
            document.getElementById('onboarding-next-btn').classList.add('hidden');
            setOnboardingButtonState(3);
            resetOnboardingScroll();
            if (onboardingPreviewMode) {
                startOnboardingPreviewSetup();
            } else {
                startBenchmark();
            }
        }, 250);
        currentOnboardingStep = 3;
        updateOnboardingDots(3);
    } else {
        completeOnboarding();
    }
}

// ========== HARDWARE BENCHMARK & SETUP ==========

let benchmarkData = null;
let hardwareInfo = null;
let setupCheckInterval = null;

// Tailles approximatives des modèles (en GB)
const MODEL_SIZES = {
    'qwen3.5:0.8b': 1.0,
    'qwen3.5:2b': 2.7,
    'qwen3.5:4b': 3.4,
    'qwen3.5:9b': 6.6,
    'qwen3:0.6b': 0.6,
    'qwen3:1.7b': 1.4,
    'qwen3:4b': 2.6,
    'qwen2.5:0.5b': 0.4,
    'qwen2.5:1.5b': 1.0,
    'qwen2.5:3b': 2.0,
    'qwen2.5:7b': 4.5,
    'qwen2.5-coder:1.5b': 1.0,
    'qwen2.5-coder:3b': 2.0,
    'qwen2.5-coder:7b': 4.5,
    'mistral:7b': 4.1,
    'dolphin-mistral:7b': 4.1,
};

function getModelSize(modelName) {
    return MODEL_SIZES[modelName] || 2.0; // Default 2GB
}

function calculateETA(modelNames) {
    // Calculer la taille totale
    let totalGB = 0;
    for (const model of modelNames) {
        totalGB += getModelSize(model);
    }
    // Estimation: ~1-2 min par GB (connexion moyenne)
    const minutes = Math.ceil(totalGB * 1.5);
    if (minutes < 1) return '< 1 min';
    if (minutes === 1) return '~1 min';
    return `~${minutes} min`;
}

function _doctorStatusLabel(status) {
    if (status === 'ok') return t('onboarding.statusOk', 'OK');
    if (status === 'warning') return t('onboarding.statusWarning', 'À revoir');
    if (status === 'error') return t('onboarding.statusError', 'Bloquant');
    return t('onboarding.statusInfo', 'Info');
}

function _normalizeDoctorStatus(status) {
    return ['ok', 'warning', 'error'].includes(status) ? status : 'warning';
}

function _doctorSummaryText(doctorData) {
    const status = _normalizeDoctorStatus(doctorData?.status);
    if (status === 'ok') {
        return t('onboarding.doctorSummaryOk', 'JoyBoy est prêt sur cette machine.');
    }
    if (status === 'error' || doctorData?.ready === false) {
        return t('onboarding.doctorSummaryError', 'JoyBoy a besoin de corrections avant de démarrer correctement.');
    }
    return t('onboarding.doctorSummaryWarningReady', 'JoyBoy peut démarrer, mais quelques points méritent d’être corrigés pour un setup public propre.');
}

function _doctorCheckDetail(check, fallbackKey, fallbackText) {
    if (!check) return t(fallbackKey, fallbackText);

    const detail = String(check.detail || '');
    const status = _normalizeDoctorStatus(check.status);

    if (check.key === 'providers') {
        const configured = detail.match(/(?:configurés?|configured)\s*:?\s*(.+)$/i);
        if (configured?.[1]) {
            return t('onboarding.providersConfigured', 'Configurés : {providers}', { providers: configured[1].trim() });
        }
        return status === 'ok'
            ? t('onboarding.providersReady', 'Providers configurés.')
            : t('onboarding.providersHint', 'Configure Hugging Face ou CivitAI dans Paramètres > Modèles.');
    }

    if (check.key === 'ollama') {
        const lower = detail.toLowerCase();
        if (lower.includes('non démarr') || lower.includes('not running')) {
            return t('onboarding.ollamaInstalledStopped', 'Ollama est installé mais non démarré.');
        }
        if (lower.includes('pas installé') || lower.includes('not installed')) {
            return t('onboarding.ollamaMissing', 'Service non détecté.');
        }
        return status === 'ok'
            ? t('onboarding.ollamaReady', 'Ollama est prêt.')
            : (detail || t('onboarding.ollamaMissing', 'Service non détecté.'));
    }

    if (check.key === 'packs') {
        const activePack = detail.match(/(?:pack local avanc[ée] actif|active local pack)\s*:?\s*(.+)$/i);
        if (activePack?.[1]) {
            return t('onboarding.packsActive', 'Pack local actif : {pack}', { pack: activePack[1].trim() });
        }
        return status === 'ok'
            ? t('onboarding.packsReady', 'Packs locaux prêts.')
            : t('onboarding.packsMissing', 'Aucun pack local actif.');
    }

    if (check.key === 'storage') {
        const storage = detail.match(/([\d.,]+)\s*GB\s+(?:libres|free)\s*[·-]\s*(?:config locale|local config)\s*(.+)$/i);
        if (storage?.[1]) {
            return t('onboarding.storageReady', '{free} GB libres · config locale {path}', {
                free: storage[1],
                path: storage[2]?.trim() || '',
            });
        }
        return status === 'ok'
            ? t('onboarding.storageOk', 'Stockage prêt.')
            : t('onboarding.storageUnknown', 'État stockage indisponible.');
    }

    if (check.key === 'models') {
        return status === 'ok'
            ? t('onboarding.modelsReady', 'Modèles de base détectés.')
            : t('onboarding.modelsMissing', 'Aucun modèle de base détecté.');
    }

    return detail || t(fallbackKey, fallbackText);
}

function _doctorCheckLabel(check) {
    if (!check) return '';
    return t(`doctor.check.${check.key}`, check.label || check.key);
}

function renderOnboardingReadiness(doctorData) {
    const wrapper = document.getElementById('onboarding-readiness');
    const grid = document.getElementById('onboarding-readiness-grid');
    const note = document.getElementById('onboarding-readiness-note');
    if (!wrapper || !grid) return;

    if (!doctorData || !Array.isArray(doctorData.checks)) {
        wrapper.classList.add('hidden');
        grid.innerHTML = '';
        return;
    }

    const checksByKey = Object.fromEntries(
        doctorData.checks.map(check => [check.key, check])
    );

    const cards = [
        {
            label: t('onboarding.doctorCard', 'Doctor'),
            status: _normalizeDoctorStatus(doctorData.status),
            detail: _doctorSummaryText(doctorData),
            full: true,
        },
        {
            label: t('onboarding.providersCard', 'Providers'),
            status: _normalizeDoctorStatus(checksByKey.providers?.status),
            detail: _doctorCheckDetail(checksByKey.providers, 'onboarding.providersHint', 'Configure Hugging Face ou CivitAI dans Paramètres > Modèles.'),
        },
        {
            label: t('onboarding.ollamaCard', 'Ollama'),
            status: _normalizeDoctorStatus(checksByKey.ollama?.status),
            detail: _doctorCheckDetail(checksByKey.ollama, 'onboarding.ollamaMissing', 'Service non détecté.'),
        },
        {
            label: t('onboarding.packsCard', 'Packs'),
            status: _normalizeDoctorStatus(checksByKey.packs?.status),
            detail: _doctorCheckDetail(checksByKey.packs, 'onboarding.packsMissing', 'Aucun pack local actif.'),
        },
        {
            label: t('onboarding.storageCard', 'Stockage'),
            status: _normalizeDoctorStatus(checksByKey.storage?.status),
            detail: _doctorCheckDetail(checksByKey.storage, 'onboarding.storageUnknown', 'État stockage indisponible.'),
        },
    ];

    grid.innerHTML = cards.map(card => `
        <div class="onboarding-readiness-card ${card.full ? 'full' : ''}">
            <div class="onboarding-readiness-head">
                <div class="onboarding-readiness-label">${escapeHtml(card.label)}</div>
                <div class="onboarding-status-pill ${escapeHtml(card.status)}">${escapeHtml(_doctorStatusLabel(card.status))}</div>
            </div>
            <div class="onboarding-readiness-detail">${escapeHtml(card.detail)}</div>
        </div>
    `).join('');

    if (note) {
        note.textContent = doctorData.status === 'ok'
            ? t('onboarding.setupNoteReady', 'Tout est déjà bien aligné. Tu pourras toujours affiner providers, modèles et packs dans Paramètres > Modèles.')
            : t('onboarding.setupNoteAction', 'Le wizard prépare le terrain. Tu pourras finaliser providers, packs locaux et imports de modèles dans Paramètres > Modèles.');
    }

    wrapper.classList.remove('hidden');
}

function showOnboardingPreviewHardware() {
    const values = {
        'hw-gpu': t('onboarding.previewGpu', 'GPU local détecté'),
        'hw-vram': t('onboarding.previewVram', 'Auto · selon machine'),
        'hw-ram': t('onboarding.previewRam', 'Mémoire système prête'),
        'hw-model': t('onboarding.previewModel', 'Modèle recommandé automatiquement'),
        'hw-quality': t('onboarding.previewQuality', 'Qualité adaptée au GPU'),
        'hw-image-model': t('onboarding.previewImageModel', 'Flux Fill / SDXL'),
        'hw-gen-time': t('onboarding.previewTime', 'Temps estimé après warmup'),
    };

    Object.entries(values).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    });

    document.getElementById('hardware-info')?.classList.remove('hidden');
}

function getOnboardingPreviewDoctor() {
    return {
        status: 'ok',
        ready: true,
        checks: [
            { key: 'providers', status: 'warning' },
            { key: 'ollama', status: 'ok' },
            { key: 'packs', status: 'ok', detail: 'pack local avancé actif: preview' },
            { key: 'storage', status: 'ok', detail: '128 GB libres · config locale ~/.joyboy' },
            { key: 'models', status: 'ok' },
        ],
    };
}

function startOnboardingPreviewSetup() {
    clearOnboardingPreviewTimer();

    const progressLabel = document.getElementById('setup-label');
    const setupStatus = document.getElementById('setup-status');
    const circularProgress = document.getElementById('setup-progress');
    const nextBtn = document.getElementById('onboarding-next-btn');
    const skipBtn = document.getElementById('onboarding-skip-btn');

    circularProgress.classList.remove('complete', 'error');
    circularProgress.classList.add('analyzing');
    document.getElementById('hardware-info')?.classList.add('hidden');
    document.getElementById('setup-eta')?.classList.add('hidden');
    renderOnboardingReadiness(null);
    if (nextBtn) nextBtn.classList.add('hidden');
    if (skipBtn) skipBtn.classList.remove('hidden');

    const previewSteps = [
        {
            progress: 12,
            stageKey: 'onboarding.setupStageRuntime',
            stageFallback: 'Initialisation locale',
            statusKey: 'onboarding.detectHardware',
            statusFallback: 'Détection du matériel...',
        },
        {
            progress: 38,
            stageKey: 'onboarding.setupStageHardware',
            stageFallback: 'Détection matériel',
            statusKey: 'onboarding.previewHardwareReady',
            statusFallback: 'Matériel détecté, recommandations en préparation...',
            hardware: true,
        },
        {
            progress: 72,
            stageKey: 'onboarding.setupStageModels',
            stageFallback: 'Préparation modèles',
            statusKey: 'onboarding.previewModelsReady',
            statusFallback: 'Catalogue modèles et providers vérifiés...',
            readiness: true,
        },
        {
            progress: 100,
            stageKey: 'onboarding.setupStageReady',
            stageFallback: 'Prêt à démarrer',
            statusKey: 'onboarding.allReady',
            statusFallback: 'Tout est prêt!',
            complete: true,
        },
    ];

    let stepIndex = 0;
    const applyPreviewStep = () => {
        const step = previewSteps[Math.min(stepIndex, previewSteps.length - 1)];
        setProgress(step.progress);
        setSetupProgressLabel(step.stageKey, step.stageFallback);
        setRuntimeText(progressLabel, step.complete ? 'common.ready' : 'onboarding.analysing', step.complete ? 'PRÊT' : 'Analyse...');
        setRuntimeText(setupStatus, step.statusKey, step.statusFallback);

        if (step.hardware) {
            showOnboardingPreviewHardware();
        }
        if (step.readiness || step.complete) {
            onboardingDoctor = getOnboardingPreviewDoctor();
            renderOnboardingReadiness(onboardingDoctor);
        }
        if (step.complete) {
            circularProgress.classList.remove('analyzing');
            circularProgress.classList.add('complete');
            if (nextBtn) {
                nextBtn.classList.remove('hidden');
                nextBtn.disabled = false;
                setRuntimeText(nextBtn, 'onboarding.start', 'Commencer');
            }
            if (skipBtn) {
                skipBtn.classList.add('hidden');
            }
            clearOnboardingPreviewTimer();
            return;
        }

        stepIndex += 1;
    };

    applyPreviewStep();
    onboardingPreviewTimer = setInterval(applyPreviewStep, 900);
}

async function startBenchmark() {
    const progressLabel = document.getElementById('setup-label');
    const setupStatus = document.getElementById('setup-status');
    const circularProgress = document.getElementById('setup-progress');

    // Start analyzing animation
    circularProgress.classList.add('analyzing');
    setProgress(10);
    setSetupProgressLabel('onboarding.setupStageRuntime', 'Initialisation locale');
    setRuntimeText(progressLabel, 'onboarding.analysing', 'Analyse...');
    renderOnboardingReadiness(onboardingDoctor);

    // Profil sélectionné (ou casual par défaut)
    const profile = selectedProfileType || 'casual';

    try {
        const onboardingStatus = await apiSettings.getOnboardingStatus();
        if (onboardingStatus.ok && onboardingStatus.data?.doctor) {
            onboardingDoctor = onboardingStatus.data.doctor;
            renderOnboardingReadiness(onboardingDoctor);
        }

        // Step 1: Get hardware info and profile-based recommendations
        setRuntimeText(setupStatus, 'onboarding.detectHardware', 'Détection du matériel...');
        setSetupProgressLabel('onboarding.setupStageHardware', 'Détection matériel');
        const hwResult = await apiGet('/api/hardware/info');
        if (!hwResult.ok) throw new Error(hwResult.error || 'Hardware info failed');
        hardwareInfo = hwResult.data;

        setProgress(30);

        // Le modèle recommandé pour ce profil + VRAM
        const recommendedModel = hardwareInfo.recommendations[profile] || hardwareInfo.recommendations['casual'];

        // Show hardware info
        document.getElementById('hw-gpu').textContent = hardwareInfo.gpu || 'CPU';
        document.getElementById('hw-vram').textContent = hardwareInfo.vram_gb > 0
            ? `${hardwareInfo.vram_gb.toFixed(1)} GB (${hardwareInfo.vram_level})`
            : '-';
        document.getElementById('hw-ram').textContent = hardwareInfo.ram_gb
            ? `${hardwareInfo.ram_gb} GB`
            : '-';
        document.getElementById('hw-model').textContent = recommendedModel;

        // Show quality level based on VRAM
        const genSettings = hardwareInfo.generation_settings;
        const qualityEl = document.getElementById('hw-quality');
        if (qualityEl && genSettings) {
            qualityEl.textContent = `${getOnboardingQualityLabel(hardwareInfo.vram_level)} (${genSettings.steps} steps)`;
        }

        // Show image model
        const imageModels = hardwareInfo.image_models;
        const imageModelEl = document.getElementById('hw-image-model');
        if (imageModelEl && imageModels) {
            imageModelEl.textContent = localizeModelDisplayName(imageModels.inpainting?.replace(' Inpaint', '') || '-');
        }

        // Estimated inpainting time (first run / after warmup)
        // Calibrated on RTX 3070 Ti (8GB, "high"): ~16s first, ~12s after
        const genTimeEstimates = {
            'low': '~40s / ~30s',
            'medium': '~25s / ~18s',
            'high': '~16s / ~12s',
            'very_high': '~10s / ~7s',
            'ultra': '~6s / ~4s',
            'extreme': '~4s / ~3s'
        };
        const genTimeEl = document.getElementById('hw-gen-time');
        if (genTimeEl) {
            genTimeEl.textContent = genTimeEstimates[hardwareInfo.vram_level] || '~16s / ~12s';
        }

        document.getElementById('hardware-info').classList.remove('hidden');

        setProgress(40);
        circularProgress.classList.remove('analyzing');

        // Step 2: Check if models already installed
        setRuntimeText(setupStatus, 'onboarding.checkingModels', 'Vérification des modèles...');
        setSetupProgressLabel('onboarding.setupStageModels', 'Préparation modèles');
        const modelsResult = await apiOllama.getModels();
        const modelsData = modelsResult.ok ? modelsResult.data : { models: [] };

        const utilityInstalled = modelsData.models?.some(m =>
            m.name === hardwareInfo.utility_model ||
            m.name.startsWith(hardwareInfo.utility_model.split(':')[0])
        );
        const chatInstalled = modelsData.models?.some(m =>
            m.name === recommendedModel ||
            m.name.startsWith(recommendedModel.split(':')[0])
        );

        if (utilityInstalled && chatInstalled) {
            // Both models already installed
            setProgress(100);
            setSetupProgressLabel('onboarding.setupStageReady', 'Prêt à démarrer');
            circularProgress.classList.add('complete');
            setRuntimeText(progressLabel, 'common.ready', 'PRÊT');
            setRuntimeText(setupStatus, 'onboarding.modelsAlreadyInstalled', 'Modèles déjà installés!');
            setRuntimeText('setup-status', 'onboarding.allReady', 'Tout est prêt!');

            const doctorResult = await apiSettings.getDoctorReport();
            if (doctorResult.ok && doctorResult.data?.success) {
                onboardingDoctor = doctorResult.data;
                renderOnboardingReadiness(onboardingDoctor);
            }

            // Apply all recommended settings based on VRAM level
            userSettings.chatModel = recommendedModel;
            applyGenerationSettings(hardwareInfo.generation_settings);
            applyImageModels(hardwareInfo.image_models);
            saveSettings();

            // Show finish button
            setTimeout(() => {
                document.getElementById('onboarding-next-btn').classList.remove('hidden');
                setRuntimeText('onboarding-next-btn', 'onboarding.start', 'Commencer');
                document.getElementById('onboarding-next-btn').disabled = false;
                document.getElementById('onboarding-skip-btn').classList.add('hidden');
            }, 500);
        } else {
            // Need to download models
            setProgress(50);
            setSetupProgressLabel('onboarding.setupStageDownloading', 'Téléchargement des modèles');

            if (!utilityInstalled && !chatInstalled) {
                setRuntimeText(setupStatus, 'onboarding.downloadTwoModels', 'Téléchargement de 2 modèles...');
            } else if (!utilityInstalled) {
                setRuntimeText(setupStatus, 'onboarding.downloadUtility', 'Téléchargement du modèle utility...');
            } else {
                setRuntimeText(setupStatus, 'onboarding.downloadChat', 'Téléchargement du modèle chat...');
            }

            setRuntimeText('setup-status', 'onboarding.installInProgress', 'Installation en cours...');
            document.getElementById('setup-eta').classList.remove('hidden');

            // Calculer l'ETA basé sur les modèles à télécharger
            const modelsToDownload = [];
            if (!utilityInstalled) modelsToDownload.push(hardwareInfo.utility_model);
            if (!chatInstalled) modelsToDownload.push(recommendedModel);
            const etaText = calculateETA(modelsToDownload);
            const setupEta = document.getElementById('setup-eta');
            if (setupEta) {
                setRuntimeText(setupEta, 'onboarding.estimatedTime', 'Temps estimé : {eta}', { eta: etaText });
            }

            // Start profile-based download (utility + chat model)
            const setupResult = await apiPost('/api/setup/profile', { profile: profile });
            if (!setupResult.ok) throw new Error(setupResult.error || 'Setup failed');
            const setupData = setupResult.data;
            console.log('[SETUP] Started:', setupData);

            // Save the chat model that will be installed + generation settings
            benchmarkData = {
                recommended_text_model: setupData.chat_model,
                utility_model: setupData.utility_model,
                generation_settings: hardwareInfo.generation_settings,
                image_models: hardwareInfo.image_models
            };

            // Poll for progress
            setupCheckInterval = setInterval(checkSetupProgress, 500);
        }
    } catch (error) {
        console.error('Benchmark error:', error);
        circularProgress.classList.remove('analyzing');
        circularProgress.classList.add('error');
        setRuntimeText(progressLabel, 'onboarding.errorShort', 'Erreur');
        setSetupProgressLabel('onboarding.errorShort', 'Erreur');
        setPlainText(setupStatus, 'Erreur: ' + error.message);

        // Allow skip
        document.getElementById('onboarding-next-btn').classList.remove('hidden');
        setRuntimeText('onboarding-next-btn', 'onboarding.continueAnyway', 'Continuer quand même');
        document.getElementById('onboarding-next-btn').disabled = false;
    }
}

async function checkSetupProgress() {
    try {
        const result = await apiGet('/api/setup/progress');
        if (!result.ok) throw new Error(result.error);
        const data = result.data;

        const progressLabel = document.getElementById('setup-label');
        const setupStatus = document.getElementById('setup-status');
        const circularProgress = document.getElementById('setup-progress');

        if (data.status === 'downloading_utility') {
            // 0-40% pour utility model
            const visualProgress = Math.min(40, data.progress * 0.4);
            setProgress(50 + visualProgress * 0.5); // 50-70%
            setSetupProgressPlainLabel(data.message || t('onboarding.downloadUtility', 'Téléchargement du modèle utility...'));
            progressLabel.textContent = data.progress + '%';
            setRuntimeText(setupStatus, 'onboarding.utilityProgress', 'Modèle utility : {message}', { message: data.message });
        } else if (data.status === 'downloading_chat') {
            // 40-100% pour chat model
            const visualProgress = 70 + (data.progress - 40) * 0.5; // 70-100%
            setProgress(Math.min(95, visualProgress));
            setSetupProgressPlainLabel(data.message || t('onboarding.downloadChat', 'Téléchargement du modèle chat...'));
            progressLabel.textContent = data.progress + '%';
            setRuntimeText(setupStatus, 'onboarding.chatProgress', 'Modèle chat : {message}', { message: data.message });
        } else if (data.status === 'downloading_text') {
            // Legacy: Map 0-100 download progress to 50-95 visual progress
            const visualProgress = 50 + (data.progress * 0.45);
            setProgress(visualProgress);
            setSetupProgressPlainLabel(data.message || t('onboarding.installInProgress', 'Installation en cours...'));
            progressLabel.textContent = data.progress + '%';
            setPlainText(setupStatus, data.message);
        } else if (data.status === 'complete') {
            clearInterval(setupCheckInterval);
            setProgress(100);
            setSetupProgressLabel('onboarding.setupStageReady', 'Prêt à démarrer');
            circularProgress.classList.add('complete');
            setRuntimeText(progressLabel, 'common.ready', 'PRÊT');
            setRuntimeText(setupStatus, 'onboarding.completed', 'Installation terminée!');
            setRuntimeText('setup-status', 'onboarding.allReady', 'Tout est prêt!');
            document.getElementById('setup-eta').classList.add('hidden');

            const doctorResult = await apiSettings.getDoctorReport();
            if (doctorResult.ok && doctorResult.data?.success) {
                onboardingDoctor = doctorResult.data;
                renderOnboardingReadiness(onboardingDoctor);
            }

            // Apply all recommended settings based on VRAM level
            if (benchmarkData?.recommended_text_model) {
                userSettings.chatModel = benchmarkData.recommended_text_model;
            } else if (data.text_model) {
                userSettings.chatModel = data.text_model;
            }
            // Apply generation settings (steps, strength, segmentation method)
            if (benchmarkData?.generation_settings) {
                applyGenerationSettings(benchmarkData.generation_settings);
            }
            // Apply image models (inpainting, text2img)
            if (benchmarkData?.image_models) {
                applyImageModels(benchmarkData.image_models);
            }
            saveSettings();

            // Show finish button
            document.getElementById('onboarding-next-btn').classList.remove('hidden');
            setRuntimeText('onboarding-next-btn', 'onboarding.start', 'Commencer');
            document.getElementById('onboarding-next-btn').disabled = false;
            document.getElementById('onboarding-skip-btn').classList.add('hidden');
        } else if (data.status === 'error') {
            clearInterval(setupCheckInterval);
            circularProgress.classList.add('error');
            setRuntimeText(progressLabel, 'onboarding.errorShort', 'Erreur');
            setSetupProgressLabel('onboarding.errorShort', 'Erreur');
            setPlainText(setupStatus, data.error || t('onboarding.downloadError', 'Erreur de téléchargement'));
            document.getElementById('setup-eta').classList.add('hidden');

            // Allow continue anyway
            document.getElementById('onboarding-next-btn').classList.remove('hidden');
            setRuntimeText('onboarding-next-btn', 'onboarding.continueAnyway', 'Continuer quand même');
            document.getElementById('onboarding-next-btn').disabled = false;
        }
    } catch (e) {
        console.error('Progress check error:', e);
    }
}

function setProgress(percent) {
    const circle = document.getElementById('progress-circle');
    const percentEl = document.getElementById('setup-percent');
    const progressFill = document.getElementById('onboarding-setup-progress-fill');
    const progressValue = document.getElementById('onboarding-setup-progress-value');
    const clamped = Math.max(0, Math.min(100, Number(percent) || 0));

    // Circumference = 2 * PI * r = 2 * 3.14159 * 52 = 326.73
    const circumference = 326.73;
    const offset = circumference - (clamped / 100) * circumference;

    if (circle) {
        circle.style.strokeDashoffset = offset;
    }
    if (percentEl) {
        percentEl.textContent = Math.round(clamped) + '%';
    }
    if (progressFill) {
        progressFill.style.width = `${clamped}%`;
    }
    if (progressValue) {
        progressValue.textContent = `${Math.round(clamped)}%`;
    }
    updateOnboardingSetupStage(clamped);
}

/**
 * Applique les paramètres de génération recommandés basés sur le niveau VRAM
 * @param {Object} settings - {steps, text2imgSteps, strength}
 */
function applyGenerationSettings(settings) {
    if (!settings) return;

    console.log('[SETUP] Application des paramètres optimisés:', settings);

    // Inpainting steps
    if (settings.steps) {
        userSettings.steps = settings.steps;
    }

    // Text2Img steps
    if (settings.text2imgSteps) {
        userSettings.text2imgSteps = settings.text2imgSteps;
    }

    // Denoising strength
    if (settings.strength) {
        userSettings.strength = settings.strength;
    }

    // NSFW strength
    if (settings.nsfwStrength) {
        userSettings.nsfwStrength = settings.nsfwStrength;
    }

    // Log le résumé
    console.log(`[SETUP] Config appliquée:
   • Inpaint steps: ${userSettings.steps}
   • Text2Img steps: ${userSettings.text2imgSteps}
   • Strength: ${Math.round(userSettings.strength * 100)}%
   • NSFW: ${Math.round((userSettings.nsfwStrength || 0.90) * 100)}%`);
}

/**
 * Applique les modèles image recommandés basés sur le niveau VRAM
 * @param {Object} imageModels - {inpainting, generation}
 */
function applyImageModels(imageModels) {
    if (!imageModels) return;

    console.log('[SETUP] Application des modèles image:', imageModels);

    // Modèle inpainting
    if (imageModels.inpainting) {
        if (typeof selectedInpaintModel !== 'undefined') {
            selectedInpaintModel = imageModels.inpainting;
        }
        Settings.set('selectedInpaintModel', imageModels.inpainting);
    }

    // Modèle text2img
    if (imageModels.generation) {
        if (typeof selectedText2ImgModel !== 'undefined') {
            selectedText2ImgModel = imageModels.generation;
        }
        Settings.set('selectedText2ImgModel', imageModels.generation);
    }

    console.log(`[SETUP] Modèles image:
   • Inpaint: ${imageModels.inpainting}
   • Text2Img: ${imageModels.generation}`);
}

async function skipOnboarding() {
    if (onboardingPreviewMode) {
        closeOnboarding();
        return;
    }

    // Stop any running setup
    if (setupCheckInterval) {
        clearInterval(setupCheckInterval);
        setupCheckInterval = null;
    }
    apiPost('/api/setup/skip', {}).catch(() => {});

    // Si on a détecté le hardware, appliquer quand même les paramètres optimisés
    if (hardwareInfo?.generation_settings) {
        applyGenerationSettings(hardwareInfo.generation_settings);
        if (hardwareInfo?.image_models) {
            applyImageModels(hardwareInfo.image_models);
        }
        saveSettings();
        console.log('[SETUP] Paramètres optimisés appliqués malgré le skip');
    }

    userProfile.hasCompletedOnboarding = true;
    userProfile.type = selectedProfileType || 'casual';
    saveProfile();

    try {
        await apiSettings.completeOnboarding({
            completed: true,
            locale: document.documentElement.lang || 'fr',
            profile_type: userProfile.type,
            profile_name: userProfile.name || ''
        });
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de marquer le skip côté backend:', error);
    }

    // Close and reveal
    closeOnboarding();
}

async function completeOnboarding() {
    const name = document.getElementById('onboarding-name').value.trim();

    if (onboardingPreviewMode) {
        closeOnboarding();
        return;
    }

    userProfile.hasCompletedOnboarding = true;
    userProfile.type = selectedProfileType || 'casual';
    userProfile.name = name;

    saveProfile();

    try {
        await apiSettings.completeOnboarding({
            completed: true,
            locale: document.documentElement.lang || 'fr',
            profile_type: userProfile.type,
            profile_name: userProfile.name || ''
        });
    } catch (error) {
        console.warn('[ONBOARDING] Impossible de finaliser côté backend:', error);
    }

    closeOnboarding();

    // Petit message de bienvenue
    console.log(`Profil configuré: ${userProfile.type}${name ? `, ${name}` : ''}`);
}

function saveProfile() {
    localStorage.setItem('userProfile', JSON.stringify(userProfile));
}

function loadProfile() {
    const saved = localStorage.getItem('userProfile');
    if (saved) {
        try {
            userProfile = { ...userProfile, ...JSON.parse(saved) };
        } catch (e) {
            console.error('Erreur chargement profil:', e);
        }
    }
}

// Récupérer le system prompt basé sur le profil
function getProfileSystemPrompt() {
    const basePrompt = PROFILE_PROMPTS[userProfile.type] || PROFILE_PROMPTS.casual;

    if (userProfile.name) {
        return basePrompt + `\n\nIMPORTANT: La personne qui te parle s'appelle ${userProfile.name}. Utilise son prénom quand c'est approprié. Toi tu es ${APP_CONFIG.name}, un assistant IA.`;
    }

    return basePrompt;
}

// Récupérer les infos de profil pour l'API
function getProfileForAI() {
    return {
        type: userProfile.type,
        name: userProfile.name,
        systemPrompt: getProfileSystemPrompt()
    };
}

// Changer le type de profil depuis les settings
function changeProfileType(type) {
    userProfile.type = type;
    saveProfile();
    updateProfileUI();
}

// Changer le prénom depuis les settings
function changeProfileName(name) {
    userProfile.name = name.trim();
    saveProfile();
}

// Mettre à jour l'UI du profil dans les settings
function updateProfileUI() {
    // Mettre à jour les options de profil
    document.querySelectorAll('.settings-profile-option').forEach(opt => {
        opt.classList.remove('selected');
        if (opt.dataset.type === userProfile.type) {
            opt.classList.add('selected');
        }
    });

    // Mettre à jour le champ nom
    const nameInput = document.getElementById('settings-profile-name');
    if (nameInput) {
        nameInput.value = userProfile.name || '';
    }
    syncLocaleSelectors(getCurrentLocale());
}

// Relancer l'onboarding
async function restartOnboarding() {
    userProfile.hasCompletedOnboarding = false;
    saveProfile();
    try {
        await apiSettings.resetOnboarding();
    } catch (error) {
        console.warn('[ONBOARDING] Reset backend impossible:', error);
    }
    closeSettings();
    openOnboarding();
}

// Initialiser l'onglet profil quand on l'ouvre
function initProfileTab() {
    updateProfileUI();
}

window.addEventListener('joyboy:locale-changed', () => {
    if (document.getElementById('onboarding-modal')?.classList.contains('open')) {
        setOnboardingSetupCopy();
        applyOnboardingFeatureSpotlight();
    }
});
