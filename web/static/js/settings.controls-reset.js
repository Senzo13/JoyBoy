// ===== SETTINGS CONTROLS AND RESET =====
// LoRA labels, generation sliders, and local reset/memory destructive actions.

// ===== LORA LABELS PER MODEL =====
// Met à jour les labels LoRA selon le modèle inpaint sélectionné
function updateLoraLabelsForModel() {
    // Utiliser le modèle effectivement sélectionné (variable globale ui.js), pas le setting sauvegardé
    const model = (typeof selectedInpaintModel !== 'undefined' ? selectedInpaintModel : null)
        || Settings.get('selectedInpaintModel') || '';
    const isFlux = model.toLowerCase().includes('flux');

    const nsfwLabel = document.getElementById('lora-nsfw-label');
    const nsfwDesc = document.getElementById('lora-nsfw-desc');
    const nsfwSliderLabel = document.getElementById('lora-nsfw-slider-label');
    const skinLabel = document.getElementById('lora-skin-label');
    const skinDesc = document.getElementById('lora-skin-desc');
    const skinSliderLabel = document.getElementById('lora-skin-slider-label');

    const breastsLabel = document.getElementById('lora-breasts-label');
    const breastsDesc = document.getElementById('lora-breasts-desc');
    const breastsSliderLabel = document.getElementById('lora-breasts-slider-label');

    if (isFlux) {
        if (nsfwLabel) nsfwLabel.textContent = 'LoRA Local Unlock';
        if (nsfwDesc) nsfwDesc.textContent = t('settings.localAdvanced.fluxUnlockDesc', 'Étend les capacités locales avancées pour Flux');
        if (nsfwSliderLabel) nsfwSliderLabel.textContent = t('settings.localAdvanced.fluxUnlockForce', 'Force LoRA Local Unlock');
        if (skinLabel) skinLabel.textContent = 'LoRA Apparel Shift';
        if (skinDesc) skinDesc.textContent = t('settings.localAdvanced.fluxApparelDesc', 'Ajuste finement les couches de vêtements via Flux');
        if (skinSliderLabel) skinSliderLabel.textContent = t('settings.localAdvanced.fluxApparelForce', 'Force LoRA Apparel');
        if (breastsLabel) breastsLabel.textContent = 'LoRA Detail Enhancer';
        if (breastsDesc) breastsDesc.textContent = t('settings.localAdvanced.fluxDetailDesc', 'Renforce les détails fins et le micro-contraste pour Flux');
        if (breastsSliderLabel) breastsSliderLabel.textContent = t('settings.localAdvanced.fluxDetailForce', 'Force LoRA Detail');
    } else {
        if (nsfwLabel) nsfwLabel.textContent = 'LoRA Local XL';
        if (nsfwDesc) nsfwDesc.textContent = t('settings.localAdvanced.xlLocalDesc', 'Améliore le réalisme des workflows locaux avancés');
        if (nsfwSliderLabel) nsfwSliderLabel.textContent = t('settings.localAdvanced.xlLocalForce', 'Force LoRA Local');
        if (skinLabel) skinLabel.textContent = 'LoRA Skin Realism';
        if (skinDesc) skinDesc.textContent = t('settings.localAdvanced.skinDesc', 'Texture de peau réaliste avec imperfections');
        if (skinSliderLabel) skinSliderLabel.textContent = t('settings.localAdvanced.skinForce', 'Force LoRA Skin');
        if (breastsLabel) breastsLabel.textContent = 'LoRA Anatomy Detail';
        if (breastsDesc) breastsDesc.textContent = t('settings.localAdvanced.anatomyDesc', 'Détails anatomiques réalistes, sans artefacts');
        if (breastsSliderLabel) breastsSliderLabel.textContent = t('settings.localAdvanced.anatomyForce', 'Force LoRA Anatomy');
    }
}

