#!/bin/bash
cd "$(dirname "$0")"

JOYBOY_QUICK_START=1
JOYBOY_SHOW_MENU=0
JOYBOY_RUN_SETUP=0

case "${1:-}" in
    --menu)
        JOYBOY_QUICK_START=0
        JOYBOY_SHOW_MENU=1
        ;;
    --setup)
        JOYBOY_RUN_SETUP=1
        ;;
    --restart|--quick|"")
        JOYBOY_QUICK_START=1
        ;;
esac

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
JOYBOY_LOCAL_URL="${JOYBOY_LOCAL_URL:-http://127.0.0.1:7860}"

MIN_PY_MAJOR=3
MIN_PY_MINOR=10

python_version_ok() {
    "$1" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_version_label() {
    "$1" - <<'PY' 2>/dev/null
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
}

python_has_venv() {
    "$1" - <<'PY' >/dev/null 2>&1
import ensurepip
import venv
PY
}

find_compatible_python() {
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && python_version_ok "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

venv_python_ok() {
    [ -x "venv/bin/python" ] && python_version_ok "venv/bin/python"
}

stop_existing_joyboy() {
    if [ "${JOYBOY_SKIP_STOP_OLD:-}" = "1" ]; then
        return 0
    fi

    local project_dir
    project_dir="$(pwd -P)"
    local pids
    pids="$(pgrep -f "web/app.py" 2>/dev/null || true)"

    for pid in $pids; do
        [ -n "$pid" ] || continue
        [ "$pid" = "$$" ] && continue
        [ "$pid" = "${PPID:-}" ] && continue
        local cwd cmdline
        cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
        cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [ "$cwd" = "$project_dir" ] && printf '%s' "$cmdline" | grep -q "web/app.py"; then
            echo "   [STARTUP] Stopping previous JoyBoy server (pid $pid)..."
            kill "$pid" 2>/dev/null || true
        fi
    done

    sleep 1
    for pid in $pids; do
        [ -n "$pid" ] || continue
        kill -0 "$pid" 2>/dev/null || continue
        local cwd cmdline
        cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
        cmdline="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        if [ "$cwd" = "$project_dir" ] && printf '%s' "$cmdline" | grep -q "web/app.py"; then
            echo "   [STARTUP] Force stopping previous JoyBoy server (pid $pid)..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

show_python_install_help() {
    echo "   [ERROR] Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ was not found."
    echo "           Install a recent Python, then run setup again."
    echo ""
    echo "           Recommended on macOS:"
    echo "             brew install python@3.12"
    echo ""
}

show_python_venv_help() {
    echo "   [ERROR] Python venv/ensurepip support is missing or broken."
    echo "           Install a complete Python build, then run setup again."
    echo ""
    echo "           Recommended on macOS:"
    echo "             brew install python@3.12"
    echo "             brew link --overwrite python@3.12"
    echo ""
}

print_url_hint() {
    echo ""
    echo "   ================================================================"
    echo "     JoyBoy opens in your browser at:"
    echo ""
    echo "         $JOYBOY_LOCAL_URL"
    echo ""
    echo "     Keep this terminal open while you use JoyBoy."
    echo "     If the browser does not open, copy/paste the URL above."
    echo "   ================================================================"
    echo ""
}

show_menu() {
    clear
    echo ""
    echo "                                    ████████"
    echo "                                   █████████"
    echo "                                   ██████████"
    echo "                                  ████████████"
    echo "                            ███████████████████████"
    echo "              ███       ███████████████████████████████         ███"
    echo "            █████████████████████████████████████████████████████"
    echo "           ███████████████████████            █████████████████   ███"
    echo "           ██████████████████                      ██████████   ██████"
    echo "           ███████████████                            ██████  ███████"
    echo "            ████████████                                 █  ████████"
    echo "            █████████                ███████               █████████"
    echo "           █████████           ██████████████████           █████████"
    echo "          ████████           ██████████████████████           ████████"
    echo "         ████████          ████████████████████████            ████████"
    echo "         ███████         ████████████████████████   ███         ███████"
    echo "        ███████         ███████████████████████   ██████         ███████"
    echo "        ███████        ██████████████████████   █████████        ███████"
    echo "       ████████       ██████████████████████   ███████████        ███████"
    echo "  ████████████        ████                            ████        ███████████"
    echo " █████████████  ███████████████████████    ██████████████████████ █████████████"
    echo " █████████████ ███████████████████████   ██████████████████████████████████████"
    echo " █████████████       █████                            █████       █████████████"
    echo " █████████████        ████                            ████        █████████████"
    echo "    ██████████        ████                            ████        ███████████"
    echo "        ███████        ████                          ████        ████████"
    echo "        ███████         ████                        ████         ███████"
    echo "         ███████         ██                       █████         ████████"
    echo "         ████████           █████               ██████         ████████"
    echo "          ████████          ████████████████████████          ████████"
    echo "           ████████            ██████████████████            ████████"
    echo "            ████████               ██████████              ██████████"
    echo "            ███████  ██                                  ███████████"
    echo "            █████   █████                              ██████████████"
    echo "           ████   ██████████                        █████████████████"
    echo "           ███  █████████████████              ███████████████████████"
    echo "              ███████████████████████████████████████████████████████"
    echo "             █████      ████████████████████████████████      █████"
    echo "           █                ████████████████████████"
    echo "         █                        ████████████"
    echo "                                   ██████████"
    echo "                                   █████████"
    echo "                                    ████████"
    echo ""
    echo "   ========================================================================"
    echo ""
    echo "                             J O Y B O Y"
    echo ""
    echo "                     \"Dream. Create. Be Free.\""
    echo ""
    echo "               100% Local  -  Zero Cloud  -  No Limits"
    echo ""
    echo "   ========================================================================"
    echo ""
    echo ""
    echo "      [1]  Full setup (first run / repair)"
    echo ""
    echo "      [2]  Quick start"
    echo ""
    echo "      [Q]  Quit"
    echo ""
    echo ""
    read -p "      Choice: " choice

    case $choice in
        1) setup ;;
        2) start_app ;;
        q|Q) exit 0 ;;
        *) show_menu ;;
    esac
}

