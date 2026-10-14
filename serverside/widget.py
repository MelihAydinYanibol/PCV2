"""
Compact, read-only summary of today's PCV2 state for dashboard widgets.

Used by the embeddable /widget page and handy on its own for homelab
dashboards (e.g. Homepage's ``customapi`` widget): ``GET /api/widget/data``.

The time-left maths mirrors the engines on the kid's computer:

* client_engine.check_exception(): exceptions are applied in order; an int
  adds/removes seconds, anything else that parses as a number sets the limit.
  A day without a configured limit is "no limit" (86399 s).
* night_lockdown.py: the current weekday's schedule, inclusive minutes,
  windows may cross midnight, whitelist overrides blocked.

Times are computed with this server's clock, so keep it in the same time
zone as the kid's computer.
"""

import json
import threading
import time
from datetime import datetime, timedelta

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
UNCONFIGURED_LIMIT = 24 * 60 * 60 - 1
RUNNING_WINDOW = 20  # usage grew within this many seconds -> "running"

# Remember the last usage numbers so we can tell which apps are counting up
_track_lock = threading.Lock()
_track = {"date": None, "usage": {}, "increase": {}}


def _note_usage(date, usage, live):
    now = time.time()
    with _track_lock:
        if not live:
            return
        if _track["date"] != date:
            _track.update(date=date, usage=dict(usage), increase={"OVERALL": now})
            return
        for name, secs in usage.items():
            try:
                if float(secs) > float(_track["usage"].get(name, 0) or 0):
                    _track["increase"][name] = now
            except (TypeError, ValueError):
                continue
        _track["usage"] = dict(usage)


def _running(name, live):
    if not live:
        return False
    with _track_lock:
        return time.time() - _track["increase"].get(name, 0) < RUNNING_WINDOW


# ------------------------------------------------------------------ limits
def _normalize_entries(exc):
    if not isinstance(exc, list):
        return []
    if len(exc) == 2 and isinstance(exc[0], (int, float)) and not isinstance(exc[0], bool):
        return [exc]  # old single-entry format [time, reason]
    return [e for e in exc if isinstance(e, (list, tuple)) and e]


def _classify(t):
    """Return ('add'|'set', seconds) like client_engine.check_exception, or (None, 0)."""
    if type(t) is int:
        return "add", t
    try:
        return "set", int(t)
    except (TypeError, ValueError):
        return None, 0


def compute_limit(name, day, limits, exceptions):
    configured = (limits.get(name) or {}).get(day) if isinstance(limits, dict) else None
    unset = configured is None
    try:
        base = UNCONFIGURED_LIMIT if unset else int(configured)
    except (TypeError, ValueError):
        base, unset = UNCONFIGURED_LIMIT, True
    effective, unlimited, added, set_to = base, unset, 0, None
    for entry in _normalize_entries((exceptions or {}).get(name)):
        kind, value = _classify(entry[0])
        if kind == "add":
            effective += value
            added += value
        elif kind == "set":
            effective, set_to, added, unlimited = value, value, 0, False
    return {
        "configured": None if unset else base,
        "effective": effective,
        "unlimited": unlimited,
        "added": added,
        "set_to": set_to,
    }


# ------------------------------------------------------------------ lockdown
def _to_min(value):
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except Exception:
        pass
    return None


def _in_window(now, start, end):
    if start is None or end is None:
        return False
    return start <= now <= end if start <= end else (now >= start or now <= end)


def _schedule(nl, day):
    if nl.get("per_day"):
        return (nl.get("days") or {}).get(day) or {}
    return nl.get("all_days") or {}


def _blocked_at(nl, dt):
    sch = _schedule(nl, DAYS[dt.weekday()])
    mins = dt.hour * 60 + dt.minute

    def any_match(windows):
        return any(isinstance(w, (list, tuple)) and len(w) == 2 and _in_window(mins, _to_min(w[0]), _to_min(w[1]))
                   for w in (windows or []))

    return any_match(sch.get("blocked")) and not any_match(sch.get("whitelist"))


_lock_memo = {"key": None, "value": None}


