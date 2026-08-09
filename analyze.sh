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
if [[ "$1" = "--run-dir" ]]; then
    shift
    if [[ $# -eq 0 ]]; then
        echo "missing value for --run-dir" >&2
        exit 2
    fi
    RUN_DIR="$1"
    shift
    if [[ "$RUN_DIR" != /* ]]; then
        if [[ -d "$CALLER_DIR/$RUN_DIR" ]]; then
            RUN_DIR="$CALLER_DIR/$RUN_DIR"
        else
            RUN_DIR="$ROOT_DIR/runs/$RUN_DIR"
        fi
    fi
    exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --run-dir "$RUN_DIR" "$@"
fi
if [[ "$1" = "--candidate" ]]; then
    exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --latest "$@"
fi
RUN_DIR="$1"
if [[ "$RUN_DIR" != /* ]]; then
    if [[ -d "$CALLER_DIR/$RUN_DIR" ]]; then
        RUN_DIR="$CALLER_DIR/$RUN_DIR"
    else
        RUN_DIR="$ROOT_DIR/runs/$RUN_DIR"
    fi
fi
shift
exec python -m eagle analyze --runtime-config "$RUNTIME_CONFIG" --run-dir "$RUN_DIR" "$@"
