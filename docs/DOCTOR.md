# Doctor

JoyBoy includes a local Doctor to help new users understand whether their machine is ready.

## What it checks

- Python runtime
- GPU / CUDA / VRAM visibility
- Ollama availability
- local provider configuration
- writable storage paths
- model readiness
- installed local packs

## Status levels

- `ok`: ready
- `warning`: usable but something should be improved
- `error`: blocking issue

## Where to find it

Open:

- `Settings > Models`
- section `Doctor`

Or run:

```bash
python scripts/bootstrap.py doctor
```

## Why it matters

The Doctor is the shortest path to fixing setup issues before users blame the app, the model, or the router for something that is actually a local environment problem.
