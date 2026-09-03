#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./reflection_inspection.sh INSPECTION_CONFIG [--mock] [--output-dir DIR]" >&2
  exit 2
fi

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CONFIG_TARGET="$1"
shift

exec conda run --no-capture-output -n eagle \
  python -m eagle.reflection_inspection --config "$CONFIG_TARGET" "$@"
