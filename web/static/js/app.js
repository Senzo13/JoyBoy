// ===== APP - Main initialization =====
// Note: resizeImageToTarget() est défini dans editor.js (chargé avant app.js)

function appT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

/**
 * Charge une image et la resize à la taille de génération
 * @param {string} imageSrc - Data URL de l'image
 */
async function setCurrentImage(imageSrc) {
    if (typeof clearVideoSource === 'function') clearVideoSource();
    currentImage = await resizeImageToTarget(imageSrc);
    updateImagePreviews();
    updateModelPickerDisplay();
    if (typeof onImageAdded === 'function') {
        onImageAdded();
    }
    updateSendButtonState('home');
    updateSendButtonState('chat');
}

// Video model defaults helper
function getVideoModelDefaults(model) {
    // Defaults fixes par modèle (non modifiables par l'utilisateur)
    const modelDefaults = {
        'wan22': { name: 'Wan 2.2 A14B', fps: 16, steps: 40, configurable: false },
        'wan': { name: 'Wan 2.1 14B', fps: 16, steps: 50, configurable: true },
        'wan22-5b': { name: 'Wan 2.2 5B', fps: 24, steps: 30, configurable: true },
        'fastwan': { name: 'FastWan 2.2 5B', fps: 24, steps: 8, configurable: false },
        'hunyuan': { name: 'HunyuanVideo 1.5', fps: 15, steps: 12, configurable: false },
        'svd': { name: 'SVD 1.1', fps: 8, steps: 18, configurable: true },
        'ltx': { name: 'LTX-Video 2B', fps: 8, steps: 8, configurable: false },
        'ltx2': { name: 'LTX-2 19B', fps: 24, steps: 8, configurable: false },  // distillé 8 steps
        'ltx2_fp8': { name: 'LTX-2 19B FP8', fps: 24, steps: 40, configurable: false },  // fp8 pré-quantifié
        'cogvideox': { name: 'CogVideoX-5B experimental', fps: 8, steps: 50, configurable: false },
        'cogvideox-q4': { name: 'CogVideoX-5B Q4 experimental', fps: 8, steps: 50, configurable: false },
        'cogvideox-2b': { name: 'CogVideoX-2B', fps: 8, steps: 50, configurable: false },
        'framepack': { name: 'FramePack F1 I2V', fps: 18, steps: 9, configurable: false },
        'framepack-fast': { name: 'FramePack F1 rapide', fps: 12, steps: 7, configurable: false },
    };
    const fallbackDefaults = modelDefaults[model] || modelDefaults['svd'];
    const runtimeDefaults = window.videoModelRuntimeDefaults?.[model];
    const defaults = { ...fallbackDefaults, ...(runtimeDefaults || {}) };

    // CogVideoX: params fixes (le modèle est entraîné pour ces valeurs)
    // Wan/SVD: settings utilisateur autorisés
    const fps = defaults.configurable ? (userSettings.videoFps || defaults.fps) : defaults.fps;
    let steps = defaults.configurable ? (userSettings.videoSteps || defaults.steps) : defaults.steps;
    const duration = userSettings.videoDuration ?? 5;
    let frames = Math.max(1, Math.round(duration * fps));

    if (model === 'framepack-fast') {
        frames = 60;
        steps = 7;
    } else if (model === 'framepack') {
        const longMode = duration >= 8;
        frames = longMode ? 180 : 90;
        steps = 9;
    }

    return {
        name: defaults.name,
        frames: frames,
        steps: steps,
        fps: fps,
    };
}

// ===== COMPOSER ACTION MENU =====

let composerActionMenuAnchor = null;

function getComposerActionMenu() {
    return document.getElementById('composer-action-menu');
}

function positionComposerActionMenu(anchor) {
    const menu = getComposerActionMenu();
    if (!menu || !anchor) return;

    const margin = 10;
    const rect = anchor.getBoundingClientRect();

    menu.style.left = '0px';
    menu.style.top = '0px';

    const menuRect = menu.getBoundingClientRect();
    let left = rect.left;
    left = Math.max(12, Math.min(left, window.innerWidth - menuRect.width - 12));

    let top = rect.bottom + margin;
    if (top + menuRect.height > window.innerHeight - 12) {
        top = rect.top - menuRect.height - margin;
    }
    top = Math.max(12, top);

    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
}

