#!/usr/bin/env bash

# Shared helpers for EAGLE's local/remote llama.cpp environment workflows.

set -euo pipefail

SCRIPT_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_ENV_DIR="$(cd -- "$SCRIPT_LIB_DIR/../.." && pwd)"
REPO_ROOT="$(cd -- "$EXPERIMENT_ENV_DIR/.." && pwd)"
MODEL_ROOT="$EXPERIMENT_ENV_DIR/model"
CONFIG_ROOT="$EXPERIMENT_ENV_DIR/config"
RUNTIME_ROOT="$EXPERIMENT_ENV_DIR/runtime"
LOG_ROOT="$RUNTIME_ROOT/logs"
PID_ROOT="$RUNTIME_ROOT/pids"
REGISTRY_PATH="$MODEL_ROOT/model_registry.local.json"
TOPOLOGY_PATH="$CONFIG_ROOT/llm_topology.json"
TOPOLOGY_EXAMPLE_PATH="$CONFIG_ROOT/llm_topology.example.json"

DEFAULT_CTX_SIZE="${CTX_SIZE:-16384}"
DEFAULT_N_GPU_LAYERS="${N_GPU_LAYERS:-99}"
DEFAULT_TEMPERATURE="${TEMPERATURE:-0.6}"
DEFAULT_TOP_P="${TOP_P:-0.95}"
DEFAULT_TOP_K="${TOP_K:-20}"
DEFAULT_BATCH_SIZE="${BATCH_SIZE:-2048}"
DEFAULT_PARALLEL="${PARALLEL_SLOTS:-1}"
DEFAULT_FLASH_ATTN="${FLASH_ATTN:-auto}"

ROLES=(reflector rewriter generator)

ensure_env_dirs() {
    mkdir -p "$MODEL_ROOT" "$CONFIG_ROOT" "$LOG_ROOT" "$PID_ROOT"
}

pause_for_enter() {
    local prompt="${1:-Press Enter to continue.}"
    read -r -p "$prompt " _
}

print_header() {
    printf '\n%s\n' "$1"
    printf '%*s\n' "${#1}" '' | tr ' ' '='
}

prompt_default() {
    local prompt="$1"
    local default="$2"
    local value
    read -r -p "$prompt [$default]: " value
    printf '%s\n' "${value:-$default}"
}

confirm() {
    local prompt="$1"
    local default="${2:-y}"
    local suffix="[Y/n]"
    [[ "$default" == "n" ]] && suffix="[y/N]"
    while true; do
        local answer
        read -r -p "$prompt $suffix " answer
        answer="${answer:-$default}"
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no) return 1 ;;
            *) echo "Please answer yes or no." ;;
        esac
    done
}

require_python3() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 is required for JSON registry/topology handling." >&2
        return 1
    fi
}

detect_llama_server() {
    local candidate
    if [[ -n "${LLAMA_SERVER_BIN:-}" && -x "${LLAMA_SERVER_BIN:-}" ]]; then
        printf '%s\n' "$LLAMA_SERVER_BIN"
        return 0
    fi
    if command -v llama-server >/dev/null 2>&1; then
        command -v llama-server
        return 0
    fi
    for candidate in \
        "$MODEL_ROOT/llama-b9174/llama-server" \
        "$MODEL_ROOT/llama.cpp/build/bin/llama-server" \
        "$MODEL_ROOT/llama.cpp/llama.cpp/build/bin/llama-server" \
        "$EXPERIMENT_ENV_DIR/vendor/llama.cpp/build/bin/llama-server" \
        "$HOME/llama.cpp/build/bin/llama-server" \
        "$HOME/llama.cpp/llama-server" \
        "/usr/local/bin/llama-server" \
        "/usr/bin/llama-server"
    do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

port_in_use() {
    local port="$1"
    [[ "$port" =~ ^[0-9]+$ && "$port" -ge 1 && "$port" -le 65535 ]] || return 0
    if command -v ss >/dev/null 2>&1; then
        local ss_output
        if ss_output="$(ss -ltn "( sport = :$port )" 2>/dev/null)"; then
            printf '%s\n' "$ss_output" | awk 'NR > 1 {found=1} END {exit found ? 0 : 1}'
            return $?
        fi
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
        return $?
    fi
    python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    sys.exit(0)
finally:
    sock.close()
sys.exit(1)
PY
}

describe_port_owner() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "( sport = :$port )" 2>/dev/null || echo "Port $port is already occupied."
    elif command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$port" -sTCP:LISTEN || true
    else
        echo "Port $port is already occupied."
    fi
}

