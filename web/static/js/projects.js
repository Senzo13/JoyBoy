// ===== PROJECTS - sidebar grouping + project workspace view =====

let sidebarProjectsExpanded = (() => {
    try {
        return localStorage.getItem('joyboy.projects.expanded') !== 'false';
    } catch {
        return true;
    }
})();
let sidebarRecentsExpanded = (() => {
    try {
        return localStorage.getItem('joyboy.recents.expanded') !== 'false';
    } catch {
        return true;
    }
})();
let activeProjectViewId = null;
let activeProjectTab = 'chats';

function projectT(key, fallback, params = {}) {
    if (typeof apiT === 'function') return apiT(key, fallback, params);
    if (typeof JoyBoyI18n !== 'undefined') return JoyBoyI18n.t(key, params, fallback);
    return fallback;
}

function projectDateLabel(value) {
    if (!value) return '';
    try {
        return new Date(value).toLocaleDateString(undefined, { day: '2-digit', month: 'short' });
    } catch {
        return '';
    }
}

function chatExcerpt(record) {
    const messages = Array.isArray(record?.messages) ? record.messages : [];
    const last = [...messages].reverse().find(msg => msg?.content);
    const raw = String(last?.content || '').replace(/\s+/g, ' ').trim();
    if (!raw) return projectT('projects.emptyChatExcerpt', 'Aucune activité encore');
    return raw.length > 96 ? `${raw.slice(0, 96).trim()}…` : raw;
}

function projectById(projectId) {
    return (projectRecordsCache || []).find(project => project.id === projectId) || null;
}

