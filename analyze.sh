#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CALLER_DIR="$PWD"
RUNTIME_CONFIG="$ROOT_DIR/configs/runtime.yaml"
cd "$ROOT_DIR"

if [[ $# -eq 0 ]]; then
    exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --latest
fi
if [[ "$1" = "--latest" ]]; then
    shift
    exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --latest "$@"
fi
RUN_DIR="$1"
if [[ "$RUN_DIR" != /* ]]; then
    RUN_DIR="$CALLER_DIR/$RUN_DIR"
fi
shift
exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --run-dir "$RUN_DIR" "$@"
