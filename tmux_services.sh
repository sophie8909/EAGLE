#!/usr/bin/env bash

set -euo pipefail

SESSION_NAME="${1:-eagle-services}"
WATCHDOG_SCRIPT="./network_watchdog.sh"
OLLAMA_SCRIPT="./ollama_llama31_8b.sh"

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
  tmux attach-session -t "$SESSION_NAME"
  exit 0
fi

tmux new-session -d -s "$SESSION_NAME" -n services "bash '$WATCHDOG_SCRIPT'"
tmux split-window -h -t "$SESSION_NAME:services" "bash '$OLLAMA_SCRIPT'"
tmux select-pane -t "$SESSION_NAME:services.0"
tmux attach-session -t "$SESSION_NAME"
