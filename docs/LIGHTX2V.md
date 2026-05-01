# LightX2V Video Backend

LightX2V is an optional local-pack backend for faster Wan video generation. JoyBoy
does not vendor the upstream repository, model weights, generated configs, or
caches in git.

## Install

Use the Video Models catalogue, or run:

```bash
python scripts/install_lightx2v_backend.py
```

The backend is cloned and pinned under:

```text
~/.joyboy/packs/lightx2v/repo
```

Model artifacts stay under JoyBoy's configured model cache, usually
`models/huggingface` or `JOYBOY_MODELS_DIR`.

## Safety Rules

JoyBoy intentionally does not install LightX2V's full `requirements.txt`, because
that file pins Torch/CUDA versions and can downgrade a working JoyBoy install.
The adapter installs only minimal safe Python packages, then installs LightX2V
with `pip install --no-deps -e`.

The default runtime profile uses:

- PyTorch SDPA attention (`torch_sdpa`)
- BF16
- block/model offload when needed
- `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`

Turbo kernels are opt-in only. Set `JOYBOY_LIGHTX2V_TURBO=1` to try the upstream
FP8/SageAttention path; JoyBoy falls back to the safe SDPA profile if the kernel
is not importable.

## Multi-GPU

LightX2V supports distributed parallel inference. JoyBoy enables it
automatically when more than one CUDA GPU is visible. Single-GPU installs stay
on the normal subprocess path.

For a 2x H100 cloud instance:

```bash
./start_linux.sh
```

Optional overrides:

- `2` for two visible GPUs
- `0,1` to force a specific `CUDA_VISIBLE_DEVICES` list
- `auto`, `all`, or `max` to use every visible CUDA GPU
- `1`, `off`, or `single` to force single-GPU mode

`JOYBOY_LIGHTX2V_PARALLEL_ATTN` accepts `ulysses` or `ring`; `ulysses` is the
default. When enabled, JoyBoy injects LightX2V's `parallel` config block and
launches the subprocess through `torch.distributed.run`.

If the distributed subprocess crashes in native CUDA code, for example with
`SIGSEGV` / exit code `-11`, JoyBoy retries the same generation once in
single-GPU mode and rebuilds the config without the parallel block. Disable
that safety fallback with `JOYBOY_LIGHTX2V_SINGLE_GPU_FALLBACK=0`.

## Models

The initial catalogue entries are:

- `lightx2v-wan22-i2v-4step`: Wan 2.2 I2V 4-step, recommended for A100/40GB-class machines.
- `lightx2v-wan22-t2v-4step`: Wan 2.2 T2V 4-step, available when its repos are present.
- `lightx2v-wan22-i2v-8gb`: experimental low-VRAM profile, visible as manual test only.

HF tokens are never stored in git. Use `HF_TOKEN` or the existing local UI/env
configuration when gated downloads require authentication.
