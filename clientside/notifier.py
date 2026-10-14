"""
Dependency-free Windows toast notifications.

Toasts are shown by handing a small script to the built-in Windows PowerShell
(5.1), which talks to the WinRT ``ToastNotificationManager``.  Doing the work
out of process keeps the engine light: no WinRT/asyncio bindings are loaded into
the long-running Python process, and a hung or crashing notification can never
stall the monitoring loop.

Notifications are delivered by a single daemon worker thread:

* ``Notifier.notify`` never blocks the caller.
* Each toast has a ``tag``; a newer toast with the same tag replaces the older
  one in Action Center instead of piling up, and if several toasts with the same
  tag are queued before the worker gets to them only the newest is shown.
* Failures are logged once per kind and never raised to the caller; after
  ``MAX_CONSECUTIVE_FAILURES`` failures in a row notifications are switched off
  for the rest of the run so a broken backend isn't retried on every check.

``safe_toast(title, body, wait=0, **kwargs)`` is kept for callers written
against the earlier win11toast-based wrapper.
"""

import base64
import logging
import os
import subprocess
import sys
import threading
import zlib
from collections import OrderedDict
from xml.sax.saxutils import escape

log = logging.getLogger("notifier")

# AppUserModelID of Windows PowerShell. It is registered on every Windows
# install, so toasts show up without having to register our own app identity.
DEFAULT_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
DEFAULT_TITLE = "HASSS Agent"
POWERSHELL_TIMEOUT = 15  # seconds
MAX_PENDING = 20
MAX_CONSECUTIVE_FAILURES = 5

_CREATE_NO_WINDOW = 0x08000000

_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{xml}
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$toast.Tag = '{tag}'
$toast.Group = 'pcv2'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show($toast)
"""


def _ps_quote(value):
    """Escape a value for use inside a single-quoted PowerShell string."""
    return value.replace("'", "''")


def _make_tag(key):
    """Toast tags are limited to 64 chars; derive a short stable tag from any key."""
    return f"t{zlib.crc32(key.encode('utf-8')):08x}"


class Notifier:
    def __init__(self, app_id=None, title=DEFAULT_TITLE):
        self.app_id = app_id or os.getenv("TOAST_APP_ID") or DEFAULT_APP_ID
        self.title = title
        self._enabled = sys.platform == "win32"
        self._pending = OrderedDict()  # tag -> (title, message, scenario)
        self._cond = threading.Condition()
        self._worker = None
        self._idle = threading.Event()
        self._idle.set()
        self._reported_errors = set()
        self._consecutive_failures = 0

    # ------------------------------------------------------------------ public

    def notify(self, message, key=None, title=None, urgent=True):
        """Queue a toast. Never blocks and never raises."""
        log.info("Notify: %s", message)
        if not self._enabled:
            return
        tag = _make_tag(key or message)
        with self._cond:
            # Coalesce: drop an older pending toast with the same tag.
            self._pending.pop(tag, None)
            while len(self._pending) >= MAX_PENDING:
                self._pending.popitem(last=False)
            self._pending[tag] = (title or self.title, message, "urgent" if urgent else None)
            self._idle.clear()
            self._ensure_worker()
            self._cond.notify()

    @property
    def available(self):
        return self._enabled

    def reset(self):
        """Re-enable notifications after they were disabled by repeated failures."""
        self._consecutive_failures = 0
        self._enabled = sys.platform == "win32"

    def flush(self, timeout=None):
        """Wait until every queued toast has been handed to Windows."""
        return self._idle.wait(timeout)

    # ----------------------------------------------------------------- private

    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="toast-worker", daemon=True)
            self._worker.start()

    def _run(self):
        while True:
            with self._cond:
                while not self._pending:
                    self._idle.set()
                    self._cond.wait()
                tag, (title, message, scenario) = self._pending.popitem(last=False)
            try:
                ok = self._show(tag, title, message, scenario)
            except Exception as e:  # never let the worker die
                self._report("unexpected", f"Toast worker error: {e}")
                ok = False
            self._record(ok)

    def _record(self, ok):
        if ok:
            self._consecutive_failures = 0
            return
        self._consecutive_failures += 1
        if self._enabled and self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self._enabled = False
            with self._cond:
                self._pending.clear()
            log.warning("Toast notifications disabled after %s failures in a row. "
                        "Monitoring continues without them.", self._consecutive_failures)

    def _build_xml(self, title, message, scenario):
        scenario_attr = f' scenario="{scenario}"' if scenario else ""
        return (
            f"<toast{scenario_attr}><visual><binding template=\"ToastGeneric\">"
            f"<text>{escape(title)}</text><text>{escape(message)}</text>"
            f"</binding></visual></toast>"
        )

    def _show(self, tag, title, message, scenario):
        # escape() handles &, <, >; apostrophes are escaped too so the XML can
        # never terminate the PowerShell here-string early.
        xml = self._build_xml(title, message, scenario).replace("'", "&apos;")
        script = _PS_TEMPLATE.format(xml=xml, tag=_ps_quote(tag), app_id=_ps_quote(self.app_id))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", encoded],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=POWERSHELL_TIMEOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
        except FileNotFoundError:
            self._report("missing", "powershell.exe not found; toast notifications disabled.")
            self._enabled = False
            return False
        except subprocess.TimeoutExpired:
            self._report("timeout", "Showing a toast timed out.")
            return False
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", "replace").strip().splitlines()
            self._report(f"rc{result.returncode}", f"Toast failed: {err[-1] if err else result.returncode}")
            return False
        return True

    def _report(self, kind, msg):
        # Log the first occurrence at WARNING, repeats at DEBUG to avoid log spam.
        if kind in self._reported_errors:
            log.debug(msg)
        else:
            self._reported_errors.add(kind)
            log.warning(msg)


_default = None
_default_lock = threading.Lock()


def get_notifier():
    """Process-wide shared notifier."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Notifier()
        return _default


def notify(message, key=None, title=None, urgent=True):
    get_notifier().notify(message, key=key, title=title, urgent=urgent)


def notifications_available():
    return get_notifier().available


def reset_notifications():
    get_notifier().reset()


def safe_toast(title, body, wait=0, scenario="urgent", **_ignored):
    """Show a toast without ever letting it break the caller.

    ``wait`` is how many seconds to block until the toast has been handed to
    Windows (0 returns immediately). Returns False if notifications are
    unavailable or the wait timed out; callers may ignore the result.
    """
    n = get_notifier()
    if not n.available:
        return False
    n.notify(body, key=body, title=title, urgent=scenario == "urgent")
    return n.flush(wait) if wait else True