// Update setting slider value
function updateSettingSlider(settingName, value) {
    const valueEl = document.getElementById(`settings-${settingName}-value`);

    if (settingName === 'steps') {
        userSettings.steps = parseInt(value);
        if (valueEl) valueEl.textContent = value;
        document.getElementById('steps-slider').value = value;
        document.getElementById('steps-value').textContent = value;
    } else if (settingName === 'text2imgSteps') {
        userSettings.text2imgSteps = parseInt(value);
        const text2imgValueEl = document.getElementById('settings-text2img-steps-value');
        if (text2imgValueEl) text2imgValueEl.textContent = value;
    } else if (settingName === 'text2imgGuidance') {
        userSettings.text2imgGuidance = parseFloat(value);
        const guidanceEl = document.getElementById('settings-text2img-guidance-value');
        if (guidanceEl) guidanceEl.textContent = value;
    } else if (settingName === 'faceRefScale') {
        userSettings.faceRefScale = parseFloat(value);
        const faceRefEl = document.getElementById('settings-face-ref-scale-value');
        if (faceRefEl) faceRefEl.textContent = value;
    } else if (settingName === 'styleRefScale') {
        userSettings.styleRefScale = parseFloat(value);
        const styleRefEl = document.getElementById('settings-style-ref-scale-value');
        if (styleRefEl) styleRefEl.textContent = value;
    } else if (settingName === 'nsfwStrength') {
        const floatVal = parseInt(value) / 100;
        userSettings.nsfwStrength = floatVal;
        const nsfwValueEl = document.getElementById('settings-nsfw-strength-value');
        if (nsfwValueEl) nsfwValueEl.textContent = Math.round(floatVal * 100) + '%';
    } else if (settingName === 'dilation') {
        userSettings.dilation = parseInt(value);
        if (valueEl) valueEl.textContent = value;
        document.getElementById('dilation-slider').value = value;
        document.getElementById('dilation-value').textContent = value + 'px';
    } else if (settingName === 'videoDuration') {
        userSettings.videoDuration = parseInt(value);
        const durEl = document.getElementById('settings-video-duration-value');
        if (durEl) {
            const currentVideoModel = userSettings.videoModel || 'svd';
            if (currentVideoModel === 'framepack-fast') {
                durEl.textContent = t('settings.generation.videoFramepackFastDuration', '5s rapide · 60 frames');
            } else if (currentVideoModel === 'framepack') {
                durEl.textContent = userSettings.videoDuration >= 8
                    ? t('settings.generation.videoFramepackLongDuration', '10s · 180 frames')
                    : t('settings.generation.videoFramepackNormalDuration', '5s · 90 frames');
            } else {
                durEl.textContent = value + 's';
            }
        }
        if ((userSettings.videoModel || 'svd').startsWith('framepack') && typeof updateVideoQualityVisibility === 'function') {
            updateVideoQualityVisibility();
        }
    } else if (settingName === 'videoFps') {
        userSettings.videoFps = parseInt(value);
        const fpsEl = document.getElementById('settings-video-fps-value');
        if (fpsEl) fpsEl.textContent = value;
    } else if (settingName === 'videoSteps') {
        userSettings.videoSteps = parseInt(value);
        const stepsEl = document.getElementById('settings-video-steps-value');
        if (stepsEl) stepsEl.textContent = value;
    } else if (settingName === 'videoRefine') {
        userSettings.videoRefine = parseInt(value);
        const refineEl = document.getElementById('settings-video-refine-value');
        if (refineEl) refineEl.textContent = value;
    } else if (settingName === 'poseStrength') {
        userSettings.poseStrength = parseFloat(value);
        const poseStrEl = document.getElementById('settings-pose-strength-value');
        if (poseStrEl) poseStrEl.textContent = value;
    }

    saveSettings();
}

// ControlNet Depth scale (0-100 slider → 0.00-1.00 float)
function updateControlnetDepth(value) {
    const intVal = parseInt(value);
    const el = document.getElementById('settings-controlnet-depth-value');
    if (intVal === 0) {
        userSettings.controlnetDepth = null;
        if (el) el.textContent = 'Auto';
    } else {
        const floatVal = intVal / 100;
        userSettings.controlnetDepth = floatVal;
        if (el) el.textContent = floatVal.toFixed(2);
    }
}

