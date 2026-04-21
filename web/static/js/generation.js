// ===== GENERATION - API calls =====
// Génération d'images (inpainting, text2img) et chat streaming
// Note: Le mode terminal est dans terminal.js

// Strength: frontend envoie userSettings.strength, le backend utilise comme override
// Si non fourni, le Smart Router décide automatiquement

function generationT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function getGenerationErrorMessage(result, fallback = '') {
    const data = result?.data || {};
    const fallbackText = fallback || generationT('common.unknownError', 'Erreur inconnue');
    if (data.userMessageKey) {
        return generationT(data.userMessageKey, data.error || fallbackText);
    }
    return data.error || result?.error || fallbackText;
}

function showGenerationError(result, fallback = '') {
    const data = result?.data || {};
    const errorMsg = getGenerationErrorMessage(result, fallback);
    const isFeatureBlocked = data.featureBlocked || data.code === 'adult_mode_locked';
    const targetChatId = typeof currentGenerationChatId !== 'undefined'
        ? (currentGenerationChatId || currentChatId)
        : currentChatId;

    if (isFeatureBlocked && typeof replaceImageSkeletonWithError === 'function') {
        replaceImageSkeletonWithError(errorMsg, targetChatId, {
            code: data.code,
            featureBlocked: true,
            userMessageKey: data.userMessageKey || '',
        });
        return;
    }

    removeSkeletonMessage(targetChatId);
    Toast.error(errorMsg);
}

const GENERATION_PROGRESS_FALLBACKS = {
    fine_tuning: 'Fine tuning',
    refine: 'Affinage',
    prepare_generation: 'Préparation de la génération...',
    prepare_region: 'Préparation de la zone...',
    prefill_inpaint: 'Pré-remplissage inpaint...',
    diffusion: 'Diffusion en cours...',
    load_text2img_model: 'Chargement du modèle Text2Img...',
    download_text2img_model: 'Téléchargement du modèle Text2Img...',
    load_openpose: 'Préparation ControlNet OpenPose...',
    download_openpose: 'Téléchargement ControlNet OpenPose...',
    quantize_openpose: 'Quantification OpenPose...',
    prepare_text2img: 'Préparation Text2Img...',
    prepare_prompt: 'Préparation du prompt...',
    prepare_preview_decoder: 'Préparation preview...',
    prepare_pose_control: 'Préparation pose ControlNet...',
    install_pose_tools: 'Installation outils pose...',
    load_pose_detector: 'Chargement détecteur OpenPose...',
    extract_pose_skeleton: 'Extraction squelette OpenPose...',
    pose_skeleton_ready: 'Squelette pose prêt...',
    pose_fallback: 'Fallback prompt de pose...',
    load_loras: 'Préparation LoRA...',
    prepare_assets: 'Préparation assets',
    download_assets: 'Téléchargement assets',
    download_schp: 'Téléchargement SCHP',
    download_segmentation: 'Téléchargement segmentation',
    segment_fusion: 'Fusion segmentation',
    download_depth: 'Préparation Depth Anything...',
    download_controlnet: 'Préparation ControlNet...',
    load_image_model: 'Chargement du modèle image...',
    download_vae: 'Préparation VAE...',
    download_fooocus: 'Préparation patch inpaint...',
    quantize_model: 'Quantification et placement GPU...',
    runtime_error: 'Erreur runtime',
};

const GENERATION_SETUP_PHASES = new Set([
    'prepare_generation',
    'prepare_region',
    'prefill_inpaint',
    'load_text2img_model',
    'download_text2img_model',
    'load_openpose',
    'download_openpose',
    'quantize_openpose',
    'prepare_text2img',
    'prepare_prompt',
    'prepare_preview_decoder',
    'prepare_pose_control',
    'install_pose_tools',
    'load_pose_detector',
    'extract_pose_skeleton',
    'pose_skeleton_ready',
    'pose_fallback',
    'load_loras',
    'prepare_assets',
    'download_assets',
    'download_schp',
    'download_segmentation',
    'segment_fusion',
    'download_depth',
    'download_controlnet',
    'load_image_model',
    'download_vae',
    'download_fooocus',
    'quantize_model',
    'runtime_error',
]);

function getGenerationProgressLabel(phase, message = '') {
    if (!phase) return message || '';
    const fallback = GENERATION_PROGRESS_FALLBACKS[phase] || message || '';
    const translated = generationT(`generation.progress.${phase}`, fallback);
    return translated || fallback || message || '';
}

function formatGenerationProgressText(phase, step, total, message = '') {
    const label = getGenerationProgressLabel(phase, message);
    const safeStep = Number(step) || 0;
    const safeTotal = Number(total) || 0;

    if (label && GENERATION_SETUP_PHASES.has(phase)) {
        return message || label;
    }
    if (message && !GENERATION_PROGRESS_FALLBACKS[phase]) {
        return message;
    }
    if (label && safeTotal > 0) {
        return `${label} ${safeStep}/${safeTotal}`;
    }
    if (label) {
        return label;
    }
    if (safeStep > 0 && safeTotal > 0) {
        return `${safeStep}/${safeTotal}`;
    }
    return '';
}

function refreshGenerationProgressTexts() {
    document.querySelectorAll('.skeleton-preview-container[data-progress-phase]').forEach(container => {
        const stepText = container.querySelector('.generation-step-text');
        if (!stepText) return;
        stepText.textContent = formatGenerationProgressText(
            container.dataset.progressPhase || '',
            container.dataset.progressStep || 0,
            container.dataset.progressTotal || 0,
            container.dataset.progressMessage || ''
        );
    });
}

window.addEventListener('joyboy:locale-changed', refreshGenerationProgressTexts);

function getInitialGenerationProgressText() {
    return formatGenerationProgressText('prepare_generation', 0, 0, '');
}

// Queue execution flags
let executingFromQueue = false;
let executingFromQueueChat = false;

const CREATIVE_GENERATION_TERMS = [
    'logo', 'image', 'photo', 'illustration', 'dessin', 'visuel',
    'poster', 'affiche', 'banner', 'bannière', 'icone', 'icône',
    'avatar', 'wallpaper', 'fond d\'écran', 'design', 'maquette',
    'video', 'vidéo', 'picture', 'pic', 'visual', 'drawing',
    'sketch', 'painting', 'flyer', 'ad', 'advertisement', 'icon',
    'mockup', 'brand', 'portrait', 'scène', 'scene', 'concept art',
    'imagen', 'foto', 'ilustración', 'ilustracion', 'dibujo',
    'cartel', 'anuncio', 'icono', 'marca',
    'immagine', 'illustrazione', 'disegno', 'manifesto', 'icona',
    'marchio'
];

const VISUAL_SUBJECT_TERMS = [
    'voiture', 'auto', 'véhicule', 'vehicule', 'car', 'vehicle',
    'coche', 'automóvil', 'automovil', 'vehículo', 'vehiculo',
    'macchina', 'automobile', 'veicolo',
    'train', 'locomotive', 'rail', 'rails', 'chemin de fer',
    'montagnes russes', 'roller coaster', 'chat', 'cat', 'chien',
    'dog', 'animal', 'créature', 'creature', 'dragon', 'robot',
    'personnage', 'character', 'paysage', 'landscape', 'montagne',
    'mountain', 'ciel', 'sky', 'maison', 'house', 'ville', 'city'
];

const GENERATION_ACTION_TERMS = [
    'crée', 'créer', 'cree', 'creer', 'génère', 'genere', 'générer',
    'generer', 'fais', 'faire', 'imagine', 'imaginer', 'dessine',
    'dessiner', 'make', 'create', 'generate', 'draw',
    'crear', 'crea', 'generar', 'genera', 'hacer', 'haz', 'imagina',
    'imaginar', 'dibujar', 'dibuja',
    'creare', 'generare', 'fare', 'fai', 'immagina', 'immaginare',
    'disegnare', 'disegna'
];

const DEV_CONTEXT_TERMS = [
    'repo', 'repository', 'codebase', 'fichier', 'file', 'dossier',
    'folder', 'git', 'commit', 'npm', 'pip', 'bug', 'stacktrace',
    'terminal', 'powershell', 'repositorio', 'archivo', 'carpeta',
    'directorio', 'codice', 'cartella', 'directory'
];

const IMAGE_ANALYSIS_TERMS = [
    'analyse', 'analyser', 'analysez', 'analyze', 'describe', 'décris',
    'decris', 'décrire', 'decrire', 'detect', 'détecte', 'detecte',
    'détecter', 'detecter', 'reconnais', 'reconnaître', 'reconnaitre',
    'identify', 'identifie', 'identifier', 'caption', 'légende', 'legende',
    'c\'est quoi', 'c est quoi', 'what is this', 'what\'s this',
    'quoi dans', 'contient', 'contains', 'comida', 'bebida', 'analiza',
    'descrivi', 'analizza'
];

