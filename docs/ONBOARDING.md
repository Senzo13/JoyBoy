# Onboarding

JoyBoy ships with a first-run onboarding flow to avoid manual setup for every user.

## Current flow

The onboarding currently covers:

1. local profile selection
2. optional display name
3. hardware detection and default setup recommendations
4. a readiness snapshot powered by the Doctor

The backend also persists onboarding state in the local JoyBoy config so the UI and runtime can stay aligned.

## What it writes locally

Onboarding state is stored outside git in:

```text
~/.joyboy/config.json
```

It can include:

- `completed`
- `locale`
- `profile_type`
- `profile_name`
- `last_completed_at`

## Restarting onboarding

From the app:

- open `Settings > Profil`
- click `Relancer`

This resets onboarding state locally and opens the wizard again.

## Design goal

The onboarding should help users reach a working local setup without reading the whole repo first.

## Companion CLI check

If you want the same readiness view from the terminal:

```bash
python scripts/bootstrap.py doctor
```
