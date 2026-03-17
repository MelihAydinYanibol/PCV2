"""
Configuration API for Parental Control Engine
Provides REST endpoints to manage time limits, exceptions, and monitor usage
"""

from flask import Flask, request, jsonify
from datetime import datetime
import json
import os
from typing import Dict, Any, Tuple

app = Flask(__name__)

# Enable CORS
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

# Configuration file paths
LIMIT_FILE = "timelimit.json"
DATA_FILE = "timeusage.json"
EXCEPTION_FILE = "exceptionaltime.json"

# Days of week mapping
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def ensure_files_exist() -> None:
    """Create required JSON files with empty defaults if they do not exist."""
    defaults = [
        (LIMIT_FILE, {}),
        (DATA_FILE, {}),
        (EXCEPTION_FILE, {}),
    ]
    for file_path, default in defaults:
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w") as f:
                    json.dump(default, f, indent=2)
            except Exception as e:
                print(f"Warning: Could not create {file_path}: {e}")


def load_limits() -> Dict[str, Any]:
    """Load time limits from file."""
    try:
        with open(LIMIT_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_limits(limits: Dict[str, Any]) -> bool:
    """Save time limits to file."""
    try:
        with open(LIMIT_FILE, "w") as f:
            json.dump(limits, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving limits: {e}")
        return False


def load_usage() -> Dict[str, Any]:
    """Load usage data from file."""
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_exceptions() -> Dict[str, Any]:
    """Load exceptions from file."""
    try:
        with open(EXCEPTION_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_exceptions(exceptions: Dict[str, Any]) -> bool:
    """Save exceptions to file."""
    try:
        with open(EXCEPTION_FILE, "w") as f:
            json.dump(exceptions, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving exceptions: {e}")
        return False


# ============================================================================
# TIME LIMITS ENDPOINTS
# ============================================================================

@app.route("/api/limits", methods=["GET"])
def get_all_limits():
    """Get all application time limits."""
    limits = load_limits()
    return jsonify({"status": "success", "data": limits}), 200


@app.route("/api/limits/<app_name>", methods=["GET"])
def get_app_limit(app_name):
    """Get time limits for a specific application."""
    limits = load_limits()
    if app_name not in limits:
        return jsonify({"status": "error", "message": f"Application '{app_name}' not found"}), 404
    
    return jsonify({"status": "success", "data": limits[app_name]}), 200


@app.route("/api/limits", methods=["POST"])
def create_app_limit():
    """
    Create a new application time limit.
    
    Body:
    {
        "app_name": "chrome.exe",
        "limits": {
            "Monday": 3600,
            "Tuesday": 3600,
            ...
        }
    }
    """
    data = request.get_json()
    
    if not data or "app_name" not in data or "limits" not in data:
        return jsonify({"status": "error", "message": "Missing 'app_name' or 'limits'"}), 400
    
    app_name = data["app_name"]
    limits = load_limits()
    
    if app_name in limits:
        return jsonify({"status": "error", "message": f"Application '{app_name}' already exists"}), 409
    
    limits[app_name] = data["limits"]
    
    if save_limits(limits):
        return jsonify({"status": "success", "message": f"Limit for '{app_name}' created", "data": limits[app_name]}), 201
    else:
        return jsonify({"status": "error", "message": "Failed to save limits"}), 500


@app.route("/api/limits/<app_name>", methods=["PUT"])
def update_app_limit(app_name):
    """
    Update time limits for an application.
    
    Body:
    {
        "limits": {
            "Monday": 7200,
            "Tuesday": 3600,
            ...
        }
    }
    """
    data = request.get_json()
    
    if not data or "limits" not in data:
        return jsonify({"status": "error", "message": "Missing 'limits'"}), 400
    
    limits = load_limits()
    
    if app_name not in limits:
        return jsonify({"status": "error", "message": f"Application '{app_name}' not found"}), 404
    
    limits[app_name] = data["limits"]
    
    if save_limits(limits):
        return jsonify({"status": "success", "message": f"Limits for '{app_name}' updated", "data": limits[app_name]}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save limits"}), 500


@app.route("/api/limits/<app_name>/<day>", methods=["PUT"])
def update_day_limit(app_name, day):
    """
    Update the time limit for a specific day.
    
    Body:
    {
        "seconds": 3600
    }
    """
    data = request.get_json()
    
    if not data or "seconds" not in data:
        return jsonify({"status": "error", "message": "Missing 'seconds'"}), 400
    
    if day not in DAYS_OF_WEEK:
        return jsonify({"status": "error", "message": f"Invalid day: {day}"}), 400
    
    limits = load_limits()
    
    if app_name not in limits:
        return jsonify({"status": "error", "message": f"Application '{app_name}' not found"}), 404
    
    limits[app_name][day] = data["seconds"]
    
    if save_limits(limits):
        return jsonify({"status": "success", "message": f"Limit for '{app_name}' on {day} updated to {data['seconds']} seconds"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save limits"}), 500


@app.route("/api/limits/<app_name>", methods=["DELETE"])
def delete_app_limit(app_name):
    """Delete an application from the limits."""
    limits = load_limits()
    
    if app_name not in limits:
        return jsonify({"status": "error", "message": f"Application '{app_name}' not found"}), 404
    
    del limits[app_name]
    
    if save_limits(limits):
        return jsonify({"status": "success", "message": f"Application '{app_name}' removed"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save limits"}), 500


# ============================================================================
# EXCEPTIONS ENDPOINTS
# ============================================================================

@app.route("/api/exceptions", methods=["GET"])
def get_all_exceptions():
    """Get all exceptions."""
    exceptions = load_exceptions()
    return jsonify({"status": "success", "data": exceptions}), 200


@app.route("/api/exceptions/<date>", methods=["GET"])
def get_date_exceptions(date):
    """Get exceptions for a specific date (YYYY-MM-DD format)."""
    exceptions = load_exceptions()
    
    if date not in exceptions:
        return jsonify({"status": "success", "data": {}}), 200
    
    # Migrate old format to new format
    date_exceptions = exceptions[date]
    for app, exc in date_exceptions.items():
        if isinstance(exc, list) and len(exc) == 2 and isinstance(exc[0], (int, float)) and not isinstance(exc[0], bool):
            # Old format: [time, reason] - convert to new format: [[time, reason]]
            date_exceptions[app] = [exc]
    
    return jsonify({"status": "success", "data": date_exceptions}), 200


@app.route("/api/exceptions/<date>/<app_name>", methods=["GET"])
def get_app_exception(date, app_name):
    """Get exception for a specific app on a specific date."""
    exceptions = load_exceptions()
    
    if date not in exceptions or app_name not in exceptions.get(date, {}):
        return jsonify({"status": "error", "message": f"No exception found for {app_name} on {date}"}), 404
    
    return jsonify({"status": "success", "data": exceptions[date][app_name]}), 200


@app.route("/api/exceptions", methods=["POST"])
def create_exception():
    """
    Create or update an exception.
    
    Body:
    {
        "date": "2026-01-17",
        "app_name": "chrome.exe",
        "exception_time": 300,  # seconds to add (can be negative)
        "reason": "Birthday"    # optional
    }
    """
    data = request.get_json()
    
    required_fields = ["date", "app_name", "exception_time"]
    if not data or not all(field in data for field in required_fields):
        return jsonify({"status": "error", "message": f"Missing required fields: {required_fields}"}), 400
    
    date = data["date"]
    app_name = data["app_name"]
    exception_time = data["exception_time"]
    reason = data.get("reason", None)
    
    # Validate date format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    exceptions = load_exceptions()
    
    if date not in exceptions:
        exceptions[date] = {}
    
    if app_name not in exceptions[date]:
        exceptions[date][app_name] = []
    else:
        # Migrate old format to new format if needed
        exc = exceptions[date][app_name]
        if isinstance(exc, list) and len(exc) == 2 and isinstance(exc[0], (int, float)) and not isinstance(exc[0], bool):
            # Old format: [time, reason] - convert to new format: [[time, reason]]
            exceptions[date][app_name] = [exc]
    
    # Store as list of [exception_time, reason] transactions
    exceptions[date][app_name].append([exception_time, reason])
    
    if save_exceptions(exceptions):
        return jsonify({"status": "success", "message": f"Exception created for {app_name} on {date}", "data": [exception_time, reason]}), 201
    else:
        return jsonify({"status": "error", "message": "Failed to save exception"}), 500


@app.route("/api/exceptions/<date>/<app_name>", methods=["DELETE"])
def delete_exception(date, app_name):
    """Delete all exceptions for a specific app on a specific date."""
    exceptions = load_exceptions()
    
    if date not in exceptions or app_name not in exceptions.get(date, {}):
        return jsonify({"status": "error", "message": f"Exception not found for {app_name} on {date}"}), 404
    
    del exceptions[date][app_name]
    
    # Remove date entry if empty
    if not exceptions[date]:
        del exceptions[date]
    
    if save_exceptions(exceptions):
        return jsonify({"status": "success", "message": f"Exception deleted for {app_name} on {date}"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save exception"}), 500


@app.route("/api/exceptions/<date>/<app_name>/<int:index>", methods=["DELETE"])
def delete_exception_transaction(date, app_name, index):
    """Delete a specific exception transaction for an app on a specific date."""
    exceptions = load_exceptions()
    
    if date not in exceptions or app_name not in exceptions.get(date, {}):
        return jsonify({"status": "error", "message": f"Exception not found for {app_name} on {date}"}), 404
    
    exc_list = exceptions[date][app_name]

    # Migrate old format [time, reason] → [[time, reason]] so index-based deletion works correctly
    if isinstance(exc_list, list) and len(exc_list) == 2 and isinstance(exc_list[0], (int, float)) and not isinstance(exc_list[0], bool):
        exc_list = [exc_list]
        exceptions[date][app_name] = exc_list

    if not isinstance(exc_list, list) or index < 0 or index >= len(exc_list):
        return jsonify({"status": "error", "message": f"Invalid exception index"}), 400
    
    exc_list.pop(index)
    
    # Remove app entry if no transactions left
    if not exc_list:
        del exceptions[date][app_name]
    
    # Remove date entry if empty
    if not exceptions[date]:
        del exceptions[date]
    
    if save_exceptions(exceptions):
        return jsonify({"status": "success", "message": f"Exception transaction deleted for {app_name} on {date}"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save exception"}), 500


# ============================================================================
# USAGE ENDPOINTS
# ============================================================================

@app.route("/api/usage", methods=["GET"])
def get_all_usage():
    """Get all usage data."""
    usage = load_usage()
    return jsonify({"status": "success", "data": usage}), 200


@app.route("/api/usage/<date>", methods=["GET"])
def get_date_usage(date):
    """Get usage data for a specific date (YYYY-MM-DD format)."""
    usage = load_usage()
    
    if date not in usage:
        return jsonify({"status": "success", "data": {}}), 200
    
    return jsonify({"status": "success", "data": usage[date]}), 200


@app.route("/api/usage/<date>/<app_name>", methods=["GET"])
def get_app_usage(date, app_name):
    """Get usage data for a specific app on a specific date."""
    usage = load_usage()
    
    if date not in usage or app_name not in usage.get(date, {}):
        return jsonify({"status": "success", "data": 0}), 200
    
    return jsonify({"status": "success", "data": usage[date][app_name]}), 200


@app.route("/api/usage/<date>/<app_name>", methods=["PUT"])
def update_app_usage(date, app_name):
    """
    Update usage for a specific app on a specific date.
    
    Body:
    {
        "seconds": 3600
    }
    """
    data = request.get_json()
    
    if not data or "seconds" not in data:
        return jsonify({"status": "error", "message": "Missing 'seconds'"}), 400
    
    # Validate date format
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    usage = load_usage()
    
    if date not in usage:
        usage[date] = {}
    
    usage[date][app_name] = data["seconds"]
    
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(usage, f)
        return jsonify({"status": "success", "message": f"Usage for {app_name} on {date} updated", "data": data["seconds"]}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": "Failed to save usage"}), 500


# ============================================================================
# STATUS & INFO ENDPOINTS
# ============================================================================

@app.route("/api/status", methods=["GET"])
def get_status():
    """Get current system status."""
    today = datetime.now().strftime("%Y-%m-%d")
    usage = load_usage()
    limits = load_limits()
    exceptions = load_exceptions()
    
    today_usage = usage.get(today, {})
    
    return jsonify({
        "status": "success",
        "data": {
            "current_date": today,
            "apps_monitored": len(limits),
            "total_apps_today": len(today_usage),
            "exceptions_today": len(exceptions.get(today, {}))
        }
    }), 200


@app.route("/api/config", methods=["GET"])
def get_config():
    """Get full configuration (limits and exceptions)."""
    limits = load_limits()
    exceptions = load_exceptions()
    
    return jsonify({
        "status": "success",
        "data": {
            "limits": limits,
            "exceptions": exceptions
        }
    }), 200


@app.route("/api/config", methods=["POST"])
def upload_config():
    """
    Upload full configuration.
    
    Body:
    {
        "limits": {...},
        "exceptions": {...}
    }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400
    
    limits_saved = True
    exceptions_saved = True
    
    if "limits" in data:
        limits_saved = save_limits(data["limits"])
    
    if "exceptions" in data:
        exceptions_saved = save_exceptions(data["exceptions"])
    
    if limits_saved and exceptions_saved:
        return jsonify({"status": "success", "message": "Configuration uploaded successfully"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to save configuration"}), 500


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({"status": "error", "message": "Internal server error"}), 500


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    ensure_files_exist()
    print("Starting Parental Control Configuration API...")
    print("Available endpoints:")
    print("  GET    /api/limits")
    print("  GET    /api/limits/<app_name>")
    print("  POST   /api/limits")
    print("  PUT    /api/limits/<app_name>")
    print("  PUT    /api/limits/<app_name>/<day>")
    print("  DELETE /api/limits/<app_name>")
    print("  GET    /api/exceptions")
    print("  GET    /api/exceptions/<date>")
    print("  GET    /api/exceptions/<date>/<app_name>")
    print("  POST   /api/exceptions")
    print("  DELETE /api/exceptions/<date>/<app_name>")
    print("  GET    /api/usage")
    print("  GET    /api/usage/<date>")
    print("  GET    /api/usage/<date>/<app_name>")
    print("  PUT    /api/usage/<date>/<app_name>")
    print("  GET    /api/status")
    print("  GET    /api/config")
    print("  POST   /api/config")
    app.run(debug=True, host="0.0.0.0", port=5000)