function escapePromptTerm(term) {
    return String(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function promptIncludesAnyTerm(text, terms) {
    const haystack = String(text || '').toLowerCase();
    return terms.some(term => {
        const normalized = String(term || '').trim().toLowerCase();
        if (!normalized) return false;
        const pattern = new RegExp(`(^|[^\\p{L}\\p{N}_-])${escapePromptTerm(normalized)}(?=$|[^\\p{L}\\p{N}_-])`, 'iu');
        return pattern.test(haystack);
    });
}

function promptLooksCreativeImageRequest(prompt) {
    const text = (prompt || '').toLowerCase();
    if (!text.trim()) return false;

    const hasCreativeTarget = promptIncludesAnyTerm(text, CREATIVE_GENERATION_TERMS)
        || promptIncludesAnyTerm(text, VISUAL_SUBJECT_TERMS);
    return hasCreativeTarget
        && promptIncludesAnyTerm(text, GENERATION_ACTION_TERMS)
        && !promptIncludesAnyTerm(text, DEV_CONTEXT_TERMS);
}

function isDirectTextToImagePrompt(prompt) {
    return promptLooksCreativeImageRequest(prompt);
}

function isImageAnalysisPrompt(prompt) {
    const text = (prompt || '').toLowerCase();
    if (!text.trim()) return false;
    return promptIncludesAnyTerm(text, IMAGE_ANALYSIS_TERMS);
}

function getExportGuidanceTypeForGeneration() {
    if (userSettings.exportGuidanceType === 'camera' || userSettings.exportGuidanceType === 'human') {
        return userSettings.exportGuidanceType;
    }

    const view = userSettings.exportView || 'auto';
    const pose = userSettings.exportPose || 'none';
    if (view !== 'auto' && pose === 'none') {
        return 'camera';
    }
    return 'human';
}

function getActiveExportView() {
    return getExportGuidanceTypeForGeneration() === 'camera' ? (userSettings.exportView || 'auto') : 'auto';
}

function getActiveExportPose() {
    return getExportGuidanceTypeForGeneration() === 'human' ? (userSettings.exportPose || 'none') : 'none';
}

// ===== SHARED CHAT STREAMING =====

/**
 * Build common chat stream request params
 */
function buildChatStreamParams(prompt) {
    const includeImageContext = !!currentImage && isImageAnalysisPrompt(prompt);
    return {
        message: prompt,
        history: getChatContext(),
        memories: [],
        image: includeImageContext ? currentImage : null,
        chatModel: userSettings.chatModel,
        reasoningEffort: typeof getTerminalReasoningEffort === 'function'
            ? getTerminalReasoningEffort(userSettings.chatModel)
            : null,
        profile: getProfileForAI(),
        allConversations: [],
        workspace: getActiveWorkspace(),
        allWorkspaces: userSettings.workspaces || [],
        contextSize: userSettings.contextSize || 4096,
        locale: window.JoyBoyI18n?.getLocale?.() || document.documentElement.lang || 'fr'
    };
}

/**
 * Clean internal markers from AI response text
 */
function cleanResponseMarkers(text) {
    return text
        .replace(/\[GENERATE_IMAGE:[^\]]+\]/gi, '')
        .replace(/\[LIST_FILES:[^\]]*\]/gi, '')
        .replace(/\[READ_FILE:[^\]]+\]/gi, '')
        .replace(/\[SEARCH:[^\]]+\]/gi, '')
        .replace(/\[GLOB:[^\]]+\]/gi, '')
        .replace(/\[WRITE_FILE:[^\]]+\][\s\S]*?\[\/WRITE_FILE\]/gi, '')
        .replace(/\[EDIT_FILE:[^\]]+\][\s\S]*?\[\/EDIT_FILE\]/gi, '')
        .replace(/\[DELETE_FILE:[^\]]+\]/gi, '')
        .trim();
}

/**
 * Handle SSE chat streaming (shared between generate() and continueChat())
 * @param {string} prompt - User prompt
 * @param {number} startTime - Timestamp when request started
 * @returns {Promise<void>}
 */
async function handleChatStream(prompt, startTime, targetChatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    if (!currentController) return;

    const streamResponse = await apiChat.stream(buildChatStreamParams(prompt), currentController?.signal);

    const msgId = createStreamingMessage(prompt);
    const reader = streamResponse.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.status === 'searching') {
                        showSearchingStatus(msgId, data.query, data.current, data.total);
                    } else if (data.status === 'search_done') {
                        hideSearchingStatus(msgId);
                    } else if (data.content) {
                        fullResponse += data.content;
                        appendToStreamingMessage(msgId, data.content);
                    } else if (data.done) {
                        const responseTime = Date.now() - startTime;

                        if (data.generate_image && data.image_prompt) {
                            console.log('[CHAT] IA demande une image:', data.image_prompt);
                            if (!targetChatId || targetChatId === currentChatId) {
                                addImageSkeletonToChat(targetChatId);
                            }
                        }

                        if (data.switch_workspace) {
                            switchToWorkspace(data.switch_workspace.name);
                        }

                        if (data.workspace_action) {
                            const wsResult = formatWorkspaceResult(data.workspace_action);
                            appendToStreamingMessage(msgId, wsResult);
                            fullResponse += wsResult;
                        }

                        finalizeStreamingMessage(msgId, responseTime, data.token_stats);
                        const finalHtml = getChatHtmlWithoutSkeleton();
                        saveCurrentChatHtml('', finalHtml, targetChatId);

                        if (fullResponse) {
                            chatHistory.push({ role: 'assistant', content: cleanResponseMarkers(fullResponse) });
                        }
                        if (data.new_memories && data.new_memories.length > 0) {
                            await saveMemories(data.new_memories);
                        }

                        if (data.generate_image && data.image_prompt) {
                            await generateImageFromChat(data.image_prompt, targetChatId);
                        }
                    } else if (data.error) {
                        appendToStreamingMessage(msgId, `\n\n${generationT('terminal.tool.error', 'Erreur')}: ${data.error}`);
                        finalizeStreamingMessage(msgId, Date.now() - startTime, null);
                        const finalHtml = getChatHtmlWithoutSkeleton();
                        saveCurrentChatHtml('', finalHtml, targetChatId);
                    }
                } catch (e) {}
            }
        }
    }
}

