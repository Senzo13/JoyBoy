// ===== SETTINGS CONTEXT - Centralized settings management =====
// Single source of truth for all user settings.
// Auto-saves to localStorage, supports subscribe/notify pattern.
// Provides a Proxy-based `userSettings` for full backward compatibility.

const JoyBoyContextSizes = Object.freeze({
    min: 2048,
    max: 262144,
    step: 2048,
    options: Object.freeze([
        { value: 2048, label: '2K', infoKey: 'vramExtra0' },
        { value: 4096, label: '4K', infoKey: 'vramExtra1' },
        { value: 8192, label: '8K', infoKey: 'vramExtra2' },
        { value: 16384, label: '16K', infoKey: 'vramExtra4' },
        { value: 32768, label: '32K', infoKey: 'vramExtra8' },
        { value: 65536, label: '64K', infoKey: 'vramExtra16' },
        { value: 131072, label: '128K', infoKey: 'vramExtra32' },
        { value: 262144, label: '256K', infoKey: 'vramExtra64' },
    ]),
    normalize(value) {
        const parsed = Number.parseInt(value, 10);
        const safe = Number.isFinite(parsed) ? parsed : 4096;
        const clamped = Math.min(this.max, Math.max(this.min, safe));
        return Math.round(clamped / this.step) * this.step;
    },
    format(value) {
        const normalized = this.normalize(value);
        if (normalized >= 1024) return `${Math.round(normalized / 1024)}K`;
        return String(normalized);
    },
    optionFor(value) {
        const normalized = this.normalize(value);
        return this.options.find(option => option.value === normalized) || null;
    },
});

window.JoyBoyContextSizes = JoyBoyContextSizes;

class SettingsContext {
    constructor() {
        this._subscribers = new Map();
        this._saveTimer = null;

        // Default values — mirrors the old userSettings object in state.js
        this._defaults = {
            chatModel: 'qwen3.5:2b',
            showActionBar: false,
            privacyDefault: false,
            steps: 35,
            strength: 0.80,
            nsfwStrength: 0.90,
            dilation: 30,
            maskEnabled: true,
            enhancePrompt: true,
            enhanceMode: 'light',
            text2imgSteps: 30,
            text2imgGuidance: 7.5,
            faceRefScale: 0.35,
            styleRefScale: 0.55,
            text2imgModel: 'epiCRealism XL',
            videoModel: 'svd',
            showAdvancedVideoModels: false,
            videoDuration: 5,
            videoFps: 24,
            videoSteps: 30,
            videoRefine: 0,
            videoAudio: false,
            faceRestore: 'off',
            videoQuality: '720p',
            backend: 'diffusers',
            ggufQuant: 'Q6_K',
            loraNsfwEnabled: false,
            loraNsfwStrength: 0.17,
            loraSkinEnabled: false,
            loraSkinStrength: 0.12,
            loraBreastsEnabled: false,
            loraBreastsStrength: 0.70,
            controlnetDepth: 0.54,
            compositeRadius: null,
            skipAutoRefine: true,
            terminalModel: null,
            terminalReasoningEffort: 'medium',
            terminalPermissionMode: 'default',
            workspaces: [],
            activeWorkspace: null,
            contextSize: 4096,
            tunnelEnabled: false,
            segformerVariant: 'fusion',
            // Formerly separate localStorage keys — now unified
            privacyMode: false,
            lastModel: null,
            selectedInpaintModel: 'epiCRealism XL (Moyen)',
            selectedText2ImgModel: 'epiCRealism XL',
            selectedVisionModel: null,
            sidebarCollapsed: true,
            editSelectedModel: null,
            exportFormat: 'auto',
            exportWidth: 768,
            exportHeight: 1344,
            exportGuidanceType: 'human',
            exportView: 'auto',
            exportPose: 'none',
            exportPresets: {},
        };

        this._data = {};
        this._load();
    }

    get(key) {
        return key in this._data ? this._data[key] : this._defaults[key];
    }

    set(key, value) {
        const old = this.get(key);
        this._data[key] = value;
        if (old !== value) {
            this._notify(key, value, old);
        }
        this._scheduleSave();
        return true;
    }

    getAll() {
        return { ...this._defaults, ...this._data };
    }

    reset(key) {
        if (key !== undefined) {
            const old = this.get(key);
            delete this._data[key];
            const val = this._defaults[key];
            if (old !== val) this._notify(key, val, old);
        } else {
            const snapshot = { ...this._data };
            this._data = {};
            for (const k of Object.keys(snapshot)) {
                const val = this._defaults[k];
                if (snapshot[k] !== val) this._notify(k, val, snapshot[k]);
            }
        }
        this._scheduleSave();
    }

