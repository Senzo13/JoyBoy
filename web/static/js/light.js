/* JoyBoy Light: UI calls the same Studio operations as the MCP server. */
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="joyboy-token"]').content;
const canvas = $('mask');
const ctx = canvas.getContext('2d', { willReadFrequently: true });
let active = null, before = null, threadId = null, exposure = {}, busy = false;
let history = [], stroke = null;

async function api(path, body, method = 'POST') {
    const options = { method, headers: { 'X-JoyBoy-Token': token } };
    if (body instanceof FormData) options.body = body;
    else if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    const response = await fetch(`/api/${path}`, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'La requête a échoué');
    return result;
}
function notice(error) {
    $('notice').textContent = error.message || error;
    $('notice').hidden = false;
}
function locks() {
    document.querySelectorAll('[data-feature]').forEach(button => {
        const feature = exposure[button.dataset.feature];
        button.disabled = busy || !feature || feature.locked;
        button.title = feature?.locked ? feature.reason : '';
    });
    $('edit').disabled ||= !active;
    $('candidate').disabled = busy || !active;
    $('upload').disabled = busy;
    $('refresh').disabled = busy;
    $('new-chat').disabled = busy;
    canvas.style.pointerEvents = busy ? 'none' : '';
}
async function run(operation) {
    if (busy) return;
    busy = true; locks(); $('notice').hidden = true;
    try { return await operation(); }
    catch (error) { notice(error); }
    finally { busy = false; locks(); }
}
async function refresh() {
    const images = await api('images', undefined, 'GET');
    $('gallery').replaceChildren();
    images.forEach(image => {
        const button = document.createElement('button');
        button.className = `thumb${image.id === active?.id ? ' active' : ''}`;
        button.title = `${image.name || 'Image'} · ${image.width} × ${image.height}`;
        button.setAttribute('aria-label', button.title);
        const img = document.createElement('img');
        img.src = `/assets/${image.id}.png`; img.alt = image.name || 'Image';
        button.append(img); button.onclick = () => { if (!busy) select(image); };
        $('gallery').append(button);
    });
    return images;
}
function select(image) {
    active = image; before = image.parent_id || null; history = [];
    canvas.width = image.width; canvas.height = image.height;
    $('source').src = `/assets/${image.id}.png`;
    $('canvas-wrap').hidden = false; $('empty').hidden = true;
    $('dimensions').textContent = `${image.width} × ${image.height} px · canevas original`;
    $('download').href = `/assets/${image.id}.png`;
    $('download').download = `joyboy-${image.id}.png`; $('download').hidden = false;
    $('compare').disabled = !before; $('compare').textContent = 'Voir l’original';
    const report = image.verification;
    $('verification').hidden = !report;
    if (report) $('verification').textContent = `✓ Dimensions conservées · ${report.protected_pixels_changed} pixel protégé modifié sur ${report.protected_pixels.toLocaleString()} · ${report.selected_pixels_changed.toLocaleString()} pixels modifiés dans la sélection.`;
    locks();
    document.querySelectorAll('.thumb').forEach(button => button.classList.toggle('active', button.querySelector('img').src.endsWith(`${image.id}.png`)));
}
async function upload(file) {
    const data = new FormData(); data.append('image', file);
    return api('import', data);
}
$('upload').onchange = event => run(async () => {
    if (!event.target.files[0]) return;
    select(await upload(event.target.files[0])); await refresh(); event.target.value = '';
});
function point(event) {
    const bounds = canvas.getBoundingClientRect();
    return { x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)),
        y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height)) };
}
canvas.onpointerdown = event => {
    if (!active || busy) return;
    event.preventDefault(); canvas.setPointerCapture(event.pointerId);
    const saved = ctx.getImageData(0, 0, canvas.width, canvas.height);
    history.push(saved); if (history.length > 12) history.shift();
    stroke = { start: point(event), previous: point(event), saved };
    paint(event);
};
function paint(event) {
    if (!stroke) return;
    const p = point(event), mode = $('tool').value;
    if (mode === 'rectangle') {
        ctx.putImageData(stroke.saved, 0, 0); ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = 'white'; ctx.fillRect(stroke.start.x, stroke.start.y, p.x - stroke.start.x, p.y - stroke.start.y);
    } else {
        const radius = Number($('brush').value) / 2;
        const distance = Math.hypot(p.x - stroke.previous.x, p.y - stroke.previous.y);
        const steps = Math.max(1, Math.ceil(distance / Math.max(1, radius / 3)));
        for (let i = 0; i <= steps; i++) JoyBoyMask.dot(ctx,
            stroke.previous.x + (p.x - stroke.previous.x) * i / steps,
            stroke.previous.y + (p.y - stroke.previous.y) * i / steps, radius, mode === 'eraser');
    }
    stroke.previous = p;
}
canvas.onpointermove = paint;
canvas.onpointerup = () => { stroke = null; };
canvas.onpointercancel = () => { stroke = null; };
$('undo').onclick = () => { if (!busy && history.length) ctx.putImageData(history.pop(), 0, 0); };
$('clear').onclick = () => { if (!busy && active) { history.push(ctx.getImageData(0, 0, canvas.width, canvas.height)); if(history.length>12) history.shift(); ctx.clearRect(0, 0, canvas.width, canvas.height); } };
$('show-mask').onchange = event => canvas.classList.toggle('mask-hidden', !event.target.checked);
$('compare').onclick = () => {
    const comparing = $('compare').textContent === 'Voir l’original';
    $('source').src = `/assets/${comparing ? before : active.id}.png`;
    $('compare').textContent = comparing ? 'Voir le résultat' : 'Voir l’original';
};
async function saveMask() {
    if (!active) throw new Error('Ajoutez une image.');
    return api('mask', { asset_id: active.id, mask: JoyBoyMask.export(canvas) });
}
async function accept(result) { select(result); await refresh(); }
$('edit').onclick = () => run(async () => {
    const mask = await saveMask();
    await accept(await api('edit', { asset_id: active.id, mask_id: mask.id, prompt: $('edit-prompt').value }));
});
$('generate').onclick = () => run(async () => accept(await api('generate', { prompt: $('edit-prompt').value })));
$('candidate').onchange = event => run(async () => {
    if (!event.target.files[0]) return;
    const mask = await saveMask(), candidate = await upload(event.target.files[0]);
    await accept(await api('apply', { asset_id: active.id, mask_id: mask.id, candidate_id: candidate.id }));
    event.target.value = '';
});
$('refresh').onclick = () => run(refresh);
function message(text, role) {
    document.querySelector('.chat-intro')?.remove();
    const element = document.createElement('div'); element.className = `message ${role}`;
    element.textContent = text; $('messages').append(element); element.scrollIntoView({ block: 'nearest' });
    return element;
}
$('new-chat').onclick = () => { threadId = null; $('messages').replaceChildren(); };
$('chat-form').onsubmit = event => {
    event.preventDefault();
    run(async () => {
        const text = $('chat-text').value.trim(); if (!text) return;
        if ($('attach').checked && !active) throw new Error('Ajoutez une image à joindre.');
        message(text, 'user'); $('chat-text').value = '';
        const pending = message('Codex réfléchit…', 'assistant');
        try {
            const result = await api('chat', { text, model: $('model').value || null, thread_id: threadId,
                image_ids: $('attach').checked ? [active.id] : [] });
            threadId = result.thread_id; pending.textContent = result.text;
        } catch (error) { pending.textContent = error.message; pending.className = 'message error'; throw error; }
    });
};
async function init() {
    locks();
    const status = await api('status', undefined, 'GET'); exposure = status.feature_exposure;
    $('connection').textContent = status.codex.authenticated ? '● Codex connecté' : '○ Codex à connecter';
    $('image-state').textContent = status.image_api.configured ? 'API Images prête · facturation séparée' : 'API Images verrouillée · clé OpenAI requise';
    (status.codex.models || []).forEach(model => {
        const option = document.createElement('option'); option.value = model.model || model.id;
        option.textContent = model.displayName || option.value;
        option.selected = !!model.isDefault; $('model').append(option);
    });
    locks();
    const images = await refresh();
    if (images.length) select(images[0]);
}
init().catch(notice);
