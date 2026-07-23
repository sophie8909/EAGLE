#!/usr/bin/env bash

# Machine-local watchdog for a hard-coded network interface.
# This file is tracked but marked uncertain in docs/REPO_STRUCTURE.md. It is not
# referenced by active experiment, EAGLE, GUI, plugin, or analysis workflows.
INTERFACE="${INTERFACE:-enp132s0}"
CHECK_IP="${CHECK_IP:-8.8.8.8}"
CHECK_INTERVAL_SECONDS="${CHECK_INTERVAL_SECONDS:-60}"
RESTART_DELAY_SECONDS="${RESTART_DELAY_SECONDS:-10}"
REQUIRED_FAILURES="${REQUIRED_FAILURES:-3}"

failure_count=0

restart_network() {
    echo "$(date -Is) network trouble detected. restarting network interface $INTERFACE"

    # This path mutates host network state and requires sudo, so it should
    # not be run as part of repository validation or experiments.
    sudo ip link set "$INTERFACE" down
    sleep 5
    sudo ip link set "$INTERFACE" up

    sudo systemctl restart NetworkManager
    sleep "$RESTART_DELAY_SECONDS"
}

while true; do
    if ip a show "$INTERFACE" | grep -q "NO-CARRIER"; then
        failure_count=0
        restart_network
    elif ping -c 1 -W 5 "$CHECK_IP" > /dev/null 2>&1; then
        failure_count=0
    else
        failure_count=$((failure_count + 1))
        echo "$(date -Is) connectivity check failed for $CHECK_IP ($failure_count/$REQUIRED_FAILURES)"

        if [ "$failure_count" -ge "$REQUIRED_FAILURES" ]; then
            failure_count=0
            restart_network
        fi
    fi
    sleep "$CHECK_INTERVAL_SECONDS"
done
