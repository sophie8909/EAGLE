#!/usr/bin/env bash

# Machine-local watchdog for a hard-coded network interface.
# This file is tracked but marked uncertain in docs/REPO_STRUCTURE.md. It is not
# referenced by active experiment, EAGLE, GUI, plugin, or analysis workflows.
INTERFACE="enp132s0"
CHECK_IP="8.8.8.8"

while true; do
    # The ping currently acts only as a connectivity probe; restart behavior is
    # gated by the interface carrier state below.
    ping -c 1 "$CHECK_IP" > /dev/null 2>&1
    if ip a show "$INTERFACE" | grep "NO-CARRIER"; then
        echo "internet down. restarting network interface $INTERFACE"
        # This path mutates host network state and requires sudo, so it should
        # not be run as part of repository validation or experiments.
        sudo ip link set "$INTERFACE" down
        sleep 5
        sudo ip link set "$INTERFACE" up
        
        sudo systemctl restart NetworkManager
        sleep 10
    fi
    sleep 60
done