function openComposerActionMenu(anchor) {
    const menu = getComposerActionMenu();
    if (!menu || !anchor) return;

    composerActionMenuAnchor = anchor;
    menu.classList.add('is-open');
    menu.setAttribute('aria-hidden', 'false');
    positionComposerActionMenu(anchor);
}

function closeComposerActionMenu() {
    const menu = getComposerActionMenu();
    if (!menu) return;
    menu.classList.remove('is-open');
    menu.setAttribute('aria-hidden', 'true');
    composerActionMenuAnchor = null;
}

function toggleComposerActionMenu(event) {
    const button = event?.currentTarget || event?.target;
    const menu = getComposerActionMenu();
    if (!menu || !button) return;

    if (menu.classList.contains('is-open') && composerActionMenuAnchor === button) {
        closeComposerActionMenu();
        return;
    }

    openComposerActionMenu(button);
}

function chooseComposerAction(type) {
    const inputMap = {
        image: 'file-input',
        face: 'face-ref-input',
        style: 'style-ref-input',
    };

    const targetId = inputMap[type];
    closeComposerActionMenu();
    if (!targetId) return;

    const input = document.getElementById(targetId);
    input?.click();
}

// ===== EVENT LISTENERS =====

// File input handler - resize à la taille de génération
document.getElementById('file-input')?.addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        if (file.type?.startsWith('video/')) {
            setCurrentVideoSourceFromFile(file);
        } else {
            const reader = new FileReader();
            reader.onload = async function(e) {
                await setCurrentImage(e.target.result);
            };
            reader.readAsDataURL(file);
        }
    }
    e.target.value = '';
});

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = event => resolve(event.target.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

// Face ref input handler (1-5 images, merged server-side)
document.getElementById('face-ref-input')?.addEventListener('change', async function(e) {
    const currentRefs = typeof getFaceRefImages === 'function' ? getFaceRefImages() : [];
    const maxRefs = typeof MAX_FACE_REF_IMAGES !== 'undefined' ? MAX_FACE_REF_IMAGES : 5;
    const remainingSlots = Math.max(0, maxRefs - currentRefs.length);
    if (remainingSlots <= 0) {
        e.target.value = '';
        return;
    }
    const files = Array.from(e.target.files || [])
        .filter(file => file.type?.startsWith('image/'))
        .slice(0, remainingSlots);

    if (!files.length) {
        e.target.value = '';
        return;
    }

    const images = await Promise.all(files.map(readFileAsDataUrl));
    faceRefImages = [...currentRefs, ...images].slice(0, maxRefs);
    syncFaceRefLegacy();
    if (typeof updateFaceRefPreviews === 'function') updateFaceRefPreviews();
    if (typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }
    e.target.value = '';
});

// Style ref input handler
document.getElementById('style-ref-input')?.addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            styleRefImage = e.target.result;
            if (typeof updateStyleRefPreviews === 'function') updateStyleRefPreviews();
        };
        reader.readAsDataURL(file);
    }
});

// Ctrl+V paste handler - resize à la taille de génération
document.addEventListener('paste', function(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('video') !== -1) {
            const blob = items[i].getAsFile();
            if (blob) {
                setCurrentVideoSourceFromFile(blob);
                e.preventDefault();
                return;
            }
        }
    }
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
            const blob = items[i].getAsFile();
            const reader = new FileReader();
            reader.onload = async function(e) {
                await setCurrentImage(e.target.result);
            };
            reader.readAsDataURL(blob);
            e.preventDefault();
            break;
        }
    }
});

async function setCurrentVideoSourceFromFile(file) {
    if (!file || !file.type?.startsWith('video/')) return;
    try {
        const dataUrl = await readFileAsDataUrl(file);
        const videoModel = userSettings.videoModel || 'svd';
        const videoDefaults = getVideoModelDefaults(videoModel);
        const activeInput = document.activeElement?.id === 'chat-prompt'
            ? document.getElementById('chat-prompt')
            : document.getElementById('prompt-input');
        const prompt = activeInput?.value?.trim?.() || '';
        if (window.Toast?.info) Toast.info('Vidéo ajoutée comme source de continuation');
        const result = await apiGeneration.registerVideoSource({
            video: dataUrl,
            fileName: file.name || 'video',
            prompt,
            video_model: videoModel,
            fps: videoDefaults.fps,
            chatId: typeof currentChatId !== 'undefined' ? currentChatId : null,
        });
        if (!result.ok || !result.data?.success) {
            Toast.error(result.data?.error || 'Impossible de préparer la vidéo');
            return;
        }
        currentImage = null;
        updateImagePreviews();
        currentVideoSource = {
            ...result.data,
            thumbnail: result.data.continuationAnchors?.[0]?.thumbnail || '',
            fileName: result.data.fileName || file.name || 'video',
        };
        if (typeof updateLastVideoContextFromResult === 'function') {
            updateLastVideoContextFromResult(result.data, prompt, null, currentChatId);
        }
        updateVideoSourcePreviews();
        if (typeof updateSendButtonState === 'function') {
            updateSendButtonState('home');
            updateSendButtonState('chat');
        }
    } catch (error) {
        console.error('[VIDEO] Source upload error:', error);
        Toast.error(error.message || 'Erreur upload vidéo');
    }
}

