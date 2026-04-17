# Releases

JoyBoy uses GitHub Releases as the user-facing update channel. The `main`
branch can move faster than a packaged version, so regular users should follow
release tags instead of treating every commit as a stable update.

## Version Source

The local version is stored in the root `VERSION` file.

Use prerelease tags while the public core is still moving quickly:

```text
v0.1.0-alpha.1
v0.1.0-alpha.2
v0.1.0-beta.1
v0.1.0
```

## Update Checker

The app exposes `/api/version/status` and checks:

- the local `VERSION` value;
- the latest non-draft GitHub release for the configured repository;
- the local git checkout against `origin/main` when `.git` is available.

The result is cached for 24 hours by default. Set these environment variables
to customize behavior:

```text
JOYBOY_UPDATE_REPO=Senzo13/JoyBoy
JOYBOY_UPDATE_BRANCH=main
JOYBOY_UPDATE_CACHE_SECONDS=86400
JOYBOY_UPDATE_CHECK=0
```

`JOYBOY_UPDATE_CHECK=0` disables remote checks while keeping the local version
visible in Settings.

## UI Behavior

JoyBoy keeps update notices quiet:

- no modal;
- no blocking toast;
- a small top-right pill appears only when an update is available;
- full details live in Settings > General > Version.

## Publishing A Release

JoyBoy has two GitHub Actions workflows for alpha releases:

- **Prepare Alpha Release** runs weekly or manually. It checks commits since the
  last `v*` tag, scores the changes, bumps `VERSION`, writes release notes, and
  opens/updates a release PR only when there is enough meaningful change.
- **Publish Release** runs after the release PR is merged into `main`. It tags
  the merge commit and creates the GitHub prerelease from the generated notes.

The scoring is intentionally conservative. Docs-only churn should not publish a
release by itself, while runtime fixes, generation changes, UI work, tests, and
release infrastructure count more.

Manual stable releases can still use the classic path:

1. Update `VERSION`.
2. Commit the change.
3. Tag the same version with a leading `v`.
4. Push the tag.
5. Create a GitHub Release from the tag and mark alpha/beta builds as
   prereleases.

Example:

```bash
git tag v0.1.0-alpha.1
git push origin v0.1.0-alpha.1
```

The release notes should call out install changes, model/runtime fixes, known
platform issues, and whether the build is alpha/beta/stable.

## Automation Thresholds

The prepare workflow defaults to:

```text
min_score=8
min_commits=4
```

You can run it manually from GitHub Actions and set `force=true` to open a
release PR even when the threshold is not met. That is useful for one important
hotfix.
