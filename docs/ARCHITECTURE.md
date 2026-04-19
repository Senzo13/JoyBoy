# Architecture

JoyBoy is being structured as a public-ready local AI harness with a clear split between:

* `public core`
* `local configuration`
* `optional local packs`

## Public core

The public core should stay focused on reusable infrastructure:

* chat and multimodal orchestration
* image/video routing
* model management
* onboarding
* doctor checks
* provider configuration
* UI shell

## Agent runtime

JoyBoy keeps agent/coding behavior in a reusable public-core layer:

```text
core/agent_runtime/
```

This layer owns runtime contracts that should not depend on Flask routes or UI
state:

* stream event names and schema versions
* tool loop guardrails
* tool output truncation
* host path masking before tool output reaches the model
* LLM provider catalog and provider-prefixed cloud model client
* bounded backend-managed subagents for coding workflows:
  * `code_explorer` for read-only codebase context
  * `verifier` for one allowlisted test/build command without shell chaining

Terminal mode can use this runtime today, and future subagents, MCP tools, pack
skills, and coding providers should plug into it instead of duplicating tool
logic in routes.

The goal is to keep this surface contributor-friendly and easy to reason about.

## Local configuration

Machine-specific state lives outside git in:

```text
~/.joyboy/config.json
```

This local config stores:

* provider credentials
* feature flags
* active local packs
* onboarding state

Priority order:

1. process environment
2. `.env`
3. local JoyBoy config

LLM cloud providers are optional. The terminal runtime accepts provider-prefixed
model ids for OpenAI-compatible providers, for example `openai:gpt-4o-mini` or
`openrouter:provider/model-name`. See `docs/LLM_PROVIDERS.md`.

## Local packs

Optional capabilities can be loaded from:

```text
~/.joyboy/packs/<pack_id>/
```

Each pack is validated through `pack.json` before activation.

Packs can expose:

* router rules
* prompt assets
* model sources
* UI overrides

This keeps the public core lean while still allowing machine-specific extensions.

## Feature exposure

The frontend should not guess what is available.

Instead:

* backend returns feature flags
* backend returns feature exposure
* UI renders visible, locked, or active surfaces accordingly

This is how JoyBoy can show an optional surface without pretending it is active everywhere.

## Onboarding + Doctor

The recommended install path is:

1. start JoyBoy with the platform launcher
2. finish onboarding
3. check the Doctor
4. add providers
5. import optional packs or model sources

Onboarding gets a new machine to a usable state quickly.
Doctor explains what is missing when the machine is not fully ready.

## Guiding principles

* keep public APIs explicit
* prefer additive extensions over hidden side effects
* avoid duplicating routing logic
* store secrets locally, never in git
* let the UI reflect backend truth

## CSS Variables

JoyBoy uses centralized CSS variables defined in:

```text
web/static/css/variables.css
```

These variables act as design tokens for consistent styling across the UI.

### Categories

* colors (primary, background, state)
* spacing (layout scale)
* typography (font sizes)
* effects (shadows, transitions, overlays)

This approach keeps styling predictable and easy to extend without modifying component-level styles.
