# Parental Controls V2

A comprehensive Windows-based parental control system that monitors application usage, enforces time limits, and provides exception management with remote dashboard configuration and offline-capable server synchronization.

## 🌟 Features

### Core Functionality
- ⏱️ **Time Limit Enforcement** - Set daily usage limits per application with per-day granularity
- 📊 **Usage Tracking** - Real-time monitoring of application usage with comprehensive statistics
- 🛡️ **Exception Management** - Grant temporary exceptions to bypass time limits for specific dates
- 🔔 **Smart Notifications** - Toast notifications at configurable intervals (30s, 60s, 2m, 5m before limit reached), fully optional: if the toast backend is missing, broken or hangs, monitoring and enforcement keep running
- 🎯 **Selective Monitoring** - Choose which applications to monitor and control
- 🌙 **Night Lockdown** - Automatically shut the computer down during parent-defined blocked time zones, with optional whitelisted exceptions, configurable the same for every day or per day of the week

### Architecture
- 🌐 **Distributed System** - Client-side engine with server-side dashboard integration
- 📡 **REST API** - Well-documented endpoints for all operations
- 💾 **Offline Resilience** - Secondary server queues requests when primary API is unavailable
- 🔄 **Auto-Sync** - Automatic synchronization when connectivity is restored
- 📱 **Web Dashboard** - Browser-based management interface for remote configuration

## 📁 Project Structure

```
ParentalControlsV2/
├── clientside/              # Local monitoring and API server
│   ├── client_engine.py     # Main application monitor and enforcer
│   ├── night_lockdown.py    # Night lockdown enforcer (shuts down in blocked zones)
│   ├── client_master.py     # Launches api, engine and night lockdown together
│   ├── api.py               # Configuration REST API (PORT 5000, needs PRIMARY_API_TOKEN)
│   ├── .env.example          # Copy to .env and set PRIMARY_API_TOKEN
│   ├── requirements.txt      # Python dependencies
│   ├── timelimit.json        # Application time limits (per day)
│   ├── timeusage.json        # Current usage statistics
│   ├── exceptionaltime.json  # Exception dates/apps
│   ├── nightlockdown.json    # Night lockdown blocked/whitelisted zones
│   └── used_exceptions.json  # Tracking of used exceptions
│
├── serverside/              # Central dashboard and proxy
│   ├── secondary_api.py     # Buffering proxy API (PORT 5035)
│   ├── auth.py               # Password sign-in, sessions, security headers
│   ├── login.html            # Sign-in page
│   ├── widget.html           # Embeddable widget for homelab dashboards (/widget)
│   ├── widget.py             # Read-only summary behind /api/widget/data
│   ├── .env.example          # Copy to .env and set DASHBOARD_PASSWORD + PRIMARY_API_TOKEN
│   ├── dashboard.html        # Web dashboard UI
│   ├── requirements.txt       # Python dependencies
│   └── request_queue.db      # SQLite queue for offline requests
│
└── README.md                # This file
```

## 🚀 Quick Start

### Prerequisites
- Windows 10/11
- Python 3.8+
- Admin privileges for enforcing application limits

### Installation

#### 1. Clientside Setup
```bash
# Navigate to clientside directory
cd clientside

# Create virtual environment
python -m venv env

# Activate virtual environment
env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env and set PRIMARY_API_TOKEN (required, see "Primary API token" below)
copy .env.example .env      # cp on Linux/macOS
```

#### 2. Serverside Setup
```bash
# Navigate to serverside directory
cd serverside

# Create virtual environment
python -m venv env

# Activate virtual environment
env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the System

#### Step 1: Start Clientside API Server
```bash
cd clientside
env\Scripts\activate
python api.py
```
The primary API will start on `http://localhost:5000`. It refuses to start until
`PRIMARY_API_TOKEN` is set in `clientside/.env` (see Step 4).

#### Step 2: Start Clientside Monitoring Engine
In a new terminal:
```bash
cd clientside
env\Scripts\activate
python client_engine.py
```

