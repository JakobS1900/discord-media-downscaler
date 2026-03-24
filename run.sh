#!/usr/bin/env bash
# Discord Media Downscaler — run from source (Linux / macOS)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f "venv/bin/python" ]; then
    echo "First run: setting up dependencies..."
    bash install.sh
    echo ""
fi

exec venv/bin/python main.py "$@"
