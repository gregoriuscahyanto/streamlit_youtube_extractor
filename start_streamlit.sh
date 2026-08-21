#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "[ERROR] .venv nicht gefunden."
    echo "Einmalig ausfuehren:"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

source .venv/bin/activate

echo "Starting streamlit_youtube_extractor..."
echo "http://localhost:8501"

python -m streamlit run app.py