// ===== WORKSPACE RESULT FORMATTING =====
// Utilisé par terminal.js ET le chat normal pour afficher les résultats d'actions fichiers
function formatWorkspaceResult(action) {
    if (!action || !action.result) return '';

    const result = action.result;
    const tt = (key, fallback, params = {}) => generationT(`terminal.tool.${key}`, fallback, params);
    let output = '\n\n---\n';

    if (!result.success) {
        output += `**${tt('error', 'Erreur')}:** ${result.error || tt('unknownError', 'Erreur inconnue')}\n`;
        return output;
    }

    switch (action.action) {
        case 'list_files':
            output += `**${tt('filesIn', 'Fichiers dans')} \`${result.path || '.'}\`:**\n\`\`\`\n`;
            if (result.items && result.items.length > 0) {
                for (const item of result.items.slice(0, 30)) {
                    if (item.type === 'dir') {
                        output += `[DIR] ${item.name}/ (${item.items_count} ${tt('items', 'éléments')})\n`;
                    } else if (item.type === 'file') {
                        output += `[FILE] ${item.name} (${item.size_display || ''})\n`;
                    } else if (item.type === 'truncated') {
                        output += `... (${tt('listTruncated', 'liste tronquée')})\n`;
                    }
                }
            } else {
                output += `(${tt('emptyFolder', 'dossier vide')})\n`;
            }
            output += '```\n';
            break;

        case 'read_file':
            output += `**${tt('contentOf', 'Contenu de')} \`${result.path}\`** (${result.lines} ${tt('lines', 'lignes')}${result.truncated ? `, ${tt('truncated', 'tronqué')}` : ''}):\n`;
            output += '```\n';
            output += result.content.slice(0, 3000);
            if (result.content.length > 3000) output += `\n... (${tt('contentTruncated', 'contenu tronqué')})`;
            output += '\n```\n';
            break;

        case 'search':
            output += `**${tt('resultsFor', 'Résultats pour')} \`${result.pattern}\`** (${result.results?.length || 0} ${tt('found', 'trouvés')}):\n`;
            if (result.results && result.results.length > 0) {
                output += '```\n';
                for (const r of result.results.slice(0, 20)) {
                    output += `${r.file}:${r.line}: ${r.content.slice(0, 100)}\n`;
                }
                if (result.results.length > 20) output += `... (${tt('contentTruncated', 'contenu tronqué')})\n`;
                output += '```\n';
            } else {
                output += `_${tt('noResult', 'Aucun résultat')}_\n`;
            }
            break;

        case 'glob':
            output += `**${tt('matchingFiles', 'Fichiers correspondant à')} \`${result.pattern}\`** (${result.files?.length || 0}):\n`;
            if (result.files && result.files.length > 0) {
                output += '```\n';
                for (const f of result.files.slice(0, 30)) {
                    output += `${f}\n`;
                }
                if (result.files.length > 30) output += `... (${tt('listTruncated', 'liste tronquée')})\n`;
                output += '```\n';
            } else {
                output += `_${tt('noFileFound', 'Aucun fichier trouvé')}_\n`;
            }
            break;

        case 'write_file':
            output += `**${tt('fileLabel', 'Fichier')} ${result.created ? tt('fileCreated', 'créé') : tt('fileModified', 'modifié')}:** \`${result.path}\`\n`;
            output += `_${tt('bytesWritten', '{bytes} octets écrits', { bytes: result.bytes_written })}_\n`;
            break;

        case 'edit_file':
            output += `**${tt('fileLabel', 'Fichier')} ${tt('fileModified', 'modifié')}:** \`${result.path}\`\n`;
            output += `_${tt('replacementsDone', '{count} remplacement(s) effectué(s)', { count: result.replacements })}_\n`;
            if (result.diff_preview) {
                output += '```diff\n' + result.diff_preview + '\n```\n';
            }
            break;

        case 'delete_file':
            output += `**${tt('fileDeleted', 'Fichier supprimé')}:** \`${result.path}\`\n`;
            break;

        case 'bash':
            const returnCode = result.return_code ?? -1;
            const bashStatus = returnCode === 0 ? 'OK' : tt('errorStatus', 'ERREUR');
            output += `**${tt('commandExecuted', 'Commande exécutée')}** [${bashStatus}] (code: ${returnCode})\n`;
            if (result.output) {
                output += '```bash\n';
                output += result.output.slice(0, 2000);
                if (result.output.length > 2000) output += `\n... (${tt('outputTruncated', 'sortie tronquée')})`;
                output += '\n```\n';
            }
            break;

        case 'create_plan':
            output += `**${tt('planCreated', 'Plan créé')}:** ${result.tasks_count} ${tt('tasks', 'tâches')}\n\n`;
            if (result.markdown) {
                output += result.markdown + '\n';
            } else if (result.tasks) {
                for (const task of result.tasks) {
                    output += `- [ ] **${task.id}.** ${task.title}\n`;
                }
            }
            break;

        case 'explore':
            output += `**${tt('exploration', 'Exploration')}:** ${result.summary}\n\n`;
            if (result.project_type && result.project_type !== 'unknown') {
                output += `**${tt('type', 'Type')}:** ${result.project_type.toUpperCase()}\n`;
            }
            if (result.technologies?.length > 0) {
                output += `**${tt('technologies', 'Technologies')}:** ${result.technologies.join(', ')}\n`;
            }
            if (result.key_files && Object.keys(result.key_files).length > 0) {
                output += `\n**${tt('analyzedFiles', 'Fichiers analysés')}:**\n`;
                for (const [path, info] of Object.entries(result.key_files)) {
                    output += `- \`${path}\` (${info.lines} ${tt('lines', 'lignes')})\n`;
                }
            }
            break;

        default:
            output += `_${tt('unknownAction', 'Action inconnue : {action}', { action: action.action })}_\n`;
    }

    return output;
}

// ===== TERMINAL MODE =====
// IMPORTANT: Toute la logique du mode terminal est maintenant dans terminal.js
// Ce fichier ne contient plus que la génération d'images et le chat normal

// ===== MODEL MANAGEMENT =====
// Compatibility shims kept on the frontend because older flows still call them.
// The actual model lifecycle now lives entirely in the backend ModelManager.
async function unloadTextModel() { return Promise.resolve(); }
async function preloadTextModel() { return Promise.resolve(); }
async function preloadImageModel() { return Promise.resolve(); }
async function unloadImageModel() { return Promise.resolve(); }
function resetImageModelLoaded() { /* backend-owned state */ }

async function onImageAdded() {
    if (terminalMode) await onImageAddedTerminal();
}

async function onImageRemoved() {
    if (terminalMode) await onImageRemovedTerminal();
}

// ===== SEND HANDLERS =====

function handleSendClick() {
    if (isGenerating) {
        stopAllGenerations();
    } else {
        generate();
    }
}

function handleChatSendClick() {
    if (isGenerating) {
        stopAllGenerations();
    } else {
        continueChat();
    }
}

