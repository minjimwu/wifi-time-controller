#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing WiFi Time Controller ==="

# Read config values
IFACE=$(python3 -c "import json; print(json.load(open('$DIR/config.json'))['hotspot_iface'])")

# 1. Kill any manually running instance
echo "[1/6] Stopping any running instance..."
sudo pkill -f "python3.*app.py" 2>/dev/null || true
sudo fuser -k 80/tcp 2>/dev/null || true

# 2. Set lid close to lock (not suspend) and disable auto-suspend
echo "[2/6] Configuring power settings..."
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=lock/' /etc/systemd/logind.conf
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=lock/' /etc/systemd/logind.conf

# Disable GNOME auto-suspend (overrides logind for desktop sessions)
SUDO_USER_NAME="${SUDO_USER:-$USER}"
DBUS="unix:path=/run/user/$(id -u "$SUDO_USER_NAME")/bus"
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power lid-close-ac-action 'nothing' 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power lid-close-battery-action 'nothing' 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null || true
sudo -u "$SUDO_USER_NAME" DBUS_SESSION_BUS_ADDRESS="$DBUS" \
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || true

# 3. Install systemd units (replace placeholders with actual paths/values)
echo "[3/6] Installing systemd units..."
for unit in wifi-timer.service wifi-schedule.service wifi-sleep.service; do
    sed -e "s|INSTALL_DIR|$DIR|g" -e "s|HOTSPOT_IFACE|$IFACE|g" "$DIR/$unit" \
        | sudo tee /etc/systemd/system/$unit > /dev/null
done
sudo cp "$DIR/wifi-sleep.timer" /etc/systemd/system/
sudo cp "$DIR/wifi-wowlan.service" /etc/systemd/system/

sudo systemctl daemon-reload

# 4. Enable and start the web app service
echo "[4/6] Enabling wifi-timer service..."
sudo systemctl enable wifi-timer.service
sudo systemctl start wifi-timer.service

# 5. Enable the sleep timer (suspends at 22:00)
echo "[5/6] Enabling sleep schedule..."
sudo systemctl enable wifi-sleep.timer
sudo systemctl start wifi-sleep.timer

# 6. Enable schedule check on boot (suspends if outside hours)
echo "[6/7] Enabling boot guard..."
sudo systemctl enable wifi-schedule.service

# 7. Enable Wake-on-WLAN
echo "[7/7] Enabling Wake-on-WLAN..."
sudo systemctl enable wifi-wowlan.service
sudo systemctl start wifi-wowlan.service

# NOTE: Do NOT restart systemd-logind here — it kills the active session.
# The lid switch setting takes effect on next reboot.

HOTSPOT_IP=$(python3 -c "import json; c=json.load(open('$DIR/config.json')); print(c.get('hotspot_ip','192.168.44.1'))" 2>/dev/null || echo "<hotspot-ip>")

echo ""
echo "==========================================="
echo "  WiFi Time Controller installed!"
echo "==========================================="
echo ""
echo "  Services:"
echo "    wifi-timer.service    — web app (auto-start on boot)"
echo "    wifi-sleep.timer      — suspend at 22:00 daily"
echo "    wifi-schedule.service — boot guard (sleep if outside hours)"
echo "    wifi-wowlan.service   — enable Wake-on-WLAN at boot"
echo ""
echo "  Lid close: lock screen (takes effect after reboot)"
echo ""
echo "  Web UI: http://$HOTSPOT_IP"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status wifi-timer"
echo "    sudo systemctl status wifi-sleep.timer"
echo "    sudo python3 $DIR/schedule.py next"
echo "    sudo bash $DIR/uninstall.sh"
echo ""
