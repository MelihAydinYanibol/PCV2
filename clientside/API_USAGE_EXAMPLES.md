# Parental Control Configuration API - Usage Examples

## Setup

Install Flask:
```bash
pip install flask
```

Run the API server:
```bash
python api.py
```

The API will start on `http://localhost:5000`

---

## Endpoints Overview

### 1. TIME LIMITS MANAGEMENT

#### Get all time limits
```bash
curl http://localhost:5000/api/limits
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
curl http://localhost:5000/api/limits/chrome.exe
```

#### Create new app limit
```bash
curl -X POST http://localhost:5000/api/limits \
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
curl -X PUT http://localhost:5000/api/limits/chrome.exe \
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
curl -X PUT http://localhost:5000/api/limits/chrome.exe/Monday \
  -H "Content-Type: application/json" \
  -d '{"seconds": 7200}'
```

#### Delete app from limits
```bash
curl -X DELETE http://localhost:5000/api/limits/discord.exe
```

---

### 2. EXCEPTIONS MANAGEMENT

#### Get all exceptions
```bash
curl http://localhost:5000/api/exceptions
```

#### Get exceptions for a specific date
```bash
curl http://localhost:5000/api/exceptions/2026-01-17
```

#### Get exception for specific app on specific date
```bash
curl http://localhost:5000/api/exceptions/2026-01-17/chrome.exe
```

#### Create/Update an exception (add 30 minutes extra)
```bash
curl -X POST http://localhost:5000/api/exceptions \
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
curl -X POST http://localhost:5000/api/exceptions \
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
curl -X POST http://localhost:5000/api/exceptions \
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
curl -X DELETE http://localhost:5000/api/exceptions/2026-01-17/chrome.exe
```

---

### 3. NIGHT LOCKDOWN

#### Get night lockdown configuration
```bash
curl http://localhost:5000/api/nightlockdown
```

#### Same schedule for every day
```bash
curl -X PUT http://localhost:5000/api/nightlockdown \
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
curl -X PUT http://localhost:5000/api/nightlockdown \
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
curl http://localhost:5000/api/usage
```

#### Get usage for specific date
```bash
curl http://localhost:5000/api/usage/2026-01-17
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
curl http://localhost:5000/api/usage/2026-01-17/chrome.exe
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
curl -X PUT http://localhost:5000/api/usage/2026-01-17/chrome.exe \
  -H "Content-Type: application/json" \
  -d '{"seconds": 5400}'
```

---

### 5. STATUS & CONFIGURATION

#### Get current system status
```bash
curl http://localhost:5000/api/status
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
curl http://localhost:5000/api/config
```

#### Upload full configuration
```bash
curl -X POST http://localhost:5000/api/config \
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
import requests

response = requests.post(
    'http://localhost:5000/api/limits',
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
import requests
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

response = requests.post(
    'http://localhost:5000/api/exceptions',
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
import requests
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

# Get today's usage
usage_resp = requests.get(f'http://localhost:5000/api/usage/{today}')
print("Today's usage:", usage_resp.json())

# Get today's exceptions
exc_resp = requests.get(f'http://localhost:5000/api/exceptions/{today}')
print("Today's exceptions:", exc_resp.json())
```

---

## HTTP Status Codes

- **200**: Successful GET or PUT request
- **201**: Successful POST request (resource created)
- **400**: Bad request (missing or invalid data)
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
