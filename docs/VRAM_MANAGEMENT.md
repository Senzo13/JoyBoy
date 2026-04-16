# Gestion VRAM - JoyBoy

## Modèles et leur usage VRAM

| Modèle | VRAM | Usage |
|--------|------|-------|
| Utility (qwen2.5:1.5b) | ~1-2 GB | Enhance prompt, image check, memory check |
| Chat (variable) | ~2-5 GB | Conversation texte |
| Inpainting (SDXL) | ~6-10 GB | Modifier une image avec masque |
| Text2Img (SDXL) | ~6-10 GB | Créer une image depuis texte |

---

## Model Picker - 3 Onglets

Le picker de modèles est organisé en **3 onglets distincts**:

| Onglet | Usage | Sauvegarde |
|--------|-------|------------|
| **Inpaint** | Quand une image est dans l'input | `localStorage.selectedInpaintModel` |
| **Text2Img** | Génération depuis texte seul | `localStorage.selectedText2ImgModel` |
| **Chat** | Modèles Ollama pour conversation | `userSettings.chatModel` |

```
┌─────────────────────────────────────────────────────────────┐
│                    MODEL PICKER                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Inpaint]  [Text2Img]  [Chat]                              │
│                                                              │
│  Sélection automatique selon contexte:                      │
│                                                              │
│  ┌─ Image dans input? ─┐                                   │
│  │                      │                                   │
│  ▼ OUI                  ▼ NON                               │
│  Onglet Inpaint         Onglet Text2Img                     │
│  (modèles *Inpaint)     (modèles sans Inpaint)             │
│                                                              │
│  getCurrentImageModel() retourne le bon modèle             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Code source:** `web/static/js/ui.js`
- `INPAINT_MODELS[]` - Liste des modèles inpainting
- `TEXT2IMG_MODELS[]` - Liste des modèles text-to-image
- `CHAT_MODELS[]` - Liste dynamique depuis Ollama
- `getCurrentImageModel()` - Retourne inpaint ou text2img selon contexte

---

## Modèles disponibles

### Inpainting (avec image)

| Modèle | Description | Taille |
|--------|-------------|--------|
| Local Studio Inpaint | Local pack workflow | ~6 GB |
| Juggernaut XL Inpaint | Bonne anatomie | ~6 GB |
| epiCRealism XL Inpaint | Textures réalistes | ~6 GB |
| Pony Diffusion V6 Inpaint | Polyvalent | ~7 GB |
| Waifu Inpaint | Style animé | ~7 GB |
| RealVisXL V4 Inpaint | Réaliste, visages | ~6 GB |
| Fluently XL v3 Inpaint | Rapide | ~6 GB |
| SDXL Inpainting | Standard | ~6 GB |

### Text2Img (sans image)

| Modèle | Description | Taille |
|--------|-------------|--------|
| Juggernaut XL v9 | Anatomie | ~6 GB |
| epiCRealism XL | Réaliste | ~6 GB |
| RealVisXL V4 | Réaliste | ~6 GB |
| SDXL Turbo | Rapide (4 steps) | ~6 GB |

---

## Flux au démarrage (PAGE LOAD / REFRESH)

```
┌─────────────────────────────────────────────────────────────┐
│                    PAGE LOAD / REFRESH                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. app.js init()                                            │
│     │                                                        │
│     ├──► /models/unload-all (POST)                          │
│     │    └── Décharge TOUS les modèles (sécurité)           │
│     │        - unload_all_image_models()                    │
│     │        - unload tous les modèles Ollama warmés        │
│     │        - clear_vram() / garbage collection            │
│     │                                                        │
│     └──► preloadOllamaModel()                               │
│          │                                                   │
│          ├──► /ollama/warmup (utility: qwen2.5:1.5b)        │
│          │    └── Charge le utility model (checks)          │
│          │                                                   │
│          └──► /ollama/warmup (chat: userSettings.chatModel) │
│               └── Charge le chat model sélectionné          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Code source:**
- `app.js` ligne ~257: appel `/models/unload-all`
- `settings.js` fonction `preloadOllamaModel()`: charge utility + chat
- `app.py` endpoint `/models/unload-all`: décharge tout

