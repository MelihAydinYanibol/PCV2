# Parental Control Configuration API - Usage Examples

## Setup

Install the dependencies:
```bash
pip install -r requirements.txt
```

Create `clientside/.env` from the example and set a token:
```bash
copy .env.example .env      # cp on Linux/macOS
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Paste the printed value as `PRIMARY_API_TOKEN=...` in `clientside/.env`, and the
same value in `serverside/.env`.

Run the API server:
```bash
python api.py
```

The API will start on `http://localhost:5000` (set `PRIMARY_API_HOST` / `PRIMARY_API_PORT`
to change this). It refuses to start without `PRIMARY_API_TOKEN` unless
`PRIMARY_API_AUTH_DISABLED=true` is set.

## Authentication

Normally only the secondary API (`serverside/secondary_api.py`) talks to this API; the
dashboard goes through it. Every `/api/*` request must carry the shared token:

```
Authorization: Bearer <PRIMARY_API_TOKEN>
```

Requests without it (or with a wrong token) get `401 Unauthorized`. There are no CORS
headers, so web pages can't call this API from a browser.

The `curl` examples below assume the token is in a shell variable:
```bash
export TOKEN=your-primary-api-token          # PowerShell: $env:TOKEN = "..."
```
and add `-H "Authorization: Bearer $TOKEN"` to every request.

---

## Endpoints Overview

### 1. TIME LIMITS MANAGEMENT

#### Get all time limits
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/limits
```

Response:
```json
{
  "status": "success",
  "data": {
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
      "Monday": 1800,
      "Tuesday": 1800,
      ...
    }
  }
}
```

#### Get limit for specific app
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/limits/chrome.exe
```

#### Create new app limit
```bash
curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:5000/api/limits \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "discord.exe",
    "limits": {
      "Monday": 1800,
      "Tuesday": 1800,
      "Wednesday": 1800,
      "Thursday": 1800,
      "Friday": 1800,
      "Saturday": 3600,
      "Sunday": 3600
    }
  }'
```

#### Update all limits for an app
```bash
curl -H "Authorization: Bearer $TOKEN" -X PUT http://localhost:5000/api/limits/chrome.exe \
  -H "Content-Type: application/json" \
  -d '{
    "limits": {
      "Monday": 7200,
      "Tuesday": 7200,
      "Wednesday": 3600,
      "Thursday": 3600,
      "Friday": 3600,
      "Saturday": 10800,
      "Sunday": 10800
    }
  }'
```

#### Update limit for specific day
```bash
curl -H "Authorization: Bearer $TOKEN" -X PUT http://localhost:5000/api/limits/chrome.exe/Monday \
  -H "Content-Type: application/json" \
  -d '{"seconds": 7200}'
```

#### Delete app from limits
```bash
curl -H "Authorization: Bearer $TOKEN" -X DELETE http://localhost:5000/api/limits/discord.exe
```

---

### 2. EXCEPTIONS MANAGEMENT

#### Get all exceptions
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/exceptions
```

#### Get exceptions for a specific date
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/exceptions/2026-01-17
```

#### Get exception for specific app on specific date
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/exceptions/2026-01-17/chrome.exe
```

#### Create/Update an exception (add 30 minutes extra)
```bash
curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:5000/api/exceptions \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-01-17",
    "app_name": "chrome.exe",
    "exception_time": 1800,
    "reason": "Homework research"
  }'
```

#### Create exception with negative time (subtract 30 minutes)
```bash
curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:5000/api/exceptions \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-01-17",
    "app_name": "youtube.exe",
    "exception_time": -1800,
    "reason": "Excessive usage"
  }'
```

#### Set exact limit for a day (override default)
```bash
curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:5000/api/exceptions \
  -H "Content-Type: application/json" \
  -d '{
    "date": "2026-01-17",
    "app_name": "chrome.exe",
    "exception_time": 7200,
    "reason": "Special occasion"
  }'
```

#### Delete exception
```bash
curl -H "Authorization: Bearer $TOKEN" -X DELETE http://localhost:5000/api/exceptions/2026-01-17/chrome.exe
```

---

### 3. NIGHT LOCKDOWN

#### Get night lockdown configuration
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/nightlockdown
```

#### Same schedule for every day
```bash
curl -H "Authorization: Bearer $TOKEN" -X PUT http://localhost:5000/api/nightlockdown \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "per_day": false,
    "all_days": {
      "blocked":   [["22:00", "07:00"]],
      "whitelist": [["23:00", "23:30"]]
    }
  }'
```

