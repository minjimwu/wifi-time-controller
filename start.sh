#!/bin/bash
cd "$(dirname "$0")"
sudo python3 app.py &
echo "WiFi Timer started (PID: $!)"
