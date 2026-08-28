#!/bin/bash
# Script to run pipeline with venv automatically

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "[SETUP] Creating Python Virtual Environment (venv)..."
    python3 -m venv venv
    source venv/bin/activate
    echo "[SETUP] Installing libraries from requirements.txt..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

python pipeline.py