async function stopAllGenerations() {
    console.log(`[STOP] Arrêt de la génération (mode: ${currentGenerationMode || 'unknown'})...`);

    // Mode terminal - utiliser le controller de terminal.js
    if (typeof terminalMode !== 'undefined' && terminalMode && typeof stopTerminalChat === 'function') {
        console.log('[STOP] Arrêt mode terminal...');
        stopTerminalChat();
        return;
    }

    // Abort current request and cancel server-side
    if (currentController) {
        currentController.abort();
        currentController = null;
    }

    // Cancel ALL: chat stream + image/video generations
    await apiSystem.cancelAll().catch(() => {});

    await apiModels.unloadAll();

    // Reset les flags locaux
    isGenerating = false;
    pendingImage = null;
    currentGenerationId = null;
    currentGenerationChatId = null;
    currentGenerationMode = null;
    if (typeof stopVideoProgressPolling === 'function') {
        stopVideoProgressPolling();
    }

    // Gérer les skeletons image (contiennent le message user à l'intérieur)
    const imageSkeleton = document.querySelector('.image-skeleton-message');
    if (imageSkeleton) {
        // Extraire le prompt du user-bubble AVANT de modifier le DOM
        const userBubble = imageSkeleton.querySelector('.user-bubble');
        const prompt = userBubble ? userBubble.textContent.replace(/'/g, "\\'") : '';
        const msgId = 'cancelled-' + Date.now();

        // Retirer les classes skeleton, transformer en message normal
        imageSkeleton.classList.remove('image-skeleton-message');
        imageSkeleton.removeAttribute('data-chat-id');
        imageSkeleton.removeAttribute('data-started-at');

        // Remplacer le contenu ai-response (skeleton) par "Pas de réponse." + action bar
        const aiResponse = imageSkeleton.querySelector('.ai-response');
        if (aiResponse) {
            aiResponse.classList.remove('loading');
            aiResponse.innerHTML = `
                <div class="chat-bubble cancelled" id="${msgId}">${generationT('chat.noResponse', 'Pas de réponse.')}</div>
                <div class="chat-actions">
                    <button class="chat-action-btn" onclick="regenerateChat('${prompt}')" title="${generationT('common.regenerate', 'Regénérer')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M1 4v6h6M23 20v-6h-6"/>
                            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                        </svg>
                    </button>
                    <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${generationT('common.copy', 'Copier')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                    </button>
                    <div class="chat-actions-divider"></div>
                    <div class="response-time"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${generationT('chat.interrupted', 'Interrompu')}</span></div>
                </div>
            `;
        }
    }

    // Gérer les bulles streaming en cours (stream déjà actif)
    if (currentStreamingMsgId) {
        const bubble = document.getElementById(currentStreamingMsgId);
        if (bubble) {
            bubble.classList.remove('streaming');
            const rawText = (streamingRawText || '').replace('|', '').trim();
            if (rawText) {
                bubble.innerHTML = formatMarkdown(rawText);
            } else {
                bubble.classList.add('cancelled');
                bubble.textContent = generationT('chat.noResponse', 'Pas de réponse.');
            }
            streamingRawText = '';
        }
        const container = document.getElementById(currentStreamingMsgId + '-container');
        if (container) {
            const aiResponse = container.querySelector('.ai-response');
            const msgId = currentStreamingMsgId;
            const userBubble = container.querySelector('.user-bubble');
            const safePrompt = userBubble ? userBubble.textContent.replace(/'/g, "\\'") : '';
            if (aiResponse && !aiResponse.querySelector('.chat-actions')) {
                aiResponse.insertAdjacentHTML('beforeend', `
                    <div class="chat-actions">
                        <button class="chat-action-btn" onclick="regenerateChat('${safePrompt}')" title="${generationT('common.regenerate', 'Regénérer')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M1 4v6h6M23 20v-6h-6"/>
                                <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                            </svg>
                        </button>
                        <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${generationT('common.copy', 'Copier')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                            </svg>
                        </button>
                        <div class="chat-actions-divider"></div>
                        <div class="response-time"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${generationT('chat.interrupted', 'Interrompu')}</span></div>
                    </div>
                `);
            }
        }
        currentStreamingMsgId = null;
        updateChatPadding();
    }

    // Gérer les skeletons texte (message user dans .user-pending-msg séparé)
    const textSkeleton = document.querySelector('.skeleton-message');
    if (textSkeleton) textSkeleton.remove();

    const pendingMsg = document.querySelector('.user-pending-msg');
    if (pendingMsg) {
        pendingMsg.classList.remove('user-pending-msg');
        const msgId = 'cancelled-' + Date.now();
        const userBubble = pendingMsg.querySelector('.user-bubble');
        const prompt = userBubble ? userBubble.textContent.replace(/'/g, "\\'") : '';
        pendingMsg.insertAdjacentHTML('beforeend', `
            <div class="ai-response">
                <div class="chat-bubble cancelled" id="${msgId}">${generationT('chat.noResponse', 'Pas de réponse.')}</div>
                <div class="chat-actions">
                    <button class="chat-action-btn" onclick="regenerateChat('${prompt}')" title="${generationT('common.regenerate', 'Regénérer')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M1 4v6h6M23 20v-6h-6"/>
                            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                        </svg>
                    </button>
                    <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${generationT('common.copy', 'Copier')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                    </button>
                    <div class="chat-actions-divider"></div>
                    <div class="response-time"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${generationT('chat.interrupted', 'Interrompu')}</span></div>
                </div>
            </div>
        `);
    }

    setSendButtonsMode(false);

    document.getElementById('loading').classList.add('hidden');
    document.getElementById('send-btn').disabled = false;

    console.log('[STOP] Génération arrêtée');
}

// Annuler les générations côté serveur (gardé pour compatibilité)
async function cancelCurrentGenerations() {
    if (currentGenerationId) {
        const chatId = currentGenerationChatId || currentChatId || null;
        await apiGeneration.cancel(currentGenerationId, chatId).catch(() => {});
        console.log('[CANCEL] Generations cancelled');
    } else {
        console.log('[CANCEL] No active generation id, skip server cancel');
    }
    currentGenerationId = null;
}

// Générer un ID unique — délégué à Str.uuid() (utils.js)
function generateUUID() {
    return Str.uuid();
}

// Récupérer toutes les conversations pour le contexte global (mémoire IA)
function getAllConversationsForContext() {
    const records = Array.isArray(chatRecordsCache) ? chatRecordsCache : [];
    if (!records.length) {
        return [{
            title: 'Current',
            messages: (chatHistory || []).slice(-5)
        }];
    }

    // Keep this deliberately compact: local LLMs get slow fast when we dump
    // full conversation archives into every request.
    return records.slice(0, 8).map(record => ({
        title: record.title || 'Conversation',
        messages: Array.isArray(record.messages) ? record.messages.slice(-5) : [],
        updatedAt: record.updatedAt || null,
    }));
}

// Anti double-submit flag pour generate()
let _genSubmitLock = false;

async function generate() {
    // Anti double-submit: verrou immédiat
    if (_genSubmitLock) {
        console.log('[GEN] Double-submit bloqué');
        return;
    }
    _genSubmitLock = true;
    setTimeout(() => { _genSubmitLock = false; }, 500); // Reset après 500ms

    const prompt = document.getElementById('prompt-input').value.trim();
    const model = getCurrentImageModel();  // Utilise le modèle du picker
    const directTextToImage = !currentImage && isDirectTextToImagePrompt(prompt);
    const imageAnalysisRequest = !!currentImage && isImageAnalysisPrompt(prompt);

    if (!prompt) {
        Toast.error(generationT('generation.promptRequired', 'Écris ce que tu veux'));
        _genSubmitLock = false;
        return;
    }

    // Mode privé : vider le chat précédent avant chaque nouvelle demande
    if (Settings.get('privacyMode')) {
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) messagesDiv.innerHTML = '';
        chatHistory = [];
    }

    // === MODE TERMINAL ===
    if (terminalMode) {
        resetComposerTextarea('prompt-input');
        refocusChatInput();
        await sendTerminalMessage(prompt);
        _genSubmitLock = false;
        return;
    }

    // Vérifier si le message active le mode terminal
    if (typeof checkTerminalTrigger === 'function') {
        const isTerminalTrigger = await checkTerminalTrigger(prompt);
        if (isTerminalTrigger) {
            resetComposerTextarea('prompt-input');
            _genSubmitLock = false;
            return;
        }
    } else {
        console.error('[GENERATION] checkTerminalTrigger non disponible - terminal.js non chargé?');
    }

    // === QUEUE: Si déjà en génération, ajouter à la queue ===
    if (isGenerating) {
        console.log('%c[GEN] → Ajout à la queue!', 'color: #22c55e; font-weight: bold');
        const mode = ((currentImage && !imageAnalysisRequest) || directTextToImage) ? 'image' : 'text';
        const options = currentImage ? { image: currentImage } : {};
        await addToQueue(prompt, mode, options);
        resetComposerTextarea('prompt-input');
        console.log(`[GEN] Prompt ajouté à la queue: ${prompt.substring(0, 30)}...`);
        return;
    }

    const hasImage = !!currentImage;
    const isImageGeneration = (hasImage && !imageAnalysisRequest) || directTextToImage;
    pendingImage = isImageGeneration && hasImage ? currentImage : null;

    if (!isImageGeneration) {
        // Vérifier si un modèle Ollama est disponible uniquement pour le chat.
        // Text2Img/Inpaint ne doivent pas rester bloqués sur le home à cause d'un
        // modèle texte alors que le pipeline image peut déjà démarrer.
        const modelCheck = await checkOllamaModelAvailable();
        if (!modelCheck.available) {
            showNoModelError(modelCheck.message);
            _genSubmitLock = false;
            return;
        }
    }

    await ensureActiveChatForRequest({ title: prompt });
    currentGenerationChatId = currentChatId;

    // Gestion du modèle texte selon le mode
    if (isImageGeneration) {
        // Mode image/text2img -> décharger le modèle texte pour libérer la VRAM
        await unloadTextModel();
    } else {
        // Mode texte -> s'assurer que le modèle texte est chargé
        await preloadTextModel();
    }

    document.getElementById('loading').classList.remove('hidden');
    isGenerating = true;
    currentGenerationMode = isImageGeneration ? (hasImage ? 'image' : 'text2img') : 'chat';  // Tracker le mode pour stop
    currentGenerationChatId = currentChatId;  // Tracker le chat pour persistance
    currentGenerationId = generateUUID();
    setSendButtonsMode(true);

    // Si pas d'image -> mode conversation avec streaming
    if (!isImageGeneration) {
        // Créer le controller APRÈS l'ouverture du chat.
        currentController = new AbortController();

        updateChatTitleNow(prompt);
        showChat();
        addToPromptHistory(prompt);
        resetComposerTextarea('prompt-input');

        // Afficher immédiatement le message + skeleton
        addChatSkeletonMessage(prompt, imageAnalysisRequest ? currentImage : null);
        refocusChatInput();

        // Tant que la requête tourne, on garde le skeleton dans la conversation.
        // Sinon un changement de conversation ferait disparaître le job en cours.
        const messagesDiv = document.getElementById('chat-messages');
        const htmlToSave = messagesDiv ? messagesDiv.innerHTML : getChatHtmlWithoutSkeleton();
        saveCurrentChatHtml(prompt, htmlToSave, currentGenerationChatId);

        const startTime = Date.now();

        try {
            await handleChatStream(prompt, startTime, currentGenerationChatId);
        } catch (err) {
            if (err.name === 'AbortError') {
                // Stream interrompu — finaliser la bulle streaming si elle existe
                if (currentStreamingMsgId) {
                    const bubble = document.getElementById(currentStreamingMsgId);
                    if (bubble) {
                        bubble.classList.remove('streaming');
                        const rawText = (streamingRawText || '').replace('|', '').trim();
                        if (rawText) {
                            bubble.innerHTML = formatMarkdown(rawText);
                        } else {
                            bubble.classList.add('cancelled');
                    bubble.textContent = generationT('chat.noResponse', 'Pas de réponse.');
                        }
                        streamingRawText = '';
                    }
                    const container = document.getElementById(currentStreamingMsgId + '-container');
                    if (container) {
                        const aiResponse = container.querySelector('.ai-response');
                        const msgId = currentStreamingMsgId;
                        const safePrompt = prompt.replace(/'/g, "\\'");
                        const responseTime = Date.now() - startTime;
                        const timeDisplay = formatTimeDisplay(responseTime, 3000, 8000);
                        if (aiResponse && !aiResponse.querySelector('.chat-actions')) {
                            aiResponse.insertAdjacentHTML('beforeend', `
                                <div class="chat-actions">
                                    <button class="chat-action-btn" onclick="regenerateChat('${safePrompt}')" title="${generationT('common.regenerate', 'Regénérer')}">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M1 4v6h6M23 20v-6h-6"/>
                                            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                                        </svg>
                                    </button>
                                    <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${generationT('common.copy', 'Copier')}">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                                        </svg>
                                    </button>
                                    <div class="chat-actions-divider"></div>
                                    <div class="response-time">${timeDisplay} <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${generationT('chat.interrupted', 'Interrompu')}</span></div>
                                </div>
                            `);
                        }
                    }
                    currentStreamingMsgId = null;
                    updateChatPadding();
                }
            } else {
                removeSkeletonMessage(currentGenerationChatId);
                console.error('Chat error:', err);
            }
        }

        document.getElementById('loading').classList.add('hidden');
        isGenerating = false;
        currentController = null;
        currentGenerationId = null;
        currentGenerationChatId = null;
        setSendButtonsMode(false);
        refocusChatInput();
        return;
    }

    currentController = new AbortController();
    const abortSignal = currentController.signal;
    updateChatTitleNow(prompt);  // Mettre à jour le titre
    addSkeletonMessage(prompt, pendingImage, hasImage, null, currentGenerationChatId);
    // Inpaint démarre déjà le polling depuis addSkeletonMessage(hasImage=true).
    // Text2Img n'a pas d'image source, donc on le démarre explicitement ici
    // pour que la carte "Généré" reçoive bien les previews backend.
    startPreviewPolling();
    showChat();
    addToPromptHistory(prompt);
    resetComposerTextarea('prompt-input');
    refocusChatInput();

    // Backend loads the model on-demand, no need to wait for preloading
    const imageRequestStartTime = Date.now();

    try {
        const enhanceVal = userSettings.enhancePrompt;
        const enhanceModeVal = userSettings.enhanceMode || 'light';
        const adultPayload = window.getAdultGenerationPayload ? window.getAdultGenerationPayload() : {};
        const faceRefs = typeof getFaceRefPayload === 'function'
            ? getFaceRefPayload()
            : (faceRefImage ? [faceRefImage] : []);
        console.log(`[GEN] enhance=${enhanceVal}, enhance_mode=${enhanceModeVal}`);
        const result = await apiGeneration.generate({
            image: pendingImage,
            prompt: prompt,
            model: model,
            chat_model: userSettings.chatModel || null,
            enhance: enhanceVal,
            enhance_mode: enhanceModeVal,
            steps: pendingImage ? userSettings.steps : (userSettings.text2imgSteps || 30),
            ...adultPayload,
            controlnet_depth: userSettings.controlnetDepth ?? null,
            composite_radius: userSettings.compositeRadius ?? null,
            skip_auto_refine: userSettings.skipAutoRefine === true,
            face_ref: faceRefs[0] || null,
            face_refs: faceRefs,
            text2img_guidance: userSettings.text2imgGuidance ?? 7.5,
            face_ref_scale: userSettings.faceRefScale ?? 0.35,
            style_ref: styleRefImage || null,
            style_ref_scale: userSettings.styleRefScale ?? 0.55,
            export_format: userSettings.exportFormat || 'auto',
            export_width: userSettings.exportWidth || 768,
            export_height: userSettings.exportHeight || 1344,
            export_view: getActiveExportView(),
            export_pose: getActiveExportPose(),
            pose_strength: userSettings.poseStrength ?? 0.5,
            export_presets: JSON.stringify(userSettings.exportPresets || {}),
            chatId: currentGenerationChatId,
            generationId: currentGenerationId,
        }, abortSignal);

        // Arrêter le polling de preview
        stopPreviewPolling();

        if (result.aborted || result.data?.cancelled || abortSignal.aborted) {
            // Génération annulée — stopAllGenerations a déjà géré le skeleton
            console.log('[GEN] Génération annulée');
        } else if (result.ok && result.data?.success) {
            const data = result.data;
            const totalGenerationTime = (Date.now() - imageRequestStartTime) / 1000;
            modifiedImage = 'data:image/png;base64,' + data.modified;

            // IMPORTANT: Si l'user a changé de chat pendant la génération, revenir au bon chat
            if (currentChatId !== currentGenerationChatId && currentGenerationChatId) {
                console.log(`%c[GEN] Chat a changé pendant génération! ${currentChatId?.substring(0,8)} -> ${currentGenerationChatId?.substring(0,8)}`, 'color: #f59e0b; font-weight: bold');
                await loadChat(currentGenerationChatId);
            }

            if (data.mode === 'txt2img') {
                originalImage = null;
                addMessageTxt2Img(prompt, modifiedImage, data.generationTime, data.seed || null, currentGenerationChatId, totalGenerationTime);
            } else {
                originalImage = 'data:image/png;base64,' + data.original;
                addMessage(prompt, pendingImage, originalImage, modifiedImage, data.generationTime, currentGenerationChatId, totalGenerationTime);
            }

            // Garder l'image dans l'input pour enchaîner les édits
            // L'user peut clear manuellement avec le bouton ✕ pour passer en text2img
            showChat();
        } else if (!result.aborted && !abortSignal.aborted) {
            showGenerationError(result);
        }
    } catch (err) {
        stopPreviewPolling();
        if (err.name === 'AbortError' || abortSignal.aborted) {
            console.log('Generation annulee');
        } else {
            removeSkeletonMessage(currentGenerationChatId);
            Toast.error(err.message);
        }
    }

    document.getElementById('loading').classList.add('hidden');
    isGenerating = false;
    pendingImage = null;
    currentController = null;
    currentGenerationId = null;
    currentGenerationChatId = null;
    setSendButtonsMode(false);
    refocusChatInput();

    // Traiter le prochain élément de la queue
    if (!executingFromQueue) {
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') {
                processNextInQueue();
            }
        }, 100);
    }
}

