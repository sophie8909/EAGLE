#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT_DIR/benchmark_models.sh" \
  --experiment ministral3_8b \
  --experiment gemma3_12b \
  "$@"
