// ===== CHAT - Messages & Skeleton =====

function chatT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

function imageLabelT(key, fallback = '', params = {}) {
    return chatT(`generation.labels.${key}`, fallback, params);
}

function imageLabelAttr(key) {
    return `data-i18n="generation.labels.${key}"`;
}

// ===== SVG ICON CONSTANTS (shared across message builders) =====
const ICON_EDIT = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
const ICON_FIX_DETAILS = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"/><path d="M5 19l1 3 1-3 3-1-3-1-1-3-1 3-3 1 3 1z"/><path d="M19 12l1 2 1-2 2-1-2-1-1-2-1 2-2 1 2 1z"/></svg>`;
const ICON_COPY = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;

// Cached DOM reference for chat-messages container (queried 20+ times)
let _chatMessagesEl = null;
function getChatMessages() {
    if (!_chatMessagesEl) _chatMessagesEl = document.getElementById('chat-messages');
    return _chatMessagesEl;
}

// Helper: barre d'action pour les images (même style que les réponses texte)
function buildImageActionsBar(prompt, generationTime, seed = null, totalTime = null) {
    const safePrompt = (prompt || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const timeHtml = totalTime
        ? formatImageTimingDisplay(generationTime, totalTime)
        : (generationTime ? formatGenTimeDisplay(generationTime) : '');
    const seedBtn = seed != null ? `
            <div class="chat-actions-divider"></div>
            <button class="chat-action-btn seed-btn" onclick="copyToClipboard('seed:${seed}')" title="Copier seed:${seed} pour reproduire cette image">
                seed:${seed}
            </button>` : '';
    return `
        <div class="chat-actions">
            <button class="chat-action-btn" onclick="copyImagePrompt('${safePrompt}')" title="Copier le prompt">
                ${ICON_COPY}
            </button>
            <div class="chat-actions-divider"></div>
            <div class="response-time">${timeHtml}</div>${seedBtn}
        </div>
    `;
}

/**
 * Fix details (ADetailer): detects faces and re-inpaints each at high resolution
 * @param {string} imageUrl - L'URL de l'image à corriger
 */
async function fixDetailsImage(imageUrl) {
    addSkeletonMessage('Fix details en cours...', imageUrl, true);

    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    try {
        const result = await apiGeneration.fixDetails({ image: imageUrl });

        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();

        removeSkeletonMessage();

        const data = result.data;

        if (data?.success) {
            const originalSrc = data.original?.startsWith('data:') ? data.original : 'data:image/png;base64,' + data.original;
            const modifiedSrc = data.modified?.startsWith('data:') ? data.modified : 'data:image/png;base64,' + data.modified;

            if (typeof addMessageEdit === 'function') {
                addMessageEdit('Fix Details', originalSrc, modifiedSrc, null, data.generationTime);
            }

            if (typeof modifiedImage !== 'undefined') modifiedImage = modifiedSrc;

            const fixedParts = [];
            if (data.faces_fixed) {
                fixedParts.push(chatT('editor.facesFixed', '{count} visage(s)', { count: data.faces_fixed }));
            }
            if (data.hands_fixed) {
                fixedParts.push(chatT('editor.handsFixed', '{count} main(s)', { count: data.hands_fixed }));
            }
            const facesMsg = fixedParts.length ? ` (${fixedParts.join(', ')})` : '';
            Toast.success(chatT('editor.detailsFixed', 'Détails corrigés en {seconds}s{faces}', {
                seconds: data.generationTime?.toFixed(1) || '?',
                faces: facesMsg,
            }));
        } else {
            Toast.error(data?.error || chatT('editor.fixDetailsFailed', 'Échec fix details'));
        }
    } catch (error) {
        console.error('[FIX-DETAILS] Erreur:', error);
        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();
        removeSkeletonMessage();
        Toast.error(chatT('editor.fixDetailsFailed', 'Échec fix details'));
    }
}

function findScopedChatElement(selector, chatId, root = document) {
    const nodes = Array.from(root.querySelectorAll(selector));
    if (!chatId) return nodes[0] || null;
    return nodes.find(node => node.dataset?.chatId === chatId) || null;
}

function removeSkeletonMessage(chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    const root = getChatMessages() || document;
    const activeChatId = typeof currentChatId !== 'undefined' ? currentChatId : null;
    const allowLegacyFallback = !chatId || chatId === activeChatId;

    // Supprimer les skeletons texte
    const textSkeleton = findScopedChatElement('.skeleton-message', chatId, root)
        || (allowLegacyFallback ? root.querySelector('.skeleton-message:not([data-chat-id])') : null);
    if (textSkeleton) textSkeleton.remove();

    // Supprimer aussi les skeletons image (inpainting)
    const imageSkeleton = findScopedChatElement('.image-skeleton-message', chatId, root)
        || (allowLegacyFallback ? root.querySelector('.image-skeleton-message:not([data-chat-id])') : null);
    if (imageSkeleton) imageSkeleton.remove();

    if (typeof saveCurrentChatHtml === 'function' && allowLegacyFallback) {
        const html = typeof getChatHtmlWithoutSkeleton === 'function'
            ? getChatHtmlWithoutSkeleton()
            : (getChatMessages()?.innerHTML || '');
        saveCurrentChatHtml('', html, chatId);
    }
}

function addSkeletonMessage(prompt, userImage, hasImage, maskImage = null, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : '')) {
    const messagesDiv = getChatMessages();
    const startedAt = Date.now();

    // IMPORTANT: Si un skeleton existe déjà (réutilisé depuis la queue), ne pas en créer un autre.
    // Toujours chercher par data-chat-id: une génération peut finir après un
    // switch de conversation, et le premier skeleton du DOM n'est pas forcément
    // celui du job courant.
    const existingSkeleton = findScopedChatElement('.image-skeleton-message', chatId, messagesDiv);
    if (existingSkeleton) {
        console.log(`%c[SKELETON] Skeleton existe déjà pour chat ${chatId?.substring(0, 10)}, skip`, 'color: #f59e0b; font-weight: bold');
        return;
    }

    console.log(`%c[SKELETON] Ajout skeleton pour chat ${chatId?.substring(0, 10)}`, 'color: #22c55e; font-weight: bold');

    // Utiliser image-skeleton-message pour les générations d'image (pas skeleton-message qui est pour le texte)
    const initialProgressText = chatT('generation.progress.prepare_generation', 'Préparation de la génération...');
    const resultLabelKey = hasImage ? 'modified' : 'generated';
    const resultLabelFallback = hasImage ? 'Modifié' : 'Généré';
    const skeletonHtml = `
        <div class="message image-skeleton-message" data-chat-id="${chatId}" data-started-at="${startedAt}">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
                ${hasImage && userImage ? `<img src="${userImage}" class="user-thumb">` : ''}
            </div>
            <div class="ai-response loading">
                <div class="result-images">
                    ${hasImage ? `
                    <div class="result-image-container skeleton-original-container">
                        <div class="result-image-wrapper">
                            <img src="${userImage}" class="result-image original-preview-image">
                        </div>
                        <div class="image-label" ${imageLabelAttr('original')}>${imageLabelT('original', 'Original')}</div>
                    </div>
                    ` : ''}
                    <div class="result-image-container modified-skeleton-container">
                        <div class="skeleton-preview-container" data-progress-phase="prepare_generation" data-progress-step="0" data-progress-total="0" data-progress-message="">
                            <div class="skeleton skeleton-image"></div>
                            <img class="skeleton-preview-image">
                            <div class="generation-progress">
                                <div class="generation-progress-bar" style="width: 0%"></div>
                            </div>
                            <div class="generation-step-text">${initialProgressText}</div>
                        </div>
                        <div class="image-label" ${imageLabelAttr(resultLabelKey)}>${imageLabelT(resultLabelKey, resultLabelFallback)}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', skeletonHtml);
    // Persist active skeletons too: if the user switches conversations while a
    // generation is running, returning to this chat should show the pending card
    // instead of losing all context.
    if (typeof saveCurrentChatHtml === 'function') {
        saveCurrentChatHtml('', messagesDiv.innerHTML, chatId);
    }
    scrollToBottom(true);

    // Adapter la taille du skeleton à l'image originale
    if (hasImage && userImage) {
        const skeletonMsg = messagesDiv.querySelector('.image-skeleton-message:last-child');
        if (skeletonMsg) {
            const originalImg = skeletonMsg.querySelector('.original-preview-image');
            const skeletonContainer = skeletonMsg.querySelector('.skeleton-preview-container');
            const modifiedContainer = skeletonMsg.querySelector('.modified-skeleton-container');

            if (originalImg && skeletonContainer) {
                // Copy the rendered Original rect. Recomputing from natural dimensions can
                // drift when CSS max-height/max-width changes and makes the skeleton bigger.
                const getDisplayedImageSize = (img) => {
                    const rect = img.getBoundingClientRect();
                    if (rect.width > 1 && rect.height > 1) {
                        return { width: Math.round(rect.width), height: Math.round(rect.height) };
                    }

                    const wrapperRect = img.closest('.result-image-wrapper')?.getBoundingClientRect();
                    if (wrapperRect?.width > 1 && wrapperRect?.height > 1) {
                        return { width: Math.round(wrapperRect.width), height: Math.round(wrapperRect.height) };
                    }

                    const naturalWidth = img.naturalWidth || 0;
                    const naturalHeight = img.naturalHeight || 0;
                    if (!naturalWidth || !naturalHeight) {
                        return null;
                    }

                    const scale = Math.min(300 / naturalWidth, 300 / naturalHeight, 1);
                    return {
                        width: Math.round(naturalWidth * scale),
                        height: Math.round(naturalHeight * scale),
                    };
                };

                // Fonction pour ajuster la taille
                const adjustSize = () => {
                    const size = getDisplayedImageSize(originalImg);

                    if (size && size.width > 0 && size.height > 0) {
                        // Appliquer les dimensions en préservant les autres styles
                        modifiedContainer?.style.setProperty('width', size.width + 'px', 'important');
                        modifiedContainer?.style.setProperty('max-width', size.width + 'px', 'important');
                        skeletonContainer.style.setProperty('width', size.width + 'px', 'important');
                        skeletonContainer.style.setProperty('height', size.height + 'px', 'important');
                        skeletonContainer.style.setProperty('max-width', 'none', 'important');
                        skeletonContainer.style.setProperty('min-width', 'unset', 'important');
                        skeletonContainer.style.setProperty('aspect-ratio', `${size.width} / ${size.height}`, 'important');
                        // The diffusion preview has its own aspect ratio while in-flight.
                        // Keep the edit preview locked to the rendered Original card so it
                        // does not look larger and then snap back when the final image lands.
                        skeletonContainer.dataset.sized = '1';
                        skeletonContainer.dataset.sizeLocked = '1';
                        console.log(`[SKELETON] Taille ajustée: ${size.width}x${size.height} (image: ${originalImg.naturalWidth}x${originalImg.naturalHeight})`);
                    } else {
                        // Retry si dimensions pas encore disponibles
                        setTimeout(adjustSize, 100);
                    }
                };

                const scheduleAdjustSize = () => {
                    requestAnimationFrame(() => requestAnimationFrame(adjustSize));
                };

                // Si l'image est déjà chargée
                if (originalImg.complete && originalImg.naturalWidth > 0) {
                    scheduleAdjustSize();
                } else {
                    // Attendre le chargement
                    originalImg.onload = scheduleAdjustSize;
                }

                // Aussi observer les changements de taille
                if (window.ResizeObserver) {
                    const resizeObserver = new ResizeObserver(() => {
                        scheduleAdjustSize();
                    });
                    resizeObserver.observe(originalImg);
                }
            }
        }
    }

    // Démarrer le polling de preview pour l'inpainting uniquement.
    // Text2Img le lance depuis generation.js, et certains fallbacks vidéo
    // utilisent hasImage=true sans image source réelle.
    if (hasImage && userImage) {
        startPreviewPolling();
    }
}

/**
 * ANCHORED SCROLL — Étape 1 : Ajout du message utilisateur + skeleton
 *
 * Insère le bloc user-message + skeleton IA, puis scroll le nouveau
 * message au "naturalTop" (position du 1er message dans le viewport).
 *
 * Premier message : pas de scroll, il apparaît en haut naturellement.
 * Messages suivants : scroll pour que le nouveau message prenne la
 * même position visuelle que le premier — les anciens messages passent
 * au-dessus, hors de vue.
 */
function addChatSkeletonMessage(prompt) {
    const messagesDiv = getChatMessages();
    const chatId = typeof currentChatId !== 'undefined' ? currentChatId : '';

    // Message utilisateur permanent (sera sauvegardé)
    const userMsgHtml = `
        <div class="message user-pending-msg" data-chat-id="${chatId}">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
            </div>
        </div>
    `;

    // Skeleton IA temporaire (ne sera pas sauvegardé)
    const skeletonHtml = `
        <div class="message skeleton-message" data-chat-id="${chatId}">
            <div class="ai-response">
                <div class="chat-bubble skeleton-bubble">
                    <div class="typing-dots">
                        <svg viewBox="0 0 24 24" width="24" height="24">
                            <circle class="td" cx="5.6" cy="5.6" r="1.6"/>
                            <circle class="td" cx="12" cy="5.6" r="1.6"/>
                            <circle class="td" cx="18.4" cy="5.6" r="1.6"/>
                            <circle class="td" cx="5.6" cy="12" r="1.6"/>
                            <circle class="td" cx="12" cy="12" r="1.6"/>
                            <circle class="td" cx="18.4" cy="12" r="1.6"/>
                            <circle class="td" cx="5.6" cy="18.4" r="1.6"/>
                            <circle class="td" cx="12" cy="18.4" r="1.6"/>
                            <circle class="td" cx="18.4" cy="18.4" r="1.6"/>
                        </svg>
                    </div>
                </div>
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', userMsgHtml + skeletonHtml);

    // Animate new entries
    const newPending = messagesDiv.querySelector('.user-pending-msg');
    const newSkeleton = messagesDiv.querySelector('.skeleton-message:last-of-type');
    if (newPending) newPending.classList.add('msg-enter');
    if (newSkeleton) newSkeleton.classList.add('msg-enter');

    // ANCHORED SCROLL : positionner le nouveau message au naturalTop
    requestAnimationFrame(() => {
        if (newPending) {
            const firstMsg = messagesDiv.querySelector('.message');
            const isFirstMessage = firstMsg === newPending;
            if (!isFirstMessage) {
                // target = distance pour que newPending soit à la même position
                // visuelle que firstMsg (naturalTop = firstMsg.offsetTop)
                const naturalTop = firstMsg ? firstMsg.offsetTop : 40;
                const target = newPending.offsetTop - naturalTop;
                messagesDiv.style.overflowY = 'auto';
                updateChatPadding();
                messagesDiv.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
            }
        }
    });
}

