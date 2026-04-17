#!/bin/bash
cd "$(dirname "$0")"

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

    # Create venv if missing
    if [ ! -d "venv" ]; then
        echo "   [1/4] Creating virtual environment..."
        if ! command -v python3 >/dev/null 2>&1; then
            echo "   [ERROR] python3 was not found."
            echo "           Install Python 3.12+ first, then run setup again."
            read -p "   Press Enter..."
            show_menu
            return
        fi
        if ! python3 -m venv venv; then
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
    read -p "   Press Enter..."
    show_menu
}

# Start the menu
show_menu
