#!/bin/bash
cd "$(dirname "$0")"

JOYBOY_QUICK_START=0
if [ "${1:-}" = "--restart" ] || [ "${1:-}" = "--quick" ]; then
    JOYBOY_QUICK_START=1
fi

export JOYBOY_MODELS_DIR="${JOYBOY_MODELS_DIR:-$PWD/models}"
export JOYBOY_HF_CACHE_DIR="${JOYBOY_HF_CACHE_DIR:-$JOYBOY_MODELS_DIR/huggingface}"
export HF_HOME="$JOYBOY_HF_CACHE_DIR"
export HF_HUB_CACHE="$JOYBOY_HF_CACHE_DIR"
export HF_ASSETS_CACHE="${HF_ASSETS_CACHE:-$JOYBOY_HF_CACHE_DIR/assets}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

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
        echo "       Run Setup first (option 1)"
        read -p "   Press Enter..."
        show_menu
        return
    fi

    if ! venv_python_ok; then
        echo "   [ERROR] Virtual environment uses Python $(python_version_label "venv/bin/python")."
        echo "           JoyBoy needs Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+."
        echo "           Run Full setup (option 1) to recreate the venv."
        read -p "   Press Enter..."
        show_menu
        return
    fi

    echo "   Python: $(python --version 2>&1)"
    echo ""
    echo "   ----------------------------------------------------------------"
    echo ""
    echo "                  http://127.0.0.1:7860"
    echo ""
    echo "   ----------------------------------------------------------------"
    echo ""
    echo "   (Ctrl+C to stop)"
    echo ""
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

if [ "$JOYBOY_QUICK_START" = "1" ]; then
    start_app
else
    show_menu
fi
