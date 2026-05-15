#!/usr/bin/env bash

set -euo pipefail

export OLLAMA_DEBUG=1
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_FLASH_ATTENTION=1

MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama not found."
  exit 1
fi

# Stop existing ollama service if running
if systemctl is-active --quiet ollama; then
  echo "Stopping system ollama service..."
  sudo systemctl stop ollama
fi

# Kill any remaining ollama processes
pkill -f ollama || true

sleep 1

echo "Starting Ollama server..."
ollama serve &
SERVER_PID=$!

sleep 5

echo "Running model: $MODEL"
ollama run "$MODEL"
