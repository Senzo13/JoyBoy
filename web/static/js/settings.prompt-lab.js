// ===== SETTINGS PROMPT LAB =====
// Prompt Lab media type, prompt helper generation, and copy actions.

// ===== PROMPT LAB =====
// Legacy DOM ids still contain "jailbreak" to avoid a risky template-wide
// migration; all user-facing copy and navigation now call this Prompt Lab.

let _jailbreakMediaType = 'image';

function toggleJailbreakMediaType(type) {
    _jailbreakMediaType = type;
    document.getElementById('prompt-lab-type-image').classList.toggle('active', type === 'image');
    document.getElementById('prompt-lab-type-video').classList.toggle('active', type === 'video');
}

async function generatePromptLabPrompt() {
    const input = document.getElementById('jailbreak-input');
    const text = input.value.trim();
    if (!text) {
        Toast.error(t('settings.promptLab.emptyTitle', 'Brief vide'), t('settings.promptLab.emptyBody', 'Décris ce que tu veux générer avant de lancer l’assistant de prompt.'));
        return;
    }

    const platform = document.getElementById('jailbreak-platform').value;
    const btn = document.getElementById('jailbreak-generate-btn');
    const resultSection = document.getElementById('jailbreak-result-section');

    // Loading state
    btn.disabled = true;
    btn.textContent = t('settings.promptLab.generating', 'Génération...');

    // Envoyer le modèle chat de l'utilisateur pour éviter les 404
    const chatModel = userSettings.chatModel || null;

    const { data, ok } = await apiSettings.generatePromptHelper({
        request: text,
        platform: platform,
        media_type: _jailbreakMediaType,
        model: chatModel
    });

    btn.disabled = false;
    btn.textContent = t('settings.promptLab.generate', 'Générer');

    if (!ok || !data?.success) {
        Toast.error(data?.error || t('settings.promptLab.generationError', 'Erreur de génération'));
        return;
    }

    // Display result
    const platformNames = {
        grok: 'Grok', sora: 'Sora', midjourney: 'Midjourney',
        dalle: 'DALL-E', stable_diffusion: 'Stable Diffusion', ideogram: 'Ideogram'
    };
    document.getElementById('jailbreak-badge-platform').textContent = platformNames[platform] || platform;
    document.getElementById('jailbreak-badge-type').textContent = _jailbreakMediaType === 'image'
        ? t('settings.promptLab.image', 'Image')
        : t('settings.promptLab.video', 'Vidéo');
    document.getElementById('jailbreak-output').textContent = data.prompt;
    // Afficher la version française si disponible
    const frenchEl = document.getElementById('jailbreak-output-fr');
    if (frenchEl) {
        frenchEl.textContent = data.prompt_fr || '';
        frenchEl.style.display = data.prompt_fr ? '' : 'none';
    }
    document.getElementById('jailbreak-tips').textContent = data.tips || '';
    resultSection.style.display = '';
}

async function copyJailbreakPrompt() {
    const text = document.getElementById('jailbreak-output').textContent;
    if (!text) return;

    const btn = document.getElementById('jailbreak-copy-btn');
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        // Fallback for non-HTTPS
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    }
    btn.textContent = `${t('settings.promptLab.copy', 'Copier')} !`;
    btn.style.background = '#22c55e';
    setTimeout(() => { btn.textContent = t('settings.promptLab.copy', 'Copier'); btn.style.background = ''; }, 1500);
}

const generateJailbreakPrompt = generatePromptLabPrompt;