#### Step 2b: Start the Night Lockdown Engine
In a new terminal:
```bash
cd clientside
env\Scripts\activate
python night_lockdown.py
```
> Tip: `python client_master.py` launches the API, the monitoring engine and the
> night lockdown engine together in a single command.

#### Step 3: Start Serverside Proxy Server (Optional but Recommended)
In another terminal:
```bash
cd serverside
env\Scripts\activate
python secondary_api.py
```
The secondary API will start on `http://localhost:5001`

#### Step 4: Set the dashboard password
```bash
cd serverside
copy .env.example .env      # cp on Linux/macOS
```
Edit `serverside/.env` and set `DASHBOARD_PASSWORD` to a long passphrase. To keep only a hash on disk instead,
run `python auth.py --hash` and paste the printed `DASHBOARD_PASSWORD_HASH=...` line in place of `DASHBOARD_PASSWORD`.
The server refuses to start without one of them.

**Primary API token.** Generate a random token and put the *same* value in both
`clientside/.env` (kid's PC) and `serverside/.env`:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
```env
PRIMARY_API_TOKEN=the-printed-value
```
The primary API answers `401 Unauthorized` to any `/api/*` request without
`Authorization: Bearer <PRIMARY_API_TOKEN>`, so only the secondary API can read or change
the configuration. If the two values don't match, the secondary API logs
`Primary API rejected the token` and shows the primary as offline (changes are queued).

#### Step 5: Access Dashboard
1. Open `http://YOUR_SERVER:5035/` and sign in with the password. Your browser (e.g. Google Password Manager) offers to save it, and fills it in next time.
2. Configure time limits, exceptions, and monitor usage

**Sign-in & security**
- Password only, no username. It is compared in constant time (or checked against the scrypt hash).
- Sessions are random tokens stored server-side (only their SHA-256), in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` over HTTPS); they last `SESSION_DAYS` (default 30). **Sign out** in Settings ends the session on the server and can wipe the browser buffer.
- After 5 wrong passwords from one address, sign-in is locked for 30 s, doubling with each further miss (max 15 min).
- Every write must come from the dashboard's own origin (CSRF protection), there are no CORS headers, and pages send a strict Content-Security-Policy, `X-Frame-Options: DENY` and `no-store` caching.
- Scripts can call the API with `Authorization: Bearer <DASHBOARD_API_TOKEN>` if you set that variable.
- The dashboard must now be opened through the server; opening `dashboard.html` as a local file no longer works.
- On the open internet, put the server behind HTTPS (e.g. Caddy or nginx) and set `TRUST_PROXY=true` and `COOKIE_SECURE=true`.

**Dashboard highlights**
- **Overview** with a live countdown of the computer time left today. It takes the overall limit, every exception (add / remove / set exact) and the next night lockdown into account, and shows the time left per app (capped by the computer's own time left).
- One-click **+15m / +30m / +1h** exceptions, plus a dialog that previews the new limit before you apply it.
- Toast notifications and confirmation dialogs for every change; queued changes (made while the kid's PC is off) are marked and can be cancelled.
- **Browser buffer**: the latest data and periodic usage samples (interval configurable under Settings) are kept in the browser's localStorage. When the kid's PC is off the dashboard shows the server's cached data with a "last seen" time; if the server itself is unreachable it falls back to the browser buffer. The page also paints instantly from the buffer on load.
- **Phone-friendly**: bottom navigation bar, dialogs open as bottom sheets (swipe down to close), tables turn into cards, large touch targets, no zoom-on-focus on iOS, safe-area support for notched phones, pull down to refresh, swipe toasts away, and the back button closes dialogs and steps back through tabs. Add it to your home screen for a full-screen app feel.
- **Light / dark switch** in the header (or press `T`). The choice is saved in a cookie (`pcv2_theme`, kept for a year) and applied before the page draws, so there is no flash. Settings → Theme can also set it back to "Match system".
- **English / Turkish switch** in the header (and on the sign-in page): one click for Turkish, one more for English (or press `L`). The choice is saved in the `pcv2_lang` cookie for a year; the first visit follows the browser's language. Durations, dates and the sign-in error messages switch too.
- One batched request per refresh (`GET /api/dashboard/data`, which now also returns today's usage and the pending queue), request timeouts, and polling that pauses while the tab is hidden.

## 🧩 Homelab Dashboard Widget (Homepage)

`http://YOUR_SERVER:5035/widget` is a small page made to live inside an iframe, e.g. a
[Homepage](https://gethomepage.dev) `iframe` widget. It fills whatever size it is given —
a one-line strip, a small tile, or a wide two-column card with per-app bars — and refreshes
its own numbers (no flashing reloads). Time left counts down live and accounts for
exceptions and the next night lockdown, exactly like the dashboard.

**Add exception** (and the `+` next to each app) opens the dashboard with the exception
dialog already filled in. The widget itself never changes anything, so another site framing
it can't trick anyone into granting time.

```yaml
# services.yaml
- Family:
    - Parental Controls:
        icon: mdi-shield-account
        href: https://pcv2.example.com/
        widget:
          type: iframe
          name: pcv2
          src: https://pcv2.example.com/widget?theme=dark&hide=title
          classes: h-56            # any height works — the layout adapts
          allowScrolling: no
```

**Signing in inside the frame.** If Homepage and PCV2 are on the same site (e.g.
`home.example.com` + `pcv2.example.com`, or the same IP on different ports), the widget uses
your normal dashboard sign-in. Otherwise set `WIDGET_TOKEN` in `serverside/.env` and add it to
the URL: `/widget?theme=dark&key=<WIDGET_TOKEN>`. That token is read-only — it only unlocks the
widget's data, never the dashboard or any change. (If Authelia sits in front, allow `/widget`
and `/api/widget/data` through it or share its session cookie as usual.)

**Options** (URL parameters, all optional):

| Option | Values | |
|---|---|---|
| `theme` | `auto` · `dark` · `light` | colours (use `dark` for Homepage's dark themes) |
| `bg` | `transparent` · `card` | blend into the host card (default) or draw its own |
| `scheme` | `dark` · `light` | only if the frame shows a solid black/white box |
| `accent` | hex, e.g. `f59e0b` | accent colour |
| `view` | `auto` · `mini` · `compact` · `full` | force a layout instead of choosing by size |
| `apps` | `chrome.exe,discord.exe` · `none` | which app rows to show |
| `max` | number | max app rows (default 8) |
| `hide` | `title,header,ring,bar,button,apps,footer` | hide parts (`title` keeps the online dot — use it when the Homepage card already shows a name) |
| `title` | text | header text |
| `lang` | `en` · `tr` | language (default: your dashboard choice) |
| `refresh` | seconds (≥10) | update interval (default 30) |
| `open` | `tab` · `top` | open the dashboard in a new tab (default) or the whole window |
| `scale` | `0.7`–`1.6` | text size |

Only `/widget` may be framed; restrict who can frame it with `WIDGET_FRAME_ANCESTORS`.

**Native Homepage widget instead of an iframe:** `GET /api/widget/data` returns ready-made text
fields, so Homepage's `customapi` widget can show them directly:

```yaml
        widget:
          type: customapi
          url: https://pcv2.example.com/api/widget/data
          refreshInterval: 30000
          headers:
            X-Widget-Key: your-widget-token
          mappings:
            - field: { data: remaining_text }
              label: Time left
            - field: { data: used_text }
              label: Used today
            - field: { data: lockdown_text }
              label: Lockdown
            - field: { data: online_text }
              label: PC
```

The dashboard also accepts deep links: `/?action=exception&app=chrome.exe&secs=900` opens the
exception dialog prefilled (it still has to be confirmed), and `?lang=tr` / `?lang=en` (on the
dashboard or `/login`) switches the language and remembers it. The widget's buttons pass its own
language along, so the dashboard opens in the same language.

## 📚 API Documentation

### Clientside API (Port 5000)

Every request needs `Authorization: Bearer <PRIMARY_API_TOKEN>`; otherwise the API returns
`401`. Normally only the secondary API calls it. See `clientside/API_USAGE_EXAMPLES.md`.

#### Time Limits
```bash
# Get all time limits
GET /api/limits

# Get limit for specific app
GET /api/limits/{app_name}

# Create new app limit
POST /api/limits
{
  "app_name": "chrome.exe",
  "limits": {
    "Monday": 3600,
    "Tuesday": 3600,
    ...
  }
}

# Update limits for an app
PUT /api/limits/{app_name}
{
  "limits": { ... }
}

# Delete an app's limits
DELETE /api/limits/{app_name}
```

#### Usage Data
```bash
# Get all usage data
GET /api/usage

# Get usage for specific date/app
GET /api/usage/{date}/{app_name}

# Update usage for date/app
PUT /api/usage/{date}/{app_name}
{
  "usage": 3600
}
```

#### Exceptions
```bash
# Get all exceptions
GET /api/exceptions

# Create exception
POST /api/exceptions
{
  "date": "2026-02-21",
  "app_name": "chrome.exe"
}

# Delete exception
DELETE /api/exceptions/{date}/{app_name}
```

#### Night Lockdown
```bash
# Get night lockdown configuration
GET /api/nightlockdown

# Replace night lockdown configuration
PUT /api/nightlockdown
{
  "enabled": true,
  "per_day": false,
  "all_days": {
    "blocked":   [["22:00", "07:00"]],
    "whitelist": [["23:00", "23:30"]]
  },
  "days": {
    "Monday":  { "blocked": [], "whitelist": [] },
    ...
  }
}
```
When `per_day` is `false`, the `all_days` schedule applies to every day. When
`true`, the matching entry in `days` is used for the current weekday. If the
current time falls inside a **blocked** window and not inside a **whitelisted**
window, the computer is shut down. Time windows may cross midnight
(e.g. `["22:00", "07:00"]`).

#### Configuration
```bash
# Get config
GET /api/config

# Update config
POST /api/config
{
  "check_interval": 5,
  "notification_times": [30, 60, 120, 300]
}
```

### Serverside Secondary API (Port 5001)

Acts as a buffering proxy between the dashboard and primary API. All endpoints mirror the primary API URLs but are hosted on the secondary server.

**Key Features:**
- Forwards all requests to primary API when available
- Automatically queues requests if primary API is unreachable
- Periodically syncs queued requests when primary API comes back online
- Provides queue status endpoints for monitoring

Response when primary is offline:
```json
{
  "status": "queued",
  "message": "Primary API unavailable. Request queued for later processing.",
  "primary_status": "offline"
}
```

For detailed secondary API documentation, see [serverside/SECONDARY_API_DOCS.md](serverside/SECONDARY_API_DOCS.md)

## 🔧 Configuration

### Time Limits Format (timelimit.json)
```json
{
  "chrome.exe": {
    "Monday": 3600,
    "Tuesday": 3600,
    "Wednesday": 3600,
    "Thursday": 3600,
    "Friday": 3600,
    "Saturday": 7200,
    "Sunday": 7200
  },
  "discord.exe": {
    ...
  }
}
```
Times are in seconds. Set to `0` to disable an app entirely for that day
(0 seconds allowed). Leaving a day **unset** (missing key or `null`) means
"not configured" — the app/`OVERALL` is treated as effectively unlimited for
that day (86399s) and is **not** restricted. This applies to `OVERALL` too, so
an empty `timelimit.json` (`{}`) no longer shuts the computer down; it simply
enforces nothing until you configure a limit.

### Usage Tracking Format (timeusage.json)
```json
{
  "2026-02-21": {
    "chrome.exe": 3600,
    "discord.exe": 1800,
    ...
  }
}
```

### Night Lockdown Format (nightlockdown.json)
```json
{
  "enabled": true,
  "per_day": false,
  "all_days": {
    "blocked":   [["22:00", "07:00"]],
    "whitelist": [["23:00", "23:30"]]
  },
  "days": {
    "Monday":    { "blocked": [["21:00", "07:00"]], "whitelist": [] },
    "Tuesday":   { "blocked": [], "whitelist": [] },
    "Wednesday": { "blocked": [], "whitelist": [] },
    "Thursday":  { "blocked": [], "whitelist": [] },
    "Friday":    { "blocked": [], "whitelist": [] },
    "Saturday":  { "blocked": [], "whitelist": [] },
    "Sunday":    { "blocked": [], "whitelist": [] }
  }
}
```
Each window is a `["HH:MM", "HH:MM"]` (24-hour) pair and may wrap past midnight.
The night lockdown engine performs a 3-minute security sleep on startup before
it begins enforcing, and re-reads this file on every check so dashboard changes
take effect without a restart.

### Exceptions Format (exceptionaltime.json)
```json
{
  "2026-02-21": {
    "chrome.exe": true,
    "gaming.exe": true
  }
}
```

## 🔐 Security & Privacy

- All data stored locally in JSON files (clientside)
- Secondary server queues use encrypted SQLite database
- No personal data transmitted unless explicitly configured
- Optional Home Assistant integration for smart home control
- The primary API (kid's PC) only accepts requests carrying the shared `PRIMARY_API_TOKEN`,
  sends no CORS headers (web pages can't call it) and never runs in Flask debug mode
- The dashboard and secondary API require the dashboard password

### Protecting the clientside folder

The token stops anyone from changing settings **through the API**, but the engines read
`timelimit.json`, `exceptionaltime.json`, `nightlockdown.json` and `timeusage.json`
straight from disk. If the kid can write to the `clientside` folder they can still edit
those files, delete them, read the token from `clientside/.env`, or stop the engines.
To close that gap:

1. Give the kid a **standard (non-administrator)** Windows account.
2. Install `clientside` in a folder the kid can't write to, e.g. `C:\ProgramData\PCV2`, and
   remove write access for their account (Properties → Security, or
   `icacls C:\ProgramData\PCV2 /inheritance:r /grant:r Administrators:(OI)(CI)F SYSTEM:(OI)(CI)F`
   and, only if the toast notifications need it, `/grant:r Users:(OI)(CI)RX`). Do **not**
   give the kid read access to `.env`.
3. Run `client_master.py` from a **Scheduled Task** owned by an admin account or
   `SYSTEM` ("Run whether user is logged on or not", restart on failure), with
   "Start in" set to that folder, so the kid can't kill it or replace the scripts.
4. If the secondary API runs on the same PC, set `PRIMARY_API_HOST=127.0.0.1`. Otherwise
   allow port 5000 in the firewall only from the server's address.

## 📝 Environment Variables

Create `clientside/.env` from `clientside/.env.example`:

```env
# Shared secret with the secondary API (required, same value in serverside/.env)
PRIMARY_API_TOKEN=long-random-token

# Listen address / port of the primary API (defaults shown)
# PRIMARY_API_HOST=0.0.0.0
# PRIMARY_API_PORT=5000

# Run without the token (NOT recommended)
# PRIMARY_API_AUTH_DISABLED=false

# Home Assistant Integration (optional)
HASS_URL=http://your-home-assistant:8123
HASS_TOKEN=your_long_lived_access_token
```

## 🛠️ Development

### Adding Custom Monitoring

To monitor additional applications, edit `client_engine.py` or use the API to dynamically add limits:

```python
# Example: Monitor VLC media player
POST /api/limits
{
  "app_name": "vlc.exe",
  "limits": {
    "Monday": 1800,
    ...
  }
}
```

### Customizing Notifications

Modify notification times in `client_engine.py`:
```python
USAGE_NOTIFIERS = [30, 60, 120, 300]  # seconds before limit
```

All toasts go through `notifier.safe_toast()` in `clientside/notifier.py`, which
never raises and never blocks the monitoring loop:

- If `win11toast` is not installed or cannot be imported (e.g. non-Windows), the
  engines log a single warning and run without notifications.
- Each toast is dispatched on a daemon thread, so a hanging Windows notification
  stack cannot freeze time tracking or enforcement.
- After 5 consecutive failures notifications are disabled for the rest of the
  run instead of being retried on every check (`MAX_CONSECUTIVE_FAILURES`).

```python
MAX_CONSECUTIVE_FAILURES = 5  # failures before toasts are given up on
MAX_OUTSTANDING = 3           # pending toasts before the backend is deemed stuck
```

## 🐛 Troubleshooting

### Primary API Not Starting
- Ensure port 5000 is not in use: `netstat -ano | findstr :5000`
- `[AUTH] No PRIMARY_API_TOKEN configured`: create `clientside/.env` with `PRIMARY_API_TOKEN=...`
- Check Python path and virtual environment activation
- Run as Administrator if encountering permission issues

### Secondary API Can't Reach Primary
- Verify primary API is running on the configured URL
- `Primary API rejected the token` / probe returns `401`: `PRIMARY_API_TOKEN` differs between
  `clientside/.env` and `serverside/.env` (restart both after changing it)
- With `PRIMARY_API_HOST=127.0.0.1` the primary only accepts connections from its own PC
- Check firewall settings
- Primary API will auto-queue requests until primary comes back online

### Time Limits Not Enforcing
- Ensure `client_engine.py` is running
- Check `timelimit.json` has correct application names (case-sensitive)
- Verify times are in seconds
- Check application names match exactly (e.g., `chrome.exe` not `Chrome`)

### Shutdown Cancelled ("These apps are preventing shutdown")
When the overall limit or night lockdown shuts the PC down, pressing **Cancel**
on the Windows "apps are preventing shutdown" screen no longer turns the
engines off:
- The engines (and `client_master.py`) hold on to Windows' close/shutdown
  console events instead of exiting, keep running, and issue the shutdown
  again on their next check (every 5s for time limits, 15s for night lockdown).
- `client_master.py` restarts any process that stops instead of exiting.
- After an enforced shutdown the engines remember it in `shutdown_pending.json`;
  when they restart (or the PC is turned back on) within 12 hours, the startup
  safety sleep drops to 20 seconds. The limit/schedule and any exceptions are
  still checked first, so granting an exception always lets the PC stay on.
  The marker clears itself once the limit/schedule allows use again.
- Legitimate shutdowns may take a few extra seconds while Windows ends the
  engines.
- For the strongest setup, start `client_master.py` from a Windows Scheduled
  Task (at logon, "restart on failure") so it comes back even if the whole
  console is killed.

### Web Dashboard Not Updating
- Verify correct API URL configured in `dashboard.html`
- Check browser console for CORS or network errors
- Ensure both API servers are running if using secondary proxy

## 📦 Dependencies

### Clientside
- Flask 3.1.3 - Web framework for REST API
- psutil 7.2.1 - System and process utilities
- requests 2.32.5 - HTTP library
- win11toast 0.36.3 - Windows toast notifications (optional; the engines run without it)
- pywin32 311 - Windows API access
- python-dotenv 1.2.1 - Environment variable management

### Serverside
- Flask 3.1.3 - Web framework
- requests 2.32.5 - HTTP client for proxy forwarding

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 👤 Author

Created by Melih

## 🤝 Contributing

Contributions welcome! Please ensure code follows existing patterns and test thoroughly before submitting.

## 📞 Support

For issues, feature requests, or questions:
1. Check the troubleshooting section above
2. Review API documentation in API_USAGE_EXAMPLES.md and SECONDARY_API_DOCS.md
3. Enable debug logging in `secondary_api.py` for verbose output

---

**Last Updated:** February 21, 2026