async function continueChat() {
    const prompt = document.getElementById('chat-prompt').value.trim();
    if (!prompt) {
        return;
    }
    const directTextToImage = !currentImage && isDirectTextToImagePrompt(prompt);
    const imageAnalysisRequest = !!currentImage && isImageAnalysisPrompt(prompt);

    // Mode privé : vider le chat précédent avant chaque nouvelle demande
    if (Settings.get('privacyMode')) {
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) messagesDiv.innerHTML = '';
        chatHistory = [];
    }

    // === QUEUE: Si déjà en génération, ajouter à la queue ===
    if (isGenerating) {
        console.log('%c[CHAT] → Ajout à la queue!', 'color: #22c55e; font-weight: bold');
        const mode = terminalMode ? 'terminal' : (((currentImage && !imageAnalysisRequest) || directTextToImage) ? 'image' : 'text');
        const options = currentImage ? { image: currentImage } : {};
        await addToQueue(prompt, mode, options);
        resetComposerTextarea('chat-prompt');
        console.log('[QUEUE] Prompt ajouté à la queue:', prompt.substring(0, 30) + '...');
        return;
    }

    // === MODE TERMINAL ===
    if (terminalMode) {
        resetComposerTextarea('chat-prompt');
        await sendTerminalMessage(prompt);
        return;
    }

    // Vérifier si le message active le mode terminal
    if (typeof checkTerminalTrigger === 'function') {
        const isTerminalTrigger = await checkTerminalTrigger(prompt);
        if (isTerminalTrigger) {
            resetComposerTextarea('chat-prompt');
            return;
        }
    } else {
        console.error('[GENERATION] checkTerminalTrigger non disponible - terminal.js non chargé?');
    }

    // Demande Text2Img explicite depuis une conversation: ne pas demander au
    // LLM de rédiger un prompt, lancer directement le pipeline image.
    if (directTextToImage) {
        const chatInput = document.getElementById('chat-prompt');
        if (chatInput) {
            resetComposerTextarea(chatInput);
        }
        const homeInput = document.getElementById('prompt-input');
        if (homeInput) homeInput.value = prompt;
        await generate();
        return;
    }

    // Vérifier si une image est présente -> mode inpainting
    const hasImage = !!currentImage;

    if (hasImage && !imageAnalysisRequest) {
        // Mode image dans le chat -> utiliser le flux d'image
        console.log('[CHAT] Image détectée, passage en mode inpainting');
        await unloadTextModel();

        // Réutiliser la logique de génération d'image
        pendingImage = currentImage;
        isGenerating = true;
        currentGenerationMode = 'image';  // Tracker le mode pour stop
        currentGenerationChatId = currentChatId;  // Tracker le chat pour sauvegarder au bon endroit
        currentGenerationId = generateUUID();
        setSendButtonsMode(true);
        currentController = new AbortController();
        const chatAbortSignal = currentController.signal;

        addToPromptHistory(prompt);
        resetComposerTextarea('chat-prompt');

        // Ajouter le message user + skeleton
        addSkeletonMessage(prompt, pendingImage, true, null, currentGenerationChatId);

        // Backend loads the model on-demand, no need to wait for preloading
        const inpaintModel = getCurrentImageModel();
        const imageRequestStartTime = Date.now();

        try {
            const adultPayload = window.getAdultGenerationPayload ? window.getAdultGenerationPayload() : {};
            const faceRefs = typeof getFaceRefPayload === 'function'
                ? getFaceRefPayload()
                : (faceRefImage ? [faceRefImage] : []);
            const result = await apiGeneration.generate({
                prompt: prompt,
                model: inpaintModel,
                chat_model: userSettings.chatModel || null,
                image: pendingImage,
                // strength géré par le Smart Router (pas d'override frontend)
                enhance: userSettings.enhancePrompt,
                enhance_mode: userSettings.enhanceMode || 'light',
                steps: pendingImage ? userSettings.steps : (userSettings.text2imgSteps || 30),
                ...adultPayload,
                controlnet_depth: userSettings.controlnetDepth ?? null,
                composite_radius: userSettings.compositeRadius ?? null,
                skip_auto_refine: userSettings.skipAutoRefine === true,
                face_ref: faceRefs[0] || null,
                face_refs: faceRefs,
                text2img_guidance: userSettings.text2imgGuidance ?? 7.5,
                face_ref_scale: userSettings.faceRefScale ?? 0.35,
                style_ref: styleRefImage || null,
                style_ref_scale: userSettings.styleRefScale ?? 0.55,
                export_format: userSettings.exportFormat || 'auto',
                export_width: userSettings.exportWidth || 768,
                export_height: userSettings.exportHeight || 1344,
                export_view: getActiveExportView(),
                export_pose: getActiveExportPose(),
                export_presets: JSON.stringify(userSettings.exportPresets || {}),
                chatId: currentGenerationChatId,
                generationId: currentGenerationId,
            }, chatAbortSignal);

            // Arrêter le polling de preview
            stopPreviewPolling();

            if (result.aborted || result.data?.cancelled || chatAbortSignal.aborted) {
                // Annulé — stopAllGenerations a déjà géré le skeleton
                console.log('[GEN] Génération annulée');
            } else if (result.ok && result.data?.success) {
                if (currentChatId !== currentGenerationChatId && currentGenerationChatId) {
                    await loadChat(currentGenerationChatId);
                }
                removeSkeletonMessage(currentGenerationChatId);
                const data = result.data;
                const totalGenerationTime = (Date.now() - imageRequestStartTime) / 1000;
                modifiedImage = 'data:image/png;base64,' + data.modified;

                if (data.mode === 'txt2img') {
                    originalImage = null;
                    addMessageTxt2Img(prompt, modifiedImage, data.generationTime, data.seed || null, currentGenerationChatId, totalGenerationTime);
                } else {
                    originalImage = 'data:image/png;base64,' + data.original;
                    addMessage(prompt, pendingImage, originalImage, modifiedImage, data.generationTime, currentGenerationChatId, totalGenerationTime);
                }

            } else if (!result.aborted && !chatAbortSignal.aborted) {
                showGenerationError(result);
            }
        } catch (err) {
            stopPreviewPolling();
            if (err.name !== 'AbortError' && !chatAbortSignal.aborted) {
                removeSkeletonMessage(currentGenerationChatId);
                Toast.error(err.message);
            }
        }

        isGenerating = false;
        pendingImage = null;
        currentController = null;
        currentGenerationId = null;
        currentGenerationChatId = null;
        setSendButtonsMode(false);
        refocusChatInput();
        // Traiter le prochain élément de la queue (sauf si depuis queue)
        if (!executingFromQueueChat) {
            setTimeout(() => processNextInQueue(), 100);
        }
        return;
    }

    // Mode texte normal
    // Vérifier si un modèle Ollama est disponible
    const modelCheck = await checkOllamaModelAvailable();
    if (!modelCheck.available) {
        showNoModelError(modelCheck.message);
        return;
    }

    // S'assurer que le modèle texte est chargé
    await preloadTextModel();

    if (isGenerating && currentController) {
        currentController.abort();
        removeSkeletonMessage();
    }

    currentController = new AbortController();

    addToPromptHistory(prompt);
    resetComposerTextarea('chat-prompt');

    isGenerating = true;
    currentGenerationMode = 'chat';  // Tracker le mode pour stop
    currentGenerationChatId = currentChatId;
    currentGenerationId = generateUUID();
    setSendButtonsMode(true);

    // Afficher immédiatement le message + skeleton
    addChatSkeletonMessage(prompt, imageAnalysisRequest ? currentImage : null);
    refocusChatInput();

    // Persister le skeleton actif: il sert de carte de progression si on
    // quitte/revient dans la conversation pendant la génération.
    const messagesDiv = document.getElementById('chat-messages');
    const htmlToSave = messagesDiv ? messagesDiv.innerHTML : getChatHtmlWithoutSkeleton();
    saveCurrentChatHtml(prompt, htmlToSave, currentGenerationChatId);

    const startTime = Date.now();

    let aborted = false;
    try {
        await handleChatStream(prompt, startTime, currentGenerationChatId);
    } catch (err) {
        if (err.name === 'AbortError') {
            aborted = true;
        } else {
            removeSkeletonMessage(currentGenerationChatId);
            console.error('Chat error:', err);
        }
    }

    isGenerating = false;
    currentController = null;
    currentGenerationId = null;
    currentGenerationChatId = null;
    setSendButtonsMode(false);
    refocusChatInput();
    if (!aborted && !executingFromQueueChat) {
        setTimeout(() => processNextInQueue(), 100);
    }
}