// Retourne le HTML sans le skeleton (pour sauvegarder)
function getChatHtmlWithoutSkeleton() {
    const messagesDiv = getChatMessages();
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = messagesDiv.innerHTML;

    // Supprimer le skeleton
    const skeleton = tempDiv.querySelector('.skeleton-message');
    if (skeleton) skeleton.remove();

    // Ancien flux projet: le sélecteur de workspace ne doit jamais être stocké
    // dans le transcript. Le launcher projet vit hors du chat, comme Codex.
    tempDiv.querySelectorAll('.terminal-workspace-picker, .project-launcher-overlay').forEach(el => el.remove());

    return tempDiv.innerHTML;
}

// Streaming message - updates in real-time
let currentStreamingMsgId = null;

/**
 * ANCHORED SCROLL — Étape 2 : Début du streaming
 *
 * Remplace le skeleton par une bulle de streaming en temps réel.
 * PAS DE SCROLL ICI — addChatSkeletonMessage() a déjà positionné
 * le viewport au bon endroit. scrollToBottom() dans appendToStreamingMessage()
 * prendra le relais si le contenu dépasse le viewport pendant le streaming.
 */
function createStreamingMessage(prompt) {
    removeSkeletonMessage();
    const messagesDiv = getChatMessages();
    const msgId = 'stream-' + Date.now();
    currentStreamingMsgId = msgId;
    streamingRawText = '';

    // Convertir le user-pending-msg en container message complet
    const pendingMsg = messagesDiv.querySelector('.user-pending-msg');
    if (pendingMsg) {
        pendingMsg.classList.remove('user-pending-msg');
        pendingMsg.id = msgId + '-container';

        const aiResponseHtml = `
            <div class="ai-response msg-enter">
                <div class="chat-bubble streaming" id="${msgId}"><span class="cursor">|</span></div>
            </div>
        `;
        pendingMsg.insertAdjacentHTML('beforeend', aiResponseHtml);
    } else {
        // Fallback si le pending-msg n'existe pas
        const messageHtml = `
            <div class="message" id="${msgId}-container">
                <div class="user-message">
                    <div class="user-bubble">${prompt}</div>
                </div>
                <div class="ai-response">
                    <div class="chat-bubble streaming" id="${msgId}"><span class="cursor">|</span></div>
                </div>
            </div>
        `;
        messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    }

    return msgId;
}

