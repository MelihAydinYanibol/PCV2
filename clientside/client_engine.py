"""
Client engine for parental control.

Tracks how long configured applications (and the computer as a whole, under the
``OVERALL`` key) are used each day, kills applications that exceed their daily
limit, shuts the computer down when the overall limit is reached, and warns the
user with Windows toasts before that happens.

Files (shared with ``api.py``):
    timelimit.json        {"chrome.exe": {"Monday": 3600, ...}, "OVERALL": {...}}
    timeusage.json        {"2026-01-17": {"chrome.exe": 1200, "OVERALL": 5400}}
    exceptionaltime.json  {"2026-01-17": {"chrome.exe": [[300, "reason"], ["7200", null]]}}
    used_exceptions.json  ids of exceptions the user was already notified about

Exception entries: an int/float adds (or, if negative, removes) seconds; a
numeric string sets the day's limit outright.

Only ``psutil`` is required; Home Assistant calls use ``urllib`` and toasts use
the dependency-free ``notifier`` module.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import psutil

from notifier import get_notifier

# ----------------------------------------------------------------- settings

LIMIT_FILE = "timelimit.json"
DATA_FILE = "timeusage.json"
EXCEPTION_FILE = "exceptionaltime.json"
USED_EXCEPTIONS_FILE = "used_exceptions.json"
ENV_FILE = ".env"

OVERALL = "OVERALL"
CHECK_INTERVAL = 5   # seconds between checks
SAFETY_SLEEP = 120   # seconds to wait after start before enforcing anything
# Elapsed time credited for a single tick is capped so a suspended/hibernated
# machine does not get hours of usage added when it wakes up.
MAX_TICK_CREDIT = CHECK_INTERVAL * 3
SHUTDOWN_RETRY_DELAY = 60

USAGE_NOTIFIERS = (30, 60, 120, 300)  # seconds remaining
TTS_EVENTS = {30: "cc5f5e65-8d04-48bb-947f-243d9184e6cc",
              60: "704097ff-8ac4-4b4b-8384-3fbfb7d70638",
              120: "18f01511-0614-4f78-8f57-5172cbd361db",
              300: "f0ca5816-3855-4ca5-801d-a816603a2763"}
# When an app (or OVERALL) has no limit configured for the current day — the key
# is missing or explicitly null — treat it as effectively unlimited for that day
# so the engine never restricts something the parent didn't set up. An explicit
# 0 still means "disabled for that day". 86399 = seconds in a day minus one.
UNCONFIGURED_LIMIT = 24 * 60 * 60 - 1

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

log = logging.getLogger("engine")


# ------------------------------------------------------------------ helpers

def load_env_file(path=ENV_FILE):
    """Minimal .env reader (KEY=VALUE lines); real environment variables win."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Could not read %s: %s", path, e)


def format_duration(seconds):
    seconds = abs(int(seconds))
    if seconds < 60:
        return f"{seconds} saniye"
    if seconds % 60 == 0:
        return f"{seconds // 60} dakika"
    return f"{seconds // 60} dakika {seconds % 60} saniye"


def subject_text(name):
    return "Bilgisayar kullanımı için" if name == OVERALL else f"{name} adlı uygulama için"


# ---------------------------------------------------------------- JSON store

