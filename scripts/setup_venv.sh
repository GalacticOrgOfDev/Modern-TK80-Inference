#!/bin/sh
# Create .venv and install core deps so the app can launch for testing.
# Run from the repo root: scripts/setup_venv.sh
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-core.txt
echo ""
echo "venv ready. Activate and launch:"
echo "  source .venv/bin/activate"
echo "  python -m app.launcher"
