# Local Packs

JoyBoy supports local packs to extend the public core without shipping every machine-specific capability in the repository itself.

## Why packs exist

- keep the public core easier to maintain
- avoid coupling every optional workflow to the main repo
- let advanced users extend JoyBoy locally
- keep secrets, local assets, and optional capabilities off the public surface

## Default location

JoyBoy looks for packs in:

```text
~/.joyboy/packs/<pack_id>/
```

## Pack manifest

Each pack must expose a `pack.json` manifest with the following fields:

- `id`
- `name`
- `version`
- `kind`
- `capabilities`
- `router_rules_path`
- `prompt_assets_path`
- `model_sources_path`
- `ui_overrides_path`
- `skills_path` (optional)
- `feature_flags_required`

Supported `kind` values currently include:

- `creative`
- `experimental`
- `adult` (legacy local-only classification for restricted/private addons, not part of the public core narrative)

## Installing a pack

Open `Addons` from the sidebar and choose one of these options:

1. import a local zip archive
2. import from a local folder path

JoyBoy validates the manifest and rolls back invalid imports.

Public users should install packs from a zip or folder they trust. Third-party packs are optional and are maintained outside the public core. See `docs/THIRD_PARTY_PACKS.md`.

For local/private workstations, a bundled source pack can also be installed with:

```bash
python scripts/bootstrap.py pack-install
```

This copies the bundled local advanced pack into `~/.joyboy/packs` and activates it.
The bundled source currently lives in `local_pack_sources/local-advanced-runtime/`.

## Activating a pack

Once imported, a pack can be activated or disabled locally from the same screen.

- inactive pack: installed, not used
- active pack: exposed to the router and UI
- invalid pack: listed with validation errors

Typical activation flow for an end user:

1. open `Addons` from the sidebar
2. go to local packs
3. import a zip or local folder
4. click `Activer`

If the machine uses the private/dev bridge, `python scripts/bootstrap.py pack-install` is the fastest path.

## Locked surfaces

Some JoyBoy UI surfaces are intentionally visible but locked until a compatible local pack is active. This helps explain capability boundaries without pretending the feature does not exist.

## Versioning expectations

When creating new packs:

- keep manifests explicit
- avoid hidden side effects
- declare capabilities clearly
- prefer additive behavior over monkey-patching core files

For a step-by-step addon guide with empty templates and a neutral example pack, see `docs/ADDONS.md`.

For public repo preparation, see:

- `docs/ARCHITECTURE.md`
- `docs/PUBLIC_MIRROR_CHECKLIST.md`