async function regenerateChat(prompt) {
    document.getElementById('chat-prompt').value = prompt;
    await continueChat();
}

// Variables pour le streaming de preview (long polling)
let previewPollingActive = false;
let lastPreviewStep = 0;
let lastPreviewPhase = 'generation';

// Démarre le long polling de preview
function startPreviewPolling() {
    // Si déjà actif, ne pas redémarrer
    if (previewPollingActive) return;

    previewPollingActive = true;
    lastPreviewStep = 0;
    lastPreviewPhase = 'generation';

    // Fonction récursive de long polling
    async function pollPreview() {
        if (!previewPollingActive) return;

        const result = await apiGeneration.getPreview(lastPreviewStep, lastPreviewPhase);

        if (!previewPollingActive) return; // Vérifie si arrêté pendant l'attente

        if (!result.ok) {
            // En cas d'erreur, réessayer après un délai
            if (previewPollingActive) {
                setTimeout(pollPreview, 1000);
            }
            return;
        }

        const data = result.data;
        if (data.done) {
            // Génération terminée
            previewPollingActive = false;
            return;
        }

        // Changement de phase - reset le compteur de steps
        if (data.phase !== lastPreviewPhase) {
            console.log(`[PREVIEW] Phase change: ${lastPreviewPhase} -> ${data.phase}`);
            lastPreviewStep = 0;
            lastPreviewPhase = data.phase;
        }

        // Mettre à jour l'affichage
        if (data.step > lastPreviewStep || data.phase_changed || data.message || data.phase === 'fine_tuning' || data.phase === 'refine') {
            lastPreviewStep = data.step;
            updateSkeletonPreview(data.preview, data.step, data.total, data.phase, data.message || '');
        }

        // Continuer le long polling immédiatement
        if (previewPollingActive) {
            pollPreview();
        }
    }

    // Démarrer le long polling
    pollPreview();
}

// Arrête le polling de preview
function stopPreviewPolling() {
    previewPollingActive = false;
    lastPreviewStep = 0;
    lastPreviewPhase = 'generation';
}

function findActiveImagePreviewContainer(targetChatId = null) {
    const skeletons = Array.from(document.querySelectorAll('.image-skeleton-message'))
        .filter(node => node.querySelector('.skeleton-preview-container'));

    if (!skeletons.length) return null;

    if (targetChatId) {
        const scoped = skeletons.filter(node => node.dataset?.chatId === targetChatId);
        if (scoped.length) {
            // Always update the newest live skeleton for that chat. A previous
            // finished card must not keep the image-skeleton-message class, but
            // if an old persisted DOM node slips through, this prevents it from
            // stealing the current generation preview.
            return scoped.at(-1).querySelector('.skeleton-preview-container');
        }
    }

    // Fallback for legacy skeletons without data-chat-id: use the newest active
    // card, never querySelector() which would target the first stale one.
    return skeletons.at(-1).querySelector('.skeleton-preview-container');
}