setup() {
    clear
    echo ""
    echo "   ================================================================"
    echo "                   SETUP - Installation"
    echo "   ================================================================"
    echo ""
    print_url_hint

    PYTHON_BIN="$(find_compatible_python)"
    if [ -z "$PYTHON_BIN" ]; then
        show_python_install_help
        read -p "   Press Enter..."
        show_menu
        return
    fi

    echo "   Python base: $("$PYTHON_BIN" --version 2>&1)"
    if ! python_has_venv "$PYTHON_BIN"; then
        show_python_venv_help
        read -p "   Press Enter..."
        show_menu
        return
    fi

    # Create venv if missing or too old
    if [ -d "venv" ] && ! venv_python_ok; then
        OLD_VERSION="$(python_version_label "venv/bin/python")"
        echo "   [1/4] Existing virtual environment uses Python ${OLD_VERSION:-unknown}"
        echo "         Recreating it with $("$PYTHON_BIN" --version 2>&1)..."
        rm -rf venv
    fi

    if [ ! -d "venv" ]; then
        echo "   [1/4] Creating virtual environment..."
        if ! "$PYTHON_BIN" -m venv venv; then
            echo "   [ERROR] Could not create the virtual environment."
            read -p "   Press Enter..."
            show_menu
            return
        fi
    else
        echo "   [1/4] Virtual environment OK"
    fi

    # Activate venv
    if ! source venv/bin/activate; then
        echo "   [ERROR] Could not activate the virtual environment."
        read -p "   Press Enter..."
        show_menu
        return
    fi

    echo "   [2/4] Installing dependencies + verification..."
    echo ""
    if ! python scripts/bootstrap.py setup; then
        echo ""
        echo "   [ERROR] Setup failed. Check the messages above, then run setup again."
        read -p "   Press Enter..."
        show_menu
        return
    fi

    echo ""
    echo "   ================================================================"
    echo "                   Setup complete!"
    echo "   ================================================================"
    echo ""
    print_url_hint
    sleep 2
    start_app
}

start_app() {
    clear
    echo ""
    echo "   ================================================================"
    echo "                      JOYBOY - Startup"
    echo "   ================================================================"
    echo ""

    # Activate venv
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    else
        echo "   [!] Virtual environment not found."
        echo "       First launch setup will create it now."
        sleep 1
        setup
        return
    fi

    if ! venv_python_ok; then
        echo "   [ERROR] Virtual environment uses Python $(python_version_label "venv/bin/python")."
        echo "           JoyBoy needs Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+."
        echo "           Setup will recreate the venv now."
        sleep 1
        setup
        return
    fi

    echo "   Python: $(python --version 2>&1)"
    print_url_hint
    echo "   (Ctrl+C to stop)"
    echo ""
    stop_existing_joyboy
    python scripts/open_browser.py --url "$JOYBOY_LOCAL_URL" --timeout 120 >/dev/null 2>&1 &
    python web/app.py

    echo ""
    echo "   ================================================================"
    echo "                   Server stopped"
    echo "   ================================================================"
    echo ""
    if [ "$JOYBOY_QUICK_START" = "1" ]; then
        exit 0
    fi
    read -p "   Press Enter..."
    show_menu
}

if [ "$JOYBOY_SHOW_MENU" = "1" ]; then
    show_menu
elif [ "$JOYBOY_RUN_SETUP" = "1" ]; then
    setup
else
    start_app
fi