// Variable pour stocker le texte brut pendant le streaming
let streamingRawText = '';

/**
 * Affiche le statut de recherche web style Claude Code avec progression
 */
function showSearchingStatus(msgId, query, current, total) {
    const bubble = document.getElementById(msgId);
    if (!bubble) return;

    // Compteur style Claude Code: "Recherche web (2/3)"
    const counter = (current && total) ? ` (${current}/${total})` : '';

    // Tronquer la query si trop longue
    const displayQuery = query && query.length > 50 ? query.substring(0, 47) + '...' : (query || '');

    bubble.innerHTML = `
        <div class="searching-status">
            <i data-lucide="search" class="searching-icon"></i>
            <span class="searching-text">Recherche web${counter}</span>
            <span class="searching-dots"><span>.</span><span>.</span><span>.</span></span>
        </div>
        <div class="searching-query">${escapeHtml(displayQuery)}</div>
    `;
    if (window.lucide) lucide.createIcons();
    scrollToBottom();
}

/**
 * Retire le message de recherche et remet le curseur normal
 */
function hideSearchingStatus(msgId) {
    const bubble = document.getElementById(msgId);
    if (!bubble) return;

    bubble.innerHTML = '<span class="cursor">|</span>';
    scrollToBottom();
}

function appendToStreamingMessage(msgId, text) {
    const bubble = document.getElementById(msgId);
    if (bubble) {
        // Accumuler le texte brut
        streamingRawText += text;

        // Formater et afficher (avec curseur)
        let formatted = formatMarkdownPartial(streamingRawText);
        bubble.innerHTML = formatted + '<span class="cursor">|</span>';

        // Scroll seulement si le bas du contenu dépasse la zone visible (au-dessus de l'input)
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) {
            const inputBar = document.querySelector('.chat-input-bar');
            const inputTop = inputBar ? (messagesDiv.clientHeight - inputBar.offsetHeight - 40) : messagesDiv.clientHeight;
            const contentBottom = bubble.getBoundingClientRect().bottom - messagesDiv.getBoundingClientRect().top + messagesDiv.scrollTop;
            const visibleBottom = messagesDiv.scrollTop + inputTop;
            if (contentBottom > visibleBottom) {
                messagesDiv.scrollTop = contentBottom - inputTop;
            }
        }
    }
}

