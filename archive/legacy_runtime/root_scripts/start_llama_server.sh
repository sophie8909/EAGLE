#!/usr/bin/env bash
set -euo pipefail

# Local operations entry point for the OpenAI-compatible llama.cpp server used
# by DSPy runs. This script owns model/server setup only; it does not install
# DSPy/GEPA, manage GUI state, or read experiment configs.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL_BASE_DIR="${MODEL_BASE_DIR:-$ROOT_DIR/models}"

# Model alias selects default Hugging Face repo, GGUF file, and local model dir.
MODEL_ALIAS="${MODEL_ALIAS:-llama31}"
HF_REPO="${HF_REPO:-}"
GGUF_NAME="${GGUF_NAME:-}"
MODEL_DIR="${MODEL_DIR:-}"
MODEL_FILE="${MODEL_FILE:-}"

# Compatibility search path for previously downloaded models outside this repo.
EAGLE_MODEL_DIR="${EAGLE_MODEL_DIR:-$HOME/EAGLE/model}"
# Server runtime defaults. `HOST`/`PORT` line up with DSPY_BASE_URL examples.
CTX_SIZE="${CTX_SIZE:-16384}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
TEMPERATURE="${TEMPERATURE:-0.6}"
TOP_P="${TOP_P:-0.95}"
TOP_K="${TOP_K:-20}"
# llama.cpp clone/build output is external generated material and ignored by Git.
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$ROOT_DIR/vendor/llama.cpp}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-}"
# Token file is local-only and ignored; exported HF_TOKEN remains the runtime
# boundary used by Hugging Face tooling.
HF_TOKEN_FILE="${HF_TOKEN_FILE:-$ROOT_DIR/key/uf_token}"

DOWNLOAD_MODEL=0
INSTALL_LLAMA_CPP=0

usage() {
    # Keep usage text in this script because it is the public CLI surface.
    cat <<'USAGE'
Usage: ./start_llama_server.sh [options]

Standalone llama.cpp OpenAI-compatible server launcher.
It does not read GEPA keys and does not set up GEPA dependencies.

Options:
  --model NAME          Model alias: llama31 or qwen3. Default: llama31.
  --download-model      Download the selected GGUF before starting.
  --install-llama-cpp   Clone/build llama.cpp under vendor/llama.cpp.
  --start-server        Compatibility no-op; this script always starts the server.
  --skip-deps           Compatibility no-op; GEPA deps are never installed here.
  --temperature VALUE   Sampling temperature. Default: 0.6.
  --top-p VALUE         Nucleus sampling top-p. Default: 0.95.
  --top-k VALUE         Top-k sampling. Default: 20.
  -h, --help            Show this help.

Environment overrides:
  MODEL_FILE=/path/to/model.gguf
  MODEL_DIR=/path/to/model-dir
  HF_REPO=owner/repo
  GGUF_NAME=file.gguf
  CTX_SIZE=16384
  HOST=127.0.0.1
  PORT=8080
  N_GPU_LAYERS=99
  TEMPERATURE=0.6
  TOP_P=0.95
  TOP_K=20
  LLAMA_SERVER_BIN=/path/to/llama-server
  EAGLE_MODEL_DIR=/path/to/EAGLE/model
  HF_TOKEN_FILE=key/uf_token

Examples:
  ./start_llama_server.sh --model llama31
  ./start_llama_server.sh --model qwen3
  ./start_llama_server.sh --model qwen3 --download-model
  MODEL_FILE=/path/to/model.gguf ./start_llama_server.sh --model qwen3
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            # Alias is resolved later so env overrides can still supply repo or
            # file details before defaults are filled in.
            MODEL_ALIAS="${2:-}"
            shift
            ;;
        --download-model)
            # Download runs before server startup and writes into ignored
            # `models/` unless MODEL_DIR/MODEL_FILE override it.
            DOWNLOAD_MODEL=1
            ;;
        --install-llama-cpp)
            # Clone/build runs before server startup and writes into ignored
            # `vendor/llama.cpp` unless LLAMA_CPP_DIR overrides it.
            INSTALL_LLAMA_CPP=1
            ;;
        --temperature)
            TEMPERATURE="${2:-}"
            shift
            ;;
        --top-p)
            TOP_P="${2:-}"
            shift
            ;;
        --top-k)
            TOP_K="${2:-}"
            shift
            ;;
        --start-server|--skip-deps)
            # Compatibility no-ops preserve older command lines without changing
            # behavior; this script always starts the server after setup.
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

