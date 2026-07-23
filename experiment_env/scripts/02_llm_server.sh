#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

refresh_or_use_registry() {
    if registry_exists; then
        if confirm "Refresh model inventory before choosing a model?" "n"; then
            "$SCRIPT_DIR/01_discover_models.sh"
        fi
    else
        echo "No model registry exists yet. Running quick discovery first."
        bash "$SCRIPT_DIR/01_discover_models.sh"
    fi
}

main() {
    ensure_env_dirs
    print_header "EAGLE LLM Server - Model Host"
    echo "This workflow starts one llama.cpp server for one or more EAGLE roles."
    echo "Warning: binding to 0.0.0.0 exposes the server on your local network."
    echo "Do not expose this llama.cpp server directly to the public internet."
    echo "Firewall rules are not changed automatically."
    echo ""

    refresh_or_use_registry
    if ! registry_exists; then
        echo "Model registry is still missing. Return after running discovery."
        return 1
    fi

    local model_id display alias roles roles_csv advertised_ip port base_url hostname server_id
    model_id="$(select_model_from_registry)"
    display="$(model_field "$model_id" display_name)"
    alias="$model_id"
    echo ""
    roles="$(ask_roles)"
    roles_csv="${roles// /,}"
    advertised_ip="$(select_lan_ipv4)"
    port="$(prompt_available_port "Port for llama.cpp" "$(find_available_port 8080)")"
    hostname="$(hostname)"
    base_url="http://$advertised_ip:$port/v1"
    server_id="$(server_id_for "$hostname" "$port" "$model_id" "$roles_csv")"

    print_header "Final Server Configuration"
    echo "Server ID:       $server_id"
    echo "Hostname:        $hostname"
    echo "Bind address:    0.0.0.0"
    echo "Advertised URL:  $base_url"
    echo "Model:           $display"
    echo "Model ID:        $model_id"
    echo "Roles:           $roles"
    echo "Topology file:   $TOPOLOGY_PATH"
    echo ""
    if ! confirm "Start this server and update topology?" "y"; then
        echo "Canceled."
        return 0
    fi

    update_topology_server "$server_id" "$hostname" "$advertised_ip" "$port" "$base_url" "$model_id" "$display" "$roles_csv"
    echo "Updated $TOPOLOGY_PATH"
    echo "LAN endpoint: $base_url"
    echo "Use your normal manual workflow to commit/push this portable topology update if this is the model host."
    echo ""
    launch_llama_server_foreground "$model_id" "0.0.0.0" "$port" "$alias"
}

main