// Cancel only the local fetch on page unload.
// Do NOT send /cancel-all here: long image/video jobs are durable now and the
// app can reconnect to their progress after a refresh or conversation switch.
window.addEventListener('beforeunload', function() {
    if (isGenerating && currentController) {
        currentController.abort();
    }
});

// Enter key handlers for prompts
// Enter = envoyer, Shift+Enter = nouvelle ligne (si textarea)
document.getElementById('prompt-input')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        generate();
    }
    handlePromptKeydown(e, this);
});

document.getElementById('chat-prompt')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        continueChat();
    }
    handlePromptKeydown(e, this);
});



// Edit prompt handlers
document.getElementById('edit-prompt')?.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        generateEdit();
    }
    handlePromptKeydown(e, this);
});

// Preset modal enter key
document.getElementById('preset-edit-input')?.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') savePreset();
});

// Close dropdowns on click outside
document.addEventListener('click', function(e) {
    const composerMenu = getComposerActionMenu();
    if (composerMenu && composerMenu.classList.contains('is-open')) {
        const clickedTrigger = e.target?.closest?.('.attach-btn');
        const clickedInsideMenu = composerMenu.contains(e.target);
        if (!clickedTrigger && !clickedInsideMenu) {
            closeComposerActionMenu();
        }
    }

    const dropdown = document.getElementById('model-dropdown');
    const chatDropdown = document.getElementById('chat-model-dropdown');
    if (dropdown && !dropdown.contains(e.target)) {
        dropdown.classList.remove('open');
    }
    if (chatDropdown && !chatDropdown.contains(e.target)) {
        chatDropdown.classList.remove('open');
    }
});

// Click on image preview -> open edit modal (solo mode)
document.getElementById('image-preview')?.addEventListener('click', function() {
    if (this.src && this.style.display !== 'none') {
        openEditModal(this.src);
    }
});

document.getElementById('chat-image-preview')?.addEventListener('click', function() {
    if (this.src && this.style.display !== 'none') {
        openEditModal(this.src);
    }
});

// ALT key -> ouvrir le modal d'edit directement
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeComposerActionMenu();
    }

    if (e.key === 'Alt' && !document.getElementById('edit-modal')?.classList.contains('open')) {
        const homePreview = document.getElementById('image-preview');
        const chatPreview = document.getElementById('chat-image-preview');

        let imgSrc = null;
        if (homePreview && homePreview.style.display !== 'none' && homePreview.src) {
            imgSrc = homePreview.src;
        } else if (chatPreview && chatPreview.style.display !== 'none' && chatPreview.src) {
            imgSrc = chatPreview.src;
        }

        if (imgSrc) {
            e.preventDefault();
            openEditModal(imgSrc);
        }
    }
});

window.addEventListener('resize', function() {
    if (composerActionMenuAnchor) {
        positionComposerActionMenu(composerActionMenuAnchor);
    }
});