// Formatage partiel pour le streaming (gère les blocs incomplets)
function formatMarkdownPartial(text) {
    // Retirer les marqueurs [GENERATE_IMAGE: ...] (internes, pas pour l'utilisateur)
    let cleaned = text.replace(/\[GENERATE_IMAGE:[^\]]*\]/gi, '');

    // Nettoyer les doubles espaces/sauts de ligne
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');

    // Échapper le HTML
    let formatted = cleaned
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Code blocks complets ```lang\ncode```
    formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const langLabel = lang || 'code';
        return `<div class="code-block">
            <div class="code-header">
                <span class="code-lang">${langLabel}</span>
                <button class="code-copy-btn" onclick="copyCodeBlock(this)">Copier</button>
            </div>
            <pre><code>${code.trim()}</code></pre>
        </div>`;
    });

    // Code block en cours (pas encore fermé) - afficher en gris
    formatted = formatted.replace(/```(\w*)\n([\s\S]*)$/g, (match, lang, code) => {
        const langLabel = lang || 'code';
        return `<div class="code-block incomplete">
            <div class="code-header">
                <span class="code-lang">${langLabel}</span>
            </div>
            <pre><code>${code}</code></pre>
        </div>`;
    });

    // Code inline `code`
    formatted = formatted.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // Headers (pendant le streaming)
    formatted = formatted.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
    formatted = formatted.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
    formatted = formatted.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');

    // Blockquotes
    formatted = formatted.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

    // Listes à puces
    formatted = formatted.replace(/^- (.+)$/gm, '<li class="md-li">$1</li>');

    // Barré ~~text~~
    formatted = formatted.replace(/~~([^~]+)~~/g, '<del>$1</del>');

    // Gras **text**
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italique *text*
    formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Sauts de ligne
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

// Formatage markdown complet style Discord
function formatMarkdown(text) {
    // Nettoyer les doubles espaces/sauts de ligne
    let cleaned = text.replace(/\n{3,}/g, '\n\n');

    // Échapper le HTML d'abord
    let formatted = cleaned
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Code blocks avec langage ```lang\ncode```
    formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const langLabel = lang || 'code';
        return `<div class="code-block">
            <div class="code-header">
                <span class="code-lang">${langLabel}</span>
                <button class="code-copy-btn" onclick="copyCodeBlock(this)">Copier</button>
            </div>
            <pre><code>${code.trim()}</code></pre>
        </div>`;
    });

    // Code inline `code`
    formatted = formatted.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // Headers ### ## #
    formatted = formatted.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
    formatted = formatted.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
    formatted = formatted.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');

    // Blockquotes > text
    formatted = formatted.replace(/^&gt; (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');

    // Listes à puces - item
    formatted = formatted.replace(/^- (.+)$/gm, '<li class="md-li">$1</li>');
    formatted = formatted.replace(/(<li class="md-li">.*<\/li>\n?)+/g, '<ul class="md-ul">$&</ul>');

    // Listes numérotées 1. item
    formatted = formatted.replace(/^\d+\. (.+)$/gm, '<li class="md-oli">$1</li>');
    formatted = formatted.replace(/(<li class="md-oli">.*<\/li>\n?)+/g, '<ol class="md-ol">$&</ol>');

    // Barré ~~text~~
    formatted = formatted.replace(/~~([^~]+)~~/g, '<del>$1</del>');

    // Souligné __text__
    formatted = formatted.replace(/__([^_]+)__/g, '<u>$1</u>');

    // Gras **text**
    formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Italique *text* ou _text_
    formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    formatted = formatted.replace(/_([^_]+)_/g, '<em>$1</em>');

    // Liens [text](url)
    formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="md-link">$1</a>');

    // Ligne horizontale ---
    formatted = formatted.replace(/^---$/gm, '<hr class="md-hr">');

    // Sauts de ligne (mais pas dans les listes)
    formatted = formatted.replace(/\n/g, '<br>');

    // Nettoyer les <br> en trop dans les listes
    formatted = formatted.replace(/<\/li><br>/g, '</li>');
    formatted = formatted.replace(/<\/ul><br>/g, '</ul>');
    formatted = formatted.replace(/<\/ol><br>/g, '</ol>');
    formatted = formatted.replace(/<\/h[234]><br>/g, m => m.replace('<br>', ''));
    formatted = formatted.replace(/<\/blockquote><br>/g, '</blockquote>');
    formatted = formatted.replace(/<hr class="md-hr"><br>/g, '<hr class="md-hr">');

    return formatted;
}

function copyCodeBlock(btn) {
    const codeBlock = btn.closest('.code-block');
    const code = codeBlock.querySelector('code').textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = `${chatT('common.copied', 'Copié')}!`;
        setTimeout(() => btn.textContent = chatT('common.copy', 'Copier'), 2000);
    });
}

/**
 * ANCHORED SCROLL — Étape finale : Formatage + recalcul padding
 *
 * Applique le markdown final et ajoute les boutons d'action, ce qui
 * peut modifier la hauteur du contenu. updateChatPadding() est appelé
 * en fin de fonction pour resynchroniser le scroll max.
 */
function finalizeStreamingMessage(msgId, responseTime, tokenStatsData = null) {
    const bubble = document.getElementById(msgId);
    const container = document.getElementById(msgId + '-container');
    if (!bubble || !container) return;

    // Remove cursor et appliquer le formatage final
    bubble.classList.remove('streaming');

    // Utiliser le texte brut accumulé
    let rawText = streamingRawText || bubble.textContent || bubble.innerText;
    rawText = rawText.replace('|', '').trim();

    // Appliquer le formatage markdown final
    bubble.innerHTML = formatMarkdown(rawText);
    streamingRawText = ''; // Reset

    // Mettre à jour les stats de tokens globales si disponibles
    if (tokenStatsData) {
        tokenStats.lastRequestTokens = tokenStatsData.total_tokens || 0;
        tokenStats.promptTokens = tokenStatsData.prompt_tokens || 0;
        tokenStats.completionTokens = tokenStatsData.completion_tokens || 0;
        tokenStats.sessionTotal += tokenStatsData.total_tokens || 0;
        tokenStats.maxContextSize = tokenStatsData.context_size || userSettings.contextSize || 4096;

        // Mettre à jour l'affichage des tokens
        updateTokenDisplay();
    }

    // Add action buttons
    const timeDisplay = formatTimeDisplay(responseTime, 3000, 8000);

    // Afficher les tokens si disponibles
    let tokenDisplay = '';
    if (tokenStatsData && tokenStatsData.total_tokens) {
        tokenDisplay = `<span class="token-count" title="Prompt: ${tokenStatsData.prompt_tokens} | ${chatT('chat.responseLabel', 'Réponse')}: ${tokenStatsData.completion_tokens}">${tokenStatsData.total_tokens} tok</span>`;
    }

    const actionsHtml = `
        <div class="chat-actions">
            <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${chatT('common.copy', 'Copier')}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
            </button>
            <button class="chat-action-btn" onclick="speakText('${msgId}')" title="${chatT('common.readAloud', 'Lire')}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                    <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                </svg>
            </button>
            <div class="chat-actions-divider"></div>
            ${tokenDisplay}
            <div class="response-time">${timeDisplay}</div>
        </div>
    `;

    const aiResponse = container.querySelector('.ai-response');
    if (aiResponse) {
        aiResponse.insertAdjacentHTML('beforeend', actionsHtml);
    }

    currentStreamingMsgId = null;

    // ANCHORED SCROLL : recalculer le padding + scroll après le reformatage
    // (le markdown + les boutons d'action modifient la hauteur du contenu)
    updateChatPadding();
    scrollToBottom();
}

function addMessage(prompt, userImage, original, modified, generationTime = null, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null), totalTime = null) {
    removeSkeletonMessage(chatId);

    const messagesDiv = getChatMessages();
    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    const messageHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
                <img src="${userImage}" class="user-thumb">
            </div>
            <div class="ai-response">
                <div class="result-images">
                    <div class="result-image-container">
                        <div class="result-image-wrapper">
                            <img src="${original}" class="result-image" onclick="openModalFromPair(this, true)">
                            <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                        </div>
                        <div class="image-label" ${imageLabelAttr('original')}>${imageLabelT('original', 'Original')}</div>
                    </div>
                    <div class="result-image-container">
                        <div class="result-image-wrapper">
                            <img src="${modified}" class="result-image" onclick="openModalFromPair(this, false)">
                            <div class="image-actions">
                                <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                                <button class="edit-btn refine-btn" onclick="fixDetailsImage(this.closest('.result-image-wrapper').querySelector('img').src)" title="Fix Details">${fixDetailsIcon}</button>
                            </div>
                        </div>
                        <div class="image-label" ${imageLabelAttr('modified')}>${imageLabelT('modified', 'Modifié')}</div>
                    </div>
                </div>
                ${buildImageActionsBar(prompt, generationTime, null, totalTime)}
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom(true);
    saveCurrentChat(prompt, '[Image generee]', messageHtml, chatId);

    setTimeout(() => {
        const lastAiResponse = document.querySelector('.message:last-child .ai-response');
        if (lastAiResponse) {
            fetchAndShowSuggestions(modified, lastAiResponse, original);
        }
    }, 100);
}

/**
 * Affiche un message pour le mode EDIT avec le masque pour vérification
 * @param {string} prompt - Le prompt utilisé
 * @param {string} original - L'image originale
 * @param {string} modified - L'image modifiée
 * @param {string} mask - Le masque utilisé (optionnel)
 * @param {number} generationTime - Temps de génération (optionnel)
 */
function addMessageEdit(prompt, original, modified, mask = null, generationTime = null, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null), totalTime = null) {
    removeSkeletonMessage(chatId);

    const messagesDiv = getChatMessages();
    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    // Si mask fourni, afficher 3 images (Original, Masque, Modifié)
    let imagesHtml;
    if (mask) {
        imagesHtml = `
            <div class="result-images result-images-3">
                <div class="result-image-container">
                    <div class="result-image-wrapper">
                        <img src="${original}" class="result-image" onclick="openModalFromPair(this, true)">
                        <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                    </div>
                    <div class="image-label" ${imageLabelAttr('original')}>${imageLabelT('original', 'Original')}</div>
                </div>
                <div class="result-image-container mask-preview">
                    <div class="result-image-wrapper">
                        <img src="${mask}" class="result-image" onclick="openModalSingle(this.src)">
                    </div>
                    <div class="image-label" ${imageLabelAttr('mask')}>${imageLabelT('mask', 'Masque')}</div>
                </div>
                <div class="result-image-container">
                    <div class="result-image-wrapper">
                        <img src="${modified}" class="result-image" onclick="openModalFromPair(this, false)">
                        <div class="image-actions">
                            <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                            <button class="edit-btn refine-btn" onclick="fixDetailsImage(this.closest('.result-image-wrapper').querySelector('img').src)" title="Fix Details">${fixDetailsIcon}</button>
                        </div>
                    </div>
                    <div class="image-label" ${imageLabelAttr('modified')}>${imageLabelT('modified', 'Modifié')}</div>
                </div>
            </div>
        `;
    } else {
        imagesHtml = `
            <div class="result-images">
                <div class="result-image-container">
                    <div class="result-image-wrapper">
                        <img src="${original}" class="result-image" onclick="openModalFromPair(this, true)">
                        <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                    </div>
                    <div class="image-label" ${imageLabelAttr('original')}>${imageLabelT('original', 'Original')}</div>
                </div>
                <div class="result-image-container">
                    <div class="result-image-wrapper">
                        <img src="${modified}" class="result-image" onclick="openModalFromPair(this, false)">
                        <div class="image-actions">
                            <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                            <button class="edit-btn refine-btn" onclick="fixDetailsImage(this.closest('.result-image-wrapper').querySelector('img').src)" title="Fix Details">${fixDetailsIcon}</button>
                        </div>
                    </div>
                    <div class="image-label" ${imageLabelAttr('modified')}>${imageLabelT('modified', 'Modifié')}</div>
                </div>
            </div>
        `;
    }

    const messageHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
                <img src="${original}" class="user-thumb">
            </div>
            <div class="ai-response">
                ${imagesHtml}
                ${buildImageActionsBar(prompt, generationTime, null, totalTime)}
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom(true);
    saveCurrentChat(prompt, '[Image editee]', messageHtml, chatId);

    // Fetch suggestions pour l'image modifiée
    setTimeout(() => {
        const lastAiResponse = document.querySelector('.message:last-child .ai-response');
        if (lastAiResponse) {
            fetchAndShowSuggestions(modified, lastAiResponse, original);
        }
    }, 100);
}

function addMessageTxt2Img(prompt, generated, generationTime = null, seed = null, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null), totalTime = null) {
    removeSkeletonMessage(chatId);

    const messagesDiv = getChatMessages();
    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    const messageHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
            </div>
            <div class="ai-response">
                <div class="result-images">
                    <div class="result-image-container">
                        <div class="result-image-wrapper">
                            <img src="${generated}" class="result-image" onclick="openModalSingle(this.src)">
                            <div class="image-actions">
                                <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                                <button class="edit-btn refine-btn" onclick="fixDetailsImage(this.closest('.result-image-wrapper').querySelector('img').src)" title="Fix Details">${fixDetailsIcon}</button>
                            </div>
                        </div>
                        <div class="image-label" ${imageLabelAttr('generated')}>${imageLabelT('generated', 'Généré')}</div>
                    </div>
                </div>
                ${buildImageActionsBar(prompt, generationTime, seed, totalTime)}
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom(true);
    saveCurrentChat(prompt, '[Image generee]', messageHtml, chatId);

    // Fetch suggestions pour l'image générée
    setTimeout(() => {
        const lastAiResponse = document.querySelector('.message:last-child .ai-response');
        if (lastAiResponse) {
            fetchAndShowSuggestions(generated, lastAiResponse);
        }
    }, 100);

    return messageHtml;
}

// Stocke le dernier contexte vidéo pour la continuation
let _lastVideoContext = { prompt: '', sourceImage: null, canContinue: false };

function addMessageVideo(videoBase64, generationTime = null, sourceImage = null, canContinue = false, modelName = null, chatId = (typeof currentChatId !== 'undefined' ? currentChatId : null)) {
    removeSkeletonMessage(chatId);

    const messagesDiv = getChatMessages();
    const downloadIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`;
    const playIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>`;

    const timeDisplay = generationTime ? `<div class="generation-time">${formatGenTimeDisplay(generationTime)}</div>` : '';
    const label = modelName || imageLabelT('video', 'Vidéo');

    const sourceHtml = sourceImage ? `
        <div class="result-image-container">
            <div class="result-image-wrapper">
                <img src="${sourceImage}" class="result-image" onclick="openModalSingle('${sourceImage}')">
            </div>
            <div class="image-label" ${imageLabelAttr('source')}>${imageLabelT('source', 'Source')}</div>
        </div>
    ` : '';

    const continueBtn = canContinue ? `
        <button class="edit-btn video-continue-btn" onclick="continueLastVideo()" title="Continuer la vidéo" style="display:flex;align-items:center;gap:4px;padding:6px 12px;margin-top:6px;background:rgba(139,92,246,0.15);border:1px solid rgba(139,92,246,0.3);border-radius:8px;cursor:pointer;color:#a78bfa;">
            ${playIcon} Continuer
        </button>
    ` : '';

    const messageHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">🎬 Génération vidéo</div>
            </div>
            <div class="ai-response">
                <div class="result-images">
                    ${sourceHtml}
                    <div class="result-image-container video-container">
                        <video controls autoplay loop muted class="result-video" style="max-width:100%;border-radius:8px;">
                            <source src="data:video/mp4;base64,${videoBase64}" type="video/mp4">
                        </video>
                        <div class="video-actions" style="position:absolute;top:8px;right:8px;display:flex;gap:4px;">
                            <a href="data:video/mp4;base64,${videoBase64}" download="video.mp4" class="edit-btn" title="Télécharger">${downloadIcon}</a>
                        </div>
                        <div class="image-label">${label} ${timeDisplay}</div>
                        ${continueBtn}
                    </div>
                </div>
            </div>
        </div>
    `;

    // Sauvegarder le contexte pour continuation
    _lastVideoContext.canContinue = canContinue;
    _lastVideoContext.sourceImage = sourceImage;

    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom();

    saveCurrentChat('🎬 Génération vidéo', '[Vidéo générée]', messageHtml, chatId);

    return messageHtml;
}

