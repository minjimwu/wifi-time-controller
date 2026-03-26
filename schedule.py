#!/usr/bin/env python3
"""
Schedule manager for wifi-time-controller.
Handles sleeping/waking the computer based on config.json schedule.

Usage (must run as root):
  sudo python3 schedule.py check    — if outside schedule, suspend until next wake time
  sudo python3 schedule.py sleep    — suspend now until next wake time
  sudo python3 schedule.py next     — print next wake time (no action)
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

with open(CONFIG_PATH) as _f:
    CONFIG = json.load(_f)

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_schedule():
    with open(CONFIG_PATH) as f:
        return json.load(f).get("schedule", {})


def parse_time(t: str):
    """Parse 'HH:MM' to (hour, minute)."""
    h, m = t.split(":")
    return int(h), int(m)


def is_in_schedule(now: datetime, schedule: dict) -> bool:
    """Check if current time is within today's schedule."""
    day_key = DAYS[now.weekday()]
    day = schedule.get(day_key)
    if not day:
        return False
    start_h, start_m = parse_time(day["start"])
    end_h, end_m = parse_time(day["end"])
    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start <= now < end


def next_wake_time(now: datetime, schedule: dict) -> datetime:
    """Find the next scheduled start time from now."""
    for offset in range(0, 8):
        check = now + timedelta(days=offset)
        day_key = DAYS[check.weekday()]
        day = schedule.get(day_key)
        if not day:
            continue
        start_h, start_m = parse_time(day["start"])
        wake = check.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        if wake > now:
            return wake
    return None


def seconds_until_end(now: datetime, schedule: dict) -> int:
    """Seconds until today's schedule ends."""
    day_key = DAYS[now.weekday()]
    day = schedule.get(day_key)
    if not day:
        return 0
    end_h, end_m = parse_time(day["end"])
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return max(0, int((end - now).total_seconds()))


def suspend_until(wake: datetime):
    """Suspend the machine and wake at the given time via rtcwake."""
    secs = max(60, int((wake - datetime.now()).total_seconds()))
    print(f"Suspending... will wake at {wake.strftime('%Y-%m-%d %H:%M')} ({secs}s)")
    subprocess.run(["rtcwake", "-m", "mem", "-s", str(secs)], check=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    schedule = load_schedule()
    now = datetime.now()

    if cmd == "next":
        wake = next_wake_time(now, schedule)
        if wake:
            print(f"Next wake: {wake.strftime('%A %Y-%m-%d %H:%M')}")
        else:
            print("No scheduled wake time found")

    elif cmd == "check":
        if is_in_schedule(now, schedule):
            remaining = seconds_until_end(now, schedule)
            print(f"In schedule. {remaining // 60} minutes remaining today.")
        else:
            grace = CONFIG.get("boot_guard_grace_minutes", 60)
            wake = next_wake_time(now, schedule)
            if wake:
                print(f"Outside schedule. Grace period: {grace} minutes before suspend.")
                print(f"Will suspend at {(now + timedelta(minutes=grace)).strftime('%H:%M')} → wake at {wake.strftime('%A %H:%M')}")
                time.sleep(grace * 60)
                # Re-check: maybe we're now inside schedule
                now2 = datetime.now()
                if is_in_schedule(now2, load_schedule()):
                    print("Now inside schedule. Staying awake.")
                else:
                    wake2 = next_wake_time(now2, load_schedule())
                    if wake2:
                        suspend_until(wake2)
            else:
                print("No schedule found, staying awake.")

    elif cmd == "sleep":
        wake = next_wake_time(now, schedule)
        if wake:
            suspend_until(wake)
        else:
            print("No next wake time found.")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
