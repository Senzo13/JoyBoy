// ===== API - Centralized fetch functions =====

function apiT(key, fallback = '', params = {}) {
    if (window.JoyBoyI18n?.t) return window.JoyBoyI18n.t(key, params, fallback);
    return fallback || key;
}

/**
 * Centralized API module for all fetch calls.
 * Reduces code duplication and provides consistent error handling.
 */

// ===== BASE FUNCTIONS =====

/**
 * Generic POST request
 * @param {string} endpoint - API endpoint
 * @param {object} data - Request body data
 * @param {object} options - Additional fetch options
 * @returns {Promise<{data: any, ok: boolean, error?: string}>}
 */
async function apiPost(endpoint, data = {}, options = {}) {
    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
            ...options
        });
        const result = await response.json();
        return { data: result, ok: response.ok, status: response.status };
    } catch (error) {
        console.error(`[API] POST ${endpoint} failed:`, error);
        return { data: null, ok: false, error: error.message };
    }
}

/**
 * Generic PUT request
 * @param {string} endpoint - API endpoint
 * @param {object} data - Request body data
 * @param {object} options - Additional fetch options
 * @returns {Promise<{data: any, ok: boolean, error?: string}>}
 */
async function apiPut(endpoint, data = {}, options = {}) {
    try {
        const response = await fetch(endpoint, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
            ...options
        });
        const result = await response.json();
        return { data: result, ok: response.ok, status: response.status };
    } catch (error) {
        console.error(`[API] PUT ${endpoint} failed:`, error);
        return { data: null, ok: false, error: error.message };
    }
}

/**
 * Generic GET request
 * @param {string} endpoint - API endpoint
 * @param {object} options - Additional fetch options
 * @returns {Promise<{data: any, ok: boolean, error?: string}>}
 */
async function apiGet(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, {
            method: 'GET',
            ...options
        });
        const result = await response.json();
        return { data: result, ok: response.ok, status: response.status };
    } catch (error) {
        console.error(`[API] GET ${endpoint} failed:`, error);
        return { data: null, ok: false, error: error.message };
    }
}

/**
 * Generic DELETE request
 * @param {string} endpoint - API endpoint
 * @param {object} options - Additional fetch options
 * @returns {Promise<{data: any, ok: boolean, error?: string}>}
 */
async function apiDelete(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, {
            method: 'DELETE',
            ...options
        });
        const result = await response.json();
        return { data: result, ok: response.ok, status: response.status };
    } catch (error) {
        console.error(`[API] DELETE ${endpoint} failed:`, error);
        return { data: null, ok: false, error: error.message };
    }
}

// ===== OLLAMA API =====

const apiOllama = {
    /**
     * Unload a model from VRAM
     * @param {string} model - Model name
     */
    async unload(model) {
        console.log(`[API] Unloading Ollama model: ${model}`);
        return apiPost('/ollama/unload', { model });
    },

    /**
     * Preload a model into VRAM
     * @param {string} model - Model name
     */
    async preload(model) {
        console.log(`[API] Preloading Ollama model: ${model}`);
        return apiPost('/ollama/preload', { model });
    },

    /**
     * Warmup a model (load with minimal context)
     * @param {string} model - Model name
     * @param {boolean} force - Force reload even if already loaded
     */
    async warmup(model, force = false) {
        console.log(`[API] Warming up Ollama model: ${model}`);
        return apiPost('/ollama/warmup', { model, force });
    },

    /**
     * Get Ollama status
     */
    async getStatus() {
        return apiGet('/ollama/status');
    },

    /**
     * Get list of installed Ollama models
     */
    async getModels() {
        return apiGet('/ollama/models');
    },

    /**
     * Search Ollama models
     * @param {string} query - Search query
     */
    async search(query = '') {
        return apiGet(`/ollama/search?q=${encodeURIComponent(query)}`);
    },

    /**
     * Pull/download an Ollama model (streaming)
     * @param {string} model - Model name
     * @returns {Response} - Raw response for streaming
     */
    async pullStream(model) {
        return fetch('/ollama/pull-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
    },

    /**
     * Delete an Ollama model
     * @param {string} model - Model name
     */
    async delete(model) {
        return apiPost('/ollama/delete', { model });
    },

    /**
     * Pull/download an Ollama model (waits for completion)
     * @param {string} model - Model name
     * @returns {Promise<{ok: boolean, error?: string}>}
     */
    async pull(model) {
        console.log(`[API] Pulling Ollama model: ${model}`);
        try {
            const response = await fetch('/ollama/pull-stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model })
            });

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let lastStatus = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const text = decoder.decode(value);
                const lines = text.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.slice(6));
                            if (data.status) lastStatus = data.status;
                            if (data.error) {
                                return { ok: false, error: data.error };
                            }
                        } catch (e) {}
                    }
                }
            }

            return { ok: true, status: lastStatus };
        } catch (error) {
            console.error('[API] Pull failed:', error);
            return { ok: false, error: error.message };
        }
    }
};

