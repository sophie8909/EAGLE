#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_CONFIG="$ROOT_DIR/configs/runtime.yaml"
cd "$ROOT_DIR"
EXPERIMENT_CONFIG="${1:-configs/experiments/microrts.yaml}"
shift || true
exec conda run --no-capture-output -n eagle \
  python -m eagle run --config "$EXPERIMENT_CONFIG" \
  --runtime-config "$RUNTIME_CONFIG" "$@"
