#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Uninstalling WiFi Time Controller ==="

# Read config
IFACE=$(python3 -c "import json; print(json.load(open('$DIR/config.json'))['hotspot_iface'])" 2>/dev/null || echo "")
CONN=$(python3 -c "import json; print(json.load(open('$DIR/config.json'))['connection_name'])" 2>/dev/null || echo "")

# 1. Stop and disable services
echo "[1/4] Stopping services..."
sudo systemctl stop wifi-timer.service 2>/dev/null || true
sudo systemctl stop wifi-sleep.timer 2>/dev/null || true
sudo systemctl disable wifi-timer.service 2>/dev/null || true
sudo systemctl disable wifi-sleep.timer 2>/dev/null || true
sudo systemctl disable wifi-schedule.service 2>/dev/null || true

# 2. Remove systemd unit files
echo "[2/4] Removing systemd units..."
sudo rm -f /etc/systemd/system/wifi-timer.service
sudo rm -f /etc/systemd/system/wifi-schedule.service
sudo rm -f /etc/systemd/system/wifi-sleep.service
sudo rm -f /etc/systemd/system/wifi-sleep.timer
sudo systemctl daemon-reload

# 3. Clean up iptables
echo "[3/4] Cleaning up iptables..."
if [ -n "$IFACE" ]; then
    while sudo iptables -D FORWARD -i "$IFACE" -j DROP 2>/dev/null; do :; done
fi

# 4. Restore power settings to defaults
echo "[4/4] Restoring power settings..."
sudo sed -i 's/^HandleLidSwitch=lock/#HandleLidSwitch=suspend/' /etc/systemd/logind.conf
sudo sed -i 's/^HandleLidSwitchExternalPower=lock/#HandleLidSwitchExternalPower=suspend/' /etc/systemd/logind.conf
# NOTE: Do NOT restart systemd-logind — it kills the active session.
# The logind lid switch setting takes effect on next reboot.

# Restore GNOME power defaults
SUDO_USER_NAME="${SUDO_USER:-$USER}"
DBUS="unix:path=/run/user/$(id -u "$SUDO_USER_NAME")/bus"
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power lid-close-ac-action 'suspend' 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power lid-close-battery-action 'suspend' 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 900 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || true

echo ""
echo "==========================================="
echo "  WiFi Time Controller uninstalled!"
echo "==========================================="
echo ""
if [ -n "$CONN" ]; then
    echo "  Note: The WiFi hotspot '$CONN' is still active."
    echo "  To remove it:  sudo nmcli connection delete $CONN"
    echo ""
fi