// Met à jour le skeleton avec la preview
function updateSkeletonPreview(previewBase64, step, total, phase = 'generation', message = '') {
    const targetChatId = typeof currentGenerationChatId !== 'undefined'
        ? (currentGenerationChatId || currentChatId)
        : currentChatId;
    const container = findActiveImagePreviewContainer(targetChatId)
        || document.querySelector('.modified-skeleton-container .skeleton-preview-container');

    if (!container) return;

    const img = container.querySelector('.skeleton-preview-image');
    const skeletonBg = container.querySelector('.skeleton-image');
    const progressBar = container.querySelector('.generation-progress-bar');
    const stepText = container.querySelector('.generation-step-text');

    // Keep raw progress data on the skeleton so a locale switch can re-render
    // the label without waiting for another backend progress event.
    container.dataset.progressPhase = phase || '';
    container.dataset.progressStep = String(step || 0);
    container.dataset.progressTotal = String(total || 0);
    container.dataset.progressMessage = message || '';

    if (img && previewBase64) {
        // Cacher le skeleton shimmer seulement quand une vraie preview existe.
        // Certains callbacks peuvent remonter un step sans image; dans ce cas
        // on garde le shimmer visible et on met juste à jour le compteur.
        if (skeletonBg) {
            skeletonBg.style.opacity = '0';
        }
        img.src = 'data:image/jpeg;base64,' + previewBase64;
        // Auto-dimensionner le container au premier preview pour respecter l'aspect ratio.
        // In edit/inpaint mode chat.js locks this box to the rendered Original image size;
        // do not override it with the intermediate latent preview aspect ratio.
        if (!container.dataset.sized && container.dataset.sizeLocked !== '1') {
            img.onload = function() {
                if (this.naturalWidth && this.naturalHeight) {
                    const ratio = this.naturalWidth / this.naturalHeight;
                    const w = container.offsetWidth || 200;
                    const h = Math.round(w / ratio);
                    container.style.height = h + 'px';
                    container.dataset.sized = '1';
                }
            };
        }
        // Blur progressif : s'étale sur toutes les phases, atteint 0 à la fin de la dernière
        // generation: 4px → 1.5px | fine_tuning: 1.5px → 0.3px | refine: 0.3px → 0px
        const progress = total > 0 ? step / total : 1;
        let blurPx;
        if (phase === 'refine') {
            blurPx = 0.3 * (1 - progress);
        } else if (phase === 'fine_tuning') {
            blurPx = 1.5 - 1.2 * progress;  // 1.5 → 0.3
        } else {
            blurPx = 4 - 2.5 * progress;    // 4 → 1.5
        }
        blurPx = Math.max(0, blurPx);
        img.style.filter = `contrast(1.05) blur(${blurPx.toFixed(1)}px)`;
        console.log(`[Preview] ${phase} step ${step}/${total} → blur: ${blurPx.toFixed(1)}px`);
        // Utiliser requestAnimationFrame pour déclencher la transition après le src change
        requestAnimationFrame(() => {
            img.classList.add('visible');
        });
    }

    if (progressBar && total > 0) {
        const percent = (step / total) * 100;
        progressBar.style.width = percent + '%';
        // Couleur différente pour le fine tuning / refine
        if (phase === 'fine_tuning' || phase === 'refine') {
            progressBar.classList.add('fine-tuning');
        } else {
            progressBar.classList.remove('fine-tuning');
        }
    }

    if (stepText && (step > 0 || message || phase)) {
        const progressText = formatGenerationProgressText(phase, step, total, message);
        if (progressText) {
            stepText.textContent = progressText;
        }
    }

    // Scroll pour garder la preview visible pendant la génération
    scrollToBottom();
}

// Génère une image après que l'IA a répondu (skeleton déjà affiché)
async function generateImageFromChat(imagePrompt, targetChatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    console.log('[GEN] Génération d\'image après chat:', imagePrompt);

    // Générer un ID pour cette génération
    currentGenerationId = generateUUID();
    currentGenerationChatId = targetChatId;
    currentGenerationMode = 'text2img';
    isGenerating = true;
    setSendButtonsMode(true);
    currentController = new AbortController();
    const imageAbortSignal = currentController.signal;

    const genStartTime = Date.now();
    const imageModel = getCurrentImageModel();

    // Backend loads the model on-demand, no need to wait for preloading

    ensureImageSkeletonForChat(targetChatId);

    // Démarrer le polling de preview maintenant que la génération commence
    startPreviewPolling();

    try {
        const adultPayload = window.getAdultGenerationPayload ? window.getAdultGenerationPayload() : {};
        const faceRefs = typeof getFaceRefPayload === 'function'
            ? getFaceRefPayload()
            : (faceRefImage ? [faceRefImage] : []);
        const result = await apiGeneration.generate({
            image: null,
            prompt: imagePrompt,
            model: imageModel,
            chat_model: userSettings.chatModel || null,
            enhance: false,
            skip_enhance: true,
            steps: userSettings.text2imgSteps || 30,
            chatId: targetChatId,
            generationId: currentGenerationId,
            face_ref: faceRefs[0] || null,
            face_refs: faceRefs,
            text2img_guidance: userSettings.text2imgGuidance ?? 7.5,
            face_ref_scale: userSettings.faceRefScale ?? 0.35,
            style_ref: styleRefImage || null,
            style_ref_scale: userSettings.styleRefScale ?? 0.55,
            export_format: userSettings.exportFormat || 'auto',
            export_width: userSettings.exportWidth || 768,
            export_height: userSettings.exportHeight || 1344,
            export_view: getActiveExportView(),
            export_pose: getActiveExportPose(),
            pose_strength: userSettings.poseStrength ?? 0.5,
            export_presets: JSON.stringify(userSettings.exportPresets || {}),
            ...adultPayload,
        }, imageAbortSignal);

        // Arrêter le polling
        stopPreviewPolling();

        const totalTimeMs = Date.now() - genStartTime;

        // Vérifier si annulé
        if (result.data?.cancelled) {
            replaceImageSkeletonWithError(generationT('generation.cancelled', 'Génération annulée'), targetChatId);
            currentGenerationId = null;
        } else if (result.ok && result.data?.success && result.data?.modified) {
            modifiedImage = 'data:image/png;base64,' + result.data.modified;
            replaceImageSkeletonWithReal(modifiedImage, totalTimeMs, targetChatId, result.data.generationTime);
            currentGenerationId = null;
        } else {
            replaceImageSkeletonWithError(result.data?.error || result.error || generationT('generation.errorCard.title', 'Erreur de génération'), targetChatId);
            currentGenerationId = null;
        }
    } catch (genErr) {
        stopPreviewPolling();
        if (genErr.name !== 'AbortError' && !imageAbortSignal.aborted) {
            replaceImageSkeletonWithError(genErr.message, targetChatId);
        } else {
            replaceImageSkeletonWithError(generationT('generation.cancelled', 'Génération annulée'), targetChatId);
        }
        currentGenerationId = null;
    } finally {
        currentController = null;
        currentGenerationChatId = null;
        currentGenerationMode = null;
        isGenerating = false;
        setSendButtonsMode(false);
    }

    // Sauvegarder le HTML final
    const finalHtml = getChatHtmlWithoutSkeleton();
    saveCurrentChatHtml('', finalHtml, targetChatId);
}

function ensureImageSkeletonForChat(chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    if (chatId && document.querySelector(`.image-skeleton-message[data-chat-id="${chatId}"]`)) {
        return;
    }
    if (chatId && chatId !== currentChatId) {
        return;
    }
    addImageSkeletonToChat(chatId);
}

