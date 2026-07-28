#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_CONFIG="$ROOT_DIR/configs/runtime.yaml"
cd "$ROOT_DIR"

command -v conda >/dev/null 2>&1 || { echo "ERROR: conda is required and was not found in PATH." >&2; exit 1; }
eval "$(conda shell.bash hook)"
CONDA_ENV="$(awk '/^[[:space:]]*conda_env:/ {sub(/^[^:]*:[[:space:]]*/, ""); print; exit}' "$RUNTIME_CONFIG")"
[[ -n "$CONDA_ENV" ]] || { echo "ERROR: environment.conda_env is missing from $RUNTIME_CONFIG." >&2; exit 1; }
conda activate "$CONDA_ENV"

if [[ $# -eq 0 ]]; then
    mapfile -t CONFIGS < <(find "$ROOT_DIR/configs/experiments" -maxdepth 1 -type f \( -name '*.yaml' -o -name '*.yml' \) | sort)
    [[ ${#CONFIGS[@]} -gt 0 ]] || { echo "ERROR: no experiment configs found." >&2; exit 1; }
    for index in "${!CONFIGS[@]}"; do printf '%d) %s\n' "$((index + 1))" "${CONFIGS[$index]#$ROOT_DIR/}"; done
    read -r -p "Select experiment: " SELECTION
    [[ "$SELECTION" =~ ^[0-9]+$ ]] && (( SELECTION >= 1 && SELECTION <= ${#CONFIGS[@]} )) || { echo "ERROR: invalid selection." >&2; exit 2; }
    set -- "${CONFIGS[$((SELECTION - 1))]}"
fi

python -m eagle run --config "$1" --runtime-config "$RUNTIME_CONFIG" "${@:2}"
