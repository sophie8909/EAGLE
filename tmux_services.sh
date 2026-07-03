#!/usr/bin/env bash

set -euo pipefail

BASE_NAME="eagle"
MODEL_ALIAS="${MODEL_ALIAS:-llama31}"

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

WATCHDOG_SCRIPT="$SCRIPT_DIR/network_watchdog.sh"
LLAMA_SERVER_SCRIPT="$SCRIPT_DIR/start_llama_server.sh"

usage() {
  cat <<'USAGE'
Usage: ./tmux_services.sh [base-name] [--model llama31|qwen3]

Starts two tmux sessions:
  <base-name>-llama-cpp   ./start_llama_server.sh --model <model>
  <base-name>-watchdog    ./network_watchdog.sh

Defaults:
  base-name: eagle
  model:     llama31

Examples:
  ./tmux_services.sh
  ./tmux_services.sh --model qwen3
  ./tmux_services.sh eagle --model llama31
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "ERROR: --model requires a value." >&2
        usage >&2
        exit 2
      fi
      MODEL_ALIAS="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      BASE_NAME="$1"
      ;;
  esac
  shift
done

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

if [ ! -f "$LLAMA_SERVER_SCRIPT" ]; then
  echo "ERROR: llama server script not found: $LLAMA_SERVER_SCRIPT"
  exit 1
fi

printf -v MODEL_ALIAS_Q '%q' "$MODEL_ALIAS"

# Start llama.cpp session
if tmux has-session -t "$LLAMA_CPP_SESSION" 2>/dev/null; then
  echo "tmux session already running: $LLAMA_CPP_SESSION"
else
  tmux new-session -d -s "$LLAMA_CPP_SESSION" -c "$SCRIPT_DIR" \
    "exec bash ./start_llama_server.sh --model $MODEL_ALIAS_Q"

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