// Ajoute un skeleton d'image dans le chat (avec support preview)
function addImageSkeletonToChat(chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    const messagesDiv = document.getElementById('chat-messages');
    if (!messagesDiv) return;

    // Ajouter une classe au dernier message pour réduire son margin-bottom
    const lastMessage = messagesDiv.querySelector('.message:last-child');
    if (lastMessage) {
        lastMessage.classList.add('before-image-skeleton');
    }

    const skeleton = document.createElement('div');
    skeleton.className = 'message image-skeleton-message';
    // Ajouter un data-attribute avec le chatId pour pouvoir détecter si c'est orphelin
    if (chatId) skeleton.setAttribute('data-chat-id', chatId);
    skeleton.setAttribute('data-started-at', Date.now());
    const initialProgressText = getInitialGenerationProgressText();
    const generatingText = generationT('generation.labels.generationInProgress', 'Génération en cours...');
    skeleton.innerHTML = `
        <div class="ai-response loading">
            <div class="result-images">
                <div class="result-image-container modified-skeleton-container">
                    <div class="skeleton-preview-container" data-progress-phase="prepare_generation" data-progress-step="0" data-progress-total="0" data-progress-message="">
                        <div class="skeleton skeleton-image"></div>
                        <img class="skeleton-preview-image">
                        <div class="generation-progress">
                            <div class="generation-progress-bar" style="width: 0%"></div>
                        </div>
                        <div class="generation-step-text">${initialProgressText}</div>
                    </div>
                    <div class="image-generating-text" data-i18n="generation.labels.generationInProgress">${generatingText}</div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.appendChild(skeleton);
    scrollToBottom();
    if (chatId && typeof saveCurrentChatHtml === 'function' && chatId === currentChatId) {
        saveCurrentChatHtml('', getCurrentChatHtml(), chatId);
    }
}

// Remplace le skeleton par l'image réelle
// targetChatId = chat où mettre le résultat (optionnel, défaut = currentChatId)
function replaceImageSkeletonWithReal(imageSrc, totalTimeMs, targetChatId = null, generationTime = null) {
    const chatId = targetChatId || currentChatId;
    const totalTime = totalTimeMs ? totalTimeMs / 1000 : null;
    const fallbackTimeText = totalTimeMs
        ? (totalTimeMs > 1000 ? `${(totalTimeMs / 1000).toFixed(1)}s` : `${totalTimeMs}ms`)
        : '';
    const timeText = formatImageTimingDisplay(generationTime, totalTime)
        || fallbackTimeText;
    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    const resultHtml = `
        <div class="result-image-container generated-image-container">
            <div class="result-image-wrapper">
                <img src="${imageSrc}" class="result-image" onclick="openModalSingle('${imageSrc}')">
                <div class="image-actions">
                    <button class="edit-btn" onclick="openEditModalWithModelSwitch('${imageSrc}')" title="${generationT('common.edit', 'Éditer')}">${editIcon}</button>
                    <button class="edit-btn refine-btn" onclick="fixDetailsImage('${imageSrc}')" title="Fix Details">${fixDetailsIcon}</button>
                </div>
            </div>
            <div class="image-gen-time image-gen-time-dual">${timeText}</div>
        </div>
    `;
    const resultMessageHtml = `
        <div class="message generated-image-message">
            <div class="ai-response">
                ${resultHtml}
            </div>
        </div>
    `;

    // Si c'est le chat actuel, mettre à jour le DOM
    if (chatId === currentChatId) {
        const skeleton = document.querySelector(`.image-skeleton-message[data-chat-id="${chatId}"]`)
                      || document.querySelector('.image-skeleton-message');
        if (skeleton) {
            const prevMessage = document.querySelector('.before-image-skeleton');
            if (prevMessage) prevMessage.classList.remove('before-image-skeleton');

            skeleton.classList.remove('image-skeleton-message');
            skeleton.classList.add('message', 'ai-response');
            skeleton.removeAttribute('data-chat-id');
            skeleton.removeAttribute('data-started-at');
            skeleton.innerHTML = resultHtml;

            return;
        }

        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) {
            console.warn('[GEN] Image skeleton missing, appending generated result card');
            messagesDiv.insertAdjacentHTML('beforeend', resultMessageHtml);
            scrollToBottom(true);
            if (typeof saveCurrentChatHtml === 'function') {
                saveCurrentChatHtml('', getCurrentChatHtml(), chatId);
            }
            return;
        }
    }

    // If the user switched conversations during the generation, update the
    // stored transcript by chatId instead of touching the currently visible DOM.
    if (chatId && typeof getChatRecord === 'function' && typeof saveCurrentChatHtml === 'function') {
        getChatRecord(chatId).then(record => {
            if (!record) return;
            const temp = document.createElement('div');
            temp.innerHTML = record.html || '';
            const skeleton = Array.from(temp.querySelectorAll('.image-skeleton-message'))
                .find(node => node.dataset?.chatId === chatId);
            if (skeleton) {
                skeleton.classList.remove('image-skeleton-message');
                skeleton.classList.add('message', 'ai-response');
                skeleton.removeAttribute('data-chat-id');
                skeleton.removeAttribute('data-started-at');
                skeleton.innerHTML = resultHtml;
            } else {
                console.warn('[GEN] Stored image skeleton missing, appending generated result card');
                temp.insertAdjacentHTML('beforeend', resultMessageHtml);
            }
            saveCurrentChatHtml('', temp.innerHTML, chatId);
        }).catch(e => console.warn('[GEN] Inactive image skeleton update failed:', e));
    }
}

function isAddonRequiredGenerationError(error, options = {}) {
    if (options?.featureBlocked || options?.code === 'adult_mode_locked') return true;
    const text = String(error || '').toLowerCase();
    return (
        text.includes('pack local')
        || text.includes('adult pack')
        || text.includes('addon')
        || text.includes('adult_mode_locked')
    );
}

function buildAddonRequiredErrorHtml() {
    const guideUrl = '/docs/THIRD_PARTY_PACKS.md';
    const guidePath = 'docs/THIRD_PARTY_PACKS.md';
    const body = generationT(
        'generation.addonRequired.body',
        'This request requires an optional local addon. Download the pack from the guide, enable it in Addons, then try again.'
    );

    return `
        <div class="chat-bubble addon-required-bubble" role="status" aria-live="polite">
            <div class="addon-required-card">
                <div class="addon-required-icon" aria-hidden="true">
                    <i data-lucide="package-plus"></i>
                </div>
                <div class="addon-required-content">
                    <div class="addon-required-kicker">${escapeHtml(generationT('generation.addonRequired.kicker', 'Optional local addon'))}</div>
                    <div class="addon-required-title">${escapeHtml(generationT('generation.addonRequired.title', 'Local addon required'))}</div>
                    <div class="addon-required-body">${escapeHtml(body)}</div>
                    <div class="addon-required-guide">
                        <i data-lucide="file-text" aria-hidden="true"></i>
                        <span>${escapeHtml(generationT('generation.addonRequired.guideHint', 'Download guide: {path}', { path: guidePath }))}</span>
                    </div>
                    <div class="addon-required-actions">
                        <button type="button" class="addon-required-btn primary" onclick="window.openAddonsHub?.(); window.setAddonsHubSection?.('library');">
                            <i data-lucide="boxes" aria-hidden="true"></i>
                            <span>${escapeHtml(generationT('generation.addonRequired.openAddons', 'Open Addons'))}</span>
                        </button>
                        <button type="button" class="addon-required-btn" onclick="window.open('${guideUrl}', '_blank', 'noopener,noreferrer')">
                            <i data-lucide="download" aria-hidden="true"></i>
                            <span>${escapeHtml(generationT('generation.addonRequired.openGuide', 'Download guide'))}</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function buildGenerationErrorHtml(error) {
    const rawError = String(error || '').trim();
    const title = generationT('generation.errorCard.title', 'Erreur de génération');
    const cancelled = generationT('generation.cancelled', 'Génération annulée');
    const showDetails = rawError && rawError !== title && rawError !== cancelled;
    const body = rawError === cancelled
        ? generationT('generation.errorCard.cancelledBody', 'La génération a été arrêtée. Tu peux relancer quand tu veux.')
        : generationT('generation.errorCard.body', 'JoyBoy n’a pas pu terminer cette génération. Réessaie, ou ajuste le prompt/modèle si l’erreur revient.');

    return `
        <div class="chat-bubble generation-error-bubble" role="alert" aria-live="polite">
            <div class="generation-error-card">
                <div class="generation-error-icon" aria-hidden="true">
                    <i data-lucide="${rawError === cancelled ? 'x-circle' : 'alert-triangle'}"></i>
                </div>
                <div class="generation-error-content">
                    <div class="generation-error-kicker">${escapeHtml(generationT('generation.errorCard.kicker', 'Image'))}</div>
                    <div class="generation-error-title">${escapeHtml(rawError === cancelled ? cancelled : title)}</div>
                    <div class="generation-error-body">${escapeHtml(body)}</div>
                    ${showDetails ? `
                        <details class="generation-error-details">
                            <summary>${escapeHtml(generationT('generation.errorCard.details', 'Détails techniques'))}</summary>
                            <pre>${escapeHtml(rawError)}</pre>
                        </details>
                    ` : ''}
                </div>
            </div>
        </div>
    `;
}

// Remplace le skeleton par une erreur
function replaceImageSkeletonWithError(error, targetChatId = null, options = {}) {
    const chatId = targetChatId || currentChatId;

    const errorHtml = isAddonRequiredGenerationError(error, options)
        ? buildAddonRequiredErrorHtml(error)
        : buildGenerationErrorHtml(error);

    // Si c'est le chat actuel, mettre à jour le DOM
    if (chatId === currentChatId) {
        const skeleton = document.querySelector(`.image-skeleton-message[data-chat-id="${chatId}"]`)
                      || document.querySelector('.image-skeleton-message');
        if (skeleton) {
            const prevMessage = document.querySelector('.before-image-skeleton');
            if (prevMessage) prevMessage.classList.remove('before-image-skeleton');

            skeleton.classList.remove('image-skeleton-message');
            skeleton.classList.add('message', 'ai-response');
            skeleton.removeAttribute('data-chat-id');
            skeleton.removeAttribute('data-started-at');
            skeleton.innerHTML = errorHtml;
            if (window.lucide) lucide.createIcons();

            return;
        }
    }

    if (chatId && typeof getChatRecord === 'function' && typeof saveCurrentChatHtml === 'function') {
        getChatRecord(chatId).then(record => {
            if (!record) return;
            const temp = document.createElement('div');
            temp.innerHTML = record.html || '';
            const skeleton = Array.from(temp.querySelectorAll('.image-skeleton-message'))
                .find(node => node.dataset?.chatId === chatId);
            if (!skeleton) return;
            skeleton.classList.remove('image-skeleton-message');
            skeleton.classList.add('message', 'ai-response');
            skeleton.removeAttribute('data-chat-id');
            skeleton.removeAttribute('data-started-at');
            skeleton.innerHTML = errorHtml;
            saveCurrentChatHtml('', temp.innerHTML, chatId);
        }).catch(e => console.warn('[GEN] Inactive image skeleton error update failed:', e));
    }
}
