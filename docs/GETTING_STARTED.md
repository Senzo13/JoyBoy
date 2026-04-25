# Getting Started

## 1. Start JoyBoy

Clone the repository, then run the platform launcher from the repo root.

### Windows

Double-click `start_windows.bat` or run:

```bat
start_windows.bat
```

### macOS

From Terminal:

```bash
chmod +x start_mac.command
./start_mac.command
```

If macOS says the launcher is not executable, run `chmod +x start_mac.command` once, then launch it again.

### Linux

```bash
./start_linux.sh
```

## 2. Open the app

```text
http://127.0.0.1:7860
```

## 3. Finish onboarding

On first launch, JoyBoy will:

- ask how you use the app
- store your local profile
- inspect your machine
- recommend default models and settings
- surface a readiness summary from the Doctor

## 4. Configure providers

Open `Settings > Models` to:

- save `HF_TOKEN`
- save `CIVITAI_API_KEY`
- inspect the Doctor report
- resolve and import model sources

Provider keys are optional at startup. Add them only when you need downloads that require auth:

- `HF_TOKEN`: useful for gated/private Hugging Face models or more reliable Hugging Face downloads.
- `CIVITAI_API_KEY`: useful for importing CivitAI model sources.
- `OLLAMA_BASE_URL`: optional if your Ollama server is not on `http://127.0.0.1:11434`.
- SignalAtlas GSC CSV imports do not need credentials. Optional direct/provider enrichments use `SIGNALATLAS_GSC_*` settings and `SEMRUSH_API_KEY`.
- PerfAtlas runs without credentials, then enriches performance evidence when optional keys are present: `PAGESPEED_API_KEY` or `GOOGLE_API_KEY` for PageSpeed Insights, `CRUX_API_KEY` or `GOOGLE_API_KEY` for CrUX/CrUX History, and `WEBPAGETEST_API_KEY` for future deep-lab waterfall/filmstrip enrichment.
- PerfAtlas exports include Markdown, AI prompt, remediation JSON, PDF, a CI gate JSON, and an evidence pack JSON with the deterministic crawl/lab/field/provider data used by the report.

If you only use already-installed local models, you can skip keys and add them later.

UI-managed secrets are stored outside git in `~/.joyboy/config.json`.

## 4b. Optional local packs

JoyBoy can import local packs from a `.zip` archive or local folder.

1. Open `Addons` from the sidebar.
2. Go to local packs.
3. Import the pack zip or folder.
4. Activate the pack.

Third-party packs are optional and are not part of the public core. See `docs/THIRD_PARTY_PACKS.md`.

## 5. Run the Bootstrap Doctor

From the repo root you can also run:

```bash
python scripts/bootstrap.py doctor
```

## 6. Verify the Doctor

The Doctor reports whether the machine is ready for:

- runtime
- GPU / VRAM
- Ollama
- provider downloads
- storage
- packs

## 7. Use the document gallery viewer

Open `Settings > Storage`, then click any saved image or video card to open the gallery viewer.

- Prompt and model metadata appear in the viewer sidebar under `Model` and `Prompt` when they were recorded for that file.
- If a file was saved without metadata, the viewer shows `Not recorded`.
- Supported shortcuts in the gallery viewer:
  - `Escape` closes the viewer
  - `Left Arrow` and `Right Arrow` move between saved items
  - `Alt + mouse wheel` zooms the current image or video preview
- Download and delete are available from the viewer buttons. There is no dedicated keyboard shortcut for those actions yet.

## FR

Le chemin conseillé est simple:

1. lancer le script de démarrage
2. ouvrir JoyBoy
3. terminer l’onboarding
4. configurer les providers dans `Paramètres > Modèles`
5. vérifier le Doctor avant d’ajouter des modèles
6. utiliser `python scripts/bootstrap.py doctor` si tu veux un check terminal rapide
7. ouvrir `Paramètres > Stockage` pour retrouver la galerie et voir les métadonnées `Modèle` et `Prompt` dans la visionneuse
