#!/usr/bin/env bash
# Discord Media Downscaler — one-click dependency setup for Linux / macOS
# Creates a virtualenv and installs all Python dependencies.
# After this, run: ./run.sh   (or double-click run.command on macOS)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================"
echo " Discord Media Downscaler — Install"
echo "================================================"
echo ""

# ── Require Python 3.9+ ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo "  Linux:  sudo apt install python3 python3-venv python3-tk"
    echo "  macOS:  brew install python3   (or download from python.org)"
    exit 1
fi

PYVER=$(python3 -c 'import sys; print(sys.version_info >= (3, 9))')
if [ "$PYVER" != "True" ]; then
    echo "ERROR: Python 3.9 or newer is required."
    python3 --version
    exit 1
fi

# ── Linux: check tkinter is available ────────────────────────────────────────
if [[ "$(uname -s)" == "Linux" ]]; then
    if ! python3 -c "import tkinter" 2>/dev/null; then
        echo "ERROR: tkinter not found."
        echo "  Install with: sudo apt install python3-tk"
        exit 1
    fi
fi

# ── Create virtualenv ─────────────────────────────────────────────────────────
if [ ! -f "venv/bin/python" ]; then
    echo "Creating virtualenv..."
    python3 -m venv venv
fi

# ── Install dependencies ──────────────────────────────────────────────────────
echo "Installing dependencies (this may take a minute on first run)..."
venv/bin/pip install --upgrade pip -q
venv/bin/pip install --upgrade -r requirements.txt -q

echo ""
echo "================================================"
echo " Done! Run the app with:"
echo "   ./run.sh          (terminal)"
if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "   Double-click run.command  (Finder)"
fi
echo "================================================"
