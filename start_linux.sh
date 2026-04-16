#!/bin/bash
# ============================================================
# Start script for Linux
# Equivalent to start_windows.bat
# Works with Lambda Labs (system Python) or venv
# ============================================================

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cd "$(dirname "$0")"

if [ "${1:-}" = "--setup" ]; then
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}[SETUP]${NC} Creating virtual environment..."
        python3 -m venv venv || exit 1
    fi
    source venv/bin/activate
    python scripts/bootstrap.py setup
    exit $?
fi

# Create venv on first run, then bootstrap dependencies through the shared helper
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[SETUP]${NC} Creating virtual environment..."
    python3 -m venv venv || exit 1
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