is_port_number() {
    local value="$1"
    [[ "$value" =~ ^[0-9]+$ && "$value" -ge 1 && "$value" -le 65535 ]]
}

prompt_available_port() {
    local prompt="$1"
    local default="$2"
    while true; do
        local port
        port="$(prompt_default "$prompt" "$default")"
        if ! is_port_number "$port"; then
            echo "Enter a valid port from 1 to 65535." >&2
            continue
        fi
        if port_in_use "$port"; then
            echo "Port $port is already in use." >&2
            describe_port_owner "$port" >&2
            default="$(find_available_port "$((port + 1))")"
            continue
        fi
        printf '%s\n' "$port"
        return 0
    done
}

find_available_port() {
    local start="${1:-8080}"
    local port
    for ((port=start; port<start+100; port++)); do
        if ! port_in_use "$port"; then
            printf '%s\n' "$port"
            return 0
        fi
    done
    return 1
}

detect_lan_ipv4s() {
    local output=""
    if command -v ip >/dev/null 2>&1; then
        output="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' | sort -u || true)"
    fi
    if [[ -z "$output" ]]; then
        output="$(hostname -I 2>/dev/null | tr ' ' '\n' | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $0 !~ /^127\./' | sort -u || true)"
    fi
    if [[ -z "$output" ]]; then
        output="$(python3 - <<'PY' 2>/dev/null || true
import socket
values = set()
try:
    infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
except OSError:
    infos = []
for info in infos:
    value = info[4][0]
    if not value.startswith("127."):
        values.add(value)
for value in sorted(values):
    print(value)
PY
)"
    fi
    printf '%s\n' "$output" | awk 'NF' | sort -u
}

is_ipv4_address() {
    local value="$1"
    [[ "$value" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    local IFS=.
    local octets
    read -r -a octets <<< "$value"
    local octet
    for octet in "${octets[@]}"; do
        [[ "$octet" -ge 0 && "$octet" -le 255 ]] || return 1
    done
    return 0
}

select_lan_ipv4() {
    local addresses=()
    mapfile -t addresses < <(detect_lan_ipv4s)
    if [[ "${#addresses[@]}" -eq 0 ]]; then
        while true; do
            local manual
            manual="$(prompt_default "No LAN IPv4 was detected. Enter the address to advertise" "127.0.0.1")"
            if is_ipv4_address "$manual"; then
                printf '%s\n' "$manual"
                return 0
            fi
            echo "Enter a valid IPv4 address." >&2
        done
    fi
    echo "Detected LAN IPv4 addresses:" >&2
    local index
    for index in "${!addresses[@]}"; do
        printf '  %d. %s\n' "$((index + 1))" "${addresses[$index]}" >&2
    done
    while true; do
        local choice
        read -r -p "Advertise which address? [1]: " choice
        choice="${choice:-1}"
        if [[ "$choice" =~ ^[0-9]+$ && "$choice" -ge 1 && "$choice" -le "${#addresses[@]}" ]]; then
            printf '%s\n' "${addresses[$((choice - 1))]}"
            return 0
        fi
        if is_ipv4_address "$choice"; then
            printf '%s\n' "$choice"
            return 0
        fi
        echo "Choose a number from the list, or enter an IPv4 address." >&2
    done
}

parse_role_selection() {
    local raw="$1"
    python3 - "$raw" <<'PY'
import sys
roles = ["reflector", "rewriter", "generator"]
raw = sys.argv[1].strip().lower()
if raw == "all":
    print(" ".join(roles))
    sys.exit(0)
parts = [part for chunk in raw.replace(",", " ").split() for part in [chunk.strip()] if part]
selected = []
for part in parts:
    if part.isdigit() and 1 <= int(part) <= len(roles):
        role = roles[int(part)-1]
    elif part in roles:
        role = part
    else:
        sys.exit(2)
    if role not in selected:
        selected.append(role)
if not selected:
    sys.exit(2)
print(" ".join(selected))
PY
}

ask_roles() {
    echo "Roles:" >&2
    echo "  1. reflector" >&2
    echo "  2. rewriter" >&2
    echo "  3. generator" >&2
    while true; do
        local raw selected
        read -r -p "Select role(s) (1, 1,3, 1 2 3, or all): " raw
        if selected="$(parse_role_selection "$raw" 2>/dev/null)"; then
            printf '%s\n' "$selected"
            return 0
        fi
        echo "Invalid role selection." >&2
    done
}

registry_exists() {
    [[ -s "$REGISTRY_PATH" ]]
}

show_registry() {
    require_python3
    if ! registry_exists; then
        echo "No model registry found at $REGISTRY_PATH"
        return 1
    fi
    python3 - "$REGISTRY_PATH" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text())
models = data.get("models", [])
if not models:
    print("No usable language GGUF models are registered.")
    sys.exit(0)
for i, model in enumerate(models, 1):
    size = model.get("size_gb")
    size_label = f"{size:.1f} GB" if isinstance(size, (int, float)) else "unknown size"
    quant = model.get("quantization") or "unknown quant"
    usable = "usable" if model.get("llama_server_compatible") else "check server"
    print(f"{i}. {model.get('display_name', model.get('stable_model_id'))} - {quant} - {size_label} - {usable}")
PY
}

select_model_from_registry() {
    require_python3
    if ! registry_exists; then
        echo "No model registry found. Run discovery first."
        return 1
    fi
    show_registry >&2
    while true; do
        local choice model_id
        read -r -p "Choose a model number: " choice
        if model_id="$(python3 - "$REGISTRY_PATH" "$choice" <<'PY' 2>/dev/null
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
models = data.get("models", [])
choice = sys.argv[2]
if not choice.isdigit() or not (1 <= int(choice) <= len(models)):
    sys.exit(2)
print(models[int(choice)-1]["stable_model_id"])
PY
)"; then
            printf '%s\n' "$model_id"
            return 0
        fi
        echo "Invalid model selection." >&2
    done
}

