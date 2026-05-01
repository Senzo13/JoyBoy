#!/bin/bash
# ============================================================
# Setup script for Linux cloud GPU (Lambda Labs, RunPod, Vast.ai)
# Downloads all models and dependencies in parallel
# Optimized for Lambda Labs (PyTorch pre-installed)
# ============================================================

set -e

echo "============================================================"
echo "   JoyBoy Cloud GPU Setup"
echo "   Linux + CUDA"
echo "============================================================"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ensure_ubuntu_python_bootstrap() {
    if python3 -c "import ensurepip, venv" >/dev/null 2>&1; then
        return 0
    fi

    echo -e "${YELLOW}[SETUP]${NC} Python venv/ensurepip support is missing."

    if ! command -v apt-get >/dev/null 2>&1; then
        echo -e "${RED}[ERROR]${NC} Install Python venv support for your distro, then rerun this script."
        exit 1
    fi

    local python_minor
    python_minor=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local venv_pkg="python${python_minor}-venv"
    local packages=("$venv_pkg" "python3-venv" "python3-pip")

    echo -e "${YELLOW}[SETUP]${NC} Installing ${packages[*]}..."
    if [ "$(id -u)" -eq 0 ]; then
        apt-get update
        apt-get install -y "${packages[@]}" || apt-get install -y python3-venv python3-pip
    elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y "${packages[@]}" || sudo apt-get install -y python3-venv python3-pip
    else
        echo -e "${RED}[ERROR]${NC} sudo is not available. Run as root:"
        echo "  apt-get update && apt-get install -y ${packages[*]}"
        exit 1
    fi

    python3 -c "import ensurepip, venv" >/dev/null 2>&1 || {
        echo -e "${RED}[ERROR]${NC} Python venv support is still unavailable after apt install."
        exit 1
    }
}

# Check CUDA
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${RED}[ERROR] nvidia-smi not found. Is CUDA installed?${NC}"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} CUDA detected:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python 3 not found${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}[OK]${NC} $PYTHON_VERSION"

# Add ~/.local/bin to PATH (pip installs binaries there)
export PATH="$HOME/.local/bin:$PATH"

ensure_ubuntu_python_bootstrap

# Always use an isolated venv. Some cloud images ship apt-managed Python
# packages with Debian versions that modern pip cannot parse.
if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
    echo -e "${YELLOW}[SETUP]${NC} Removing incomplete virtual environment..."
    rm -rf venv
fi
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[SETUP]${NC} Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo -e "${GREEN}[OK]${NC} Virtual environment activated"

# Install PyTorch with CUDA inside the venv instead of reusing the system stack.
echo -e "${YELLOW}[SETUP]${NC} Installing PyTorch + CUDA..."
pip install --upgrade pip
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128

# ============================================================
# FIX VERSION CONFLICTS (Lambda Labs has system packages that conflict)
# ============================================================
echo -e "${YELLOW}[SETUP]${NC} Fixing version conflicts..."

# huggingface-hub 1.x breaks the currently pinned transformers/diffusers/peft stack.
pip install "huggingface-hub>=0.34.0,<1.0"

# Install requirements
echo -e "${YELLOW}[SETUP]${NC} Installing requirements..."
pip install -r scripts/requirements.txt

# Force reinstall the Python ML libraries to avoid system package conflicts.
# Keep Torch pinned separately above; reinstalling unpinned torchvision can bump
# Torch to a version that external video packs have not validated yet.
echo -e "${YELLOW}[SETUP]${NC} Reinstalling ML stack (fixing Lambda system conflicts)..."
pip install --force-reinstall transformers diffusers accelerate
pip install "huggingface-hub>=0.34.0,<1.0" --force-reinstall

# IMPORTANT: numpy<2 MUST be installed LAST (torchvision pulls numpy 2.x)
# mediapipe/tensorflow need numpy<2
echo -e "${YELLOW}[SETUP]${NC} Forcing numpy<2 (mediapipe/tensorflow compatibility)..."
pip install "numpy<2" --force-reinstall

# Install additional dependencies for Linux
echo -e "${YELLOW}[SETUP]${NC} Installing Linux-specific dependencies..."
pip install triton
pip install flash_attn --no-build-isolation 2>/dev/null || echo -e "${YELLOW}[WARN]${NC} FlashAttention build skipped (Wan native will retry at runtime)"
pip install sageattention --no-build-isolation 2>/dev/null || echo -e "${YELLOW}[WARN]${NC} SageAttention build skipped (will retry at runtime)"

