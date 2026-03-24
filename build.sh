#!/usr/bin/env bash
# Discord Media Downscaler — build self-contained binary for Linux / macOS
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================"
echo " Discord Media Downscaler — Build"
echo "================================================"
echo ""

if [ ! -f "venv/bin/python" ]; then
    echo "Running install first..."
    bash install.sh
    echo ""
fi

echo "Building binary with PyInstaller..."
venv/bin/python -m PyInstaller DiscordMediaDownscaler.spec --clean --noconfirm

PLATFORM="$(uname -s | tr '[:upper:]' '[:lower:]')"
echo ""
echo "================================================"
echo " SUCCESS: dist/DiscordMediaDownscaler"
echo " Platform: $PLATFORM"
echo ""
echo " To run: ./dist/DiscordMediaDownscaler"
echo "================================================"
