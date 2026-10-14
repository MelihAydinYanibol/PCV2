import subprocess
import sys
import time

from shutdown_guard import install_shutdown_survival

PROCESSES = {
    "API": "api.py",
    "Main engine": "client_engine.py",
    "Night lockdown engine": "night_lockdown.py",
}

# Don't let Windows' close/shutdown console events kill the launcher either,
# so a cancelled shutdown still leaves someone around to restart the engines.
install_shutdown_survival("client_master")


def start(script):
    return subprocess.Popen([sys.executable, script])


# 1. Start all processes
processes = {name: start(script) for name, script in PROCESSES.items()}

print("All processes are running. Press Ctrl+C to stop them all.")

try:
    # 2. Keep the parent script alive and restart anything that stops, so
    #    enforcement can't be switched off by killing one of the processes
    #    (or by one dying while a shutdown is cancelled).
    while True:
        for name, process in processes.items():
            if process.poll() is not None:
                print(f"{name} died (exit code {process.returncode}). Restarting...")
                processes[name] = start(PROCESSES[name])
        time.sleep(1)

except KeyboardInterrupt:
    # 3. Clean shutdown: if you stop this script, kill the others too
    print("\nStopping processes...")
    for process in processes.values():
        process.terminate()
    sys.exit()
