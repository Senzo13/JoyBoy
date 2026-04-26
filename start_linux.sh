#!/bin/bash
# ============================================================
# Start script for Linux
# Equivalent to start_windows.bat
# Works with Lambda Labs (system Python) or venv
# ============================================================

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

cd "$(dirname "$0")"

export JOYBOY_MODELS_DIR="${JOYBOY_MODELS_DIR:-$PWD/models}"
export JOYBOY_HF_CACHE_DIR="${JOYBOY_HF_CACHE_DIR:-$JOYBOY_MODELS_DIR/huggingface}"
export HF_HOME="$JOYBOY_HF_CACHE_DIR"
export HF_HUB_CACHE="$JOYBOY_HF_CACHE_DIR"
export HF_ASSETS_CACHE="${HF_ASSETS_CACHE:-$JOYBOY_HF_CACHE_DIR/assets}"

ensure_ubuntu_python_bootstrap() {
    if python3 -c "import ensurepip, venv" >/dev/null 2>&1; then
        return 0
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        echo -e "${RED}[ERROR]${NC} Python venv support is missing. Install it for your distro and rerun this script."
        exit 1
    fi

    local python_minor
    python_minor=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local venv_pkg="python${python_minor}-venv"
    local packages=("$venv_pkg" "python3-venv" "python3-pip")

    echo -e "${YELLOW}[SETUP]${NC} Installing missing Python venv support..."
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
}

create_venv() {
    ensure_ubuntu_python_bootstrap
    if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
        echo -e "${YELLOW}[SETUP]${NC} Removing incomplete virtual environment..."
        rm -rf venv
    fi
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}[SETUP]${NC} Creating virtual environment..."
        python3 -m venv venv || exit 1
    fi
}

if [ "${1:-}" = "--setup" ]; then
    create_venv
    source venv/bin/activate
    python scripts/bootstrap.py setup
    exit $?
fi

# Create venv on first run, then bootstrap dependencies through the shared helper
if [ ! -d "venv" ]; then
    create_venv
    source venv/bin/activate
    python scripts/bootstrap.py setup || exit 1
elif [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
    create_venv
    source venv/bin/activate
    python scripts/bootstrap.py setup || exit 1
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo -e "${GREEN}[OK]${NC} Virtual environment activated"
else
    echo -e "${GREEN}[OK]${NC} Using system Python"
fi

# Start Ollama if not running
if command -v ollama &> /dev/null; then
    if ! pgrep -x "ollama" > /dev/null; then
        echo -e "${YELLOW}[OLLAMA]${NC} Starting Ollama service..."
        ollama serve &>/dev/null &
        sleep 2
    fi
fi

# Start the app
echo ""
echo -e "${GREEN}Starting JoyBoy...${NC}"
echo ""

python3 web/app.py
