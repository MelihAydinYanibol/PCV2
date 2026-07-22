# Secondary Server API - Documentation

## Overview

The Secondary Server API acts as a **buffering proxy** between the client and the primary API. It:

- ✅ Receives all requests from the web dashboard
- ✅ Forwards requests to the primary API (client-side)
- ✅ If primary API is down, automatically **queues** requests to SQLite
- ✅ Periodically syncs queued requests when primary API comes back online
- ✅ Provides status and queue management endpoints

## Architecture

```
[Dashboard] → [Secondary API (Server)] → [Primary API (Client)]
                       ↓
                   [SQLite Queue]
                   (if offline)
```

## Setup

### Installation

Install Flask and requests:
```bash
pip install flask requests
```

### Run the Server

```bash
python secondary_api.py
```

The secondary API will start on `http://YOUR_SERVER_IP:5001`

### Update Dashboard

Change the API URL in `dashboard.html`:

**Before:**
```javascript
const API_URL = 'http://127.0.0.1:5000/api';
```

**After:**
```javascript
const API_URL = 'http://YOUR_SERVER_IP:5001/api';
```

## How It Works

### Scenario 1: Primary API Online (Normal Operation)
```
User Action → Secondary API (receives) → Forwards to Primary API → Returns response
```

### Scenario 2: Primary API Offline (Buffering)
```
User Action → Secondary API (receives) → Can't reach Primary → Queues request
            → Returns: "status": "queued"
            
[Time passes, Primary API comes back online]
            
Background Worker → Checks Primary Status → Syncs all queued requests
                  → Primary API processes them → Queue cleared
```

## Endpoints

### Standard API Endpoints (Proxy)

All endpoints from the primary API are available through the secondary API:

```
GET    /api/limits
POST   /api/limits
GET    /api/limits/<app>
PUT    /api/limits/<app>
DELETE /api/limits/<app>

GET    /api/exceptions
POST   /api/exceptions
DELETE /api/exceptions/<date>/<app>

GET    /api/usage
PUT    /api/usage/<date>/<app>

GET    /api/nightlockdown
PUT    /api/nightlockdown

GET    /api/config
POST   /api/config
```

**Response when Primary is Offline (Write Operations):**
```json
{
  "status": "queued",
  "message": "Primary API unavailable. Request queued for later processing.",
  "primary_status": "offline"
}
```

### Server Management Endpoints

#### Get Server & Primary Status
```bash
GET /api/server/status
```

Response:
```json
{
  "status": "success",
  "data": {
    "server_status": "online",
    "primary_api": "online",
    "queue": {
      "pending": 0,
      "synced": 5,
      "failed": 0
    },
    "timestamp": "2026-01-17T21:30:00.123456"
  }
}
```

#### Get Request Queue
```bash
GET /api/server/queue
```

Response:
```json
{
  "status": "success",
  "data": {
    "count": 2,
    "items": [
      {
        "id": 1,
        "method": "POST",
        "endpoint": "/limits",
        "data": {
          "app_name": "chrome.exe",
          "limits": {...}
        }
      },
      {
        "id": 2,
        "method": "PUT",
        "endpoint": "/exceptions/2026-01-17/discord.exe",
        "data": {...}
      }
    ]
  }
}
```

#### Manually Trigger Sync
```bash
POST /api/server/sync
```

Response:
```json
{
  "status": "success",
  "data": {
    "synced": 2,
    "failed": 0
  }
}
```

#### Clear Queue
```bash
POST /api/server/queue/clear
```

⚠️ **Warning**: This deletes all queued requests!

## Configuration

Edit these settings in `secondary_api.py`:

```python
PRIMARY_API_URL = 'http://127.0.0.1:5000/api'  # Primary API location
QUEUE_DB = 'request_queue.db'                   # SQLite database file
SYNC_INTERVAL = 5                               # Check every 5 seconds
REQUEST_TIMEOUT = 2                             # Timeout for requests
```

