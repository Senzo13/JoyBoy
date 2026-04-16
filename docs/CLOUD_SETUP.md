# Cloud / Remote GPU Setup

Use this guide when JoyBoy runs on a remote GPU machine such as Lambda, RunPod, Vast.ai, or a self-managed Linux box.

## 1. Clone the project

```bash
cd ~
git clone <YOUR_REPOSITORY_URL>
cd crock
```

Do not hardcode tokens in the clone URL.

## 2. Configure providers

You have two safe options:

### Option A: local `.env`

```bash
cp .env.example .env
```

Then edit `.env` with your own values:

```bash
HF_TOKEN=hf_your_token_here
CIVITAI_API_KEY=your_civitai_key_here
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

### Option B: JoyBoy UI

Start JoyBoy once, open `Settings > Models`, and save provider secrets there.

UI-managed secrets are stored locally in `~/.joyboy/config.json` and stay out of git.

## 3. Install and start JoyBoy

### Linux

```bash
./start_linux.sh
```

### Manual fallback

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 web/app.py
```

JoyBoy listens on:

```text
http://127.0.0.1:7860
```

## 4. Access JoyBoy from another machine

### SSH tunnel

```bash
ssh -L 7860:localhost:7860 user@server-ip
```

Then open:

```text
http://127.0.0.1:7860
```

### Cloudflare Tunnel

If you already use `cloudflared`, you can expose the local port through your own tunnel workflow. Keep the public endpoint private and temporary unless you know exactly what you are exposing.

## 5. Recommended first checks

After startup:

1. open JoyBoy
2. complete onboarding
3. open `Settings > Models`
4. run the Doctor
5. verify providers and disk paths

## 6. Troubleshooting

### Ollama not reachable

Set or override:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
```

### CUDA out of memory

- use the Doctor report to confirm GPU memory
- prefer lighter default models
- unload unused models from the UI

### Provider download fails

- verify the provider key in `Settings > Models`
- confirm the source URL is public or that the key grants access

### Port already in use

```bash
lsof -i :7860
```

Then stop the conflicting process.