// Handle video button click - T2V (text to video) or I2V (image to video)
async function handleVideoClick() {
    // Get prompt from the appropriate input
    const homePrompt = document.getElementById('prompt-input');
    const chatPrompt = document.getElementById('chat-prompt');
    const prompt = (document.activeElement?.id === 'chat-prompt'
        ? (chatPrompt?.value || homePrompt?.value || '')
        : (homePrompt?.value || chatPrompt?.value || '')
    ).trim();

    // Check if there's an image in the input
    const homePreview = document.getElementById('image-preview');
    const chatPreview = document.getElementById('chat-image-preview');

    let imgSrc = null;
    if (homePreview && homePreview.style.display !== 'none' && homePreview.src) {
        imgSrc = homePreview.src;
    } else if (chatPreview && chatPreview.style.display !== 'none' && chatPreview.src) {
        imgSrc = chatPreview.src;
    }

    if (isGenerating) {
        if (!currentVideoSource?.videoSessionId && !imgSrc && !prompt) {
            await JoyDialog.alert(appT('app.videoPromptRequired', 'Écris un prompt pour la vidéo (T2V mode)'));
            return;
        }
        await addToQueue(prompt || 'Vidéo', 'video', {
            image: imgSrc,
            videoSource: currentVideoSource ? { ...currentVideoSource } : null,
        });
        resetComposerTextarea('prompt-input');
        resetComposerTextarea('chat-prompt');
        console.log(`[VIDEO] Prompt ajouté à la queue: ${(prompt || 'Vidéo').substring(0, 30)}...`);
        return;
    }

    if (currentVideoSource?.videoSessionId) {
        openVideoContinuationPanel({
            videoSessionId: currentVideoSource.videoSessionId,
            prefillPrompt: prompt,
        });
        return;
    }

    // T2V mode: no image, just prompt
    if (!imgSrc) {
        if (!prompt) {
            await JoyDialog.alert(appT('app.videoPromptRequired', 'Écris un prompt pour la vidéo (T2V mode)'));
            return;
        }
        // Generate video from text only
        await generateVideoFromText(prompt);
        return;
    }

    // I2V mode: with image (and optional prompt)
    await generateVideoFromImageWithPrompt(imgSrc, prompt);
}

// Generate video from text only (T2V mode)
async function generateVideoFromText(prompt) {
    if (isGenerating) return;

    const requestChatId = typeof ensureVisibleChatForRequest === 'function'
        ? await ensureVisibleChatForRequest({ title: prompt })
        : typeof ensureActiveChatForRequest === 'function'
            ? await ensureActiveChatForRequest({ title: prompt })
            : currentChatId;
    if (typeof showChat === 'function') {
        showChat();
    }

    isGenerating = true;
    currentGenerationMode = 'video';
    currentGenerationChatId = requestChatId;
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') {
        setSendButtonsMode(true);
    } else {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }

    const videoModel = userSettings.videoModel || 'svd';
    const videoDefaults = getVideoModelDefaults(videoModel);
    const targetFrames = videoDefaults.frames;
    const numSteps = videoDefaults.steps;
    const modelName = videoDefaults.name;

    // Clear input
    resetComposerTextarea('prompt-input');
    resetComposerTextarea('chat-prompt');

    // Add user message with video prompt
    if (typeof addUserMessageToChat === 'function') {
        const title = 'Text to Video';
        const displayPrompt = prompt ? `${title}: ${prompt}` : title;
        const renderedPrompt = typeof buildVideoUserPromptHtml === 'function'
            ? buildVideoUserPromptHtml(title, prompt)
            : displayPrompt;
        addUserMessageToChat(renderedPrompt, {
            fullPrompt: prompt ? `${title}\n${prompt}` : title,
            renderedHtml: typeof buildVideoUserPromptHtml === 'function',
        });
    }

    // Add video skeleton (no source image for T2V)
    if (typeof addVideoSkeletonToChat === 'function') {
        addVideoSkeletonToChat(null, requestChatId);
    }

    if (typeof scrollToBottom === 'function') {
        scrollToBottom(true);
    }

    const startTime = Date.now();

    startVideoProgressPolling();

    try {
        const result = await apiGeneration.generateVideo({
            image: null,
            prompt: prompt,
            video_model: videoModel,
            target_frames: targetFrames,
            num_steps: numSteps,
            fps: videoDefaults.fps,
            add_audio: userSettings.videoAudio === true,
            audio_engine: userSettings.videoAudioEngine || 'auto',
            quality: userSettings.videoQuality || '720p',
            allow_experimental_video: userSettings.showAdvancedVideoModels === true,
            chatId: requestChatId
        });

        stopVideoProgressPolling();
        const data = result.data;
        const generationTime = (Date.now() - startTime) / 1000;

        if (data?.success && data.video) {
            if (typeof updateLastVideoContextFromResult === 'function') {
                updateLastVideoContextFromResult(data, prompt, null, requestChatId);
            }
            if (typeof replaceVideoSkeletonWithReal === 'function') {
                replaceVideoSkeletonWithReal(null, data.format || 'mp4', generationTime * 1000, requestChatId, data);
            }
        } else {
            if (typeof replaceVideoSkeletonWithError === 'function') {
                replaceVideoSkeletonWithError(data?.error || 'Génération échouée', requestChatId);
            }
        }
    } catch (error) {
        stopVideoProgressPolling();
        console.error('T2V generation error:', error);
        if (typeof replaceVideoSkeletonWithError === 'function') {
            replaceVideoSkeletonWithError(error.message, requestChatId);
        }
    } finally {
        isGenerating = false;
        currentGenerationId = null;
        currentGenerationMode = null;
        currentGenerationChatId = null;
        if (typeof setSendButtonsMode === 'function') {
            setSendButtonsMode(false);
        } else {
            updateSendButtonState('home');
            updateSendButtonState('chat');
        }
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') processNextInQueue();
        }, 100);
    }
}