// ===== IMAGE MODELS API =====

const apiModels = {
    /**
     * Preload an image model (Stable Diffusion, etc.)
     * @param {string} model - Model name
     */
    async preloadImage(model) {
        console.log(`[API] Preloading image model: ${model}`);
        return apiPost('/models/preload-image', { model });
    },

    /**
     * Unload the current image model
     */
    async unloadImage() {
        console.log('[API] Unloading image model');
        return apiPost('/models/unload-image');
    },

    /**
     * Unload all models (image + Ollama)
     */
    async unloadAll() {
        console.log('[API] Unloading all models');
        return apiPost('/models/unload-all');
    },

    /**
     * Get all models status
     */
    async getStatus() {
        return apiGet('/check-models');
    },

    /**
     * Alias for getStatus (used by settings.js)
     */
    async checkModels() {
        return this.getStatus();
    },

    /**
     * Download an image model
     * @param {string} modelKey - Model key identifier
     */
    async download(modelKey) {
        return apiPost('/models/download', { model_key: modelKey });
    },

    /**
     * Delete an image model
     * @param {string} modelKey - Model key identifier
     */
    async delete(modelKey) {
        return apiPost('/models/delete', { model_key: modelKey });
    }
};

// ===== SETTINGS / HARNESS API =====

const apiSettings = {
    async getProviderStatus(options = {}) {
        const query = options.discoverModels ? '?discover_models=1' : '';
        return apiGet(`/api/providers/status${query}`);
    },

    async getFeatureFlags() {
        return apiGet('/api/features/status');
    },

    async setFeatureFlag(key, value) {
        return apiPost('/api/features/set', { key, value });
    },

    async getPacksStatus() {
        return apiGet('/api/packs/status');
    },

    async getPackEditorPrompts() {
        return apiGet('/api/packs/editor-prompts');
    },

    async setPackActive(packId, enabled = true) {
        return apiPost('/api/packs/activate', { pack_id: packId, enabled });
    },

    async importPackArchive(file, replace = false) {
        try {
            const formData = new FormData();
            formData.append('archive', file);
            formData.append('replace', replace ? 'true' : 'false');
            const response = await fetch('/api/packs/import', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            return { data: result, ok: response.ok, status: response.status };
        } catch (error) {
            console.error('[API] importPackArchive failed:', error);
            return { data: null, ok: false, error: error.message };
        }
    },

    async importPackFromPath(sourcePath, replace = false) {
        return apiPost('/api/packs/import', { source_path: sourcePath, replace });
    },

    async saveProviderSecret(key, value) {
        return apiPost('/api/providers/secret', { key, value });
    },

    async getMcpConfig(options = {}) {
        const query = options.loadTools ? '?load_tools=1' : '';
        return apiGet(`/api/mcp/config${query}`);
    },

    async updateMcpConfig(config) {
        return apiPut('/api/mcp/config', config);
    },

    async testMcpServer(serverName) {
        return apiPost(`/api/mcp/test/${encodeURIComponent(serverName)}`, {});
    },

    async startMcpCliAuth(serverName) {
        return apiPost(`/api/mcp/cli-auth/${encodeURIComponent(serverName)}/start`, {});
    },

    async getBrowserUseStatus() {
        return apiGet('/api/browser-use/status');
    },

    async installBrowserUse(options = {}) {
        return apiPost('/api/browser-use/install', options);
    },

    async browserUseAction(action, payload = {}) {
        return apiPost('/api/browser-use/action', { action, payload });
    },

    async clearProviderSecret(key) {
        return apiPost('/api/providers/secret/clear', { key });
    },

    async setProviderAuthMode(providerId, authMode, key = '') {
        return apiPost('/api/providers/auth-mode', {
            provider_id: providerId,
            auth_mode: authMode,
            key,
        });
    },

    async getHarnessAudit() {
        return apiGet('/api/harness/audit');
    },

    async getDoctorReport() {
        return apiGet('/api/doctor/report');
    },

    async getOnboardingStatus(options = {}) {
        const query = options.includeDoctor ? '?doctor=1' : '';
        return apiGet(`/api/onboarding/status${query}`);
    },

    async completeOnboarding(payload = {}) {
        return apiPost('/api/onboarding/complete', payload);
    },

    async resetOnboarding() {
        return apiPost('/api/onboarding/reset');
    },

    async setLocale(locale) {
        return apiPost('/api/onboarding/locale', { locale });
    },

    async resolveModelSource(source, targetFamily = 'generic') {
        return apiPost('/api/models/import/resolve', {
            source,
            target_family: targetFamily
        });
    },

    async startModelImport(source, targetFamily = 'generic', includeRecommended = true) {
        return apiPost('/api/models/import/start', {
            source,
            target_family: targetFamily,
            include_recommended: includeRecommended
        });
    },

    async getModelImportStatus(jobId = '') {
        const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
        return apiGet(`/api/models/import/status${suffix}`);
    },

    async generatePromptHelper(payload) {
        return apiPost('/api/prompt-helper/generate', payload);
    }
};

// ===== APP / VERSION API =====

const apiApp = {
    async getVersionStatus(refresh = false) {
        const suffix = refresh ? '?refresh=1' : '';
        return apiGet(`/api/version/status${suffix}`);
    },

    async updateAndRestart() {
        return apiPost('/api/version/update', { restart: true });
    }
};

// ===== RUNTIME API =====

const apiRuntime = {
    async getStatus() {
        return apiGet('/api/runtime/status');
    },

    async listJobs(status = '') {
        const suffix = status ? `?status=${encodeURIComponent(status)}` : '';
        return apiGet(`/api/runtime/jobs${suffix}`);
    },

    async getJob(jobId) {
        return apiGet(`/api/runtime/jobs/${encodeURIComponent(jobId)}`);
    },

    async cancelJob(jobId, payload = {}) {
        return apiPost(`/api/runtime/jobs/${encodeURIComponent(jobId)}/cancel`, payload || {});
    },

    async cancelConversationJobs(conversationId) {
        return apiPost(`/api/runtime/conversations/${encodeURIComponent(conversationId)}/cancel-jobs`, {});
    },

    async listConversations() {
        return apiGet('/api/runtime/conversations');
    },

    async createConversation(payload = {}) {
        return apiPost('/api/runtime/conversations', payload);
    },

    async getConversation(conversationId) {
        return apiGet(`/api/runtime/conversations/${encodeURIComponent(conversationId)}`);
    },

    async appendConversationMessage(conversationId, message = {}) {
        return apiPost(`/api/runtime/conversations/${encodeURIComponent(conversationId)}/messages`, message);
    }
};

// ===== MODULES / SIGNALATLAS API =====

const apiModules = {
    async list() {
        return apiGet('/api/modules');
    }
};

function createAuditModuleApi(moduleId) {
    const cleanId = String(moduleId || '').trim().toLowerCase();
    return {
        async listAudits(limit = 40) {
            return apiGet(`/api/${cleanId}/audits?limit=${encodeURIComponent(limit)}`);
        },

        async createAudit(payload = {}) {
            return apiPost(`/api/${cleanId}/audits`, payload);
        },

        async getAudit(auditId) {
            return apiGet(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}`);
        },

        async deleteAudit(auditId) {
            return apiDelete(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}`);
        },

        async rerunAi(auditId, payload = {}) {
            return apiPost(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}/rerun-ai`, payload);
        },

        async compareAi(auditId, payload = {}) {
            return apiPost(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}/compare-ai`, payload);
        },

        async getModelContext() {
            return apiGet(`/api/${cleanId}/models/context`);
        },

        async getProviderStatus(target = '', mode = '') {
            const params = new URLSearchParams();
            if (target) params.set('target', target);
            if (mode) params.set('mode', mode);
            const query = params.toString();
            return apiGet(`/api/${cleanId}/providers/status${query ? `?${query}` : ''}`);
        },

        async importOrganicPotential(auditId, formData) {
            try {
                const response = await fetch(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}/organic-potential/import`, {
                    method: 'POST',
                    body: formData,
                });
                const result = await response.json();
                return { data: result, ok: response.ok, status: response.status };
            } catch (error) {
                console.error(`[API] ${cleanId} organic potential import failed:`, error);
                return { data: null, ok: false, error: error.message };
            }
        },

        async fetchExportText(auditId, formatName = 'prompt') {
            try {
                const response = await fetch(`/api/${cleanId}/audits/${encodeURIComponent(auditId)}/export/${encodeURIComponent(formatName)}`);
                const content = await response.text();
                return { ok: response.ok, data: content, status: response.status };
            } catch (error) {
                console.error(`[API] ${cleanId} export fetch failed:`, error);
                return { ok: false, error: error.message, data: '' };
            }
        }
    };
}

const apiSignalAtlas = createAuditModuleApi('signalatlas');
const apiPerfAtlas = createAuditModuleApi('perfatlas');
const apiCyberAtlas = createAuditModuleApi('cyberatlas');

const apiDeployAtlas = {
    async listServers() {
        return apiGet('/api/deployatlas/servers');
    },
    async saveServer(payload = {}) {
        return apiPost('/api/deployatlas/servers', payload);
    },
    async deleteServer(serverId) {
        return apiDelete(`/api/deployatlas/servers/${encodeURIComponent(serverId)}`);
    },
    async testServer(serverId, payload = {}) {
        return apiPost(`/api/deployatlas/servers/${encodeURIComponent(serverId || 'new')}/test`, payload);
    },
    async analyzeProject(formData) {
        try {
            const response = await fetch('/api/deployatlas/projects/analyze', {
                method: 'POST',
                body: formData,
            });
            const result = await response.json();
            return { data: result, ok: response.ok, status: response.status };
        } catch (error) {
            console.error('[API] DeployAtlas project analysis failed:', error);
            return { data: null, ok: false, error: error.message };
        }
    },
    async listDeployments(limit = 40) {
        return apiGet(`/api/deployatlas/deployments?limit=${encodeURIComponent(limit)}`);
    },
    async createDeployment(payload = {}) {
        return apiPost('/api/deployatlas/deployments', payload);
    },
    async getDeployment(deploymentId) {
        return apiGet(`/api/deployatlas/deployments/${encodeURIComponent(deploymentId)}`);
    },
    async cancelDeployment(deploymentId) {
        return apiPost(`/api/deployatlas/deployments/${encodeURIComponent(deploymentId)}/cancel`, {});
    },
    async getModelContext() {
        return apiGet('/api/deployatlas/models/context');
    },
    async getProviderStatus() {
        return apiGet('/api/deployatlas/providers/status');
    }
};

// ===== TERMINAL API =====

const apiTerminal = {
    async getTools() {
        return apiGet('/terminal/tools');
    }
};

// ===== GENERATION API =====

const apiGeneration = {
    /**
     * POST with AbortSignal support (used by generate, generateEdit, refine)
     */
    async _postWithAbort(endpoint, params, signal = null) {
        const options = signal ? { signal } : {};
        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params),
                ...options
            });
            const result = await response.json();
            return { data: result, ok: response.ok };
        } catch (error) {
            if (error.name === 'AbortError' || signal?.aborted) {
                return { data: null, ok: false, aborted: true };
            }
            return { data: null, ok: false, error: error.message };
        }
    },

    /**
     * Cancel a generation in progress
     * @param {string} generationId - Generation ID
     * @param {string} chatId - Chat ID (optional)
     * @param {boolean} forceUnload - Force unload models after cancel
     */
    async cancel(generationId, chatId = null, forceUnload = false, cancelByChat = false) {
        console.log(`[API] Cancelling generation: ${generationId}`);
        return apiPost('/cancel-generation', {
            generationId,
            chatId,
            forceUnload,
            cancelByChat
        });
    },

    /**
     * Generate image (inpainting or text2img)
     */
    async generate(params, signal = null) {
        return this._postWithAbort('/generate', params, signal);
    },

    /**
     * Generate with edit mask
     */
    async generateEdit(params, signal = null) {
        return this._postWithAbort('/generate-edit', params, signal);
    },

    /**
     * Get generation preview (long polling)
     * @param {number} lastStep - Last received step
     * @param {string} lastPhase - Last received phase ('generation' or 'fine_tuning')
     */
    async getPreview(lastStep = 0, lastPhase = 'generation') {
        return apiGet(`/generate/preview?last_step=${lastStep}&last_phase=${lastPhase}`);
    },

    /**
     * Upscale an image
     * @param {object} params - Upscale parameters
     */
    async upscale(params) {
        return apiPost('/upscale', params);
    },

    /**
     * Expand/outpaint an image
     * @param {object} params - Expand parameters
     */
    async expand(params) {
        return apiPost('/expand', params);
    },

    /**
     * X-ray mask detection (SegFormer clothing segmentation)
     * @param {object} params - { image: base64 }
     */
    async xrayMask(params) {
        return apiPost('/xray-mask', params);
    },

    /**
     * Generate video from image
     * @param {object} params - Video generation parameters
     */
    async generateVideo(params) {
        return apiPost('/generate-video', params);
    },

    /**
     * Register uploaded/pasted video as continuation source
     */
    async registerVideoSource(params) {
        return apiPost('/video-source', params);
    },

    /**
     * Get video generation progress
     */
    async getVideoProgress() {
        return apiGet('/video-progress');
    },

    /**
     * Fix details: ADetailer face detection + per-face re-inpaint at high resolution
     */
    async fixDetails(params, signal = null) {
        return this._postWithAbort('/fix-details', params, signal);
    },

    /**
     * Reset video state
     */
    async resetVideo() {
        return apiPost('/reset-video');
    },

    /**
     * Get video info
     */
    async getVideoInfo() {
        return apiGet('/video-info');
    }
};

// ===== CHAT API =====

const apiChat = {
    /**
     * Stream chat response (returns raw Response for streaming)
     * @param {object} params - Chat parameters
     * @param {AbortSignal} signal - AbortController signal
     * @returns {Response} - Raw response for streaming
     */
    async stream(params, signal = null) {
        const options = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        };
        if (signal) options.signal = signal;
        return fetch('/chat-stream', options);
    },

    /**
     * Get image suggestions based on content
     * @param {string} imageBase64 - Base64 image data
     */
    async getSuggestions(imageBase64) {
        return apiPost('/get-suggestions', {
            image: imageBase64,
            locale: window.JoyBoyI18n?.getLocale?.() || document.documentElement.lang || 'fr'
        });
    },

    /**
     * Delete chat files (videos, etc.)
     * @param {string} chatId - Chat ID
     */
    async deleteFiles(chatId) {
        return apiPost('/delete-chat-files', { chatId });
    }
};

// ===== CONFIG API =====

const apiConfig = {
    /**
     * Get app configuration
     */
    async get() {
        return apiGet('/api/config');
    },

};

// ===== SYSTEM API =====

const apiSystem = {
    /**
     * Cancel all active generations (chat + image + video)
     */
    async cancelAll() {
        return apiPost('/cancel-all');
    },

    /**
     * Hard reset - stops everything and clears all VRAM
     * Cancels generations, unloads all models, clears memory
     * @returns {Promise<{ok: boolean, data: {results: object}}>}
     */
    async hardReset() {
        console.log('[API] Hard reset - stopping all processes');
        return apiPost('/system/hard-reset');
    },

};

// ===== GLOBAL FUNCTIONS =====

/**
 * Restart the backend server
 */
function restartBackend() {
    // Cibler tous les boutons restart (home + chat)
    document.querySelectorAll('.restart-btn').forEach(btn => {
        btn.classList.add('restarting');
    });

    console.log('[SYSTEM] Restarting backend...');

    // Fire and forget - don't wait for response (server will die)
    fetch('/system/restart', { method: 'POST' }).catch(() => {});

    // Show toast
    if (typeof Toast !== 'undefined') {
        Toast.info(apiT('api.restartTitle', 'Redémarrage'), apiT('api.restartBody', 'Le backend redémarre...'), 3000);
    }
}

/**
 * Reset restart buttons state (called on page load)
 */
function resetRestartButtons() {
    document.querySelectorAll('.restart-btn').forEach(btn => {
        btn.classList.remove('restarting');
    });
}