async function continueLastVideo() {
    if (!_lastVideoContext.canContinue) return;

        const videoModel = userSettings.videoModel || 'svd';
    const videoDefaults = getVideoModelDefaults(videoModel);

    isGenerating = true;
    currentGenerationMode = 'video';
    currentGenerationId = typeof generateUUID === 'function' ? generateUUID() : Date.now().toString();
    if (typeof setSendButtonsMode === 'function') {
        setSendButtonsMode(true);
    } else if (typeof updateSendButtonState === 'function') {
        updateSendButtonState('home');
        updateSendButtonState('chat');
    }

    addSkeletonMessage(`🎬 Continuation ${videoDefaults.name}...`, null, true);
    scrollToBottom();

    startVideoProgressPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.generateVideo({
            video_model: videoModel,
            prompt: _lastVideoContext.prompt,
            continue: true,
            target_frames: videoDefaults.frames,
            num_steps: videoDefaults.steps,
            fps: videoDefaults.fps,
            add_audio: userSettings.videoAudio === true,
            face_restore: userSettings.faceRestore || 'off',
            chatId: typeof currentChatId !== 'undefined' ? currentChatId : null,
            quality: userSettings.videoQuality || '720p',
            refine_passes: parseInt(userSettings.videoRefine) || 0,
            allow_experimental_video: userSettings.showAdvancedVideoModels === true
        });

        stopVideoProgressPolling();
        const data = result.data;
        const generationTime = (Date.now() - startTime) / 1000;

        if (data?.success && data.video) {
            addMessageVideo(data.video, generationTime, null, data.canContinue, videoDefaults.name);
        } else {
            removeSkeletonMessage();
        }
    } catch (e) {
        stopVideoProgressPolling();
        removeSkeletonMessage();
        console.error('[VIDEO] Continue error:', e);
    } finally {
        isGenerating = false;
        currentGenerationId = null;
        currentGenerationMode = null;
        if (typeof setSendButtonsMode === 'function') {
            setSendButtonsMode(false);
        } else if (typeof updateSendButtonState === 'function') {
            updateSendButtonState('home');
            updateSendButtonState('chat');
        }
    }
}