require_command() {
    # Fail before invoking setup steps that depend on missing host tools.
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Missing command: $cmd" >&2
        exit 1
    fi
}

prepend_user_bin() {
    # `uv` installed with `python3 -m pip --user` commonly lands here.
    local user_bin="$HOME/.local/bin"
    if [[ -d "$user_bin" && ":$PATH:" != *":$user_bin:"* ]]; then
        export PATH="$user_bin:$PATH"
    fi
}

ensure_uv() {
    # Hugging Face download can use `uvx` when hf/huggingface-cli are absent.
    prepend_user_bin

    if command -v uv >/dev/null 2>&1; then
        return
    fi

    echo "uv not found. Installing uv with python3 -m pip --user..."
    require_command python3
    python3 -m pip install --user uv
    prepend_user_bin

    if ! command -v uv >/dev/null 2>&1; then
        echo "uv installation finished, but uv is still not on PATH." >&2
        echo "Add this to PATH and rerun: $HOME/.local/bin" >&2
        exit 1
    fi
}

configure_model_defaults() {
    # Alias-specific defaults are filled only when the caller has not already
    # supplied HF_REPO/GGUF_NAME/MODEL_DIR through the environment.
    case "$MODEL_ALIAS" in
        llama31)
            HF_REPO="${HF_REPO:-bartowski/Meta-Llama-3.1-8B-Instruct-GGUF}"
            GGUF_NAME="${GGUF_NAME:-Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}"
            MODEL_DIR="${MODEL_DIR:-$MODEL_BASE_DIR/llama31}"
            ;;
        qwen3)
            HF_REPO="${HF_REPO:-Qwen/Qwen3-8B-GGUF}"
            GGUF_NAME="${GGUF_NAME:-Qwen3-8B-Q4_K_M.gguf}"
            MODEL_DIR="${MODEL_DIR:-$MODEL_BASE_DIR/qwen3}"
            ;;
        *)
            echo "Invalid --model value: $MODEL_ALIAS" >&2
            echo "Choose one of: llama31, qwen3" >&2
            exit 2
            ;;
    esac

    MODEL_FILE="${MODEL_FILE:-$MODEL_DIR/$GGUF_NAME}"

    if [[ ! -f "$MODEL_FILE" && -f "$EAGLE_MODEL_DIR/$GGUF_NAME" ]]; then
        # Reuse an existing model from the older EAGLE path without copying it
        # into this repo's ignored `models/` directory.
        MODEL_FILE="$EAGLE_MODEL_DIR/$GGUF_NAME"
    fi
}

download_model() {
    # Download only when requested; normal server startup never fetches models.
    ensure_uv
    mkdir -p "$MODEL_DIR"

    if [[ -f "$MODEL_FILE" ]]; then
        # Existing files are treated as authoritative local model assets.
        echo "Model already exists: $MODEL_FILE"
        return
    fi

    if [[ -z "${HF_TOKEN:-}" && -f "$HF_TOKEN_FILE" ]]; then
        # Token loading is local and optional; no secret is written to repo files.
        export HF_TOKEN
        HF_TOKEN="$(tr -d '[:space:]' < "$HF_TOKEN_FILE")"
    fi

    echo "Downloading $GGUF_NAME from $HF_REPO..."
    if command -v hf >/dev/null 2>&1; then
        # Prefer the modern `hf` command when available.
        hf download "$HF_REPO" --include "$GGUF_NAME" --local-dir "$MODEL_DIR"
    elif command -v huggingface-cli >/dev/null 2>&1; then
        # Fall back to the older CLI name for existing environments.
        huggingface-cli download "$HF_REPO" --include "$GGUF_NAME" --local-dir "$MODEL_DIR"
    else
        # Last resort avoids adding a permanent Python dependency to the repo.
        uvx --from huggingface_hub hf download "$HF_REPO" --include "$GGUF_NAME" --local-dir "$MODEL_DIR"
    fi
}

