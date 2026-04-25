// ===== UTILS - Shared utilities =====

/**
 * Centralized utility functions used across the application.
 * Reduces code duplication and provides consistent behavior.
 */

// ===== TOAST NOTIFICATIONS =====

const Toast = {
    /**
     * Show a toast notification
     * @param {string} title - Toast title
     * @param {string} message - Toast message (optional)
     * @param {string} type - Toast type: 'success', 'error', 'info'
     * @param {number} duration - Duration in ms (default: 4000)
     */
    show(title, message = '', type = 'info', duration = 4000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const icons = {
            success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
            error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
            info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
        };

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <div class="toast-icon">${icons[type] || icons.info}</div>
            <div class="toast-content">
                <div class="toast-title">${title}</div>
                ${message ? `<div class="toast-message">${message}</div>` : ''}
            </div>
            <button class="toast-close" onclick="this.parentElement.classList.add('hide')">×</button>
        `;

        container.appendChild(toast);

        // Auto remove
        setTimeout(() => {
            toast.classList.add('hide');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    success(title, message = '', duration = 4000) {
        this.show(title, message, 'success', duration);
    },

    error(title, message = '', duration = 4000) {
        this.show(title, message, 'error', duration);
    },

    info(title, message = '', duration = 4000) {
        this.show(title, message, 'info', duration);
    }
};

// ===== SHARED DIALOG =====

const JoyDialog = (() => {
    let elements = null;
    let activeRequest = null;
    let lastFocusedElement = null;
    const queue = [];

    function translate(key, fallback, params = {}) {
        return window.JoyBoyI18n?.t?.(key, params, fallback) || fallback;
    }

    function ensureElements() {
        if (elements) return elements;

        const root = document.getElementById('joy-dialog');
        if (!root) return null;

        elements = {
            root,
            panel: root.querySelector('.joy-dialog-panel'),
            title: document.getElementById('joy-dialog-title'),
            message: document.getElementById('joy-dialog-message'),
            cancelBtn: document.getElementById('joy-dialog-cancel-btn'),
            confirmBtn: document.getElementById('joy-dialog-confirm-btn'),
        };
        elements.inputWrap = document.createElement('label');
        elements.inputWrap.className = 'joy-dialog-input-wrap';
        elements.inputWrap.hidden = true;
        elements.input = document.createElement('input');
        elements.input.className = 'joy-dialog-input';
        elements.input.type = 'text';
        elements.input.autocomplete = 'off';
        elements.inputWrap.appendChild(elements.input);
        elements.message?.insertAdjacentElement('afterend', elements.inputWrap);

        elements.cancelBtn?.addEventListener('click', () => close(false));
        elements.confirmBtn?.addEventListener('click', () => close(true));

        elements.root.addEventListener('click', (event) => {
            if (event.target === elements.root) {
                close(false);
            }
        });

        document.addEventListener('keydown', handleKeydown);
        window.addEventListener('joyboy:locale-changed', () => {
            if (activeRequest) {
                render(activeRequest.options);
            }
        });

        return elements;
    }

    function handleKeydown(event) {
        if (!activeRequest) return;

        if (event.key === 'Escape') {
            event.preventDefault();
            close(false);
            return;
        }

        if (event.key === 'Enter') {
            const targetTag = document.activeElement?.tagName;
            if (targetTag === 'TEXTAREA') return;
            event.preventDefault();
            const refs = ensureElements();
            close(document.activeElement !== refs?.cancelBtn);
        }
    }

    function getDefaultTitle(options) {
        if (options.title) return options.title;

        if (options.type === 'confirm') {
            return translate(
                options.variant === 'danger' ? 'common.warning' : 'common.notice',
                options.variant === 'danger' ? 'Warning' : 'Notice'
            );
        }

        if (options.variant === 'danger') {
            return translate('common.error', 'Error');
        }

        return translate('common.notice', 'Notice');
    }

    function getConfirmLabel(options) {
        if (options.confirmLabel) return options.confirmLabel;
        if (options.type === 'confirm') {
            return translate(
                options.variant === 'danger' ? 'common.delete' : 'common.confirm',
                options.variant === 'danger' ? 'Delete' : 'Confirm'
            );
        }
        if (options.type === 'prompt') {
            return translate('common.save', 'Save');
        }
        return translate('common.ok', 'OK');
    }

    function render(options) {
        const refs = ensureElements();
        if (!refs) return;

        const isConfirm = options.type === 'confirm';
        const isPrompt = options.type === 'prompt';
        const title = getDefaultTitle(options);

        refs.title.textContent = title || '';
        refs.title.classList.toggle('is-hidden', !title);
        refs.message.textContent = options.message || '';
        refs.inputWrap.hidden = !isPrompt;
        if (isPrompt) {
            refs.input.value = String(options.defaultValue || '');
            refs.input.placeholder = options.placeholder || '';
            refs.input.maxLength = Number(options.maxLength || 0) > 0 ? Number(options.maxLength) : 1000;
        } else {
            refs.input.value = '';
            refs.input.placeholder = '';
            refs.input.removeAttribute('maxLength');
        }
        refs.cancelBtn.hidden = !(isConfirm || isPrompt);
        refs.cancelBtn.textContent = options.cancelLabel || translate('common.cancel', 'Cancel');
        refs.confirmBtn.textContent = getConfirmLabel(options);
        refs.confirmBtn.classList.toggle('is-danger', options.variant === 'danger');
        refs.root.dataset.variant = options.variant || 'default';
    }

    function showNext() {
        if (activeRequest || queue.length === 0) return;

        activeRequest = queue.shift();
        render(activeRequest.options);

        const refs = ensureElements();
        if (!refs) {
            const fallbackResult = activeRequest.options.type === 'confirm'
                ? false
                : activeRequest.options.type === 'prompt' ? null : true;
            activeRequest.resolve(fallbackResult);
            activeRequest = null;
            showNext();
            return;
        }

        lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        document.body.classList.add('joy-dialog-open');
        refs.root.classList.add('is-open');
        refs.root.setAttribute('aria-hidden', 'false');

        requestAnimationFrame(() => {
            const target = activeRequest.options.type === 'prompt'
                ? refs.input
                : activeRequest.options.type === 'confirm' ? refs.cancelBtn : refs.confirmBtn;
            target?.focus();
            if (activeRequest.options.type === 'prompt') refs.input?.select?.();
        });
    }

    function close(result) {
        if (!activeRequest) return;

        const refs = ensureElements();
        if (refs) {
            refs.root.classList.remove('is-open');
            refs.root.setAttribute('aria-hidden', 'true');
        }
        document.body.classList.remove('joy-dialog-open');

        const { resolve, options } = activeRequest;
        activeRequest = null;

        if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
            lastFocusedElement.focus();
        }
        lastFocusedElement = null;

        if (options.type === 'confirm') {
            resolve(Boolean(result));
        } else if (options.type === 'prompt') {
            resolve(result ? (refs?.input?.value ?? '') : null);
        } else {
            resolve(true);
        }

        showNext();
    }

    function enqueue(options) {
        return new Promise((resolve) => {
            queue.push({ options, resolve });
            showNext();
        });
    }

    return {
        alert(message, options = {}) {
            return enqueue({ ...options, type: 'alert', message });
        },
        confirm(message, options = {}) {
            return enqueue({ ...options, type: 'confirm', message });
        },
        prompt(message, options = {}) {
            return enqueue({ ...options, type: 'prompt', message });
        },
    };
})();

window.JoyDialog = JoyDialog;

// ===== SHARED TOOLTIP =====

const JoyTooltip = (() => {
    let elements = null;
    let activeTrigger = null;

    function ensureElements() {
        if (elements) return elements;

        const root = document.getElementById('joy-tooltip');
        const inner = document.getElementById('joy-tooltip-inner');
        if (!root || !inner) return null;

        elements = { root, inner };
        return elements;
    }

    function normalizeTrigger(element) {
        if (!(element instanceof HTMLElement)) return null;

        const title = element.getAttribute('title');
        if (title) {
            element.setAttribute('data-tooltip', title);
            if (!element.getAttribute('aria-label')) {
                element.setAttribute('aria-label', title);
            }
            element.removeAttribute('title');
        }

        return element;
    }

    function scanTitles(root = document) {
        if (root instanceof HTMLElement) {
            normalizeTrigger(root);
        }
        root.querySelectorAll?.('[title]').forEach(normalizeTrigger);
    }

    function getTriggerFromNode(node) {
        if (!(node instanceof Element)) return null;
        return node.closest('[data-tooltip], [title]');
    }

    function getTooltipText(element) {
        if (!(element instanceof HTMLElement)) return '';
        normalizeTrigger(element);
        return (element.getAttribute('data-tooltip') || '').trim();
    }

    function hide() {
        const refs = ensureElements();
        if (!refs) return;
        refs.root.classList.remove('is-open');
        refs.root.setAttribute('aria-hidden', 'true');
        activeTrigger = null;
    }

    function position(trigger) {
        const refs = ensureElements();
        if (!refs || !trigger) return;

        const margin = 10;
        const rect = trigger.getBoundingClientRect();
        const tooltipRect = refs.root.getBoundingClientRect();
        let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);
        left = Math.max(12, Math.min(left, window.innerWidth - tooltipRect.width - 12));

        let top = rect.top - tooltipRect.height - margin;
        refs.root.dataset.placement = 'top';
        if (top < 12) {
            top = rect.bottom + margin;
            refs.root.dataset.placement = 'bottom';
        }

        refs.root.style.left = `${Math.round(left)}px`;
        refs.root.style.top = `${Math.round(top)}px`;
    }

    function show(trigger) {
        const refs = ensureElements();
        if (!refs) return;

        const text = getTooltipText(trigger);
        if (!text) {
            hide();
            return;
        }

        activeTrigger = trigger;
        refs.inner.textContent = text;
        refs.root.classList.add('is-open');
        refs.root.setAttribute('aria-hidden', 'false');
        refs.root.style.left = '0px';
        refs.root.style.top = '0px';
        requestAnimationFrame(() => position(trigger));
    }

    function init() {
        ensureElements();
        scanTitles();

        document.addEventListener('mouseover', (event) => {
            const trigger = getTriggerFromNode(event.target);
            if (!trigger) {
                hide();
                return;
            }
            if (trigger !== activeTrigger) {
                show(trigger);
            }
        });

        document.addEventListener('mouseout', (event) => {
            if (!activeTrigger) return;
            const next = event.relatedTarget;
            if (next instanceof Node && activeTrigger.contains(next)) return;
            const leaving = getTriggerFromNode(event.target);
            if (leaving && leaving === activeTrigger) {
                hide();
            }
        });

        document.addEventListener('focusin', (event) => {
            const trigger = getTriggerFromNode(event.target);
            if (trigger) show(trigger);
        });

        document.addEventListener('focusout', (event) => {
            const trigger = getTriggerFromNode(event.target);
            if (trigger && trigger === activeTrigger) {
                hide();
            }
        });

        window.addEventListener('scroll', () => {
            if (activeTrigger) position(activeTrigger);
        }, true);

        window.addEventListener('resize', () => {
            if (activeTrigger) position(activeTrigger);
        });

        window.addEventListener('joyboy:locale-changed', () => {
            scanTitles();
            if (activeTrigger) show(activeTrigger);
        });

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach((node) => {
                        if (node instanceof HTMLElement) {
                            scanTitles(node);
                        }
                    });
                } else if (mutation.type === 'attributes' && mutation.target instanceof HTMLElement) {
                    normalizeTrigger(mutation.target);
                }
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['title', 'data-tooltip'],
        });
    }

    return {
        init,
        show,
        hide,
        rescan: scanTitles,
    };
})();

window.JoyTooltip = JoyTooltip;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => JoyTooltip.init(), { once: true });
} else {
    JoyTooltip.init();
}

// ===== DOM HELPERS =====

const DOM = {
    /**
     * Get element by ID
     * @param {string} id - Element ID
     * @returns {HTMLElement|null}
     */
    get(id) {
        return document.getElementById(id);
    },

    /**
     * Query selector shorthand
     * @param {string} selector - CSS selector
     * @param {HTMLElement} parent - Parent element (default: document)
     * @returns {HTMLElement|null}
     */
    $(selector, parent = document) {
        return parent.querySelector(selector);
    },

    /**
     * Query selector all shorthand
     * @param {string} selector - CSS selector
     * @param {HTMLElement} parent - Parent element (default: document)
     * @returns {NodeList}
     */
    $$(selector, parent = document) {
        return parent.querySelectorAll(selector);
    },

    /**
     * Show element (remove hidden class or set display)
     * @param {string|HTMLElement} el - Element ID or element
     */
    show(el) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.classList.remove('hidden');
            if (element.style.display === 'none') {
                element.style.display = '';
            }
        }
    },

    /**
     * Hide element (add hidden class)
     * @param {string|HTMLElement} el - Element ID or element
     */
    hide(el) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.classList.add('hidden');
        }
    },

    /**
     * Toggle element visibility
     * @param {string|HTMLElement} el - Element ID or element
     * @param {boolean} show - Force show/hide (optional)
     */
    toggle(el, show = undefined) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            if (show === undefined) {
                element.classList.toggle('hidden');
            } else {
                show ? this.show(element) : this.hide(element);
            }
        }
    },

    /**
     * Set element enabled/disabled state with visual feedback
     * @param {string|HTMLElement} el - Element ID or element
     * @param {boolean} enabled - Enable state
     */
    setEnabled(el, enabled) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.style.opacity = enabled ? '1' : '0.4';
            element.style.pointerEvents = enabled ? 'auto' : 'none';
            if (element.disabled !== undefined) {
                element.disabled = !enabled;
            }
        }
    },

    /**
     * Add class to element
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} className - Class name to add
     */
    addClass(el, className) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.classList.add(className);
        }
    },

    /**
     * Remove class from element
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} className - Class name to remove
     */
    removeClass(el, className) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.classList.remove(className);
        }
    },

    /**
     * Toggle class on element
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} className - Class name to toggle
     * @param {boolean} force - Force add/remove (optional)
     */
    toggleClass(el, className, force = undefined) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.classList.toggle(className, force);
        }
    },

    /**
     * Check if element has class
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} className - Class name to check
     * @returns {boolean}
     */
    hasClass(el, className) {
        const element = typeof el === 'string' ? this.get(el) : el;
        return element ? element.classList.contains(className) : false;
    },

    /**
     * Set element text content
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} text - Text content
     */
    setText(el, text) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.textContent = text;
        }
    },

    /**
     * Set element HTML content
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} html - HTML content
     */
    setHtml(el, html) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element) {
            element.innerHTML = html;
        }
    },

    /**
     * Set element value (for inputs)
     * @param {string|HTMLElement} el - Element ID or element
     * @param {string} value - Value to set
     */
    setValue(el, value) {
        const element = typeof el === 'string' ? this.get(el) : el;
        if (element && element.value !== undefined) {
            element.value = value;
        }
    },

    /**
     * Get element value (for inputs)
     * @param {string|HTMLElement} el - Element ID or element
     * @returns {string}
     */
    getValue(el) {
        const element = typeof el === 'string' ? this.get(el) : el;
        return element ? element.value || '' : '';
    }
};

// ===== STRING HELPERS =====

const Str = {
    /**
     * Truncate string with ellipsis
     * @param {string} str - String to truncate
     * @param {number} maxLength - Maximum length
     * @returns {string}
     */
    truncate(str, maxLength) {
        if (!str || str.length <= maxLength) return str;
        return str.slice(0, maxLength) + '...';
    },

    /**
     * Format bytes to human readable
     * @param {number} bytes - Bytes
     * @param {number} decimals - Decimal places
     * @returns {string}
     */
    formatBytes(bytes, decimals = 1) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
    },

    /**
     * Format duration in milliseconds to readable string
     * @param {number} ms - Milliseconds
     * @returns {string}
     */
    formatDuration(ms) {
        if (ms < 1000) return `${ms}ms`;
        return `${(ms / 1000).toFixed(1)}s`;
    },

    /**
     * Generate a UUID v4
     * @returns {string}
     */
    uuid() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }
};

// ===== HTML HELPERS =====

/**
 * Escape HTML special characters to prevent XSS
 * @param {string} text - Raw text to escape
 * @returns {string} HTML-safe string
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===== VIDEO PROGRESS POLLING =====

let _videoProgressInterval = null;

/**
 * Start polling video generation progress (reusable across all video gen functions)
 * @param {Function} onProgress - Callback with progress data (default: updateVideoSkeletonProgress)
 * @param {number} intervalMs - Polling interval (default: 500)
 * @returns {void}
 */
function startVideoProgressPolling(onProgress = null, intervalMs = 500) {
    stopVideoProgressPolling();
    // Video progress is a single global backend state. Frontend consumers must
    // map it to the newest active skeleton, otherwise old chat messages can steal
    // updates from the generation currently running.
    _videoProgressInterval = setInterval(async () => {
        try {
            const result = await apiGeneration.getVideoProgress();
            if (result.data?.active) {
                const callback = onProgress || (typeof updateVideoSkeletonProgress === 'function' ? updateVideoSkeletonProgress : null);
                if (callback) callback(result.data);
            }
        } catch (e) { /* ignore polling errors */ }
    }, intervalMs);
}

/**
 * Stop video progress polling
 */
function stopVideoProgressPolling() {
    if (_videoProgressInterval) {
        clearInterval(_videoProgressInterval);
        _videoProgressInterval = null;
    }
}
