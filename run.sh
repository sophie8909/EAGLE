#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="eagle"
INSTALL_MODE=true
GUI_PORT="${EAGLE_GUI_PORT:-8082}"

for arg in "$@"; do
  case "$arg" in
    --gui)
      INSTALL_MODE=false
      ;;
    --setup|--install)
      INSTALL_MODE=true
      ;;
    --mock)
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

echo "[1/3] Checking conda..."

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
  echo "ERROR: conda not found. Install or initialize conda first." >&2
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"

echo "[2/3] Checking environment..."

if ! conda env list | awk 'NF && $1 !~ /^#/ {print $1}' | grep -qx "$ENV_NAME"; then
  echo "Creating conda env: $ENV_NAME"
  conda env create --file environment.yml
fi

conda activate "$ENV_NAME"

if [ "$INSTALL_MODE" = true ]; then
  echo "[Install] Installing EAGLE and its Python dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -e .
fi

echo "[3/3] Launching NiceGUI dashboard..."

echo "GUI URL: http://127.0.0.1:${GUI_PORT}"
EAGLE_GUI_PORT="$GUI_PORT" python -m eagle_ui
