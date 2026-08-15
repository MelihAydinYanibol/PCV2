"""
Night Lockdown Engine for Parental Control

Monitors the current time against parent-defined blocked and whitelisted time
zones. When the computer is turned on inside a blocked window (and not inside a
whitelisted window that overrides it), the computer is shut down.

Configuration is stored in ``nightlockdown.json`` and can be managed through the
REST API / web dashboard.  The schedule may be the same for every day of the
week, or configured individually for each day of the week — the parent decides
via the ``per_day`` flag.

Config format (nightlockdown.json)::

    {
        "enabled": true,
        "per_day": false,
        "all_days": {
            "blocked":   [["22:00", "07:00"]],
            "whitelist": [["23:00", "23:30"]]
        },
        "days": {
            "Monday":    {"blocked": [], "whitelist": []},
            "Tuesday":   {"blocked": [], "whitelist": []},
            "Wednesday": {"blocked": [], "whitelist": []},
            "Thursday":  {"blocked": [], "whitelist": []},
            "Friday":    {"blocked": [], "whitelist": []},
            "Saturday":  {"blocked": [], "whitelist": []},
            "Sunday":    {"blocked": [], "whitelist": []}
        }
    }

A time window is a ``["HH:MM", "HH:MM"]`` pair.  Windows may wrap past midnight
(e.g. ``["22:00", "07:00"]`` means 22:00 through 07:00 the next morning).
"""

import json
import os
import time
from datetime import datetime

try:
    from notifier import safe_toast
except Exception as _notifier_error:  # notifications must never stop the lockdown
    print(f"Notifier unavailable, continuing without toasts: {_notifier_error}")

    def safe_toast(*args, **kwargs):
        return False

NIGHT_LOCKDOWN_FILE = "nightlockdown.json"
CHECK_INTERVAL = 15  # seconds between checks
SAFETY_SLEEP = 180   # 3 minutes security sleep when the module opens
NOTIFY_TIMEOUT = 2   # max seconds to wait for the shutdown toast

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ISO_DAY_MAP = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
               5: "Friday", 6: "Saturday", 7: "Sunday"}


def default_config():
    """Return a disabled default night-lockdown configuration."""
    return {
        "enabled": False,
        "per_day": False,
        "all_days": {"blocked": [], "whitelist": []},
        "days": {day: {"blocked": [], "whitelist": []} for day in DAYS_OF_WEEK},
    }


def ensure_files_exist():
    """Create the night lockdown config file with defaults if it is missing."""
    if not os.path.exists(NIGHT_LOCKDOWN_FILE):
        try:
            with open(NIGHT_LOCKDOWN_FILE, "w") as f:
                json.dump(default_config(), f, indent=2)
        except Exception as e:
            print(f"Warning: Could not create {NIGHT_LOCKDOWN_FILE}: {e}")


def load_config():
    """Load night lockdown config, falling back to defaults on error."""
    try:
        with open(NIGHT_LOCKDOWN_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_config()

    # Merge with defaults so missing keys never crash the engine
    config = default_config()
    if isinstance(data, dict):
        config["enabled"] = bool(data.get("enabled", False))
        config["per_day"] = bool(data.get("per_day", False))
        if isinstance(data.get("all_days"), dict):
            config["all_days"]["blocked"] = data["all_days"].get("blocked", []) or []
            config["all_days"]["whitelist"] = data["all_days"].get("whitelist", []) or []
        if isinstance(data.get("days"), dict):
            for day in DAYS_OF_WEEK:
                day_cfg = data["days"].get(day)
                if isinstance(day_cfg, dict):
                    config["days"][day]["blocked"] = day_cfg.get("blocked", []) or []
                    config["days"][day]["whitelist"] = day_cfg.get("whitelist", []) or []
    return config


def _time_to_minutes(value):
    """Convert an 'HH:MM' string to minutes since midnight. Returns None if invalid."""
    try:
        hours, minutes = str(value).split(":")
        hours, minutes = int(hours), int(minutes)
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours * 60 + minutes
    except Exception:
        pass
    return None


def _in_window(now_minutes, start, end):
    """
    Return True if now_minutes falls inside the [start, end] window.

    Supports windows that wrap past midnight (start > end), e.g. 22:00 -> 07:00.
    """
    if start is None or end is None:
        return False
    if start <= end:
        return start <= now_minutes <= end
    # Wraps past midnight
    return now_minutes >= start or now_minutes <= end


def _matches_any_window(now_minutes, windows):
    """Return True if now_minutes is inside any of the given time windows."""
    if not isinstance(windows, list):
        return False
    for window in windows:
        if isinstance(window, (list, tuple)) and len(window) == 2:
            start = _time_to_minutes(window[0])
            end = _time_to_minutes(window[1])
            if _in_window(now_minutes, start, end):
                return True
    return False


def get_active_schedule(config, day):
    """Return the {'blocked', 'whitelist'} schedule that applies for the given day."""
    if config.get("per_day"):
        return config.get("days", {}).get(day, {"blocked": [], "whitelist": []})
    return config.get("all_days", {"blocked": [], "whitelist": []})


def is_locked_down(config, now=None):
    """
    Determine whether the current moment falls inside a blocked window.

    A moment is "locked down" when it is inside a blocked window AND NOT inside
    a whitelisted window (whitelist overrides blocked).
    """
    if not config.get("enabled"):
        return False

    now = now or datetime.now()
    day = ISO_DAY_MAP.get(now.isoweekday())
    now_minutes = now.hour * 60 + now.minute

    schedule = get_active_schedule(config, day)
    blocked = schedule.get("blocked", [])
    whitelist = schedule.get("whitelist", [])

    if _matches_any_window(now_minutes, blocked):
        # Whitelisted windows carve exceptions out of blocked windows
        if _matches_any_window(now_minutes, whitelist):
            return False
        return True
    return False


def notify_shutdown():
    """Best-effort toast warning the user before the computer shuts down.

    Waits a couple of seconds so the toast has a chance to reach Windows
    before the shutdown command is issued, but never longer than that - the
    shutdown must happen whether or not the notification works.
    """
    safe_toast(
        "HASSS Agent",
        "Gece kilidi aktif. Bilgisayar kapatılıyor.",
        wait=NOTIFY_TIMEOUT,
        scenario="urgent",
    )


def shutdown():
    """Force an immediate shutdown of the computer."""
    print("Night lockdown active. Shutting down the computer.")
    notify_shutdown()
    os.system("shutdown /s /t 0 /F")


def main():
    ensure_files_exist()
    print(f"Night Lockdown started -- Waiting {SAFETY_SLEEP} seconds for security.")
    time.sleep(SAFETY_SLEEP)
    print("Night Lockdown monitoring started.\n")

    while True:
        config = load_config()
        if is_locked_down(config):
            shutdown()
            # Give the shutdown command time to take effect before looping again
            time.sleep(CHECK_INTERVAL)
        else:
            if config.get("enabled"):
                print(f"Night lockdown check passed at {datetime.now().strftime('%H:%M:%S')}")
            else:
                print("Night lockdown disabled.")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("Exiting due to KeyboardInterrupt.")
            break
        except Exception as e:
            print(f"Error in night lockdown loop: {e}")
            time.sleep(2)
            continue
