#!/usr/bin/env python3
import json
import subprocess
import threading
import time
import os
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# --- Configuration (from config.json) ---
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_config_path) as _f:
    CONFIG = json.load(_f)

CONNECTION_NAME = CONFIG["connection_name"]
HOTSPOT_IFACE = CONFIG["hotspot_iface"]
USB_DEVICE = CONFIG["usb_device"]
DESKTOP_USER = CONFIG.get("desktop_user", "")
ONLINE_MINUTES = CONFIG.get("online_minutes", 40)
OFFLINE_MINUTES = CONFIG.get("offline_minutes", 15)
PORT = CONFIG.get("port", 80)
VOICE_ALERTS = CONFIG.get("voice_alerts", [10, 5, 1])  # minutes remaining

# --- State ---
state = {
    "phase": "idle",        # idle | online | offline
    "end_time": 0,          # unix timestamp when current phase ends
    "start_time": 0,        # unix timestamp when online phase started
    "online_mins": ONLINE_MINUTES,
    "offline_mins": OFFLINE_MINUTES,
}
state_lock = threading.Lock()


def speak(text: str):
    """Speak text via spd-say using the desktop user's audio session."""
    if not DESKTOP_USER:
        return
    def _speak():
        try:
            import pwd
            uid = str(pwd.getpwnam(DESKTOP_USER).pw_uid)
            subprocess.run(
                ["sudo", "-u", DESKTOP_USER,
                 "env", f"XDG_RUNTIME_DIR=/run/user/{uid}",
                 f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                 "spd-say", "-w", text],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
        except Exception as e:
            print(f"TTS failed: {e}")
    threading.Thread(target=_speak, daemon=True).start()


def run_cmd(cmd: list[str]):
    """Run a command (app must be started with sudo)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        print(f"cmd {cmd} failed: {proc.stderr.strip()}")
    return proc.returncode == 0


def block_internet():
    """Block forwarding from hotspot interface (clients keep WiFi + web access)."""
    # Drop forwarded traffic from hotspot clients
    run_cmd(["iptables", "-I", "FORWARD", "-i", HOTSPOT_IFACE, "-j", "DROP"])
    print("Internet BLOCKED for hotspot clients")


def allow_internet():
    """Allow forwarding from hotspot interface."""
    # Remove all DROP rules for this interface
    while run_cmd(["iptables", "-D", "FORWARD", "-i", HOTSPOT_IFACE, "-j", "DROP"]):
        pass
    print("Internet ALLOWED for hotspot clients")


def usb_reset():
    """Reset the USB WiFi adapter by unbinding and rebinding."""
    print("WATCHDOG: Resetting USB WiFi adapter...")
    unbind = f"/sys/bus/usb/drivers/usb/unbind"
    bind = f"/sys/bus/usb/drivers/usb/bind"
    try:
        with open(unbind, "w") as f:
            f.write(USB_DEVICE)
        time.sleep(3)
        with open(bind, "w") as f:
            f.write(USB_DEVICE)
        time.sleep(5)
        # Wait for interface to reappear
        for _ in range(10):
            if os.path.exists(f"/sys/class/net/{HOTSPOT_IFACE}"):
                break
            time.sleep(1)
        # Bring hotspot back up
        subprocess.run(
            ["nmcli", "connection", "up", CONNECTION_NAME],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(2)
        # Re-apply iptables block if needed
        with state_lock:
            if state["phase"] != "online":
                block_internet()
        print("WATCHDOG: USB WiFi adapter recovered successfully")
        speak("WiFi adapter recovered.")
    except Exception as e:
        print(f"WATCHDOG: USB reset failed: {e}")


def watchdog_loop():
    """Monitor dmesg for firmware errors and auto-reset the USB adapter."""
    error_count = 0
    CHECK_INTERVAL = 30  # seconds between checks
    ERROR_THRESHOLD = 5  # errors to trigger reset
    COOLDOWN = 120       # seconds after reset before checking again
    last_check = time.monotonic()

    while True:
        time.sleep(CHECK_INTERVAL)

        # Detect resume from suspend — if elapsed time >> CHECK_INTERVAL, we slept
        now = time.monotonic()
        elapsed = now - last_check
        last_check = now
        if elapsed > CHECK_INTERVAL * 3:
            error_count = 0
            print(f"WATCHDOG: Resume from suspend detected ({int(elapsed)}s gap), skipping check")
            continue

        try:
            result = subprocess.run(
                ["dmesg", "--since", f"-{CHECK_INTERVAL}s"],
                capture_output=True, text=True, timeout=10,
            )
            # Count firmware error lines for our adapter
            errors = [
                line for line in result.stdout.splitlines()
                if "rtw88" in line and (
                    "failed to get tx report" in line
                    or "failed to download firmware" in line
                    or "failed to leave" in line
                )
            ]
            if errors:
                error_count += len(errors)
                print(f"WATCHDOG: {len(errors)} firmware errors detected (total: {error_count})")
            else:
                error_count = max(0, error_count - 1)  # slowly decay

            if error_count >= ERROR_THRESHOLD:
                print(f"WATCHDOG: Error threshold reached ({error_count}), resetting adapter...")
                usb_reset()
                error_count = 0
                time.sleep(COOLDOWN)  # cooldown after reset
                last_check = time.monotonic()

        except Exception as e:
            print(f"WATCHDOG: check failed: {e}")


def timer_loop():
    """Background thread: wait for phase end, then toggle WiFi."""
    alerted = set()  # track which alerts have fired
    while True:
        with state_lock:
            phase = state["phase"]
            end_time = state["end_time"]

        if phase == "idle":
            alerted.clear()
            time.sleep(1)
            continue

        remaining = end_time - time.time()

        # Voice alerts during online phase
        if phase == "online" and remaining > 0:
            remaining_mins = remaining / 60
            for mins in VOICE_ALERTS:
                if mins not in alerted and remaining_mins <= mins:
                    alerted.add(mins)
                    if mins == 1:
                        speak("Last 1 minute!")
                    else:
                        speak(f"{mins} minutes remaining")

        if remaining > 0:
            time.sleep(min(remaining, 1))
            continue

        # Phase expired
        alerted.clear()
        with state_lock:
            if state["phase"] == "online":
                speak("Time is up. WiFi paused.")
                block_internet()
                state["phase"] = "offline"
                state["end_time"] = time.time() + state["offline_mins"] * 60
            elif state["phase"] == "offline":
                # Stay blocked — user must click Start for internet
                state["phase"] = "idle"
                state["end_time"] = 0


@app.route("/")
def index():
    return render_template_string(HTML_PAGE,
                                  connection_name=CONNECTION_NAME,
                                  online_mins=ONLINE_MINUTES,
                                  offline_mins=OFFLINE_MINUTES)


@app.route("/start", methods=["POST"])
def start():
    with state_lock:
        if state["phase"] != "idle":
            return jsonify(ok=False, msg="Already running"), 409
        allow_internet()
        now = time.time()
        state["phase"] = "online"
        state["start_time"] = now
        state["end_time"] = now + state["online_mins"] * 60
        speak(f"WiFi started. {state['online_mins']} minutes.")
    return jsonify(ok=True, phase="online", seconds=state["online_mins"] * 60)


@app.route("/stop", methods=["POST"])
def stop():
    with state_lock:
        if state["phase"] == "online":
            # Calculate cooldown proportionally to time used
            total_online = state["online_mins"] * 60
            used = time.time() - state["start_time"]
            pct = min(used / total_online, 1.0)
            cooldown = pct * state["offline_mins"] * 60
            block_internet()
            state["phase"] = "offline"
            state["end_time"] = time.time() + cooldown
            cooldown_mins = round(cooldown / 60, 1)
            speak(f"WiFi stopped. Cooldown {cooldown_mins} minutes.")
            return jsonify(ok=True, phase="offline", cooldown=int(cooldown))
        elif state["phase"] == "offline":
            # Already in cooldown — no cancel allowed
            return jsonify(ok=False, msg="In cooldown"), 409
        state["phase"] = "idle"
        state["end_time"] = 0
    return jsonify(ok=True)


@app.route("/status")
def status():
    with state_lock:
        remaining = max(0, state["end_time"] - time.time()) if state["phase"] != "idle" else 0
        return jsonify(
            phase=state["phase"],
            remaining=int(remaining),
            online_mins=state["online_mins"],
            offline_mins=state["offline_mins"],
        )


# ──────────────────────────────────────────────
# HTML / JS  (single-page, no extra files)
# ──────────────────────────────────────────────
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WiFi Timer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f172a; color: #e2e8f0;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh;
  }
  .card {
    background: #1e293b; border-radius: 16px; padding: 40px 48px;
    text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,.4);
    min-width: 340px;
  }
  h1 { font-size: 1.3rem; margin-bottom: 8px; color: #94a3b8; }
  .phase-label {
    font-size: 1rem; margin-bottom: 24px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .1em;
  }
  .phase-idle    { color: #64748b; }
  .phase-online  { color: #22c55e; }
  .phase-offline { color: #ef4444; }

  .timer {
    font-size: 4rem; font-weight: 700; font-variant-numeric: tabular-nums;
    margin-bottom: 32px; letter-spacing: 2px;
  }

  .btn {
    padding: 12px 36px; border: none; border-radius: 8px;
    font-size: 1.1rem; font-weight: 600; cursor: pointer;
    transition: background .2s;
  }
  .btn-start { background: #22c55e; color: #0f172a; }
  .btn-start:hover { background: #16a34a; }
  .btn-stop  { background: #ef4444; color: #fff; }
  .btn-stop:hover  { background: #dc2626; }
  .btn:disabled { opacity: .4; cursor: not-allowed; }

  .info { margin-top: 24px; font-size: .85rem; color: #64748b; }
</style>
</head>
<body>
<div class="card">
  <h1>{{ connection_name }}</h1>
  <div class="phase-label phase-idle" id="phaseLabel">IDLE</div>
  <div class="timer" id="timer">00:00</div>
  <button class="btn btn-start" id="startBtn" onclick="doStart()">Start</button>
  <div class="info">
    Online: {{ online_mins }} min &nbsp;|&nbsp; Offline: {{ offline_mins }} min
  </div>
</div>

<script>
let pollTimer;

function fmt(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
}

function updateUI(data) {
  const label = document.getElementById('phaseLabel');
  const timer = document.getElementById('timer');
  const btn   = document.getElementById('startBtn');

  label.textContent = data.phase.toUpperCase();
  label.className = 'phase-label phase-' + data.phase;
  timer.textContent = fmt(data.remaining);

  if (data.phase === 'idle') {
    btn.textContent = 'Start';
    btn.className = 'btn btn-start';
    btn.disabled = false;
    btn.onclick = doStart;
  } else if (data.phase === 'online') {
    btn.textContent = 'Stop';
    btn.className = 'btn btn-stop';
    btn.disabled = false;
    btn.onclick = doStop;
  } else {
    btn.textContent = 'WiFi Paused';
    btn.className = 'btn btn-stop';
    btn.disabled = true;
    btn.onclick = null;
  }
}

async function poll() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    updateUI(d);
  } catch(e) { console.error(e); }
}

async function doStart() {
  const btn = document.getElementById('startBtn');
  btn.disabled = true;
  try { await fetch('/start', {method:'POST'}); } finally { poll(); }
}

async function doStop() {
  const btn = document.getElementById('startBtn');
  btn.disabled = true;
  try { await fetch('/stop', {method:'POST'}); } finally { poll(); }
}

pollTimer = setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("ERROR: This app must be run with sudo.")
        print("Usage: sudo python3 app.py")
        exit(1)
    # Block internet on startup — user must click Start
    block_internet()
    threading.Thread(target=timer_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
