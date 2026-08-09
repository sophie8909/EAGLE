#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CALLER_DIR="$(pwd)"
cd "$ROOT_DIR"

if [[ $# -eq 0 || "${1:-}" == "--latest" ]]; then
  exec python -m eagle analyze --runtime-config "$ROOT_DIR/configs/runtime.yaml" "$@"
fi

RUN_DIR="$1"
shift
if [[ "$RUN_DIR" != /* ]]; then
  RUN_DIR="$CALLER_DIR/$RUN_DIR"
fi
exec python -m eagle analyze \
  --runtime-config "$ROOT_DIR/configs/runtime.yaml" \
  --run-dir "$RUN_DIR" "$@"
