#!/usr/bin/env bash
set -euo pipefail

# Compatibility entry point retained for existing bookmarks. The interactive
# LLM-server workflow owns llama.cpp startup and topology updates now.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$#" -gt 0 ]]; then
    echo "experiment_env/start_llama_server.sh is now interactive and ignores command-line arguments."
    echo "Use ./experiment_env/start.sh, then choose 'LLM server - model host'."
    echo ""
fi

exec "$SCRIPT_DIR/scripts/02_llm_server.sh"