function chatsForProject(projectId) {
    return (chatRecordsCache || [])
        .filter(record => record.projectId === projectId && !record.archived)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

function recentChats() {
    return (chatRecordsCache || [])
        .filter(record => !record.projectId && !record.archived)
        .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

function persistSidebarSectionState() {
    try {
        localStorage.setItem('joyboy.projects.expanded', String(sidebarProjectsExpanded));
        localStorage.setItem('joyboy.recents.expanded', String(sidebarRecentsExpanded));
    } catch {
        // localStorage can be unavailable in private or restricted contexts.
    }
}

function toggleSidebarProjectsSection(event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    sidebarProjectsExpanded = !sidebarProjectsExpanded;
    persistSidebarSectionState();
    renderChatList();
}

function toggleSidebarRecentsSection(event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    sidebarRecentsExpanded = !sidebarRecentsExpanded;
    persistSidebarSectionState();
    renderChatList();
}

function renderSidebarChatItem(record, options = {}) {
    const { nested = false } = options;
    const isActive = record.id === currentChatId;
    const hasRunningJob = typeof shouldShowChatAsRunning === 'function'
        ? shouldShowChatAsRunning(record)
        : (typeof hasActiveRuntimeJobForChat === 'function' && hasActiveRuntimeJobForChat(record.id));
    const isWorkspaceChat = record.mode === 'terminal' && !!record.workspace?.path;
    const active = `${isActive ? ' active' : ''}${hasRunningJob ? ' running' : ''}${isWorkspaceChat ? ' workspace-chat' : ''}${nested ? ' nested' : ''}`;
    const date = projectDateLabel(record.updatedAt);
    const title = escapeHtml(record.title || projectT('chat.newConversation', 'Nouvelle conversation'));
    const statusTitle = projectT('chat.running', 'Génération en cours');
    const workspaceName = isWorkspaceChat ? escapeHtml(record.workspace.name || record.workspace.path) : '';
    const itemTitle = isWorkspaceChat ? `${title} - ${escapeHtml(record.workspace.path)}` : title;
    const iconName = isWorkspaceChat ? 'folder-code' : 'message-square';
    const chatIdArg = escapeHtml(JSON.stringify(record.id));
    const doubleClick = isWorkspaceChat ? `ondblclick="openWorkspaceFolderFromChat(${chatIdArg}, event)"` : '';
    const menuLabel = escapeHtml(projectT('projects.chatMenu', 'Actions du chat'));

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
            <button class="chat-list-menu" onclick="openChatListActionMenu(${chatIdArg}, event)" title="${menuLabel}" aria-label="${menuLabel}">
                <i data-lucide="more-horizontal"></i>
            </button>
        </div>
    `;
}

function renderProjectTree(project) {
    const projectIdArg = escapeHtml(JSON.stringify(project.id));
    const projectChats = chatsForProject(project.id);
    const expanded = project.expanded !== false;
    const active = activeProjectViewId === project.id || projectChats.some(record => record.id === currentChatId);
    const name = escapeHtml(project.name || projectT('projects.untitled', 'Projet sans nom'));
    const menuLabel = escapeHtml(projectT('projects.projectMenu', 'Actions du projet'));
    const toggleLabel = escapeHtml(expanded ? projectT('projects.collapse', 'Replier') : projectT('projects.expand', 'Déplier'));

    return `
        <div class="project-tree${active ? ' active' : ''}">
            <div class="project-tree-row" onclick="showProjectView(${projectIdArg})" role="button" tabindex="0">
                <button class="project-tree-toggle" type="button" onclick="toggleProjectExpanded(${projectIdArg}, event)" aria-label="${toggleLabel}">
                    <i data-lucide="${expanded ? 'chevron-down' : 'chevron-right'}"></i>
                </button>
                <i data-lucide="folder" class="project-tree-icon"></i>
                <span class="project-tree-name">${name}</span>
                <button class="project-tree-menu" type="button" onclick="openProjectActionMenu(${projectIdArg}, event)" title="${menuLabel}" aria-label="${menuLabel}">
                    <i data-lucide="more-horizontal"></i>
                </button>
            </div>
            ${expanded ? `
                <div class="project-tree-chats">
                    ${projectChats.length
                        ? projectChats.slice(0, 6).map(record => renderSidebarChatItem(record, { nested: true })).join('')
                        : `<div class="project-tree-empty">${escapeHtml(projectT('projects.noProjectChats', 'Aucun chat dans ce projet'))}</div>`
                    }
                </div>
            ` : ''}
        </div>
    `;
}

function renderSidebarSections() {
    const list = document.getElementById('chat-list');
    if (!list) return;

    const projects = (projectRecordsCache || []).filter(project => !project.archived);
    const recents = recentChats();

    list.innerHTML = `
        <div class="chat-list-section projects-section">
            <button class="chat-list-section-title" type="button" onclick="toggleSidebarProjectsSection(event)">
                <span>${escapeHtml(projectT('projects.title', 'Projets'))}</span>
                <i data-lucide="${sidebarProjectsExpanded ? 'chevron-down' : 'chevron-right'}"></i>
            </button>
            ${sidebarProjectsExpanded ? `
                <button class="project-new-btn" type="button" onclick="createProjectFromSidebar()">
                    <i data-lucide="folder-plus"></i>
                    <span>${escapeHtml(projectT('projects.newProject', 'Nouveau projet'))}</span>
                </button>
                ${projects.length
                    ? projects.map(project => renderProjectTree(project)).join('')
                    : `<div class="chat-list-empty compact">${escapeHtml(projectT('projects.noProjects', 'Aucun projet'))}</div>`
                }
            ` : ''}
        </div>
        <div class="chat-list-section recent-section">
            <button class="chat-list-section-title" type="button" onclick="toggleSidebarRecentsSection(event)">
                <span>${escapeHtml(projectT('projects.recents', 'Récents'))}</span>
                <i data-lucide="${sidebarRecentsExpanded ? 'chevron-down' : 'chevron-right'}"></i>
            </button>
            ${sidebarRecentsExpanded ? (
                recents.length
                    ? recents.map(record => renderSidebarChatItem(record)).join('')
                    : `<div class="chat-list-empty compact">${escapeHtml(projectT('projects.noRecentChats', 'Aucun chat récent'))}</div>`
            ) : ''}
        </div>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [list] });
}

