#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_ENV="$ROOT/run_env.sh"
PID_FILE="$ROOT/runtime/pids/llm-watchdog.pid"
INTERVAL_SECONDS="${EAGLE_WATCHDOG_INTERVAL_SECONDS:-10}"
ONCE=false

usage() {
    cat <<'EOF'
Usage: ./watchdog.sh [--once] [--interval SECONDS]

Monitor the EAGLE llama-server through run_env.sh. When the managed runtime is
stopped or unhealthy, start it through the canonical runtime entrypoint.

Environment:
  EAGLE_WATCHDOG_INTERVAL_SECONDS  Poll interval when --interval is omitted.
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

if [[ ! -x "$RUN_ENV" ]]; then
    echo "ERROR: canonical runtime entrypoint is not executable: $RUN_ENV" >&2
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

check_runtime() {
    if "$RUN_ENV" status; then
        return 0
    fi
    echo "watchdog: runtime is not healthy; starting it." >&2
    "$RUN_ENV" start
}

acquire_pid_file
trap release_pid_file EXIT
trap 'exit 130' INT TERM

if [[ "$ONCE" == true ]]; then
    check_runtime
    exit 0
fi

echo "watchdog: monitoring EAGLE runtime every ${INTERVAL_SECONDS}s (PID $$)."
while true; do
    check_runtime || echo "watchdog: runtime start failed; will retry." >&2
    sleep "$INTERVAL_SECONDS"
done
