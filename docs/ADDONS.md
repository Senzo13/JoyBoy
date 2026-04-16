# JoyBoy Addons and Local Packs

JoyBoy addons are local packs that extend the public core without editing core files. A pack can add routing rules, prompt assets, model sources, or optional UI surfaces. This keeps the repo clean for open source contributors while still letting advanced users build powerful local extensions.

## Quick Mental Model

- The public core stays generic: chat, web, image, video, routing, model manager, onboarding, doctor, and UI.
- Addons live locally in `~/.joyboy/packs/<pack_id>/`.
- A pack is imported from a local folder or a `.zip` archive in `Settings > Models > Local packs`.
- JoyBoy validates `pack.json` before activating a pack.
- Private or sensitive packs should stay outside git and outside the future public mirror.

## Minimal Structure

```text
my-addon/
  pack.json
  assets/
    router_rules.json
    prompt_assets.json
    model_sources.json
    ui_overrides.json
```

You can start from:

- `docs/addons/templates/empty-addon/`
- `docs/addons/examples/creative-router-pack/`

## Manifest Contract

Every pack must expose a `pack.json` file:

```json
{
  "id": "my-local-addon",
  "name": "My Local Addon",
  "version": "0.1.0",
  "kind": "creative",
  "description": "Describe the local capability this addon provides.",
  "capabilities": [
    "router_rules",
    "prompt_assets",
    "model_sources",
    "ui_overrides"
  ],
  "router_rules_path": "assets/router_rules.json",
  "prompt_assets_path": "assets/prompt_assets.json",
  "model_sources_path": "assets/model_sources.json",
  "ui_overrides_path": "assets/ui_overrides.json",
  "feature_flags_required": []
}
```

Supported `kind` values are currently:

- `creative`
- `experimental`
- `adult`

Use `adult` only for local-only packs that should not be marketed as part of the public core.

## Asset Files

`router_rules.json`
: Adds intent hints or routing enrichments. Keep rules additive and predictable.

`prompt_assets.json`
: Stores prompt fragments, negative prompt fragments, style presets, or reusable wording.

`model_sources.json`
: Declares optional Hugging Face, CivitAI, or future provider sources required by the pack.

`ui_overrides.json`
: Declares optional UI surfaces or labels that should only appear when the pack is active.

The current validator checks that the manifest and referenced files exist. Schemas should stay simple and explicit so contributors and AI coding agents can modify them safely.

## Importing a Pack

From the UI:

1. Open `Settings > Models`.
2. Go to `Local packs`.
3. Import a `.zip` archive or paste a local folder path.
4. Activate the pack.

From a private/dev workstation, the bootstrap helper can install the bundled local source pack:

```bash
python scripts/bootstrap.py pack-install
```

## Creating a Zip

On Windows PowerShell:

```powershell
Compress-Archive -Path .\my-addon -DestinationPath .\my-addon.zip -CompressionLevel Optimal
```

On macOS/Linux:

```bash
zip -r my-addon.zip my-addon
```

JoyBoy accepts archives where `pack.json` is at the zip root or inside one top-level folder.

## Public Repo Rule

For the open source repo, keep addons neutral unless the addon itself is meant to be shared publicly. Do not commit private model credentials, private pack archives, generated outputs, local caches, or sensitive prompt assets.

---

# Addons et Packs Locaux

Les addons JoyBoy sont des packs locaux qui étendent le core public sans modifier les fichiers du core. Un pack peut ajouter des règles de routing, des prompts, des sources de modèles ou des surfaces UI optionnelles.

## À Retenir

- Le core public reste générique: chat, web, image, vidéo, routing, model manager, onboarding, doctor et UI.
- Les addons vivent localement dans `~/.joyboy/packs/<pack_id>/`.
- Un pack s’importe depuis un dossier local ou une archive `.zip` dans `Paramètres > Modèles > Packs locaux`.
- JoyBoy valide `pack.json` avant activation.
- Les packs privés ou sensibles restent hors git et hors futur miroir public.

## Structure Minimale

```text
my-addon/
  pack.json
  assets/
    router_rules.json
    prompt_assets.json
    model_sources.json
    ui_overrides.json
```

Tu peux démarrer avec:

- `docs/addons/templates/empty-addon/`
- `docs/addons/examples/creative-router-pack/`

## Contrat du Manifeste

Chaque pack expose un fichier `pack.json`:

```json
{
  "id": "my-local-addon",
  "name": "My Local Addon",
  "version": "0.1.0",
  "kind": "creative",
  "description": "Décris la capacité locale ajoutée par cet addon.",
  "capabilities": [
    "router_rules",
    "prompt_assets",
    "model_sources",
    "ui_overrides"
  ],
  "router_rules_path": "assets/router_rules.json",
  "prompt_assets_path": "assets/prompt_assets.json",
  "model_sources_path": "assets/model_sources.json",
  "ui_overrides_path": "assets/ui_overrides.json",
  "feature_flags_required": []
}
```

Valeurs `kind` supportées:

- `creative`
- `experimental`
- `adult`

Utilise `adult` uniquement pour des packs locaux qui ne doivent pas être marketés comme surface du core public.

## Import

Depuis l’UI:

1. Ouvre `Paramètres > Modèles`.
2. Va dans `Packs locaux`.
3. Importe une archive `.zip` ou colle le chemin d’un dossier local.
4. Active le pack.

Depuis une machine privée/dev:

```bash
python scripts/bootstrap.py pack-install
```

## Créer une Archive

PowerShell:

```powershell
Compress-Archive -Path .\my-addon -DestinationPath .\my-addon.zip -CompressionLevel Optimal
```

macOS/Linux:

```bash
zip -r my-addon.zip my-addon
```

JoyBoy accepte une archive où `pack.json` est à la racine du zip ou dans un dossier racine unique.
