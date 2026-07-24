#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "\${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="eagle"
INSTALL_MODE=true
GUI_PORT="\${EAGLE_GUI_PORT:-8082}"

for arg in "$@"; do
    case "$arg" in
        --gui|--skip-install)
            INSTALL_MODE=false
            ;;
        --setup|--install)
            INSTALL_MODE=true
            ;;
        *)
            echo "Unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

if ! command -v conda >/dev/null 2>&1; then
    for conda_root in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/miniforge3"; do
        if [ -f "$conda_root/etc/profile.d/conda.sh" ]; then
            # shellcheck disable=SC1090
            source "$conda_root/etc/profile.d/conda.sh"
            break
        fi
    done
fi
if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda is required for the EAGLE runtime." >&2
    exit 1
fi
source "$(conda info --base)/etc/profile.d/conda.sh"

if ! conda env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -qx "$ENV_NAME"; then
    conda env create --file "$ROOT_DIR/environment.yml"
fi
conda activate "$ENV_NAME"

if [ "$INSTALL_MODE" = true ]; then
    python -m pip install --upgrade pip
    python -m pip install -e "$ROOT_DIR"
fi

GUI_PID=""
WATCHDOG_PID=""
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [ -n "$WATCHDOG_PID" ] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
        kill "$WATCHDOG_PID" 2>/dev/null || true
    fi
    if [ -n "$GUI_PID" ] && kill -0 "$GUI_PID" 2>/dev/null; then
        kill "$GUI_PID" 2>/dev/null || true
    fi
    wait "$WATCHDOG_PID" 2>/dev/null || true
    wait "$GUI_PID" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT INT TERM

echo "EAGLE GUI: http://127.0.0.1:\${GUI_PORT}"
EAGLE_GUI_PORT="$GUI_PORT" python -m eagle_ui &
GUI_PID=$!
python -m eagle.runtime.watchdog --pid "$GUI_PID" &
WATCHDOG_PID=$!

set +e
wait "$GUI_PID"
GUI_STATUS=$?
set -e
exit "$GUI_STATUS"