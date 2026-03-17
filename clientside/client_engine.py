import json
import time
import psutil
from datetime import datetime
from win10toast import ToastNotifier
import threading
import requests
import os
from dotenv import load_dotenv

USAGE_NOTIFIERS = [30,60,120,300] # seconds
TTS_EVENTS = {30:"cc5f5e65-8d04-48bb-947f-243d9184e6cc",
              60:"704097ff-8ac4-4b4b-8384-3fbfb7d70638",
              120:"18f01511-0614-4f78-8f57-5172cbd361db",
              300:"f0ca5816-3855-4ca5-801d-a816603a2763"} # seconds
LIMIT_FILE = "timelimit.json"
DATA_FILE = "timeusage.json"
EXCEPTION_FILE = "exceptionaltime.json"
USED_EXCEPTIONS_FILE = "used_exceptions.json"
CHECK_INTERVAL = 5  # seconds
load_dotenv()
HASS_URL = os.getenv("HASS_URL","http://homeassistant.local:8123")
TOKEN = os.getenv("HASS_TOKEN")
SAFETY_SLEEP = 120


USED_EXCEPTIONS=[]

def ensure_files_exist():
    """Create required JSON files with empty defaults if they do not exist."""
    defaults = [
        (LIMIT_FILE, {}),
        (DATA_FILE, {}),
        (EXCEPTION_FILE, {}),
        (USED_EXCEPTIONS_FILE, []),
    ]
    for file_path, default in defaults:
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w") as f:
                    json.dump(default, f, indent=2)
            except Exception as e:
                print(f"Warning: Could not create {file_path}: {e}")