function addChatMessageWithGenerated(prompt, response, generated, responseTime = null) {
    removeSkeletonMessage();
    const messagesDiv = getChatMessages();
    const msgId = Date.now();
    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    const timeDisplay = formatTimeDisplay(responseTime, 5000, 15000);

    const messageHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
            </div>
            <div class="ai-response">
                <div class="chat-bubble" id="chat-${msgId}">${response}</div>
                <div class="result-images">
                    <div class="result-image-container">
                        <div class="result-image-wrapper">
                            <img src="${generated}" class="result-image" onclick="openModalSingle(this.src)">
                            <div class="image-actions">
                                <button class="edit-btn" onclick="openEditModal(this.closest('.result-image-wrapper').querySelector('img').src)" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                                <button class="edit-btn refine-btn" onclick="fixDetailsImage(this.closest('.result-image-wrapper').querySelector('img').src)" title="Fix Details">${fixDetailsIcon}</button>
                            </div>
                        </div>
                        <div class="image-label" ${imageLabelAttr('generated')}>${imageLabelT('generated', 'Généré')}</div>
                    </div>
                </div>
                <div class="chat-actions">
                    <button class="chat-action-btn" onclick="regenerateChat('${prompt.replace(/'/g, "\\'")}')" title="${chatT('common.regenerate', 'Regénérer')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M1 4v6h6M23 20v-6h-6"/>
                            <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                        </svg>
                    </button>
                    <button class="chat-action-btn" onclick="speakText('chat-${msgId}')" title="${chatT('common.readAloud', 'Lire')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                            <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                        </svg>
                    </button>
                    <button class="chat-action-btn" onclick="copyText('chat-${msgId}')" title="${chatT('common.copy', 'Copier')}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                        </svg>
                    </button>
                    <div class="chat-actions-divider"></div>
                    <div class="response-time">${timeDisplay}</div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom(true);

    // Fetch suggestions pour l'image générée
    setTimeout(() => {
        const lastAiResponse = document.querySelector('.message:last-child .ai-response');
        if (lastAiResponse) {
            fetchAndShowSuggestions(generated, lastAiResponse);
        }
    }, 100);

    return messageHtml;
}

