# Good First Issues

These issues are intentionally small, useful, and safe for new contributors. They are written so maintainers can copy them directly into GitHub issues and label them `good first issue`.

Active newcomer tasks live in the GitHub issue tracker: [open good first issues](https://github.com/Senzo13/JoyBoy/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22).

Before starting, read [CONTRIBUTING.md](../CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md). If an item below already exists as a GitHub issue, use the GitHub issue as the source of truth.

## 1. Add a Doctor check for missing `.env.example`

Labels: `good first issue`, `docs`, `doctor`

Problem:
New users can miss provider setup if `.env.example` is missing or outdated.

Suggested files:
- `core/infra/doctor.py`
- `.env.example`
- `tests/test_harness_audit.py`

Acceptance criteria:
- Doctor reports whether `.env.example` exists.
- The message explains that real secrets must stay out of git.
- A lightweight test covers the check.

## 2. Add a UI copy pass for provider secret placeholders

Labels: `good first issue`, `ui`, `i18n`

Problem:
Provider setup copy should be clear that tokens are optional and local.

Suggested files:
- `web/static/js/i18n.js`
- `web/static/js/settings.js`
- `docs/GETTING_STARTED.md`

Acceptance criteria:
- Provider placeholder/help text is clear in English and French.
- No real token examples are introduced.
- `node --check web/static/js/i18n.js` passes.

## 3. Add tests for pack editor prompt exposure

Labels: `good first issue`, `tests`, `packs`

Problem:
The editor should only receive safe, browser-facing prompt snippets from active packs.

Suggested files:
- `core/infra/packs.py`
- `tests/test_packs_smoke.py`

Acceptance criteria:
- Test covers active pack exposing `editor_auto_fill_prompt`.
- Test covers inactive pack returning no editor prompt.
- Full test module passes with `python -m unittest tests.test_packs_smoke`.

## 4. Improve release hygiene warnings for generated files

Labels: `good first issue`, `cli`, `developer-experience`

Problem:
New contributors can accidentally keep generated outputs, local caches, or provider artifacts in their working tree.

Suggested files:
- `.gitignore`
- `docs/SECURITY_AND_CONTENT_POLICY.md`
- `docs/GETTING_STARTED.md`

Acceptance criteria:
- Docs explain which local files should never be committed.
- `.gitignore` covers one missing generated/cache path if needed.
- The guidance is short and does not mention private repo workflows.

## 5. Add a README media checklist

Labels: `good first issue`, `docs`

Problem:
Maintainers need clear guidance for adding screenshots and GIFs without leaking private outputs.

Suggested files:
- `README.md`
- `docs/SECURITY_AND_CONTENT_POLICY.md`

Acceptance criteria:
- Checklist explains safe screenshots, consent, no secrets, no private files.
- README still renders without broken local links.
- No generated output files are committed.

## 6. Add keyboard shortcut docs for the gallery viewer

Labels: `good first issue`, `docs`, `gallery`

Problem:
The gallery viewer has useful interactions that should be documented for users.

Suggested files:
- `docs/GETTING_STARTED.md`
- `web/static/js/modal.js`
- `web/static/css/modal.css`

Acceptance criteria:
- Docs list supported viewer interactions.
- If shortcuts exist in code, docs match behavior.
- If shortcuts do not exist, issue can be split into a follow-up implementation.

## 7. Add a small test for model picker filtering

Labels: `good first issue`, `tests`, `ui`

Problem:
The frontend filters image/video models based on local feature exposure. A regression test or small JS helper test would make this safer.

Suggested files:
- `web/static/js/ui.js`
- `tests/`

Acceptance criteria:
- The filter logic is extracted or documented enough to test.
- Test covers locked local-pack models being hidden or disabled.
- Existing JS syntax checks still pass.

## 8. Improve error text when a local pack import fails

Labels: `good first issue`, `packs`, `ux`

Problem:
Pack import errors can be technically correct but not always actionable.

Suggested files:
- `core/infra/packs.py`
- `web/routes/settings.py`
- `web/static/js/settings.js`

Acceptance criteria:
- Missing `pack.json` error explains expected folder structure.
- Invalid referenced asset path names the missing file.
- Existing pack smoke tests still pass.

## 9. Add a neutral example image-edit prompt set

Labels: `good first issue`, `docs`, `prompts`

Problem:
New users need safe example prompts for background, lighting, clothing, outpaint, and brush fill.

Suggested files:
- `docs/PROMPTS.md`
- `README.md`

Acceptance criteria:
- Adds 8-12 neutral prompts.
- Prompts cover multiple edit intents.
- Examples avoid private or explicit content.

## 10. Add a launcher troubleshooting section for Windows

Labels: `good first issue`, `docs`, `windows`

Problem:
Windows users often need quick fixes for Python, venv, CUDA, and Ollama startup issues.

Suggested files:
- `docs/GETTING_STARTED.md`
- `docs/DOCTOR.md`
- `start_windows.bat`

Acceptance criteria:
- Adds common symptoms and fixes.
- Keeps instructions short and non-destructive.
- Does not add new dependencies.

## 11. Add CSS variables documentation

Labels: `good first issue`, `ui`, `docs`

Problem:
UI contributors need to know where colors, spacing, and surface tokens live.

Suggested files:
- `web/static/css/variables.css`
- `docs/ARCHITECTURE.md`

Acceptance criteria:
- Documents the key variable groups.
- Adds comments only where helpful.
- No visual behavior changes required.

## 12. Add a terminal tool safety smoke test

Labels: `good first issue`, `terminal`, `tests`

Problem:
Terminal/project mode should never allow obviously destructive commands without safety handling.

Suggested files:
- `core/backends/terminal_tools.py`
- `tests/test_terminal_tools.py`

Acceptance criteria:
- Test covers at least one blocked destructive command.
- Test covers one allowed read-only command.
- Existing terminal tests pass.

## 13. Add an addons page empty state screenshot placeholder

Labels: `good first issue`, `ui`, `addons`

Problem:
The addons/local packs page should be easy to understand before any pack is installed.

Suggested files:
- `web/static/js/settings.js`
- `web/static/css/modal.css`
- `docs/ADDONS.md`

Acceptance criteria:
- Empty state explains what addons are and where they live.
- Button text is clear and translated.
- No adult/sensitive pack is shown as a default public example.

## 14. Add a pack archive hygiene regression test

Labels: `good first issue`, `tests`, `security`

Problem:
Private or sensitive pack archives should stay out of normal commits and public release bundles.

Suggested files:
- `.gitignore`
- `core/infra/packs.py`
- `tests/test_packs_smoke.py`

Acceptance criteria:
- Test or docs cover a fake sensitive pack archive under `dist/packs/`.
- The expected behavior is clear: keep it local, do not commit it.
- Existing pack smoke tests pass.
