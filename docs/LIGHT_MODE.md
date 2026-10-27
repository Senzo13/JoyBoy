# JoyBoy Light and MCP (local prototype)

JoyBoy Light keeps image import, brush/rectangle selection, erasing, undo,
immutable image versions, comparison and PNG export in a small local interface.
Chat runs through the official Codex app-server. Explicit image generation and
masked model edits use the OpenAI Images API with separate billing.

## Start

Install Python 3.11+ and an official Codex CLI, then:

```bash
python3 scripts/start_light.py
```

Windows: `py -3 scripts/start_light.py`. Open `http://127.0.0.1:7861`.
Use `--port 7862` if that local port is occupied. The server binds only to
`127.0.0.1`. This development server is intended for a local desktop prototype.

The launcher creates `~/.joyboy/venvs/light`, installs only
`scripts/requirements-light.txt`, and runs `python -m web.light`.
It imports no Torch, diffusion pipeline, Ollama service or video runtime and
does not download model weights. Existing full JoyBoy launchers still work.

Sign in using the official CLI's `codex login`. Light asks the app-server for
account status and models; it never opens the Codex credential file or forwards
subscription tokens. If your CLI launcher is broken, set `JOYBOY_CODEX_BIN` to a
working official executable. macOS discovery also checks the app's bundled CLI.
No account identifier/email is returned to the UI or MCP.
The Images API key is removed from the Codex child process environment so that
configuring image billing cannot silently switch Codex to that API key.
Codex's own stored API-key login, if selected by the user, still uses API billing.

For image generation and API edits, set `OPENAI_API_KEY` in your environment,
the repository's ignored `.env`, or JoyBoy's existing local provider config.
The image controls remain visible and locked until a key is configured. A key's
presence is readiness only; model access and billing are verified by the API
request. The default draft model is `gpt-image-2.5-sunburst`; override with
`JOYBOY_OPENAI_IMAGE_MODEL` if needed. Draft quality is `low`.

Images, masks, candidates, results and metadata live in `~/.joyboy/studio`.
`JOYBOY_STUDIO_DIR` or `--data-dir` can select another external directory.
Inputs are decoded to an EXIF-oriented RGBA PNG once. The decoded canvas is
preserved; original file encoding/metadata is not retained. Import is limited to
40 MiB and 16 megapixels. Each operation creates new files with random IDs.
The source file is never overwritten.

## Pixel protection and layers

1. Add an image. Light keeps its decoded dimensions, including odd pixel sizes.
2. Paint or draw rectangles over the editable area. White means editable;
   black means protected. The visual overlay is a separate mask layer.
3. Describe the edit and choose **Modifier la sélection**, or expand
   **Appliquer un calque déjà généré** to import a same-size candidate.
4. A candidate layer is merged through the selection using the shared
   `composite_with_original(..., strict=True)` helper.
5. A new image version records the source, mask, candidate, dimensions and pixel
   counts. Compare with the original or download the verified PNG.

OpenAI expects a PNG alpha mask: transparent means editable. The API adapter
explicitly inverts JoyBoy's grayscale selection into that alpha channel.
The model's mask is guidance, so a local merge restores every protected RGBA
pixel from the source. The saved PNG is verified against the decoded source:
`dimensions_preserved`, `protected_pixels_changed`, `selected_pixels_changed`.
An unchanged selection is reported as zero changed pixels rather than called a
successful visible edit.

The model can return a different output size. Only the generated candidate is
resized to the original canvas; this is recorded as `provider_size` and
`candidate_resized`. The source and mask are never resized. Local candidate
imports reject dimension mismatches. Optional MCP feathering is clipped inside
the selection, so it cannot alter protected pixels. Alpha is preserved outside
the mask, including RGB values of fully transparent pixels.

This prototype exposes source/mask/candidate/result layers and immutable versions,
not a general-purpose multilayer painting application. Selections are grayscale
PNG masks; alpha-mask files must first be explicitly converted to that convention.

## MCP for Codex

The official Python MCP SDK is pinned to its v1 maintenance line (`mcp>=1.28,<2`).
Run over stdio; there is no network MCP listener or bearer token to configure:

```bash
python3 scripts/start_light.py --mcp --allow-root /absolute/path/to/your/images
```

Only the studio directory is readable by default. Add `--allow-root` once per
trusted image directory. Resolved paths and symlinks must remain within those
roots. This grants read access; generated files stay in the studio directory.
The UI uses uploads rather than arbitrary filesystem paths.

Add an entry using **Codex Settings → MCP servers**, or your local Codex config:

```toml
[mcp_servers.joyboy]
command = "/absolute/path/to/python3"
args = ["/absolute/path/to/JoyBoy/scripts/start_light.py", "--mcp", "--allow-root", "/absolute/path/to/images"]
startup_timeout_sec = 120
tool_timeout_sec = 300
```

Do not put API keys in a committed MCP config. The server reads the existing
local JoyBoy provider settings/environment. First-time dependency installation
can be done by launching Light before connecting the MCP client.

