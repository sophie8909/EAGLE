#!/usr/bin/env bash

set -euo pipefail

BASE_NAME="${1:-eagle}"

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

WATCHDOG_SCRIPT="$SCRIPT_DIR/network_watchdog.sh"
LLAMA_CPP_SCRIPT="$SCRIPT_DIR/run_llama_cpp.sh"

DEFAULT_LLAMA_CPP_SERVER_BIN="$SCRIPT_DIR/model/llama-b9174/llama-server"
DEFAULT_LLAMA_CPP_MODEL_PATH="$SCRIPT_DIR/model/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
OLD_LLAMA_CPP_SERVER_BIN="/home/mhlab/llama-b9174-bin-ubuntu-vulkan-x64/llama-b9174/llama-server"
OLD_LLAMA_CPP_MODEL_PATH="/home/mhlab/.cache/huggingface/hub/models--bartowski--Meta-Llama-3.1-8B-Instruct-GGUF/snapshots/bf5b95e96dac0462e2a09145ec66cae9a3f12067/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
PLACEHOLDER_LLAMA_CPP_MODEL_PATH="/absolute/path/to/your/model.gguf"

LLAMA_CPP_SERVER_BIN="${LLAMA_CPP_SERVER_BIN:-$DEFAULT_LLAMA_CPP_SERVER_BIN}"
LLAMA_CPP_MODEL_PATH="${LLAMA_CPP_MODEL_PATH:-$DEFAULT_LLAMA_CPP_MODEL_PATH}"

if [[ "$LLAMA_CPP_SERVER_BIN" == "$OLD_LLAMA_CPP_SERVER_BIN" ]]; then
  LLAMA_CPP_SERVER_BIN="$DEFAULT_LLAMA_CPP_SERVER_BIN"
fi

if [[ "$LLAMA_CPP_MODEL_PATH" == "$PLACEHOLDER_LLAMA_CPP_MODEL_PATH" || "$LLAMA_CPP_MODEL_PATH" == "$OLD_LLAMA_CPP_MODEL_PATH" ]]; then
  LLAMA_CPP_MODEL_PATH="$DEFAULT_LLAMA_CPP_MODEL_PATH"
fi

LLAMA_CPP_SESSION="${BASE_NAME}-llama-cpp"
WATCHDOG_SESSION="${BASE_NAME}-watchdog"

if ! command -v tmux >/dev/null 2>&1; then
  echo "ERROR: tmux not found."
  exit 1
fi

if [ ! -f "$WATCHDOG_SCRIPT" ]; then
  echo "ERROR: watchdog script not found: $WATCHDOG_SCRIPT"
  exit 1
fi

if [ ! -f "$LLAMA_CPP_SCRIPT" ]; then
  echo "ERROR: llama.cpp script not found: $LLAMA_CPP_SCRIPT"
  exit 1
fi

if [ ! -x "$LLAMA_CPP_SERVER_BIN" ]; then
  echo "ERROR: llama.cpp server binary not executable: $LLAMA_CPP_SERVER_BIN"
  exit 1
fi

if [[ "$LLAMA_CPP_MODEL_PATH" != *.gguf ]]; then
  echo "ERROR: LLAMA_CPP_MODEL_PATH must point to a GGUF file: $LLAMA_CPP_MODEL_PATH"
  exit 1
fi

if [ ! -f "$LLAMA_CPP_MODEL_PATH" ]; then
  echo "ERROR: llama.cpp model file not found: $LLAMA_CPP_MODEL_PATH"
  exit 1
fi

# Start llama.cpp session
if tmux has-session -t "$LLAMA_CPP_SESSION" 2>/dev/null; then
  echo "tmux session already running: $LLAMA_CPP_SESSION"
else
  tmux new-session -d -s "$LLAMA_CPP_SESSION" \
    "cd '$SCRIPT_DIR' && exec env -u MODEL_PATH LLAMA_CPP_SERVER_BIN='$LLAMA_CPP_SERVER_BIN' LLAMA_CPP_MODEL_PATH='$LLAMA_CPP_MODEL_PATH' bash ./run_llama_cpp.sh"

  echo "Started tmux session: $LLAMA_CPP_SESSION"
fi

# Start watchdog session
if tmux has-session -t "$WATCHDOG_SESSION" 2>/dev/null; then
  echo "tmux session already running: $WATCHDOG_SESSION"
else
  tmux new-session -d -s "$WATCHDOG_SESSION" \
    "cd '$SCRIPT_DIR' && exec bash ./network_watchdog.sh"

  echo "Started tmux session: $WATCHDOG_SESSION"
fi

echo
echo "Attach llama.cpp:"
echo "tmux attach -t $LLAMA_CPP_SESSION"

echo
echo "Attach watchdog:"
echo "tmux attach -t $WATCHDOG_SESSION"
