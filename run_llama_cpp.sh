#!/usr/bin/env bash

set -euo pipefail

SERVER_BIN="${LLAMA_CPP_SERVER_BIN:-llama-server}"
HOST="${LLAMA_CPP_HOST:-127.0.0.1}"
PORT="${LLAMA_CPP_PORT:-8080}"
MODEL_PATH="${LLAMA_CPP_MODEL_PATH:-}"
CTX_SIZE="${LLAMA_CPP_CTX_SIZE:-8192}"
GPU_LAYERS="${LLAMA_CPP_N_GPU_LAYERS:-999}"

if ! command -v "$SERVER_BIN" >/dev/null 2>&1; then
  echo "ERROR: llama.cpp server binary not found: $SERVER_BIN"
  echo "Set LLAMA_CPP_SERVER_BIN to the llama-server executable."
  exit 1
fi

if [ -z "$MODEL_PATH" ]; then
  echo "ERROR: LLAMA_CPP_MODEL_PATH is required."
  exit 1
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: model file not found: $MODEL_PATH"
  exit 1
fi

echo "Starting llama.cpp server on http://$HOST:$PORT/v1"
echo "Model path: $MODEL_PATH"

exec "$SERVER_BIN" \
  --host "$HOST" \
  --port "$PORT" \
  -m "$MODEL_PATH" \
  -c "$CTX_SIZE" \
  -ngl "$GPU_LAYERS" \
  ${LLAMA_CPP_EXTRA_ARGS:-}