echo ""
echo "============================================================"
echo "   Downloading Models (parallel)"
echo "============================================================"
echo ""

# Create models directory
mkdir -p models/checkpoints

# ============================================================
# FUNCTION: Download with progress (using Python module)
# ============================================================
download_hf_model() {
    local repo=$1
    local name=$2
    local required=${3:-required}
    if [ "$required" = "gated" ] && [ -z "${HF_TOKEN:-}" ] && [ -z "${HUGGINGFACE_TOKEN:-}" ]; then
        echo -e "${YELLOW}[SKIP]${NC} $name requires Hugging Face access. Set HF_TOKEN and rerun to pre-download it."
        return 0
    fi
    echo -e "${YELLOW}[DL]${NC} $name..."
    (
        python3 - "$repo" "$name" <<'PY'
import os
import sys
from huggingface_hub import snapshot_download

repo = sys.argv[1]
name = sys.argv[2]
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or None
snapshot_download(repo, token=token)
print(f"[OK] Downloaded {name}")
PY
    ) || {
        if [ "$required" = "optional" ] || [ "$required" = "gated" ]; then
            echo -e "${YELLOW}[WARN]${NC} Optional model download failed: $name"
            exit 0
        fi
        exit 1
    } &
}

# ============================================================
# IMAGE MODELS
# ============================================================
echo -e "${GREEN}[IMAGE MODELS]${NC}"

# Flux Kontext (editing intelligent, 12B)
download_hf_model "black-forest-labs/FLUX.1-Kontext-dev" "Flux Kontext 12B" "gated"

# SDXL stack (generic inpainting stack)
echo -e "${YELLOW}[DL]${NC} epicRealismXL (CivitAI → downloaded at runtime)..."
# Note: CivitAI models are downloaded at runtime, but we can pre-download SDXL base
download_hf_model "stabilityai/stable-diffusion-xl-base-1.0" "SDXL Base"
download_hf_model "diffusers/stable-diffusion-xl-1.0-inpainting-0.1" "SDXL Inpaint"
download_hf_model "lllyasviel/sd_control_collection" "ControlNet Depth"

# ============================================================
# VIDEO MODELS
# ============================================================
echo -e "${GREEN}[VIDEO MODELS]${NC}"

# Wan 2.2 5B (main video model)
download_hf_model "Wan-AI/Wan2.2-TI2V-5B-Diffusers" "Wan 2.2 5B"

# FastWan (distilled, faster)
download_hf_model "FastVideo/FastWan2.2-TI2V-5B-FullAttn-Diffusers" "FastWan 2.2 5B"

# LTX-Video 2B (includes distilled 0.9.8)
download_hf_model "Lightricks/LTX-Video" "LTX-Video 2B"

# ============================================================
# TEXT ENCODERS (shared)
# ============================================================
echo -e "${GREEN}[TEXT ENCODERS]${NC}"

# T5-XXL (used by LTX, Wan, etc.)
download_hf_model "google/umt5-xxl" "UMT5-XXL"

# ============================================================
# SUPPORT MODELS
# ============================================================
echo -e "${GREEN}[SUPPORT MODELS]${NC}"

# Segmentation
download_hf_model "mattmdjaga/segformer_b2_clothes" "SegFormer B2 Clothes"

# Depth estimation
download_hf_model "LiheYoung/depth-anything-large-hf" "Depth Anything Large"

# Face detection/restoration
download_hf_model "IDEA-Research/grounding-dino-base" "GroundingDINO"

# ============================================================
# OLLAMA (for chat/prompts)
# ============================================================
echo ""
echo -e "${GREEN}[OLLAMA]${NC}"

if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}[DL]${NC} Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Start Ollama in background
echo -e "${YELLOW}[OLLAMA]${NC} Starting Ollama service..."
ollama serve &>/dev/null &
sleep 3

# Download models
echo -e "${YELLOW}[DL]${NC} Downloading Ollama models..."
ollama pull dolphin-phi:2.7b &
ollama pull qwen2.5vl:3b &

# ============================================================
# WAIT FOR ALL DOWNLOADS
# ============================================================
echo ""
echo -e "${YELLOW}[WAIT]${NC} Waiting for all downloads to complete..."
wait

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}   Setup Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "To start the app:"
echo ""
echo "  cd ~/JoyBoy && ./start_linux.sh"
echo ""
echo "Then use SSH tunnel from your PC:"
echo "  ssh -L 7860:localhost:7860 ubuntu@YOUR_IP"
echo "  Open http://localhost:7860 in browser"
echo ""