| Tool | Behavior |
| --- | --- |
| `joyboy_status` | Codex auth type/model catalog, API readiness, shared feature locks |
| `joyboy_import` | Import from an allowed path, return asset ID |
| `joyboy_mask` | Rectangles `[x,y,width,height]` or a grayscale PNG path |
| `joyboy_apply` | Local exact composition of a candidate through a mask, no model call |
| `joyboy_edit` | Separately billed OpenAI masked edit, then strict composition |
| `joyboy_generate` | Separately billed draft generation |
| `joyboy_inspect` | Metadata, output path and verification counts |
| `joyboy_preview` | Image preview (thumbnail; full PNG stays on disk) |
| `joyboy_chat` | Official Codex conversation with optional vision attachments |

Example tool sequence: import source → import candidate → create mask → apply →
inspect → preview. A mask is bound to one source revision and cannot accidentally
be applied to another. Model chat/image generation are explicit operations,
not inferred through a second prompt router.

## Official integration boundaries

Verified on 2026-10-27 against official documentation and installed Codex
`0.164.0-alpha.11.1`:

- `codex app-server --listen stdio://` supports `initialize`, `account/read`,
  `model/list`, `thread/start`, `thread/resume`, `turn/start`, agent messages and
  terminal turn statuses. Light accepts success only when a turn is `completed`.
- The model selector uses `model/list`, not hardcoded names. Its catalog is not
  an entitlement guarantee; a completed turn proves access for that call.
- Text and `localImage` attachments are supported. Vision input is not an
  exposed image-generation/mask endpoint. Light does not claim that Codex's
  internal image tool can be remotely invoked through this bridge.
- Chat replies are returned after completion; this prototype does not yet stream
  tokens to the browser. Conversations can resume while their IDs are retained
  by the UI/MCP caller. There is no history browser yet.
- Chat starts with a read-only sandbox and no auto-approved action requests.
  Sandboxed command network access is disabled; file reads follow Codex's
  read-only sandbox policy. The installed protocol rejects the older
  `readOnly.access` field, so the bridge does not send it or claim restricted
  read roots for Codex chat. MCP image imports have their own explicit roots.
  Per-thread overrides explicitly disable each inherited MCP server/plugin and
  Apps, and the bridge checks the resulting MCP tool catalog before inference.
  An empty `mcp_servers={}` table does not clear inherited configuration in the
  installed CLI, so the bridge does not rely on that form. These thread overrides
  do not change the user's Codex config.
  Requests needing client approvals receive an explicit unsupported-method error.
  This prototype is not a full Codex tool/approval client.
- The official managed Codex login is appropriate for this local/open-source
  integration. Hosted/commercial integrations should follow the documented
  **Sign in with ChatGPT** path and its eligibility requirements.
- ChatGPT/Codex subscription access does not pay for OpenAI API image calls.
  No cookies, credential extraction or alternate backend endpoints are used.

Sources: [Codex app-server](https://learn.chatgpt.com/docs/app-server),
[image generation and masks](https://developers.openai.com/api/docs/guides/image-generation),
[image edit API](https://developers.openai.com/api/reference/python/resources/images/methods/edit),
[billing separation](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform),
[official MCP SDK v1](https://py.sdk.modelcontextprotocol.io/v1/).

## Validation

After launching once to install the small environment:

```bash
~/.joyboy/venvs/light/bin/python -m unittest tests.test_light_studio tests.test_light_mcp tests.test_light_codex tests.test_editor_static
```

Windows: use `~/.joyboy/venvs/light/Scripts/python.exe` (expand `~` to your user
directory) with the same arguments.

The tests cover odd canvas sizes, transparent RGBA pixels, clipped feathering,
mask polarity, provider payloads, API-key absence, immutable source revisions,
path/symlink restrictions, HTTP origin/token checks, app-server events, and real
stdio MCP import/mask/apply/inspect/preview calls. Provider HTTP responses are
mocked in the automated suite; that does not establish live API image access.

Local prototype validation on 2026-10-27: 22 targeted tests passed. A real stdio
MCP run imported an AI-generated blue mug and an orange edit candidate, created
a mask and composited the result at 1254 × 1254. The persisted PNG preserved all
1,428,536 protected pixels; 143,972 pixels changed inside the selection. The
candidate came from the session's built-in image tool, which has no explicit
mask argument; the mask was enforced by JoyBoy's local composition. No live
OpenAI Images API request was made because no API key was configured.

Browser verification covered rectangle/eraser/undo, candidate application,
comparison, PNG download, desktop/mobile layout, and a real Codex vision reply
(“Orange”) about the edited image. No JavaScript errors or mobile horizontal
overflow occurred. The broader GPU-dependent test suite cannot run in this
minimal environment without Torch; it was not installed for this prototype.
An additional real Codex turn used the new server's `joyboy_inspect` MCP tool
and correctly reported 1254 × 1254 with zero changed protected pixels. The
connection was configured only for that test thread; global Codex settings were
not edited.