    subscribe(key, callback) {
        if (!this._subscribers.has(key)) {
            this._subscribers.set(key, []);
        }
        this._subscribers.get(key).push(callback);
    }

    unsubscribe(key, callback) {
        const cbs = this._subscribers.get(key);
        if (!cbs) return;
        const idx = cbs.indexOf(callback);
        if (idx !== -1) cbs.splice(idx, 1);
    }

    _notify(key, value, old) {
        const cbs = this._subscribers.get(key);
        if (cbs) {
            for (const cb of cbs) {
                try { cb(value, old, key); } catch (e) { console.error('[Settings] Subscriber error:', e); }
            }
        }
    }

    _scheduleSave() {
        if (this._saveTimer) clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => this._save(), 150);
    }

    _save() {
        try {
            localStorage.setItem('userSettings', JSON.stringify(this._data));
        } catch (e) {
            console.error('[Settings] Save error:', e);
        }
    }

    _load() {
        // 1. Load existing blob
        try {
            const saved = localStorage.getItem('userSettings');
            if (saved) {
                this._data = JSON.parse(saved);
            }
        } catch (e) {
            console.error('[Settings] Load error:', e);
            this._data = {};
        }

        // 2. Migrate separate localStorage keys into the blob
        const migrations = {
            privacyMode:          (v) => v === 'true' || v === true,
            lastModel:            (v) => v,
            selectedInpaintModel: (v) => v,
            selectedText2ImgModel:(v) => v,
            selectedVisionModel:  (v) => v,
            sidebarCollapsed:     (v) => v === 'true' || v === true,
            editSelectedModel:    (v) => v,
        };

        let migrated = false;
        for (const [key, transform] of Object.entries(migrations)) {
            // Only migrate if not already present in the blob
            if (!(key in this._data)) {
                const raw = localStorage.getItem(key);
                if (raw !== null) {
                    this._data[key] = transform(raw);
                    migrated = true;
                }
            }
            // Remove old separate key regardless (cleanup)
            localStorage.removeItem(key);
        }

        // 3. Apply privacyDefault → privacyMode at startup
        if (this.get('privacyDefault') && !this.get('privacyMode')) {
            this._data.privacyMode = true;
            migrated = true;
        }

        // 4. Old builds defaulted MMAudio to ON. Flip it once so existing installs
        // inherit the new safer default, while preserving future manual changes.
        try {
            const audioMigrationKey = 'joyboyVideoAudioDefaultOffMigrated';
            if (localStorage.getItem(audioMigrationKey) !== '1') {
                this._data.videoAudio = false;
                localStorage.setItem(audioMigrationKey, '1');
                migrated = true;
            }
        } catch (e) {
            console.warn('[Settings] Video audio migration skipped:', e);
        }

        // 5. FaceRef is now smart-capped server-side. Reset old aggressive local
        // values once so users do not keep a misleading high slider from older builds.
        try {
            const faceRefMigrationKey = 'joyboyFaceRefSmartCapMigrated';
            if (localStorage.getItem(faceRefMigrationKey) !== '1') {
                const rawFaceScale = parseFloat(this._data.faceRefScale ?? this._defaults.faceRefScale);
                if (Number.isFinite(rawFaceScale) && rawFaceScale > 0.35) {
                    this._data.faceRefScale = 0.35;
                    migrated = true;
                }
                localStorage.setItem(faceRefMigrationKey, '1');
            }
        } catch (e) {
            console.warn('[Settings] FaceRef migration skipped:', e);
        }

        // 6. Save if we migrated anything
        if (migrated) {
            this._save();
        }

        console.log('[Settings] Loaded', Object.keys(this._data).length, 'settings');
    }
}

// ===== GLOBAL SINGLETON =====
window.Settings = new SettingsContext();

// ===== PROXY-BASED userSettings (full backward compatibility) =====
// All existing code like `userSettings.steps = 35` or `userSettings.steps`
// continues to work transparently through this Proxy.
window.userSettings = new Proxy({}, {
    get(_, key) {
        return Settings.get(key);
    },
    set(_, key, value) {
        return Settings.set(key, value);
    },
    has(_, key) {
        return key in Settings._data || key in Settings._defaults;
    },
    ownKeys() {
        return Object.keys(Settings.getAll());
    },
    getOwnPropertyDescriptor(_, key) {
        if (key in Settings._data || key in Settings._defaults) {
            return { configurable: true, enumerable: true, value: Settings.get(key) };
        }
    }
});

// ===== BACKWARD COMPAT: privacyMode as global =====
// Code that reads `privacyMode` (the global variable) still works
// because state.js will define it as a getter.
