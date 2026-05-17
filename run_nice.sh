#!/usr/bin/env bash

set -e

ENV_NAME="eagle"
PYTHON_VERSION="3.11"

GUI_MODE=false
INSTALL_MODE=false

for arg in "$@"; do
  case $arg in
    --gui)
      GUI_MODE=true
      shift
      ;;
    --install)
      INSTALL_MODE=true
      shift
      ;;
  esac
done

# -----------------------------
# Fast path: no setup
# -----------------------------
if [ "$GUI_MODE" = true ]; then
  python -m eagle_gui_web.app
  exit 0
fi

# -----------------------------
# Setup mode
# -----------------------------
echo "[1/3] Checking conda..."

if ! command -v conda >/dev/null 2>&1; then
  echo "ERROR: conda not found."
  exit 1
fi

source "$(conda info --base)/etc/profile.d/conda.sh"

echo "[2/3] Checking environment..."

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Creating conda env: $ENV_NAME"
  conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"

  INSTALL_MODE=true
fi

conda activate "$ENV_NAME"

if [ "$INSTALL_MODE" = true ]; then
  echo "[Install] Installing packages..."

  python -m pip install --upgrade pip

  if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
  else
    echo "requirements.txt not found"
  fi
fi

echo "[3/3] Launching NiceGUI dashboard..."

python -m eagle_gui_web.app
