# JoyBoy

**JoyBoy is a local-first AI workstation for chat, coding, image generation, image editing, video experiments, model management, MCP tools, and optional extensions.**

It is built to feel like a product, not a folder of scripts: launch it, let onboarding check your machine, pick a model, and start creating. JoyBoy can stay fully local by default with Ollama and local media models, while still letting you connect API providers, MCP servers, Browser Use, and private local packs when you want more power.

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](scripts/requirements.txt)
[![Local First](https://img.shields.io/badge/local--first-zero--cloud-111827.svg)](#local-first-by-default)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-0f172a.svg)](#models-and-providers)
[![Extensions](https://img.shields.io/badge/extensions-MCP%20%7C%20packs%20%7C%20browser-2563eb.svg)](#extensions-mcp-and-browser-use)

## What JoyBoy Does

JoyBoy brings the main local AI workflows into one interface:

- **Chat** with local Ollama models or optional cloud providers.
- **Project mode** for coding, workspace analysis, tool execution, todos, and repository work.
- **Image generation** with local/provider models and a model catalogue.
- **Image editing and inpainting** with brush masks, quick prompts, outpaint/expand, upscale, and before/after viewing.
- **Video workflows** for image-to-video, video continuation, model downloads, and local GPU profiles.
- **Model management** for local image, video, and LLM models.
- **Gallery** with prompts, models, metadata, images, and videos.
- **Doctor and onboarding** to check dependencies, GPU profile, providers, caches, and setup state.
- **Extensions** through native tools, MCP connectors, Browser Use, and local packs.

The goal is simple: make a private AI workstation that is powerful, understandable, and easy to operate on a real machine.

## Preview

| Local Chat And Runtime | Image Edit Result |
| --- | --- |
| ![JoyBoy local chat with Ollama model selector and runtime meters](docs/assets/joyboy-chat.jpg) | ![JoyBoy image editing result with original and modified previews](docs/assets/joyboy-image-edit-result.jpg) |

| Edit Mode | Before/After Viewer |
| --- | --- |
| ![JoyBoy edit mode with brush, mask controls, quick prompts, and model picker](docs/assets/joyboy-edit-mode.jpg) | ![JoyBoy before and after comparison viewer](docs/assets/joyboy-before-after-viewer.jpg) |

## Quick Start

Clone the repository, then run the launcher for your platform.

### Windows

Double-click `start_windows.bat`, or run:

```bat
start_windows.bat
```

### macOS

```bash
chmod +x start_mac.command
./start_mac.command
```

### Linux

```bash
./start_linux.sh
```

Then open:

```text
http://127.0.0.1:7860
```

On first launch, JoyBoy guides you through setup and onboarding. It detects your GPU/RAM profile, checks required dependencies, explains what the app can do, and helps you fix missing pieces without making you dig through random terminal logs.

If you already completed setup, the launcher uses the fast path and starts the server directly.

### Remote GPU / Lambda Cloud

For a remote GPU machine, keep JoyBoy private with an SSH tunnel.

Windows PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

macOS / Linux:

```bash
ssh -i ~/.ssh/<KEY_NAME> -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

Then clone and start JoyBoy on the remote machine:

```bash
git clone https://github.com/Senzo13/JoyBoy.git
cd JoyBoy
chmod +x start_linux.sh
./start_linux.sh
```

Open `http://127.0.0.1:7860` on your local computer while the SSH session stays open.

If JoyBoy is already running in one SSH terminal, open a second local terminal for the tunnel only:

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -N -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

If your local `7860` port is busy:

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -N -L 7861:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

Then open `http://127.0.0.1:7861`.

See [Cloud / Remote GPU Setup](docs/CLOUD_SETUP.md) for the full Lambda-style setup notes.

## Easy To Use

JoyBoy is designed around everyday use:

- Launch from one script per platform.
- Use onboarding and Doctor when something is missing.
- Download, equip, and delete models from the model pages.
- Pick chat, image, or video models from the UI.
- Paste images or videos directly into the input.
- Watch generation progress with live status, progress bars, and runtime logs.
- Open the F10 runtime console when you want to see what JoyBoy is doing.
- Use the update controls to pull new code without memorizing git commands.

The advanced pieces are still there, but the default path is meant to be obvious.

## Core Features

### Chat And Local Models

JoyBoy can run local chat through Ollama and can switch between installed models from the picker. It also tracks runtime state so models can be unloaded when memory gets tight.

Useful for:

- Private local chat.
- Lightweight utility models.
- Larger local LLMs when your GPU/RAM can handle them.
- Switching between fast, creative, coding, and vision-capable models.

### Coding And Project Mode

Project mode gives JoyBoy a workspace-aware coding surface. It can inspect files, plan work, use tools, keep task state, and help with repository changes.

Useful for:

- Repo analysis.
- Frontend/backend implementation.
- Debugging.
- Code review style checks.
- Tool-driven local workflows.

### Image Generation And Editing

JoyBoy includes image generation, model catalogues, provider imports, SDXL/Flux-style workflows, inpainting, masks, quick prompts, expand/outpaint, upscale, and before/after comparison.

Useful for:

- Text-to-image.
- Image-to-image.
- Local inpainting.
- Product/portrait/background edits.
- Iterating with a visible gallery and metadata.

### Video Generation And Continuation

JoyBoy exposes video models through the same local model mindset: catalogue, install/equip flows, GPU-aware profiles, progress reporting, and gallery output.

Useful for:

- Image-to-video.
- Video continuation.
- Testing Wan/FastWan/LTX/LTX-2.3/FramePack-style workflows.
- Comparing 8GB, 20GB, 24GB, 40GB, and larger GPU behavior.

Video generation is still hardware-sensitive. JoyBoy tries to keep the controls friendly while making VRAM/RAM/offload behavior visible.

## Extensions, MCP, And Browser Use

JoyBoy has an Extensions hub because not every workflow belongs hardcoded inside the public core.

There are three extension families:

- **Native extensions**: built into JoyBoy, such as Browser Use and local runtime panels.
- **MCP connectors**: tool servers for GitHub, filesystem access, databases, SaaS tools, search, deployment platforms, and other external systems.
- **Local packs**: private addons stored outside git for custom prompts, routes, UI surfaces, model recipes, or machine-specific features.

### MCP Connectors

MCP lets JoyBoy connect tools without stuffing every integration directly into the app. MCP config stays local in:

```text
~/.joyboy/config.json
```

JoyBoy can show configured MCP servers, enabled tools, missing environment variables, OAuth/token requirements, and runtime health from the UI.

Examples of MCP-style workflows:

- GitHub repositories, issues, pull requests, and CI.
- Filesystem access with explicit allowed folders.
- PostgreSQL/Neon databases.
- Netlify/Vercel/Cloudflare deployment tooling.
- Google Workspace-style documents, sheets, and slides.
- Market research, web fetch, and search tooling.

### Browser Use

Browser Use is an optional local browser automation surface. It opens a resizable right-side panel, can navigate local or public pages, take screenshots, click, scroll, type, and show a live cursor/action log while it works.

You can call it from chat with:

```text
@browser-use open localhost:3000 and check the main button
```

It is especially useful for:

- Testing local websites.
- Opening localhost apps.
- Checking frontend changes visually.
- Navigating pages while seeing what the agent is doing.

Browser Use is optional. If the runtime is missing, JoyBoy can install Playwright/Chromium locally from the UI.

### Computer Use

Computer Use is the planned desktop-control surface for controlling the actual computer, not just a browser tab. Because real OS mouse/keyboard control is sensitive and platform-specific, JoyBoy exposes it as a **local-pack extension surface** instead of baking it directly into the public core.

The intended design is:

- Visible cursor on the user's screen.
- Screenshots and click/type/scroll actions.
- Explicit user-controlled permissions.
- Platform-specific implementation in a local pack.
- Reuse of the Browser Use UI/runtime patterns where possible.

Until a trusted local pack is installed, Computer Use stays visible-but-locked in the Extensions hub.

## Local First By Default

JoyBoy is designed for privacy and control:

- No cloud account is required by default.
- Local chats, outputs, galleries, packs, caches, and settings stay on your machine.
- Provider keys are optional.
- Secrets are read from environment variables, `.env`, or local UI config.
- Local packs live outside the repository.
- Model weights and generated files are not meant to be committed.

The public repository is the neutral core. Private workflows should be added through local packs.

## Models And Providers

JoyBoy can work fully locally, or with optional providers.

Local model paths include:

- Ollama chat models.
- Hugging Face model downloads.
- CivitAI imports.
- Local image models.
- Local video models.
- Utility models for captioning, segmentation, depth, parsing, and routing.

Optional provider/API variables include:

- `HF_TOKEN`
- `CIVITAI_API_KEY`
- `OLLAMA_BASE_URL`
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`
- `MOONSHOT_API_KEY`
- `NOVITA_API_KEY`
- `MINIMAX_API_KEY`
- `VOLCENGINE_API_KEY`
- `ZHIPU_API_KEY`
- `VLLM_API_KEY`
- `VLLM_BASE_URL`
- `GLM_BASE_URL`

UI-managed secrets are stored outside git in:

```text
~/.joyboy/config.json
```

You only need provider keys for gated downloads or cloud models. Local-only usage can start without keys.

## GPU And Runtime Profiles

JoyBoy tries to adapt to the machine it is running on:

- 8GB VRAM consumer GPUs.
- 20GB/24GB cards.
- 40GB cards such as A100-class machines.
- CPU/MPS-limited machines for lighter workflows.

The app uses GPU profiles, VRAM/RAM displays, unload controls, and model compatibility hints to make local AI less mysterious.

If CUDA is expected but JoyBoy reports CPU-only PyTorch, rerun the launcher and choose the full setup/repair path.

## Public Core And Local Packs

Local packs live in:

```text
~/.joyboy/packs/<pack_id>/
```

Packs can extend JoyBoy without polluting the public repository:

- custom routing
- prompt libraries
- private workflows
- machine-specific backends
- extra UI surfaces
- experimental model integrations

Third-party packs are external addons distributed separately from JoyBoy. They are not part of the official public core and may have their own safety, licensing, and maintenance rules.

See:

- [Local Packs](docs/LOCAL_PACKS.md)
- [Addons](docs/ADDONS.md)
- [Third-Party Packs](docs/THIRD_PARTY_PACKS.md)

## Documentation

- [Getting Started](docs/GETTING_STARTED.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP](docs/MCP.md)
- [Local Packs](docs/LOCAL_PACKS.md)
- [Addons and Pack Templates](docs/ADDONS.md)
- [Packaging](docs/PACKAGING.md)
- [Third-Party Packs](docs/THIRD_PARTY_PACKS.md)
- [VRAM Management](docs/VRAM_MANAGEMENT.md)
- [Releases and Update Checks](docs/RELEASES.md)
- [Security and Content Policy](docs/SECURITY_AND_CONTENT_POLICY.md)
- [Repository SEO and Discovery](docs/SEO_AND_DISCOVERY.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)
- [Good First Issues](docs/GOOD_FIRST_ISSUES.md)

## Contributing

JoyBoy is being prepared as a clean public local AI core. Good contributions keep the app easy to understand and avoid committing secrets, generated files, model weights, caches, or local packs.

Good first areas:

- onboarding polish
- Doctor checks
- UI/UX improvements
- model catalogue reliability
- MCP connector quality
- tests around local packs
- documentation
- packaging and launcher reliability

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [ROADMAP.md](ROADMAP.md), and [docs/GOOD_FIRST_ISSUES.md](docs/GOOD_FIRST_ISSUES.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
