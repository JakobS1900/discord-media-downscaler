#!/usr/bin/env bash
# Discord Media Downscaler — macOS Finder double-click launcher
# (Terminal.app sets CWD to $HOME, so we navigate to the script directory first.)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "venv/bin/python" ]; then
    echo "First run: setting up dependencies (this may take a minute)..."
    echo ""
    bash install.sh
    echo ""
fi

venv/bin/python main.py
# No 'exec' — keep Terminal open so the user sees any error output