async function toggleProjectExpanded(projectId, event = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    const project = projectById(projectId) || await getProjectRecord(projectId);
    if (!project) return;
    await setProjectExpanded(projectId, project.expanded === false);
}

async function createProjectFromSidebar() {
    openProjectCreateModal();
}

function closeProjectCreateModal() {
    document.querySelector('.project-create-modal:not(.project-delete-modal)')?.remove();
    document.removeEventListener('keydown', handleProjectCreateModalKeydown);
}

function closeProjectDeleteModal() {
    document.querySelector('.project-delete-modal')?.remove();
    document.removeEventListener('keydown', handleProjectDeleteModalKeydown);
}

function handleProjectCreateModalKeydown(event) {
    if (event.key === 'Escape') closeProjectCreateModal();
}

function handleProjectDeleteModalKeydown(event) {
    if (event.key === 'Escape') closeProjectDeleteModal();
}

function setProjectCreateModalError(message = '') {
    const error = document.getElementById('project-create-error');
    if (!error) return;
    error.textContent = message;
    error.hidden = !message;
}

function setProjectDeleteModalError(message = '') {
    const error = document.getElementById('project-delete-error');
    if (!error) return;
    error.textContent = message;
    error.hidden = !message;
}

async function submitProjectCreateModal(event = null) {
    event?.preventDefault?.();
    const input = document.getElementById('project-create-name-input');
    const submit = document.getElementById('project-create-submit');
    const rawName = String(input?.value || '').trim();
    if (!rawName) {
        setProjectCreateModalError(projectT('projects.createEmpty', 'Ajoute un nom de projet.'));
        input?.focus();
        return;
    }

    setProjectCreateModalError('');
    if (submit) submit.disabled = true;
    try {
        const project = await createProject({ name: cleanProjectName(rawName) });
        closeProjectCreateModal();
        showProjectView(project.id);
        if (typeof Toast !== 'undefined') {
            Toast.success(projectT('projects.projectCreated', 'Projet créé'));
        }
    } catch (error) {
        console.error('[projects] create project failed', error);
        if (submit) submit.disabled = false;
        setProjectCreateModalError(projectT('projects.createFailed', 'Impossible de créer le projet.'));
    }
}

function openProjectCreateModal() {
    closeProjectCreateModal();
    closeProjectDeleteModal();
    const modal = document.createElement('div');
    modal.className = 'project-create-modal';
    modal.setAttribute('role', 'presentation');
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeProjectCreateModal();
    });
    modal.innerHTML = `
        <form class="project-create-panel" role="dialog" aria-modal="true" aria-labelledby="project-create-title" onsubmit="submitProjectCreateModal(event)">
            <div class="project-create-header">
                <div class="project-create-icon" aria-hidden="true">
                    <i data-lucide="folder-plus"></i>
                </div>
                <div>
                    <h2 id="project-create-title">${escapeHtml(projectT('projects.createTitle', 'Créer un projet'))}</h2>
                    <p>${escapeHtml(projectT('projects.createCopy', 'Donne un nom clair pour regrouper tes chats et sources.'))}</p>
                </div>
                <button class="project-create-close" type="button" onclick="closeProjectCreateModal()" aria-label="${escapeHtml(projectT('common.close', 'Fermer'))}">
                    <i data-lucide="x"></i>
                </button>
            </div>
            <label class="project-create-field" for="project-create-name-input">
                <span>${escapeHtml(projectT('projects.createNameLabel', 'Nom du projet'))}</span>
                <input
                    id="project-create-name-input"
                    class="project-create-input"
                    type="text"
                    autocomplete="off"
                    maxlength="80"
                    placeholder="${escapeHtml(projectT('projects.createPlaceholder', 'Ex. Client SEO, App mobile, Refonte site'))}"
                >
            </label>
            <div class="project-create-error" id="project-create-error" hidden></div>
            <div class="project-create-actions">
                <button class="project-create-btn secondary" type="button" onclick="closeProjectCreateModal()">
                    ${escapeHtml(projectT('projects.createCancel', 'Annuler'))}
                </button>
                <button class="project-create-btn primary" id="project-create-submit" type="submit">
                    ${escapeHtml(projectT('projects.createConfirm', 'Créer le projet'))}
                </button>
            </div>
        </form>
    `;

    document.body.appendChild(modal);
    document.addEventListener('keydown', handleProjectCreateModalKeydown);
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [modal] });
    requestAnimationFrame(() => document.getElementById('project-create-name-input')?.focus());
}