// Composite Blur Radius (0=Auto, 1-64px)
function updateCompositeRadius(value) {
    const intVal = parseInt(value);
    const el = document.getElementById('settings-composite-radius-value');
    if (intVal === 0) {
        userSettings.compositeRadius = null;
        if (el) el.textContent = 'Auto';
    } else {
        userSettings.compositeRadius = intVal;
        if (el) el.textContent = intVal + 'px';
    }
}

// Confirm clear memory
async function confirmClearMemory() {
    const confirmed = await JoyDialog.confirm(
        t('settings.memory.confirmClear', 'Voulez-vous vraiment supprimer tous les faits mémorisés localement ?'),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    await clearAllMemories();
    initMemoryTab();
    await JoyDialog.alert(t('settings.memory.cleared', 'Mémoire locale effacée'));
}

// Reset complet - efface TOUT et repart à zéro
async function confirmFullReset() {
    const confirmed = await JoyDialog.confirm(
        t(
            'settings.reset.fullConfirm',
            'ATTENTION : cette action va tout effacer :\n\n' +
            '- Toutes les conversations\n' +
            '- Tous les faits mémorisés localement\n' +
            '- Tous les paramètres\n' +
            '- Le profil utilisateur\n' +
            '- Le cache local\n\n' +
            'Tu devras refaire le setup initial.\n\n' +
            'Continuer ?'
        ),
        { variant: 'danger' }
    );

    if (!confirmed) return;

    // Double confirmation
    const doubleConfirm = await JoyDialog.confirm(
        t('settings.reset.fullDoubleConfirm', 'Dernière chance : es-tu vraiment sûr de vouloir tout effacer ?'),
        { variant: 'danger' }
    );
    if (!doubleConfirm) return;

    console.log('[RESET] Reset complet en cours...');

    try {
        // 1. Vider IndexedDB (conversations, mémoires, settings)
        if (typeof clearCacheDB === 'function') {
            await clearCacheDB();
            console.log('[RESET] IndexedDB vidée');
        }

        // 2. Vider localStorage
        localStorage.clear();
        console.log('[RESET] localStorage vidé');

        // 3. Vider sessionStorage
        sessionStorage.clear();
        console.log('[RESET] sessionStorage vidé');

        // 4. Supprimer les cookies du domaine (si existants)
        document.cookie.split(";").forEach(c => {
            document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;expires=" + new Date().toUTCString() + ";path=/");
        });
        console.log('[RESET] Cookies supprimés');

        // 5. Réinitialiser aussi l'onboarding backend/local config hors navigateur.
        // Sinon l'app peut rester cachée après un reset navigateur complet.
        try {
            sessionStorage.setItem('forceOnboardingAfterReset', '1');
            await apiSettings.resetOnboarding();
            console.log('[RESET] onboarding backend réinitialisé');
        } catch (error) {
            console.warn('[RESET] Reset onboarding backend impossible:', error);
        }

        await JoyDialog.alert(t('settings.reset.fullDone', 'Reset complet terminé. La page va se recharger.'));

        // 6. Recharger la page (va redéclencher l'onboarding)
        window.location.reload();

    } catch (err) {
        console.error('[RESET] Erreur:', err);
        await JoyDialog.alert(t('settings.reset.fullError', 'Erreur pendant le reset : {error}', { error: err.message }), { variant: 'danger' });
    }
}

// Confirm clear all chats
async function confirmClearChats() {
    const confirmed = await JoyDialog.confirm(
        t('settings.memory.confirmClearChats', 'Voulez-vous vraiment supprimer toutes les conversations locales ?'),
        { variant: 'danger' }
    );
    if (!confirmed) return;

    await clearCacheDB();
    initMemoryTab();
    showHome();
    await JoyDialog.alert(t('settings.memory.clearedChats', 'Conversations locales supprimées'));
}

// Check models status - séparer installés et disponibles

// ========== ONBOARDING ==========
