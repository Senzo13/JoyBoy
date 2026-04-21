// ===== JOYBOY I18N =====
// Lightweight client-side i18n for the current vanilla JS frontend.

(function initJoyBoyI18n() {
    const STORAGE_KEY = 'joyboy.locale';
    const SUPPORTED_LOCALES = ['fr', 'en', 'es', 'it'];
    const DEFAULT_LOCALE = 'fr';

    const DATA = window.JoyBoyI18nData || {};
    const MESSAGES = DATA.messages || { fr: {}, en: {}, es: {}, it: {} };
    const BINDINGS = Array.isArray(DATA.bindings) ? DATA.bindings : [];

    function getNestedValue(obj, path) {
        return String(path || '')
            .split('.')
            .reduce((current, part) => (current && Object.prototype.hasOwnProperty.call(current, part) ? current[part] : undefined), obj);
    }

    function interpolate(template, params = {}) {
        return String(template).replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ''));
    }

    function normalizeLocale(locale) {
        const lower = String(locale || '').trim().toLowerCase();
        if (!lower) return DEFAULT_LOCALE;
        const exact = SUPPORTED_LOCALES.find(item => item === lower);
        if (exact) return exact;
        const prefix = lower.split(/[-_]/)[0];
        return SUPPORTED_LOCALES.includes(prefix) ? prefix : DEFAULT_LOCALE;
    }

    function detectLocale() {
        const candidates = [];
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved) candidates.push(saved);
        } catch (error) {
            console.warn('[I18N] Unable to read locale from localStorage:', error);
        }
        if (Array.isArray(navigator.languages)) candidates.push(...navigator.languages);
        if (navigator.language) candidates.push(navigator.language);
        candidates.push(document.documentElement.lang || DEFAULT_LOCALE, DEFAULT_LOCALE);
        return normalizeLocale(candidates.find(Boolean));
    }

    let currentLocale = detectLocale();

    function t(key, params = {}, fallback = '') {
        const message =
            getNestedValue(MESSAGES[currentLocale], key)
            ?? getNestedValue(MESSAGES[DEFAULT_LOCALE], key)
            ?? fallback
            ?? key;
        return interpolate(message, params);
    }

    function hasStoredLocale() {
        try {
            return Boolean(localStorage.getItem(STORAGE_KEY));
        } catch {
            return false;
        }
    }

    function setElementValue(element, value, attr = 'text') {
        if (!element) return;
        if (attr === 'text') {
            element.textContent = value;
            return;
        }
        if (attr === 'html') {
            element.innerHTML = value;
            return;
        }
        element.setAttribute(attr, value);
    }

    function populateLocaleOptions() {
        const selects = document.querySelectorAll('[data-locale-select]');
        selects.forEach(select => {
            const previous = select.value || currentLocale;
            select.innerHTML = SUPPORTED_LOCALES.map(locale => (
                `<option value="${locale}">${t(`localeNames.${locale}`)}</option>`
            )).join('');
            select.value = normalizeLocale(previous);
        });
    }

    function applyTranslations(root = document) {
        BINDINGS.forEach(({ selector, key, attr = 'text' }) => {
            root.querySelectorAll(selector).forEach(element => {
                setElementValue(element, t(key), attr);
            });
        });

        root.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            if (!key) return;
            const attr = element.getAttribute('data-i18n-attr') || 'text';
            setElementValue(element, t(key), attr);
        });

        root.querySelectorAll('[data-i18n-tooltip]').forEach(element => {
            const key = element.getAttribute('data-i18n-tooltip');
            if (!key) return;
            const value = t(key);
            element.setAttribute('data-tooltip', value);
            element.setAttribute('aria-label', value);
            element.removeAttribute('title');
        });

        populateLocaleOptions();
        document.documentElement.lang = currentLocale;
    }

    function setLocale(locale, options = {}) {
        const { persist = true } = options;
        currentLocale = normalizeLocale(locale);

        if (persist) {
            try {
                localStorage.setItem(STORAGE_KEY, currentLocale);
            } catch (error) {
                console.warn('[I18N] Unable to persist locale:', error);
            }
        }

        applyTranslations();
        window.dispatchEvent(new CustomEvent('joyboy:locale-changed', {
            detail: { locale: currentLocale },
        }));

        return currentLocale;
    }

    window.JoyBoyI18n = {
        locales: [...SUPPORTED_LOCALES],
        defaultLocale: DEFAULT_LOCALE,
        t,
        setLocale,
        getLocale: () => currentLocale,
        hasStoredLocale,
        applyTranslations,
        normalizeLocale,
        _messages: MESSAGES,
        _bindings: BINDINGS,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => applyTranslations(), { once: true });
    } else {
        applyTranslations();
    }
})();