def load_exceptions():
    try:
        with open(EXCEPTION_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def load_used_exceptions():
    try:
        with open(USED_EXCEPTIONS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_used_exceptions(used_exceptions):
    with open(USED_EXCEPTIONS_FILE, "w") as f:
        json.dump(used_exceptions, f)

def load_limits():
    try:
        with open(LIMIT_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def load_usage(file=DATA_FILE):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_usage(usage):
    with open(DATA_FILE, "w") as f:
        json.dump(usage, f)
        f.close()

def shutdown():
    import os
    print("Time exceeded for overall usage. Shutting down the computer.")
    os.system('shutdown /s /t 0 /F') 

def trigger_tag_event(tag_id): 
    # We run this in a function to be threaded
    def send_request():
        url = f"{HASS_URL}/api/events/tag_scanned"
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }
        data = {"tag_id": tag_id}

        try:
            requests.post(url, headers=headers, json=data, timeout=2)
            print("HA Tag Event Triggered.")
        except Exception as e:
            print(f"Failed to trigger HA event: {e}")

    # Start as a background thread so it doesn't freeze the timer
    threading.Thread(target=send_request).start()


def notify(limit,usage,name=None):
    toaster = ToastNotifier()
    if limit - usage in USAGE_NOTIFIERS:
        if name == "OVERALL":
            whole_txt = "Kalan bilgisayar kullanım süresi"
            if limit - usage in TTS_EVENTS:
                trigger_tag_event(TTS_EVENTS.get(limit - usage))
        else:
            whole_txt = f"{name} adlı uygulama için kalan süre"
        if limit - usage < 60: txt = f"{limit-usage} saniye"
        elif (limit - usage) % 60 == 0: txt = f"{(limit-usage)//60} dakika"
        else:txt = f"{(limit - usage) // 60} dakika {(limit - usage) % 60} saniye"
        toaster.show_toast(
            "HASSS Agent",
            f"{whole_txt} {txt}",
            duration=7,
            threaded=True
        )
        print(f"Sent notification for {name} for remaining {txt}")

def check_exception(name,default_limit,default_usage,today):
    exceptions = load_exceptions()
    if today in exceptions and name in exceptions.get(today, {}):
        entries = exceptions.get(today).get(name, [])
        base_limit = default_limit
        last_reason = None
        if name == "OVERALL":
            txt_name = "Bilgisayar kullanımı için"
        else:
            txt_name = f"{name} adlı uygulama için"

        for entry in entries:
            try:
                t = entry[0]
            except Exception:
                continue
            try:
                reason = entry[1]
            except Exception:
                reason = None
            if reason == "null":
                reason = None

            # Integer adjustments (add/subtract)
            if type(t) == int:
                exception_id = f"{today}_{name}_{t}"
                if exception_id not in USED_EXCEPTIONS:
                    if t >= 0:
                        if t % 60 == 0:
                            t_txt = f"{t//60} dakika"
                        elif t > 60:
                            t_txt = f"{t//60} dakika {t%60} saniye"
                        else:
                            t_txt = f"{t} saniye"
                        toaster = ToastNotifier()
                        toaster.show_toast(
                            "HASSS Agent",
                            f"{txt_name} {t_txt} eklendi.",
                            duration=7,
                            threaded=True,
                        )
                        print(f"Sent notification for {name} for exceptional time addition of {t}")
                    else:
                        if abs(t) % 60 == 0:
                            t_txt = f"{abs(t)//60} dakika"
                        elif abs(t) > 60:
                            t_txt = f"{abs(t)//60} dakika {abs(t)%60} saniye"
                        else:
                            t_txt = f"{abs(t)} saniye"
                        toaster = ToastNotifier()
                        toaster.show_toast(
                            "HASSS Agent",
                            f"{txt_name} {t_txt} azaltıldı.",
                            duration=7,
                            threaded=True,
                        )
                        print(f"Sent notification for {name} for exceptional time substriction of {t}")

                    USED_EXCEPTIONS.append(exception_id)
                    save_used_exceptions(USED_EXCEPTIONS)

                base_limit += t
                last_reason = reason
            else:
                # Try to interpret non-int as a set-limit (string numbers)
                try:
                    t_int = int(t)
                except Exception:
                    continue
                exception_id = f"{today}_{name}_{t_int}"
                if exception_id not in USED_EXCEPTIONS:
                    if t_int % 60 == 0:
                        t_txt = f"{t_int//60} dakika"
                    elif t_int > 60:
                        t_txt = f"{t_int//60} dakika {t_int%60} saniye"
                    else:
                        t_txt = f"{t_int} saniye"
                    toaster = ToastNotifier()
                    toaster.show_toast(
                        "HASSS Agent",
                        f"{txt_name} süre {t_txt} yapıldı.",
                        duration=7,
                        threaded=True,
                    )
                    print(f"Sent notification for {name} for exceptional time set of {t_int}")
                    USED_EXCEPTIONS.append(exception_id)
                    save_used_exceptions(USED_EXCEPTIONS)

                base_limit = t_int
                last_reason = reason

        return base_limit, last_reason
    return default_limit, None


def main():
    global USED_EXCEPTIONS
    ensure_files_exist()
    print(f"Code Started -- Waiting {SAFETY_SLEEP} seconds for security.")
    time.sleep(SAFETY_SLEEP)
    USED_EXCEPTIONS = load_used_exceptions()
    print("Starting monitor\n")
    while True:
        killed = []
        limits = load_limits()
        usage = load_usage()
        found_processes = {}
        for proc in psutil.process_iter(attrs=['pid', 'name', 'create_time']):
            name = proc.info['name']
            pid = proc.info['pid']
            if name in list(limits):
                print(f"Found Process : {name} PID : {pid}")
                if proc.info['name'] in found_processes:
                    found_processes[proc.info['name']].append(proc)
                else:
                    found_processes[proc.info['name']] = [proc]
        print("\n\n")
        found_processes["OVERALL"] = "OVERALL"
        dow = {1:"Monday",2:"Tuesday",3:"Wednesday",4:"Thursday",5:"Friday",6:"Saturday",7:"Sunday"}.get(datetime.now().isoweekday())
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in usage:
            usage[today] = {}

        for name,procs in found_processes.items():
            if today not in list(usage):
                usage[today] = {}
            # Safely get the configured limit for the name (handles missing entries)
            name_limits = limits.get(name) or {}
            app_lim = name_limits.get(dow, 0)

            # Always treat missing usage as 0 so exceptions (including OVERALL) apply immediately
            app_usg = usage.get(today, {}).get(name, 0)

            exception_lim, reason = check_exception(name, app_lim, app_usg, today)
            print(exception_lim, reason)
            if exception_lim != app_lim:
                app_lim = exception_lim

            if app_lim <= app_usg:
                if name != "OVERALL":
                    for proc in procs:
                        print(f"Time exceeded for {name} PID : {proc.info['pid']}. Terminating.")
                        try:
                            proc.kill()
                        except:
                            pass
                        if proc.info['name'] not in killed:
                            killed.append(proc.info['name'])
                else:
                    shutdown()
                    break
            else:
                print(f"Time checked for : {name}. Usage : {app_usg}/{app_lim}")
                notify(app_lim, app_usg, name)
        print("Sleeping for 5 seconds.")
        time.sleep(CHECK_INTERVAL)
        for name,proc in found_processes.items():
            if name not in killed:
                try:usage[today][name] += CHECK_INTERVAL
                except:usage[today][name] = CHECK_INTERVAL
        save_usage(usage=usage)

if __name__ == "__main__":
    main()