// Generate video from image with optional prompt (I2V mode)
async function generateVideoFromImageWithPrompt(imgSrc, prompt) {
    if (isGenerating) return;

    const requestChatId = typeof ensureVisibleChatForRequest === 'function'
        ? await ensureVisibleChatForRequest({ title: prompt || 'Vidéo' })
        : typeof ensureActiveChatForRequest === 'function'
            ? await ensureActiveChatForRequest({ title: prompt || 'Vidéo' })
            : currentChatId;
    if (typeof showChat === 'function') {
        showChat();
    }

    isGenerating = true;
    currentGenerationMode = 'video';
    currentGenerationChatId = requestChatId;
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') {
        setSendButtonsMode(true);
    } else {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }

    const videoModel = userSettings.videoModel || 'svd';
    const videoDefaults = getVideoModelDefaults(videoModel);
    const targetFrames = videoDefaults.frames;
    const numSteps = videoDefaults.steps;
    const modelName = videoDefaults.name;

    // Clear input
    resetComposerTextarea('prompt-input');
    resetComposerTextarea('chat-prompt');

    const displayPrompt = prompt ? `${modelName}: ${prompt}` : modelName;
    const renderedPrompt = typeof buildVideoUserPromptHtml === 'function'
        ? buildVideoUserPromptHtml(modelName, prompt)
        : displayPrompt;
    const usedVideoSkeleton = typeof addUserMessageWithThumb === 'function' && typeof addVideoSkeletonToChat === 'function';
    if (typeof addUserMessageWithThumb === 'function' && typeof addVideoSkeletonToChat === 'function') {
        addUserMessageWithThumb(renderedPrompt, imgSrc, {
            fullPrompt: prompt ? `${modelName}\n${prompt}` : modelName,
            renderedHtml: typeof buildVideoUserPromptHtml === 'function',
        });
        addVideoSkeletonToChat(imgSrc, requestChatId);
    } else if (typeof addSkeletonMessage === 'function') {
        addSkeletonMessage(displayPrompt, imgSrc, true, null, requestChatId);
    }

    if (typeof scrollToBottom === 'function') {
        scrollToBottom(true);
    }

    const startTime = Date.now();

    startVideoProgressPolling();

    try {
        const result = await apiGeneration.generateVideo({
            image: imgSrc,
            prompt: prompt,
            video_model: videoModel,
            target_frames: targetFrames,
            num_steps: numSteps,
            fps: videoDefaults.fps,
            add_audio: userSettings.videoAudio === true,
            audio_engine: userSettings.videoAudioEngine || 'auto',
            face_restore: userSettings.faceRestore || 'off',
            quality: userSettings.videoQuality || '720p',
            refine_passes: parseInt(userSettings.videoRefine) || 0,
            allow_experimental_video: userSettings.showAdvancedVideoModels === true,
            chatId: requestChatId
        });

        stopVideoProgressPolling();
        const data = result.data;
        const generationTime = (Date.now() - startTime) / 1000;

        if (data?.success && data.video) {
            if (typeof _lastVideoContext !== 'undefined') {
                if (typeof updateLastVideoContextFromResult === 'function') {
                    updateLastVideoContextFromResult(data, prompt, imgSrc, requestChatId);
                } else {
                    _lastVideoContext.prompt = prompt;
                    _lastVideoContext.sourceImage = imgSrc;
                    _lastVideoContext.canContinue = data.canContinue;
                }
            }
            if (usedVideoSkeleton && typeof replaceVideoSkeletonWithReal === 'function') {
                replaceVideoSkeletonWithReal(data.video, data.format || 'mp4', generationTime * 1000, requestChatId, data);
            } else if (typeof addMessageVideo === 'function') {
                if (typeof removeSkeletonMessage === 'function') {
                    removeSkeletonMessage(requestChatId);
                }
                addMessageVideo(data.video, generationTime, imgSrc, data.canContinue, modelName, requestChatId, data);
            }
        } else {
            if (usedVideoSkeleton && typeof replaceVideoSkeletonWithError === 'function') {
                replaceVideoSkeletonWithError(data?.error || appT('app.generationFailed', 'Génération échouée'), requestChatId);
            } else if (typeof removeSkeletonMessage === 'function') {
                removeSkeletonMessage(requestChatId);
            }
            await JoyDialog.alert(appT('common.errorWithMessage', 'Erreur : {error}', {
                error: data?.error || appT('app.generationFailed', 'Génération échouée'),
            }), { variant: 'danger' });
        }
    } catch (error) {
        stopVideoProgressPolling();
        console.error('I2V generation error:', error);
        if (usedVideoSkeleton && typeof replaceVideoSkeletonWithError === 'function') {
            replaceVideoSkeletonWithError(error.message, requestChatId);
        } else if (typeof removeSkeletonMessage === 'function') {
            removeSkeletonMessage(requestChatId);
        }
        await JoyDialog.alert(appT('common.errorWithMessage', 'Erreur : {error}', { error: error.message }), { variant: 'danger' });
    } finally {
        isGenerating = false;
        currentGenerationId = null;
        currentGenerationMode = null;
        currentGenerationChatId = null;
        if (typeof setSendButtonsMode === 'function') {
            setSendButtonsMode(false);
        } else {
            updateSendButtonState('home');
            updateSendButtonState('chat');
        }
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') processNextInQueue();
        }, 100);
    }
}

