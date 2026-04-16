# Linux Cloud GPU Setup

Quick setup for Vast.ai, RunPod, Lambda Labs, etc.

## Requirements
- Ubuntu 20.04+ / Debian 11+
- NVIDIA GPU with CUDA 12+
- 40GB+ disk space for models

## One-liner Setup

```bash
git clone https://github.com/YOUR_REPO/crock.git
cd crock
chmod +x setup_linux.sh start_linux.sh
./setup_linux.sh
```

## Manual Setup

```bash
# 1. Create venv
python3 -m venv venv
source venv/bin/activate

# 2. Install PyTorch + CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

# 3. Install requirements
pip install -r requirements.txt

# 4. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull qwen2.5:1.5b

# 5. Start app
python web/app.py
```

## Access

After starting, you'll see:
```
============================================================
   TUNNEL CLOUDFLARE ACTIF
   https://xxxx-xxxx-xxxx.trycloudflare.com
============================================================
```

Open this URL in your browser (from your local PC).

## Download Models Manually

If setup_linux.sh fails or you want specific models:

```bash
# Image models
huggingface-cli download diffusers/stable-diffusion-xl-1.0-inpainting-0.1
huggingface-cli download lllyasviel/sd_control_collection

# Video models
huggingface-cli download Wan-AI/Wan2.2-TI2V-5B-Diffusers
huggingface-cli download FastVideo/FastWan2.2-TI2V-5B-FullAttn-Diffusers
huggingface-cli download Lightricks/LTX-Video
```

## Troubleshooting

### SageAttention build fails
```bash
# Install build dependencies
apt-get install -y python3-dev build-essential
pip install sageattention --no-build-isolation
```

### Triton errors
```bash
pip uninstall triton-windows -y  # In case it was installed
pip install triton
```

### CUDA out of memory
Models auto-detect VRAM and use appropriate offloading:
- 24GB+: GPU direct (fastest)
- 12-24GB: model_cpu_offload
- <12GB: sequential_cpu_offload (slow)

### FFmpeg not found
```bash
apt-get install -y ffmpeg
```
