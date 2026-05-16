#!/usr/bin/env bash

set -euo pipefail

BASE_NAME="${1:-eagle}"

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

WATCHDOG_SCRIPT="$SCRIPT_DIR/network_watchdog.sh"
OLLAMA_SCRIPT="$SCRIPT_DIR/run_ollama.sh"

OLLAMA_SESSION="${BASE_NAME}-ollama"
WATCHDOG_SESSION="${BASE_NAME}-watchdog"

if ! command -v tmux >/dev/null 2>&1; then
  echo "ERROR: tmux not found."
  exit 1
fi

if [ ! -f "$WATCHDOG_SCRIPT" ]; then
  echo "ERROR: watchdog script not found: $WATCHDOG_SCRIPT"
  exit 1
fi

if [ ! -f "$OLLAMA_SCRIPT" ]; then
  echo "ERROR: ollama script not found: $OLLAMA_SCRIPT"
  exit 1
fi

# Start ollama session
if tmux has-session -t "$OLLAMA_SESSION" 2>/dev/null; then
  echo "tmux session already running: $OLLAMA_SESSION"
else
  tmux new-session -d -s "$OLLAMA_SESSION" \
    "cd '$SCRIPT_DIR' && exec bash ./run_ollama.sh"

  echo "Started tmux session: $OLLAMA_SESSION"
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
echo "Attach ollama:"
echo "tmux attach -t $OLLAMA_SESSION"

echo
echo "Attach watchdog:"
echo "tmux attach -t $WATCHDOG_SESSION"