// Reconnecte au progress d'une génération vidéo après refresh
function reconnectVideoProgress() {
    // Si pas de skeleton existant (chat vide), en créer un minimal
    const messagesDiv = document.getElementById('chat-messages');
    if (messagesDiv && !document.querySelector('.image-skeleton-message')) {
        const chatView = document.getElementById('chat-view');
        const homeView = document.getElementById('home-view');
        if (chatView) chatView.style.display = 'flex';
        if (homeView) homeView.style.display = 'none';

        messagesDiv.insertAdjacentHTML('beforeend', `
            <div class="message image-skeleton-message video-skeleton-message" data-started-at="${Date.now()}">
                <div class="ai-response loading">
                    <div class="result-images">
                        <div class="result-image-container modified-skeleton-container">
                            <div class="skeleton-preview-container">
                                <div class="skeleton skeleton-image"></div>
                                <div class="generation-progress">
                                    <div class="generation-progress-bar" style="width: 0%"></div>
                                </div>
                                <div class="generation-step-text">Reconnexion...</div>
                            </div>
                            <div class="image-label">${appT('app.videoInProgress', 'Vidéo en cours')}</div>
                        </div>
                    </div>
                </div>
            </div>
        `);
    }

    // Polling with custom handler: reload page when generation finishes
    startVideoProgressPolling((progress) => {
        if (progress.active) {
            updateVideoSkeletonProgress(progress);
        } else {
            stopVideoProgressPolling();
            isGenerating = false;
            location.reload();
        }
    });
}

