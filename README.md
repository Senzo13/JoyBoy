# JoyBoy - Local AI Harness, Workstation, and Image Editor

**JoyBoy is a local AI harness and local AI workstation: a private ChatGPT / Grok-style chat app, local AI image editor, Ollama-assisted image generation workspace, SDXL inpainting UI, CivitAI model imports manager, local addons runtime, and Codex-style project mode in development.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](scripts/requirements.txt)
[![Local First](https://img.shields.io/badge/local--first-zero--cloud-111827.svg)](#why-joyboy)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-0f172a.svg)](#local-secrets)
[![Stable Diffusion](https://img.shields.io/badge/media-SDXL%20%7C%20Flux%20%7C%20Video-2563eb.svg)](#features)

Run AI chat, image workflows, model management, and local creative tools on your own machine. JoyBoy is built for people who want an open source ChatGPT alternative, an offline AI assistant, a local Stable Diffusion / SDXL interface, and a privacy-focused AI harness without relying on a cloud account.

JoyBoy is especially aimed at long-tail local AI workflows: **local AI harness**, **local AI workstation**, **local AI image editor**, **Ollama image generation routing**, **SDXL inpainting UI**, **CivitAI model imports**, and **8GB VRAM Stable Diffusion / SDXL workflows** on consumer hardware.

## Preview

| Local chat and runtime | Image edit result |
| --- | --- |
| ![JoyBoy local chat with Ollama model selector and runtime meters](docs/assets/joyboy-chat.jpg) | ![JoyBoy image editing result with original and modified previews](docs/assets/joyboy-image-edit-result.jpg) |

| Edit mode | Before/after viewer |
| --- | --- |
| ![JoyBoy edit mode with brush, mask controls, quick prompts, and model picker](docs/assets/joyboy-edit-mode.jpg) | ![JoyBoy before and after comparison viewer](docs/assets/joyboy-before-after-viewer.jpg) |

## Features

- **Private local AI chat** with Ollama UI controls and local model routing.
- **Local AI harness** for routing prompts, tools, jobs, models, runtime state, and optional extensions from one app.
- **Local AI workstation** that keeps chat, image generation, image editing, video tests, gallery, model imports, and runtime panels together.
- **Text-to-image generation** with local image models, Ollama-assisted routing, and provider imports.
- **Local AI image editor / SDXL inpainting UI** for background edits, clothing edits, lighting, brush masks, expand/outpaint, and detail fixes.
- **Video experiments** for local image-to-video workflows on consumer GPUs.
- **CivitAI model imports and Hugging Face imports** with local runtime profiles and 8GB VRAM-aware Stable Diffusion / SDXL defaults.
- **Local addons / packs** that can extend routing rules, prompt assets, model sources, and UI surfaces without polluting the public core.
- **Gallery and metadata** for generated images/videos, prompts, models, and local artifacts.
- **Doctor and runtime panels** for VRAM/RAM state, loaded models, provider keys, and machine readiness.
- **Project mode in development** for Codex / Claude Code-style workspace-aware assistance and terminal tools.

## Why JoyBoy

JoyBoy is designed for local AI users who care about privacy, control, and hardware limits.

- **Zero cloud by default**: chats, outputs, provider secrets, and optional packs stay on your computer.
- **One local app**: chat, image generation, video tests, model picker, gallery, local packs, and runtime status live together.
- **Harness mindset**: JoyBoy coordinates models, jobs, tools, providers, and packs instead of leaving each workflow as a separate script.
- **Consumer GPU friendly**: profiles target real machines, including 8 GB VRAM setups.
- **Open source core**: the public repository ships the neutral local AI workstation; optional packs remain separate.
- **Extensible by design**: addons can add workflows without turning the core app into a private monolith.

## Use Cases

- Run a local ChatGPT-like or Grok-like assistant with Ollama.
- Use a local LLM harness and local AI harness to coordinate chat, tools, model routing, and creative jobs.
- Use JoyBoy as a local AI workstation for chat, image generation, image editing, runtime jobs, and model management.
- Generate images locally with SDXL, Flux-style workflows, Ollama-assisted routing, and imported checkpoints.
- Edit photos in a local AI image editor with SDXL inpainting, brush masks, background changes, lighting changes, and outpainting.
- Test local image-to-video workflows without a hosted AI platform.
- Manage Hugging Face and CivitAI model imports from a local UI.
- Run 8GB VRAM Stable Diffusion / SDXL workflows with profiles designed for consumer GPUs.
- Build local addons for custom routing, prompts, model presets, and creator workflows.
- Experiment with a local Codex-style dev assistant that can understand a project workspace.

## Quick Start

Clone the repository, then run the launcher for your platform.

### Windows

Double-click `start_windows.bat` or run:

```bat
start_windows.bat
```

### macOS

```bash
chmod +x start_mac.command
./start_mac.command
```

If macOS says the launcher is not executable, run the `chmod +x` command above once from Terminal, then launch it again.

### Linux

```bash
./start_linux.sh
```

Then open:

```text
http://127.0.0.1:7860
```

On first launch, JoyBoy runs onboarding, detects your machine profile, and shows a Doctor report if something is missing. The launchers include a first-time setup/repair path and a fast start path.

The first inpaint, text-to-image, or video run can take longer than the next ones. JoyBoy may need to download or prepare missing runtime assets such as segmentation checkpoints, SCHP human parsing files, ControlNet helpers, preview VAEs, or video components. The generation card shows setup/download progress while this happens; once cached locally, later generations reuse those assets.

If you have an NVIDIA GPU but JoyBoy logs `0.0GB VRAM` or `torch ... +cpu`, run the Windows launcher and choose **Setup complet**. That repairs the local virtual environment and reinstalls PyTorch with CUDA support.

## Local Secrets

Provider keys are optional and stay local:

- `HF_TOKEN`
- `CIVITAI_API_KEY`
- `OLLAMA_BASE_URL`

Set them through environment variables, a local `.env`, or the JoyBoy settings UI. UI-managed secrets are stored outside git in:

```text
~/.joyboy/config.json
```

The public repo only ships placeholders such as `HF_TOKEN=` and `CIVITAI_API_KEY=`. You only need provider keys for downloads that require them, for example gated Hugging Face models or CivitAI model imports. If you already use local models only, you can start without keys and add them later in the UI.

## Public Core + Local Packs

JoyBoy separates the open source core from optional local extensions.

The public core includes orchestration, routing, onboarding, Doctor checks, model/provider import flows, gallery UI, runtime storage, and pack validation.

Local packs live in:

```text
~/.joyboy/packs/<pack_id>/
```

Some optional local packs may target mature or adult workflows where legal, consensual, and compliant with platform policies. These packs are not part of the public core.

See [Local Packs](docs/LOCAL_PACKS.md), [Addons](docs/ADDONS.md), and [Third-Party Packs](docs/THIRD_PARTY_PACKS.md) for the pack contract.

## Documentation

- [Getting Started](docs/GETTING_STARTED.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Local Packs](docs/LOCAL_PACKS.md)
- [Addons and Pack Templates](docs/ADDONS.md)
- [Third-Party Packs](docs/THIRD_PARTY_PACKS.md)
- [VRAM Management](docs/VRAM_MANAGEMENT.md)
- [Security and Content Policy](docs/SECURITY_AND_CONTENT_POLICY.md)
- [Repository SEO and Discovery](docs/SEO_AND_DISCOVERY.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)
- [Good First Issues](docs/GOOD_FIRST_ISSUES.md)

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [ROADMAP.md](ROADMAP.md), and [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md).

Good early contributions include docs, Doctor checks, UI polish, model import UX, tests around local packs, and release hygiene. Browse open [`good first issue`](https://github.com/Senzo13/JoyBoy/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22) tasks if you want a contained first PR.

## License

Apache License 2.0. See [LICENSE](LICENSE).