def lockdown_info(nl, now=None):
    """{'enabled', 'active', 'starts_at', 'ends_at'} as datetimes (or None)."""
    if not isinstance(nl, dict) or not nl.get("enabled"):
        return {"enabled": False, "active": False, "starts_at": None, "ends_at": None}
    now = now or datetime.now()
    key = json.dumps(nl, sort_keys=True) + now.strftime("|%Y-%m-%d %H:%M")
    if _lock_memo["key"] == key:
        return _lock_memo["value"]

    base = now.replace(second=0, microsecond=0)
    horizon = 8 * 24 * 60
    result = {"enabled": True, "active": _blocked_at(nl, now), "starts_at": None, "ends_at": None}
    has_blocked = any((_schedule(nl, d).get("blocked") or []) for d in DAYS)
    if has_blocked:
        step = timedelta(minutes=1)
        if result["active"]:
            for i in range(1, horizon):
                t = base + i * step
                if not _blocked_at(nl, t):
                    result["ends_at"] = t
                    break
        else:
            for i in range(1, horizon):
                t = base + i * step
                if _blocked_at(nl, t):
                    result["starts_at"] = t
                    for j in range(i + 1, i + horizon):
                        u = base + j * step
                        if not _blocked_at(nl, u):
                            result["ends_at"] = u
                            break
                    break
    _lock_memo.update(key=key, value=result)
    return result


# ------------------------------------------------------------------ text
def fmt_dur(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def _iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


# ------------------------------------------------------------------ summary
def summarize(batch):
    """Turn the dashboard batch payload into the widget summary."""
    now = datetime.now()
    server = batch.get("server") or {}
    live = server.get("primary_api") == "online"
    date = server.get("server_date") or now.strftime("%Y-%m-%d")
    day = DAYS[datetime.strptime(date, "%Y-%m-%d").weekday()]
    limits = batch.get("limits") or {}
    exceptions = batch.get("today_exceptions") or {}
    usage = batch.get("today_usage") or {}
    _note_usage(date, usage, live)

    def entry(name):
        lim = compute_limit(name, day, limits, exceptions)
        used = int(usage.get(name, 0) or 0)
        remaining = None if lim["unlimited"] else max(0, lim["effective"] - used)
        return {
            "name": name,
            "limit": None if lim["unlimited"] else lim["effective"],
            "base_limit": lim["configured"],
            "used": used,
            "remaining": remaining,
            "unlimited": lim["unlimited"],
            "exception_added": lim["added"],
            "exception_set_to": lim["set_to"],
            "running": _running(name, live),
        }

    overall = entry("OVERALL")
    lock = lockdown_info(batch.get("night_lockdown"), now)
    pc_remaining, pc_reason = overall["remaining"], (None if overall["unlimited"] else "limit")
    if lock["active"]:
        pc_remaining, pc_reason = 0, "lockdown-active"
    elif lock["starts_at"]:
        until_lock = int((lock["starts_at"] - now).total_seconds())
        if pc_remaining is None or until_lock < pc_remaining:
            pc_remaining, pc_reason = max(0, until_lock), "lockdown"

    apps = []
    for name in sorted((n for n in limits if n != "OVERALL"), key=str.lower):
        a = entry(name)
        own = a["remaining"]
        a["effective_remaining"] = own if pc_remaining is None else (pc_remaining if own is None else min(own, pc_remaining))
        apps.append(a)

    queue = batch.get("queue") or []
    if pc_reason == "lockdown-active":
        status = "Locked (night lockdown)"
    elif pc_remaining is None:
        status = "No limit today"
    elif pc_remaining <= 0:
        status = "Time is up"
    else:
        status = f"{fmt_dur(pc_remaining)} left"

    return {
        "generated_at": _iso(now),
        "date": date,
        "day": day,
        "online": live,
        "last_seen": server.get("last_synced") if not live else _iso(now),
        "overall": overall,
        "pc_remaining": pc_remaining,
        "pc_reason": pc_reason,
        "lockdown": {
            "enabled": lock["enabled"],
            "active": lock["active"],
            "starts_at": _iso(lock["starts_at"]),
            "ends_at": _iso(lock["ends_at"]),
            "starts_in": int((lock["starts_at"] - now).total_seconds()) if lock["starts_at"] else None,
        },
        "apps": apps,
        "pending_changes": len(queue),
        # Flat, pre-formatted fields for dashboards that just print values (Homepage customapi)
        "status_text": status,
        "online_text": "Online" if live else "Offline",
        "remaining_text": "No limit" if pc_remaining is None else fmt_dur(pc_remaining),
        "used_text": fmt_dur(overall["used"]),
        "limit_text": "No limit" if overall["unlimited"] else fmt_dur(overall["limit"]),
        "lockdown_text": (
            "Active" if lock["active"] else
            (lock["starts_at"].strftime("%H:%M") if lock["starts_at"] else "Off")
        ),
    }