// Met à jour le skeleton avec la progression vidéo
function updateVideoSkeletonProgress(progress) {
    // Important: a chat can contain several old video results. Always update the
    // newest still-active skeleton; using querySelector() would target the first
    // old message and leave the current generation stuck on "Préparation...".
    const activeVideoSkeletons = Array.from(document.querySelectorAll('.video-skeleton-message'))
        .filter(node => node.querySelector('.video-skeleton, .skeleton-preview-container'));
    const activeImageSkeletons = Array.from(document.querySelectorAll('.image-skeleton-message'));
    const skeleton = activeVideoSkeletons.at(-1) || activeImageSkeletons.at(-1);
    if (!skeleton) return;

    const progressBar = skeleton.querySelector('.generation-progress-bar');
    const stepText = skeleton.querySelector('.generation-step-text');

    if (!progressBar || !stepText) return;

    const safeStep = Number(progress.step) || 0;
    const safeTotal = Math.max(Number(progress.total_steps) || 0, 1);
    const safePass = Math.max(Number(progress.pass) || 1, 1);
    const safeTotalPasses = Math.max(Number(progress.total_passes) || 1, 1);

    let percent = 0;
    let text = progress.message || '';

    if (progress.phase === 'loading') {
        percent = 5;
        text = text || 'Chargement...';
    } else if (progress.phase === 'generating') {
        // Progression basée sur les passes et steps
        const passProgress = (safePass - 1) / safeTotalPasses;
        const stepProgress = safeStep / safeTotal / safeTotalPasses;
        percent = Math.round((passProgress + stepProgress) * 80) + 10; // 10-90%
        text = text || `Passe ${safePass}/${safeTotalPasses}`;
    } else if (progress.phase === 'decoding') {
        const decodeProgress = safeStep / safeTotal;
        percent = Math.round(90 + decodeProgress * 6); // 90-96%
        text = text || `Décodage vidéo ${safeStep}/${safeTotal}`;
    } else if (progress.phase === 'restoring' || progress.phase === 'face_restore') {
        percent = 92;
        text = text || 'Restauration visages...';
    } else if (progress.phase === 'encoding') {
        const encodeProgress = safeStep / safeTotal;
        percent = Math.round(96 + encodeProgress * 3); // 96-99%
        text = text || `Export MP4 ${safeStep}/${safeTotal}`;
    } else if (progress.phase === 'audio') {
        percent = 99;
        text = text || 'Audio...';
    } else {
        percent = Math.min(99, Math.max(0, Math.round((safeStep / safeTotal) * 100)));
        text = text || 'Préparation...';
    }

    progressBar.style.width = Math.max(0, Math.min(percent, 99)) + '%';
    stepText.textContent = text;
}

// Double-click to reset sliders
document.getElementById('dilation-slider')?.addEventListener('dblclick', function() {
    this.value = DEFAULT_DILATION;
    updateDilation(DEFAULT_DILATION);
});

document.getElementById('strength-slider')?.addEventListener('dblclick', function() {
    this.value = DEFAULT_STRENGTH;
    updateStrength(DEFAULT_STRENGTH);
});

document.getElementById('steps-slider')?.addEventListener('dblclick', function() {
    this.value = DEFAULT_STEPS;
    updateSteps(DEFAULT_STEPS);
});

// Auto-resize textareas
function autoResizeTextarea(textarea) {
    if (!textarea) return;
    const minHeight = 32;
    const maxHeight = 150;
    textarea.style.height = 'auto';
    const nextHeight = Math.max(minHeight, Math.min(textarea.scrollHeight, maxHeight));
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';

    if (typeof updateChatPadding === 'function') {
        requestAnimationFrame(updateChatPadding);
    }
}

function resetComposerTextarea(textareaOrId) {
    const textarea = typeof textareaOrId === 'string'
        ? document.getElementById(textareaOrId)
        : textareaOrId;
    if (!textarea) return;
    textarea.value = '';
    autoResizeTextarea(textarea);
}

document.getElementById('prompt-input')?.addEventListener('input', function() {
    autoResizeTextarea(this);
    updateSendButtonState('home');
});

document.getElementById('chat-prompt')?.addEventListener('input', function() {
    autoResizeTextarea(this);
    updateSendButtonState('chat');
});

// Update send button cursor based on input content
function updateSendButtonState(mode) {
    const isHome = mode === 'home';
    const input = document.getElementById(isHome ? 'prompt-input' : 'chat-prompt');
    const sendBtn = document.getElementById(isHome ? 'send-btn' : 'chat-send-btn');

    if (!input || !sendBtn) return;

    // Always enable during generation (for stop button)
    if (typeof isGenerating !== 'undefined' && isGenerating) {
        sendBtn.classList.remove('empty');
        return;
    }

    const hasContent = input.value.trim().length > 0;
    // Check global currentImage variable instead of style
    const hasImage = typeof currentImage !== 'undefined' && currentImage !== null;

    if (hasContent || hasImage) {
        sendBtn.classList.remove('empty');
        sendBtn.classList.add('ready');
    } else {
        sendBtn.classList.add('empty');
        sendBtn.classList.remove('ready');
    }
}

// Initialize send button states on page load
document.addEventListener('DOMContentLoaded', function() {
    updateSendButtonState('home');
    updateSendButtonState('chat');
    autoResizeTextarea(document.getElementById('prompt-input'));
    autoResizeTextarea(document.getElementById('chat-prompt'));
    // Reset restart buttons state (au cas où un restart précédent les a bloqués)
    if (typeof resetRestartButtons === 'function') {
        resetRestartButtons();
    }
});

