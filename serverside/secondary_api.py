"""
Secondary Server API - Buffering Proxy
Receives requests and forwards to primary API, queues if unavailable
"""

from flask import Flask, request, jsonify
from datetime import datetime
import json
import sqlite3
import threading
import time
import requests
import logging
from queue import Queue
from typing import Dict, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Enable gzip compression
try:
    from flask_compress import Compress
    Compress(app)
except ImportError:
    print("[WARNING] flask-compress not installed. Compression disabled.")

# Session with connection pooling and retries for primary API requests
def create_session():
    """Create a requests session with connection pooling and retry strategy."""
    session = requests.Session()
    
    # Retry strategy for failed connections
    retry_strategy = Retry(
        total=1,  # Only 1 retry to keep latency low over network
        connect=0,  # Don't retry on connection errors (offline primary) - avoids doubling the timeout
        backoff_factor=0.1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,  # Connection pooling
        pool_maxsize=10       # Maximum size of pool
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# Global session for reuse
PRIMARY_API_SESSION = create_session()

# Disable Flask's verbose logging
""" log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR) """

# Configuration
PRIMARY_API_URL = 'http://localhost:5000/api'
QUEUE_DB = 'request_queue.db'
SYNC_INTERVAL = 10  # seconds
REQUEST_TIMEOUT = 4.0  # seconds for data requests
PROBE_TIMEOUT = 1.0    # seconds for fast liveness probes

# Request queue for async syncing
sync_queue = Queue()

# Status caching to reduce spam
_primary_status_cache = {
    'last_check': 0,
    'is_alive': False,
    'cache_ttl': 15,  # Cache for 15 seconds
    'last_status': None  # Track last status for change detection
}

# ============================================================================
# DATABASE SETUP
# ============================================================================

def init_db():
    """Initialize SQLite database for request queue and cache."""
    conn = sqlite3.connect(QUEUE_DB, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')  # Enable WAL mode for better concurrency
    conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS request_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending'
        )
    ''')
    # Cache table for API responses
    c.execute('''
        CREATE TABLE IF NOT EXISTS data_cache (
            endpoint TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def add_to_queue(method: str, endpoint: str, data: str = None):
    """Add request to queue."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('''
            INSERT INTO request_queue (method, endpoint, data, status)
            VALUES (?, ?, ?, ?)
        ''', (method, endpoint, data, 'pending'))
        conn.commit()
        conn.close()
        print(f"[QUEUE] Added {method} {endpoint} to queue")
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to add to queue: {e}")

def get_queue():
    """Get all pending requests from queue."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('SELECT id, method, endpoint, data FROM request_queue WHERE status = ? ORDER BY created_at', ('pending',))
        rows = c.fetchall()
        conn.close()
        return rows
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to get queue: {e}")
        return []

def mark_queued_request_done(request_id: int):
    """Mark queued request as synced."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('UPDATE request_queue SET status = ? WHERE id = ?', ('synced', request_id))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to mark done: {e}")

def mark_queued_request_failed(request_id: int, max_retries: int = 3):
    """Mark queued request as failed, or retry if under max_retries."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('SELECT retry_count FROM request_queue WHERE id = ?', (request_id,))
        row = c.fetchone()
        
        if row and row[0] < max_retries:
            # Reset to pending for retry
            c.execute('UPDATE request_queue SET retry_count = retry_count + 1, status = ? WHERE id = ?', 
                     ('pending', request_id))
        else:
            # Give up after max retries
            c.execute('UPDATE request_queue SET retry_count = retry_count + 1, status = ? WHERE id = ?', 
                     ('failed', request_id))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to mark failed: {e}")

def get_queue_stats():
    """Get queue statistics."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('SELECT status, COUNT(*) FROM request_queue GROUP BY status')
        stats = dict(c.fetchall())
        conn.close()
        return stats
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to get stats: {e}")
        return {}

# ============================================================================
# DATA CACHING
# ============================================================================

def cache_endpoint_data(endpoint: str, data: Dict):
    """Cache response data from an endpoint."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        data_json = json.dumps(data)
        # Cache expires in 1 hour
        c.execute('''
            INSERT OR REPLACE INTO data_cache (endpoint, data, cached_at, expires_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, datetime('now', '+1 hour'))
        ''', (endpoint, data_json))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to cache data: {e}")

def get_cached_endpoint_data(endpoint: str, allow_expired: bool = False):
    """Get cached data for an endpoint.

    When allow_expired=False (default), only returns data that has not yet
    passed its expiry time.  When allow_expired=True, the most-recently
    cached row is returned even if it has expired — this is used as a
    last-resort fallback so the dashboard can still display known-good data
    when the primary API has been offline for longer than the cache TTL.
    """
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        if allow_expired:
            # Return the most recently cached row regardless of expiry
            c.execute('''
                SELECT data FROM data_cache
                WHERE endpoint = ?
                ORDER BY cached_at DESC
                LIMIT 1
            ''', (endpoint,))
        else:
            c.execute('''
                SELECT data FROM data_cache 
                WHERE endpoint = ? AND expires_at > CURRENT_TIMESTAMP
            ''', (endpoint,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
        return None
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to get cached data: {e}")
        return None

# ============================================================================
# PRIMARY API COMMUNICATION
# ============================================================================

def _update_primary_status(is_alive: bool):
    """Update the cached primary API liveness status."""
    prev = _primary_status_cache.get('last_status')
    _primary_status_cache['last_check'] = time.time()
    _primary_status_cache['is_alive'] = is_alive
    if is_alive != prev:
        print(f"[CHECK] Primary API is now {'ONLINE' if is_alive else 'OFFLINE'}")
        _primary_status_cache['last_status'] = is_alive

def check_primary_alive():
    """Check if primary API is available (with caching to reduce spam)."""
    global _primary_status_cache
    
    current_time = time.time()
    # Use cached result if still valid
    if current_time - _primary_status_cache['last_check'] < _primary_status_cache['cache_ttl']:
        return _primary_status_cache['is_alive']
    
    # Try the well-known status endpoint first
    is_alive = False
    probe_urls = [f'{PRIMARY_API_URL}/status', PRIMARY_API_URL]
    last_exception = None
    for url in probe_urls:
        try:
            response = PRIMARY_API_SESSION.get(url, timeout=PROBE_TIMEOUT)
            # Consider alive if we get an HTTP 200
            if response.status_code == 200:
                is_alive = True
                break
            else:
                # Log non-200 for diagnosis
                print(f"[CHECK] Probe to {url} returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            last_exception = e
            # Keep trying other probe urls
            # Only verbose-print when debugging
            print(f"[CHECK] Probe to {url} failed: {type(e).__name__}: {e}")
            continue
    
    # Update cache
    _update_primary_status(is_alive)
    
    return is_alive

def forward_to_primary(method: str, endpoint: str, data: Dict = None) -> tuple:
    """Forward request to primary API. Returns (success, response_data, status_code).
    status_code is None when the primary is unreachable (connection/timeout error)."""
    url = f'{PRIMARY_API_URL}{endpoint}'
    headers = {'Content-Type': 'application/json'}
    
    try:
        if method == 'GET':
            response = PRIMARY_API_SESSION.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        elif method == 'POST':
            response = PRIMARY_API_SESSION.post(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        elif method == 'PUT':
            response = PRIMARY_API_SESSION.put(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        elif method == 'DELETE':
            response = PRIMARY_API_SESSION.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            return False, {'status': 'error', 'message': 'Unsupported method'}, 400
        
        # Check if response is successful
        if response.status_code >= 400:
            print(f"[ERROR] Primary API returned {response.status_code}")
            return False, response.json() if response.text else None, response.status_code
        
        return True, response.json(), response.status_code
    except requests.exceptions.Timeout:
        # Silently fail on timeout - status is cached elsewhere
        return False, None, None
    except requests.exceptions.ConnectionError:
        # Silently fail on connection error - status is cached elsewhere
        return False, None, None
    except Exception as e:
        print(f"[ERROR] Forward failed: {type(e).__name__}")
        return False, None, None

# ============================================================================
# CORS HEADERS
# ============================================================================

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify({"status": "ok"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        return response, 200

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response

# ============================================================================
# PROXY ENDPOINTS - These mirror the primary API
# ============================================================================

def proxy_request(method: str, endpoint: str, data: Dict = None, return_queued: bool = False):
    """Generic proxy request handler."""
    # Skip the expensive forward attempt when the primary is known to be offline.
    # check_primary_alive() returns instantly from cache within its TTL window,
    # so this avoids blocking on REQUEST_TIMEOUT for every request while offline.
    primary_alive = check_primary_alive()

    success, response, status_code = False, None, None
    if primary_alive:
        success, response, status_code = forward_to_primary(method, endpoint, data)

    if success:
        _update_primary_status(True)

        # Cache successful GET responses
        if method == 'GET':
            cache_endpoint_data(endpoint, response)
        return jsonify(response), 200

    # Primary is reachable but returned an error (4xx/5xx) - propagate the error
    # rather than queuing, since the primary explicitly rejected the request.
    if status_code is not None:
        _update_primary_status(True)
        return jsonify(response), status_code

    # Unreachable due to connection/timeout errors (or known offline from cache)
    if primary_alive:
        # We tried and failed - update cache so subsequent requests skip the attempt
        _update_primary_status(False)

    # Primary is unreachable (connection/timeout error) or marked offline
    if method != 'GET' and return_queued:
        # Queue write operations
        data_json = json.dumps(data) if data else None
        add_to_queue(method, endpoint, data_json)
        
        return jsonify({
            "status": "queued",
            "message": "Primary API unavailable. Request queued for later processing.",
            "primary_status": "offline"
        }), 202
    elif method == 'GET':
        # Try to get cached data for read operations; use allow_expired=True so
        # that data stored before the cache TTL elapsed is still served when the
        # primary has been offline longer than one hour.
        cached_data = get_cached_endpoint_data(endpoint, allow_expired=True)
        if cached_data:
            return jsonify({
                "status": "success",
                "data": cached_data.get('data', {}),
                "cached": True,
                "message": "Data from local cache (primary API offline)"
            }), 200
        
        # No cached data available
        return jsonify({
            "status": "error",
            "message": "Primary API unavailable. No cached data available.",
            "data": {}
        }), 503
    else:
        # Other operations
        return jsonify({
            "status": "error",
            "message": "Primary API unavailable"
        }), 503

# LIMITS ENDPOINTS
@app.route("/api/limits", methods=["GET"])
def get_limits():
    return proxy_request('GET', '/limits')

@app.route("/api/limits/<app_name>", methods=["GET"])
def get_limit(app_name):
    return proxy_request('GET', f'/limits/{app_name}')

@app.route("/api/limits", methods=["POST"])
def create_limit():
    return proxy_request('POST', '/limits', request.get_json(), return_queued=True)

@app.route("/api/limits/<app_name>", methods=["PUT"])
def update_limit(app_name):
    return proxy_request('PUT', f'/limits/{app_name}', request.get_json(), return_queued=True)

@app.route("/api/limits/<app_name>/<day>", methods=["PUT"])
def update_day_limit(app_name, day):
    return proxy_request('PUT', f'/limits/{app_name}/{day}', request.get_json(), return_queued=True)

@app.route("/api/limits/<app_name>", methods=["DELETE"])
def delete_limit(app_name):
    return proxy_request('DELETE', f'/limits/{app_name}', return_queued=True)

# EXCEPTIONS ENDPOINTS
@app.route("/api/exceptions", methods=["GET"])
def get_exceptions():
    return proxy_request('GET', '/exceptions')

@app.route("/api/exceptions/<date>", methods=["GET"])
def get_date_exceptions(date):
    return proxy_request('GET', f'/exceptions/{date}')

@app.route("/api/exceptions/<date>/<app_name>", methods=["GET"])
def get_exception(date, app_name):
    return proxy_request('GET', f'/exceptions/{date}/{app_name}')

@app.route("/api/exceptions", methods=["POST"])
def create_exception():
    return proxy_request('POST', '/exceptions', request.get_json(), return_queued=True)

@app.route("/api/exceptions/<date>/<app_name>", methods=["DELETE"])
def delete_exception(date, app_name):
    return proxy_request('DELETE', f'/exceptions/{date}/{app_name}', return_queued=True)


@app.route("/api/exceptions/<date>/<app_name>/<int:index>", methods=["DELETE"])
def delete_exception_transaction_proxy(date, app_name, index):
    """Proxy delete for a specific exception transaction (queues when primary offline)."""
    return proxy_request('DELETE', f'/exceptions/{date}/{app_name}/{index}', return_queued=True)

# USAGE ENDPOINTS
@app.route("/api/usage", methods=["GET"])
def get_usage():
    return proxy_request('GET', '/usage')

@app.route("/api/usage/<date>", methods=["GET"])
def get_date_usage(date):
    return proxy_request('GET', f'/usage/{date}')

@app.route("/api/usage/<date>/<app_name>", methods=["GET"])
def get_app_usage(date, app_name):
    return proxy_request('GET', f'/usage/{date}/{app_name}')

@app.route("/api/usage/<date>/<app_name>", methods=["PUT"])
def update_usage(date, app_name):
    return proxy_request('PUT', f'/usage/{date}/{app_name}', request.get_json(), return_queued=True)

# STATUS & CONFIG ENDPOINTS
@app.route("/api/status", methods=["GET"])
def get_status():
    return proxy_request('GET', '/status')

@app.route("/api/config", methods=["GET"])
def get_config():
    return proxy_request('GET', '/config')

@app.route("/api/config", methods=["POST"])
def upload_config():
    return proxy_request('POST', '/config', request.get_json(), return_queued=True)

# BATCH ENDPOINT
@app.route("/api/dashboard/data", methods=["GET"])
def get_dashboard_data():
    """Batch endpoint: returns all dashboard data in a single request.

    Fetches limits, status, today's exceptions and full config in parallel
    from the primary API (or from the local cache when offline) so the
    browser only needs one round-trip to populate the entire dashboard.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    endpoint_map = {
        'limits': '/limits',
        'status': '/status',
        'today_exceptions': f'/exceptions/{today}',
        'config': '/config',
    }

    def fetch_one(key, endpoint):
        """Fetch one endpoint and fall back to cache on failure."""
        if check_primary_alive():
            success, response, status_code = forward_to_primary('GET', endpoint)
            if success:
                cache_endpoint_data(endpoint, response)
                return key, response.get('data', {}), True
            elif status_code is None:
                # Connection/timeout error - mark primary offline so other requests skip
                _update_primary_status(False)
        # Use allow_expired=True so that configuration data cached before the
        # TTL elapsed is still served when the primary has been offline longer
        # than one hour — a single query covers both fresh and stale rows.
        cached = get_cached_endpoint_data(endpoint, allow_expired=True)
        if cached:
            return key, cached.get('data', {}), False
        return key, {}, False

    results = {}
    any_primary_success = False
    with ThreadPoolExecutor(max_workers=len(endpoint_map)) as executor:
        futures = {executor.submit(fetch_one, k, ep): k for k, ep in endpoint_map.items()}
        for future in as_completed(futures):
            key, data, succeeded = future.result()
            results[key] = data
            if succeeded:
                any_primary_success = True

    # Only update the primary-alive cache when primary was actually confirmed
    # reachable.  If every fetch_one call returned from the offline cache
    # (no real connection attempt was made), do NOT reset last_check — let the
    # TTL expire naturally so check_primary_alive() will probe again on the
    # next cycle instead of perpetually reporting "offline".
    if any_primary_success:
        _update_primary_status(True)

    results['server'] = {
        'primary_api': 'online' if any_primary_success else 'offline',
        'timestamp': datetime.now().isoformat(),
    }

    return jsonify({"status": "success", "data": results}), 200

# ============================================================================
# SERVER-SPECIFIC ENDPOINTS
# ============================================================================

@app.route("/api/server/status", methods=["GET"])
def server_status():
    """Get server and primary API status."""
    primary_alive = check_primary_alive()
    queue_stats = get_queue_stats()
    
    return jsonify({
        "status": "success",
        "data": {
            "server_status": "online",
            "primary_api": "online" if primary_alive else "offline",
            "queue": queue_stats,
            "timestamp": datetime.now().isoformat()
        }
    }), 200

@app.route("/api/server/queue", methods=["GET"])
def get_server_queue():
    """Get current request queue."""
    queue_items = get_queue()
    items = []
    for item_id, method, endpoint, data in queue_items:
        items.append({
            "id": item_id,
            "method": method,
            "endpoint": endpoint,
            "data": json.loads(data) if data else None
        })
    
    return jsonify({
        "status": "success",
        "data": {
            "count": len(items),
            "items": items
        }
    }), 200

@app.route("/api/server/queue/<int:item_id>", methods=["DELETE"])
def cancel_queue_item(item_id):
    """Cancel (delete) a single pending queue item by ID."""
    try:
        conn = sqlite3.connect(QUEUE_DB, timeout=10)
        c = conn.cursor()
        c.execute('SELECT id, method, endpoint FROM request_queue WHERE id = ? AND status = ?', (item_id, 'pending'))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "message": "Queue item not found or already processed"}), 404
        c.execute('DELETE FROM request_queue WHERE id = ? AND status = ?', (item_id, 'pending'))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted == 0:
            # Item was processed by the background worker between SELECT and DELETE
            return jsonify({"status": "error", "message": "Queue item was already processed"}), 409
        print(f"[QUEUE] Cancelled item {item_id}: {row[1]} {row[2]}")
        return jsonify({"status": "success", "message": f"Queue item {item_id} cancelled"}), 200
    except sqlite3.OperationalError as e:
        print(f"[ERROR] Failed to cancel queue item {item_id}: {e}")
        return jsonify({"status": "error", "message": "Database error"}), 500

@app.route("/api/server/queue/clear", methods=["POST"])
def clear_queue():
    """Clear the request queue (dangerous!)."""
    conn = sqlite3.connect(QUEUE_DB)
    c = conn.cursor()
    c.execute('DELETE FROM request_queue')
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "success",
        "message": "Queue cleared"
    }), 200

@app.route("/api/server/sync", methods=["POST"])
def manual_sync():
    """Manually trigger queue sync."""
    synced, failed = sync_requests()
    
    return jsonify({
        "status": "success",
        "data": {
            "synced": synced,
            "failed": failed
        }
    }), 200

# ============================================================================
# BACKGROUND SYNC WORKER
# ============================================================================

def sync_requests():
    """Sync queued requests to primary API."""
    queue_items = get_queue()
    synced = 0
    failed = 0
    skipped = 0
    
    if not queue_items:
        return synced, failed
    
    print(f"[SYNC] Starting sync of {len(queue_items)} queued requests...")
    
    for item_id, method, endpoint, data in queue_items:
        # Skip GET requests - these should never be queued
        if method == 'GET':
            mark_queued_request_done(item_id)
            skipped += 1
            continue
            
        try:
            data_dict = json.loads(data) if data else None
            print(f"[SYNC] Processing {item_id}: {method} {endpoint}")
            if data_dict:
                print(f"[SYNC]   Data: {data_dict}")
            
            success, response, _ = forward_to_primary(method, endpoint, data_dict)
            
            if success:
                mark_queued_request_done(item_id)
                synced += 1
                print(f"[SYNC] ✓ Synced {method} {endpoint} (ID: {item_id})")
                if response:
                    print(f"[SYNC]   Response: {response}")
            else:
                mark_queued_request_failed(item_id)
                failed += 1
                print(f"[SYNC] ✗ Failed {method} {endpoint} (ID: {item_id})")
                if response:
                    print(f"[SYNC]   Error: {response}")
        except Exception as e:
            mark_queued_request_failed(item_id)
            failed += 1
            print(f"[SYNC] ✗ Exception syncing {method} {endpoint} (ID: {item_id}): {e}")
    
    print(f"[SYNC] Completed: {synced} synced, {failed} failed, {skipped} skipped (GET requests)")
    return synced, failed

def refresh_cache():
    """Refresh critical data cache from primary API."""
    if not check_primary_alive():
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    # List of endpoints to cache
    endpoints_to_cache = [
        '/limits',
        '/exceptions',
        f'/exceptions/{today}',
        f'/usage/{today}',
        '/config',
        '/status'
    ]
    
    for endpoint in endpoints_to_cache:
        try:
            success, response, _ = forward_to_primary('GET', endpoint)
            if success:
                cache_endpoint_data(endpoint, response)
                print(f"[CACHE] Refreshed {endpoint}")
        except Exception as e:
            print(f"[CACHE] Failed to refresh {endpoint}: {e}")

def background_sync_worker():
    """Background thread that periodically syncs queued requests and refreshes cache."""
    while True:
        time.sleep(SYNC_INTERVAL)
        if check_primary_alive():
            sync_requests()
            refresh_cache()

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal server error"}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("PARENTAL CONTROL - SECONDARY SERVER API")
    print("=" * 70)
    print(f"Primary API: {PRIMARY_API_URL}")
    print(f"Queue Database: {QUEUE_DB}")
    print(f"Sync Interval: {SYNC_INTERVAL} seconds")
    print("=" * 70)
    
    # Initialize database
    init_db()
    
    # Start background sync worker
    worker_thread = threading.Thread(target=background_sync_worker, daemon=True)
    worker_thread.start()
    
    print("\nServer Endpoints:")
    print("  Proxy: All endpoints from primary API at /api/*")
    print("  Batch: GET /api/dashboard/data")
    print("  Server Status: GET /api/server/status")
    print("  Queue Status: GET /api/server/queue")
    print("  Manual Sync: POST /api/server/sync")
    print("  Clear Queue: POST /api/server/queue/clear")
    print("\nStarting server...\n")
    
    app.run(debug=False, host="0.0.0.0", port=5035)