model_field() {
    local model_id="$1"
    local field="$2"
    python3 - "$REGISTRY_PATH" "$model_id" "$field" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
model_id, field = sys.argv[2], sys.argv[3]
for model in data.get("models", []):
    if model.get("stable_model_id") == model_id:
        value = model.get(field)
        if isinstance(value, list):
            print("\n".join(str(item) for item in value))
        elif value is not None:
            print(value)
        sys.exit(0)
sys.exit(2)
PY
}

ensure_topology() {
    ensure_env_dirs
    if [[ ! -f "$TOPOLOGY_PATH" ]]; then
        cat > "$TOPOLOGY_PATH" <<'JSON'
{
  "version": 1,
  "servers": {},
  "roles": {}
}
JSON
    fi
}

show_topology() {
    require_python3
    ensure_topology
    python3 - "$TOPOLOGY_PATH" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
servers = data.get("servers", {})
roles = data.get("roles", {})
print("Role assignments:")
for role in ("reflector", "rewriter", "generator"):
    entry = roles.get(role) or {}
    server_id = entry.get("server_id")
    server = servers.get(server_id or "", {})
    if not server:
        print(f"  {role}: unassigned")
        continue
    print(f"  {role}: {server_id} - {server.get('model_display_name') or server.get('model_id')} - {server.get('base_url')}")
print("")
print("Known servers:")
if not servers:
    print("  none")
for server_id, server in sorted(servers.items()):
    roles_label = ", ".join(server.get("roles") or [])
    print(f"  {server_id}: {server.get('hostname')} {server.get('base_url')} {server.get('model_display_name') or server.get('model_id')} roles=[{roles_label}]")
PY
}

server_id_for() {
    local host="$1"
    local port="$2"
    local model_id="$3"
    local roles_slug="$4"
    python3 - "$host" "$port" "$model_id" "$roles_slug" <<'PY'
import hashlib, re, sys
host, port, model, roles = sys.argv[1:]
base = "-".join(part for part in [host, port, model, roles] if part)
slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:52]
digest = hashlib.sha1(base.encode()).hexdigest()[:8]
print(f"{slug}-{digest}" if slug else f"server-{digest}")
PY
}

update_topology_server() {
    local server_id="$1"
    local hostname="$2"
    local advertised_ip="$3"
    local port="$4"
    local base_url="$5"
    local model_id="$6"
    local model_display_name="$7"
    local roles_csv="$8"
    require_python3
    ensure_topology
    python3 - "$TOPOLOGY_PATH" "$server_id" "$hostname" "$advertised_ip" "$port" "$base_url" "$model_id" "$model_display_name" "$roles_csv" <<'PY'
import json, sys
from datetime import datetime, timezone
path, server_id, hostname, ip, port, base_url, model_id, display, roles_csv = sys.argv[1:]
roles = [item for item in roles_csv.split(",") if item]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data.setdefault("version", 1)
servers = data.setdefault("servers", {})
role_map = data.setdefault("roles", {})
servers[server_id] = {
    "hostname": hostname,
    "advertised_ip": ip,
    "port": int(port),
    "base_url": base_url.rstrip("/") if base_url.rstrip("/").endswith("/v1") else base_url.rstrip("/") + "/v1",
    "model_id": model_id,
    "model_display_name": display,
    "roles": roles,
    "protocol": "openai-compatible",
    "health_path": "/health",
}
for role in roles:
    role_map[role] = {"server_id": server_id}
data["updated_at"] = datetime.now(timezone.utc).isoformat()
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
import os
os.replace(tmp, path)
PY
}

