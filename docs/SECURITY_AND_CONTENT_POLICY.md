# Security and Content Policy

JoyBoy is designed as a local-first application.

## Local-first expectations

- user files stay on the user machine
- provider secrets stay local
- model downloads are initiated by the local user
- optional local packs extend the app outside the public core

## Public core vs local extensions

The public repository should remain focused on:

- routing
- orchestration
- model management
- onboarding
- diagnostics
- provider integration
- reusable UI

Optional local extensions should be loaded through local packs instead of being hardwired into the public surface.

## Repository hygiene

- do not commit secrets
- do not commit model weights
- do not commit local caches or outputs
- prefer neutral documentation and reproducible setup instructions

## Public README media

Public screenshots and GIFs should be safe, consent-based, and non-explicit.

Recommended demo assets:

- UI screenshots
- neutral image-edit before/after examples
- onboarding, Doctor, model picker, or local pack management screens
- short videos showing the workflow rather than sensitive outputs

Avoid putting explicit adult, private, or identity-sensitive outputs directly in the public README. If an optional local pack needs separate documentation, host it separately with clear warnings and make sure it complies with the hosting platform rules, model licenses, and all applicable laws.

## Contributor rule of thumb

If a capability depends on machine-local assets, sensitive prompts, private tokens, or optional behavior, prefer expressing it through a local pack or a local configuration gate rather than hardcoding it directly into the public core.

## Screenshort and GIF Safety Checklist
- [ ] Screenshot content is safe for public viewing
- [ ] Proper consent has been obtained if people or user data are shown
- [ ] No secrets are visible (API keys, passwords, tokens)
- [ ] No private files or sensitive data are included