function addChatMessageWithPendingImage(prompt, response, genPrompt) {
    const messagesDiv = getChatMessages();
    const msgId = Date.now();

    const messageHtml = `
        <div class="message" id="pending-msg-${msgId}" data-chat-id="${currentChatId}" data-started-at="${Date.now()}">
            <div class="user-message">
                <div class="user-bubble">${prompt}</div>
            </div>
            <div class="ai-response">
                <div class="chat-bubble" id="chat-${msgId}">${response}</div>
                <div class="result-images pending-generation" id="pending-images-${msgId}">
                    <div class="result-image-container">
                        <div class="skeleton skeleton-image" id="pending-skeleton-${msgId}"></div>
                        <div class="image-label" ${imageLabelAttr('generationInProgress')}>${imageLabelT('generationInProgress', 'Génération en cours...')}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', messageHtml);
    scrollToBottom();

    window.pendingMsgId = msgId;
}

function replacePendingImageWithReal(imageSrc, genTime) {
    const msgId = window.pendingMsgId;
    if (!msgId) return;

    const imagesContainer = document.getElementById(`pending-images-${msgId}`);
    if (!imagesContainer) return;

    const editIcon = ICON_EDIT;
    const fixDetailsIcon = ICON_FIX_DETAILS;

    const seconds = (genTime / 1000).toFixed(1);

    imagesContainer.innerHTML = `
        <div class="result-image-container">
            <div class="result-image-wrapper">
                <img src="${imageSrc}" class="result-image" onclick="openModalSingle('${imageSrc}')">
                <div class="image-actions">
                    <button class="edit-btn" onclick="openEditModal('${imageSrc}')" title="${chatT('common.edit', 'Éditer')}">${editIcon}</button>
                    <button class="edit-btn refine-btn" onclick="fixDetailsImage('${imageSrc}')" title="Fix Details">${fixDetailsIcon}</button>
                </div>
            </div>
            <div class="image-label">${imageLabelT('generatedWithTime', 'Généré ({seconds}s)', { seconds })}</div>
        </div>
    `;

    modifiedImage = imageSrc;
    window.pendingMsgId = null;

    // Fetch suggestions pour l'image générée
    setTimeout(() => {
        const msgContainer = document.getElementById(`pending-msg-${msgId}`);
        if (msgContainer) {
            const aiResponse = msgContainer.querySelector('.ai-response');
            if (aiResponse) {
                fetchAndShowSuggestions(imageSrc, aiResponse);
            }
        }
    }, 100);
}

function replacePendingImageWithError(errorMsg) {
    const msgId = window.pendingMsgId;
    if (!msgId) return;

    const imagesContainer = document.getElementById(`pending-images-${msgId}`);
    if (!imagesContainer) return;

    imagesContainer.innerHTML = `
        <div class="result-image-container">
            <div class="chat-bubble" style="background: #2a1a1a; border-color: #ef4444; color: #ef4444;">
                Erreur de generation: ${errorMsg}
            </div>
        </div>
    `;

    window.pendingMsgId = null;
}


// ===== SUGGESTIONS INTELLIGENTES (style Claude) =====

let suggestionsFetching = false;  // Flag pour éviter les appels multiples
let lastSuggestionsImage = null;  // Dernière image pour laquelle on a fetch

// Stockage global des suggestions pour éviter les problèmes d'encodage dans onclick
let pendingSuggestions = [];

/**
 * Récupère et affiche les suggestions pour une image
 * @param {string} imageSrc - Image principale (modifiée)
 * @param {HTMLElement} containerElement - Conteneur où afficher
 * @param {string} originalSrc - Image originale (optionnel, pour choix original/modifié)
 */
async function fetchAndShowSuggestions(imageSrc, containerElement, originalSrc = null) {
    if (!imageSrc || !containerElement) return;

    // Éviter les appels multiples pour la même image
    if (suggestionsFetching || lastSuggestionsImage === imageSrc) return;
    suggestionsFetching = true;
    lastSuggestionsImage = imageSrc;

    // Nettoyer les anciennes suggestions stockées (limite mémoire)
    if (pendingSuggestions.length > 50) {
        pendingSuggestions = pendingSuggestions.slice(-20);
    }

    // Créer le conteneur de suggestions avec loading
    const suggestionsDiv = document.createElement('div');
    suggestionsDiv.className = 'suggestions-container';
    suggestionsDiv.innerHTML = `
        <div class="suggestions-loading">
            <div class="spinner"></div>
            <span>Analyse...</span>
        </div>
    `;
    containerElement.appendChild(suggestionsDiv);

    try {
        const result = await apiChat.getSuggestions(imageSrc);
        const data = result.data;

        if (data?.success && data.suggestions) {
            showSuggestions(data.suggestions, suggestionsDiv, imageSrc, originalSrc);
        } else {
            suggestionsDiv.remove();
        }
    } catch (e) {
        console.log('Suggestions error:', e);
        suggestionsDiv.remove();
    } finally {
        suggestionsFetching = false;
    }
}

/**
 * Affiche les suggestions dans le conteneur
 * @param {Array} suggestions - Liste des suggestions
 * @param {HTMLElement} container - Conteneur
 * @param {string} imageSrc - Image modifiée
 * @param {string} originalSrc - Image originale (optionnel)
 */
function showSuggestions(suggestions, container, imageSrc, originalSrc = null) {
    if (!suggestions || suggestions.length === 0) {
        container.remove();
        return;
    }

    const hasOriginal = originalSrc && originalSrc !== imageSrc;

    // Stocker les données dans le tableau global (évite les problèmes d'encodage)
    const baseIndex = pendingSuggestions.length;
    suggestions.forEach((s, i) => {
        pendingSuggestions.push({
            prompt: s.prompt,
            modifiedImage: imageSrc,
            originalImage: originalSrc
        });
    });

    container.innerHTML = suggestions.map((s, index) => {
        const dataIndex = baseIndex + index;
        const escapedLabel = s.label.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const originalLabel = imageLabelT('original', 'Original');
        const modifiedLabel = imageLabelT('modified', 'Modifié');
        const originalTitle = imageLabelT('applyOriginal', 'Appliquer sur l’original');
        const modifiedTitle = imageLabelT('applyModified', 'Appliquer sur le modifié');

        // Boutons Original/Modifié si on a les deux images
        const targetButtons = hasOriginal ? `
            <div class="suggestion-targets">
                <button class="suggestion-target-btn" onclick="event.stopPropagation(); applySuggestionByIndex(${dataIndex}, true)" title="${originalTitle}">${originalLabel}</button>
                <button class="suggestion-target-btn" onclick="event.stopPropagation(); applySuggestionByIndex(${dataIndex}, false)" title="${modifiedTitle}">${modifiedLabel}</button>
            </div>
        ` : '';

        // Si on a les boutons Original/Modifié, seuls ces boutons sont cliquables (pas le texte)
        const itemClickHandler = hasOriginal ? '' : `onclick="applySuggestionByIndex(${dataIndex}, false)"`;

        return `
            <div class="suggestion-item" ${itemClickHandler}>
                <svg class="suggestion-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="15 10 20 15 15 20"></polyline>
                    <path d="M4 4v7a4 4 0 0 0 4 4h12"></path>
                </svg>
                <span class="suggestion-label">${escapedLabel}</span>
                ${targetButtons}
            </div>
        `;
    }).join('');
}

/**
 * Applique une suggestion par son index dans pendingSuggestions
 * @param {number} index - Index dans pendingSuggestions
 * @param {boolean} useOriginal - true pour utiliser l'image originale, false pour la modifiée
 */
async function applySuggestionByIndex(index, useOriginal = false) {
    const data = pendingSuggestions[index];
    if (!data) {
        console.error('[SUGGESTIONS] Index invalide:', index);
        return;
    }

    const prompt = data.prompt;
    const imageSrc = useOriginal && data.originalImage ? data.originalImage : data.modifiedImage;

    console.log('[SUGGESTIONS] Applying:', { prompt: prompt.substring(0, 50), useOriginal, hasImage: !!imageSrc });

    // Désactiver les suggestions cliquées
    document.querySelectorAll('.suggestion-item').forEach(el => {
        el.style.pointerEvents = 'none';
        el.style.opacity = '0.5';
    });

    // IMPORTANT: Ne pas créer de nouveau chat si des messages existent déjà
    const messagesDiv = getChatMessages();
    const hasMessages = messagesDiv && messagesDiv.children.length > 0;

    if (!currentChatId && !hasMessages) {
        // Seulement créer si vraiment aucun chat n'existe
        await createNewChat();
    }

    showChat();

    // Ajouter le skeleton
    addSkeletonMessage(prompt.substring(0, 50) + '...', imageSrc, true);

    // Activer le mode génération
    isGenerating = true;
    currentGenerationMode = 'image';
    currentController = new AbortController();
    if (typeof setSendButtonsMode === 'function') setSendButtonsMode(true);
    if (typeof startPreviewPolling === 'function') startPreviewPolling();

    const startTime = Date.now();

    try {
        const result = await apiGeneration.generate({
            prompt: prompt,
            image: imageSrc,
            model: typeof getCurrentImageModel === 'function' ? getCurrentImageModel() : 'epiCRealism XL (Moyen)',
            enhance: false,
            steps: userSettings.steps,
        }, currentController.signal);

        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();

        const data = result.data;
        const genTime = Math.round((Date.now() - startTime) / 1000);

        if (data?.success && data.modified) {
            const newImage = 'data:image/png;base64,' + data.modified;
            addMessage(prompt.substring(0, 50) + '...', imageSrc, imageSrc, newImage, genTime);
            modifiedImage = newImage;

            // Récupérer les nouvelles suggestions pour l'image générée
            // Passer l'image source comme original pour le choix Orig/Mod
            const lastAiResponse = document.querySelector('.message:last-child .ai-response');
            if (lastAiResponse) {
                fetchAndShowSuggestions(newImage, lastAiResponse, imageSrc);
            }
        } else {
            if (typeof showGenerationError === 'function') {
                showGenerationError(result, chatT('app.generationFailed', 'Génération échouée'));
            } else {
                removeSkeletonMessage();
                await JoyDialog.alert(chatT('common.errorWithMessage', 'Erreur : {error}', {
                    error: data?.error || result.error || chatT('app.generationFailed', 'Génération échouée'),
                }), { variant: 'danger' });
            }
        }
    } catch (e) {
        if (typeof stopPreviewPolling === 'function') stopPreviewPolling();
        removeSkeletonMessage();
        if (e.name !== 'AbortError') {
            await JoyDialog.alert(chatT('common.errorWithMessage', 'Erreur : {error}', { error: e.message }), { variant: 'danger' });
        }
    } finally {
        isGenerating = false;
        currentController = null;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);
        if (typeof refocusChatInput === 'function') refocusChatInput();
        // Traiter le prochain élément de la queue
        setTimeout(() => {
            if (typeof processNextInQueue === 'function') {
                processNextInQueue();
            }
        }, 100);
    }
}

// ===== TERMINAL MODE HELPERS =====

/**
 * Ajoute un message AI simple au chat (pour le mode terminal)
 */
function addAiMessageToChat(text) {
    const messagesDiv = getChatMessages();
    const formattedText = formatMarkdown(text);

    const msgHtml = `
        <div class="message">
            <div class="ai-response">
                <div class="chat-bubble">${formattedText}</div>
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', msgHtml);
    scrollToBottom();
}

/**
 * Ajoute une ligne de texte style terminal (sans bubble)
 * @param {string} text - Texte à afficher
 * @param {string} type - Type: 'system', 'success', 'error', 'warning', 'info', 'dim', 'code', 'prompt', 'user', 'blank'
 */
function addTerminalLine(text, type = 'system') {
    const messagesDiv = getChatMessages();
    if (!messagesDiv) return;

    // Mapping type → icone Lucide
    const typeIcons = {
        'user': 'chevron-right',
        'error': 'x',
        'success': 'check',
        'warning': 'alert-triangle',
        'info': 'info',
        'prompt': 'arrow-right',
        'tool-call': 'terminal'
    };

    let className = `terminal-line terminal-${type}`;
    const icon = typeIcons[type];

    if (type === 'blank') {
        messagesDiv.insertAdjacentHTML('beforeend', `<div class="${className}">&nbsp;</div>`);
        scrollToBottom();
        return;
    }

    const escapedText = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');

    if (icon) {
        const lineHtml = `<div class="${className}"><i data-lucide="${icon}" class="terminal-icon"></i>${escapedText}</div>`;
        messagesDiv.insertAdjacentHTML('beforeend', lineHtml);
        if (window.lucide) lucide.createIcons();
    } else {
        messagesDiv.insertAdjacentHTML('beforeend', `<div class="${className}">${escapedText}</div>`);
    }
    scrollToBottom();
}

