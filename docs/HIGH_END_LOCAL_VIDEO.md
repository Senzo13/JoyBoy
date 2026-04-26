# High-End Local Video

JoyBoy keeps high-end video generation local-first. The public core exposes
capabilities and UI controls, while model weights, generated videos, caches, and
machine-specific packs stay outside git.

## Local model profile

- Chat: `llama3.3:70b-instruct-q8_0` for high VRAM setups.
- Extreme chat: `qwen3:235b-a22b-instruct-2507-q4_K_M`.
- Extreme INT8 option: `qwen3:235b-a22b-instruct-2507-q8_0`.
- Video keyframe analysis: `qwen3-vl:32b-instruct-q8_0`.

JoyBoy does not auto-pull these heavy models. Install them explicitly with
Ollama when the machine has enough VRAM/RAM.

## Runtime optimization

On CUDA GPUs, launchers set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
before Python starts so PyTorch can reduce allocator fragmentation during large
video jobs. Video generation also enables cuDNN benchmarking and TF32 matmul
for faster inference without changing model choice, resolution, steps, or
prompts. High-VRAM Wan 5B/FastWan pipelines prefer GPU-direct placement when
they fit. Large MoE/14B pipelines keep CPU offload when needed, and FramePack
uses group offload on 40GB-class cards unless explicitly forced to GPU-direct.

Set `JOYBOY_VIDEO_FORCE_CPU_OFFLOAD=1` to force Diffusers video pipelines back
to CPU offload, or `JOYBOY_WAN_NATIVE_FORCE_OFFLOAD=1` to force native Wan 5B
offload if a specific machine is too tight on VRAM. Set
`JOYBOY_VIDEO_DISABLE_OOM_RETRY=1` to disable the automatic Wan/FastWan retry
from GPU-direct to CPU offload. Set `JOYBOY_FASTWAN_FORCE_OFFLOAD=1` to keep
FastWan offloaded, or `JOYBOY_FRAMEPACK_GPU_DIRECT=1` to test FramePack
GPU-direct on cards with more spare VRAM.

## Video continuation

Each generated video now gets a persisted session under `output/videos`, which
is ignored by git. A session stores:

- the generated video path and model metadata;
- prompt/final prompt, FPS, frame count, and duration;
- keyframe thumbnails and the last frame for continuation;
- optional analysis and continuation chain metadata.

When continuing a video, JoyBoy uses the selected keyframe as the I2V anchor,
optionally analyzes the existing keyframes locally, builds a continuity prompt,
generates the next segment, trims the duplicated anchor frame, and joins the
new segment to the source MP4.

## Audio

`audio_engine=auto` prefers native LTX-2 audio when available. Otherwise, when
automatic audio is enabled, JoyBoy runs MMAudio on the final clip so continuation
audio matches the whole video.
