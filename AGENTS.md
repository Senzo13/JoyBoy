# Contributor Notes

This repository is being prepared as a public-ready local AI harness.

## Core Rules

- Treat the repository as a clean public core.
- Keep secrets out of git.
- Keep generated files, model weights, caches, and local packs out of the repo.
- Prefer reusable infrastructure over one-off patches.
- Do not duplicate routing or prompt logic across multiple files.
- Code duplication is prohibited; extract shared components/helpers before adding parallel implementations.

## Public Core vs Local Extensions

- The public core should handle generic chat, image, video, routing, onboarding, doctor, providers, and model orchestration.
- Machine-specific extensions should be loaded through local packs stored outside the repo, typically in `~/.joyboy/packs`.
- UI surfaces that depend on a local pack should remain visible-but-locked when the pack is missing.

## Editing Guidance

- Keep routing decisions centralized.
- Reuse existing helpers before adding new flags or endpoints.
- When adding UI controls, hide or lock them through the feature exposure map instead of hardcoding behavior in multiple views.
- Preserve the existing visual identity unless a UX improvement is clearly worth the change.

## Secrets and Providers

- Provider credentials must be read from environment variables, `.env`, or local UI config.
- Never commit tokens, cookies, or account-specific URLs.
- Update `.env.example` and setup docs when provider behavior changes.

## Open Source Readiness

When making changes, keep these questions in mind:

1. Can a new contributor understand where this logic belongs?
2. Does this change keep the public surface neutral and maintainable?
3. Can the same behavior be extended later through a local pack instead of hardcoding it in the core?
4. Is the install path still obvious for a first-time user?
