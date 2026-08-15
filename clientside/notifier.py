"""Failsafe wrapper around the optional Windows toast notification backend.

Toast notifications are a convenience, never a requirement: they go through
the Windows WinRT stack, which can be missing (running on a non-Windows box,
``win11toast`` not installed), broken (notifications disabled by policy,
corrupted registration) or simply hang for a long time.  None of that should
ever stop the parental control engines from tracking usage and enforcing
limits, so every toast is sent through :func:`safe_toast`, which

* never raises - any backend failure is caught and printed,
* never blocks the caller by default - the toast is dispatched on a daemon
  thread so a hanging WinRT call cannot freeze the monitoring loop,
* gives up gracefully - after ``MAX_CONSECUTIVE_FAILURES`` failed toasts in a
  row notifications are disabled for the rest of the run instead of retrying
  (and possibly hanging) on every single check.
"""

import sys
import threading

# Stop trying to notify after this many failures in a row.
MAX_CONSECUTIVE_FAILURES = 5
# How many dispatched-but-unfinished toasts we tolerate before assuming the
# backend is hung and treating further attempts as failures.
MAX_OUTSTANDING = 3

try:
    from win11toast import toast as _toast
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on platform / install
    _toast = None
    _IMPORT_ERROR = e

_lock = threading.Lock()
_consecutive_failures = 0
_outstanding = 0
_disabled = _toast is None
_warned_unavailable = False


def _log(message):
    """Print in a single write so toast-thread logs don't split caller logs."""
    try:
        sys.stdout.write(f"{message}\n")
    except Exception:
        pass


def notifications_available():
    """True while toasts are still being attempted."""
    with _lock:
        return not _disabled


def reset_notifications():
    """Re-enable notifications after they were disabled by repeated failures."""
    global _consecutive_failures, _disabled
    with _lock:
        _consecutive_failures = 0
        _disabled = _toast is None


def _record_success():
    global _consecutive_failures
    with _lock:
        _consecutive_failures = 0


def _record_failure(reason):
    global _consecutive_failures, _disabled
    with _lock:
        _consecutive_failures += 1
        failures = _consecutive_failures
        just_disabled = failures >= MAX_CONSECUTIVE_FAILURES and not _disabled
        if just_disabled:
            _disabled = True
    _log(f"Failed to send notification ({failures}/{MAX_CONSECUTIVE_FAILURES}): {reason}")
    if just_disabled:
        _log("Toast notifications disabled after repeated failures. "
             "Monitoring continues without them.")


def safe_toast(title, body, wait=0, **kwargs):
    """Show a toast without ever letting it break the caller.

    ``wait`` is the number of seconds to block waiting for the toast to be
    handed to Windows; 0 (the default) dispatches it and returns immediately.
    Pass a small value when the toast must have a chance to appear before the
    caller does something drastic, such as shutting the computer down.

    Returns True when the toast was dispatched (and, when ``wait`` is set,
    completed within that time), False when it was skipped or failed.  The
    return value is informational - callers may ignore it.
    """
    global _outstanding, _warned_unavailable

    with _lock:
        if _disabled:
            if _toast is None and not _warned_unavailable:
                _warned_unavailable = True
                _log(f"Toast notifications unavailable, continuing without them: {_IMPORT_ERROR}")
            return False
        if _outstanding >= MAX_OUTSTANDING:
            hung = _outstanding
        else:
            hung = 0
            _outstanding += 1

    if hung:
        _record_failure(f"{hung} earlier notifications still pending, backend looks stuck")
        return False

    done = threading.Event()
    result = {}

    def worker():
        global _outstanding
        try:
            _toast(title, body, **kwargs)
            result["ok"] = True
        except BaseException as e:  # keep a broken backend inside this thread
            result["error"] = e
        finally:
            with _lock:
                _outstanding -= 1
            done.set()
            if "error" in result:
                _record_failure(result["error"])
            elif result.get("ok"):
                _record_success()

    try:
        threading.Thread(target=worker, name="toast-notifier", daemon=True).start()
    except Exception as e:
        with _lock:
            _outstanding -= 1
        _record_failure(f"could not start notification thread: {e}")
        return False

    if wait:
        if not done.wait(wait):
            # The toast may still show up later; we just stop waiting for it.
            _log(f"Notification still pending after {wait}s, continuing.")
            return False
        return bool(result.get("ok"))
    return True