// Refocus input après envoi de message
function refocusChatInput() {
    const chatPrompt = document.getElementById('chat-prompt');
    const promptInput = document.getElementById('prompt-input');

    // Resynchronise la hauteur: vide => une ligne, texte conservé => taille réelle.
    if (chatPrompt) {
        autoResizeTextarea(chatPrompt);
        setTimeout(() => chatPrompt.focus(), 100);
    }
    if (promptInput) {
        autoResizeTextarea(promptInput);
        setTimeout(() => promptInput.focus(), 100);
    }
}

// ===== INITIALIZATION =====
async function loadAppConfig() {
    try {
        const result = await apiConfig.get();
        if (result.data) {
            APP_CONFIG = { ...APP_CONFIG, ...result.data };
            if (result.data.defaults) {
                DEFAULT_STEPS = result.data.defaults.steps ?? DEFAULT_STEPS;
                DEFAULT_STRENGTH = result.data.defaults.strength ?? DEFAULT_STRENGTH;
                DEFAULT_DILATION = result.data.defaults.dilation ?? DEFAULT_DILATION;
            }
        }
        console.log(`[CONFIG] ${APP_CONFIG.name} loaded`);
    } catch (e) {
        console.warn('[CONFIG] Using default config');
    }
}

// Log ASCII art to console
async function logAsciiArt() {
    try {
        const response = await fetch('/static/ascii-art/joyboy.txt');
        const ascii = await response.text();
        console.log('\n%c' + ascii, 'color: #a855f7; font-family: monospace; font-size: 10px;');
        console.log('%c Dream. Create. Be Free. ', 'background: linear-gradient(90deg, #a855f7, #3b82f6); color: white; font-size: 14px; padding: 5px 15px; border-radius: 5px; font-weight: bold;');
        console.log('%c 100% Local · Zero Cloud · No Limits ', 'color: #666; font-size: 11px;');
        console.log('\n');
    } catch (e) {
        console.log('%c JoyBoy ', 'background: #a855f7; color: white; font-size: 16px; padding: 5px 15px; border-radius: 5px;');
    }
}

async function init() {
    // Log ASCII art to browser console
    logAsciiArt();

    // Vérifier si une génération vidéo est en cours AVANT d'unload
    // Retry 2x en cas de latence réseau (Cloudflare tunnel, etc.)
    let activeVideoGeneration = false;
    for (let attempt = 0; attempt < 2 && !activeVideoGeneration; attempt++) {
        try {
            const vpResult = await apiGeneration.getVideoProgress();
            if (vpResult.data?.active) {
                activeVideoGeneration = true;
                console.log('[INIT] Génération vidéo en cours, skip unload-all');
                isGenerating = true;
                reconnectVideoProgress();
            }
        } catch (e) {
            console.warn(`[INIT] video-progress check failed (attempt ${attempt + 1}):`, e.message);
            if (attempt === 0) await new Promise(r => setTimeout(r, 1000));
        }
    }

    // NOTE: Plus de déchargement au refresh - les modèles restent chargés pour réutilisation rapide
    // L'utilisateur peut utiliser /unload ou le terminal pour décharger manuellement si besoin

    // Load config first
    await loadAppConfig();

    // Effects
    initEffects();

    // Load data
    loadPresets();
    loadConversationCache({ showHomeOnLoad: !activeVideoGeneration });
    if (typeof startRuntimeJobsPolling === 'function') startRuntimeJobsPolling();

    // Apply settings to UI (settings loaded at SettingsContext construction time)
    initSettingsFromCache();
    loadProfile();

    // Charger les modèles texte pour le picker
    loadTextModelsForPicker();

    // Mettre à jour le picker avec le modèle chat actif
    updateModelPickerDisplay();

    // Version/update status is deliberately subtle: no modal, just a small
    // header pill when a published release or dev checkout update exists.
    if (typeof initAppVersionStatus === 'function') {
        initAppVersionStatus();
    }

    // Check onboarding almost immediately. The modal now opens from local state
    // first, so first launch does not wait on backend Doctor/model checks.
    setTimeout(() => {
        checkOnboarding();
    }, 40);

    // Initialize UI components
    initPrivacyButton();
    initSidebarState();
    initModalZoom();
    initEditorZoom();
    initEditorKeyboard();
}

// Run on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