---

## Flux de changement de modèle IMAGE (picker)

```
┌─────────────────────────────────────────────────────────────┐
│            CHANGEMENT MODÈLE IMAGE (picker)                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Utilisateur sélectionne un nouveau modèle               │
│     (onglet Inpaint ou Text2Img)                            │
│     │                                                        │
│     ├──► Sauvegarde dans localStorage                       │
│     │    - selectedInpaintModel (si onglet inpaint)        │
│     │    - selectedText2ImgModel (si onglet text2img)      │
│     │                                                        │
│     └──► /api/log/model-change (POST)                       │
│          │                                                   │
│          └──► unload_all_image_models()                     │
│               - Décharge inpaint_pipe                       │
│               - Décharge text2img_pipe                      │
│               - clear_vram()                                │
│                                                              │
│  2. À la prochaine génération:                              │
│     │                                                        │
│     └──► load_inpaint_model(nouveau_modèle)                 │
│          ou load_text2img_model(nouveau_modèle)             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Code source:**
- `ui.js` fonction `selectPickerModel()`: sauvegarde + appelle `/api/log/model-change`
- `app.py` endpoint `/api/log/model-change`: décharge l'ancien modèle image

---

## Flux de changement de modèle CHAT (picker)

```
┌─────────────────────────────────────────────────────────────┐
│            CHANGEMENT MODÈLE CHAT (picker)                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Utilisateur sélectionne un nouveau modèle (onglet Chat) │
│     │                                                        │
│     ├──► Sauvegarde dans userSettings.chatModel             │
│     │                                                        │
│     └──► /api/log/model-change (POST)                       │
│          type: 'chat'                                        │
│          │                                                   │
│          ├──► ollama_service.unload_model(ancien)           │
│          │    └── keep_alive: "0s" pour décharger           │
│          │                                                   │
│          └──► ollama_service.preload_model(nouveau)         │
│               └── Charge le nouveau modèle en VRAM          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Flux de génération d'image

```
┌─────────────────────────────────────────────────────────────┐
│                  GÉNÉRATION D'IMAGE                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Avant génération (/generate ou /generate-edit):         │
│     │                                                        │
│     ├──► log_loaded_models() - Affiche modèles en VRAM      │
│     │                                                        │
│     ├──► Décharge TOUS les modèles Ollama                   │
│     │    - utility model (qwen2.5:1.5b)                     │
│     │    - chat model                                        │
│     │    └── Libère ~3-8GB VRAM                             │
│     │                                                        │
│     └──► load_inpaint_model() ou load_text2img_model()      │
│          └── Charge SD en VRAM (~6GB)                       │
│                                                              │
│  2. Génération en cours...                                   │
│     │                                                        │
│     └──► Previews en temps réel (polling /generate/preview) │
│                                                              │
│  3. Après génération:                                        │
│     │                                                        │
│     └──► Le modèle SD reste chargé pour les édits suivants  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Mode Chat (pas d'image dans l'input)

```
État initial: utility + chat chargés

Utilisateur envoie un message texte:
  → utility fait les checks (image? memory?)
  → chat répond
  → Rien ne change

Utilisateur demande une image (text2img détecté):
  1. utility améliore le prompt
  2. DÉCHARGER utility + chat
  3. CHARGER text2img (modèle sélectionné dans onglet Text2Img)
  4. Générer l'image
  5. DÉCHARGER text2img
  6. RECHARGER utility + chat
  → Retour à l'état initial
```

## Mode Inpainting (image dans l'input)

```
Image détectée dans l'input:
  1. DÉCHARGER chat (si chargé)
  2. CHARGER utility (si pas chargé)
  3. CHARGER inpainting (modèle sélectionné dans onglet Inpaint)

Utilisateur envoie un prompt:
  1. utility améliore le prompt
  2. DÉCHARGER utility
  3. Générer avec inpainting (déjà chargé)
  4. Garder inpainting chargé
  → Prêt pour le prochain inpainting

