#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEFAULT_SERVER_BIN="$REPO_DIR/model/llama-b9174/llama-server"

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$DEFAULT_SERVER_BIN}"
LLAMA_HOST="${LLAMA_HOST:-0.0.0.0}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_MODEL="${LLAMA_MODEL:-ericflo/Llama-3.2-3B-COT:Q4_K_M}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-4096}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:--1}"

if ! command -v "$LLAMA_SERVER_BIN" >/dev/null 2>&1; then
  echo "ERROR: llama.cpp server binary not found: $LLAMA_SERVER_BIN"
  echo "Set LLAMA_SERVER_BIN to the llama-server executable."
  exit 1
fi

echo "Starting llama.cpp server on http://$LLAMA_HOST:$LLAMA_PORT/v1"
echo "Model: $LLAMA_MODEL"
echo "Command: $LLAMA_SERVER_BIN -hf $LLAMA_MODEL --host $LLAMA_HOST --port $LLAMA_PORT -c $LLAMA_CTX_SIZE -ngl $LLAMA_N_GPU_LAYERS"

exec "$LLAMA_SERVER_BIN" \
  -hf "$LLAMA_MODEL" \
  --host "$LLAMA_HOST" \
  --port "$LLAMA_PORT" \
  -c "$LLAMA_CTX_SIZE" \
  -ngl "$LLAMA_N_GPU_LAYERS"
