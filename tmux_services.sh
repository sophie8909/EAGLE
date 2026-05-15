#!/usr/bin/env bash

set -euo pipefail

SESSION_NAME="${1:-eagle-services}"
SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"
WATCHDOG_SCRIPT="$SCRIPT_DIR/network_watchdog.sh"
OLLAMA_SCRIPT="$SCRIPT_DIR/run_ollama.sh"

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

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "tmux session already running: $SESSION_NAME"
  exit 0
fi

tmux new-session -d -s "$SESSION_NAME" -n services "cd '$SCRIPT_DIR' && exec bash ./run_ollama.sh"
tmux split-window -h -t "$SESSION_NAME:services" "cd '$SCRIPT_DIR' && exec bash ./network_watchdog.sh"
tmux select-pane -t "$SESSION_NAME:services.0"
echo "Started tmux session: $SESSION_NAME"
echo "Attach with: tmux attach -t $SESSION_NAME"