## Examples

### Using cURL

```bash
# Check if primary API is available
curl http://YOUR_SERVER:5001/api/server/status

# Create app (will queue if primary offline)
curl -X POST http://YOUR_SERVER:5001/api/limits \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "chrome.exe",
    "limits": {
      "Monday": 3600,
      "Tuesday": 3600,
      ...
    }
  }'

# Check queue
curl http://YOUR_SERVER:5001/api/server/queue

# Manually sync
curl -X POST http://YOUR_SERVER:5001/api/server/sync
```

### Using Python

```python
import requests

# Check status
response = requests.get('http://YOUR_SERVER:5001/api/server/status')
print(response.json())

# Get queue
response = requests.get('http://YOUR_SERVER:5001/api/server/queue')
queue = response.json()
print(f"Queued requests: {queue['data']['count']}")
```

## Database Schema

The `request_queue.db` SQLite database contains:

```sql
CREATE TABLE request_queue (
    id INTEGER PRIMARY KEY,
    method TEXT,              -- GET, POST, PUT, DELETE
    endpoint TEXT,            -- /limits, /exceptions, etc.
    data TEXT,               -- JSON payload
    created_at TIMESTAMP,    -- When request was queued
    retry_count INTEGER,     -- Number of sync attempts
    status TEXT              -- pending, synced, failed
)
```

## Troubleshooting

### Primary API Not Connecting

Check the `PRIMARY_API_URL` setting matches your primary API location:

```python
PRIMARY_API_URL = 'http://127.0.0.1:5000/api'  # Adjust IP/port as needed
```

### Requests Not Syncing

1. Check if primary API is online:
   ```bash
   curl http://YOUR_SERVER:5001/api/server/status
   ```

2. Manually trigger sync:
   ```bash
   curl -X POST http://YOUR_SERVER:5001/api/server/sync
   ```

3. Check queue contents:
   ```bash
   curl http://YOUR_SERVER:5001/api/server/queue
   ```

### Queue Growing Too Large

- Ensure primary API is actually online and responding
- Check if there are connectivity issues between server and client
- Manually clear if needed (data loss!):
  ```bash
  curl -X POST http://YOUR_SERVER:5001/api/server/queue/clear
  ```

## Deployment

### On Linux Server

```bash
# Install
pip install flask requests

# Run with nohup (stays running)
nohup python secondary_api.py > api.log 2>&1 &

# Check status
tail -f api.log
```

### Using systemd Service

Create `/etc/systemd/system/parental-secondary-api.service`:

```ini
[Unit]
Description=Parental Control Secondary API
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/serverside
ExecStart=/usr/bin/python3 secondary_api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable parental-secondary-api
sudo systemctl start parental-secondary-api
sudo systemctl status parental-secondary-api
```

## Security Notes

⚠️ **Important**: This setup is for **local network only**. For production/internet deployment:

1. Add authentication (API keys, OAuth)
2. Use HTTPS/TLS encryption
3. Validate all input data
4. Add rate limiting
5. Use proper firewall rules
6. Consider reverse proxy (nginx)

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Dashboard (Web Interface)                                    │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP Requests
                   ↓
┌─────────────────────────────────────────────────────────────┐
│ Secondary Server API (Port 5001)                            │
│  • Receives all requests                                     │
│  • Acts as proxy to primary API                             │
│  • Queues if primary unavailable                            │
└──────────┬─────────────────────────────┬────────────────────┘
           │                             │
    Primary Online    Primary Offline
           │                    │
           ↓                    ↓
    ┌─────────────────┐  ┌──────────────┐
    │ Primary API     │  │ SQLite Queue │
    │ (Port 5000)     │  │ (Buffering)  │
    │ Client-side     │  │              │
    └─────────────────┘  └──────────────┘
           ↑                    │
           │                    │
           └────── Sync ────────┘
        (When Online Again)
```
