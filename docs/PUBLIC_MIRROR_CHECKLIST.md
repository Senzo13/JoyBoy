# Public Mirror Checklist

Use this checklist when preparing a clean public mirror from the private development repo.

## 1. Copy only the public core

Keep:

- reusable core code
- onboarding
- doctor
- provider config
- model import flow
- UI shell
- community files
- neutral docs

Do not copy:

- private experiments
- machine-local caches
- generated outputs
- local packs
- secrets
- test prompts or examples you would not want to publish

## 2. Re-scan the public surface

Before pushing:

- search for hardcoded tokens
- search for provider secrets
- search for legacy private wording
- verify screenshots and GIFs are neutral
- verify docs match the public core and not the private bridge

Recommended commands:

```bash
python scripts/bootstrap.py doctor
```

```bash
python -m py_compile config.py web/routes/settings.py core/infra/packs.py core/infra/doctor.py core/infra/model_imports.py
```

```bash
python scripts/bootstrap.py mirror --dry-run
```

Use `public_mirror.exclude` to keep track of assets and docs that must stay in the private workspace.

## 3. Check repo hygiene

- `.env.example` only contains placeholders
- `.gitignore` covers local outputs and config
- no model weights are committed
- no archives, backups, or temp files are tracked

## 4. Validate onboarding flow

On a fresh machine or clean workspace:

- launcher starts
- onboarding appears
- doctor report loads
- providers can be configured
- model source import resolves correctly

## 5. Validate pack behavior

- no pack installed → optional surfaces stay visible but locked
- invalid pack → import is rejected cleanly
- valid pack → pack is listed and can be activated

## 6. Validate docs

Make sure these files are up to date:

- `README.md`
- `docs/GETTING_STARTED.md`
- `docs/ONBOARDING.md`
- `docs/DOCTOR.md`
- `docs/LOCAL_PACKS.md`
- `docs/ARCHITECTURE.md`
- `CONTRIBUTING.md`
- `SECURITY.md`

## 7. Final GitHub readiness

- issue templates enabled
- PR template present
- code of conduct present
- security policy present
- roadmap or contribution guidance present

The public mirror should feel intentional, easy to install, and safe to contribute to from day one.
