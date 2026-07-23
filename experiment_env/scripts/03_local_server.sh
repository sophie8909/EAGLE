#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

list_known_servers() {
    require_python3
    ensure_topology
    python3 - "$TOPOLOGY_PATH" <<'PY'
import json, sys, urllib.request
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
servers = list(sorted((data.get("servers") or {}).items()))
if not servers:
    print("No known servers in topology.")
    sys.exit(1)
for index, (server_id, server) in enumerate(servers, 1):
    base_url = str(server.get("base_url", "")).rstrip("/")
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    ok = False
    for suffix in ("/health", "/v1/models"):
        try:
            with urllib.request.urlopen(root + suffix, timeout=2) as response:
                ok = 200 <= response.status < 300
                if ok:
                    break
        except Exception:
            pass
    status = "healthy" if ok else "unreachable"
    roles = ", ".join(server.get("roles") or [])
    print(f"{index}. {server_id} - {server.get('hostname')} {server.get('advertised_ip')}:{server.get('port')} - {server.get('model_display_name') or server.get('model_id')} - roles=[{roles}] - {status}")
PY
}

select_server_id() {
    list_known_servers >&2 || return 1
    while true; do
        local choice server_id
        read -r -p "Choose a known server number: " choice
        if server_id="$(python3 - "$TOPOLOGY_PATH" "$choice" <<'PY' 2>/dev/null
import json, sys
servers = list(sorted((json.loads(open(sys.argv[1], encoding="utf-8").read()).get("servers") or {}).items()))
choice = sys.argv[2]
if not choice.isdigit() or not (1 <= int(choice) <= len(servers)):
    sys.exit(2)
print(servers[int(choice)-1][0])
PY
)"; then
            printf '%s\n' "$server_id"
            return 0
        fi
        echo "Invalid server selection." >&2
    done
}

assign_roles_to_existing_server() {
    local roles="$1"
    local server_id="$2"
    python3 - "$TOPOLOGY_PATH" "$server_id" "$roles" <<'PY'
import json, os, sys
from datetime import datetime, timezone
path, server_id, roles_raw = sys.argv[1:]
roles = roles_raw.split()
data = json.loads(open(path, encoding="utf-8").read())
servers = data.setdefault("servers", {})
if server_id not in servers:
    raise SystemExit(f"Unknown server: {server_id}")
server_roles = list(servers[server_id].get("roles") or [])
for role in roles:
    if role not in server_roles:
        server_roles.append(role)
    data.setdefault("roles", {})[role] = {"server_id": server_id}
servers[server_id]["roles"] = server_roles
data["updated_at"] = datetime.now(timezone.utc).isoformat()
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
os.replace(tmp, path)
PY
}

configure_manual_endpoint() {
    local roles="$1"
    local base_url model_name host port server_id hostname roles_csv advertised_ip
    base_url="$(prompt_default "OpenAI-compatible base URL" "http://192.168.1.20:8080/v1")"
    model_name="$(prompt_default "Model alias/name sent in requests" "local-model")"
    hostname="$(prompt_default "Server hostname label" "manual-lan-server")"
    advertised_ip="$(python3 - "$base_url" <<'PY'
from urllib.parse import urlparse
import sys
print(urlparse(sys.argv[1]).hostname or "manual")
PY
)"
    port="$(python3 - "$base_url" <<'PY'
from urllib.parse import urlparse
import sys
print(urlparse(sys.argv[1]).port or 8080)
PY
)"
    roles_csv="${roles// /,}"
    server_id="$(server_id_for "$hostname" "$port" "$model_name" "$roles_csv")"
    echo ""
    echo "Manual endpoint: $base_url"
    echo "Roles: $roles"
    if confirm "Save this role routing?" "y"; then
        update_topology_server "$server_id" "$hostname" "$advertised_ip" "$port" "$base_url" "$model_name" "$model_name" "$roles_csv"
        echo "Saved $TOPOLOGY_PATH"
    fi
}

configure_local_model_endpoint() {
    local roles="$1"
    if ! registry_exists; then
        echo "No local model registry found. Run discovery first."
        return 1
    fi
    local model_id display port base_url hostname server_id roles_csv
    model_id="$(select_model_from_registry)"
    display="$(model_field "$model_id" display_name)"
    port="$(prompt_available_port "Local llama.cpp port" "$(find_available_port 8080)")"
    hostname="$(hostname)"
    base_url="http://127.0.0.1:$port/v1"
    roles_csv="${roles// /,}"
    server_id="$(server_id_for "$hostname" "$port" "$model_id" "$roles_csv")"
    update_topology_server "$server_id" "$hostname" "127.0.0.1" "$port" "$base_url" "$model_id" "$display" "$roles_csv"
    echo "Saved local role routing: $base_url"
    if confirm "Start this local model server now?" "y"; then
        launch_llama_server_foreground "$model_id" "127.0.0.1" "$port" "$model_id"
    fi
}

configure_role_assignments() {
    local roles source server_id
    roles="$(ask_roles)"
    while true; do
        print_header "Role Source"
        echo "1. Known remote LLM server from llm_topology.json"
        echo "2. Local model from model_registry.local.json"
        echo "3. Manually entered LAN OpenAI-compatible endpoint"
        echo "4. Return"
        read -r -p "Choose a source [1-4]: " source
        case "${source:-}" in
            1)
                server_id="$(select_server_id)" || return 0
                assign_roles_to_existing_server "$roles" "$server_id"
                echo "Saved role assignment(s) for: $roles"
                return 0
                ;;
            2) configure_local_model_endpoint "$roles"; return 0 ;;
            3) configure_manual_endpoint "$roles"; return 0 ;;
            4) return 0 ;;
            *) echo "Invalid selection." ;;
        esac
    done
}

start_local_model_server() {
    if ! registry_exists; then
        echo "No local model registry found. Run discovery first."
        return 1
    fi
    local model_id port
    model_id="$(select_model_from_registry)"
    port="$(prompt_available_port "Local llama.cpp port" "$(find_available_port 8080)")"
    launch_llama_server_foreground "$model_id" "127.0.0.1" "$port" "$model_id"
}

main_menu() {
    ensure_env_dirs
    ensure_topology
    while true; do
        print_header "EAGLE Local Server - EA Host"
        echo "1. Show current role assignments"
        echo "2. Configure role assignments"
        echo "3. Validate all configured endpoints"
        echo "4. Start a local model server"
        echo "5. Refresh local model inventory"
        echo "6. Return"
        local choice
        read -r -p "Choose an option [1-6]: " choice
        case "${choice:-}" in
            1) show_topology; pause_for_enter ;;
            2) configure_role_assignments; pause_for_enter ;;
            3) validate_topology_endpoints; pause_for_enter ;;
            4) start_local_model_server ;;
            5) "$SCRIPT_DIR/01_discover_models.sh" ;;
            6) return 0 ;;
            *) echo "Invalid selection." ;;
        esac
    done
}

main_menu
