#!/bin/bash
# start_api.sh - Launch the FastAPI server

echo "🚀 Starting Morsebiz Invoice Parser API..."

# Activate virtual environment if needed
# source venv/bin/activate

# Start Uvicorn
uvicorn api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --log-level info

