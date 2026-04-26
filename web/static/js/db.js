// ===== DB - IndexedDB (Memories + Conversation persistence) =====

const CONVERSATIONS_STORE = 'conversations';
const PROJECTS_STORE = 'projects';
let chatRecordsCache = [];
let chatRecordsReady = false;
let projectRecordsCache = [];
let projectRecordsReady = false;
let runtimeJobsCache = [];
let runtimeJobsPollTimer = null;
let runtimeJobsHydrated = false;
const runtimeJobsCancelRequests = new Set();

const RUNTIME_JOB_DONE_STATES = new Set(['done', 'error', 'cancelled']);
const CHAT_PENDING_VISUAL_STATE_RE = /(?:image|video|skeleton)-skeleton-message|user-pending-msg|streaming/;

function chatRecordHasPendingVisuals(recordOrHtml) {
    const html = typeof recordOrHtml === 'string'
        ? recordOrHtml
        : (recordOrHtml?.html || '');
    return CHAT_PENDING_VISUAL_STATE_RE.test(html || '');
}

function hasLocalPendingGenerationForChat(chatId) {
    const targetChatId = chatId ? String(chatId) : '';
    const activeGenerationChatId = typeof currentGenerationChatId !== 'undefined' && currentGenerationChatId
        ? String(currentGenerationChatId)
        : '';
    return Boolean(
        typeof isGenerating !== 'undefined'
        && isGenerating
        && targetChatId
        && activeGenerationChatId
        && activeGenerationChatId === targetChatId
    );
}

function shouldShowChatAsRunning(record) {
    const chatId = record?.id ? String(record.id) : '';
    if (!chatId) return false;
    if (typeof hasActiveRuntimeJobForChat === 'function' && hasActiveRuntimeJobForChat(chatId)) return true;
    if (hasLocalPendingGenerationForChat(chatId)) return true;
    return !runtimeJobsHydrated && chatRecordHasPendingVisuals(record);
}

function shouldSanitizePersistedChatHtml(chatId) {
    return Boolean(
        runtimeJobsHydrated
        && chatId
        && !hasActiveRuntimeJobForChat(chatId)
        && !hasLocalPendingGenerationForChat(chatId)
    );
}

function cleanupStalePendingUiForActiveChat() {
    if (!shouldSanitizePersistedChatHtml(currentChatId)) return;
    if (typeof sanitizeChatTranscriptHtml !== 'function') return;

    const messagesDiv = getMessagesDiv();
    const rawHtml = messagesDiv?.innerHTML || '';
    if (!chatRecordHasPendingVisuals(rawHtml)) return;

    const cleanHtml = sanitizeChatTranscriptHtml(rawHtml);
    if (cleanHtml === rawHtml) return;

    if (messagesDiv) {
        messagesDiv.innerHTML = cleanHtml;
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [messagesDiv] });
        if (typeof updateChatPadding === 'function') updateChatPadding();
    }

    const cacheIndex = chatRecordsCache.findIndex(record => record.id === currentChatId);
    if (cacheIndex >= 0) {
        chatRecordsCache.splice(cacheIndex, 1, {
            ...chatRecordsCache[cacheIndex],
            html: cleanHtml,
        });
    }

    getChatRecord(currentChatId).then(record => {
        if (!record) return;
        return putChatRecord({ ...record, html: cleanHtml });
    }).catch(e => console.warn('[CHAT] Active stale pending cleanup failed:', e));
}

