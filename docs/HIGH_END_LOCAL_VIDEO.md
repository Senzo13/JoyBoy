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