function openProjectDeleteModal(projectId) {
    const project = projectById(projectId);
    if (!project) return;
    closeProjectCreateModal();
    closeProjectDeleteModal();

    const projectIdArg = escapeHtml(JSON.stringify(projectId));
    const projectName = project.name || projectT('projects.untitled', 'Projet sans nom');
    const modal = document.createElement('div');
    modal.className = 'project-create-modal project-delete-modal';
    modal.setAttribute('role', 'presentation');
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeProjectDeleteModal();
    });
    modal.innerHTML = `
        <form class="project-create-panel project-delete-panel" role="dialog" aria-modal="true" aria-labelledby="project-delete-title" onsubmit="submitProjectDeleteModal(event, ${projectIdArg})">
            <div class="project-create-header">
                <div class="project-create-icon project-delete-icon" aria-hidden="true">
                    <i data-lucide="trash-2"></i>
                </div>
                <div>
                    <h2 id="project-delete-title">${escapeHtml(projectT('projects.deleteTitle', 'Supprimer le projet'))}</h2>
                    <p>${escapeHtml(projectT('projects.deleteCopy', 'Le projet "{project}" sera retiré de ta sidebar.', { project: projectName }))}</p>
                </div>
                <button class="project-create-close" type="button" onclick="closeProjectDeleteModal()" aria-label="${escapeHtml(projectT('common.close', 'Fermer'))}">
                    <i data-lucide="x"></i>
                </button>
            </div>
            <div class="project-delete-name">${escapeHtml(projectName)}</div>
            <label class="project-delete-option">
                <input id="project-delete-chats-input" type="checkbox">
                <span>
                    <strong>${escapeHtml(projectT('projects.deleteChatsLabel', 'Supprimer aussi les chats du projet'))}</strong>
                    <small>${escapeHtml(projectT('projects.deleteChatsHint', 'Sinon, les chats restent disponibles dans Récents.'))}</small>
                </span>
            </label>
            <div class="project-create-error" id="project-delete-error" hidden></div>
            <div class="project-create-actions">
                <button class="project-create-btn secondary" type="button" onclick="closeProjectDeleteModal()">
                    ${escapeHtml(projectT('common.cancel', 'Annuler'))}
                </button>
                <button class="project-create-btn danger" id="project-delete-submit" type="submit">
                    ${escapeHtml(projectT('projects.deleteConfirmButton', 'Supprimer le projet'))}
                </button>
            </div>
        </form>
    `;

    document.body.appendChild(modal);
    document.addEventListener('keydown', handleProjectDeleteModalKeydown);
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [modal] });
    requestAnimationFrame(() => document.getElementById('project-delete-submit')?.focus());
}

async function submitProjectDeleteModal(event = null, projectId) {
    event?.preventDefault?.();
    const submit = document.getElementById('project-delete-submit');
    const deleteChats = Boolean(document.getElementById('project-delete-chats-input')?.checked);
    setProjectDeleteModalError('');
    if (submit) submit.disabled = true;
    try {
        await deleteProject(projectId, { deleteChats });
        closeProjectDeleteModal();
        if (activeProjectViewId === projectId && typeof showHome === 'function') showHome();
        if (typeof Toast !== 'undefined') Toast.success(projectT('projects.projectDeleted', 'Projet supprimé'));
    } catch (error) {
        console.error('[projects] delete project failed', error);
        if (submit) submit.disabled = false;
        setProjectDeleteModalError(projectT('projects.deleteFailed', 'Impossible de supprimer le projet.'));
    }
}

function hideProjectView() {
    activeProjectViewId = null;
    const projectsView = document.getElementById('projects-view');
    if (projectsView) projectsView.style.display = 'none';
    document.body.classList.remove('projects-mode');
}

