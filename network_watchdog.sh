# !/bin/bash

INTERFACE="enp132s0"
CHECK_IP="8.8.8.8"

while true; do
    ping -c 1 $CHECK_IP > /dev/null 2>&1
    if ip a show $INTERFACE | grep "NO-CARRRIER"; then
        echo "internet down. restarting network interface $INTERFACE"
        sudo ip link set $INTERFACE down
        sleep 5
        sudo ip link set $INTERFACE up
        
        sudo systemctl restart NetworkManager
        sleep 10
    fi
    sleep 60
done