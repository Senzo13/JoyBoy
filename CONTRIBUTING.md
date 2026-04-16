# Contributing

Thanks for considering a contribution to JoyBoy.

## Before you start

- read the README
- read the Code of Conduct
- keep secrets out of git
- keep generated assets, caches, and weights out of the repo
- prefer small, reviewable changes

## First contribution path

If this is your first JoyBoy contribution:

1. pick an open [`good first issue`](https://github.com/Senzo13/JoyBoy/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22)
2. read the issue acceptance criteria before editing
3. keep the change narrow and user-facing
4. run the smallest relevant check listed in the issue
5. open a PR with screenshots if the UI changed

Useful starting points:

- [Good First Issues](docs/GOOD_FIRST_ISSUES.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and Content Policy](docs/SECURITY_AND_CONTENT_POLICY.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## Branches and pull requests

The public `main` branch is protected. External contributors should fork the repo, create a focused branch, and open a pull request. Maintainers review and merge PRs into `main`.

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
- link the issue they close when applicable

## Scope guidelines

Please avoid bundling unrelated changes together. Router, UI, model management, onboarding, and docs often touch each other, but try to keep each PR centered on one coherent improvement.

## Security and sensitive content

Do not open a public issue for secrets leakage, unsafe file handling, or private pack contents. Follow [SECURITY.md](SECURITY.md).

The public core should stay neutral. Optional local packs can extend behavior, but pack-specific assets and generated outputs should stay outside the repo unless they are safe, licensed, and intentionally public.
