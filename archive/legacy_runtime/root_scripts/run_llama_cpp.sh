#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

DEFAULT_SERVER_BIN="$SCRIPT_DIR/model/llama-b9174/llama-server"
DEFAULT_MODEL_PATH="$SCRIPT_DIR/model/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
OLD_SERVER_BIN="/home/mhlab/llama-b9174-bin-ubuntu-vulkan-x64/llama-b9174/llama-server"
OLD_MODEL_PATH="/home/mhlab/.cache/huggingface/hub/models--bartowski--Meta-Llama-3.1-8B-Instruct-GGUF/snapshots/bf5b95e96dac0462e2a09145ec66cae9a3f12067/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
PLACEHOLDER_MODEL_PATH="/absolute/path/to/your/model.gguf"

SERVER_BIN="${LLAMA_CPP_SERVER_BIN:-$DEFAULT_SERVER_BIN}"
HOST="${LLAMA_CPP_HOST:-127.0.0.1}"
PORT="${LLAMA_CPP_PORT:-8080}"
MODEL_PATH="${LLAMA_CPP_MODEL_PATH:-$DEFAULT_MODEL_PATH}"
CTX_SIZE="${LLAMA_CPP_CTX_SIZE:-8192}"
GPU_LAYERS="${LLAMA_CPP_N_GPU_LAYERS:-999}"

if [[ "$SERVER_BIN" == "$OLD_SERVER_BIN" ]]; then
  SERVER_BIN="$DEFAULT_SERVER_BIN"
fi

if [[ "$MODEL_PATH" == "$PLACEHOLDER_MODEL_PATH" || "$MODEL_PATH" == "$OLD_MODEL_PATH" ]]; then
  MODEL_PATH="$DEFAULT_MODEL_PATH"
fi

echo "SERVER_BIN=$SERVER_BIN"
echo "MODEL_PATH=$MODEL_PATH"

if [[ -z "$MODEL_PATH" ]]; then
  echo "ERROR: MODEL_PATH is required. Set LLAMA_CPP_MODEL_PATH or MODEL_PATH."
  exit 1
fi

if [[ "$MODEL_PATH" == *llama-server ]]; then
  echo "ERROR: MODEL_PATH incorrectly points to llama-server"
  exit 1
fi

if [[ "$MODEL_PATH" != *.gguf ]]; then
  echo "ERROR: MODEL_PATH must point to a GGUF file"
  exit 1
fi

if ! command -v "$SERVER_BIN" >/dev/null 2>&1; then
  echo "ERROR: llama.cpp server binary not found: $SERVER_BIN"
  echo "Set LLAMA_CPP_SERVER_BIN to the llama-server executable."
  exit 1
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: model file not found: $MODEL_PATH"
  exit 1
fi

echo "Starting llama.cpp server on http://$HOST:$PORT/v1"
echo "Model path: $MODEL_PATH"
echo "Command: $SERVER_BIN -m $MODEL_PATH --host $HOST --port $PORT -c $CTX_SIZE -ngl $GPU_LAYERS ${LLAMA_CPP_EXTRA_ARGS:-}"

exec "$SERVER_BIN" \
  -m "$MODEL_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  -c "$CTX_SIZE" \
  -ngl "$GPU_LAYERS" \
  ${LLAMA_CPP_EXTRA_ARGS:-}