function showProjectView(projectId) {
    const project = projectById(projectId);
    if (!project) return;
    activeProjectViewId = projectId;

    const homeView = document.getElementById('home-view');
    const chatView = document.getElementById('chat-view');
    const modalView = document.getElementById('modal-view');
    const addonsView = document.getElementById('addons-view');
    const extensionsView = document.getElementById('extensions-view');
    const deployAtlasView = document.getElementById('deployatlas-view');
    const modelsView = document.getElementById('models-view');
    const projectsView = document.getElementById('projects-view');
    if (homeView) homeView.style.display = 'none';
    if (chatView) chatView.style.display = 'none';
    if (modalView) modalView.style.display = 'none';
    if (addonsView) addonsView.style.display = 'none';
    if (extensionsView) extensionsView.style.display = 'none';
    if (deployAtlasView) deployAtlasView.style.display = 'none';
    if (modelsView) modelsView.style.display = 'none';
    if (projectsView) projectsView.style.display = 'flex';

    document.body.classList.remove('addons-mode');
    document.body.classList.remove('extensions-mode');
    document.body.classList.remove('models-mode');
    document.body.classList.remove('modules-mode');
    document.body.classList.remove('signalatlas-mode');
    document.body.classList.remove('perfatlas-mode');
    document.body.classList.remove('cyberatlas-mode');
    document.body.classList.remove('deployatlas-mode');
    document.body.classList.add('projects-mode');
    document.querySelectorAll('.sidebar-hub-btn').forEach(btn => btn.classList.remove('active'));

    renderProjectView(projectId);
    renderChatList();
}

function openProject(projectId) {
    showProjectView(projectId);
}

function refreshProjectView() {
    const view = document.getElementById('projects-view');
    if (!activeProjectViewId || !view || view.style.display === 'none') return;
    const project = projectById(activeProjectViewId);
    if (!project) {
        activeProjectViewId = null;
        if (typeof showHome === 'function') showHome();
        return;
    }
    renderProjectView(activeProjectViewId);
}

