#!/usr/bin/env bash
# ShipMate setup script for Linux/macOS
set -euo pipefail

echo "Setting up ShipMate..."

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "Error: Python 3.10+ is required." >&2
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo ""
echo "Setup complete!"
echo "Activate:  source .venv/bin/activate"
echo "Run app:   python start.py"
echo "Run tests: python -m pytest tests/"
