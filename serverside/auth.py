"""
Password authentication for the secondary API and web dashboard.

* One shared password, read from ``serverside/.env``:

      DASHBOARD_PASSWORD=some long passphrase
      # or, instead of the plain password, a hash made with
      #   python auth.py --hash
      DASHBOARD_PASSWORD_HASH=scrypt:32768:8:1$...

* The login page is a plain HTML form (POST + redirect), so browsers such as
  Chrome / Google Password Manager offer to save and later autofill it.
* Sessions are random server-side tokens. Only a SHA-256 of each token is
  stored (SQLite), the cookie is HttpOnly + SameSite=Strict (+ Secure over
  HTTPS), and logging out deletes the session on the server.
* Repeated wrong passwords from one address are locked out with a growing
  delay; every state-changing request must come from this same origin.
* Scripts / tools can use ``Authorization: Bearer <DASHBOARD_API_TOKEN>`` when
  that variable is set.
* The embeddable ``/widget`` page is the only page that may be shown inside
  another site's iframe (``WIDGET_FRAME_ANCESTORS``). It contains no data
  itself; its data endpoint needs a sign-in or the read-only ``WIDGET_TOKEN``.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import threading
import time
from urllib.parse import quote, urlparse

from flask import Response, jsonify, redirect, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

COOKIE_NAME = "pcv2_session"
SERVERSIDE_DIR = os.path.dirname(os.path.abspath(__file__))

# Lockout policy: after FREE_ATTEMPTS failures from one address, each further
# failure doubles the wait, starting at BASE_LOCKOUT seconds, up to MAX_LOCKOUT.
FREE_ATTEMPTS = 5
BASE_LOCKOUT = 30
MAX_LOCKOUT = 15 * 60
FAILURE_MEMORY = 60 * 60  # forget failures after an hour without new ones

# Paths reachable without signing in
PUBLIC_PATHS = {"/login", "/favicon.ico", "/widget"}
# Read-only endpoints the widget token may call
WIDGET_PATHS = {"/api/widget/data"}


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Auth:
    def __init__(self, app, db_path):
        self.app = app
        self.db_path = db_path
        self.disabled = _env_bool("AUTH_DISABLED")
        self.password = os.getenv("DASHBOARD_PASSWORD") or None
        self.password_hash = os.getenv("DASHBOARD_PASSWORD_HASH") or None
        api_token = os.getenv("DASHBOARD_API_TOKEN") or None
        self.api_token_digest = _sha256(api_token) if api_token else None
        widget_token = os.getenv("WIDGET_TOKEN") or None
        self.widget_token_digest = _sha256(widget_token) if widget_token else None
        if widget_token and len(widget_token) < 16:
            print("[AUTH] WARNING: WIDGET_TOKEN is short. Use a long random value.")
        # Who may show /widget in an iframe, e.g. "https://home.example.com http://192.168.1.10:3000"
        self.widget_ancestors = " ".join(
            a for a in (os.getenv("WIDGET_FRAME_ANCESTORS") or "*").replace(",", " ").split()
            if a == "*" or a == "'self'" or a.startswith(("http://", "https://"))
        ) or "'self'"
        self.session_seconds = int(float(os.getenv("SESSION_DAYS", "30")) * 86400)
        self.trust_proxy = _env_bool("TRUST_PROXY")
        self.force_secure_cookie = _env_bool("COOKIE_SECURE")
        self._failures = {}  # ip -> [count, last_failure_ts, locked_until_ts]
        self._lock = threading.Lock()

        if not self.disabled and not (self.password or self.password_hash):
            sys.exit(
                "\n[AUTH] No dashboard password configured.\n"
                "       Add DASHBOARD_PASSWORD=... (or DASHBOARD_PASSWORD_HASH=...) to serverside/.env\n"
                "       or set AUTH_DISABLED=true to run without sign-in (not recommended).\n"
            )
        if self.password and len(self.password) < 10:
            print("[AUTH] WARNING: DASHBOARD_PASSWORD is shorter than 10 characters. Use a longer passphrase.")
        if self.disabled:
            print("[AUTH] WARNING: authentication is DISABLED (AUTH_DISABLED=true). Anyone on the network can change limits.")

        self._init_db()
        app.before_request(self._guard)
        app.after_request(self._security_headers)
        app.add_url_rule("/login", "login", self._login, methods=["GET", "POST"])
        app.add_url_rule("/logout", "logout", self._logout, methods=["POST"])
        app.add_url_rule("/api/auth/status", "auth_status", self._status, methods=["GET"])

    # ------------------------------------------------------------------ storage
    def _db(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._db()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                ip TEXT,
                user_agent TEXT
            )"""
        )
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (int(time.time()),))
        conn.commit()
        conn.close()

    def _create_session(self):
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn = self._db()
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO auth_sessions (token_hash, created_at, expires_at, last_seen, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
            (_sha256(token), now, now + self.session_seconds, now, self._client_ip(),
             (request.headers.get("User-Agent") or "")[:200]),
        )
        conn.commit()
        conn.close()
        return token

    def _valid_session(self, token):
        if not token or len(token) > 200:
            return False
        now = int(time.time())
        conn = self._db()
        row = conn.execute(
            "SELECT expires_at, last_seen FROM auth_sessions WHERE token_hash = ?", (_sha256(token),)
        ).fetchone()
        if row and row[0] > now:
            if now - row[1] > 300:  # don't write on every poll
                conn.execute("UPDATE auth_sessions SET last_seen = ? WHERE token_hash = ?", (now, _sha256(token)))
                conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def _delete_session(self, token):
        if not token:
            return
        conn = self._db()
        conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_sha256(token),))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------ helpers
    def _client_ip(self):
        if self.trust_proxy:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.remote_addr or "?"

    def _is_https(self):
        if request.is_secure:
            return True
        return self.trust_proxy and request.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _check_password(self, candidate: str) -> bool:
        if not candidate or len(candidate) > 1024:
            return False
        if self.password_hash:
            try:
                return check_password_hash(self.password_hash, candidate)
            except Exception:
                return False
        # Compare fixed-length digests in constant time
        return hmac.compare_digest(_sha256(candidate), _sha256(self.password))

    def _check_bearer(self):
        if not self.api_token_digest:
            return False
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(_sha256(header[7:].strip()), self.api_token_digest)

    def _check_widget_key(self):
        """Read-only widget token, sent as X-Widget-Key header or ?key= (for iframe URLs)."""
        if not self.widget_token_digest:
            return False
        key = request.headers.get("X-Widget-Key") or request.args.get("key") or ""
        return bool(key) and hmac.compare_digest(_sha256(key), self.widget_token_digest)

    def _same_origin(self):
        """Reject cross-site writes (CSRF). Browsers always send Origin on POST/PUT/DELETE."""
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            # Non-browser clients (curl, scripts) don't send it; they still need a valid session or token.
            return True
        if origin == "null":
            return False
        parsed = urlparse(origin)
        host = request.headers.get("X-Forwarded-Host") if self.trust_proxy and request.headers.get("X-Forwarded-Host") else request.host
        return parsed.netloc.lower() == (host or "").lower()

    def _lockout_remaining(self, ip):
        with self._lock:
            entry = self._failures.get(ip)
            if not entry:
                return 0
            if time.time() - entry[1] > FAILURE_MEMORY:
                del self._failures[ip]
                return 0
            return max(0, int(entry[2] - time.time() + 0.999))

    def _record_failure(self, ip):
        with self._lock:
            now = time.time()
            entry = self._failures.get(ip)
            if not entry or now - entry[1] > FAILURE_MEMORY:
                entry = [0, now, 0]
            entry[0] += 1
            entry[1] = now
            if entry[0] >= FREE_ATTEMPTS:
                wait = min(MAX_LOCKOUT, BASE_LOCKOUT * (2 ** (entry[0] - FREE_ATTEMPTS)))
                entry[2] = now + wait
            self._failures[ip] = entry
            print(f"[AUTH] Failed sign-in from {ip} (attempt {entry[0]})")
            # Keep the table bounded
            if len(self._failures) > 10000:
                for key in sorted(self._failures, key=lambda k: self._failures[k][1])[:5000]:
                    del self._failures[key]

    def _clear_failures(self, ip):
        with self._lock:
            self._failures.pop(ip, None)

    def _safe_next(self, value):
        """Only allow redirects to local paths (no open redirect)."""
        if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
            return "/"
        return value

    def _set_cookie(self, response, token, max_age):
        response.set_cookie(
            COOKIE_NAME, token, max_age=max_age, httponly=True, samesite="Strict",
            secure=self.force_secure_cookie or self._is_https(), path="/",
        )

    def authenticated(self):
        if self.disabled:
            return True
        if self._check_bearer():
            return True
        return self._valid_session(request.cookies.get(COOKIE_NAME))

    # ------------------------------------------------------------------ hooks
    def _guard(self):
        path = request.path
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and not self._same_origin():
            return jsonify({"status": "error", "message": "Cross-site request blocked"}), 403
        if path in PUBLIC_PATHS:
            return None
        if self.authenticated():
            return None
        if path in WIDGET_PATHS and request.method == "GET" and self._check_widget_key():
            return None
        if path.startswith("/api/"):
            return jsonify({"status": "error", "message": "Sign-in required", "auth": "required"}), 401
        # Keep the query string (e.g. /?action=exception&app=...) across the sign-in
        target = request.full_path.rstrip("?") if request.method == "GET" else "/"
        return redirect("/login?next=" + quote(target, safe="/"), code=303)

    def _security_headers(self, response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        framable = request.path == "/widget"
        if not framable:
            response.headers["X-Frame-Options"] = "DENY"
        # same-origin (not no-referrer): no-referrer makes browsers send "Origin: null" on form posts
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if response.mimetype == "text/html":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
                f"frame-ancestors {self.widget_ancestors if framable else chr(39) + 'none' + chr(39)}; "
                "base-uri 'none'; object-src 'none'"
            )
        if request.path.startswith("/api/") or request.path in ("/login", "/logout", "/", "/dashboard", "/widget"):
            response.headers["Cache-Control"] = "no-store"
        if self._is_https():
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    # ------------------------------------------------------------------ views
    def _lang(self):
        """Language chosen with the dashboard's TR/EN button (pcv2_lang cookie)."""
        return "tr" if request.cookies.get("pcv2_lang") == "tr" else "en"

    def _login_page(self, error="", status=200):
        with open(os.path.join(SERVERSIDE_DIR, "login.html"), "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{ERROR}}", error).replace("{{ERROR_CLASS}}", "show" if error else "")
        return Response(html, status=status, mimetype="text/html")

    def _login(self):
        if self.disabled:
            return redirect("/", code=303)
        if request.method == "GET":
            if self.authenticated():
                return redirect(self._safe_next(request.args.get("next")), code=303)
            return self._login_page()

        ip = self._client_ip()
        wait = self._lockout_remaining(ip)
        if wait:
            minutes, seconds = divmod(wait, 60)
            if self._lang() == "tr":
                left = f"{minutes} dk {seconds:02d} sn" if minutes else f"{seconds} sn"
                msg = f"Çok fazla yanlış deneme. {left} sonra tekrar deneyin."
            else:
                left = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
                msg = f"Too many wrong attempts. Try again in {left}."
            return self._login_page(msg, 429)

        if not self._check_password(request.form.get("password", "")):
            self._record_failure(ip)
            return self._login_page("Yanlış şifre." if self._lang() == "tr" else "Wrong password.", 401)

        self._clear_failures(ip)
        token = self._create_session()
        print(f"[AUTH] Signed in from {ip}")
        response = redirect(self._safe_next(request.args.get("next") or request.form.get("next")), code=303)
        self._set_cookie(response, token, self.session_seconds)
        return response

    def _logout(self):
        self._delete_session(request.cookies.get(COOKIE_NAME))
        response = redirect("/login", code=303)
        self._set_cookie(response, "", 0)
        return response

    def _status(self):
        return jsonify({"status": "success", "data": {"authenticated": True, "auth_disabled": self.disabled}}), 200


def init_auth(app, db_path):
    return Auth(app, db_path)


if __name__ == "__main__":
    # Helper: python auth.py --hash  -> prints a DASHBOARD_PASSWORD_HASH line for .env
    if "--hash" in sys.argv:
        import getpass
        first = getpass.getpass("New dashboard password: ")
        if first != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
        if len(first) < 10:
            print("Warning: shorter than 10 characters.")
        print("\nAdd this line to serverside/.env (and remove DASHBOARD_PASSWORD):\n")
        print(f"DASHBOARD_PASSWORD_HASH='{generate_password_hash(first)}'")
    else:
        print("Usage: python auth.py --hash")
