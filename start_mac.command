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
    echo "      [1]  Setup complet (premiere fois / reparer)"
    echo ""
    echo "      [2]  Demarrer rapidement"
    echo ""
    echo "      [Q]  Quitter"
    echo ""
    echo ""
    read -p "      Choix: " choice

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

    # Creer venv si n'existe pas
    if [ ! -d "venv" ]; then
        echo "   [1/4] Creation de l'environnement virtuel..."
        python3 -m venv venv
    else
        echo "   [1/4] Environnement virtuel OK"
    fi

    # Activer venv
    source venv/bin/activate

    echo "   [2/4] Bootstrap dependances + verification..."
    echo ""
    python scripts/bootstrap.py setup

    echo ""
    echo "   ================================================================"
    echo "                   Setup termine !"
    echo "   ================================================================"
    echo ""
    sleep 2
    start_app
}

start_app() {
    clear
    echo ""
    echo "   ================================================================"
    echo "                      JOYBOY - Demarrage"
    echo "   ================================================================"
    echo ""

    # Activer venv
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    else
        echo "   [!] Environnement virtuel non trouve."
        echo "       Lance le Setup d'abord (option 1)"
        read -p "   Appuie sur Entree..."
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
    echo "   (Ctrl+C pour arreter)"
    echo ""
    python web/app.py

    echo ""
    echo "   ================================================================"
    echo "                   Serveur arrete"
    echo "   ================================================================"
    echo ""
    read -p "   Appuie sur Entree..."
    show_menu
}

# Lancer le menu
show_menu