class JsonStore:
    """
    A JSON file that is only re-read when it changes on disk.

    If the file is missing, half-written (by another process) or corrupt, the
    last successfully loaded value is kept instead of silently falling back to
    an empty default — a corrupt usage file must never reset the day's usage.
    """

    def __init__(self, path, default_factory):
        self.path = path
        self._default_factory = default_factory
        self._data = default_factory()
        self._stamp = None
        self._warned = False

    def ensure_exists(self):
        if not os.path.exists(self.path):
            self.save(self._default_factory())

    def _file_stamp(self):
        try:
            st = os.stat(self.path)
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def changed_on_disk(self):
        return self._file_stamp() != self._stamp

    def load(self):
        stamp = self._file_stamp()
        if stamp is None or stamp == self._stamp:
            return self._data
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            # Leave _stamp untouched so the next call retries the read.
            if not self._warned:
                log.warning("Could not read %s (%s); keeping last known data.", self.path, e)
                self._warned = True
            return self._data
        if not isinstance(data, type(self._default_factory())):
            log.warning("Unexpected content in %s; keeping last known data.", self.path)
            self._stamp = stamp
            return self._data
        self._data, self._stamp, self._warned = data, stamp, False
        return self._data

    def save(self, data):
        """Atomically replace the file. Returns True on success."""
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            # The API may have the file open for reading, which makes
            # os.replace fail on Windows; retry briefly before giving up.
            for attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05)
        except OSError as e:
            log.error("Could not save %s: %s", self.path, e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        self._data, self._stamp = data, self._file_stamp()
        return True


# --------------------------------------------------------------- components

class UsageTracker:
    """
    Accumulates usage in memory and merges it into timeusage.json.

    Only the increments since the last flush are kept separately, so edits made
    to the file by the API (e.g. a parent resetting today's usage) are picked up
    instead of being overwritten by a stale copy.
    """

    def __init__(self, store):
        self.store = store
        self._pending = {}   # day -> name -> whole seconds not yet written
        self._carry = {}     # name -> fractional seconds not yet counted

    def get(self, day, name):
        saved = self.store.load().get(day, {}).get(name, 0)
        if not isinstance(saved, (int, float)):
            saved = 0
        return int(saved) + self._pending.get(day, {}).get(name, 0)

    def add(self, day, names, seconds):
        day_pending = self._pending.setdefault(day, {})
        for name in names:
            total = self._carry.get(name, 0.0) + seconds
            whole = int(total)
            self._carry[name] = total - whole
            if whole:
                day_pending[name] = day_pending.get(name, 0) + whole

    def flush(self):
        if not self._pending:
            return
        current = self.store.load()  # re-reads only if changed externally
        merged = dict(current)
        for day, increments in self._pending.items():
            day_usage = dict(merged.get(day) or {})
            for name, secs in increments.items():
                prev = day_usage.get(name, 0)
                day_usage[name] = (int(prev) if isinstance(prev, (int, float)) else 0) + secs
            merged[day] = day_usage
        if self.store.save(merged):
            self._pending.clear()


class LimitResolver:
    """Reads the configured per-day limits."""

    def __init__(self, store):
        self.store = store

    def tracked_names(self):
        return [name for name in self.store.load() if name != OVERALL]

    def base_limit(self, name, dow):
        per_day = self.store.load().get(name)
        value = per_day.get(dow) if isinstance(per_day, dict) else None
        if value is None or isinstance(value, bool):
            return UNCONFIGURED_LIMIT
        try:
            return int(value)
        except (TypeError, ValueError):
            log.warning("Invalid limit %r for %s on %s; treating as unconfigured.", value, name, dow)
            return UNCONFIGURED_LIMIT


class ExceptionResolver:
    """Applies today's exceptions to a base limit and announces new ones once."""

    def __init__(self, store, used_store, notifier):
        self.store = store
        self.used_store = used_store
        self.notifier = notifier
        self._used = set()
        self._day = None

    def _load_used(self, day):
        used = self.used_store.load()
        self._used = {i for i in used if isinstance(i, str)} if isinstance(used, list) else set()
        self._day = day
        # Drop ids from previous days so the file does not grow forever.
        todays = {i for i in self._used if i.startswith(f"{day}_")}
        if todays != self._used:
            self._used = todays
            self.used_store.save(sorted(todays))

    @staticmethod
    def _entries(raw):
        if not isinstance(raw, list):
            return []
        # Legacy single-entry format: [time, reason]
        if len(raw) == 2 and isinstance(raw[0], (int, float, str)) and not isinstance(raw[0], bool):
            return [raw]
        return [e for e in raw if isinstance(e, (list, tuple)) and e]

    def apply(self, day, name, base_limit):
        if self._day != day:
            self._load_used(day)
        raw = self.store.load().get(day, {})
        entries = self._entries(raw.get(name) if isinstance(raw, dict) else None)

        limit, new_ids = base_limit, []
        for idx, entry in enumerate(entries):
            value = entry[0]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                amount, is_set = int(value), False
            else:
                try:
                    amount, is_set = int(str(value).strip()), True
                except ValueError:
                    log.warning("Ignoring invalid exception %r for %s on %s.", value, name, day)
                    continue
            limit = amount if is_set else limit + amount

            entry_id = f"{day}_{name}_{idx}_{amount}"
            legacy_id = f"{day}_{name}_{amount}"
            if entry_id not in self._used and legacy_id not in self._used:
                new_ids.append(entry_id)
                self._announce(name, amount, is_set)

        if new_ids:
            self._used.update(new_ids)
            self.used_store.save(sorted(self._used))
        return limit

    def _announce(self, name, amount, is_set):
        if is_set:
            action = f"süre {format_duration(amount)} yapıldı."
        elif amount >= 0:
            action = f"{format_duration(amount)} eklendi."
        else:
            action = f"{format_duration(amount)} azaltıldı."
        self.notifier.notify(f"{subject_text(name)} {action}", key=f"exc:{name}")


class HomeAssistant:
    """Fire-and-forget Home Assistant tag events (stdlib only)."""

    def __init__(self, url, token):
        self.url = (url or "").rstrip("/")
        self.token = token

    def trigger_tag(self, tag_id):
        if not self.token or not self.url:
            log.debug("Home Assistant not configured; skipping tag %s.", tag_id)
            return
        threading.Thread(target=self._post, args=(tag_id,), daemon=True, name="ha-tag").start()

    def _post(self, tag_id):
        req = urllib.request.Request(
            f"{self.url}/api/events/tag_scanned",
            data=json.dumps({"tag_id": tag_id}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                resp.read()
            log.info("Home Assistant tag event %s triggered.", tag_id)
        except (urllib.error.URLError, OSError) as e:
            log.warning("Failed to trigger Home Assistant event: %s", e)


class RemainingTimeNotifier:
    """
    Warns when remaining time crosses one of ``USAGE_NOTIFIERS``.

    Crossing detection (rather than an exact ``remaining == threshold`` match)
    means a warning is never skipped because of timer jitter, and a threshold is
    re-armed if an exception raises the limit back above it.
    """

    def __init__(self, notifier, home_assistant, thresholds=USAGE_NOTIFIERS):
        self.notifier = notifier
        self.ha = home_assistant
        self.thresholds = sorted(thresholds)
        self._fired = {}  # name -> set of thresholds already announced
        self._day = None

    def check(self, day, name, remaining):
        if day != self._day:
            self._fired.clear()
            self._day = day
        fired = self._fired.setdefault(name, set())
        fired.difference_update({t for t in fired if remaining > t})

        crossed = [t for t in self.thresholds if remaining <= t and t not in fired]
        if not crossed:
            return
        fired.update(crossed)
        threshold = crossed[0]  # the smallest one is the most relevant

        prefix = "Kalan bilgisayar kullanım süresi" if name == OVERALL else f"{name} adlı uygulama için kalan süre"
        self.notifier.notify(f"{prefix} {format_duration(remaining)}", key=f"remaining:{name}")
        # Only play the spoken announcement when it is still accurate.
        if name == OVERALL and threshold in TTS_EVENTS and threshold - remaining <= CHECK_INTERVAL:
            self.ha.trigger_tag(TTS_EVENTS[threshold])


class ProcessController:
    """Finds tracked processes and terminates them."""

    def __init__(self):
        self._access_denied_warned = set()

    def scan(self, tracked_names):
        """Return {configured name: [pid, ...]}, matching names case-insensitively."""
        lookup = {n.lower(): n for n in tracked_names}
        found = {}
        if not lookup:
            return found
        for proc in psutil.process_iter(["name"]):
            pname = proc.info.get("name")
            if pname:
                configured = lookup.get(pname.lower())
                if configured is not None:
                    found.setdefault(configured, []).append(proc.pid)
        return found

    def kill(self, name, pids):
        for pid in pids:
            try:
                psutil.Process(pid).kill()
                log.info("Time exceeded for %s, killed PID %s.", name, pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                if name not in self._access_denied_warned:
                    self._access_denied_warned.add(name)
                    log.error("Access denied killing %s (PID %s); is the engine running elevated?", name, pid)


# ------------------------------------------------------------------- engine

class ClientEngine:
    def __init__(self):
        load_env_file()
        self.notifier = get_notifier()
        self.limits_store = JsonStore(LIMIT_FILE, dict)
        self.usage_store = JsonStore(DATA_FILE, dict)
        self.exception_store = JsonStore(EXCEPTION_FILE, dict)
        self.used_store = JsonStore(USED_EXCEPTIONS_FILE, list)

        self.limits = LimitResolver(self.limits_store)
        self.usage = UsageTracker(self.usage_store)
        self.exceptions = ExceptionResolver(self.exception_store, self.used_store, self.notifier)
        self.remaining = RemainingTimeNotifier(
            self.notifier,
            HomeAssistant(os.getenv("HASS_URL", "http://homeassistant.local:8123"), os.getenv("HASS_TOKEN")),
        )
        self.processes = ProcessController()
        self._active = set()  # names credited with usage on the next tick

    def ensure_files_exist(self):
        for store in (self.limits_store, self.usage_store, self.exception_store, self.used_store):
            store.ensure_exists()

    def effective_limit(self, day, dow, name):
        return self.exceptions.apply(day, name, self.limits.base_limit(name, dow))

    def tick(self, elapsed):
        now = datetime.now()
        day, dow = now.strftime("%Y-%m-%d"), DAYS[now.weekday()]

        # Credit the time since the last tick to whatever was running then.
        if self._active:
            self.usage.add(day, self._active, min(max(elapsed, 0.0), MAX_TICK_CREDIT))
        self._active = set()

        # OVERALL first: if the machine is shutting down nothing else matters.
        overall_limit = self.effective_limit(day, dow, OVERALL)
        overall_used = self.usage.get(day, OVERALL)
        if overall_used >= overall_limit:
            self.usage.flush()
            self.shutdown(overall_used, overall_limit)
            return
        self.remaining.check(day, OVERALL, overall_limit - overall_used)
        self._active.add(OVERALL)

        for name, pids in self.processes.scan(self.limits.tracked_names()).items():
            limit = self.effective_limit(day, dow, name)
            used = self.usage.get(day, name)
            if used >= limit:
                self.processes.kill(name, pids)
            else:
                log.debug("%s: %s/%s s", name, used, limit)
                self.remaining.check(day, name, limit - used)
                self._active.add(name)

        self.usage.flush()

    def shutdown(self, used, limit):
        log.warning("Overall usage %s/%s s exceeded. Shutting down the computer.", used, limit)
        self.notifier.notify("Bilgisayar kullanım süresi doldu. Bilgisayar kapatılıyor.", key="shutdown")
        self.notifier.flush(timeout=5)
        try:
            subprocess.run(["shutdown", "/s", "/t", "0", "/f"], check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.CalledProcessError) as e:
            log.error("Shutdown command failed: %s", e)
        # Give Windows time to act; if it did not, the next tick tries again.
        time.sleep(SHUTDOWN_RETRY_DELAY)

    def run(self, safety_sleep=SAFETY_SLEEP):
        self.ensure_files_exist()
        log.info("Engine started -- waiting %s seconds for security.", safety_sleep)
        time.sleep(safety_sleep)
        log.info("Monitoring started.")

        consecutive_errors = 0
        last = time.monotonic()
        while True:
            now = time.monotonic()
            elapsed, last = now - last, now
            try:
                self.tick(elapsed)
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                log.exception("Error during check (%s in a row).", consecutive_errors)
            # Keep a steady cadence regardless of how long the tick took, but
            # back off a little if something keeps failing.
            delay = CHECK_INTERVAL * min(1 + consecutive_errors, 6)
            time.sleep(max(0.0, delay - (time.monotonic() - now)))


def setup_logging():
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    # Toast texts are Turkish; don't let a cp1252 console turn logging into errors.
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=level, stream=sys.stdout,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")


if __name__ == "__main__":
    setup_logging()
    try:
        ClientEngine().run()
    except KeyboardInterrupt:
        log.info("Exiting due to KeyboardInterrupt.")
