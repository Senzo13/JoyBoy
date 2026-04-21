// ===== SETTINGS SUBSCRIBERS =====
// Bidirectional synchronization between sidebar controls and settings modal controls.

// ===== SETTINGS SUBSCRIBERS — bidirectional sync sidebar ↔ modal =====

// Steps: sidebar slider ↔ modal slider
Settings.subscribe('steps', (val) => {
    const sidebarSlider = document.getElementById('steps-slider');
    const sidebarValue = document.getElementById('steps-value');
    const modalSlider = document.getElementById('settings-steps');
    const modalValue = document.getElementById('settings-steps-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = val;
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = val;
});

// Strength: sidebar slider ↔ modal slider
Settings.subscribe('strength', (val) => {
    const pct = Math.round(val * 100) + '%';
    const sidebarSlider = document.getElementById('strength-slider');
    const sidebarValue = document.getElementById('strength-value');
    const modalSlider = document.getElementById('settings-strength');
    const modalValue = document.getElementById('settings-strength-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = pct;
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = pct;
});

// Dilation: sidebar slider ↔ modal slider
Settings.subscribe('dilation', (val) => {
    const sidebarSlider = document.getElementById('dilation-slider');
    const sidebarValue = document.getElementById('dilation-value');
    const modalSlider = document.getElementById('settings-dilation');
    const modalValue = document.getElementById('settings-dilation-value');
    if (sidebarSlider) sidebarSlider.value = val;
    if (sidebarValue) sidebarValue.textContent = val + 'px';
    if (modalSlider) modalSlider.value = val;
    if (modalValue) modalValue.textContent = val;
});

// Mask toggle: sidebar ↔ modal
Settings.subscribe('maskEnabled', (val) => {
    const sidebarToggle = document.getElementById('mask-toggle');
    const sliderContainer = document.getElementById('dilation-slider-container');
    if (sidebarToggle) sidebarToggle.classList.toggle('active', val);
    if (sliderContainer) {
        sliderContainer.style.opacity = val ? '1' : '0.4';
        sliderContainer.style.pointerEvents = val ? 'auto' : 'none';
    }
});

// Enhance prompt toggle: sidebar ↔ modal
Settings.subscribe('enhancePrompt', (val) => {
    const sidebarToggle = document.getElementById('enhance-toggle');
    const modalToggle = document.getElementById('toggle-enhance-prompt');
    if (sidebarToggle) sidebarToggle.classList.toggle('active', val);
    if (modalToggle) modalToggle.classList.toggle('active', val);
});

// Video settings
Settings.subscribe('videoDuration', (val) => {
    const slider = document.getElementById('settings-video-duration');
    const display = document.getElementById('settings-video-duration-value');
    if (slider) slider.value = val;
    if (display) display.textContent = val + 's';
});

Settings.subscribe('videoSteps', (val) => {
    const slider = document.getElementById('settings-video-steps');
    const display = document.getElementById('settings-video-steps-value');
    if (slider) slider.value = val;
    if (display) display.textContent = val;
});

// LoRA toggles
Settings.subscribe('loraNsfwEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-nsfw');
    const sliderRow = document.getElementById('lora-nsfw-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

Settings.subscribe('loraSkinEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-skin');
    const sliderRow = document.getElementById('lora-skin-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

Settings.subscribe('loraBreastsEnabled', (val) => {
    const toggle = document.getElementById('toggle-lora-breasts');
    const sliderRow = document.getElementById('lora-breasts-slider-row');
    if (toggle) toggle.classList.toggle('active', val);
    if (sliderRow) sliderRow.style.opacity = val ? '1' : '0.4';
});

// LoRA labels update on model change
Settings.subscribe('selectedInpaintModel', () => updateLoraLabelsForModel());

// Video audio toggle
Settings.subscribe('videoAudio', (val) => {
    const toggle = document.getElementById('toggle-video-audio');
    if (toggle) toggle.classList.toggle('active', val === true);
});

Settings.subscribe('showAdvancedVideoModels', (val) => {
    const toggle = document.getElementById('toggle-show-advanced-video-models');
    if (toggle) toggle.classList.toggle('active', val);
    if (typeof loadVideoModelsForRuntime === 'function') {
        loadVideoModelsForRuntime();
    }
});
