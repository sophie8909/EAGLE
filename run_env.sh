#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
COMMAND="start"
if [[ $# -gt 0 && "$1" != --* ]]; then
  COMMAND="$1"
  shift
fi
MODEL_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      [[ $# -ge 2 ]] || { echo "ERROR: --model requires a GGUF path." >&2; exit 2; }
      MODEL_ARGS+=(--model "$2")
      shift 2
      ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$COMMAND" in start|stop|restart|status|check) ;; *) echo "ERROR: unknown command: $COMMAND" >&2; exit 2 ;; esac

exec conda run --no-capture-output -n eagle \
  python -m eagle runtime "$COMMAND" --config configs/runtime.yaml "${MODEL_ARGS[@]}"
