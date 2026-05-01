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
if [ -z "${HF_HUB_CACHE:-}" ] || [ "$HF_HUB_CACHE" = "$JOYBOY_HF_CACHE_DIR" ]; then
    export HF_HUB_CACHE="$JOYBOY_HF_CACHE_DIR/hub"
fi
if [ -z "${HUGGINGFACE_HUB_CACHE:-}" ] || [ "$HUGGINGFACE_HUB_CACHE" = "$JOYBOY_HF_CACHE_DIR" ]; then
    export HUGGINGFACE_HUB_CACHE="$HF_HUB_CACHE"
fi
export HF_ASSETS_CACHE="${HF_ASSETS_CACHE:-$JOYBOY_HF_CACHE_DIR/assets}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export USE_HUB_KERNELS="${USE_HUB_KERNELS:-0}"
JOYBOY_LOCAL_URL="${JOYBOY_LOCAL_URL:-http://127.0.0.1:7860}"

print_url_hint() {
    echo ""
    echo "=============================================================="
    echo "  JoyBoy opens in your browser at:"
    echo ""
    echo "      $JOYBOY_LOCAL_URL"
    echo ""
    echo "  Keep this terminal open while you use JoyBoy."
    echo "  If the browser does not open, copy/paste the URL above."
    echo "=============================================================="
    echo ""
}

stop_existing_joyboy() {
    if [ "${JOYBOY_SKIP_STOP_OLD:-}" = "1" ]; then
        return 0
    fi

    local project_dir
    project_dir="$(pwd -P)"
    local pids=""

    if command -v pgrep >/dev/null 2>&1; then
        pids="$(
            {
                pgrep -f "web/app.py" 2>/dev/null || true
                pgrep -f "$project_dir/web/app.py" 2>/dev/null || true
                pgrep -f "lightx2v" 2>/dev/null || true
            } | sort -u
        )"
    fi

    for pid in $pids; do
        [ -n "$pid" ] || continue
        [ "$pid" = "$$" ] && continue
        [ "$pid" = "${PPID:-}" ] && continue
        [ -d "/proc/$pid" ] || continue

        local cwd cmdline
        cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
        cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        if { printf '%s' "$cmdline" | grep -Fq "$project_dir/web/app.py"; } \
            || { [ "$cwd" = "$project_dir" ] && printf '%s' "$cmdline" | grep -Fq "web/app.py"; } \
            || { printf '%s' "$cmdline" | grep -Fq "lightx2v" && { [ "$cwd" = "$project_dir" ] || printf '%s' "$cmdline" | grep -Fq "$project_dir"; }; }; then
            echo -e "${YELLOW}[STARTUP]${NC} Stopping previous JoyBoy GPU process (pid $pid)..."
            kill "$pid" 2>/dev/null || true
        fi
    done

    sleep 1
    for pid in $pids; do
        [ -n "$pid" ] || continue
        [ -d "/proc/$pid" ] || continue
        local cwd cmdline
        cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
        cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        if { printf '%s' "$cmdline" | grep -Fq "$project_dir/web/app.py"; } \
            || { [ "$cwd" = "$project_dir" ] && printf '%s' "$cmdline" | grep -Fq "web/app.py"; } \
            || { printf '%s' "$cmdline" | grep -Fq "lightx2v" && { [ "$cwd" = "$project_dir" ] || printf '%s' "$cmdline" | grep -Fq "$project_dir"; }; }; then
            echo -e "${YELLOW}[STARTUP]${NC} Force stopping previous JoyBoy GPU process (pid $pid)..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

clear_ghost_gpu_vram() {
    if [ "${JOYBOY_SKIP_GHOST_VRAM_CLEANUP:-}" = "1" ]; then
        return 0
    fi
    command -v nvidia-smi >/dev/null 2>&1 || return 0

    local used_mb gpu_pids
    used_mb="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -d '[:space:]')"
    [ -n "$used_mb" ] || return 0
    gpu_pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits 2>/dev/null | tr -d '[:space:]')"

    if [ "$used_mb" -gt "${JOYBOY_GHOST_VRAM_THRESHOLD_MB:-2048}" ] 2>/dev/null && [ -z "$gpu_pids" ]; then
        echo -e "${YELLOW}[STARTUP]${NC} Ghost VRAM detected (${used_mb}MiB used, no CUDA process)."
        if command -v systemctl >/dev/null 2>&1; then
            if [ "$(id -u)" -eq 0 ]; then
                systemctl restart nvidia-persistenced 2>/dev/null || true
            elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
                sudo -n systemctl restart nvidia-persistenced 2>/dev/null || true
            else
                echo -e "${YELLOW}[STARTUP]${NC} Run manually if VRAM stays high: sudo systemctl restart nvidia-persistenced"
                return 0
            fi
            sleep 3
            local after_mb
            after_mb="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -n 1 | tr -d '[:space:]')"
            echo -e "${GREEN}[STARTUP]${NC} Ghost VRAM cleanup: ${used_mb}MiB -> ${after_mb:-?}MiB"
        fi
    fi
}

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
    print_url_hint
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
print_url_hint
stop_existing_joyboy
clear_ghost_gpu_vram

if [ "${JOYBOY_OPEN_BROWSER:-}" = "1" ] || [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    python scripts/open_browser.py --url "$JOYBOY_LOCAL_URL" --timeout 120 >/dev/null 2>&1 &
fi

python3 web/app.py
