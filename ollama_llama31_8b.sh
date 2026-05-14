#!/usr/bin/env bash

set -euo pipefail

MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama not found."
  exit 1
fi

ollama run "$MODEL"
