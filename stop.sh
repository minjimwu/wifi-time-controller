#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
sudo pkill -f "python3 app.py" 2>/dev/null || true
# Clean up iptables rules
IFACE=$(python3 -c "import json; print(json.load(open('$DIR/config.json'))['hotspot_iface'])" 2>/dev/null)
if [ -n "$IFACE" ]; then
    sudo iptables -D FORWARD -i "$IFACE" -j DROP 2>/dev/null
fi
echo "WiFi Timer stopped and iptables cleaned up"