#### Different schedule per day of the week
```bash
curl -H "Authorization: Bearer $TOKEN" -X PUT http://localhost:5000/api/nightlockdown \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "per_day": true,
    "days": {
      "Friday":   {"blocked": [["23:59", "08:00"]], "whitelist": []},
      "Saturday": {"blocked": [["23:59", "09:00"]], "whitelist": []},
      "Sunday":   {"blocked": [["21:00", "07:00"]], "whitelist": []}
    }
  }'
```

Windows are `["HH:MM", "HH:MM"]` (24-hour) and may cross midnight. When the
current time is inside a **blocked** window and not inside a **whitelisted**
window, the computer is shut down.

---

### 4. USAGE TRACKING

#### Get all usage data
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/usage
```

#### Get usage for specific date
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/usage/2026-01-17
```

Response:
```json
{
  "status": "success",
  "data": {
    "chrome.exe": 3600,
    "discord.exe": 900,
    "OVERALL": 4500
  }
}
```

#### Get usage for specific app on specific date
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/usage/2026-01-17/chrome.exe
```

Response:
```json
{
  "status": "success",
  "data": 3600
}
```

#### Update usage (useful for corrections)
```bash
curl -H "Authorization: Bearer $TOKEN" -X PUT http://localhost:5000/api/usage/2026-01-17/chrome.exe \
  -H "Content-Type: application/json" \
  -d '{"seconds": 5400}'
```

---

### 5. STATUS & CONFIGURATION

#### Get current system status
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/status
```

Response:
```json
{
  "status": "success",
  "data": {
    "current_date": "2026-01-17",
    "apps_monitored": 5,
    "total_apps_today": 3,
    "exceptions_today": 1
  }
}
```

#### Get full configuration (limits + exceptions)
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5000/api/config
```

#### Upload full configuration
```bash
curl -H "Authorization: Bearer $TOKEN" -X POST http://localhost:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "limits": {
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
        "Monday": 1800,
        "Tuesday": 1800,
        "Wednesday": 1800,
        "Thursday": 1800,
        "Friday": 1800,
        "Saturday": 3600,
        "Sunday": 3600
      }
    },
    "exceptions": {
      "2026-01-17": {
        "chrome.exe": [1800, "Homework"],
        "youtube.exe": [-900, "Over limit"]
      }
    }
  }'
```

---

## Python Examples

### Add a new app to monitor
```python
import os
import requests

HEADERS = {'Authorization': f"Bearer {os.environ['PRIMARY_API_TOKEN']}"}

response = requests.post(
    'http://localhost:5000/api/limits',
    headers=HEADERS,
    json={
        'app_name': 'spotify.exe',
        'limits': {
            'Monday': 1800,
            'Tuesday': 1800,
            'Wednesday': 1800,
            'Thursday': 1800,
            'Friday': 1800,
            'Saturday': 3600,
            'Sunday': 3600
        }
    }
)
print(response.json())
```

### Grant extra time today
```python
import os
import requests

HEADERS = {'Authorization': f"Bearer {os.environ['PRIMARY_API_TOKEN']}"}
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

response = requests.post(
    'http://localhost:5000/api/exceptions',
    headers=HEADERS,
    json={
        'date': today,
        'app_name': 'chrome.exe',
        'exception_time': 1200,
        'reason': 'Special project'
    }
)
print(response.json())
```

### Check today's status
```python
import os
import requests

HEADERS = {'Authorization': f"Bearer {os.environ['PRIMARY_API_TOKEN']}"}
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

# Get today's usage
usage_resp = requests.get(f'http://localhost:5000/api/usage/{today}', headers=HEADERS)
print("Today's usage:", usage_resp.json())

# Get today's exceptions
exc_resp = requests.get(f'http://localhost:5000/api/exceptions/{today}', headers=HEADERS)
print("Today's exceptions:", exc_resp.json())
```

---

## HTTP Status Codes

- **200**: Successful GET or PUT request
- **201**: Successful POST request (resource created)
- **400**: Bad request (missing or invalid data)
- **401**: Missing or wrong `Authorization: Bearer <PRIMARY_API_TOKEN>` header
- **404**: Resource not found
- **409**: Conflict (e.g., app already exists)
- **500**: Internal server error

---

## Notes

- All time values are in **seconds**
- Dates must be in **YYYY-MM-DD** format
- Days must be one of: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday
- Negative exception times reduce the available time
- Positive exception times add to the available time
