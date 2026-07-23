#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

while true; do
    printf '\nEAGLE Experiment Environment\n'
    printf '============================\n'
    echo "1. Local server - EA host"
    echo "2. LLM server - model host"
    echo "3. Discover and organize models"
    echo "4. Show configuration"
    echo "5. Exit"
    read -r -p "Choose an option [1-5]: " choice
    case "${choice:-}" in
        1) "$ROOT_DIR/scripts/03_local_server.sh" ;;
        2) "$ROOT_DIR/scripts/02_llm_server.sh" ;;
        3) "$ROOT_DIR/scripts/01_discover_models.sh" ;;
        4)
            # shellcheck source=scripts/lib/common.sh
            source "$ROOT_DIR/scripts/lib/common.sh"
            show_topology
            pause_for_enter
            ;;
        5) exit 0 ;;
        *) echo "Invalid selection." ;;
    esac
done
