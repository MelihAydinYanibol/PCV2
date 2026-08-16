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
│   ├── api.py               # Configuration REST API (PORT 5000)
│   ├── requirements.txt      # Python dependencies
│   ├── timelimit.json        # Application time limits (per day)
│   ├── timeusage.json        # Current usage statistics
│   ├── exceptionaltime.json  # Exception dates/apps
│   ├── nightlockdown.json    # Night lockdown blocked/whitelisted zones
│   └── used_exceptions.json  # Tracking of used exceptions
│
├── serverside/              # Central dashboard and proxy
│   ├── secondary_api.py     # Buffering proxy API (PORT 5001)
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

# Create .env file (for Home Assistant integration - optional)
echo HASS_URL=http://your-hass-instance:8123 > .env
echo HASS_TOKEN=your-token >> .env
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
The primary API will start on `http://localhost:5000`

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

#### Step 4: Access Dashboard
1. If using serverside: Open `serverside/dashboard.html` in a browser
2. Update the API URL in the dashboard HTML to match your server (default: `http://127.0.0.1:5001/api`)
3. Configure time limits, exceptions, and monitor usage

## 📚 API Documentation

### Clientside API (Port 5000)

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
- CORS enabled for cross-origin requests

## 📝 Environment Variables

Create a `.env` file in the clientside directory (optional):

```env
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
- Check Python path and virtual environment activation
- Run as Administrator if encountering permission issues

### Secondary API Can't Reach Primary
- Verify primary API is running on the configured URL
- Check firewall settings
- Primary API will auto-queue requests until primary comes back online

### Time Limits Not Enforcing
- Ensure `client_engine.py` is running
- Check `timelimit.json` has correct application names (case-sensitive)
- Verify times are in seconds
- Check application names match exactly (e.g., `chrome.exe` not `Chrome`)

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