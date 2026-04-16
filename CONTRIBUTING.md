# Contributing

Thanks for considering a contribution to JoyBoy.

## Before you start

- read the README
- keep secrets out of git
- keep generated assets, caches, and weights out of the repo
- prefer small, reviewable changes

## Architecture expectations

JoyBoy is being structured as:

- a clean public core
- local provider configuration
- optional local packs loaded outside the repo

When adding features:

- reuse existing helpers
- avoid duplicating routing logic
- prefer explicit interfaces over hardcoded side effects
- keep UI behavior aligned with backend feature exposure

## Setup

1. run the platform start script
2. open JoyBoy locally
3. use `Settings > Models` to configure providers
4. run the Doctor before debugging deeper issues

Optional terminal check:

```bash
python scripts/bootstrap.py doctor
```

## Pull requests

Good PRs usually:

- explain the problem clearly
- describe the user-facing impact
- mention any settings, routes, or model-loading behavior affected
- include screenshots when the UI changes

## Scope guidelines

Please avoid bundling unrelated changes together. Router, UI, model management, onboarding, and docs often touch each other, but try to keep each PR centered on one coherent improvement.