validate_topology_endpoints() {
    require_python3
    ensure_topology
    python3 - "$TOPOLOGY_PATH" <<'PY'
import json, sys, urllib.error, urllib.request
from urllib.parse import urlparse
path = sys.argv[1]
data = json.loads(open(path, encoding="utf-8").read())
servers = data.get("servers", {})
roles = data.get("roles", {})
for role in ("reflector", "rewriter", "generator"):
    entry = roles.get(role) or {}
    server_id = entry.get("server_id")
    server = servers.get(server_id or "")
    if not server:
        print(f"{role}: missing assignment")
        continue
    base_url = str(server.get("base_url", "")).rstrip("/")
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    checked = []
    ok = False
    for suffix in ("/health", "/v1/models"):
        url = root + suffix if suffix.startswith("/") else root + "/" + suffix
        checked.append(url)
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 300:
                    ok = True
                    break
        except Exception:
            pass
    status = "ok" if ok else "unreachable"
    print(f"{role}: {status} - {server_id} - {base_url} - tried {', '.join(checked)}")
PY
}

launch_llama_server_foreground() {
    local model_id="$1"
    local bind_host="$2"
    local port="$3"
    local alias="$4"
    local model_path
    local mmproj_path
    local llama_server
    model_path="$(model_field "$model_id" organized_model_path)"
    mmproj_path="$(model_field "$model_id" organized_mmproj_path || true)"
    if [[ -n "$model_path" && "$model_path" != /* ]]; then
        model_path="$EXPERIMENT_ENV_DIR/$model_path"
    fi
    if [[ -n "$mmproj_path" && "$mmproj_path" != /* ]]; then
        mmproj_path="$EXPERIMENT_ENV_DIR/$mmproj_path"
    fi
    if [[ -z "$model_path" || ! -e "$model_path" ]]; then
        echo "Organized model link is missing for $model_id. Refresh model discovery." >&2
        return 1
    fi
    if port_in_use "$port"; then
        echo "Port $port is already in use; refusing to start a duplicate server."
        describe_port_owner "$port"
        return 1
    fi
    if ! llama_server="$(detect_llama_server)"; then
        echo "Could not find an executable llama-server. Set LLAMA_SERVER_BIN or install/build llama.cpp." >&2
        return 1
    fi
    local pid_file="$PID_ROOT/llama_${port}.pid"
    if [[ -f "$pid_file" ]]; then
        local old_pid
        old_pid="$(cat "$pid_file" 2>/dev/null || true)"
        if [[ -n "$old_pid" && -d "/proc/$old_pid" ]]; then
            echo "PID record exists for a running process: $pid_file -> $old_pid"
            ps -fp "$old_pid" || true
            return 1
        fi
    fi
    local log_file="$LOG_ROOT/llama_${model_id}_${port}_$(date +%Y%m%d_%H%M%S).log"
    echo "$$" > "$pid_file"
    trap 'rm -f "$pid_file"' EXIT INT TERM
    echo "Starting llama.cpp server:"
    echo "  binary: $llama_server"
    echo "  model:  $model_path"
    echo "  bind:   $bind_host:$port"
    echo "  alias:  $alias"
    echo "  log:    $log_file"
    local command=(
        "$llama_server"
        -m "$model_path"
        --alias "$alias"
        --host "$bind_host"
        --port "$port"
        --ctx-size "$DEFAULT_CTX_SIZE"
        --n-gpu-layers "$DEFAULT_N_GPU_LAYERS"
        --temp "$DEFAULT_TEMPERATURE"
        --top-p "$DEFAULT_TOP_P"
        --top-k "$DEFAULT_TOP_K"
        --batch-size "$DEFAULT_BATCH_SIZE"
        --parallel "$DEFAULT_PARALLEL"
        --flash-attn "$DEFAULT_FLASH_ATTN"
        --log-file "$log_file"
    )
    if [[ -n "$mmproj_path" && -e "$mmproj_path" ]]; then
        command+=(--mmproj "$mmproj_path")
    fi
    exec "${command[@]}"
}
