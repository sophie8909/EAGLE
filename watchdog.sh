#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/runtime/pids/watchdog.pid"
INTERVAL_SECONDS="${EAGLE_WATCHDOG_INTERVAL_SECONDS:-300}"
INTERFACE="${EAGLE_WATCHDOG_INTERFACE:-}"
ONCE=false

usage() {
    cat <<'EOF'
Usage: ./watchdog.sh [--once] [--interval SECONDS]

Monitor and recover the local network interface. This watchdog does not manage
llama-server; the experiment launcher owns that lifecycle.

Environment:
  EAGLE_WATCHDOG_INTERVAL_SECONDS  Poll interval when --interval is omitted.
  EAGLE_WATCHDOG_INTERFACE         Interface to monitor; default is the
                                    interface used by the default route, with a
                                    non-loopback fallback.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --once)
            ONCE=true
            shift
            ;;
        --interval)
            [[ $# -ge 2 ]] || { echo "ERROR: --interval requires seconds." >&2; exit 2; }
            INTERVAL_SECONDS="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$INTERVAL_SECONDS" =~ ^[1-9][0-9]*(\.[0-9]+)?$ ]]; then
    echo "ERROR: watchdog interval must be a positive number of seconds." >&2
    exit 2
fi

if ! command -v ip >/dev/null 2>&1; then
    echo "ERROR: watchdog requires the ip command for network-interface checks." >&2
    exit 1
fi

acquire_pid_file() {
    mkdir -p "$(dirname -- "$PID_FILE")"
    if [[ -f "$PID_FILE" ]]; then
        local existing_pid
        existing_pid="$(<"$PID_FILE")"
        if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
            echo "ERROR: watchdog is already running with PID $existing_pid." >&2
            exit 1
        fi
    fi
    local temporary="$PID_FILE.tmp.$$"
    printf '%s\n' "$$" > "$temporary"
    mv -f -- "$temporary" "$PID_FILE"
}

release_pid_file() {
    if [[ -f "$PID_FILE" ]] && [[ "$(<"$PID_FILE")" == "$$" ]]; then
        rm -f -- "$PID_FILE"
    fi
}

detect_interface() {
    if [[ -n "$INTERFACE" ]]; then
        return 0
    fi
    INTERFACE="$(ip -o route show default 2>/dev/null | awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
    if [[ -z "$INTERFACE" ]]; then
        INTERFACE="$(ip -o link show 2>/dev/null | awk -F': ' '$2 !~ /^lo([:@]|$)/ { sub(/@.*/, "", $2); print $2; exit }')"
    fi
}

check_connection() {
    detect_interface
    if [[ -z "$INTERFACE" ]]; then
        echo "watchdog: no default-route network interface detected." >&2
        return 1
    fi
    if ! ip link show dev "$INTERFACE" >/dev/null 2>&1; then
        echo "watchdog: network interface does not exist: $INTERFACE" >&2
        return 1
    fi
    local link_state
    link_state="$(ip -o link show dev "$INTERFACE")"
    if [[ "$link_state" != *" state UP "* ]]; then
        echo "watchdog: network interface is not UP: $INTERFACE" >&2
        return 1
    fi
    local carrier_path="/sys/class/net/$INTERFACE/carrier"
    if [[ -r "$carrier_path" ]] && [[ "$(<"$carrier_path")" != "1" ]]; then
        echo "watchdog: network interface has no carrier: $INTERFACE" >&2
        return 1
    fi
    return 0
}

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
        return
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        echo "watchdog: sudo is required to restart network interface $INTERFACE." >&2
        return 1
    fi
    sudo -n "$@"
}

restart_interface() {
    detect_interface
    if [[ -z "$INTERFACE" ]]; then
        echo "watchdog: cannot restart network interface; none detected." >&2
        return 1
    fi
    echo "watchdog: restarting network interface: $INTERFACE" >&2
    if ! run_privileged ip link set dev "$INTERFACE" down; then
        echo "watchdog: failed to bring interface down: $INTERFACE" >&2
        return 1
    fi
    if ! run_privileged ip link set dev "$INTERFACE" up; then
        echo "watchdog: failed to bring interface up: $INTERFACE" >&2
        return 1
    fi
    return 0
}

check_and_recover() {
    if check_connection; then
        return 0
    fi
    restart_interface || return 1
    sleep 1
    check_connection
}

acquire_pid_file
trap release_pid_file EXIT
trap 'exit 130' INT TERM

if [[ "$ONCE" == true ]]; then
    check_and_recover
    exit 0
fi

echo "watchdog: monitoring and recovering local network interface every ${INTERVAL_SECONDS}s (PID $$)."
while true; do
    check_and_recover || echo "watchdog: interface recovery failed; will retry." >&2
    sleep "$INTERVAL_SECONDS"
done