function requestToPromise(request) {
    return new Promise((resolve, reject) => {
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

function txDone(tx) {
    return new Promise((resolve, reject) => {
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error || new Error('Transaction aborted'));
    });
}

function makeChatId() {
    return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function makeProjectId() {
    return `project-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function cleanChatTitle(text) {
    const fallback = apiT('chat.newConversation', 'Nouvelle conversation');
    const normalized = (text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) return fallback;
    return normalized.length > 44 ? `${normalized.slice(0, 44).trim()}…` : normalized;
}

function cleanProjectName(text) {
    const fallback = apiT('projects.untitled', 'Projet sans nom');
    const normalized = (text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) return fallback;
    return normalized.length > 56 ? `${normalized.slice(0, 56).trim()}…` : normalized;
}

function getCurrentChatHtml() {
    if (typeof getChatHtmlWithoutSkeleton === 'function') {
        return getChatHtmlWithoutSkeleton();
    }
    const messagesDiv = document.getElementById('chat-messages');
    return messagesDiv ? messagesDiv.innerHTML : '';
}

function getMessagesDiv() {
    return document.getElementById('chat-messages');
}

function baseChatRecord(id = makeChatId()) {
    const now = Date.now();
    return {
        id,
        title: apiT('chat.newConversation', 'Nouvelle conversation'),
        mode: 'chat',
        workspace: null,
        projectId: null,
        pinned: false,
        lastVisualReference: null,
        messages: [],
        html: '',
        createdAt: now,
        updatedAt: now,
        archived: false
    };
}

function baseProjectRecord(id = makeProjectId()) {
    const now = Date.now();
    return {
        id,
        name: apiT('projects.untitled', 'Projet sans nom'),
        description: '',
        sourceIds: [],
        createdAt: now,
        updatedAt: now,
        expanded: true,
        archived: false
    };
}

function updateChatCache(record) {
    chatRecordsCache = chatRecordsCache.filter(item => item.id !== record.id);
    if (!record.archived) chatRecordsCache.unshift(record);
    chatRecordsCache.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

function updateProjectCache(record) {
    projectRecordsCache = projectRecordsCache.filter(item => item.id !== record.id);
    if (!record.archived) projectRecordsCache.unshift(record);
    projectRecordsCache.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

// Initialiser IndexedDB (memories + settings + conversations)
function initCacheDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            cacheDB = request.result;
            resolve(cacheDB);
        };

        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            const tx = e.target.transaction;

            // Old experimental stores are intentionally removed, but conversations
            // are now first-class state and must survive future migrations.
            if (db.objectStoreNames.contains('chats')) db.deleteObjectStore('chats');
            if (db.objectStoreNames.contains('queue')) db.deleteObjectStore('queue');

            let convStore;
            if (!db.objectStoreNames.contains(CONVERSATIONS_STORE)) {
                convStore = db.createObjectStore(CONVERSATIONS_STORE, { keyPath: 'id' });
            } else {
                convStore = tx.objectStore(CONVERSATIONS_STORE);
            }
            if (!convStore.indexNames.contains('updatedAt')) {
                convStore.createIndex('updatedAt', 'updatedAt', { unique: false });
            }
            if (!convStore.indexNames.contains('createdAt')) {
                convStore.createIndex('createdAt', 'createdAt', { unique: false });
            }
            if (!convStore.indexNames.contains('projectId')) {
                convStore.createIndex('projectId', 'projectId', { unique: false });
            }
            if (!convStore.indexNames.contains('archived')) {
                convStore.createIndex('archived', 'archived', { unique: false });
            }

            let projectStore;
            if (!db.objectStoreNames.contains(PROJECTS_STORE)) {
                projectStore = db.createObjectStore(PROJECTS_STORE, { keyPath: 'id' });
            } else {
                projectStore = tx.objectStore(PROJECTS_STORE);
            }
            if (!projectStore.indexNames.contains('updatedAt')) {
                projectStore.createIndex('updatedAt', 'updatedAt', { unique: false });
            }
            if (!projectStore.indexNames.contains('createdAt')) {
                projectStore.createIndex('createdAt', 'createdAt', { unique: false });
            }
            if (!projectStore.indexNames.contains('archived')) {
                projectStore.createIndex('archived', 'archived', { unique: false });
            }

            if (!db.objectStoreNames.contains(MEMORIES_STORE)) {
                const memStore = db.createObjectStore(MEMORIES_STORE, { keyPath: 'id', autoIncrement: true });
                memStore.createIndex('createdAt', 'createdAt', { unique: false });
            }
            if (!db.objectStoreNames.contains(SETTINGS_STORE)) {
                db.createObjectStore(SETTINGS_STORE, { keyPath: 'key' });
            }
        };
    });
}

// ===== CONVERSATIONS =====

async function getChatRecord(chatId) {
    if (!chatId) return null;
    if (!cacheDB) await initCacheDB();
    const tx = cacheDB.transaction(CONVERSATIONS_STORE, 'readonly');
    const store = tx.objectStore(CONVERSATIONS_STORE);
    return requestToPromise(store.get(chatId));
}

async function putChatRecord(record) {
    if (!record?.id) return null;
    if (!cacheDB) await initCacheDB();
    record.updatedAt = record.updatedAt || Date.now();
    const tx = cacheDB.transaction(CONVERSATIONS_STORE, 'readwrite');
    tx.objectStore(CONVERSATIONS_STORE).put(record);
    await txDone(tx);
    updateChatCache(record);
    renderChatList();
    if (typeof refreshProjectView === 'function') refreshProjectView();
    return record;
}

async function getAllChatRecords() {
    if (!cacheDB) await initCacheDB();
    const tx = cacheDB.transaction(CONVERSATIONS_STORE, 'readonly');
    const store = tx.objectStore(CONVERSATIONS_STORE);
    const all = await requestToPromise(store.getAll());
    return (all || [])
        .filter(record => !record.archived)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

async function getProjectRecord(projectId) {
    if (!projectId) return null;
    if (!cacheDB) await initCacheDB();
    const tx = cacheDB.transaction(PROJECTS_STORE, 'readonly');
    const store = tx.objectStore(PROJECTS_STORE);
    return requestToPromise(store.get(projectId));
}

async function putProjectRecord(record) {
    if (!record?.id) return null;
    if (!cacheDB) await initCacheDB();
    record.name = cleanProjectName(record.name);
    record.updatedAt = record.updatedAt || Date.now();
    const tx = cacheDB.transaction(PROJECTS_STORE, 'readwrite');
    tx.objectStore(PROJECTS_STORE).put(record);
    await txDone(tx);
    updateProjectCache(record);
    renderChatList();
    if (typeof refreshProjectView === 'function') refreshProjectView();
    return record;
}

async function getAllProjectRecords() {
    if (!cacheDB) await initCacheDB();
    const tx = cacheDB.transaction(PROJECTS_STORE, 'readonly');
    const store = tx.objectStore(PROJECTS_STORE);
    const all = await requestToPromise(store.getAll());
    return (all || [])
        .filter(record => !record.archived)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

async function loadAllProjects() {
    const records = await getAllProjectRecords();
    projectRecordsCache = records;
    projectRecordsReady = true;
    return records;
}

async function createProject(options = {}) {
    const record = baseProjectRecord();
    if (options.name) record.name = cleanProjectName(options.name);
    if (options.description) record.description = String(options.description);
    await putProjectRecord(record);
    return record;
}

async function renameProject(projectId, nextName) {
    const record = await getProjectRecord(projectId);
    if (!record) return null;
    record.name = cleanProjectName(nextName);
    record.updatedAt = Date.now();
    return putProjectRecord(record);
}

async function setProjectExpanded(projectId, expanded) {
    const record = await getProjectRecord(projectId);
    if (!record) return null;
    record.expanded = Boolean(expanded);
    record.updatedAt = Date.now();
    return putProjectRecord(record);
}

async function moveChatToProject(chatId, projectId) {
    const record = await getChatRecord(chatId);
    if (!record) return null;
    record.projectId = projectId || null;
    record.updatedAt = Date.now();
    await putChatRecord(record);
    if (typeof refreshProjectView === 'function') refreshProjectView();
    return record;
}

async function archiveChat(chatId, event) {
    if (event) event.stopPropagation();
    const record = await getChatRecord(chatId);
    if (!record) return;
    record.archived = true;
    record.updatedAt = Date.now();
    await putChatRecord(record);
    chatRecordsCache = chatRecordsCache.filter(item => item.id !== chatId);
    if (currentChatId === chatId) {
        currentChatId = null;
        chatHistory = [];
        const messagesDiv = getMessagesDiv();
        if (messagesDiv) messagesDiv.innerHTML = '';
        if (typeof showHome === 'function') showHome();
    }
    renderChatList();
    if (typeof Toast !== 'undefined') {
        Toast.success(apiT('projects.chatArchived', 'Chat archivé'));
    }
}

async function deleteProject(projectId, options = {}) {
    const { deleteChats = false } = options;
    if (!projectId || !cacheDB) return;

    const tx = cacheDB.transaction([PROJECTS_STORE, CONVERSATIONS_STORE], 'readwrite');
    const projects = tx.objectStore(PROJECTS_STORE);
    const conversations = tx.objectStore(CONVERSATIONS_STORE);
    const allChats = await requestToPromise(conversations.getAll());
    const activeChatBelongsToProject = (allChats || []).some(chat => chat.id === currentChatId && chat.projectId === projectId);

    for (const chat of allChats || []) {
        if (chat.projectId !== projectId) continue;
        if (deleteChats) {
            conversations.delete(chat.id);
        } else {
            chat.projectId = null;
            chat.updatedAt = Date.now();
            conversations.put(chat);
        }
    }
    projects.delete(projectId);
    await txDone(tx);

    projectRecordsCache = projectRecordsCache.filter(item => item.id !== projectId);
    chatRecordsCache = await getAllChatRecords();
    if (deleteChats && activeChatBelongsToProject) {
        currentChatId = null;
        chatHistory = [];
        const messagesDiv = getMessagesDiv();
        if (messagesDiv) messagesDiv.innerHTML = '';
        if (typeof applyTerminalChatState === 'function') applyTerminalChatState(null);
    }
    renderChatList();
    if (typeof refreshProjectView === 'function') refreshProjectView();
}

async function persistCurrentChat(extra = {}) {
    const targetChatId = extra.chatId || currentChatId;
    if (!targetChatId) return null;

    const isActiveChat = targetChatId === currentChatId;
    const existing = await getChatRecord(targetChatId);
    const record = existing || baseChatRecord(targetChatId);
    const messages = Array.isArray(extra.messages)
        ? extra.messages
        : (isActiveChat ? chatHistory : (record.messages || []));
    record.messages = messages;
    // Never read the live DOM for an inactive chat. Async generations can finish
    // after the user switched conversations; using the active DOM here would
    // overwrite the wrong transcript and make older requests disappear.
    record.html = typeof extra.html === 'string'
        ? extra.html
        : (isActiveChat ? getCurrentChatHtml() : (record.html || ''));
    if (extra.mode !== undefined) record.mode = extra.mode || 'chat';
    if (extra.workspace !== undefined) record.workspace = extra.workspace || null;
    if (extra.projectId !== undefined) record.projectId = extra.projectId || null;
    if (extra.lastVisualReference !== undefined) record.lastVisualReference = extra.lastVisualReference || null;
    if (extra.title) record.title = cleanChatTitle(extra.title);
    if ((!record.title || record.title === apiT('chat.newConversation', 'Nouvelle conversation')) && messages.length) {
        const firstUser = messages.find(msg => msg.role === 'user');
        if (firstUser?.content) record.title = cleanChatTitle(firstUser.content);
    }
    record.updatedAt = Date.now();
    return putChatRecord(record);
}

async function createNewChat(options = {}) {
    const record = baseChatRecord();
    if (options.mode) record.mode = options.mode;
    if (options.workspace) record.workspace = options.workspace;
    if (options.projectId) record.projectId = options.projectId;
    if (options.title) record.title = cleanChatTitle(options.title);
    currentChatId = record.id;
    chatHistory = [];
    currentImage = null;
    if (typeof updateImagePreviews === 'function') updateImagePreviews();

    const messagesDiv = getMessagesDiv();
    if (messagesDiv) messagesDiv.innerHTML = '';

    sessionStorage.removeItem('chatHtml');
    sessionStorage.removeItem('chatImage');

    if (typeof resetTokenStats === 'function') resetTokenStats();
    await putChatRecord(record);
    if (typeof applyTerminalChatState === 'function') {
        applyTerminalChatState(record);
    }
    if (typeof apiRuntime !== 'undefined' && apiRuntime.createConversation) {
        apiRuntime.createConversation({ id: record.id, title: record.title })
            .catch(e => console.warn('[RUNTIME] Conversation mirror failed:', e));
    }

    console.log(`[CHAT] Nouvelle conversation: ${record.id}`);
    if (typeof renderChatList === 'function') {
        renderChatList();
    }
    if (typeof showChat === 'function') {
        showChat();
    }
    const input = document.getElementById('message-input');
    input?.focus?.();
    return record.id;
}

async function ensureActiveChatForRequest(options = {}) {
    const title = typeof options === 'string' ? options : (options.title || '');

    if (!currentChatId) {
        await createNewChat(title ? { title } : {});
    } else if (title && typeof updateChatTitleNow === 'function') {
        updateChatTitleNow(title);
    }

    if (typeof showChat === 'function') {
        showChat();
    }
    renderChatList();
    return currentChatId;
}

async function ensureVisibleChatForRequest(options = {}) {
    const chatId = typeof ensureActiveChatForRequest === 'function'
        ? await ensureActiveChatForRequest(options)
        : currentChatId;

    if (typeof showChat === 'function') {
        showChat();
    }
    const messagesDiv = getMessagesDiv();
    if (messagesDiv && chatId && typeof persistCurrentChat === 'function') {
        persistCurrentChat({ chatId, html: messagesDiv.innerHTML || '' })
            .catch(e => console.warn('[CHAT] Visible chat persist failed:', e));
    }
    return chatId;
}

async function waitForNewChat() { return Promise.resolve(); }

function saveCurrentChat(userMessage, aiResponse, html, chatId = currentChatId) {
    if (!chatId) return;
    if (chatId === currentChatId) {
        if (userMessage) chatHistory.push({ role: 'user', content: userMessage });
        if (aiResponse) chatHistory.push({ role: 'assistant', content: aiResponse });
        // saveCurrentChat() is usually called with a single message snippet.
        // Persist the full live transcript, otherwise the DB keeps only the last
        // generation and older requests look "deleted" when reloading a chat.
        persistCurrentChat({ chatId, html: getCurrentChatHtml() }).catch(e => console.error('[CHAT] Persist failed:', e));
        return;
    }

    getChatRecord(chatId).then(record => {
        const next = record || baseChatRecord(chatId);
        const messages = Array.isArray(next.messages) ? [...next.messages] : [];
        if (userMessage) messages.push({ role: 'user', content: userMessage });
        if (aiResponse) messages.push({ role: 'assistant', content: aiResponse });
        const nextHtml = html ? `${next.html || ''}${html}` : (next.html || '');
        return persistCurrentChat({ chatId, messages, html: nextHtml });
    }).catch(e => console.error('[CHAT] Persist inactive failed:', e));
}

function saveCurrentChatHtml(userMessage, html, chatId = currentChatId) {
    if (!chatId) return;
    if (chatId === currentChatId) {
        if (userMessage) chatHistory.push({ role: 'user', content: userMessage });
        persistCurrentChat({ chatId, html: html || getCurrentChatHtml() }).catch(e => console.error('[CHAT] Persist HTML failed:', e));
        return;
    }

    getChatRecord(chatId).then(record => {
        const next = record || baseChatRecord(chatId);
        const messages = Array.isArray(next.messages) ? [...next.messages] : [];
        if (userMessage) messages.push({ role: 'user', content: userMessage });
        return persistCurrentChat({ chatId, messages, html: html || next.html || '' });
    }).catch(e => console.error('[CHAT] Persist inactive HTML failed:', e));
}

function loadAllChats(options = {}) {
    const { showHomeOnLoad = true } = options;
    return initCacheDB().then(() => {
        return Promise.all([getAllChatRecords(), loadAllProjects()]);
    }).then(([records]) => {
        chatRecordsCache = records;
        chatRecordsReady = true;
        renderChatList();
        if (showHomeOnLoad && typeof showHome === 'function') showHome();
    }).catch(e => console.error('Erreur init DB:', e));
}

async function loadChat(chatId) {
    let record = await getChatRecord(chatId);
    if (!record) return;
    currentChatId = record.id;
    chatHistory = Array.isArray(record.messages) ? record.messages : [];
    if (typeof cacheLastVisualReferenceForChat === 'function') {
        cacheLastVisualReferenceForChat(record.id, record.lastVisualReference || null);
    }
    let html = record.html || '';
    if (shouldSanitizePersistedChatHtml(record.id) && typeof sanitizeChatTranscriptHtml === 'function') {
        const cleanHtml = sanitizeChatTranscriptHtml(html);
        if (cleanHtml !== html) {
            html = cleanHtml;
            record = { ...record, html };
            const cacheIndex = chatRecordsCache.findIndex(item => item.id === record.id);
            if (cacheIndex >= 0) chatRecordsCache.splice(cacheIndex, 1, record);
            putChatRecord(record).catch(e => console.warn('[CHAT] Stored stale pending cleanup failed:', e));
        }
    }
    const messagesDiv = getMessagesDiv();
    if (messagesDiv) {
        messagesDiv.innerHTML = html;
        // Workspace/project selection is UI state, not transcript content.
        // Older builds accidentally saved that card in chats; strip it on load.
        messagesDiv.querySelectorAll('.terminal-workspace-picker, .project-launcher-overlay').forEach(el => el.remove());
    }
    if (typeof applyTerminalChatState === 'function') {
        applyTerminalChatState(record);
    }
    if (typeof showChat === 'function') showChat();
    if (typeof resetTokenStats === 'function') resetTokenStats();
    renderChatList();
    setTimeout(() => {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        if (typeof hydratePersistedVideos === 'function') hydratePersistedVideos(messagesDiv);
        if (typeof updateChatPadding === 'function') updateChatPadding();
        if (typeof scrollToBottom === 'function') scrollToBottom(true);
    }, 0);
}

async function deleteChat(chatId, event) {
    if (event) event.stopPropagation();
    if (!chatId || !cacheDB) return;
    if (locallyCancelRuntimeJobs(job => job.conversation_id === chatId, apiT('runtime.conversationDeleted', 'Conversation supprimée'))) {
        renderRuntimeJobs();
    }
    if (typeof apiRuntime !== 'undefined' && apiRuntime.cancelConversationJobs) {
        apiRuntime.cancelConversationJobs(chatId)
            .catch(e => console.warn('[RUNTIME] Conversation jobs cancel failed:', e))
            .finally(() => refreshRuntimeJobs());
    }
    const tx = cacheDB.transaction(CONVERSATIONS_STORE, 'readwrite');
    tx.objectStore(CONVERSATIONS_STORE).delete(chatId);
    await txDone(tx).catch(e => console.error('[CHAT] Delete failed:', e));
    chatRecordsCache = chatRecordsCache.filter(item => item.id !== chatId);
    if (currentChatId === chatId) {
        currentChatId = null;
        chatHistory = [];
        const messagesDiv = getMessagesDiv();
        if (messagesDiv) messagesDiv.innerHTML = '';
        if (typeof applyTerminalChatState === 'function') {
            // Deleting the active project chat must clear the global terminal
            // UI state; otherwise the next normal prompt can be routed as a
            // ghost workspace message and reopen the project picker.
            applyTerminalChatState(null);
        }
        if (typeof showHome === 'function') showHome();
    }
    renderChatList();
    if (typeof refreshProjectView === 'function') refreshProjectView();
}

async function renameChat(chatId, event) {
    if (event) event.stopPropagation();
    openChatRenameEditor(chatId, event);
}

let chatListLongPressTimer = null;
let chatListLongPressPoint = null;
let chatListLongPressPointer = null;
let chatListSuppressClickUntil = 0;
let chatListPopoverCleanup = null;

const CHAT_LIST_LONG_PRESS_MS = 620;
const CHAT_LIST_LONG_PRESS_MOVE_PX = 9;

function clearChatListLongPress() {
    if (chatListLongPressTimer) {
        clearTimeout(chatListLongPressTimer);
        chatListLongPressTimer = null;
    }
    if (chatListLongPressPointer?.element && chatListLongPressPointer.pointerId !== undefined) {
        try {
            chatListLongPressPointer.element.releasePointerCapture?.(chatListLongPressPointer.pointerId);
        } catch (_) {
            // Pointer capture may already be released by the browser.
        }
    }
    chatListLongPressPoint = null;
    chatListLongPressPointer = null;
}

function closeChatListPopover() {
    if (chatListPopoverCleanup) {
        chatListPopoverCleanup();
        chatListPopoverCleanup = null;
    }
    document.querySelectorAll('.chat-list-action-popover').forEach(node => node.remove());
}

function chatListPopoverPosition(popover, x, y) {
    const margin = 8;
    const rect = popover.getBoundingClientRect();
    const left = Math.max(margin, Math.min(x, window.innerWidth - rect.width - margin));
    const top = Math.max(margin, Math.min(y, window.innerHeight - rect.height - margin));
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
}

function getChatListAnchorPoint(event) {
    if (Number.isFinite(event?.clientX) && Number.isFinite(event?.clientY)) {
        return { x: event.clientX, y: event.clientY };
    }
    const rect = event?.currentTarget?.getBoundingClientRect?.();
    if (rect) {
        return { x: rect.left + 24, y: rect.top + Math.min(rect.height, 42) };
    }
    return { x: 20, y: 20 };
}

function attachChatListPopoverLifecycle(popover) {
    const closeOnPointerDown = (event) => {
        if (popover.contains(event.target)) return;
        closeChatListPopover();
    };
    const closeOnKeydown = (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeChatListPopover();
        }
    };
    const closeOnWindowChange = () => closeChatListPopover();

    document.addEventListener('pointerdown', closeOnPointerDown, true);
    document.addEventListener('keydown', closeOnKeydown, true);
    window.addEventListener('resize', closeOnWindowChange);
    window.addEventListener('scroll', closeOnWindowChange, true);

    chatListPopoverCleanup = () => {
        document.removeEventListener('pointerdown', closeOnPointerDown, true);
        document.removeEventListener('keydown', closeOnKeydown, true);
        window.removeEventListener('resize', closeOnWindowChange);
        window.removeEventListener('scroll', closeOnWindowChange, true);
    };
}

function openChatListActionMenu(chatId, event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    clearChatListLongPress();
    closeChatListPopover();

    const record = chatRecordsCache.find(item => item.id === chatId);
    if (!record) return;

    const point = getChatListAnchorPoint(event);
    const popover = document.createElement('div');
    popover.className = 'chat-list-action-popover';
    popover.setAttribute('role', 'menu');
    popover.dataset.chatId = chatId;
    popover.innerHTML = `
        <div class="chat-list-action-title">${escapeHtml(record.title || apiT('chat.newConversation', 'Nouvelle conversation'))}</div>
        <button class="chat-list-action-option" type="button" role="menuitem">
            <i data-lucide="pencil"></i>
            <span>${escapeHtml(apiT('chat.rename', 'Renommer'))}</span>
        </button>
    `;

    const button = popover.querySelector('.chat-list-action-option');
    button?.addEventListener('click', (clickEvent) => openChatRenameEditor(chatId, clickEvent, point));

    document.body.appendChild(popover);
    chatListPopoverPosition(popover, point.x, point.y);
    attachChatListPopoverLifecycle(popover);
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [popover] });
    button?.focus();
}

function openChatRenameEditor(chatId, event = null, fallbackPoint = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();

    const record = chatRecordsCache.find(item => item.id === chatId);
    if (!record) return;

    const point = fallbackPoint || getChatListAnchorPoint(event);
    closeChatListPopover();

    const popover = document.createElement('div');
    popover.className = 'chat-list-action-popover chat-list-rename-popover';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', apiT('chat.rename', 'Renommer'));
    popover.dataset.chatId = chatId;
    popover.innerHTML = `
        <label class="chat-list-rename-label" for="chat-rename-input">
            ${escapeHtml(apiT('chat.renamePrompt', 'Nouveau nom'))}
        </label>
        <input
            id="chat-rename-input"
            class="chat-list-rename-input"
            type="text"
            maxlength="80"
            value="${escapeHtml(record.title || '')}"
            placeholder="${escapeHtml(apiT('chat.renamePlaceholder', 'Nom de la conversation'))}"
        >
        <div class="chat-list-rename-error" aria-live="polite"></div>
        <div class="chat-list-rename-actions">
            <button class="chat-list-rename-cancel" type="button">${escapeHtml(apiT('common.cancel', 'Annuler'))}</button>
            <button class="chat-list-rename-save" type="button">${escapeHtml(apiT('common.save', 'Enregistrer'))}</button>
        </div>
    `;

    const input = popover.querySelector('.chat-list-rename-input');
    const error = popover.querySelector('.chat-list-rename-error');
    const cancel = popover.querySelector('.chat-list-rename-cancel');
    const save = popover.querySelector('.chat-list-rename-save');
    let isSaving = false;

    const commit = async () => {
        if (isSaving) return;
        const nextTitle = (input?.value || '').replace(/\s+/g, ' ').trim();
        if (!nextTitle) {
            input?.classList.add('is-invalid');
            if (error) error.textContent = apiT('chat.renameEmpty', 'Le nom ne peut pas être vide.');
            return;
        }

        try {
            isSaving = true;
            if (save) save.disabled = true;
            const freshRecord = await getChatRecord(chatId);
            if (!freshRecord) {
                closeChatListPopover();
                return;
            }

            freshRecord.title = cleanChatTitle(nextTitle);
            freshRecord.updatedAt = Date.now();
            await putChatRecord(freshRecord);
            closeChatListPopover();
            if (typeof Toast !== 'undefined') {
                Toast.success(apiT('chat.renameSaved', 'Conversation renommée'));
            }
        } catch (err) {
            console.error('[CHAT] Rename failed:', err);
            isSaving = false;
            if (save) save.disabled = false;
            if (error) error.textContent = apiT('chat.renameFailed', 'Impossible de renommer la conversation.');
            if (typeof Toast !== 'undefined') {
                Toast.error(apiT('chat.renameFailed', 'Impossible de renommer la conversation.'));
            }
        }
    };

    input?.addEventListener('input', () => {
        input.classList.remove('is-invalid');
        if (error) error.textContent = '';
    });
    input?.addEventListener('keydown', (keyEvent) => {
        if (keyEvent.key === 'Enter') {
            keyEvent.preventDefault();
            commit();
        }
    });
    cancel?.addEventListener('click', () => closeChatListPopover());
    save?.addEventListener('click', commit);

    document.body.appendChild(popover);
    chatListPopoverPosition(popover, point.x, point.y);
    attachChatListPopoverLifecycle(popover);
    requestAnimationFrame(() => {
        input?.focus();
        input?.select();
    });
}

function isChatListControlTarget(event) {
    return Boolean(event?.target?.closest?.('button, input, textarea, select, a, .chat-list-action-popover'));
}

function handleChatListItemClick(chatId, event) {
    if (isChatListControlTarget(event) || Date.now() < chatListSuppressClickUntil) {
        event?.preventDefault?.();
        event?.stopPropagation?.();
        chatListSuppressClickUntil = 0;
        return;
    }
    loadChat(chatId);
}

function startChatListLongPress(chatId, event) {
    if (isChatListControlTarget(event)) return;
    if (event?.button !== undefined && event.button !== 0) return;

    clearChatListLongPress();
    closeChatListPopover();

    chatListLongPressPoint = { x: event.clientX || 0, y: event.clientY || 0 };
    chatListLongPressPointer = { element: event.currentTarget, pointerId: event.pointerId };
    try {
        event.currentTarget?.setPointerCapture?.(event.pointerId);
    } catch (_) {
        // Some browsers do not allow capture for every pointer type.
    }

    chatListLongPressTimer = setTimeout(() => {
        chatListSuppressClickUntil = Date.now() + 900;
        openChatListActionMenu(chatId, {
            preventDefault() {},
            stopPropagation() {},
            clientX: chatListLongPressPoint?.x || event.clientX || 20,
            clientY: chatListLongPressPoint?.y || event.clientY || 20,
            currentTarget: event.currentTarget,
        });
    }, CHAT_LIST_LONG_PRESS_MS);
}

function moveChatListLongPress(event) {
    if (!chatListLongPressTimer || !chatListLongPressPoint) return;
    const dx = Math.abs((event.clientX || 0) - chatListLongPressPoint.x);
    const dy = Math.abs((event.clientY || 0) - chatListLongPressPoint.y);
    if (dx > CHAT_LIST_LONG_PRESS_MOVE_PX || dy > CHAT_LIST_LONG_PRESS_MOVE_PX) {
        clearChatListLongPress();
    }
}

function handleChatListItemKeydown(chatId, event) {
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        loadChat(chatId);
        return;
    }

    if (event.key === 'F2') {
        renameChat(chatId, event);
        return;
    }

    if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
        openChatListActionMenu(chatId, event);
    }
}

// ===== RUNTIME JOBS =====

function isRuntimeJobActive(job) {
    return Boolean(job && !RUNTIME_JOB_DONE_STATES.has(String(job.status || '').toLowerCase()));
}

function hasChatRecord(chatId) {
    return Boolean(chatId && chatRecordsCache.some(record => record.id === chatId));
}

function isRuntimeJobOrphan(job) {
    return Boolean(chatRecordsReady && job?.conversation_id && !hasChatRecord(job.conversation_id));
}

function isCurrentRuntimeJob(job) {
    const jobId = job?.id ? String(job.id) : '';
    const activeJobId = typeof currentGenerationId !== 'undefined' && currentGenerationId
        ? String(currentGenerationId)
        : '';
    if (jobId && activeJobId && jobId === activeJobId) return true;

    const jobChatId = job?.conversation_id ? String(job.conversation_id) : '';
    const activeChatId = typeof currentGenerationChatId !== 'undefined' && currentGenerationChatId
        ? String(currentGenerationChatId)
        : (typeof currentChatId !== 'undefined' && currentChatId ? String(currentChatId) : '');
    return Boolean(isGenerating && jobChatId && activeChatId && jobChatId === activeChatId);
}

function locallyCancelRuntimeJobs(predicate, message) {
    let changed = false;
    runtimeJobsCache = runtimeJobsCache.map(job => {
        if (predicate(job) && isRuntimeJobActive(job)) {
            changed = true;
            return {
                ...job,
                status: 'cancelled',
                phase: 'cancelled',
                progress: 100,
                message: message || apiT('runtime.cancelled', 'Arrêté')
            };
        }
        return job;
    });
    return changed;
}

function hasActiveRuntimeJobForChat(chatId) {
    if (!chatId) return false;
    return runtimeJobsCache.some(job => isRuntimeJobActive(job) && job.conversation_id === chatId);
}

function notifyRuntimeJobsUpdated() {
    window.dispatchEvent(new CustomEvent('joyboy:runtime-jobs-updated', {
        detail: {
            jobs: Array.isArray(runtimeJobsCache) ? runtimeJobsCache : [],
        },
    }));
}

function runtimeJobLabel(job) {
    const kind = String(job?.kind || 'task');
    if (kind === 'image') return apiT('runtime.kindImage', 'Image');
    if (kind === 'video') return apiT('runtime.kindVideo', 'Vidéo');
    if (kind === 'terminal') return apiT('runtime.kindTerminal', 'Terminal');
    if (kind === 'model') return apiT('runtime.kindModel', 'Modèle');
    if (kind === 'signalatlas') return apiT('runtime.kindSignalAtlas', 'SignalAtlas');
    if (kind === 'perfatlas') return apiT('runtime.kindPerfAtlas', 'PerfAtlas');
    if (kind === 'cyberatlas') return apiT('runtime.kindCyberAtlas', 'CyberAtlas');
    if (kind === 'deployatlas') return apiT('runtime.kindDeployAtlas', 'DeployAtlas');
    return apiT('runtime.kindTask', 'Tâche');
}

function renderRuntimeJobs() {
    const container = document.getElementById('runtime-job-list');
    if (!container) return;

    const activeJobs = runtimeJobsCache
        .filter(job => isRuntimeJobActive(job) && !isRuntimeJobOrphan(job))
        .slice(0, 5);
    if (!activeJobs.length) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = activeJobs.map(job => {
        const jobId = escapeHtml(job.id || '');
        const titleSource = job.prompt || job.model || runtimeJobLabel(job);
        const title = escapeHtml(cleanChatTitle(titleSource));
        const kind = escapeHtml(runtimeJobLabel(job));
        const phase = escapeHtml(job.phase || job.status || apiT('runtime.running', 'En cours'));
        const message = escapeHtml(job.message || apiT('runtime.running', 'En cours'));
        const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
        const openLabel = escapeHtml(apiT('runtime.open', 'Ouvrir'));
        const cancelLabel = escapeHtml(apiT('runtime.cancel', 'Arrêter'));
        return `
            <div class="runtime-job-card" data-job-id="${jobId}">
                <div class="runtime-job-main" onclick="openRuntimeJob('${jobId}')" title="${openLabel}">
                    <div class="runtime-job-kicker">${kind}</div>
                    <div class="runtime-job-title">${title}</div>
                    <div class="runtime-job-message">${message}</div>
                </div>
                <button class="runtime-job-cancel" onclick="cancelRuntimeJob('${jobId}', event)" title="${cancelLabel}" aria-label="${cancelLabel}">
                    <i data-lucide="square"></i>
                </button>
                <div class="runtime-job-progress" aria-label="${phase}">
                    <div class="runtime-job-progress-fill" style="width:${progress}%"></div>
                </div>
            </div>
        `;
    }).join('');

    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [container] });
}

async function refreshRuntimeJobs() {
    if (typeof apiRuntime === 'undefined' || !apiRuntime.listJobs) return;
    try {
        const result = await apiRuntime.listJobs();
        const jobs = Array.isArray(result.data?.jobs) ? result.data.jobs : [];
        // Do not auto-cancel server work from a local cache guess. Conversation
        // deletion uses /cancel-jobs explicitly; this poller only hides orphans.
        runtimeJobsCache = jobs.filter(job =>
            !(isRuntimeJobActive(job) && isRuntimeJobOrphan(job) && !isCurrentRuntimeJob(job))
        );
        runtimeJobsHydrated = true;
        cleanupStalePendingUiForActiveChat();
        renderRuntimeJobs();
        renderChatList();
        notifyRuntimeJobsUpdated();
    } catch (e) {
        console.warn('[RUNTIME] Jobs refresh failed:', e);
    }
}

function startRuntimeJobsPolling() {
    if (runtimeJobsPollTimer) return;
    refreshRuntimeJobs();
    runtimeJobsPollTimer = setInterval(refreshRuntimeJobs, 2500);
}

function stopRuntimeJobsPolling() {
    if (!runtimeJobsPollTimer) return;
    clearInterval(runtimeJobsPollTimer);
    runtimeJobsPollTimer = null;
}

async function openRuntimeJob(jobId) {
    const job = runtimeJobsCache.find(item => item.id === jobId);
    if (job?.conversation_id) {
        await loadChat(job.conversation_id);
        return;
    }
    const moduleId = String(job?.metadata?.module_id || '').trim().toLowerCase();
    if (moduleId && typeof openAuditModuleWorkspace === 'function') {
        await openAuditModuleWorkspace(moduleId, job?.metadata?.audit_id || job?.metadata?.deployment_id || null);
    }
}

async function cancelRuntimeJob(jobId, event) {
    if (event) event.stopPropagation();
    if (typeof apiRuntime === 'undefined' || !apiRuntime.cancelJob) return;
    if (locallyCancelRuntimeJobs(job => job.id === jobId, apiT('runtime.cancelled', 'Arrêté'))) {
        renderRuntimeJobs();
        renderChatList();
        notifyRuntimeJobsUpdated();
    }
    try {
        await apiRuntime.cancelJob(jobId);
        await refreshRuntimeJobs();
    } catch (e) {
        console.error('[RUNTIME] Cancel failed:', e);
    }
}

function renderChatList() {
    if (typeof renderSidebarSections === 'function') {
        renderSidebarSections();
        return;
    }

    const list = document.getElementById('chat-list');
    if (!list) return;

    if (!chatRecordsCache.length) {
        list.innerHTML = `<div class="chat-list-empty">${apiT('chat.noConversations', 'Aucune conversation')}</div>`;
        return;
    }

    list.innerHTML = chatRecordsCache.map(record => {
        const isActive = record.id === currentChatId;
        // DOM skeletons are only a visual fallback. The runtime job store is the
        // source of truth after refresh/reload, so stale saved HTML cannot hide
        // or fake an active generation.
        const hasRunningJob = shouldShowChatAsRunning(record);
        const isWorkspaceChat = record.mode === 'terminal' && !!record.workspace?.path;
        const active = `${isActive ? ' active' : ''}${hasRunningJob ? ' running' : ''}${isWorkspaceChat ? ' workspace-chat' : ''}`;
        const date = record.updatedAt ? new Date(record.updatedAt).toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' }) : '';
        const title = escapeHtml(record.title || apiT('chat.newConversation', 'Nouvelle conversation'));
        const statusTitle = apiT('chat.running', 'Génération en cours');
        const workspaceName = isWorkspaceChat ? escapeHtml(record.workspace.name || record.workspace.path) : '';
        const itemTitle = isWorkspaceChat ? `${title} - ${escapeHtml(record.workspace.path)}` : title;
        const iconName = isWorkspaceChat ? 'folder-code' : 'message-square';
        const chatIdArg = escapeHtml(JSON.stringify(record.id));
        const doubleClick = isWorkspaceChat ? `ondblclick="openWorkspaceFolderFromChat(${chatIdArg}, event)"` : '';
        const renameLabel = escapeHtml(apiT('chat.rename', 'Renommer'));
        const deleteLabel = escapeHtml(apiT('chat.delete', 'Supprimer'));
        return `
            <div
                class="chat-list-item${active}"
                role="button"
                tabindex="0"
                onclick="handleChatListItemClick(${chatIdArg}, event)"
                onkeydown="handleChatListItemKeydown(${chatIdArg}, event)"
                onpointerdown="startChatListLongPress(${chatIdArg}, event)"
                onpointermove="moveChatListLongPress(event)"
                onpointerup="clearChatListLongPress()"
                onpointercancel="clearChatListLongPress()"
                onpointerleave="clearChatListLongPress()"
                oncontextmenu="openChatListActionMenu(${chatIdArg}, event)"
                ${doubleClick}
                title="${itemTitle}"
            >
                <i data-lucide="${iconName}" class="chat-list-icon"></i>
                <span class="chat-list-title">${title}</span>
                ${isWorkspaceChat ? `<span class="chat-list-mode-badge" title="${workspaceName}">Dev</span>` : ''}
                ${hasRunningJob ? `<span class="chat-list-status" title="${statusTitle}"></span>` : ''}
                <span class="chat-list-date">${date}</span>
                <button class="chat-list-rename" onclick="renameChat(${chatIdArg}, event)" title="${renameLabel}" aria-label="${renameLabel}">
                    <i data-lucide="pencil"></i>
                </button>
                <button class="chat-list-delete" onclick="deleteChat(${chatIdArg}, event)" title="${deleteLabel}" aria-label="${deleteLabel}">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        `;
    }).join('');

    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [list] });
}

async function openWorkspaceFolderFromChat(chatId, event = null) {
    if (event?.target?.closest?.('button')) return;
    event?.preventDefault?.();
    event?.stopPropagation?.();

    const record = chatRecordsCache.find(item => item.id === chatId) || await getChatRecord(chatId);
    const path = record?.workspace?.path;
    if (!path) return;

    try {
        const response = await fetch('/workspace/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Impossible d’ouvrir le dossier');
        }
        if (typeof Toast !== 'undefined') {
            Toast.success(`Dossier ouvert: ${record.workspace.name || path}`);
        }
    } catch (err) {
        console.error('[WORKSPACE] Open folder failed:', err);
        if (typeof Toast !== 'undefined') {
            Toast.error(`Impossible d’ouvrir le dossier: ${err.message}`);
        }
    }
}

function getConversationCount() {
    return chatRecordsCache.length;
}

function getChatContext() {
    return chatHistory.slice(-20);
}

function updateChatTitleNow(userMessage) {
    if (!currentChatId || !userMessage) return;
    getChatRecord(currentChatId).then(record => {
        if (!record) return;
        const fallback = apiT('chat.newConversation', 'Nouvelle conversation');
        if (!record.title || record.title === fallback) {
            record.title = cleanChatTitle(userMessage);
            record.updatedAt = Date.now();
            return putChatRecord(record);
        }
    }).catch(e => console.error('[CHAT] Title update failed:', e));
}

// ===== MEMORIES =====

async function loadMemories() {
    if (!cacheDB) return [];

    try {
        const tx = cacheDB.transaction(MEMORIES_STORE, 'readonly');
        const store = tx.objectStore(MEMORIES_STORE);
        const request = store.getAll();

        return new Promise((resolve) => {
            request.onsuccess = () => {
                userMemories = request.result.map(m => m.content);
                console.log(`[MEMORY] ${userMemories.length} memoires chargees`);
                resolve(userMemories);
            };
            request.onerror = () => {
                console.error('[MEMORY] Erreur chargement');
                resolve([]);
            };
        });
    } catch (e) {
        console.error('[MEMORY] Erreur:', e);
        return [];
    }
}

async function saveMemories(newMemories) {
    if (!cacheDB || !newMemories || newMemories.length === 0) return;

    try {
        const tx = cacheDB.transaction(MEMORIES_STORE, 'readwrite');
        const store = tx.objectStore(MEMORIES_STORE);

        for (const mem of newMemories) {
            if (!userMemories.includes(mem)) {
                store.add({ content: mem, createdAt: Date.now() });
                userMemories.push(mem);
                console.log(`[MEMORY] Nouvelle memoire: ${mem}`);
            }
        }

        if (userMemories.length > MAX_MEMORIES) {
            await cleanupMemories();
        }
    } catch (e) {
        console.error('[MEMORY] Erreur sauvegarde:', e);
    }
}

async function cleanupMemories() {
    if (!cacheDB) return;

    console.log(`[MEMORY] Nettoyage: ${userMemories.length} -> ${CLEANUP_KEEP} memoires`);

    try {
        const tx = cacheDB.transaction(MEMORIES_STORE, 'readwrite');
        const store = tx.objectStore(MEMORIES_STORE);
        const index = store.index('createdAt');
        const request = index.getAll();

        request.onsuccess = () => {
            const allMems = request.result;
            allMems.sort((a, b) => a.createdAt - b.createdAt);

            const toDelete = allMems.slice(0, allMems.length - CLEANUP_KEEP);
            const deleteTx = cacheDB.transaction(MEMORIES_STORE, 'readwrite');
            const deleteStore = deleteTx.objectStore(MEMORIES_STORE);

            for (const mem of toDelete) deleteStore.delete(mem.id);
            userMemories = allMems.slice(-CLEANUP_KEEP).map(m => m.content);
            console.log(`[MEMORY] Nettoyage termine: ${userMemories.length} memoires restantes`);
        };
    } catch (e) {
        console.error('[MEMORY] Erreur nettoyage:', e);
    }
}

function getMemoriesForAI() { return userMemories; }

async function clearAllMemories() {
    if (!cacheDB) return;
    try {
        const tx = cacheDB.transaction(MEMORIES_STORE, 'readwrite');
        const store = tx.objectStore(MEMORIES_STORE);
        store.clear();
        userMemories = [];
        console.log('[MEMORY] Memoire effacee');
    } catch (e) {
        console.error('[MEMORY] Erreur effacement:', e);
    }
}

async function clearCacheDB() {
    if (cacheDB) { cacheDB.close(); cacheDB = null; }

    return new Promise((resolve) => {
        const deleteRequest = indexedDB.deleteDatabase(DB_NAME);
        deleteRequest.onsuccess = () => {
            console.log('[RESET] IndexedDB supprimee');
            userMemories = [];
            chatRecordsCache = [];
            chatRecordsReady = false;
            projectRecordsCache = [];
            projectRecordsReady = false;
            currentChatId = null;
            chatHistory = [];
            resolve();
        };
        deleteRequest.onerror = () => resolve();
        deleteRequest.onblocked = () => setTimeout(resolve, 1000);
    });
}

async function loadConversationCache(options = {}) {
    await loadAllChats(options);
    await loadMemories();
}

async function togglePrivacy() {
    const newVal = !Settings.get('privacyMode');
    Settings.set('privacyMode', newVal);
    Settings.set('privacyDefault', newVal);  // Keep in sync so it persists on restart
    Settings._save();  // Force immediate save (don't rely on debounce)

    // Reset la conversation — nouveau chat propre
    await createNewChat();
}

function cancelCurrentRequest() {
    if (currentController) {
        currentController.abort();
        currentController = null;
        isGenerating = false;
        if (typeof setSendButtonsMode === 'function') setSendButtonsMode(false);

        // Annuler TOUT côté serveur (chat stream + image/video)
        apiSystem.cancelAll().catch(() => {});

        // Gérer les skeletons image (contiennent le message user à l'intérieur)
        const imageSkeleton = document.querySelector('.image-skeleton-message');
        if (imageSkeleton) {
            const userBubble = imageSkeleton.querySelector('.user-bubble');
            const prompt = userBubble ? userBubble.textContent.replace(/'/g, "\\'") : '';
            const msgId = 'cancelled-' + Date.now();

            imageSkeleton.classList.remove('image-skeleton-message');
            imageSkeleton.removeAttribute('data-chat-id');
            imageSkeleton.removeAttribute('data-started-at');

            const aiResponse = imageSkeleton.querySelector('.ai-response');
            if (aiResponse) {
                aiResponse.classList.remove('loading');
                aiResponse.innerHTML = `
                    <div class="chat-bubble cancelled" id="${msgId}">${apiT('chat.noResponse', 'Pas de réponse.')}</div>
                    <div class="chat-actions">
                        <button class="chat-action-btn" onclick="regenerateChat('${prompt}')" title="${apiT('common.regenerate', 'Regénérer')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M1 4v6h6M23 20v-6h-6"/>
                                <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                            </svg>
                        </button>
                        <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${apiT('common.copy', 'Copier')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                            </svg>
                        </button>
                        <div class="chat-actions-divider"></div>
                        <div class="response-time"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${apiT('chat.interrupted', 'Interrompu')}</span></div>
                    </div>
                `;
            }
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
                    <div class="chat-bubble cancelled" id="${msgId}">${apiT('chat.noResponse', 'Pas de réponse.')}</div>
                    <div class="chat-actions">
                        <button class="chat-action-btn" onclick="regenerateChat('${prompt}')" title="${apiT('common.regenerate', 'Regénérer')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M1 4v6h6M23 20v-6h-6"/>
                                <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/>
                            </svg>
                        </button>
                        <button class="chat-action-btn" onclick="copyText('${msgId}')" title="${apiT('common.copy', 'Copier')}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                            </svg>
                        </button>
                        <div class="chat-actions-divider"></div>
                        <div class="response-time"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"></path><path d="M8 12h8"></path></svg><span class="speed">${apiT('chat.interrupted', 'Interrompu')}</span></div>
                    </div>
                </div>
            `);
        }

        document.getElementById('loading').classList.add('hidden');
        console.log('[REQUEST] Requete annulee');
    }
}

async function clearConversationCache() {
    await clearCacheDB();
    const messagesDiv = document.getElementById('chat-messages');
    if (messagesDiv) messagesDiv.innerHTML = '';
    chatRecordsCache = [];
    projectRecordsCache = [];
    projectRecordsReady = false;
    currentChatId = null;
    chatHistory = [];
    currentImage = null;
    originalImage = null;
    modifiedImage = null;
    renderChatList();
}

function initPrivacyButton() {
    // Apply initial state
    _applyPrivacyUI(Settings.get('privacyMode'));

    // Subscribe so any change (ghost button OR settings toggle) syncs all UI
    Settings.subscribe('privacyMode', _applyPrivacyUI);
}

function _applyPrivacyUI(isPrivate) {
    const btns = [
        document.getElementById('privacy-btn'),
        document.getElementById('home-privacy-btn')
    ];

    if (isPrivate) {
        btns.forEach(btn => btn?.classList.add('active'));
        document.body.classList.add('privacy-active');
    } else {
        btns.forEach(btn => btn?.classList.remove('active'));
        document.body.classList.remove('privacy-active');
    }

    // Sync the settings modal toggle too
    const settingsToggle = document.getElementById('toggle-privacy-default');
    if (settingsToggle) {
        settingsToggle.classList.toggle('active', isPrivate);
    }
}
