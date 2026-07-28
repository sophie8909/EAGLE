#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OPERATION="start"
RUNTIME_CONFIG="configs/runtime.yaml"

if [[ $# -gt 0 && "$1" != --* ]]; then
    OPERATION="$1"
    shift
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            [[ $# -ge 2 ]] || { echo "ERROR: --config requires a path." >&2; exit 2; }
            RUNTIME_CONFIG="$2"
            shift 2
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done
case "$OPERATION" in start|stop|restart|status|check) ;; *) echo "ERROR: unknown operation: $OPERATION" >&2; exit 2 ;; esac

cd "$ROOT_DIR"
[[ "$RUNTIME_CONFIG" = /* ]] || RUNTIME_CONFIG="$ROOT_DIR/$RUNTIME_CONFIG"
command -v conda >/dev/null 2>&1 || { echo "ERROR: conda is required and was not found in PATH." >&2; exit 1; }
eval "$(conda shell.bash hook)"
CONDA_ENV="$(awk '/^[[:space:]]*conda_env:/ {sub(/^[^:]*:[[:space:]]*/, ""); print; exit}' "$RUNTIME_CONFIG")"
[[ -n "$CONDA_ENV" ]] || { echo "ERROR: environment.conda_env is missing from $RUNTIME_CONFIG." >&2; exit 1; }
conda activate "$CONDA_ENV"
python -m eagle runtime "$OPERATION" --config "$RUNTIME_CONFIG"
