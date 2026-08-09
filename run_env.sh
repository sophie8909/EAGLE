#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMMAND="${1:-start}"
case "$COMMAND" in
  start|stop|restart|status|check) ;;
  *) printf 'Usage: %s [start|stop|restart|status|check]\n' "$0" >&2; exit 2 ;;
esac

exec python -m eagle runtime "$COMMAND" --config "$ROOT_DIR/configs/runtime.yaml"