// ===== CLAUDE CODE STYLE FORMATTING =====
// Formatage des tool calls comme Claude Code: ● Action(path) avec ⎿ résultat

/**
 * Affiche un tool call style Claude Code
 * Ex: ● Read(src/app.js)
 * @param {string} action - Action (Read, Write, Edit, Bash, etc.)
 * @param {string} target - Cible (fichier, commande, etc.)
 * @returns {HTMLElement} L'élément créé
 */
function addToolCall(action, target) {
    console.log(`%c[CHAT] addToolCall appelé: ${action}(${target})`, 'color: #3b82f6; font-weight: bold;');

    const messagesDiv = getChatMessages();
    if (!messagesDiv) {
        console.error('[CHAT] chat-messages not found!');
        return null;
    }

    const el = document.createElement('div');
    el.className = 'tool-call-line';

    // Formatter l'action: read_file -> Read, write_file -> Write, etc.
    const formatAction = (a) => {
        const map = {
            'read_file': 'Read',
            'write_file': 'Write',
            'edit_file': 'Edit',
            'delete_file': 'Delete',
            'list_files': 'List',
            'search': 'Search',
            'glob': 'Glob',
            'bash': 'Bash',
            'open_workspace': 'Open',
            'explore': 'Explore',
            'create_plan': 'Plan',
            'update_plan': 'UpdatePlan'
        };
        return map[a] || a.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
    };

    // Tronquer le chemin si trop long
    const displayTarget = target && target.length > 60
        ? '...' + target.slice(-57)
        : (target || '');

    const displayAction = formatAction(action);
    el.innerHTML = `<span class="tool-bullet">●</span> <span class="tool-action">${displayAction}</span>(<span class="tool-target">${escapeHtml(displayTarget)}</span>)`;
    messagesDiv.appendChild(el);
    scrollToBottom(document.body.classList.contains('terminal-mode'));
    return el;
}

/**
 * Affiche un résultat de tool call style Claude Code
 * Ex: ⎿ 234 lines
 * @param {string} text - Texte du résultat
 * @param {string} type - 'success', 'error', 'info'
 * @returns {HTMLElement} L'élément créé
 */
function addToolResult(text, type = 'success') {
    console.log(`%c[CHAT] addToolResult appelé: ${text} (${type})`, 'color: #22c55e; font-weight: bold;');

    const messagesDiv = getChatMessages();
    if (!messagesDiv) {
        console.error('[CHAT] chat-messages not found!');
        return null;
    }

    const el = document.createElement('div');
    el.className = `tool-result-line tool-result-${type}`;
    el.innerHTML = `<span class="tool-corner">⎿</span> ${escapeHtml(text)}`;
    messagesDiv.appendChild(el);
    scrollToBottom(document.body.classList.contains('terminal-mode'));
    return el;
}

// escapeHtml() défini dans utils.js (chargé avant chat.js)

/**
 * Ajoute une ligne terminal avec une icone Lucide
 * @param {string} iconName - Nom de l'icone Lucide (ex: 'folder', 'file-text')
 * @param {string} text - Texte à afficher
 * @param {string} type - Type de ligne (system, success, error, etc.)
 * @param {boolean} spin - Si true, l'icône tourne (pour loader)
 * @returns {HTMLElement} L'élément créé
 */
function addTerminalLineWithIcon(iconName, text, type = 'system', spin = false) {
    const messagesDiv = getChatMessages();
    if (!messagesDiv) return null;

    const lineEl = document.createElement('div');
    lineEl.className = `terminal-line terminal-${type}`;

    const escapedText = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const spinClass = spin ? ' spin' : '';
    lineEl.innerHTML = `<i data-lucide="${iconName}" class="terminal-icon${spinClass}"></i> ${escapedText}`;

    messagesDiv.appendChild(lineEl);

    // Initialiser l'icone Lucide
    if (window.lucide) lucide.createIcons();

    scrollToBottom(document.body.classList.contains('terminal-mode'));
    return lineEl;
}

/**
 * Variable pour stocker les éléments de loading terminal
 */
let terminalLoadingElements = [];

/**
 * Affiche un message de loading animé qui peut être supprimé
 * @param {string} text - Texte à afficher
 * @returns {HTMLElement} L'élément créé (pour le supprimer plus tard)
 */
function showTerminalLoading(text) {
    const el = addTerminalLineWithIcon('loader-2', text, 'system', true);
    if (el) {
        el.classList.add('terminal-loading-msg');
        terminalLoadingElements.push(el);
    }
    return el;
}

/**
 * Supprime un message de loading avec animation de slide-up
 * @param {HTMLElement} element - L'élément à supprimer
 * @param {string} successText - Texte de succès à afficher brièvement (optionnel)
 * @returns {Promise} Résolue quand l'animation est terminée
 */
function hideTerminalLoading(element, successText = null) {
    return new Promise((resolve) => {
        if (!element) {
            resolve();
            return;
        }

        // Si on veut afficher un message de succès d'abord
        if (successText) {
            // Transformer en message de succès
            element.className = 'terminal-line terminal-success';
            element.innerHTML = `<i data-lucide="check" class="terminal-icon"></i> ${successText}`;
            if (window.lucide) lucide.createIcons();

            // Attendre un peu puis animer la disparition
            setTimeout(() => {
                animateOut(element, resolve);
            }, 800);
        } else {
            // Disparition directe
            animateOut(element, resolve);
        }
    });

    function animateOut(el, done) {
        el.classList.add('terminal-fade-out');
        el.addEventListener('animationend', () => {
            el.remove();
            // Retirer de la liste
            const idx = terminalLoadingElements.indexOf(el);
            if (idx > -1) terminalLoadingElements.splice(idx, 1);
            done();
        }, { once: true });
    }
}

/**
 * Supprime tous les messages de loading en cours
 */
function hideAllTerminalLoading() {
    const promises = terminalLoadingElements.map(el => hideTerminalLoading(el));
    return Promise.all(promises);
}

/**
 * Ajoute un message utilisateur style terminal
 */
function addTerminalUserLine(text) {
    const messagesDiv = getChatMessages();
    if (!messagesDiv) return;

    const messageEl = document.createElement('div');
    messageEl.className = 'message terminal-chat-message';
    messageEl.innerHTML = `
        <div class="user-message">
            <div class="user-bubble">${escapeHtml(text)}</div>
        </div>
    `;
    messagesDiv.appendChild(messageEl);
    scrollToBottom();
}

/**
 * Ajoute le skeleton chat seulement si on n'est PAS en mode terminal
 * En mode terminal, on utilise juste le message utilisateur + Thinking animation
 */
function addChatSkeletonMessageSmart(prompt) {
    if (terminalMode) {
        // En mode terminal: juste le message utilisateur style terminal
        addTerminalUserLine(prompt);
    } else {
        // Mode normal: skeleton classique
        addChatSkeletonMessage(prompt);
    }
}

/**
 * Ajoute un message utilisateur simple au chat (pour le mode terminal)
 */
function addUserMessageToChat(text) {
    const messagesDiv = getChatMessages();
    const escapedText = text.replace(/</g, '&lt;').replace(/>/g, '&gt;');

    const msgHtml = `
        <div class="message">
            <div class="user-message">
                <div class="user-bubble">${escapedText}</div>
            </div>
        </div>
    `;

    messagesDiv.insertAdjacentHTML('beforeend', msgHtml);
    scrollToBottom(true);
}
