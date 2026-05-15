#!/usr/bin/env bash

set -euo pipefail

INTERFACE="${NETWORK_INTERFACE:-enp132s0}"
CHECK_IP="${NETWORK_CHECK_IP:-8.8.8.8}"
SLEEP_SECONDS="${NETWORK_WATCHDOG_INTERVAL:-60}"

while true; do
    if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
        echo "ERROR: network interface not found: $INTERFACE"
        exit 1
    fi

    if ip link show "$INTERFACE" | grep -q "NO-CARRIER" || ! ping -c 1 -W 3 "$CHECK_IP" >/dev/null 2>&1; then
        echo "network check failed. restarting interface $INTERFACE"
        sudo ip link set "$INTERFACE" down
        sleep 5
        sudo ip link set "$INTERFACE" up
        
        sudo systemctl restart NetworkManager
        sleep 10
    fi
    sleep "$SLEEP_SECONDS"
done
