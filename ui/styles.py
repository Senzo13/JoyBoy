"""
CSS pour interface IA
"""

DARK_THEME_CSS = """
/* ===== RESET GRADIO ===== */
.gradio-container {
    background: #000 !important;
    min-height: 100vh !important;
    max-width: 100% !important;
    padding: 0 !important;
}
.gradio-container > * {
    max-width: 100% !important;
}

/* Supprimer tous les encadrés */
.gr-panel, .gr-box, .gr-form, .gr-block {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

/* ===== CACHER ONGLETS ===== */
.hidden-tabs > .tab-nav {
    display: none !important;
}
.hidden-tabs {
    border: none !important;
}
.tabitem {
    border: none !important;
    background: transparent !important;
}

/* ===== TAB HOME - CENTRE VERTICAL ===== */
.tab-home {
    min-height: 100vh !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    padding: 20px !important;
}

/* Logo */
.logo-container {
    text-align: center;
    margin-bottom: 40px;
}
.logo-text {
    font-size: 52px;
    font-weight: 600;
    color: white;
    letter-spacing: 2px;
}

/* ===== INPUT BAR - UNE SEULE LIGNE ===== */
.home-center {
    width: 100%;
    max-width: 680px;
}
.home-input-col {
    width: 100%;
}

.unified-input-bar {
    background: #1a1a1a !important;
    border: 1px solid #333 !important;
    border-radius: 26px !important;
    padding: 4px 6px 4px 14px !important;
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    gap: 0 !important;
    width: 100% !important;
    position: relative !important;
    z-index: 1 !important;
}

/* Supprimer tout overlay qui bloque */
.unified-input-bar::before,
.unified-input-bar::after,
.unified-input-bar > div::before,
.unified-input-bar > div::after {
    display: none !important;
    pointer-events: none !important;
}

/* Input bar dans Home - 90% largeur ecran */
.tab-home .unified-input-bar {
    max-width: 90vw !important;
    min-width: 500px !important;
}

/* Bouton attach */
.attach-btn {
    background: transparent !important;
    border: none !important;
    color: #555 !important;
    padding: 10px !important;
    min-width: 40px !important;
    max-width: 40px !important;
    font-size: 18px !important;
}
.attach-btn:hover {
    color: #888 !important;
}

/* Miniature image */
.image-thumb-indicator {
    min-width: 0 !important;
}
.thumb-img {
    width: 30px;
    height: 30px;
    border-radius: 6px;
    object-fit: cover;
}

/* INPUT - prend tout l'espace */
.main-prompt-input {
    flex: 1 1 auto !important;
    min-width: 100px !important;
    background: transparent !important;
    border: none !important;
    position: relative !important;
    z-index: 100 !important;
}
.main-prompt-input > div,
.main-prompt-input > div > div {
    position: relative !important;
    z-index: 100 !important;
}
.main-prompt-input input,
.main-prompt-input textarea {
    background: transparent !important;
    border: none !important;
    color: white !important;
    font-size: 15px !important;
    padding: 10px 12px !important;
    width: 100% !important;
    pointer-events: all !important;
    cursor: text !important;
    position: relative !important;
    z-index: 999 !important;
    -webkit-user-select: text !important;
    user-select: text !important;
}
.main-prompt-input input::placeholder,
.main-prompt-input textarea::placeholder {
    color: #666 !important;
}
.main-prompt-input input:focus,
.main-prompt-input textarea:focus {
    outline: none !important;
    box-shadow: none !important;
}

/* DROPDOWN */
.model-select {
    min-width: 160px !important;
    position: relative !important;
    z-index: 500 !important;
}
.model-select > div {
    background: #252525 !important;
    border: 1px solid #444 !important;
    border-radius: 20px !important;
    padding: 6px 12px !important;
}
.model-select input {
    color: #ccc !important;
    font-size: 13px !important;
    cursor: pointer !important;
    background: transparent !important;
    border: none !important;
}
.model-select .options {
    background: #1a1a1a !important;
    border: 1px solid #333 !important;
    border-radius: 8px !important;
    margin-top: 4px !important;
}
.model-select .option {
    color: white !important;
    padding: 10px 14px !important;
}
.model-select .option:hover {
    background: #333 !important;
}

/* Bouton envoi rond */
.send-btn-round {
    width: 40px !important;
    height: 40px !important;
    min-width: 40px !important;
    max-width: 40px !important;
    border-radius: 50% !important;
    background: white !important;
    color: black !important;
    border: none !important;
    font-size: 16px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    margin-left: 8px !important;
}
.send-btn-round:hover {
    background: #e5e5e5 !important;
}

/* ===== CHAT VIEW ===== */
.chat-header {
    padding: 16px 30px;
    display: flex;
    align-items: center;
    position: sticky;
    top: 0;
    background: #000;
    z-index: 50;
}
.back-btn {
    background: transparent !important;
    border: none !important;
    color: white !important;
    font-size: 24px !important;
    padding: 8px !important;
    min-width: 44px !important;
}
.share-btn {
    background: #1a1a1a !important;
    border: 1px solid #333 !important;
    border-radius: 20px !important;
    color: white !important;
    padding: 10px 18px !important;
    font-size: 14px !important;
}

/* Chat container - conversation en haut */
.tab-chat {
    display: flex !important;
    flex-direction: column !important;
    min-height: 100vh !important;
    padding-top: 0 !important;
    justify-content: flex-start !important;
    align-items: stretch !important;
}

/* Message user - a droite, en haut */
.user-msg {
    padding: 20px 40px 10px 40px;
    margin-top: 0 !important;
}
.user-bubble {
    display: flex;
    justify-content: flex-end;
    align-items: flex-start;
    gap: 12px;
}
.bubble-text {
    background: #2563eb;
    border: none;
    border-radius: 18px 18px 4px 18px;
    padding: 12px 16px;
    color: white;
    font-size: 15px;
    max-width: 400px;
}
.bubble-thumb {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    object-fit: cover;
}

/* Reponse AI - a gauche */
.ai-response {
    padding: 10px 40px;
    display: flex;
    justify-content: flex-start;
}

/* Images - reponse IA */
.images-row {
    display: flex !important;
    justify-content: center !important;
    gap: 16px !important;
    padding: 20px 40px !important;
    margin-top: 10px !important;
}
.result-img {
    border-radius: 12px !important;
    overflow: hidden;
}
.result-img img {
    border-radius: 12px !important;
}
.img-col-right {
    position: relative;
}
.expand-btn {
    position: absolute !important;
    bottom: 12px !important;
    right: 12px !important;
    width: 36px !important;
    height: 36px !important;
    min-width: 36px !important;
    border-radius: 50% !important;
    background: rgba(0,0,0,0.7) !important;
    border: none !important;
    color: white !important;
    font-size: 14px !important;
}

/* Zone messages - en haut */
.chat-messages {
    flex: 0 0 auto !important;
    padding-bottom: 120px !important;
    margin-top: 0 !important;
}

/* Input bas chat */
.chat-input-row {
    position: fixed !important;
    bottom: 20px !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    width: 100% !important;
    max-width: 700px !important;
    padding: 0 20px !important;
    z-index: 100 !important;
}
.chat-bar {
    background: #1a1a1a !important;
    width: 100% !important;
}

/* ===== MODAL VIEW ===== */
.tab-modal {
    padding: 0 !important;
}
.modal-header {
    padding: 16px 30px;
    display: flex;
    align-items: center;
}
.modal-btn {
    background: transparent !important;
    border: none !important;
    color: white !important;
    font-size: 18px !important;
    padding: 8px !important;
    min-width: 44px !important;
}
.close-btn {
    background: transparent !important;
    border: none !important;
    color: #666 !important;
    font-size: 22px !important;
    padding: 8px !important;
    min-width: 44px !important;
}
.close-btn:hover {
    color: white !important;
}

.modal-body {
    display: flex;
    justify-content: center;
    padding: 20px 40px;
    gap: 30px;
}
.modal-main {
    display: flex;
    justify-content: center;
    align-items: flex-start;
}
.modal-main-img {
    border-radius: 12px !important;
    max-height: 55vh;
}
.modal-side {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.modal-thumb {
    border-radius: 8px !important;
    border: 2px solid transparent !important;
}
.modal-thumb.selected {
    border-color: #3b82f6 !important;
}
.thumb-label {
    background: transparent !important;
    border: none !important;
    color: #666 !important;
    font-size: 11px !important;
    padding: 2px 0 10px 0 !important;
}

/* Actions */
.modal-actions {
    display: flex !important;
    justify-content: center !important;
    gap: 10px !important;
    padding: 15px 20px !important;
    flex-wrap: wrap !important;
    visibility: visible !important;
    opacity: 1 !important;
}
.modal-actions > div {
    display: contents !important;
}
.action-pill {
    display: inline-flex !important;
    background: #1a1a1a !important;
    border: 1px solid #2a2a2a !important;
    border-radius: 22px !important;
    color: white !important;
    padding: 10px 18px !important;
    font-size: 13px !important;
    min-width: auto !important;
    visibility: visible !important;
    opacity: 1 !important;
}
.action-pill:hover {
    background: #252525 !important;
}

/* Input modal */
.modal-input-row {
    display: flex;
    justify-content: center;
    padding: 10px 20px 30px 20px;
}
.modal-input-row .unified-input-bar {
    max-width: 550px;
    width: 100%;
}

/* ===== LOADING ===== */
.loading-status {
    text-align: center;
    margin-top: 20px;
}
.loading-spinner {
    color: #888;
    font-size: 14px;
    animation: pulse 1.5s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
}

/* ===== GLOBAL ===== */
footer { display: none !important; }
.gr-padded { padding: 0 !important; }

/* Cacher seulement les labels de texte, pas les elements de formulaire */
.label-wrap > span:first-child { display: none !important; }
span.svelte-1gfkn6j { display: none !important; }

/* Forcer les inputs a etre cliquables */
.unified-input-bar * {
    pointer-events: auto !important;
}
"""

# JS pour Ctrl+V
PASTE_JS = """
<script>
document.addEventListener('paste', function(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') !== -1) {
            const blob = items[i].getAsFile();
            const input = document.querySelector('input[type="file"]');
            if (input) {
                const dt = new DataTransfer();
                dt.items.add(new File([blob], 'paste.png', {type:'image/png'}));
                input.files = dt.files;
                input.dispatchEvent(new Event('change', {bubbles:true}));
            }
            e.preventDefault();
            break;
        }
    }
});
</script>
"""

# Icones
ICONS = {
    'attach': '📎',
    'send': '↑',
    'back': '←',
    'share': '↗',
    'expand': '⤢',
    'close': '✕',
    'download': '↓',
    'play': '▶',
    'sparkle': '✨',
    'mountain': '⛰',
    'user': '👤',
    'upscale': '⬆',
    'expand': '⤡',
}
