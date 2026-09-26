"""Keeps the enforcement engines alive through a cancelled shutdown.

When an engine shuts the computer down, Windows walks every running program
and asks it to close.  Console programs - like the Python engines - receive a
close/shutdown console event and, with Python's default handler, exit on the
spot.  Other programs may then hold the shutdown up and Windows shows the
"these apps are preventing shutdown" screen with a *Cancel* button.  Pressing
Cancel at that moment used to leave the computer running with every engine
already gone, i.e. limits were no longer enforced at all.

This module closes that hole in three ways:

* :func:`install_shutdown_survival` registers a console control handler that
  holds on to the close/logoff/shutdown event instead of exiting.  The
  handler runs on its own thread, so the enforcement loop keeps running
  while Windows is shutting down.  If the shutdown really goes through,
  Windows terminates the process anyway; if it is cancelled, the engine is
  still alive and simply issues the shutdown again on its next check.
* :func:`force_shutdown` issues the shutdown and records a "pending" marker
  on disk.
* :func:`shutdown_recently_enforced` lets an engine that was (re)started
  shortly after an enforced shutdown skip most of its startup safety sleep,
  so restarting the engines - or rebooting - no longer hands out minutes of
  free time.  The marker never causes a shutdown by itself: the engine still
  checks the limit / schedule first, so an exception granted by the parent
  is always honoured.
"""

import json
import os
import sys
import time

PENDING_FILE = "shutdown_pending.json"
# How long a recorded enforced shutdown shortens the startup safety sleep.
PENDING_MAX_AGE = 12 * 60 * 60  # seconds

CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6
_HELD_EVENTS = {
    CTRL_CLOSE_EVENT: "close",
    CTRL_LOGOFF_EVENT: "logoff",
    CTRL_SHUTDOWN_EVENT: "shutdown",
}

# Keep a reference to the ctypes callback so it is never garbage collected.
_handler_ref = None


def _log(message):
    try:
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
    except Exception:
        pass


def install_shutdown_survival(name="engine"):
    """Stop console close/logoff/shutdown events from killing this process.

    Returns True when the handler was installed. Safe to call on non-Windows
    systems (does nothing) and safe to call more than once.
    """
    global _handler_ref
    if _handler_ref is not None:
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def _handler(event):
            event_name = _HELD_EVENTS.get(event)
            if event_name is None:
                # Ctrl+C / Ctrl+Break: let Python handle them as usual.
                return 0
            _log(f"[{name}] Received console {event_name} event - staying alive "
                 f"and continuing to enforce.")
            # Hold this handler thread instead of returning: returning (or
            # the default handler) makes Windows end the process right away.
            # The main loop keeps running meanwhile. If the shutdown goes
            # through, Windows terminates the process; if it is cancelled,
            # the engine is still running and enforces again.
            while True:
                time.sleep(60)

        _handler_ref = handler_type(_handler)
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_ref, True):
            _handler_ref = None
            _log(f"[{name}] Could not install shutdown survival handler.")
            return False
        return True
    except Exception as e:
        _handler_ref = None
        _log(f"[{name}] Could not install shutdown survival handler: {e}")
        return False


def _load_pending():
    try:
        with open(PENDING_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pending(data):
    try:
        with open(PENDING_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        _log(f"Warning: Could not write {PENDING_FILE}: {e}")


def mark_shutdown_enforced(source):
    """Record that ``source`` enforced a shutdown just now."""
    data = _load_pending()
    data[source] = time.time()
    _save_pending(data)


def clear_shutdown_enforced(source):
    """Forget a recorded enforced shutdown once ``source`` no longer requires one."""
    data = _load_pending()
    if source in data:
        del data[source]
        _save_pending(data)


def shutdown_recently_enforced(source, max_age=PENDING_MAX_AGE):
    """True if ``source`` enforced a shutdown within the last ``max_age`` seconds."""
    marked = _load_pending().get(source)
    if not isinstance(marked, (int, float)):
        return False
    return 0 <= time.time() - marked <= max_age


def force_shutdown(source):
    """Record the enforced shutdown and tell Windows to shut down now.

    Callers must keep checking afterwards and call this again while the
    restriction still applies: if the shutdown is cancelled, this is what
    turns the computer off again.
    """
    mark_shutdown_enforced(source)
    os.system("shutdown /s /t 0 /F")
