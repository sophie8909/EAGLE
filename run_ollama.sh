#!/usr/bin/env bash

set -euo pipefail

export OLLAMA_DEBUG=1
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_FLASH_ATTENTION=1

MODEL="${OLLAMA_MODEL:-llama3.1:8b}"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_HOST="$HOST"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama not found."
  exit 1
fi

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet ollama; then
  echo "Stopping system ollama service..."
  sudo systemctl stop ollama
fi

pkill -f "[o]llama serve" || true

sleep 1

echo "Starting Ollama server on $OLLAMA_HOST..."
ollama serve &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

sleep 5

echo "Running model: $MODEL"
ollama run "$MODEL"
