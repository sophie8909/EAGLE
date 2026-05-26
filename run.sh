#!/usr/bin/env bash

set -e

ENV_NAME="eagle"
PYTHON_VERSION="3.11"

INSTALL_MODE=true

for arg in "$@"; do
  case "$arg" in
    --gui)
      INSTALL_MODE=false
      ;;
    --setup|--install)
      INSTALL_MODE=true
      ;;
  esac
done

echo "[1/3] Checking conda..."

if ! command -v conda >/dev/null 2>&1; then
  if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
  elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
  else
    echo "ERROR: conda not found."
    exit 1
  fi
else
  source "$(conda info --base)/etc/profile.d/conda.sh"
fi

echo "[2/3] Checking environment..."

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Creating conda env: $ENV_NAME"
  conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
fi

conda activate "$ENV_NAME"

if [ "$INSTALL_MODE" = true ]; then
  echo "[Install] Installing packages..."

  python -m pip install --upgrade pip

  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
  else
    echo "ERROR: requirements.txt not found"
    exit 1
  fi
fi

echo "[3/3] Launching NiceGUI dashboard..."

python -m eagle_ui.app