function renderProjectView(projectId) {
    const content = document.getElementById('projects-view-content');
    const project = projectById(projectId);
    if (!content || !project) return;

    const chats = chatsForProject(projectId);
    const projectName = escapeHtml(project.name || projectT('projects.untitled', 'Projet sans nom'));
    const chatCount = chats.length;
    const sourceCount = Array.isArray(project.sourceIds) ? project.sourceIds.length : 0;
    const tab = activeProjectTab === 'sources' ? 'sources' : 'chats';

    content.innerHTML = `
        <section class="project-page">
            <div class="project-page-title">
                <i data-lucide="folder"></i>
                <div>
                    <div class="project-page-kicker">${escapeHtml(projectT('projects.title', 'Projets'))}</div>
                    <h1>${projectName}</h1>
                </div>
                <button class="project-page-menu" type="button" onclick="openProjectActionMenu(${escapeHtml(JSON.stringify(projectId))}, event)">
                    <i data-lucide="more-horizontal"></i>
                </button>
            </div>

            <button class="project-new-chat-hero" type="button" onclick="createChatInProject(${escapeHtml(JSON.stringify(projectId))})">
                <i data-lucide="plus"></i>
                <span>${escapeHtml(projectT('projects.newChatInProject', 'Nouveau chat dans {project}', { project: project.name }))}</span>
            </button>

            <div class="project-tabs" role="tablist">
                <button class="project-tab ${tab === 'chats' ? 'active' : ''}" type="button" onclick="setProjectTab('chats')">
                    ${escapeHtml(projectT('projects.chats', 'Chats'))}
                    <span>${chatCount}</span>
                </button>
                <button class="project-tab ${tab === 'sources' ? 'active' : ''}" type="button" onclick="setProjectTab('sources')">
                    ${escapeHtml(projectT('projects.sources', 'Sources'))}
                    <span>${sourceCount}</span>
                </button>
            </div>

            ${tab === 'chats' ? renderProjectChats(chats, projectId) : renderProjectSources(project)}
        </section>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [content] });
}

function renderProjectChats(chats, projectId) {
    if (!chats.length) {
        return `
            <div class="project-empty-state">
                <i data-lucide="message-square-plus"></i>
                <h2>${escapeHtml(projectT('projects.noProjectChats', 'Aucun chat dans ce projet'))}</h2>
                <p>${escapeHtml(projectT('projects.noProjectChatsBody', 'Crée un chat ici pour garder ce contexte séparé des récents.'))}</p>
                <button type="button" onclick="createChatInProject(${escapeHtml(JSON.stringify(projectId))})">${escapeHtml(projectT('projects.newChat', 'Nouveau chat'))}</button>
            </div>
        `;
    }

    return `
        <div class="project-chat-table">
            ${chats.map(record => {
                const chatId = escapeHtml(JSON.stringify(record.id));
                const title = escapeHtml(record.title || projectT('chat.newConversation', 'Nouvelle conversation'));
                const excerpt = escapeHtml(chatExcerpt(record));
                const date = escapeHtml(projectDateLabel(record.updatedAt));
                return `
                    <div class="project-chat-row" onclick="loadChat(${chatId})" role="button" tabindex="0">
                        <div class="project-chat-row-main">
                            <strong>${title}</strong>
                            <span>${excerpt}</span>
                        </div>
                        <time>${date}</time>
                        <button class="project-chat-row-menu" type="button" onclick="openChatListActionMenu(${chatId}, event)" aria-label="${escapeHtml(projectT('projects.chatMenu', 'Actions du chat'))}">
                            <i data-lucide="more-horizontal"></i>
                        </button>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function renderProjectSources(project) {
    return `
        <div class="project-empty-state">
            <i data-lucide="file-text"></i>
            <h2>${escapeHtml(projectT('projects.noSources', 'Aucune source ajoutée'))}</h2>
            <p>${escapeHtml(projectT('projects.sourcesPlaceholder', 'Les fichiers, URLs, notes et contexte projet arriveront ici.'))}</p>
            <button type="button" disabled>${escapeHtml(projectT('projects.addSource', 'Ajouter une source'))}</button>
        </div>
    `;
}

function setProjectTab(tab) {
    activeProjectTab = tab === 'sources' ? 'sources' : 'chats';
    refreshProjectView();
}

async function createChatInProject(projectId) {
    const project = projectById(projectId);
    if (!project) return;
    await createNewChat({ projectId });
    if (typeof Toast !== 'undefined') {
        Toast.success(projectT('projects.chatCreated', 'Chat créé dans {project}', { project: project.name }));
    }
}

async function openProjectActionMenu(projectId, event) {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    closeChatListPopover();

    const project = projectById(projectId) || await getProjectRecord(projectId);
    if (!project) return;

    const point = getChatListAnchorPoint(event);
    const popover = document.createElement('div');
    popover.className = 'chat-list-action-popover project-action-popover';
    popover.setAttribute('role', 'menu');
    popover.dataset.projectId = projectId;

    const expanded = project.expanded !== false;
    popover.innerHTML = `
        <div class="chat-list-action-title">${escapeHtml(project.name || projectT('projects.untitled', 'Projet sans nom'))}</div>
        <button class="chat-list-action-option" type="button" data-action="new-chat"><i data-lucide="message-square-plus"></i><span>${escapeHtml(projectT('projects.newChat', 'Nouveau chat'))}</span></button>
        <button class="chat-list-action-option" type="button" data-action="rename"><i data-lucide="pencil"></i><span>${escapeHtml(projectT('projects.renameProject', 'Renommer le projet'))}</span></button>
        <button class="chat-list-action-option" type="button" data-action="toggle"><i data-lucide="${expanded ? 'chevron-right' : 'chevron-down'}"></i><span>${escapeHtml(expanded ? projectT('projects.collapse', 'Replier') : projectT('projects.expand', 'Déplier'))}</span></button>
        <div class="chat-list-action-separator"></div>
        <button class="chat-list-action-option danger" type="button" data-action="delete"><i data-lucide="trash-2"></i><span>${escapeHtml(projectT('projects.deleteProject', 'Supprimer le projet'))}</span></button>
    `;

    popover.querySelector('[data-action="new-chat"]')?.addEventListener('click', () => {
        closeChatListPopover();
        createChatInProject(projectId);
    });
    popover.querySelector('[data-action="rename"]')?.addEventListener('click', () => openProjectRenameEditor(projectId, event, point));
    popover.querySelector('[data-action="toggle"]')?.addEventListener('click', () => {
        closeChatListPopover();
        setProjectExpanded(projectId, !expanded);
    });
    popover.querySelector('[data-action="delete"]')?.addEventListener('click', async () => {
        closeChatListPopover();
        openProjectDeleteModal(projectId);
    });

    document.body.appendChild(popover);
    chatListPopoverPosition(popover, point.x, point.y);
    attachChatListPopoverLifecycle(popover);
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [popover] });
    popover.querySelector('button')?.focus();
}

function openProjectRenameEditor(projectId, event = null, fallbackPoint = null) {
    event?.preventDefault?.();
    event?.stopPropagation?.();

    const project = projectById(projectId);
    if (!project) return;

    const point = fallbackPoint || getChatListAnchorPoint(event);
    closeChatListPopover();

    const popover = document.createElement('div');
    popover.className = 'chat-list-action-popover chat-list-rename-popover';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', projectT('projects.renameProject', 'Renommer le projet'));
    popover.dataset.projectId = projectId;
    popover.innerHTML = `
        <label class="chat-list-rename-label" for="project-rename-input">${escapeHtml(projectT('projects.renameProject', 'Renommer le projet'))}</label>
        <input id="project-rename-input" class="chat-list-rename-input" type="text" maxlength="80" value="${escapeHtml(project.name || '')}" placeholder="${escapeHtml(projectT('projects.projectNamePlaceholder', 'Nom du projet'))}">
        <div class="chat-list-rename-error" aria-live="polite"></div>
        <div class="chat-list-rename-actions">
            <button class="chat-list-rename-cancel" type="button">${escapeHtml(projectT('common.cancel', 'Annuler'))}</button>
            <button class="chat-list-rename-save" type="button">${escapeHtml(projectT('common.save', 'Enregistrer'))}</button>
        </div>
    `;

    const input = popover.querySelector('.chat-list-rename-input');
    const error = popover.querySelector('.chat-list-rename-error');
    const cancel = popover.querySelector('.chat-list-rename-cancel');
    const save = popover.querySelector('.chat-list-rename-save');

    const commit = async () => {
        const nextName = (input?.value || '').replace(/\s+/g, ' ').trim();
        if (!nextName) {
            input?.classList.add('is-invalid');
            if (error) error.textContent = projectT('projects.nameRequired', 'Le nom du projet est requis.');
            return;
        }
        if (save) save.disabled = true;
        await renameProject(projectId, nextName);
        closeChatListPopover();
        if (typeof Toast !== 'undefined') Toast.success(projectT('projects.projectRenamed', 'Projet renommé'));
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

function buildMoveChatOptions(chatId) {
    const projects = (projectRecordsCache || []).filter(project => !project.archived);
    const noneLabel = escapeHtml(projectT('projects.noProject', 'Aucun projet'));
    const options = [
        `<button class="chat-list-action-option compact" type="button" data-project-id=""><i data-lucide="inbox"></i><span>${noneLabel}</span></button>`
    ];
    for (const project of projects) {
        options.push(`<button class="chat-list-action-option compact" type="button" data-project-id="${escapeHtml(project.id)}"><i data-lucide="folder"></i><span>${escapeHtml(project.name)}</span></button>`);
    }
    return `
        <div class="chat-list-action-group-label">${escapeHtml(projectT('projects.moveToProject', 'Déplacer vers le projet'))}</div>
        <div class="chat-list-action-projects" data-chat-id="${escapeHtml(chatId)}">${options.join('')}</div>
    `;
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
        <div class="chat-list-action-title">${escapeHtml(record.title || projectT('chat.newConversation', 'Nouvelle conversation'))}</div>
        <button class="chat-list-action-option" type="button" data-action="share" disabled>
            <i data-lucide="share"></i><span>${escapeHtml(projectT('projects.share', 'Partager'))}</span>
        </button>
        <button class="chat-list-action-option" type="button" data-action="group" disabled>
            <i data-lucide="user-plus"></i><span>${escapeHtml(projectT('projects.groupChat', 'Démarrer une conversation de groupe'))}</span>
        </button>
        <button class="chat-list-action-option" type="button" data-action="rename">
            <i data-lucide="pencil"></i><span>${escapeHtml(projectT('chat.rename', 'Renommer'))}</span>
        </button>
        ${buildMoveChatOptions(chatId)}
        <div class="chat-list-action-separator"></div>
        <button class="chat-list-action-option" type="button" data-action="pin" disabled>
            <i data-lucide="pin"></i><span>${escapeHtml(projectT('projects.pinChat', 'Épingler le chat'))}</span>
        </button>
        <button class="chat-list-action-option" type="button" data-action="archive">
            <i data-lucide="archive"></i><span>${escapeHtml(projectT('projects.archive', 'Archiver'))}</span>
        </button>
        <button class="chat-list-action-option danger" type="button" data-action="delete">
            <i data-lucide="trash-2"></i><span>${escapeHtml(projectT('chat.delete', 'Supprimer'))}</span>
        </button>
    `;

    popover.querySelector('[data-action="rename"]')?.addEventListener('click', (clickEvent) => openChatRenameEditor(chatId, clickEvent, point));
    popover.querySelector('[data-action="archive"]')?.addEventListener('click', async () => {
        closeChatListPopover();
        await archiveChat(chatId);
    });
    popover.querySelector('[data-action="delete"]')?.addEventListener('click', async () => {
        closeChatListPopover();
        await deleteChat(chatId);
    });
    popover.querySelectorAll('[data-project-id]').forEach(button => {
        button.addEventListener('click', async () => {
            const projectId = button.getAttribute('data-project-id') || null;
            closeChatListPopover();
            await moveChatToProject(chatId, projectId);
            if (typeof Toast !== 'undefined') {
                const project = projectId ? projectById(projectId) : null;
                Toast.success(projectId
                    ? projectT('projects.chatMovedToProject', 'Chat déplacé vers {project}', { project: project?.name || '' })
                    : projectT('projects.chatMovedToRecents', 'Chat replacé dans Récents'));
            }
        });
    });

    document.body.appendChild(popover);
    chatListPopoverPosition(popover, point.x, point.y);
    attachChatListPopoverLifecycle(popover);
    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [popover] });
    popover.querySelector('button:not(:disabled)')?.focus();
}

window.renderSidebarSections = renderSidebarSections;
window.showProjectView = showProjectView;
window.openProject = openProject;
window.refreshProjectView = refreshProjectView;
window.createProjectFromSidebar = createProjectFromSidebar;
window.openProjectCreateModal = openProjectCreateModal;
window.closeProjectCreateModal = closeProjectCreateModal;
window.submitProjectCreateModal = submitProjectCreateModal;
window.openProjectDeleteModal = openProjectDeleteModal;
window.closeProjectDeleteModal = closeProjectDeleteModal;
window.submitProjectDeleteModal = submitProjectDeleteModal;
window.createChatInProject = createChatInProject;
window.toggleProjectExpanded = toggleProjectExpanded;
window.openProjectActionMenu = openProjectActionMenu;
window.toggleSidebarProjectsSection = toggleSidebarProjectsSection;
window.toggleSidebarRecentsSection = toggleSidebarRecentsSection;
window.setProjectTab = setProjectTab;
window.openChatListActionMenu = openChatListActionMenu;

window.addEventListener('joyboy:locale-changed', () => {
    renderSidebarSections();
    refreshProjectView();
});
