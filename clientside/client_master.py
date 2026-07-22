import subprocess
import sys
import time

# 1. Start all processes
api_process = subprocess.Popen([sys.executable, 'api.py'])
main_process = subprocess.Popen([sys.executable, 'client_engine.py'])
night_lockdown_process = subprocess.Popen([sys.executable, 'night_lockdown.py'])

print("All processes are running. Press Ctrl+C to stop them all.")

try:
    # 2. Keep the parent script alive so the children don't get orphaned
    while True:
        # Optional: Check if a process has crashed
        if api_process.poll() is not None:
            print("API process died. Exiting...")
            break
        if main_process.poll() is not None:
            print("Main engine died. Exiting...")
            break
        if night_lockdown_process.poll() is not None:
            print("Night lockdown engine died. Exiting...")
            break
        time.sleep(1)

except KeyboardInterrupt:
    # 3. Clean shutdown: if you stop this script, kill the others too
    print("\nStopping processes...")
    api_process.terminate()
    main_process.terminate()
    night_lockdown_process.terminate()
    sys.exit()
