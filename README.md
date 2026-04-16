# JoyBoy

JoyBoy is a **local-first ChatGPT / Grok-like workstation** for people who want chat, image editing, image generation, video experiments, and project tools running on their own machine.

Think: one local app for talking to models, editing images, testing video workflows, managing local providers, and experimenting with a future Codex/Claude Code-style project mode.

![JoyBoy UI placeholder](docs/assets/readme-hero-placeholder.svg)

> TODO: replace this placeholder with a short GIF or screenshot of the main JoyBoy workflow.

## Why JoyBoy

- **Everything starts local**: chats, outputs, provider secrets, and optional packs stay on your machine.
- **Chat + media in one place**: chat, image edit, text-to-image, video, gallery, model picker, and runtime status.
- **Smart image routing**: background edits, lighting, clothing edits, outpainting, brush inpainting, pose/repose, and more.
- **GPU-aware runtime**: JoyBoy tries to fit real consumer hardware, including 8 GB VRAM profiles.
- **Local packs/addons**: optional packs can add routing rules, prompt assets, model sources, and UI overrides.
- **Project mode in progress**: a Codex/Claude Code-style local dev mode is being built for workspace-aware tool use.

## Demo

![Before/after placeholder](docs/assets/readme-before-after-placeholder.svg)

Suggested public demo assets:

- a short GIF showing prompt -> preview -> result;
- a safe before/after edit with non-sensitive content;
- screenshots of onboarding, Doctor, model picker, gallery, or local packs.

Keep public README media safe, consent-based, and non-explicit.

## Quick Start

Clone the repository, then run the launcher for your platform.

On Windows, double-click `start_windows.bat` or run:

```bat
start_windows.bat
```

On macOS:

```bash
./start_mac.command
```

On Linux:

```bash
./start_linux.sh
```

Then open:

```text
http://127.0.0.1:7860
```

On first launch, JoyBoy runs onboarding, detects the machine profile, and shows a Doctor report if something is missing.

The launchers include a first-time setup/repair path and a fast start path.

## Local Secrets

Provider keys are optional and should stay local:

- `HF_TOKEN`
- `CIVITAI_API_KEY`
- `OLLAMA_BASE_URL`

You can set them through environment variables, a local `.env`, or the JoyBoy settings UI. UI-managed secrets are stored outside git in:

```text
~/.joyboy/config.json
```

The public repo only ships placeholders such as `HF_TOKEN=` and `CIVITAI_API_KEY=`.

You only need provider keys for downloads that require them, for example gated Hugging Face models or CivitAI model imports. If you already use local models only, you can start without keys and add them later in the UI.

## Public Core + Local Packs

JoyBoy separates the open source core from optional local extensions.

The public core includes orchestration, routing, onboarding, Doctor checks, model/provider import flows, gallery UI, runtime storage, and pack validation.

Local packs live in:

```text
~/.joyboy/packs/<pack_id>/
```

Some optional local packs may target mature or adult workflows where legal, consensual, and compliant with platform policies. These packs are not part of the public core.

See [Local Packs](docs/LOCAL_PACKS.md), [Addons](docs/ADDONS.md), and [Third-Party Packs](docs/THIRD_PARTY_PACKS.md) for the pack contract.

## Public Mirror

The public repository should not include real provider tokens, private `.env` files, downloaded model weights, generated outputs, local caches, or private pack assets.

Preview the clean public mirror:

```bash
python scripts/bootstrap.py mirror --dry-run
```

Build it locally:

```bash
python scripts/build_public_mirror.py --target _public_mirror_ready --overwrite
```

## Docs

- [Getting Started](docs/GETTING_STARTED.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Local Packs](docs/LOCAL_PACKS.md)
- [Addons and Pack Templates](docs/ADDONS.md)
- [Third-Party Packs](docs/THIRD_PARTY_PACKS.md)
- [VRAM Management](docs/VRAM_MANAGEMENT.md)
- [Security and Content Policy](docs/SECURITY_AND_CONTENT_POLICY.md)
- [Good First Issues](docs/GOOD_FIRST_ISSUES.md)

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [ROADMAP.md](ROADMAP.md), and [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md).

Good early contributions include docs, Doctor checks, UI polish, model import UX, tests around local packs, and public mirror hygiene.

## License

MIT
