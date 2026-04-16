# Security Policy

## Supported scope

Security reports are welcome for:

- secrets leakage risks
- unsafe local file handling
- remote exposure mistakes
- provider credential handling
- unsafe archive import behavior

## Reporting

Please do not open a public issue for sensitive security problems.

Instead:

- contact the maintainer privately
- include steps to reproduce
- include affected files, routes, or screens

## Secrets

- never commit real tokens
- use `.env`, environment variables, or the local settings UI
- remember that UI-managed secrets live in `~/.joyboy/config.json`
