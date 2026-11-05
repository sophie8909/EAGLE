#!/usr/bin/env bash
set -euo pipefail

# Wrapper for python -m eagle experiment; it manages the configured local LLM.
# Use --connect-only when another application already provides the server.

if [[ $# -lt 1 ]]; then
  echo "Usage: ./experiment.sh CONFIG_FOLDER_OR_YAML [--connect-only] [--mock] [--skip-final-test] | ./experiment.sh --resume RUN_DIR_OR_CONFIG_FOLDER [--connect-only] [--mock] [--skip-final-test]" >&2
  exit 2
fi

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ "$1" == "--resume" ]]; then
  exec conda run --no-capture-output -n eagle \
    python -m eagle experiment "$@"
fi

CONFIG_TARGET="$1"
shift

exec conda run --no-capture-output -n eagle \
  python -m eagle experiment --config-dir "$CONFIG_TARGET" "$@"