Prochain inpainting:
  1. RECHARGER utility
  2. utility améliore le prompt
  3. DÉCHARGER utility
  4. Générer avec inpainting
  → Répéter...

Utilisateur retire l'image de l'input:
  1. DÉCHARGER inpainting
  2. RECHARGER utility + chat
  → Retour au mode chat
```

---

## Endpoints de gestion VRAM

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/models/unload-all` | POST | Décharge TOUS les modèles (sécurité au refresh) |
| `/models/unload-image` | POST | Décharge le modèle image uniquement |
| `/models/preload-image` | POST | Précharge le modèle image sélectionné |
| `/ollama/warmup` | POST | Précharge un modèle Ollama en VRAM |
| `/api/log/model-change` | POST | Gère le changement de modèle (décharge ancien, charge nouveau) |
| `/check-models` | GET | Vérifie le statut des modèles (téléchargé, en cours, taille) |
| `/models/download` | POST | Lance le téléchargement d'un modèle en background |

---

## Téléchargement de modèles

```
┌─────────────────────────────────────────────────────────────┐
│              TÉLÉCHARGEMENT DE MODÈLE                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Utilisateur clique "Télécharger" dans Settings          │
│     │                                                        │
│     └──► /models/download (POST)                            │
│          │                                                   │
│          ├──► get_model_total_size() - Récupère taille HF  │
│          │                                                   │
│          ├──► Thread de téléchargement (background)         │
│          │    └── snapshot_download()                       │
│          │                                                   │
│          └──► Thread de monitoring (progression)            │
│               └── get_cache_folder_size() toutes les 1s    │
│                                                              │
│  2. Frontend poll /check-models toutes les 2s               │
│     │                                                        │
│     └──► Affiche progression réelle: "2.3 GB / 6.5 GB"     │
│                                                              │
│  3. Téléchargement terminé quand downloaded: true           │
│     │                                                        │
│     └──► Toast "Succès: modèle téléchargé"                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Résumé des transitions

| De | Vers | Actions |
|----|------|---------|
| Chat | Text2img | unload(utility, chat) → load(text2img) → generate → unload(text2img) → load(utility, chat) |
| Chat | Inpainting | unload(chat) → load(inpainting) → [loop: load(utility) → enhance → unload(utility) → generate] |
| Inpainting | Chat | unload(inpainting) → load(utility, chat) |
| Refresh page | - | unload(tout) → load(utility) → load(chat) |
| Change model inpaint | - | unload(image) → (chargé à la prochaine génération) |
| Change model text2img | - | unload(image) → (chargé à la prochaine génération) |
| Change model chat | - | unload(ancien) → load(nouveau) |

---

## Règles importantes

1. **Au refresh**: TOUJOURS décharger tout puis recharger utility + chat
2. **Jamais** utility + image model en même temps (sauf brièvement pour enhance)
3. **Toujours** décharger utility AVANT de générer
4. **Inpainting**: garder le modèle image chargé pour enchaîner
5. **Text2img**: décharger après car l'utilisateur retourne au chat
6. **Changement modèle image**: décharger immédiatement, charger à la demande
7. **Changement modèle chat**: décharger ancien, charger nouveau immédiatement
8. **Picker auto-switch**: L'onglet change automatiquement selon présence d'image

---

## Notes techniques

- **GPU 8GB**: Le CPU offload est activé automatiquement (`USE_CPU_OFFLOAD = VRAM_GB <= 10`)
- **Partage VRAM**: Ollama et SD ne peuvent pas coexister efficacement
- **keep_alive: "0s"**: Commande Ollama pour décharger un modèle immédiatement
- **keep_alive: "-1"**: Garde le modèle chargé indéfiniment (utility)
- **clear_vram()**: Appelle `gc.collect()` et `torch.cuda.empty_cache()`
- **Progression téléchargement**: Basée sur la taille réelle du dossier cache vs taille totale HF