find_llama_server() {
    # Resolve a server binary without mutating the filesystem.
    local candidate

    if [[ -n "$LLAMA_SERVER_BIN" ]]; then
        # An explicit binary path wins over PATH and repo-local candidates.
        if [[ -x "$LLAMA_SERVER_BIN" ]]; then
            printf '%s\n' "$LLAMA_SERVER_BIN"
            return 0
        fi
        echo "LLAMA_SERVER_BIN is not executable: $LLAMA_SERVER_BIN" >&2
        return 1
    fi

    if command -v llama-server >/dev/null 2>&1; then
        # PATH lookup supports system-level installs.
        command -v llama-server
        return 0
    fi

    for candidate in \
        "$EAGLE_MODEL_DIR/llama-b9174/llama-server" \
        "$EAGLE_MODEL_DIR/llama.cpp/build/bin/llama-server" \
        "$EAGLE_MODEL_DIR/llama.cpp/llama.cpp/build/bin/llama-server" \
        "$LLAMA_CPP_DIR/build/bin/llama-server" \
        "$LLAMA_CPP_DIR/build/bin/server" \
        "$LLAMA_CPP_DIR/server" \
        "$LLAMA_CPP_DIR/llama-server"
    do
        if [[ -x "$candidate" ]]; then
            # Search both historical EAGLE locations and this repo's ignored
            # vendor build output.
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

install_llama_cpp() {
    # This function manages third-party source/build output under LLAMA_CPP_DIR.
    require_command git
    require_command cmake

    mkdir -p "$(dirname "$LLAMA_CPP_DIR")"

    if [[ -d "$LLAMA_CPP_DIR/.git" ]]; then
        # Existing clone is updated in place to keep install idempotent.
        echo "Updating llama.cpp in $LLAMA_CPP_DIR..."
        git -C "$LLAMA_CPP_DIR" pull --ff-only
    elif [[ -e "$LLAMA_CPP_DIR" ]]; then
        # Refuse to overwrite an unknown path because vendor output may be local
        # user state outside this repository's source control.
        echo "Path exists but is not a git checkout: $LLAMA_CPP_DIR" >&2
        echo "Move it away or set LLAMA_CPP_DIR=/path/to/llama.cpp." >&2
        exit 1
    else
        # Clone only on explicit install; normal server startup remains offline.
        echo "Cloning llama.cpp -> $LLAMA_CPP_DIR..."
        git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_DIR"
    fi

    echo "Building llama-server..."
    cmake -S "$LLAMA_CPP_DIR" -B "$LLAMA_CPP_DIR/build" -DGGML_CUDA=ON
    cmake --build "$LLAMA_CPP_DIR/build" --config Release --target llama-server -j "$(nproc)"
}

start_server() {
    # Resolve inputs, then replace the shell with llama-server.
    local llama_server

    if ! llama_server="$(find_llama_server)"; then
        cat >&2 <<EOF
Missing command: llama-server

Install/build llama.cpp first:
  ./start_llama_server.sh --install-llama-cpp --model $MODEL_ALIAS

Or point to an existing binary:
  LLAMA_SERVER_BIN=/path/to/llama-server ./start_llama_server.sh --model $MODEL_ALIAS

This script also checks:
  $EAGLE_MODEL_DIR/llama-b9174/llama-server
EOF
        exit 1
    fi

    if [[ ! -f "$MODEL_FILE" ]]; then
        # Missing model is a user/setup issue, not an experiment config fallback.
        echo "Model file not found: $MODEL_FILE" >&2
        echo "Run with --download-model first, or set MODEL_FILE=/path/to/model.gguf." >&2
        exit 1
    fi

    echo "Starting llama.cpp server at http://$HOST:$PORT/v1"
    echo "Model alias: $MODEL_ALIAS"
    echo "Model file: $MODEL_FILE"
    echo "Using llama-server: $llama_server"
    echo "Sampling: temperature=$TEMPERATURE top_p=$TOP_P top_k=$TOP_K"
    # `exec` makes llama-server the foreground process for clean signal handling.
    exec "$llama_server" \
        -m "$MODEL_FILE" \
        --host "$HOST" \
        --port "$PORT" \
        --ctx-size "$CTX_SIZE" \
        --n-gpu-layers "$N_GPU_LAYERS" \
        --temp "$TEMPERATURE" \
        --top-p "$TOP_P" \
        --top-k "$TOP_K"
}

configure_model_defaults

if [[ "$DOWNLOAD_MODEL" -eq 1 ]]; then
    # Optional generated model setup happens after alias defaults are known.
    download_model
fi

if [[ "$INSTALL_LLAMA_CPP" -eq 1 ]]; then
    # Optional external dependency setup happens before binary resolution.
    install_llama_cpp
fi

start_server
